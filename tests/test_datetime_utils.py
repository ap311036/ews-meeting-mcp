from __future__ import annotations

from datetime import timezone
import unittest

from ews_meeting_mcp.datetime_utils import parse_iso_datetime


class DatetimeUtilsTests(unittest.TestCase):
    def test_parse_iso_datetime_accepts_rfc3339_z_suffix(self) -> None:
        value = parse_iso_datetime("2026-06-11T10:00:00Z")

        self.assertEqual(value.hour, 10)
        self.assertEqual(value.tzinfo, timezone.utc)

    def test_parse_iso_datetime_preserves_numeric_offset(self) -> None:
        value = parse_iso_datetime("2026-06-11T10:00:00+08:00")

        self.assertEqual(value.isoformat(), "2026-06-11T10:00:00+08:00")


if __name__ == "__main__":
    unittest.main()
