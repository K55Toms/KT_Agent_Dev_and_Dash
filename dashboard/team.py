"""Observed team roster and an immutable, nonmonetary recognition ledger.

Only the server's authenticated Chief of Staff tool handler may call issue_award.
Task identity and authority are rechecked against its trusted dashboard task map;
there is deliberately no browser/manual award API.
"""

from copy import deepcopy
from datetime import datetime, timezone
from dataclasses import dataclass
import hashlib
import json

from dashboard.project_files import FileAccessError, scan_preview


PROFILES = {
    "chief_of_staff": ("Mara Vale", "Coordinate product delivery, task ownership, dependencies, integration, and release evidence."),
    "product_manager": ("Elias Renn", "Define the product, users, scope, priorities and testable acceptance criteria."),
    "technical_architect": ("Soren Hale", "Own cross-system architecture, contracts, dependency decisions and migration design."),
    "backend_developer": ("Kira Voss", "Implement backend services, data models, APIs and integrations against agreed requirements."),
    "frontend_developer": ("Theo Arden", "Implement agreed UI designs, accessible components and backend integration."),
    "ui_designer": ("Lina Cass", "Design user journeys, accessible interactions, screen states and component specifications."),
    "qa_engineer": ("Juno Mercer", "Verify acceptance criteria independently with behavioural, integration and adversarial tests."),
    "security_reviewer": ("Dax Corven", "Independently review threat boundaries, authorization, credential handling and security controls."),
    "code_quality_reviewer": ("Nadia Quinn", "Independently review correctness, architecture, maintainability and test adequacy."),
    "platform_reliability_engineer": ("Owen Drake", "Own secure delivery pipelines, environments, observability, recovery and dependency maintenance."),
    "agent_evaluation_engineer": ("Iris Wren", "Evaluate agent task quality, routing, handoffs, security compliance and cost per accepted result."),
    "technical_writer": ("Felix Ward", "Maintain verified developer setup, API documentation, architecture notes and runbooks."),
    "user_documentation_writer": ("Amara Reed", "Write user guidance and release notes grounded in verified delivered behaviour."),
    "expert_escalation": ("Silas Knox", "On-demand Astra specialist for consequential ambiguity, difficult defects or sensitive reviews."),
}
AWARD_FIELDS = {"id", "issuer", "source_task", "source_event_id", "recipient_id", "kind", "coins", "reason", "issued_at", "week"}
MAX_WEEKLY_COINS = 100
MAX_AWARD_COINS = 20
MAX_AWARDS = 10000


class TeamError(ValueError):
    """A safe error suitable for the scoped native tool response."""


def _now():
    return datetime.now(timezone.utc)


def _week(instant):
    year, week, _ = instant.isocalendar()
    return f"{year}-W{week:02d}"


def _task_map(tasks):
    values = tasks.values() if isinstance(tasks, dict) else tasks
    return {task["id"]: task for task in values}


def _identifier(value, label):
    if (not isinstance(value, str) or not value or len(value) > 160
            or any(ord(char) < 33 or ord(char) > 126 for char in value)):
        raise TeamError(f"Invalid {label}")
    return value


@dataclass(frozen=True, repr=False, slots=True)
class _PreparedReason:
    # Opaque, immutable proof used only between trusted backend methods.
    # Default object repr intentionally does not expose the text.
    nonce: object
    reason: str


