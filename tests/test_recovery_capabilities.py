"""Pure predicate tests with synthetic proof; these do not establish native behavior."""
from copy import deepcopy
from types import SimpleNamespace
import unittest

from dashboard.recovery_capabilities import (
    AssessmentCapabilityUnavailable, RecoveryCapabilities,
)


class StartupClient:
    """Synthetic metadata client; never spawns a native process or model turn."""
    def __init__(self, *, rows=None, event=None, cursor=None):
        self.process = None
        self.closed = False
        self.rows = [] if rows is None else rows
        self.event = event
        self.cursor = cursor
        self.on_message = lambda message: None
        self.requests = []

    def connect(self):
        self.process = object()
        self.requests += [('initialize', {}), ('initialized', {})]
        if self.event:
            self.on_message(self.event)

    def request_readonly(self, method, params, *, timeout=30):
        return self.request(method, params, timeout=timeout)

    def request(self, method, params, timeout=30):
        self.requests.append((method, params))
        if method != 'thread/loaded/list':
            raise AssertionError('Unexpected native action in startup observation')
        return {'data': self.rows, 'nextCursor': self.cursor}


class RecoveryCapabilityTests(unittest.TestCase):
    def setUp(self):
        self.provider = RecoveryCapabilities(clock=lambda: 100.)
        self.client = StartupClient()
        self.provider.connect_and_observe_startup(self.client, 'e' * 64)
        self.owner = SimpleNamespace(exclusive=True, owner_id='a' * 32, boot_id='b' * 64)
        self.task = {'id': 'task', 'thread_id': 'thread', 'turn_id': 'turn', 'status': 'unknown'}
        self.children = {'count': 0, 'unresolved': 0}
        self.record = {'id': 'task', 'restart': {'planned': True, 'pre_boot_id': 'c' * 64},
            'clearance_evidence': {'source': 'native_metadata', 'task_id': 'task', 'thread_id': 'thread',
                'turn_id': 'turn', 'owner_id': self.owner.owner_id, 'boot_id': self.owner.boot_id,
                'connection_generation': 'e' * 64, 'source_stamp': 'd' * 64,
                'checked_monotonic': 99., 'metadata_complete': True, 'activity_complete': True,
                'reason_codes': [], 'observations': [
                    {'kind': 'root_runtime', 'status': 'idle', 'source': 'native_metadata'},
                    {'kind': 'descendant_activity', 'status': 'checked', 'count': 0, 'source': 'native_metadata'}],
                'last_turn': {'id': 'turn', 'status': 'completed', 'source': 'native_metadata'}}}

    def check(self):
        return self.provider.clearance(task=self.task, recovery=self.record,
                                       children=self.children, owner=self.owner)

    def test_supported_strategy_never_enables_native_assessment_or_resume(self):
        self.assertEqual({'assessment': False, 'same_thread': False, 'new_linked': True}, self.provider.describe())
        self.assertFalse(self.provider.validate_assessment({}, {}, {}))
        with self.assertRaises(AssessmentCapabilityUnavailable):
            self.provider.assessment_options({}, {}, {})

    def test_default_missing_reviewed_native_startup_evidence_stays_blocked(self):
        self.provider = RecoveryCapabilities()
        self.assertEqual(['startup_unverified'], self.check()['reason_codes'])

    def test_changed_connection_generation_or_closed_client_invalidates_startup_observation(self):
        self.record['clearance_evidence']['connection_generation'] = 'f' * 64
        self.assertFalse(self.check()['cleared'])
        self.record['clearance_evidence']['connection_generation'] = 'e' * 64
        self.client.closed = True
        self.assertFalse(self.check()['cleared'])

    def test_actual_startup_observation_only_uses_initialize_and_loaded_list(self):
        self.assertEqual(['initialize', 'initialized', 'thread/loaded/list', 'thread/loaded/list'],
                         [method for method, _ in self.client.requests])
        for client in (StartupClient(rows=['active']), StartupClient(cursor='next'),
                       StartupClient(event={'method': 'turn/started'}),
                       StartupClient(event={'method': 'item/started'}),
                       StartupClient(event={'method': 'mcpServer/startupStatus/updated'}),
                       StartupClient(event={'method': 'unrecognized/futureExecution'}),
                       StartupClient(event={'id': 'request', 'method': 'request/approval'})):
            provider = RecoveryCapabilities()
            self.assertFalse(provider.connect_and_observe_startup(client, 'e' * 64))
        with self.assertRaises(ValueError):
            self.provider.connect_and_observe_startup(self.client, 'e' * 64)

    def test_startup_diagnostics_copy_no_native_identifiers_or_payload(self):
        client = StartupClient(event={'method': 'unknown/method', 'params': {'private': 'do not copy'}})
        provider = RecoveryCapabilities()
        self.assertFalse(provider.connect_and_observe_startup(client, 'e' * 64))
        self.assertEqual(('startup_unknown_notification',), provider.startup_reason_codes)
        client = StartupClient(rows=['private-native-thread'])
        self.assertFalse(provider.connect_and_observe_startup(client, 'e' * 64))
        self.assertEqual(('loaded_threads_present',), provider.startup_reason_codes)

    def test_only_exact_disabled_remote_control_status_is_passive_metadata(self):
        for status in ('disabled', 'connecting', 'connected', 'errored', None, 'unknown'):
            client = StartupClient(event={'method': 'remoteControl/status/changed',
                'params': {'status': status, 'installationId': 'private', 'serverName': 'private'}})
            provider = RecoveryCapabilities()
            self.assertEqual(status == 'disabled', provider.connect_and_observe_startup(client, 'e' * 64))
            self.assertEqual(() if status == 'disabled' else ('startup_remote_control_notification',),
                             provider.startup_reason_codes)

    def test_later_remote_control_activity_stays_invalid_after_disabled_notification(self):
        self.assertTrue(self.provider.startup_current(self.client, 'e' * 64))
        self.assertFalse(self.provider.observe_runtime_notification({
            'method': 'remoteControl/status/changed', 'params': {'status': 'disabled'}}))
        self.assertTrue(self.check()['cleared'])
        self.assertTrue(self.provider.observe_runtime_notification({
            'method': 'remoteControl/status/changed', 'params': {'status': 'connected'}}))
        self.assertFalse(self.provider.startup_current(self.client, 'e' * 64))
        self.assertEqual(['startup_unverified'], self.check()['reason_codes'])
        self.provider.observe_runtime_notification({'method': 'remoteControl/status/changed',
                                                    'params': {'status': 'disabled'}})
        self.assertFalse(self.check()['cleared'])

    def test_malformed_later_remote_status_invalidates_but_ordinary_events_do_not(self):
        self.assertFalse(self.provider.observe_runtime_notification({'method': 'turn/completed', 'params': {}}))
        self.assertTrue(self.provider.startup_current(self.client, 'e' * 64))
        self.assertTrue(self.provider.observe_runtime_notification({'method': 'remoteControl/status/changed', 'params': None}))
        self.assertFalse(self.check()['cleared'])

    def test_conjunction_clears_only_previous_local_process_epoch_and_preserves_old_outcome(self):
        before = deepcopy((self.task, self.record, self.children))
        result = self.check()
        self.assertTrue(result['cleared'])
        self.assertTrue(result['historical_fence'])
        self.assertEqual(before, (self.task, self.record, self.children))
        self.assertEqual('previous_boot_ended', result['observations'][0]['status'])

    def test_same_boot_missing_boot_or_unplanned_restart_stays_blocked(self):
        for restart in (None, {}, {'planned': True}, {'planned': True, 'pre_boot_id': self.owner.boot_id},
                        {'planned': 'true', 'pre_boot_id': 'c' * 64}):
            self.record['restart'] = restart
            self.assertFalse(self.check()['cleared'])

    def test_owner_exclusive_identity_and_boot_must_match_current_observation(self):
        for key, value in (('exclusive', False), ('exclusive', 1), ('owner_id', 'reused'), ('boot_id', 'invalid')):
            old = getattr(self.owner, key)
            setattr(self.owner, key, value)
            self.assertFalse(self.check()['cleared'])
            setattr(self.owner, key, old)

    def test_current_evidence_not_previous_recovery_or_human_claim(self):
        original = deepcopy(self.record['clearance_evidence'])
        for changes in ({'source': 'human_annotation'}, {'task_id': 'other'}, {'thread_id': 'other'},
                        {'turn_id': 'other'}, {'owner_id': 'f' * 32}, {'boot_id': 'f' * 64},
                        {'source_stamp': ''}, {'connection_generation': ''}):
            self.record['clearance_evidence'] = dict(original, **changes)
            self.assertFalse(self.check()['cleared'])

    def test_stale_future_nan_or_boolean_monotonic_observation_is_rejected(self):
        for checked in (39., 101., float('nan'), float('inf'), True, None):
            self.record['clearance_evidence']['checked_monotonic'] = checked
            self.assertFalse(self.check()['cleared'])

    def test_fresh_postboot_historical_inprogress_is_not_relabelled(self):
        evidence = self.record['clearance_evidence']
        evidence['last_turn']['status'] = 'inProgress'
        evidence['reason_codes'] = ['turn_unresolved', 'historical_descendant_unresolved']
        self.assertTrue(self.check()['historical_fence'])
        self.assertEqual('inProgress', evidence['last_turn']['status'])
        self.assertEqual('unknown', self.task['status'])

    def test_current_activity_and_incomplete_coverage_are_never_waived_by_boot(self):
        evidence = self.record['clearance_evidence']
        for reason in ('root_active', 'active_descendant', 'goal_unresolved', 'background_activity',
                       'check_limit', 'ownership_unverified', 'unreconciled_turn',
                       'history_missing', 'unexpected_hydrated_items', 'transport_changed'):
            evidence['reason_codes'] = [reason]
            self.assertFalse(self.check()['cleared'], reason)
        evidence['reason_codes'] = []
        for key in ('metadata_complete', 'activity_complete'):
            evidence[key] = False
            self.assertFalse(self.check()['cleared'])
            evidence[key] = True

    def test_native_status_and_descendant_count_must_independently_agree(self):
        evidence = self.record['clearance_evidence']
        for status in ('active', 'systemError', 'unverified', None):
            evidence['observations'][0]['status'] = status
            self.assertFalse(self.check()['cleared'])
        evidence['observations'][0]['status'] = 'idle'
        self.children['count'] = 1
        self.assertFalse(self.check()['cleared'])
        evidence['observations'][1]['count'] = 1
        self.assertTrue(self.check()['cleared'])
        self.children['unresolved'] = 1
        self.assertFalse(self.check()['cleared'])

    def test_known_external_activity_cannot_be_cleared_by_local_boot(self):
        self.task['external_activity_unresolved'] = True
        self.assertEqual(['external_activity_unverified'], self.check()['reason_codes'])

    def test_missing_or_unknown_turn_never_fabricates_native_outcome(self):
        evidence = self.record['clearance_evidence']
        for last_turn in (None, {'id': 'other', 'status': 'completed', 'source': 'native_metadata'},
                          {'id': 'turn', 'status': 'unknown', 'source': 'native_metadata'},
                          {'id': 'turn', 'status': 'completed', 'source': 'human_annotation'}):
            evidence['last_turn'] = last_turn
            self.assertFalse(self.check()['cleared'])

    def test_absent_old_turn_can_cross_boot_fence_with_complete_current_activity(self):
        self.record['clearance_evidence'].update(last_turn=None, reason_codes=['turn_unverified'])
        self.assertTrue(self.check()['cleared'])

    def test_missing_history_requires_current_empty_loaded_inventory_after_boot(self):
        evidence = self.record['clearance_evidence']
        evidence.update(last_turn=None, reason_codes=['history_missing'], observations=[],
                        metadata_complete=False, activity_complete=False)
        self.assertFalse(self.check()['cleared'])
        evidence['history_absence'] = self.provider.inspect_unavailable_history(
            self.client, connection_generation='e' * 64)
        self.assertTrue(self.check()['cleared'])
        self.client.rows = ['unknown-active-thread']
        evidence['history_absence'] = self.provider.inspect_unavailable_history(
            self.client, connection_generation='e' * 64)
        self.assertFalse(self.check()['cleared'])

    def test_only_exact_bound_new_unstarted_continuation_may_be_exempt_from_inventory(self):
        self.client.rows = ['new-owned-thread']
        result = self.provider.inspect_unavailable_history(self.client, connection_generation='e' * 64)
        self.assertEqual('unverified', result['status'])
        result = self.provider.inspect_unavailable_history(self.client, connection_generation='e' * 64,
                                                          allowed_thread_id='new-owned-thread')
        self.assertEqual('no_conflicting_loaded_threads', result['status'])
        self.client.rows.append('another-thread')
        self.assertEqual('unverified', self.provider.inspect_unavailable_history(
            self.client, connection_generation='e' * 64, allowed_thread_id='new-owned-thread')['status'])


if __name__ == '__main__':
    unittest.main()
