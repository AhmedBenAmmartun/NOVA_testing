"""Durable chunked audio: the recording must survive everything else."""

from __future__ import annotations

import json
import wave
from pathlib import Path

import pytest

from nova_capture.audio_chunks import (
    ChunkedAudioRecorder,
    chunk_filename,
    read_manifest,
    scan_audio_dir,
)


SAMPLE_RATE = 800
CHUNK_SECONDS = 2.0


def _recorder(path: Path, **overrides) -> ChunkedAudioRecorder:
    options = {
        "sample_rate": SAMPLE_RATE,
        "channels": 1,
        "sample_width": 2,
        "chunk_seconds": CHUNK_SECONDS,
        "fsync": False,
    }
    options.update(overrides)
    return ChunkedAudioRecorder(path, **options)


def _feed(recorder: ChunkedAudioRecorder, seconds: float) -> None:
    frames = int(seconds * recorder.sample_rate)
    recorder.write_pcm(b"\x01\x00" * frames)


def test_chunks_roll_over_and_each_one_is_a_valid_wav(tmp_path: Path) -> None:
    recorder = _recorder(tmp_path / "audio")
    recorder.start()
    _feed(recorder, CHUNK_SECONDS * 3)
    recorder.stop()

    files = sorted((tmp_path / "audio").glob("*.wav"))
    assert len(files) == 3
    for index, path in enumerate(files, start=1):
        assert path.name == chunk_filename(index)
        with wave.open(str(path), "rb") as handle:
            assert handle.getframerate() == SAMPLE_RATE
            assert handle.getnchannels() == 1
            assert handle.getnframes() == int(CHUNK_SECONDS * SAMPLE_RATE)


def test_completed_chunks_are_playable_before_the_session_ends(tmp_path: Path) -> None:
    """The whole point: a crash mid-lecture must not cost the lecture."""
    recorder = _recorder(tmp_path / "audio")
    recorder.start()
    _feed(recorder, CHUNK_SECONDS * 2)

    # The recorder is still running and has never been stopped.
    finished = sorted((tmp_path / "audio").glob("*.wav"))
    assert len(finished) == 2
    for path in finished:
        with wave.open(str(path), "rb") as handle:
            assert handle.getnframes() > 0

    recorder.stop()


def test_manifest_records_every_completed_chunk(tmp_path: Path) -> None:
    recorder = _recorder(tmp_path / "audio")
    recorder.start()
    _feed(recorder, CHUNK_SECONDS * 2 + 0.5)
    recorder.stop()

    records = read_manifest(tmp_path / "audio")
    assert [item["sequence"] for item in records] == [1, 2, 3]
    assert records[0]["start_seconds"] == pytest.approx(0.0)
    assert records[0]["end_seconds"] == pytest.approx(CHUNK_SECONDS)
    assert records[1]["start_seconds"] == pytest.approx(CHUNK_SECONDS)
    assert records[2]["end_seconds"] == pytest.approx(CHUNK_SECONDS * 2 + 0.5)
    for item in records:
        assert item["status"] == "complete"
        assert item["sample_rate"] == SAMPLE_RATE
        assert (tmp_path / "audio" / item["file"]).stat().st_size == item["bytes"]


def test_timestamps_come_from_frames_not_the_wall_clock(tmp_path: Path) -> None:
    recorder = _recorder(tmp_path / "audio")
    recorder.start()
    _feed(recorder, CHUNK_SECONDS * 5)
    recorder.stop()

    records = read_manifest(tmp_path / "audio")
    previous_end = 0.0
    for item in records:
        assert item["start_seconds"] == pytest.approx(previous_end)
        previous_end = item["end_seconds"]
    assert previous_end == pytest.approx(CHUNK_SECONDS * 5)


def test_partial_chunk_is_finalized_on_stop(tmp_path: Path) -> None:
    recorder = _recorder(tmp_path / "audio")
    recorder.start()
    _feed(recorder, CHUNK_SECONDS + 0.75)
    recorder.stop()

    report = scan_audio_dir(tmp_path / "audio")
    assert report.chunk_count == 2
    assert report.recorded_seconds == pytest.approx(CHUNK_SECONDS + 0.75)
    assert report.healthy
    assert not list((tmp_path / "audio").glob("*.tmp"))


def test_empty_final_chunk_is_not_published(tmp_path: Path) -> None:
    recorder = _recorder(tmp_path / "audio")
    recorder.start()
    _feed(recorder, CHUNK_SECONDS)
    recorder.stop()

    report = scan_audio_dir(tmp_path / "audio")
    assert report.chunk_count == 1
    assert report.manifest_entries == 1


