from __future__ import annotations

from datetime import datetime, time, timedelta
import unittest

from ews_meeting_mcp.scheduler import TimeBlock, parse_time_range, suggest_slots
from ews_meeting_mcp.scheduler import merge_blocks


class SchedulerTests(unittest.TestCase):
    def test_merge_overlapping_blocks(self) -> None:
        blocks = [
            TimeBlock(dt("2026-06-10T10:00:00+08:00"), dt("2026-06-10T10:30:00+08:00")),
            TimeBlock(dt("2026-06-10T10:15:00+08:00"), dt("2026-06-10T11:00:00+08:00")),
        ]

        self.assertEqual(
            merge_blocks(blocks),
            [TimeBlock(dt("2026-06-10T10:00:00+08:00"), dt("2026-06-10T11:00:00+08:00"))],
        )

    def test_suggest_slots_skips_busy_blocks(self) -> None:
        busy = [
            TimeBlock(dt("2026-06-10T09:30:00+08:00"), dt("2026-06-10T10:00:00+08:00")),
            TimeBlock(dt("2026-06-10T10:30:00+08:00"), dt("2026-06-10T11:00:00+08:00")),
        ]

        slots = suggest_slots(
            busy,
            dt("2026-06-10T09:00:00+08:00"),
            dt("2026-06-10T12:00:00+08:00"),
            timedelta(minutes=30),
            limit=3,
        )

        self.assertEqual(
            slots,
            [
                TimeBlock(dt("2026-06-10T09:00:00+08:00"), dt("2026-06-10T09:30:00+08:00")),
                TimeBlock(dt("2026-06-10T10:00:00+08:00"), dt("2026-06-10T10:30:00+08:00")),
                TimeBlock(dt("2026-06-10T11:00:00+08:00"), dt("2026-06-10T11:30:00+08:00")),
            ],
        )

    def test_suggest_slots_stays_inside_workday(self) -> None:
        slots = suggest_slots(
            [],
            dt("2026-06-10T17:45:00+08:00"),
            dt("2026-06-10T19:00:00+08:00"),
            timedelta(minutes=30),
        )

        self.assertEqual(slots, [])

    def test_suggest_slots_avoids_morning_and_lunch(self) -> None:
        slots = suggest_slots(
            [],
            dt("2026-06-10T09:00:00+08:00"),
            dt("2026-06-10T15:00:00+08:00"),
            timedelta(minutes=30),
            workday_start=time(10, 0),
            excluded_windows=[(time(12, 0), time(14, 0))],
            limit=6,
        )

        self.assertEqual(
            slots,
            [
                TimeBlock(dt("2026-06-10T10:00:00+08:00"), dt("2026-06-10T10:30:00+08:00")),
                TimeBlock(dt("2026-06-10T10:15:00+08:00"), dt("2026-06-10T10:45:00+08:00")),
                TimeBlock(dt("2026-06-10T10:30:00+08:00"), dt("2026-06-10T11:00:00+08:00")),
                TimeBlock(dt("2026-06-10T10:45:00+08:00"), dt("2026-06-10T11:15:00+08:00")),
                TimeBlock(dt("2026-06-10T11:00:00+08:00"), dt("2026-06-10T11:30:00+08:00")),
                TimeBlock(dt("2026-06-10T11:15:00+08:00"), dt("2026-06-10T11:45:00+08:00")),
            ],
        )

    def test_suggest_slots_skips_slot_that_touches_excluded_window(self) -> None:
        slots = suggest_slots(
            [],
            dt("2026-06-10T11:30:00+08:00"),
            dt("2026-06-10T15:00:00+08:00"),
            timedelta(minutes=45),
            workday_start=time(10, 0),
            excluded_windows=[(time(12, 0), time(14, 0))],
            limit=1,
        )

        self.assertEqual(
            slots,
            [TimeBlock(dt("2026-06-10T14:00:00+08:00"), dt("2026-06-10T14:45:00+08:00"))],
        )

    def test_parse_time_range(self) -> None:
        self.assertEqual(parse_time_range("12:00-14:00"), (time(12, 0), time(14, 0)))


def dt(value: str) -> datetime:
    return datetime.fromisoformat(value)


if __name__ == "__main__":
    unittest.main()
