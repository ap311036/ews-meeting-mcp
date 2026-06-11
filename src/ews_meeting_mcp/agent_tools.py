from __future__ import annotations

from datetime import datetime, timedelta
import re
from typing import Any, Callable

from .audit import read_audit_log, record_lifecycle_audit
from .confirmations import ConfirmationLedger, confirmation_id
from .config import EwsConfig, keychain_status, setup_check
from .datetime_utils import parse_iso_datetime
from .errors import EwsToolError
from .ews_client import EwsClient, default_window
from .meeting import MeetingRequest, build_meeting_preview
from .policy import load_policy
from .scheduler import TimeBlock, overlaps, parse_time_range, suggest_slots


ClientFactory = Callable[[], EwsClient]

def default_client_factory() -> EwsClient:
    return EwsClient(EwsConfig.from_env())


def ews_keychain_status() -> dict[str, object]:
    return keychain_status()


def ews_setup_check() -> dict[str, Any]:
    try:
        load_policy()
    except EwsToolError as error:
        payload = dict(error.payload)
        payload.setdefault("ready", False)
        payload.setdefault("next_action", payload.get("required_action", "fix_policy_file"))
        return payload
    return setup_check()


def ews_get_audit_log(
    *,
    limit: int = 50,
    action: str | None = None,
    status: str | None = None,
) -> list[dict[str, Any]]:
    return read_audit_log(limit=limit, action=action, status=status)


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


def ews_find_calendar_events(
    *,
    start: str,
    end: str,
    subject_contains: str | None = None,
    location_contains: str | None = None,
    organizer_email: str | None = None,
    attendee_email: str | None = None,
    limit: int = 20,
    client_factory: ClientFactory = default_client_factory,
) -> list[dict[str, Any]]:
    client = client_factory()
    return client.find_calendar_events(
        parse_iso_datetime(start),
        parse_iso_datetime(end),
        subject_contains=subject_contains,
        location_contains=location_contains,
        organizer_email=organizer_email,
        attendee_email=attendee_email,
        limit=max(1, limit),
    )


def ews_verify_meeting(
    *,
    id: str,
    changekey: str | None = None,
    client_factory: ClientFactory = default_client_factory,
) -> dict[str, Any]:
    client = client_factory()
    return client.verify_meeting(id, changekey)


def ews_resolve_attendees(
    *,
    attendees: list[str],
    limit: int = 5,
    client_factory: ClientFactory = default_client_factory,
) -> list[dict[str, Any]]:
    return client_factory().resolve_attendees(attendees, limit=limit)


def default_room_options() -> list[dict[str, Any]]:
    return [dict(room) for room in load_policy().rooms]


def ews_list_rooms(
    attendee_count: int | None = None,
    query: str | None = None,
    room_list: str | None = None,
    source: str = "auto",
    limit: int = 100,
    client_factory: ClientFactory = default_client_factory,
) -> dict[str, Any]:
    requested_source = _room_source(source)
    option_limit = max(1, limit)

    if requested_source == "static":
        rooms = _filtered_rooms(default_room_options(), attendee_count=attendee_count, query=query, limit=option_limit)
        return _room_directory_payload(source="static", options=rooms)

    try:
        exchange_directory = _exchange_room_directory(
            client_factory=client_factory,
            attendee_count=attendee_count,
            query=query,
            room_list=room_list,
            limit=option_limit,
        )
    except EwsToolError as error:
        if requested_source == "auto" and _room_discovery_error_is_recoverable(error):
            rooms = _filtered_rooms(default_room_options(), attendee_count=attendee_count, query=query, limit=option_limit)
            return _room_directory_payload(source="static", options=rooms)
        raise

    if requested_source == "auto" and not exchange_directory.get("options"):
        rooms = _filtered_rooms(default_room_options(), attendee_count=attendee_count, query=query, limit=option_limit)
        return _room_directory_payload(source="static", options=rooms)

    return exchange_directory


