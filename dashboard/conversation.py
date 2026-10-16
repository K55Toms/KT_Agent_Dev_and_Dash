"""Bounded, scanner-approved conversations for currently dashboard-owned runtimes."""
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import queue
import re
from pathlib import Path
import threading
import uuid

from .codex_client import ProtocolError, RequestRejected
from .project_files import FileAccessError, scan_preview

TERMINAL = {"completed", "interrupted", "failed"}
IDENTIFIER = re.compile(r"[A-Za-z0-9_.:/-]{1,200}\Z")
PERMISSION = re.compile(r"\b(secret|password|credential|token|api.?key|permission|approval|approve|authorize|sandbox|unsandbox|bypass)\b", re.I)
AUTHORIZATION_CHOICE = re.compile(r"^(accept|decline|cancel|allow|deny|approve|reject|grant|confirm|proceed)\b", re.I)
REWARD_TOOL = {"type": "function", "name": "issue_rebel_reward", "description": "Recognize an observed completed teammate task with nonfinancial Rebel coins or Agent of the Week. Never self-award.", "inputSchema": {"type": "object", "additionalProperties": False, "required": ["recipient_id", "kind", "coins", "reason"], "properties": {"recipient_id": {"type": "string"}, "kind": {"type": "string", "enum": ["rebel_coins", "agent_of_week"]}, "coins": {"type": "integer", "minimum": 1, "maximum": 20}, "reason": {"type": "string", "minLength": 1, "maxLength": 500}}}}


def timestamp():
    return datetime.now(timezone.utc).isoformat()


def safe_text(text, maximum=32000):
    if (not isinstance(text, str) or not text.strip() or len(text) > maximum
            or any(ord(c) < 32 and c not in '\n\t' or ord(c) == 127 for c in text)):
        raise ValueError("Provide bounded plain text")
    try:
        scan_preview(text.encode('utf-8'))
    except FileAccessError:
        raise ValueError("Sensitive-content checks did not pass; nothing was sent or saved") from None
    return text.strip()


