"""Handlers for actions the dashboard shell sends over the WebSocket.

Each handler returns a list of dashboard messages to broadcast back
(activity entries, notifications, refreshed task lists, ...). Agent prompts
and approval decisions cross the private local command bridge; they are never
executed by the dashboard process itself. "Forget" moves memory notes to the
vault's NOVA/.trash instead of deleting them.
"""

from __future__ import annotations

import ctypes
import os
from pathlib import Path

import feeds
from app_registry import perform_action, public_message, set_pinned
from security import can_open_recent_target, is_sensitive_path
from nova_bridge import BridgeValidationError, CommandStore, command_store

VIRTUAL_KEYS = {
    "playpause": 0xB3,
    "next": 0xB0,
    "previous": 0xB1,
}

def _press_key(vk_code: int) -> None:
    keyeventf_keyup = 0x0002
    ctypes.windll.user32.keybd_event(vk_code, 0, 0, 0)
    ctypes.windll.user32.keybd_event(vk_code, 0, keyeventf_keyup, 0)


def _activity(tag: str, text: str, status: str = "ok") -> dict:
    return {
        "type": "activity",
        "time": feeds.now_label(),
        "tag": tag,
        "text": text,
        "status": status,
    }


def _notify(title: str, text: str, icon: str = "◉") -> dict:
    return {"type": "notify", "icon": icon, "title": title, "text": text}


def _start(target: str) -> bool:
    try:
        os.startfile(target)  # noqa: S606 - launching user-chosen local apps
        return True
    except (OSError, AttributeError):
        return False


