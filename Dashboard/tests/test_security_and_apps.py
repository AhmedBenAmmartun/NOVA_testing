from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

DASHBOARD_DIR = Path(__file__).resolve().parent.parent
PROJECT_ROOT = DASHBOARD_DIR.parent
for path in (str(PROJECT_ROOT), str(DASHBOARD_DIR)):
    if path not in sys.path:
        sys.path.insert(0, path)

import actions  # noqa: E402
from app_registry import normalize_record, perform_action  # noqa: E402
from security import (  # noqa: E402
    can_open_recent_target,
    is_sensitive_name,
    is_sensitive_path,
    safe_recent_target,
)


class SensitiveFileTests(unittest.TestCase):
    def test_sensitive_names_and_directories_are_rejected(self) -> None:
        blocked = [
            ".env",
            ".env.local",
            "credentials.json",
            "secrets-prod.txt",
            "token-cache.json",
            "passwords.csv",
            "id_rsa",
            "id_ed25519",
            "client.pem",
            "private.key",
            "identity.pfx",
            "identity.p12",
            "vault.kdbx",
        ]
        for name in blocked:
            with self.subTest(name=name):
                self.assertTrue(is_sensitive_name(name))
        self.assertTrue(is_sensitive_path(r"C:\Users\Ahmed\.ssh\known_hosts"))
        self.assertTrue(is_sensitive_path(r"C:\Users\Ahmed\.aws\config"))
        self.assertTrue(is_sensitive_path(r"C:\NOVA\.azure\profile.json"))
        self.assertFalse(is_sensitive_path(r"C:\Users\Ahmed\Documents\report.pdf"))

    def test_shortcut_target_is_resolved_before_recent_item_is_allowed(self) -> None:
        shortcut = Path("report.lnk")
        safe = safe_recent_target(
            shortcut,
            resolver=lambda _path: r"C:\Users\Ahmed\Documents\report.pdf",
        )
        self.assertEqual(safe, ("report", r"C:\Users\Ahmed\Documents\report.pdf"))

        unsafe = safe_recent_target(
            shortcut,
            resolver=lambda _path: r"C:\Users\Ahmed\AI Agent\.env",
        )
        self.assertIsNone(unsafe)

    def test_unresolved_shortcuts_fail_closed(self) -> None:
        self.assertIsNone(safe_recent_target(Path("report.lnk"), resolver=lambda _path: None))

    def test_backend_guard_blocks_sensitive_recent_target(self) -> None:
        self.assertFalse(can_open_recent_target(r"C:\Users\Ahmed\.gnupg\private-keys-v1.d\key"))
        with patch.object(actions, "_start") as starter:
            replies = actions.handle(
                {"type": "open_recent", "id": "recent_123"},
                {"recent": {"recent_123": r"C:\Users\Ahmed\AI Agent\.env"}},
                None,
            )
        starter.assert_not_called()
        self.assertIn("blocked", replies[0]["text"].lower())


class ApplicationRegistryTests(unittest.TestCase):
    def test_normalized_records_have_stable_opaque_ids(self) -> None:
        first = normalize_record(
            name="Visual Studio Code",
            app_type="win32",
            launch_target=r"C:\Program Files\Microsoft VS Code\Code.exe",
            process_names=("Code.exe",),
        )
        second = normalize_record(
            name="Visual Studio Code",
            app_type="win32",
            launch_target=r"C:\Program Files\Microsoft VS Code\Code.exe",
            process_names=("Code.exe",),
        )
        self.assertIsNotNone(first)
        self.assertIsNotNone(second)
        assert first is not None and second is not None
        self.assertEqual(first.app_id, second.app_id)
        self.assertTrue(first.app_id.startswith("app_"))
        self.assertEqual(first.name, "VS Code")

    def test_public_record_never_exposes_launch_information(self) -> None:
        record = normalize_record(
            name="Mail",
            app_type="uwp",
            launch_target=r"shell:AppsFolder\microsoft.windowscommunicationsapps_8wekyb3d8bbwe!microsoft.windowslive.mail",
            aumid="private-aumid",
        )
        self.assertIsNotNone(record)
        public = record.public()  # type: ignore[union-attr]
        self.assertNotIn("launch_target", public)
        self.assertNotIn("launchTarget", public)
        self.assertNotIn("processNames", public)
        self.assertNotIn("aumid", public)

    def test_invalid_ids_and_path_injection_are_rejected(self) -> None:
        self.assertEqual(perform_action({}, "app_missing", "activate"), (False, "invalid_app_id"))
        replies = actions.handle(
            {
                "type": "app_action",
                "id": r"C:\Windows\System32\cmd.exe",
                "action": "launch",
                "command": "powershell -enc ...",
            },
            {"apps": {}},
            None,
        )
        self.assertIn("not registered", replies[0]["text"].lower())

    def test_win32_and_uwp_records_are_normalized(self) -> None:
        win32 = normalize_record(
            name="Calculator",
            app_type="win32",
            launch_target=r"C:\Windows\System32\calc.exe",
            process_names=("calc.exe",),
        )
        uwp = normalize_record(
            name="Photos",
            app_type="uwp",
            launch_target=r"shell:AppsFolder\Microsoft.Windows.Photos_8wekyb3d8bbwe!App",
            aumid="Microsoft.Windows.Photos_8wekyb3d8bbwe!App",
        )
        self.assertEqual(win32.app_type, "win32")  # type: ignore[union-attr]
        self.assertEqual(uwp.app_type, "uwp")  # type: ignore[union-attr]


if __name__ == "__main__":
    unittest.main()
