"""Ephemeral complete native approval context; never a persisted transcript.

Shapes are verified against Codex 0.163 experimental App Server schemas. Unsupported
scope is unavailable for grants, while native decline remains possible.
"""
from collections import OrderedDict
from copy import deepcopy
import json
import unicodedata

MAX_CONTEXT = 131072
MAX_ITEMS = 64
MAX_CACHE = 524288
UNAVAILABLE = 'Complete request context is unavailable or unsupported. Decline or stop this run.'


def bounded(value):
    encoded = json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(',', ':')).encode('utf-8')
    if len(encoded) > MAX_CONTEXT:
        raise ValueError(UNAVAILABLE)
    # JSON escaping alone can hide bidi/zero-width controls from a human reviewer.
    for char in encoded.decode('utf-8'):
        if unicodedata.category(char) in {'Cf', 'Cs'}:
            raise ValueError(UNAVAILABLE)
    def check(item, depth=0):
        if depth > 16:
            raise ValueError(UNAVAILABLE)
        if isinstance(item, str):
            if any(unicodedata.category(c) in {'Cc', 'Cf', 'Cs'} and c not in '\n\t' for c in item):
                raise ValueError(UNAVAILABLE)
        elif isinstance(item, dict):
            for key, val in item.items():
                check(key, depth + 1)
                check(val, depth + 1)
        elif isinstance(item, list):
            for val in item:
                check(val, depth + 1)
    check(value)
    return encoded


def shape(value, allowed, required=()):
    if not isinstance(value, dict) or set(value) - set(allowed) or set(required) - set(value):
        raise ValueError(UNAVAILABLE)


def string(value, optional=False):
    if optional and value is None:
        return
    if not isinstance(value, str) or not value.strip():
        raise ValueError(UNAVAILABLE)


def path_entry(value):
    shape(value, ('type', 'path', 'pattern', 'value'), ('type',))
    kind = value['type']
    if kind in {'path', 'glob_pattern'}:
        key = 'path' if kind == 'path' else 'pattern'
        shape(value, ('type', key), ('type', key))
        string(value[key])
    elif kind == 'special':
        shape(value, ('type', 'value'), ('type', 'value'))
        special = value['value']
        shape(special, ('kind', 'subpath'), ('kind',))
        if special['kind'] not in {'root', 'minimal', 'project_roots', 'tmpdir', 'slash_tmp'}:
            raise ValueError(UNAVAILABLE)
        if special['kind'] != 'project_roots' and 'subpath' in special:
            raise ValueError(UNAVAILABLE)
        string(special.get('subpath'), optional=True)
    else:
        raise ValueError(UNAVAILABLE)


def permissions(value):
    if value is None:
        return
    shape(value, ('fileSystem', 'network'))
    network = value.get('network')
    if network is not None:
        shape(network, ('enabled',))
        if network.get('enabled') is not None and type(network['enabled']) is not bool:
            raise ValueError(UNAVAILABLE)
    fs = value.get('fileSystem')
    if fs is not None:
        shape(fs, ('entries', 'globScanMaxDepth', 'read', 'write'))
        depth = fs.get('globScanMaxDepth')
        if depth is not None and (type(depth) is not int or depth < 1):
            raise ValueError(UNAVAILABLE)
        for key in ('read', 'write', 'entries'):
            entries = fs.get(key)
            if entries is None:
                continue
            if not isinstance(entries, list) or len(entries) > 100:
                raise ValueError(UNAVAILABLE)
            for entry in entries:
                if key != 'entries':
                    string(entry)
                else:
                    shape(entry, ('access', 'path'), ('access', 'path'))
                    if entry['access'] not in {'read', 'write', 'deny'}:
                        raise ValueError(UNAVAILABLE)
                    path_entry(entry['path'])


def string_list(value):
    if not isinstance(value, list) or len(value) > 100:
        raise ValueError(UNAVAILABLE)
    for item in value:
        string(item)


def network_amendment(value):
    shape(value, ('action', 'host'), ('action', 'host'))
    if value['action'] not in {'allow', 'deny'}:
        raise ValueError(UNAVAILABLE)
    string(value['host'])


def command_actions(value):
    if value is None:
        return
    if not isinstance(value, list) or len(value) > 100:
        raise ValueError(UNAVAILABLE)
    for action in value:
        shape(action, ('type', 'command', 'name', 'path', 'query'), ('type', 'command'))
        kind = action['type']
        allowed = {'read': ('type', 'command', 'name', 'path'),
                   'listFiles': ('type', 'command', 'path'),
                   'search': ('type', 'command', 'path', 'query'),
                   'unknown': ('type', 'command')}.get(kind)
        if allowed is None:
            raise ValueError(UNAVAILABLE)
        shape(action, allowed, allowed if kind == 'read' else ('type', 'command'))
        for key, val in action.items():
            string(val, optional=key in {'path', 'query'} and kind != 'read')