def _room_source(source: str) -> str:
    normalized = (source or "auto").strip().lower()
    if normalized not in {"auto", "exchange", "static"}:
        raise ValueError("source must be one of: auto, exchange, static")
    return normalized


def _exchange_room_directory(
    *,
    client_factory: ClientFactory,
    attendee_count: int | None,
    query: str | None,
    room_list: str | None,
    limit: int,
) -> dict[str, Any]:
    try:
        client = client_factory()
        directory = client.discover_rooms(room_list=room_list.strip() if room_list else None)
    except EwsToolError:
        raise
    except Exception as exc:
        raise EwsToolError(
            "exchange_room_directory_unavailable",
            f"Exchange room directory is unavailable: {exc}",
            required_action="use_static_rooms",
            next_action="use_static_rooms",
            recoverable=True,
            user_message=(
                "Exchange room discovery is unavailable right now. "
                "Use configured fallback rooms or try again later."
            ),
        ) from exc

    rooms = directory.get("rooms", [])
    if not isinstance(rooms, list):
        rooms = []
    filtered_rooms = _filtered_rooms(_dedupe_rooms(rooms), attendee_count=attendee_count, query=query, limit=limit)
    room_lists = directory.get("room_lists", [])
    if not isinstance(room_lists, list):
        room_lists = []
    return {
        **_room_directory_payload(source="exchange", options=filtered_rooms),
        "room_lists": room_lists,
    }


def _room_discovery_error_is_recoverable(error: EwsToolError) -> bool:
    return error.error_code in {"credentials_missing", "exchange_room_directory_unavailable"} or bool(
        error.payload.get("recoverable")
    )


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
        parse_iso_datetime(start),
        parse_iso_datetime(end),
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
    workday_start: str | None = None,
    workday_end: str | None = None,
    avoid: list[str] | None = None,
    client_factory: ClientFactory = default_client_factory,
) -> list[dict[str, str]]:
    if workday_start is None or workday_end is None or avoid is None:
        policy = load_policy()
        if workday_start is None:
            workday_start = policy.workday_start
        if workday_end is None:
            workday_end = policy.workday_end
        if avoid is None:
            avoid = policy.avoid
    window_start = parse_iso_datetime(start)
    window_end = parse_iso_datetime(end)
    client = client_factory()
    attendee_emails = _attendee_emails(attendees, client)
    busy = client.get_free_busy(attendee_emails, window_start, window_end)
    room_infos = _room_infos(rooms or [], client, use_default=require_room)
    room_infos = _rooms_with_capacity(room_infos, attendee_count=len(attendee_emails))
    if require_room and not rooms and not room_infos:
        room_infos = _rooms_with_capacity(default_room_options(), attendee_count=len(attendee_emails))
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
    body_format: str = "html",
    location: str = "",
    client_factory: ClientFactory = default_client_factory,
) -> dict[str, Any]:
    arguments = {
        "subject": subject,
        "attendees": attendees,
        "rooms": rooms or [],
        "start": start,
        "end": end,
        "body": body,
        "body_format": body_format,
        "location": location,
    }
    try:
        needs_client = _needs_resolution(attendees) or _rooms_need_resolution(rooms or [])
        client = client_factory() if needs_client else None
        if _needs_resolution(attendees):
            if client is None:
                client = client_factory()
            attendees = _attendee_emails(attendees, client)
        else:
            attendees = [attendee.strip() for attendee in attendees]
        room_infos = _room_infos(rooms or [], client) if rooms else []
        room_emails = [room["email"] for room in room_infos]
        if not location and room_infos:
            location = room_infos[0]["name"]
        request = _meeting_request(subject, attendees, room_emails, start, end, body, body_format, location)
        preview = build_meeting_preview(request, confirmed=False)
        preview["confirmation_id"] = _confirmation_id("create_meeting", preview)
        warning = _record_lifecycle_audit(action="create_meeting", status="preview", arguments=arguments, result=preview)
        if warning:
            preview["audit_warning"] = warning
        return preview
    except EwsToolError as error:
        _record_lifecycle_audit(
            action="create_meeting",
            status=_audit_status_for_error(error),
            arguments=arguments,
            error=error,
        )
        raise


