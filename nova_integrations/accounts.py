"""Account registry with provider isolation and safe labels."""

from __future__ import annotations

import hashlib
import re
from dataclasses import replace

from .models import AccountHealth, ConnectedAccount, ContentMode, Provider
from .secrets import SecretStore, delete_all_cursors, oauth_key
from .storage import IntegrationDatabase


_LABEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _().-]{1,49}$")


def stable_account_id(provider: Provider, provider_subject: str) -> str:
    digest = hashlib.sha256(f"{provider.value}:{provider_subject}".encode("utf-8")).hexdigest()
    return f"{provider.value[:2]}_{digest[:20]}"


def mask_principal(value: str) -> str:
    value = value.strip()
    if "@" not in value:
        return "connected account"
    local, domain = value.split("@", 1)
    shown = local[:2] + "***" if local else "***"
    return f"{shown}@{domain}"


class AccountRegistry:
    def __init__(self, database: IntegrationDatabase, secrets: SecretStore) -> None:
        self.database = database
        self.secrets = secrets

    def add(self, account: ConnectedAccount, oauth_cache: str) -> None:
        if not _LABEL_RE.fullmatch(account.label.strip()):
            raise ValueError(
                "Account label must be 2-50 characters and contain only letters, numbers, spaces, '.', '-', '_', or parentheses."
            )
        existing = self.database.get_account(account.label)
        if existing and existing.account_id != account.account_id:
            raise ValueError(f"An account label named '{account.label}' already exists.")
        self.secrets.set(oauth_key(account.provider.value, account.account_id), oauth_cache)
        self.database.upsert_account(account)
        self.database.audit(
            "account_connected",
            account_id=account.account_id,
            provider=account.provider.value,
            detail=f"label={account.label}; services={','.join(account.enabled_services)}",
        )

    def list(self) -> list[ConnectedAccount]:
        return self.database.list_accounts()

    def resolve(self, account_id_or_label: str) -> ConnectedAccount:
        account = self.database.get_account(account_id_or_label)
        if not account:
            raise KeyError(f"No connected NOVA account matches '{account_id_or_label}'.")
        return account

    def update_health(self, account: ConnectedAccount, health: AccountHealth, detail: str = "") -> None:
        self.database.set_account_health(account.account_id, health, detail)

    def update_content_mode(self, account_id_or_label: str, mode: ContentMode) -> ConnectedAccount:
        account = self.resolve(account_id_or_label)
        updated = replace(account, content_mode=mode)
        self.database.upsert_account(updated)
        return updated

    def update_notifications(
        self,
        account_id_or_label: str,
        *,
        enabled: bool | None = None,
        important_only: bool | None = None,
    ) -> ConnectedAccount:
        account = self.resolve(account_id_or_label)
        updated = replace(
            account,
            notifications_enabled=(
                account.notifications_enabled if enabled is None else bool(enabled)
            ),
            important_only=(
                account.important_only if important_only is None else bool(important_only)
            ),
        )
        self.database.upsert_account(updated)
        self.database.audit(
            "notification_policy_updated",
            account_id=updated.account_id,
            provider=updated.provider.value,
            detail=(
                f"enabled={updated.notifications_enabled}; "
                f"important_only={updated.important_only}"
            ),
        )
        return updated

    def disconnect(self, account_id_or_label: str) -> ConnectedAccount:
        account = self.resolve(account_id_or_label)
        self.secrets.delete(oauth_key(account.provider.value, account.account_id))
        delete_all_cursors(self.secrets, account.provider.value, account.account_id)
        self.database.delete_account(account.account_id)
        self.database.audit(
            "account_disconnected",
            account_id=account.account_id,
            provider=account.provider.value,
            detail=f"label={account.label}",
        )
        return account
