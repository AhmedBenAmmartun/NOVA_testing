"""Wall-clock soak monitor for a live NOVA class recording.

Automated tests can prove the *logic* survives three hours in milliseconds.
They cannot prove that this Windows machine, this microphone driver, this
network, and this LiveKit account survive three hours -- only a real run can,
and that is what this script watches.

It is strictly an observer. It never starts, stops, or touches a recording; if
it decides the run has failed, it says so and keeps watching, because the
recording is still the most valuable thing in the room.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from nova_capture.audio_chunks import scan_audio_dir  # noqa: E402
from nova_capture.control import read_active_session  # noqa: E402
from nova_capture.recorder_process import read_recorder_state  # noqa: E402
from nova_capture.status import latest_session_path  # noqa: E402
from nova_capture.supervisor import read_health  # noqa: E402


@dataclass
class SoakResult:
    started_at: str = ""
    finished_at: str = ""
    session_path: str = ""
    samples: int = 0
    minutes_watched: float = 0.0
    chunks_first: int = 0
    chunks_last: int = 0
    recorded_seconds: float = 0.0
    max_last_write_age: float = 0.0
    max_transcript_lag: float = 0.0
    recorder_rss_start_mb: float = 0.0
    recorder_rss_max_mb: float = 0.0
    stt_reconnects: int = 0
    failures: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return not self.failures

    def as_dict(self) -> dict[str, Any]:
        payload = {
            key: getattr(self, key)
            for key in (
                "started_at",
                "finished_at",
                "session_path",
                "samples",
                "minutes_watched",
                "chunks_first",
                "chunks_last",
                "recorded_seconds",
                "max_last_write_age",
                "max_transcript_lag",
                "recorder_rss_start_mb",
                "recorder_rss_max_mb",
                "stt_reconnects",
            )
        }
        payload["failures"] = list(self.failures)
        payload["warnings"] = list(self.warnings)
        payload["passed"] = self.passed
        return payload


def _rss_mb(pid: Any) -> float:
    try:
        import psutil

        return psutil.Process(int(pid)).memory_info().rss / (1024 * 1024)
    except Exception:
        return 0.0


def _process_alive(pid: Any) -> bool:
    try:
        import psutil

        return psutil.Process(int(pid)).is_running()
    except Exception:
        return False


def resolve_session(explicit: str | None) -> Path | None:
    if explicit:
        return Path(explicit).expanduser().resolve()
    active = read_active_session(clean_stale=True)
    if active is not None:
        return Path(active.session_path)
    return latest_session_path()


def run_soak(
    *,
    minutes: float,
    interval_seconds: float,
    session: str | None = None,
    stall_tolerance_seconds: float = 90.0,
    memory_growth_mb: float = 250.0,
    sleep=time.sleep,
) -> SoakResult:
    result = SoakResult(started_at=datetime.now().astimezone().isoformat(timespec="seconds"))

    session_path = resolve_session(session)
    if session_path is None or not session_path.is_dir():
        result.failures.append("no class session directory could be resolved")
        result.finished_at = result.started_at
        return result

    result.session_path = str(session_path)
    log_dir = session_path / "endurance"
    log_dir.mkdir(parents=True, exist_ok=True)
    csv_path = log_dir / f"soak-{datetime.now().strftime('%Y%m%d-%H%M%S')}.csv"

    deadline = time.monotonic() + max(1.0, minutes * 60.0)
    started = time.monotonic()
    last_chunk_count = -1
    last_progress = time.monotonic()

    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "elapsed_seconds",
                "chunks",
                "recorded_seconds",
                "last_write_age",
                "audio_status",
                "stt_status",
                "notes_status",
                "transcript_lag",
                "recorder_rss_mb",
                "recorder_alive",
            ]
        )

        while time.monotonic() < deadline:
            elapsed = time.monotonic() - started
            recorder = read_recorder_state(session_path) or {}
            integrity = scan_audio_dir(
                session_path / "audio",
                recording=recorder.get("status") == "recording",
            )
            health = read_health(session_path) or {}
            workers = health.get("workers") if isinstance(health.get("workers"), dict) else {}
            workers = workers if isinstance(workers, dict) else {}

            audio_status = str(recorder.get("status") or "unknown")
            stt_status = str((workers.get("stt") or {}).get("status") or "unknown")
            notes_status = str((workers.get("notes") or {}).get("status") or "unknown")
            lag = float(health.get("transcript_lag_seconds") or 0.0)
            age = recorder.get("last_write_age_seconds")
            age_value = float(age) if age is not None else 0.0
            rss = _rss_mb(recorder.get("pid"))
            alive = _process_alive(recorder.get("pid"))

            result.samples += 1
            if result.chunks_first == 0:
                result.chunks_first = integrity.chunk_count
                result.recorder_rss_start_mb = rss
            result.chunks_last = integrity.chunk_count
            result.recorded_seconds = integrity.recorded_seconds
            result.max_last_write_age = max(result.max_last_write_age, age_value)
            result.max_transcript_lag = max(result.max_transcript_lag, lag)
            result.recorder_rss_max_mb = max(result.recorder_rss_max_mb, rss)
            recovery = health.get("recovery")
            if isinstance(recovery, dict):
                result.stt_reconnects = int(recovery.get("stt_reconnects") or 0)

            writer.writerow(
                [
                    round(elapsed, 1),
                    integrity.chunk_count,
                    round(integrity.recorded_seconds, 1),
                    round(age_value, 2),
                    audio_status,
                    stt_status,
                    notes_status,
                    round(lag, 2),
                    round(rss, 1),
                    alive,
                ]
            )
            handle.flush()

            if integrity.chunk_count > last_chunk_count:
                last_chunk_count = integrity.chunk_count
                last_progress = time.monotonic()
            elif (time.monotonic() - last_progress) > stall_tolerance_seconds:
                _add_once(
                    result.failures,
                    f"audio stopped growing for {stall_tolerance_seconds:.0f}s "
                    f"at chunk {integrity.chunk_count}",
                )

            if audio_status not in {"recording", "unknown"}:
                _add_once(result.failures, f"recorder reported status={audio_status}")
            if recorder.get("pid") and not alive:
                _add_once(result.failures, "recorder process is no longer running")
            if not integrity.healthy:
                _add_once(
                    result.failures,
                    "audio integrity check failed: "
                    + json.dumps(integrity.as_dict(), ensure_ascii=False),
                )
            if stt_status in {"offline", "failed"}:
                _add_once(result.warnings, f"transcription status={stt_status}")
            if notes_status == "degraded":
                _add_once(result.warnings, "live notes degraded")
            if (
                result.recorder_rss_start_mb
                and rss - result.recorder_rss_start_mb > memory_growth_mb
            ):
                _add_once(
                    result.failures,
                    f"recorder memory grew {rss - result.recorder_rss_start_mb:.0f} MB",
                )

            print(
                f"[{elapsed / 60.0:6.1f} min] chunks={integrity.chunk_count} "
                f"audio={audio_status} stt={stt_status} notes={notes_status} "
                f"lag={lag:.1f}s rss={rss:.0f}MB",
                flush=True,
            )
            sleep(max(1.0, interval_seconds))

    result.minutes_watched = (time.monotonic() - started) / 60.0
    result.finished_at = datetime.now().astimezone().isoformat(timespec="seconds")

    if result.chunks_last <= result.chunks_first:
        result.failures.append("no new audio chunks were produced during the soak")

    summary_path = log_dir / (csv_path.stem + ".summary.json")
    summary_path.write_text(
        json.dumps(result.as_dict(), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"\nSoak log:     {csv_path}")
    print(f"Soak summary: {summary_path}")
    return result


def _add_once(bucket: list[str], message: str) -> None:
    if message not in bucket:
        bucket.append(message)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="nova-class-endurance")
    parser.add_argument("--minutes", type=float, default=150.0)
    parser.add_argument("--interval-seconds", type=float, default=30.0)
    parser.add_argument("--session", default=None)
    args = parser.parse_args(argv)

    print("=" * 60)
    print("NOVA CLASS CAPTURE ENDURANCE SOAK")
    print("=" * 60)
    print(f"Watching for {args.minutes:.0f} minute(s).")
    print("This observer never stops the recording.")
    print()

    result = run_soak(
        minutes=args.minutes,
        interval_seconds=args.interval_seconds,
        session=args.session,
    )

    print()
    print("=" * 60)
    print("RESULT:", "PASS" if result.passed else "FAIL")
    print(f"Watched:        {result.minutes_watched:.1f} min ({result.samples} samples)")
    print(f"Chunks:         {result.chunks_first} -> {result.chunks_last}")
    print(f"Recorded audio: {result.recorded_seconds / 60.0:.1f} min")
    print(f"Max write age:  {result.max_last_write_age:.1f}s")
    print(f"Max lag:        {result.max_transcript_lag:.1f}s")
    print(
        f"Recorder RSS:   {result.recorder_rss_start_mb:.0f} MB -> "
        f"{result.recorder_rss_max_mb:.0f} MB"
    )
    print(f"STT reconnects: {result.stt_reconnects}")
    for item in result.warnings:
        print("WARNING:", item)
    for item in result.failures:
        print("FAILURE:", item)
    print("=" * 60)
    return 0 if result.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
