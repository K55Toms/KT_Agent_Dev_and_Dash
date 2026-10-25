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

# Only these locally authored messages may cross the error boundary. Never expose
# exception text, native payload excerpts, scanner output, or unknown field names.
REVIEW_FAILURES = {
    'request_unavailable': ('This request is no longer live in this dashboard process.', 'Refresh the dashboard. A completed, resolved or disconnected request cannot be approved.', False),
    'context_missing': ('The complete native request context has not been captured.', 'Leave the request pending and try reviewing again. Decline or stop if it remains unavailable.', True),
    'context_too_large': ('The complete request exceeds the review size limit.', 'Ask the agent to split the operation into smaller requests; decline or stop this request.', False),
    'unsafe_text': ('The request contains ambiguous or unsupported control characters.', 'Decline or stop this request and ask for a plain-text operation.', False),
    'unsupported_shape': ('The native request contains an unsupported protocol shape.', 'Leave it pending while compatibility is investigated, or decline or stop the run.', False),
    'unsupported_cached_item': ('The native item context has an unsupported shape.', 'Leave it pending while compatibility is investigated, or decline or stop the run.', False),
    'unsupported_environment': ('This request targets an environment other than the supported local environment.', 'Decline or stop this request; remote-environment approval is not supported.', False),
    'unsupported_action': ('This native action does not support the current one-request review flow.', 'Decline or stop the run; terminal-input and unknown action approvals are not supported.', False),
    'accept_not_offered': ('Codex did not explicitly offer a one-request accept decision.', 'Decline or stop this request; the dashboard will not substitute a session-wide grant.', False),
    'command_missing': ('The exact command for this approval is missing.', 'Leave it pending and try reviewing again. Do not approve using a parent command as a substitute.', True),
    'cwd_missing': ('The exact working directory for this approval is missing.', 'Leave it pending and try reviewing again, or decline or stop this request.', True),
    'cached_context_mismatch': ('The approval context differs from its cached native item.', 'Leave it pending for compatibility investigation; do not approve a substituted command.', True),
    'unsupported_permissions': ('The requested permission overlay has an unsupported shape.', 'Leave it pending for compatibility investigation, or decline or stop the run.', False),
    'managed_network_scope': ('This is a managed-network approval that may release multiple queued requests.', 'Decline or stop this request; grouped network approvals are not supported.', False),
    'session_file_grant': ('This file request asks for a session-wide root grant.', 'Decline or stop this request; ask for a single bounded file-change request.', False),
    'file_changes_missing': ('The complete file changes for this exact native item are missing.', 'Leave it pending and try reviewing again, or decline or stop this request.', True),
    'scanner_unavailable': ('The reviewed sensitive-content scanner is unavailable.', 'Restore the required scanner and configuration, then try reviewing again. Nothing was approved.', True),
    'scanner_blocked': ('Sensitive-content checks did not pass; the context is withheld.', 'Inspect the operation safely for sensitive data or a scanner error before trying again. Nothing was approved.', True),
    'scanner_failed': ('Sensitive-content checks could not complete.', 'Restore the local scanner service, then try reviewing again. Nothing was approved.', True),
    'sensitive_review_disabled': ('Local sensitive-request review is disabled.', 'Enable local sensitive-request review in Settings, or ask for a reviewable alternative.', False),
    'sensitive_confirmation_required': ('Explicit confirmation of local sensitive-request review is required.', 'Reveal and review this exact request locally, then explicitly approve it once.', False),
    'sensitive_review_not_needed': ('This request passed sensitive-content checks.', 'Use the standard complete review and Approve once.', True),
    'request_changed': ('This request changed during review.', 'Review the current request again before approving.', True),
    'receipt_required': ('A current complete review is required before approval.', 'Review this request again, then choose Approve once.', True),
    'request_busy': ('A decision or guidance operation is already in progress for this request.', 'Wait for that operation to finish, then refresh.', True),
    'alternative_unavailable': ('This native request cannot receive guidance followed by a scoped decline.', 'Use the supported request controls or stop this run.', False),
    'decline_not_offered': ('Codex did not offer a decline that continues this turn.', 'Approve once after a complete review, or stop the run. The dashboard will not substitute an interruption for a continuing decline.', False),
    'cancel_not_offered': ('Codex did not offer a scoped cancellation for this request.', 'Use the available request controls or stop the run explicitly.', False),
    'guidance_rejected': ('Codex rejected the guidance; the request was not declined.', 'Review the current request or stop the run. Nothing was retried.', True),
    'guidance_invalid': ('The guidance is invalid or did not pass sensitive-content checks.', 'Use bounded plain text without sensitive data, then try again. Nothing was sent or declined.', True),
    'project_policy_unavailable': ('Project approval settings could not be verified.', 'Review this request manually or restore valid settings. No automatic decision was sent.', True),
    'project_policy_changed': ('Automatic approval was revoked or changed before this decision.', 'Review this pending request manually. Enabling automatic mode does not approve existing requests.', False),
    'automatic_queue_full': ('The automatic review queue is full.', 'Review this request manually. No automatic decision was sent.', False),
}


