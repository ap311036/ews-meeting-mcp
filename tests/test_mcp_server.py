from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from ews_meeting_agent.mcp_server import handle_request


class McpServerTests(unittest.TestCase):
    def test_lists_tools(self) -> None:
        response = handle_request({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})

        self.assertEqual(response["id"], 1)
        tool_names = [tool["name"] for tool in response["result"]["tools"]]
        self.assertIn("ews_keychain_status", tool_names)
        self.assertIn("ews_resolve_attendees", tool_names)
        self.assertIn("ews_suggest_slots", tool_names)
        self.assertIn("ews_create_meeting_preview", tool_names)
        self.assertIn("ews_create_meeting_confirmed", tool_names)

    def test_keychain_status_tool_has_empty_schema(self) -> None:
        response = handle_request({"jsonrpc": "2.0", "id": 10, "method": "tools/list"})

        tools = response["result"]["tools"]
        tool = next(item for item in tools if item["name"] == "ews_keychain_status")

        self.assertIn("without revealing the password", tool["description"])
        self.assertEqual(tool["inputSchema"], {"type": "object", "properties": {}, "additionalProperties": False})

    def test_keychain_status_tool_returns_status_payload(self) -> None:
        with patch("ews_meeting_agent.agent_tools.keychain_status") as status:
            status.return_value = {
                "configured": False,
                "source": "missing",
                "service": "ews-meeting-mcp",
                "account": "bk00325",
                "setup_command": "security add-generic-password ...",
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

    def test_suggest_slots_tool_schema_accepts_rooms(self) -> None:
        response = handle_request({"jsonrpc": "2.0", "id": 12, "method": "tools/list"})

        tools = response["result"]["tools"]
        tool = next(item for item in tools if item["name"] == "ews_suggest_slots")

        self.assertIn("rooms", tool["inputSchema"]["properties"])
        self.assertIn("require_room", tool["inputSchema"]["properties"])

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
                        "attendees": ["eason.lin@linebank.com.tw"],
                        "start": "2026-06-15T11:00:00+08:00",
                        "end": "2026-06-15T11:30:00+08:00",
                    },
                },
            }
        )

        payload = _tool_payload(response)
        self.assertEqual(payload["action"], "dry_run")
        self.assertFalse(payload["will_send_invites"])

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
                        "attendees": ["eason.lin@linebank.com.tw"],
                        "start": "2026-06-15T11:00:00+08:00",
                        "end": "2026-06-15T11:30:00+08:00",
                        "confirm": False,
                    },
                },
            }
        )

        self.assertTrue(response["result"]["isError"])
        self.assertIn("confirm=true", response["result"]["content"][0]["text"])

    def test_tool_schemas_avoid_const_keyword_for_client_compatibility(self) -> None:
        response = handle_request({"jsonrpc": "2.0", "id": 4, "method": "tools/list"})

        schemas = [tool["inputSchema"] for tool in response["result"]["tools"]]
        self.assertFalse(any(_contains_key(schema, "const") for schema in schemas))


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
