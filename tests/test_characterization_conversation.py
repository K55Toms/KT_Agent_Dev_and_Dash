"""Characterization of the Codex conversation items and question flows as projected by the dashboard.

These tests pin today's behaviour (golden file tests/fixtures/characterization/conversation.json): the
snapshot, the conversation view the dashboard serves for a task (``Dashboard.conversation``), and the
replies and rejections it sends to the native client. A later refactor of the Codex-shaped code in
dashboard/server.py and dashboard/conversation.py can then be proven behaviour-preserving. They describe
what the dashboard does now; they do not assert that it is the desired design.

The message shapes below mirror those in tests/test_conversation.py; they are copied as shapes (that
module nests its builders inside a TestCase, so they cannot be imported). Unlike that module, these
tests do not stub the secret scanner, so they need the reviewed scanner (gitleaks).
"""
import json
import unittest

from tests.characterization import ScriptedDashboard, check_golden, normalize, require_scanner

GOLDEN = "conversation"
TURN = {"id": "turn-one"}
QUESTION_ID = "question-item"

needs_scanner = require_scanner()


def secret_looking_text():
    # Built at run time so no secret-looking literal exists in this source file.
    return "pass" + "word = " + '"' + "x7Qm2" + "Lp9Zr4Tv8" + '"'


