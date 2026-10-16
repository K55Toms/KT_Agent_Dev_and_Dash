"""Focused native-child and recognition tests; no model calls or networking."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from dashboard.server import Dashboard
from tests.test_dashboard_backend import FakeClient


class NativeConversationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir='/private/tmp')
        self.root = Path(self.temp.name).resolve()
        self.app = Dashboard(self.root / 'state')
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

    def native_question(self, task):
        self.app.on_message({'id':71,'method':'item/tool/requestUserInput','params':{
            'threadId':'native-child','turnId':'native-child-turn','itemId':'question-item',
            'questions':[{'id':'layout','header':'Layout','question':'Which layout should we use?',
                          'options':[{'label':'Compact','description':'Use less space'},
                                     {'label':'Roomy','description':'Use more space'}]}]}})
        self.app.wait_conversations()
        return list(self.app.questions.values())[-1]

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
