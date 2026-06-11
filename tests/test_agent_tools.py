from __future__ import annotations

from datetime import datetime, timedelta
import os
import tempfile
import threading
import unittest
from unittest.mock import patch

from ews_meeting_mcp.audit import AuditLog
from ews_meeting_mcp.confirmations import ConfirmationLedger
from ews_meeting_mcp import agent_tools
from ews_meeting_mcp.errors import EwsToolError
from ews_meeting_mcp.scheduler import TimeBlock


class FakeClient:
    def __init__(self) -> None:
        self.calls: list[tuple[list[str], int]] = []
        self.free_busy_calls: list[list[str]] = []
        self.free_busy_by_attendee_calls: list[list[str]] = []
        self.created_attendees: list[str] | None = None
        self.created_rooms: list[str] | None = None
        self.fetched_events: list[tuple[str, str]] = []
        self.cancelled_events: list[tuple[str, str, bool]] = []
        self.updated_events: list[tuple[str, str, dict[str, object], list[str], bool, str]] = []
        self.created_meetings = 0
        self.event = {
            "id": "event-1",
            "changekey": "ck-1",
            "uid": "uid-1",
            "subject": "Old sync",
            "start": "2026-06-15T10:00:00+08:00",
            "end": "2026-06-15T10:30:00+08:00",
            "location": "Room A",
            "body": "old body",
            "organizer": {"name": "Organizer", "email": "organizer@example.com"},
            "required_attendees": [{"name": "Ming", "email": "ming.wang@example.com"}],
            "resources": [],
            "is_meeting": True,
            "is_cancelled": False,
            "is_recurring": False,
            "type": "single",
            "is_organizer": True,
        }

    def resolve_attendees(self, attendees: list[str], *, limit: int = 5) -> list[dict[str, object]]:
        self.calls.append((attendees, limit))
        results: list[dict[str, object]] = []
        for attendee in attendees:
            if attendee == "Alex":
                results.append(
                    {
                        "query": "Alex",
                        "status": "ambiguous",
                        "matches": [
                            {"name": "Alex Chen", "email": "alex.chen@example.com"},
                            {"name": "Alex Lin", "email": "alex.lin@example.com"},
                        ],
                    }
                )
            elif attendee == "nobody":
                results.append({"query": "nobody", "status": "not_found", "matches": []})
            elif "@" in attendee:
                results.append(
                    {
                        "query": attendee,
                        "status": "email",
                        "matches": [{"name": attendee, "email": attendee}],
                    }
                )
            else:
                email = "ming.wang@example.com"
                if "MeetingRoom" in attendee:
                    email = attendee
                results.append(
                    {
                        "query": attendee,
                        "status": "resolved",
                        "matches": [{"name": attendee, "email": email}],
                    }
                )
        return results

    def get_free_busy(self, attendees: list[str], start: datetime, end: datetime) -> list[object]:
        self.free_busy_calls.append(attendees)
        return []

    def get_free_busy_by_attendee(
        self,
        attendees: list[str],
        start: datetime,
        end: datetime,
    ) -> dict[str, list[object]]:
        self.free_busy_by_attendee_calls.append(attendees)
        busy_start = start + timedelta(minutes=30)
        busy_end = start + timedelta(minutes=60)
        return {
            "3-1MeetingRoom@example.com": [],
            "3-2MeetingRoom@example.com": [TimeBlock(busy_start, busy_end)],
            "2-11MeetingRoom@example.com": [],
            "2-13MeetingRoom@example.com": [],
            "2-14MeetingRoom@example.com": [],
            "3-4MeetingRoom@example.com": [],
        }

    def create_meeting(self, request: object) -> dict[str, str]:
        self.created_meetings += 1
        self.created_attendees = request.attendees
        self.created_rooms = request.rooms
        return {"id": "event-1", "changekey": "ck-1"}

    def find_calendar_events(
        self,
        start: datetime,
        end: datetime,
        *,
        subject_contains: str | None = None,
        location_contains: str | None = None,
        organizer_email: str | None = None,
        attendee_email: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, object]]:
        return [dict(self.event)]

    def get_calendar_event(self, item_id: str, changekey: str) -> dict[str, object]:
        self.fetched_events.append((item_id, changekey))
        if item_id != self.event["id"]:
            raise EwsToolError("meeting_not_found", "Meeting was not found")
        if changekey != self.event["changekey"]:
            raise EwsToolError("stale_meeting", "Meeting changekey is stale")
        return dict(self.event)

    def verify_meeting(self, item_id: str, changekey: str | None = None) -> dict[str, object]:
        self.fetched_events.append((item_id, changekey or ""))
        return {
            "status": "found",
            "id": item_id,
            "changekey": changekey or "ck-1",
            "uid": "uid-1",
            "subject": "Project sync",
            "attendees": [{"email": "ming.wang@example.com", "response_status": "accept"}],
            "rooms": [{"email": "room@example.com", "response_status": "unknown"}],
            "resources": [{"email": "room@example.com", "response_status": "unknown"}],
        }

    def cancel_meeting(self, item_id: str, changekey: str, *, send_meeting_cancellations: bool) -> dict[str, object]:
        self.cancelled_events.append((item_id, changekey, send_meeting_cancellations))
        return {"id": item_id, "changekey": "ck-2", "cancelled": True}

    def update_meeting(
        self,
        item_id: str,
        changekey: str,
        updates: dict[str, object],
        *,
        update_fields: list[str],
        send_meeting_invitations: bool,
        body_format: str = "html",
    ) -> dict[str, object]:
        self.updated_events.append((item_id, changekey, updates, update_fields, send_meeting_invitations, body_format))
        changed = dict(self.event)
        changed.update(updates)
        changed["changekey"] = "ck-2"
        return changed


class FakeDynamicClient(FakeClient):
    def __init__(self) -> None:
        super().__init__()
        self.discover_room_list: str | None = None

    def discover_rooms(self, *, room_list: str | None = None) -> dict[str, object]:
        self.discover_room_list = room_list
        return {
            "room_lists": [
                {"name": "Taipei Rooms", "email": "taipei-rooms@example.com"},
                {"name": "Tokyo Rooms", "email": "tokyo-rooms@example.com"},
            ],
            "rooms": [
                {
                    "name": "3-1 Meeting Room(12P)",
                    "email": "3-1MeetingRoom@example.com",
                    "capacity": 12,
                    "room_list": "Taipei Rooms",
                    "source": "exchange",
                },
                {
                    "name": "3-1 Meeting Room(12P)",
                    "email": "3-1MeetingRoom@example.com",
                    "capacity": 12,
                    "room_list": "Taipei Rooms",
                    "source": "exchange",
                },
                {
                    "name": "3-2 Meeting Room(6P)",
                    "email": "3-2MeetingRoom@example.com",
                    "capacity": 6,
                    "room_list": "Taipei Rooms",
                    "source": "exchange",
                },
                {
                    "name": "Tokyo Board Room(8P)",
                    "email": "tokyo-board@example.com",
                    "capacity": 8,
                    "room_list": "Tokyo Rooms",
                    "source": "exchange",
                },
            ],
        }

    def get_free_busy_by_attendee(
        self,
        attendees: list[str],
        start: datetime,
        end: datetime,
    ) -> dict[str, list[object]]:
        self.free_busy_by_attendee_calls.append(attendees)
        return {attendee: [] for attendee in attendees}


