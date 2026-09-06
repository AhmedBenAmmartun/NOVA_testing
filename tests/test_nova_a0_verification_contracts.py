from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from nova_verification import VerificationStatus, verify_fields, verify_text_write
from tools import capabilities as capability_tools
from tools import class_capture as class_tools


def test_verify_fields_reports_verified_and_failed() -> None:
    good = verify_fields(
        "demo",
        expected={"state": "ready"},
        observed={"state": "ready"},
    )
    assert good.ok
    assert good.status is VerificationStatus.VERIFIED
    assert "VERIFIED" in good.render()

    bad = verify_fields(
        "demo",
        expected={"state": "ready"},
        observed={"state": "broken"},
    )
    assert not bad.ok
    assert bad.status is VerificationStatus.FAILED
    assert "expected='ready'" in bad.observation


def test_verify_text_write_reads_exact_bytes(tmp_path: Path) -> None:
    target = tmp_path / "note.txt"
    target.write_text("hello NOVA", encoding="utf-8")

    good = verify_text_write(target, "hello NOVA")
    assert good.ok
    assert "sha256=" in good.observation
    assert "hello NOVA" not in good.observation

    bad = verify_text_write(target, "different")
    assert not bad.ok
    assert bad.status is VerificationStatus.FAILED


def test_class_start_contract_requires_transcript_health_and_audio(tmp_path: Path) -> None:
    active = SimpleNamespace(
        course="COT3400",
        session_id="session-a0",
        session_path=str(tmp_path),
    )

    (tmp_path / "session.json").write_text("{}", encoding="utf-8")
    (tmp_path / "transcript.jsonl").write_text("", encoding="utf-8")
    (tmp_path / "transcript.txt").write_text("", encoding="utf-8")
    (tmp_path / "health.json").write_text(
        json.dumps(
            {
                "session_id": "session-a0",
                "workers": {"audio": {"status": "recording"}},
            }
        ),
        encoding="utf-8",
    )

    good = class_tools._verify_class_start_artifacts(
        active,
        expected_course="COT3400",
    )
    assert good.ok

    (tmp_path / "health.json").write_text(
        json.dumps(
            {
                "session_id": "session-a0",
                "workers": {"audio": {"status": "failed"}},
            }
        ),
        encoding="utf-8",
    )
    bad = class_tools._verify_class_start_artifacts(
        active,
        expected_course="COT3400",
    )
    assert not bad.ok
    assert "audio_status" in bad.observation


class _FakeSpec:
    capability_id = "demo"
    tools = (object(),)


class _FakeRegistry:
    def get(self, _capability_id: str):
        return _FakeSpec()


class _FakeManager:
    def __init__(self, active: bool, exposed: bool) -> None:
        self.registry = _FakeRegistry()
        self._active = active
        self._exposed = exposed

    def is_active(self, _capability_id: str) -> bool:
        return self._active

    def build_tool_context(self):
        items = [SimpleNamespace(id="control")]
        if self._exposed:
            items.append(SimpleNamespace(id="nova_demo"))
        return items


def test_capability_contract_observes_state_and_toolset() -> None:
    good = capability_tools._verify_capability_state(
        _FakeManager(active=True, exposed=True),
        "demo",
        expected_active=True,
    )
    assert good.ok

    bad = capability_tools._verify_capability_state(
        _FakeManager(active=True, exposed=False),
        "demo",
        expected_active=True,
    )
    assert not bad.ok
    assert "toolset_exposed" in bad.observation


def test_a0_is_wired_into_existing_mutations_only() -> None:
    root = Path(__file__).resolve().parents[1]

    files_text = (root / "tools" / "files.py").read_text(encoding="utf-8-sig")
    assert "verify_text_write(path, content)" in files_text

    caps_text = (root / "tools" / "capabilities.py").read_text(encoding="utf-8-sig")
    assert "_verify_capability_state" in caps_text
    assert "await agent.update_tools(manager.build_tool_context())" in caps_text

    class_text = (root / "tools" / "class_capture.py").read_text(encoding="utf-8-sig")
    assert "_verify_class_start_artifacts" in class_text
    assert '"audio_status": "recording"' in class_text
    assert '"class_capture_stop"' in class_text

    service_text = (root / "nova_lab" / "service.py").read_text(encoding="utf-8-sig")
    for contract in (
        '"nova_lab_register"',
        '"nova_lab_test_job_start"',
        '"nova_lab_test_evidence"',
        '"nova_lab_candidate"',
    ):
        assert contract in service_text

    assert "promote_to_active" not in service_text
    assert "activate_production" not in service_text
