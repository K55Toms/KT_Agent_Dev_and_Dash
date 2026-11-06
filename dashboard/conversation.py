"""Bounded, scanner-approved conversations for currently dashboard-owned runtimes."""
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import queue
import re
import sqlite3
from pathlib import Path
import threading
from typing import Optional
import uuid

from .backends.claude_stream import NEUTRAL_KEYS
from .codex_client import ProtocolError, RequestRejected
from .diagnostics import DETAILS
from .project_files import FileAccessError, scan_preview
from .team import PROFILES

TERMINAL = {"completed", "interrupted", "failed"}
CLAUDE_RESUMABLE = {"completed", "failed", "interrupted", "unknown"}
CLAUDE_MAX_INVOCATIONS = 50
CLAUDE_STEER = "Guidance cannot be sent into a running Claude turn; send a follow-up after it finishes."
CLAUDE_STILL_RUNNING = ("A Claude process from before the restart may still be running; wait for it to end "
                        "before sending a follow-up.")
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


def check_claude_instruction(text):
    """Refuse, before any state change, an instruction the Claude argv builder would refuse: one starting
    with '-' (it would read as an option). Empty, over-long and control-character text is refused earlier
    by text_field/safe_text."""
    if not isinstance(text, str) or text.lstrip().startswith("-") or "\0" in text:
        raise ValueError("An instruction cannot start with '-'")


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
        self.child_metadata_requested = set()
        self.conversation_queue = queue.Queue(maxsize=64)
        self.conversation_worker = threading.Thread(target=self._conversation_loop, daemon=True)
        self.conversation_worker.start()

    def _owned(self, thread_id):
        return self.owned_threads.get(thread_id) if isinstance(thread_id, str) else None

    def _register_thread(self, thread_id, task_id, parent=None):
        if task_id not in self.tasks:
            raise ValueError('Run no longer exists')
        if self.tasks.get(task_id, {}).get('task_purpose') == 'recovery_assessment':
            raise ValueError('Assessment tasks never acquire native thread authority')
        if not isinstance(thread_id, str) or not IDENTIFIER.fullmatch(thread_id):
            raise ValueError('Invalid runtime identifier')
        if len(self.owned_threads) >= 256 and thread_id not in self.owned_threads:
            self.omitted_count += 1
            self.runtime_tracking_lost = True
            raise ValueError('Runtime coverage limit reached')
        if thread_id in self.owned_threads:
            if (self.owned_threads[thread_id]['task_id'] != task_id
                    or self.owned_threads[thread_id]['parent'] != parent):
                raise ValueError('Runtime identifier collision')
            return
        self.owned_threads[thread_id] = {'task_id': task_id, 'parent': parent, 'turns': set(), 'current_turn': None, 'active': True}
        if parent is not None:
            self._child_activity(thread_id)

    def team_tasks(self):
        return {**{record['id']: record for record in self._visible_observed_tasks()}, **self.tasks}

    def _visible_observed_tasks(self):
        return [record for record in self.observed_tasks.values()
                if (record.get('role') is None or record.get('role') in self.roles)
                and record.get('parent_task_id') in self.tasks
                and record.get('project_id') == self.tasks[record['parent_task_id']]['project_id']]

    def team_snapshot(self):
        """Caller holds self.lock. In a Claude deployment the view lists only Claude runs (and their delegates) and has
        no reward area; a Codex deployment's snapshot is exactly Team.snapshot over team_tasks."""
        tasks = self.team_tasks()
        if self.backend.capabilities.provider != 'claude':
            return self.team.snapshot(tasks)
        tasks = {key: record for key, record in tasks.items()
                 if (record.get('provider') == 'claude' if record['id'] in self.tasks
                     else self.tasks.get(record.get('parent_task_id'), {}).get('provider') == 'claude')}
        return self.team.snapshot(tasks, rewards=False)

    def delegated_activities(self):
        """Return only the observed activity projection, never native tool content."""
        fields = ('id', 'parent_task_id', 'project_id', 'thread_id', 'parent_thread_id',
                  'role', 'title', 'status', 'created_at', 'updated_at')
        return [{field: record.get(field) for field in fields}
                for record in sorted(self._visible_observed_tasks(),
                                     key=lambda record: (record.get('updated_at', ''), record['id']), reverse=True)]

    def _child_waiting(self, thread_id):
        return (any(request.get('binding', (None,))[0] == thread_id
                    and self.approvals.get(key, {}).get('status') == 'pending'
                    for key, request in self.pending.items())
                or any(request.get('thread_id') == thread_id for request in self.question_requests.values()))

    def _sync_child_activity(self, task_id):
        """Reflect exact live request ownership without changing terminal children."""
        for thread_id, owned in self.owned_threads.items():
            if owned['task_id'] != task_id or owned['parent'] is None or not owned.get('active'):
                continue
            waiting = self._child_waiting(thread_id)
            record = self.observed_tasks.get(hashlib.sha256(('child:' + thread_id).encode()).hexdigest())
            if record and (waiting or record['status'] == 'waiting_approval'):
                desired = 'waiting_approval' if waiting else 'running'
                if record['status'] != desired:
                    self._child_activity(thread_id, status=desired)

    def active_children(self, task_id):
        return [(thread_id, owned) for thread_id, owned in self.owned_threads.items()
                if owned['task_id'] == task_id and owned['parent'] is not None and owned.get('active')]

    def active_project_roots(self, exclude_task=None):
        active_ids = {task['id'] for task in self.tasks.values()
                      if task['id'] != exclude_task and task['status'] in {'queued', 'running', 'waiting_approval'}}
        active_ids = {identifier for identifier in active_ids
                      if self.tasks[identifier].get("task_purpose") != "recovery_assessment"}
        active_ids.update(owned['task_id'] for owned in self.owned_threads.values()
                          if owned['parent'] is not None and owned.get('active'))
        roots = self.recovery_hold_roots(exclude_task) if hasattr(self, "recoveries") else []
        return roots + [Path(self.projects[self.tasks[identifier]['project_id']]['path']) for identifier in active_ids
                if identifier in self.tasks and self.tasks[identifier]['project_id'] in self.projects]

    def _child_activity(self, thread_id, role_id=None, status=None):
        owned = self._owned(thread_id)
        if not owned or not owned['parent']:
            return
        key = hashlib.sha256(('child:'+thread_id).encode()).hexdigest()
        record = self.observed_tasks.get(key)
        if record is None:
            parent = self.tasks[owned['task_id']]
            record = {'id':key,'parent_task_id':parent['id'],'project_id':parent['project_id'],
                      'thread_id':thread_id,'parent_thread_id':owned['parent'],
                      'role':None,'title':'Unattributed delegated task',
                      'status':'running','created_at':timestamp(),'updated_at':timestamp()}
            self.observed_tasks[key] = record
        if record is not None:
            if isinstance(role_id, str) and role_id in self.roles:
                record.update(role=role_id, title=self.roles[role_id]['label']+' delegated task')
            record.update(thread_id=thread_id, parent_thread_id=owned['parent'])
            if status == 'running' and self._child_waiting(thread_id):
                status = 'waiting_approval'
            if status in {'queued','running','waiting_approval','completed','failed','interrupted','unknown'}:
                record['status'] = status
            record['updated_at'] = timestamp()
            try:
                self.store.put('team_activity',record)
            except (sqlite3.Error, OSError):
                self.runtime_tracking_lost = True
                parent = self.tasks[owned['task_id']]
                parent['recovery_hold'] = True
                try:
                    self.store.put('task', parent)
                except (sqlite3.Error, OSError):
                    pass  # Storage failure cannot justify clearing the in-memory hold.
        if len(self.observed_tasks)>1000:
            oldest = sorted((record for record in self.observed_tasks.values()
                             if record.get('status') in TERMINAL), key=lambda x:x['updated_at'])[:len(self.observed_tasks)-1000]
            for record in oldest:
                self.observed_tasks.pop(record['id'],None)
                self.store.delete('team_activity',record['id'])

    def _delegation_parent_live(self, owned):
        if (not owned or not owned.get('active') or owned.get('limited')
                or owned.get('current_turn') not in owned['turns']):
            return False
        task = self.tasks.get(owned['task_id'])
        return bool(task and task.get("task_purpose") != "recovery_assessment" and (task['status'] in {'queued', 'running', 'waiting_approval'}
                              or owned['parent'] is not None and task['status'] in TERMINAL))

    def _note_turn(self, thread_id: str, turn_id: str, phase: str, status: Optional[str] = None) -> None:
        """Record a turn start or completion on an owned thread; the caller holds self.lock.

        phase is "started" or "completed". A completion only counts for the thread's current turn;
        status maps to completed, failed or interrupted, anything else to unknown. An unowned thread
        changes nothing. The caller validates turn_id.
        """
        owned = self._owned(thread_id)
        if not owned:
            return
        if phase=='started' and len(owned['turns'])>=200 and turn_id not in owned['turns']:
            self.omitted_count+=1
            owned.update(current_turn=turn_id, active=True, limited=True)
            return
        if phase=='started':
            owned['turns'].add(turn_id)
            owned['current_turn']=turn_id
            owned['active']=True
            owned['last_status']='running'
            self._child_activity(thread_id,status='running')
        elif turn_id==owned.get('current_turn'):
            owned['active']=False
            owned['last_status'] = {'completed':'completed','failed':'failed','interrupted':'interrupted'}.get(status,'unknown')
            self._child_activity(thread_id,status=owned['last_status'])
            if owned['parent']:
                for key,request in list(self.question_requests.items()):
                    if request['thread_id']==thread_id:
                        self.questions[key]['status']='unavailable'
                        del self.question_requests[key]
                self._resume_after_request(self.tasks[owned['task_id']])

    def _conversation_metadata(self, method, params):
        # Only bounded protocol identity/status is handled here. No model text is read.
        owned = self._owned(params.get('threadId'))
        if method == 'thread/started':
            thread = params.get('thread',{})
            if not isinstance(thread,dict):
                return
            parent, child = thread.get('parentThreadId'),thread.get('id')
            parent_owned = self._owned(parent)
            if parent_owned and self.tasks[parent_owned['task_id']].get('task_purpose') == 'recovery_assessment':
                self._assessment_violation(self.tasks[parent_owned['task_id']])
                return
            if self._delegation_parent_live(parent_owned):
                try:
                    self._register_thread(child,parent_owned['task_id'],parent)
                except ValueError:
                    return
                self._child_activity(child,thread.get('agentRole'))
        elif method in {'item/started', 'item/completed'} and owned:
            item = params.get('item',{})
            if isinstance(item, dict) and item.get('type') == 'subAgentActivity':
                if self.tasks[owned['task_id']].get('task_purpose') == 'recovery_assessment':
                    self._assessment_violation(self.tasks[owned['task_id']])
                    return
                child = item.get('agentThreadId')
                if (params.get('turnId') not in owned['turns']
                        or params.get('turnId') != owned.get('current_turn') or child == params.get('threadId')):
                    return
                if item.get('kind') in {'completed', 'interrupted'}:
                    child_owned = self._owned(child)
                    if child_owned and child_owned['parent'] == params['threadId']:
                        child_owned.update(active=False, last_status=item['kind'])
                        self._child_activity(child, status=item['kind'])
                    return
                if item.get('kind') != 'started':
                    return
                if not self._delegation_parent_live(owned):
                    return
                try:
                    self._register_thread(child, owned['task_id'], params['threadId'])
                except ValueError:
                    return
                self._queue_child_metadata(params['threadId'], child)
                return
            if method != 'item/completed':
                return
            if not isinstance(item,dict) or item.get('type')!='collabAgentToolCall' or item.get('status')!='completed' or item.get('senderThreadId')!=params.get('threadId'):
                return
            receivers,states = item.get('receiverThreadIds'),item.get('agentsStates')
            if not isinstance(receivers,list) or len(receivers)>16 or not isinstance(states,dict) or len(states)>16:
                return
            for receiver in receivers:
                if item.get('tool')=='spawnAgent':
                    if (not self._delegation_parent_live(owned)
                            or params.get('turnId') != owned.get('current_turn')):
                        continue
                    try:
                        self._register_thread(receiver,owned['task_id'],params['threadId'])
                    except ValueError:
                        continue
                    self._queue_child_metadata(params['threadId'], receiver)
                child = self._owned(receiver)
                if child and child['task_id']==owned['task_id']:
                    state=states.get(receiver,{})
                    state=state.get('status') if isinstance(state,dict) else None
                    if state in {'completed','errored','interrupted','shutdown','notFound'}:
                        child['active'] = False
                    elif state in {'running','pendingInit'}:
                        child['active'] = True
                    activity_status = {'completed':'completed','errored':'failed','interrupted':'interrupted','shutdown':'interrupted','notFound':'unknown','running':'running','pendingInit':'queued'}.get(state)
                    if activity_status:
                        child['last_status'] = activity_status
                    self._child_activity(receiver,status=activity_status)
        elif owned and method in {'turn/started','turn/completed'}:
            turn=params.get('turn',{})
            turn_id=turn.get('id') if isinstance(turn,dict) else None
            if not isinstance(turn_id,str) or not IDENTIFIER.fullmatch(turn_id):
                return
            if method=='turn/started':
                self._note_turn(params['threadId'], turn_id, 'started')
            else:
                # The raw native status is passed through; _note_turn maps it exactly as before.
                self._note_turn(params['threadId'], turn_id, 'completed', turn.get('status'))
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

    def _queue_child_metadata(self, parent, child):
        key = (parent, child)
        if key in self.child_metadata_requested or len(self.child_metadata_requested) >= 256:
            return
        owned = self._owned(child)
        if not owned or owned['parent'] != parent:
            return
        self.child_metadata_requested.add(key)
        self._queue_conversation({'method': 'dashboard/childMetadata', 'params': {
            'threadId': parent, 'childThreadId': child, 'taskId': owned['task_id']}})

    def _read_child_metadata(self, params):
        parent, child, task_id = params['threadId'], params['childThreadId'], params['taskId']
        with self.lock:
            owned = self._owned(child)
            parent_owned = self._owned(parent)
            client = self.client
            if (not client or client.closed or not owned or not parent_owned
                    or owned['parent'] != parent or owned['task_id'] != task_id
                    or parent_owned['task_id'] != task_id):
                return
            project_path = self.projects[self.tasks[task_id]['project_id']]['path']
        # Metadata-only protocol read on the worker; never fetch turns or access
        # native rollout files. Ignore every field other than fixed identity data.
        response = client.request_readonly('thread/read', {'threadId': child, 'includeTurns': False})
        thread = response.get('thread') if isinstance(response, dict) else None
        if not isinstance(thread, dict):
            return
        identity = {key: thread.get(key) for key in ('id', 'parentThreadId', 'agentRole', 'cwd')}
        del thread, response
        with self.lock:
            if (self.client is not client or client.closed or self._owned(child) is not owned
                    or self._owned(parent) is not parent_owned):
                return
            if (identity['id'] != child or identity['parentThreadId'] != parent
                    or identity['cwd'] != project_path):
                owned['limited'] = True
                self.omitted_count += 1
                return
            role = identity['agentRole']
            self._child_activity(child, role,
                                 status=owned.get('last_status', 'running' if owned.get('active') else 'unknown'))
            self._sync_child_activity(task_id)

    def _append_message(self, task_id, kind, text, turn_id, sender, receivers=(), status='complete', event_id=None):
        """Append one message; True when it was added, False when refused or an already-recorded event_id."""
        if task_id not in self.tasks:
            return False
        key = hashlib.sha256((task_id + '\0' + (event_id or uuid.uuid4().hex)).encode()).hexdigest()
        if any(x['id'] == key for x in self.messages):
            return False
        record = {'id': key, 'task_id': task_id, 'kind': kind, 'text': text,
                  'created_at': timestamp(), 'turn_id': turn_id, 'sender': sender,
                  'receivers': list(receivers), 'status': status}
        self.messages.append(record)
        self.store.put('conversation', record)
        if hasattr(self, 'delivery_operations'):
            self._delivery_message(record)
        own = [m for m in self.messages if m['task_id'] == task_id]
        remove = {m['id'] for m in own[:-200]}
        survivors = [m for m in self.messages if m['id'] not in remove]
        remove.update(m['id'] for m in survivors[:-2000])
        self.messages = [m for m in self.messages if m['id'] not in remove]
        for key in remove:
            self.store.delete('conversation', key)
        return True

    def _claude_send_state(self, task):
        """Follow-up rules for a Claude run (decision 5): a new `claude -p --resume` process per message."""
        if self.runtime_tracking_lost:
            return None, 'Runtime tracking limit reached; stop the dashboard and inspect project state before restarting'
        if self.connection['status'] != 'connected':
            return None, 'Claude Code is not ready.'
        if task['status'] in {'queued', 'running', 'waiting_approval'} or task['id'] in self.runs:
            return None, CLAUDE_STEER
        if task['id'] in self.message_busy or task['id'] in self.launching_tasks:
            return None, 'A message is already being sent'
        if task['status'] not in CLAUDE_RESUMABLE:
            return None, 'This run has no available turn for guidance'
        if any(entry.get('code') == 'claude_permission_mode' for entry in task.get('diagnostics') or []):
            return None, 'This run was stopped because of its permission mode and cannot be continued; start a new run.'
        record = task.get('claude') or {}
        session_id = record.get('session_id')
        if not isinstance(session_id, str) or not session_id:
            return None, 'This run has no Claude session to continue; start a new run.'
        owned = self._owned(session_id)
        if (type(record.get('invocations')) is not int or record['invocations'] >= CLAUDE_MAX_INVOCATIONS
                or owned and len(owned['turns']) >= 200):
            return None, 'This run reached the follow-up limit; start a new run.'
        return 'followup', None

    def _send_state(self, task):
        if task and task.get("delivery_context"):
            return None, "Use delivery controls for check and review runs"
        if task and task.get("provider") == "claude":
            return self._claude_send_state(task)
        if task and task.get("recovery_stop_pending"):
            return None, "Stopping; wait for confirmed interruption before sending guidance"
        if task and task.get("task_purpose") == "recovery_assessment":
            return self._assessment_send_state(task)
        elif task and (task.get("status") == "unknown" or task.get("recovery_hold")
                       or any(child.get("parent_task_id") == task["id"]
                              and (child.get("status") == "unknown"
                                   or task.get("status") in TERMINAL
                                   and child.get("status") in {"queued", "running", "waiting_approval"})
                              for child in self.observed_tasks.values())):
            return None, "Use recovery assessment and approve a fresh continuation plan"
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
            messages = [m for m in self.messages if m['task_id'] == task_id]
            thread_ids = {task.get('thread_id')}
            thread_ids.update(thread for thread, owned in self.owned_threads.items() if owned['task_id'] == task_id)
            for message in messages:
                thread_ids.add(message.get('sender'))
                thread_ids.update(message.get('receivers', []))
            agents = {}
            for thread in thread_ids:
                if not isinstance(thread, str):
                    continue
                if thread == task.get('thread_id'):
                    role = task.get('role')
                else:
                    activity = self.observed_tasks.get(hashlib.sha256(('child:' + thread).encode()).hexdigest(), {})
                    role = activity.get('role') if activity.get('parent_task_id') == task_id else None
                if role in PROFILES and role in self.roles:
                    agents[thread] = {'role_id': role, 'name': PROFILES[role][0]}
            return deepcopy({'task_id': task_id, 'turn_id': task['turn_id'],
                'messages': [{k:v for k,v in m.items() if k != 'task_id'} for m in messages],
                'agents': agents,
                'questions': [q for q in self.questions.values() if q['task_id'] == task_id],
                'recovery_available': self.recovery_available(task),
                'can_send': mode is not None, 'send_mode': mode, 'blocked_reason': reason, 'send_disabled_reason': reason,
                'omitted_count': self.omitted_count, 'retention': 'local_scanned', 'coverage': 'Dashboard-managed visible messages and observed collaboration only. Reasoning, tool output, desktop sessions and unavailable events are excluded. Latest 200 messages per task; 2000 overall.'})

    def send_message(self, task_id, data):
        if not isinstance(data, dict) or set(data) != {'text', 'expected_turn_id'}:
            raise ValueError('Invalid message fields')
        self._require_active_provider_for(task_id)
        text = safe_text(data['text'], 16000)
        self._claude_refuse_if_old_process(task_id)
        with self.lock:
            if self.tasks.get(task_id, {}).get('task_purpose') == 'recovery_assessment':
                return self._assessment_send(task_id, {**data, 'text': text})
            task = self.tasks.get(task_id)
            mode, reason = self._send_state(task)
            if not mode:
                # A live native decision needs its scoped reply. Refreshing the
                # same conversation cannot clear that decision or resume work.
                raise ValueError(reason)
            if data['expected_turn_id'] != task['turn_id']:
                raise ValueError('Refresh the conversation before sending')
            if task.get('provider') == 'claude':
                return self._claude_followup(task, text)
            self._verify_task_policy(task)
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
            response = self.backend.steer(params, client=client) if mode == 'steer' else self.backend.start_turn(params, client=client)
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
                if task.get('task_purpose', 'development') == 'development':
                    task['recovery_hold'] = True
                self._finish_approvals(task)
                self._expire_questions(task_id)
                self.store.put('task', task)
            raise ProtocolError('Message state is unknown; no retry occurred') from None
        finally:
            with self.lock:
                self.message_busy.discard(task_id)
                self.starting_turn.discard(task_id)

    @staticmethod
    def _claude_flagged(task):
        """An unknown Claude task whose latest diagnostic says a child from before a restart may still run.
        Only such a task holds its project (recovery_hold_roots); any other unknown Claude task holds nothing."""
        logs = task.get('diagnostics') or []
        return (task.get('provider') == 'claude' and task.get('status') == 'unknown' and bool(logs)
                and logs[-1].get('code') == 'claude_possibly_running')

    def _refuse_claude_possibly_running(self, root, exclude_task=None):
        """Caller holds self.lock: refuse Claude work overlapping a flagged project with that flag's own text."""
        for other in self.tasks.values():
            project = self.projects.get(other.get('project_id'))
            if other['id'] == exclude_task or not self._claude_flagged(other) or project is None:
                continue
            held = Path(project['path'])
            if root == held or root in held.parents or held in root.parents:
                raise ValueError(DETAILS['claude_possibly_running'][0])

    def _claude_refuse_if_old_process(self, task_id):
        """After a restart warned that the old child may still run, re-check (outside the lock) before resuming
        the same session: two processes must never work on one session."""
        with self.lock:
            task = self.tasks.get(task_id)
            if (not task or task.get('provider') != 'claude' or task.get('status') != 'unknown'
                    or task_id in self.runs or not self._claude_flagged(task)):
                return
            probe_task = deepcopy(task)
        if self._claude_old_process_alive(probe_task):
            raise ValueError(CLAUDE_STILL_RUNNING)

    def _claude_followup(self, task, text):
        """Caller holds self.lock and _send_state allowed a follow-up. Everything is checked before the first
        state change; the launch worker then runs `claude -p <text> --resume <session_id>`."""
        check_claude_instruction(text)
        self._refuse_claude_possibly_running(Path(self.projects[task['project_id']]['path']), exclude_task=task['id'])
        self._check_followup_scope(task)
        record = task['claude']
        number = record['invocations'] + 1
        turn_id = f'turn-{number}'
        if not IDENTIFIER.fullmatch(turn_id):
            raise ValueError('This run has no available turn for guidance')
        usage = task.get('usage') if isinstance(task.get('usage'), dict) else {}
        cost = task.get('cost') if isinstance(task.get('cost'), dict) else {}
        usd = cost.get('usd')
        candidate = deepcopy(task)
        candidate['claude'].update(
            invocations=number, pid=None, started_at=None, pid_started=None,
            # Each --resume is a new process whose counters restart at zero: the parser adds these baselines
            # so the task keeps running totals (Review Focus 4).
            usage_baseline={k: v if type(v) is int and v >= 0 else 0
                            for k, v in ((k, usage.get(k, 0)) for k in NEUTRAL_KEYS)},
            cost_baseline=float(usd) if type(usd) in (int, float) and usd >= 0 else 0.0)
        candidate.update(status='queued', error=None, plan=[], turn_id=turn_id, updated_at=timestamp())
        try:
            self.store.put('task', candidate)
        except (sqlite3.Error, OSError):
            raise FileAccessError(503, 'Follow-up could not be saved. Nothing was started.') from None
        task.clear()
        task.update(candidate)
        self.launching_tasks.add(task['id'])
        worker = threading.Thread(target=self._launch_claude,
                                  args=(task['id'], text, record['session_id'], number), daemon=True)
        self.workers = [x for x in self.workers if x.is_alive()]
        self.workers.append(worker)
        worker.start()
        return {'status': 'sent', 'mode': 'followup'}

    def _check_followup_scope(self, task):
        if task.get("task_purpose") != "recovery_assessment" and (task.get("recovery_hold")
                or any(child.get("parent_task_id") == task["id"]
                       and child.get("status") in {"unknown", "queued", "running", "waiting_approval"}
                       for child in self.observed_tasks.values())):
            raise ValueError("Use recovery assessment before continuing unresolved work")
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
        # Permissions/roots are sticky thread state validated before the first turn.
        # Reselecting the temporary named profile attempts a disk-config lookup.
        return {'model': role['model'], 'effort': role['reasoning'],
            'approvalPolicy': 'on-request',
            'approvalsReviewer': 'user'}

    def _queue_conversation(self, message):
        if self.conversation_stopping.is_set() or len(json.dumps(message)) > 65536:
            self.omitted_count += 1
            if hasattr(self, 'delivery_operations'):
                self._delivery_review_unavailable(message)
            return False
        try:
            self.conversation_queue.put_nowait(deepcopy(message))
        except queue.Full:
            if hasattr(self, 'delivery_operations'):
                self._delivery_review_unavailable(message)
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
                if hasattr(self, 'delivery_operations'):
                    self._delivery_review_unavailable(message)
                pass  # Raw payloads and validation errors never reach logs.
            finally:
                self.conversation_queue.task_done()

    def wait_conversations(self):
        self.conversation_queue.join()

    def _process_conversation(self, message):
        method, params = message['method'], message['params']
        if method == 'dashboard/stopAssessment':
            try:
                self.interrupt(params['taskId'], {})
            except (ValueError, ProtocolError, OSError):
                pass
            return
        if method == 'dashboard/childMetadata':
            return self._read_child_metadata(params)
        if method == 'item/tool/requestUserInput':
            serialized = json.dumps(params.get('questions', []), ensure_ascii=False)
            options = [option.get('label', '') for question in params.get('questions', []) if isinstance(question, dict)
                       for option in (question.get('options') or []) if isinstance(option, dict)]
            if PERMISSION.search(serialized) or any(AUTHORIZATION_CHOICE.search(label) for label in options):
                with self.lock:
                    owned = self._owned(params.get('threadId'))
                    task = self.tasks.get(owned['task_id']) if owned else None
                    if task:
                        return self._approval(message, task)
            return self._question(message)
        if method == 'item/tool/call':
            if params.get('tool') == 'register_task_output':
                return self._output_tool(message)
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
                if hasattr(self, 'delivery_operations'):
                    self._delivery_review_unavailable(message)
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
        elif item.get('type') == 'subAgentActivity':
            text = {'started': 'Native specialist activity observed: started.',
                    'interacted': 'Native specialist activity observed: interacted.',
                    'interrupted': 'Native specialist activity observed: interrupted.',
                    'completed': 'Native specialist activity observed: completed.'}.get(item.get('kind'))
            child_id = item.get('agentThreadId')
            with self.lock:
                child = self._owned(child_id)
                if (text and self._owned(params['threadId']) is owned and child
                        and child['parent'] == params['threadId'] and child['task_id'] == task_id):
                    # A fixed native lifecycle observation, never a reconstructed
                    # prompt or a claim about what the agents said to one another.
                    self._append_message(task_id, 'system', text, params['turnId'],
                                         params['threadId'], [child_id], event_id='|'.join(event))
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
                            if (not self._delegation_parent_live(owned)
                                    or params.get('turnId') != owned.get('current_turn')):
                                return
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
        if task.get('recovery_stop_pending'):
            return False
        current = owned.get('current_turn') or task['turn_id']
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
            self._sync_child_activity(task['id'])

    def respond_question(self, question_id, data):
        if not isinstance(data,dict) or set(data)!={'answers'} or not isinstance(data['answers'],dict): raise ValueError('Invalid answers')
        with self.lock:
            asked=self.question_requests.get(question_id)
            self._require_active_provider(self.tasks.get(asked['task_id']) if asked else None)
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
        self._sync_child_activity(task['id'])
        if not any(a['task_id']==task['id'] and a['status']=='pending' for a in self.approvals.values()) and not any(r['task_id']==task['id'] for r in self.question_requests.values()) and task['status']=='waiting_approval':
            task.update(status='running',updated_at=timestamp())
            self.store.put('task',task)

    def _reward(self,message):
        params=message['params']
        success=False
        with self.lock:
            owned=self._owned(params.get('threadId'))
            task=self.tasks.get(owned['task_id']) if owned else None
            if task and task.get('task_purpose') == 'recovery_assessment':
                self._assessment_violation(task)
            authorized=bool(task and not task.get('recovery_stop_pending') and task.get('task_purpose') != 'recovery_assessment' and not self.runtime_tracking_lost and not self.runtime_requests_disabled and owned and not owned.get('limited') and owned['parent'] is None and task and task['role']=='chief_of_staff' and task['status']=='running' and params.get('turnId')==task['turn_id'] and params.get('tool')=='issue_rebel_reward' and params.get('namespace') in {None,''})
            client=self.client
        if authorized:
            args=params.get('arguments')
            try:
                if not isinstance(args,dict) or set(args)!={'recipient_id','kind','coins','reason'}: raise ValueError('Invalid reward fields')
                # The ledger revalidates task authority atomically at insertion.
                prepared=self.team.prepare_reason(args['reason'])
                with self.lock:
                    if (task.get('recovery_stop_pending') or task.get('task_purpose') == 'recovery_assessment' or self.runtime_tracking_lost or self.runtime_requests_disabled or self.client is not client or client.closed or not self._owned(params['threadId'])
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
