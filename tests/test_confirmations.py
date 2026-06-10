from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from ews_meeting_mcp.confirmations import ConfirmationLedger, confirmation_id, default_state_dir
from ews_meeting_mcp.errors import EwsToolError


class ConfirmationTests(unittest.TestCase):
    def test_confirmation_id_uses_canonical_json(self) -> None:
        left = confirmation_id("create_meeting", {"b": 2, "a": {"z": 9, "y": 8}})
        right = confirmation_id("create_meeting", {"a": {"y": 8, "z": 9}, "b": 2})

        self.assertEqual(left, right)
        self.assertEqual(len(left), 64)

    def test_confirmation_id_changes_with_payload(self) -> None:
        first = confirmation_id("create_meeting", {"subject": "A"})
        second = confirmation_id("create_meeting", {"subject": "B"})

        self.assertNotEqual(first, second)

    def test_ledger_uses_configured_state_dir_and_records_safe_result_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as state_dir:
            with patch.dict(os.environ, {"EWS_MEETING_AGENT_STATE_DIR": state_dir}, clear=False):
                self.assertEqual(default_state_dir(), Path(state_dir))
                ledger = ConfirmationLedger()

                entry = ledger.record_completed(
                    id="abc",
                    action="create_meeting",
                    result={"created": {"id": "event-1"}, "preview": {"attendees": ["a@example.com"]}},
                )

                self.assertEqual(entry["confirmation_id"], "abc")
                self.assertEqual(ledger.completed("abc")["result"]["created"]["id"], "event-1")
                stored = json.loads((Path(state_dir) / "confirmation-ledger.json").read_text())
                self.assertEqual(stored["completed"]["abc"]["action"], "create_meeting")
                self.assertNotIn("password", json.dumps(stored).lower())

    def test_ledger_prefers_mcp_state_dir_environment_name(self) -> None:
        with tempfile.TemporaryDirectory() as state_dir:
            with patch.dict(
                os.environ,
                {
                    "EWS_MEETING_MCP_STATE_DIR": state_dir,
                    "EWS_MEETING_AGENT_STATE_DIR": "/tmp/legacy-state",
                },
                clear=False,
            ):
                self.assertEqual(default_state_dir(), Path(state_dir))

    def test_ledger_reserve_blocks_duplicate_or_in_progress_confirmation(self) -> None:
        with tempfile.TemporaryDirectory() as state_dir:
            ledger = ConfirmationLedger(Path(state_dir))

            ledger.reserve(id="abc", action="create_meeting")
            with self.assertRaises(EwsToolError) as raised:
                ledger.reserve(id="abc", action="create_meeting")
            self.assertEqual(raised.exception.error_code, "confirmation_in_progress")

            ledger.record_completed(id="abc", action="create_meeting", result={"created": {"id": "event-1"}})
            with self.assertRaises(EwsToolError) as duplicate:
                ledger.reserve(id="abc", action="create_meeting")
            self.assertEqual(duplicate.exception.error_code, "duplicate_confirmation")
            self.assertEqual(duplicate.exception.payload["prior_result"]["created"]["id"], "event-1")

    def test_ledger_release_removes_pending_confirmation(self) -> None:
        with tempfile.TemporaryDirectory() as state_dir:
            ledger = ConfirmationLedger(Path(state_dir))

            ledger.reserve(id="abc", action="create_meeting")
            ledger.release("abc")
            ledger.reserve(id="abc", action="create_meeting")

            stored = json.loads((Path(state_dir) / "confirmation-ledger.json").read_text())
            self.assertIn("abc", stored["pending"])

    def test_corrupt_ledger_returns_structured_error(self) -> None:
        with tempfile.TemporaryDirectory() as state_dir:
            path = Path(state_dir) / "confirmation-ledger.json"
            path.write_text("{not-json", encoding="utf-8")

            with self.assertRaises(EwsToolError) as raised:
                ConfirmationLedger(Path(state_dir)).completed("abc")

        self.assertEqual(raised.exception.error_code, "confirmation_ledger_unavailable")
        self.assertEqual(raised.exception.payload["required_action"], "repair_confirmation_ledger")


if __name__ == "__main__":
    unittest.main()
