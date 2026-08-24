from __future__ import annotations

import asyncio
import logging
import os
import platform


logger = logging.getLogger("nova.class_capture.notifications")


def notifications_enabled() -> bool:
    value = os.getenv("NOVA_CLASS_ANSWER_POPUP", "1").strip().casefold()
    return value not in {"0", "false", "no", "off"}


def _show_windows_toast(title: str, message: str) -> None:
    try:
        from winotify import Notification

        toast = Notification(
            app_id="NOVA Class Intelligence",
            title=title[:96],
            msg=message[:600],
            duration="long",
        )
        toast.show()
    except Exception:
        logger.exception("live answer notification failed")


async def show_answer_popup(question: str, answer: str) -> None:
    if not notifications_enabled() or platform.system() != "Windows":
        return
    title = "NOVA • Class Question"
    message = f"Q: {question.strip()}\n\n{answer.strip()}"
    await asyncio.to_thread(_show_windows_toast, title, message)
