"""A full 180-minute sitting at the PRODUCTION chunk size, simulated.

The 2026-08-27 lecture died at 38m36s. This module drives a complete three-hour
class through the real `ChunkedAudioRecorder` and the real supervisor and
asserts the properties that failure violated: one session id, one continuous
chunk sequence, exact timestamps, nothing overwritten, no automatic stop, and no
memory that grows with the length of the lecture.

**Chunk size here is the production default, not a test-tuned value.** The
recorder is constructed without `chunk_seconds`, so it uses
`audio_chunks.DEFAULT_CHUNK_SECONDS` (20 s) — the same value
`class_capture.py` passes for `NOVA_CLASS_AUDIO_CHUNK_SECONDS`. 180 minutes at
20 seconds is **540 chunks**, which is what a real three-hour class produces.
An earlier version of this file used 30-second chunks and therefore asserted
360, a count no real session would ever have.

Only the *sample rate* is scaled down (800 Hz instead of 16 kHz) and only to
keep the fixture's disk footprint sane. Chunk boundaries, sequence numbering,
manifest records and timestamp arithmetic are all frame-derived, so they behave
identically at 16 kHz — `test_nova_class_recovery.py` exercises the real
16 kHz recorder against a real microphone.
"""

from __future__ import annotations

import re
import tracemalloc
from pathlib import Path

import pytest

from nova_capture.audio_chunks import (
    DEFAULT_CHUNK_SECONDS,
    ChunkedAudioRecorder,
    read_manifest,
    scan_audio_dir,
)
from nova_capture.supervisor import (
    ClassSessionSupervisor,
    SessionOutcome,
    WorkerStatus,
)


LONG_SESSION_SECONDS = 180 * 60

#: Deliberately NOT a constant of this module's choosing. A three-hour class
#: must produce whatever the shipped default produces.
PRODUCTION_CHUNK_SECONDS = DEFAULT_CHUNK_SECONDS
EXPECTED_CHUNKS = int(LONG_SESSION_SECONDS / PRODUCTION_CHUNK_SECONDS)

#: Scaled only to keep the fixture small on disk; see the module docstring.
SAMPLE_RATE = 800


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


# --- the production default itself ------------------------------------------


def test_production_chunk_default_is_twenty_seconds() -> None:
    """If the shipped default moves, this whole module must be revisited."""
    assert DEFAULT_CHUNK_SECONDS == 20.0

    source = (Path(__file__).resolve().parents[1] / "class_capture.py").read_text(
        encoding="utf-8-sig"
    )
    match = re.search(
        r'_env_float\(\s*"NOVA_CLASS_AUDIO_CHUNK_SECONDS"\s*,\s*([0-9.]+)\s*\)',
        source,
    )
    assert match is not None, "class_capture.py must set an explicit chunk default"
    assert float(match.group(1)) == DEFAULT_CHUNK_SECONDS, (
        "class_capture.py and audio_chunks.py disagree about the chunk default"
    )


def test_three_hours_at_the_production_default_is_540_chunks() -> None:
    assert EXPECTED_CHUNKS == 540


# --- the simulated sitting ---------------------------------------------------


@pytest.fixture(scope="module")
def long_session(tmp_path_factory) -> dict:
    """Record a simulated three-hour lecture once and reuse the evidence."""
    root = tmp_path_factory.mktemp("long-session")
    audio_dir = root / "audio"

    # No chunk_seconds argument: this is the shipped default doing the work.
    recorder = ChunkedAudioRecorder(
        audio_dir,
        sample_rate=SAMPLE_RATE,
        channels=1,
        fsync=False,
    )
    assert recorder.chunk_seconds == PRODUCTION_CHUNK_SECONDS

    clock = FakeClock()
    supervisor = ClassSessionSupervisor(
        session_id="2026-08-28_09-00-00_longrun",
        course="COP3710",
        session_path=root,
        clock=clock,
        health_interval_seconds=0.0,
    )
    supervisor.open()

    tracemalloc.start()
    baseline, _peak = tracemalloc.get_traced_memory()
    half_way_retained: float | None = None

    recorder.start()
    # One second of device callbacks at a time, exactly as sounddevice delivers.
    block = b"\x01\x00" * SAMPLE_RATE
    for second in range(LONG_SESSION_SECONDS):
        recorder.write_pcm(block)
        clock.advance(1.0)
        if second == LONG_SESSION_SECONDS // 2:
            current, _ = tracemalloc.get_traced_memory()
            half_way_retained = current - baseline
        if second % 60 == 0:
            supervisor.audio_progress(
                recorded_seconds=recorder.recorded_seconds,
                chunks=recorder.chunk_count,
                last_chunk=recorder.last_sequence,
                last_write_age_seconds=0.0,
            )
            supervisor.transcription_progress(recorder.recorded_seconds - 2.0)

    retained, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    bytes_written = sum(path.stat().st_size for path in audio_dir.glob("*.wav"))

    return {
        "root": root,
        "audio_dir": audio_dir,
        "recorder": recorder,
        "supervisor": supervisor,
        "clock": clock,
        "retained_bytes": retained - baseline,
        "half_way_retained_bytes": half_way_retained,
        "peak_bytes": peak,
        "bytes_written": bytes_written,
    }


def test_three_hours_never_stops_itself(long_session: dict) -> None:
    recorder: ChunkedAudioRecorder = long_session["recorder"]
    supervisor: ClassSessionSupervisor = long_session["supervisor"]

    assert recorder.active, "the recorder must still be recording after 180 minutes"
    assert not supervisor.stop_requested
    assert not supervisor.finalized
    assert supervisor.worker_status("audio") is WorkerStatus.RECORDING


