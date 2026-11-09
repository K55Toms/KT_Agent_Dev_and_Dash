"""The owner's own Claude Code terminal sessions (observed sessions) and their approval cards.

Thread-safe: the listener calls this from its handler threads. One lock guards the in-memory state.
Secret scanning runs before the lock is taken, and the store is written after it is released (under a
separate store lock, so writes are not reordered). A store error is swallowed: the in-memory state is
kept and nothing is raised to the caller.

Stored (SQLite kind ``observed_session``): ids and status only, never a summary, tool input or path.
Approval cards are in memory only. The raw tool input of a card is kept only for matching (as its
canonical JSON) and never leaves through ``snapshot()``.

Two-way record (spec 5.2): later events of the same session and the same agent (``agent_id`` None for
the main session) settle a card's outcome. A ``post_tool_use`` with the same ``tool_name`` and equal
``tool_input`` means the call ran; ``stop`` means the agent moved on, so the call did not run; and
``session_end`` (no ``agent_id``) settles every agent's cards of that session as not run. A
``post_tool_use`` for another call is not evidence (parallel calls). A ``post_tool_use`` without
``tool_input`` (same tool or no tool name) might have been the card's call, so a later ``stop`` or
``session_end`` then settles the card with outcome ``unknown`` instead of ``not run``. Without evidence the
outcome stays ``unknown``. Inference never resolves a held request: the terminal stays in charge.

Session ids pass the same scan as the project name. An id the scan refuses is shown and stored only as an
opaque stable id (``s-`` and 12 hex digits of its SHA-256); the real id is kept in memory for matching.
"""
import hashlib
import json
import re
import threading
import time
import uuid
from typing import Optional

from .approval_review import ReviewError, bounded as review_bytes
from .backends.claude_hook import _SESSION
from .conversation import safe_text
from .hook_http import HeldRequest
from .observed_hook import ObservedEvent

KIND = "observed_session"
SUMMARY_MAX = 240
PROJECT_MAX = 255
MAX_FINISHED_CARDS = 64
WITHHELD = "withheld"
INFERRED = "terminal (inferred)"
DENIED_WARNING = "ran although denied here"
_MOVED_ON = ("stop", "session_end")
_SEPARATORS = re.compile(r"[/\\]")
MAX_RETRY_DELETES = 1024
SESSION_ID_MAX = 200
_SESSION_KEYS = ("id", "project", "first_seen", "last_seen", "status", "subagent_seen_at")


def _canonical(tool_input) -> Optional[str]:
    """Exact JSON form for equality (so 1, 1.0 and true stay distinct); None if it cannot be encoded."""
    try:
        return json.dumps(tool_input, sort_keys=True, ensure_ascii=False, allow_nan=False,
                          separators=(",", ":"))
    except (TypeError, ValueError, RecursionError):
        return None


def _scanned(text, maximum) -> Optional[str]:
    """The text if it passes the dashboard's plain-text and secret checks, else None."""
    try:
        return safe_text(text, maximum=maximum)
    except (ValueError, TypeError, UnicodeError, RecursionError):
        return None


def project_name(cwd) -> str:
    """Final path segment of ``cwd`` after the scan; ``unknown`` when absent or refused."""
    if not isinstance(cwd, str):
        return "unknown"
    name = _SEPARATORS.split(cwd.rstrip("/\\"))[-1]  # POSIX or Windows-style separators
    if not name or len(name) > PROJECT_MAX:
        return "unknown"
    return _scanned(name, PROJECT_MAX) or "unknown"


def opaque_session_id(session_id: str) -> str:
    """The stable id shown and stored in place of a session id the scan refuses."""
    return "s-" + hashlib.sha256(session_id.encode("utf-8")).hexdigest()[:12]


def _card_texts(request):
    """(summary, tool_name, agent_type) for display, through the managed card's review pipeline."""
    params = {"tool_name": request.tool_name, "tool_input": request.tool_input}
    if request.agent_type is not None:
        params["agent_type"] = request.agent_type
    summary = None
    try:
        encoded = review_bytes(params)
        if _scanned(encoded.decode("utf-8"), len(encoded)) is not None:
            text = review_bytes(request.tool_input).decode("utf-8")
            summary = text if len(text) <= SUMMARY_MAX else text[:SUMMARY_MAX - 1] + "…"
    except (ReviewError, ValueError, TypeError, UnicodeError, RecursionError):
        summary = None
    if summary is not None:
        return summary, request.tool_name, request.agent_type
    # The full request was refused: show the short identifiers only if they pass on their own.
    labels = request.tool_name if request.agent_type is None else request.tool_name + "\n" + request.agent_type
    if _scanned(labels, 200) is not None:
        return WITHHELD, request.tool_name, request.agent_type
    return WITHHELD, WITHHELD, None if request.agent_type is None else WITHHELD


