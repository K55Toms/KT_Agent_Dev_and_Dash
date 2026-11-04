"""Plan 5 Task 7: delivery readiness for Claude runs, without the Ponytail gate.

Evidence kind: fake-binary evidence, not a live run. Delivery runs execute tests/fake_claude.py replaying synthetic
fixtures (delivery_checks_*.jsonl, delivery_review.jsonl, each with its own session id) through the real argv builder,
ClaudeRun and HTTP handler. Nothing here shows how the real CLI reports a Bash exit status.

Owner answer 4: a Claude run can reach ``ready`` when every other gate passes; the Ponytail row reads "Not applicable
for Claude" and is never counted as passed. Codex behaviour is pinned by the unedited Codex delivery tests.
"""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
import uuid

from dashboard.backends.claude_stream import StreamState, translate_stream_line
from dashboard.delivery import digest
from dashboard.ponytail_policy import (NOT_APPLICABLE_METADATA, NotApplicablePolicy, PolicyError, PonytailPolicy,
                                       policy_instructions)
from dashboard.server import Dashboard
from tests.test_claude_slice2b_baseline import Slice2bHarness, wait_for

CHECK = "python3 -m unittest"
PONYTAIL_SHAPE = {"name": "ponytail", "mode": "full", "version": "5.3.2", "sha256": "9" * 64}


class RaisingPolicy:
    def __init__(self):
        self.calls = 0

    def load(self):
        self.calls += 1
        raise PolicyError("Approved Ponytail policy configuration is invalid.")


class ClaudeDeliveryHarness(Slice2bHarness):
    def setUp(self):
        super().setUp()
        self.record = self.root / "record.jsonl"

    def use(self, fixture):
        # A new dict per run (never mutated in place); callers wait for each run to finish before the next use().
        self.app.claude_env_extra = dict(FAKE_CLAUDE_FIXTURE=fixture, FAKE_CLAUDE_RECORD=str(self.record))

    def last_argv(self):
        lines = [json.loads(line) for line in self.record.read_text().splitlines() if line.strip()]
        return [entry for entry in lines if "argv" in entry][-1]

    def delivery(self, task_id):
        status, body = self.http("GET", f"/api/tasks/{task_id}/delivery")
        self.assertEqual(200, status, body)
        return body

    def approve_plan(self, project_id, commands=(CHECK,)):
        status, plan = self.http("GET", f"/api/projects/{project_id}/check-plan")
        self.assertEqual(200, status, plan)
        status, plan = self.http("POST", f"/api/projects/{project_id}/check-plan",
                                 {"expected_version": plan["version"], "commands": list(commands), "confirmed": True})
        self.assertEqual(200, status, plan)
        return plan

    def subject(self):
        task = self.finished_task()
        self.assertEqual("completed", task["status"])
        self.approve_plan(task["project_id"])
        return task

    def run_checks(self, task, fixture="delivery_checks_pass"):
        current = self.delivery(task["id"])
        self.assertTrue(current["actions"]["run_checks"], current)
        self.use(fixture)
        status, answer = self.http("POST", f"/api/tasks/{task['id']}/delivery/checks", {
            "expected_snapshot": current["snapshot_digest"], "expected_plan_version": current["plan_version"],
            "operation_id": uuid.uuid4().hex, "confirmed": True})
        self.assertEqual(200, status, answer)
        runner = answer["check_operation"]["task_id"]
        self.wait_finished(runner)
        return runner, self.delivery(task["id"])

    def run_review(self, task, fixture="delivery_review"):
        current = self.delivery(task["id"])
        self.assertTrue(current["actions"]["start_review"], current)
        self.use(fixture)
        status, answer = self.http("POST", f"/api/tasks/{task['id']}/delivery/reviews", {
            "expected_snapshot": current["snapshot_digest"], "check_operation_id": current["check_operation"]["id"],
            "operation_id": uuid.uuid4().hex, "confirmed": True})
        self.assertEqual(200, status, answer)
        runner = answer["review_operation"]["task_id"]
        self.wait_finished(runner)
        return runner, self.delivery(task["id"])

    def accept(self, task):
        current = self.delivery(task["id"])
        self.assertTrue(current["actions"]["review_decision"], current)
        review_id = current["review_operation"]["id"]
        status, preview = self.http("GET", f"/api/tasks/{task['id']}/delivery/reviews/{review_id}")
        self.assertEqual(200, status, preview)
        status, answer = self.http("POST", f"/api/tasks/{task['id']}/delivery/review-decision", {
            "review_id": review_id, "receipt_id": preview["receipt_id"], "review_digest": preview["review_digest"],
            "expected_snapshot": preview["snapshot_digest"], "decision": "accept", "confirmed": True})
        self.assertEqual(200, status, answer)
        return answer

    def ready_subject(self):
        task = self.subject()
        self.run_checks(task)
        self.run_review(task)
        result = self.accept(task)
        self.assertEqual("ready", result["status"], result)
        return task, result

    def add_child(self, task_id, role, status):
        key = uuid.uuid4().hex
        with self.app.lock:
            self.app.observed_tasks[key] = {"id": key, "parent_task_id": task_id, "project_id": self.app.tasks[task_id]["project_id"],
                                            "thread_id": "agent-" + key[:8], "parent_thread_id": "s", "role": role,
                                            "title": "Unattributed delegated task", "status": status,
                                            "created_at": "2026-11-04T00:00:00+00:00", "updated_at": "2026-11-04T00:00:00+00:00"}
        return key