@needs_scanner
class ConversationProjectionTests(ScriptedDashboard):
    def check(self, name):
        """Golden the snapshot and the stored conversation view together (both normalized)."""
        self.app.wait_conversations()
        snapshot = normalize(self.app.snapshot())
        view = self.view()
        check_golden(self, GOLDEN, name, {"conversation": view, "snapshot": snapshot})
        return snapshot, view

    def view(self):
        """The dashboard's own projection of the stored conversation, with ids made stable."""
        view = self.app.conversation(self.current["id"])
        # Message ids are hashes of the task id and event id, so they differ on every run.
        for number, message in enumerate(view["messages"], 1):
            message["id"] = "message-%d" % number
        view["task_id"] = "task-1"
        for question in view["questions"]:
            question["task_id"] = "task-1"
        return normalize(view, roots=(self.root,))

    def check_replies(self, name, responses, rejections):
        """Pin what the dashboard sent to the native client (exact lists and a normalized golden)."""
        self.assertEqual(responses, self.fake.responses)
        self.assertEqual(rejections, self.fake.rejections)
        check_golden(self, GOLDEN, name, normalize({"rejections": rejections,
                                                    "responses": [list(reply) for reply in self.fake.responses]}))

    def start(self):
        self.current = self.task()
        self.event("turn/started", turn={**TURN, "status": "inProgress"})
        return self.current

    def agent_message(self, item_id, text, **extra):
        self.event("item/completed", item={"type": "agentMessage", "id": item_id, "text": text,
                                           "phase": "final_answer", **extra})

    def ask(self, rpc_id=71, thread="thread-one", turn="turn-one"):
        self.app.on_message({"id": rpc_id, "method": "item/tool/requestUserInput", "params": {
            "threadId": thread, "turnId": turn, "itemId": QUESTION_ID,
            "questions": [{"id": "layout", "header": "Layout", "question": "Which layout should we use?",
                           "options": [{"label": "Compact", "description": "Use less space"},
                                       {"label": "Roomy", "description": "Use more space"}]}]}})
        self.app.wait_conversations()
        return list(self.app.questions.values())[-1]

    def tool_call(self, rpc_id, tool, thread="thread-one", turn="turn-one"):
        self.app.on_message({"id": rpc_id, "method": "item/tool/call", "params": {
            "threadId": thread, "turnId": turn, "callId": "SYNTHETIC_CALL", "tool": tool,
            "arguments": {"note": "SYNTHETIC_PRIVATE_TOOL_ARGUMENT"}}})
        self.app.wait_conversations()

    def test_agent_message_item_projection(self):
        task = self.start()
        self.check("agent_message.before_items")
        self.agent_message("item-one", "SYNTHETIC_AGENT_REPLY")
        snapshot, view = self.check("agent_message.completed")
        # The run's instruction is the first stored message; the agent reply follows it.
        self.assertEqual(["user", "agent"], [message["kind"] for message in view["messages"]])
        self.assertEqual("SYNTHETIC_AGENT_REPLY", view["messages"][1]["text"])
        self.assertEqual("SYNTHETIC_AGENT_REPLY", snapshot["tasks"][0]["last_summary"])
        self.assertEqual("model-reported", snapshot["tasks"][0]["last_summary_source"])
        self.assertEqual("running", snapshot["tasks"][0]["status"])
        self.assertEqual("SYNTHETIC_AGENT_REPLY", self.app.tasks[task["id"]]["last_summary"])
        # The same item delivered twice, and item types the conversation does not store, add nothing.
        self.agent_message("item-one", "SYNTHETIC_AGENT_REPLY")
        self.event("item/completed", item={"type": "reasoning", "id": "item-reasoning", "text": "SYNTHETIC_REASONING"})
        self.event("item/completed", item={"type": "commandExecution", "id": "item-command", "command": "SYNTHETIC_COMMAND"})
        again, again_view = self.check("agent_message.duplicates_and_other_items_ignored")
        self.assertEqual(view["messages"], again_view["messages"])
        self.assertEqual(snapshot["tasks"], again["tasks"])
        # An item from a turn the thread never started is ignored.
        self.event("item/completed", turnId="turn-stale", item={"type": "agentMessage", "id": "item-stale",
                                                                 "text": "SYNTHETIC_STALE_REPLY"})
        _, stale_view = self.check("agent_message.stale_turn_item_ignored")
        self.assertEqual(2, len(stale_view["messages"]))
        self.assertNotIn("SYNTHETIC_REASONING", json.dumps(stale_view))
        self.assertNotIn("SYNTHETIC_COMMAND", json.dumps(stale_view))
        self.assertEqual([], self.fake.responses)
        self.assertEqual([], self.fake.rejections)

    def test_agent_message_with_sensitive_text_is_withheld(self):
        self.start()
        self.agent_message("item-secret", secret_looking_text())
        snapshot, view = self.check("agent_message.sensitive_withheld")
        self.assertEqual(["user", "system"], [message["kind"] for message in view["messages"]])
        self.assertEqual("Agent message withheld because sensitive-content checks did not pass.",
                         view["messages"][1]["text"])
        self.assertNotIn(secret_looking_text(), json.dumps(self.app.conversation(self.current["id"])))
        self.assertNotIn(secret_looking_text(), json.dumps(self.app.snapshot()))
        self.assertNotIn(secret_looking_text().encode(), (self.root / "state/dashboard.sqlite3").read_bytes())
        # A withheld message never becomes the task summary.
        self.assertNotIn("last_summary_source", snapshot["tasks"][0])

    def test_requestuserinput_question_pending_then_answered(self):
        task = self.start()
        question = self.ask()
        self.assertEqual("pending", question["status"])
        snapshot, view = self.check("question_answer.pending")
        self.assertEqual("waiting_approval", snapshot["tasks"][0]["status"])
        self.assertEqual("pending", snapshot["questions"][0]["status"])
        self.assertEqual(["pending"], [q["status"] for q in view["questions"]])
        self.assertFalse(view["can_send"])
        self.assertEqual("Answer the pending question or interrupt the run", view["blocked_reason"])
        self.check_replies("question_answer.replies_before_answer", [], [])
        # A choice outside the offered options is refused and nothing is sent.
        with self.assertRaises(ValueError):
            self.app.respond_question(question["id"], {"answers": {"layout": ["Elsewhere"]}})
        self.assertEqual([], self.fake.responses)
        self.assertEqual({"status": "resolved"}, self.app.respond_question(question["id"], {"answers": {"layout": ["Compact"]}}))
        answered, answered_view = self.check("question_answer.answered")
        self.assertEqual("running", answered["tasks"][0]["status"])
        self.assertEqual([], answered["questions"])
        self.assertEqual(["resolved"], [q["status"] for q in answered_view["questions"]])
        self.assertEqual(["user", "user"], [message["kind"] for message in answered_view["messages"]])
        self.assertEqual("Layout: Compact", answered_view["messages"][1]["text"])
        self.assertTrue(answered_view["can_send"])
        self.check_replies("question_answer.replies", [(71, {"answers": {"layout": {"answers": ["Compact"]}}})], [])
        # The question is spent: a second answer is refused and nothing more is sent.
        with self.assertRaises(ValueError):
            self.app.respond_question(question["id"], {"answers": {"layout": ["Roomy"]}})
        self.assertEqual(1, len(self.fake.responses))
        self.assertEqual("running", self.app.tasks[task["id"]]["status"])

    def test_question_expires_on_turn_completed(self):
        self.start()
        question = self.ask(rpc_id=72)
        self.check("question_expiry.pending")
        self.event("turn/completed", turn={**TURN, "status": "completed"})
        final, view = self.check("question_expiry.turn_completed")
        # Expired unanswered, not answered: the turn ended before anyone replied.
        # The snapshot lists only questions still awaiting a reply; the stored conversation keeps the outcome.
        self.assertEqual([], final["questions"])
        self.assertEqual(["unavailable"], [q["status"] for q in view["questions"]])
        self.assertEqual("completed", final["tasks"][0]["status"])
        self.assertEqual(["SYNTHETIC_PRIVATE_TASK_INSTRUCTION"], [message["text"] for message in view["messages"]])
        with self.assertRaises(ValueError):
            self.app.respond_question(question["id"], {"answers": {"layout": ["Compact"]}})
        self.check_replies("question_expiry.replies", [], [])

    def test_unsupported_tool_call_is_rejected(self):
        self.start()
        # A tool call from a thread the dashboard does not own, or for a turn that is not current, is rejected.
        self.tool_call(41, "SYNTHETIC_UNSUPPORTED_TOOL", thread="thread-unknown")
        self.tool_call(42, "SYNTHETIC_UNSUPPORTED_TOOL", turn="turn-stale")
        snapshot, view = self.check("tool_call.rejected")
        self.assertEqual("running", snapshot["tasks"][0]["status"])
        self.assertEqual([], snapshot["questions"])
        self.assertEqual(1, len(view["messages"]))
        self.check_replies("tool_call.rejected_replies", [], [41, 42])
        # On the live turn an unsupported tool is answered with a failure result, not accepted.
        self.tool_call(43, "SYNTHETIC_UNSUPPORTED_TOOL")
        live, live_view = self.check("tool_call.unsupported_on_live_turn")
        self.assertEqual("running", live["tasks"][0]["status"])
        self.assertEqual(1, len(live_view["messages"]))
        self.assertEqual([41, 42], self.fake.rejections)
        self.assertEqual(1, len(self.fake.responses))
        request_id, result = self.fake.responses[0]
        self.assertEqual(43, request_id)
        self.assertIs(False, result["success"])
        self.assertNotIn("SYNTHETIC_PRIVATE_TOOL_ARGUMENT", json.dumps(self.app.snapshot()))
        check_golden(self, GOLDEN, "tool_call.unsupported_on_live_turn_replies",
                     normalize({"rejections": self.fake.rejections,
                                "responses": [list(reply) for reply in self.fake.responses]}))


if __name__ == "__main__":
    unittest.main()
