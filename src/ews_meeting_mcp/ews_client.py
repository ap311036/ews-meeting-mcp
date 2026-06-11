from __future__ import annotations

from datetime import datetime, timedelta
import re
from typing import Any
from zoneinfo import ZoneInfo

from .config import EwsConfig
from .datetime_utils import parse_iso_datetime
from .errors import EwsToolError
from .meeting import MeetingRequest, render_body_for_format
from .scheduler import TimeBlock


class EwsClient:
    def __init__(self, config: EwsConfig) -> None:
        self.config = config
        self._account = None

    @property
    def account(self) -> Any:
        if self._account is None:
            self._account = self._build_account()
        return self._account

    def probe(self) -> dict[str, str]:
        account = self.account
        return {
            "primary_smtp_address": str(account.primary_smtp_address),
            "root_folder": str(account.root),
        }

    def list_calendar(self, start: datetime, end: datetime, *, limit: int = 20) -> list[dict[str, str]]:
        start = self._to_ews_datetime(start)
        end = self._to_ews_datetime(end)
        items = (
            self.account.calendar.view(start=start, end=end)
            .only("subject", "start", "end", "location")
            .order_by("start")
        )
        return [
            {
                "subject": str(item.subject or ""),
                "start": str(item.start),
                "end": str(item.end),
                "location": str(item.location or ""),
            }
            for item in items[:limit]
        ]

    def find_calendar_events(
        self,
        start: datetime,
        end: datetime,
        *,
        subject_contains: str | None = None,
        location_contains: str | None = None,
        organizer_email: str | None = None,
        attendee_email: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        start = self._to_ews_datetime(start)
        end = self._to_ews_datetime(end)
        items = (
            self.account.calendar.view(start=start, end=end)
            .only(
                "id",
                "changekey",
                "uid",
                "subject",
                "start",
                "end",
                "location",
                "body",
                "organizer",
                "required_attendees",
                "resources",
                "is_meeting",
                "is_cancelled",
                "recurrence",
                "type",
            )
            .order_by("start")
        )
        matches: list[dict[str, Any]] = []
        match_limit = max(1, limit)
        for item in items:
            event = _calendar_event_to_dict(item)
            if not _event_matches_filters(
                event,
                subject_contains=subject_contains,
                location_contains=location_contains,
                organizer_email=organizer_email,
                attendee_email=attendee_email,
            ):
                continue
            matches.append(event)
            if len(matches) >= match_limit:
                break
        return matches

    def get_free_busy(self, attendees: list[str], start: datetime, end: datetime) -> list[TimeBlock]:
        by_attendee = self.get_free_busy_by_attendee(attendees, start, end)
        busy: list[TimeBlock] = []
        for blocks in by_attendee.values():
            busy.extend(blocks)
        return busy

    def get_free_busy_by_attendee(
        self,
        attendees: list[str],
        start: datetime,
        end: datetime,
    ) -> dict[str, list[TimeBlock]]:
        start = self._to_ews_datetime(start)
        end = self._to_ews_datetime(end)
        account_tuples = [(email, "Required", False) for email in attendees]
        free_busy_entries = self.account.protocol.get_free_busy_info(
            accounts=account_tuples,
            start=start,
            end=end,
            merged_free_busy_interval=15,
        )

        busy_by_attendee: dict[str, list[TimeBlock]] = {email: [] for email in attendees}
        for email, entry in zip(attendees, free_busy_entries):
            for event in getattr(entry, "calendar_events", []) or []:
                status = str(getattr(event, "busy_type", "")).lower()
                if status in {"busy", "tentative", "oof", "working_elsewhere"}:
                    busy_by_attendee[email].append(TimeBlock(event.start, event.end))
        return busy_by_attendee

    def resolve_attendees(self, attendees: list[str], *, limit: int = 5) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        match_limit = max(1, limit)

        for attendee in attendees:
            query = attendee.strip()
            if _looks_like_email(query):
                results.append(
                    {
                        "query": query,
                        "status": "email",
                        "matches": [{"name": query, "email": query, "source": "input"}],
                    }
                )
                continue

            matches = self._resolve_name(query)
            status = _resolution_status(len(matches))
            results.append(
                {
                    "query": query,
                    "status": status,
                    "matches": matches[:match_limit],
                }
            )

        return results

    def discover_rooms(self, *, room_list: str | None = None) -> dict[str, Any]:
        protocol = self.account.protocol
        try:
            _ensure_protocol_version(protocol)
            room_list_items = list(protocol.get_roomlists())
        except Exception as exc:
            raise RuntimeError(f"Exchange room lists are unavailable: {exc}") from exc

        normalized_room_lists = [_room_list_to_dict(item) for item in room_list_items]
        selected_lists: list[dict[str, str]] = []
        for normalized in normalized_room_lists:
            if not normalized["email"]:
                continue
            if room_list and not _matches_room_list(normalized, room_list):
                continue
            selected_lists.append(normalized)

        rooms: list[dict[str, Any]] = []
        for normalized in selected_lists:
            try:
                exchange_rooms = protocol.get_rooms(normalized["email"])
            except Exception as exc:
                raise RuntimeError(
                    f"Exchange rooms are unavailable for room list {normalized.get('name') or normalized.get('email')}: {exc}"
                ) from exc
            for room in exchange_rooms:
                room_info = _room_to_dict(room, room_list=normalized)
                if room_info["email"]:
                    rooms.append(room_info)

        return {
            "room_lists": normalized_room_lists,
            "rooms": _dedupe_room_infos(rooms),
        }

    def create_meeting(self, request: MeetingRequest) -> dict[str, str]:
        request.validate()
        try:
            from exchangelib import CalendarItem
        except ImportError as exc:
            raise RuntimeError(
                "Missing dependency 'exchangelib'. Run: pip install -r requirements.txt"
            ) from exc
        try:
            from exchangelib.items import SEND_TO_ALL_AND_SAVE_COPY
        except ImportError:
            SEND_TO_ALL_AND_SAVE_COPY = "SendToAllAndSaveCopy"

        item = CalendarItem(
            account=self.account,
            folder=self.account.calendar,
            subject=request.subject,
            body=_ews_body(render_body_for_format(request.body, request.body_format), request.body_format),
            start=self._to_ews_datetime(request.start),
            end=self._to_ews_datetime(request.end),
            location=request.location,
            required_attendees=request.attendees,
            resources=request.rooms or [],
        )
        item.save(send_meeting_invitations=SEND_TO_ALL_AND_SAVE_COPY)

        return {
            "id": str(getattr(item, "id", "") or ""),
            "changekey": str(getattr(item, "changekey", "") or ""),
            "subject": str(item.subject or ""),
            "start": str(item.start),
            "end": str(item.end),
        }

    def get_calendar_event(self, item_id: str, changekey: str) -> dict[str, Any]:
        item = self._get_calendar_item(item_id, changekey)
        return _calendar_event_to_dict(item)

    def verify_meeting(self, item_id: str, changekey: str | None = None) -> dict[str, Any]:
        item = self._get_calendar_item(item_id, changekey)
        event = _calendar_event_to_dict(item)
        rooms = [_participant_to_dict(resource) for resource in getattr(item, "resources", []) or []]
        return {
            "status": "found",
            "id": event["id"],
            "changekey": event["changekey"],
            "uid": event["uid"],
            "subject": event["subject"],
            "start": event["start"],
            "end": event["end"],
            "location": event["location"],
            "organizer": event["organizer"],
            "organizer_item": {
                "is_meeting": event["is_meeting"],
                "is_cancelled": event["is_cancelled"],
                "is_recurring": event["is_recurring"],
                "type": event["type"],
                "is_organizer": event.get("is_organizer"),
            },
            "attendees": [
                _participant_to_dict(attendee) for attendee in getattr(item, "required_attendees", []) or []
            ],
            "rooms": rooms,
            "resources": rooms,
        }

    def cancel_meeting(
        self,
        item_id: str,
        changekey: str,
        *,
        send_meeting_cancellations: bool,
    ) -> dict[str, Any]:
        item = self._get_calendar_item(item_id, changekey)
        target = _calendar_event_to_dict(item)
        item.move_to_trash(
            send_meeting_cancellations=_send_disposition(send_meeting_cancellations),
        )
        return {**target, "cancelled": True}

    def update_meeting(
        self,
        item_id: str,
        changekey: str,
        updates: dict[str, Any],
        *,
        update_fields: list[str],
        send_meeting_invitations: bool,
        body_format: str = "html",
    ) -> dict[str, Any]:
        item = self._get_calendar_item(item_id, changekey)
        for field in update_fields:
            value = updates[field]
            if field in {"start", "end"}:
                value = self._to_ews_datetime(_coerce_datetime(value))
            elif field == "body":
                value = _ews_body(render_body_for_format(str(value), body_format), body_format)
            setattr(item, field, value)
        item.save(
            update_fields=update_fields,
            send_meeting_invitations=_send_disposition(send_meeting_invitations),
        )
        return _calendar_event_to_dict(item)

    def _build_account(self) -> Any:
        try:
            from exchangelib import Account, Configuration, Credentials, DELEGATE
            from exchangelib.protocol import BaseProtocol, NoVerifyHTTPAdapter
            from exchangelib import BASIC, NTLM
            from exchangelib.winzone import MS_TIMEZONE_TO_IANA_MAP
        except ImportError as exc:
            raise RuntimeError(
                "Missing dependency 'exchangelib'. Run: pip install -r requirements.txt"
            ) from exc

        MS_TIMEZONE_TO_IANA_MAP.setdefault("", self.config.timezone)

        auth_type = {"BASIC": BASIC, "NTLM": NTLM}.get(self.config.auth_type)
        if auth_type is None:
            raise RuntimeError("EWS_AUTH_TYPE must be BASIC or NTLM for this PoC")

        credentials = Credentials(
            username=self.config.username,
            password=self.config.password,
        )
        configuration = Configuration(
            service_endpoint=self.config.endpoint,
            credentials=credentials,
            auth_type=auth_type,
        )

        # Keep TLS verification enabled by default. If the company uses an
        # internal CA, install that CA locally instead of disabling validation.
        if False:
            BaseProtocol.HTTP_ADAPTER_CLS = NoVerifyHTTPAdapter

        return Account(
            primary_smtp_address=self.config.email,
            config=configuration,
            autodiscover=False,
            access_type=DELEGATE,
        )

    def _resolve_name(self, query: str) -> list[dict[str, str]]:
        if not query:
            return []

        protocol = self.account.protocol
        _ensure_protocol_version(protocol)
        resolutions = protocol.resolve_names(
            [query],
            return_full_contact_data=True,
        )
        matches: list[dict[str, str]] = []
        seen_emails: set[str] = set()
        for resolution in resolutions:
            match = _resolution_to_match(resolution)
            email = match.get("email", "").lower()
            if not email or email in seen_emails:
                continue
            seen_emails.add(email)
            matches.append(match)
        return matches

    def _get_calendar_item(self, item_id: str, changekey: str | None = None) -> Any:
        try:
            if changekey:
                return self.account.calendar.get(id=item_id, changekey=changekey)
            return self.account.calendar.get(id=item_id)
        except Exception as exc:
            error_name = exc.__class__.__name__.lower()
            message = str(exc)
            lowered = message.lower()
            if "changekey" in error_name or "changekey" in lowered or "change key" in lowered or "stale" in lowered:
                raise EwsToolError(
                    "stale_meeting",
                    "The meeting changekey is stale. Search for the event again and retry with the latest changekey.",
                    id=item_id,
                    changekey=changekey,
                ) from exc
            if "doesnotexist" in error_name or "itemnotfound" in error_name or "not found" in lowered:
                raise EwsToolError(
                    "meeting_not_found",
                    "The meeting was not found with the provided id and changekey.",
                    id=item_id,
                    changekey=changekey,
                ) from exc
            raise EwsToolError(
                "ews_meeting_lookup_failed",
                "Exchange could not look up the meeting. Check EWS connectivity and try again.",
                id=item_id,
                changekey=changekey,
                detail=message,
            ) from exc

    def _to_ews_datetime(self, value: datetime) -> Any:
        try:
            from exchangelib import EWSDateTime, EWSTimeZone
        except ImportError as exc:
            raise RuntimeError(
                "Missing dependency 'exchangelib'. Run: pip install -r requirements.txt"
            ) from exc

        target_tz = ZoneInfo(self.config.timezone)
        if value.tzinfo is None:
            local_value = value
        else:
            local_value = value.astimezone(target_tz).replace(tzinfo=None)

        ews_timezone = EWSTimeZone(self.config.timezone)
        return EWSDateTime(
            local_value.year,
            local_value.month,
            local_value.day,
            local_value.hour,
            local_value.minute,
            local_value.second,
            local_value.microsecond,
            tzinfo=ews_timezone,
        )


def _looks_like_email(value: str) -> bool:
    return re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", value) is not None


def _resolution_status(match_count: int) -> str:
    if match_count == 0:
        return "not_found"
    if match_count == 1:
        return "resolved"
    return "ambiguous"


def _calendar_event_to_dict(item: Any) -> dict[str, Any]:
    recurrence = getattr(item, "recurrence", None)
    event_type = getattr(item, "type", "")
    event = {
        "id": str(getattr(item, "id", "") or ""),
        "changekey": str(getattr(item, "changekey", "") or ""),
        "uid": str(getattr(item, "uid", "") or ""),
        "subject": str(getattr(item, "subject", "") or ""),
        "start": _event_datetime_value(getattr(item, "start", "")),
        "end": _event_datetime_value(getattr(item, "end", "")),
        "location": str(getattr(item, "location", "") or ""),
        "body": str(getattr(item, "body", "") or ""),
        "organizer": _mailbox_to_dict(getattr(item, "organizer", None)),
        "required_attendees": [_mailbox_to_dict(attendee) for attendee in getattr(item, "required_attendees", []) or []],
        "resources": [_mailbox_to_dict(resource) for resource in getattr(item, "resources", []) or []],
        "is_meeting": bool(getattr(item, "is_meeting", False)),
        "is_cancelled": bool(getattr(item, "is_cancelled", False)),
        "is_recurring": recurrence is not None,
        "recurrence": str(recurrence or ""),
        "type": str(event_type or ""),
    }
    if hasattr(item, "is_organizer"):
        event["is_organizer"] = bool(getattr(item, "is_organizer"))
    return event


def _event_datetime_value(value: Any) -> str:
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value or "")


