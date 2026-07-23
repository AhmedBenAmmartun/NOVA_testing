"""Encrypted OS-backed secret storage for OAuth caches and sync cursors."""

from __future__ import annotations

from abc import ABC, abstractmethod
from threading import RLock
import json


class SecretStoreError(RuntimeError):
    pass


class SecretStore(ABC):
    @abstractmethod
    def get(self, key: str) -> str | None: ...

    @abstractmethod
    def set(self, key: str, value: str) -> None: ...

    @abstractmethod
    def delete(self, key: str) -> None: ...


class KeyringSecretStore(SecretStore):
    """Uses Windows Credential Manager through Python keyring on Windows."""

    def __init__(self, service_name: str = "NOVA.Integrations") -> None:
        try:
            import keyring
            from keyring.errors import KeyringError
        except ImportError as exc:
            raise SecretStoreError("Install the 'keyring' package before connecting accounts.") from exc

        backend_name = keyring.get_keyring().__class__.__module__.lower()
        if "fail" in backend_name or "plaintext" in backend_name:
            raise SecretStoreError(
                "No secure OS keyring backend is available. NOVA will not store OAuth tokens in plaintext."
            )
        self._keyring = keyring
        self._keyring_error = KeyringError
        self._service = service_name

    def get(self, key: str) -> str | None:
        try:
            return self._keyring.get_password(self._service, key)
        except self._keyring_error as exc:
            raise SecretStoreError("Could not read NOVA credentials from the OS keyring.") from exc

    def set(self, key: str, value: str) -> None:
        if not value:
            raise SecretStoreError("Refusing to store an empty credential value.")
        try:
            self._keyring.set_password(self._service, key, value)
        except self._keyring_error as exc:
            raise SecretStoreError("Could not save NOVA credentials to the OS keyring.") from exc

    def delete(self, key: str) -> None:
        try:
            self._keyring.delete_password(self._service, key)
        except Exception:
            # Deleting an already-absent item is intentionally idempotent.
            return


class MemorySecretStore(SecretStore):
    """Test-only in-memory store. Never use for real account authorization."""

    def __init__(self) -> None:
        self._items: dict[str, str] = {}
        self._lock = RLock()

    def get(self, key: str) -> str | None:
        with self._lock:
            return self._items.get(key)

    def set(self, key: str, value: str) -> None:
        with self._lock:
            self._items[key] = value

    def delete(self, key: str) -> None:
        with self._lock:
            self._items.pop(key, None)


def oauth_key(provider: str, account_id: str) -> str:
    return f"oauth:{provider}:{account_id}"


def cursor_key(provider: str, account_id: str, resource: str) -> str:
    return f"cursor:{provider}:{account_id}:{resource}"


def _cursor_index_key(provider: str, account_id: str) -> str:
    return f"cursor-index:{provider}:{account_id}"


def get_cursor(store: SecretStore, provider: str, account_id: str, resource: str) -> str | None:
    return store.get(cursor_key(provider, account_id, resource))


def set_cursor(store: SecretStore, provider: str, account_id: str, resource: str, value: str) -> None:
    key = cursor_key(provider, account_id, resource)
    store.set(key, value)
    index_key = _cursor_index_key(provider, account_id)
    try:
        current = json.loads(store.get(index_key) or "[]")
    except json.JSONDecodeError:
        current = []
    keys = sorted(set(str(item) for item in current) | {key})
    store.set(index_key, json.dumps(keys))


def delete_cursor(store: SecretStore, provider: str, account_id: str, resource: str) -> None:
    key = cursor_key(provider, account_id, resource)
    store.delete(key)
    index_key = _cursor_index_key(provider, account_id)
    try:
        current = json.loads(store.get(index_key) or "[]")
    except json.JSONDecodeError:
        current = []
    remaining = [str(item) for item in current if str(item) != key]
    if remaining:
        store.set(index_key, json.dumps(sorted(set(remaining))))
    else:
        store.delete(index_key)


def delete_all_cursors(store: SecretStore, provider: str, account_id: str) -> None:
    index_key = _cursor_index_key(provider, account_id)
    try:
        keys = json.loads(store.get(index_key) or "[]")
    except json.JSONDecodeError:
        keys = []
    for key in keys:
        store.delete(str(key))
    store.delete(index_key)
