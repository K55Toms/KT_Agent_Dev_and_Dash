"""Plan 5 Task 8: one user journey through the slice 2b features of a Claude deployment.

Evidence kind: fake-binary evidence, not a live run. Every run executes tests/fake_claude.py replaying a sanitized
fixture through the real argv builder, ClaudeRun and the real HTTP handler. Nothing here shows how the real CLI
behaves; a mocked journey cannot establish that a live integration works.

Journey: start a run, see its reply, send a follow-up and see the second reply, attach an output, see the team view
(model-reported summary, no rewards, an unnamed delegate under the parent's role), run delivery checks and a review,
read readiness (Ponytail not applicable, not counted as passed), delete the task and find nothing left.

Each run is started only after the previous one has finished and been reaped (``wait_finished``), and ``use`` builds a
new env dict per run, so no fake env is shared between runs started in sequence.
"""
import json
import unittest

from tests.test_claude_delivery import ClaudeDeliveryHarness
from tests.test_claude_slice2b_baseline import FOLLOWUP, INSTRUCTION, REPORT, SESSION

MARKER = "SENSITIVE_ASSISTANT_TEXT_MARKER"


class ClaudeSlice2bJourney(ClaudeDeliveryHarness):
    def conversation(self, task_id):
        status, view = self.http("GET", f"/api/tasks/{task_id}/conversation")
        self.assertEqual(200, status, view)
        return view

    def test_conversation_outputs_team_delivery_and_deletion(self):
        # 1. Start a run (it also launches one unnamed built-in delegate) and see the reply.
        task = self.finished_task("subagent")
        self.assertEqual("completed", task["status"])
        view = self.conversation(task["id"])
        self.assertEqual(["user", "agent"], [m["kind"] for m in view["messages"]])
        self.assertEqual([INSTRUCTION, "synthetic main answer"], [m["text"] for m in view["messages"]])
        self.assertTrue(view["can_send"])
        self.assertEqual("followup", view["send_mode"])

        # 2. Follow-up: a new turn with its own reply, after the first exchange.
        first_turn = task["turn_id"]
        task = self.followup(task)
        self.assertNotEqual(first_turn, task["turn_id"])
        view = self.conversation(task["id"])
        self.assertEqual(["user", "agent", "user", "agent"], [m["kind"] for m in view["messages"]])
        self.assertEqual([INSTRUCTION, "synthetic main answer", FOLLOWUP, MARKER],
                         [m["text"] for m in view["messages"]])

        # 3. Attach an output owned by the human; it is listed for the current turn and previews.
        self.write_report()
        status, answer = self.attach(task)
        self.assertEqual(200, status, answer)
        self.assertEqual(("human", REPORT, task["turn_id"]),
                         (answer["output"]["source"], answer["output"]["path"], answer["output"]["turn_id"]))
        outputs = self.task_state(task["id"])["outputs"]
        self.assertEqual([REPORT], [o["path"] for o in outputs])
        status, preview = self.http("GET", f"/api/tasks/{task['id']}/outputs/{outputs[0]['id']}")
        self.assertEqual(200, status, preview)
        self.assertIn("Synthetic report", json.dumps(preview))

        # 4. Team view: the task under its role with a model-reported summary, no rewards, and the unnamed
        # delegate listed under the parent's role.
        status, team = self.http("GET", "/api/team")
        self.assertEqual(200, status)
        self.assertEqual(([], False), (team["awards"], team["rewards"]))
        member = next(m for m in team["members"] if m["id"] == "backend_developer")
        self.assertNotIn("coins", member)
        self.assertNotIn("agent_of_week", member)
        self.assertEqual((task["id"], MARKER), (member["last_task"]["id"], member["last_task"]["last_summary"]))
        by_source = {a["source"]: a for a in member["activities"]}
        self.assertEqual({"direct", "delegated"}, set(by_source))
        self.assertEqual(task["id"], by_source["direct"]["id"])
        self.assertEqual((task["id"], True), (by_source["delegated"]["parent_task_id"],
                                              by_source["delegated"]["unnamed_delegate"]))
        self.assertIsNone(by_source["delegated"]["role"])

        # 5. Delivery: checks, then review, then the human decision. Ponytail is not applicable throughout.
        self.approve_plan(task["project_id"])
        before = self.delivery(task["id"])
        self.assertEqual(("awaiting_checks", "not_applicable"), (before["status"], before["ponytail"]))
        checks_id, after_checks = self.run_checks(task)
        self.assertEqual(("awaiting_review", "not_applicable"), (after_checks["status"], after_checks["ponytail"]))
        self.assertEqual((1, 1), (after_checks["check_operation"]["passed_checks"],
                                  after_checks["check_operation"]["required_checks"]))
        review_id, after_review = self.run_review(task)
        self.assertTrue(after_review["actions"]["review_decision"])
        self.assertNotEqual("ready", after_review["status"])  # ready needs the human decision too
        ready = self.accept(task)
        self.assertEqual(("ready", "not_applicable", []), (ready["status"], ready["ponytail"], ready["reason_codes"]))
        self.assertEqual("ready", self.task_state(task["id"])["delivery_summary"]["status"])

        # 6. Delete the task; the task, its runner tasks, delegate rows, outputs, messages and holds are gone.
        shown = self.task_state(task["id"])
        self.assertTrue(shown["can_delete"])
        status, answer = self.http("POST", f"/api/tasks/{task['id']}/delete",
                                   {"expected_version": shown["deletion_version"], "confirmed": True})
        self.assertEqual((200, {"task_id": task["id"], "deleted": True}), (status, answer))
        # The check and review runner tasks are separate tasks and stay (existing deletion behaviour, as for Codex);
        # the subject's operations, messages, outputs and delegate rows go with it.
        self.assertNotIn(task["id"], [t["id"] for t in self.state()["tasks"]])
        self.assertNotIn(task["id"], self.app.tasks)
        self.assertEqual([], [m for m in self.app.messages if m.get("task_id") == task["id"]])
        self.assertEqual(404, self.http("GET", f"/api/tasks/{task['id']}/conversation")[0])
        self.assertEqual({checks_id, review_id}, {t["id"] for t in self.state()["tasks"]})
        self.assertEqual([], [r for r in self.app.observed_tasks.values() if r["parent_task_id"] == task["id"]])
        self.assertNotIn(SESSION, self.app.owned_threads)
        self.assertEqual({}, self.app.runs)
        member = next(m for m in self.http("GET", "/api/team")[1]["members"] if m["id"] == "backend_developer")
        self.assertEqual(([], None), (member["activities"], member["last_task"]))
        self.assertEqual({}, self.app.delivery_operations)


if __name__ == "__main__":
    unittest.main()
