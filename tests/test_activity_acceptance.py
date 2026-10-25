"""Independent HTTP activity acceptance using synthetic protocol events, no inference.

The preview scanner is stubbed; these checks do not prove native integration or
scanner effectiveness. Only ephemeral isolated loopback HTTP is exercised.
"""
import http.client
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from dashboard.server import Dashboard, make_server
from tests.test_dashboard_backend import FakeClient


class ActivityAcceptanceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir='/private/tmp')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.scan = patch('dashboard.conversation.scan_preview', return_value=None)
        self.scan.start()
        self.addCleanup(self.scan.stop)
        self.app = Dashboard(self.root / 'state')
        self.addCleanup(self.app.close)
        self.app.client = self.fake = FakeClient()
        self.app.connection['status'] = 'connected'
        self.server = make_server(self.app, 0)
        self.http_thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.http_thread.start()
        self.addCleanup(self.close_http)
        project = self.app.add_project({'name': 'Acceptance fixture', 'path': str(self.root)})
        result = self.app.start_task({'project_id': project['id'], 'title': 'Build activity view',
            'instruction': 'Synthetic acceptance task only', 'role': 'chief_of_staff'})
        self.app.workers[-1].join(3)
        self.assertFalse(self.app.workers[-1].is_alive())
        self.task = self.app.tasks[result['id']]
        self.assertTrue(self.task['turn_id'])

    def close_http(self):
        self.server.shutdown()
        self.server.server_close()
        self.http_thread.join(3)

    def get(self, path):
        connection = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=3)
        try:
            connection.request('GET', path)
            response = connection.getresponse()
            body = json.loads(response.read())
            self.assertEqual(200, response.status, body)
            self.assertEqual('no-store', response.getheader('Cache-Control'))
            return body
        finally:
            connection.close()

    def post(self, path, body):
        connection = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=3)
        try:
            connection.request('POST', path, json.dumps(body), {
                'Content-Type': 'application/json',
                'Origin': 'http://127.0.0.1:' + str(self.server.server_port)})
            response = connection.getresponse()
            self.assertEqual(200, response.status, response.read().decode() if response.status != 200 else path)
            return json.loads(response.read())
        finally:
            connection.close()

    def event(self, method, thread_id=None, **params):
        self.app.on_message({'method': method, 'params': {
            'threadId': thread_id or self.task['thread_id'],
            'turnId': self.task['turn_id'], **params}})

    def child(self, thread='worker', role='backend_developer', parent=None):
        self.event('thread/started', thread={'id': thread,
            'parentThreadId': parent or self.task['thread_id'], 'agentRole': role})
        self.event('turn/started', thread_id=thread,
            **{'turn': {'id': thread + '-turn', 'status': 'inProgress'}})

    def activities(self):
        return {a['thread_id']: a for a in self.get('/api/state')['delegated_activities']}

    def test_overview_and_team_routes_share_all_observed_work_and_parent_links(self):
        self.child()
        self.child('qa', 'qa_engineer', 'worker')
        state = self.get('/api/state')
        self.assertEqual([self.task['id']], [task['id'] for task in state['tasks']])
        activities = self.activities()
        self.assertEqual({'worker', 'qa'}, set(activities))
        self.assertEqual('worker', activities['qa']['parent_thread_id'])
        self.assertTrue(all(a['parent_task_id'] == self.task['id'] for a in activities.values()))
        members = {m['id']: m for m in self.get('/api/team')['members']}
        self.assertEqual('direct', members['chief_of_staff']['activities'][0]['source'])
        self.assertEqual('delegated', members['qa_engineer']['activities'][0]['source'])
        self.assertEqual(activities['qa']['id'], members['qa_engineer']['activities'][0]['id'])
        conversation = self.get('/api/tasks/' + activities['qa']['parent_task_id'] + '/conversation')
        self.assertEqual(self.task['turn_id'], conversation['turn_id'])
        self.assertEqual([], members['frontend_developer']['activities'])

    def test_child_request_and_completion_leave_sibling_status_independent(self):
        self.child()
        self.child('qa', 'qa_engineer')
        self.app.on_message({'id': 701, 'method': 'item/commandExecution/requestApproval',
            'params': {'threadId': 'worker', 'turnId': 'worker-turn', 'itemId': 'command',
                       'command': 'pwd', 'cwd': str(self.root)}})
        self.assertEqual('waiting_approval', self.activities()['worker']['status'])
        self.assertEqual('running', self.activities()['qa']['status'])
        approval = next(a for a in self.app.approvals.values() if a['status'] == 'pending')
        self.app.respond_approval(approval['id'], {'decision': 'decline'})
        self.assertEqual([(701, {'decision': 'decline'})], self.fake.responses)
        self.assertEqual('running', self.activities()['worker']['status'])
        self.event('turn/completed', thread_id='worker', **{'turn': {'id': 'worker-turn', 'status': 'completed'}})
        self.assertEqual('completed', self.activities()['worker']['status'])
        self.assertEqual('running', self.activities()['qa']['status'])

    def test_stale_child_completion_cannot_overwrite_new_turn(self):
        self.child()
        self.event('turn/started', thread_id='worker', **{'turn': {'id': 'new-turn', 'status': 'inProgress'}})
        self.event('turn/completed', thread_id='worker', **{'turn': {'id': 'worker-turn', 'status': 'failed'}})
        self.assertEqual('running', self.activities()['worker']['status'])
        self.event('turn/completed', thread_id='worker', **{'turn': {'id': 'new-turn', 'status': 'failed'}})
        self.assertEqual('failed', self.activities()['worker']['status'])

    def test_complete_child_review_acceptance_resumes_then_completes_observed_work(self):
        self.child()
        self.app.on_message({'id': 702, 'method': 'item/commandExecution/requestApproval',
            'params': {'threadId': 'worker', 'turnId': 'worker-turn', 'itemId': 'review-command',
                'command': '/usr/bin/true', 'cwd': str(self.root), 'startedAtMs': 1,
                'availableDecisions': ['accept', 'decline', 'cancel']}})
        approval = next(a for a in self.get('/api/state')['approvals'] if a['status'] == 'pending')
        self.assertEqual('waiting_approval', self.activities()['worker']['status'])
        with patch('dashboard.server.scan_preview', return_value=None):
            review = self.get('/api/approvals/' + approval['id'] + '/review')
            self.assertEqual('/usr/bin/true', review['context']['command'])
            self.assertEqual(str(self.root), review['context']['cwd'])
            self.assertEqual([], self.fake.responses)
            self.post('/api/approvals/' + approval['id'] + '/respond',
                {'decision': 'accept', 'review_id': review['review_id']})
        self.assertEqual([(702, {'decision': 'accept'})], self.fake.responses)
        self.assertEqual('running', self.activities()['worker']['status'])
        self.event('turn/completed', thread_id='worker', **{'turn': {'id': 'worker-turn', 'status': 'completed'}})
        self.assertEqual('completed', self.activities()['worker']['status'])

    def test_inactive_or_limited_child_cannot_register_a_new_delegate(self):
        self.child()
        self.app.owned_threads['worker']['active'] = False
        self.child('inactive-child', 'qa_engineer', 'worker')
        self.assertNotIn('inactive-child', self.activities())
        self.app.owned_threads['worker'].update(active=True, limited=True)
        self.child('limited-child', 'qa_engineer', 'worker')
        self.assertNotIn('limited-child', self.activities())

    def test_live_child_can_delegate_after_root_turn_completes(self):
        self.child()
        self.event('turn/completed', **{'turn': {'id': self.task['turn_id'], 'status': 'completed'}})
        self.child('late-qa', 'qa_engineer', 'worker')
        self.assertIn('late-qa', self.activities())
        self.assertEqual('worker', self.activities()['late-qa']['parent_thread_id'])

    def test_modern_delegation_metadata_also_registers_nested_work_after_root_completion(self):
        self.child()
        self.event('turn/completed', **{'turn': {'id': self.task['turn_id'], 'status': 'completed'}})
        original = self.fake.request
        def reply(method, params):
            if method == 'thread/read':
                self.assertEqual({'threadId': 'modern-qa', 'includeTurns': False}, params)
                return {'thread': {'id': 'modern-qa', 'parentThreadId': 'worker',
                    'agentRole': 'qa_engineer', 'cwd': str(self.root)}}
            return original(method, params)
        with patch.object(self.fake, 'request', side_effect=reply):
            self.event('item/started', thread_id='worker', turnId='worker-turn',
                item={'id': 'modern-spawn', 'type': 'subAgentActivity',
                      'kind': 'started', 'agentThreadId': 'modern-qa'})
            self.app.wait_conversations()
        self.assertEqual('worker', self.activities()['modern-qa']['parent_thread_id'])
        self.assertEqual('qa_engineer', self.activities()['modern-qa']['role'])

    def test_disconnect_preserves_completed_work_and_marks_active_unknown(self):
        self.child()
        self.child('qa', 'qa_engineer')
        self.event('turn/completed', thread_id='qa', **{'turn': {'id': 'qa-turn', 'status': 'completed'}})
        self.app.disconnected()
        activities = self.activities()
        self.assertEqual('unknown', activities['worker']['status'])
        self.assertEqual('completed', activities['qa']['status'])
        before = len(self.fake.requests)
        self.get('/api/team')
        self.get('/api/state')
        self.assertEqual(before, len(self.fake.requests), 'Reading activity must never replay work')
