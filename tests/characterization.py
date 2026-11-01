"""Helpers for the Codex characterization tests (not a test module).

The characterization tests pin what ``Dashboard`` projects into ``snapshot()`` after scripted Codex
messages, so a later refactor can be proven behaviour-preserving. Goldens live in
``tests/fixtures/characterization/<file>.json``: one JSON object mapping golden names to normalized
snapshots. Set ``CHARACTERIZE=1`` to (re)write the entries a test checks; review the diff and commit.

The goldens hold the synthetic policy's ``sha256``, ``pricing_date`` and ``source`` values. That is an
accepted exception to "synthetic values only": they describe the test policy, not a real one.

Tests that need the reviewed secret scanner use ``require_scanner()``: they skip locally when gitleaks is
missing, but fail when ``CI=true`` so a CI run can never pass without having scanned.
"""
import functools
import json
import os
from pathlib import Path
import re
import tempfile
import time
import unittest

from dashboard.project_files import FileAccessError, SensitiveContentError, scan_preview
from dashboard.server import Dashboard
from tests.policy_fixtures import SyntheticPolicy
from tests.test_dashboard_backend import FakeClient

GOLDEN_DIRECTORY = Path(__file__).resolve().parent / "fixtures" / "characterization"
UUID = re.compile(r"\b(?:[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}|[0-9a-f]{32})\b")
TIMESTAMP = re.compile(r"\b\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})?")
# Top-level snapshot lists whose item ids get a readable ordinal prefix.
ID_PREFIXES = (("projects", "project"), ("tasks", "task"), ("approvals", "approval"), ("questions", "question"))
# Configuration-derived or machine-specific values that say nothing about run state, and hashes
# computed from timestamps and ids (so they differ on every run).
DROPPED_KEYS = {"roles", "pricing", "directory_identity", "attention_version", "deletion_version",
                "compliance_role_digest"}
TIMESTAMP_MARK = "<timestamp>"
PATH_MARK = "<path>"
ROOT_MARK = "<root>"

_scanner_state = {}


def scanner_available():
    """True when the reviewed secret scanner can scan (probed once with harmless text)."""
    if "ok" not in _scanner_state:
        try:
            scan_preview(b"synthetic harmless text\n")
            _scanner_state["ok"] = True
        except FileAccessError:
            _scanner_state["ok"] = False
    return _scanner_state["ok"]


def require_scanner():
    """Decorator (class or test function): skip locally without the scanner, fail in CI.

    Scanner and ``CI`` are read when the decorator is applied, like ``unittest.skipUnless``. For a class the check runs in
    ``setUp``, so every test in it is skipped or fails; the class is otherwise returned unchanged.
    """
    if scanner_available():
        return lambda target: target

    in_ci = os.environ.get("CI") == "true"

    def guard():
        if in_ci:
            raise AssertionError("Gitleaks is required in CI; the reviewed secret scanner is unavailable")
        raise unittest.SkipTest("reviewed secret scanner (gitleaks) is unavailable")

    def decorate(target):
        if isinstance(target, type):
            original = target.setUp

            @functools.wraps(original)
            def set_up(self):
                guard()
                original(self)

            target.setUp = set_up
            return target

        @functools.wraps(target)
        def wrapper(*args, **kwargs):
            guard()
            return target(*args, **kwargs)

        return wrapper

    return decorate


def require_scanner_to_characterize():
    """With CHARACTERIZE=1 a golden may only be written after the secret scan, so fail without the scanner."""
    if os.environ.get("CHARACTERIZE") == "1" and not scanner_available():
        raise AssertionError("CHARACTERIZE=1 needs the reviewed secret scanner (gitleaks); "
                             "refusing to normalize or write a golden that was not secret-scanned")