def _mailbox_to_dict(value: Any) -> dict[str, str]:
    if value is None:
        return {"name": "", "email": ""}
    name = _mailbox_name(value)
    email = _mailbox_email(value)
    return {"name": name or email, "email": email}


def _participant_to_dict(value: Any) -> dict[str, str]:
    result = _mailbox_to_dict(value)
    result["response_status"] = _response_status(value)
    last_response = _event_datetime_value(getattr(value, "last_response_time", ""))
    if last_response:
        result["last_response_time"] = last_response
    return result


def _response_status(value: Any) -> str:
    for attr in ["response_type", "response_status", "response", "status"]:
        candidate = getattr(value, attr, None)
        if candidate:
            return str(candidate).lower()
    return "unknown"


def _event_matches_filters(
    event: dict[str, Any],
    *,
    subject_contains: str | None,
    location_contains: str | None,
    organizer_email: str | None,
    attendee_email: str | None,
) -> bool:
    if subject_contains and subject_contains.lower() not in str(event.get("subject", "")).lower():
        return False
    if location_contains and location_contains.lower() not in str(event.get("location", "")).lower():
        return False
    if organizer_email:
        organizer = event.get("organizer")
        organizer_value = organizer.get("email", "") if isinstance(organizer, dict) else ""
        if organizer_email.lower() != str(organizer_value).lower():
            return False
    if attendee_email:
        attendee = attendee_email.lower()
        attendee_values = [
            str(person.get("email", "")).lower()
            for person in event.get("required_attendees", [])
            if isinstance(person, dict)
        ]
        resource_values = [
            str(person.get("email", "")).lower()
            for person in event.get("resources", [])
            if isinstance(person, dict)
        ]
        if attendee not in attendee_values and attendee not in resource_values:
            return False
    return True


