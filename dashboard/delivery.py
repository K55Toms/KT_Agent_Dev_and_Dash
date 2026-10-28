"""Current-code delivery evidence; native execution status remains independent."""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import sqlite3
import stat
import time
import uuid

from .ponytail_policy import PolicyError
from .project_files import (FileAccessError, MAX_CANDIDATES, MAX_FILES, MAX_FILE_BYTES,
    _git, _same_root, _worktree, checked_path, root_descriptor, scan_preview)

ACTIVE = {'queued', 'running', 'waiting_approval'}
HEX = re.compile(r'[0-9a-f]{64}\Z')
IDENTIFIER = re.compile(r'[A-Za-z0-9_.:/-]{1,200}\Z')
MAX_OPERATIONS = 1000
MAX_TOTAL_BYTES = 16 * 1024 * 1024


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode()).hexdigest()


def exact(data, names):
    if not isinstance(data, dict) or set(data) != set(names):
        raise ValueError('Delivery action fields do not match')
    if 'confirmed' in data and data['confirmed'] is not True:
        raise ValueError('Explicit delivery action confirmation is required')


def conflict():
    raise FileAccessError(409, 'Delivery evidence changed. Refresh and review the current state.')



POLICY_ERROR = 'The approved Ponytail policy or registered profiles are unavailable or changed.'
POLICY_ACTION = 'Repair the approved plugin or profile files, then reload the dashboard when idle and retry. Policy updates require review.'


class DeliveryNotStarted(FileAccessError):
    """Definitive local preflight failure, never an uncertain native dispatch result."""
    def __init__(self, error):
        status = error.status if isinstance(error, FileAccessError) else 503 if isinstance(error, (OSError, sqlite3.Error)) else 400
        self.code = 'approved_policy_unavailable' if isinstance(error, PolicyError) else 'delivery_not_started'
        self.action = POLICY_ACTION if isinstance(error, PolicyError) else 'Refresh the delivery setup and retry explicitly. No automatic retry occurred.'
        super().__init__(status, POLICY_ERROR if isinstance(error, PolicyError) else 'Delivery setup did not start a new run.')


