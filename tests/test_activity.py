"""Delegated activity projections driven by fake native events; no model calls."""
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from dashboard.server import Dashboard
from tests.test_dashboard_backend import FakeClient


class ActivityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir='/private/tmp')
        self.root = Path(self.temp.name).resolve()
        self.app = Dashboard(self.root / 'state')
        self.client = FakeClient()
        self.app.client = self.client
        self.app.connection['status'] = 'connected'
        self.project = self.app.add_project({'name': 'Activity fixture', 'path': str(self.root)})
        self.scanner = patch('dashboard.conversation.scan_preview', lambda _: None)
        self.scanner.start()
        result = self.app.start_task({'project_id': self.project['id'], 'title': 'Ship the activity view',
                                     'instruction': 'Implement the requested view', 'role': 'chief_of_staff'})
        self.app.workers[-1].join(3)
        self.assertFalse(self.app.workers[-1].is_alive())
        self.task = self.app.tasks[result['id']]

    def tearDown(self):
        self.app.close()
        self.scanner.stop()
        self.temp.cleanup()

    def event(self, method, **params):
        self.app.on_message({'method': method, 'params': {
            'threadId': self.task['thread_id'], 'turnId': self.task['turn_id'], **params}})

    def child(self, child='child-backend', role='backend_developer', parent=None):
        parent = parent or self.task['thread_id']
        self.event('thread/started', thread={'id': child, 'parentThreadId': parent, 'agentRole': role})
        self.event('turn/started', threadId=child, turnId=child + '-turn',
                   turn={'id': child + '-turn', 'status': 'inProgress'})
        return next(record for record in self.app.observed_tasks.values() if record['thread_id'] == child)

    def test_state_and_roster_expose_direct_and_delegated_work_without_double_counting(self):
        activity = self.child()
        activity.update(prompt='PRIVATE_TOOL_PROMPT', last_summary='PRIVATE_SUMMARY',
                        transcript='PRIVATE_TRANSCRIPT', reasoning='PRIVATE_REASONING')
        state = self.app.snapshot()
        self.assertEqual(1, len(state['tasks']))
        self.assertEqual(1, len(state['delegated_activities']))
        projected = state['delegated_activities'][0]
        self.assertEqual({'id', 'parent_task_id', 'project_id', 'thread_id', 'parent_thread_id',
                          'role', 'title', 'status', 'created_at', 'updated_at'}, set(projected))
        self.assertEqual(self.task['id'], projected['parent_task_id'])
        self.assertEqual(self.task['thread_id'], projected['parent_thread_id'])
        self.assertEqual(self.project['id'], projected['project_id'])
        self.assertNotIn('PRIVATE_', json.dumps(projected))
        members = {member['id']: member for member in self.app.team.snapshot(self.app.team_tasks())['members']}
        direct = members['chief_of_staff']['activities']
        delegated = members['backend_developer']['activities']
        self.assertEqual([self.task['id']], [entry['id'] for entry in direct])
        self.assertEqual('direct', direct[0]['source'])
        self.assertIsNone(direct[0]['parent_task_id'])
        self.assertEqual('delegated', delegated[0]['source'])
        self.assertNotIn('PRIVATE_', json.dumps(delegated))
        self.assertEqual([], members['qa_engineer']['activities'])

    def test_nested_lineage_and_observed_failure_interruption(self):
        self.child()
        nested = self.child('child-qa', 'qa_engineer', parent='child-backend')
        self.assertEqual(self.task['id'], nested['parent_task_id'])
        self.assertEqual('child-backend', nested['parent_thread_id'])
        self.event('turn/completed', threadId='child-qa', turnId='child-qa-turn',
                   turn={'id': 'child-qa-turn', 'status': 'failed'})
        self.assertEqual('failed', nested['status'])
        self.event('item/completed', item={'type': 'subAgentActivity', 'id': 'stop-backend',
                                         'kind': 'interrupted', 'agentThreadId': 'child-backend'})
        backend = next(record for record in self.app.observed_tasks.values() if record['role'] == 'backend_developer')
        self.assertEqual('interrupted', backend['status'])
        self.assertFalse(self.app.active_children(self.task['id']))

    def test_child_approval_waiting_and_resolution_do_not_change_sibling(self):
        backend = self.child()
        sibling = self.child('child-qa', 'qa_engineer')
        self.app.on_message({'id': 333, 'method': 'item/commandExecution/requestApproval', 'params': {
            'threadId': 'child-backend', 'turnId': 'child-backend-turn', 'itemId': 'approval-item',
            'command': 'pwd', 'cwd': self.project['path']}})
        self.assertEqual('waiting_approval', backend['status'])
        self.assertEqual('running', sibling['status'])
        self.event('serverRequest/resolved', threadId='child-backend', requestId=333)
        self.assertEqual('running', backend['status'])
        self.assertEqual('running', sibling['status'])

    def test_child_question_waiting_then_resolves(self):
        backend = self.child()
        self.app.on_message({'id': 334, 'method': 'item/tool/requestUserInput', 'params': {
            'threadId': 'child-backend', 'turnId': 'child-backend-turn', 'itemId': 'question',
            'questions': [{'id': 'layout', 'header': 'Layout', 'question': 'Which layout?',
                           'options': [{'label': 'Compact', 'description': 'Less space'},
                                       {'label': 'Roomy', 'description': 'More space'}]}]}})
        self.app.wait_conversations()
        self.assertEqual('waiting_approval', backend['status'])
        question = next(iter(self.app.questions.values()))
        self.app.respond_question(question['id'], {'answers': {'layout': ['Compact']}})
        self.assertEqual('running', backend['status'])

    def test_unknown_role_is_unattributed_and_foreign_scope_never_appears(self):
        self.event('thread/started', thread={'id': 'unknown-child', 'parentThreadId': self.task['thread_id'],
                                            'agentRole': 'unregistered'})
        self.event('thread/started', thread={'id': 'foreign-child', 'parentThreadId': 'unowned',
                                            'agentRole': 'backend_developer'})
        activity = self.app.delegated_activities()
        self.assertEqual(1, len(activity))
        self.assertEqual('unknown-child', activity[0]['thread_id'])
        self.assertIsNone(activity[0]['role'])
        self.assertEqual('Unattributed delegated task', activity[0]['title'])
        backend = self.child()
        backend['project_id'] = 'foreign-project'
        self.assertEqual(['unknown-child'], [record['thread_id'] for record in self.app.delegated_activities()])
        members = self.app.team.snapshot(self.app.team_tasks())['members']
        self.assertEqual([], next(member for member in members if member['id'] == 'backend_developer')['activities'])

    def test_disconnect_and_restart_keep_terminal_history_and_mark_active_unknown(self):
        backend = self.child()
        qa = self.child('child-qa', 'qa_engineer')
        self.event('turn/completed', threadId='child-qa', turnId='child-qa-turn',
                   turn={'id': 'child-qa-turn', 'status': 'completed'})
        self.app.disconnected()
        self.assertEqual('unknown', backend['status'])
        self.assertEqual('completed', qa['status'])
        self.app.close()
        self.app = Dashboard(self.root / 'state')
        projected = {record['role']: record for record in self.app.delegated_activities()}
        self.assertEqual('unknown', projected['backend_developer']['status'])
        self.assertEqual('completed', projected['qa_engineer']['status'])
        self.assertEqual('child-backend', projected['backend_developer']['thread_id'])
        self.assertEqual(self.task['thread_id'], projected['backend_developer']['parent_thread_id'])
        self.assertIsNone(self.app.client)

    def test_delayed_role_metadata_preserves_queued_started_and_approval_states(self):
        original_request = self.client.request
        for index, expected in enumerate(('queued', 'running', 'waiting_approval')):
            with self.subTest(expected=expected):
                child = 'delayed-child-' + str(index)
                entered, release = threading.Event(), threading.Event()

                def request(method, params):
                    if method == 'thread/read':
                        entered.set()
                        release.wait(3)
                        return {'thread': {'id': child, 'parentThreadId': self.task['thread_id'],
                                           'agentRole': 'backend_developer', 'cwd': self.project['path']}}
                    return original_request(method, params)

                self.client.request = request
                self.event('item/completed', item={
                    'type': 'collabAgentToolCall', 'id': 'queued-spawn-' + str(index),
                    'tool': 'spawnAgent', 'status': 'completed', 'senderThreadId': self.task['thread_id'],
                    'receiverThreadIds': [child], 'agentsStates': {child: {'status': 'pendingInit'}}})
                try:
                    self.assertTrue(entered.wait(3))
                    if expected != 'queued':
                        self.event('turn/started', threadId=child, turnId=child + '-turn',
                                   turn={'id': child + '-turn', 'status': 'inProgress'})
                    if expected == 'waiting_approval':
                        self.app.on_message({'id': 400 + index, 'method': 'item/commandExecution/requestApproval',
                                             'params': {'threadId': child, 'turnId': child + '-turn',
                                                        'itemId': 'delayed-approval', 'command': 'pwd',
                                                        'cwd': self.project['path']}})
                finally:
                    release.set()
                self.app.wait_conversations()
                activity = next(record for record in self.app.delegated_activities() if record['thread_id'] == child)
                self.assertEqual(expected, activity['status'])
                if expected == 'queued':
                    self.event('turn/started', threadId=child, turnId=child + '-turn',
                               turn={'id': child + '-turn', 'status': 'inProgress'})
                    activity = next(record for record in self.app.delegated_activities() if record['thread_id'] == child)
                    self.assertEqual('running', activity['status'])
        self.client.request = original_request


if __name__ == '__main__':
    unittest.main()