def _coerce_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    return parse_iso_datetime(str(value))


def _send_disposition(enabled: bool) -> str:
    if not enabled:
        return "SendToNone"
    try:
        from exchangelib.items import SEND_TO_ALL_AND_SAVE_COPY
    except ImportError:
        SEND_TO_ALL_AND_SAVE_COPY = "SendToAllAndSaveCopy"
    return SEND_TO_ALL_AND_SAVE_COPY


def _ews_body(body: str, body_format: str) -> object:
    if body_format == "html":
        try:
            from exchangelib import HTMLBody
        except ImportError:
            return body
        return HTMLBody(body)
    return body


def _resolution_to_match(resolution: Any) -> dict[str, str]:
    mailbox = resolution[0] if isinstance(resolution, tuple) else resolution
    contact = resolution[1] if isinstance(resolution, tuple) and len(resolution) > 1 else None

    name = (
        getattr(mailbox, "name", None)
        or getattr(contact, "display_name", None)
        or getattr(contact, "complete_name", None)
        or ""
    )
    email = (
        getattr(mailbox, "email_address", None)
        or getattr(contact, "email_address", None)
        or _first_contact_email(contact)
        or ""
    )
    source = "directory"
    return {
        "name": str(name or email),
        "email": str(email),
        "source": source,
    }


