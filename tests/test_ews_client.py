from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from types import SimpleNamespace
import unittest

from ews_meeting_agent.config import EwsConfig
from ews_meeting_agent.ews_client import EwsClient
from ews_meeting_agent.errors import EwsToolError


@dataclass
class FakeMailbox:
    name: str
    email_address: str


@dataclass
class FakeNestedMailbox:
    name: str
    mailbox: FakeMailbox


class FakeConfig:
    def __init__(self) -> None:
        self.version = None


class FakeProtocol:
    def __init__(self) -> None:
        self.config = FakeConfig()
        self.calls: list[tuple[list[str], bool]] = []
        self.roomlist_calls = 0
        self.room_calls: list[str] = []
        self.version_accesses = 0

    @property
    def version(self) -> object:
        self.version_accesses += 1
        self.config.version = object()
        return self.config.version

    def resolve_names(self, names: list[str], *, return_full_contact_data: bool) -> list[FakeMailbox]:
        if self.config.version is None:
            raise AttributeError("'NoneType' object has no attribute 'api_version'")
        self.calls.append((names, return_full_contact_data))
        if names == ["王小明"]:
            return [FakeMailbox(name="王小明", email_address="ming.wang@example.com")]
        if names == ["Alex"]:
            return [
                FakeMailbox(name="Alex Chen", email_address="alex.chen@example.com"),
                FakeMailbox(name="Alex Lin", email_address="alex.lin@example.com"),
            ]
        return []

    def get_roomlists(self) -> list[FakeMailbox]:
        if self.config.version is None:
            raise AttributeError("'NoneType' object has no attribute 'api_version'")
        self.roomlist_calls += 1
        return [
            FakeMailbox(name="Taipei Rooms", email_address="taipei-rooms@example.com"),
            FakeMailbox(name="Tokyo Rooms", email_address="tokyo-rooms@example.com"),
        ]

    def get_rooms(self, room_list: str) -> list[FakeMailbox]:
        self.room_calls.append(room_list)
        if room_list == "taipei-rooms@example.com":
            return [
                FakeMailbox(name="3-1 Meeting Room(12P)", email_address="3-1MeetingRoom@example.com"),
                FakeMailbox(name="3-1 Meeting Room(12P)", email_address="3-1MeetingRoom@example.com"),
                FakeNestedMailbox(
                    name="3-2 Meeting Room(6 p)",
                    mailbox=FakeMailbox(name="3-2 mailbox", email_address="3-2MeetingRoom@example.com"),
                ),
            ]
        return [FakeMailbox(name="Tokyo Board Room(8P)", email_address="tokyo-board@example.com")]


class FakeAccount:
    def __init__(self) -> None:
        self.protocol = FakeProtocol()


class FakeCalendarView:
    def __init__(self, items: list[object]) -> None:
        self.items = items
        self.only_fields: tuple[str, ...] = ()
        self.order_fields: tuple[str, ...] = ()

    def only(self, *fields: str) -> "FakeCalendarView":
        self.only_fields = fields
        return self

    def order_by(self, *fields: str) -> "FakeCalendarView":
        self.order_fields = fields
        return self

    def __getitem__(self, value: object) -> list[object]:
        return self.items[value]


class FakeCalendar:
    def __init__(self, items: list[object]) -> None:
        self.items = items
        self.view_calls: list[tuple[object, object]] = []
        self.get_calls: list[tuple[str, str]] = []

    def view(self, *, start: object, end: object) -> FakeCalendarView:
        self.view_calls.append((start, end))
        return FakeCalendarView(self.items)

    def get(self, *, id: str, changekey: str | None = None) -> object:
        self.get_calls.append((id, changekey))
        for item in self.items:
            if getattr(item, "id", "") == id and (changekey is None or getattr(item, "changekey", "") == changekey):
                return item
        if any(getattr(item, "id", "") == id for item in self.items):
            raise RuntimeError("stale object")
        raise RuntimeError("not found")


class FakeFailingCalendar:
    def get(self, *, id: str, changekey: str) -> object:
        raise RuntimeError("server unavailable")


class FakeFailingCalendarAccount(FakeAccount):
    def __init__(self) -> None:
        super().__init__()
        self.calendar = FakeFailingCalendar()


class FakeCalendarAccount(FakeAccount):
    def __init__(self, items: list[object]) -> None:
        super().__init__()
        self.calendar = FakeCalendar(items)


