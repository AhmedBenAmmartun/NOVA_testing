from __future__ import annotations

import asyncio
import json
from pathlib import Path

from nova_learning import (
    Experience,
    NDJSONExperienceStore,
    begin_experience,
    end_experience,
    observed,
    redact,
)


def test_redaction_removes_secrets_and_large_content() -> None:
    safe = redact(
        {
            "api_key": "secret-value",
            "file_path": r"C:\\Users\\someone\\Documents\\report.pdf",
            "transcript": "private class transcript",
            "nested": {"Authorization": "Bearer abc123"},
        }
    )
    assert safe["api_key"] == "<redacted>"
    assert safe["file_path"] == "file:report.pdf"
    assert safe["transcript"] == "<transcript redacted>"
    assert safe["nested"]["Authorization"] == "<redacted>"


def test_store_appends_experience_and_patch(tmp_path: Path) -> None:
    store = NDJSONExperienceStore(tmp_path)
    experience = Experience(intent="open_app", utterance_redacted="open Spotify")
    first = store.append_experience(experience)
    second = store.append_patch(
        experience.id,
        {"user_correction": "not that one", "outcome": "failure"},
    )

    assert first.path.exists()
    assert second.path.exists()
    all_lines = []
    for path in sorted(tmp_path.glob("*.ndjson")):
        all_lines.extend(path.read_text(encoding="utf-8").splitlines())
    records = [json.loads(line) for line in all_lines]
    assert [item["record_type"] for item in records] == ["experience", "patch"]
    assert records[0]["experience"]["id"] == experience.id


def test_observed_records_success_and_failure() -> None:
    @observed("desktop.test")
    async def ok(*, value: int) -> int:
        return value + 1

    @observed("desktop.fail")
    async def fail(*, token: str) -> None:
        raise RuntimeError("boom")

    async def run() -> None:
        scope = begin_experience(Experience())
        assert await ok(value=2) == 3
        try:
            await fail(token="top-secret")
        except RuntimeError:
            pass
        experience = end_experience(scope)
        assert len(experience.tools) == 2
        assert experience.tools[0].ok is True
        assert experience.tools[1].ok is False
        assert experience.tools[1].error == "RuntimeError"

    asyncio.run(run())