class ClaudeDeliveryTests(ClaudeDeliveryHarness):
    def test_not_applicable_policy_never_counts_as_passed(self):
        bundle = NotApplicablePolicy().load()
        self.assertEqual({"provider": "claude", "ponytail": "not_applicable"}, bundle.metadata)
        self.assertEqual((None, None, ""), (bundle.version, bundle.digest, bundle.text))
        # The Claude deployment's source is the not-applicable policy, never the injected Codex-shaped one.
        self.assertIsInstance(self.app.policy_provider, NotApplicablePolicy)
        task = self.subject()
        self.assertEqual(NOT_APPLICABLE_METADATA, self.app.tasks[task["id"]]["compliance_policy"])
        result = self.delivery(task["id"])
        self.assertEqual("not_applicable", result["ponytail"])
        # Nothing but the other gates moves the status: no checks yet means awaiting checks, never ready or passed.
        self.assertEqual("awaiting_checks", result["status"])
        self.assertEqual({"run_checks": True, "start_review": False, "review_decision": False}, result["actions"])
        self.assertIsNone(result["check_operation"])
        # Checks alone are not enough either: the review gate still has to pass.
        self.run_checks(task)
        self.assertEqual("awaiting_review", self.delivery(task["id"])["status"])
        # The not-applicable bundle never adds Ponytail text to a role prompt.
        self.assertEqual("x", policy_instructions("qa_engineer", "x", bundle))

    def test_claude_task_ready_when_all_other_gates_pass(self):
        task, result = self.ready_subject()
        self.assertEqual("not_applicable", result["ponytail"])
        self.assertEqual([], result["reason_codes"])
        self.assertEqual((1, 1), (result["check_operation"]["passed_checks"], result["check_operation"]["required_checks"]))
        # Ready is recorded in the task list summary too.
        shown = self.task_state(task["id"])
        self.assertTrue(shown["delivery_available"])
        self.assertEqual("ready", shown["delivery_summary"]["status"])

    def test_claude_checks_run_starts_qa_engineer_run_in_project(self):
        task = self.subject()
        runner_id, result = self.run_checks(task)
        record = self.last_argv()
        argv = record["argv"]
        self.assertEqual("qa_engineer", argv[argv.index("--agent") + 1])
        self.assertEqual(str(self.project_dir), str(Path(record["cwd"]).resolve()))
        runner = self.app.tasks[runner_id]
        self.assertEqual(("claude", "qa_engineer", "completed", task["project_id"]),
                         (runner["provider"], runner["role"], runner["status"], runner["project_id"]))
        operation = self.app.delivery_operations[result["check_operation"]["id"]]
        self.assertEqual({"operation_id": operation["id"], "subject_id": task["id"], "kind": "checks"},
                         runner["delivery_context"])
        self.assertEqual(([operation["commands"][0]["id"]], False), (operation["passed"], operation["failed"]))
        self.assertEqual("awaiting_review", result["status"])
        self.assertFalse(runner_id in [t["id"] for t in self.state()["tasks"] if t.get("delivery_available")])
        # A delivery run takes no follow-up: delivery controls only.
        status, answer = self.http("POST", f"/api/tasks/{runner_id}/message", {"text": "again", "expected_turn_id": runner["turn_id"]})
        self.assertEqual(400, status, answer)
        self.assertEqual(("completed", 1), (self.app.tasks[runner_id]["status"], self.app.tasks[runner_id]["claude"]["invocations"]))
        with self.app.lock:
            self.assertEqual((None, "Use delivery controls for check and review runs"), self.app._send_state(self.app.tasks[runner_id]))

    def test_claude_review_run_starts_code_quality_reviewer_and_matches_message_sender_and_turn(self):
        task = self.subject()
        self.run_checks(task)
        runner_id, result = self.run_review(task)
        argv = self.last_argv()["argv"]
        self.assertEqual("code_quality_reviewer", argv[argv.index("--agent") + 1])
        runner = self.app.tasks[runner_id]
        self.assertEqual(("claude", "code_quality_reviewer", "completed"), (runner["provider"], runner["role"], runner["status"]))
        operation = self.app.delivery_operations[result["review_operation"]["id"]]
        replies = [m for m in self.app.messages if m["task_id"] == runner_id and m["kind"] == "agent"]
        self.assertEqual(1, len(replies))
        self.assertEqual((runner["thread_id"], runner["turn_id"]), (replies[0]["sender"], replies[0]["turn_id"]))
        self.assertEqual([replies[0]["id"]], [row["id"] for row in operation["review_messages"]])
        self.assertEqual([replies[0]["id"]], operation["review_expected"])
        self.assertTrue(result["actions"]["review_decision"])
        status, preview = self.http("GET", f"/api/tasks/{task['id']}/delivery/reviews/{operation['id']}")
        self.assertEqual(200, status, preview)
        self.assertEqual([replies[0]["text"]], [m["text"] for m in preview["messages"]])

    def test_review_message_from_another_turn_or_sender_is_ignored(self):
        task = self.subject()
        self.run_checks(task)
        runner_id, _ = self.run_review(task)
        review_id = self.delivery(task["id"])["review_operation"]["id"]
        before = deepcopy(self.app.delivery_operations[review_id])
        runner = self.app.tasks[runner_id]
        with self.app.lock:
            self.app._append_message(runner_id, "agent", "Forged other-turn approval", "turn-9", runner["thread_id"],
                                     event_id="forged-turn")
            self.app._append_message(runner_id, "agent", "Forged other-sender approval", runner["turn_id"],
                                     task["thread_id"], event_id="forged-sender")
        self.assertEqual(before, self.app.delivery_operations[review_id])
        # The subject's own replies never count as review content either.
        self.assertTrue(self.delivery(task["id"])["actions"]["review_decision"])

    def test_code_snapshot_change_after_review_invalidates_it(self):
        task, _ = self.ready_subject()
        (self.project_dir / "changed.py").write_text("VALUE = 2\n")
        result = self.delivery(task["id"])
        self.assertEqual(("stale", ["checks_stale"]), (result["status"], result["reason_codes"]))
        (self.project_dir / "changed.py").unlink()
        self.assertEqual("ready", self.delivery(task["id"])["status"])
        # A role (policy) change after review: the policy digest and the subject's role binding no longer match.
        with self.app.lock:
            self.app.roles["backend_developer"] = dict(self.app.roles["backend_developer"], instructions="Changed prompt")
        result = self.delivery(task["id"])
        self.assertEqual(("unverified", ["policy_binding_changed"]), (result["status"], result["reason_codes"]))

    def test_delivery_refused_when_subject_is_not_latest_completed_turn(self):
        task = self.subject()
        _, checked = self.run_checks(task)
        old_checks = checked["check_operation"]["id"]
        later = self.followup(self.task_state(task["id"]))
        self.assertEqual(("completed", "turn-2"), (later["status"], later["turn_id"]))
        result = self.delivery(task["id"])
        self.assertEqual(("stale", ["checks_stale"]), (result["status"], result["reason_codes"]))
        self.assertFalse(result["actions"]["start_review"])
        status, answer = self.http("POST", f"/api/tasks/{task['id']}/delivery/reviews", {
            "expected_snapshot": result["snapshot_digest"], "check_operation_id": old_checks,
            "operation_id": uuid.uuid4().hex, "confirmed": True})
        self.assertEqual((409, "delivery_not_started"), (status, answer.get("code")))
        # A subject whose latest turn did not complete is not verified and starts nothing.
        with self.app.lock:
            self.app.tasks[task["id"]]["status"] = "failed"
        result = self.delivery(task["id"])
        self.assertEqual(("unverified", ["implementation_or_children_unresolved"]), (result["status"], result["reason_codes"]))
        count = len(self.app.delivery_operations)
        status, answer = self.http("POST", f"/api/tasks/{task['id']}/delivery/checks", {
            "expected_snapshot": result["snapshot_digest"], "expected_plan_version": result["plan_version"],
            "operation_id": uuid.uuid4().hex, "confirmed": True})
        self.assertEqual((409, "delivery_not_started"), (status, answer.get("code")))
        self.assertEqual(count, len(self.app.delivery_operations))

    def test_failing_check_output_leaves_readiness_not_ready(self):
        task = self.subject()
        # A non-zero exit, and an unapproved shell command (Claude reports no cwd per command), both fail the checks.
        for fixture in ("delivery_checks_fail", "delivery_checks_other"):
            with self.subTest(fixture=fixture):
                runner_id, result = self.run_checks(task, fixture)
                self.assertEqual("completed", self.app.tasks[runner_id]["status"])  # the run itself completed
                self.assertEqual(("checks_failed", ["successful_native_checks_required"]),
                                 (result["status"], result["reason_codes"]))
                self.assertTrue(self.app.delivery_operations[result["check_operation"]["id"]]["failed"])
                self.assertFalse(result["actions"]["start_review"])

    def test_finished_unnamed_delegate_does_not_block(self):
        task = self.subject()
        self.add_child(task["id"], None, "completed")
        self.add_child(task["id"], "qa_engineer", "completed")
        self.assertEqual("awaiting_checks", self.delivery(task["id"])["status"])

    def test_active_or_unknown_child_blocks(self):
        task = self.subject()
        for role, status in ((None, "running"), (None, "unknown"), ("qa_engineer", "unknown"),
                             ("qa_engineer", "waiting_approval"), ("not_a_role", "completed")):
            with self.subTest(role=role, status=status):
                key = self.add_child(task["id"], role, status)
                result = self.delivery(task["id"])
                self.assertEqual(("unverified", ["implementation_or_children_unresolved"]),
                                 (result["status"], result["reason_codes"]))
                self.assertFalse(any(result["actions"].values()))
                with self.app.lock:
                    del self.app.observed_tasks[key]
        self.assertEqual("awaiting_checks", self.delivery(task["id"])["status"])

    def test_omitted_delegation_blocks(self):
        task = self.subject()
        with self.app.lock:
            self.app.tasks[task["id"]]["claude"]["delegation_omitted"] = 1
        result = self.delivery(task["id"])
        self.assertEqual(("unverified", ["implementation_or_children_unresolved"]), (result["status"], result["reason_codes"]))

    def test_forged_codex_shaped_policy_on_claude_task_is_rejected(self):
        task = self.subject()
        _, checked = self.run_checks(task)
        self.assertEqual("awaiting_review", checked["status"])
        # An operation bound to a Ponytail-shaped policy digest never counts.
        operation_id = checked["check_operation"]["id"]
        forged = digest({"policy": PONYTAIL_SHAPE, "roles": self.app.roles})
        with self.app.lock:
            self.app.delivery_operations[operation_id]["policy"] = forged
        self.assertEqual(("stale", ["checks_stale"]), (self.delivery(task["id"])["status"],
                                                       self.delivery(task["id"])["reason_codes"]))
        # A Claude task stamped with a Ponytail-shaped policy is refused outright.
        with self.app.lock:
            self.app.tasks[task["id"]]["compliance_policy"] = dict(PONYTAIL_SHAPE)
        result = self.delivery(task["id"])
        self.assertEqual(("unverified", ["policy_binding_changed"]), (result["status"], result["reason_codes"]))
        self.assertFalse(any(result["actions"].values()))
        # So is a missing role binding.
        with self.app.lock:
            self.app.tasks[task["id"]].update(compliance_policy=dict(NOT_APPLICABLE_METADATA), compliance_role_digest=None)
        self.assertEqual("unverified", self.delivery(task["id"])["status"])


