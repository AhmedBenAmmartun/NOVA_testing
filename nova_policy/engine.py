"""Central permission, confirmation, and auditing system for NOVA."""

from __future__ import annotations

import json
import secrets
import threading
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import IntEnum
from pathlib import Path


AsyncAction = Callable[[], Awaitable[str]]


class PermissionLevel(IntEnum):
    """Risk level assigned to a NOVA action."""

    READ_ONLY = 0
    REVERSIBLE = 1
    SENSITIVE = 2
    RESTRICTED = 3


#: The only actor kinds NOVA recognizes. Anything else is a forgery attempt.
_PRINCIPAL_KINDS = frozenset({"user", "worker", "system"})


@dataclass(frozen=True, slots=True)
class Principal:
    """WHO is asking for an action.

    The permission engine used to have no notion of an actor: every call site
    passed the literal string ``"voice"``, so a request from an internal worker
    would have been byte-for-byte indistinguishable from Ahmed asking. That
    matters most for session grants -- keyed only by action name, one human
    approval would have silently authorized unlimited worker invocations of
    that action for the rest of the session -- and for the audit log, which
    could not attribute anything after an incident.

    A Principal is minted by TRUSTED CODE through the constructors below. It
    must never be built from model output or a tool argument: if the model
    could hand over ``principal="user"``, the whole boundary would be
    decorative. That is why ``kind`` is validated against a closed set rather
    than accepted as free text.
    """

    kind: str
    id: str
    #: Which principal spawned this one, for the delegation chain in the audit
    #: log. Attribution needs the chain, not just the leaf.
    parent: str | None = None

    def __post_init__(self) -> None:
        if self.kind not in _PRINCIPAL_KINDS:
            raise ValueError(
                f"Unknown principal kind {self.kind!r}. "
                f"Expected one of {sorted(_PRINCIPAL_KINDS)}."
            )
        if not str(self.id).strip():
            raise ValueError("A principal must have an id.")

    @classmethod
    def user(cls, id: str = "ahmed") -> "Principal":
        """The human at the keyboard or microphone. The only approver."""
        return cls(kind="user", id=id)

    @classmethod
    def worker(cls, id: str, *, parent: str | None = None) -> "Principal":
        """An internal NOVA worker. Never an approver, never a default."""
        return cls(kind="worker", id=id, parent=parent)

    @classmethod
    def system(cls, id: str) -> "Principal":
        """Scheduled or background NOVA machinery acting on its own."""
        return cls(kind="system", id=id)

    @property
    def is_user(self) -> bool:
        return self.kind == "user"

    @property
    def key(self) -> str:
        """Stable identity for grant keying and audit records."""
        return f"{self.kind}:{self.id}"


@dataclass(frozen=True, slots=True)
class ActionPolicy:
    """Security policy assigned to one NOVA action."""

    name: str
    level: PermissionLevel
    confirmation_message: str = ""
    timeout_seconds: int = 60
    allow_session_approval: bool = False
    #: Whether a non-user principal may invoke this action at all.
    #: Default False on purpose: a policy that has not thought about workers
    #: has not authorized them. Opting in must be a deliberate act.
    worker_invocable: bool = False


@dataclass(slots=True)
class PendingAction:
    """An action waiting for the user's approval."""

    action_id: str
    policy: ActionPolicy
    summary: str
    executor: AsyncAction = field(repr=False)
    session_id: str = "voice"
    created_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    expires_at: datetime = field(
        default_factory=lambda: (
            datetime.now(timezone.utc)
            + timedelta(seconds=60)
        )
    )


