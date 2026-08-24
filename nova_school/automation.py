from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from pathlib import Path

from nova_runtime import NovaRuntime

from .materials import SUPPORTED_MATERIAL_EXTENSIONS
from .organizer import SchoolMaterialOrganizer
from .paths import school_runtime_root


logger = logging.getLogger("nova.school.automation")


@dataclass(slots=True)
class _ObservedFile:
    size: int
    mtime_ns: int
    stable_passes: int = 0


def default_download_directories() -> tuple[Path, ...]:
    candidates = (
        Path.home() / "Downloads",
        Path.home() / "OneDrive" / "Downloads",
    )
    return tuple(path for path in candidates if path.is_dir())


class SchoolAutomationService:
    """Managed Downloads automation running through nova_runtime.

    The service keeps a small local signature database so restarting NOVA does
    not repeatedly re-process unchanged files. Originals are never deleted.
    """

    def __init__(
        self,
        *,
        organizer: SchoolMaterialOrganizer | None = None,
        download_directories: tuple[Path, ...] | None = None,
        poll_seconds: float = 4.0,
        state_path: Path | None = None,
    ) -> None:
        self.organizer = organizer or SchoolMaterialOrganizer()
        self.download_directories = (
            download_directories
            if download_directories is not None
            else default_download_directories()
        )
        self.poll_seconds = max(1.0, float(poll_seconds))
        self.state_path = (
            state_path.expanduser().resolve()
            if state_path is not None
            else school_runtime_root() / "downloads_state.json"
        )
        self._observed: dict[Path, _ObservedFile] = {}
        self._handled: dict[Path, tuple[int, int]] = self._load_state()

    def _load_state(self) -> dict[Path, tuple[int, int]]:
        try:
            payload = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return {}

        handled: dict[Path, tuple[int, int]] = {}
        for key, value in payload.get("handled", {}).items():
            try:
                handled[Path(key)] = (int(value[0]), int(value[1]))
            except (TypeError, ValueError, IndexError):
                continue
        return handled

    def _save_state(self) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": 1,
            "handled": {
                str(path): [signature[0], signature[1]]
                for path, signature in sorted(
                    self._handled.items(),
                    key=lambda item: str(item[0]).casefold(),
                )
            },
        }
        temporary = self.state_path.with_suffix(".json.tmp")
        temporary.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        temporary.replace(self.state_path)

    async def run(self) -> None:
        while True:
            try:
                await self.scan_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                # One corrupt/locked file must not permanently kill automation.
                logger.exception("Downloads automation scan failed")
            await asyncio.sleep(self.poll_seconds)

    async def scan_once(self) -> list:
        results = []
        live_paths: set[Path] = set()
        state_changed = False

        for folder in self.download_directories:
            if not folder.is_dir():
                continue

            for path in folder.iterdir():
                if not path.is_file() or path.suffix.lower() not in SUPPORTED_MATERIAL_EXTENSIONS:
                    continue

                path = path.resolve()
                live_paths.add(path)
                try:
                    stat = path.stat()
                except OSError:
                    continue

                signature = (stat.st_size, stat.st_mtime_ns)
                if self._handled.get(path) == signature:
                    continue

                prior = self._observed.get(path)
                if prior is None or (prior.size, prior.mtime_ns) != signature:
                    self._observed[path] = _ObservedFile(*signature)
                    continue

                prior.stable_passes += 1
                if prior.stable_passes < 1:
                    continue

                result = self.organizer.organize(path)
                results.append(result)

                # Error results are retried on a later scan. All other outcomes
                # are remembered, including needs_review, so the watcher does
                # not spam the audit file every four seconds.
                if result.status != "error":
                    self._handled[path] = signature
                    state_changed = True

        stale_observed = set(self._observed) - live_paths
        for path in stale_observed:
            self._observed.pop(path, None)

        stale_handled = {
            path
            for path in self._handled
            if path.parent in self.download_directories and path not in live_paths
        }
        for path in stale_handled:
            self._handled.pop(path, None)
            state_changed = True

        if state_changed:
            try:
                self._save_state()
            except Exception:
                logger.exception("could not persist Downloads automation state")

        return results

    async def start(self, runtime: NovaRuntime) -> str:
        return await runtime.jobs.start("school.downloads", self.run())
