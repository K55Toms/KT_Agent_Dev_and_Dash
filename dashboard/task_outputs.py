"""Explicit task/turn associations to scanner-checked project text outputs."""
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import os
from pathlib import PurePosixPath
import re
import sqlite3
import time
import unicodedata
import uuid

from .project_files import (MAX_FILE_BYTES, FileAccessError, checked_path, git_visible_paths, preview_file, root_descriptor,
                            scan_preview, source_descriptor)

MAX_OUTPUTS = 8
MAX_SUGGESTIONS = MAX_OUTPUTS
SUGGESTION_SECONDS = 15.0  # total scan budget per run; one scan can overrun it by its own timeout
# Bidi, zero-width and similar format characters, and line or paragraph separators: a path with one can look like another.
UNSAFE_CATEGORIES = frozenset({'Cf', 'Zl', 'Zp'})
OUTPUT_TOOL = {'type': 'function', 'name': 'register_task_output',
    'description': 'Register a report or other text deliverable produced for this task and current turn. Provide its project-relative path. Registration does not accept delivery or authorize release.',
    'inputSchema': {'type': 'object', 'additionalProperties': False, 'required': ['path'],
                    'properties': {'path': {'type': 'string', 'minLength': 1, 'maxLength': 4096}}}}


def metadata(row):
    return {**{key: row[key] for key in ('id', 'path', 'turn_id', 'registered_at', 'source')},
            'title': PurePosixPath(row['path']).name}


def relative_candidates(project_path, written):
    """String logic only: (tool, raw path) pairs to distinct project-relative candidates. No file system access.

    PurePosixPath.relative_to compares whole path parts, so a sibling directory such as /proj2 is not inside /proj.
    A raw path that is relative, outside the registered path as written, or that spells a ``..`` part is dropped."""
    base = PurePosixPath(project_path)
    seen, result = set(), []
    for tool, raw in written:
        try:
            relative = PurePosixPath(raw).relative_to(base).as_posix()
        except (ValueError, TypeError):
            continue
        if relative in seen:
            continue
        seen.add(relative)
        result.append((tool, relative))
    return result


def verify_suggestions(project, candidates, deadline):
    """Check candidates against the project without reading content; at most MAX_SUGGESTIONS {'path', 'tool'} rows.

    Order: checked_path and character rules (strings), then descriptors (no symlinks, regular file, one link, within
    the preview size), then Git visibility, then the path-only secret scan (one batch; one by one only if the batch is
    refused). The content is scanned again when the owner attaches the file. Any failure drops candidates silently:
    no error text, count or path is kept. Call it without holding the dashboard lock."""
    staged = []
    for tool, relative in candidates:
        try:
            parts = checked_path(relative)
        except FileAccessError:
            continue
        if any(unicodedata.category(char) in UNSAFE_CATEGORIES for char in relative):
            continue
        staged.append((tool, relative, parts))
    opened = []
    try:
        with root_descriptor(project['path']) as root_fd:
            info = os.fstat(root_fd)
            if project.get('directory_identity') != {'device': info.st_dev, 'inode': info.st_ino}:
                return []
            for tool, relative, parts in staged:
                try:
                    with source_descriptor(root_fd, parts) as (_descriptor, file_info):
                        if file_info.st_size > MAX_FILE_BYTES:
                            continue
                except Exception:  # noqa: BLE001 - never carries or logs the path
                    continue
                opened.append((tool, relative))
        visible = git_visible_paths(project['path'], [relative for _tool, relative in opened])
    except Exception:  # noqa: BLE001
        return []
    opened = [(tool, relative) for tool, relative in opened if relative in visible]
    if not opened:
        return []
    try:
        scan_preview('\n'.join(relative for _tool, relative in opened).encode('utf-8'))
        clean = opened
    except FileAccessError as error:
        if error.status != 403:  # the scanner could not run: nothing is offered
            return []
        clean = []
        for tool, relative in opened:
            if time.monotonic() > deadline or len(clean) >= MAX_SUGGESTIONS:
                break
            try:
                scan_preview(relative.encode('utf-8'))
            except Exception:  # noqa: BLE001 - a finding or a scanner problem: drop this path only
                continue
            clean.append((tool, relative))
    except Exception:  # noqa: BLE001
        return []
    return [{'path': relative, 'tool': tool} for tool, relative in clean[:MAX_SUGGESTIONS]]


