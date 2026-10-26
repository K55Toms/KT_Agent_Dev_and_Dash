"""Explicit local-history deletion, separate from native execution or recovery clearance."""
from copy import deepcopy
import hashlib
import json
import re
import sqlite3

from .project_files import FileAccessError

ACTIVE = {'queued', 'running', 'waiting_approval'}
DELETABLE = {'completed', 'failed', 'interrupted', 'unknown'}
IN_FLIGHT = {'prepared', 'dispatching', 'attached', 'stop_requested'}


class TaskDeletionMixin:
    def task_deletion_state(self, task):
        """Caller holds the dashboard lock; version binds confirmation to current authority."""
        task_id = task['id']
        children = [row for row in self.observed_tasks.values() if row.get('parent_task_id') == task_id]
        owned = [(key, row) for key, row in self.owned_threads.items() if row.get('task_id') == task_id]
        approvals = [row for row in self.approvals.values() if row.get('task_id') == task_id]
        questions = [row for row in self.questions.values() if row.get('task_id') == task_id]
        operations = [row for row in self.recovery_operations.values()
                      if task_id in {row.get('origin_task_id'), row.get('target_task_id')}]
        delivery = [row for row in self.delivery_operations.values()
                    if task_id in {row.get('subject_id'), row.get('task_id')}]
        linked = {row.get('target_task_id') for row in operations} | {row.get('task_id') for row in delivery}
        linked.discard(None)
        linked.add(task_id)
        busy = sorted(identifier for identifier in linked if identifier in self.message_busy
                      or identifier in self.starting_turn or identifier in self.assessment_jobs
                      or identifier in self.launching_tasks)
        record = self.recoveries.get(task_id)
        live_request = any(row.get('status') == 'pending' for row in approvals) or any(
            request.get('task_id') == task_id for request in self.question_requests.values())
        blocker = None
        if task.get('status') not in DELETABLE or any(row.get('status') in ACTIVE for row in children) or any(
                row.get('active') for _, row in owned):
            blocker = 'Stop the run and its active agents before deleting it.'
        elif live_request:
            blocker = 'Resolve the pending request or stop the run before deleting it.'
        elif (busy or record and record.get('state') == 'checking'
              or any(row.get('status') in IN_FLIGHT for row in operations)
              or any(self.tasks.get(identifier, {}).get('status') in ACTIVE for identifier in linked)):
            blocker = 'Wait for the current operation to finish or stop it before deleting this run.'
        version = hashlib.sha256(json.dumps({
            'task': task, 'children': sorted(children, key=lambda row: row['id']),
            'owned': [[key, {**row, 'turns': sorted(row.get('turns', ())) }] for key, row in sorted(owned)],
            'approvals': approvals, 'questions': questions, 'live_request': live_request,
            'recovery': record, 'operations': operations, 'delivery': delivery, 'busy': busy,
            'linked': [[key, self.tasks.get(key)] for key in sorted(linked)],
        }, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        return {'can_delete': blocker is None, 'deletion_blocker': blocker, 'deletion_version': version}

    def delete_task(self, task_id, data):
        if (not isinstance(data, dict) or set(data) != {'expected_version', 'confirmed'}
                or data['confirmed'] is not True or not isinstance(data['expected_version'], str)
                or not re.fullmatch(r'[0-9a-f]{64}', data['expected_version'])):
            raise ValueError('Confirm deletion using the current run version')
        with self.lock:
            task = self.tasks.get(task_id)
            if task is None:
                raise FileAccessError(404, 'Run was not found. Refresh the dashboard.')
            current = self.task_deletion_state(task)
            if data['expected_version'] != current['deletion_version']:
                raise FileAccessError(409, 'Run changed. Refresh and confirm deletion again.')
            if not current['can_delete']:
                raise FileAccessError(409, current['deletion_blocker'])
            # Read every persisted association before one transaction; publish no partial cleanup.
            predicates = {
                'task': lambda row: row['id'] == task_id,
                'conversation': lambda row: row.get('task_id') == task_id,
                'approval': lambda row: row.get('task_id') == task_id,
                'team_activity': lambda row: row.get('parent_task_id') == task_id,
                'attention_dismissal': lambda row: row['id'] == task_id,
                'recovery': lambda row: row['id'] == task_id,
                'recovery_operation': lambda row: task_id in {row.get('origin_task_id'), row.get('target_task_id')},
                'recovery_handoff': lambda row: row.get('origin_task_id') == task_id,
                'assessment_context': lambda row: row['id'] == task_id or row.get('task_id') == task_id,
                'delivery_operation': lambda row: task_id in {row.get('subject_id'), row.get('task_id')},
            }
            deletes = [('task', task_id), *[(kind, row['id']) for kind, predicate in predicates.items()
                       for row in self.store.load(kind) if predicate(row)]]
            removed = {}
            for kind, identifier in deletes:
                removed.setdefault(kind, set()).add(identifier)
            puts = []
            updated_recoveries = {}
            for identifier, record in self.recoveries.items():
                if identifier != task_id and (record.get('assessment_task_id') == task_id
                        or record.get('operation_id') in removed.get('recovery_operation', set())):
                    revised = deepcopy(record)
                    revised.update(assessment_task_id=None, plan=None, operation_id=None,
                                   revision=record['revision'] + 1)
                    updated_recoveries[identifier] = revised
                    puts.append(('recovery', revised))
            try:
                self.store.put_many(puts, deletes=deletes)
            except (sqlite3.Error, OSError, ValueError, TypeError):
                raise FileAccessError(503, 'Run could not be deleted. Nothing was removed; restore local storage and retry.') from None
            threads = {identifier for identifier, row in self.owned_threads.items() if row['task_id'] == task_id}
            if task.get('thread_id'):
                threads.add(task['thread_id'])
            for identifier in threads:
                self.owned_threads.pop(identifier, None)
                self.approval_reviews.expire(identifier)
            self.child_metadata_requested = {pair for pair in self.child_metadata_requested if not threads.intersection(pair)}
            for mapping, kind in ((self.tasks, 'task'), (self.approvals, 'approval'),
                    (self.observed_tasks, 'team_activity'), (self.attention_dismissals, 'attention_dismissal'),
                    (self.recoveries, 'recovery'), (self.recovery_operations, 'recovery_operation'),
                    (self.recovery_handoffs, 'recovery_handoff'), (self.delivery_operations, 'delivery_operation')):
                for identifier in removed.get(kind, ()):
                    mapping.pop(identifier, None)
            self.recoveries.update(updated_recoveries)
            self.messages = [row for row in self.messages if row.get('task_id') != task_id]
            for mapping in (self.questions, self.question_requests, self.pending):
                for identifier, row in list(mapping.items()):
                    if row.get('task_id') == task_id:
                        del mapping[identifier]
            self.actual.pop(task_id, None)
            self.recovery_receipts.clear()
            for identifier in removed.get('recovery_handoff', ()):
                self.handoff_reviews.pop(identifier, None)
            for identifier, receipt in list(self.delivery_receipts.items()):
                if (receipt.get('task_id') == task_id
                        or receipt.get('review_id') in removed.get('delivery_operation', set())):
                    del self.delivery_receipts[identifier]
            self._recovery_changed()
            return {'task_id': task_id, 'deleted': True}
