"""Task output associations use disposable projects and synthetic native calls."""
from copy import deepcopy
import http.client
import json
import os
import sqlite3
import threading
from unittest.mock import patch

from dashboard.project_files import FileAccessError, SensitiveContentError, preview_file
from dashboard.server import Dashboard, make_server
from tests.policy_fixtures import SyntheticPolicy
from tests.test_delivery_backend import DeliveryFixture


class TaskOutputTests(DeliveryFixture):
    def attach(self, path='feature.py', **updates):
        return self.app.attach_task_output(self.subject['id'], {'path': path,
            'expected_turn_id': self.app.tasks[self.subject['id']]['turn_id'], 'confirmed': True, **updates})

    def output(self, identifier):
        return self.app.task_output(self.subject['id'], identifier)

    def test_attach_open_idempotence_persistence_and_metadata_only_state(self):
        row = self.attach()['output']
        self.assertEqual(row, self.attach()['output'])
        self.assertEqual('feature.py', row['title'])
        self.assertEqual('human', row['source'])
        status, result = self.output(row['id'])
        self.assertEqual(200, status)
        self.assertEqual('available', result['state'])
        self.assertIn('example', result['content'])
        with patch('dashboard.task_outputs.preview_file', side_effect=AssertionError('State must not read files')):
            task = next(row for row in self.app.snapshot()['tasks'] if row['id'] == self.subject['id'])
        self.assertEqual([row], task['outputs'])
        self.assertNotIn('content', str(task['outputs']))
        self.assertNotIn('sha256', task['outputs'][0])
        self.app.close()
        self.app = Dashboard(self.root / 'state', policy_provider=SyntheticPolicy())
        self.assertEqual(row, self.app.output_metadata(self.app.tasks[self.subject['id']])[0])
        self.assertEqual('available', self.output(row['id'])[1]['state'])

    def test_changed_missing_scanner_block_and_unavailable_never_return_content(self):
        row = self.attach()['output']
        (self.project_root / 'feature.py').write_text('print("updated report")\n')
        self.assertEqual('changed', self.output(row['id'])[1]['state'])
        self.assertNotIn('content', self.output(row['id'])[1])
        updated = self.attach()['output']
        self.assertNotEqual(row['id'], updated['id'])
        self.assertEqual('available', self.output(updated['id'])[1]['state'])
        for error, expected, state in [(SensitiveContentError(), 403, 'blocked'),
                                      (FileAccessError(503, 'synthetic scanner unavailable'), 503, 'unavailable')]:
            with patch('dashboard.project_files.scan_preview', side_effect=error):
                status, result = self.output(updated['id'])
            self.assertEqual((expected, state), (status, result['state']))
            self.assertNotIn('content', result)
        (self.project_root / 'feature.py').unlink()
        self.assertEqual((404, 'missing'), (self.output(updated['id'])[0], self.output(updated['id'])[1]['state']))

    def test_invalid_identity_paths_turn_confirmations_and_cross_task(self):
        row = self.attach()['output']
        for updates in ({'confirmed': 1}, {'extra': True}, {'expected_turn_id': 'old'}):
            with self.assertRaises((ValueError, FileAccessError)):
                self.attach(**updates)
        for path in ('../outside', '/etc/passwd', '.env', '.git/config', 'missing.md'):
            with self.assertRaises(FileAccessError):
                self.attach(path)
        other = deepcopy(self.app.tasks[self.subject['id']])
        other.update(id='a' * 32, outputs=[])
        self.app.tasks[other['id']] = other
        with self.assertRaises(FileAccessError):
            self.app.task_output(other['id'], row['id'])
        self.app.tasks[self.subject['id']]['turn_id'] = 'new-turn'
        self.assertEqual([], self.app.output_metadata(self.app.tasks[self.subject['id']]))
        with self.assertRaises(FileAccessError):
            self.output(row['id'])

    def test_context_changes_during_preview_and_storage_failure_do_not_publish(self):
        real = preview_file
        mutations = [lambda: self.app.tasks[self.subject['id']].update(turn_id='changed-turn'),
                     lambda: self.app.tasks[self.subject['id']].update(project_id='missing-project'),
                     lambda: self.app.projects[self.project['id']].update(name='changed-project')]
        for mutate in mutations:
            task, project = deepcopy(self.app.tasks[self.subject['id']]), deepcopy(self.app.projects[self.project['id']])
            def race(*args):
                result = real(*args)
                mutate()
                return result
            with patch('dashboard.task_outputs.preview_file', side_effect=race), self.assertRaises(FileAccessError):
                self.attach()
            self.app.tasks[self.subject['id']] = task
            self.app.projects[self.project['id']] = project
        with patch.object(self.app.store, 'put', side_effect=sqlite3.OperationalError('synthetic failure')):
            with self.assertRaises(FileAccessError) as error:
                self.attach()
        self.assertEqual(503, error.exception.status)
        self.assertEqual([], self.app.output_metadata(self.app.tasks[self.subject['id']]))

    def native(self, **updates):
        message = {'id': 800, 'method': 'item/tool/call', 'params': {'threadId': self.subject['thread_id'],
            'turnId': self.subject['turn_id'], 'tool': 'register_task_output', 'callId': 'output-call',
            'arguments': {'path': 'feature.py'}, **updates}}
        self.app._output_tool(message)
        return self.client.responses[-1][1]['success']

    def test_native_registration_positive_and_no_child_stale_limited_or_assessment_authority(self):
        task = self.app.tasks[self.subject['id']]
        task['status'] = 'running'
        owned = self.app._owned(task['thread_id'])
        owned['active'] = True
        self.assertTrue(self.native())
        self.assertEqual('native', self.app.output_metadata(self.app.tasks[task['id']])[0]['source'])
        for update in ({'turnId': 'stale'}, {'namespace': 'other'}, {'arguments': {'path': 'feature.py', 'task_id': task['id']}}):
            self.assertFalse(self.native(**update))
        for key, value in [('limited', True), ('parent', 'child-parent'), ('active', False), ('current_turn', 'old-turn')]:
            previous = owned.get(key)
            owned[key] = value
            self.assertFalse(self.native())
            owned[key] = previous
        for key, value in [('task_purpose', 'recovery_assessment'), ('delivery_context', {'kind': 'review'}),
                           ('recovery_stop_pending', True), ('recovery_hold', True)]:
            task = self.app.tasks[self.subject['id']]
            previous = task.get(key)
            task[key] = value
            self.assertFalse(self.native())
            if previous is None:
                task.pop(key)
            else:
                task[key] = previous
        self.app.resolved_requests.add(800)
        self.assertFalse(self.native())

    def test_dynamic_tool_is_advertised_and_dispatches_on_live_root(self):
        options = next(params for method, params in self.client.requests if method == 'thread/start')
        self.assertIn('register_task_output', {tool['name'] for tool in options['dynamicTools']})
        task = self.app.tasks[self.subject['id']]
        task['status'] = 'running'
        self.app._owned(task['thread_id'])['active'] = True
        self.app.on_message({'id': 801, 'method': 'item/tool/call', 'params': {
            'threadId': task['thread_id'], 'turnId': task['turn_id'], 'tool': 'register_task_output',
            'arguments': {'path': 'feature.py'}, 'callId': 'native-output-call'}})
        self.app.wait_conversations()
        self.assertTrue(self.client.responses[-1][1]['success'])
        for name in ('runtime_tracking_lost', 'runtime_requests_disabled'):
            setattr(self.app, name, True)
            self.assertFalse(self.native())
            setattr(self.app, name, False)
        self.app.connection['status'] = 'disconnected'
        self.assertFalse(self.native())

    def test_registration_rechecks_live_authority_and_directory_after_scan(self):
        task = self.app.tasks[self.subject['id']]
        task['status'] = 'running'
        owned = self.app._owned(task['thread_id'])
        owned['active'] = True
        def disconnect(*args):
            result = preview_file(*args)
            self.app.connection['status'] = 'disconnected'
            return result
        with patch('dashboard.task_outputs.preview_file', side_effect=disconnect):
            self.assertFalse(self.native())
        self.assertEqual([], self.app.output_metadata(task))
        self.app.connection['status'] = 'connected'
        def replace_root(*args):
            result = preview_file(*args)
            self.project_root.rename(self.root / 'previous-project')
            self.project_root.mkdir()
            return result
        with patch('dashboard.task_outputs.preview_file', side_effect=replace_root):
            self.assertFalse(self.native())
        self.assertEqual([], self.app.output_metadata(task))

    def test_file_mutation_replacement_parent_swap_and_hardlink_during_scan_block(self):
        path = self.project_root / 'feature.py'
        for mode in ('mutate', 'replace', 'hardlink'):
            path.write_text('safe original\n')
            def race(_data):
                if mode == 'mutate':
                    path.write_text('safe modified\n')
                elif mode == 'replace':
                    path.unlink()
                    path.write_text('safe replacement\n')
                else:
                    os.link(path, self.project_root / 'copy.py')
            with patch('dashboard.project_files.scan_preview', side_effect=race), self.assertRaises(FileAccessError):
                preview_file(self.project_root, 'feature.py')
            if (self.project_root / 'copy.py').exists():
                (self.project_root / 'copy.py').unlink()
        folder = self.project_root / 'reports'
        folder.mkdir()
        (folder / 'result.md').write_text('safe original\n')
        def swap(_data):
            folder.rename(self.project_root / 'previous-reports')
            folder.mkdir()
            (folder / 'result.md').write_text('safe replacement\n')
        with patch('dashboard.project_files.scan_preview', side_effect=swap), self.assertRaises(FileAccessError):
            preview_file(self.project_root, 'reports/result.md')

    def test_output_limit_and_scanner_failures_leave_no_phantom_associations(self):
        with patch('dashboard.task_outputs.scan_preview', side_effect=FileAccessError(503, 'unavailable')):
            with self.assertRaises(FileAccessError):
                self.attach()
        self.assertEqual([], self.app.output_metadata(self.app.tasks[self.subject['id']]))
        for index in range(8):
            path = f'report{index}.md'
            (self.project_root / path).write_text('safe report\n')
            self.attach(path)
        with self.assertRaises(FileAccessError) as error:
            self.attach()
        self.assertEqual(409, error.exception.status)

    def test_http_origin_exact_fields_and_read_only_open(self):
        server = make_server(self.app, 0)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        route = '/api/tasks/' + self.subject['id'] + '/outputs'
        def request(method, path, data=None, origin=True):
            connection = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=15)
            headers = {'Content-Type': 'application/json'}
            if origin:
                headers['Origin'] = 'http://127.0.0.1:' + str(server.server_port)
            connection.request(method, path, body=json.dumps(data) if data else None, headers=headers)
            response = connection.getresponse()
            result = response.status, json.loads(response.read())
            connection.close()
            return result
        data = {'path': 'feature.py', 'expected_turn_id': self.subject['turn_id'], 'confirmed': True}
        try:
            self.assertEqual(403, request('POST', route, data, origin=False)[0])
            self.assertEqual(400, request('POST', route, {**data, 'extra': True})[0])
            status, result = request('POST', route, data)
            self.assertEqual(200, status)
            self.assertEqual('available', request('GET', route + '/' + result['output']['id'])[1]['state'])
        finally:
            server.shutdown()
            server.server_close()
            worker.join(2)


class DeliverySummaryTests(DeliveryFixture):
    def test_summary_is_historical_cache_and_state_never_takes_snapshots(self):
        self.assertEqual('not_checked', self.app.delivery_summary(self.subject)['status'])
        detail = self.delivery()
        summary = self.app.delivery_summary(self.subject)
        self.assertEqual(detail['status'], summary['status'])
        self.assertEqual('historical', summary['freshness'])
        with patch('dashboard.delivery.code_snapshot', side_effect=AssertionError('No per-row snapshots')):
            state = self.app.snapshot()
        self.assertEqual(summary, state['tasks'][0]['delivery_summary'])
        self.plan()
        self.assertEqual('stale', self.app.delivery_summary(self.subject)['freshness'])
        self.delivery()
        self.app.connection['status'] = 'disconnected'
        self.assertEqual('stale', self.app.delivery_summary(self.subject)['freshness'])