def ews_create_meeting_confirmed(
    *,
    subject: str,
    attendees: list[str],
    rooms: list[str] | None = None,
    start: str,
    end: str,
    body: str = "",
    body_format: str = "html",
    location: str = "",
    confirmation_id: str = "",
    confirm: bool = False,
    client_factory: ClientFactory = default_client_factory,
) -> dict[str, Any]:
    arguments = {
        "subject": subject,
        "attendees": attendees,
        "rooms": rooms or [],
        "start": start,
        "end": end,
        "body": body,
        "body_format": body_format,
        "location": location,
        "confirmation_id": confirmation_id,
        "confirm": confirm,
    }
    try:
        if confirm is not True:
            raise _confirmation_mismatch("Create confirmation requires confirm=true and a matching confirmation_id.")
        if not confirmation_id:
            raise _confirmation_mismatch("Create confirmation requires a matching confirmation_id from preview.")
        _reserve_confirmation(confirmation_id, "create_meeting")

        try:
            client = client_factory()
            attendee_emails = _attendee_emails(attendees, client)
            room_infos = _room_infos(rooms or [], client)
            room_emails = [room["email"] for room in room_infos]
            if not location and room_infos:
                location = room_infos[0]["name"]
            request = _meeting_request(subject, attendee_emails, room_emails, start, end, body, body_format, location)
            preview = build_meeting_preview(request, confirmed=False)
            preview["confirmation_id"] = _confirmation_id("create_meeting", preview)
            _require_confirmation_id(confirmation_id, str(preview["confirmation_id"]))
        except Exception:
            _release_confirmation(confirmation_id)
            raise

        created = client.create_meeting(request)
        confirmed_preview = dict(preview)
        confirmed_preview["action"] = "create_meeting"
        confirmed_preview["will_send_invites"] = True
        result = {"preview": confirmed_preview, "created": created}
        warning = _record_completed_confirmation(confirmation_id, "create_meeting", result)
        if warning:
            result["confirmation_ledger_warning"] = warning
        audit_warning = _record_lifecycle_audit(
            action="create_meeting",
            status="confirmed",
            arguments=arguments,
            result=result,
        )
        if audit_warning:
            result["audit_warning"] = audit_warning
        return result
    except EwsToolError as error:
        _record_lifecycle_audit(
            action="create_meeting",
            status=_audit_status_for_error(error),
            arguments=arguments,
            error=error,
        )
        raise


def ews_update_meeting_preview(
    *,
    id: str,
    changekey: str,
    subject: str | None = None,
    start: str | None = None,
    end: str | None = None,
    location: str | None = None,
    body: str | None = None,
    body_format: str = "html",
    send_meeting_invitations: bool = True,
    client_factory: ClientFactory = default_client_factory,
) -> dict[str, Any]:
    arguments = {
        "id": id,
        "changekey": changekey,
        "subject": subject,
        "start": start,
        "end": end,
        "location": location,
        "body": body,
        "body_format": body_format,
        "send_meeting_invitations": send_meeting_invitations,
    }
    try:
        client = client_factory()
        current = client.get_calendar_event(id, changekey)
        updates = _meeting_updates(subject=subject, start=start, end=end, location=location, body=body)
        proposed = _proposed_event(current, updates)
        preview = {
            "action": "update_meeting_preview",
            "will_save": False,
            "will_send_updates": False,
            "confirmed_will_send_updates": send_meeting_invitations,
            "current_event": current,
            "proposed_event": proposed,
            "updates": updates,
            "body_format": body_format if body is not None else None,
            "warnings": _update_warnings(updates),
        }
        preview["confirmation_id"] = _confirmation_id("update_meeting", preview)
        warning = _record_lifecycle_audit(action="update_meeting", status="preview", arguments=arguments, result=preview)
        if warning:
            preview["audit_warning"] = warning
        return preview
    except EwsToolError as error:
        _record_lifecycle_audit(
            action="update_meeting",
            status=_audit_status_for_error(error),
            arguments=arguments,
            error=error,
        )
        raise


