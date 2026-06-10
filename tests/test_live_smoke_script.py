from __future__ import annotations

from contextlib import redirect_stdout
import io
import json
import os
import unittest
from unittest.mock import patch

import scripts.live_smoke as live_smoke


class FakeTools:
    def __init__(self, *, ready: bool = True) -> None:
        self.ready = ready
        self.calls: list[tuple[str, dict[str, object]]] = []

    def ews_setup_check(self) -> dict[str, object]:
        self.calls.append(("setup", {}))
        if self.ready:
            return {"ready": True, "next_action": "ready"}
        return {"ready": False, "error_code": "credentials_missing", "required_action": "show_setup_command"}

    def ews_resolve_attendees(self, **kwargs: object) -> list[dict[str, object]]:
        self.calls.append(("resolve", kwargs))
        attendees = kwargs.get("attendees", [])
        return [
            {"query": attendee, "status": "email", "matches": [{"email": attendee, "name": attendee}]}
            for attendee in attendees
        ]

    def ews_get_free_busy(self, **kwargs: object) -> list[dict[str, object]]:
        self.calls.append(("free_busy", kwargs))
        return []

    def ews_suggest_slots(self, **kwargs: object) -> list[dict[str, object]]:
        self.calls.append(("suggest", kwargs))
        return [{"start": "2026-06-15T10:00:00+08:00", "end": "2026-06-15T10:30:00+08:00"}]

    def ews_create_meeting_preview(self, **kwargs: object) -> dict[str, object]:
        self.calls.append(("create_preview", kwargs))
        return {"confirmation_id": "create-id", "subject": kwargs["subject"]}

    def ews_create_meeting_confirmed(self, **kwargs: object) -> dict[str, object]:
        self.calls.append(("create_confirmed", kwargs))
        return {"created": {"id": "event-1", "changekey": "ck-1"}}

    def ews_verify_meeting(self, **kwargs: object) -> dict[str, object]:
        self.calls.append(("verify", kwargs))
        return {"status": "found", "id": kwargs["id"], "rooms": [{"response_status": "unknown"}]}

    def ews_cancel_meeting_preview(self, **kwargs: object) -> dict[str, object]:
        self.calls.append(("cancel_preview", kwargs))
        return {"confirmation_id": "cancel-id", "cancellation_target": {"id": kwargs["id"]}}

    def ews_cancel_meeting_confirmed(self, **kwargs: object) -> dict[str, object]:
        self.calls.append(("cancel_confirmed", kwargs))
        return {"cancelled": {"id": kwargs["id"], "cancelled": True}}


class LiveSmokeScriptTests(unittest.TestCase):
    def test_setup_command_reports_readiness(self) -> None:
        tools = FakeTools(ready=True)

        code, payload = _run(["setup"], tools)

        self.assertEqual(code, 0)
        self.assertEqual(payload["command"], "setup")
        self.assertTrue(payload["setup"]["ready"])
        self.assertEqual([name for name, _ in tools.calls], ["setup"])

    def test_setup_command_returns_nonzero_when_not_ready(self) -> None:
        tools = FakeTools(ready=False)

        code, payload = _run(["setup"], tools)

        self.assertEqual(code, 2)
        self.assertEqual(payload["setup"]["error_code"], "credentials_missing")

    def test_read_only_smoke_does_not_create_or_cancel(self) -> None:
        tools = FakeTools(ready=True)

        with _env():
            code, payload = _run(["read-only", "--attendee", "a@example.com"], tools)

        self.assertEqual(code, 0)
        self.assertEqual(payload["command"], "read-only")
        self.assertEqual(
            [name for name, _ in tools.calls],
            ["setup", "resolve", "free_busy", "suggest"],
        )

    def test_create_cancel_requires_confirm_live_before_setup_or_side_effects(self) -> None:
        tools = FakeTools(ready=True)

        code, payload = _run(["create-cancel", "--attendee", "a@example.com"], tools)

        self.assertEqual(code, 2)
        self.assertEqual(payload["error_code"], "live_confirmation_required")
        self.assertEqual(tools.calls, [])

    def test_create_cancel_confirm_live_runs_preview_create_verify_cancel(self) -> None:
        tools = FakeTools(ready=True)

        with _env():
            code, payload = _run(
                [
                    "create-cancel",
                    "--attendee",
                    "a@example.com",
                    "--confirm-live",
                    "--start",
                    "2026-06-15T10:00:00+08:00",
                    "--end",
                    "2026-06-15T10:30:00+08:00",
                    "--subject",
                    "live smoke",
                ],
                tools,
            )

        self.assertEqual(code, 0)
        self.assertEqual(payload["command"], "create-cancel")
        self.assertEqual(
            [name for name, _ in tools.calls],
            ["setup", "create_preview", "create_confirmed", "verify", "cancel_preview", "cancel_confirmed"],
        )
        create_call = dict(tools.calls[2][1])
        cancel_call = dict(tools.calls[-1][1])
        self.assertTrue(create_call["confirm"])
        self.assertEqual(create_call["confirmation_id"], "create-id")
        self.assertTrue(cancel_call["confirm"])
        self.assertEqual(cancel_call["confirmation_id"], "cancel-id")


def _run(argv: list[str], tools: FakeTools) -> tuple[int, object]:
    stdout = io.StringIO()
    with redirect_stdout(stdout):
        code = live_smoke.main(argv, tools=tools)
    return code, json.loads(stdout.getvalue())


def _env() -> object:
    return patch.dict(
        os.environ,
        {
            "EWS_ENDPOINT": "https://ews.example.com/EWS/Exchange.asmx",
            "EWS_EMAIL": "organizer@example.com",
            "EWS_USERNAME": "organizer",
            "EWS_PASSWORD": "secret",
            "EWS_TIMEZONE": "Asia/Taipei",
        },
        clear=False,
    )


if __name__ == "__main__":
    unittest.main()
