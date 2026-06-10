from __future__ import annotations

from datetime import datetime, timedelta
import re
from typing import Any, Callable

from .config import EwsConfig
from .ews_client import EwsClient, default_window
from .meeting import MeetingRequest, build_meeting_preview
from .scheduler import TimeBlock, overlaps, parse_time_range, suggest_slots


ClientFactory = Callable[[], EwsClient]

KNOWN_ROOMS: dict[str, dict[str, Any]] = {
    "2-11": {"name": "2-11 Meeting Room", "email": "2-11MeetingRoom@linebank.com.tw"},
    "2-13": {"name": "2-13 Meeting Room", "email": "2-13MeetingRoom@linebank.com.tw"},
    "2-14": {"name": "2-14 Meeting Room", "email": "2-14MeetingRoom@linebank.com.tw"},
    "3-1": {
        "name": "3-1 Meeting Room(12P)",
        "email": "3-1MeetingRoom@linebank.com.tw",
        "capacity": 12,
    },
    "3-2": {
        "name": "3-2 Meeting Room(6P)",
        "email": "3-2MeetingRoom@linebank.com.tw",
        "capacity": 6,
    },
    "3-4": {
        "name": "3-4 Meeting Room(6P)",
        "email": "3-4MeetingRoom@linebank.com.tw",
        "capacity": 6,
    },
}


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


def ews_resolve_attendees(
    *,
    attendees: list[str],
    limit: int = 5,
    client_factory: ClientFactory = default_client_factory,
) -> list[dict[str, Any]]:
    return client_factory().resolve_attendees(attendees, limit=limit)


def default_room_options() -> list[dict[str, Any]]:
    return [dict(room) for room in KNOWN_ROOMS.values()]


def ews_get_free_busy(
    *,
    attendees: list[str],
    start: str,
    end: str,
    client_factory: ClientFactory = default_client_factory,
) -> list[dict[str, str]]:
    client = client_factory()
    attendee_emails = _attendee_emails(attendees, client)
    blocks = client.get_free_busy(
        attendee_emails,
        datetime.fromisoformat(start),
        datetime.fromisoformat(end),
    )
    return [_block_to_dict(block) for block in blocks]


