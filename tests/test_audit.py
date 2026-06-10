from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from ews_meeting_mcp.audit import AuditLog, build_audit_entry, read_audit_log, record_lifecycle_audit


class AuditLogTests(unittest.TestCase):
    def test_audit_log_uses_state_dir_and_redacts_sensitive_values(self) -> None:
        with tempfile.TemporaryDirectory() as state_dir:
            with patch.dict(os.environ, {"EWS_MEETING_AGENT_STATE_DIR": state_dir}, clear=False):
                warning = record_lifecycle_audit(
                    action="create_meeting",
                    status="preview",
                    payload={
                        "arguments": {
                            "subject": "Sync",
                            "attendees": ["a@example.com"],
                            "EWS_PASSWORD": "do-not-store",
                            "api_token": "also-secret",
                        },
                        "result": {"confirmation_id": "abc"},
                    },
                )

                self.assertIsNone(warning)
                path = Path(state_dir) / "audit-log.jsonl"
                raw = path.read_text(encoding="utf-8")
                self.assertIn("create_meeting", raw)
                self.assertNotIn("do-not-store", raw)
                self.assertNotIn("also-secret", raw)
                self.assertNotIn("password", raw.lower())

    def test_audit_log_appends_jsonl_and_reads_recent_filtered_entries(self) -> None:
        with tempfile.TemporaryDirectory() as state_dir:
            log = AuditLog(Path(state_dir))
            log.append(build_audit_entry(action="create_meeting", status="preview", payload={"subject": "A"}))
            log.append(build_audit_entry(action="create_meeting", status="confirmed", payload={"subject": "A"}))
            log.append(build_audit_entry(action="cancel_meeting", status="preview", payload={"subject": "B"}))

            all_entries = log.read(limit=10)
            confirmed = log.read(limit=10, status="confirmed")
            create_entries = log.read(limit=10, action="create_meeting")
            recent_one = log.read(limit=1)

        self.assertEqual(len(all_entries), 3)
        self.assertEqual([entry["status"] for entry in confirmed], ["confirmed"])
        self.assertEqual(len(create_entries), 2)
        self.assertEqual(recent_one[0]["action"], "cancel_meeting")

    def test_read_audit_log_filters_via_env_state_dir(self) -> None:
        with tempfile.TemporaryDirectory() as state_dir:
            with patch.dict(os.environ, {"EWS_MEETING_AGENT_STATE_DIR": state_dir}, clear=False):
                record_lifecycle_audit(action="update_meeting", status="error", payload={}, error_code="empty_update")
                record_lifecycle_audit(action="update_meeting", status="preview", payload={})

                entries = read_audit_log(limit=50, action="update_meeting", status="error")

        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["error_code"], "empty_update")

    def test_build_audit_entry_extracts_lifecycle_fields(self) -> None:
        entry = build_audit_entry(
            action="create_meeting",
            status="confirmed",
            payload={
                "result": {
                    "preview": {
                        "confirmation_id": "abc",
                        "subject": "Sync",
                        "start": "2026-06-15T10:00:00+08:00",
                        "end": "2026-06-15T10:30:00+08:00",
                        "location": "3-1 Meeting Room(12P)",
                        "attendees": ["a@example.com"],
                        "rooms": ["room@example.com"],
                    },
                    "created": {"id": "event-1", "changekey": "ck-1", "uid": "uid-1"},
                }
            },
        )

        self.assertEqual(entry["confirmation_id"], "abc")
        self.assertEqual(entry["id"], "event-1")
        self.assertEqual(entry["changekey"], "ck-1")
        self.assertEqual(entry["uid"], "uid-1")
        self.assertEqual(entry["subject"], "Sync")
        self.assertEqual(entry["attendees"], ["a@example.com"])
        self.assertEqual(entry["resources"], ["room@example.com"])

    def test_corrupt_jsonl_lines_are_skipped(self) -> None:
        with tempfile.TemporaryDirectory() as state_dir:
            path = Path(state_dir) / "audit-log.jsonl"
            path.write_text('{bad-json\n{"action":"create_meeting","status":"preview"}\n', encoding="utf-8")

            entries = AuditLog(Path(state_dir)).read(limit=50)

        self.assertEqual(entries, [{"action": "create_meeting", "status": "preview"}])


if __name__ == "__main__":
    unittest.main()