class TaskOutputsMixin:
    def output_metadata(self, task):
        result = []
        rows = task.get('outputs', [])
        for row in (rows if isinstance(rows, list) else [])[:MAX_OUTPUTS]:
            try:
                if (not isinstance(row, dict) or row.get('turn_id') != task.get('turn_id')
                        or not isinstance(row.get('id'), str) or not re.fullmatch('[0-9a-f]{32}', row['id'])
                        or not isinstance(row.get('sha256'), str) or not re.fullmatch('[0-9a-f]{64}', row['sha256'])
                        or row.get('source') not in {'native', 'human'}
                        or not isinstance(row.get('registered_at'), str) or len(row['registered_at']) > 50):
                    continue
                checked_path(row['path'])
                result.append(metadata(row))
            except (KeyError, TypeError, FileAccessError):
                continue
        return result

    def suggestion_metadata(self, task):
        """Strings only, no file system access (the snapshot calls it under the dashboard lock)."""
        record = task.get('claude') if isinstance(task.get('claude'), dict) else {}
        rows = record.get('output_suggestions')
        if task.get('provider') != 'claude' or not isinstance(rows, list) or not self.can_attach_output(task):
            return []
        attached = {row.get('path') for row in task.get('outputs', []) if isinstance(row, dict)
                    and row.get('turn_id') == task.get('turn_id')}
        result = []
        for row in rows[:MAX_SUGGESTIONS]:
            try:
                if (isinstance(row, dict) and row.get('turn_id') == task.get('turn_id') and row.get('tool') in {'Write', 'Edit'}
                        and row.get('path') not in attached):
                    checked_path(row['path'])
                    result.append({'path': row['path'], 'tool': row['tool']})
            except (KeyError, TypeError, FileAccessError):
                continue
        return result

    def _claude_output_suggestions(self, task_id, state):
        """After a Claude run ended, outside self.lock; never raises. Keeps only project-relative paths."""
        try:
            written = list(getattr(state, 'written_paths', None) or [])
            if not written:
                return
            with self.lock:
                task = self.tasks.get(task_id)
                if task is None or task.get('provider') != 'claude' or not self.can_attach_output(task):
                    return
                turn_id = task['turn_id']
                project, stamp = self._output_context(task_id, turn_id)
            accepted = verify_suggestions(project, relative_candidates(project['path'], written),
                                          time.monotonic() + SUGGESTION_SECONDS)
            if not accepted:
                return
            with self.lock:
                fresh_project, fresh_stamp = self._output_context(task_id, turn_id)
                if project != fresh_project or stamp != fresh_stamp:
                    return
                candidate = deepcopy(self.tasks[task_id])
                record = candidate.get('claude')
                if not isinstance(record, dict):
                    return
                record['output_suggestions'] = [{**row, 'turn_id': turn_id} for row in accepted]
                try:
                    self.store.put('task', candidate)
                except (sqlite3.Error, OSError):
                    return
                self.tasks[task_id] = candidate
        except Exception:  # noqa: BLE001 - nothing here may reach the exit handler's thread, a log or a notice
            return

    @staticmethod
    def can_attach_output(task):
        return bool(task.get('status') == 'completed' and task.get('turn_id')
                    and task.get('task_purpose', 'development') == 'development'
                    and not task.get('delivery_context') and not task.get('recovery_hold')
                    and not task.get('recovery_stop_pending'))

    def _output_context(self, task_id, expected_turn, native=None):
        task = self.tasks.get(task_id)
        if task is None:
            raise FileAccessError(404, 'Task was not found')
        if (not isinstance(expected_turn, str) or task.get('turn_id') != expected_turn
                or task.get('task_purpose', 'development') != 'development'
                or task.get('delivery_context') or task.get('recovery_hold') or task.get('recovery_stop_pending')):
            raise FileAccessError(409, 'Output task context changed; refresh before retrying')
        if native is None:
            if not self.can_attach_output(task):
                raise FileAccessError(409, 'Only completed development tasks accept historical outputs')
        else:
            thread_id, client, rpc_id = native
            owned = self._owned(thread_id)
            if (not client or client.closed or self.client is not client or self.connection['status'] != 'connected'
                    or rpc_id in self.resolved_requests or not owned or owned.get('parent') is not None
                    or owned.get('task_id') != task_id or task.get('thread_id') != thread_id
                    or owned.get('current_turn') != expected_turn or expected_turn not in owned.get('turns', set())
                    or not self._question_live({'thread_id': thread_id, 'turn_id': expected_turn})):
                raise FileAccessError(409, 'Output registration requires the live owned task turn')
        project = self.projects.get(task.get('project_id'))
        if not project or not isinstance(project.get('directory_identity'), dict):
            raise FileAccessError(409, 'Registered project identity is unavailable')
        with root_descriptor(project['path']) as descriptor:
            info = os.fstat(descriptor)
            if project['directory_identity'] != {'device': info.st_dev, 'inode': info.st_ino}:
                raise FileAccessError(409, 'Registered project directory changed')
        stamp = {key: deepcopy(task.get(key)) for key in ('id', 'project_id', 'thread_id', 'turn_id',
            'status', 'revision', 'task_purpose', 'recovery_hold', 'recovery_stop_pending', 'delivery_context')}
        return deepcopy(project), stamp

    def _register_output(self, task_id, path, expected_turn, native=None):
        checked_path(path)
        with self.lock:
            project, stamp = self._output_context(task_id, expected_turn, native)
        scan_preview(path.encode('utf-8'))
        preview = preview_file(project['path'], path)
        checksum = hashlib.sha256(preview['content'].encode('utf-8')).hexdigest()
        with self.lock:
            fresh_project, fresh_stamp = self._output_context(task_id, expected_turn, native)
            if project != fresh_project or stamp != fresh_stamp:
                raise FileAccessError(409, 'Output task context changed during review')
            task = self.tasks[task_id]
            rows = [row for row in task.get('outputs', []) if row.get('turn_id') == expected_turn]
            for row in rows:
                if row.get('path') == path and row.get('sha256') == checksum:
                    return {'task_id': task_id, 'output': metadata(row)}
            if len(rows) >= MAX_OUTPUTS:
                raise FileAccessError(409, 'This task turn already has eight registered outputs')
            row = {'id': uuid.uuid4().hex, 'path': path, 'turn_id': expected_turn,
                   'registered_at': datetime.now(timezone.utc).isoformat(), 'sha256': checksum,
                   'source': 'native' if native else 'human'}
            candidate = deepcopy(task)
            candidate['outputs'] = [*rows, row]
            try:
                self.store.put('task', candidate)
            except (sqlite3.Error, OSError):
                raise FileAccessError(503, 'Output association could not be saved') from None
            self.tasks[task_id] = candidate
            return {'task_id': task_id, 'output': metadata(row)}

    def attach_task_output(self, task_id, data):
        if not isinstance(data, dict) or set(data) != {'path', 'expected_turn_id', 'confirmed'} or data['confirmed'] is not True:
            raise ValueError('Explicit output association confirmation is required')
        return self._register_output(task_id, data['path'], data['expected_turn_id'])

    def task_output(self, task_id, output_id):
        with self.lock:
            task = self.tasks.get(task_id)
            if task is None:
                raise FileAccessError(404, 'Task was not found')
            row = next((entry for entry in self.output_metadata(task) if entry['id'] == output_id), None)
            if row is None:
                raise FileAccessError(404, 'Registered output was not found for this task turn')
            original = next(entry for entry in task['outputs'] if entry['id'] == output_id)
            expected_hash = original['sha256']
            project, stamp = self._output_read_context(task)
        try:
            preview = preview_file(project['path'], row['path'])
        except FileAccessError as error:
            state = 'missing' if error.status == 404 else 'unavailable' if error.status >= 500 else 'blocked'
            return error.status, {'task_id': task_id, **row, 'state': state,
                                  'error': {'missing': 'Registered output is missing.', 'unavailable': 'Output checks are unavailable.',
                                            'blocked': 'Output preview is blocked.'}[state]}
        with self.lock:
            current = self.tasks.get(task_id)
            if current is None or self._output_read_context(current) != (project, stamp):
                raise FileAccessError(409, 'Output task context changed during review')
        if hashlib.sha256(preview['content'].encode('utf-8')).hexdigest() != expected_hash:
            return 200, {'task_id': task_id, **row, 'state': 'changed'}
        return 200, {'task_id': task_id, **row, **preview, 'state': 'available'}

    def _output_read_context(self, task):
        project = self.projects.get(task.get('project_id'))
        if not project or not isinstance(project.get('directory_identity'), dict):
            raise FileAccessError(409, 'Registered project identity is unavailable')
        with root_descriptor(project['path']) as descriptor:
            info = os.fstat(descriptor)
            if project['directory_identity'] != {'device': info.st_dev, 'inode': info.st_ino}:
                raise FileAccessError(409, 'Registered project directory changed')
        return deepcopy(project), (task['id'], task.get('project_id'), task.get('turn_id'), deepcopy(task.get('outputs')))

    def _output_tool(self, message):
        params = message['params']
        success = False
        with self.lock:
            client = self.client
            owned = self._owned(params.get('threadId'))
            task_id = owned.get('task_id') if owned else None
        try:
            args = params.get('arguments')
            if (params.get('tool') != 'register_task_output' or params.get('namespace') not in {None, ''}
                    or not isinstance(args, dict) or set(args) != {'path'}):
                raise ValueError('Invalid output registration')
            self._register_output(task_id, args['path'], params.get('turnId'), (params.get('threadId'), client, message['id']))
            success = True
        except (ValueError, FileAccessError, OSError):
            pass
        if client and not client.closed:
            client.respond(message['id'], {'contentItems': [{'type': 'inputText', 'text':
                'Output registered for this task turn.' if success else 'Output registration unavailable: task authority, project path, content checks or storage did not pass.'}], 'success': success})