class PermissionEngine:
    """Authorize, confirm, deny, execute, and audit NOVA actions."""

    def __init__(self, *, audit_path: Path | str | None = None) -> None:
        project_root = Path(__file__).resolve().parent.parent

        self.audit_path = (
            Path(audit_path)
            if audit_path is not None
            else project_root / "audit_logs" / "nova_actions.jsonl"
        )

        self.audit_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        self._policies: dict[str, ActionPolicy] = {}
        self._pending: dict[str, PendingAction] = {}
        self._session_grants: set[tuple[str, str]] = set()
        self._lock = threading.RLock()

        self.safe_mode = False

    def register(self, policy: ActionPolicy) -> None:
        """Register or replace an action policy."""

        with self._lock:
            self._policies[policy.name] = policy

    def get_policy(
        self,
        action_name: str,
    ) -> ActionPolicy | None:
        """Return a registered policy."""

        with self._lock:
            return self._policies.get(action_name)

    async def run(
        self,
        action_name: str,
        summary: str,
        executor: AsyncAction,
        *,
        principal: Principal,
        session_id: str = "voice",
    ) -> str:
        """
        Authorize and possibly execute an action.

        Read-only and reversible actions normally run immediately.
        Sensitive actions wait for confirmation.
        Restricted actions are blocked.
        """

        policy = self.get_policy(action_name)

        if policy is None:
            self._audit(
                action=action_name,
                status="denied",
                summary=summary,
                reason="No registered permission policy",
            )

            return (
                f"NOVA refused '{action_name}' because it does not "
                "have a registered permission policy."
            )

        if (
            self.safe_mode
            and policy.level > PermissionLevel.READ_ONLY
        ):
            self._audit(
                action=action_name,
                status="denied",
                summary=summary,
                reason="Safe Mode enabled",
            )

            return (
                "NOVA Safe Mode is enabled. Actions that change "
                "the computer are temporarily blocked."
            )

        if policy.level == PermissionLevel.RESTRICTED:
            self._audit(
                action=action_name,
                status="denied",
                summary=summary,
                reason="Restricted action",
            )

            return (
                f"'{action_name}' is restricted and disabled "
                "by default."
            )

        # A non-user principal may only touch actions that deliberately opted
        # in. Checked BEFORE session grants, so no amount of prior human
        # approval can promote a worker into an action it was never allowed.
        if not principal.is_user and not policy.worker_invocable:
            self._audit(
                action=action_name,
                status="denied",
                summary=summary,
                reason="Principal is not permitted to invoke this action",
                principal=principal,
            )
            return (
                f"NOVA refused '{action_name}': it may only be performed at "
                "Ahmed's request, not by an internal worker."
            )

        # Grants are keyed by PRINCIPAL, not by a shared session string. When
        # every caller passed the literal "voice", one human approval would
        # have silently authorized every worker for the rest of the session.
        session_key = (
            f"{session_id}|{principal.key}",
            action_name,
        )

        already_approved = (
            session_key in self._session_grants
        )

        if (
            policy.level <= PermissionLevel.REVERSIBLE
            or already_approved
        ):
            return await self._execute(
                action_name=action_name,
                summary=summary,
                executor=executor,
                principal=principal,
            )

        # Carry the principal-scoped key onto the pending action, so that an
        # approval grants authority to the principal who asked -- and to nobody
        # else.
        return self._create_confirmation(
            policy=policy,
            summary=summary,
            executor=executor,
            session_id=session_key[0],
        )

    async def approve(
        self,
        action_id: str = "latest",
        *,
        scope: str = "once",
        principal: Principal | None = None,
    ) -> str:
        """Approve and execute a pending action.

        Only a user principal may approve. Enforced here in trusted code rather
        than by leaving the method undecorated: a worker that could approve its
        own request would make every confirmation tier decorative, and the
        absence of a ``@function_tool`` is a convention, not a boundary.
        """

        actor = principal or Principal.user()
        if not actor.is_user:
            self._audit(
                action="approve",
                status="denied",
                summary=f"Approval attempted for {action_id}",
                reason="Only a user principal may approve an action",
                principal=actor,
            )
            return (
                "NOVA refused that approval: only Ahmed can approve a pending "
                "action, not an internal worker."
            )

        pending = self._resolve_pending(action_id)

        if pending is None:
            return "There is no matching pending NOVA action."

        now = datetime.now(timezone.utc)

        if pending.expires_at <= now:
            self._remove_pending(
                pending.action_id
            )

            self._audit(
                action=pending.policy.name,
                status="expired",
                summary=pending.summary,
                action_id=pending.action_id,
            )

            return (
                "That confirmation request expired. "
                "Ask NOVA to perform the action again."
            )

        normalized_scope = (
            scope
            .strip()
            .lower()
            .replace("-", "_")
        )

        if normalized_scope not in {
            "once",
            "session",
        }:
            return (
                "Approval scope must be 'once' "
                "or 'session'."
            )

        if normalized_scope == "session":
            if not pending.policy.allow_session_approval:
                return (
                    "This action can only be approved once. "
                    "Session approval is not allowed."
                )

            with self._lock:
                self._session_grants.add(
                    (
                        pending.session_id,
                        pending.policy.name,
                    )
                )

        self._remove_pending(
            pending.action_id
        )

        self._audit(
            action=pending.policy.name,
            status="approved",
            summary=pending.summary,
            action_id=pending.action_id,
            approval_scope=normalized_scope,
        )

        return await self._execute(
            action_name=pending.policy.name,
            summary=pending.summary,
            executor=pending.executor,
            action_id=pending.action_id,
        )

    def deny(
        self,
        action_id: str = "latest",
    ) -> str:
        """Deny and remove a pending action."""

        pending = self._resolve_pending(action_id)

        if pending is None:
            return "There is no matching pending NOVA action."

        self._remove_pending(
            pending.action_id
        )

        self._audit(
            action=pending.policy.name,
            status="denied",
            summary=pending.summary,
            action_id=pending.action_id,
            reason="User denied confirmation",
        )

        return f"Cancelled: {pending.summary}"

    def list_pending(self) -> str:
        """List actions currently waiting for approval."""

        self._remove_expired()

        with self._lock:
            pending_actions = list(
                self._pending.values()
            )

        if not pending_actions:
            return "There are no pending NOVA actions."

        pending_actions.sort(
            key=lambda item: item.created_at
        )

        now = datetime.now(timezone.utc)
        lines = ["Pending NOVA actions:"]

        for pending in pending_actions:
            remaining = max(
                0,
                int(
                    (
                        pending.expires_at
                        - now
                    ).total_seconds()
                ),
            )

            lines.append(
                f"- {pending.action_id}: "
                f"{pending.summary} "
                f"({remaining} seconds remaining)"
            )

        return "\n".join(lines)

    def set_safe_mode(
        self,
        enabled: bool,
    ) -> str:
        """Enable or disable NOVA Safe Mode."""

        enabled = bool(enabled)

        with self._lock:
            self.safe_mode = enabled

            if enabled:
                pending_count = len(
                    self._pending
                )

                self._pending.clear()
                self._session_grants.clear()
            else:
                pending_count = 0

        self._audit(
            action="safe_mode",
            status=(
                "enabled"
                if enabled
                else "disabled"
            ),
            summary=(
                "NOVA Safe Mode changed. "
                f"Cancelled pending actions: {pending_count}"
            ),
        )

        if enabled:
            return (
                "NOVA Safe Mode is enabled. "
                "All computer-changing actions are blocked, "
                "and pending actions were cancelled."
            )

        return "NOVA Safe Mode is disabled."

    def clear_session(
        self,
        session_id: str = "voice",
    ) -> None:
        """Remove temporary approvals and pending actions for one session."""

        # Grant keys are "<session>|<principal>", so clearing a session must
        # match on the session half and drop every principal's grants within
        # it. Comparing the whole key would silently leak grants across a
        # session boundary.
        def _same_session(key: str) -> bool:
            return key.split("|", 1)[0] == session_id

        with self._lock:
            self._session_grants = {
                grant
                for grant in self._session_grants
                if not _same_session(grant[0])
            }
            pending_ids = [
                action_id
                for action_id, pending in self._pending.items()
                if _same_session(pending.session_id)
            ]
            for action_id in pending_ids:
                self._pending.pop(action_id, None)

    def _create_confirmation(
        self,
        policy: ActionPolicy,
        summary: str,
        executor: AsyncAction,
        session_id: str,
    ) -> str:
        self._remove_expired()

        action_id = secrets.token_hex(3)
        now = datetime.now(timezone.utc)

        pending = PendingAction(
            action_id=action_id,
            policy=policy,
            summary=summary,
            executor=executor,
            session_id=session_id,
            created_at=now,
            expires_at=(
                now
                + timedelta(
                    seconds=policy.timeout_seconds
                )
            ),
        )

        with self._lock:
            self._pending[action_id] = pending

        self._audit(
            action=policy.name,
            status="confirmation_required",
            summary=summary,
            action_id=action_id,
        )

        scope_message = ""

        if policy.allow_session_approval:
            scope_message = (
                " You may approve it once or "
                "for this session."
            )

        return (
            "Confirmation required. "
            f"{policy.confirmation_message} "
            f"Action ID: {action_id}."
            f"{scope_message}"
        )

    async def _execute(
        self,
        action_name: str,
        summary: str,
        executor: AsyncAction,
        action_id: str | None = None,
        principal: Principal | None = None,
    ) -> str:
        self._audit(
            action=action_name,
            status="started",
            summary=summary,
            action_id=action_id,
            principal=principal,
        )

        try:
            result = await executor()

            self._audit(
                action=action_name,
                status="completed",
                summary=summary,
                action_id=action_id,
                principal=principal,
            )

            return result

        except Exception as error:
            self._audit(
                action=action_name,
                status="failed",
                summary=summary,
                action_id=action_id,
                principal=principal,
                reason=type(error).__name__,
            )

            return (
                f"NOVA could not complete '{action_name}'. "
                "The failure was recorded in the audit log."
            )

    def _resolve_pending(
        self,
        action_id: str,
    ) -> PendingAction | None:
        self._remove_expired()

        cleaned_id = (
            action_id
            .strip()
            .lower()
        )

        with self._lock:
            if cleaned_id != "latest":
                return self._pending.get(
                    cleaned_id
                )

            if not self._pending:
                return None

            return max(
                self._pending.values(),
                key=lambda item: item.created_at,
            )

    def _remove_pending(
        self,
        action_id: str,
    ) -> None:
        with self._lock:
            self._pending.pop(
                action_id,
                None,
            )

    def _remove_expired(self) -> None:
        now = datetime.now(timezone.utc)

        with self._lock:
            expired = [
                pending
                for pending in self._pending.values()
                if pending.expires_at <= now
            ]

            for pending in expired:
                self._pending.pop(
                    pending.action_id,
                    None,
                )

        for pending in expired:
            self._audit(
                action=pending.policy.name,
                status="expired",
                summary=pending.summary,
                action_id=pending.action_id,
            )

    @staticmethod
    def _safe_summary(
        summary: str,
    ) -> str:
        """Remove obvious secret-related information from audit summaries."""

        cleaned = " ".join(
            summary
            .replace("\r", " ")
            .replace("\n", " ")
            .split()
        )

        sensitive_terms = (
            "password",
            "api key",
            "api_key",
            "secret",
            "access token",
            "refresh token",
            ".env",
            ".spotify_cache",
        )

        lowered = cleaned.lower()

        if any(
            term in lowered
            for term in sensitive_terms
        ):
            return "[Sensitive action summary redacted]"

        return cleaned[:300]

    def _audit(
        self,
        *,
        action: str,
        status: str,
        summary: str,
        action_id: str | None = None,
        reason: str | None = None,
        approval_scope: str | None = None,
        principal: Principal | None = None,
    ) -> None:
        """Write action metadata without saving private contents."""

        record = {
            "timestamp": datetime.now(
                timezone.utc
            ).isoformat(),
            "action": action,
            "status": status,
            "summary": self._safe_summary(
                summary
            ),
            "action_id": action_id,
            "reason": reason,
            "approval_scope": approval_scope,
            # Without an actor and its delegation chain, a post-incident review
            # cannot say who caused an action -- only that it happened.
            "principal": principal.key if principal else None,
            "principal_parent": principal.parent if principal else None,
        }

        try:
            with self.audit_path.open(
                "a",
                encoding="utf-8",
            ) as audit_file:
                audit_file.write(
                    json.dumps(
                        record,
                        ensure_ascii=False,
                    )
                    + "\n"
                )
        except OSError:
            # An audit-log failure must not crash NOVA.
            pass


