from __future__ import annotations

from dataclasses import dataclass
import unittest

from ews_meeting_agent.config import EwsConfig
from ews_meeting_agent.ews_client import EwsClient


@dataclass
class FakeMailbox:
    name: str
    email_address: str


class FakeProtocol:
    def __init__(self) -> None:
        self.calls: list[tuple[list[str], bool]] = []

    def resolve_names(self, names: list[str], *, return_full_contact_data: bool) -> list[FakeMailbox]:
        self.calls.append((names, return_full_contact_data))
        if names == ["王小明"]:
            return [FakeMailbox(name="王小明", email_address="ming.wang@example.com")]
        if names == ["Alex"]:
            return [
                FakeMailbox(name="Alex Chen", email_address="alex.chen@example.com"),
                FakeMailbox(name="Alex Lin", email_address="alex.lin@example.com"),
            ]
        return []


class FakeAccount:
    def __init__(self) -> None:
        self.protocol = FakeProtocol()


class EwsClientResolveTests(unittest.TestCase):
    def test_resolve_attendees_returns_statuses_and_matches(self) -> None:
        client = EwsClient(
            EwsConfig(
                endpoint="https://ews.example.com/EWS/Exchange.asmx",
                email="organizer@example.com",
                username="organizer",
                password="secret",
            )
        )
        account = FakeAccount()
        client._account = account

        result = client.resolve_attendees(
            ["王小明", "Alex", "nobody", "direct.person@example.com"],
            limit=1,
        )

        self.assertEqual(
            [(item["query"], item["status"]) for item in result],
            [
                ("王小明", "resolved"),
                ("Alex", "ambiguous"),
                ("nobody", "not_found"),
                ("direct.person@example.com", "email"),
            ],
        )
        self.assertEqual(result[0]["matches"][0]["email"], "ming.wang@example.com")
        self.assertEqual(len(result[1]["matches"]), 1)
        self.assertEqual(result[3]["matches"][0]["email"], "direct.person@example.com")
        self.assertEqual(
            account.protocol.calls,
            [
                (["王小明"], True),
                (["Alex"], True),
                (["nobody"], True),
            ],
        )


if __name__ == "__main__":
    unittest.main()
