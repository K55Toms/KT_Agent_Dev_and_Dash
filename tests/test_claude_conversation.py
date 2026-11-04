"""Plan 5 Task 2: Claude assistant replies appear in the conversation view.

Evidence kind: fake-binary evidence (tests/fake_claude.py replaying sanitized fixtures through the real runner
and HTTP handler, via the shared Slice2bHarness). The text under test is the synthetic marker the fixtures carry.
The sensitive-content scanner is replaced by a stand-in that flags a runtime-built sentinel (never a real secret).
"""
import json
import uuid
from unittest.mock import patch

from dashboard.backends.base import NeutralEvent
from dashboard.backends.claude_stream import MAX_MESSAGE_TEXT, TRUNCATION_MARKER, StreamState, translate_stream_line
from dashboard.project_files import FileAccessError
from dashboard.server import CLAUDE_REPLY_WITHHELD
from tests import test_claude_slice2b_baseline as baseline

REPLY = "SENSITIVE_ASSISTANT_TEXT_MARKER"


class ClaudeConversationTests(baseline.Slice2bHarness):
    def view(self, task):
        status, view = self.http("GET", f"/api/tasks/{task['id']}/conversation")
        self.assertEqual(200, status)
        return view

    def replies(self, task):
        return [m for m in self.view(task)["messages"] if m["kind"] != "user"]

    def test_assistant_text_appears_once_in_order_with_turn_id(self):
        task = self.finished_task()
        view = self.view(task)
        self.assertEqual(["user", "agent"], [m["kind"] for m in view["messages"]])
        reply = view["messages"][1]
        self.assertEqual(REPLY, reply["text"])
        self.assertEqual(baseline.SESSION, reply["sender"])
        self.assertEqual(task["thread_id"], reply["sender"])
        self.assertEqual(task["turn_id"], reply["turn_id"])
        self.assertEqual("complete", reply["status"])

    def test_only_the_main_agent_text_is_shown(self):
        task = self.finished_task("subagent")
        texts = [m["text"] for m in self.view(task)["messages"]]
        self.assertEqual([baseline.INSTRUCTION, "synthetic main answer"], texts)
        blob = json.dumps(self.view(task))
        for marker in ("SENSITIVE_SUBAGENT_TEXT_MARKER", "SENSITIVE_TOOL_INPUT_MARKER", "SENSITIVE_HOOK_OUTPUT_MARKER"):
            self.assertNotIn(marker, blob)

    def test_followup_keeps_earlier_messages_and_new_turn_id(self):
        task = self.finished_task()
        first = self.replies(task)[0]
        after = self.followup(task)
        view = self.view(after)
        self.assertEqual(["user", "agent", "user", "agent"], [m["kind"] for m in view["messages"]])
        self.assertEqual(first, view["messages"][1])
        self.assertEqual(task["turn_id"], view["messages"][1]["turn_id"])
        self.assertNotEqual(task["turn_id"], after["turn_id"])
        self.assertEqual(after["turn_id"], view["messages"][3]["turn_id"])
        self.assertEqual(baseline.FOLLOWUP, view["messages"][2]["text"])
        self.assertEqual(baseline.SESSION, view["messages"][3]["sender"])

    def stream_line(self, task, text, uuid="00000000-0000-4000-8000-0000000000aa"):
        return json.dumps({"type": "assistant", "uuid": uuid, "message": {"id": "msg_x", "content": [
            {"type": "text", "text": text}]}})

    def feed(self, task, line, turn_id=None):
        """Run one stream line through the parser and the real event handler, as the runner does."""
        state = StreamState(turn_id=turn_id or task["turn_id"])
        state.session_id = baseline.SESSION
        run = object()
        with self.app.lock:
            self.app.runs[task["id"]] = run
        try:
            for event in translate_stream_line(line, state):
                self.app._claude_event_locked(task["id"], run, event, baseline.SESSION)
        finally:
            with self.app.lock:
                self.app.runs.pop(task["id"], None)

    def test_duplicate_stream_line_makes_one_message(self):
        task = self.finished_task()
        before = len(self.replies(task))
        line = self.stream_line(task, "replayed text")
        for _ in range(3):
            self.feed(task, line)
        self.assertEqual(before + 1, len(self.replies(task)))
        self.feed(task, line, turn_id="turn-9")  # the same line seen again after a resume
        self.assertEqual(before + 1, len(self.replies(task)))

    def test_lines_sharing_a_message_id_both_appear(self):
        task = self.finished_task()
        before = len(self.replies(task))
        for text in ("part one", "part two"):
            self.feed(task, json.dumps({"type": "assistant", "message": {"id": "msg_same", "content": [
                {"type": "text", "text": text}]}}))
        self.assertEqual(["part one", "part two"], [m["text"] for m in self.replies(task)[before:]])

    def test_lone_surrogate_text_is_withheld_without_crashing(self):
        task = self.finished_task()
        self.feed(task, self.stream_line(task, "\ud800", uuid="u-surrogate"))
        last = self.replies(task)[-1]
        self.assertEqual(("system", CLAUDE_REPLY_WITHHELD), (last["kind"], last["text"]))

    def test_other_task_messages_are_not_returned(self):
        first = self.finished_task()
        status, second = self.http("POST", "/api/tasks", {"project_id": first["project_id"], "title": "Second",
                                                          "instruction": "Second synthetic instruction",
                                                          "role": "backend_developer"})
        self.assertEqual(200, status, second)
        self.wait_finished(second["id"])
        with self.app.lock:
            self.app._append_message(second["id"], "agent", "ONLY_FOR_THE_SECOND_TASK", "turn-1", "other-session",
                                     event_id="seeded")
        self.assertIn("ONLY_FOR_THE_SECOND_TASK", json.dumps(self.view(second)))
        self.assertNotIn("ONLY_FOR_THE_SECOND_TASK", json.dumps(self.view(first)))
        self.assertEqual({first["id"], second["id"]}, {m["task_id"] for m in self.app.messages})

    def test_message_text_is_scanned_and_never_stored_when_refused(self):
        secret = "SENTINEL_SECRET_" + uuid.uuid4().hex  # built at run time, never stored in the repo

        def scan(data):
            if secret.encode() in data:
                raise FileAccessError(422, "found")

        task = self.finished_task()
        stored = self.app.tasks[task["id"]]
        with patch("dashboard.conversation.scan_preview", side_effect=scan):
            with self.app.lock:
                self.app._claude_reply(stored, baseline.SESSION, task["turn_id"],
                                       {"text": "before " + secret, "event_id": "claude|turn-1|secret|0"})
                self.app._claude_reply(stored, baseline.SESSION, task["turn_id"],
                                       {"text": "clean text", "event_id": "claude|turn-1|clean|0"})
        withheld, clean = self.replies(task)[-2:]
        self.assertEqual(("system", CLAUDE_REPLY_WITHHELD), (withheld["kind"], withheld["text"]))
        self.assertEqual(("agent", "clean text"), (clean["kind"], clean["text"]))
        rows = self.app.store.db.execute("SELECT body FROM records").fetchall()
        self.assertNotIn(secret, json.dumps([self.view(task), self.app.snapshot(), [tuple(r) for r in rows]]))

    def test_refused_reply_in_a_real_run_leaves_only_the_placeholder(self):
        def scan(data):
            if REPLY.encode() in data:
                raise FileAccessError(422, "found")

        with patch("dashboard.conversation.scan_preview", side_effect=scan):
            task = self.finished_task()
        withheld = self.replies(task)
        self.assertEqual([("system", CLAUDE_REPLY_WITHHELD)], [(m["kind"], m["text"]) for m in withheld])
        self.assertNotIn(REPLY, json.dumps(self.view(task)))

    def test_long_text_is_truncated_with_a_marker_not_dropped(self):
        state = StreamState(turn_id="turn-1")
        translate_stream_line(json.dumps({"type": "system", "subtype": "init", "session_id": baseline.SESSION}), state)
        line = json.dumps({"type": "assistant", "uuid": "u-long", "message": {"content": [
            {"type": "text", "text": "y" * (MAX_MESSAGE_TEXT + 500)}]}})
        (event,) = translate_stream_line(line, state)
        task = self.finished_task()
        with self.app.lock:
            self.app._claude_reply(self.app.tasks[task["id"]], baseline.SESSION, task["turn_id"], event.data)
        text = self.replies(task)[-1]["text"]
        self.assertEqual(MAX_MESSAGE_TEXT, len(text))
        self.assertTrue(text.endswith(TRUNCATION_MARKER))
        self.assertEqual("agent", self.replies(task)[-1]["kind"])

    def test_message_event_for_a_refused_or_foreign_run_is_ignored(self):
        task = self.finished_task()
        before = len(self.app.messages)
        event = NeutralEvent("message", baseline.SESSION, "turn-1", {"text": "late", "event_id": "claude|turn-1|x|0"})
        self.app._claude_event_locked(task["id"], object(), event, None)  # not the task's run: ignored
        self.assertEqual(before, len(self.app.messages))


if __name__ == "__main__":
    import unittest
    unittest.main()
