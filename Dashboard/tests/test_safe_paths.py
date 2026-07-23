from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

DASHBOARD_DIR = Path(__file__).resolve().parent.parent
PROJECT_ROOT = DASHBOARD_DIR.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(DASHBOARD_DIR))

import safe_paths  # noqa: E402
import actions  # noqa: E402


MUST_BLOCK = [
    ".env", ".env.local", ".env.production",
    "credentials.json", "secrets.yaml", "secret.txt",
    "token.json", "tokens.db", "password.txt", "passwords.csv",
    "id_rsa", "id_ed25519",
    r"C:\Users\ahmed\.ssh\config",
    r"C:\Users\x\.gnupg\secring.gpg",
    r"C:\Users\x\.aws\credentials",
    r"C:\Users\x\.azure\accessTokens.json",
    "cert.pem", "private.key", "client.pfx", "store.p12", "vault.kdbx",
]

MUST_ALLOW = [
    "report.pdf", "notes.md", "agent.py", "photo.jpg", "budget.xlsx",
    "environment-setup.md", "main.tsx", "lecture-07.pdf", "resume.docx",
]


class SensitivePathTests(unittest.TestCase):
    def test_denylist_blocks_all_required_patterns(self):
        for path in MUST_BLOCK:
            self.assertTrue(safe_paths.is_sensitive_path(path), f"should block {path!r}")

    def test_normal_files_are_not_blocked(self):
        for path in MUST_ALLOW:
            self.assertFalse(safe_paths.is_sensitive_path(path), f"should allow {path!r}")

    def test_matching_is_case_insensitive(self):
        self.assertTrue(safe_paths.is_sensitive_path(r"C:\x\.SSH\ID_RSA"))
        self.assertTrue(safe_paths.is_sensitive_path("Cert.PEM"))
        self.assertTrue(safe_paths.is_sensitive_path(".ENV.LOCAL"))


class ShortcutResolutionTests(unittest.TestCase):
    def test_lnk_resolving_to_secret_is_unsafe(self):
        original = safe_paths.resolve_shortcut
        safe_paths.resolve_shortcut = lambda _p: r"C:\Users\ahmed\proj\.env"
        try:
            # innocent shortcut name, but it points at a secret
            self.assertFalse(safe_paths.is_safe_to_surface("notes", r"C:\r\notes.lnk"))
        finally:
            safe_paths.resolve_shortcut = original

    def test_lnk_resolving_to_safe_file_is_safe(self):
        original = safe_paths.resolve_shortcut
        safe_paths.resolve_shortcut = lambda _p: r"C:\Users\ahmed\docs\report.pdf"
        try:
            self.assertTrue(safe_paths.is_safe_to_surface("report", r"C:\r\report.lnk"))
        finally:
            safe_paths.resolve_shortcut = original

    def test_sensitive_name_rejected_even_if_resolution_fails(self):
        original = safe_paths.resolve_shortcut
        safe_paths.resolve_shortcut = lambda _p: None
        try:
            self.assertFalse(safe_paths.is_safe_to_surface(".env", r"C:\r\.env.lnk"))
        finally:
            safe_paths.resolve_shortcut = original


class BackendRefusalTests(unittest.TestCase):
    """The backend open action must refuse sensitive files, not just the UI."""

    def setUp(self):
        self.started: list[str] = []
        self._original_start = actions._start
        actions._start = lambda target: self.started.append(target) or True

    def tearDown(self):
        actions._start = self._original_start

    def _handle(self, message, targets):
        return actions.handle(message, targets, approvals=None)

    def test_open_recent_refuses_sensitive_and_never_calls_startfile(self):
        messages = self._handle(
            {"type": "open_recent", "name": ".env"},
            {"recent": {".env": r"C:\Users\ahmed\proj\.env.lnk"}},
        )
        self.assertEqual(self.started, [])
        self.assertTrue(any("protected" in m.get("text", "").lower() for m in messages))

    def test_open_recent_allows_a_safe_file(self):
        messages = self._handle(
            {"type": "open_recent", "name": "report.pdf"},
            {"recent": {"report.pdf": r"C:\Users\ahmed\docs\report.pdf"}},
        )
        self.assertEqual(len(self.started), 1)
        self.assertTrue(any(m.get("type") == "activity" for m in messages))

    def test_launch_refuses_sensitive_target(self):
        messages = self._handle(
            {"type": "launch", "app": "creds"},
            {"apps": {"creds": r"C:\Users\ahmed\.aws\credentials"}},
        )
        self.assertEqual(self.started, [])
        self.assertTrue(any("protected" in m.get("text", "").lower() for m in messages))

    def test_open_folder_refuses_sensitive_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            aws_dir = os.path.join(tmp, ".aws")
            os.makedirs(aws_dir)
            messages = self._handle(
                {"type": "open_folder", "name": ".aws"},
                {"folders": {".aws": aws_dir}},
            )
            self.assertEqual(self.started, [])
            self.assertTrue(any("protected" in m.get("text", "").lower() for m in messages))


if __name__ == "__main__":
    unittest.main()
