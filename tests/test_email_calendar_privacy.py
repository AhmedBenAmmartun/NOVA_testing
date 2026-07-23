from __future__ import annotations

import unittest

from nova_integrations.models import (
    AccountCategory,
    ConnectedAccount,
    ContentMode,
    Provider,
)
from nova_integrations.services import account_allows_body_to_cloud


class PrivacyModeTests(unittest.TestCase):
    def _account(self, mode: ContentMode) -> ConnectedAccount:
        return ConnectedAccount(
            account_id="test",
            provider=Provider.MICROSOFT,
            label="FGCU School",
            category=AccountCategory.SCHOOL,
            principal_hint="ah***@fgcu.edu",
            enabled_services=("mail", "calendar"),
            content_mode=mode,
        )

    def test_metadata_only_cannot_return_body_to_cloud(self) -> None:
        self.assertFalse(account_allows_body_to_cloud(self._account(ContentMode.METADATA_ONLY)))

    def test_local_private_cannot_return_body_to_cloud(self) -> None:
        self.assertFalse(account_allows_body_to_cloud(self._account(ContentMode.LOCAL_PRIVATE)))

    def test_cloud_allowed_is_explicit(self) -> None:
        self.assertTrue(account_allows_body_to_cloud(self._account(ContentMode.CLOUD_ALLOWED)))


if __name__ == "__main__":
    unittest.main()