def ews_suggest_slots(
    *,
    attendees: list[str],
    rooms: list[str] | None = None,
    require_room: bool = False,
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
    client = client_factory()
    attendee_emails = _attendee_emails(attendees, client)
    busy = client.get_free_busy(attendee_emails, window_start, window_end)
    room_infos = _room_infos(rooms or [], client, use_default=require_room)
    room_infos = _rooms_with_capacity(room_infos, attendee_count=len(attendee_emails))
    slot_limit = 1000 if room_infos else limit
    slots = suggest_slots(
        busy,
        window_start,
        window_end,
        timedelta(minutes=duration_minutes),
        workday_start=datetime.strptime(workday_start, "%H:%M").time(),
        workday_end=datetime.strptime(workday_end, "%H:%M").time(),
        excluded_windows=[parse_time_range(value) for value in avoid],
        limit=slot_limit,
    )
    if not room_infos:
        return [_block_to_dict(slot) for slot in slots]

    room_busy = client.get_free_busy_by_attendee(
        [room["email"] for room in room_infos],
        window_start,
        window_end,
    )
    suggestions: list[dict[str, Any]] = []
    for slot in slots:
        available_rooms = [
            room
            for room in room_infos
            if not any(overlaps(slot, busy_block) for busy_block in room_busy.get(room["email"], []))
        ]
        if available_rooms:
            payload = _block_to_dict(slot)
            payload["available_rooms"] = available_rooms
            payload["attendee_count"] = len(attendee_emails)
            suggestions.append(payload)
        if len(suggestions) >= limit:
            break
    return suggestions


def ews_create_meeting_preview(
    *,
    subject: str,
    attendees: list[str],
    rooms: list[str] | None = None,
    start: str,
    end: str,
    body: str = "",
    location: str = "",
    client_factory: ClientFactory = default_client_factory,
) -> dict[str, Any]:
    needs_client = _needs_resolution(attendees) or _rooms_need_resolution(rooms or [])
    client = client_factory() if needs_client else None
    if _needs_resolution(attendees):
        if client is None:
            client = client_factory()
        attendees = _attendee_emails(attendees, client)
    room_infos = _room_infos(rooms or [], client) if rooms else []
    room_emails = [room["email"] for room in room_infos]
    if not location and room_infos:
        location = room_infos[0]["name"]
    request = _meeting_request(subject, attendees, room_emails, start, end, body, location)
    return build_meeting_preview(request, confirmed=False)


def ews_create_meeting_confirmed(
    *,
    subject: str,
    attendees: list[str],
    rooms: list[str] | None = None,
    start: str,
    end: str,
    body: str = "",
    location: str = "",
    confirm: bool = False,
    client_factory: ClientFactory = default_client_factory,
) -> dict[str, Any]:
    if confirm is not True:
        raise PermissionError("Refusing to create meeting without confirm=true")

    client = client_factory()
    attendee_emails = _attendee_emails(attendees, client)
    room_infos = _room_infos(rooms or [], client)
    room_emails = [room["email"] for room in room_infos]
    if not location and room_infos:
        location = room_infos[0]["name"]
    request = _meeting_request(subject, attendee_emails, room_emails, start, end, body, location)
    preview = build_meeting_preview(request, confirmed=True)
    created = client.create_meeting(request)
    return {"preview": preview, "created": created}


def _meeting_request(
    subject: str,
    attendees: list[str],
    rooms: list[str],
    start: str,
    end: str,
    body: str,
    location: str,
) -> MeetingRequest:
    return MeetingRequest(
        subject=subject,
        attendees=attendees,
        rooms=rooms,
        start=datetime.fromisoformat(start),
        end=datetime.fromisoformat(end),
        body=body,
        location=location,
    )


def _block_to_dict(block: Any) -> dict[str, str]:
    return {"start": str(block.start), "end": str(block.end)}


def _needs_resolution(attendees: list[str]) -> bool:
    return any(not _looks_like_email(attendee.strip()) for attendee in attendees)


def _looks_like_email(value: str) -> bool:
    return re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", value) is not None


def _attendee_emails(attendees: list[str], client: EwsClient) -> list[str]:
    cleaned = [attendee.strip() for attendee in attendees]
    if not _needs_resolution(cleaned):
        return cleaned

    resolved = client.resolve_attendees(cleaned, limit=5)
    emails: list[str] = []
    for item in resolved:
        query = str(item.get("query", ""))
        status = str(item.get("status", ""))
        matches = item.get("matches", [])
        if not isinstance(matches, list):
            matches = []

        if status in {"email", "resolved"} and len(matches) == 1:
            email = str(matches[0].get("email", "")).strip()
            if _looks_like_email(email):
                emails.append(email)
                continue

        if status == "ambiguous":
            raise ValueError(
                f"Attendee '{query}' is ambiguous. Ask the user to choose one email: "
                f"{_format_matches(matches)}"
            )

        raise ValueError(f"Could not resolve attendee '{query}' to an email address.")

    return emails


def _room_infos(
    rooms: list[str],
    client: EwsClient | None,
    *,
    use_default: bool = False,
) -> list[dict[str, Any]]:
    if use_default and not rooms:
        return default_room_options()

    room_infos: list[dict[str, Any]] = []
    unresolved: list[str] = []
    for room in rooms:
        query = room.strip()
        if not query:
            continue
        known_room = KNOWN_ROOMS.get(_room_key(query))
        if known_room:
            room_infos.append(dict(known_room))
        elif _looks_like_email(query):
            room_infos.append({"name": query, "email": query, "capacity": _room_capacity(query)})
        else:
            unresolved.append(query)

    if unresolved:
        if client is None:
            raise ValueError(f"Could not resolve room without EWS directory lookup: {', '.join(unresolved)}")
        room_infos.extend(_resolved_room_infos(unresolved, client))
    return _dedupe_rooms(room_infos)


def _rooms_need_resolution(rooms: list[str]) -> bool:
    for room in rooms:
        query = room.strip()
        if not query:
            continue
        if KNOWN_ROOMS.get(_room_key(query)) or _looks_like_email(query):
            continue
        return True
    return False


def _room_key(value: str) -> str:
    match = re.search(r"\b(\d+-\d+)\b", value.strip())
    return match.group(1) if match else value.strip()


def _resolved_room_infos(rooms: list[str], client: EwsClient) -> list[dict[str, Any]]:
    resolved = client.resolve_attendees(rooms, limit=5)
    room_infos: list[dict[str, Any]] = []
    for item in resolved:
        query = str(item.get("query", ""))
        status = str(item.get("status", ""))
        matches = item.get("matches", [])
        if not isinstance(matches, list):
            matches = []
        if status in {"email", "resolved"} and len(matches) == 1:
            name = str(matches[0].get("name", "")).strip() or query
            email = str(matches[0].get("email", "")).strip()
            if _looks_like_email(email):
                room_infos.append({"name": name, "email": email, "capacity": _room_capacity(name)})
                continue
        if status == "ambiguous":
            raise ValueError(
                f"Room '{query}' is ambiguous. Ask the user to choose one room email: "
                f"{_format_matches(matches)}"
            )
        raise ValueError(f"Could not resolve room '{query}' to an email address.")
    return room_infos


def _dedupe_rooms(rooms: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for room in rooms:
        email = room["email"].lower()
        if email in seen:
            continue
        seen.add(email)
        deduped.append(room)
    return deduped


def _rooms_with_capacity(rooms: list[dict[str, Any]], *, attendee_count: int) -> list[dict[str, Any]]:
    filtered: list[dict[str, Any]] = []
    for room in rooms:
        capacity = room.get("capacity")
        if isinstance(capacity, int) and capacity < attendee_count:
            continue
        filtered.append(room)
    return filtered


def _room_capacity(name: str) -> int | None:
    match = re.search(r"\((\d+)P\)", name)
    return int(match.group(1)) if match else None


def _format_matches(matches: list[object]) -> str:
    labels: list[str] = []
    for match in matches:
        if not isinstance(match, dict):
            continue
        name = str(match.get("name", "")).strip()
        email = str(match.get("email", "")).strip()
        if name and email:
            labels.append(f"{name} <{email}>")
        elif email:
            labels.append(email)
    return ", ".join(labels) if labels else "no candidates returned"