class ReviewError(ValueError):
    def __init__(self, code, sensitive_findings=False):
        self.code = code if code in REVIEW_FAILURES else 'unsupported_shape'
        self.sensitive_findings = sensitive_findings and self.code == 'scanner_blocked'
        super().__init__(REVIEW_FAILURES[self.code][0])

    def public(self):
        message, action, retryable = REVIEW_FAILURES[self.code]
        return {'error': message, 'code': self.code, 'action': action, 'retryable': retryable}


def bounded(value):
    encoded = json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(',', ':')).encode('utf-8')
    if len(encoded) > MAX_CONTEXT:
        raise ReviewError('context_too_large')
    # JSON escaping alone can hide bidi/zero-width controls from a human reviewer.
    for char in encoded.decode('utf-8'):
        if unicodedata.category(char) in {'Cf', 'Cs'}:
            raise ReviewError('unsafe_text')
    def check(item, depth=0):
        if depth > 16:
            raise ReviewError('unsupported_shape')
        if isinstance(item, str):
            if any(unicodedata.category(c) in {'Cc', 'Cf', 'Cs'} and c not in '\n\t' for c in item):
                raise ReviewError('unsafe_text')
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
        raise ReviewError('unsupported_shape')


def string(value, optional=False, empty=False, code='context_missing'):
    if optional and value is None:
        return
    if not isinstance(value, str) or (not empty and not value.strip()):
        raise ReviewError(code)


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
            raise ReviewError('unsupported_shape')
        if special['kind'] != 'project_roots' and 'subpath' in special:
            raise ReviewError('unsupported_shape')
        string(special.get('subpath'), optional=True, empty=True)
    else:
        raise ReviewError('unsupported_shape')


def permissions(value):
    if value is None:
        return
    shape(value, ('fileSystem', 'network'))
    network = value.get('network')
    if network is not None:
        shape(network, ('enabled',))
        if network.get('enabled') is not None and type(network['enabled']) is not bool:
            raise ReviewError('unsupported_shape')
    fs = value.get('fileSystem')
    if fs is not None:
        shape(fs, ('entries', 'globScanMaxDepth', 'read', 'write'))
        depth = fs.get('globScanMaxDepth')
        if depth is not None and (type(depth) is not int or depth < 1):
            raise ReviewError('unsupported_shape')
        for key in ('read', 'write', 'entries'):
            entries = fs.get(key)
            if entries is None:
                continue
            if not isinstance(entries, list) or len(entries) > 100:
                raise ReviewError('unsupported_shape')
            for entry in entries:
                if key != 'entries':
                    string(entry)
                else:
                    shape(entry, ('access', 'path'), ('access', 'path'))
                    if entry['access'] not in {'read', 'write', 'deny'}:
                        raise ReviewError('unsupported_shape')
                    path_entry(entry['path'])


def string_list(value):
    if not isinstance(value, list) or len(value) > 100:
        raise ReviewError('unsupported_shape')
    for item in value:
        string(item, empty=True)


def network_amendment(value):
    shape(value, ('action', 'host'), ('action', 'host'))
    if value['action'] not in {'allow', 'deny'}:
        raise ReviewError('unsupported_shape')
    string(value['host'])


def command_actions(value):
    if value is None:
        return
    if not isinstance(value, list) or len(value) > 100:
        raise ReviewError('unsupported_shape')
    for action in value:
        shape(action, ('type', 'command', 'name', 'path', 'query'), ('type', 'command'))
        kind = action['type']
        allowed = {'read': ('type', 'command', 'name', 'path'),
                   'listFiles': ('type', 'command', 'path'),
                   'search': ('type', 'command', 'path', 'query'),
                   'unknown': ('type', 'command')}.get(kind)
        if allowed is None:
            raise ReviewError('unsupported_shape')
        shape(action, allowed, allowed if kind == 'read' else ('type', 'command'))
        for key, val in action.items():
            string(val, optional=key in {'path', 'query'} and kind != 'read', empty=True)