def normalize(snapshot, roots=()):
    """Return ``snapshot`` with ids, timestamps and paths made stable and keys sorted.

    uuid-like ids become ordinals (``task-1``, ``approval-1``); timestamps become ``<timestamp>``
    (a null stays null, so set-versus-unset is still visible); absolute paths become ``<path>`` and
    any ``roots`` prefix inside a string becomes ``<root>``. Raises AssertionError if the result
    contains a secret-looking value according to the project's reviewed scanner policy.
    """
    ids = {}

    def assign(value, prefix):
        if value not in ids:
            ids[value] = "%s-%d" % (prefix, sum(1 for v in ids.values() if v.startswith(prefix + "-")) + 1)

    if isinstance(snapshot, dict):
        for key, prefix in ID_PREFIXES:
            for item in snapshot.get(key) or []:
                if isinstance(item, dict) and isinstance(item.get("id"), str) and UUID.fullmatch(item["id"]):
                    assign(item["id"], prefix)

    def text(value):
        for root in roots:
            value = value.replace(str(root), ROOT_MARK)
        value = TIMESTAMP.sub(TIMESTAMP_MARK, value)
        for found in UUID.findall(value):
            assign(found, "id")
        return UUID.sub(lambda match: ids[match.group(0)], value)

    def walk(value, key=None):
        if isinstance(value, dict):
            return {k: walk(v, k) for k, v in sorted(value.items()) if k not in DROPPED_KEYS}
        if isinstance(value, (list, tuple)):
            return [walk(v) for v in value]
        if isinstance(value, str):
            if key and (key == "at" or key.endswith("_at")):
                return TIMESTAMP_MARK
            value = text(value)
            return PATH_MARK if value.startswith("/") and not value.startswith("//") else value
        return value

    result = walk(snapshot)
    require_scanner_to_characterize()
    if scanner_available():
        try:
            scan_preview(json.dumps(result, sort_keys=True, indent=2).encode())
        except SensitiveContentError:
            raise AssertionError("normalized snapshot contains a secret-looking value; it must not be recorded") from None
    return result


def _golden_path(file):
    return GOLDEN_DIRECTORY / (file + ".json")


def _load(file):
    path = _golden_path(file)
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def check_golden(testcase, file, name, actual):
    """Compare ``actual`` with entry ``name`` of golden file ``file``; with CHARACTERIZE=1 write it instead."""
    require_scanner_to_characterize()
    if os.environ.get("CHARACTERIZE") == "1":
        goldens = _load(file)
        goldens[name] = actual
        GOLDEN_DIRECTORY.mkdir(parents=True, exist_ok=True)
        _golden_path(file).write_text(json.dumps(goldens, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        # Record the write, then fail once the test body has finished so every checkpoint is written.
        if not getattr(testcase, "_golden_written", False):
            testcase._golden_written = True

            def fail():
                raise AssertionError("golden written, review and commit")
            testcase.addCleanup(fail)
        return
    goldens = _load(file)
    if name not in goldens:
        testcase.fail("golden %s.json has no entry %r; generate it with CHARACTERIZE=1 on the baseline and review it" % (file, name))
    testcase.assertEqual(goldens[name], actual, "projection differs from golden %s.json entry %r" % (file, name))


class ScriptedDashboard(unittest.TestCase):
    """Mixin: a Dashboard on a FakeClient, plus helpers to start a task and script Codex messages."""

    def setUp(self):
        # macOS: the suite assumes /private/tmp, as the existing tests and CI (macos-15) do.
        self.temp = tempfile.TemporaryDirectory(dir="/private/tmp")
        self.root = Path(self.temp.name).resolve()
        self.app = Dashboard(self.root / "state", policy_provider=SyntheticPolicy())
        self.fake = FakeClient()
        self.app.client = self.fake
        self.app.connection["status"] = "connected"
        self.project = self.app.add_project({"name": "Project One", "path": str(self.root)})

    def tearDown(self):
        self.app.close()
        self.temp.cleanup()

    def task(self):
        task = self.app.start_task({"project_id": self.project["id"], "title": "SYNTHETIC_TASK_TITLE",
                                    "instruction": "SYNTHETIC_PRIVATE_TASK_INSTRUCTION", "role": "backend_developer"})
        self.assertTrue(self.fake.started.wait(2))
        self.app.workers[-1].join(2)
        for _ in range(100):
            if self.app.tasks[task["id"]]["turn_id"]:
                return self.app.tasks[task["id"]]
            time.sleep(.005)
        self.fail("Task did not start")

    def event(self, method, **kwargs):
        self.app.on_message({"method": method, "params": {"threadId": "thread-one", "turnId": "turn-one", **kwargs}})

    def approval(self, task, rpc_id=17, method="item/commandExecution/requestApproval"):
        self.app.on_message({"id": rpc_id, "method": method, "params": {
            "threadId": task["thread_id"], "turnId": task["turn_id"],
            "command": "SYNTHETIC_PRIVATE_COMMAND", "reason": "SYNTHETIC_PRIVATE_REASON"}})
        return list(self.app.approvals.values())[-1]
