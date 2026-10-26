"""Independent HTTP acceptance with disposable files and synthetic runtime events.

These checks do not launch Codex or establish native/browser integration evidence.
"""
import http.client
import json
from pathlib import Path
import subprocess
import tempfile
import threading
import unittest
import uuid

from dashboard.server import Dashboard, make_server, now, unknown_cost
from dashboard.settings import SettingsStore
from tests.policy_fixtures import SyntheticPolicy
from tests.test_dashboard_backend import FakeClient


class IsolatedUIFixture:
    def __init__(self):
        self.temp = tempfile.TemporaryDirectory(prefix='ui-review-acceptance-', dir='/private/tmp')
        self.root = Path(self.temp.name)
        self.project_root = self.root / 'project'
        self.project_root.mkdir()
        subprocess.run(['git', 'init', '-q', str(self.project_root)], check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        (self.project_root / 'report.md').write_text('# Synthetic report\n\nVerified fixture deliverable.\n')
        self.app = Dashboard(self.root / 'state', policy_provider=SyntheticPolicy())
        self.app.settings = SettingsStore(self.root, config_path=self.root / 'settings.toml')
        self.client = FakeClient()
        self.app.client = self.client
        self.app.connection.update(status='connected', detail='Synthetic test runtime; no Codex process.')
        self.project = self.app.add_project({'name': 'Synthetic UI acceptance', 'path': str(self.project_root)})
        self.server = self.thread = None

    def task(self, title='Synthetic approval journey', status='running'):
        identifier = uuid.uuid4().hex
        task = {'id': identifier, 'project_id': self.project['id'], 'title': title,
                'role': 'chief_of_staff', 'model': 'gpt-6.1-sol', 'reasoning': 'medium',
                'status': status, 'thread_id': 'fixture-thread-' + identifier,
                'turn_id': 'fixture-turn-' + identifier, 'plan': [], 'usage': None,
                'cost': unknown_cost(), 'error': None, 'created_at': now(), 'updated_at': now()}
        self.app.tasks[identifier] = task
        self.app.store.put('task', task)
        self.app._register_thread(task['thread_id'], identifier)
        self.app.owned_threads[task['thread_id']].update(current_turn=task['turn_id'], turns={task['turn_id']})
        return task

    def emit(self, task, method, **params):
        self.app.on_message({'method': method, 'params': {
            'threadId': task['thread_id'], 'turnId': task['turn_id'], **params}})

    def start_http(self):
        self.server = make_server(self.app, 0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        return self.server.server_port

    def request(self, path, body=None, origin=True):
        port = self.server.server_port
        headers = {'Origin': f'http://127.0.0.1:{port}'} if origin else {}
        if body is not None:
            headers['Content-Type'] = 'application/json'
        connection = http.client.HTTPConnection('127.0.0.1', port, timeout=10)
        connection.request('POST' if body is not None else 'GET', path,
                           json.dumps(body) if body is not None else None, headers)
        response = connection.getresponse()
        result = response.status, json.loads(response.read())
        connection.close()
        return result

    def close(self):
        if self.server:
            self.server.shutdown()
            self.server.server_close()
            self.thread.join(3)
        self.app.close()
        self.temp.cleanup()


class UIReviewHTTPAcceptance(unittest.TestCase):
    def setUp(self):
        self.fixture = IsolatedUIFixture()
        self.addCleanup(self.fixture.close)
        self.fixture.start_http()

    def test_completed_report_attach_open_reload_and_changed_file_are_distinct(self):
        f = self.fixture
        task = f.task(status='completed')
        path = f'/api/tasks/{task["id"]}/outputs'
        status, associated = f.request(path, {'path': 'report.md', 'expected_turn_id': task['turn_id'], 'confirmed': True})
        self.assertEqual(200, status)
        output = associated['output']
        status, opened = f.request(path + '/' + output['id'])
        self.assertEqual((200, 'available'), (status, opened['state']))
        self.assertIn('Verified fixture deliverable.', opened['content'])
        projected = next(t for t in f.request('/api/state')[1]['tasks'] if t['id'] == task['id'])
        self.assertEqual([output], projected['outputs'])
        self.assertNotIn('content', projected['outputs'][0])
        self.assertEqual('not_checked', projected['delivery_summary']['status'])
        persisted = next(t for t in f.app.store.load('task') if t['id'] == task['id'])
        self.assertEqual(output['id'], persisted['outputs'][0]['id'])
        (f.project_root / 'report.md').write_text('# Changed synthetic report\n')
        status, changed = f.request(path + '/' + output['id'])
        self.assertEqual((200, 'changed'), (status, changed['state']))
        self.assertNotIn('content', changed)
        (f.project_root / 'report.md').unlink()
        self.assertEqual((404, 'missing'), (lambda r: (r[0], r[1]['state']))(f.request(path + '/' + output['id'])))

    def test_report_association_cannot_cross_tasks_or_follow_up_turns(self):
        f = self.fixture
        task = f.task(status='completed')
        status, associated = f.request(f'/api/tasks/{task["id"]}/outputs',
            {'path': 'report.md', 'expected_turn_id': task['turn_id'], 'confirmed': True})
        self.assertEqual(200, status)
        other = f.task(status='completed')
        self.assertEqual(404, f.request(f'/api/tasks/{other["id"]}/outputs/{associated["output"]["id"]}')[0])
        f.app.tasks[task['id']]['turn_id'] = 'fixture-next-turn'
        projected = next(t for t in f.request('/api/state')[1]['tasks'] if t['id'] == task['id'])
        self.assertEqual([], projected['outputs'])
        self.assertEqual(404, f.request(f'/api/tasks/{task["id"]}/outputs/{associated["output"]["id"]}')[0])

    def test_supported_command_review_approval_continuation_and_completion(self):
        f = self.fixture
        task = f.task()
        f.app.on_message({'id': 51, 'method': 'item/commandExecution/requestApproval', 'params': {
            'threadId': task['thread_id'], 'turnId': task['turn_id'], 'itemId': 'synthetic-command',
            'startedAtMs': 1, 'command': '/usr/bin/true', 'cwd': str(f.project_root),
            'reason': 'Synthetic no-op command approval', 'availableDecisions': ['accept', 'decline', 'cancel']}})
        approval = next(iter(f.app.approvals.values()))
        self.assertEqual('waiting_approval', task['status'])
        status, review = f.request(f'/api/approvals/{approval["id"]}/review')
        self.assertEqual(200, status)
        self.assertEqual('/usr/bin/true', review['context']['command'])
        status, _ = f.request(f'/api/approvals/{approval["id"]}/respond', {'decision': 'accept', 'review_id': review['review_id']})
        self.assertEqual(200, status)
        self.assertEqual((51, {'decision': 'accept'}), f.client.responses[-1])
        self.assertEqual('running', task['status'])
        f.emit(task, 'item/completed', item={'id': 'synthetic-command', 'type': 'commandExecution',
            'status': 'completed', 'command': '/usr/bin/true', 'cwd': str(f.project_root), 'exitCode': 0})
        f.emit(task, 'turn/completed', turn={'id': task['turn_id'], 'status': 'completed'})
        self.assertEqual('completed', task['status'])
        self.assertEqual(409, f.request(f'/api/approvals/{approval["id"]}/respond', {'decision': 'accept', 'review_id': review['review_id']})[0])
        self.assertEqual(1, len(f.client.responses))
