from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / "class_capture.py").read_text(encoding="utf-8")


def test_class_capture_has_downloads_auto_organize_kill_switch() -> None:
    assert 'NOVA_CLASS_AUTO_ORGANIZE_DOWNLOADS' in SOURCE
    assert 'if auto_organize_downloads:' in SOURCE
    assert 'organize_recent_downloads_for_course' in SOURCE


def test_downloads_auto_organize_guard_defaults_off_for_safety() -> None:
    assert '_env_bool("NOVA_CLASS_AUTO_ORGANIZE_DOWNLOADS", False)' in SOURCE


def test_smoke_test_can_disable_downloads_scan_without_disabling_capture() -> None:
    assert 'disabled by NOVA_CLASS_AUTO_ORGANIZE_DOWNLOADS' in SOURCE
