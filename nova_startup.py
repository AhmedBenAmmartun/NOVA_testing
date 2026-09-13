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

load_dotenv(
    ENV_PATH,
    override=True,
)


# Import runtime-owned subsystems only after loading .env.
from nova_guardian import get_guardian_runtime  # noqa: E402
from nova_integrations.startup_hook import (  # noqa: E402
    start_integrations_safely,
    stop_integrations_safely,
)
from nova_runtime import HealthState, NovaRuntime, TaskStore  # noqa: E402
from nova_runtime.store import runtime_root  # noqa: E402


RUNTIME_DIRECTORY = runtime_root() / "runtime"
LOG_PATH = RUNTIME_DIRECTORY / "nova_startup.log"
STATUS_PATH = RUNTIME_DIRECTORY / "nova_status.json"

RUNTIME_DIRECTORY.mkdir(
    parents=True,
    exist_ok=True,
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


def runtime_health_summary(
    core_runtime: NovaRuntime,
) -> dict[str, dict[str, str]]:
    """Return safe, JSON-ready local runtime health metadata."""

    summary: dict[str, dict[str, str]] = {}

    for name, component in core_runtime.health.snapshot().items():
        summary[name] = {
            "state": component.state.value,
            "detail": component.detail,
            "updated_at": component.updated_at.isoformat(),
        }

    return summary


def build_core_runtime() -> NovaRuntime:
    """Build the persistent NOVA Core with its canonical durable task store."""
    return NovaRuntime(task_store=TaskStore())


def recover_runtime_tasks(
    core_runtime: NovaRuntime,
) -> int:
    """Recover durable local task state without making startup depend on it."""

    store = core_runtime.task_store

    if store is None:
        core_runtime.health.set(
            "task_store",
            HealthState.FAILED,
            "not_configured",
        )
        logger.error(
            "Persistent NOVA Core started without its canonical task store."
        )
        return 0

    try:
        recovered = store.recover()

    except Exception as error:
        core_runtime.health.set(
            "task_store",
            HealthState.DEGRADED,
            f"recovery:{type(error).__name__}",
        )
        logger.exception(
            "Durable task recovery failed; NOVA core remains available."
        )
        return 0

    core_runtime.health.set(
        "task_store",
        HealthState.HEALTHY,
        f"recovered:{len(recovered)}",
    )

    return len(recovered)


async def start_guardian_safely(
    core_runtime: NovaRuntime,
) -> tuple[Any | None, bool, bool]:
    """Attach Guardian without making NOVA Core depend on Guardian startup."""

    guardian_runtime: Any | None = None

    try:
        guardian_runtime = get_guardian_runtime()
        started = await guardian_runtime.start()

    except Exception as error:
        core_runtime.health.set(
            "guardian",
            HealthState.DEGRADED,
            f"start:{type(error).__name__}",
        )
        logger.exception(
            "Guardian could not start; NOVA core remains available."
        )
        return guardian_runtime, False, False

    core_runtime.health.set(
        "guardian",
        HealthState.HEALTHY,
        "started" if started else "available",
    )

    return guardian_runtime, True, started


def guardian_summary_safely(
    guardian_runtime: Any | None,
    core_runtime: NovaRuntime,
) -> dict[str, Any]:
    """Read Guardian status without allowing a summary failure to kill core."""

    if guardian_runtime is None:
        return {
            "available": False,
            "running": False,
        }

    try:
        return dict(guardian_runtime.safe_summary())

    except Exception as error:
        core_runtime.health.set(
            "guardian",
            HealthState.DEGRADED,
            f"summary:{type(error).__name__}",
        )
        logger.exception(
            "Guardian status could not be read; NOVA core remains available."
        )
        return {
            "available": True,
            "running": False,
            "summary_error": type(error).__name__,
        }


async def stop_guardian_safely(
    guardian_runtime: Any | None,
    core_runtime: NovaRuntime,
) -> bool:
    """Stop Guardian without masking an earlier degraded state."""

    if guardian_runtime is None:
        return False

    try:
        stopped = bool(
            await guardian_runtime.stop()
        )

    except Exception as error:
        core_runtime.health.set(
            "guardian",
            HealthState.DEGRADED,
            f"shutdown:{type(error).__name__}",
        )
        logger.exception(
            "Guardian did not stop normally."
        )
        return False

    component = core_runtime.health.get(
        "guardian"
    )

    if (
        component is None
        or component.state
        not in {
            HealthState.DEGRADED,
            HealthState.FAILED,
        }
    ):
        core_runtime.health.set(
            "guardian",
            HealthState.STOPPED,
            "shutdown",
        )

    return stopped


def write_status(
    *,
    state: str,
    guardian: dict[str, Any] | None = None,
    core_runtime: NovaRuntime | None = None,
    error: str | None = None,
) -> None:
    """Write NOVA's current status to a local JSON file."""

    payload = {
        "application": "NOVA",
        "process_id": os.getpid(),
        "state": state,
        "mode": "standby",
        "updated_at": utc_timestamp(),
        "core": (
            runtime_health_summary(core_runtime)
            if core_runtime is not None
            else None
        ),
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
    Run NOVA Core for three seconds, with Guardian attached when available.

    The check succeeds when the provider-independent local core can start and
    stop. Guardian failure is reported as degraded subsystem health, not as a
    dead NOVA process.
    """

    core_runtime = build_core_runtime()
    recover_runtime_tasks(core_runtime)

    guardian_runtime: Any | None = None

    try:
        (
            guardian_runtime,
            guardian_available,
            guardian_started,
        ) = await start_guardian_safely(
            core_runtime
        )

        status = guardian_summary_safely(
            guardian_runtime,
            core_runtime,
        )

        write_status(
            state="startup_check_running",
            guardian=status,
            core_runtime=core_runtime,
        )

        print(
            "Guardian available:",
            guardian_available,
        )

        print(
            "Guardian newly started:",
            guardian_started,
        )

        print(
            "Status:",
            status,
        )

        await asyncio.sleep(3)

        stopped = await stop_guardian_safely(
            guardian_runtime,
            core_runtime,
        )

        final_status = guardian_summary_safely(
            guardian_runtime,
            core_runtime,
        )

        write_status(
            state="startup_check_complete",
            guardian=final_status,
            core_runtime=core_runtime,
        )

        print(
            "Guardian stopped:",
            stopped,
        )

        print(
            "Final:",
            final_status,
        )

        return 0

    except Exception as error:
        core_runtime.health.set(
            "runtime",
            HealthState.FAILED,
            f"startup_check:{type(error).__name__}",
        )

        logger.exception(
            "NOVA local-core startup check failed."
        )

        write_status(
            state="startup_check_failed",
            guardian=guardian_summary_safely(
                guardian_runtime,
                core_runtime,
            ),
            core_runtime=core_runtime,
            error=(
                f"{type(error).__name__}: "
                f"{error}"
            ),
        )

        print(
            "Local-core startup check failed:",
            type(error).__name__,
            error,
        )

        return 1

    finally:
        await stop_guardian_safely(
            guardian_runtime,
            core_runtime,
        )
        await core_runtime.shutdown()


async def run_standby() -> int:
    """
    Run NOVA's provider-independent local core process.

    The process owns NovaRuntime for its full lifetime. Guardian window/security
    monitoring and local integrations attach as failure-isolated subsystems.
    Gemini Live, microphone streaming, and screen vision stay optional and are
    not required for this process to remain alive.
    """

    core_runtime = build_core_runtime()
    recover_runtime_tasks(core_runtime)

    guardian_runtime: Any | None = None

    try:
        (
            guardian_runtime,
            guardian_available,
            guardian_started,
        ) = await start_guardian_safely(
            core_runtime
        )

        integrations_started = start_integrations_safely()

        core_runtime.health.set(
            "integrations",
            (
                HealthState.HEALTHY
                if integrations_started
                else HealthState.DEGRADED
            ),
            (
                "started"
                if integrations_started
                else "unavailable"
            ),
        )

        logger.info(
            "NOVA local core is running. "
            "Guardian available: %s; newly started: %s",
            guardian_available,
            guardian_started,
        )

        while True:
            status = guardian_summary_safely(
                guardian_runtime,
                core_runtime,
            )

            write_status(
                state="standby",
                guardian=status,
                core_runtime=core_runtime,
            )

            await asyncio.sleep(10)

    except asyncio.CancelledError:
        logger.info(
            "NOVA local core was cancelled."
        )
        return 0

    except Exception as error:
        core_runtime.health.set(
            "runtime",
            HealthState.FAILED,
            f"loop:{type(error).__name__}",
        )

        logger.exception(
            "NOVA local core encountered an error."
        )

        write_status(
            state="standby_error",
            guardian=guardian_summary_safely(
                guardian_runtime,
                core_runtime,
            ),
            core_runtime=core_runtime,
            error=(
                f"{type(error).__name__}: "
                f"{error}"
            ),
        )

        return 1

    finally:
        stop_integrations_safely()

        core_runtime.health.set(
            "integrations",
            HealthState.STOPPED,
            "shutdown",
        )

        await stop_guardian_safely(
            guardian_runtime,
            core_runtime,
        )

        await core_runtime.shutdown()

        write_status(
            state="stopped",
            guardian=guardian_summary_safely(
                guardian_runtime,
                core_runtime,
            ),
            core_runtime=core_runtime,
        )

        logger.info(
            "NOVA local core stopped."
        )


def parse_arguments() -> argparse.Namespace:
    """Read command-line arguments."""

    parser = argparse.ArgumentParser(
        description=(
            "Launch NOVA's provider-independent local core."
        )
    )

    parser.add_argument(
        "--check",
        action="store_true",
        help=(
            "Run a short local-core startup test and exit."
        ),
    )

    return parser.parse_args()


def main() -> int:
    """Start NOVA's persistent local core supervisor."""

    arguments = parse_arguments()

    if not acquire_single_instance():
        logger.info(
            "Another NOVA local core process "
            "is already running."
        )

        print(
            "NOVA local core is already running."
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
            "NOVA local core was stopped manually."
        )

        return 0

    finally:
        release_single_instance()


if __name__ == "__main__":
    sys.exit(main())
