from __future__ import annotations

import os
import tempfile
import unittest
from unittest.mock import patch

from ews_meeting_agent.errors import EwsToolError
from ews_meeting_agent.policy import load_policy


class PolicyTests(unittest.TestCase):
    def test_defaults_match_current_scheduling_policy(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.dict(os.environ, {}, clear=True):
                with patch("os.getcwd", return_value=tmpdir):
                    policy = load_policy()

        self.assertEqual(policy.workday_start, "10:00")
        self.assertEqual(policy.workday_end, "18:00")
        self.assertEqual(policy.avoid, ["12:00-14:00"])
        self.assertEqual(
            [room["alias"] for room in policy.rooms],
            ["2-11", "2-13", "2-14", "3-1", "3-2", "3-4"],
        )

    def test_env_policy_file_overrides_scheduling_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "policy.json")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(
                    '{"workday_start": "09:30", "workday_end": "17:30", "avoid": ["12:30-13:30"]}'
                )

            with patch.dict(os.environ, {"EWS_MEETING_POLICY_FILE": path}, clear=True):
                policy = load_policy()

        self.assertEqual(policy.workday_start, "09:30")
        self.assertEqual(policy.workday_end, "17:30")
        self.assertEqual(policy.avoid, ["12:30-13:30"])

    def test_invalid_json_raises_structured_config_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "policy.json")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write("{not-json")

            with patch.dict(os.environ, {"EWS_MEETING_POLICY_FILE": path}, clear=True):
                with self.assertRaises(EwsToolError) as raised:
                    load_policy()

        payload = raised.exception.payload
        self.assertEqual(payload["error_code"], "policy_invalid_json")
        self.assertEqual(payload["required_action"], "fix_policy_file")
        self.assertEqual(payload["policy_file"], path)

    def test_policy_rooms_merge_with_defaults_and_override_by_alias(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "policy.json")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(
                    """
                    {
                      "rooms": [
                        {
                          "alias": "3-1",
                          "name": "Custom 3-1",
                          "email": "custom-3-1@example.com",
                          "capacity": 16
                        },
                        {
                          "alias": "5-1",
                          "name": "5-1 Meeting Room(20P)",
                          "email": "5-1MeetingRoom@example.com",
                          "capacity": 20
                        }
                      ]
                    }
                    """
                )

            with patch.dict(os.environ, {"EWS_MEETING_POLICY_FILE": path}, clear=True):
                policy = load_policy()

        room_by_alias = {room["alias"]: room for room in policy.rooms}
        self.assertEqual(room_by_alias["2-11"]["email"], "2-11MeetingRoom@linebank.com.tw")
        self.assertEqual(room_by_alias["3-1"]["email"], "custom-3-1@example.com")
        self.assertEqual(room_by_alias["3-1"]["capacity"], 16)
        self.assertEqual(room_by_alias["5-1"]["capacity"], 20)


if __name__ == "__main__":
    unittest.main()