def test_in_progress_chunk_is_visible_while_recording(tmp_path: Path) -> None:
    audio = tmp_path / "audio"
    recorder = _recorder(audio)
    recorder.start()
    _feed(recorder, CHUNK_SECONDS * 2 + 0.5)

    report = scan_audio_dir(audio)
    assert report.chunk_count == 2, "completed chunks are readable mid-lecture"
    assert report.incomplete_files == [f"{chunk_filename(3)}.tmp"]

    recorder.stop()


def test_orphaned_temp_chunk_from_a_crash_is_detectable(tmp_path: Path) -> None:
    """An abrupt death leaves a .tmp behind; the next startup must see it."""
    audio = tmp_path / "audio"
    recorder = _recorder(audio)
    recorder.start()
    _feed(recorder, CHUNK_SECONDS * 2)
    recorder.stop()

    # Exactly what a killed process leaves: an unfinished, unrenamed chunk.
    (audio / f"{chunk_filename(3)}.tmp").write_bytes(b"RIFF")

    report = scan_audio_dir(audio)
    assert report.chunk_count == 2, "completed chunks must survive"
    assert report.incomplete_files == [f"{chunk_filename(3)}.tmp"]
    assert not report.healthy


def test_missing_and_truncated_chunks_are_detected(tmp_path: Path) -> None:
    audio = tmp_path / "audio"
    recorder = _recorder(audio)
    recorder.start()
    _feed(recorder, CHUNK_SECONDS * 4)
    recorder.stop()

    (audio / chunk_filename(2)).unlink()
    truncated = audio / chunk_filename(3)
    truncated.write_bytes(truncated.read_bytes()[:100])

    report = scan_audio_dir(audio)
    assert report.missing_files == [chunk_filename(2)]
    assert report.truncated_files == [chunk_filename(3)]
    assert not report.healthy


def test_timestamp_gap_is_detected(tmp_path: Path) -> None:
    audio = tmp_path / "audio"
    audio.mkdir()
    manifest = audio / "manifest.jsonl"
    rows = [
        {
            "sequence": 1,
            "file": chunk_filename(1),
            "start_seconds": 0.0,
            "end_seconds": 20.0,
            "frames": 16000,
            "bytes": 0,
            "sample_rate": 800,
            "channels": 1,
            "sample_width": 2,
            "status": "complete",
        },
        {
            "sequence": 2,
            "file": chunk_filename(2),
            "start_seconds": 45.0,
            "end_seconds": 65.0,
            "frames": 16000,
            "bytes": 0,
            "sample_rate": 800,
            "channels": 1,
            "sample_width": 2,
            "status": "complete",
        },
    ]
    manifest.write_text(
        "\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8"
    )
    for row in rows:
        (audio / row["file"]).write_bytes(b"x" * 64)

    report = scan_audio_dir(audio)
    assert report.timestamp_gaps == [{"after_seconds": 20.0, "before_seconds": 45.0}]
    assert not report.healthy


def test_malformed_manifest_line_is_reported_not_crashed(tmp_path: Path) -> None:
    audio = tmp_path / "audio"
    recorder = _recorder(audio)
    recorder.start()
    _feed(recorder, CHUNK_SECONDS)
    recorder.stop()

    with (audio / "manifest.jsonl").open("a", encoding="utf-8") as handle:
        handle.write("{not json at all\n")

    report = scan_audio_dir(audio)
    assert report.malformed_manifest_lines == 1
    assert report.chunk_count == 1


def test_restarted_recorder_resumes_instead_of_overwriting(tmp_path: Path) -> None:
    """A restarted recorder process must never reuse sequence 1."""
    audio = tmp_path / "audio"
    first = _recorder(audio)
    first.start()
    _feed(first, CHUNK_SECONDS * 2)
    first.stop()

    second = _recorder(audio)
    second.start()
    _feed(second, CHUNK_SECONDS * 2)
    second.stop()

    report = scan_audio_dir(audio)
    assert report.chunk_count == 4
    assert report.recorded_seconds == pytest.approx(CHUNK_SECONDS * 4)
    assert report.healthy
    records = read_manifest(audio)
    assert [item["sequence"] for item in records] == [1, 2, 3, 4]
    assert records[2]["start_seconds"] == pytest.approx(CHUNK_SECONDS * 2)


def test_recorder_state_file_reports_progress(tmp_path: Path) -> None:
    recorder = _recorder(tmp_path / "audio")
    recorder.start()
    _feed(recorder, CHUNK_SECONDS * 2)
    payload = recorder.write_state(status="recording")
    recorder.stop()

    assert payload["status"] == "recording"
    assert payload["chunks"] == 2
    assert payload["last_chunk"] == 2
    assert payload["recorded_seconds"] == pytest.approx(CHUNK_SECONDS * 2)
    on_disk = json.loads(
        (tmp_path / "audio" / "recorder.json").read_text(encoding="utf-8")
    )
    assert on_disk["chunks"] == 2
