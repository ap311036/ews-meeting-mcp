from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from ews_meeting_mcp.audit import record_lifecycle_audit
from ews_meeting_mcp.confirmations import ConfirmationLedger
from ews_meeting_mcp.mcp_server import handle_request


class McpServerTests(unittest.TestCase):
    def test_initialize_reports_package_version(self) -> None:
        with open("package.json", "r", encoding="utf-8") as handle:
            package_version = json.load(handle)["version"]

        response = handle_request({"jsonrpc": "2.0", "id": 1, "method": "initialize"})

        self.assertEqual(response["result"]["serverInfo"]["name"], "ews-meeting-mcp")
        self.assertEqual(response["result"]["serverInfo"]["version"], package_version)
        self.assertIn("interactive multiple-choice UI", response["result"]["instructions"])
        self.assertIn("clickable choice controls", response["result"]["instructions"])

    def test_lists_tools(self) -> None:
        response = handle_request({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})

        self.assertEqual(response["id"], 1)
        tool_names = [tool["name"] for tool in response["result"]["tools"]]
        self.assertIn("ews_keychain_status", tool_names)
        self.assertIn("ews_setup_check", tool_names)
        self.assertIn("ews_get_audit_log", tool_names)
        self.assertIn("ews_signature_setup_guide", tool_names)
        self.assertIn("ews_list_rooms", tool_names)
        self.assertIn("ews_resolve_attendees", tool_names)
        self.assertIn("ews_verify_meeting", tool_names)
        self.assertIn("ews_suggest_slots", tool_names)
        self.assertIn("ews_create_meeting_preview", tool_names)
        self.assertIn("ews_create_meeting_confirmed", tool_names)
        self.assertIn("ews_find_calendar_events", tool_names)
        self.assertIn("ews_update_meeting_preview", tool_names)
        self.assertIn("ews_update_meeting_confirmed", tool_names)
        self.assertIn("ews_cancel_meeting_preview", tool_names)
        self.assertIn("ews_cancel_meeting_confirmed", tool_names)

    def test_keychain_status_tool_has_empty_schema(self) -> None:
        response = handle_request({"jsonrpc": "2.0", "id": 10, "method": "tools/list"})

        tools = response["result"]["tools"]
        tool = next(item for item in tools if item["name"] == "ews_keychain_status")

        self.assertIn("without revealing the password", tool["description"])
        self.assertEqual(tool["inputSchema"], {"type": "object", "properties": {}, "additionalProperties": False})

    def test_setup_check_tool_has_empty_schema(self) -> None:
        response = handle_request({"jsonrpc": "2.0", "id": 17, "method": "tools/list"})

        tools = response["result"]["tools"]
        tool = next(item for item in tools if item["name"] == "ews_setup_check")

        self.assertIn("ready", tool["description"])
        self.assertEqual(tool["inputSchema"], {"type": "object", "properties": {}, "additionalProperties": False})

    def test_signature_setup_guide_tool_has_empty_schema_and_returns_sample(self) -> None:
        tools_response = handle_request({"jsonrpc": "2.0", "id": 33, "method": "tools/list"})
        tool = next(item for item in tools_response["result"]["tools"] if item["name"] == "ews_signature_setup_guide")

        response = handle_request(
            {
                "jsonrpc": "2.0",
                "id": 34,
                "method": "tools/call",
                "params": {"name": "ews_signature_setup_guide", "arguments": {}},
            }
        )

        payload = _tool_payload(response)
        self.assertIn("HTML signature", tool["description"])
        self.assertEqual(tool["inputSchema"], {"type": "object", "properties": {}, "additionalProperties": False})
        self.assertFalse(response["result"]["isError"])
        self.assertIn("sample_html", payload)
        self.assertIn("EWS_MEETING_SIGNATURE_HTML_PATH", payload["env"])
        self.assertIn("Best Regards", payload["sample_html"])

    def test_get_audit_log_tool_schema_and_call(self) -> None:
        with tempfile.TemporaryDirectory() as state_dir:
            with patch.dict(os.environ, {"EWS_MEETING_AGENT_STATE_DIR": state_dir}, clear=False):
                record_lifecycle_audit(action="create_meeting", status="preview", payload={"subject": "A"})
                record_lifecycle_audit(action="create_meeting", status="confirmed", payload={"subject": "A"})
                response = handle_request(
                    {
                        "jsonrpc": "2.0",
                        "id": 29,
                        "method": "tools/call",
                        "params": {
                            "name": "ews_get_audit_log",
                            "arguments": {"limit": 10, "action": "create_meeting", "status": "confirmed"},
                        },
                    }
                )

        tools_response = handle_request({"jsonrpc": "2.0", "id": 30, "method": "tools/list"})
        tool = next(item for item in tools_response["result"]["tools"] if item["name"] == "ews_get_audit_log")
        payload = _tool_payload(response)

        self.assertFalse(response["result"]["isError"])
        self.assertIn("limit", tool["inputSchema"]["properties"])
        self.assertIn("action", tool["inputSchema"]["properties"])
        self.assertIn("status", tool["inputSchema"]["properties"])
        self.assertEqual(len(payload), 1)
        self.assertEqual(payload[0]["status"], "confirmed")

    def test_setup_check_tool_returns_readiness_payload(self) -> None:
        with patch.dict(
            os.environ,
            {
                "EWS_ENDPOINT": "https://example.test/EWS/Exchange.asmx",
                "EWS_EMAIL": "ews.user@example.test",
                "EWS_USERNAME": "bk00325",
                "EWS_PASSWORD_KEYCHAIN_SERVICE": "ews-meeting-mcp",
            },
            clear=True,
        ):
            with patch("ews_meeting_mcp.config.load_dotenv"):
                with patch("subprocess.run") as run:
                    run.side_effect = subprocess.CalledProcessError(44, ["security"])

                    response = handle_request(
                        {
                            "jsonrpc": "2.0",
                            "id": 18,
                            "method": "tools/call",
                            "params": {"name": "ews_setup_check", "arguments": {}},
                        }
                    )

        payload = _tool_payload(response)
        self.assertFalse(payload["ready"])
        self.assertEqual(payload["next_action"], "show_setup_command")
        self.assertEqual(payload["error_code"], "credentials_missing")
        self.assertEqual(payload["checks"][-1]["error_code"], "credentials_missing")
        self.assertIn(payload["setup_command"], payload["user_message"])

    def test_setup_check_tool_returns_env_setup_payload_before_keychain_lookup(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            with patch("ews_meeting_mcp.config.load_dotenv"):
                with patch("subprocess.run") as run:
                    response = handle_request(
                        {
                            "jsonrpc": "2.0",
                            "id": 19,
                            "method": "tools/call",
                            "params": {"name": "ews_setup_check", "arguments": {}},
                        }
                    )

        payload = _tool_payload(response)
        self.assertFalse(payload["ready"])
        self.assertEqual(payload["next_action"], "fix_mcp_env")
        self.assertEqual(payload["error_code"], "credentials_missing")
        self.assertIn("EWS_ENDPOINT", payload["setup_command"])
        run.assert_not_called()

    def test_setup_check_tool_returns_ready_when_env_password_is_present(self) -> None:
        with patch.dict(
            os.environ,
            {
                "EWS_ENDPOINT": "https://example.test/EWS/Exchange.asmx",
                "EWS_EMAIL": "ews.user@example.test",
                "EWS_USERNAME": "bk00325",
                "EWS_PASSWORD": "secret-from-env",
            },
            clear=True,
        ):
            with patch("ews_meeting_mcp.config.load_dotenv"):
                response = handle_request(
                    {
                        "jsonrpc": "2.0",
                        "id": 20,
                        "method": "tools/call",
                        "params": {"name": "ews_setup_check", "arguments": {}},
                    }
                )

        payload = _tool_payload(response)
        self.assertTrue(payload["ready"])
        self.assertEqual(payload["next_action"], "ready")

    def test_keychain_status_tool_returns_status_payload(self) -> None:
        with patch("ews_meeting_mcp.agent_tools.keychain_status") as status:
            status.return_value = {
                "configured": False,
                "source": "missing",
                "service": "ews-meeting-mcp",
                "account": "bk00325",
                "setup_command": "security add-generic-password ...",
                "required_action": "show_setup_command",
                "user_message": "請執行：\nsecurity add-generic-password ...",
            }

            response = handle_request(
                {
                    "jsonrpc": "2.0",
                    "id": 13,
                    "method": "tools/call",
                    "params": {"name": "ews_keychain_status", "arguments": {}},
                }
            )

        payload = _tool_payload(response)
        self.assertFalse(payload["configured"])
        self.assertEqual(payload["source"], "missing")
        self.assertIn("setup_command", payload)
        self.assertEqual(payload["required_action"], "show_setup_command")
        self.assertIn(payload["setup_command"], payload["user_message"])

    def test_ews_tools_preflight_setup_before_doing_work(self) -> None:
        with patch("ews_meeting_mcp.agent_tools.ews_setup_check") as status:
            status.return_value = {
                "ready": False,
                "error_code": "credentials_missing",
                "next_action": "show_setup_command",
                "source": "missing",
                "service": "ews-meeting-mcp",
                "account": "bk00325",
                "setup_command": "security add-generic-password ...",
                "required_action": "show_setup_command",
                "user_message": "請執行：\nsecurity add-generic-password ...",
            }
            with patch("ews_meeting_mcp.agent_tools.ews_resolve_attendees") as resolve:
                response = handle_request(
                    {
                        "jsonrpc": "2.0",
                        "id": 16,
                        "method": "tools/call",
                        "params": {
                            "name": "ews_resolve_attendees",
                            "arguments": {"attendees": ["Eason", "Riva"]},
                        },
                    }
                )

        self.assertTrue(response["result"]["isError"])
        payload = _tool_payload(response)
        self.assertEqual(payload["required_action"], "show_setup_command")
        self.assertEqual(payload["error_code"], "credentials_missing")
        self.assertIn("setup_command", payload)
        resolve.assert_not_called()

    def test_lifecycle_preflight_setup_error_is_audited(self) -> None:
        with tempfile.TemporaryDirectory() as state_dir:
            with patch.dict(os.environ, {"EWS_MEETING_AGENT_STATE_DIR": state_dir}, clear=False):
                with patch("ews_meeting_mcp.agent_tools.ews_setup_check") as status:
                    status.return_value = {
                        "ready": False,
                        "error_code": "credentials_missing",
                        "next_action": "show_setup_command",
                        "required_action": "show_setup_command",
                    }
                    response = handle_request(
                        {
                            "jsonrpc": "2.0",
                            "id": 31,
                            "method": "tools/call",
                            "params": {
                                "name": "ews_update_meeting_preview",
                                "arguments": {
                                    "id": "event-1",
                                    "changekey": "ck-1",
                                    "subject": "New sync",
                                },
                            },
                        }
                    )
                    audit_response = handle_request(
                        {
                            "jsonrpc": "2.0",
                            "id": 32,
                            "method": "tools/call",
                            "params": {
                                "name": "ews_get_audit_log",
                                "arguments": {"action": "update_meeting", "status": "error"},
                            },
                        }
                    )

        payload = _tool_payload(response)
        audit_entries = _tool_payload(audit_response)
        self.assertTrue(response["result"]["isError"])
        self.assertEqual(payload["error_code"], "credentials_missing")
        self.assertEqual(len(audit_entries), 1)
        self.assertEqual(audit_entries[0]["error_code"], "credentials_missing")
        self.assertEqual(audit_entries[0]["id"], "event-1")
        self.assertEqual(audit_entries[0]["changekey"], "ck-1")

    def test_ews_tools_preflight_reports_invalid_policy_before_missing_credentials(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "policy.json")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write("{not-json")

            with patch.dict(os.environ, {"EWS_MEETING_POLICY_FILE": path}, clear=True):
                response = handle_request(
                    {
                        "jsonrpc": "2.0",
                        "id": 21,
                        "method": "tools/call",
                        "params": {
                            "name": "ews_suggest_slots",
                            "arguments": {
                                "attendees": ["eason@example.com"],
                                "start": "2026-06-15T10:00:00+08:00",
                                "end": "2026-06-15T11:00:00+08:00",
                            },
                        },
                    }
                )

        self.assertTrue(response["result"]["isError"])
        payload = _tool_payload(response)
        self.assertEqual(payload["error_code"], "policy_invalid_json")
        self.assertEqual(payload["required_action"], "fix_policy_file")
        self.assertEqual(payload["policy_file"], path)

    def test_suggest_slots_tool_schema_accepts_rooms(self) -> None:
        response = handle_request({"jsonrpc": "2.0", "id": 12, "method": "tools/list"})

        tools = response["result"]["tools"]
        tool = next(item for item in tools if item["name"] == "ews_suggest_slots")

        self.assertIn("rooms", tool["inputSchema"]["properties"])
        self.assertIn("require_room", tool["inputSchema"]["properties"])
        attendee_description = tool["inputSchema"]["properties"]["attendees"]["description"]
        self.assertIn("display names", attendee_description)
        self.assertIn("do not ask the user for full email", attendee_description)

    def test_list_rooms_tool_schema_accepts_attendee_count(self) -> None:
        response = handle_request({"jsonrpc": "2.0", "id": 14, "method": "tools/list"})

        tools = response["result"]["tools"]
        tool = next(item for item in tools if item["name"] == "ews_list_rooms")

        self.assertIn("Exchange meeting rooms", tool["description"])
        self.assertIn("attendee_count", tool["inputSchema"]["properties"])
        self.assertIn("query", tool["inputSchema"]["properties"])
        self.assertIn("room_list", tool["inputSchema"]["properties"])
        self.assertIn("source", tool["inputSchema"]["properties"])
        self.assertIn("limit", tool["inputSchema"]["properties"])
        self.assertEqual(tool["inputSchema"]["properties"]["source"]["enum"], ["auto", "exchange", "static"])

    def test_list_rooms_tool_returns_structured_options(self) -> None:
        response = handle_request(
            {
                "jsonrpc": "2.0",
                "id": 15,
                "method": "tools/call",
                "params": {"name": "ews_list_rooms", "arguments": {"attendee_count": 7, "source": "static"}},
            }
        )

        payload = _tool_payload(response)
        self.assertEqual(payload["source"], "static")
        self.assertIn("options", payload)
        self.assertIn("selection_hint", payload)
        self.assertIn("3-1", [option["value"] for option in payload["options"]])

    def test_list_rooms_source_static_does_not_preflight_credentials(self) -> None:
        with patch("ews_meeting_mcp.agent_tools.keychain_status") as status:
            response = handle_request(
                {
                    "jsonrpc": "2.0",
                    "id": 22,
                    "method": "tools/call",
                    "params": {"name": "ews_list_rooms", "arguments": {"source": "static"}},
                }
            )

        payload = _tool_payload(response)
        self.assertFalse(response["result"]["isError"])
        self.assertEqual(payload["source"], "static")
        status.assert_not_called()

    def test_resolve_attendees_tool_schema_accepts_names_or_emails(self) -> None:
        response = handle_request({"jsonrpc": "2.0", "id": 11, "method": "tools/list"})

        tools = response["result"]["tools"]
        tool = next(item for item in tools if item["name"] == "ews_resolve_attendees")

        self.assertIn("company Exchange directory", tool["description"])
        self.assertEqual(tool["inputSchema"]["required"], ["attendees"])
        self.assertIn("attendees", tool["inputSchema"]["properties"])
        self.assertIn("limit", tool["inputSchema"]["properties"])

    def test_preview_tool_does_not_send_invites(self) -> None:
        response = handle_request(
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {
                    "name": "ews_create_meeting_preview",
                    "arguments": {
                        "subject": "Project sync",
                        "attendees": ["eason.lin@example.com"],
                        "start": "2026-06-15T11:00:00+08:00",
                        "end": "2026-06-15T11:30:00+08:00",
                    },
                },
            }
        )

        payload = _tool_payload(response)
        self.assertEqual(payload["action"], "dry_run")
        self.assertFalse(payload["will_send_invites"])
        self.assertIn("confirmation_id", payload)

    def test_confirmed_tool_requires_confirm_true(self) -> None:
        response = handle_request(
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {
                    "name": "ews_create_meeting_confirmed",
                    "arguments": {
                        "subject": "Project sync",
                        "attendees": ["eason.lin@example.com"],
                        "start": "2026-06-15T11:00:00+08:00",
                        "end": "2026-06-15T11:30:00+08:00",
                        "confirm": False,
                    },
                },
            }
        )

        self.assertTrue(response["result"]["isError"])
        self.assertIn("confirm=true", response["result"]["content"][0]["text"])

    def test_duplicate_confirmation_bypasses_setup_preflight(self) -> None:
        with tempfile.TemporaryDirectory() as state_dir:
            with patch.dict(os.environ, {"EWS_MEETING_AGENT_STATE_DIR": state_dir}, clear=True):
                ConfirmationLedger().record_completed(
                    id="done-id",
                    action="create_meeting",
                    result={"created": {"id": "event-1", "changekey": "ck-1"}},
                )
                with patch("ews_meeting_mcp.agent_tools.ews_setup_check") as setup:
                    setup.return_value = {"ready": False, "error_code": "credentials_missing"}
                    response = handle_request(
                        {
                            "jsonrpc": "2.0",
                            "id": 26,
                            "method": "tools/call",
                            "params": {
                                "name": "ews_create_meeting_confirmed",
                                "arguments": {
                                    "subject": "Project sync",
                                    "attendees": ["eason.lin@example.com"],
                                    "start": "2026-06-15T11:00:00+08:00",
                                    "end": "2026-06-15T11:30:00+08:00",
                                    "confirm": True,
                                    "confirmation_id": "done-id",
                                },
                            },
                        }
                    )

        payload = _tool_payload(response)
        self.assertTrue(response["result"]["isError"])
        self.assertEqual(payload["error_code"], "duplicate_confirmation")
        self.assertEqual(payload["prior_result"]["created"]["id"], "event-1")
        setup.assert_not_called()

    def test_confirmed_tool_missing_confirmation_id_bypasses_setup_preflight(self) -> None:
        with patch("ews_meeting_mcp.agent_tools.ews_setup_check") as setup:
            setup.return_value = {"ready": False, "error_code": "credentials_missing"}
            response = handle_request(
                {
                    "jsonrpc": "2.0",
                    "id": 27,
                    "method": "tools/call",
                    "params": {
                        "name": "ews_create_meeting_confirmed",
                        "arguments": {
                            "subject": "Project sync",
                            "attendees": ["eason.lin@example.com"],
                            "start": "2026-06-15T11:00:00+08:00",
                            "end": "2026-06-15T11:30:00+08:00",
                            "confirm": True,
                        },
                    },
                }
            )

        payload = _tool_payload(response)
        self.assertTrue(response["result"]["isError"])
        self.assertEqual(payload["error_code"], "confirmation_mismatch")
        setup.assert_not_called()

    def test_corrupt_confirmation_ledger_bypasses_setup_preflight_for_structured_error(self) -> None:
        with tempfile.TemporaryDirectory() as state_dir:
            path = os.path.join(state_dir, "confirmation-ledger.json")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write("{not-json")

            with patch.dict(os.environ, {"EWS_MEETING_AGENT_STATE_DIR": state_dir}, clear=True):
                with patch("ews_meeting_mcp.agent_tools.ews_setup_check") as setup:
                    setup.return_value = {"ready": False, "error_code": "credentials_missing"}
                    response = handle_request(
                        {
                            "jsonrpc": "2.0",
                            "id": 28,
                            "method": "tools/call",
                            "params": {
                                "name": "ews_create_meeting_confirmed",
                                "arguments": {
                                    "subject": "Project sync",
                                    "attendees": ["eason.lin@example.com"],
                                    "start": "2026-06-15T11:00:00+08:00",
                                    "end": "2026-06-15T11:30:00+08:00",
                                    "confirm": True,
                                    "confirmation_id": "abc",
                                },
                            },
                        }
                    )

        payload = _tool_payload(response)
        self.assertTrue(response["result"]["isError"])
        self.assertEqual(payload["error_code"], "confirmation_ledger_unavailable")
        self.assertEqual(payload["required_action"], "repair_confirmation_ledger")
        setup.assert_not_called()

    def test_tool_schemas_avoid_const_keyword_for_client_compatibility(self) -> None:
        response = handle_request({"jsonrpc": "2.0", "id": 4, "method": "tools/list"})

        schemas = [tool["inputSchema"] for tool in response["result"]["tools"]]
        self.assertFalse(any(_contains_key(schema, "const") for schema in schemas))

    def test_lifecycle_tool_schemas_expose_find_preview_confirm_flow(self) -> None:
        response = handle_request({"jsonrpc": "2.0", "id": 23, "method": "tools/list"})

        tools = {tool["name"]: tool for tool in response["result"]["tools"]}

        self.assertIn("subject_contains", tools["ews_find_calendar_events"]["inputSchema"]["properties"])
        self.assertIn("attendee_email", tools["ews_find_calendar_events"]["inputSchema"]["properties"])
        self.assertEqual(tools["ews_verify_meeting"]["inputSchema"]["required"], ["id"])
        self.assertIn("changekey", tools["ews_verify_meeting"]["inputSchema"]["properties"])
        self.assertIn("confirmation_id", tools["ews_create_meeting_confirmed"]["inputSchema"]["properties"])
        self.assertIn("confirmation_id", tools["ews_update_meeting_confirmed"]["inputSchema"]["properties"])
        self.assertIn("confirmation_id", tools["ews_cancel_meeting_confirmed"]["inputSchema"]["properties"])
        self.assertIn("confirm=true", tools["ews_create_meeting_confirmed"]["description"])
        self.assertIn("confirm=true", tools["ews_update_meeting_confirmed"]["description"])
        self.assertIn("confirm=true", tools["ews_cancel_meeting_confirmed"]["description"])
        self.assertIn("confirm", tools["ews_create_meeting_confirmed"]["inputSchema"]["required"])
        self.assertIn("confirmation_id", tools["ews_create_meeting_confirmed"]["inputSchema"]["required"])
        self.assertIn("confirm", tools["ews_update_meeting_confirmed"]["inputSchema"]["required"])
        self.assertIn("confirmation_id", tools["ews_update_meeting_confirmed"]["inputSchema"]["required"])
        self.assertIn("confirm", tools["ews_cancel_meeting_confirmed"]["inputSchema"]["required"])
        self.assertIn("confirmation_id", tools["ews_cancel_meeting_confirmed"]["inputSchema"]["required"])

    def test_meeting_schemas_default_body_format_to_html(self) -> None:
        response = handle_request({"jsonrpc": "2.0", "id": 29, "method": "tools/list"})

        tools = {tool["name"]: tool for tool in response["result"]["tools"]}
        create_body_format = tools["ews_create_meeting_preview"]["inputSchema"]["properties"]["body_format"]
        update_body_format = tools["ews_update_meeting_preview"]["inputSchema"]["properties"]["body_format"]
        include_signature = tools["ews_create_meeting_preview"]["inputSchema"]["properties"]["include_signature"]

        self.assertEqual(create_body_format["default"], "html")
        self.assertEqual(create_body_format["enum"], ["html", "text"])
        self.assertEqual(update_body_format["default"], "html")
        self.assertEqual(update_body_format["enum"], ["html", "text"])
        self.assertEqual(include_signature["default"], True)

    def test_update_confirmed_false_returns_structured_confirmation_error(self) -> None:
        response = handle_request(
            {
                "jsonrpc": "2.0",
                "id": 24,
                "method": "tools/call",
                "params": {
                    "name": "ews_update_meeting_confirmed",
                    "arguments": {
                        "id": "event-1",
                        "changekey": "ck-1",
                        "subject": "New sync",
                        "confirm": False,
                        "confirmation_id": "abc",
                    },
                },
            }
        )

        payload = _tool_payload(response)
        self.assertTrue(response["result"]["isError"])
        self.assertEqual(payload["error_code"], "confirmation_mismatch")
        self.assertIn("confirm=true", payload["message"])

    def test_cancel_confirmed_false_returns_structured_confirmation_error(self) -> None:
        response = handle_request(
            {
                "jsonrpc": "2.0",
                "id": 25,
                "method": "tools/call",
                "params": {
                    "name": "ews_cancel_meeting_confirmed",
                    "arguments": {
                        "id": "event-1",
                        "changekey": "ck-1",
                        "confirm": False,
                        "confirmation_id": "abc",
                    },
                },
            }
        )

        payload = _tool_payload(response)
        self.assertTrue(response["result"]["isError"])
        self.assertEqual(payload["error_code"], "confirmation_mismatch")
        self.assertIn("confirm=true", payload["message"])


def _tool_payload(response: dict[str, object]) -> dict[str, object]:
    content = response["result"]["content"][0]["text"]
    return json.loads(content)


def _contains_key(value: object, key: str) -> bool:
    if isinstance(value, dict):
        return key in value or any(_contains_key(item, key) for item in value.values())
    if isinstance(value, list):
        return any(_contains_key(item, key) for item in value)
    return False


if __name__ == "__main__":
    unittest.main()
