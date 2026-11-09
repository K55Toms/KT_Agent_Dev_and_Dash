"""Tests for the observed-sessions model (dashboard/observed.py)."""
import dataclasses
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dashboard import project_files  # noqa: E402
from dashboard.hook_http import HeldRequest  # noqa: E402
from dashboard.observed import ObservedSessions  # noqa: E402
from dashboard.observed_hook import parse_observed  # noqa: E402
from dashboard.project_files import SensitiveContentError  # noqa: E402
from dashboard.store import Store  # noqa: E402

MAIN = "00000000-0000-4000-8000-00000000a001"
OTHER = "00000000-0000-4000-8000-00000000a002"
AGENT = "agent-synthetic-1"
# Credential-shaped values are built at runtime and are obviously fake.
FAKE_KEY = "sk-" + "x" * 30
MARKER = b"sk-"


def fake_scan(data):
    """Stand-in for the reviewed scanner: refuses anything holding the fake credential prefix."""
    if MARKER in data:
        raise SensitiveContentError()


class Clock:
    def __init__(self, start=1_000_000.0):
        self.now = start

    def __call__(self):
        return self.now


def event(name, session=MAIN, cwd="/synthetic/projects/alpha", **extra):
    body = {"hook_event_name": name, "session_id": session}
    if cwd is not None:
        body["cwd"] = cwd
    body.update(extra)
    return parse_observed(json.dumps(body).encode("utf-8"))


def permission(tool_input=None, tool_name="Bash", session=MAIN, **extra):
    return event("PermissionRequest", session=session, tool_name=tool_name,
                 tool_input={"command": "echo synthetic"} if tool_input is None else tool_input, **extra)


def post(tool_input=None, tool_name="Bash", session=MAIN, **extra):
    return event("PostToolUse", session=session, tool_name=tool_name,
                 tool_input={"command": "echo synthetic"} if tool_input is None else tool_input, **extra)


class FailingStore:
    def __init__(self):
        self.calls = 0

    def load(self, kind):
        return []

    def put_many(self, puts, deletes=()):
        self.calls += 1
        raise sqlite3.OperationalError("disk I/O error")

    def put(self, kind, record):
        self.put_many([(kind, record)])

    def delete(self, kind, identifier):
        self.put_many([], [(kind, identifier)])


class ObservedSessionsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = Store(Path(self.temp.name).resolve() / "state")
        self.addCleanup(self.store.close)
        self.clock = Clock()
        scanner = patch("dashboard.conversation.scan_preview", side_effect=fake_scan)
        scanner.start()
        self.addCleanup(scanner.stop)
        self.model = ObservedSessions(self.store, clock=self.clock)

    def session(self, session_id=MAIN, model=None):
        snap = (model or self.model).snapshot()
        found = [s for s in snap["sessions"] if s["id"] == session_id]
        return found[0] if found else None

    def card(self, approval_id):
        return [c for c in self.model.snapshot()["approvals"] if c["id"] == approval_id][0]

    def pending(self, ev=None, wait=300):
        ev = ev or permission()
        held = HeldRequest()
        approval_id = self.model.add_pending(ev, held, self.clock() + wait)
        self.assertIsNotNone(approval_id)
        return approval_id, held

    # sessions

    def test_first_event_creates_session(self):
        self.assertEqual(self.model.snapshot()["sessions"], [])
        self.model.record(event("SubagentStop", agent_id=AGENT, agent_type="synthetic-worker"))
        session = self.session()
        self.assertEqual(session["id"], MAIN)
        self.assertEqual(session["project"], "alpha")
        self.assertEqual(session["status"], "active")
        self.assertEqual(session["first_seen"], self.clock.now)
        self.assertEqual(session["last_seen"], self.clock.now)
        stored = self.store.load("observed_session")
        self.assertEqual(len(stored), 1)
        self.assertEqual(set(stored[0]), {"id", "project", "first_seen", "last_seen", "status",
                                          "subagent_seen_at"})
        self.assertEqual(stored[0]["project"], "alpha")
        self.clock.now += 5
        self.model.record(event("Stop", cwd=None))
        self.assertEqual(self.session()["first_seen"], self.clock.now - 5)
        self.assertEqual(self.session()["last_seen"], self.clock.now)
        self.assertEqual(self.session()["project"], "alpha")

    def test_project_is_final_segment_or_unknown(self):
        cases = {"/synthetic/projects/beta/": "beta", None: "unknown", "/": "unknown",
                 "/synthetic/" + FAKE_KEY: "unknown", "relative": "relative"}
        for index, (cwd, expected) in enumerate(cases.items()):
            with self.subTest(cwd=cwd):
                session_id = "00000000-0000-4000-8000-%012d" % index
                self.model.record(event("Stop", session=session_id, cwd=cwd))
                self.assertEqual(self.session(session_id)["project"], expected)

    def test_session_end_marks_ended_and_any_event_reactivates(self):
        self.model.record(event("Stop"))
        self.model.record(event("SessionEnd", reason="other"))
        self.assertEqual(self.session()["status"], "ended")
        self.assertEqual(self.store.load("observed_session")[0]["status"], "ended")
        self.clock.now += 10
        self.model.record(event("SubagentStart", agent_id=AGENT, agent_type="synthetic-worker"))
        self.assertEqual(self.session()["status"], "active")
        self.assertEqual(self.store.load("observed_session")[0]["status"], "active")

    def test_quiet_is_computed_not_stored(self):
        self.model.record(event("Stop"))
        self.clock.now += 1799
        self.assertEqual(self.session()["status"], "active")
        self.clock.now += 1
        self.assertEqual(self.session()["status"], "quiet")
        self.assertEqual(self.store.load("observed_session")[0]["status"], "active")
        self.model.record(event("Stop"))
        self.assertEqual(self.session()["status"], "active")
        self.model.record(event("SessionEnd"))
        self.clock.now += 99999
        self.assertEqual(self.session()["status"], "ended")
        short = ObservedSessions(self.store, clock=self.clock, quiet_seconds=60)
        self.assertEqual(self.model.snapshot()["limits"]["quiet_seconds"], 1800)
        self.assertEqual(short.snapshot()["limits"]["quiet_seconds"], 60)

    def test_subagent_activity_has_time_not_count(self):
        self.model.record(event("Stop"))
        self.assertIsNone(self.session()["subagent_seen_at"])
        self.clock.now += 3
        self.model.record(event("SubagentStart", agent_id=AGENT, agent_type="synthetic-worker"))
        first = self.clock.now
        self.assertEqual(self.session()["subagent_seen_at"], first)
        for _ in range(4):
            self.clock.now += 2
            self.model.record(event("SubagentStop", agent_id=AGENT, agent_type="synthetic-worker"))
        session = self.session()
        self.assertEqual(session["subagent_seen_at"], self.clock.now)
        self.assertFalse(any("count" in key for key in session))
        self.assertNotIn(5, [v for v in session.values() if isinstance(v, int) and not isinstance(v, bool)])

    def test_cap_evicts_ended_then_quiet_first(self):
        ids = ["00000000-0000-4000-8000-%012d" % i for i in range(258)]
        for i in range(256):
            self.clock.now += 1
            self.model.record(event("Stop", session=ids[i]))
        # session 100 ends; sessions 0..99 are older and go quiet
        self.model.record(event("SessionEnd", session=ids[100]))
        self.clock.now += 3600
        self.assertEqual(len(self.model.snapshot()["sessions"]), 256)
        self.model.record(event("Stop", session=ids[256]))
        present = {s["id"] for s in self.model.snapshot()["sessions"]}
        self.assertEqual(len(present), 256)
        self.assertNotIn(ids[100], present)
        self.assertIn(ids[0], present)
        self.model.record(event("Stop", session=ids[257]))
        present = {s["id"] for s in self.model.snapshot()["sessions"]}
        self.assertEqual(len(present), 256)
        self.assertNotIn(ids[0], present)
        self.assertIn(ids[1], present)
        stored = {s["id"] for s in self.store.load("observed_session")}
        self.assertEqual(stored, present)

    def test_sessions_reload_from_store(self):
        self.model.record(event("Stop"))
        self.model.record(event("SessionEnd", session=OTHER))
        reloaded = ObservedSessions(self.store, clock=self.clock)
        self.assertEqual(self.session(MAIN, reloaded)["status"], "active")
        self.assertEqual(self.session(OTHER, reloaded)["status"], "ended")
        self.assertEqual(self.session(MAIN, reloaded)["project"], "alpha")
        # a malformed stored record is dropped, not trusted
        self.store.put("observed_session", {"id": "bad id!", "project": FAKE_KEY})
        self.assertEqual(len(ObservedSessions(self.store, clock=self.clock).snapshot()["sessions"]), 2)

    def test_store_error_keeps_state_and_does_not_raise(self):
        failing = FailingStore()
        model = ObservedSessions(failing, clock=self.clock)
        model.record(event("Stop"))
        approval_id = model.add_pending(permission(), HeldRequest(), self.clock() + 60)
        self.assertGreater(failing.calls, 0)
        self.assertEqual(self.session(MAIN, model)["status"], "active")
        self.assertEqual(model.answer(approval_id, "allow"), "ok")

    def test_concurrent_records_are_safe(self):
        def worker(n):
            for i in range(50):
                self.model.record(event("Stop", session="00000000-0000-4000-8000-%06d%06d" % (n, i % 5)))
        threads = [threading.Thread(target=worker, args=(n,)) for n in range(6)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(len(self.model.snapshot()["sessions"]), 30)
        self.assertEqual(len(self.store.load("observed_session")), 30)

    # approvals

    def test_pending_cap_refuses_and_counts(self):
        model = ObservedSessions(self.store, clock=self.clock, max_pending=3)
        helds = [HeldRequest() for _ in range(5)]
        ids = [model.add_pending(permission(), held, self.clock() + 60) for held in helds]
        self.assertTrue(all(ids[:3]))
        self.assertEqual(ids[3:], [None, None])
        snap = model.snapshot()
        self.assertEqual(snap["refused"], 2)
        self.assertEqual(snap["limits"]["max_pending"], 3)
        self.assertEqual(len(snap["approvals"]), 3)
        self.assertIsNone(helds[3].decision)  # a refused request is never answered by the model
        helds[0].wait(0)
        model.finish(ids[0])
        self.assertIsNotNone(model.add_pending(permission(), HeldRequest(), self.clock() + 60))
        self.assertEqual(model.snapshot()["refused"], 2)
        self.assertEqual(self.model.snapshot()["limits"]["max_pending"], 32)
        self.assertEqual(self.model.snapshot()["limits"]["max_sessions"], 256)

    def test_card_fields(self):
        approval_id, _ = self.pending(permission(agent_id=AGENT, agent_type="synthetic-worker"), wait=120)
        card = self.card(approval_id)
        self.assertEqual(card["session_id"], MAIN)
        self.assertEqual(card["project"], "alpha")
        self.assertEqual(card["tool_name"], "Bash")
        self.assertIn("echo synthetic", card["summary"])
        self.assertEqual(card["agent_type"], "synthetic-worker")
        self.assertEqual(card["status"], "pending")
        self.assertIsNone(card["decided_by"])
        self.assertIsNone(card["decision"])
        self.assertEqual(card["outcome"], "unknown")
        self.assertIsNone(card["decided_at"])
        self.assertEqual(card["expires_at"], self.clock.now + 120)
        self.assertEqual(card["created_at"], self.clock.now)
        self.assertIsNone(card["warning"])
        # add_pending also records the session
        self.assertEqual(self.session()["status"], "active")
        with self.assertRaises(ValueError):
            self.model.add_pending(event("Stop"), HeldRequest(), self.clock() + 60)

    def test_credential_shaped_cwd_and_input_never_in_snapshot_or_store(self):
        cwd = "/synthetic/" + FAKE_KEY + "/" + FAKE_KEY
        ev = permission({"command": "curl -H 'Authorization: Bearer " + FAKE_KEY + "' https://example.invalid"},
                        cwd=cwd)
        approval_id = self.model.add_pending(ev, HeldRequest(), self.clock() + 60)
        self.model.record(post({"command": "printf " + FAKE_KEY}, cwd=cwd))
        card = self.card(approval_id)
        self.assertEqual(card["summary"], "withheld")
        self.assertEqual(card["project"], "unknown")
        self.assertEqual(self.session()["project"], "unknown")
        dumped = json.dumps(self.model.snapshot())
        stored = json.dumps(self.store.load("observed_session"))
        for text in (dumped, stored):
            self.assertNotIn(FAKE_KEY, text)
            self.assertNotIn("sk-", text)
            self.assertNotIn("/synthetic", text)
            self.assertNotIn("curl", text)

    @unittest.skipUnless(shutil.which("gitleaks"), "reviewed secret scanner not installed")
    def test_real_scanner_withholds_token_shaped_input_and_cwd(self):
        # A token-shaped value built at runtime from a hash of a fixed label: high entropy, obviously fake.
        token = "ghp_" + hashlib.sha256(b"observed-synthetic").hexdigest()[:36]
        with patch("dashboard.conversation.scan_preview", wraps=project_files.scan_preview):
            model = ObservedSessions(self.store, clock=self.clock)
            safe = model.add_pending(permission({"command": "echo plain"}, session=OTHER), HeldRequest(), 1.0)
            ev = permission({"command": "echo " + token}, cwd="/synthetic/" + token)
            approval_id = model.add_pending(ev, HeldRequest(), self.clock() + 60)
        cards = {c["id"]: c for c in model.snapshot()["approvals"]}
        self.assertEqual(cards[safe]["summary"], '{"command":"echo plain"}')
        self.assertEqual(cards[safe]["project"], "alpha")
        self.assertEqual(cards[approval_id]["summary"], "withheld")
        self.assertEqual(cards[approval_id]["project"], "unknown")
        self.assertNotIn(token, json.dumps(model.snapshot()))
        self.assertNotIn(token, json.dumps(self.store.load("observed_session")))

    def test_unsafe_text_input_is_withheld_by_review_pipeline(self):
        # parse_request already refuses this; the model re-checks with the managed review pipeline anyway
        ev = permission()
        unsafe = dataclasses.replace(ev.request, tool_input={"command": "echo ‮ reversed"})
        approval_id, _ = self.pending(dataclasses.replace(ev, request=unsafe))
        self.assertEqual(self.card(approval_id)["summary"], "withheld")
        self.assertNotIn("reversed", json.dumps(self.model.snapshot()))

    def test_snapshot_has_no_tool_input(self):
        long_value = "echo " + "word " * 400
        approval_id, _ = self.pending(permission({"command": long_value, "description": "synthetic"}))
        snap = self.model.snapshot()
        card = self.card(approval_id)

        def keys(value):
            if isinstance(value, dict):
                for key, item in value.items():
                    yield key
                    yield from keys(item)
            elif isinstance(value, list):
                for item in value:
                    yield from keys(item)
        self.assertNotIn("tool_input", set(keys(snap)))
        self.assertNotIn(long_value, json.dumps(snap))
        self.assertLessEqual(len(card["summary"]), 300)
        self.assertNotIn("cwd", set(keys(snap)))
        self.assertEqual(set(snap), {"sessions", "approvals", "refused", "limits"})

    def test_answer_ok_resolves_held_first_wins(self):
        approval_id, held = self.pending()
        self.clock.now += 4
        self.assertEqual(self.model.answer(approval_id, "deny"), "ok")
        self.assertEqual(held.decision, "deny")
        card = self.card(approval_id)
        self.assertEqual((card["status"], card["decided_by"], card["decision"], card["decided_at"]),
                         ("answered", "dashboard", "deny", self.clock.now))
        self.assertEqual(self.model.answer(approval_id, "allow"), "closed")
        self.assertEqual(held.decision, "deny")
        with self.assertRaises(ValueError):
            self.model.answer(approval_id, "maybe")

    def test_answer_after_close_reports_closed_and_does_not_resolve(self):
        approval_id, held = self.pending()
        held.wait(0)  # the hold timed out
        self.model.finish(approval_id)
        card = self.card(approval_id)
        self.assertEqual((card["status"], card["decided_by"], card["decision"]), ("closed", "timed out", None))
        self.assertEqual(self.model.answer(approval_id, "allow"), "closed")
        self.assertEqual(self.card(approval_id)["decision"], None)

        other_id, other = self.pending()
        other.mark_closed()  # the client went away
        self.model.finish(other_id)
        self.assertEqual(self.card(other_id)["status"], "closed")
        self.assertEqual(self.card(other_id)["decided_by"], "unknown")
        self.assertEqual(self.model.answer(other_id, "allow"), "closed")

        # an answer racing a hold that already ended (before finish ran) reports closed
        third_id, third = self.pending()
        third.wait(0)
        self.assertEqual(self.model.answer(third_id, "allow"), "closed")
        self.assertEqual(third.decision, "deny")

        # a card closed by inference cannot be answered and its hold is not resolved
        fourth_id, fourth = self.pending(permission({"command": "echo fourth"}))
        self.model.record(event("Stop"))
        self.assertEqual(self.model.answer(fourth_id, "allow"), "closed")
        self.assertIsNone(fourth.decision)

    def test_finish_after_dashboard_answer_keeps_decision(self):
        approval_id, held = self.pending()
        self.model.answer(approval_id, "allow")
        held.wait(0)
        self.model.finish(approval_id)
        card = self.card(approval_id)
        self.assertEqual((card["status"], card["decided_by"], card["decision"]), ("answered", "dashboard", "allow"))
        self.model.finish(approval_id)  # repeat is harmless
        self.model.finish("no-such-id")

    def test_answer_unknown_id(self):
        self.assertEqual(self.model.answer("0" * 32, "allow"), "unknown")
        self.assertEqual(self.model.answer("", "deny"), "unknown")

    # two-way record (spec 5.2)

    def test_post_tool_use_match_closes_card_as_terminal_inferred_ran(self):
        approval_id, held = self.pending(permission({"command": "echo a", "timeout": 5}))
        self.clock.now += 7
        self.model.record(post({"timeout": 5, "command": "echo a"}))
        card = self.card(approval_id)
        self.assertEqual((card["status"], card["decided_by"], card["decision"], card["outcome"]),
                         ("closed", "terminal (inferred)", None, "ran"))
        self.assertEqual(card["decided_at"], self.clock.now)
        self.assertIsNone(card["warning"])
        self.assertIsNone(held.decision)
        # the hold ending later does not overwrite the inference
        held.wait(0)
        self.model.finish(approval_id)
        self.assertEqual(self.card(approval_id)["decided_by"], "terminal (inferred)")
        self.assertEqual(self.card(approval_id)["outcome"], "ran")

    def test_match_after_timeout_is_terminal_inferred(self):
        approval_id, held = self.pending()
        held.wait(0)
        self.model.finish(approval_id)
        self.model.record(post())
        card = self.card(approval_id)
        self.assertEqual((card["decided_by"], card["outcome"]), ("terminal (inferred)", "ran"))

    def test_identical_requests_match_one_card_each(self):
        first, _ = self.pending()
        second, _ = self.pending()
        self.model.record(post())
        self.assertEqual(self.card(first)["outcome"], "ran")
        self.assertEqual(self.card(second)["outcome"], "unknown")
        self.assertEqual(self.card(second)["status"], "pending")
        self.model.record(post())
        self.assertEqual(self.card(second)["outcome"], "ran")

    def test_later_other_event_closes_card_as_not_run(self):
        enders = {"other_call": lambda: post({"command": "echo b"}),
                  "other_tool": lambda: post({"command": "echo synthetic"}, tool_name="Read"),
                  "stop": lambda: event("Stop"),
                  "session_end": lambda: event("SessionEnd")}
        for name, make in enders.items():
            with self.subTest(name):
                approval_id, held = self.pending()
                self.clock.now += 1
                self.model.record(make())
                card = self.card(approval_id)
                self.assertEqual((card["status"], card["decided_by"], card["outcome"], card["decided_at"]),
                                 ("closed", "terminal (inferred)", "not run", self.clock.now))
                self.assertIsNone(held.decision)
                # a later matching event does not change a settled outcome
                self.model.record(post())
                self.assertEqual(self.card(approval_id)["outcome"], "not run")
                self.model.finish(approval_id)

    def test_other_session_does_not_close_card(self):
        approval_id, _ = self.pending()
        self.model.record(event("Stop", session=OTHER))
        self.model.record(post({"command": "echo b"}, session=OTHER))
        self.model.record(event("SessionEnd", session=OTHER))
        self.assertEqual(self.card(approval_id)["status"], "pending")
        self.assertEqual(self.card(approval_id)["outcome"], "unknown")

    def test_subagent_event_does_not_close_main_session_card(self):
        main_id, _ = self.pending()
        sub_id, _ = self.pending(permission(agent_id=AGENT, agent_type="synthetic-worker"))
        # subagent events never touch the main card
        self.model.record(post({"command": "echo other"}, agent_id=AGENT))
        self.model.record(event("SubagentStop", agent_id=AGENT, agent_type="synthetic-worker"))
        self.assertEqual(self.card(main_id)["status"], "pending")
        self.assertEqual(self.card(main_id)["outcome"], "unknown")
        self.assertEqual(self.card(sub_id)["outcome"], "not run")
        # a matching main-session PostToolUse does not satisfy another agent's card
        other_sub, _ = self.pending(permission(agent_id="agent-synthetic-9", agent_type="synthetic-worker"))
        self.model.record(post())
        self.assertEqual(self.card(main_id)["outcome"], "ran")
        self.assertEqual(self.card(other_sub)["outcome"], "unknown")
        self.model.record(event("Stop"))
        self.assertEqual(self.card(other_sub)["outcome"], "unknown")
        self.assertEqual(self.card(other_sub)["status"], "pending")

    def test_post_tool_use_after_dashboard_allow_records_ran(self):
        approval_id, _ = self.pending()
        self.model.answer(approval_id, "allow")
        decided_at = self.card(approval_id)["decided_at"]
        self.clock.now += 3
        self.model.record(post())
        card = self.card(approval_id)
        self.assertEqual((card["status"], card["decided_by"], card["decision"], card["outcome"]),
                         ("answered", "dashboard", "allow", "ran"))
        self.assertEqual(card["decided_at"], decided_at)
        self.assertIsNone(card["warning"])

    def test_post_tool_use_after_dashboard_deny_raises_warning_flag(self):
        approval_id, _ = self.pending()
        self.model.answer(approval_id, "deny")
        self.model.record(post())
        card = self.card(approval_id)
        self.assertEqual((card["decided_by"], card["decision"], card["outcome"]), ("dashboard", "deny", "ran"))
        self.assertEqual(card["warning"], "ran although denied here")

    def test_unmatched_card_stays_unknown_not_guessed(self):
        approval_id, held = self.pending()
        # events that are not evidence: no tool input, other sessions, subagent lifecycle, permission requests
        self.model.record(event("PostToolUse", tool_name="Bash"))
        self.model.record(event("PostToolUse"))
        self.model.record(event("SessionStart"))
        self.model.record(permission({"command": "echo next"}))
        self.model.record(event("SubagentStart", agent_id=AGENT, agent_type="synthetic-worker"))
        card = self.card(approval_id)
        self.assertEqual((card["status"], card["outcome"], card["decided_by"]), ("pending", "unknown", None))
        held.wait(0)
        self.model.finish(approval_id)
        self.clock.now += 99999
        card = self.card(approval_id)
        self.assertEqual((card["outcome"], card["decided_by"]), ("unknown", "timed out"))


if __name__ == "__main__":
    unittest.main()
