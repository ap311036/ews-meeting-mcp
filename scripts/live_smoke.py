from __future__ import annotations

import argparse
from datetime import datetime, timedelta
import json
from pathlib import Path
import sys
from typing import Any
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from ews_meeting_agent import agent_tools  # noqa: E402
from ews_meeting_agent.config import EwsConfig  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="live_smoke.py",
        description="Opt-in live EWS smoke checks for ews-meeting-mcp.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("setup", help="Check local setup without calling EWS.")

    read_only = subparsers.add_parser("read-only", help="Run read-only EWS checks.")
    _add_attendees(read_only)
    read_only.add_argument("--days", type=int, default=2)
    read_only.add_argument("--duration-minutes", type=int, default=30)
    read_only.add_argument("--limit", type=int, default=3)

    create_cancel = subparsers.add_parser(
        "create-cancel",
        help="Create then cancel a live smoke meeting. Requires --confirm-live.",
    )
    _add_attendees(create_cancel)
    create_cancel.add_argument("--confirm-live", action="store_true")
    create_cancel.add_argument("--start", help="Optional ISO start datetime. Defaults to tomorrow 10:00 local time.")
    create_cancel.add_argument("--end", help="Optional ISO end datetime. Defaults to start + 30 minutes.")
    create_cancel.add_argument("--subject", default="")
    create_cancel.add_argument("--body", default="Created by ews-meeting-mcp live smoke and immediately cancelled.")
    create_cancel.add_argument("--location", default="EWS MCP live smoke")

    return parser


def main(argv: list[str] | None = None, *, tools: Any = agent_tools) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "setup":
        setup_status = tools.ews_setup_check()
        _print({"command": "setup", "setup": setup_status})
        return 0 if setup_status.get("ready") else 2

    if args.command == "read-only":
        return _read_only(args, tools=tools)

    if args.command == "create-cancel":
        return _create_cancel(args, tools=tools)

    parser.error(f"Unsupported command: {args.command}")
    return 2


def _read_only(args: argparse.Namespace, *, tools: Any) -> int:
    setup_status = tools.ews_setup_check()
    if not setup_status.get("ready"):
        _print({"command": "read-only", "setup": setup_status})
        return 2

    config = EwsConfig.from_env()
    now = datetime.now(ZoneInfo(config.timezone))
    end = now + timedelta(days=max(1, args.days))
    resolved = tools.ews_resolve_attendees(attendees=args.attendee)
    attendees = _resolved_emails_or_original(args.attendee, resolved)
    free_busy = tools.ews_get_free_busy(
        attendees=attendees,
        start=now.isoformat(),
        end=end.isoformat(),
    )
    suggestions = tools.ews_suggest_slots(
        attendees=attendees,
        start=now.isoformat(),
        end=end.isoformat(),
        duration_minutes=args.duration_minutes,
        limit=args.limit,
    )
    _print(
        {
            "command": "read-only",
            "setup": setup_status,
            "resolved_attendees": resolved,
            "free_busy": free_busy,
            "suggestions": suggestions,
        }
    )
    return 0


def _create_cancel(args: argparse.Namespace, *, tools: Any) -> int:
    if not args.confirm_live:
        _print(
            {
                "command": "create-cancel",
                "error_code": "live_confirmation_required",
                "message": "Refusing live create/cancel smoke without --confirm-live.",
            }
        )
        return 2

    setup_status = tools.ews_setup_check()
    if not setup_status.get("ready"):
        _print({"command": "create-cancel", "setup": setup_status})
        return 2

    start, end = _smoke_window(args)
    subject = args.subject or f"ews-meeting-mcp live smoke {datetime.now().strftime('%Y%m%d-%H%M%S')}"
    preview = tools.ews_create_meeting_preview(
        subject=subject,
        attendees=args.attendee,
        start=start,
        end=end,
        body=args.body,
        location=args.location,
    )
    created = tools.ews_create_meeting_confirmed(
        subject=subject,
        attendees=args.attendee,
        start=start,
        end=end,
        body=args.body,
        location=args.location,
        confirmation_id=str(preview["confirmation_id"]),
        confirm=True,
    )
    created_item = created.get("created", {})
    verify_created = tools.ews_verify_meeting(
        id=str(created_item.get("id", "")),
        changekey=str(created_item.get("changekey", "")) or None,
    )
    cancel_preview = tools.ews_cancel_meeting_preview(
        id=str(created_item.get("id", "")),
        changekey=str(created_item.get("changekey", "")),
    )
    cancelled = tools.ews_cancel_meeting_confirmed(
        id=str(created_item.get("id", "")),
        changekey=str(created_item.get("changekey", "")),
        confirmation_id=str(cancel_preview["confirmation_id"]),
        confirm=True,
    )
    _print(
        {
            "command": "create-cancel",
            "setup": setup_status,
            "preview": preview,
            "created": created,
            "verify_created": verify_created,
            "cancel_preview": cancel_preview,
            "cancelled": cancelled,
        }
    )
    return 0


def _add_attendees(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--attendee", action="append", required=True)


def _resolved_emails_or_original(attendees: list[str], resolved: list[dict[str, Any]]) -> list[str]:
    emails: list[str] = []
    for original, item in zip(attendees, resolved):
        matches = item.get("matches", []) if isinstance(item, dict) else []
        status = item.get("status", "") if isinstance(item, dict) else ""
        if status in {"email", "resolved"} and isinstance(matches, list) and len(matches) == 1:
            email = str(matches[0].get("email", "")).strip()
            if email:
                emails.append(email)
                continue
        emails.append(original)
    return emails


def _smoke_window(args: argparse.Namespace) -> tuple[str, str]:
    if args.start:
        start = datetime.fromisoformat(args.start)
    else:
        config = EwsConfig.from_env()
        now = datetime.now(ZoneInfo(config.timezone))
        start = (now + timedelta(days=1)).replace(hour=10, minute=0, second=0, microsecond=0)
    if args.end:
        end = datetime.fromisoformat(args.end)
    else:
        end = start + timedelta(minutes=30)
    return start.isoformat(), end.isoformat()


def _print(value: object) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    raise SystemExit(main())