def _room_list_to_dict(room_list: Any) -> dict[str, str]:
    name = _mailbox_name(room_list)
    email = _mailbox_email(room_list)
    return {"name": name or email, "email": email}


def _room_to_dict(room: Any, *, room_list: dict[str, str]) -> dict[str, Any]:
    name = _mailbox_name(room)
    email = _mailbox_email(room)
    return {
        "name": name or email,
        "email": email,
        "capacity": _room_capacity(name),
        "room_list": room_list.get("name") or room_list.get("email") or "",
        "source": "exchange",
    }


def _mailbox_name(value: Any) -> str:
    if isinstance(value, str):
        return value
    name = str(
        getattr(value, "name", None)
        or getattr(value, "display_name", None)
        or getattr(value, "displayName", None)
        or ""
    )
    if name:
        return name
    mailbox = getattr(value, "mailbox", None)
    if mailbox is not None:
        nested = _mailbox_name(mailbox)
        if nested:
            return nested
    return ""


def _mailbox_email(value: Any) -> str:
    if isinstance(value, str):
        return value if _looks_like_email(value) else ""

    for attr in ["email_address", "email", "smtp_address", "address"]:
        candidate = getattr(value, attr, None)
        if isinstance(candidate, str) and candidate:
            return candidate
        if candidate is not None and not isinstance(candidate, (int, float, bool)):
            nested = _mailbox_email(candidate)
            if nested:
                return nested

    mailbox = getattr(value, "mailbox", None)
    if mailbox is not None:
        nested = _mailbox_email(mailbox)
        if nested:
            return nested
    return ""