class Team:
    def __init__(self, store, roles):
        self.store = store
        self._reason_nonce = object()
        self.roles = {key: deepcopy(value) for key, value in roles.items() if key in PROFILES}

    def _awards(self):
        # A hard bound fails closed rather than silently omitting reward history.
        rows = self.store.db.execute(
            "SELECT body FROM records WHERE kind='team_award' ORDER BY rowid LIMIT ?",
            (MAX_AWARDS + 1,)).fetchall()
        if len(rows) > MAX_AWARDS:
            raise TeamError("Recognition ledger requires maintenance")
        try:
            awards = [json.loads(row[0]) for row in rows]
            for award in awards:
                if not isinstance(award, dict) or set(award) != AWARD_FIELDS:
                    raise ValueError
                if (award["issuer"] != "chief_of_staff"
                        or not isinstance(award["recipient_id"], str)
                        or award["recipient_id"] not in PROFILES
                        or award["recipient_id"] == "chief_of_staff"
                        or not isinstance(award["kind"], str)
                        or award["kind"] not in {"rebel_coins", "agent_of_week"}
                        or type(award["coins"]) is not int
                        or not 1 <= award["coins"] <= MAX_AWARD_COINS):
                    raise ValueError
                source = _identifier(award["source_task"], "source task")
                event = _identifier(award["source_event_id"], "source event")
                expected = hashlib.sha256((source + "\0" + event).encode("utf-8")).hexdigest()
                issued = datetime.fromisoformat(award["issued_at"])
                if (award["id"] != expected or self._reason_text(award["reason"]) != award["reason"]
                        or issued.tzinfo is None or _week(issued.astimezone(timezone.utc)) != award["week"]):
                    raise ValueError
            return awards
        except (TypeError, ValueError):
            raise TeamError("Recognition ledger could not be read safely") from None

    def snapshot(self, tasks):
        task_values = list(_task_map(tasks).values())
        with self.store.lock:
            awards = self._awards()
        current_week = _week(_now())
        members = []
        for role_id, (name, description) in PROFILES.items():
            if role_id not in self.roles:
                continue
            role = self.roles[role_id]
            observed = [task for task in task_values if task.get("role") == role_id]
            activities = []
            for task in sorted(observed, key=lambda item: (item.get('updated_at', ''), item.get('created_at', ''), item['id']), reverse=True):
                activity = {key: task.get(key) for key in (
                    'id', 'project_id', 'role', 'title', 'status', 'created_at',
                    'updated_at', 'thread_id', 'parent_thread_id', 'parent_task_id')}
                activity['source'] = 'delegated' if task.get('parent_task_id') else 'direct'
                activities.append(activity)
            latest = max(observed, key=lambda task: (task.get("updated_at", ""), task.get("created_at", ""), task["id"])) if observed else None
            last_task = ({key: latest.get(key) for key in ("id", "title", "status", "updated_at", "last_summary", "parent_task_id")}
                         if latest is not None else None)
            if last_task is not None and latest.get("last_summary_source") != "model-reported":
                last_task["last_summary"] = None
            received = [award for award in awards if award["recipient_id"] == role_id]
            members.append({
                "id": role_id, "name": name, "role": role.get("label", role_id.replace("_", " ").title()),
                "description": role.get("description", description),
                "portrait": f"/team-portraits/{role_id}.svg", "model": role.get("model"),
                "reasoning": role.get("reasoning"), "last_task": deepcopy(last_task),
                "activities": deepcopy(activities),
                "coins": sum(award["coins"] for award in received),
                "agent_of_week": any(award["kind"] == "agent_of_week" and award["week"] == current_week for award in received),
            })
        # All-time totals remain complete; only recent history is sent to the UI.
        return {"members": members, "awards": deepcopy(list(reversed(awards[-100:]))) }

    @staticmethod
    def _reason_text(reason):
        if (not isinstance(reason, str) or not reason.strip() or len(reason) > 500
                or any(ord(char) < 32 or ord(char) == 127 for char in reason)):
            raise TeamError("Provide a short plain-text recognition reason")
        return reason.strip()

    def prepare_reason(self, reason):
        """Scan outside Dashboard.lock; return a nonserializable, private proof.

        This proves content scanning only, never award authority. The caller must
        recheck the native request binding and task state before issuing an award.
        """
        reason = self._reason_text(reason)
        try:
            scan_preview(reason.encode("utf-8"))
        except FileAccessError:
            raise TeamError("Recognition withheld: sensitive-content checks did not pass") from None
        return _PreparedReason(self._reason_nonce, reason)

    def issue_award(self, source_task, recipient_id, kind, coins, reason, source_event_id, tasks, *, prepared_reason=None):
        """Record a genuine CoS tool request, revalidating canonical task authority.

        The caller holds the dashboard lock while passing its current task map.
        The native tool handler binds source_task/event identity to the live RPC;
        clients and model arguments cannot supply an issuer or source task.
        """
        if not isinstance(source_task, dict):
            raise TeamError("A live Chief of Staff task is required")
        task_id = _identifier(source_task.get("id"), "source task")
        event_id = _identifier(source_event_id, "source event")
        canonical = _task_map(tasks).get(task_id)
        if (not canonical or canonical.get("role") != "chief_of_staff"
                or canonical.get("status") not in {"running", "waiting_approval"}
                or not canonical.get("thread_id") or not canonical.get("turn_id")
                or any(source_task.get(key) != canonical.get(key)
                       for key in ("role", "status", "thread_id", "turn_id"))):
            raise TeamError("Only the active Chief of Staff task can issue recognition")
        if not isinstance(recipient_id, str) or recipient_id not in self.roles or recipient_id == "chief_of_staff":
            raise TeamError("Choose a known teammate other than the issuing Chief of Staff")
        if not isinstance(kind, str) or kind not in {"rebel_coins", "agent_of_week"}:
            raise TeamError("Choose a supported recognition kind")
        if type(coins) is not int or not 1 <= coins <= MAX_AWARD_COINS:
            raise TeamError("Recognition requires between 1 and 20 Rebel coins")
        if not any(task.get("role") == recipient_id and task.get("status") == "completed"
                   for task in _task_map(tasks).values()):
            raise TeamError("Recognition requires an observed completed teammate task")
        reason = self._reason_text(reason)
        # Event IDs are runtime-scoped opaque values and must not carry free text.
        if any(char not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-.:/" for char in event_id):
            raise TeamError("Invalid source event")
        award_id = hashlib.sha256((task_id + "\0" + event_id).encode("utf-8")).hexdigest()
        payload = {"issuer": "chief_of_staff", "source_task": task_id, "source_event_id": event_id,
                   "recipient_id": recipient_id, "kind": kind, "coins": coins, "reason": reason}
        if prepared_reason is None:
            self.prepare_reason(reason)
        elif (type(prepared_reason) is not _PreparedReason
              or prepared_reason.nonce is not self._reason_nonce
              or prepared_reason.reason != reason):
            raise TeamError("Recognition content must pass its own sensitive-content check")
        instant = _now()
        award = {"id": award_id, **payload, "issued_at": instant.isoformat(timespec="seconds"), "week": _week(instant)}
        # BEGIN IMMEDIATE also serializes separate Store instances against the same
        # database. Never use Store.put's INSERT OR REPLACE for immutable awards.
        with self.store.lock:
            self.store.db.execute("BEGIN IMMEDIATE")
            try:
                awards = self._awards()
                duplicate = next((entry for entry in awards if entry["id"] == award_id), None)
                if duplicate:
                    if any(duplicate[key] != value for key, value in payload.items()):
                        raise TeamError("The recognition event was already recorded with different details")
                    self.store.db.commit()
                    return deepcopy(duplicate)
                if len(awards) >= MAX_AWARDS:
                    raise TeamError("Recognition ledger requires maintenance")
                if any(entry["source_task"] == task_id and entry["recipient_id"] == recipient_id for entry in awards):
                    raise TeamError("This task already recognized that teammate")
                weekly = [entry for entry in awards if entry["week"] == award["week"]]
                if sum(entry["coins"] for entry in weekly if entry["recipient_id"] == recipient_id) + coins > MAX_WEEKLY_COINS:
                    raise TeamError("This teammate has reached the weekly Rebel coin limit")
                if kind == "agent_of_week" and any(entry["kind"] == kind for entry in weekly):
                    raise TeamError("Agent of the Week was already issued this UTC week")
                self.store.db.execute("INSERT INTO records VALUES (?,?,?)", ("team_award", award_id, json.dumps(award)))
                self.store.db.commit()
                return deepcopy(award)
            except BaseException:
                self.store.db.rollback()
                raise