def code_snapshot(project):
    """Hash bounded Git-visible file bytes, including opaque assets; reveal none."""
    root = project['path']
    with root_descriptor(root) as root_fd:
        info = os.fstat(root_fd)
        expected = project.get('directory_identity')
        if expected and (info.st_dev, info.st_ino) != (expected['device'], expected['inode']):
            raise FileAccessError(409, 'Registered project identity changed')
        _worktree(root)
        code, output = _git(root, 'ls-files', '--cached', '--others', '--exclude-standard', '-z')
        raw = output.split(b'\0')
        if code or len(raw) - 1 > MAX_CANDIDATES or raw[-1] != b'':
            raise FileAccessError(409, 'Delivery file coverage is incomplete')
        try:
            candidates = sorted(set(value.decode('utf-8') for value in raw if value))
        except UnicodeError:
            raise FileAccessError(409, 'Delivery file names are unsupported') from None
        # ls-files already excludes ignored untracked paths; tracked files stay covered.
        paths = candidates
        if len(paths) > MAX_FILES:
            raise FileAccessError(409, 'Delivery file coverage exceeds its limit')
        head_code, initial_head = _git(root, 'rev-parse', '--verify', 'HEAD')
        rows, witnesses, content, total = [], [], bytearray(), 0
        for name in paths:
            parts = checked_path(name)
            parent = os.dup(root_fd)
            target = None
            try:
                try:
                    for part in parts[:-1]:
                        child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
                        os.close(parent)
                        parent = child
                    target = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
                except FileNotFoundError:
                    rows.append([name, 'deleted'])
                    witnesses.append((parts, None))
                    continue
                before = os.fstat(target)
                if (not stat.S_ISREG(before.st_mode) or before.st_nlink != 1
                        or before.st_uid != os.getuid() or before.st_size > MAX_FILE_BYTES):
                    raise FileAccessError(409, 'Delivery file is unsupported or exceeds its limit')
                data = bytearray()
                while len(data) <= MAX_FILE_BYTES:
                    chunk = os.read(target, min(65536, MAX_FILE_BYTES + 1 - len(data)))
                    if not chunk:
                        break
                    data.extend(chunk)
                after = os.fstat(target)
                if (len(data) > MAX_FILE_BYTES or (before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns, before.st_mode)
                        != (after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns, after.st_mode)):
                    raise FileAccessError(409, 'Delivery files changed during inspection')
                total += len(data)
                if total > MAX_TOTAL_BYTES:
                    raise FileAccessError(409, 'Delivery content exceeds its limit')
                rows.append([name, stat.S_IMODE(before.st_mode), hashlib.sha256(data).hexdigest()])
                witnesses.append((parts, (after.st_dev, after.st_ino, after.st_mode, after.st_nlink, after.st_uid,
                                         after.st_size, after.st_mtime_ns, after.st_ctime_ns)))
                content.extend(data)
                content.extend(b'\n')
            except OSError:
                raise FileAccessError(409, 'Delivery file coverage is unavailable or contains an unsafe link') from None
            finally:
                if target is not None:
                    os.close(target)
                os.close(parent)
        scan_preview(bytes(content))
        # Scanner work may take time: every file/deletion must still be the same object.
        for parts, expected_file in witnesses:
            parent, target = os.dup(root_fd), None
            try:
                try:
                    for part in parts[:-1]:
                        child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
                        os.close(parent)
                        parent = child
                    target = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
                except FileNotFoundError:
                    if expected_file is not None:
                        raise FileAccessError(409, 'Delivery files changed during content checks')
                    continue
                current = os.fstat(target)
                actual = (current.st_dev, current.st_ino, current.st_mode, current.st_nlink, current.st_uid,
                          current.st_size, current.st_mtime_ns, current.st_ctime_ns)
                if actual != expected_file:
                    raise FileAccessError(409, 'Delivery files changed during content checks')
            except OSError:
                raise FileAccessError(409, 'Delivery files changed during content checks') from None
            finally:
                if target is not None:
                    os.close(target)
                os.close(parent)
        code, head = _git(root, 'rev-parse', '--verify', 'HEAD')
        if code != head_code or head != initial_head:
            raise FileAccessError(409, 'Delivery revision changed during content checks')
        head = head.strip().decode('ascii', errors='ignore') if code == 0 else None
        if head is not None and not re.fullmatch(r'[0-9a-f]{40}|[0-9a-f]{64}', head):
            raise FileAccessError(409, 'Delivery revision is unsupported')
        code, again = _git(root, 'ls-files', '--cached', '--others', '--exclude-standard', '-z')
        _same_root(root, root_fd)
        if code or again != output:
            raise FileAccessError(409, 'Delivery files changed during inspection')
        return digest({'root': [root, info.st_dev, info.st_ino], 'head': head, 'files': rows})


def command_matches(native, approved):
    if native == approved:
        return True
    try:
        parts = shlex.split(native) if isinstance(native, str) and len(native) <= 4096 else []
    except ValueError:
        return False
    return len(parts) == 3 and parts[0] in {'/bin/zsh', '/bin/bash', '/bin/sh'} and parts[1] == '-lc' and parts[2] == approved