def ews_update_meeting_confirmed(
    *,
    id: str,
    changekey: str,
    confirmation_id: str = "",
    subject: str | None = None,
    start: str | None = None,
    end: str | None = None,
    location: str | None = None,
    body: str | None = None,
    body_format: str = "html",
    confirm: bool = False,
    send_meeting_invitations: bool = True,
    client_factory: ClientFactory = default_client_factory,
) -> dict[str, Any]:
    arguments = {
        "id": id,
        "changekey": changekey,
        "confirmation_id": confirmation_id,
        "subject": subject,
        "start": start,
        "end": end,
        "location": location,
        "body": body,
        "body_format": body_format,
        "confirm": confirm,
        "send_meeting_invitations": send_meeting_invitations,
    }
    try:
        if confirm is not True:
            raise _confirmation_mismatch("Update confirmation requires confirm=true and a matching confirmation_id.")
        if not confirmation_id:
            raise _confirmation_mismatch("Update confirmation requires a matching confirmation_id from preview.")
        _reserve_confirmation(confirmation_id, "update_meeting")

        try:
            preview = ews_update_meeting_preview(
                id=id,
                changekey=changekey,
                subject=subject,
                start=start,
                end=end,
                location=location,
                body=body,
                body_format=body_format,
                send_meeting_invitations=send_meeting_invitations,
                client_factory=client_factory,
            )
            _require_confirmation_id(confirmation_id, str(preview["confirmation_id"]))
            updates = preview["updates"]
            if not isinstance(updates, dict):
                updates = {}
            update_fields = [field for field in ["subject", "start", "end", "location", "body"] if field in updates]
            if not update_fields:
                raise EwsToolError(
                    "empty_update",
                    "No supported update fields were provided. Refusing to save an empty Exchange update.",
                    required_action="provide_update_fields",
                    user_message="請提供至少一個要更新的欄位，例如 subject、start、end、location 或 body，然後重新預覽。",
                )
            client = client_factory()
        except Exception:
            _release_confirmation(confirmation_id)
            raise

        updated = client.update_meeting(
            id,
            changekey,
            updates,
            update_fields=update_fields,
            body_format=body_format,
            send_meeting_invitations=send_meeting_invitations,
        )
        result = {
            "preview": preview,
            "updated": updated,
            "update_fields": update_fields,
            "sent_meeting_updates": send_meeting_invitations,
        }
        warning = _record_completed_confirmation(confirmation_id, "update_meeting", result)
        if warning:
            result["confirmation_ledger_warning"] = warning
        audit_warning = _record_lifecycle_audit(
            action="update_meeting",
            status="confirmed",
            arguments=arguments,
            result=result,
        )
        if audit_warning:
            result["audit_warning"] = audit_warning
        return result
    except EwsToolError as error:
        _record_lifecycle_audit(
            action="update_meeting",
            status=_audit_status_for_error(error),
            arguments=arguments,
            error=error,
        )
        raise


def ews_cancel_meeting_preview(
    *,
    id: str,
    changekey: str,
    send_meeting_cancellations: bool = True,
    client_factory: ClientFactory = default_client_factory,
) -> dict[str, Any]:
    arguments = {
        "id": id,
        "changekey": changekey,
        "send_meeting_cancellations": send_meeting_cancellations,
    }
    try:
        client = client_factory()
        current = client.get_calendar_event(id, changekey)
        preview = {
            "action": "cancel_meeting_preview",
            "will_move_to_trash": False,
            "will_send_cancellations": False,
            "send_meeting_cancellations": send_meeting_cancellations,
            "cancellation_target": current,
            "warnings": _cancel_warnings(current),
        }
        preview["confirmation_id"] = _confirmation_id("cancel_meeting", preview)
        warning = _record_lifecycle_audit(action="cancel_meeting", status="preview", arguments=arguments, result=preview)
        if warning:
            preview["audit_warning"] = warning
        return preview
    except EwsToolError as error:
        _record_lifecycle_audit(
            action="cancel_meeting",
            status=_audit_status_for_error(error),
            arguments=arguments,
            error=error,
        )
        raise


