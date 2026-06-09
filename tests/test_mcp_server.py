from __future__ import annotations

import json
import unittest

from ews_meeting_agent.mcp_server import handle_request


class McpServerTests(unittest.TestCase):
    def test_lists_tools(self) -> None:
        response = handle_request({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})

        self.assertEqual(response["id"], 1)
        tool_names = [tool["name"] for tool in response["result"]["tools"]]
        self.assertIn("ews_suggest_slots", tool_names)
        self.assertIn("ews_create_meeting_preview", tool_names)
        self.assertIn("ews_create_meeting_confirmed", tool_names)

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


def _tool_payload(response: dict[str, object]) -> dict[str, object]:
    content = response["result"]["content"][0]["text"]
    return json.loads(content)


if __name__ == "__main__":
    unittest.main()

