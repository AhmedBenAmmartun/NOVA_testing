"""Failure-isolated hook for NOVA standby startup."""

from __future__ import annotations

import logging

from .runtime import start_integration_supervisor, stop_integration_supervisor


logger = logging.getLogger("nova.integrations.startup")


def start_integrations_safely() -> bool:
    try:
        start_integration_supervisor()
        logger.info("NOVA email/calendar supervisor started")
        return True
    except Exception:
        logger.exception(
            "NOVA email/calendar supervisor could not start; core standby remains available"
        )
        return False


def stop_integrations_safely() -> None:
    try:
        stop_integration_supervisor()
    except Exception:
        logger.exception("NOVA email/calendar supervisor did not stop normally")