class ApprovalReviews:
    """Bounded item cache. Caller serializes mutations with the dashboard lock."""
    def __init__(self):
        self.items = OrderedDict()
        self.size = 0

    def clear(self):
        self.items.clear()
        self.size = 0

    def discard(self, key):
        old = self.items.pop(key, None)
        if old:
            self.size -= old[1]

    def expire(self, thread_id, turn_id=None):
        for key in list(self.items):
            if key[0] == thread_id and (turn_id is None or key[1] == turn_id):
                self.discard(key)

    def remember(self, params):
        item = params.get('item')
        if not isinstance(item, dict) or item.get('type') not in {'commandExecution', 'fileChange'}:
            return
        key = (params.get('threadId'), params.get('turnId'), item.get('id'))
        if not all(isinstance(x, str) and 0 < len(x) <= 200 for x in key):
            return
        self.discard(key)
        try:
            if item['type'] == 'commandExecution':
                shape(item, ('type', 'id', 'command', 'commandActions', 'cwd', 'durationMs',
                             'exitCode', 'aggregatedOutput', 'pluginId', 'processId', 'scriptPath', 'source', 'status'))
                context = {'command': item.get('command'), 'cwd': item.get('cwd')}
            else:
                shape(item, ('type', 'id', 'changes', 'status'))
                context = {'changes': item.get('changes')}
            encoded = bounded(context)
        except (ValueError, TypeError, UnicodeError, RecursionError):
            return
        while self.items and (len(self.items) >= MAX_ITEMS or self.size + len(encoded) > MAX_CACHE):
            self.discard(next(iter(self.items)))
        self.items[key] = (deepcopy(context), len(encoded))
        self.size += len(encoded)

    def context(self, params, kind):
        """Return the entire known grant context, with no excerpts or omission."""
        bounded(params)
        for key in ('threadId', 'turnId', 'itemId'):
            string(params.get(key))
        if type(params.get('startedAtMs')) is not int or params['startedAtMs'] < 0:
            raise ValueError(UNAVAILABLE)
        base = {key: params[key] for key in ('threadId', 'turnId', 'itemId', 'startedAtMs')}
        string(params.get('reason'), optional=True)
        cached = self.items.get((params['threadId'], params['turnId'], params['itemId']), ({}, 0))[0]
        if kind == 'command':
            shape(params, ('threadId', 'turnId', 'itemId', 'startedAtMs', 'additionalPermissions',
                          'approvalId', 'availableDecisions', 'command', 'commandActions', 'cwd',
                          'environmentId', 'kind', 'networkApprovalContext', 'proposedExecpolicyAmendment',
                          'proposedNetworkPolicyAmendments', 'reason'))
            # Real 0.163 local-only App Server callbacks identify this environment as
            # 'local'; never infer that any other native environment is local.
            if (params.get('kind', 'command') != 'command'
                    or params.get('environmentId') not in (None, 'local')):
                raise ValueError(UNAVAILABLE)
            decisions = params.get('availableDecisions')
            # A missing/null list does not prove that this callback permits acceptance.
            if not isinstance(decisions, list) or 'accept' not in decisions:
                raise ValueError('This native request does not explicitly offer one-request approval. Decline or stop the run.')
            for decision in decisions:
                if isinstance(decision, str) and decision in {'accept', 'acceptForSession', 'decline', 'cancel'}:
                    continue
                if isinstance(decision, dict) and set(decision) == {'acceptWithExecpolicyAmendment'}:
                    overlay = decision['acceptWithExecpolicyAmendment']
                    shape(overlay, ('execpolicy_amendment',), ('execpolicy_amendment',))
                    string_list(overlay['execpolicy_amendment'])
                    continue  # Shown verbatim, never sent or applied by this dashboard.
                if isinstance(decision, dict) and set(decision) == {'applyNetworkPolicyAmendment'}:
                    overlay = decision['applyNetworkPolicyAmendment']
                    shape(overlay, ('network_policy_amendment',), ('network_policy_amendment',))
                    network_amendment(overlay['network_policy_amendment'])
                    continue
                raise ValueError(UNAVAILABLE)
            context = {**base, **deepcopy(params)}
            for key in ('command', 'cwd'):
                if context.get(key) is None:
                    context[key] = cached.get(key)
                string(context[key])
                if cached.get(key) is not None and context[key] != cached[key]:
                    raise ValueError(UNAVAILABLE)
            for key in ('additionalPermissions', 'networkApprovalContext', 'reason', 'approvalId',
                        'environmentId', 'proposedExecpolicyAmendment', 'proposedNetworkPolicyAmendments'):
                context.setdefault(key, None)
            context.setdefault('kind', 'command')
            string(context['approvalId'], optional=True)
            command_actions(context.get('commandActions'))
            if context['proposedExecpolicyAmendment'] is not None:
                string_list(context['proposedExecpolicyAmendment'])
            proposals = context['proposedNetworkPolicyAmendments']
            if proposals is not None:
                if not isinstance(proposals, list) or len(proposals) > 100:
                    raise ValueError(UNAVAILABLE)
                for proposal in proposals:
                    network_amendment(proposal)
            permissions(context['additionalPermissions'])
            net = context['networkApprovalContext']
            if net is not None:
                # Managed-network approval can release several queued requests for a
                # host/protocol; native context omits the port and exact command set.
                raise ValueError('Managed-network approval has broader queued-request scope. Decline or stop this run.')
        elif kind == 'file_change':
            shape(params, ('threadId', 'turnId', 'itemId', 'startedAtMs', 'reason', 'grantRoot'))
            # Native grantRoot is documented as a session-long root grant, not one patch.
            if params.get('grantRoot') is not None:
                raise ValueError('This file request includes a session-wide root grant. Only one-request approvals are supported.')
            changes = cached.get('changes')
            if not isinstance(changes, list) or not changes or len(changes) > 100:
                raise ValueError(UNAVAILABLE)
            for change in changes:
                shape(change, ('path', 'kind', 'diff'), ('path', 'kind', 'diff'))
                string(change['path'])
                string(change['diff'])
                operation = change['kind']
                shape(operation, ('type', 'move_path'), ('type',))
                if operation['type'] not in {'add', 'delete', 'update'}:
                    raise ValueError(UNAVAILABLE)
                if 'move_path' in operation and operation['type'] != 'update':
                    raise ValueError(UNAVAILABLE)
                string(operation.get('move_path'), optional=True)
            context = {**base, 'reason': params.get('reason'), 'grantRoot': None,
                       'changes': deepcopy(changes)}
        else:
            raise ValueError(UNAVAILABLE)
        bounded(context)
        return context