def handle(
    message: dict,
    targets: dict,
    approvals,
    bridge: CommandStore | None = None,
) -> list[dict]:
    """Dispatch one client action; returns messages to broadcast."""
    bridge = bridge or command_store
    kind = message.get("type")

    if kind == "media":
        action = str(message.get("action", ""))
        vk_code = VIRTUAL_KEYS.get(action)
        if vk_code is None:
            return []
        _press_key(vk_code)
        return [_activity("Tool", f'spotify.{action}()')]

    # Backward-compatible trusted-name action used by older NOVA clients and
    # regression tests. New dashboard code sends ``app_action`` with an opaque
    # registered ID. This branch never accepts a browser-supplied path: it only
    # resolves a name against the backend-owned target map.
    if kind == "launch":
        name = str(message.get("app", "")).strip()
        target = targets.get("apps", {}).get(name)
        if target is None:
            return [_notify("Apps", f"Could not find {name} on this PC.", "▣")]
        if not isinstance(target, str) or is_sensitive_path(target):
            return [_notify("Apps", "NOVA blocked a protected application target.", "▣")]
        if not _start(target):
            return [_notify("Apps", f"Windows refused to launch {name}.", "▣")]
        return [_activity("Tool", f'apps.launch("{name}")')]

    if kind == "app_action":
        app_id = message.get("id")
        action = str(message.get("action", "activate")).strip().lower()
        if not isinstance(app_id, str):
            return [_notify("Apps", "Invalid application request.", "▣")]
        ok, status = perform_action(targets.get("apps", {}), app_id.strip(), action)
        if not ok:
            text = "That application is not registered." if status == "invalid_app_id" else "Windows could not complete that application action."
            return [_notify("Apps", text, "▣")]
        return [_activity("Tool", f'apps.{status}("{app_id[:12]}")')]

    if kind == "pin_app":
        app_id = message.get("id")
        pinned = bool(message.get("pinned"))
        if not isinstance(app_id, str) or not set_pinned(targets.get("apps", {}), app_id.strip(), pinned):
            return [_notify("Apps", "That application is no longer registered.", "▣")]
        update = public_message(targets.get("apps", {}))
        update.update({"folders": list(targets.get("folders", {})), "recent": []})
        return [update, _activity("Tool", f'apps.pin("{app_id[:12]}", {str(pinned).lower()})')]

    if kind == "refresh_apps":
        update, refreshed = feeds.scan_apps()
        for key, value in refreshed.items():
            targets.setdefault(key, {}).clear()
            targets[key].update(value)
        return [update, _activity("Tool", "apps.refresh()")]

    if kind == "open_folder":
        name = str(message.get("name", "")).strip()
        target = targets.get("folders", {}).get(name)
        if target is None or not Path(target).is_dir():
            return [_notify("Folders", f"Folder {name} is not available.", "▣")]
        if is_sensitive_path(target):
            return [_notify("Folders", "NOVA blocked a protected folder.", "▣")]
        if not _start(target):
            return [_notify("Folders", f"Windows could not open {name}.", "▣")]
        return [_activity("Tool", f'explorer.open("{name}")')]

    if kind == "open_recent":
        # Current clients send an opaque ID. Older clients used the display
        # name. Both are resolved only through the backend-owned target map.
        lookup = message.get("id")
        if not isinstance(lookup, str) or not lookup.strip():
            lookup = message.get("name")
        if not isinstance(lookup, str) or not lookup.strip():
            return [_notify("Files", "Invalid recent-file request.", "▤")]
        lookup = lookup.strip()
        target = targets.get("recent", {}).get(lookup)
        if target is None:
            return [_notify("Files", "That recent file is no longer available.", "▤")]
        if not isinstance(target, str) or not can_open_recent_target(target):
            return [_notify("Files", "NOVA blocked a protected sensitive file.", "▤")]
        if not _start(target):
            return [_notify("Files", "Windows could not open that recent file.", "▤")]
        return [_activity("Tool", f'files.open_recent("{lookup[:14]}")')]


    if kind == "sync_integrations":
        try:
            from nova_integrations.runtime import get_runtime

            results = get_runtime().sync.sync_all()
            summary = ", ".join(
                f"{item.resource}: +{item.added} ~{item.updated} -{item.deleted}"
                for item in results
            ) or "No enabled account services were available."
            messages = [
                _activity("Tool", "integrations.sync_all()"),
                _notify("Email & Calendar", summary, "✉"),
            ]
            try:
                import integration_feeds

                messages.extend(integration_feeds.snapshot_messages())
            except Exception:
                pass
            return messages
        except Exception as error:
            return [
                _activity("Tool", "integrations.sync_all()", "denied"),
                _notify("Email & Calendar", f"Synchronization failed: {str(error)[:240]}", "⚠"),
            ]

    if kind == "task":
        task_id = message.get("id")
        done = bool(message.get("done"))
        if isinstance(task_id, int) and feeds.set_task_done(task_id, done):
            refreshed = feeds.tasks_message()
            result = [refreshed] if refreshed else []
            verb = "done" if done else "reopened"
            result.append(_activity("Task", f"tasks.mark_{verb}(#{task_id})"))
            return result
        return []

    if kind == "forget":
        title = str(message.get("title", "")).strip()
        if feeds.forget_memory(title):
            messages = [_activity("Memory", f'obsidian.forget("{title}")')]
            snapshot = feeds.obsidian_message()
            if snapshot:
                messages.append(snapshot)
            messages.append(
                _notify("Obsidian", f"{title} moved to NOVA/.trash in the vault.", "◈")
            )
            return messages
        return [_notify("Obsidian", f"Could not find memory note {title}.", "◈")]

    if kind == "approval":
        if not isinstance(message.get("id"), str) or not isinstance(
            message.get("decision"), str
        ):
            return [_notify("Approval", "Invalid approval request.", "◉")]
        action_id = message["id"].strip()
        decision = message["decision"].strip().lower()
        scope_value = message.get("scope", "once")
        scope = scope_value.strip().lower() if isinstance(scope_value, str) else ""
        if approvals is not None and action_id not in approvals.pending:
            return [
                _notify(
                    "Approval",
                    "That request is no longer pending. Refresh the approval list.",
                    "◉",
                )
            ]
        try:
            command = bridge.enqueue_approval(
                action_id,
                decision,
                scope=scope,
            )
        except BridgeValidationError as error:
            return [_notify("Approval", str(error), "◉")]
        active = bridge.active_session()["active"]
        state = "sent to NOVA" if active else "queued for NOVA for up to two minutes"
        return [
            _activity(
                "Task",
                f"approval.{decision}({action_id})",
                "running",
            ),
            _notify(
                "Approval",
                f"Decision {state}. Command {command['id'][:8]}.",
                "◉",
            )
        ]

    if kind == "delegate":
        value = message.get("text")
        text = value.strip() if isinstance(value, str) else ""
        if not text:
            return []
        try:
            command = bridge.enqueue_delegate(text)
        except BridgeValidationError as error:
            return [_notify("NOVA", str(error), "◉")]
        active = bridge.active_session()["active"]
        state = "sent to the active session" if active else "queued for up to two minutes"
        return [
            _activity("Task", f'delegate("{text[:60]}")', "running"),
            _notify(
                "NOVA",
                f"Command {state}. ID {command['id'][:8]}.",
                "◉",
            ),
        ]

    return []