class ClaudeCheckParser(unittest.TestCase):
    """The parser reads Bash calls only for a delivery checks run and never lets command text or output out."""
    SESSION = "00000000-0000-4000-8000-00000000c4e1"

    def lines(self, name):
        return (Path(__file__).resolve().parent / "fixtures" / "claude" / (name + ".jsonl")).read_text().splitlines()

    def events(self, name, commands):
        state = StreamState(check_commands=commands)
        return [event for line in self.lines(name) for event in translate_stream_line(line, state)]

    def test_check_events_only_for_checks_runs_and_carry_ids_only(self):
        self.assertEqual([], [e for e in self.events("delivery_checks_pass", None) if e.kind.startswith("check_")])
        found = [(e.kind, dict(e.data)) for e in self.events("delivery_checks_pass", {CHECK: "c1"}) if e.kind.startswith("check_")]
        self.assertEqual([("check_command", {"tool_use_id": "toolu_synth_dc1", "check_id": "c1"}),
                          ("check_result", {"tool_use_id": "toolu_synth_dc1", "ok": True})], found)
        failed = [dict(e.data) for e in self.events("delivery_checks_fail", {CHECK: "c1"}) if e.kind == "check_result"]
        self.assertEqual([{"tool_use_id": "toolu_synth_dc2", "ok": False}], failed)
        other = [dict(e.data) for e in self.events("delivery_checks_other", {CHECK: "c1"}) if e.kind == "check_command"]
        self.assertEqual([None, "c1"], [row["check_id"] for row in other])
        for event in self.events("delivery_checks_other", {CHECK: "c1"}):
            self.assertNotIn("ls -la", json.dumps(dict(event.data)))
            self.assertNotIn("synthetic listing", json.dumps(dict(event.data)))

    def test_denied_or_not_executed_call_is_never_ok(self):
        denied = [line for line in self.lines("denied")]
        state = StreamState(check_commands={"SENSITIVE_TOOL_INPUT_MARKER": "c1"})
        found = [(e.kind, dict(e.data)) for line in denied for e in translate_stream_line(line, state)
                 if e.kind.startswith("check_")]
        self.assertEqual([("check_command", {"tool_use_id": "toolu_synth_d1", "check_id": "c1"}),
                          ("check_result", {"tool_use_id": "toolu_synth_d1", "ok": False})], found)