class FakeMeetingItem:
    def __init__(self) -> None:
        self.id = "event-1"
        self.changekey = "ck-1"
        self.uid = "uid-1"
        self.subject = "Project sync"
        self.start = "2026-06-15T10:00:00+08:00"
        self.end = "2026-06-15T10:30:00+08:00"
        self.location = "3-1 Meeting Room"
        self.body = "old body"
        self.organizer = FakeMailbox(name="Organizer", email_address="organizer@example.com")
        self.required_attendees = [FakeMailbox(name="Ming", email_address="ming.wang@example.com")]
        self.resources = [FakeMailbox(name="Room", email_address="room@example.com")]
        self.is_meeting = True
        self.is_cancelled = False
        self.recurrence = None
        self.type = "Single"
        self.is_organizer = True
        self.save_calls: list[dict[str, object]] = []
        self.trash_calls: list[dict[str, object]] = []

    def save(self, **kwargs: object) -> None:
        self.save_calls.append(kwargs)
        self.changekey = "ck-2"

    def move_to_trash(self, **kwargs: object) -> None:
        self.trash_calls.append(kwargs)
        self.id = ""
        self.changekey = "ck-2"


class FakeFailingVersionProtocol:
    config = FakeConfig()

    @property
    def version(self) -> object:
        raise RuntimeError("version lookup failed")

    def get_roomlists(self) -> list[FakeMailbox]:
        raise AssertionError("get_roomlists should not be reached")


class FakeFailingVersionAccount:
    def __init__(self) -> None:
        self.protocol = FakeFailingVersionProtocol()


