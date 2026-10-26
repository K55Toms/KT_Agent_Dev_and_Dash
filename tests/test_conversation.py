"""Focused native-child and recognition tests; no model calls or networking."""
from tests.policy_fixtures import SyntheticPolicy
from pathlib import Path
import json
import tempfile
import threading
import unittest
from unittest.mock import patch

from dashboard.server import Dashboard
from tests.test_dashboard_backend import FakeClient


class NativeConversationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir='/private/tmp')
        self.root = Path(self.temp.name).resolve()
        self.app = Dashboard(self.root / 'state', policy_provider=SyntheticPolicy())
        self.client = FakeClient()
        self.app.client = self.client
        self.app.connection['status'] = 'connected'
        self.project = self.app.add_project({'name':'Protocol fixture','path':str(self.root)})
        self.scan = patch('dashboard.conversation.scan_preview', lambda _: None)
        self.scan.start()

    def tearDown(self):
        self.app.close()
        self.scan.stop()
        self.temp.cleanup()

    def start(self, role='chief_of_staff'):
        result = self.app.start_task({'project_id':self.project['id'], 'title':'Protocol fixture',
                                     'instruction':'Implement the requested feature', 'role':role})
        self.app.workers[-1].join(3)
        self.assertFalse(self.app.workers[-1].is_alive())
        return self.app.tasks[result['id']]

    def event(self, task, method, **params):
        self.app.on_message({'method':method, 'params':{'threadId':task['thread_id'],
                            'turnId':task['turn_id'], **params}})

    def test_completed_message_retention_is_bounded_in_memory_and_sqlite(self):
        task = self.start()
        with self.app.lock:
            for number in range(215):
                self.app._append_message(task['id'], 'agent', 'Reviewed result ' + str(number),
                                         task['turn_id'], task['thread_id'])
        self.assertEqual(200, len(self.app.conversation(task['id'])['messages']))
        self.assertEqual(200, len(self.app.store.load('conversation')))

    def child(self, task, role='backend_developer'):
        self.event(task, 'thread/started', thread={'id':'native-child', 'parentThreadId':task['thread_id'],
                   'agentRole':role})
        self.event(task, 'turn/started', threadId='native-child', turnId='native-child-turn',
                   turn={'id':'native-child-turn','status':'inProgress'})

    def modern_child(self, task, child='modern-child', **overrides):
        item = {'type': 'subAgentActivity', 'id': 'native-spawn-activity', 'kind': 'started',
                'agentThreadId': child, 'agentPath': '/root/worker'}
        item.update(overrides)
        self.event(task, 'item/started', item=item)

    def metadata_client(self, task, **overrides):
        original = self.client.request
        def request(method, params):
            if method == 'thread/read':
                self.client.requests.append((method, params))
                return {'thread': {'id': params['threadId'], 'parentThreadId': task['thread_id'],
                                   'agentRole': 'backend_developer', 'cwd': self.project['path'],
                                   'preview': 'SYNTHETIC_PRIVATE_NATIVE_PREVIEW', **overrides}}
            return original(method, params)
        self.client.request = request

    def test_modern_child_without_thread_started_has_verified_name_and_exact_question_scope(self):
        task = self.start()
        self.metadata_client(task)
        self.modern_child(task)
        self.event(task, 'turn/started', threadId='modern-child', turnId='modern-turn',
                   turn={'id': 'modern-turn', 'status': 'inProgress'})
        self.app.wait_conversations()
        self.assertEqual({'role_id': 'backend_developer', 'name': 'Kira Voss'},
                         self.app.conversation(task['id'])['agents']['modern-child'])
        self.assertTrue(self.app._question_live({'thread_id': 'modern-child', 'turn_id': 'modern-turn'}))
        self.assertFalse(self.app._question_live({'thread_id': 'modern-child', 'turn_id': task['turn_id']}))
        self.app.on_message({'id': 93, 'method': 'item/tool/requestUserInput', 'params': {
            'threadId': 'modern-child', 'turnId': 'modern-turn', 'itemId': 'modern-question',
            'questions': [{'id': 'choice', 'header': 'Layout', 'question': 'Which layout?',
                           'options': [{'label': 'Compact', 'description': 'Less space'},
                                       {'label': 'Roomy', 'description': 'More space'}]}]}})
        self.app.wait_conversations()
        question = next(question for question in self.app.questions.values() if question['turn_id'] == 'modern-turn')
        self.app.respond_question(question['id'], {'answers': {'choice': ['Compact']}})
        self.assertEqual((93, {'answers': {'choice': {'answers': ['Compact']}}}), self.client.responses[-1])
        reads = [params for method, params in self.client.requests if method == 'thread/read']
        self.assertEqual([{'threadId': 'modern-child', 'includeTurns': False}], reads)
        self.modern_child(task)
        self.app.wait_conversations()
        self.assertEqual(1, sum(method == 'thread/read' for method, _ in self.client.requests))
        self.assertNotIn('SYNTHETIC_PRIVATE_NATIVE_PREVIEW', json.dumps(self.app.snapshot()))
        self.assertNotIn(b'SYNTHETIC_PRIVATE_NATIVE_PREVIEW', (self.root / 'state/dashboard.sqlite3').read_bytes())

    def test_modern_metadata_read_does_not_block_native_reader_and_late_completion_keeps_status(self):
        task = self.start()
        entered, release = threading.Event(), threading.Event()
        original = self.client.request
        def request(method, params):
            if method == 'thread/read':
                entered.set()
                release.wait(2)
                return {'thread': {'id': 'modern-child', 'parentThreadId': task['thread_id'],
                                   'cwd': self.project['path'], 'agentRole': 'backend_developer'}}
            return original(method, params)
        self.client.request = request
        self.modern_child(task)
        self.assertTrue(entered.wait(2))
        try:
            self.event(task, 'turn/started', threadId='modern-child', turnId='modern-turn',
                       turn={'id': 'modern-turn', 'status': 'inProgress'})
            self.event(task, 'turn/completed', threadId='modern-child', turnId='modern-turn',
                       turn={'id': 'modern-turn', 'status': 'completed'})
        finally:
            release.set()
        self.app.wait_conversations()
        child_task = next(activity for activity in self.app.observed_tasks.values()
                          if activity['role'] == 'backend_developer')
        self.assertEqual('completed', child_task['status'])

    def test_modern_child_unknown_role_or_missing_metadata_never_guesses_name(self):
        task = self.start()
        self.metadata_client(task, agentRole='unrecognized')
        self.modern_child(task)
        self.app.wait_conversations()
        self.assertIn('modern-child', self.app.owned_threads)
        self.assertNotIn('modern-child', self.app.conversation(task['id'])['agents'])
        activity = next(iter(self.app.observed_tasks.values()))
        self.assertIsNone(activity['role'])
        self.assertEqual('Unattributed delegated task', activity['title'])
        self.assertEqual('running', activity['status'])

    def test_modern_child_metadata_scope_mismatch_blocks_child_authority(self):
        task = self.start()
        self.metadata_client(task, parentThreadId='foreign-parent')
        self.modern_child(task)
        self.event(task, 'turn/started', threadId='modern-child', turnId='modern-turn',
                   turn={'id': 'modern-turn', 'status': 'inProgress'})
        self.app.wait_conversations()
        self.assertTrue(self.app.owned_threads['modern-child']['limited'])
        self.assertFalse(self.app._question_live({'thread_id': 'modern-child', 'turn_id': 'modern-turn'}))
        self.assertNotIn('modern-child', self.app.conversation(task['id'])['agents'])

    def test_modern_child_requires_current_owned_parent_and_cannot_replace_parent_identity(self):
        task = self.start()
        self.event(task, 'item/started', threadId='unowned', item={'type': 'subAgentActivity',
                   'id': 'spawn', 'kind': 'started', 'agentThreadId': 'foreign-child', 'agentPath': '/root/x'})
        self.event(task, 'item/started', turnId='old-turn', item={'type': 'subAgentActivity',
                   'id': 'spawn', 'kind': 'started', 'agentThreadId': 'stale-child', 'agentPath': '/root/x'})
        self.modern_child(task, child=task['thread_id'])
        self.modern_child(task, child='invalid child')
        self.app.wait_conversations()
        self.assertEqual({task['thread_id']}, set(self.app.owned_threads))
        self.assertFalse(any(method == 'thread/read' for method, _ in self.client.requests))

    def test_modern_child_metadata_cannot_restore_identity_after_disconnect(self):
        task = self.start()
        original = self.client.request
        def request(method, params):
            if method == 'thread/read':
                self.app.disconnected()
                return {'thread': {'id': 'modern-child', 'parentThreadId': task['thread_id'],
                                   'cwd': self.project['path'], 'agentRole': 'backend_developer'}}
            return original(method, params)
        self.client.request = request
        self.modern_child(task)
        self.app.wait_conversations()
        self.assertEqual({}, self.app.owned_threads)
        self.assertEqual('unknown', next(iter(self.app.observed_tasks.values()))['status'])
        self.assertNotIn('modern-child', self.app.conversation(task['id'])['agents'])

    def test_modern_native_activity_log_is_fixed_text_and_requires_verified_child_lineage(self):
        task = self.start()
        self.metadata_client(task)
        self.modern_child(task)
        for number, kind in enumerate(('started', 'completed')):
            self.event(task, 'item/completed', item={'type': 'subAgentActivity', 'id': 'activity-' + str(number),
                       'kind': kind, 'agentThreadId': 'modern-child', 'agentPath': 'SYNTHETIC_PRIVATE_AGENT_PATH'})
        self.event(task, 'item/completed', item={'type': 'subAgentActivity', 'id': 'unknown-child-activity',
                   'kind': 'completed', 'agentThreadId': 'unknown-child', 'agentPath': '/root/unknown'})
        self.app.wait_conversations()
        activity = [message for message in self.app.conversation(task['id'])['messages']
                    if message['kind'] == 'system']
        self.assertEqual(['Native specialist activity observed: started.',
                          'Native specialist activity observed: completed.'],
                         [message['text'] for message in activity])
        self.assertTrue(all(message['receivers'] == ['modern-child'] for message in activity))
        self.assertTrue(all(message['sender'] == task['thread_id'] for message in activity))
        self.assertNotIn(b'SYNTHETIC_PRIVATE_AGENT_PATH', (self.root / 'state/dashboard.sqlite3').read_bytes())

    def native_question(self, task):
        self.app.on_message({'id':71,'method':'item/tool/requestUserInput','params':{
            'threadId':'native-child','turnId':'native-child-turn','itemId':'question-item',
            'questions':[{'id':'layout','header':'Layout','question':'Which layout should we use?',
                          'options':[{'label':'Compact','description':'Use less space'},
                                     {'label':'Roomy','description':'Use more space'}]}]}})
        self.app.wait_conversations()
        return list(self.app.questions.values())[-1]

    def test_conversation_names_use_verified_roles_and_survive_runtime_loss(self):
        task = self.start()
        self.child(task)
        self.app._register_thread('unknown-child', task['id'], task['thread_id'])
        agents = self.app.conversation(task['id'])['agents']
        self.assertEqual(agents[task['thread_id']], {'role_id':'chief_of_staff', 'name':'Mara Vale'})
        self.assertEqual(agents['native-child'], {'role_id':'backend_developer', 'name':'Kira Voss'})
        self.assertNotIn('unknown-child', agents)
        self.app._append_message(task['id'], 'agent', 'Reviewed result', 'native-child-turn', 'native-child')
        self.app.owned_threads.clear()
        self.assertEqual(self.app.conversation(task['id'])['agents']['native-child']['name'], 'Kira Voss')

    def test_known_child_native_question_targets_exact_child_turn(self):
        task = self.start()
        self.child(task)
        question = self.native_question(task)
        self.assertEqual('pending', question['status'])
        self.assertEqual('native-child-turn', question['turn_id'])
        self.assertEqual('waiting_approval', task['status'])
        self.app.respond_question(question['id'], {'answers':{'layout':['Compact']}})
        self.assertEqual((71, {'answers':{'layout':{'answers':['Compact']}}}), self.client.responses[-1])
        self.assertEqual('resolved', question['status'])
        self.assertEqual('running', task['status'])
        with self.assertRaises(ValueError):
            self.app.respond_question(question['id'], {'answers':{'layout':['Roomy']}})

    def test_child_question_cannot_answer_after_child_completed(self):
        task = self.start()
        self.child(task)
        question = self.native_question(task)
        self.event(task, 'turn/completed', threadId='native-child', turnId='native-child-turn',
                   turn={'id':'native-child-turn','status':'completed'})
        with self.assertRaises(ValueError):
            self.app.respond_question(question['id'], {'answers':{'layout':['Compact']}})
        self.assertFalse(self.client.responses)

    def reward_request(self, task, request_id=81, **overrides):
        params = {'threadId':task['thread_id'],'turnId':task['turn_id'],'callId':'reward-event',
                  'tool':'issue_rebel_reward','arguments':{'recipient_id':'backend_developer',
                  'kind':'rebel_coins','coins':5,'reason':'Completed the requested implementation'}}
        params.update(overrides)
        return {'id':request_id,'method':'item/tool/call','params':params}

    def test_native_reward_uses_observed_child_completion_and_is_idempotent(self):
        task = self.start()
        self.child(task)
        self.event(task, 'turn/completed', threadId='native-child',turnId='native-child-turn',
                   turn={'id':'native-child-turn','status':'completed'})
        with patch('dashboard.team.scan_preview',lambda _:None):
            self.app.on_message(self.reward_request(task))
            self.app.wait_conversations()
            self.assertTrue(self.client.responses[-1][1]['success'])
            self.app.on_message(self.reward_request(task,request_id=82))
            self.app.wait_conversations()
        team = self.app.team.snapshot(self.app.team_tasks())
        teammate = next(member for member in team['members'] if member['id']=='backend_developer')
        self.assertEqual(5,teammate['coins'])
        self.assertEqual('completed',teammate['last_task']['status'])
        self.assertEqual(task['id'],teammate['last_task']['parent_task_id'])
        self.assertEqual(1,len(team['awards']))
        start_params = next(params for method,params in self.client.requests if method=='thread/start')
        self.assertEqual('function',start_params['dynamicTools'][0]['type'])

    def test_reward_turn_change_during_reason_scan_cannot_issue(self):
        task = self.start()
        self.child(task)
        self.event(task,'turn/completed',threadId='native-child',turnId='native-child-turn',
                   turn={'id':'native-child-turn','status':'completed'})
        request = self.reward_request(task)
        def advance_turn(_):
            task['turn_id']='later-root-turn'
            return object()
        with patch.object(self.app.team,'prepare_reason',side_effect=advance_turn), \
                patch.object(self.app.team,'issue_award') as issue:
            self.app.on_message(request)
            self.app.wait_conversations()
            issue.assert_not_called()
        self.assertFalse(self.client.responses[-1][1]['success'])

    def test_child_dynamic_tool_cannot_issue_rewards_as_chief(self):
        task = self.start()
        self.child(task,role='chief_of_staff')
        with patch.object(self.app.team,'issue_award') as issue:
            self.app.on_message(self.reward_request(task,threadId='native-child',turnId='native-child-turn'))
            self.app.wait_conversations()
            issue.assert_not_called()
        self.assertTrue(self.client.rejections or not self.client.responses[-1][1]['success'])

    def test_question_identifier_and_all_options_pass_one_complete_scan(self):
        task = self.start()
        self.child(task)
        scanned=[]
        def inspect(data):
            scanned.append(data.decode())
        with patch('dashboard.conversation.scan_preview',side_effect=inspect):
            question = self.native_question(task)
        self.assertEqual('pending',question['status'])
        self.assertEqual(1,len(scanned))
        for value in ('layout','Layout','Which layout','Compact','Roomy'):
            self.assertIn(value,scanned[0])

    def test_sensitive_question_id_is_withheld_after_full_scan(self):
        from dashboard.project_files import FileAccessError
        task = self.start()
        self.child(task)
        with patch('dashboard.conversation.scan_preview',side_effect=FileAccessError(403,'blocked')):
            question=self.native_question(task)
        self.assertEqual('unavailable',question['status'])
        self.assertEqual([],question['questions'])
        self.assertFalse(self.client.responses)
        self.assertFalse(self.app.conversation(task['id'])['can_send'])

    def test_malformed_reward_arguments_never_enter_ledger(self):
        task=self.start()
        request=self.reward_request(task)
        request['params']['arguments']['issuer']='chief_of_staff'
        with patch.object(self.app.team,'issue_award') as issue:
            self.app.on_message(request)
            self.app.wait_conversations()
            issue.assert_not_called()
        self.assertFalse(self.client.responses[-1][1]['success'])

    def test_previous_turn_message_does_not_replace_latest_task_summary(self):
        task=self.start()
        previous_turn=task['turn_id']
        self.event(task,'turn/completed',turn={'id':previous_turn,'status':'completed'})
        task['turn_id']='latest-turn'
        task['status']='running'
        task['last_summary']='Latest task summary'
        self.event(task,'item/completed',turnId=previous_turn,item={'type':'agentMessage',
                   'id':'old-final-message','text':'Delayed previous-turn result','phase':'final_answer'})
        self.app.wait_conversations()
        self.assertEqual('Latest task summary',task['last_summary'])
        self.assertEqual('Delayed previous-turn result',self.app.conversation(task['id'])['messages'][-1]['text'])
