from __future__ import annotations

from datetime import datetime
import unittest

from ews_meeting_mcp.meeting import MeetingRequest, build_meeting_preview, normalize_recurrence, render_body_for_format


class MeetingTests(unittest.TestCase):
    def test_build_meeting_preview_marks_dry_run_until_confirmed(self) -> None:
        request = MeetingRequest(
            subject="Project sync",
            attendees=["eason.lin@example.com"],
            rooms=["3-1MeetingRoom@example.com"],
            start=datetime.fromisoformat("2026-06-15T11:00:00+08:00"),
            end=datetime.fromisoformat("2026-06-15T11:30:00+08:00"),
            body="Discuss next steps",
            location="3-1 Meeting Room(12P)",
        )

        preview = build_meeting_preview(request, confirmed=False)

        self.assertEqual(preview["action"], "dry_run")
        self.assertFalse(preview["will_send_invites"])
        self.assertEqual(preview["subject"], "Project sync")
        self.assertEqual(preview["attendees"], ["eason.lin@example.com"])
        self.assertEqual(preview["rooms"], ["3-1MeetingRoom@example.com"])

    def test_build_meeting_preview_marks_confirmed_send(self) -> None:
        request = MeetingRequest(
            subject="Project sync",
            attendees=["eason.lin@example.com"],
            start=datetime.fromisoformat("2026-06-15T11:00:00+08:00"),
            end=datetime.fromisoformat("2026-06-15T11:30:00+08:00"),
        )

        preview = build_meeting_preview(request, confirmed=True)

        self.assertEqual(preview["action"], "create_meeting")
        self.assertTrue(preview["will_send_invites"])

    def test_preview_defaults_body_format_to_html(self) -> None:
        request = MeetingRequest(
            subject="Project sync",
            attendees=["eason.lin@example.com"],
            start=datetime.fromisoformat("2026-06-15T11:00:00+08:00"),
            end=datetime.fromisoformat("2026-06-15T11:30:00+08:00"),
        )

        preview = build_meeting_preview(request, confirmed=False)

        self.assertEqual(preview["body_format"], "html")

    def test_preview_includes_normalized_weekly_recurrence(self) -> None:
        request = MeetingRequest(
            subject="Project sync",
            attendees=["eason.lin@example.com"],
            start=datetime.fromisoformat("2026-06-15T11:00:00+08:00"),
            end=datetime.fromisoformat("2026-06-15T11:30:00+08:00"),
            recurrence={
                "type": "weekly",
                "interval": 1,
                "weekdays": ["MO", "WE"],
                "range": {"type": "end_date", "end_date": "2026-07-26"},
            },
        )

        preview = build_meeting_preview(request, confirmed=False)

        self.assertEqual(
            preview["recurrence"],
            {
                "type": "weekly",
                "interval": 1,
                "weekdays": ["MO", "WE"],
                "range": {"type": "end_date", "end_date": "2026-07-26"},
            },
        )

    def test_business_days_are_weekdays_in_recurrence_payload(self) -> None:
        recurrence = normalize_recurrence(
            {
                "type": "weekly",
                "weekdays": ["MO", "TU", "WE", "TH", "FR"],
                "range": {"type": "end_date", "end_date": "2026-07-26"},
            }
        )

        self.assertEqual(recurrence["weekdays"], ["MO", "TU", "WE", "TH", "FR"])

    def test_recurrence_rejects_invalid_values(self) -> None:
        base = {
            "type": "weekly",
            "interval": 1,
            "weekdays": ["MO"],
            "range": {"type": "end_date", "end_date": "2026-07-26"},
        }

        for override in [
            {"weekdays": []},
            {"weekdays": ["XX"]},
            {"interval": 0},
            {"range": {}},
            {"range": {"type": "end_date"}},
        ]:
            recurrence = {**base, **override}
            with self.subTest(recurrence=recurrence):
                with self.assertRaises(ValueError):
                    normalize_recurrence(recurrence)

    def test_plain_text_body_renders_safe_html_with_links_and_line_breaks(self) -> None:
        rendered = render_body_for_format(
            "Hi team,\n請先看 PRD: https://wiki.example.com/prd/123?x=1&y=2\n\n<script>alert(1)</script>"
        )

        self.assertIn("<p>Hi team,<br>", rendered)
        self.assertIn(
            '<a href="https://wiki.example.com/prd/123?x=1&amp;y=2">'
            "https://wiki.example.com/prd/123?x=1&amp;y=2</a>",
            rendered,
        )
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", rendered)
        self.assertNotIn("<script>", rendered)

    def test_explicit_html_body_is_preserved(self) -> None:
        body = '<p>PRD: <a href="https://wiki.example.com/prd/123">link</a></p>'

        self.assertEqual(render_body_for_format(body), body)

    def test_text_body_format_is_preserved_as_plain_text(self) -> None:
        body = "Line 1\nLine 2"

        self.assertEqual(render_body_for_format(body, "text"), body)


if __name__ == "__main__":
    unittest.main()
