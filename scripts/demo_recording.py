#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import time
from typing import Any


def main() -> None:
    parser = argparse.ArgumentParser(description="Print a safe fake EWS Meeting MCP recording demo.")
    parser.add_argument("--fast", action="store_true", help="Run with shorter pauses for rehearsal.")
    args = parser.parse_args()
    delay = 0.15 if args.fast else 0.75

    scene(
        "User request",
        'Find a 30-minute slot for Alice and Bob this week, with a six-person room. '
        "Preview before sending any invitation.",
        delay,
    )
    tool(
        "ews_setup_check",
        {},
        {
            "ready": True,
            "credential_source": "macOS Keychain",
            "endpoint": "https://mail.company.com/EWS/Exchange.asmx",
            "password_returned": False,
        },
        delay,
    )
    tool(
        "ews_resolve_attendees",
        {"attendees": ["Alice", "Bob"]},
        [
            {"input": "Alice", "selected": "alice@example.com"},
            {"input": "Bob", "selected": "bob@example.com"},
        ],
        delay,
    )
    tool(
        "ews_list_rooms",
        {"attendee_count": 2, "source": "auto"},
        {
            "source": "exchange",
            "options": [
                {"value": "3-1MeetingRoom@example.com", "name": "3-1 Meeting Room(12P)", "capacity": 12},
                {"value": "3-2MeetingRoom@example.com", "name": "3-2 Meeting Room(6P)", "capacity": 6},
            ],
        },
        delay,
    )
    tool(
        "ews_suggest_slots",
        {
            "attendees": ["alice@example.com", "bob@example.com"],
            "require_room": True,
            "duration_minutes": 30,
        },
        [
            {
                "start": "2026-06-15T11:00:00+08:00",
                "end": "2026-06-15T11:30:00+08:00",
                "available_rooms": [{"name": "3-2 Meeting Room(6P)", "email": "3-2MeetingRoom@example.com"}],
            },
            {
                "start": "2026-06-16T15:30:00+08:00",
                "end": "2026-06-16T16:00:00+08:00",
                "available_rooms": [{"name": "3-1 Meeting Room(12P)", "email": "3-1MeetingRoom@example.com"}],
            },
        ],
        delay,
    )
    tool(
        "ews_create_meeting_preview",
        {
            "subject": "Project sync",
            "attendees": ["alice@example.com", "bob@example.com"],
            "rooms": ["3-2MeetingRoom@example.com"],
            "start": "2026-06-15T11:00:00+08:00",
            "end": "2026-06-15T11:30:00+08:00",
        },
        {
            "action": "dry_run",
            "will_send_invites": False,
            "subject": "Project sync",
            "attendees": ["alice@example.com", "bob@example.com"],
            "rooms": ["3-2MeetingRoom@example.com"],
            "confirmation_id": "demo-8f0c1c4d",
        },
        delay,
    )
    scene("Human confirmation", "Confirm: send this exact invitation.", delay)
    tool(
        "ews_create_meeting_confirmed",
        {"confirm": True, "confirmation_id": "demo-8f0c1c4d"},
        {
            "created": {"id": "AAMk-demo-event", "changekey": "CQAAABYAA-demo"},
            "duplicate_guard": "recorded",
        },
        delay,
    )
    tool(
        "ews_verify_meeting",
        {"id": "AAMk-demo-event", "changekey": "CQAAABYAA-demo"},
        {
            "exists": True,
            "organizer_item": "verified",
            "room_response_status": "pending",
        },
        delay,
    )
    scene(
        "Result",
        "Credentials stayed local. The invite was created only after confirmation. "
        "The action is now verifiable and audit-friendly.",
        delay,
    )


def scene(title: str, text: str, delay: float) -> None:
    print()
    print(f"### {title}")
    print(text)
    pause(delay)


def tool(name: str, arguments: Any, result: Any, delay: float) -> None:
    print()
    print(f"$ mcp.call {name}")
    pause(delay * 0.55)
    print("arguments:")
    print_json(arguments)
    pause(delay * 0.55)
    print("result:")
    print_json(result)
    pause(delay)


def print_json(value: Any) -> None:
    print(json.dumps(value, indent=2, ensure_ascii=False))


def pause(seconds: float) -> None:
    sys.stdout.flush()
    time.sleep(seconds)


if __name__ == "__main__":
    main()
