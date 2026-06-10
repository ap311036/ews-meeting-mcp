from __future__ import annotations

from datetime import datetime, timedelta
import unittest

from ews_meeting_agent import agent_tools
from ews_meeting_agent.scheduler import TimeBlock


class FakeClient:
    def __init__(self) -> None:
        self.calls: list[tuple[list[str], int]] = []
        self.free_busy_calls: list[list[str]] = []
        self.free_busy_by_attendee_calls: list[list[str]] = []
        self.created_attendees: list[str] | None = None
        self.created_rooms: list[str] | None = None

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
            "3-1MeetingRoom@linebank.com.tw": [],
            "3-2MeetingRoom@linebank.com.tw": [TimeBlock(busy_start, busy_end)],
            "2-11MeetingRoom@linebank.com.tw": [],
            "2-13MeetingRoom@linebank.com.tw": [],
            "2-14MeetingRoom@linebank.com.tw": [],
            "3-4MeetingRoom@linebank.com.tw": [],
        }

    def create_meeting(self, request: object) -> dict[str, str]:
        self.created_attendees = request.attendees
        self.created_rooms = request.rooms
        return {"id": "event-1", "changekey": "ck-1"}


class AgentToolTests(unittest.TestCase):
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
                    "3-1MeetingRoom@linebank.com.tw",
                    "3-2MeetingRoom@linebank.com.tw",
                    "2-11MeetingRoom@linebank.com.tw",
                    "2-13MeetingRoom@linebank.com.tw",
                    "2-14MeetingRoom@linebank.com.tw",
                ]
            ],
        )
        self.assertEqual(result[0]["available_rooms"][0]["email"], "3-1MeetingRoom@linebank.com.tw")
        self.assertNotIn(
            "3-2MeetingRoom@linebank.com.tw",
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
        self.assertIn("3-1MeetingRoom@linebank.com.tw", room_emails)
        self.assertNotIn("3-2MeetingRoom@linebank.com.tw", room_emails)
        self.assertNotIn("3-4MeetingRoom@linebank.com.tw", room_emails)
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

    def test_suggest_slots_reports_ambiguous_names_before_free_busy_lookup(self) -> None:
        client = FakeClient()

        with self.assertRaisesRegex(ValueError, "Alex.*alex.chen@example.com.*alex.lin@example.com"):
            agent_tools.ews_suggest_slots(
                attendees=["Alex"],
                start="2026-06-15T10:00:00+08:00",
                end="2026-06-15T11:00:00+08:00",
                client_factory=lambda: client,
            )

        self.assertEqual(client.free_busy_calls, [])

    def test_create_meeting_confirmed_resolves_names_before_creating(self) -> None:
        client = FakeClient()

        result = agent_tools.ews_create_meeting_confirmed(
            subject="Sync",
            attendees=["王小明"],
            rooms=["3-1"],
            start="2026-06-15T10:00:00+08:00",
            end="2026-06-15T11:00:00+08:00",
            confirm=True,
            client_factory=lambda: client,
        )

        self.assertEqual(result["preview"]["attendees"], ["ming.wang@example.com"])
        self.assertEqual(result["preview"]["rooms"], ["3-1MeetingRoom@linebank.com.tw"])
        self.assertEqual(client.created_attendees, ["ming.wang@example.com"])
        self.assertEqual(client.created_rooms, ["3-1MeetingRoom@linebank.com.tw"])

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

        self.assertEqual(result["rooms"], ["2-11MeetingRoom@linebank.com.tw"])
        self.assertEqual(result["location"], "2-11 Meeting Room")

    def test_known_room_metadata_includes_capacity_when_name_declares_people(self) -> None:
        rooms = agent_tools.default_room_options()

        room_by_email = {room["email"]: room for room in rooms}
        self.assertEqual(room_by_email["3-1MeetingRoom@linebank.com.tw"]["alias"], "3-1")
        self.assertEqual(room_by_email["3-1MeetingRoom@linebank.com.tw"]["capacity"], 12)
        self.assertEqual(room_by_email["3-2MeetingRoom@linebank.com.tw"]["capacity"], 6)

    def test_list_rooms_returns_structured_options_for_user_selection(self) -> None:
        result = agent_tools.ews_list_rooms(attendee_count=7)

        self.assertEqual(result["selection_hint"], "Ask the user to choose one room value, or choose no specific room.")
        values = [option["value"] for option in result["options"]]
        self.assertIn("3-1", values)
        self.assertNotIn("3-2", values)
        self.assertNotIn("3-4", values)
        first = result["options"][0]
        self.assertIn("label", first)
        self.assertIn("email", first)
        self.assertIn("capacity", first)


if __name__ == "__main__":
    unittest.main()