def ews_cancel_meeting_confirmed(
    *,
    id: str,
    changekey: str,
    confirmation_id: str = "",
    confirm: bool = False,
    send_meeting_cancellations: bool = True,
    client_factory: ClientFactory = default_client_factory,
) -> dict[str, Any]:
    arguments = {
        "id": id,
        "changekey": changekey,
        "confirmation_id": confirmation_id,
        "confirm": confirm,
        "send_meeting_cancellations": send_meeting_cancellations,
    }
    try:
        if confirm is not True:
            raise _confirmation_mismatch("Cancel confirmation requires confirm=true and a matching confirmation_id.")
        if not confirmation_id:
            raise _confirmation_mismatch("Cancel confirmation requires a matching confirmation_id from preview.")
        _reserve_confirmation(confirmation_id, "cancel_meeting")

        try:
            preview = ews_cancel_meeting_preview(
                id=id,
                changekey=changekey,
                send_meeting_cancellations=send_meeting_cancellations,
                client_factory=client_factory,
            )
            _require_confirmation_id(confirmation_id, str(preview["confirmation_id"]))
            target = preview["cancellation_target"]
            if isinstance(target, dict):
                _validate_cancel_target(target)
            client = client_factory()
        except Exception:
            _release_confirmation(confirmation_id)
            raise

        cancelled = client.cancel_meeting(
            id,
            changekey,
            send_meeting_cancellations=send_meeting_cancellations,
        )
        result = {
            "preview": preview,
            "cancelled": cancelled,
            "moved_to_trash": True,
            "sent_meeting_cancellations": send_meeting_cancellations,
        }
        warning = _record_completed_confirmation(confirmation_id, "cancel_meeting", result)
        if warning:
            result["confirmation_ledger_warning"] = warning
        audit_warning = _record_lifecycle_audit(
            action="cancel_meeting",
            status="confirmed",
            arguments=arguments,
            result=result,
        )
        if audit_warning:
            result["audit_warning"] = audit_warning
        return result
    except EwsToolError as error:
        _record_lifecycle_audit(
            action="cancel_meeting",
            status=_audit_status_for_error(error),
            arguments=arguments,
            error=error,
        )
        raise


def _meeting_request(
    subject: str,
    attendees: list[str],
    rooms: list[str],
    start: str,
    end: str,
    body: str,
    body_format: str,
    location: str,
) -> MeetingRequest:
    return MeetingRequest(
        subject=subject,
        attendees=attendees,
        rooms=rooms,
        start=parse_iso_datetime(start),
        end=parse_iso_datetime(end),
        body=body,
        body_format=body_format,
        location=location,
    )


def _meeting_updates(
    *,
    subject: str | None,
    start: str | None,
    end: str | None,
    location: str | None,
    body: str | None,
) -> dict[str, object]:
    updates: dict[str, object] = {}
    for key, value in [
        ("subject", subject),
        ("start", start),
        ("end", end),
        ("location", location),
        ("body", body),
    ]:
        if value is not None:
            updates[key] = value
    return updates


def _proposed_event(current: dict[str, Any], updates: dict[str, object]) -> dict[str, Any]:
    proposed = dict(current)
    proposed.update(updates)
    return proposed


def _update_warnings(updates: dict[str, object]) -> list[str]:
    warnings: list[str] = [
        "Only subject, start, end, location, and body updates are supported; attendees and resources are unchanged."
    ]
    if not updates:
        warnings.append("No supported update fields were provided.")
    return warnings


