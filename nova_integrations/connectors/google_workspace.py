"""Google Gmail and Calendar connector using installed-app OAuth."""

from __future__ import annotations

import base64
import hashlib
import html
import json
import re
from datetime import date, datetime, time, timedelta, timezone
from email.utils import parseaddr
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

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
from .base import CalendarSyncBatch, ConnectorError, MailSyncBatch, RateLimited, ReconnectRequired, WorkspaceConnector


OPENID_SCOPES = ("openid", "email", "profile")
GMAIL_READONLY = "https://www.googleapis.com/auth/gmail.readonly"
GMAIL_METADATA = "https://www.googleapis.com/auth/gmail.metadata"
CALENDAR_EVENTS_READONLY = "https://www.googleapis.com/auth/calendar.events.readonly"
CALENDAR_LIST_READONLY = "https://www.googleapis.com/auth/calendar.calendarlist.readonly"


class GoogleWorkspaceConnector(WorkspaceConnector):
    provider = Provider.GOOGLE

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
        try:
            from google_auth_oauthlib.flow import InstalledAppFlow
        except ImportError as exc:
            raise ConnectorError(
                "Google integration packages are missing. Install requirements-email-calendar.txt."
            ) from exc

        client_path = Path(self.config.google.client_config_path).expanduser()
        if not client_path.is_file():
            raise ConnectorError(
                "Google OAuth Desktop client JSON was not found. Put its local path in the NOVA integrations config."
            )
        scopes = list(OPENID_SCOPES)
        if "mail" in services:
            scopes.append(GMAIL_READONLY if content_mode != ContentMode.METADATA_ONLY else GMAIL_METADATA)
        if "calendar" in services:
            scopes.extend((CALENDAR_EVENTS_READONLY, CALENDAR_LIST_READONLY))

        flow = InstalledAppFlow.from_client_secrets_file(str(client_path), scopes=scopes)
        credentials = flow.run_local_server(
            host="127.0.0.1",
            port=0,
            open_browser=True,
            authorization_prompt_message="NOVA is opening Google authorization in your browser.",
            success_message="NOVA Google authorization completed. You may close this browser tab.",
        )
        profile = self._userinfo(credentials.token)
        subject = str(profile.get("sub") or profile.get("email") or "").strip()
        email = str(profile.get("email") or "").strip()
        if not subject:
            raise ConnectorError("Google did not return a stable account identity.")

        account = ConnectedAccount(
            account_id=stable_account_id(Provider.GOOGLE, subject),
            provider=Provider.GOOGLE,
            label=label.strip(),
            category=category,
            principal_hint=mask_principal(email),
            enabled_services=tuple(sorted(set(services))),
            content_mode=content_mode,
        )
        self.registry.add(account, credentials.to_json())
        return account

    def test_account(self, account: ConnectedAccount) -> str:
        credentials = self._credentials(account)
        enabled: list[str] = []
        if "mail" in account.enabled_services:
            gmail = self._build("gmail", "v1", credentials)
            gmail.users().getProfile(userId="me").execute()
            enabled.append("mail")
        if "calendar" in account.enabled_services:
            calendar = self._build("calendar", "v3", credentials)
            calendar.calendarList().list(maxResults=1).execute()
            enabled.append("calendar")
        return f"Google account '{account.label}' is connected for {', '.join(enabled) or 'no services'}."

    def sync_mail(self, account: ConnectedAccount) -> MailSyncBatch:
        if "mail" not in account.enabled_services:
            return MailSyncBatch()
        credentials = self._credentials(account)
        gmail = self._build("gmail", "v1", credentials)
        resource = "gmail"
        history_id = get_cursor(self.secrets, self.provider.value, account.account_id, resource)
        if not history_id:
            items = self._gmail_initial(gmail, account)
            profile = gmail.users().getProfile(userId="me").execute()
            set_cursor(self.secrets, self.provider.value, account.account_id, resource, str(profile["historyId"]))
            return MailSyncBatch(items=items, baseline=True)

        try:
            items: dict[str, MailSummary] = {}
            removed: set[str] = set()
            page_token: str | None = None
            latest_history = history_id
            while True:
                request = gmail.users().history().list(
                    userId="me",
                    startHistoryId=history_id,
                    historyTypes=[
                        "messageAdded",
                        "messageDeleted",
                        "labelAdded",
                        "labelRemoved",
                    ],
                    labelId="INBOX",
                    pageToken=page_token,
                    maxResults=500,
                )
                response = request.execute()
                latest_history = str(response.get("historyId") or latest_history)
                for record in response.get("history", []):
                    for entry in record.get("messagesAdded", []):
                        message_id = str(entry.get("message", {}).get("id") or "")
                        if message_id:
                            item = self._gmail_message(gmail, account, message_id)
                            if item:
                                items[message_id] = item
                    for change_name in ("labelsAdded", "labelsRemoved"):
                        for entry in record.get(change_name, []):
                            message = entry.get("message", {})
                            message_id = str(message.get("id") or "")
                            if not message_id:
                                continue
                            item = self._gmail_message(gmail, account, message_id)
                            if item:
                                items[message_id] = item
                                removed.discard(message_id)
                            else:
                                # This also covers INBOX label removal.
                                removed.add(message_id)
                                items.pop(message_id, None)
                    for entry in record.get("messagesDeleted", []):
                        message_id = str(entry.get("message", {}).get("id") or "")
                        if message_id:
                            removed.add(message_id)
                page_token = response.get("nextPageToken")
                if not page_token:
                    break
            set_cursor(self.secrets, self.provider.value, account.account_id, resource, latest_history)
            return MailSyncBatch(items=list(items.values()), removed_ids=sorted(removed))
        except Exception as exc:
            if self._google_status(exc) == 404:
                delete_cursor(self.secrets, self.provider.value, account.account_id, resource)
                baseline = self.sync_mail(account)
                baseline.cursor_reset = True
                return baseline
            self._raise_google(exc)
            raise

    def sync_calendar(self, account: ConnectedAccount) -> CalendarSyncBatch:
        if "calendar" not in account.enabled_services:
            return CalendarSyncBatch()
        credentials = self._credentials(account)
        service = self._build("calendar", "v3", credentials)
        calendars = self._all_pages(service.calendarList().list, "items", maxResults=250)
        all_items: list[CalendarEvent] = []
        removed: list[tuple[str, str, str]] = []
        any_baseline = False
        any_reset = False
        now = datetime.now(timezone.utc)
        time_min = (now - timedelta(days=self.config.sync.calendar_past_days)).isoformat()
        time_max = (now + timedelta(days=self.config.sync.calendar_future_days)).isoformat()

        for calendar in calendars:
            cal_id = str(calendar.get("id") or "")
            if not cal_id:
                continue
            cal_name = str(calendar.get("summaryOverride") or calendar.get("summary") or "Calendar")
            cal_tz = str(calendar.get("timeZone") or self.config.local_timezone)
            suffix = hashlib.sha256(cal_id.encode("utf-8")).hexdigest()[:24]
            resource = f"gcal:{suffix}"
            token = get_cursor(self.secrets, self.provider.value, account.account_id, resource)
            params: dict[str, Any] = {
                "calendarId": cal_id,
                "singleEvents": True,
                "showDeleted": True,
                "maxResults": 2500,
            }
            baseline = token is None
            if token:
                params["syncToken"] = token
            else:
                params["timeMin"] = time_min
                params["timeMax"] = time_max
            try:
                while True:
                    response = service.events().list(**params).execute()
                    for raw in response.get("items", []):
                        event = self._google_event(account, cal_id, cal_name, cal_tz, raw)
                        if event:
                            all_items.append(event)
                        elif str(raw.get("status")) == "cancelled" and raw.get("id"):
                            removed.append((cal_id, str(raw["id"]), ""))
                    page = response.get("nextPageToken")
                    if page:
                        params["pageToken"] = page
                    else:
                        sync_token = response.get("nextSyncToken")
                        if sync_token:
                            set_cursor(self.secrets, self.provider.value, account.account_id, resource, str(sync_token))
                        break
                any_baseline = any_baseline or baseline
            except Exception as exc:
                if self._google_status(exc) == 410:
                    delete_cursor(self.secrets, self.provider.value, account.account_id, resource)
                    any_reset = True
                    params.pop("syncToken", None)
                    params.pop("pageToken", None)
                    params["timeMin"] = time_min
                    params["timeMax"] = time_max
                    while True:
                        response = service.events().list(**params).execute()
                        for raw in response.get("items", []):
                            event = self._google_event(account, cal_id, cal_name, cal_tz, raw)
                            if event:
                                all_items.append(event)
                            elif str(raw.get("status")) == "cancelled" and raw.get("id"):
                                removed.append((cal_id, str(raw["id"]), ""))
                        page = response.get("nextPageToken")
                        if page:
                            params["pageToken"] = page
                            continue
                        sync_token = response.get("nextSyncToken")
                        if sync_token:
                            set_cursor(
                                self.secrets,
                                self.provider.value,
                                account.account_id,
                                resource,
                                str(sync_token),
                            )
                        break
                    any_baseline = True
                else:
                    self._raise_google(exc)
        return CalendarSyncBatch(
            items=all_items,
            removed_keys=removed,
            baseline=any_baseline,
            cursor_reset=any_reset,
        )

    def fetch_message_body(self, account: ConnectedAccount, message_id: str) -> str:
        credentials = self._credentials(account)
        gmail = self._build("gmail", "v1", credentials)
        try:
            raw = gmail.users().messages().get(userId="me", id=message_id, format="full").execute()
        except Exception as exc:
            self._raise_google(exc)
            raise
        body = self._extract_gmail_body(raw.get("payload", {}))
        return _clean_body(body)

    def _credentials(self, account: ConnectedAccount):
        try:
            from google.auth.transport.requests import Request
            from google.oauth2.credentials import Credentials
        except ImportError as exc:
            raise ConnectorError("Google integration packages are missing.") from exc
        raw = self.secrets.get(oauth_key(self.provider.value, account.account_id))
        if not raw:
            raise ReconnectRequired(f"Google account '{account.label}' needs to be reconnected.")
        credentials = Credentials.from_authorized_user_info(json.loads(raw))
        try:
            if not credentials.valid:
                if credentials.expired and credentials.refresh_token:
                    credentials.refresh(Request())
                    self.secrets.set(
                        oauth_key(self.provider.value, account.account_id), credentials.to_json()
                    )
                else:
                    raise ReconnectRequired(f"Google account '{account.label}' needs to be reconnected.")
        except ReconnectRequired:
            raise
        except Exception as exc:
            raise ReconnectRequired(f"Google account '{account.label}' authorization expired.") from exc
        return credentials

    @staticmethod
    def _build(api: str, version: str, credentials):
        try:
            from googleapiclient.discovery import build
        except ImportError as exc:
            raise ConnectorError("google-api-python-client is not installed.") from exc
        return build(api, version, credentials=credentials, cache_discovery=False)

    @staticmethod
    def _userinfo(access_token: str) -> dict[str, Any]:
        import requests

        response = requests.get(
            "https://openidconnect.googleapis.com/v1/userinfo",
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=20,
        )
        response.raise_for_status()
        return response.json()

    def _gmail_initial(self, gmail, account: ConnectedAccount) -> list[MailSummary]:
        response = gmail.users().messages().list(
            userId="me",
            labelIds=["INBOX"],
            maxResults=self.config.sync.initial_mail_limit,
        ).execute()
        items: list[MailSummary] = []
        for entry in response.get("messages", []):
            item = self._gmail_message(gmail, account, str(entry.get("id") or ""))
            if item:
                items.append(item)
        return items

    def _gmail_message(self, gmail, account: ConnectedAccount, message_id: str) -> MailSummary | None:
        if not message_id:
            return None
        raw = gmail.users().messages().get(
            userId="me",
            id=message_id,
            format="metadata",
            metadataHeaders=["From", "Subject", "Date"],
        ).execute()
        labels = set(raw.get("labelIds", []))
        if "INBOX" not in labels:
            return None
        headers = {
            str(item.get("name", "")).lower(): str(item.get("value", ""))
            for item in raw.get("payload", {}).get("headers", [])
        }
        sender_name, sender_address = parseaddr(headers.get("from", ""))
        internal_ms = int(raw.get("internalDate") or 0)
        received = datetime.fromtimestamp(internal_ms / 1000, timezone.utc).isoformat()
        return MailSummary(
            provider=self.provider,
            account_id=account.account_id,
            message_id=message_id,
            sender_name=sender_name or sender_address or "Unknown sender",
            sender_address=sender_address,
            subject=headers.get("subject") or "(No subject)",
            received_at=received,
            is_read="UNREAD" not in labels,
            importance="high" if "IMPORTANT" in labels else "normal",
            web_link=f"https://mail.google.com/mail/u/0/#inbox/{message_id}",
            snippet="",
        )

    def _google_event(
        self,
        account: ConnectedAccount,
        calendar_id: str,
        calendar_name: str,
        calendar_timezone: str,
        raw: dict[str, Any],
    ) -> CalendarEvent | None:
        if raw.get("status") == "cancelled" and not raw.get("start"):
            return None
        start, start_tz, all_day = _google_datetime(raw.get("start", {}), calendar_timezone)
        end, _, _ = _google_datetime(raw.get("end", {}), calendar_timezone)
        if not start or not end:
            return None
        original = raw.get("originalStartTime") or raw.get("start") or {}
        occurrence_id = str(original.get("dateTime") or original.get("date") or start)
        meeting_link = str(raw.get("hangoutLink") or "")
        if not meeting_link:
            for entry in raw.get("conferenceData", {}).get("entryPoints", []):
                if entry.get("entryPointType") == "video" and entry.get("uri"):
                    meeting_link = str(entry["uri"])
                    break
        return CalendarEvent(
            provider=self.provider,
            account_id=account.account_id,
            calendar_id=calendar_id,
            event_id=str(raw.get("id") or ""),
            occurrence_id=occurrence_id,
            title=str(raw.get("summary") or "(Private or untitled event)"),
            start_utc=start,
            end_utc=end,
            original_timezone=start_tz,
            all_day=all_day,
            status=str(raw.get("transparency") or "opaque").replace("opaque", "busy").replace("transparent", "free"),
            cancelled=raw.get("status") == "cancelled",
            sensitivity=str(raw.get("visibility") or "default"),
            location=str(raw.get("location") or ""),
            web_link=str(raw.get("htmlLink") or ""),
            meeting_link=meeting_link,
            calendar_name=calendar_name,
        )

    @staticmethod
    def _extract_gmail_body(payload: dict[str, Any]) -> str:
        mime = str(payload.get("mimeType") or "")
        data = payload.get("body", {}).get("data")
        if data and mime in {"text/plain", "text/html"}:
            decoded = base64.urlsafe_b64decode(str(data) + "===").decode("utf-8", errors="replace")
            return decoded
        plain_parts: list[str] = []
        html_parts: list[str] = []
        for part in payload.get("parts", []) or []:
            content = GoogleWorkspaceConnector._extract_gmail_body(part)
            if not content:
                continue
            if str(part.get("mimeType")) == "text/plain":
                plain_parts.append(content)
            elif str(part.get("mimeType")) == "text/html":
                html_parts.append(content)
        return "\n".join(plain_parts or html_parts)

    @staticmethod
    def _all_pages(callable_method, item_key: str, **kwargs) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        page_token: str | None = None
        while True:
            response = callable_method(pageToken=page_token, **kwargs).execute()
            items.extend(response.get(item_key, []))
            page_token = response.get("nextPageToken")
            if not page_token:
                return items

    @staticmethod
    def _google_status(exc: Exception) -> int | None:
        response = getattr(exc, "resp", None)
        return getattr(response, "status", None)

    def _raise_google(self, exc: Exception) -> None:
        status = self._google_status(exc)
        if status in {401, 403}:
            raise ReconnectRequired("Google authorization is no longer valid or lacks the requested read-only scope.") from exc
        if status == 429:
            raise RateLimited("Google API rate limit reached.", retry_after=60) from exc
        if status and status >= 500:
            raise ConnectorError("Google service is temporarily unavailable.") from exc
        raise ConnectorError("Google synchronization failed without exposing private response content.") from exc


def _google_datetime(raw: dict[str, Any], fallback_timezone: str) -> tuple[str | None, str, bool]:
    if raw.get("dateTime"):
        value = str(raw["dateTime"])
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            tz_name = str(raw.get("timeZone") or fallback_timezone or "UTC")
            parsed = parsed.replace(tzinfo=ZoneInfo(tz_name))
        return parsed.astimezone(timezone.utc).isoformat(), str(raw.get("timeZone") or parsed.tzinfo), False
    if raw.get("date"):
        tz_name = str(raw.get("timeZone") or fallback_timezone or "UTC")
        parsed_date = date.fromisoformat(str(raw["date"]))
        parsed = datetime.combine(parsed_date, time.min, tzinfo=ZoneInfo(tz_name))
        return parsed.astimezone(timezone.utc).isoformat(), tz_name, True
    return None, fallback_timezone, False


def _clean_body(value: str) -> str:
    value = re.sub(r"<style.*?</style>|<script.*?</script>", " ", value, flags=re.I | re.S)
    value = re.sub(r"<[^>]+>", " ", value)
    value = html.unescape(value)
    value = re.sub(r"[ \t]+", " ", value)
    value = re.sub(r"\n{3,}", "\n\n", value)
    return value.strip()[:20000]