def _matches_room_list(room_list: dict[str, str], query: str) -> bool:
    lowered = query.strip().lower()
    if not lowered:
        return True
    return lowered in str(room_list.get("name", "")).lower() or lowered in str(room_list.get("email", "")).lower()


def _dedupe_room_infos(rooms: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for room in rooms:
        email = str(room.get("email", "")).lower()
        if not email or email in seen:
            continue
        seen.add(email)
        deduped.append(room)
    return deduped


def _room_capacity(name: str) -> int | None:
    match = re.search(r"\(\s*(\d+)\s*p\s*\)", name, flags=re.IGNORECASE)
    return int(match.group(1)) if match else None


def _first_contact_email(contact: Any) -> str:
    if contact is None:
        return ""

    email_addresses = getattr(contact, "email_addresses", None)
    if isinstance(email_addresses, dict):
        for value in email_addresses.values():
            if value:
                return str(value)
    if isinstance(email_addresses, (list, tuple)):
        for value in email_addresses:
            if value:
                return str(value)
    return ""


def _ensure_protocol_version(protocol: Any) -> None:
    config = getattr(protocol, "config", None)
    if getattr(config, "version", None) is not None:
        return

    version = getattr(protocol, "version", None)
    if config is not None and getattr(config, "version", None) is None and version is not None:
        config.version = version


def default_window(days: int, timezone_name: str = "Asia/Taipei") -> tuple[datetime, datetime]:
    now = datetime.now(ZoneInfo(timezone_name))
    return now, now + timedelta(days=days)
