"""New-linked recovery after a reviewed startup contract and observed local boot fence.

The capability description names supported strategies, not permission to execute them.
Native assessment and same-thread resume remain unsupported. The caller owns fresh
metadata acquisition and atomic source-stamp comparison before any native mutation.
"""
import hashlib
import json
import math
import re
import threading
import time

MAX_RECOVERY_DESCENDANTS = 256

ASSESSMENT_CONTRACT = {
    'version': 1,
    'purpose': 'recovery_assessment',
    'input': 'bounded_scanned_human_selected_packet',
    'authority': 'conversation_only',
    'unavailable': [
        'shell', 'filesystem_tools', 'mcp', 'plugins', 'connector_actions',
        'project_effect_hooks', 'goals', 'delegation', 'dynamic_tools',
        'model_network_tools', 'escalation',
    ],
    'security_controls': 'preserve_mandatory_hooks_scanners_and_admin_policy',
    'proof': 'unverified',
}


class AssessmentCapabilityUnavailable(ValueError):
    """Fixed safe error without native configuration or payload content."""

    def __init__(self):
        super().__init__('Restricted assessment capability has not passed native isolation proof')


def _digest(value):
    return isinstance(value, str) and re.fullmatch(r'[0-9a-f]{64}', value) is not None


class RecoveryCapabilities:
    """Require observed evidence; no HTTP flag or human assertion can clear activity."""

    contract_digest = hashlib.sha256(json.dumps(
        ASSESSMENT_CONTRACT, sort_keys=True, separators=(',', ':')
    ).encode('utf-8')).hexdigest()

    def __init__(self, *, clock=time.monotonic):
        self._clock = clock
        self._startup_lock = threading.RLock()
        self._startup_generation = None
        self._startup_client = None
        self.startup_reason_codes = ('startup_not_observed',)

    def connect_and_observe_startup(self, client, connection_generation):
        """Observe a fresh connection before any managed work can be dispatched.

        initialize/initialized plus two metadata-only loaded-list requests cannot
        themselves request model work. This bounded observation is generation-local
        evidence, not a signed attestation or a guarantee about external processes.
        Caller must construct a fresh client and keep dispatch disabled until return.
        Existing/live clients must never be passed here to manufacture a new epoch.
        """
        self._startup_generation = None
        self._startup_client = None
        self.startup_reason_codes = ('startup_observation_incomplete',)
        if not _digest(connection_generation) or getattr(client, 'process', None) is not None:
            raise ValueError('Startup observation requires a fresh client and exact generation')
        original = client.on_message
        unexpected = threading.Event()
        diagnostic_lock = threading.Lock()
        reasons = set()

        def reason(code):
            with diagnostic_lock:
                reasons.add(code)

        def observed(message):
            method = message.get('method') if isinstance(message, dict) else None
            # No payload is retained. Unknown events cannot establish quiet startup.
            harmless = {'account/updated', 'account/rateLimits/updated',
                        'account/gatewayOAuth/changed', 'deprecationNotice', 'configWarning'}
            params = message.get('params') if isinstance(message, dict) else None
            # Installed RemoteControlStatusChangedNotification declares 'disabled'.
            # Observe only that enum; never read/log installationId or serverName.
            remote_disabled = (method == 'remoteControl/status/changed'
                               and isinstance(params, dict) and params.get('status') == 'disabled')
            if (not isinstance(message, dict) or 'id' in message
                    or method not in harmless and not remote_disabled):
                if not isinstance(message, dict):
                    reason('malformed_notification')
                elif 'id' in message:
                    reason('startup_server_request')
                elif isinstance(method, str) and method.startswith('mcpServer/'):
                    reason('startup_mcp_notification')
                elif isinstance(method, str) and method.startswith(('thread/', 'turn/', 'item/', 'model/')):
                    reason('startup_execution_notification')
                elif isinstance(method, str) and method.startswith('codex/event'):
                    # Legacy discriminator names are allowlisted diagnostic codes;
                    # no native message fields, identifiers or payloads are copied.
                    known_legacy = {
                        'codex/event/session_configured': 'startup_legacy_session_configured',
                        'codex/event/mcp_startup_update': 'startup_legacy_mcp_update',
                        'codex/event/mcp_startup_complete': 'startup_legacy_mcp_complete',
                    }
                    reason(known_legacy.get(method, 'startup_legacy_notification'))
                else:
                    known_notices = {
                        'remoteControl/status/changed': 'startup_remote_control_notification',
                        'app/list/updated': 'startup_app_inventory_notification',
                        'skills/changed': 'startup_skill_inventory_notification',
                        'project/changed': 'startup_project_changed_notification',
                        'warning': 'startup_warning_notification',
                        'guardianWarning': 'startup_guardian_warning_notification',
                        'error': 'startup_error_notification',
                        'hook/started': 'startup_hook_notification',
                        'hook/completed': 'startup_hook_notification',
                        'fs/changed': 'startup_filesystem_notification',
                        'command/exec/outputDelta': 'startup_command_notification',
                        'process/outputDelta': 'startup_process_notification',
                        'process/exited': 'startup_process_notification',
                    }
                    reason(known_notices.get(method, 'startup_unknown_notification'))
                with self._startup_lock:
                    unexpected.set()
            original(message)

        def empty_loaded():
            response = client.request_readonly('thread/loaded/list', {'limit': 1}, timeout=3)
            if not isinstance(response, dict) or not isinstance(response.get('data'), list):
                reason('loaded_list_shape_unverified')
                return False
            if response.get('nextCursor') is not None:
                reason('loaded_list_incomplete')
                return False
            if response['data']:
                reason('loaded_threads_present')
                return False
            return True

        client.on_message = observed
        try:
            client.connect()
            first_empty = empty_loaded()
            # Bounded startup observation; it does not start or resume a native turn.
            unexpected.wait(.25)
            final_empty = empty_loaded()
            with self._startup_lock:
                if first_empty and final_empty and not unexpected.is_set() and not client.closed:
                    self._startup_client = client
                    self._startup_generation = connection_generation
                    self.startup_reason_codes = ()
                    return True
            if client.closed:
                reason('startup_transport_closed')
            return False
        finally:
            client.on_message = original
            with diagnostic_lock:
                if reasons:
                    self.startup_reason_codes = tuple(sorted(reasons))

    def describe(self):
        return {'assessment': False, 'same_thread': False, 'new_linked': True}

    def startup_current(self, client, connection_generation):
        with self._startup_lock:
            return (client is not None and client is self._startup_client and not client.closed
                    and self._startup_generation == connection_generation)

    def observe_runtime_notification(self, message):
        """A later remote writer permanently invalidates this connection's evidence."""
        if not isinstance(message, dict) or message.get('method') != 'remoteControl/status/changed':
            return False
        params = message.get('params')
        if isinstance(params, dict) and params.get('status') == 'disabled':
            return False
        with self._startup_lock:
            self._startup_generation = None
            self._startup_client = None
            self.startup_reason_codes = ('current_remote_control_unverified',)
        return True

    def inspect_unavailable_history(self, client, *, connection_generation, allowed_thread_id=None):
        """Current local loaded inventory, only for genuinely unavailable old history.

        The caller may exempt its exact owned newly attached continuation root before
        any turn is sent. This is not a browser-selectable arbitrary thread exemption.
        No thread contents or ids are returned or persisted by this method.
        """
        result = {'source': 'current_native_loaded_inventory',
                  'connection_generation': connection_generation,
                  'checked_monotonic': self._clock(), 'status': 'unverified', 'count': None}
        if (client is not self._startup_client or client.closed
                or connection_generation != self._startup_generation):
            return result
        response = client.request_readonly('thread/loaded/list', {'limit': 256}, timeout=3)
        rows = response.get('data') if isinstance(response, dict) else None
        if (not isinstance(rows, list) or len(rows) > 256 or response.get('nextCursor') is not None
                or any(not isinstance(identifier, str) for identifier in rows)
                or len(set(rows)) != len(rows)):
            return result
        permitted = {allowed_thread_id} if isinstance(allowed_thread_id, str) and allowed_thread_id else set()
        if set(rows) - permitted:
            return result
        result.update(status='no_conflicting_loaded_threads', count=len(rows), checked_monotonic=self._clock())
        return result

    def assessment_options(self, task, project, role):
        # Do not manufacture configuration keys or suppress mandatory security hooks.
        raise AssessmentCapabilityUnavailable()

    def validate_assessment(self, response, task, project):
        # read-only, approvalPolicy=never and dynamicTools=[] are not tool isolation.
        return False

    def clearance(self, *, task, recovery, children, owner):
        """Clear previous local processes, never their business or external outcomes.

        clearance_evidence is an internal snapshot of this check's sanitized native
        observations, not the previous persisted recovery record or user annotations.
        Native root/child/goal/background errors are not waived by a computer restart.
        Only stale stored inProgress/unknown-child records may cross a verified fence.
        """
        def blocked(reason):
            return {'cleared': False, 'historical_fence': False,
                    'reason_codes': [reason], 'observations': []}

        owner_id = getattr(owner, 'owner_id', None)
        boot_id = getattr(owner, 'boot_id', None)
        if (getattr(owner, 'exclusive', None) is not True or not isinstance(owner_id, str)
                or re.fullmatch(r'[0-9a-f]{32}', owner_id) is None):
            return blocked('single_owner_unverified')
        restart = recovery.get('restart')
        if not isinstance(restart, dict) or restart.get('planned') is not True:
            return blocked('boot_fence_required')
        previous_boot = restart.get('pre_boot_id')
        if not _digest(previous_boot) or not _digest(boot_id) or previous_boot == boot_id:
            return blocked('boot_fence_unverified')

        evidence = recovery.get('clearance_evidence')
        if not isinstance(evidence, dict):
            return blocked('metadata_unavailable')
        if (not self._startup_client or self._startup_client.closed
                or self._startup_generation != evidence.get('connection_generation')):
            return blocked('startup_unverified')
        if (evidence.get('source') != 'native_metadata' or evidence.get('task_id') != task.get('id')
                or recovery.get('id') != task.get('id') or not task.get('id')
                or evidence.get('thread_id') != task.get('thread_id')
                or evidence.get('turn_id') != task.get('turn_id')
                or evidence.get('owner_id') != owner_id or evidence.get('boot_id') != boot_id
                or not isinstance(evidence.get('connection_generation'), str)
                or not evidence['connection_generation'] or not _digest(evidence.get('source_stamp'))):
            return blocked('ownership_unverified')
        checked = evidence.get('checked_monotonic')
        if (type(checked) not in (float, int) or not math.isfinite(checked)
                or not 0 <= self._clock() - checked <= 60):
            return blocked('transport_changed')
        reasons = evidence.get('reason_codes')
        historical_reasons = {'turn_unresolved', 'historical_descendant_unresolved', 'turn_unverified', 'history_missing'}
        if (not isinstance(reasons, list) or any(not isinstance(reason, str) for reason in reasons)
                or set(reasons) - historical_reasons):
            return blocked('activity_unverified')
        absence = evidence.get('history_absence')
        history_absent = 'history_missing' in reasons
        if history_absent:
            observed = absence.get('checked_monotonic') if isinstance(absence, dict) else None
            if (not isinstance(absence, dict) or absence.get('source') != 'current_native_loaded_inventory'
                    or absence.get('connection_generation') != self._startup_generation
                    or absence.get('status') != 'no_conflicting_loaded_threads'
                    or type(absence.get('count')) is not int or absence['count'] not in (0, 1)
                    or type(observed) not in (float, int) or not math.isfinite(observed)
                    or not 0 <= self._clock() - observed <= 60):
                return blocked('metadata_unavailable')
        elif evidence.get('metadata_complete') is not True or evidence.get('activity_complete') is not True:
            return blocked('check_limit')
        observations = evidence.get('observations')
        if not isinstance(observations, list) or any(not isinstance(row, dict) for row in observations):
            return blocked('metadata_unavailable')
        roots = [row for row in observations if row.get('kind') == 'root_runtime']
        descendants = [row for row in observations if row.get('kind') == 'descendant_activity']
        if not history_absent and (len(roots) != 1 or roots[0].get('source') != 'native_metadata'
                or roots[0].get('status') not in {'idle', 'notLoaded'}
                or len(descendants) != 1 or descendants[0].get('source') != 'native_metadata'
                or descendants[0].get('status') != 'checked'):
            return blocked('activity_unverified')
        if (not isinstance(children, dict) or type(children.get('count')) is not int
                or not 0 <= children['count'] <= MAX_RECOVERY_DESCENDANTS or type(children.get('unresolved')) is not int
                or children['unresolved'] != 0 or not history_absent and (
                    type(descendants[0].get('count')) is not int or descendants[0]['count'] != children['count'])):
            return blocked('active_descendant')
        last_turn = evidence.get('last_turn')
        if last_turn is not None and (not isinstance(last_turn, dict) or last_turn.get('id') != task['turn_id']
                or last_turn.get('source') != 'native_metadata'
                or last_turn.get('status') not in {'completed', 'failed', 'interrupted', 'inProgress'}):
            return blocked('metadata_unavailable')
        if last_turn is None and not {'turn_unverified', 'history_missing'}.intersection(reasons):
            return blocked('metadata_unavailable')
        if task.get('external_activity_unresolved') is True:
            # Native local metadata and a reboot cannot establish remote quiescence.
            return blocked('external_activity_unverified')
        return {'cleared': True, 'historical_fence': True, 'reason_codes': [],
                'observations': [{'kind': 'local_process_epoch', 'status': 'previous_boot_ended',
                                  'source': 'verified_os_boot_identity'}]}