def _valid_session(record) -> bool:
    if not isinstance(record, dict) or not isinstance(record.get("id"), str) or not _SESSION.match(record["id"]):
        return False
    number = (int, float)
    return (isinstance(record.get("project"), str) and len(record["project"]) <= PROJECT_MAX
            and isinstance(record.get("first_seen"), number) and isinstance(record.get("last_seen"), number)
            and record.get("status") in ("active", "ended")
            and (record.get("subagent_seen_at") is None or isinstance(record["subagent_seen_at"], number)))


class ObservedSessions:
    def __init__(self, store, clock=time.time, quiet_seconds=1800, max_sessions=256, max_pending=32):
        self._store = store
        self._clock = clock
        self.quiet_seconds = quiet_seconds
        self.max_sessions = max_sessions
        self.max_pending = max_pending
        self._lock = threading.Lock()
        self._store_lock = threading.Lock()
        self._sessions = {}
        self._cards = {}      # approval id -> public card (insertion order = creation order)
        self._held = {}       # approval id -> HeldRequest, until finish()
        self._evidence = {}   # approval id -> (session key, agent_id, tool_name, canonical input)
        self._maybe_ran = set()  # approval ids that saw a PostToolUse without tool_input that could be theirs
        self._aliases = {}    # real session id the scan refused -> its opaque id (memory only, never stored)
        self._retry_deletes = set()  # evicted session ids whose store delete has not succeeded yet
        self._refused = 0
        try:
            loaded = store.load(KIND)
        except Exception:  # an unreadable store starts empty rather than failing the dashboard
            loaded = []
        for record in loaded:
            if _valid_session(record):
                self._sessions[record["id"]] = {key: record[key] for key in _SESSION_KEYS}
        pruned = []
        while len(self._sessions) > max_sessions:
            victim = self._victim(None)
            del self._sessions[victim]
            pruned.append(victim)
        if pruned:  # rows beyond the cap leave the store too, not only memory
            self._persist([], pruned)

    # sessions

    def record(self, event: ObservedEvent) -> None:
        if not isinstance(event, ObservedEvent):
            raise ValueError("bad_event")
        self._record(event)

    def _record(self, event) -> str:
        """Record the event; returns the session's key (its id, or the opaque id when the scan refused it)."""
        with self._lock:
            key = self._known(event.session_id)
        project = clean = None
        if key is None:  # scans run outside the lock, once per new session
            project = project_name(event.cwd)
            clean = _scanned(event.session_id, SESSION_ID_MAX) is not None
        with self._lock:
            if key is None:
                key = self._known(event.session_id)
            if key is None:
                key = event.session_id if clean else self._alias(event.session_id)
            evicted = self._touch(key, event, project)
            self._infer(key, event)
        self._persist([key], evicted)
        return key

    def _known(self, session_id):
        """The key of a session already seen in memory, else None (caller holds the lock)."""
        if session_id in self._aliases:
            return self._aliases[session_id]
        return session_id if session_id in self._sessions else None

    def _alias(self, session_id):
        opaque = opaque_session_id(session_id)
        self._aliases[session_id] = opaque
        return opaque

    def _touch(self, key, event, project):
        now = self._clock()
        session = self._sessions.get(key)
        evicted = []
        if session is None:
            session = {"id": key, "project": project or project_name(None), "first_seen": now,
                       "last_seen": now, "status": "active", "subagent_seen_at": None}
            self._sessions[key] = session
            while len(self._sessions) > self.max_sessions:
                victim = self._victim(key)
                del self._sessions[victim]
                evicted.append(victim)
            if evicted:
                gone = set(evicted)
                for real in [real for real, opaque in self._aliases.items() if opaque in gone]:
                    del self._aliases[real]
        session["last_seen"] = now
        session["status"] = "ended" if event.kind == "session_end" else "active"
        if event.agent_id is not None or event.kind in ("subagent_start", "subagent_stop"):
            session["subagent_seen_at"] = now
        return evicted

    def _victim(self, keep):
        # oldest ended first, then the oldest by last activity (quiet sessions are the oldest active ones)
        candidates = [s for s in self._sessions.values() if s["id"] != keep]
        return min(candidates, key=lambda s: (s["status"] != "ended", s["last_seen"]))["id"]

    def _persist(self, session_ids, evicted):
        """Write the touched sessions and delete the evicted ones, with every delete that failed before.

        A failed delete stays in a bounded retry set, so the next successful write removes the row."""
        with self._store_lock:
            with self._lock:
                puts = [(KIND, dict(self._sessions[s])) for s in session_ids if s in self._sessions]
                self._retry_deletes.update(evicted)
                self._retry_deletes.difference_update(self._sessions)  # a returning session is not deleted
                while len(self._retry_deletes) > MAX_RETRY_DELETES:
                    self._retry_deletes.pop()
                deletes = sorted(self._retry_deletes)
            try:
                self._store.put_many(puts, [(KIND, s) for s in deletes])
            except Exception:  # the in-memory state stays authoritative; the next write retries the record
                return
            with self._lock:
                self._retry_deletes.difference_update(deletes)

    # inference (caller holds the lock)

    def _infer(self, key, event):
        if event.kind not in ("post_tool_use",) + _MOVED_ON:
            return
        now = self._clock()
        # session_end carries no agent_id and ends every agent of the session (R11); the others are per agent
        mine = [i for i, (session, agent, _, _) in self._evidence.items()
                if session == key and (event.kind == "session_end" or agent == event.agent_id)]
        if event.kind != "post_tool_use":
            for approval_id in mine:
                # moved on: not run, unless an incomplete PostToolUse may have been this very call
                self._settle(approval_id, "unknown" if approval_id in self._maybe_ran else "not run", now)
            return
        # Only a match is evidence. A PostToolUse for another call proves nothing (R10): a parallel sibling
        # call can finish while this card's prompt is still open.
        canonical = None if event.tool_input is None else _canonical(event.tool_input)
        for approval_id in mine:
            _, _, tool_name, card_input = self._evidence[approval_id]
            if canonical is None or event.tool_name is None:
                # incomplete: cannot prove the call ran, but it may have been this one
                if (event.tool_name in (None, tool_name)) and canonical in (None, card_input):
                    self._maybe_ran.add(approval_id)
                continue
            if event.tool_name == tool_name and canonical == card_input:
                self._settle(approval_id, "ran", now)
                return

    def _settle(self, approval_id, outcome, now):
        card = self._cards[approval_id]
        del self._evidence[approval_id]
        self._maybe_ran.discard(approval_id)
        card["outcome"] = outcome
        if card["decided_by"] == "dashboard":
            if outcome == "ran" and card["decision"] == "deny":
                card["warning"] = DENIED_WARNING
            return
        card.update(status="closed", decided_by=INFERRED, decided_at=now)

    # approvals

    def add_pending(self, event: ObservedEvent, held: HeldRequest, expires_at: float) -> Optional[str]:
        """Record the event's session and open a card for its held request. None when the pending cap is
        reached (the request is then left alone, so Claude's own prompt stays in charge)."""
        if not isinstance(event, ObservedEvent) or event.kind != "permission_request" or event.request is None:
            raise ValueError("bad_event")
        key = self._record(event)
        with self._lock:
            if len(self._held) >= self.max_pending:
                self._refused += 1
                return None
        summary, tool_name, agent_type = _card_texts(event.request)
        canonical = _canonical(event.request.tool_input)
        with self._lock:
            if len(self._held) >= self.max_pending:
                self._refused += 1
                return None
            now = self._clock()
            session = self._sessions.get(key)
            approval_id = uuid.uuid4().hex
            self._cards[approval_id] = {
                "id": approval_id, "session_id": key,
                "project": session["project"] if session else project_name(None),
                "tool_name": tool_name, "summary": summary, "agent_type": agent_type, "status": "pending",
                "decided_by": None, "decision": None, "outcome": "unknown", "decided_at": None,
                "expires_at": expires_at, "created_at": now, "warning": None}
            self._held[approval_id] = held
            if canonical is not None:
                self._evidence[approval_id] = (key, event.agent_id, event.request.tool_name, canonical)
            self._trim_cards()
            return approval_id

    def _trim_cards(self):
        finished = [i for i in self._cards if i not in self._held]
        for approval_id in finished[:max(0, len(finished) - MAX_FINISHED_CARDS)]:
            del self._cards[approval_id]
            self._evidence.pop(approval_id, None)
            self._maybe_ran.discard(approval_id)

    def finish(self, approval_id: str) -> None:
        """Called after a hold ended. A card still pending closes as timed out or unknown (connection
        closed); a card already answered or settled by inference keeps its record."""
        with self._lock:
            held = self._held.pop(approval_id, None)
            card = self._cards.get(approval_id)
            if held is None or card is None:
                return
            if card["status"] == "pending":
                card.update(status="closed", decided_by="timed out" if held.expired else "unknown")
            self._trim_cards()

    def answer(self, approval_id: str, decision: str) -> str:
        if decision not in ("allow", "deny"):
            raise ValueError("bad_decision")
        with self._lock:
            card = self._cards.get(approval_id)
            if card is None:
                return "unknown"
            held = self._held.get(approval_id)
            if card["status"] != "pending" or held is None or not held.resolve(decision):
                return "closed"
            card.update(status="answered", decided_by="dashboard", decision=decision, decided_at=self._clock())
            return "ok"

    def snapshot(self) -> dict:
        with self._lock:
            now = self._clock()
            sessions = []
            for session in sorted(self._sessions.values(), key=lambda s: s["last_seen"], reverse=True):
                view = dict(session)
                if view["status"] == "active" and now - view["last_seen"] >= self.quiet_seconds:
                    view["status"] = "quiet"
                sessions.append(view)
            approvals = [dict(card) for card in reversed(list(self._cards.values()))]
            return {"sessions": sessions, "approvals": approvals, "refused": self._refused,
                    "limits": {"max_sessions": self.max_sessions, "max_pending": self.max_pending,
                               "quiet_seconds": self.quiet_seconds}}