class CodexDeploymentUnchanged(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir="/private/tmp")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()

    def test_codex_deployment_still_refuses_not_applicable_and_uses_ponytail(self):
        default = Dashboard(self.root / "default")
        self.addCleanup(default.close)
        self.assertIsInstance(default.policy_provider, PonytailPolicy)
        policy = RaisingPolicy()
        app = Dashboard(self.root / "codex", policy_provider=policy)
        self.addCleanup(app.close)
        self.assertIs(policy, app.policy_provider)
        (self.root / "project").mkdir()
        project = app.add_project({"name": "Project", "path": str(self.root / "project")})
        # The Codex start path still loads Ponytail first (no provider refusal), for delivery runs too.
        data = {"project_id": project["id"], "title": "Delivery", "instruction": "Run checks", "role": "qa_engineer"}
        with self.assertRaises(PolicyError):
            app._start_task(data, delivery_operation={"id": "3" * 32})
        self.assertEqual(1, policy.calls)
        # A record stamped "not applicable" (a Claude run) is never verified in a Codex deployment.
        stamp = {"id": "a" * 32, "project_id": project["id"], "title": "T", "role": "backend_developer",
                 "status": "completed", "thread_id": "s", "turn_id": "turn-1", "provider": "claude",
                 "compliance_policy": dict(NOT_APPLICABLE_METADATA), "compliance_role_digest": "0" * 64,
                 "claude": {"delegation_omitted": 0}, "updated_at": "2026-11-04T00:00:00+00:00"}
        with app.lock:
            app.tasks[stamp["id"]] = stamp
        result = app.delivery(stamp["id"])
        self.assertEqual(("unverified", ["policy_binding_changed"]), (result["status"], result["reason_codes"]))
        self.assertEqual(1, policy.calls)  # refused before any Ponytail load
        # A Codex record keeps the Codex result shape: no Ponytail row is added.
        codex = dict(stamp, id="b" * 32, provider="codex", compliance_policy=dict(PONYTAIL_SHAPE))
        with app.lock:
            app.tasks[codex["id"]] = codex
        result = app.delivery(codex["id"])
        self.assertNotIn("ponytail", result)
        self.assertEqual(("unverified", ["approved_policy_unavailable"]), (result["status"], result["reason_codes"]))
        # The Codex generation is still the App Server connection generation.
        self.assertEqual(app._recovery_connection_generation(app.client), app._delivery_generation())


if __name__ == "__main__":
    unittest.main()
