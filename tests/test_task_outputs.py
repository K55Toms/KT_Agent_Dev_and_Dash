"""Task output associations use disposable projects and synthetic native calls."""
from copy import deepcopy
import http.client
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import tempfile
import threading
import time
import unicodedata
import unittest
from unittest.mock import patch

from dashboard.project_files import FileAccessError, SensitiveContentError, preview_file
from dashboard.server import Dashboard, make_server
from dashboard.task_outputs import MAX_OUTPUTS, relative_candidates, verify_suggestions
from tests.dashboard_key_harness import make_test_server
from tests.policy_fixtures import SyntheticPolicy
from tests.test_claude_slice2b_baseline import FOLLOWUP, REPORT, Slice2bHarness, wait_for
from tests.test_delivery_backend import DeliveryFixture


class TaskOutputTests(DeliveryFixture):
    def attach(self, path='feature.py', **updates):
        return self.app.attach_task_output(self.subject['id'], {'path': path,
            'expected_turn_id': self.app.tasks[self.subject['id']]['turn_id'], 'confirmed': True, **updates})

    def output(self, identifier):
        return self.app.task_output(self.subject['id'], identifier)

    def test_attach_open_idempotence_persistence_and_metadata_only_state(self):
        row = self.attach()['output']
        self.assertEqual(row, self.attach()['output'])
        self.assertEqual('feature.py', row['title'])
        self.assertEqual('human', row['source'])
        status, result = self.output(row['id'])
        self.assertEqual(200, status)
        self.assertEqual('available', result['state'])
        self.assertIn('example', result['content'])
        with patch('dashboard.task_outputs.preview_file', side_effect=AssertionError('State must not read files')):
            task = next(row for row in self.app.snapshot()['tasks'] if row['id'] == self.subject['id'])
        self.assertEqual([row], task['outputs'])
        self.assertNotIn('content', str(task['outputs']))
        self.assertNotIn('sha256', task['outputs'][0])
        self.app.close()
        self.app = Dashboard(self.root / 'state', policy_provider=SyntheticPolicy())
        self.assertEqual(row, self.app.output_metadata(self.app.tasks[self.subject['id']])[0])
        self.assertEqual('available', self.output(row['id'])[1]['state'])

    def test_changed_missing_scanner_block_and_unavailable_never_return_content(self):
        row = self.attach()['output']
        (self.project_root / 'feature.py').write_text('print("updated report")\n')
        self.assertEqual('changed', self.output(row['id'])[1]['state'])
        self.assertNotIn('content', self.output(row['id'])[1])
        updated = self.attach()['output']
        self.assertNotEqual(row['id'], updated['id'])
        self.assertEqual('available', self.output(updated['id'])[1]['state'])
        for error, expected, state in [(SensitiveContentError(), 403, 'blocked'),
                                      (FileAccessError(503, 'synthetic scanner unavailable'), 503, 'unavailable')]:
            with patch('dashboard.project_files.scan_preview', side_effect=error):
                status, result = self.output(updated['id'])
            self.assertEqual((expected, state), (status, result['state']))
            self.assertNotIn('content', result)
        (self.project_root / 'feature.py').unlink()
        self.assertEqual((404, 'missing'), (self.output(updated['id'])[0], self.output(updated['id'])[1]['state']))

    def test_invalid_identity_paths_turn_confirmations_and_cross_task(self):
        row = self.attach()['output']
        for updates in ({'confirmed': 1}, {'extra': True}, {'expected_turn_id': 'old'}):
            with self.assertRaises((ValueError, FileAccessError)):
                self.attach(**updates)
        for path in ('../outside', '/etc/passwd', '.env', '.git/config', 'missing.md'):
            with self.assertRaises(FileAccessError):
                self.attach(path)
        other = deepcopy(self.app.tasks[self.subject['id']])
        other.update(id='a' * 32, outputs=[])
        self.app.tasks[other['id']] = other
        with self.assertRaises(FileAccessError):
            self.app.task_output(other['id'], row['id'])
        self.app.tasks[self.subject['id']]['turn_id'] = 'new-turn'
        self.assertEqual([], self.app.output_metadata(self.app.tasks[self.subject['id']]))
        with self.assertRaises(FileAccessError):
            self.output(row['id'])

    def test_context_changes_during_preview_and_storage_failure_do_not_publish(self):
        real = preview_file
        mutations = [lambda: self.app.tasks[self.subject['id']].update(turn_id='changed-turn'),
                     lambda: self.app.tasks[self.subject['id']].update(project_id='missing-project'),
                     lambda: self.app.projects[self.project['id']].update(name='changed-project')]
        for mutate in mutations:
            task, project = deepcopy(self.app.tasks[self.subject['id']]), deepcopy(self.app.projects[self.project['id']])
            def race(*args):
                result = real(*args)
                mutate()
                return result
            with patch('dashboard.task_outputs.preview_file', side_effect=race), self.assertRaises(FileAccessError):
                self.attach()
            self.app.tasks[self.subject['id']] = task
            self.app.projects[self.project['id']] = project
        with patch.object(self.app.store, 'put', side_effect=sqlite3.OperationalError('synthetic failure')):
            with self.assertRaises(FileAccessError) as error:
                self.attach()
        self.assertEqual(503, error.exception.status)
        self.assertEqual([], self.app.output_metadata(self.app.tasks[self.subject['id']]))

    def native(self, **updates):
        message = {'id': 800, 'method': 'item/tool/call', 'params': {'threadId': self.subject['thread_id'],
            'turnId': self.subject['turn_id'], 'tool': 'register_task_output', 'callId': 'output-call',
            'arguments': {'path': 'feature.py'}, **updates}}
        self.app._output_tool(message)
        return self.client.responses[-1][1]['success']

    def test_native_registration_positive_and_no_child_stale_limited_or_assessment_authority(self):
        task = self.app.tasks[self.subject['id']]
        task['status'] = 'running'
        owned = self.app._owned(task['thread_id'])
        owned['active'] = True
        self.assertTrue(self.native())
        self.assertEqual('native', self.app.output_metadata(self.app.tasks[task['id']])[0]['source'])
        for update in ({'turnId': 'stale'}, {'namespace': 'other'}, {'arguments': {'path': 'feature.py', 'task_id': task['id']}}):
            self.assertFalse(self.native(**update))
        for key, value in [('limited', True), ('parent', 'child-parent'), ('active', False), ('current_turn', 'old-turn')]:
            previous = owned.get(key)
            owned[key] = value
            self.assertFalse(self.native())
            owned[key] = previous
        for key, value in [('task_purpose', 'recovery_assessment'), ('delivery_context', {'kind': 'review'}),
                           ('recovery_stop_pending', True), ('recovery_hold', True)]:
            task = self.app.tasks[self.subject['id']]
            previous = task.get(key)
            task[key] = value
            self.assertFalse(self.native())
            if previous is None:
                task.pop(key)
            else:
                task[key] = previous
        self.app.resolved_requests.add(800)
        self.assertFalse(self.native())

    def test_dynamic_tool_is_advertised_and_dispatches_on_live_root(self):
        options = next(params for method, params in self.client.requests if method == 'thread/start')
        self.assertIn('register_task_output', {tool['name'] for tool in options['dynamicTools']})
        task = self.app.tasks[self.subject['id']]
        task['status'] = 'running'
        self.app._owned(task['thread_id'])['active'] = True
        self.app.on_message({'id': 801, 'method': 'item/tool/call', 'params': {
            'threadId': task['thread_id'], 'turnId': task['turn_id'], 'tool': 'register_task_output',
            'arguments': {'path': 'feature.py'}, 'callId': 'native-output-call'}})
        self.app.wait_conversations()
        self.assertTrue(self.client.responses[-1][1]['success'])
        for name in ('runtime_tracking_lost', 'runtime_requests_disabled'):
            setattr(self.app, name, True)
            self.assertFalse(self.native())
            setattr(self.app, name, False)
        self.app.connection['status'] = 'disconnected'
        self.assertFalse(self.native())

    def test_registration_rechecks_live_authority_and_directory_after_scan(self):
        task = self.app.tasks[self.subject['id']]
        task['status'] = 'running'
        owned = self.app._owned(task['thread_id'])
        owned['active'] = True
        def disconnect(*args):
            result = preview_file(*args)
            self.app.connection['status'] = 'disconnected'
            return result
        with patch('dashboard.task_outputs.preview_file', side_effect=disconnect):
            self.assertFalse(self.native())
        self.assertEqual([], self.app.output_metadata(task))
        self.app.connection['status'] = 'connected'
        def replace_root(*args):
            result = preview_file(*args)
            self.project_root.rename(self.root / 'previous-project')
            self.project_root.mkdir()
            return result
        with patch('dashboard.task_outputs.preview_file', side_effect=replace_root):
            self.assertFalse(self.native())
        self.assertEqual([], self.app.output_metadata(task))

    def test_file_mutation_replacement_parent_swap_and_hardlink_during_scan_block(self):
        path = self.project_root / 'feature.py'
        for mode in ('mutate', 'replace', 'hardlink'):
            path.write_text('safe original\n')
            def race(_data):
                if mode == 'mutate':
                    path.write_text('safe modified\n')
                elif mode == 'replace':
                    path.unlink()
                    path.write_text('safe replacement\n')
                else:
                    os.link(path, self.project_root / 'copy.py')
            with patch('dashboard.project_files.scan_preview', side_effect=race), self.assertRaises(FileAccessError):
                preview_file(self.project_root, 'feature.py')
            if (self.project_root / 'copy.py').exists():
                (self.project_root / 'copy.py').unlink()
        folder = self.project_root / 'reports'
        folder.mkdir()
        (folder / 'result.md').write_text('safe original\n')
        def swap(_data):
            folder.rename(self.project_root / 'previous-reports')
            folder.mkdir()
            (folder / 'result.md').write_text('safe replacement\n')
        with patch('dashboard.project_files.scan_preview', side_effect=swap), self.assertRaises(FileAccessError):
            preview_file(self.project_root, 'reports/result.md')

    def test_output_limit_and_scanner_failures_leave_no_phantom_associations(self):
        with patch('dashboard.task_outputs.scan_preview', side_effect=FileAccessError(503, 'unavailable')):
            with self.assertRaises(FileAccessError):
                self.attach()
        self.assertEqual([], self.app.output_metadata(self.app.tasks[self.subject['id']]))
        for index in range(8):
            path = f'report{index}.md'
            (self.project_root / path).write_text('safe report\n')
            self.attach(path)
        with self.assertRaises(FileAccessError) as error:
            self.attach()
        self.assertEqual(409, error.exception.status)

    def test_http_origin_exact_fields_and_read_only_open(self):
        server = make_test_server(self.app, 0)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        route = '/api/tasks/' + self.subject['id'] + '/outputs'
        def request(method, path, data=None, origin=True):
            connection = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=15)
            headers = {'Content-Type': 'application/json'}
            if origin:
                headers['Origin'] = 'http://127.0.0.1:' + str(server.server_port)
            connection.request(method, path, body=json.dumps(data) if data else None, headers=headers)
            response = connection.getresponse()
            result = response.status, json.loads(response.read())
            connection.close()
            return result
        data = {'path': 'feature.py', 'expected_turn_id': self.subject['turn_id'], 'confirmed': True}
        try:
            self.assertEqual(403, request('POST', route, data, origin=False)[0])
            self.assertEqual(400, request('POST', route, {**data, 'extra': True})[0])
            status, result = request('POST', route, data)
            self.assertEqual(200, status)
            self.assertEqual('available', request('GET', route + '/' + result['output']['id'])[1]['state'])
        finally:
            server.shutdown()
            server.server_close()
            worker.join(2)


