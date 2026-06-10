from __future__ import annotations

from datetime import datetime
import unittest

from ews_meeting_agent.meeting import MeetingRequest, build_meeting_preview


class MeetingTests(unittest.TestCase):
    def test_build_meeting_preview_marks_dry_run_until_confirmed(self) -> None:
        request = MeetingRequest(
            subject="Project sync",
            attendees=["eason.lin@linebank.com.tw"],
            rooms=["3-1MeetingRoom@linebank.com.tw"],
            start=datetime.fromisoformat("2026-06-15T11:00:00+08:00"),
            end=datetime.fromisoformat("2026-06-15T11:30:00+08:00"),
            body="Discuss next steps",
            location="3-1 Meeting Room(12P)",
        )

        preview = build_meeting_preview(request, confirmed=False)

        self.assertEqual(preview["action"], "dry_run")
        self.assertFalse(preview["will_send_invites"])
        self.assertEqual(preview["subject"], "Project sync")
        self.assertEqual(preview["attendees"], ["eason.lin@linebank.com.tw"])
        self.assertEqual(preview["rooms"], ["3-1MeetingRoom@linebank.com.tw"])

    def test_build_meeting_preview_marks_confirmed_send(self) -> None:
        request = MeetingRequest(
            subject="Project sync",
            attendees=["eason.lin@linebank.com.tw"],
            start=datetime.fromisoformat("2026-06-15T11:00:00+08:00"),
            end=datetime.fromisoformat("2026-06-15T11:30:00+08:00"),
        )

        preview = build_meeting_preview(request, confirmed=True)

        self.assertEqual(preview["action"], "create_meeting")
        self.assertTrue(preview["will_send_invites"])


if __name__ == "__main__":
    unittest.main()
