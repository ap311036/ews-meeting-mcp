from __future__ import annotations

import argparse
from datetime import datetime, timedelta
import json
import warnings

from .config import EwsConfig
from .ews_client import EwsClient, default_window
from .meeting import MeetingRequest, build_meeting_preview
from .scheduler import parse_time_range, suggest_slots


def main() -> None:
    _suppress_known_warnings()
    parser = argparse.ArgumentParser(prog="ews-meeting-mcp")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("env")
    subparsers.add_parser("probe")

    calendar = subparsers.add_parser("calendar")
    calendar.add_argument("--days", type=int, default=7)

    freebusy = subparsers.add_parser("freebusy")
    _add_attendees(freebusy)
    _add_window(freebusy)

    suggest = subparsers.add_parser("suggest")
    _add_attendees(suggest)
    _add_window(suggest)
    suggest.add_argument("--duration-minutes", type=int, default=30)
    suggest.add_argument("--limit", type=int, default=5)
    suggest.add_argument("--workday-start", default="10:00")
    suggest.add_argument("--workday-end", default="18:00")
    suggest.add_argument(
        "--avoid",
        action="append",
        default=["12:00-14:00"],
        help="Daily time range to avoid, in HH:MM-HH:MM format. Can be repeated.",
    )

    create = subparsers.add_parser("create-meeting")
    _add_attendees(create)
    _add_window(create)
    create.add_argument("--subject", required=True)
    create.add_argument("--body", default="")
    create.add_argument("--location", default="")
    create.add_argument(
        "--confirm",
        action="store_true",
        help="Actually create the meeting and send invitations. Without this flag, only prints a preview.",
    )

    args = parser.parse_args()
    config = EwsConfig.from_env()

    if args.command == "env":
        _print(config.redacted())
        return

    client = EwsClient(config)

    if args.command == "probe":
        _print(client.probe())
        return

    if args.command == "calendar":
        start, end = default_window(args.days, config.timezone)
        _print(client.list_calendar(start, end))
        return

    if args.command == "freebusy":
        start, end = _parse_window(args)
        _print([block.__dict__ for block in client.get_free_busy(args.attendee, start, end)])
        return

    if args.command == "suggest":
        start, end = _parse_window(args)
        busy = client.get_free_busy(args.attendee, start, end)
        slots = suggest_slots(
            busy,
            start,
            end,
            timedelta(minutes=args.duration_minutes),
            workday_start=_parse_time(args.workday_start),
            workday_end=_parse_time(args.workday_end),
            excluded_windows=[parse_time_range(value) for value in args.avoid],
            limit=args.limit,
        )
        _print([slot.__dict__ for slot in slots])
        return

    if args.command == "create-meeting":
        start, end = _parse_window(args)
        request = MeetingRequest(
            subject=args.subject,
            attendees=args.attendee,
            start=start,
            end=end,
            body=args.body,
            location=args.location,
        )
        preview = build_meeting_preview(request, confirmed=args.confirm)
        if not args.confirm:
            _print(preview)
            return

        result = client.create_meeting(request)
        _print({"preview": preview, "created": result})


def _add_attendees(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--attendee", action="append", required=True)


def _add_window(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--start", required=True, help="ISO datetime, e.g. 2026-06-10T09:00:00+08:00")
    parser.add_argument("--end", required=True, help="ISO datetime, e.g. 2026-06-10T18:00:00+08:00")


def _parse_window(args: argparse.Namespace) -> tuple[datetime, datetime]:
    return datetime.fromisoformat(args.start), datetime.fromisoformat(args.end)


def _parse_time(value: str) -> object:
    return datetime.strptime(value, "%H:%M").time()


def _print(value: object) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, default=str))


def _suppress_known_warnings() -> None:
    warnings.filterwarnings(
        "ignore",
        message="urllib3 v2 only supports OpenSSL.*",
        category=Warning,
    )
    warnings.filterwarnings(
        "ignore",
        message="Cannot convert value '' on field '_start_timezone'.*",
        category=UserWarning,
    )


if __name__ == "__main__":
    main()