def _cancel_warnings(current: dict[str, Any]) -> list[str]:
    warnings = ["Confirmed cancel moves the item to trash and sends meeting cancellations when requested."]
    if _is_recurring_event(current):
        warnings.append("Recurring meeting cancellation is not supported by this first implementation.")
    if current.get("is_organizer") is False:
        warnings.append("Only organizer meetings can be cancelled by this tool when organizer status is exposed.")
    return warnings


def _validate_cancel_target(target: dict[str, Any]) -> None:
    if _is_recurring_event(target):
        raise EwsToolError(
            "unsupported_recurring_meeting",
            "Recurring meeting cancellation is not supported yet. Cancel this meeting manually in Outlook.",
            required_action="cancel_manually",
        )
    if target.get("is_organizer") is not True:
        raise EwsToolError(
            "not_meeting_organizer",
            "Only meetings where organizer status is explicitly confirmed can be cancelled by this tool.",
            required_action="ask_organizer",
        )
    if target.get("is_meeting") is False:
        raise EwsToolError(
            "unsupported_calendar_item",
            "Only meeting calendar items can be cancelled by this tool.",
            required_action="cancel_manually",
        )


def _is_recurring_event(event: dict[str, Any]) -> bool:
    if event.get("is_recurring") is True:
        return True
    event_type = str(event.get("type", "")).lower()
    return any(marker in event_type for marker in ["recurring", "occurrence", "exception"])


def _require_confirmation_id(provided: str, expected: str) -> None:
    if not provided or provided != expected:
        raise _confirmation_mismatch("confirmation_id does not match the latest preview.")


def _confirmation_mismatch(message: str) -> EwsToolError:
    return EwsToolError(
        "confirmation_mismatch",
        message,
        required_action="preview_again",
        user_message="Preview the meeting change again, show it to the user, then confirm with the returned confirmation_id.",
    )


def _confirmation_id(action: str, payload: dict[str, Any]) -> str:
    return confirmation_id(action, payload)


def _reserve_confirmation(id: str, action: str) -> None:
    ConfirmationLedger().reserve(id=id, action=action)


def _release_confirmation(id: str) -> None:
    ConfirmationLedger().release(id)


def _raise_if_duplicate_confirmation(id: str) -> None:
    entry = ConfirmationLedger().completed(id)
    if entry is None:
        return
    raise EwsToolError(
        "duplicate_confirmation",
        "This confirmation_id was already completed. Do not retry the Exchange operation blindly.",
        required_action="do_not_retry",
        next_action="treat_as_already_handled",
        confirmation_id=id,
        prior_result=entry.get("result"),
        completed_at=entry.get("completed_at"),
        user_message="這個 confirmation_id 已經成功處理過；請視為已處理，不要直接重送邀請或更新。",
    )


def _record_completed_confirmation(id: str, action: str, result: dict[str, Any]) -> dict[str, Any] | None:
    try:
        ConfirmationLedger().record_completed(id=id, action=action, result=result)
    except EwsToolError as error:
        return error.payload
    return None


def _record_lifecycle_audit(
    *,
    action: str,
    status: str,
    arguments: dict[str, Any] | None = None,
    result: dict[str, Any] | None = None,
    error: EwsToolError | None = None,
) -> dict[str, Any] | None:
    payload: dict[str, Any] = {}
    if arguments:
        payload["arguments"] = arguments
    if result:
        payload["result"] = result
    error_code = None
    if error:
        payload["error"] = error.payload
        error_code = error.error_code
    return record_lifecycle_audit(
        action=action,
        status=status,
        payload=payload,
        error_code=error_code,
    )