permission_engine = PermissionEngine()


DEFAULT_POLICIES = (
    ActionPolicy(
        name="close_app",
        level=PermissionLevel.SENSITIVE,
        confirmation_message=(
            "Closing the application could discard "
            "unsaved work. Do you approve?"
        ),
        timeout_seconds=60,
    ),
    ActionPolicy(
        name="restart_app",
        level=PermissionLevel.SENSITIVE,
        confirmation_message=(
            "Restarting the application could discard "
            "unsaved work. Do you approve?"
        ),
        timeout_seconds=60,
    ),
    ActionPolicy(
        name="capture_screen",
        level=PermissionLevel.SENSITIVE,
        confirmation_message=(
            "This will capture everything visible on "
            "all connected screens. Do you approve?"
        ),
        timeout_seconds=45,
        allow_session_approval=True,
    ),
    ActionPolicy(
        name="analyze_screen_with_gpt56",
        level=PermissionLevel.SENSITIVE,
        confirmation_message=(
            "This will capture your screen and share "
            "the image with OpenAI for analysis. "
            "Do you approve?"
        ),
        timeout_seconds=45,
    ),
    ActionPolicy(
        name="send_to_recycle_bin",
        level=PermissionLevel.SENSITIVE,
        confirmation_message=(
            "This will move the selected item to the "
            "Windows Recycle Bin. Do you approve?"
        ),
        timeout_seconds=60,
    ),
    ActionPolicy(
        name="send_email",
        level=PermissionLevel.SENSITIVE,
        confirmation_message=(
            "This will send a message to another person. "
            "Do you approve?"
        ),
        timeout_seconds=60,
    ),
    ActionPolicy(
        name="permanent_delete",
        level=PermissionLevel.RESTRICTED,
    ),
    ActionPolicy(
        name="arbitrary_shell_command",
        level=PermissionLevel.RESTRICTED,
    ),
    ActionPolicy(
        name="install_software",
        level=PermissionLevel.RESTRICTED,
    ),
    ActionPolicy(
        name="disable_security",
        level=PermissionLevel.RESTRICTED,
    ),
)


for policy in DEFAULT_POLICIES:
    permission_engine.register(
        policy
    )