class ConversationMixin:
    def _init_conversation(self):
        self.messages = self.store.load('conversation')
        self.questions = {}
        self.question_requests = {}
        self.owned_threads = {}
        self.observed_tasks = {x['id']: x for x in self.store.load('team_activity')}
        for activity in self.observed_tasks.values():
            if activity['status'] in {'queued', 'running', 'waiting_approval'}:
                activity.update(status='unknown', updated_at=timestamp())
                self.store.put('team_activity', activity)
        self.omitted_count = 0
        self.conversation_stopping = threading.Event()
        self.message_busy = set()
        self.starting_turn = set()
        self.conversation_seen = set()
        self.resolved_requests = set()
        self.runtime_requests_disabled = False
        self.runtime_tracking_lost = False
        self.conversation_queue = queue.Queue(maxsize=64)
        self.conversation_worker = threading.Thread(target=self._conversation_loop, daemon=True)
        self.conversation_worker.start()

    def _owned(self, thread_id):
        return self.owned_threads.get(thread_id) if isinstance(thread_id, str) else None

    def _register_thread(self, thread_id, task_id, parent=None):
        if not isinstance(thread_id, str) or not IDENTIFIER.fullmatch(thread_id):
            raise ValueError('Invalid runtime identifier')
        if len(self.owned_threads) >= 256 and thread_id not in self.owned_threads:
            self.omitted_count += 1
            self.runtime_tracking_lost = True
            raise ValueError('Runtime coverage limit reached')
        if thread_id in self.owned_threads:
            if self.owned_threads[thread_id]['task_id'] != task_id:
                raise ValueError('Runtime identifier collision')
            return
        self.owned_threads[thread_id] = {'task_id': task_id, 'parent': parent, 'turns': set(), 'current_turn': None, 'active': True}

    def team_tasks(self):
        return {**self.observed_tasks, **self.tasks}

    def active_children(self, task_id):
        return [(thread_id, owned) for thread_id, owned in self.owned_threads.items()
                if owned['task_id'] == task_id and owned['parent'] is not None and owned.get('active')]

    def active_project_roots(self, exclude_task=None):
        active_ids = {task['id'] for task in self.tasks.values()
                      if task['id'] != exclude_task and task['status'] in {'queued', 'running', 'waiting_approval'}}
        active_ids.update(owned['task_id'] for owned in self.owned_threads.values()
                          if owned['parent'] is not None and owned.get('active'))
        return [Path(self.projects[self.tasks[identifier]['project_id']]['path']) for identifier in active_ids
                if identifier in self.tasks and self.tasks[identifier]['project_id'] in self.projects]

    def _child_activity(self, thread_id, role_id=None, status=None):
        owned = self._owned(thread_id)
        if not owned or not owned['parent']:
            return
        key = hashlib.sha256(('child:'+thread_id).encode()).hexdigest()
        record = self.observed_tasks.get(key)
        if record is None and role_id in self.roles:
            parent = self.tasks[owned['task_id']]
            record = {'id':key,'parent_task_id':parent['id'],'project_id':parent['project_id'],
                      'role':role_id,'title':self.roles[role_id]['label']+' delegated task',
                      'status':'running','created_at':timestamp(),'updated_at':timestamp()}
            self.observed_tasks[key] = record
        if record is not None:
            if status in {'running','completed','failed','interrupted','unknown'}:
                record['status'] = status
            record['updated_at'] = timestamp()
            self.store.put('team_activity',record)
        if len(self.observed_tasks)>1000:
            oldest = sorted(self.observed_tasks.values(),key=lambda x:x['updated_at'])[:-1000]
            for record in oldest:
                self.observed_tasks.pop(record['id'],None)
                self.store.delete('team_activity',record['id'])

    def _conversation_metadata(self, method, params):
        # Only bounded protocol identity/status is handled here. No model text is read.
        owned = self._owned(params.get('threadId'))
        if method == 'thread/started':
            thread = params.get('thread',{})
            if not isinstance(thread,dict):
                return
            parent, child = thread.get('parentThreadId'),thread.get('id')
            parent_owned = self._owned(parent)
            if parent_owned and self.tasks[parent_owned['task_id']]['status'] in {'queued','running','waiting_approval'}:
                try:
                    self._register_thread(child,parent_owned['task_id'],parent)
                except ValueError:
                    return
                self._child_activity(child,thread.get('agentRole'))
        elif method == 'item/completed' and owned:
            item = params.get('item',{})
            if not isinstance(item,dict) or item.get('type')!='collabAgentToolCall' or item.get('status')!='completed' or item.get('senderThreadId')!=params.get('threadId'):
                return
            receivers,states = item.get('receiverThreadIds'),item.get('agentsStates')
            if not isinstance(receivers,list) or len(receivers)>16 or not isinstance(states,dict) or len(states)>16:
                return
            for receiver in receivers:
                if item.get('tool')=='spawnAgent':
                    try:
                        self._register_thread(receiver,owned['task_id'],params['threadId'])
                    except ValueError:
                        continue
                child = self._owned(receiver)
                if child and child['task_id']==owned['task_id']:
                    state=states.get(receiver,{})
                    state=state.get('status') if isinstance(state,dict) else None
                    if state in {'completed','errored','interrupted','shutdown','notFound'}:
                        child['active'] = False
                    elif state in {'running','pendingInit'}:
                        child['active'] = True
                    self._child_activity(receiver,status={'completed':'completed','errored':'failed','interrupted':'interrupted','shutdown':'interrupted','notFound':'unknown','running':'running'}.get(state))
        elif owned and method in {'turn/started','turn/completed'}:
            turn=params.get('turn',{})
            turn_id=turn.get('id') if isinstance(turn,dict) else None
            if not isinstance(turn_id,str) or not IDENTIFIER.fullmatch(turn_id):
                return
            if method=='turn/started' and len(owned['turns'])>=200 and turn_id not in owned['turns']:
                self.omitted_count+=1
                owned.update(current_turn=turn_id, active=True, limited=True)
                return
            if method=='turn/started':
                owned['turns'].add(turn_id)
                owned['current_turn']=turn_id
                owned['active']=True
                self._child_activity(params['threadId'],status='running')
            elif turn_id==owned.get('current_turn'):
                owned['active']=False
                self._child_activity(params['threadId'],status={'completed':'completed','failed':'failed','interrupted':'interrupted'}.get(turn.get('status'),'unknown'))
                if owned['parent']:
                    for key,request in list(self.question_requests.items()):
                        if request['thread_id']==params['threadId']:
                            self.questions[key]['status']='unavailable'
                            del self.question_requests[key]
                    self._resume_after_request(self.tasks[owned['task_id']])
        elif owned and method=='serverRequest/resolved':
            request_id=params.get('requestId')
            if type(request_id) not in {str,int}:
                return
            if request_id in self.resolved_requests or len(self.resolved_requests)<10000:
                self.resolved_requests.add(request_id)
            else:
                self.omitted_count+=1
                self.runtime_requests_disabled = True
                self._expire_questions()
            self._expire_questions(owned['task_id'],'resolved',request_id)
            self._resume_after_request(self.tasks[owned['task_id']])

    def _append_message(self, task_id, kind, text, turn_id, sender, receivers=(), status='complete', event_id=None):
        key = hashlib.sha256((task_id + '\0' + (event_id or uuid.uuid4().hex)).encode()).hexdigest()
        if any(x['id'] == key for x in self.messages):
            return
        record = {'id': key, 'task_id': task_id, 'kind': kind, 'text': text,
                  'created_at': timestamp(), 'turn_id': turn_id, 'sender': sender,
                  'receivers': list(receivers), 'status': status}
        self.messages.append(record)
        self.store.put('conversation', record)
        own = [m for m in self.messages if m['task_id'] == task_id]
        remove = {m['id'] for m in own[:-200]}
        survivors = [m for m in self.messages if m['id'] not in remove]
        remove.update(m['id'] for m in survivors[:-2000])
        self.messages = [m for m in self.messages if m['id'] not in remove]
        for key in remove:
            self.store.delete('conversation', key)

    def _send_state(self, task):
        if self.runtime_tracking_lost:
            return None, 'Runtime tracking limit reached; stop the dashboard and inspect project state before restarting'
        if not task or self.connection['status'] != 'connected' or not self.client or self.client.closed:
            return None, 'Codex is disconnected'
        owned = self._owned(task.get('thread_id'))
        if not owned or owned['parent'] is not None:
            return None, 'Previous runtime history is read-only after restart or disconnect'
        if task['id'] in self.message_busy:
            return None, 'A message is already being sent'
        if any(q['task_id'] == task['id'] for q in self.question_requests.values()):
            return None, 'Answer the pending question or interrupt the run'
        if any(a['task_id'] == task['id'] and a['status'] == 'pending' for a in self.approvals.values()):
            return None, 'Resolve the native request or interrupt the run'
        if task['status'] == 'running' and task.get('turn_id'):
            return 'steer', None
        if task['status'] in TERMINAL and task.get('turn_id') and len(owned['turns'])<200:
            return 'followup', None
        return None, 'This run has no available turn for guidance'

    def conversation(self, task_id):
        with self.lock:
            task = self.tasks.get(task_id)
            if not task:
                raise ValueError('Unknown task')
            mode, reason = self._send_state(task)
            return deepcopy({'task_id': task_id, 'turn_id': task['turn_id'],
                'messages': [{k:v for k,v in m.items() if k != 'task_id'} for m in self.messages if m['task_id'] == task_id],
                'questions': [q for q in self.questions.values() if q['task_id'] == task_id],
                'can_send': mode is not None, 'send_mode': mode, 'blocked_reason': reason, 'send_disabled_reason': reason,
                'omitted_count': self.omitted_count, 'retention': 'local_scanned', 'coverage': 'Dashboard-managed visible messages and observed collaboration only. Reasoning, tool output, desktop sessions and unavailable events are excluded. Latest 200 messages per task; 2000 overall.'})

    def send_message(self, task_id, data):
        if not isinstance(data, dict) or set(data) != {'text', 'expected_turn_id'}:
            raise ValueError('Invalid message fields')
        text = safe_text(data['text'], 16000)
        with self.lock:
            task = self.tasks.get(task_id)
            mode, _ = self._send_state(task)
            if not mode or data['expected_turn_id'] != task['turn_id']:
                raise ValueError('Refresh the conversation before sending')
            if mode == 'followup':
                self._check_followup_scope(task)
            client, thread_id, previous_turn = self.client, task['thread_id'], task['turn_id']
            previous_status = task['status']
            self.message_busy.add(task_id)
            if mode == 'followup':
                self.starting_turn.add(task_id)
                task.update(status='queued', error=None, plan=[])
                self.store.put('task', task)
        try:
            params = {'threadId': thread_id, 'input': [{'type': 'text', 'text': text}]}
            if mode == 'steer':
                params['expectedTurnId'] = previous_turn
            else:
                params.update(self._turn_options(task))
            response = client.request('turn/steer' if mode == 'steer' else 'turn/start', params)
            new_turn = response.get('turnId') if mode == 'steer' else response.get('turn', {}).get('id')
            if not isinstance(new_turn, str) or not IDENTIFIER.fullmatch(new_turn) or mode == 'steer' and new_turn != previous_turn:
                raise ProtocolError('Invalid turn acknowledgement')
            with self.lock:
                if self.client is not client or client.closed or not self._owned(thread_id):
                    raise ProtocolError('Runtime changed while sending')
                if mode == 'followup':
                    observed = task['turn_id']
                    if observed != previous_turn and observed != new_turn:
                        raise ProtocolError('Turn identity changed')
                    task['turn_id'] = new_turn
                    self.owned_threads[thread_id]['turns'].add(new_turn)
                    if task['status'] == 'queued':
                        task['status'] = 'running'
                    self.owned_threads[thread_id].update(current_turn=new_turn, active=task['status'] in {'running', 'waiting_approval'})
                    task['updated_at'] = timestamp()
                    self.store.put('task', task)
                self._append_message(task_id, 'user', text, new_turn, 'You', status='sent')
            return {'status': 'sent', 'mode': mode}
        except RequestRejected:
            with self.lock:
                if mode == 'followup' and task['status'] == 'queued' and task['turn_id'] == previous_turn:
                    task['status'] = previous_status
                    self.store.put('task', task)
            raise ValueError('Codex rejected the message; nothing was retried') from None
        except (ProtocolError, OSError, ValueError, TypeError):
            with self.lock:
                task.update(status='unknown', error='Message acknowledgement was lost; nothing will be retried', updated_at=timestamp())
                self._finish_approvals(task)
                self._expire_questions(task_id)
                self.store.put('task', task)
            raise ProtocolError('Message state is unknown; no retry occurred') from None
        finally:
            with self.lock:
                self.message_busy.discard(task_id)
                self.starting_turn.discard(task_id)

    def _check_followup_scope(self, task):
        if self.runtime_tracking_lost:
            raise ValueError('Runtime tracking limit reached; restart after inspecting project state')
        from pathlib import Path
        root = Path(self.projects[task['project_id']]['path'])
        if not root.is_dir() or str(root.resolve()) != str(root):
            raise ValueError('Registered project changed')
        conflicts = list(self.publishing)
        conflicts.extend(self.active_project_roots(exclude_task=task['id']))
        if any(root == other or root in other.parents or other in root.parents for other in conflicts):
            raise ValueError('Overlapping development or repository work is active')
        if sum(t['status'] in {'queued','running','waiting_approval'} for t in self.tasks.values()) >= 3:
            raise ValueError('Too many active runs')

    def _turn_options(self, task):
        role = self.roles[task['role']]
        project = self.projects[task['project_id']]
        return {'model': role['model'], 'effort': role['reasoning'], 'approvalPolicy': 'on-request',
            'approvalsReviewer': 'user', 'sandboxPolicy': {'type':'workspaceWrite', 'writableRoots':[project['path']], 'networkAccess':False, 'excludeSlashTmp':True, 'excludeTmpdirEnvVar':True}}

    def _queue_conversation(self, message):
        if self.conversation_stopping.is_set() or len(json.dumps(message)) > 65536:
            self.omitted_count += 1
            return False
        try:
            self.conversation_queue.put_nowait(deepcopy(message))
        except queue.Full:
            self.omitted_count += 1
            # Never block the protocol reader or expose unreviewed text when overloaded.
            return False
        return True

    def _conversation_loop(self):
        while True:
            message = self.conversation_queue.get()
            try:
                if message is None:
                    return
                if not self.conversation_stopping.is_set():
                    self._process_conversation(message)
            except (ValueError, FileAccessError, ProtocolError, OSError, KeyError, TypeError):
                pass  # Raw payloads and validation errors never reach logs.
            finally:
                self.conversation_queue.task_done()

    def wait_conversations(self):
        self.conversation_queue.join()

    def _process_conversation(self, message):
        method, params = message['method'], message['params']
        if method == 'item/tool/requestUserInput':
            return self._question(message)
        if method == 'item/tool/call':
            return self._reward(message)
        item = params.get('item', {})
        with self.lock:
            owned = self._owned(params.get('threadId'))
            if not owned or params.get('turnId') not in owned['turns']:
                return
            task_id = owned['task_id']
            event = (params['threadId'], params['turnId'], item.get('id'))
            if event in self.conversation_seen or not isinstance(item.get('id'), str) or not IDENTIFIER.fullmatch(item['id']):
                return
            if len(self.conversation_seen) >= 10000:
                self.omitted_count += 1
                return
            self.conversation_seen.add(event)
        if item.get('type') == 'agentMessage':
            try:
                text = safe_text(item.get('text'))
            except ValueError:
                text = 'Agent message withheld because sensitive-content checks did not pass.'
                kind = 'system'
            else:
                kind = 'agent'
            with self.lock:
                if not self._owned(params['threadId']):
                    return
                self._append_message(task_id, kind, text, params['turnId'], params['threadId'], event_id='|'.join(event))
                if kind == 'agent' and owned['parent'] and owned.get('current_turn') == params['turnId'] and item.get('phase') in {None,'final_answer'}:
                    key=hashlib.sha256(('child:'+params['threadId']).encode()).hexdigest()
                    if key in self.observed_tasks:
                        self.observed_tasks[key].update(last_summary=text[:1000],last_summary_source='model-reported')
                        self.store.put('team_activity',self.observed_tasks[key])
                if kind == 'agent' and self.tasks[task_id]['turn_id'] == params['turnId'] and owned['parent'] is None and item.get('phase') in {None,'final_answer'}:
                    self.tasks[task_id]['last_summary'] = text[:1000]
                    self.tasks[task_id]['last_summary_source'] = 'model-reported'
                    self.store.put('task', self.tasks[task_id])
        elif item.get('type') == 'collabAgentToolCall':
            if item.get('senderThreadId') != params['threadId'] or item.get('status') != 'completed':
                return
            receivers, states = item.get('receiverThreadIds'), item.get('agentsStates')
            if not isinstance(receivers,list) or len(receivers)>16 or not all(isinstance(x,str) and IDENTIFIER.fullmatch(x) for x in receivers) or not isinstance(states,dict) or len(states)>16:
                return
            with self.lock:
                if not self._owned(params['threadId']):
                    return
                if item.get('tool') == 'spawnAgent':
                    for receiver in receivers:
                        if receiver not in self.owned_threads:
                            self._register_thread(receiver, task_id, params['threadId'])
                if any(not self._owned(x) or self._owned(x)['task_id'] != task_id for x in receivers):
                    return
            texts = []
            if item.get('prompt'):
                texts.append((params['threadId'], receivers, item['prompt'], 'prompt'))
            for source, state in states.items():
                if source in receivers and isinstance(state,dict) and state.get('message'):
                    texts.append((source,[params['threadId']],state['message'],'reply:'+source))
            for sender, targets, body, suffix in texts:
                if self.conversation_stopping.is_set():
                    return
                try:
                    text = safe_text(body)
                    kind = 'interagent'
                except ValueError:
                    text, kind = 'Collaboration text withheld because sensitive-content checks did not pass.', 'system'
                with self.lock:
                    if self._owned(params['threadId']):
                        self._append_message(task_id,kind,text,params['turnId'],sender,targets,event_id='|'.join(event)+suffix)

    def _expire_questions(self, task_id=None, status='unavailable', rpc_id=None, thread_id=None):
        for key, request in list(self.question_requests.items()):
            if (task_id is None or request['task_id']==task_id) and (rpc_id is None or request['rpc_id']==rpc_id) and (thread_id is None or request['thread_id']==thread_id):
                self.questions[key]['status'] = status
                del self.question_requests[key]

    def _question_live(self, request):
        owned = self._owned(request.get('thread_id'))
        if self.runtime_tracking_lost or self.runtime_requests_disabled or not owned or owned.get('limited') or not owned.get('active'):
            return False
        task = self.tasks[owned['task_id']]
        current = owned.get('current_turn') if owned['parent'] else task['turn_id']
        allowed = {'running', 'waiting_approval'} | (TERMINAL if owned['parent'] else set())
        return task['status'] in allowed and current == request.get('turn_id')

    def _prune_questions(self):
        removable = [key for key in self.questions if key not in self.question_requests]
        for key in removable[:-100]:
            del self.questions[key]

    def _question(self, message):
        params = message['params']
        binding = {'thread_id':params.get('threadId'), 'turn_id':params.get('turnId')}
        with self.lock:
            owned = self._owned(params.get('threadId'))
            if not owned or message['id'] in self.resolved_requests or not self._question_live(binding):
                return
            task = self.tasks[owned['task_id']]
            client = self.client
        def bounded(value, maximum):
            if not isinstance(value,str) or not value.strip() or len(value)>maximum or any(ord(c)<32 and c not in '\n\t' or ord(c)==127 for c in value):
                raise ValueError('Invalid question text')
            return value.strip()
        clean = []
        valid = True
        try:
            questions = params.get('questions')
            if not isinstance(questions,list) or not 1<=len(questions)<=3:
                raise ValueError('Invalid questions')
            for q in questions:
                if not isinstance(q,dict) or q.get('isSecret',False) is not False or type(q.get('isOther',False)) is not bool:
                    raise ValueError('Unsupported question')
                identifier = bounded(q.get('id'),200)
                if not IDENTIFIER.fullmatch(identifier) or identifier in {'__proto__','constructor','prototype'}:
                    raise ValueError('Invalid question id')
                options = q.get('options') or []
                if not isinstance(options,list) or len(options)>10:
                    raise ValueError('Invalid options')
                options = [{'label':bounded(o.get('label'),200),'description':bounded(o.get('description'),1000)} for o in options if isinstance(o,dict)] if all(isinstance(o,dict) for o in options) else None
                if options is None or len({o['label'] for o in options})!=len(options) or any(AUTHORIZATION_CHOICE.search(o['label']) for o in options):
                    raise ValueError('Invalid options')
                clean.append({'id':identifier,'header':bounded(q.get('header'),100),'question':bounded(q.get('question'),2000),'options':options,'is_other':q.get('isOther',False)})
            serialized = json.dumps(clean)
            if len({q['id'] for q in clean}) != len(clean) or PERMISSION.search(serialized):
                raise ValueError('Unsupported permission question')
            safe_text(serialized,48000)  # One full scan includes model-provided IDs.
        except ValueError:
            valid = False
        with self.lock:
            if message['id'] in self.resolved_requests or self.client is not client or self.connection['status']!='connected' or not self._question_live(binding):
                return
            if any(r['rpc_id']==message['id'] for r in self.question_requests.values()):
                return
            if len(self.question_requests)>=16:
                self._approval(message,task)  # visible interrupt-only fallback
                return
            key=uuid.uuid4().hex
            self.questions[key]={'id':key,'task_id':task['id'],'thread_id':params['threadId'],'turn_id':params['turnId'],'status':'pending' if valid else 'unavailable','questions':clean if valid else [],'prompt':None if valid else 'This question requires sensitive or permission-related input. Interrupt the run and use an appropriate review flow.'}
            self.question_requests[key]={'rpc_id':message['id'],'task_id':task['id'],**binding,'client':client,'answerable':valid}
            self._prune_questions()
            if task['status'] not in TERMINAL:
                task['status'] = 'waiting_approval'
            task['updated_at'] = timestamp()
            self.store.put('task',task)

    def respond_question(self, question_id, data):
        if not isinstance(data,dict) or set(data)!={'answers'} or not isinstance(data['answers'],dict): raise ValueError('Invalid answers')
        with self.lock:
            record=deepcopy(self.questions.get(question_id))
            request=self.question_requests.get(question_id)
            if not request or not request['answerable'] or not record or record['status']!='pending': raise ValueError('Question unavailable')
        if set(data['answers']) != {q['id'] for q in record['questions']}: raise ValueError('Answer every current question')
        answers={}
        for q in record['questions']:
            selected=data['answers'][q['id']]
            if not isinstance(selected,list) or len(selected)!=1: raise ValueError('Choose one answer per question')
            text=safe_text(selected[0],4000)
            if q['options'] and not q['is_other'] and text not in {o['label'] for o in q['options']}: raise ValueError('Choose a listed option')
            answers[q['id']]={'answers':[text]}
        with self.lock:
            if self.question_requests.get(question_id) is not request or self.connection['status']!='connected' or self.client is not request['client'] or self.client.closed or not self._owned(request['thread_id']): raise ValueError('Question expired')
            task=self.tasks[request['task_id']]
            if not self._question_live(request) or self.questions[question_id]['status']!='pending': raise ValueError('Question expired')
            self.questions[question_id]['status']='answering'
            try:
                self.client.respond(request['rpc_id'],{'answers':answers})
            except ProtocolError:
                self.questions[question_id]['status']='unavailable'
                self.question_requests.pop(question_id,None)
                task.update(status='unknown',error='Question response delivery is unknown',updated_at=timestamp())
                self.store.put('task',task)
                raise
            self.questions[question_id]['status']='resolved'
            self.question_requests.pop(question_id,None)
            for q in record['questions']:
                self._append_message(task['id'],'user',q['header']+': '+answers[q['id']]['answers'][0],request['turn_id'],'You',status='sent')
            self._resume_after_request(task)
            return {'status':'resolved'}

    def _resume_after_request(self, task):
        if not any(a['task_id']==task['id'] and a['status']=='pending' for a in self.approvals.values()) and not any(r['task_id']==task['id'] for r in self.question_requests.values()) and task['status']=='waiting_approval':
            task.update(status='running',updated_at=timestamp())
            self.store.put('task',task)

    def _reward(self,message):
        params=message['params']
        success=False
        with self.lock:
            owned=self._owned(params.get('threadId'))
            task=self.tasks.get(owned['task_id']) if owned else None
            authorized=bool(not self.runtime_tracking_lost and not self.runtime_requests_disabled and owned and not owned.get('limited') and owned['parent'] is None and task and task['role']=='chief_of_staff' and task['status']=='running' and params.get('turnId')==task['turn_id'] and params.get('tool')=='issue_rebel_reward' and params.get('namespace') in {None,''})
            client=self.client
        if authorized:
            args=params.get('arguments')
            try:
                if not isinstance(args,dict) or set(args)!={'recipient_id','kind','coins','reason'}: raise ValueError('Invalid reward fields')
                # The ledger revalidates task authority atomically at insertion.
                prepared=self.team.prepare_reason(args['reason'])
                with self.lock:
                    if (self.runtime_tracking_lost or self.runtime_requests_disabled or self.client is not client or client.closed or not self._owned(params['threadId'])
                            or message['id'] in self.resolved_requests or task['thread_id'] != params['threadId']
                            or task['turn_id'] != params.get('turnId') or task['status'] != 'running'
                            or self._owned(params['threadId'])['parent'] is not None):
                        raise ValueError('Runtime expired')
                    self.team.issue_award(task,args['recipient_id'],args['kind'],args['coins'],args['reason'],params.get('callId'),self.team_tasks(),prepared_reason=prepared)
                    success=True
            except (ValueError,FileAccessError):
                pass
        if client and not client.closed:
            client.respond(message['id'],{'contentItems':[{'type':'inputText','text':'Recognition recorded.' if success else 'Recognition unavailable: live authority, recipient, bounds or sensitive-content checks did not pass.'}],'success':success})
