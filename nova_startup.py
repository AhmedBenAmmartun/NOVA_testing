"""NOVA Windows startup and lightweight standby supervisor."""

from __future__ import annotations

import argparse
import asyncio
import ctypes
import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parent
ENV_PATH = PROJECT_ROOT / ".env"

LOG_DIRECTORY = PROJECT_ROOT / "logs"
LOG_PATH = LOG_DIRECTORY / "nova_startup.log"
STATUS_PATH = LOG_DIRECTORY / "nova_status.json"

LOG_DIRECTORY.mkdir(
    parents=True,
    exist_ok=True,
)

load_dotenv(
    ENV_PATH,
    override=True,
)


logging.basicConfig(
    filename=LOG_PATH,
    level=logging.INFO,
    format=(
        "%(asctime)s | %(levelname)s | "
        "%(name)s | %(message)s"
    ),
)

logger = logging.getLogger(
    "nova.startup"
)


# Import Guardian only after loading .env.
from nova_guardian import get_guardian_runtime  # noqa: E402
from nova_integrations.startup_hook import (  # noqa: E402
    start_integrations_safely,
    stop_integrations_safely,
)


ERROR_ALREADY_EXISTS = 183
MUTEX_NAME = r"Local\NOVAStandbySupervisor"

_mutex_handle: int | None = None
_kernel32: Any | None = None


def acquire_single_instance() -> bool:
    """
    Prevent multiple NOVA standby processes from running.

    Returns False when another standby process is already running.
    """

    global _mutex_handle
    global _kernel32

    if os.name != "nt":
        return True

    try:
        kernel32 = ctypes.WinDLL(
            "kernel32",
            use_last_error=True,
        )

        kernel32.CreateMutexW.argtypes = [
            ctypes.c_void_p,
            ctypes.c_bool,
            ctypes.c_wchar_p,
        ]

        kernel32.CreateMutexW.restype = (
            ctypes.c_void_p
        )

        kernel32.CloseHandle.argtypes = [
            ctypes.c_void_p
        ]

        kernel32.CloseHandle.restype = (
            ctypes.c_bool
        )

        handle = kernel32.CreateMutexW(
            None,
            False,
            MUTEX_NAME,
        )

        if not handle:
            raise OSError(
                ctypes.get_last_error(),
                "Could not create NOVA instance lock.",
            )

        if (
            ctypes.get_last_error()
            == ERROR_ALREADY_EXISTS
        ):
            kernel32.CloseHandle(
                handle
            )
            return False

        _kernel32 = kernel32
        _mutex_handle = int(handle)

        return True

    except Exception:
        logger.exception(
            "NOVA could not create its single-instance lock."
        )

        # Do not block startup if the mutex fails.
        return True


def release_single_instance() -> None:
    """Release NOVA's Windows process lock."""

    global _mutex_handle
    global _kernel32

    if (
        _mutex_handle is None
        or _kernel32 is None
    ):
        return

    try:
        _kernel32.CloseHandle(
            ctypes.c_void_p(
                _mutex_handle
            )
        )

    except Exception:
        logger.debug(
            "NOVA could not release its process lock normally.",
            exc_info=True,
        )

    finally:
        _mutex_handle = None
        _kernel32 = None


def utc_timestamp() -> str:
    """Return the current UTC timestamp."""

    return datetime.now(
        timezone.utc
    ).isoformat()


def write_status(
    *,
    state: str,
    guardian: dict[str, Any] | None = None,
    error: str | None = None,
) -> None:
    """Write NOVA's current status to a local JSON file."""

    payload = {
        "application": "NOVA",
        "process_id": os.getpid(),
        "state": state,
        "mode": "standby",
        "updated_at": utc_timestamp(),
        "guardian": guardian,
        "error": error,
    }

    temporary_path = STATUS_PATH.with_suffix(
        ".json.tmp"
    )

    try:
        temporary_path.write_text(
            json.dumps(
                payload,
                indent=2,
                ensure_ascii=False,
                default=str,
            ),
            encoding="utf-8",
        )

        temporary_path.replace(
            STATUS_PATH
        )

    except Exception:
        logger.exception(
            "NOVA could not update its status file."
        )


async def run_startup_check() -> int:
    """
    Run Guardian for three seconds and stop.

    This tests the supervisor without leaving it active.
    """

    runtime = get_guardian_runtime()

    try:
        started = await runtime.start()

        status = runtime.safe_summary()

        write_status(
            state="startup_check_running",
            guardian=status,
        )

        print(
            "Started:",
            started,
        )

        print(
            "Status:",
            status,
        )

        await asyncio.sleep(3)

        stopped = await runtime.stop()
        final_status = runtime.safe_summary()

        write_status(
            state="startup_check_complete",
            guardian=final_status,
        )

        print(
            "Stopped:",
            stopped,
        )

        print(
            "Final:",
            final_status,
        )

        return 0

    except Exception as error:
        logger.exception(
            "NOVA startup check failed."
        )

        write_status(
            state="startup_check_failed",
            error=(
                f"{type(error).__name__}: "
                f"{error}"
            ),
        )

        print(
            "Startup check failed:",
            type(error).__name__,
            error,
        )

        return 1


async def run_standby() -> int:
    """
    Run NOVA's lightweight local standby process.

    Guardian window and security monitoring stay active.
    Gemini Live, microphone streaming, and screen vision stay off.
    """

    runtime = get_guardian_runtime()

    try:
        started = await runtime.start()

        integrations_started = start_integrations_safely()

        logger.info(
            "NOVA entered standby mode. "
            "Guardian newly started: %s",
            started,
        )

        while True:
            status = runtime.safe_summary()

            write_status(
                state="standby",
                guardian=status,
            )

            await asyncio.sleep(10)

    except asyncio.CancelledError:
        logger.info(
            "NOVA standby was cancelled."
        )
        return 0

    except Exception as error:
        logger.exception(
            "NOVA standby encountered an error."
        )

        write_status(
            state="standby_error",
            guardian=runtime.safe_summary(),
            error=(
                f"{type(error).__name__}: "
                f"{error}"
            ),
        )

        return 1

    finally:
        stop_integrations_safely()

        try:
            await runtime.stop()

        except Exception:
            logger.exception(
                "Guardian did not stop normally."
            )

        write_status(
            state="stopped",
            guardian=runtime.safe_summary(),
        )

        logger.info(
            "NOVA standby stopped."
        )


def parse_arguments() -> argparse.Namespace:
    """Read command-line arguments."""

    parser = argparse.ArgumentParser(
        description=(
            "Launch NOVA in local standby mode."
        )
    )

    parser.add_argument(
        "--check",
        action="store_true",
        help=(
            "Run a short startup test and exit."
        ),
    )

    return parser.parse_args()


def main() -> int:
    """Start NOVA's standby supervisor."""

    arguments = parse_arguments()

    if not acquire_single_instance():
        logger.info(
            "Another NOVA standby process "
            "is already running."
        )

        print(
            "NOVA standby is already running."
        )

        return 0

    try:
        if arguments.check:
            return asyncio.run(
                run_startup_check()
            )

        return asyncio.run(
            run_standby()
        )

    except KeyboardInterrupt:
        logger.info(
            "NOVA standby was stopped manually."
        )

        return 0

    finally:
        release_single_instance()


if __name__ == "__main__":
    sys.exit(main())