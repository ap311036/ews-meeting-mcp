from __future__ import annotations

import unittest

from ews_meeting_agent import agent_tools


class FakeClient:
    def __init__(self) -> None:
        self.calls: list[tuple[list[str], int]] = []

    def resolve_attendees(self, attendees: list[str], *, limit: int = 5) -> list[dict[str, object]]:
        self.calls.append((attendees, limit))
        return [
            {
                "query": "王小明",
                "status": "resolved",
                "matches": [{"name": "王小明", "email": "ming.wang@example.com"}],
            }
        ]


class AgentToolTests(unittest.TestCase):
    def test_resolve_attendees_delegates_to_client(self) -> None:
        client = FakeClient()

        result = agent_tools.ews_resolve_attendees(
            attendees=["王小明"],
            limit=3,
            client_factory=lambda: client,
        )

        self.assertEqual(client.calls, [(["王小明"], 3)])
        self.assertEqual(result[0]["matches"][0]["email"], "ming.wang@example.com")


if __name__ == "__main__":
    unittest.main()