def _audit_status_for_error(error: EwsToolError) -> str:
    if error.error_code == "duplicate_confirmation":
        return "duplicate"
    if error.error_code == "confirmation_in_progress":
        return "in_progress"
    return "error"


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
            raise EwsToolError(
                "ambiguous_attendee",
                f"Attendee '{query}' is ambiguous.",
                query=query,
                matches=_safe_matches(matches),
                required_action="choose_attendee_candidate",
                next_action="ask_user_to_choose_attendee_candidate",
                user_message=(
                    f"找到多個符合 '{query}' 的人員。請讓使用者從候選人中選擇一位，"
                    "不要要求使用者手動輸入完整 email。"
                ),
            )

        raise EwsToolError(
            "attendee_not_found",
            f"Could not resolve attendee '{query}' to an email address.",
            query=query,
            matches=_safe_matches(matches),
            required_action="clarify_attendee",
            next_action="ask_user_for_more_specific_attendee_name_or_email",
            user_message=(
                f"找不到符合 '{query}' 的公司通訊錄人員。請使用者提供更完整的姓名、別名或 email。"
            ),
        )

    return emails


def _room_infos(
    rooms: list[str],
    client: EwsClient | None,
    *,
    use_default: bool = False,
) -> list[dict[str, Any]]:
    if use_default and not rooms:
        dynamic_rooms = _dynamic_room_infos_for_scheduling(client)
        if dynamic_rooms:
            return dynamic_rooms
        return default_room_options()
    if not rooms:
        return []

    room_infos: list[dict[str, Any]] = []
    unresolved: list[str] = []
    known_rooms = _known_rooms()
    for room in rooms:
        query = room.strip()
        if not query:
            continue
        known_room = known_rooms.get(_room_key(query))
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


def _dynamic_room_infos_for_scheduling(client: EwsClient | None) -> list[dict[str, Any]]:
    if client is None or not hasattr(client, "discover_rooms"):
        return []
    try:
        directory = client.discover_rooms(room_list=None)
    except Exception:
        return []
    rooms = directory.get("rooms", [])
    if not isinstance(rooms, list):
        return []
    return _dedupe_rooms([room for room in rooms if isinstance(room, dict) and room.get("email")])


def _rooms_need_resolution(rooms: list[str]) -> bool:
    if not rooms:
        return False

    known_rooms = _known_rooms()
    for room in rooms:
        query = room.strip()
        if not query:
            continue
        if known_rooms.get(_room_key(query)) or _looks_like_email(query):
            continue
        return True
    return False


def _known_rooms() -> dict[str, dict[str, Any]]:
    return {room["alias"]: dict(room) for room in default_room_options()}


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


def _filtered_rooms(
    rooms: list[dict[str, Any]],
    *,
    attendee_count: int | None,
    query: str | None,
    limit: int,
) -> list[dict[str, Any]]:
    filtered = [dict(room) for room in rooms if isinstance(room, dict)]
    if attendee_count is not None:
        filtered = _rooms_with_capacity(filtered, attendee_count=attendee_count)
    query_text = (query or "").strip().lower()
    if query_text:
        filtered = [room for room in filtered if _room_matches_query(room, query_text)]
    return filtered[:limit]


def _room_matches_query(room: dict[str, Any], query: str) -> bool:
    fields = [
        room.get("alias"),
        room.get("name"),
        room.get("email"),
        room.get("room_list"),
    ]
    return any(query in str(field or "").lower() for field in fields)


def _room_directory_payload(*, source: str, options: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "source": source,
        "selection_hint": "Ask the user to choose one room value, or choose no specific room.",
        "options": [_room_selection_option(room) for room in options],
    }


def _room_selection_option(room: dict[str, Any]) -> dict[str, Any]:
    source = str(room.get("source", "static"))
    value = room["email"] if source == "exchange" else room.get("alias", room["email"])
    option = {
        "label": room["name"],
        "value": value,
        "email": room["email"],
        "name": room["name"],
        "capacity": room.get("capacity"),
        "room_list": room.get("room_list"),
        "source": source,
    }
    if room.get("alias"):
        option["alias"] = room.get("alias")
    return option


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


def _safe_matches(matches: list[object]) -> list[dict[str, str]]:
    safe: list[dict[str, str]] = []
    for match in matches:
        if not isinstance(match, dict):
            continue
        safe.append(
            {
                "name": str(match.get("name", "")),
                "email": str(match.get("email", "")),
            }
        )
    return safe
