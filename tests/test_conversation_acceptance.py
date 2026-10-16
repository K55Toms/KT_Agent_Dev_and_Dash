"""Independent lifecycle regressions with synthetic protocol events, no model calls."""
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch

from dashboard.server import Dashboard
from dashboard.codex_client import ProtocolError, RequestRejected
from dashboard.project_files import FileAccessError
from tests.test_dashboard_backend import FakeClient


class ConversationAcceptanceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir="/private/tmp")
        self.root = Path(self.temp.name).resolve()
        self.scan = patch("dashboard.conversation.scan_preview", return_value=None)
        self.scan.start()
        self.app = Dashboard(self.root / "state")
        self.fake = FakeClient()
        self.app.client = self.fake
        self.app.connection["status"] = "connected"
        project = self.app.add_project({"name": "Synthetic acceptance fixture", "path": str(self.root)})
        self.task = self.app.start_task({"project_id": project["id"], "title": "Synthetic conversation",
                                        "instruction": "Synthetic acceptance fixture only.", "role": "chief_of_staff"})
        for _ in range(200):
            if self.app.tasks[self.task["id"]]["turn_id"]:
                break
            time.sleep(.01)
        self.task = self.app.tasks[self.task["id"]]
        self.assertTrue(self.task["turn_id"])

    def tearDown(self):
        self.app.close()
        self.scan.stop()
        self.temp.cleanup()

    def event(self, method, **params):
        self.app.on_message({"method": method, "params": {
            "threadId": self.task["thread_id"], "turnId": self.task["turn_id"], **params}})

    def question(self):
        self.app.on_message({"id": 71, "method": "item/tool/requestUserInput", "params": {
            "threadId": self.task["thread_id"], "turnId": self.task["turn_id"], "itemId": "question-item",
            "questions": [{"id": "layout", "header": "Layout", "question": "Which layout should be used?",
                           "options": [{"label": "Compact", "description": "Compact layout"},
                                       {"label": "Spacious", "description": "Spacious layout"}]}]}})
        self.app.wait_conversations()

    def test_pending_question_is_discoverable_without_opening_conversation(self):
        self.question()
        snapshot = self.app.snapshot()
        self.assertTrue(any(q["task_id"] == self.task["id"] and q["status"] == "pending"
                            for q in snapshot.get("questions", [])))

    def test_only_completed_visible_agent_text_is_recorded(self):
        self.event("item/agentMessage/delta", delta="Synthetic unapproved delta")
        self.event("item/completed", item={"id": "tool-output", "type": "commandExecution", "aggregatedOutput": "Synthetic raw tool output"})
        self.event("item/completed", item={"id": "visible", "type": "agentMessage", "phase": "final_answer", "text": "Synthetic visible result"})
        self.app.wait_conversations()
        text = " ".join(m["text"] for m in self.app.conversation(self.task["id"])["messages"])
        self.assertIn("Synthetic visible result", text)
        self.assertNotIn("Synthetic unapproved delta", text)
        self.assertNotIn("Synthetic raw tool output", text)

    def test_steering_is_bound_to_exact_turn_and_never_replayed(self):
        original = self.fake.request
        def reply(method, params):
            result = original(method, params)
            return {"turnId": params["expectedTurnId"]} if method == "turn/steer" else result
        with patch.object(self.fake, "request", side_effect=reply):
            self.app.send_message(self.task["id"], {"text": "Synthetic follow-up guidance", "expected_turn_id": self.task["turn_id"]})
        self.assertIn(("turn/steer", {"threadId": self.task["thread_id"], "expectedTurnId": self.task["turn_id"],
                                     "input": [{"type": "text", "text": "Synthetic follow-up guidance"}]}), self.fake.requests)
        count = len(self.fake.requests)
        with self.assertRaises(ValueError):
            self.app.send_message(self.task["id"], {"text": "Synthetic stale guidance", "expected_turn_id": "old-turn"})
        self.assertEqual(count, len(self.fake.requests))

    def test_question_answer_maps_once_to_the_current_native_request(self):
        self.question()
        question = self.app.conversation(self.task["id"])["questions"][0]
        with self.assertRaises(ValueError):
            self.app.respond_question(question["id"], {"answers": {"layout": ["Unknown choice"]}})
        self.assertEqual([], self.fake.responses)
        self.app.respond_question(question["id"], {"answers": {"layout": ["Compact"]}})
        self.assertEqual([(71, {"answers": {"layout": {"answers": ["Compact"]}}})], self.fake.responses)
        with self.assertRaises(ValueError):
            self.app.respond_question(question["id"], {"answers": {"layout": ["Compact"]}})
        self.assertEqual(1, len(self.fake.responses))

    def test_permission_like_question_is_not_an_approval_bypass(self):
        self.app.on_message({"id": 72, "method": "item/tool/requestUserInput", "params": {
            "threadId": self.task["thread_id"], "turnId": self.task["turn_id"], "itemId": "permission-item",
            "questions": [{"id": "permission", "header": "Permission", "question": "Approve this access request?",
                           "options": [{"label": "Accept", "description": "Grant access"},
                                       {"label": "Cancel", "description": "Cancel request"}]}]}})
        self.app.wait_conversations()
        record = self.app.conversation(self.task["id"])["questions"][0]
        self.assertEqual("unavailable", record["status"])
        with self.assertRaises(ValueError):
            self.app.respond_question(record["id"], {"answers": {"permission": ["Accept"]}})
        self.assertEqual([], self.fake.responses)

    def test_generic_connector_consent_choices_are_not_treated_as_advisory(self):
        self.app.on_message({"id": 75, "method": "item/tool/requestUserInput", "params": {
            "threadId": self.task["thread_id"], "turnId": self.task["turn_id"], "itemId": "generic-consent",
            "questions": [{"id": "continue", "header": "Continue", "question": "Which option?",
                           "options": [{"label": "Accept", "description": "Continue"},
                                       {"label": "Cancel", "description": "Stop here"}]}]}})
        self.app.wait_conversations()
        record = self.app.conversation(self.task["id"])["questions"][0]
        self.assertEqual("unavailable", record["status"])
        self.assertEqual([], record["questions"])
        self.assertEqual([], self.fake.responses)

    def test_saved_visible_history_is_read_only_after_restart(self):
        self.event("item/completed", item={"id": "persisted", "type": "agentMessage", "text": "Synthetic saved result"})
        self.app.wait_conversations()
        identifier = self.task["id"]
        self.app.close()
        self.app = Dashboard(self.root / "state")
        self.app.client = FakeClient()
        self.app.connection["status"] = "connected"
        history = self.app.conversation(identifier)
        self.assertTrue(any(m["text"] == "Synthetic saved result" for m in history["messages"]))
        self.assertFalse(history["can_send"])

    def test_interrupted_question_does_not_permanently_block_followup(self):
        self.question()
        self.event("turn/completed", turn={"id": self.task["turn_id"], "status": "interrupted"})
        self.app.wait_conversations()
        state = self.app.conversation(self.task["id"])
        self.assertTrue(state["can_send"], state["blocked_reason"])
        self.assertEqual("followup", state["send_mode"])
        self.assertFalse(any(q["status"] == "pending" for q in state["questions"]))

    def test_terminal_error_expires_question_without_completion_notification(self):
        self.question()
        self.event("error", willRetry=False)
        self.app.wait_conversations()
        state = self.app.conversation(self.task["id"])
        self.assertFalse(any(q["status"] == "pending" for q in state["questions"]))
        self.assertTrue(state["can_send"], state["blocked_reason"])

    def test_child_final_message_survives_queued_spawn_and_slow_scanner(self):
        from dashboard.conversation import safe_text
        entered, release = threading.Event(), threading.Event()
        def slow_scan(value, *args, **kwargs):
            if value == "Synthetic slow scan":
                entered.set()
                if not release.wait(5):
                    raise AssertionError("Synthetic scanner gate was not released")
            return safe_text(value, *args, **kwargs)
        with patch("dashboard.conversation.safe_text", side_effect=slow_scan):
            self.event("item/completed", item={"id": "intro", "type": "agentMessage", "text": "Synthetic slow scan"})
            self.assertTrue(entered.wait(2))
            try:
                self.event("item/completed", item={"id": "spawn", "type": "collabAgentToolCall",
                    "tool": "spawnAgent", "status": "completed", "senderThreadId": self.task["thread_id"],
                    "receiverThreadIds": ["child-thread"], "agentsStates": {"child-thread": {"status": "running"}},
                    "prompt": "Synthetic delegated task"})
                self.app.on_message({"method": "turn/started", "params": {
                    "threadId": "child-thread", "turn": {"id": "child-turn", "status": "inProgress"}}})
                self.app.on_message({"method": "item/completed", "params": {
                    "threadId": "child-thread", "turnId": "child-turn", "item": {
                        "id": "child-final", "type": "agentMessage", "phase": "final_answer",
                        "text": "Synthetic child result"}}})
            finally:
                release.set()
            self.app.wait_conversations()
        state = self.app.conversation(self.task["id"])
        self.assertTrue(any(m["text"] == "Synthetic child result" for m in state["messages"]))

    def test_live_child_reserves_project_and_can_be_stopped_after_parent_finishes(self):
        self.app.on_message({"method": "thread/started", "params": {"thread": {
            "id": "active-child", "parentThreadId": self.task["thread_id"], "agentRole": "backend_developer"}}})
        self.app.on_message({"method": "turn/started", "params": {
            "threadId": "active-child", "turn": {"id": "active-child-turn", "status": "inProgress"}}})
        self.event("turn/completed", turn={"id": self.task["turn_id"], "status": "completed"})
        service = Mock()
        service.publish.return_value = {"published": True}
        self.app.git_service = service
        with self.assertRaises(FileAccessError) as error:
            self.app.publish_project(self.task["project_id"], {})
        self.assertEqual(409, error.exception.status)
        service.publish.assert_not_called()
        self.assertGreater(next(t for t in self.app.snapshot()["tasks"] if t["id"] == self.task["id"])["active_children"], 0)
        self.app.interrupt(self.task["id"], {})
        self.assertIn(("turn/interrupt", {"threadId": "active-child", "turnId": "active-child-turn"}), self.fake.requests)
        self.app.on_message({"method": "turn/completed", "params": {
            "threadId": "active-child", "turn": {"id": "active-child-turn", "status": "interrupted"}}})
        self.app.publish_project(self.task["project_id"], {})
        service.publish.assert_called_once()

    def test_child_question_remains_answerable_after_parent_turn_finishes(self):
        self.app.on_message({"method": "thread/started", "params": {"thread": {
            "id": "question-child", "parentThreadId": self.task["thread_id"], "agentRole": "backend_developer"}}})
        self.app.on_message({"method": "turn/started", "params": {
            "threadId": "question-child", "turn": {"id": "question-child-turn", "status": "inProgress"}}})
        self.event("turn/completed", turn={"id": self.task["turn_id"], "status": "completed"})
        self.app.on_message({"id": 79, "method": "item/tool/requestUserInput", "params": {
            "threadId": "question-child", "turnId": "question-child-turn", "itemId": "child-question",
            "questions": [{"id": "style", "header": "Style", "question": "Which coding style?", "options": []}]}})
        self.app.wait_conversations()
        record = self.app.conversation(self.task["id"])["questions"][0]
        self.assertEqual("pending", record["status"])
        self.app.respond_question(record["id"], {"answers": {"style": ["Use the existing style"]}})
        self.assertIn((79, {"answers": {"style": {"answers": ["Use the existing style"]}}}), self.fake.responses)
        self.assertEqual("completed", self.task["status"])

    def test_abrupt_restart_never_claims_child_activity_is_still_live(self):
        self.app.store.put("team_activity", {"id": "crash-fixture", "role": "backend_developer", "status": "running",
            "title": "Synthetic pre-crash child", "created_at": "2026-10-16T00:00:00+00:00", "updated_at": "2026-10-16T00:00:00+00:00"})
        self.app.close()
        self.app = Dashboard(self.root / "state")
        self.assertEqual("unknown", self.app.observed_tasks["crash-fixture"]["status"])
        self.assertEqual({}, self.app.owned_threads)

    def test_thread_tracking_saturation_blocks_new_work_and_publication(self):
        for index in range(255):
            self.app._register_thread(f"bounded-child-{index}", self.task["id"], self.task["thread_id"])
        with self.assertRaises(ValueError):
            self.app._register_thread("overflow-child", self.task["id"], self.task["thread_id"])
        self.assertTrue(self.app.runtime_tracking_lost)
        self.assertEqual(256, len(self.app.owned_threads))
        self.event("turn/completed", turn={"id": self.task["turn_id"], "status": "completed"})
        self.app.owned_threads.clear()
        with self.assertRaises(FileAccessError):
            self.app.publish_project(self.task["project_id"], {})
        with self.assertRaises(ValueError):
            self.app.start_task({"project_id": self.task["project_id"], "title": "Blocked synthetic run",
                                 "instruction": "Synthetic bounded runtime fixture", "role": "backend_developer"})

    def test_followup_notifications_can_complete_before_rpc_acknowledgement(self):
        previous = self.task["turn_id"]
        self.event("turn/completed", turn={"id": previous, "status": "completed"})
        original = self.fake.request
        def reply(method, params):
            result = original(method, params)
            if method == "turn/start":
                self.event("turn/started", turn={"id": "next-turn", "status": "inProgress"})
                self.event("turn/completed", turn={"id": "next-turn", "status": "completed"})
                return {"turn": {"id": "next-turn", "status": "completed"}}
            return result
        with patch.object(self.fake, "request", side_effect=reply):
            self.app.send_message(self.task["id"], {"text": "Synthetic follow-up", "expected_turn_id": previous})
        self.assertEqual("completed", self.task["status"])
        self.assertEqual("next-turn", self.task["turn_id"])
        self.assertFalse(self.app.owned_threads[self.task["thread_id"]]["active"])

    def test_explicit_followup_rejection_restores_finished_state(self):
        previous = self.task["turn_id"]
        self.event("turn/completed", turn={"id": previous, "status": "completed"})
        with patch.object(self.fake, "request", side_effect=RequestRejected("Synthetic rejection")) as native:
            with self.assertRaises(ValueError):
                self.app.send_message(self.task["id"], {"text": "Synthetic rejected follow-up", "expected_turn_id": previous})
        self.assertEqual(1, native.call_count)
        self.assertEqual("completed", self.task["status"])
        self.assertFalse(any(m["text"] == "Synthetic rejected follow-up" for m in self.app.messages))

    def test_ambiguous_followup_is_unknown_and_never_replayed(self):
        previous = self.task["turn_id"]
        self.event("turn/completed", turn={"id": previous, "status": "completed"})
        data = {"text": "Synthetic uncertain follow-up", "expected_turn_id": previous}
        with patch.object(self.fake, "request", side_effect=ProtocolError("Synthetic transport loss")) as native:
            with self.assertRaises(ProtocolError):
                self.app.send_message(self.task["id"], data)
            self.assertEqual("unknown", self.task["status"])
            with self.assertRaises(ValueError):
                self.app.send_message(self.task["id"], data)
            self.assertEqual(1, native.call_count)