class DeliverySummaryTests(DeliveryFixture):
    def test_summary_is_historical_cache_and_state_never_takes_snapshots(self):
        self.assertEqual('not_checked', self.app.delivery_summary(self.subject)['status'])
        detail = self.delivery()
        summary = self.app.delivery_summary(self.subject)
        self.assertEqual(detail['status'], summary['status'])
        self.assertEqual('historical', summary['freshness'])
        with patch('dashboard.delivery.code_snapshot', side_effect=AssertionError('No per-row snapshots')):
            state = self.app.snapshot()
        self.assertEqual(summary, state['tasks'][0]['delivery_summary'])
        self.plan()
        self.assertEqual('stale', self.app.delivery_summary(self.subject)['freshness'])
        self.delivery()
        self.app.connection['status'] = 'disconnected'
        self.assertEqual('stale', self.app.delivery_summary(self.subject)['freshness'])


REJECTED = "Request rejected. Check fields, connection, project and action availability."


class ClaudeOutputTests(Slice2bHarness):
    """Owner-attached outputs on completed Claude tasks (Plan 5 Task 5). Fake-binary evidence: the run is
    replayed by tests/fake_claude.py; nothing here shows how the real CLI behaves. Claude has no model-registered
    output tool, so every output is ``source: "human"``."""

    def raw_attach(self, task, path, turn=None, confirmed=True):
        return self.http("POST", f"/api/tasks/{task['id']}/outputs",
                         {"path": path, "expected_turn_id": task["turn_id"] if turn is None else turn,
                          "confirmed": confirmed})

    def persisted(self, task):
        rows = [row for row in self.app.store.load("task") if row["id"] == task["id"]]
        self.assertEqual(1, len(rows))
        return rows[0].get("outputs", [])

    def stored(self, task):
        return self.app.tasks[task["id"]].get("outputs", [])

    def test_owner_can_attach_output_to_completed_claude_task(self):
        task = self.finished_task()
        self.assertTrue(task["can_attach_output"])
        self.write_report()
        status, answer = self.attach(task)
        self.assertEqual(200, status, answer)
        self.assertEqual("human", answer["output"]["source"])
        self.assertEqual(task["turn_id"], answer["output"]["turn_id"])
        self.assertEqual(["human"], [row["source"] for row in self.stored(task)])
        again = self.attach(task)
        self.assertEqual(answer["output"]["id"], again[1]["output"]["id"])
        self.assertEqual(1, len(self.stored(task)))

    def test_attach_requires_explicit_confirmation(self):
        task = self.finished_task()
        self.write_report()
        for confirmed in (False, "true", 1):
            status, answer = self.raw_attach(task, REPORT, confirmed=confirmed)
            self.assertEqual(400, status, confirmed)
            self.assertEqual(REJECTED, answer["error"])
            self.assertEqual([], self.stored(task))
            self.assertEqual([], self.persisted(task))

    def test_output_refused_after_followup_started(self):
        task = self.finished_task()
        self.write_report()
        self.app.claude_env_extra = dict(FAKE_CLAUDE_FIXTURE="resumed", FAKE_CLAUDE_DELAY_MS="400")
        status, _ = self.http("POST", f"/api/tasks/{task['id']}/message",
                              {"text": FOLLOWUP, "expected_turn_id": task["turn_id"]})
        self.assertEqual(200, status)
        self.assertNotEqual("completed", self.task_state(task["id"])["status"])
        status, answer = self.attach(task)
        self.assertEqual(409, status, answer)
        self.assertEqual("Output task context changed; refresh before retrying", answer["error"])
        self.assertEqual([], self.stored(task))
        # The CURRENT (new) turn id while the follow-up still runs: refused by the status check.
        current = self.app.tasks[task["id"]]["turn_id"]
        self.assertNotEqual(task["turn_id"], current)
        self.assertNotEqual("completed", self.app.tasks[task["id"]]["status"])
        status, answer = self.raw_attach(task, REPORT, turn=current)
        self.assertEqual(409, status, answer)
        self.assertEqual("Only completed development tasks accept historical outputs", answer["error"])
        self.assertEqual([], self.stored(task))
        self.assertEqual([], self.persisted(task))
        self.wait_finished(task["id"])
        self.assertEqual([], self.stored(task))

    def test_output_on_turn_one_not_shown_as_turn_two_output(self):
        task = self.finished_task()
        self.write_report()
        self.assertEqual(200, self.attach(task)[0])
        after = self.followup(task)
        self.assertNotEqual(task["turn_id"], after["turn_id"])
        self.assertEqual([], after["outputs"])
        # The old turn id is stale now and cannot be attached to.
        status, _ = self.attach(task)
        self.assertEqual(409, status)
        # The new turn can take its own output, and only that one is listed.
        (self.project_dir / "second.md").write_text("# Second\n")
        status, answer = self.http("POST", f"/api/tasks/{task['id']}/outputs",
                                   {"path": "second.md", "expected_turn_id": after["turn_id"], "confirmed": True})
        self.assertEqual(200, status, answer)
        self.assertEqual(["second.md"], [o["path"] for o in self.task_state(task["id"])["outputs"]])

    def test_stale_expected_turn_refused(self):
        task = self.finished_task()
        self.write_report()
        for turn in ("not-the-turn", "0" * 32):
            status, _ = self.raw_attach(task, REPORT, turn=turn)
            self.assertEqual(409, status)
        status, _ = self.http("POST", f"/api/tasks/{task['id']}/outputs", {"path": REPORT, "confirmed": True})
        self.assertNotEqual(200, status)
        self.assertEqual([], self.stored(task))

    def test_path_escape_symlink_and_secret_file_refused_for_claude(self):
        task = self.finished_task()
        outside = self.root / "outside.md"
        outside.write_text("# Outside the project\n")
        (self.project_dir / "link.md").symlink_to(outside)
        (self.project_dir / "dirlink").symlink_to(self.root)
        # Deliberately nonfunctional credential-shaped value, built at run time (same shape as test_project_files).
        value = "synthetic" + "-nonfunctional-" + "fixture"
        secret_line = "api_" + "key = '" + value + "'\n"
        (self.project_dir / "notes.md").write_text(secret_line)
        (self.project_dir / ".env").write_text("SYNTHETIC_ENV_CONTENT=1\n")
        traversal = "Absolute paths and traversal are forbidden"
        forbidden = "Credential, runtime and build paths cannot be browsed"
        not_visible = "File is not a Git-visible source file"
        cases = [
            ("../outside.md", 400, traversal), ("/etc/hosts", 400, traversal), (str(outside), 400, traversal),
            ("a/../../outside.md", 400, traversal),
            ("link.md", 403, "Source file is unavailable or contains an unsafe link"),
            ("dirlink/outside.md", 404, not_visible), ("missing.md", 404, not_visible),
            (".env", 403, forbidden), (".git/config", 403, forbidden),
            ("notes.md", 403, "Preview blocked: sensitive-content findings. No content has been returned."),
        ]
        answers = []
        for path, expected_status, expected_error in cases:
            status, answer = self.raw_attach(task, path)
            answers.append(answer)
            self.assertEqual((expected_status, {"error": expected_error}), (status, answer), path)
            self.assertEqual([], self.stored(task), path)
            self.assertEqual([], self.persisted(task), path)
        # A clean file of the same size passes, so notes.md was refused by the scanner and for no other reason.
        (self.project_dir / "clean.md").write_text("x" * len(secret_line))
        self.assertEqual(len(secret_line), (self.project_dir / "clean.md").stat().st_size)
        status, answer = self.attach(task, "clean.md")
        self.assertEqual(200, status, answer)
        # Neither the secret nor the .env content appears in any answer, the state body or the store.
        everything = json.dumps(answers) + json.dumps(self.state()) + json.dumps(self.app.store.load("task"))
        for needle in (value, "SYNTHETIC_ENV_CONTENT"):
            self.assertNotIn(needle, everything)

    def test_non_completed_statuses_refuse_attach(self):
        task = self.finished_task()
        self.write_report()
        for status_name in ("failed", "interrupted", "unknown"):
            self.app.tasks[task["id"]]["status"] = status_name
            self.assertFalse(self.task_state(task["id"])["can_attach_output"], status_name)
            status, answer = self.attach(task)
            self.assertEqual(409, status, status_name)
            self.assertEqual("Only completed development tasks accept historical outputs", answer["error"])
            self.assertEqual([], self.stored(task))
            self.assertEqual([], self.persisted(task))

    def test_project_removed_or_identity_changed_refuses_attach(self):
        task = self.finished_task()
        self.write_report()
        project = self.app.projects[task["project_id"]]
        identity = dict(project["directory_identity"])
        project["directory_identity"] = {"device": identity["device"], "inode": identity["inode"] + 1}
        status, answer = self.attach(task)
        self.assertEqual((409, "Registered project directory changed"), (status, answer["error"]))
        project["directory_identity"] = identity
        project["directory_identity"] = None
        status, answer = self.attach(task)
        self.assertEqual((409, "Registered project identity is unavailable"), (status, answer["error"]))
        project["directory_identity"] = identity
        del self.app.projects[task["project_id"]]
        status, answer = self.attach(task)
        self.assertEqual((409, "Registered project identity is unavailable"), (status, answer["error"]))
        self.assertEqual([], self.stored(task))
        self.assertEqual([], self.persisted(task))

    def test_deleting_claude_task_removes_its_outputs(self):
        task = self.finished_task()
        self.write_report()
        status, answer = self.attach(task)
        self.assertEqual(200, status, answer)
        output_id = answer["output"]["id"]
        self.assertEqual(1, len(self.persisted(task)))
        task = self.task_state(task["id"])
        status, answer = self.http("POST", f"/api/tasks/{task['id']}/delete",
                                   {"expected_version": task["deletion_version"], "confirmed": True})
        self.assertEqual(200, status, answer)
        self.assertEqual([], [row for row in self.app.store.load("task") if row["id"] == task["id"]])
        self.assertNotIn(task["id"], self.app.tasks)
        self.assertNotIn(output_id, json.dumps(self.state()))
        status, _ = self.http("GET", f"/api/tasks/{task['id']}/outputs/{output_id}")
        self.assertEqual(404, status)

    def test_output_limit_for_a_claude_turn(self):
        task = self.finished_task()
        for index in range(MAX_OUTPUTS):
            (self.project_dir / f"r{index}.md").write_text(f"# Report {index}\n")
            status, answer = self.attach(task, f"r{index}.md")
            self.assertEqual(200, status, answer)
        self.assertEqual(MAX_OUTPUTS, len(self.task_state(task["id"])["outputs"]))
        (self.project_dir / "extra.md").write_text("# Extra\n")
        status, answer = self.attach(task, "extra.md")
        self.assertEqual((409, "This task turn already has eight registered outputs"), (status, answer["error"]))
        self.assertEqual(MAX_OUTPUTS, len(self.persisted(task)))
        # Re-attaching an already registered, unchanged report is idempotent even at the limit.
        self.assertEqual(200, self.attach(task, "r0.md")[0])
        self.assertEqual(MAX_OUTPUTS, len(self.persisted(task)))


