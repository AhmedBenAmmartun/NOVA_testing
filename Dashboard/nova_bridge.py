"""Private, local command bridge shared by NOVA and its desktop dashboard.

Vendored copy for standalone (dashboard-only) runs: server.py only reaches
this file when Dashboard/ has no agent.py next to it, i.e. it isn't nested
inside the full NOVA repo. When embedded in NOVA, the real module at the
repo root (imported by agent.py and nova_agent_bridge.py too, so the live
agent and the dashboard share the same on-disk bridge state) takes
precedence via server.py's sys.path ordering — this copy is never loaded
there. Keep both copies in sync if this logic ever changes; the only
intentional difference is the default bridge directory below (this copy's
project_root is already Dashboard/, so no extra "Dashboard" path segment).

The dashboard and LiveKit agent run in separate processes.  This module moves
small, validated command envelopes between them using atomic file renames.  It
does not transport credentials, environment variables, file contents, or
arbitrary executable code.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import time
from pathlib import Path
from typing import Any


CONTRACT = "nova.local-command.v1"
MAX_COMMAND_TEXT = 1_000
MAX_RESULT_TEXT = 500
MAX_PENDING_COMMANDS = 100
DEFAULT_COMMAND_TTL_SECONDS = 120
# The heartbeat loop reports every ~1s, but a single long NOVA response
# (speaking for 8-10+ seconds) can outlast a tight threshold and made the
# dashboard flash "Agent offline" mid-conversation even though nothing was
# actually wrong - widened 2026-07-27 after observing exactly that.
ACTIVE_HEARTBEAT_SECONDS = 15
AGENT_STATUS_HEARTBEAT_SECONDS = 15
STALE_CLAIM_SECONDS = 5 * 60

_SAFE_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_AGENT_PHASES = frozenset({"starting", "idle", "listening", "thinking", "speaking", "tool_running", "error"})


class BridgeValidationError(ValueError):
    """Raised when a dashboard command fails the local bridge contract."""


def _clean_text(value: Any, *, limit: int) -> str:
    if not isinstance(value, str):
        return ""
    return " ".join(value.replace("\x00", " ").split())[:limit]


class CommandStore:
    """Atomic on-disk inbox/outbox for one local NOVA installation."""

    def __init__(self, root: Path | str | None = None) -> None:
        project_root = Path(__file__).resolve().parent
        configured = os.getenv("NOVA_BRIDGE_DIR")
        selected = Path(root or configured or project_root / "runtime" / "bridge")
        self.root = selected if selected.is_absolute() else project_root / selected
        self.inbox = self.root / "inbox"
        self.processing = self.root / "processing"
        self.results = self.root / "results"
        self.state_path = self.root / "active_session.json"

    def _ensure(self) -> None:
        for directory in (self.root, self.inbox, self.processing, self.results):
            directory.mkdir(parents=True, exist_ok=True)
            try:
                directory.chmod(0o700)
            except OSError:
                pass

    @staticmethod
    def _read_json(path: Path) -> dict[str, Any] | None:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        return value if isinstance(value, dict) else None

    def _write_atomic(self, directory: Path, name: str, payload: dict[str, Any]) -> Path:
        self._ensure()
        temporary = directory / f".{name}.{secrets.token_hex(4)}.tmp"
        destination = directory / name
        data = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        with temporary.open("x", encoding="utf-8") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            temporary.chmod(0o600)
        except OSError:
            pass
        os.replace(temporary, destination)
        return destination

    def active_session(self) -> dict[str, Any]:
        """Backward-compatible command-routing heartbeat state."""
        state = self._read_json(self.state_path) or {}
        session_id = state.get("session_id")
        heartbeat_at = state.get("heartbeat_at")
        active = (
            isinstance(session_id, str)
            and bool(_SAFE_ID.fullmatch(session_id))
            and isinstance(heartbeat_at, (int, float))
            and time.time() - float(heartbeat_at) <= ACTIVE_HEARTBEAT_SECONDS
        )
        return {
            "active": active,
            "session_id": session_id if active else None,
            "heartbeat_at": heartbeat_at if active else None,
        }

    def agent_status(self) -> dict[str, Any]:
        """Detailed short-timeout status used only by the dashboard display."""
        state = self._read_json(self.state_path) or {}
        session_id = state.get("session_id")
        heartbeat_at = state.get("heartbeat_at")
        heartbeat_age = (
            max(0.0, time.time() - float(heartbeat_at))
            if isinstance(heartbeat_at, (int, float))
            else None
        )
        active = (
            isinstance(session_id, str)
            and bool(_SAFE_ID.fullmatch(session_id))
            and heartbeat_age is not None
            and heartbeat_age <= AGENT_STATUS_HEARTBEAT_SECONDS
        )
        phase = state.get("phase") if state.get("phase") in _AGENT_PHASES else "idle"
        if not active:
            phase = "offline"
        return {
            "active": active,
            "session_id": session_id if active else None,
            "heartbeat_at": heartbeat_at if active else None,
            "heartbeat_age": heartbeat_age if active else None,
            "started_at": state.get("started_at") if active else None,
            "last_transition_at": state.get("last_transition_at") if active else None,
            "pid": state.get("pid") if active else None,
            "phase": phase,
            "status": phase,
            "route": state.get("route") if active else None,
            "model": state.get("model") if active else None,
            "detail": state.get("detail") if active else None,
        }

    @staticmethod
    def _normalize_phase(phase: str | None) -> str:
        cleaned = _clean_text(phase, limit=32).lower()
        if cleaned not in _AGENT_PHASES:
            raise BridgeValidationError("Invalid NOVA agent phase")
        return cleaned

    def heartbeat(
        self,
        session_id: str,
        *,
        phase: str | None = None,
        route: str | None = None,
        model: str | None = None,
        detail: str | None = None,
    ) -> None:
        if not _SAFE_ID.fullmatch(session_id):
            raise BridgeValidationError("Invalid bridge session ID")
        now = time.time()
        existing = self._read_json(self.state_path) or {}
        same_session = existing.get("session_id") == session_id
        started_at = existing.get("started_at") if same_session else now
        previous_phase = existing.get("phase") if same_session else None
        selected_phase = self._normalize_phase(phase or previous_phase or "starting")
        last_transition_at = (
            existing.get("last_transition_at")
            if same_session and previous_phase == selected_phase
            else now
        )
        payload: dict[str, Any] = {
            "contract": CONTRACT,
            "session_id": session_id,
            "started_at": started_at,
            "heartbeat_at": now,
            "pid": os.getpid(),
        }
        has_status = phase is not None or (same_session and "phase" in existing)
        if has_status:
            payload.update(
                {
                    "last_transition_at": last_transition_at,
                    "phase": selected_phase,
                    "route": _clean_text(route, limit=80)
                    or (existing.get("route") if same_session else None),
                    "model": _clean_text(model, limit=160)
                    or (existing.get("model") if same_session else None),
                    "detail": _clean_text(detail, limit=200) or None,
                }
            )
        self._write_atomic(self.root, self.state_path.name, payload)

    def update_agent_status(
        self,
        session_id: str,
        phase: str,
        *,
        route: str | None = None,
        model: str | None = None,
        detail: str | None = None,
    ) -> None:
        """Publish an immediate phase transition and refresh the heartbeat."""
        self.heartbeat(
            session_id,
            phase=phase,
            route=route,
            model=model,
            detail=detail,
        )

    def clear_heartbeat(self, session_id: str) -> None:
        current = self._read_json(self.state_path) or {}
        if current.get("session_id") != session_id:
            return
        try:
            self.state_path.unlink()
        except OSError:
            pass

    def enqueue_delegate(self, text: str) -> dict[str, Any]:
        cleaned = _clean_text(text, limit=MAX_COMMAND_TEXT)
        if not cleaned:
            raise BridgeValidationError("Delegated text is empty")
        return self._enqueue("delegate", {"text": cleaned})

    def enqueue_approval(
        self,
        action_id: str,
        decision: str,
        *,
        scope: str = "once",
    ) -> dict[str, Any]:
        action_id = _clean_text(action_id, limit=64)
        decision = _clean_text(decision, limit=16).lower()
        scope = _clean_text(scope, limit=16).lower()
        if not _SAFE_ID.fullmatch(action_id):
            raise BridgeValidationError("Invalid approval action ID")
        if decision not in {"approve", "deny"}:
            raise BridgeValidationError("Decision must be approve or deny")
        if scope not in {"once", "session"}:
            raise BridgeValidationError("Approval scope must be once or session")
        return self._enqueue(
            "approval",
            {"action_id": action_id, "decision": decision, "scope": scope},
        )

    def _enqueue(self, kind: str, payload: dict[str, Any]) -> dict[str, Any]:
        self._ensure()
        if len(list(self.inbox.glob("*.json"))) >= MAX_PENDING_COMMANDS:
            raise BridgeValidationError("The dashboard command queue is full")
        now = time.time()
        command_id = secrets.token_hex(12)
        active = self.active_session()
        command = {
            "contract": CONTRACT,
            "id": command_id,
            "kind": kind,
            "created_at": now,
            "expires_at": now + DEFAULT_COMMAND_TTL_SECONDS,
            "target_session": active["session_id"],
            "payload": payload,
        }
        self._write_atomic(self.inbox, f"{command_id}.json", command)
        return command

    @staticmethod
    def _valid_command(command: dict[str, Any]) -> bool:
        base_valid = (
            command.get("contract") == CONTRACT
            and isinstance(command.get("id"), str)
            and bool(_SAFE_ID.fullmatch(command["id"]))
            and command.get("kind") in {"delegate", "approval"}
            and isinstance(command.get("payload"), dict)
            and isinstance(command.get("expires_at"), (int, float))
            and (
                command.get("target_session") is None
                or (
                    isinstance(command.get("target_session"), str)
                    and bool(_SAFE_ID.fullmatch(command["target_session"]))
                )
            )
        )
        if not base_valid:
            return False
        payload = command["payload"]
        if command["kind"] == "delegate":
            text = payload.get("text")
            return isinstance(text, str) and 0 < len(text.strip()) <= MAX_COMMAND_TEXT
        action_id = payload.get("action_id")
        return (
            isinstance(action_id, str)
            and bool(_SAFE_ID.fullmatch(action_id))
            and payload.get("decision") in {"approve", "deny"}
            and payload.get("scope", "once") in {"once", "session"}
        )

    def _recover_stale_claims(self) -> None:
        cutoff = time.time() - STALE_CLAIM_SECONDS
        for path in self.processing.glob("*.json"):
            try:
                if path.stat().st_mtime >= cutoff:
                    continue
            except OSError:
                continue
            command = self._read_json(path)
            if not command or not self._valid_command(command):
                try:
                    path.unlink()
                except OSError:
                    pass
                continue
            if float(command["expires_at"]) <= time.time():
                self.complete(path, command, "expired", "Dashboard command expired before NOVA could run it.")
                continue
            try:
                os.replace(path, self.inbox / f"{command['id']}.json")
            except OSError:
                pass

    def claim(self, session_id: str, *, limit: int = 10) -> list[tuple[Path, dict[str, Any]]]:
        if not _SAFE_ID.fullmatch(session_id):
            raise BridgeValidationError("Invalid bridge session ID")
        self._ensure()
        self._recover_stale_claims()
        claimed: list[tuple[Path, dict[str, Any]]] = []
        for path in sorted(self.inbox.glob("*.json")):
            if len(claimed) >= max(1, min(limit, 25)):
                break
            command = self._read_json(path)
            if not command or not self._valid_command(command):
                try:
                    path.unlink()
                except OSError:
                    pass
                continue
            target_session = command.get("target_session")
            if target_session and target_session != session_id:
                continue
            destination = self.processing / f"{session_id}-{command['id']}.json"
            try:
                os.replace(path, destination)
            except OSError:
                continue
            if float(command["expires_at"]) <= time.time():
                self.complete(destination, command, "expired", "Dashboard command expired before NOVA could run it.")
                continue
            claimed.append((destination, command))
        return claimed

    def complete(
        self,
        claimed_path: Path,
        command: dict[str, Any],
        status: str,
        message: str,
    ) -> None:
        if status not in {"completed", "failed", "expired"}:
            raise BridgeValidationError("Invalid command result status")
        command_id = str(command.get("id", ""))
        if not _SAFE_ID.fullmatch(command_id):
            raise BridgeValidationError("Invalid command result ID")
        result = {
            "contract": CONTRACT,
            "id": command_id,
            "kind": command.get("kind"),
            "status": status,
            "completed_at": time.time(),
            "message": _clean_text(message, limit=MAX_RESULT_TEXT),
        }
        self._write_atomic(self.results, f"{command_id}.json", result)
        try:
            claimed_path.unlink()
        except OSError:
            pass

    def read_results(self, *, limit: int = 25) -> list[dict[str, Any]]:
        self._ensure()
        results: list[dict[str, Any]] = []
        for path in sorted(self.results.glob("*.json"))[: max(1, min(limit, 100))]:
            result = self._read_json(path)
            try:
                path.unlink()
            except OSError:
                continue
            if (
                result
                and result.get("contract") == CONTRACT
                and result.get("status") in {"completed", "failed", "expired"}
                and result.get("kind") in {"delegate", "approval"}
            ):
                results.append(result)
        return results


command_store = CommandStore()
