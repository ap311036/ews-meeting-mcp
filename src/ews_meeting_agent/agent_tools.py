from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Callable

from .config import EwsConfig
from .ews_client import EwsClient, default_window
from .meeting import MeetingRequest, build_meeting_preview
from .scheduler import parse_time_range, suggest_slots


ClientFactory = Callable[[], EwsClient]


def default_client_factory() -> EwsClient:
    return EwsClient(EwsConfig.from_env())


def ews_probe(client_factory: ClientFactory = default_client_factory) -> dict[str, str]:
    return client_factory().probe()


def ews_list_calendar(
    *,
    days: int = 7,
    client_factory: ClientFactory = default_client_factory,
) -> list[dict[str, str]]:
    client = client_factory()
    start, end = default_window(days, client.config.timezone)
    return client.list_calendar(start, end)


def ews_get_free_busy(
    *,
    attendees: list[str],
    start: str,
    end: str,
    client_factory: ClientFactory = default_client_factory,
) -> list[dict[str, str]]:
    blocks = client_factory().get_free_busy(
        attendees,
        datetime.fromisoformat(start),
        datetime.fromisoformat(end),
    )
    return [_block_to_dict(block) for block in blocks]


def ews_suggest_slots(
    *,
    attendees: list[str],
    start: str,
    end: str,
    duration_minutes: int = 30,
    limit: int = 5,
    workday_start: str = "10:00",
    workday_end: str = "18:00",
    avoid: list[str] | None = None,
    client_factory: ClientFactory = default_client_factory,
) -> list[dict[str, str]]:
    avoid = avoid or ["12:00-14:00"]
    window_start = datetime.fromisoformat(start)
    window_end = datetime.fromisoformat(end)
    busy = client_factory().get_free_busy(attendees, window_start, window_end)
    slots = suggest_slots(
        busy,
        window_start,
        window_end,
        timedelta(minutes=duration_minutes),
        workday_start=datetime.strptime(workday_start, "%H:%M").time(),
        workday_end=datetime.strptime(workday_end, "%H:%M").time(),
        excluded_windows=[parse_time_range(value) for value in avoid],
        limit=limit,
    )
    return [_block_to_dict(slot) for slot in slots]


def ews_create_meeting_preview(
    *,
    subject: str,
    attendees: list[str],
    start: str,
    end: str,
    body: str = "",
    location: str = "",
) -> dict[str, Any]:
    request = _meeting_request(subject, attendees, start, end, body, location)
    return build_meeting_preview(request, confirmed=False)


def ews_create_meeting_confirmed(
    *,
    subject: str,
    attendees: list[str],
    start: str,
    end: str,
    body: str = "",
    location: str = "",
    confirm: bool = False,
    client_factory: ClientFactory = default_client_factory,
) -> dict[str, Any]:
    if confirm is not True:
        raise PermissionError("Refusing to create meeting without confirm=true")

    request = _meeting_request(subject, attendees, start, end, body, location)
    preview = build_meeting_preview(request, confirmed=True)
    created = client_factory().create_meeting(request)
    return {"preview": preview, "created": created}


def _meeting_request(
    subject: str,
    attendees: list[str],
    start: str,
    end: str,
    body: str,
    location: str,
) -> MeetingRequest:
    return MeetingRequest(
        subject=subject,
        attendees=attendees,
        start=datetime.fromisoformat(start),
        end=datetime.fromisoformat(end),
        body=body,
        location=location,
    )


def _block_to_dict(block: Any) -> dict[str, str]:
    return {"start": str(block.start), "end": str(block.end)}