class SuggestionPathTests(unittest.TestCase):
    """relative_candidates and verify_suggestions against a disposable Git project. Strings first, then descriptors,
    then Git visibility, then the path-only scan; nothing outside the project is ever opened."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir="/private/tmp")
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.root = self.base / "proj"
        self.root.mkdir()
        subprocess.run(["git", "init", "-q", str(self.root)], check=True, timeout=20)
        info = os.stat(self.root)
        self.project = {"path": str(self.root), "directory_identity": {"device": info.st_dev, "inode": info.st_ino}}

    def write(self, relative, text="# text\n"):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        return path

    def verify(self, *written, seconds=30):
        return verify_suggestions(self.project, relative_candidates(self.project["path"], list(written)),
                                  time.monotonic() + seconds)

    def raw(self, relative, tool="Write"):
        return (tool, f"{self.root}/{relative}")

    def test_strings_only_conversion_and_the_sibling_directory_trap(self):
        sibling = (self.base / "proj2")
        sibling.mkdir()
        (sibling / "x.md").write_text("x")
        outside = [("Write", f"{self.base}/proj2/x.md"), ("Write", "/etc/hosts"), ("Write", "docs/relative.md"),
                   ("Write", f"{self.root}/../outside.md"), ("Write", str(self.root)), ("Write", None)]
        self.assertEqual([("Write", "../outside.md")], [c for c in relative_candidates(str(self.root), outside)
                                                          if ".." in c[1]])  # kept as a string, refused by checked_path
        self.assertEqual([], self.verify(*outside))
        with patch("dashboard.task_outputs.os.stat", side_effect=AssertionError("no file system access")), \
                patch("dashboard.task_outputs.Path", side_effect=AssertionError("no file system access"), create=True):
            self.assertEqual([("Write", "a/b.md"), ("Edit", "c.md")],
                            relative_candidates(str(self.root), [self.raw("a/b.md"), self.raw("a/./b.md"), self.raw("c.md", "Edit")]))

    def test_good_files_pass_in_order_with_their_tool_and_duplicates_collapse(self):
        self.write("docs/report.md")
        self.write("src/app.py", "x = 1\n")
        self.assertEqual([{"path": "docs/report.md", "tool": "Write"}, {"path": "src/app.py", "tool": "Edit"}],
                         self.verify(self.raw("docs/report.md"), self.raw("src/app.py", "Edit"), self.raw("docs/report.md", "Edit")))

    def test_missing_directory_fifo_hardlink_symlink_credential_ignored_oversize_and_format_characters_are_dropped(self):
        self.write("ok.md")
        self.write("dir/inner.md")
        os.mkfifo(self.root / "pipe.md")
        self.write("hard_a.md")
        os.link(self.root / "hard_a.md", self.root / "hard_b.md")
        outside = self.base / "outside.md"
        outside.write_text("outside\n")
        os.symlink(outside, self.root / "link.md")
        os.symlink(self.root / "dir", self.root / "linkdir")
        self.write(".env", "TOKEN=x\n")
        self.write(".gitignore", "ignored.md\n")
        self.write("ignored.md")
        self.write("big.md", "x" * (256 * 1024 + 1))
        self.write("bidi‮.md")
        self.write("zero​width.md")
        names = ["missing.md", "dir", "pipe.md", "hard_a.md", "hard_b.md", "link.md", "linkdir/inner.md", ".env", "ignored.md",
                 "big.md", "bidi‮.md", "zero​width.md", "ok.md"]
        self.assertEqual([{"path": "ok.md", "tool": "Write"}], self.verify(*[self.raw(name) for name in names]))

    def test_case_and_normalization_variants_of_the_project_path_are_dropped_and_a_lone_surrogate_costs_nothing(self):
        self.write("a.md")
        upper = str(self.root).replace("/proj", "/PROJ")
        self.assertEqual([], self.verify(("Write", f"{upper}/a.md")))
        accented = self.base / "pr\u00f6j"  # composed spelling registered, decomposed spelling reported
        accented.mkdir()
        (accented / "b.md").write_text("# b\n")
        subprocess.run(["git", "init", "-q", str(accented)], check=True, timeout=20)
        info = os.stat(accented)
        project = {"path": str(accented), "directory_identity": {"device": info.st_dev, "inode": info.st_ino}}
        decomposed = unicodedata.normalize("NFD", str(accented))
        self.assertNotEqual(str(accented), decomposed)
        self.assertEqual([], verify_suggestions(project, relative_candidates(project["path"], [("Write", decomposed + "/b.md")]),
                                                time.monotonic() + 30))
        self.assertEqual([{"path": "b.md", "tool": "Write"}],
                         verify_suggestions(project, relative_candidates(project["path"], [("Write", str(accented) + "/b.md")]),
                                            time.monotonic() + 30))
        self.assertEqual([{"path": "a.md", "tool": "Write"}], self.verify(self.raw("\ud800.md"), self.raw("a.md")))

    def test_the_project_directory_replaced_after_registration_offers_nothing(self):
        self.write("ok.md")
        self.project["directory_identity"] = {"device": 1, "inode": 1}
        self.assertEqual([], self.verify(self.raw("ok.md")))

    def test_a_scanner_finding_drops_only_that_path_and_an_unavailable_scanner_drops_all(self):
        for name in ("a.md", "b.md", "c.md"):
            self.write(name)
        calls = []

        def finding_for_b(data):
            calls.append(data)
            if b"b.md" in data:
                raise SensitiveContentError()

        with patch("dashboard.task_outputs.scan_preview", side_effect=finding_for_b):
            result = self.verify(*[self.raw(name) for name in ("a.md", "b.md", "c.md")])
        self.assertEqual(["a.md", "c.md"], [row["path"] for row in result])
        self.assertEqual(4, len(calls))  # one batch, then one scan per path
        with patch("dashboard.task_outputs.scan_preview", side_effect=FileAccessError(503, "scanner path leak /secret")):
            self.assertEqual([], self.verify(self.raw("a.md")))

    def test_an_error_naming_the_path_is_swallowed_and_never_surfaces(self):
        self.write("a.md")
        boom = OSError(5, "boom", str(self.root / "a.md"))
        with patch("dashboard.task_outputs.source_descriptor", side_effect=boom):
            self.assertEqual([], self.verify(self.raw("a.md")))
        with patch("dashboard.task_outputs.git_visible_paths", side_effect=boom):
            self.assertEqual([], self.verify(self.raw("a.md")))
        with patch("dashboard.task_outputs.scan_preview", side_effect=boom):
            self.assertEqual([], self.verify(self.raw("a.md")))

    def test_at_most_eight_are_returned_and_the_budget_stops_the_slow_path(self):
        for index in range(12):
            self.write(f"f{index}.md")
        names = [self.raw(f"f{index}.md") for index in range(12)]
        self.assertEqual(8, len(self.verify(*names)))
        with patch("dashboard.task_outputs.scan_preview", side_effect=[SensitiveContentError()] + [None] * 20):
            slow = self.verify(*names, seconds=-1)  # the budget is spent before the first single scan
        self.assertEqual([], slow)


class SuggestionIntegrationTests(Slice2bHarness):
    """Fake-binary evidence: tests/fixtures/claude/write_edit.jsonl replays Write and Edit calls (shapes seen live
    on 2026-11-11) with paths inside, outside and beside the project. Nothing here shows the real CLI's behaviour."""

    def finished_with_suggestions(self, expect=True):
        (self.project_dir / "docs").mkdir()
        (self.project_dir / "docs" / "report.md").write_text("# Report\n")
        (self.project_dir / "src").mkdir()
        (self.project_dir / "src" / "app.py").write_text("x = 1\n")
        (self.project_dir / "sub.txt").write_text("sub\n")
        task = self.finished_task("write_edit")
        if expect:
            self.assertTrue(wait_for(lambda: self.task_state(task["id"])["output_suggestions"], 10), "no suggestions arrived")
        return self.task_state(task["id"])

    def test_a_run_that_wrote_and_edited_files_offers_only_project_files_chosen_by_the_main_session(self):
        task = self.finished_with_suggestions()
        self.assertEqual([{"path": "docs/report.md", "tool": "Write"}, {"path": "src/app.py", "tool": "Edit"}],
                         task["output_suggestions"])
        self.assertNotIn("output_suggestions", task["claude"])  # the raw list never leaves the server
        self.assertNotIn("SENSITIVE_TOOL_INPUT_MARKER", json.dumps(self.state()))
        self.assertEqual([], task["outputs"])  # nothing is attached automatically
        self.assertTrue(task["can_attach_output"])

    def test_an_attached_suggestion_disappears_from_the_list_and_survives_a_restart_until_then(self):
        task = self.finished_with_suggestions()
        status, answer = self.attach(task, "docs/report.md")
        self.assertEqual(200, status, answer)
        self.assertEqual([{"path": "src/app.py", "tool": "Edit"}], self.task_state(task["id"])["output_suggestions"])
        rows = [row for row in self.app.store.load("task") if row["id"] == task["id"]]
        self.assertEqual(2, len(rows[0]["claude"]["output_suggestions"]))  # stored with turn id, filtered when shown

    def test_other_turns_and_non_completed_tasks_show_no_suggestions(self):
        task = self.finished_with_suggestions()
        with self.app.lock:
            self.app.tasks[task["id"]]["turn_id"] = "turn-9"
        self.assertEqual([], self.task_state(task["id"])["output_suggestions"])
        with self.app.lock:
            self.app.tasks[task["id"]]["turn_id"] = task["turn_id"]
            self.app.tasks[task["id"]]["status"] = "failed"
        self.assertEqual([], self.task_state(task["id"])["output_suggestions"])

    def spy_on_suggestions(self):
        done = threading.Event()
        original = self.app._claude_output_suggestions

        def wrapper(task_id, state):
            try:
                return original(task_id, state)
            finally:
                done.set()

        self.app._claude_output_suggestions = wrapper  # the exit handler looks the method up on the instance
        return done

    def test_a_run_without_write_or_edit_calls_has_none(self):
        done = self.spy_on_suggestions()
        with patch("dashboard.task_outputs.verify_suggestions", side_effect=AssertionError("nothing to verify")):
            task = self.finished_task("success")
            self.assertTrue(done.wait(10), "the exit handler never reached the suggestion step")
        self.assertEqual([], self.task_state(task["id"])["output_suggestions"])

    def test_an_error_naming_the_path_never_reaches_state_diagnostics_or_logs(self):
        done = self.spy_on_suggestions()
        (self.project_dir / "docs").mkdir()
        (self.project_dir / "docs" / "report.md").write_text("# Report\n")
        leak = OSError(5, "SECRET_BOOM", str(self.project_dir / "docs" / "report.md"))
        with self.assertNoLogs(level="DEBUG"), patch("dashboard.task_outputs.source_descriptor", side_effect=leak):
            task = self.finished_task("write_edit")
            self.assertTrue(done.wait(10))
        shown = json.dumps(self.state()) + json.dumps(self.app.tasks[task["id"]], default=str)
        for text in ("SECRET_BOOM", "docs/report.md"):
            self.assertNotIn(text, shown)
        self.assertEqual([], self.task_state(task["id"])["output_suggestions"])

    def test_a_task_that_changed_during_the_scan_stores_nothing(self):
        done = self.spy_on_suggestions()
        (self.project_dir / "docs").mkdir()
        (self.project_dir / "docs" / "report.md").write_text("# Report\n")

        def change_the_task(data):
            with self.app.lock:
                for row in self.app.tasks.values():
                    row["revision"] = row.get("revision", 0) + 1  # any change of the stamped fields, as another request would make

        with patch("dashboard.task_outputs.scan_preview", side_effect=change_the_task):
            task = self.finished_task("write_edit")
            self.assertTrue(done.wait(10))
        self.assertEqual([], self.task_state(task["id"])["output_suggestions"])
        self.assertNotIn("output_suggestions", self.app.tasks[task["id"]]["claude"])

    def test_the_paths_are_scanned_outside_the_dashboard_lock(self):
        owned = []

        def probe(data):
            owned.append(self.app.lock._is_owned())  # is the scanning thread itself inside self.lock?

        (self.project_dir / "docs").mkdir()
        (self.project_dir / "docs" / "report.md").write_text("# Report\n")
        with patch("dashboard.task_outputs.scan_preview", side_effect=probe):
            task = self.finished_task("write_edit")
            self.assertTrue(wait_for(lambda: owned, 10), "the scan was never reached")
        self.assertEqual({False}, set(owned))
        self.assertTrue(task["can_attach_output"])
