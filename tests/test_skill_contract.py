from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class SkillContractTests(unittest.TestCase):
    def test_skill_requires_name_resolution_before_scheduling(self) -> None:
        text = (ROOT / "skills" / "ews-meeting-mcp" / "SKILL.md").read_text()

        self.assertIn("ews_resolve_attendees", text)
        self.assertIn("not a complete email address", text)
        self.assertIn("ask the user to choose", text)
        self.assertIn("ask whether a meeting room is needed", text)
        self.assertIn("require_room", text)
        self.assertIn("capacity", text)
        self.assertIn("ews_keychain_status", text)
        self.assertIn("setup_command", text)
        self.assertIn("required_action", text)
        self.assertIn("verbatim", text)
        self.assertIn("ews_list_rooms", text)
        self.assertIn("structured meeting-room choices", text)


if __name__ == "__main__":
    unittest.main()
