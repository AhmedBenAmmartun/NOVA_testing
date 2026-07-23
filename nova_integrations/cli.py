"""Local setup CLI for NOVA Google and Microsoft accounts."""

from __future__ import annotations

import argparse
import json
import shutil
from datetime import datetime, timedelta
from pathlib import Path

from .config import load_config, local_data_root
from .connectors import AdminApprovalRequired, ConnectorError
from .models import AccountCategory, ContentMode, Provider
from .runtime import get_runtime


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="nova-integrations")
    parser.add_argument("--config", help="Path to local integrations config.json")
    sub = parser.add_subparsers(dest="command", required=True)

    init = sub.add_parser("init-config", help="Create a local config from the bundled example")
    init.add_argument("--force", action="store_true")

    accounts = sub.add_parser("accounts")
    account_sub = accounts.add_subparsers(dest="account_command", required=True)

    connect = account_sub.add_parser("connect")
    connect.add_argument("provider", choices=["google", "microsoft"])
    connect.add_argument("--label", required=True)
    connect.add_argument("--category", choices=[item.value for item in AccountCategory], default="personal")
    connect.add_argument("--services", nargs="+", choices=["mail", "calendar"], default=["mail", "calendar"])
    connect.add_argument("--content-mode", choices=[item.value for item in ContentMode], default="metadata_only")

    account_sub.add_parser("list")

    test = account_sub.add_parser("test")
    test.add_argument("account")

    reconnect = account_sub.add_parser("reconnect")
    reconnect.add_argument("account")

    disconnect = account_sub.add_parser("disconnect")
    disconnect.add_argument("account")
    disconnect.add_argument("--confirm-label", required=True)

    mode = account_sub.add_parser("set-content-mode")
    mode.add_argument("account")
    mode.add_argument("mode", choices=[item.value for item in ContentMode])

    notification = account_sub.add_parser("notifications")
    notification.add_argument("account")
    notification.add_argument("--enabled", choices=["on", "off", "keep"], default="keep")
    notification.add_argument(
        "--important-only", choices=["on", "off", "keep"], default="keep"
    )

    sync = sub.add_parser("sync")
    sync.add_argument("--account")

    agenda = sub.add_parser("agenda")
    agenda.add_argument("--days", type=int, default=7)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.config:
        import os

        os.environ["NOVA_INTEGRATIONS_CONFIG"] = args.config

    if args.command == "init-config":
        return _init_config(force=args.force)

    runtime = get_runtime()
    try:
        if args.command == "accounts":
            if args.account_command == "list":
                for account in runtime.accounts.list():
                    print(
                        f"{account.label} | id={account.account_id} | {account.provider.value} | "
                        f"{account.category.value} | services={','.join(account.enabled_services)} | "
                        f"mode={account.content_mode.value} | health={account.health.value} | "
                        f"last_sync={account.last_sync_at or 'never'} | principal={account.principal_hint}"
                    )
                return 0

            if args.account_command == "connect":
                provider = Provider(args.provider)
                services = tuple(sorted(set(args.services)))
                _print_scopes(provider, services, ContentMode(args.content_mode))
                account = runtime.connectors[provider].connect(
                    label=args.label,
                    category=AccountCategory(args.category),
                    services=services,
                    content_mode=ContentMode(args.content_mode),
                )
                print(f"Connected {account.label} as {account.account_id}. No password was stored.")
                return 0

            if args.account_command == "test":
                account = runtime.accounts.resolve(args.account)
                print(runtime.connectors[account.provider].test_account(account))
                return 0

            if args.account_command == "reconnect":
                previous = runtime.accounts.resolve(args.account)
                _print_scopes(previous.provider, previous.enabled_services, previous.content_mode)
                account = runtime.connectors[previous.provider].connect(
                    label=previous.label,
                    category=previous.category,
                    services=previous.enabled_services,
                    content_mode=previous.content_mode,
                )
                print(f"Reconnected {account.label}.")
                return 0

            if args.account_command == "disconnect":
                account = runtime.accounts.resolve(args.account)
                if args.confirm_label != account.label:
                    raise ValueError("Disconnect confirmation must exactly match the account label.")
                runtime.accounts.disconnect(account.account_id)
                print(f"Disconnected {account.label} and removed only its local cached metadata.")
                return 0

            if args.account_command == "notifications":
                enabled = None if args.enabled == "keep" else args.enabled == "on"
                important_only = (
                    None
                    if args.important_only == "keep"
                    else args.important_only == "on"
                )
                updated = runtime.accounts.update_notifications(
                    args.account,
                    enabled=enabled,
                    important_only=important_only,
                )
                print(
                    f"{updated.label} notifications: enabled={updated.notifications_enabled}, "
                    f"important_only={updated.important_only}."
                )
                return 0

            if args.account_command == "set-content-mode":
                previous = runtime.accounts.resolve(args.account)
                requested = ContentMode(args.mode)
                updated = runtime.accounts.update_content_mode(args.account, requested)
                print(f"{updated.label} content mode is now {updated.content_mode.value}.")
                if (
                    previous.provider == Provider.GOOGLE
                    and previous.content_mode == ContentMode.METADATA_ONLY
                    and requested != ContentMode.METADATA_ONLY
                    and "mail" in previous.enabled_services
                ):
                    print(
                        "Google was originally authorized with gmail.metadata. "
                        "Run 'accounts reconnect' for this label to grant gmail.readonly before body access."
                    )
                return 0

        if args.command == "sync":
            results = runtime.sync.sync_account(args.account) if args.account else runtime.sync.sync_all()
            for result in results:
                print(
                    f"{result.account_id} {result.resource}: added={result.added} updated={result.updated} "
                    f"deleted={result.deleted} notifications={result.notifications} reset={result.cursor_reset}"
                )
            return 0

        if args.command == "agenda":
            start = datetime.now(runtime.calendar.timezone)
            end = start + timedelta(days=max(1, min(args.days, 60)))
            for account, event in runtime.calendar.date_range(start, end):
                print(runtime.calendar.format_event(account, event))
            return 0
    except AdminApprovalRequired as exc:
        print(f"ADMIN APPROVAL REQUIRED: {exc}")
        return 3
    except (ConnectorError, KeyError, ValueError) as exc:
        print(f"ERROR: {exc}")
        return 2
    return 1


def _init_config(*, force: bool) -> int:
    target = local_data_root() / "config.json"
    if target.exists() and not force:
        print(f"Config already exists: {target}")
        return 0
    bundled = Path(__file__).resolve().parent.parent / "config" / "nova_integrations.example.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    if bundled.exists():
        shutil.copy2(bundled, target)
    else:
        target.write_text(json.dumps({"local_timezone": "America/New_York"}, indent=2), encoding="utf-8")
    print(f"Created local config: {target}")
    return 0


def _print_scopes(provider: Provider, services: tuple[str, ...], mode: ContentMode) -> None:
    print("NOVA will request only these delegated read-only permissions:")
    if provider == Provider.GOOGLE:
        print("- openid, email, profile (identify the selected account)")
        if "mail" in services:
            print(
                "- gmail.metadata" if mode == ContentMode.METADATA_ONLY else "- gmail.readonly"
            )
        if "calendar" in services:
            print("- calendar.events.readonly")
            print("- calendar.calendarlist.readonly")
    else:
        print("- User.Read")
        if "mail" in services:
            print("- Mail.Read")
        if "calendar" in services:
            print("- Calendars.Read")
    print("NOVA never asks for your account password and does not request send/delete/write access.")


if __name__ == "__main__":
    raise SystemExit(main())