class FakeEmptyDynamicClient(FakeClient):
    def discover_rooms(self, *, room_list: str | None = None) -> dict[str, object]:
        return {
            "room_lists": [{"name": "Empty Rooms", "email": "empty-rooms@example.com"}],
            "rooms": [],
        }


class AgentToolTests(unittest.TestCase):
    def setUp(self) -> None:
        self._state_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._state_dir.cleanup)
        self._env_patch = patch.dict(
            os.environ,
            {"EWS_MEETING_AGENT_STATE_DIR": self._state_dir.name},
            clear=False,
        )
        self._env_patch.start()
        self.addCleanup(self._env_patch.stop)

    def test_resolve_attendees_delegates_to_client(self) -> None:
        client = FakeClient()

        result = agent_tools.ews_resolve_attendees(
            attendees=["王小明"],
            limit=3,
            client_factory=lambda: client,
        )

        self.assertEqual(client.calls, [(["王小明"], 3)])
        self.assertEqual(result[0]["matches"][0]["email"], "ming.wang@example.com")

    def test_suggest_slots_resolves_names_before_free_busy_lookup(self) -> None:
        client = FakeClient()

        agent_tools.ews_suggest_slots(
            attendees=["王小明"],
            start="2026-06-15T10:00:00+08:00",
            end="2026-06-15T11:00:00+08:00",
            client_factory=lambda: client,
        )

        self.assertEqual(client.calls, [(["王小明"], 5)])
        self.assertEqual(client.free_busy_calls, [["ming.wang@example.com"]])

    def test_suggest_slots_filters_available_rooms_for_each_person_slot(self) -> None:
        client = FakeClient()

        result = agent_tools.ews_suggest_slots(
            attendees=["王小明"],
            rooms=["3-1", "3-2", "2-11", "2-13", "2-14"],
            start="2026-06-15T10:00:00+08:00",
            end="2026-06-15T11:00:00+08:00",
            duration_minutes=30,
            limit=2,
            client_factory=lambda: client,
        )

        self.assertEqual(
            client.free_busy_by_attendee_calls,
            [
                [
                    "3-1MeetingRoom@example.com",
                    "3-2MeetingRoom@example.com",
                    "2-11MeetingRoom@example.com",
                    "2-13MeetingRoom@example.com",
                    "2-14MeetingRoom@example.com",
                ]
            ],
        )
        self.assertEqual(result[0]["available_rooms"][0]["email"], "3-1MeetingRoom@example.com")
        self.assertNotIn(
            "3-2MeetingRoom@example.com",
            [room["email"] for room in result[1]["available_rooms"]],
        )

    def test_suggest_slots_can_use_default_rooms_when_room_is_required(self) -> None:
        client = FakeClient()

        result = agent_tools.ews_suggest_slots(
            attendees=["A", "B", "C", "D", "E", "F", "G"],
            require_room=True,
            start="2026-06-15T10:00:00+08:00",
            end="2026-06-15T11:00:00+08:00",
            duration_minutes=30,
            limit=1,
            client_factory=lambda: client,
        )

        room_emails = [room["email"] for room in result[0]["available_rooms"]]
        self.assertIn("3-1MeetingRoom@example.com", room_emails)
        self.assertNotIn("3-2MeetingRoom@example.com", room_emails)
        self.assertNotIn("3-4MeetingRoom@example.com", room_emails)
        self.assertEqual(result[0]["attendee_count"], 7)

    def test_suggest_slots_without_room_requirement_keeps_existing_behavior(self) -> None:
        client = FakeClient()

        result = agent_tools.ews_suggest_slots(
            attendees=["A", "B"],
            start="2026-06-15T10:00:00+08:00",
            end="2026-06-15T11:00:00+08:00",
            duration_minutes=30,
            limit=1,
            client_factory=lambda: client,
        )

        self.assertNotIn("available_rooms", result[0])
        self.assertEqual(client.free_busy_by_attendee_calls, [])

    def test_suggest_slots_accepts_rfc3339_z_datetimes(self) -> None:
        client = FakeClient()

        result = agent_tools.ews_suggest_slots(
            attendees=["A", "B"],
            start="2026-06-11T10:00:00Z",
            end="2026-06-11T11:00:00Z",
            duration_minutes=30,
            limit=1,
            client_factory=lambda: client,
        )

        self.assertEqual(result[0]["start"], "2026-06-11 10:00:00+00:00")

    def test_suggest_slots_uses_policy_defaults_when_scheduling_args_are_omitted(self) -> None:
        client = FakeClient()
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "policy.json")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write('{"workday_start": "13:00", "workday_end": "14:00", "avoid": []}')

            with patch.dict(os.environ, {"EWS_MEETING_POLICY_FILE": path}, clear=True):
                result = agent_tools.ews_suggest_slots(
                    attendees=["ming.wang@example.com"],
                    start="2026-06-15T10:00:00+08:00",
                    end="2026-06-15T14:00:00+08:00",
                    duration_minutes=30,
                    limit=1,
                    client_factory=lambda: client,
                )

        self.assertEqual(result[0]["start"], "2026-06-15 13:00:00+08:00")

    def test_suggest_slots_explicit_scheduling_args_win_over_policy_defaults(self) -> None:
        client = FakeClient()
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "policy.json")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write('{"workday_start": "13:00", "workday_end": "14:00", "avoid": []}')

            with patch.dict(os.environ, {"EWS_MEETING_POLICY_FILE": path}, clear=True):
                result = agent_tools.ews_suggest_slots(
                    attendees=["ming.wang@example.com"],
                    start="2026-06-15T10:00:00+08:00",
                    end="2026-06-15T14:00:00+08:00",
                    duration_minutes=30,
                    limit=1,
                    workday_start="10:00",
                    workday_end="11:00",
                    avoid=[],
                    client_factory=lambda: client,
                )

        self.assertEqual(result[0]["start"], "2026-06-15 10:00:00+08:00")

    def test_suggest_slots_with_explicit_scheduling_args_does_not_load_policy(self) -> None:
        client = FakeClient()
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "policy.json")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write("{not-json")

            with patch.dict(os.environ, {"EWS_MEETING_POLICY_FILE": path}, clear=True):
                result = agent_tools.ews_suggest_slots(
                    attendees=["ming.wang@example.com"],
                    start="2026-06-15T10:00:00+08:00",
                    end="2026-06-15T14:00:00+08:00",
                    duration_minutes=30,
                    limit=1,
                    workday_start="10:00",
                    workday_end="11:00",
                    avoid=[],
                    client_factory=lambda: client,
                )

        self.assertEqual(result[0]["start"], "2026-06-15 10:00:00+08:00")

    def test_suggest_slots_reports_ambiguous_names_before_free_busy_lookup(self) -> None:
        client = FakeClient()

        with self.assertRaises(EwsToolError) as raised:
            agent_tools.ews_suggest_slots(
                attendees=["Alex"],
                start="2026-06-15T10:00:00+08:00",
                end="2026-06-15T11:00:00+08:00",
                client_factory=lambda: client,
            )

        self.assertEqual(raised.exception.error_code, "ambiguous_attendee")
        self.assertEqual(raised.exception.payload["required_action"], "choose_attendee_candidate")
        self.assertIn("不要要求使用者手動輸入完整 email", raised.exception.payload["user_message"])
        matches = raised.exception.payload["matches"]
        self.assertEqual(matches[0]["email"], "alex.chen@example.com")
        self.assertEqual(matches[1]["email"], "alex.lin@example.com")
        self.assertEqual(client.free_busy_calls, [])

    def test_create_meeting_confirmed_resolves_names_before_creating(self) -> None:
        client = FakeClient()
        preview = agent_tools.ews_create_meeting_preview(
            subject="Sync",
            attendees=["王小明"],
            rooms=["3-1"],
            start="2026-06-15T10:00:00+08:00",
            end="2026-06-15T11:00:00+08:00",
            client_factory=lambda: client,
        )

        result = agent_tools.ews_create_meeting_confirmed(
            subject="Sync",
            attendees=["王小明"],
            rooms=["3-1"],
            start="2026-06-15T10:00:00+08:00",
            end="2026-06-15T11:00:00+08:00",
            confirmation_id=str(preview["confirmation_id"]),
            confirm=True,
            client_factory=lambda: client,
        )

        self.assertEqual(result["preview"]["attendees"], ["ming.wang@example.com"])
        self.assertEqual(result["preview"]["rooms"], ["3-1MeetingRoom@example.com"])
        self.assertEqual(result["preview"]["confirmation_id"], preview["confirmation_id"])
        self.assertEqual(client.created_attendees, ["ming.wang@example.com"])
        self.assertEqual(client.created_rooms, ["3-1MeetingRoom@example.com"])
        self.assertEqual(client.created_meetings, 1)

    def test_create_preview_returns_deterministic_confirmation_id(self) -> None:
        first = agent_tools.ews_create_meeting_preview(
            subject="Sync",
            attendees=["ming.wang@example.com"],
            rooms=["3-1"],
            start="2026-06-15T10:00:00+08:00",
            end="2026-06-15T11:00:00+08:00",
        )
        second = agent_tools.ews_create_meeting_preview(
            subject="Sync",
            attendees=["ming.wang@example.com"],
            rooms=["3-1"],
            start="2026-06-15T10:00:00+08:00",
            end="2026-06-15T11:00:00+08:00",
        )

        self.assertEqual(first["confirmation_id"], second["confirmation_id"])

    def test_create_preview_appends_configured_signature_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "signature.html")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write('<div class="sig">Best Regards,<br>Your Name</div>')

            with patch.dict(os.environ, {"EWS_MEETING_SIGNATURE_HTML_PATH": path}, clear=False):
                preview = agent_tools.ews_create_meeting_preview(
                    subject="Sync",
                    attendees=["ming.wang@example.com"],
                    start="2026-06-15T10:00:00+08:00",
                    end="2026-06-15T11:00:00+08:00",
                    body="Meeting agenda",
                )

        self.assertIn("<p>Meeting agenda</p>", preview["body"])
        self.assertIn("Best Regards", preview["body"])
        self.assertIn("Your Name", preview["body"])
        self.assertEqual(preview["signature"]["configured"], True)
        self.assertEqual(preview["signature"]["included"], True)

    def test_create_preview_can_disable_signature_for_one_request(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "signature.html")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write("<div>Signature</div>")

            with patch.dict(os.environ, {"EWS_MEETING_SIGNATURE_HTML_PATH": path}, clear=False):
                preview = agent_tools.ews_create_meeting_preview(
                    subject="Sync",
                    attendees=["ming.wang@example.com"],
                    start="2026-06-15T10:00:00+08:00",
                    end="2026-06-15T11:00:00+08:00",
                    body="Meeting agenda",
                    include_signature=False,
                )

        self.assertEqual(preview["body"], "<p>Meeting agenda</p>")
        self.assertEqual(preview["signature"]["configured"], True)
        self.assertEqual(preview["signature"]["included"], False)

    def test_create_preview_normalizes_email_whitespace_for_confirmation_id(self) -> None:
        client = FakeClient()
        preview = agent_tools.ews_create_meeting_preview(
            subject="Sync",
            attendees=[" ming.wang@example.com "],
            rooms=["3-1"],
            start="2026-06-15T10:00:00+08:00",
            end="2026-06-15T11:00:00+08:00",
        )

        result = agent_tools.ews_create_meeting_confirmed(
            subject="Sync",
            attendees=["ming.wang@example.com"],
            rooms=["3-1"],
            start="2026-06-15T10:00:00+08:00",
            end="2026-06-15T11:00:00+08:00",
            confirmation_id=str(preview["confirmation_id"]),
            confirm=True,
            client_factory=lambda: client,
        )

        self.assertEqual(result["preview"]["attendees"], ["ming.wang@example.com"])

    def test_confirmed_create_requires_confirmation_id_before_client_setup(self) -> None:
        def fail_client_factory() -> FakeClient:
            raise AssertionError("client should not be created without confirmation_id")

        with self.assertRaises(EwsToolError) as raised:
            agent_tools.ews_create_meeting_confirmed(
                subject="Sync",
                attendees=["ming.wang@example.com"],
                start="2026-06-15T10:00:00+08:00",
                end="2026-06-15T11:00:00+08:00",
                confirm=True,
                client_factory=fail_client_factory,
            )

        self.assertEqual(raised.exception.error_code, "confirmation_mismatch")

    def test_duplicate_create_confirmation_does_not_call_client_again(self) -> None:
        client = FakeClient()
        preview = agent_tools.ews_create_meeting_preview(
            subject="Sync",
            attendees=["ming.wang@example.com"],
            rooms=["3-1"],
            start="2026-06-15T10:00:00+08:00",
            end="2026-06-15T11:00:00+08:00",
        )

        agent_tools.ews_create_meeting_confirmed(
            subject="Sync",
            attendees=["ming.wang@example.com"],
            rooms=["3-1"],
            start="2026-06-15T10:00:00+08:00",
            end="2026-06-15T11:00:00+08:00",
            confirmation_id=str(preview["confirmation_id"]),
            confirm=True,
            client_factory=lambda: client,
        )

        def fail_client_factory() -> FakeClient:
            raise AssertionError("client should not be called for duplicate confirmation")

        with self.assertRaises(EwsToolError) as raised:
            agent_tools.ews_create_meeting_confirmed(
                subject="Sync",
                attendees=["ming.wang@example.com"],
                rooms=["3-1"],
                start="2026-06-15T10:00:00+08:00",
                end="2026-06-15T11:00:00+08:00",
                confirmation_id=str(preview["confirmation_id"]),
                confirm=True,
                client_factory=fail_client_factory,
            )

        self.assertEqual(raised.exception.error_code, "duplicate_confirmation")
        self.assertEqual(raised.exception.payload["prior_result"]["created"]["id"], "event-1")
        self.assertEqual(client.created_meetings, 1)

    def test_create_lifecycle_writes_preview_confirmed_and_duplicate_audit_entries(self) -> None:
        client = FakeClient()
        preview = agent_tools.ews_create_meeting_preview(
            subject="Sync",
            attendees=["ming.wang@example.com"],
            rooms=["3-1"],
            start="2026-06-15T10:00:00+08:00",
            end="2026-06-15T11:00:00+08:00",
        )
        agent_tools.ews_create_meeting_confirmed(
            subject="Sync",
            attendees=["ming.wang@example.com"],
            rooms=["3-1"],
            start="2026-06-15T10:00:00+08:00",
            end="2026-06-15T11:00:00+08:00",
            confirmation_id=str(preview["confirmation_id"]),
            confirm=True,
            client_factory=lambda: client,
        )

        with self.assertRaises(EwsToolError):
            agent_tools.ews_create_meeting_confirmed(
                subject="Sync",
                attendees=["ming.wang@example.com"],
                rooms=["3-1"],
                start="2026-06-15T10:00:00+08:00",
                end="2026-06-15T11:00:00+08:00",
                confirmation_id=str(preview["confirmation_id"]),
                confirm=True,
                client_factory=lambda: client,
            )

        entries = agent_tools.ews_get_audit_log(limit=20, action="create_meeting")
        statuses = [entry["status"] for entry in entries]
        self.assertIn("preview", statuses)
        self.assertIn("confirmed", statuses)
        self.assertIn("duplicate", statuses)
        confirmed = next(entry for entry in entries if entry["status"] == "confirmed")
        self.assertEqual(confirmed["confirmation_id"], preview["confirmation_id"])
        self.assertEqual(confirmed["id"], "event-1")
        self.assertEqual(confirmed["changekey"], "ck-1")
        self.assertEqual(confirmed["subject"], "Sync")
        self.assertEqual(confirmed["attendees"], ["ming.wang@example.com"])
        self.assertEqual(confirmed["resources"], ["3-1MeetingRoom@example.com"])

    def test_in_progress_confirmation_writes_audit_entry(self) -> None:
        class BlockingClient(FakeClient):
            def __init__(self) -> None:
                super().__init__()
                self.entered_create = threading.Event()
                self.allow_create_return = threading.Event()

            def create_meeting(self, request: object) -> dict[str, str]:
                self.entered_create.set()
                self.allow_create_return.wait(timeout=1)
                return super().create_meeting(request)

        client = BlockingClient()
        preview = agent_tools.ews_create_meeting_preview(
            subject="Sync",
            attendees=["ming.wang@example.com"],
            rooms=["3-1"],
            start="2026-06-15T10:00:00+08:00",
            end="2026-06-15T11:00:00+08:00",
        )

        errors: list[BaseException] = []

        def first_call() -> None:
            try:
                agent_tools.ews_create_meeting_confirmed(
                    subject="Sync",
                    attendees=["ming.wang@example.com"],
                    rooms=["3-1"],
                    start="2026-06-15T10:00:00+08:00",
                    end="2026-06-15T11:00:00+08:00",
                    confirmation_id=str(preview["confirmation_id"]),
                    confirm=True,
                    client_factory=lambda: client,
                )
            except BaseException as exc:
                errors.append(exc)

        thread = threading.Thread(target=first_call)
        thread.start()
        self.assertTrue(client.entered_create.wait(timeout=1))

        with self.assertRaises(EwsToolError) as raised:
            agent_tools.ews_create_meeting_confirmed(
                subject="Sync",
                attendees=["ming.wang@example.com"],
                rooms=["3-1"],
                start="2026-06-15T10:00:00+08:00",
                end="2026-06-15T11:00:00+08:00",
                confirmation_id=str(preview["confirmation_id"]),
                confirm=True,
                client_factory=lambda: client,
            )

        client.allow_create_return.set()
        thread.join(timeout=1)
        entries = agent_tools.ews_get_audit_log(limit=20, action="create_meeting", status="in_progress")

        self.assertEqual(raised.exception.error_code, "confirmation_in_progress")
        self.assertEqual(errors, [])
        self.assertEqual(entries[0]["confirmation_id"], preview["confirmation_id"])
        self.assertEqual(entries[0]["error_code"], "confirmation_in_progress")

    def test_in_progress_create_confirmation_does_not_call_client_again(self) -> None:
        class BlockingClient(FakeClient):
            def __init__(self) -> None:
                super().__init__()
                self.entered_create = threading.Event()
                self.allow_create_return = threading.Event()

            def create_meeting(self, request: object) -> dict[str, str]:
                self.entered_create.set()
                self.allow_create_return.wait(timeout=1)
                return super().create_meeting(request)

        client = BlockingClient()
        preview = agent_tools.ews_create_meeting_preview(
            subject="Sync",
            attendees=["ming.wang@example.com"],
            rooms=["3-1"],
            start="2026-06-15T10:00:00+08:00",
            end="2026-06-15T11:00:00+08:00",
        )
        result: dict[str, object] = {}
        errors: list[BaseException] = []

        def first_call() -> None:
            try:
                result.update(
                    agent_tools.ews_create_meeting_confirmed(
                        subject="Sync",
                        attendees=["ming.wang@example.com"],
                        rooms=["3-1"],
                        start="2026-06-15T10:00:00+08:00",
                        end="2026-06-15T11:00:00+08:00",
                        confirmation_id=str(preview["confirmation_id"]),
                        confirm=True,
                        client_factory=lambda: client,
                    )
                )
            except BaseException as exc:
                errors.append(exc)

        thread = threading.Thread(target=first_call)
        thread.start()
        self.assertTrue(client.entered_create.wait(timeout=1))

        with self.assertRaises(EwsToolError) as raised:
            agent_tools.ews_create_meeting_confirmed(
                subject="Sync",
                attendees=["ming.wang@example.com"],
                rooms=["3-1"],
                start="2026-06-15T10:00:00+08:00",
                end="2026-06-15T11:00:00+08:00",
                confirmation_id=str(preview["confirmation_id"]),
                confirm=True,
                client_factory=lambda: client,
            )

        client.allow_create_return.set()
        thread.join(timeout=1)

        self.assertEqual(raised.exception.error_code, "confirmation_in_progress")
        self.assertEqual(errors, [])
        self.assertEqual(result["created"]["id"], "event-1")
        self.assertEqual(client.created_meetings, 1)

    def test_create_returns_success_with_ledger_warning_if_completion_record_fails(self) -> None:
        client = FakeClient()
        preview = agent_tools.ews_create_meeting_preview(
            subject="Sync",
            attendees=["ming.wang@example.com"],
            rooms=["3-1"],
            start="2026-06-15T10:00:00+08:00",
            end="2026-06-15T11:00:00+08:00",
        )

        with patch.object(
            ConfirmationLedger,
            "record_completed",
            side_effect=EwsToolError(
                "confirmation_ledger_unavailable",
                "ledger cannot be written",
                required_action="repair_confirmation_ledger",
            ),
        ):
            result = agent_tools.ews_create_meeting_confirmed(
                subject="Sync",
                attendees=["ming.wang@example.com"],
                rooms=["3-1"],
                start="2026-06-15T10:00:00+08:00",
                end="2026-06-15T11:00:00+08:00",
                confirmation_id=str(preview["confirmation_id"]),
                confirm=True,
                client_factory=lambda: client,
            )

        self.assertEqual(result["created"]["id"], "event-1")
        self.assertEqual(result["confirmation_ledger_warning"]["error_code"], "confirmation_ledger_unavailable")

        with self.assertRaises(EwsToolError) as raised:
            agent_tools.ews_create_meeting_confirmed(
                subject="Sync",
                attendees=["ming.wang@example.com"],
                rooms=["3-1"],
                start="2026-06-15T10:00:00+08:00",
                end="2026-06-15T11:00:00+08:00",
                confirmation_id=str(preview["confirmation_id"]),
                confirm=True,
                client_factory=lambda: client,
            )

        self.assertEqual(raised.exception.error_code, "confirmation_in_progress")
        self.assertEqual(client.created_meetings, 1)

    def test_audit_write_failure_does_not_block_confirmed_create(self) -> None:
        client = FakeClient()
        preview = agent_tools.ews_create_meeting_preview(
            subject="Sync",
            attendees=["ming.wang@example.com"],
            rooms=["3-1"],
            start="2026-06-15T10:00:00+08:00",
            end="2026-06-15T11:00:00+08:00",
        )

        with patch.object(AuditLog, "append", side_effect=OSError("audit directory is read-only")):
            result = agent_tools.ews_create_meeting_confirmed(
                subject="Sync",
                attendees=["ming.wang@example.com"],
                rooms=["3-1"],
                start="2026-06-15T10:00:00+08:00",
                end="2026-06-15T11:00:00+08:00",
                confirmation_id=str(preview["confirmation_id"]),
                confirm=True,
                client_factory=lambda: client,
            )

        self.assertEqual(result["created"]["id"], "event-1")
        self.assertEqual(result["audit_warning"]["error_code"], "audit_log_unavailable")
        self.assertEqual(client.created_meetings, 1)

    def test_preview_with_known_room_alias_does_not_require_client(self) -> None:
        def fail_client_factory() -> FakeClient:
            raise AssertionError("client should not be created for known room aliases")

        result = agent_tools.ews_create_meeting_preview(
            subject="Sync",
            attendees=["ming.wang@example.com"],
            rooms=["2-11"],
            start="2026-06-15T10:00:00+08:00",
            end="2026-06-15T11:00:00+08:00",
            client_factory=fail_client_factory,
        )

        self.assertEqual(result["rooms"], ["2-11MeetingRoom@example.com"])
        self.assertEqual(result["location"], "2-11 Meeting Room")

    def test_known_room_metadata_includes_capacity_when_name_declares_people(self) -> None:
        rooms = agent_tools.default_room_options()

        room_by_email = {room["email"]: room for room in rooms}
        self.assertEqual(room_by_email["3-1MeetingRoom@example.com"]["alias"], "3-1")
        self.assertEqual(room_by_email["3-1MeetingRoom@example.com"]["capacity"], 12)
        self.assertEqual(room_by_email["3-2MeetingRoom@example.com"]["capacity"], 6)

    def test_list_rooms_returns_structured_options_for_user_selection(self) -> None:
        result = agent_tools.ews_list_rooms(attendee_count=7, source="static")

        self.assertEqual(result["source"], "static")
        self.assertEqual(result["selection_hint"], "Ask the user to choose one room value, or choose no specific room.")
        values = [option["value"] for option in result["options"]]
        self.assertIn("3-1", values)
        self.assertNotIn("3-2", values)
        self.assertNotIn("3-4", values)
        first = result["options"][0]
        self.assertIn("label", first)
        self.assertIn("email", first)
        self.assertIn("capacity", first)
        self.assertEqual(first["source"], "static")

    def test_list_rooms_auto_uses_dynamic_exchange_rooms(self) -> None:
        client = FakeDynamicClient()

        result = agent_tools.ews_list_rooms(
            attendee_count=7,
            query="3-",
            room_list="Taipei Rooms",
            source="auto",
            limit=100,
            client_factory=lambda: client,
        )

        self.assertEqual(result["source"], "exchange")
        self.assertEqual(client.discover_room_list, "Taipei Rooms")
        self.assertEqual(result["room_lists"][0]["name"], "Taipei Rooms")
        self.assertEqual(len(result["options"]), 1)
        option = result["options"][0]
        self.assertEqual(option["label"], "3-1 Meeting Room(12P)")
        self.assertEqual(option["value"], "3-1MeetingRoom@example.com")
        self.assertEqual(option["email"], "3-1MeetingRoom@example.com")
        self.assertEqual(option["name"], "3-1 Meeting Room(12P)")
        self.assertEqual(option["capacity"], 12)
        self.assertEqual(option["room_list"], "Taipei Rooms")
        self.assertEqual(option["source"], "exchange")

    def test_list_rooms_source_static_is_credential_free(self) -> None:
        def fail_client_factory() -> FakeClient:
            raise AssertionError("static room listing should not create an EWS client")

        result = agent_tools.ews_list_rooms(source="static", client_factory=fail_client_factory)

        self.assertEqual(result["source"], "static")
        self.assertIn("3-1", [option["value"] for option in result["options"]])

    def test_list_rooms_auto_falls_back_to_static_when_credentials_are_missing(self) -> None:
        def fail_client_factory() -> FakeClient:
            raise EwsToolError(
                "credentials_missing",
                "missing credentials",
                required_action="show_setup_command",
                recoverable=True,
            )

        result = agent_tools.ews_list_rooms(source="auto", attendee_count=7, client_factory=fail_client_factory)

        self.assertEqual(result["source"], "static")
        self.assertIn("3-1", [option["value"] for option in result["options"]])

    def test_list_rooms_source_exchange_requires_credentials(self) -> None:
        def fail_client_factory() -> FakeClient:
            raise EwsToolError(
                "credentials_missing",
                "missing credentials",
                required_action="show_setup_command",
            )

        with self.assertRaises(EwsToolError) as error:
            agent_tools.ews_list_rooms(source="exchange", client_factory=fail_client_factory)

        self.assertEqual(error.exception.error_code, "credentials_missing")

    def test_list_rooms_source_exchange_reports_recoverable_roomlist_failure(self) -> None:
        def fail_client_factory() -> FakeClient:
            raise RuntimeError("roomlist endpoint failed")

        with self.assertRaises(EwsToolError) as error:
            agent_tools.ews_list_rooms(source="exchange", client_factory=fail_client_factory)

        self.assertEqual(error.exception.error_code, "exchange_room_directory_unavailable")
        self.assertTrue(error.exception.payload["recoverable"])

    def test_require_room_prefers_dynamic_rooms_when_available(self) -> None:
        client = FakeDynamicClient()

        result = agent_tools.ews_suggest_slots(
            attendees=["a@example.com", "b@example.com", "c@example.com", "d@example.com", "e@example.com", "f@example.com", "g@example.com"],
            require_room=True,
            start="2026-06-15T10:00:00+08:00",
            end="2026-06-15T11:00:00+08:00",
            duration_minutes=30,
            limit=1,
            client_factory=lambda: client,
        )

        room_emails = [room["email"] for room in result[0]["available_rooms"]]
        self.assertEqual(client.free_busy_by_attendee_calls, [["3-1MeetingRoom@example.com", "tokyo-board@example.com"]])
        self.assertIn("3-1MeetingRoom@example.com", room_emails)
        self.assertIn("tokyo-board@example.com", room_emails)
        self.assertNotIn("3-2MeetingRoom@example.com", room_emails)

    def test_list_rooms_auto_falls_back_to_static_when_exchange_returns_no_options(self) -> None:
        client = FakeEmptyDynamicClient()

        result = agent_tools.ews_list_rooms(
            source="auto",
            attendee_count=7,
            client_factory=lambda: client,
        )

        self.assertEqual(result["source"], "static")
        self.assertIn("3-1", [option["value"] for option in result["options"]])

    def test_require_room_falls_back_to_static_when_dynamic_rooms_do_not_fit_capacity(self) -> None:
        client = FakeDynamicClient()
        attendees = [f"person{i}@example.com" for i in range(13)]
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "policy.json")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(
                    """
                    {
                      "rooms": [
                        {"alias": "5-1", "name": "5-1 Meeting Room(20P)", "email": "5-1MeetingRoom@example.com", "capacity": 20}
                      ]
                    }
                    """
                )

            with patch.dict(os.environ, {"EWS_MEETING_POLICY_FILE": path}, clear=True):
                result = agent_tools.ews_suggest_slots(
                    attendees=attendees,
                    require_room=True,
                    start="2026-06-15T10:00:00+08:00",
                    end="2026-06-15T11:00:00+08:00",
                    duration_minutes=30,
                    limit=1,
                    client_factory=lambda: client,
                )

        free_busy_emails = client.free_busy_by_attendee_calls[0]
        room_emails = [room["email"] for room in result[0]["available_rooms"]]
        self.assertIn("5-1MeetingRoom@example.com", free_busy_emails)
        self.assertNotIn("3-1MeetingRoom@example.com", free_busy_emails)
        self.assertNotIn("3-2MeetingRoom@example.com", free_busy_emails)
        self.assertIn("5-1MeetingRoom@example.com", room_emails)

    def test_setup_check_returns_structured_error_for_invalid_policy_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "policy.json")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write("{not-json")

            with patch.dict(os.environ, {"EWS_MEETING_POLICY_FILE": path}, clear=True):
                result = agent_tools.ews_setup_check()

        self.assertFalse(result["ready"])
        self.assertEqual(result["error_code"], "policy_invalid_json")
        self.assertEqual(result["required_action"], "fix_policy_file")
        self.assertEqual(result["policy_file"], path)

    def test_setup_check_reads_policy_file_from_dotenv_before_reporting_ready(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            policy_path = os.path.join(tmpdir, "policy.json")
            with open(policy_path, "w", encoding="utf-8") as handle:
                handle.write("{not-json")
            with open(os.path.join(tmpdir, ".env"), "w", encoding="utf-8") as handle:
                handle.write(
                    "\n".join(
                        [
                            "EWS_ENDPOINT=https://example.test/EWS/Exchange.asmx",
                            "EWS_EMAIL=ews.user@example.test",
                            "EWS_USERNAME=bk00325",
                            "EWS_PASSWORD=secret-from-dotenv",
                            f"EWS_MEETING_POLICY_FILE={policy_path}",
                        ]
                    )
                )

            old_cwd = os.getcwd()
            os.chdir(tmpdir)
            try:
                with patch.dict(os.environ, {}, clear=True):
                    result = agent_tools.ews_setup_check()
            finally:
                os.chdir(old_cwd)

        self.assertFalse(result["ready"])
        self.assertEqual(result["error_code"], "policy_invalid_json")
        self.assertEqual(result["required_action"], "fix_policy_file")
        self.assertEqual(result["policy_file"], policy_path)
        self.assertNotIn("secret-from-dotenv", str(result))

    def test_list_rooms_uses_policy_rooms_merged_with_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "policy.json")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(
                    """
                    {
                      "rooms": [
                        {"alias": "3-1", "name": "Custom 3-1", "email": "custom-3-1@example.com", "capacity": 16},
                        {"alias": "5-1", "name": "5-1 Meeting Room(20P)", "email": "5-1MeetingRoom@example.com", "capacity": 20}
                      ]
                    }
                    """
                )

            with patch.dict(os.environ, {"EWS_MEETING_POLICY_FILE": path}, clear=True):
                result = agent_tools.ews_list_rooms()

        by_value = {option["value"]: option for option in result["options"]}
        self.assertEqual(by_value["2-11"]["email"], "2-11MeetingRoom@example.com")
        self.assertEqual(by_value["3-1"]["email"], "custom-3-1@example.com")
        self.assertEqual(by_value["5-1"]["capacity"], 20)

    def test_require_room_fallback_uses_policy_rooms_merged_with_defaults(self) -> None:
        client = FakeClient()
        attendees = [f"person{i}@example.com" for i in range(13)]
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "policy.json")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(
                    """
                    {
                      "rooms": [
                        {"alias": "5-1", "name": "5-1 Meeting Room(20P)", "email": "5-1MeetingRoom@example.com", "capacity": 20}
                      ]
                    }
                    """
                )

            with patch.dict(os.environ, {"EWS_MEETING_POLICY_FILE": path}, clear=True):
                result = agent_tools.ews_suggest_slots(
                    attendees=attendees,
                    require_room=True,
                    start="2026-06-15T10:00:00+08:00",
                    end="2026-06-15T11:00:00+08:00",
                    duration_minutes=30,
                    limit=1,
                    client_factory=lambda: client,
                )

        room_emails = [room["email"] for room in result[0]["available_rooms"]]
        self.assertIn("5-1MeetingRoom@example.com", room_emails)
        self.assertNotIn("3-1MeetingRoom@example.com", room_emails)

    def test_find_calendar_events_delegates_filters_to_client(self) -> None:
        client = FakeClient()

        result = agent_tools.ews_find_calendar_events(
            start="2026-06-15T00:00:00+08:00",
            end="2026-06-16T00:00:00+08:00",
            subject_contains="sync",
            location_contains="Room",
            organizer_email="organizer@example.com",
            attendee_email="ming.wang@example.com",
            limit=5,
            client_factory=lambda: client,
        )

        self.assertEqual(result[0]["id"], "event-1")
        self.assertEqual(result[0]["changekey"], "ck-1")
        self.assertEqual(result[0]["uid"], "uid-1")
        self.assertEqual(result[0]["required_attendees"][0]["email"], "ming.wang@example.com")

    def test_verify_meeting_delegates_to_client(self) -> None:
        client = FakeClient()

        result = agent_tools.ews_verify_meeting(
            id="event-1",
            changekey="ck-1",
            client_factory=lambda: client,
        )

        self.assertEqual(client.fetched_events, [("event-1", "ck-1")])
        self.assertEqual(result["status"], "found")
        self.assertEqual(result["rooms"][0]["response_status"], "unknown")

    def test_update_preview_fetches_exact_event_and_does_not_save(self) -> None:
        client = FakeClient()

        preview = agent_tools.ews_update_meeting_preview(
            id="event-1",
            changekey="ck-1",
            subject="New sync",
            start="2026-06-15T11:00:00+08:00",
            end="2026-06-15T11:30:00+08:00",
            client_factory=lambda: client,
        )

        self.assertEqual(client.fetched_events, [("event-1", "ck-1")])
        self.assertEqual(client.updated_events, [])
        self.assertEqual(preview["current_event"]["subject"], "Old sync")
        self.assertEqual(preview["proposed_event"]["subject"], "New sync")
        self.assertEqual(preview["proposed_event"]["start"], "2026-06-15T11:00:00+08:00")
        self.assertIn("confirmation_id", preview)

    def test_confirmed_update_requires_matching_confirmation_id(self) -> None:
        client = FakeClient()

        with self.assertRaises(EwsToolError) as raised:
            agent_tools.ews_update_meeting_confirmed(
                id="event-1",
                changekey="ck-1",
                subject="New sync",
                confirm=True,
                confirmation_id="wrong",
                client_factory=lambda: client,
            )

        self.assertEqual(raised.exception.error_code, "confirmation_mismatch")
        self.assertEqual(client.updated_events, [])

    def test_confirmed_update_requires_confirmation_id(self) -> None:
        client = FakeClient()

        with self.assertRaises(EwsToolError) as raised:
            agent_tools.ews_update_meeting_confirmed(
                id="event-1",
                changekey="ck-1",
                subject="New sync",
                confirm=True,
                client_factory=lambda: client,
            )

        self.assertEqual(raised.exception.error_code, "confirmation_mismatch")
        self.assertEqual(client.fetched_events, [])
        self.assertEqual(client.updated_events, [])

    def test_confirmed_update_requires_confirm_true(self) -> None:
        client = FakeClient()
        preview = agent_tools.ews_update_meeting_preview(
            id="event-1",
            changekey="ck-1",
            subject="New sync",
            client_factory=lambda: client,
        )

        with self.assertRaises(EwsToolError) as raised:
            agent_tools.ews_update_meeting_confirmed(
                id="event-1",
                changekey="ck-1",
                subject="New sync",
                confirm=False,
                confirmation_id=str(preview["confirmation_id"]),
                client_factory=lambda: client,
            )

        self.assertEqual(raised.exception.error_code, "confirmation_mismatch")
        self.assertEqual(client.updated_events, [])

    def test_confirmed_update_requires_matching_send_update_choice(self) -> None:
        client = FakeClient()
        preview = agent_tools.ews_update_meeting_preview(
            id="event-1",
            changekey="ck-1",
            subject="New sync",
            send_meeting_invitations=True,
            client_factory=lambda: client,
        )

        with self.assertRaises(EwsToolError) as raised:
            agent_tools.ews_update_meeting_confirmed(
                id="event-1",
                changekey="ck-1",
                subject="New sync",
                send_meeting_invitations=False,
                confirm=True,
                confirmation_id=str(preview["confirmation_id"]),
                client_factory=lambda: client,
            )

        self.assertEqual(raised.exception.error_code, "confirmation_mismatch")
        self.assertEqual(client.updated_events, [])

    def test_confirmed_update_saves_supported_update_fields(self) -> None:
        client = FakeClient()
        preview = agent_tools.ews_update_meeting_preview(
            id="event-1",
            changekey="ck-1",
            subject="New sync",
            location="Room B",
            body="new body",
            send_meeting_invitations=True,
            client_factory=lambda: client,
        )

        result = agent_tools.ews_update_meeting_confirmed(
            id="event-1",
            changekey="ck-1",
            subject="New sync",
            location="Room B",
            body="new body",
            confirm=True,
            confirmation_id=str(preview["confirmation_id"]),
            client_factory=lambda: client,
        )

        self.assertEqual(
            client.updated_events,
            [
                (
                    "event-1",
                    "ck-1",
                    {"subject": "New sync", "location": "Room B", "body": "new body"},
                    ["subject", "location", "body"],
                    True,
                    "html",
                )
            ],
        )
        self.assertEqual(result["updated"]["changekey"], "ck-2")

    def test_duplicate_update_confirmation_does_not_call_client_again(self) -> None:
        client = FakeClient()
        preview = agent_tools.ews_update_meeting_preview(
            id="event-1",
            changekey="ck-1",
            subject="New sync",
            client_factory=lambda: client,
        )
        agent_tools.ews_update_meeting_confirmed(
            id="event-1",
            changekey="ck-1",
            subject="New sync",
            confirm=True,
            confirmation_id=str(preview["confirmation_id"]),
            client_factory=lambda: client,
        )

        def fail_client_factory() -> FakeClient:
            raise AssertionError("client should not be called for duplicate confirmation")

        with self.assertRaises(EwsToolError) as raised:
            agent_tools.ews_update_meeting_confirmed(
                id="event-1",
                changekey="ck-1",
                subject="New sync",
                confirm=True,
                confirmation_id=str(preview["confirmation_id"]),
                client_factory=fail_client_factory,
            )

        self.assertEqual(raised.exception.error_code, "duplicate_confirmation")
        self.assertEqual(raised.exception.payload["prior_result"]["updated"]["changekey"], "ck-2")
        self.assertEqual(len(client.updated_events), 1)

    def test_confirmed_update_refuses_empty_update_before_saving(self) -> None:
        client = FakeClient()
        preview = agent_tools.ews_update_meeting_preview(
            id="event-1",
            changekey="ck-1",
            client_factory=lambda: client,
        )

        with self.assertRaises(EwsToolError) as raised:
            agent_tools.ews_update_meeting_confirmed(
                id="event-1",
                changekey="ck-1",
                confirm=True,
                confirmation_id=str(preview["confirmation_id"]),
                client_factory=lambda: client,
            )

        self.assertEqual(raised.exception.error_code, "empty_update")
        self.assertEqual(client.updated_events, [])

    def test_cancel_preview_fetches_exact_event_and_does_not_cancel(self) -> None:
        client = FakeClient()

        preview = agent_tools.ews_cancel_meeting_preview(
            id="event-1",
            changekey="ck-1",
            client_factory=lambda: client,
        )

        self.assertEqual(client.fetched_events, [("event-1", "ck-1")])
        self.assertEqual(client.cancelled_events, [])
        self.assertEqual(preview["cancellation_target"]["id"], "event-1")
        self.assertIn("confirmation_id", preview)

    def test_confirmed_cancel_requires_matching_confirmation_id(self) -> None:
        client = FakeClient()

        with self.assertRaises(EwsToolError) as raised:
            agent_tools.ews_cancel_meeting_confirmed(
                id="event-1",
                changekey="ck-1",
                confirm=True,
                confirmation_id="wrong",
                client_factory=lambda: client,
            )

        self.assertEqual(raised.exception.error_code, "confirmation_mismatch")
        self.assertEqual(client.cancelled_events, [])

    def test_confirmed_cancel_requires_confirmation_id(self) -> None:
        client = FakeClient()

        with self.assertRaises(EwsToolError) as raised:
            agent_tools.ews_cancel_meeting_confirmed(
                id="event-1",
                changekey="ck-1",
                confirm=True,
                client_factory=lambda: client,
            )

        self.assertEqual(raised.exception.error_code, "confirmation_mismatch")
        self.assertEqual(client.fetched_events, [])
        self.assertEqual(client.cancelled_events, [])

    def test_confirmed_cancel_requires_confirm_true(self) -> None:
        client = FakeClient()
        preview = agent_tools.ews_cancel_meeting_preview(
            id="event-1",
            changekey="ck-1",
            client_factory=lambda: client,
        )

        with self.assertRaises(EwsToolError) as raised:
            agent_tools.ews_cancel_meeting_confirmed(
                id="event-1",
                changekey="ck-1",
                confirm=False,
                confirmation_id=str(preview["confirmation_id"]),
                client_factory=lambda: client,
            )

        self.assertEqual(raised.exception.error_code, "confirmation_mismatch")
        self.assertEqual(client.cancelled_events, [])

    def test_confirmed_cancel_moves_to_trash(self) -> None:
        client = FakeClient()
        preview = agent_tools.ews_cancel_meeting_preview(
            id="event-1",
            changekey="ck-1",
            client_factory=lambda: client,
        )

        result = agent_tools.ews_cancel_meeting_confirmed(
            id="event-1",
            changekey="ck-1",
            confirm=True,
            confirmation_id=str(preview["confirmation_id"]),
            client_factory=lambda: client,
        )

        self.assertEqual(client.cancelled_events, [("event-1", "ck-1", True)])
        self.assertTrue(result["cancelled"]["cancelled"])

    def test_duplicate_cancel_confirmation_does_not_call_client_again(self) -> None:
        client = FakeClient()
        preview = agent_tools.ews_cancel_meeting_preview(
            id="event-1",
            changekey="ck-1",
            client_factory=lambda: client,
        )
        agent_tools.ews_cancel_meeting_confirmed(
            id="event-1",
            changekey="ck-1",
            confirm=True,
            confirmation_id=str(preview["confirmation_id"]),
            client_factory=lambda: client,
        )

        def fail_client_factory() -> FakeClient:
            raise AssertionError("client should not be called for duplicate confirmation")

        with self.assertRaises(EwsToolError) as raised:
            agent_tools.ews_cancel_meeting_confirmed(
                id="event-1",
                changekey="ck-1",
                confirm=True,
                confirmation_id=str(preview["confirmation_id"]),
                client_factory=fail_client_factory,
            )

        self.assertEqual(raised.exception.error_code, "duplicate_confirmation")
        self.assertTrue(raised.exception.payload["prior_result"]["cancelled"]["cancelled"])
        self.assertEqual(len(client.cancelled_events), 1)

    def test_confirmed_cancel_restricts_recurring_meetings_when_exposed(self) -> None:
        client = FakeClient()
        client.event["is_recurring"] = True
        preview = agent_tools.ews_cancel_meeting_preview(
            id="event-1",
            changekey="ck-1",
            client_factory=lambda: client,
        )

        with self.assertRaises(EwsToolError) as raised:
            agent_tools.ews_cancel_meeting_confirmed(
                id="event-1",
                changekey="ck-1",
                confirm=True,
                confirmation_id=str(preview["confirmation_id"]),
                client_factory=lambda: client,
            )

        self.assertEqual(raised.exception.error_code, "unsupported_recurring_meeting")

    def test_confirmed_cancel_restricts_recurring_occurrence_type_when_exposed(self) -> None:
        client = FakeClient()
        client.event["is_recurring"] = False
        client.event["type"] = "Occurrence"
        preview = agent_tools.ews_cancel_meeting_preview(
            id="event-1",
            changekey="ck-1",
            client_factory=lambda: client,
        )

        with self.assertRaises(EwsToolError) as raised:
            agent_tools.ews_cancel_meeting_confirmed(
                id="event-1",
                changekey="ck-1",
                confirm=True,
                confirmation_id=str(preview["confirmation_id"]),
                client_factory=lambda: client,
            )

        self.assertEqual(raised.exception.error_code, "unsupported_recurring_meeting")
        self.assertEqual(client.cancelled_events, [])

    def test_confirmed_cancel_requires_explicit_organizer_status(self) -> None:
        client = FakeClient()
        del client.event["is_organizer"]
        preview = agent_tools.ews_cancel_meeting_preview(
            id="event-1",
            changekey="ck-1",
            client_factory=lambda: client,
        )

        with self.assertRaises(EwsToolError) as raised:
            agent_tools.ews_cancel_meeting_confirmed(
                id="event-1",
                changekey="ck-1",
                confirm=True,
                confirmation_id=str(preview["confirmation_id"]),
                client_factory=lambda: client,
            )

        self.assertEqual(raised.exception.error_code, "not_meeting_organizer")
        self.assertEqual(client.cancelled_events, [])
        self.assertEqual(client.cancelled_events, [])


if __name__ == "__main__":
    unittest.main()
