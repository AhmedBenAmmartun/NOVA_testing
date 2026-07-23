"""Defensive local security monitoring for NOVA Guardian."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import psutil

from .config import (
    GuardianConfiguration,
    load_guardian_configuration,
)
from .events import (
    GuardianEventCategory,
    GuardianEventSeverity,
    GuardianEventType,
    create_guardian_event,
)
from .state import (
    GuardianState,
    get_guardian_state,
)


logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ProcessSnapshot:
    """Safe information about a running process."""

    process_id: int
    name: str
    executable: str | None
    command_line: tuple[str, ...]
    username: str | None


@dataclass(frozen=True, slots=True)
class ListenerSnapshot:
    """Safe information about one listening network socket."""

    address: str
    port: int
    process_id: int | None
    process_name: str | None


class SecurityMonitor:
    """
    Perform defensive local Windows security checks.

    Guardian reports observations but never performs destructive
    actions automatically.
    """

    def __init__(
        self,
        *,
        configuration: GuardianConfiguration | None = None,
        state: GuardianState | None = None,
    ) -> None:
        self.configuration = (
            configuration
            if configuration is not None
            else load_guardian_configuration()
        )

        self.state = (
            state
            if state is not None
            else get_guardian_state()
        )

        self._known_processes: dict[
            int,
            ProcessSnapshot,
        ] = {}

        self._known_listeners: set[
            tuple[str, int, int | None]
        ] = set()

        self._protection_status: dict[
            str,
            bool | None,
        ] = {}

        self._baseline_created = False

    @staticmethod
    def _process_snapshot(
        process: psutil.Process,
    ) -> ProcessSnapshot | None:
        """Read process information without failing the scan."""

        try:
            information = process.as_dict(
                attrs=[
                    "pid",
                    "name",
                    "exe",
                    "cmdline",
                    "username",
                ]
            )

        except (
            psutil.NoSuchProcess,
            psutil.AccessDenied,
            psutil.ZombieProcess,
        ):
            return None

        process_id = information.get("pid")

        if not isinstance(process_id, int):
            return None

        raw_name = information.get("name")
        raw_executable = information.get("exe")
        raw_command_line = information.get(
            "cmdline"
        )
        raw_username = information.get(
            "username"
        )

        name = (
            str(raw_name).strip().lower()
            if raw_name
            else "unknown"
        )

        executable = (
            str(raw_executable).strip()
            if raw_executable
            else None
        )

        command_line = tuple(
            str(item)
            for item in (
                raw_command_line
                if isinstance(
                    raw_command_line,
                    list,
                )
                else []
            )
        )

        username = (
            str(raw_username).strip()
            if raw_username
            else None
        )

        return ProcessSnapshot(
            process_id=process_id,
            name=name,
            executable=executable,
            command_line=command_line,
            username=username,
        )

    def _running_processes(
        self,
    ) -> dict[int, ProcessSnapshot]:
        """Create a snapshot of running processes."""

        snapshots: dict[
            int,
            ProcessSnapshot,
        ] = {}

        for process in psutil.process_iter():
            snapshot = self._process_snapshot(
                process
            )

            if snapshot is not None:
                snapshots[
                    snapshot.process_id
                ] = snapshot

        return snapshots

    @staticmethod
    def _process_risk_reasons(
        process: ProcessSnapshot,
    ) -> list[str]:
        """
        Return basic defensive warning signals.

        These observations do not prove that a process is malicious.
        """

        reasons: list[str] = []
        risk_score = 0

        executable = (
            process.executable or ""
        ).lower()

        command_line = " ".join(
            process.command_line
        ).lower()

        temporary_locations = (
            "\\appdata\\local\\temp\\",
            "\\windows\\temp\\",
            "\\temp\\",
        )

        if any(
            location in executable
            for location in temporary_locations
        ):
            reasons.append(
                "executable_started_from_temporary_folder"
            )
            risk_score += 2

        if "\\downloads\\" in executable:
            reasons.append(
                "executable_started_from_downloads"
            )
            risk_score += 1

        suspicious_command_markers = (
            "-encodedcommand",
            " -enc ",
            "frombase64string",
            "downloadstring",
            "invoke-expression",
            "iex(",
            "regsvr32 /s /n /u /i:",
        )

        matched_markers = [
            marker
            for marker in suspicious_command_markers
            if marker in command_line
        ]

        if matched_markers:
            reasons.append(
                "unusual_script_command"
            )
            risk_score += 2

        executable_name = Path(
            executable
        ).name.lower()

        suspicious_double_extensions = (
            ".pdf.exe",
            ".doc.exe",
            ".docx.exe",
            ".jpg.exe",
            ".png.exe",
            ".txt.exe",
            ".zip.exe",
        )

        if any(
            executable_name.endswith(
                extension
            )
            for extension
            in suspicious_double_extensions
        ):
            reasons.append(
                "suspicious_double_file_extension"
            )
            risk_score += 3

        if risk_score < 2:
            return []

        return reasons

    def _record_suspicious_process(
        self,
        process: ProcessSnapshot,
        reasons: list[str],
    ) -> None:
        """Record a defensive process alert."""

        event = create_guardian_event(
            event_type=(
                GuardianEventType
                .SUSPICIOUS_PROCESS_DETECTED
            ),
            category=(
                GuardianEventCategory.PROCESS
            ),
            severity=(
                GuardianEventSeverity.MEDIUM
            ),
            title="Unusual process detected",
            message=(
                "NOVA noticed a newly started process "
                "with unusual characteristics. This does "
                "not necessarily mean it is malicious."
            ),
            source="security_monitor",
            metadata={
                "process_id": (
                    process.process_id
                ),
                "process_name": process.name,
                "executable": (
                    process.executable
                ),
                "reasons": reasons,
            },
            requires_attention=True,
        )

        self.state.record_event(event)

    @staticmethod
    def _address_parts(
        local_address: Any,
    ) -> tuple[str, int] | None:
        """Normalize a psutil network address."""

        if not local_address:
            return None

        address = getattr(
            local_address,
            "ip",
            None,
        )

        port = getattr(
            local_address,
            "port",
            None,
        )

        if address is None and isinstance(
            local_address,
            tuple,
        ):
            if len(local_address) >= 2:
                address = local_address[0]
                port = local_address[1]

        if not isinstance(address, str):
            return None

        if not isinstance(port, int):
            return None

        return address, port

    def _listening_connections(
        self,
    ) -> dict[
        tuple[str, int, int | None],
        ListenerSnapshot,
    ]:
        """Read listening TCP sockets."""

        listeners: dict[
            tuple[str, int, int | None],
            ListenerSnapshot,
        ] = {}

        try:
            connections = psutil.net_connections(
                kind="inet"
            )

        except (
            psutil.AccessDenied,
            OSError,
        ):
            logger.warning(
                "Guardian could not inspect all "
                "network listeners."
            )
            return listeners

        for connection in connections:
            if (
                connection.status
                != psutil.CONN_LISTEN
            ):
                continue

            address_parts = (
                self._address_parts(
                    connection.laddr
                )
            )

            if address_parts is None:
                continue

            address, port = address_parts
            process_id = connection.pid

            process_name: str | None = None

            if process_id is not None:
                try:
                    process_name = (
                        psutil.Process(
                            process_id
                        )
                        .name()
                        .strip()
                        .lower()
                    )

                except (
                    psutil.NoSuchProcess,
                    psutil.AccessDenied,
                    psutil.ZombieProcess,
                ):
                    process_name = None

            key = (
                address,
                port,
                process_id,
            )

            listeners[key] = ListenerSnapshot(
                address=address,
                port=port,
                process_id=process_id,
                process_name=process_name,
            )

        return listeners

    @staticmethod
    def _listener_is_public(
        listener: ListenerSnapshot,
    ) -> bool:
        """
        Return whether a listener can accept non-loopback traffic.
        """

        normalized = (
            listener.address
            .strip()
            .lower()
        )

        return normalized not in {
            "127.0.0.1",
            "::1",
            "localhost",
        }

    def _record_new_listener(
        self,
        listener: ListenerSnapshot,
    ) -> None:
        """Record a newly observed public listener."""

        event = create_guardian_event(
            event_type=(
                GuardianEventType
                .NETWORK_LISTENER_DETECTED
            ),
            category=(
                GuardianEventCategory.NETWORK
            ),
            severity=(
                GuardianEventSeverity.MEDIUM
            ),
            title="New network listener detected",
            message=(
                "A process began listening for network "
                "connections. This may be legitimate, "
                "such as a development server."
            ),
            source="security_monitor",
            metadata={
                "address": listener.address,
                "port": listener.port,
                "process_id": (
                    listener.process_id
                ),
                "process_name": (
                    listener.process_name
                ),
            },
            requires_attention=False,
        )

        self.state.record_event(event)

    @staticmethod
    def _run_powershell_json(
        command: str,
    ) -> Any | None:
        """Run a read-only PowerShell status command."""

        creation_flags = 0

        if os.name == "nt":
            creation_flags = getattr(
                subprocess,
                "CREATE_NO_WINDOW",
                0,
            )

        try:
            completed = subprocess.run(
                [
                    "powershell.exe",
                    "-NoProfile",
                    "-NonInteractive",
                    "-Command",
                    command,
                ],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
                creationflags=creation_flags,
            )

        except (
            OSError,
            subprocess.SubprocessError,
        ):
            return None

        if completed.returncode != 0:
            logger.debug(
                "Guardian PowerShell status command failed: %s",
                completed.stderr.strip(),
            )
            return None

        output = completed.stdout.strip()

        if not output:
            return None

        try:
            return json.loads(output)

        except json.JSONDecodeError:
            logger.debug(
                "Guardian received invalid PowerShell JSON."
            )
            return None

    def _read_protection_status(
        self,
    ) -> dict[str, bool | None]:
        """Read Defender and Windows Firewall status."""

        status: dict[
            str,
            bool | None,
        ] = {
            "defender_antivirus": None,
            "defender_realtime": None,
            "firewall_domain": None,
            "firewall_private": None,
            "firewall_public": None,
        }

        defender = self._run_powershell_json(
            "Get-MpComputerStatus | "
            "Select-Object AntivirusEnabled,"
            "RealTimeProtectionEnabled | "
            "ConvertTo-Json -Compress"
        )

        if isinstance(defender, dict):
            antivirus = defender.get(
                "AntivirusEnabled"
            )

            realtime = defender.get(
                "RealTimeProtectionEnabled"
            )

            if isinstance(antivirus, bool):
                status[
                    "defender_antivirus"
                ] = antivirus

            if isinstance(realtime, bool):
                status[
                    "defender_realtime"
                ] = realtime

        firewall = self._run_powershell_json(
            "Get-NetFirewallProfile | "
            "Select-Object Name,"
            "@{Name='Enabled';"
            "Expression={$_.Enabled.ToString()}} | "
            "ConvertTo-Json -Compress"
        )

        firewall_profiles: list[
            dict[str, Any]
        ] = []

        if isinstance(firewall, dict):
            firewall_profiles = [
                firewall
            ]

        elif isinstance(firewall, list):
            firewall_profiles = [
                profile
                for profile in firewall
                if isinstance(profile, dict)
            ]

        for profile in firewall_profiles:
            raw_name = profile.get("Name")
            enabled = profile.get("Enabled")

            if not isinstance(
                raw_name,
                str,
            ):
                continue

            normalized_enabled: bool

            if isinstance(enabled, bool):
                normalized_enabled = enabled

            elif isinstance(enabled, str):
                cleaned_enabled = (
                    enabled
                    .strip()
                    .lower()
                )

                if cleaned_enabled == "true":
                    normalized_enabled = True

                elif cleaned_enabled == "false":
                    normalized_enabled = False

                else:
                    # Unknown or not configured.
                    continue

            elif isinstance(enabled, int):
                normalized_enabled = bool(
                    enabled
                )

            else:
                continue

            key = (
                "firewall_"
                + raw_name.strip().lower()
            )

            if key in status:
                status[key] = (
                    normalized_enabled
                )

        return status

    def _record_protection_change(
        self,
        protection_name: str,
        enabled: bool,
    ) -> None:
        """Record disabled or restored protection."""

        if enabled:
            event_type = (
                GuardianEventType
                .SECURITY_PROTECTION_RESTORED
            )

            severity = (
                GuardianEventSeverity.INFO
            )

            title = (
                "Security protection restored"
            )

            message = (
                f"{protection_name} is "
                "enabled again."
            )

            requires_attention = False

        else:
            event_type = (
                GuardianEventType
                .SECURITY_PROTECTION_DISABLED
            )

            severity = (
                GuardianEventSeverity.HIGH
            )

            title = (
                "Security protection disabled"
            )

            message = (
                f"{protection_name} appears "
                "to be disabled."
            )

            requires_attention = True

        event = create_guardian_event(
            event_type=event_type,
            category=(
                GuardianEventCategory.SECURITY
            ),
            severity=severity,
            title=title,
            message=message,
            source="security_monitor",
            metadata={
                "protection": (
                    protection_name
                ),
                "enabled": enabled,
            },
            requires_attention=(
                requires_attention
            ),
        )

        self.state.record_event(event)

    def _check_protection_changes(
        self,
        current_status: dict[
            str,
            bool | None,
        ],
    ) -> None:
        """Compare security protection with its previous status."""

        for protection_name, enabled in (
            current_status.items()
        ):
            if enabled is None:
                continue

            previous = (
                self._protection_status.get(
                    protection_name
                )
            )

            if previous is None and not enabled:
                self._record_protection_change(
                    protection_name,
                    enabled=False,
                )

            elif previous is True and not enabled:
                self._record_protection_change(
                    protection_name,
                    enabled=False,
                )

            elif previous is False and enabled:
                self._record_protection_change(
                    protection_name,
                    enabled=True,
                )

            self._protection_status[
                protection_name
            ] = enabled

    def poll_once(
        self,
    ) -> dict[str, Any]:
        """Perform one defensive security scan."""

        if not self.configuration.enabled:
            return {
                "enabled": False,
                "reason": "guardian_disabled",
            }

        if not (
            self.configuration
            .security_monitor_enabled
        ):
            return {
                "enabled": False,
                "reason": (
                    "security_monitor_disabled"
                ),
            }

        processes = (
            self._running_processes()
        )

        listeners = (
            self._listening_connections()
        )

        protection_status = (
            self._read_protection_status()
        )

        suspicious_process_count = 0
        new_listener_count = 0

        if self._baseline_created:
            previous_process_ids = set(
                self._known_processes
            )

            for process_id, process in (
                processes.items()
            ):
                if (
                    process_id
                    in previous_process_ids
                ):
                    continue

                reasons = (
                    self._process_risk_reasons(
                        process
                    )
                )

                if reasons:
                    suspicious_process_count += 1

                    self._record_suspicious_process(
                        process,
                        reasons,
                    )

            current_listener_keys = set(
                listeners
            )

            new_listener_keys = (
                current_listener_keys
                - self._known_listeners
            )

            for listener_key in (
                new_listener_keys
            ):
                listener = listeners[
                    listener_key
                ]

                if self._listener_is_public(
                    listener
                ):
                    new_listener_count += 1

                    self._record_new_listener(
                        listener
                    )

        self._check_protection_changes(
            protection_status
        )

        self._known_processes = processes

        self._known_listeners = set(
            listeners
        )

        self._baseline_created = True

        return {
            "enabled": True,
            "running_process_count": len(
                processes
            ),
            "listening_socket_count": len(
                listeners
            ),
            "suspicious_new_processes": (
                suspicious_process_count
            ),
            "new_public_listeners": (
                new_listener_count
            ),
            "protection_status": (
                protection_status
            ),
        }

    async def run(
        self,
        stop_event: asyncio.Event,
    ) -> None:
        """Run defensive checks until stopped."""

        interval = max(
            5.0,
            self.configuration
            .security_scan_interval_seconds,
        )

        logger.info(
            "NOVA security monitor started."
        )

        while not stop_event.is_set():
            await asyncio.to_thread(
                self.poll_once
            )

            try:
                await asyncio.wait_for(
                    stop_event.wait(),
                    timeout=interval,
                )

            except TimeoutError:
                continue

        logger.info(
            "NOVA security monitor stopped."
        )