class EwsClientResolveTests(unittest.TestCase):
    def test_resolve_attendees_returns_statuses_and_matches(self) -> None:
        client = EwsClient(
            EwsConfig(
                endpoint="https://ews.example.com/EWS/Exchange.asmx",
                email="organizer@example.com",
                username="organizer",
                password="secret",
            )
        )
        account = FakeAccount()
        client._account = account

        result = client.resolve_attendees(
            ["王小明", "Alex", "nobody", "direct.person@example.com"],
            limit=1,
        )

        self.assertEqual(
            [(item["query"], item["status"]) for item in result],
            [
                ("王小明", "resolved"),
                ("Alex", "ambiguous"),
                ("nobody", "not_found"),
                ("direct.person@example.com", "email"),
            ],
        )
        self.assertEqual(result[0]["matches"][0]["email"], "ming.wang@example.com")
        self.assertEqual(len(result[1]["matches"]), 1)
        self.assertEqual(result[3]["matches"][0]["email"], "direct.person@example.com")
        self.assertEqual(
            account.protocol.calls,
            [
                (["王小明"], True),
                (["Alex"], True),
                (["nobody"], True),
            ],
        )
        self.assertEqual(account.protocol.version_accesses, 1)

    def test_discover_rooms_uses_exchange_roomlists_and_rooms(self) -> None:
        client = EwsClient(
            EwsConfig(
                endpoint="https://ews.example.com/EWS/Exchange.asmx",
                email="organizer@example.com",
                username="organizer",
                password="secret",
            )
        )
        account = FakeAccount()
        client._account = account

        result = client.discover_rooms(room_list="Taipei")

        self.assertEqual(account.protocol.roomlist_calls, 1)
        self.assertEqual(account.protocol.room_calls, ["taipei-rooms@example.com"])
        self.assertEqual(
            result["room_lists"],
            [
                {"name": "Taipei Rooms", "email": "taipei-rooms@example.com"},
                {"name": "Tokyo Rooms", "email": "tokyo-rooms@example.com"},
            ],
        )
        self.assertEqual(len(result["rooms"]), 2)
        self.assertEqual(result["rooms"][0]["email"], "3-1MeetingRoom@example.com")
        self.assertEqual(result["rooms"][0]["capacity"], 12)
        self.assertEqual(result["rooms"][0]["room_list"], "Taipei Rooms")
        self.assertEqual(result["rooms"][0]["source"], "exchange")
        self.assertEqual(result["rooms"][1]["email"], "3-2MeetingRoom@example.com")
        self.assertEqual(result["rooms"][1]["capacity"], 6)

    def test_discover_rooms_accepts_string_roomlists(self) -> None:
        client = EwsClient(
            EwsConfig(
                endpoint="https://ews.example.com/EWS/Exchange.asmx",
                email="organizer@example.com",
                username="organizer",
                password="secret",
            )
        )
        account = FakeAccount()
        account.protocol.get_roomlists = lambda: ["taipei-rooms@example.com"]
        client._account = account

        result = client.discover_rooms()

        self.assertEqual(account.protocol.room_calls, ["taipei-rooms@example.com"])
        self.assertEqual(result["room_lists"], [{"name": "taipei-rooms@example.com", "email": "taipei-rooms@example.com"}])

    def test_discover_rooms_maps_version_initialization_failure(self) -> None:
        client = EwsClient(
            EwsConfig(
                endpoint="https://ews.example.com/EWS/Exchange.asmx",
                email="organizer@example.com",
                username="organizer",
                password="secret",
            )
        )
        client._account = FakeFailingVersionAccount()

        with self.assertRaisesRegex(RuntimeError, "Exchange room lists are unavailable"):
            client.discover_rooms()

    def test_find_calendar_events_serializes_stable_metadata_and_filters(self) -> None:
        item = FakeMeetingItem()
        client = EwsClient(
            EwsConfig(
                endpoint="https://ews.example.com/EWS/Exchange.asmx",
                email="organizer@example.com",
                username="organizer",
                password="secret",
            )
        )
        account = FakeCalendarAccount([item])
        client._account = account
        client._to_ews_datetime = lambda value: value

        result = client.find_calendar_events(
            datetime.fromisoformat("2026-06-15T00:00:00+08:00"),
            datetime.fromisoformat("2026-06-16T00:00:00+08:00"),
            subject_contains="project",
            location_contains="3-1",
            organizer_email="organizer@example.com",
            attendee_email="ming.wang@example.com",
            limit=10,
        )

        self.assertEqual(len(result), 1)
        self.assertEqual(account.calendar.view_calls[0][0].isoformat(), "2026-06-15T00:00:00+08:00")
        self.assertEqual(result[0]["id"], "event-1")
        self.assertEqual(result[0]["changekey"], "ck-1")
        self.assertEqual(result[0]["uid"], "uid-1")
        self.assertEqual(result[0]["organizer"]["email"], "organizer@example.com")
        self.assertEqual(result[0]["required_attendees"][0]["email"], "ming.wang@example.com")
        self.assertEqual(result[0]["resources"][0]["email"], "room@example.com")
        self.assertTrue(result[0]["is_meeting"])
        self.assertFalse(result[0]["is_recurring"])

    def test_find_calendar_events_applies_limit_after_filters(self) -> None:
        non_match = FakeMeetingItem()
        non_match.id = "event-0"
        non_match.changekey = "ck-0"
        non_match.subject = "Other"
        match = FakeMeetingItem()
        match.id = "event-1"
        match.changekey = "ck-1"
        match.subject = "Project sync"
        client = EwsClient(
            EwsConfig(
                endpoint="https://ews.example.com/EWS/Exchange.asmx",
                email="organizer@example.com",
                username="organizer",
                password="secret",
            )
        )
        account = FakeCalendarAccount([non_match, match])
        client._account = account
        client._to_ews_datetime = lambda value: value

        result = client.find_calendar_events(
            datetime.fromisoformat("2026-06-15T00:00:00+08:00"),
            datetime.fromisoformat("2026-06-16T00:00:00+08:00"),
            subject_contains="project",
            limit=1,
        )

        self.assertEqual([event["id"] for event in result], ["event-1"])

    def test_get_calendar_event_uses_exact_id_and_changekey(self) -> None:
        item = FakeMeetingItem()
        client = EwsClient(
            EwsConfig(
                endpoint="https://ews.example.com/EWS/Exchange.asmx",
                email="organizer@example.com",
                username="organizer",
                password="secret",
            )
        )
        account = FakeCalendarAccount([item])
        client._account = account

        result = client.get_calendar_event("event-1", "ck-1")

        self.assertEqual(account.calendar.get_calls, [("event-1", "ck-1")])
        self.assertEqual(result["id"], "event-1")

    def test_get_calendar_event_reports_stale_or_missing_items(self) -> None:
        item = FakeMeetingItem()
        client = EwsClient(
            EwsConfig(
                endpoint="https://ews.example.com/EWS/Exchange.asmx",
                email="organizer@example.com",
                username="organizer",
                password="secret",
            )
        )
        client._account = FakeCalendarAccount([item])

        with self.assertRaises(EwsToolError) as stale:
            client.get_calendar_event("event-1", "old-ck")
        with self.assertRaises(EwsToolError) as missing:
            client.get_calendar_event("event-2", "ck-1")

        self.assertEqual(stale.exception.error_code, "stale_meeting")
        self.assertEqual(missing.exception.error_code, "meeting_not_found")

    def test_get_calendar_event_reports_unknown_lookup_failures_separately(self) -> None:
        client = EwsClient(
            EwsConfig(
                endpoint="https://ews.example.com/EWS/Exchange.asmx",
                email="organizer@example.com",
                username="organizer",
                password="secret",
            )
        )
        client._account = FakeFailingCalendarAccount()

        with self.assertRaises(EwsToolError) as raised:
            client.get_calendar_event("event-1", "ck-1")

        self.assertEqual(raised.exception.error_code, "ews_meeting_lookup_failed")

    def test_verify_meeting_returns_attendees_rooms_and_response_status(self) -> None:
        item = FakeMeetingItem()
        item.required_attendees = [
            SimpleNamespace(
                mailbox=FakeMailbox(name="Ming", email_address="ming.wang@example.com"),
                response_type="Accept",
                last_response_time="2026-06-14T09:00:00+08:00",
            )
        ]
        item.resources = [
            SimpleNamespace(
                mailbox=FakeMailbox(name="3-1 Meeting Room(12P)", email_address="room@example.com"),
                response_type="Tentative",
            ),
            FakeMailbox(name="3-2 Meeting Room(6P)", email_address="room2@example.com"),
        ]
        client = EwsClient(
            EwsConfig(
                endpoint="https://ews.example.com/EWS/Exchange.asmx",
                email="organizer@example.com",
                username="organizer",
                password="secret",
            )
        )
        account = FakeCalendarAccount([item])
        client._account = account

        result = client.verify_meeting("event-1")

        self.assertEqual(account.calendar.get_calls, [("event-1", None)])
        self.assertEqual(result["status"], "found")
        self.assertEqual(result["id"], "event-1")
        self.assertEqual(result["changekey"], "ck-1")
        self.assertEqual(result["uid"], "uid-1")
        self.assertTrue(result["organizer_item"]["is_meeting"])
        self.assertEqual(result["attendees"][0]["email"], "ming.wang@example.com")
        self.assertEqual(result["attendees"][0]["response_status"], "accept")
        self.assertEqual(result["attendees"][0]["last_response_time"], "2026-06-14T09:00:00+08:00")
        self.assertEqual(result["rooms"][0]["email"], "room@example.com")
        self.assertEqual(result["rooms"][0]["response_status"], "tentative")
        self.assertEqual(result["rooms"][1]["email"], "room2@example.com")
        self.assertEqual(result["rooms"][1]["response_status"], "unknown")

    def test_verify_meeting_can_use_exact_changekey(self) -> None:
        item = FakeMeetingItem()
        client = EwsClient(
            EwsConfig(
                endpoint="https://ews.example.com/EWS/Exchange.asmx",
                email="organizer@example.com",
                username="organizer",
                password="secret",
            )
        )
        account = FakeCalendarAccount([item])
        client._account = account

        result = client.verify_meeting("event-1", "ck-1")

        self.assertEqual(account.calendar.get_calls, [("event-1", "ck-1")])
        self.assertEqual(result["id"], "event-1")

    def test_cancel_meeting_moves_exact_item_to_trash(self) -> None:
        item = FakeMeetingItem()
        client = EwsClient(
            EwsConfig(
                endpoint="https://ews.example.com/EWS/Exchange.asmx",
                email="organizer@example.com",
                username="organizer",
                password="secret",
            )
        )
        client._account = FakeCalendarAccount([item])

        result = client.cancel_meeting("event-1", "ck-1", send_meeting_cancellations=True)

        self.assertEqual(item.trash_calls, [{"send_meeting_cancellations": "SendToAllAndSaveCopy"}])
        self.assertEqual(result["id"], "event-1")
        self.assertEqual(result["changekey"], "ck-1")
        self.assertEqual(item.id, "")

    def test_update_meeting_saves_only_requested_fields(self) -> None:
        item = FakeMeetingItem()
        client = EwsClient(
            EwsConfig(
                endpoint="https://ews.example.com/EWS/Exchange.asmx",
                email="organizer@example.com",
                username="organizer",
                password="secret",
            )
        )
        client._account = FakeCalendarAccount([item])

        result = client.update_meeting(
            "event-1",
            "ck-1",
            {"subject": "New sync", "location": "Room B"},
            update_fields=["subject", "location"],
            send_meeting_invitations=True,
        )

        self.assertEqual(item.subject, "New sync")
        self.assertEqual(item.location, "Room B")
        self.assertEqual(
            item.save_calls,
            [{"update_fields": ["subject", "location"], "send_meeting_invitations": "SendToAllAndSaveCopy"}],
        )
        self.assertEqual(result["changekey"], "ck-2")

    def test_update_meeting_body_defaults_to_safe_html(self) -> None:
        item = FakeMeetingItem()
        client = EwsClient(
            EwsConfig(
                endpoint="https://ews.example.com/EWS/Exchange.asmx",
                email="organizer@example.com",
                username="organizer",
                password="secret",
            )
        )
        client._account = FakeCalendarAccount([item])

        client.update_meeting(
            "event-1",
            "ck-1",
            {"body": "PRD: https://wiki.example.com/prd/123\n<script>alert(1)</script>"},
            update_fields=["body"],
            send_meeting_invitations=True,
        )

        rendered = str(item.body)
        self.assertIn("<p>PRD: ", rendered)
        self.assertIn('<a href="https://wiki.example.com/prd/123">https://wiki.example.com/prd/123</a>', rendered)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", rendered)
        self.assertNotIn("<script>", rendered)


if __name__ == "__main__":
    unittest.main()