class DeliveryMixin:
    def _init_delivery(self):
        self.check_plans = {row['id']: row for row in self.store.load('check_plan')}
        self.delivery_operations = {row['id']: row for row in self.store.load('delivery_operation')}
        self.delivery_receipts = {}
        self.delivery_inflight = set()
        self.delivery_summaries = {}

    def _delivery_summary_stamp(self, task):
        project_id = task.get('project_id')
        return digest({'task': task, 'project': self.projects.get(project_id),
            'children': [row for row in self.observed_tasks.values() if row.get('parent_task_id') == task['id']],
            'plan': self.check_plans.get(project_id), 'roles': self.roles,
            'operations': [row for row in self.delivery_operations.values() if row.get('subject_id') == task['id']],
            'connection': [self.connection.get('status'), bool(self.client and not self.client.closed)],
            'policy': [str(getattr(self.policy_provider, 'cache_root', '')), getattr(self.policy_provider, 'version', None),
                       getattr(self.policy_provider, 'digest', None)]})

    def delivery_summary(self, task):
        cached = self.delivery_summaries.get(task['id'])
        if not cached:
            return {'status': 'not_checked', 'checked_at': None, 'freshness': 'unavailable', 'reason_codes': []}
        result = deepcopy(cached['summary'])
        if cached['stamp'] != self._delivery_summary_stamp(task):
            result.update(freshness='stale', reason_codes=['context_changed'])
        return result

    def check_plan(self, project_id):
        with self.lock:
            if project_id not in self.projects:
                raise FileAccessError(404, 'Registered project was not found')
            row = self.check_plans.get(project_id, {})
            return deepcopy({'project_id': project_id, 'version': row.get('version', 0),
                'commands': row.get('commands', []), 'approved_at': row.get('approved_at')})

    def approve_check_plan(self, project_id, data):
        exact(data, {'expected_version', 'commands', 'confirmed'})
        if type(data['expected_version']) is not int or not isinstance(data['commands'], list) or not 1 <= len(data['commands']) <= 8:
            raise ValueError('Choose between one and eight exact check commands')
        commands = []
        for number, text in enumerate(data['commands']):
            if (not isinstance(text, str) or not text.strip() or text != text.strip() or len(text) > 2000
                    or any(ord(char) < 32 or ord(char) == 127 for char in text)):
                raise ValueError('Check commands must be bounded single-line text')
            scan_preview(text.encode('utf-8'))
            commands.append({'id': digest(text), 'label': 'Check ' + str(number + 1), 'command': text})
        if sum(len(row['command']) for row in commands) > 8000:
            raise ValueError('Approved checks exceed the combined command limit')
        if len({row['id'] for row in commands}) != len(commands):
            raise ValueError('Check commands must be distinct')
        with self.lock:
            previous = self.check_plan(project_id)
            if previous['version'] != data['expected_version']:
                conflict()
            if any(task.get('project_id') == project_id and task['status'] in ACTIVE for task in self.tasks.values()):
                raise FileAccessError(409, 'Wait for project work to stop before changing its check plan')
            row = {'id': project_id, 'version': previous['version'] + 1, 'commands': commands, 'approved_at': self._delivery_now()}
            self.store.put('check_plan', row)
            self.check_plans[project_id] = row
            self.delivery_receipts.clear()
            return self.check_plan(project_id)

    @staticmethod
    def _delivery_now():
        from .conversation import timestamp
        return timestamp()

    def _delivery_policy_digest(self, bundle):
        return digest({'policy': bundle.metadata, 'roles': self.roles})

    def _delivery_policy(self):
        bundle = self.policy_provider.load()
        return self._delivery_policy_digest(bundle), bundle

    @staticmethod
    def _delivery_subject_stamp(task):
        return digest([task.get(key) for key in ('id', 'project_id', 'role', 'turn_id', 'status',
            'updated_at', 'recovery_hold', 'compliance_policy', 'compliance_role_digest')])

    def _delivery_subject(self, task_id):
        task = self.tasks.get(task_id)
        if task is None:
            raise FileAccessError(404, 'Task was not found')
        return task

    def _delivery_context(self, task):
        policy, _bundle = self._delivery_policy()
        project = self.projects[task['project_id']]
        snapshot = digest({'code': code_snapshot(project), 'policy': policy, 'task_id': task['id'], 'turn': task.get('turn_id')})
        return snapshot, policy

    def _delivery_operation_summary(self, operation):
        if not operation:
            return None
        runner = self.tasks.get(operation.get('task_id'), {})
        result = {key: operation.get(key) for key in ('id', 'task_id')}
        result['status'] = runner.get('status', 'unknown')
        if operation['kind'] == 'checks':
            result.update(passed_checks=len(operation.get('passed', [])), required_checks=len(operation['commands']))
        elif operation.get('decision_ack'):
            result['decision_ack'] = deepcopy(operation['decision_ack'])
        return result

    def _delivery_children_clear(self, task_ids):
        return not self.runtime_tracking_lost and not any(
            row.get('parent_task_id') in task_ids and
            (row.get('role') not in self.roles or row.get('status') in ACTIVE | {'unknown'})
            for row in self.observed_tasks.values())

    def _delivery_operation_current(self, operation, task, snapshot, policy, version):
        runner = self.tasks.get(operation.get('task_id'), {})
        return (operation.get('subject_id') == task['id'] and operation.get('subject_stamp') == self._delivery_subject_stamp(task)
            and operation.get('snapshot') == snapshot
            and operation.get('policy') == policy and operation.get('plan_version') == version
            and operation.get('generation') == self._recovery_connection_generation(self.client)
            and runner.get('delivery_context') == {'operation_id': operation['id'], 'subject_id': task['id'], 'kind': operation['kind']}
            and runner.get('project_id') == task['project_id']
            and runner.get('role') == ('qa_engineer' if operation['kind'] == 'checks' else 'code_quality_reviewer'))

    def _delivery_operations(self, task_id):
        records = [row for row in self.delivery_operations.values() if row.get('subject_id') == task_id]
        checks = next((row for row in reversed(records) if row['kind'] == 'checks'), None)
        reviews = next((row for row in reversed(records) if row['kind'] == 'review'), None)
        return checks, reviews

    def delivery_available(self, task):
        if not task.get('compliance_policy') or task.get('delivery_context'):
            return False
        return task.get('role') in {'backend_developer', 'frontend_developer'} or any(
            row.get('parent_task_id') == task['id']
            and row.get('role') in {None, 'backend_developer', 'frontend_developer'}
            for row in self.observed_tasks.values())

    def delivery(self, task_id):
        with self.lock:
            stamp = self._delivery_summary_stamp(self._delivery_subject(task_id))
        result = self._delivery_evaluate(task_id)
        with self.lock:
            task = self.tasks.get(task_id)
            if task is not None:
                self.delivery_summaries[task_id] = {'stamp': stamp, 'summary': {
                    'status': result['status'], 'checked_at': self._delivery_now(),
                    'freshness': 'historical', 'reason_codes': list(result['reason_codes'])}}
        return result

    def _delivery_evaluate(self, task_id):
        with self.lock:
            task = deepcopy(self._delivery_subject(task_id))
            plan = self.check_plan(task['project_id'])
            checks, review = self._delivery_operations(task_id)
            enforced = self.delivery_available(task)
        result = {'task_id': task_id, 'status': 'not_enforced', 'snapshot_digest': None, 'policy_digest': None,
            'plan_version': plan['version'], 'check_operation': self._delivery_operation_summary(checks),
            'review_operation': self._delivery_operation_summary(review), 'reason_codes': [],
            'actions': {'run_checks': False, 'start_review': False, 'review_decision': False}}
        if not enforced:
            return result
        try:
            snapshot, policy = self._delivery_context(task)
        except PolicyError:
            result.update(status='unverified', reason_codes=['approved_policy_unavailable'], policy_action=POLICY_ACTION)
            return result
        except (FileAccessError, OSError, ValueError):
            result.update(status='unverified', reason_codes=['current_snapshot_unavailable'])
            return result
        result.update(snapshot_digest=snapshot, policy_digest=policy, status='awaiting_checks')
        with self.lock:
            if self.tasks.get(task_id, {}).get('turn_id') != task.get('turn_id'):
                result.update(status='stale', reason_codes=['task_changed'])
                return result
            ids = {task_id, *(row['task_id'] for row in (checks, review) if row and row.get('task_id'))}
            if (task['status'] != 'completed' or task.get('recovery_hold') or not self._delivery_children_clear(ids)):
                result.update(status='unverified', reason_codes=['implementation_or_children_unresolved'])
                return result
            if not plan['commands']:
                result['reason_codes'] = ['check_plan_required']
                return result
            connected = bool(self.client and not self.client.closed and self.connection['status'] == 'connected')
            busy = any(self.tasks.get(row.get('task_id'), {}).get('status') in ACTIVE for row in (checks, review) if row)
            result['actions']['run_checks'] = connected and not busy
            if not checks:
                return result
            if not self._delivery_operation_current(checks, task, snapshot, policy, plan['version']):
                result.update(status='stale', reason_codes=['checks_stale'])
                return result
            check_task = self.tasks.get(checks['task_id'], {})
            if check_task.get('status') in ACTIVE:
                result.update(status='checks_running')
                return result
            if (check_task.get('status') != 'completed' or checks.get('failed')
                    or set(checks.get('passed', [])) != {row['id'] for row in checks['commands']}):
                result.update(status='checks_failed', reason_codes=['successful_native_checks_required'])
                return result
            result.update(status='awaiting_review')
            result['actions']['start_review'] = connected and not busy
            if not review or review.get('check_operation_id') != checks['id']:
                return result
            if not self._delivery_operation_current(review, task, snapshot, policy, plan['version']):
                result.update(status='stale', reason_codes=['review_stale'])
                return result
            review_task = self.tasks.get(review['task_id'], {})
            if review_task.get('status') in ACTIVE:
                result.update(status='review_running')
                return result
            if review_task.get('status') != 'completed' or review.get('failed'):
                result.update(status='changes_requested', reason_codes=['independent_review_required'])
                return result
            if not self._delivery_review_messages(review):
                result.update(status='unverified', reason_codes=['complete_review_messages_required'])
                return result
            result['actions']['review_decision'] = connected
            if review.get('decision') == 'accept':
                if review.get('decision_digest') == digest({'snapshot': snapshot, 'messages': digest(self._delivery_review_messages(review))}):
                    result['status'] = 'ready'
                else:
                    result.update(status='stale', reason_codes=['review_content_changed'])
            elif review.get('decision') == 'reject':
                result['status'] = 'changes_requested'
            return result

    def _delivery_start(self, task_id, data, kind):
        operation_id = data.get('operation_id') if isinstance(data, dict) else None
        if not isinstance(operation_id, str) or not re.fullmatch(r'[0-9a-f]{32}', operation_id):
            raise ValueError('Provide a fresh delivery operation identifier')
        with self.lock:
            if operation_id in self.delivery_inflight:
                raise FileAccessError(409, 'This delivery request is still being processed. Refresh before retrying.')
            self.delivery_inflight.add(operation_id)
        try:
            return self._delivery_start_reserved(task_id, data, kind)
        except (FileAccessError, ValueError, OSError, sqlite3.Error) as error:
            with self.lock:
                published = operation_id in self.delivery_operations or any(
                    (task.get('delivery_context') or {}).get('operation_id') == operation_id for task in self.tasks.values())
            if not published:
                raise DeliveryNotStarted(error) from None
            raise
        finally:
            with self.lock:
                self.delivery_inflight.discard(operation_id)

    def _delivery_start_reserved(self, task_id, data, kind):
        required = {'expected_snapshot', 'operation_id', 'confirmed'} | ({'expected_plan_version'} if kind == 'checks' else {'check_operation_id'})
        exact(data, required)
        if not isinstance(data['operation_id'], str) or not re.fullmatch(r'[0-9a-f]{32}', data['operation_id']):
            raise ValueError('Provide a fresh delivery operation identifier')
        payload_digest = digest(data)
        with self.lock:
            subject_stamp = self._delivery_subject_stamp(self._delivery_subject(task_id))
            old = self.delivery_operations.get(data['operation_id'])
            if old:
                if old.get('subject_id') != task_id or old.get('request_digest') != payload_digest or old['kind'] != kind:
                    conflict()
                replay = True
            else:
                replay = False
        if replay:
            return self.delivery(task_id)
        current = self.delivery(task_id)
        action = 'run_checks' if kind == 'checks' else 'start_review'
        if not current['actions'][action] or current['snapshot_digest'] != data['expected_snapshot']:
            conflict()
        if kind == 'checks' and (type(data['expected_plan_version']) is not int or current['plan_version'] != data['expected_plan_version']):
            conflict()
        if kind == 'review' and current['check_operation']['id'] != data['check_operation_id']:
            conflict()
        with self.lock:
            task = self._delivery_subject(task_id)
            plan = deepcopy(self.check_plans[task['project_id']])
            if (plan['version'] != current['plan_version']
                    or self._delivery_subject_stamp(task) != subject_stamp):
                conflict()
            if len(self.delivery_operations) >= MAX_OPERATIONS:
                raise FileAccessError(409, 'Delivery evidence storage requires owner maintenance')
            operation = {'id': data['operation_id'], 'subject_id': task_id, 'kind': kind,
                'snapshot': current['snapshot_digest'], 'policy': current['policy_digest'], 'plan_version': plan['version'],
                'subject_stamp': subject_stamp,
                'request_digest': payload_digest, 'generation': self._recovery_connection_generation(self.client),
                'created_at': self._delivery_now(), 'commands': plan['commands'] if kind == 'checks' else [],
                'passed': [], 'started_items': {}, 'failed': False, 'review_messages': [], 'review_expected': []}
            if kind == 'review':
                operation['check_operation_id'] = data['check_operation_id']
            role = 'qa_engineer' if kind == 'checks' else 'code_quality_reviewer'
            instruction = ('Run these exact human-approved check commands from the registered project root using normal sandbox and approval controls. Do not modify implementation or delegate. Report results.\n' + '\n'.join(row['command'] for row in plan['commands'])) if kind == 'checks' else (
                'Independently review the current project changes and the agreed task outcome. Do not edit implementation or delegate. Review correctness, safety, completeness and Ponytail simplicity. Report findings and limitations as visible messages. Human acceptance is separate.\nTask objective:\n' + self._delivery_task_objective(task_id))
            payload = {'project_id': task['project_id'], 'title': 'Delivery checks' if kind == 'checks' else 'Independent delivery review', 'instruction': instruction, 'role': role}
        self._start_task(payload, delivery_operation=operation)
        return self.delivery(task_id)

    def _delivery_validate_prepared(self, operation, bundle):
        subject = self.tasks.get(operation.get('subject_id'), {})
        plan = self.check_plans.get(subject.get('project_id'), {})
        if (subject.get('status') != 'completed' or subject.get('recovery_hold')
                or operation.get('subject_stamp') != self._delivery_subject_stamp(subject)
                or operation.get('plan_version') != plan.get('version')
                or operation.get('policy') != self._delivery_policy_digest(bundle)
                or operation.get('generation') != self._recovery_connection_generation(self.client)):
            conflict()
        if operation['kind'] == 'review':
            checks = self.delivery_operations.get(operation.get('check_operation_id'), {})
            runner = self.tasks.get(checks.get('task_id'), {})
            if (checks.get('subject_id') != subject['id'] or checks.get('snapshot') != operation['snapshot']
                    or checks.get('policy') != operation['policy'] or checks.get('plan_version') != operation['plan_version']
                    or checks.get('generation') != operation['generation'] or runner.get('status') != 'completed'
                    or runner.get('role') != 'qa_engineer' or checks.get('failed')
                    or set(checks.get('passed', [])) != {row['id'] for row in checks.get('commands', [])}):
                conflict()

    def _delivery_validate_operation(self, task):
        context = task.get('delivery_context')
        if not context:
            return
        operation = self.delivery_operations.get(context.get('operation_id'))
        if not operation or operation.get('task_id') != task['id']:
            conflict()
        subject = self.tasks.get(operation.get('subject_id'), {})
        plan = self.check_plans.get(subject.get('project_id'), {})
        if (operation.get('subject_stamp') != self._delivery_subject_stamp(subject)
                or operation.get('plan_version') != plan.get('version')
                or operation.get('generation') != self._recovery_connection_generation(self.client)
                or not self._delivery_children_clear({subject.get('id'), task['id']})):
            conflict()

    def _delivery_revalidate_snapshot(self, task):
        context = task.get('delivery_context')
        if not context:
            return
        with self.lock:
            self._delivery_validate_operation(task)
            operation = deepcopy(self.delivery_operations[context['operation_id']])
            subject = deepcopy(self.tasks[operation['subject_id']])
        snapshot, policy = self._delivery_context(subject)
        if snapshot != operation['snapshot'] or policy != operation['policy']:
            conflict()
        with self.lock:
            self._delivery_validate_operation(task)

    def _delivery_task_objective(self, task_id):
        task = self.tasks[task_id]
        rows = [row['text'] for row in self.messages if row['task_id'] == task_id and row['kind'] == 'user'
                and row.get('status') == 'sent' and row.get('turn_id') == task.get('turn_id')]
        text = '\n'.join(rows)
        if not text or len(text) > 24000:
            raise FileAccessError(409, 'Complete current task guidance is unavailable for independent review')
        return text

    def start_delivery_checks(self, task_id, data):
        self._require_active_provider_for(task_id)
        return self._delivery_start(task_id, data, 'checks')

    def start_delivery_review(self, task_id, data):
        self._require_active_provider_for(task_id)
        return self._delivery_start(task_id, data, 'review')

    def _save_delivery_operation(self, operation):
        try:
            self.store.put('delivery_operation', operation)
        except (sqlite3.Error, OSError):
            self.runtime_tracking_lost = True
            return False
        self.delivery_operations[operation['id']] = operation
        return True

    def _delivery_native_event(self, method, params):
        """Called under the state lock; never retain native output or unknown commands."""
        owned = self._owned(params.get('threadId'))
        if not owned or owned['parent'] is not None:
            return
        task = self.tasks.get(owned['task_id'], {})
        context = task.get('delivery_context')
        operation = deepcopy(self.delivery_operations.get(context.get('operation_id'))) if isinstance(context, dict) else None
        if not operation or operation.get('task_id') != task.get('id'):
            return
        item = params.get('item')
        if operation['kind'] == 'review':
            if (method == 'item/completed' and isinstance(item, dict) and item.get('type') == 'agentMessage'
                    and params.get('turnId') == owned.get('current_turn')
                    and params.get('turnId') == task.get('turn_id')):
                identifier = item.get('id')
                if not isinstance(identifier, str) or not IDENTIFIER.fullmatch(identifier):
                    operation['failed'] = True
                else:
                    key = hashlib.sha256((task['id'] + '\0' + '|'.join((params['threadId'], params['turnId'], identifier))).encode()).hexdigest()
                    if len(operation['review_expected']) >= 64 and key not in operation['review_expected']:
                        operation['failed'] = True
                    elif key not in operation['review_expected']:
                        operation['review_expected'].append(key)
                self._save_delivery_operation(operation)
            return
        if task.get('status') not in ACTIVE or not owned.get('active'):
            return
        item = params.get('item')
        turn = params.get('turnId')
        if (method not in {'item/started', 'item/completed'} or not isinstance(item, dict)
                or item.get('type') != 'commandExecution' or turn != owned.get('current_turn')
                or turn != task.get('turn_id') or turn not in owned['turns']):
            return
        identifier = item.get('id')
        if not isinstance(identifier, str) or not IDENTIFIER.fullmatch(identifier):
            return
        match = next((row for row in operation['commands'] if command_matches(item.get('command'), row['command'])), None)
        if not match or item.get('cwd') != self.projects[task['project_id']]['path']:
            return
        binding = [turn, match['id']]
        if method == 'item/started':
            if len(operation['started_items']) >= 128 and identifier not in operation['started_items']:
                operation['failed'] = True
            elif identifier in operation['started_items'] and operation['started_items'][identifier] != binding:
                operation['failed'] = True
            else:
                operation['started_items'][identifier] = binding
        elif operation['started_items'].get(identifier) == binding:
            if item.get('status') == 'completed' and type(item.get('exitCode')) is int and item['exitCode'] == 0:
                operation['passed'] = sorted(set(operation['passed']) | {match['id']})
            else:
                operation['failed'] = True
        self._save_delivery_operation(operation)

    def _delivery_review_unavailable(self, message):
        params = message.get('params', {}) if isinstance(message, dict) else {}
        item = params.get('item') if isinstance(params, dict) else None
        if isinstance(item, dict) and item.get('type') != 'agentMessage':
            return
        with self.lock:
            owned = self._owned(params.get('threadId'))
            task = self.tasks.get(owned['task_id'], {}) if owned and owned['parent'] is None else {}
            context = task.get('delivery_context') or {}
            operation = deepcopy(self.delivery_operations.get(context.get('operation_id')))
            if operation and operation['kind'] == 'review' and params.get('turnId') == task.get('turn_id'):
                operation['failed'] = True
                self._save_delivery_operation(operation)

    def _delivery_message(self, message):
        task = self.tasks.get(message['task_id'], {})
        context = task.get('delivery_context')
        operation = deepcopy(self.delivery_operations.get(context.get('operation_id'))) if isinstance(context, dict) else None
        if (not operation or operation['kind'] != 'review'
                or message.get('sender') != task.get('thread_id') or message.get('turn_id') != task.get('turn_id')):
            return
        if message['kind'] == 'system':
            operation['failed'] = True
        elif message['kind'] != 'agent':
            return
        elif len(operation['review_messages']) >= 64:
            operation['failed'] = True
        elif not any(row['id'] == message['id'] for row in operation['review_messages']):
            operation['review_messages'].append({'id': message['id'], 'digest': digest(message['text'])})
        self._save_delivery_operation(operation)

    def _delivery_review_messages(self, operation):
        ids = operation.get('review_messages', [])
        if (not ids or operation.get('failed')
                or set(operation.get('review_expected', [])) != {row['id'] for row in ids}):
            return []
        available = {row['id']: row for row in self.messages}
        result = []
        for item in ids:
            message = available.get(item['id'])
            if not message or digest(message['text']) != item['digest']:
                return []
            result.append({'id': message['id'], 'text': message['text']})
        return result

    def delivery_review(self, task_id, review_id):
        current = self.delivery(task_id)
        with self.lock:
            operation = self.delivery_operations.get(review_id)
            if (not operation or operation['kind'] != 'review' or operation['subject_id'] != task_id
                    or not current['actions']['review_decision'] or current['review_operation']['id'] != review_id):
                conflict()
            messages = self._delivery_review_messages(operation)
        encoded = json.dumps(messages, ensure_ascii=False).encode('utf-8')
        if not messages or len(encoded) > 128 * 1024:
            raise FileAccessError(409, 'Complete review content is unavailable')
        scan_preview(encoded)
        after = self.delivery(task_id)
        if after != current:
            conflict()
        review_digest = digest(messages)
        receipt = uuid.uuid4().hex
        with self.lock:
            latest = self.delivery_operations.get(review_id)
            if not latest or digest(self._delivery_review_messages(latest)) != review_digest:
                conflict()
            self.delivery_receipts = {key: row for key, row in self.delivery_receipts.items() if time.monotonic() - row['at'] <= 60}
            if len(self.delivery_receipts) >= 200:
                self.delivery_receipts.clear()
            self.delivery_receipts[receipt] = {'task_id': task_id, 'review_id': review_id,
                'snapshot': current['snapshot_digest'], 'digest': review_digest, 'at': time.monotonic()}
        return {'review_id': review_id, 'snapshot_digest': current['snapshot_digest'], 'review_digest': review_digest,
            'receipt_id': receipt, 'messages': messages, 'current': True}

    def delivery_review_decision(self, task_id, data):
        exact(data, {'review_id', 'receipt_id', 'review_digest', 'expected_snapshot', 'decision', 'confirmed'})
        if not isinstance(data['decision'], str) or data['decision'] not in {'accept', 'reject'}:
            raise ValueError('Choose an explicit review decision')
        current = self.delivery(task_id)
        with self.lock:
            receipt = self.delivery_receipts.pop(data['receipt_id'], None) if isinstance(data['receipt_id'], str) else None
            operation = deepcopy(self.delivery_operations.get(data['review_id'])) if isinstance(data['review_id'], str) else None
            if (not receipt or not operation or not current['actions']['review_decision']
                    or receipt['task_id'] != task_id or receipt['review_id'] != data['review_id']
                    or receipt['snapshot'] != current['snapshot_digest'] or data['expected_snapshot'] != current['snapshot_digest']
                    or receipt['digest'] != data['review_digest'] or time.monotonic() - receipt['at'] > 60
                    or current['review_operation']['id'] != data['review_id']
                    or digest(self._delivery_review_messages(operation)) != data['review_digest']):
                conflict()
            operation['decision'] = data['decision']
            operation['decision_ack'] = {key: data[key] for key in ('decision', 'receipt_id', 'review_digest', 'expected_snapshot')}
            operation['decision_digest'] = digest({'snapshot': current['snapshot_digest'], 'messages': data['review_digest']})
            if not self._save_delivery_operation(operation):
                raise FileAccessError(503, 'Review decision could not be saved; readiness remains unverified')
        return self.delivery(task_id)