def test_one_logical_session_for_the_whole_sitting(long_session: dict) -> None:
    supervisor: ClassSessionSupervisor = long_session["supervisor"]
    health = supervisor.health_snapshot()
    assert health["session_id"] == "2026-08-28_09-00-00_longrun"
    assert health["duration_seconds"] == pytest.approx(LONG_SESSION_SECONDS, abs=1.0)


def test_a_real_three_hour_class_produces_540_chunks(long_session: dict) -> None:
    """The headline number, produced by the recorder rather than asserted at it."""
    recorder: ChunkedAudioRecorder = long_session["recorder"]
    records = read_manifest(long_session["audio_dir"])
    files = sorted(long_session["audio_dir"].glob("*.wav"))

    assert recorder.chunk_count == EXPECTED_CHUNKS == 540
    assert len(records) == 540
    assert len(files) == 540


def test_chunk_sequence_is_continuous_across_three_hours(long_session: dict) -> None:
    records = read_manifest(long_session["audio_dir"])
    sequences = [item["sequence"] for item in records]
    assert sequences == list(range(1, EXPECTED_CHUNKS + 1))


def test_nothing_was_overwritten(long_session: dict) -> None:
    """540 distinct sequence numbers, 540 distinct files, one record each."""
    records = read_manifest(long_session["audio_dir"])
    sequences = [item["sequence"] for item in records]
    names = [item["file"] for item in records]

    assert len(set(sequences)) == len(sequences), "a sequence number was reused"
    assert len(set(names)) == len(names), "a chunk filename was reused"

    on_disk = {path.name for path in long_session["audio_dir"].glob("*.wav")}
    assert on_disk == set(names), "manifest and directory disagree"

    # Every published chunk carries real audio; none was silently replaced by
    # a later, shorter write.
    for item in records[:-1]:
        assert item["frames"] == int(PRODUCTION_CHUNK_SECONDS * SAMPLE_RATE)


def test_frame_ranges_are_continuous_and_complete(long_session: dict) -> None:
    records = read_manifest(long_session["audio_dir"])
    total_frames = sum(item["frames"] for item in records)
    assert total_frames == LONG_SESSION_SECONDS * SAMPLE_RATE

    expected_start = 0.0
    for item in records:
        assert item["start_seconds"] == pytest.approx(expected_start, abs=1e-6)
        span = item["end_seconds"] - item["start_seconds"]
        assert span == pytest.approx(item["frames"] / SAMPLE_RATE, abs=1e-6)
        expected_start = item["end_seconds"]


def test_timestamp_drift_is_effectively_zero_at_three_hours(
    long_session: dict,
) -> None:
    records = read_manifest(long_session["audio_dir"])
    previous_end = 0.0
    for item in records:
        assert item["start_seconds"] == pytest.approx(previous_end, abs=1e-6)
        previous_end = item["end_seconds"]
    # Last chunk ends exactly on the three-hour mark, with no accumulated drift.
    assert previous_end == pytest.approx(LONG_SESSION_SECONDS, abs=1e-6)


def test_manifest_and_files_agree_after_three_hours(long_session: dict) -> None:
    report = scan_audio_dir(long_session["audio_dir"], recording=True)
    assert report.chunk_count == EXPECTED_CHUNKS
    assert report.recorded_seconds == pytest.approx(LONG_SESSION_SECONDS, abs=0.5)
    assert report.sequence_gaps == []
    assert report.timestamp_gaps == []
    assert report.missing_files == []
    assert report.truncated_files == []
    assert report.unlisted_files == []
    assert report.malformed_manifest_lines == 0
    # Still recording, so the chunk in flight is in progress, not damage.
    assert report.incomplete_files == []
    assert report.healthy


def test_memory_does_not_grow_with_lecture_length(long_session: dict) -> None:
    """Audio must stream to disk, never accumulate in RAM."""
    retained = long_session["retained_bytes"]
    half_way = long_session["half_way_retained_bytes"]
    written = long_session["bytes_written"]

    assert written > 5_000_000, "the simulation must write a meaningful amount"
    # Only per-chunk metadata may be retained -- a few hundred small records,
    # not three hours of PCM.
    assert retained < 1_000_000, f"recorder retained {retained} bytes of memory"
    assert retained < written / 10

    # And the second half must not cost more than the first: memory is a
    # function of chunk count, not of how long the class has been running.
    assert half_way is not None
    assert retained - half_way < 500_000, (
        f"memory grew {retained - half_way} bytes over the second 90 minutes"
    )


def test_long_session_finalizes_as_one_completed_class(long_session: dict) -> None:
    recorder: ChunkedAudioRecorder = long_session["recorder"]
    supervisor: ClassSessionSupervisor = long_session["supervisor"]

    supervisor.request_stop("user_requested")
    recorder.stop()
    supervisor.audio_progress(
        recorded_seconds=recorder.recorded_seconds,
        chunks=recorder.chunk_count,
        last_chunk=recorder.last_sequence,
        last_write_age_seconds=0.0,
        status=WorkerStatus.STOPPED,
    )
    supervisor.set_worker("stt", WorkerStatus.CONNECTED)
    supervisor.set_worker("notes", WorkerStatus.ACTIVE)

    outcome = supervisor.finalize()
    assert outcome is SessionOutcome.COMPLETED
    assert supervisor.health_snapshot()["audio_integrity"]["healthy"] is True
    # A clean stop on an exact chunk boundary publishes nothing extra.
    assert recorder.chunk_count == EXPECTED_CHUNKS


def test_health_file_is_written_and_readable(long_session: dict) -> None:
    root: Path = long_session["root"]
    assert (root / "health.json").is_file()
    assert (root / "events.jsonl").is_file()