class ApprovalReviews:
    """Bounded item cache. Caller serializes mutations with the dashboard lock."""
    def __init__(self):
        self.items = OrderedDict()
        self.failures = OrderedDict()
        self.size = 0

    def clear(self):
        self.items.clear()
        self.failures.clear()
        self.size = 0

    def discard(self, key):
        old = self.items.pop(key, None)
        self.failures.pop(key, None)
        if old:
            self.size -= old[1]

    def expire(self, thread_id, turn_id=None):
        for key in set(self.items) | set(self.failures):
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
        except (ValueError, TypeError, UnicodeError, RecursionError) as error:
            code = error.code if isinstance(error, ReviewError) else 'unsupported_cached_item'
            if code == 'unsupported_shape':
                code = 'unsupported_cached_item'
            self.failures[key] = code
            while len(self.failures) > MAX_ITEMS:
                self.failures.popitem(last=False)
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
            raise ReviewError('unsupported_shape')
        base = {key: params[key] for key in ('threadId', 'turnId', 'itemId', 'startedAtMs')}
        string(params.get('reason'), optional=True, empty=True)
        cache_key = (params['threadId'], params['turnId'], params['itemId'])
        cached = self.items.get(cache_key, ({}, 0))[0]
        if kind == 'command':
            shape(params, ('threadId', 'turnId', 'itemId', 'startedAtMs', 'additionalPermissions',
                          'approvalId', 'availableDecisions', 'command', 'commandActions', 'cwd',
                          'environmentId', 'kind', 'networkApprovalContext', 'proposedExecpolicyAmendment',
                          'proposedNetworkPolicyAmendments', 'reason'))
            # Real 0.163 local-only App Server callbacks identify this environment as
            # 'local'; never infer that any other native environment is local.
            if params.get('kind', 'command') != 'command':
                raise ReviewError('unsupported_action')
            if params.get('environmentId') not in (None, 'local'):
                raise ReviewError('unsupported_environment')
            decisions = params.get('availableDecisions')
            # A missing/null list does not prove that this callback permits acceptance.
            if not isinstance(decisions, list) or 'accept' not in decisions:
                raise ReviewError('accept_not_offered')
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
                raise ReviewError('unsupported_shape')
            context = {**base, **deepcopy(params)}
            callback = params.get('approvalId') is not None
            if callback:
                string(params['approvalId'])
                # Native zsh-exec-bridge subcommands share a parent itemId but have
                # distinct callback IDs. Review the exact callback, not its parent.
                context['parentItemContext'] = deepcopy(cached) if cached else None
            for key in ('command', 'cwd'):
                if context.get(key) is None and not callback:
                    context[key] = cached.get(key)
                    if context[key] is None and cache_key in self.failures:
                        raise ReviewError(self.failures[cache_key])
                string(context.get(key), code='command_missing' if key == 'command' else 'cwd_missing')
                if not callback and cached.get(key) is not None and context[key] != cached[key]:
                    raise ReviewError('cached_context_mismatch')
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
                    raise ReviewError('unsupported_shape')
                for proposal in proposals:
                    network_amendment(proposal)
            try:
                permissions(context['additionalPermissions'])
            except (ValueError, TypeError, KeyError):
                raise ReviewError('unsupported_permissions') from None
            net = context['networkApprovalContext']
            if net is not None:
                # Managed-network approval can release several queued requests for a
                # host/protocol; native context omits the port and exact command set.
                raise ReviewError('managed_network_scope')
        elif kind == 'file_change':
            shape(params, ('threadId', 'turnId', 'itemId', 'startedAtMs', 'reason', 'grantRoot'))
            # Native grantRoot is documented as a session-long root grant, not one patch.
            if params.get('grantRoot') is not None:
                raise ReviewError('session_file_grant')
            changes = cached.get('changes')
            if not isinstance(changes, list) or not changes or len(changes) > 100:
                raise ReviewError(self.failures.get(cache_key, 'file_changes_missing'))
            for change in changes:
                shape(change, ('path', 'kind', 'diff'), ('path', 'kind', 'diff'))
                string(change['path'])
                string(change['diff'], empty=True)
                operation = change['kind']
                shape(operation, ('type', 'move_path'), ('type',))
                if operation['type'] not in {'add', 'delete', 'update'}:
                    raise ReviewError('unsupported_shape')
                if 'move_path' in operation and operation['type'] != 'update':
                    raise ReviewError('unsupported_shape')
                string(operation.get('move_path'), optional=True)
            context = {**base, 'reason': params.get('reason'), 'grantRoot': None,
                       'changes': deepcopy(changes)}
        else:
            raise ReviewError('unsupported_shape')
        bounded(context)
        return context
