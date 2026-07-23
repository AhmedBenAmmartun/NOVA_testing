"""Microsoft Graph connector for personal, school, and work Outlook accounts."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from typing import Any

import requests

from ..accounts import AccountRegistry, mask_principal, stable_account_id
from ..config import IntegrationConfig
from ..models import AccountCategory, CalendarEvent, ConnectedAccount, ContentMode, MailSummary, Provider
from ..secrets import (
    SecretStore,
    delete_cursor,
    get_cursor,
    oauth_key,
    set_cursor,
)
from .base import (
    AdminApprovalRequired,
    CalendarSyncBatch,
    ConnectorError,
    MailSyncBatch,
    RateLimited,
    ReconnectRequired,
    WorkspaceConnector,
)


GRAPH_ROOT = "https://graph.microsoft.com/v1.0"
BASE_SCOPES = ("User.Read",)
MAIL_SCOPE = "Mail.Read"
CALENDAR_SCOPE = "Calendars.Read"


class MicrosoftGraphConnector(WorkspaceConnector):
    provider = Provider.MICROSOFT

    def __init__(
        self,
        config: IntegrationConfig,
        registry: AccountRegistry,
        secrets: SecretStore,
    ) -> None:
        self.config = config
        self.registry = registry
        self.secrets = secrets

    def connect(
        self,
        *,
        label: str,
        category: AccountCategory,
        services: tuple[str, ...],
        content_mode: ContentMode,
    ) -> ConnectedAccount:
        msal = self._msal()
        client_id = self.config.microsoft.client_id.strip()
        if not client_id:
            raise ConnectorError(
                "Microsoft public-client application ID is missing from the NOVA integrations config."
            )
        cache = msal.SerializableTokenCache()
        app = msal.PublicClientApplication(
            client_id=client_id,
            authority=self.config.microsoft.authority,
            token_cache=cache,
        )
        scopes = self._scopes(services)
        interactive_kwargs: dict[str, Any] = {
            "scopes": scopes,
            "prompt": "select_account",
        }
        window_handle = self._console_window_handle()
        if window_handle:
            interactive_kwargs["parent_window_handle"] = window_handle
        result = app.acquire_token_interactive(**interactive_kwargs)
        if "access_token" not in result:
            self._raise_auth_result(result)
        claims = result.get("id_token_claims") or {}
        provider_subject = str(claims.get("oid") or claims.get("sub") or "")
        username = str(claims.get("preferred_username") or claims.get("email") or "")
        if not provider_subject:
            accounts = app.get_accounts()
            if accounts:
                provider_subject = str(accounts[0].get("home_account_id") or "")
                username = username or str(accounts[0].get("username") or "")
        if not provider_subject:
            raise ConnectorError("Microsoft did not return a stable account identity.")

        account = ConnectedAccount(
            account_id=stable_account_id(Provider.MICROSOFT, provider_subject),
            provider=Provider.MICROSOFT,
            label=label.strip(),
            category=category,
            principal_hint=mask_principal(username),
            enabled_services=tuple(sorted(set(services))),
            content_mode=content_mode,
        )
        self.registry.add(account, cache.serialize())
        return account

    def test_account(self, account: ConnectedAccount) -> str:
        token = self._access_token(account)
        profile = self._graph_get("/me?$select=id,displayName,userPrincipalName", token)
        display = str(profile.get("displayName") or account.label)
        return f"Microsoft account '{account.label}' is connected ({display[:80]})."

    def sync_mail(self, account: ConnectedAccount) -> MailSyncBatch:
        if "mail" not in account.enabled_services:
            return MailSyncBatch()
        token = self._access_token(account)
        resource = "msmail"
        cursor = get_cursor(self.secrets, self.provider.value, account.account_id, resource)
        baseline = cursor is None
        url = cursor or (
            GRAPH_ROOT
            + "/me/mailFolders/inbox/messages/delta"
            + "?$select=id,subject,from,receivedDateTime,isRead,importance,webLink,bodyPreview,parentFolderId,categories"
            + "&$top=100"
        )
        items: list[MailSummary] = []
        removed: list[str] = []
        try:
            while url:
                response = self._graph_get(url, token, absolute=True)
                for raw in response.get("value", []):
                    message_id = str(raw.get("id") or "")
                    if not message_id:
                        continue
                    if "@removed" in raw:
                        removed.append(message_id)
                        continue
                    sender = raw.get("from", {}).get("emailAddress", {}) or {}
                    items.append(
                        MailSummary(
                            provider=self.provider,
                            account_id=account.account_id,
                            message_id=message_id,
                            sender_name=str(sender.get("name") or sender.get("address") or "Unknown sender"),
                            sender_address=str(sender.get("address") or ""),
                            subject=str(raw.get("subject") or "(No subject)"),
                            received_at=_graph_datetime(raw.get("receivedDateTime")),
                            is_read=bool(raw.get("isRead")),
                            importance=str(raw.get("importance") or "normal"),
                            web_link=str(raw.get("webLink") or ""),
                            snippet="",
                        )
                    )
                next_url = response.get("@odata.nextLink")
                if next_url:
                    url = str(next_url)
                    continue
                delta = response.get("@odata.deltaLink")
                if delta:
                    set_cursor(self.secrets, self.provider.value, account.account_id, resource, str(delta))
                url = ""
            return MailSyncBatch(items=items, removed_ids=removed, baseline=baseline)
        except _GraphSyncReset:
            delete_cursor(self.secrets, self.provider.value, account.account_id, resource)
            reset = self.sync_mail(account)
            reset.cursor_reset = True
            return reset

    def sync_calendar(self, account: ConnectedAccount) -> CalendarSyncBatch:
        if "calendar" not in account.enabled_services:
            return CalendarSyncBatch()
        token = self._access_token(account)
        calendars_response = self._graph_get(
            "/me/calendars?$select=id,name,color,canEdit&$top=100", token
        )
        calendars = calendars_response.get("value", [])
        all_items: list[CalendarEvent] = []
        removed: list[tuple[str, str, str]] = []
        any_baseline = False
        any_reset = False
        now = datetime.now(timezone.utc)
        start = (now - timedelta(days=self.config.sync.calendar_past_days)).isoformat().replace("+00:00", "Z")
        end = (now + timedelta(days=self.config.sync.calendar_future_days)).isoformat().replace("+00:00", "Z")

        for calendar in calendars:
            calendar_id = str(calendar.get("id") or "")
            if not calendar_id:
                continue
            calendar_name = str(calendar.get("name") or "Calendar")
            suffix = hashlib.sha256(calendar_id.encode("utf-8")).hexdigest()[:24]
            resource = f"mscal:{suffix}"
            cursor = get_cursor(self.secrets, self.provider.value, account.account_id, resource)
            baseline = cursor is None
            url = cursor or (
                GRAPH_ROOT
                + f"/me/calendars/{requests.utils.quote(calendar_id, safe='')}/calendarView/delta"
                + f"?startDateTime={start}&endDateTime={end}"
                + "&$select=id,subject,start,end,isAllDay,showAs,isCancelled,sensitivity,location,webLink,onlineMeeting,originalStart,type"
                + "&$top=200"
            )
            try:
                while url:
                    response = self._graph_get(
                        url,
                        token,
                        absolute=True,
                        extra_headers={"Prefer": 'outlook.timezone="UTC"'},
                    )
                    for raw in response.get("value", []):
                        event_id = str(raw.get("id") or "")
                        if not event_id:
                            continue
                        if "@removed" in raw:
                            # Graph tombstones commonly contain only the remote event ID.
                            # Remove all locally cached occurrences for that remote ID.
                            removed.append((calendar_id, event_id, ""))
                            continue
                        occurrence_id = str(
                            raw.get("originalStart")
                            or raw.get("start", {}).get("dateTime")
                            or event_id
                        )
                        start_utc = _graph_datetime(raw.get("start", {}).get("dateTime"))
                        end_utc = _graph_datetime(raw.get("end", {}).get("dateTime"))
                        meeting_link = str((raw.get("onlineMeeting") or {}).get("joinUrl") or "")
                        all_items.append(
                            CalendarEvent(
                                provider=self.provider,
                                account_id=account.account_id,
                                calendar_id=calendar_id,
                                event_id=event_id,
                                occurrence_id=occurrence_id,
                                title=str(raw.get("subject") or "(Private or untitled event)"),
                                start_utc=start_utc,
                                end_utc=end_utc,
                                original_timezone=str(raw.get("start", {}).get("timeZone") or "UTC"),
                                all_day=bool(raw.get("isAllDay")),
                                status=str(raw.get("showAs") or "busy"),
                                cancelled=bool(raw.get("isCancelled")),
                                sensitivity=str(raw.get("sensitivity") or "normal"),
                                location=str((raw.get("location") or {}).get("displayName") or ""),
                                web_link=str(raw.get("webLink") or ""),
                                meeting_link=meeting_link,
                                calendar_name=calendar_name,
                            )
                        )
                    next_url = response.get("@odata.nextLink")
                    if next_url:
                        url = str(next_url)
                        continue
                    delta = response.get("@odata.deltaLink")
                    if delta:
                        set_cursor(self.secrets, self.provider.value, account.account_id, resource, str(delta))
                    url = ""
                any_baseline = any_baseline or baseline
            except _GraphSyncReset:
                delete_cursor(self.secrets, self.provider.value, account.account_id, resource)
                any_reset = True
                any_baseline = True
                # A later supervisor pass rebuilds this calendar baseline. Avoid recursive loops.
                continue
        return CalendarSyncBatch(
            items=all_items,
            removed_keys=removed,
            baseline=any_baseline,
            cursor_reset=any_reset,
        )

    def fetch_message_body(self, account: ConnectedAccount, message_id: str) -> str:
        token = self._access_token(account)
        encoded = requests.utils.quote(message_id, safe="")
        response = self._graph_get(
            f"/me/messages/{encoded}?$select=id,body",
            token,
            extra_headers={"Prefer": 'outlook.body-content-type="text"'},
        )
        body = str((response.get("body") or {}).get("content") or "")
        return "\n".join(line.rstrip() for line in body.splitlines()).strip()[:20000]

    def _access_token(self, account: ConnectedAccount) -> str:
        msal = self._msal()
        serialized = self.secrets.get(oauth_key(self.provider.value, account.account_id))
        if not serialized:
            raise ReconnectRequired(f"Microsoft account '{account.label}' needs to be reconnected.")
        cache = msal.SerializableTokenCache()
        cache.deserialize(serialized)
        app = msal.PublicClientApplication(
            client_id=self.config.microsoft.client_id,
            authority=self.config.microsoft.authority,
            token_cache=cache,
        )
        accounts = app.get_accounts()
        if not accounts:
            raise ReconnectRequired(f"Microsoft account '{account.label}' needs to be reconnected.")
        result = app.acquire_token_silent(self._scopes(account.enabled_services), account=accounts[0])
        if not result or "access_token" not in result:
            raise ReconnectRequired(f"Microsoft account '{account.label}' authorization expired.")
        if cache.has_state_changed:
            self.secrets.set(oauth_key(self.provider.value, account.account_id), cache.serialize())
        return str(result["access_token"])

    def _graph_get(
        self,
        path_or_url: str,
        token: str,
        *,
        absolute: bool = False,
        extra_headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        url = path_or_url if absolute or path_or_url.startswith("https://") else GRAPH_ROOT + path_or_url
        headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
        headers.update(extra_headers or {})
        response = requests.get(url, headers=headers, timeout=30)
        if response.status_code == 410:
            raise _GraphSyncReset()
        if response.status_code == 429:
            retry = int(response.headers.get("Retry-After", "60") or 60)
            raise RateLimited("Microsoft Graph rate limit reached.", retry_after=retry)
        if response.status_code in {401}:
            raise ReconnectRequired("Microsoft authorization is no longer valid.")
        if response.status_code in {403}:
            text = _safe_graph_error(response)
            if "consent" in text.lower() or "authorization_requestdenied" in text.lower():
                raise AdminApprovalRequired(
                    "This Microsoft 365 tenant requires administrator approval for NOVA's delegated Mail.Read or Calendars.Read access."
                )
            raise ConnectorError("Microsoft Graph denied the read-only request.")
        if response.status_code >= 500:
            raise ConnectorError("Microsoft Graph is temporarily unavailable.")
        if not response.ok:
            raise ConnectorError(f"Microsoft Graph request failed with HTTP {response.status_code}.")
        return response.json()

    @staticmethod
    def _scopes(services: tuple[str, ...]) -> list[str]:
        scopes = list(BASE_SCOPES)
        if "mail" in services:
            scopes.append(MAIL_SCOPE)
        if "calendar" in services:
            scopes.append(CALENDAR_SCOPE)
        return scopes

    @staticmethod
    def _raise_auth_result(result: dict[str, Any]) -> None:
        error = str(result.get("error") or "")
        description = str(result.get("error_description") or "")
        combined = f"{error} {description}".lower()
        if "admin" in combined or "consent" in combined or "aadsts65001" in combined:
            raise AdminApprovalRequired(
                "Your school or work Microsoft 365 tenant requires administrator approval for NOVA."
            )
        raise ConnectorError("Microsoft sign-in did not complete. No password or token was stored.")

    @staticmethod
    def _msal():
        try:
            import msal
        except ImportError as exc:
            raise ConnectorError("Install the 'msal' package before connecting Microsoft accounts.") from exc
        return msal

    @staticmethod
    def _console_window_handle() -> int | None:
        try:
            import ctypes

            return int(ctypes.windll.kernel32.GetConsoleWindow()) or None
        except Exception:
            return None


class _GraphSyncReset(Exception):
    pass


def _graph_datetime(value: Any) -> str:
    if not value:
        return datetime.now(timezone.utc).isoformat()
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat()


def _safe_graph_error(response: requests.Response) -> str:
    try:
        data = response.json()
        error = data.get("error") or {}
        return f"{error.get('code', '')} {error.get('message', '')}"[:500]
    except Exception:
        return f"HTTP {response.status_code}"
