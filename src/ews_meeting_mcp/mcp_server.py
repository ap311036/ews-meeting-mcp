from __future__ import annotations

import json
import sys
import traceback
import warnings
from typing import Any, Callable

from . import agent_tools
from .audit import record_lifecycle_audit
from .confirmations import ConfirmationLedger
from .errors import EwsToolError


SERVER_INFO = {"name": "ews-meeting-mcp", "version": "0.1.17"}

TOOL_HANDLERS: dict[str, Callable[..., Any]] = {
    "ews_keychain_status": agent_tools.ews_keychain_status,
    "ews_setup_check": agent_tools.ews_setup_check,
    "ews_get_audit_log": agent_tools.ews_get_audit_log,
    "ews_probe": agent_tools.ews_probe,
    "ews_list_calendar": agent_tools.ews_list_calendar,
    "ews_find_calendar_events": agent_tools.ews_find_calendar_events,
    "ews_verify_meeting": agent_tools.ews_verify_meeting,
    "ews_list_rooms": agent_tools.ews_list_rooms,
    "ews_resolve_attendees": agent_tools.ews_resolve_attendees,
    "ews_get_free_busy": agent_tools.ews_get_free_busy,
    "ews_suggest_slots": agent_tools.ews_suggest_slots,
    "ews_create_meeting_preview": agent_tools.ews_create_meeting_preview,
    "ews_create_meeting_confirmed": agent_tools.ews_create_meeting_confirmed,
    "ews_update_meeting_preview": agent_tools.ews_update_meeting_preview,
    "ews_update_meeting_confirmed": agent_tools.ews_update_meeting_confirmed,
    "ews_cancel_meeting_preview": agent_tools.ews_cancel_meeting_preview,
    "ews_cancel_meeting_confirmed": agent_tools.ews_cancel_meeting_confirmed,
}

EWS_CREDENTIAL_TOOLS = {
    "ews_probe",
    "ews_list_calendar",
    "ews_find_calendar_events",
    "ews_verify_meeting",
    "ews_resolve_attendees",
    "ews_get_free_busy",
    "ews_suggest_slots",
    "ews_create_meeting_confirmed",
    "ews_update_meeting_preview",
    "ews_update_meeting_confirmed",
    "ews_cancel_meeting_preview",
    "ews_cancel_meeting_confirmed",
}

LIFECYCLE_ACTION_BY_TOOL = {
    "ews_create_meeting_preview": "create_meeting",
    "ews_create_meeting_confirmed": "create_meeting",
    "ews_update_meeting_preview": "update_meeting",
    "ews_update_meeting_confirmed": "update_meeting",
    "ews_cancel_meeting_preview": "cancel_meeting",
    "ews_cancel_meeting_confirmed": "cancel_meeting",
}


def main() -> None:
    _suppress_known_warnings()
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
            response = handle_request(request)
        except Exception as exc:
            response = _error_response(None, -32603, f"Internal error: {exc}")
            traceback.print_exc(file=sys.stderr)
        if response is not None:
            print(json.dumps(response, ensure_ascii=False), flush=True)


def handle_request(request: dict[str, Any]) -> dict[str, Any] | None:
    request_id = request.get("id")
    method = request.get("method")

    if method == "notifications/initialized":
        return None
    if method == "initialize":
        return _result_response(
            request_id,
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": SERVER_INFO,
                "instructions": (
                    "Before any EWS scheduling, call ews_setup_check. If ready=false, show "
                    "user_message as-is, or show setup_command verbatim in a fenced shell block, and stop; "
                    "do not ask for attendee emails or continue scheduling until setup is ready. "
                    "Resolve non-email attendee names with ews_resolve_attendees before scheduling. "
                    "Use ews_suggest_slots with resolved email addresses and candidate rooms when a room "
                    "is needed. Before sending invitations, show the preview from "
                    "ews_create_meeting_preview and ask the user to confirm, then pass the same "
                    "confirmation_id to ews_create_meeting_confirmed. For existing meetings, "
                    "use ews_find_calendar_events, preview update/cancel actions, then call the matching "
                    "confirmed tool only with confirm=true and the returned confirmation_id. After confirmed "
                    "create/update, use ews_verify_meeting when the user needs server-side verification or room "
                    "response status."
                ),
            },
        )
    if method == "tools/list":
        return _result_response(request_id, {"tools": _tool_defs()})
    if method == "tools/call":
        return _handle_tool_call(request_id, request.get("params") or {})

    return _error_response(request_id, -32601, f"Unknown method: {method}")


def _handle_tool_call(request_id: Any, params: dict[str, Any]) -> dict[str, Any]:
    name = params.get("name")
    arguments = params.get("arguments") or {}
    handler = TOOL_HANDLERS.get(name)
    if handler is None:
        return _tool_error(request_id, f"Unknown tool: {name}")

    if name in EWS_CREDENTIAL_TOOLS and _needs_credential_preflight(name, arguments):
        setup_status = agent_tools.ews_setup_check()
        if not setup_status.get("ready", True):
            _audit_lifecycle_preflight_error(name, arguments, setup_status)
            return _tool_json_error(request_id, setup_status)

    try:
        result = handler(**arguments)
    except EwsToolError as exc:
        return _tool_json_error(request_id, exc.payload)
    except Exception as exc:
        return _tool_error(request_id, str(exc))

    return _result_response(
        request_id,
        {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(result, ensure_ascii=False, indent=2, default=str),
                }
            ],
            "isError": False,
        },
    )


def _meeting_schema(*, include_confirm: bool) -> dict[str, Any]:
    properties: dict[str, Any] = {
        "subject": {"type": "string"},
        "attendees": {"type": "array", "items": {"type": "string"}, "minItems": 1},
        "rooms": {
            "type": "array",
            "items": {"type": "string"},
            "default": [],
            "description": "Meeting room names, aliases, or email addresses.",
        },
        "start": {"type": "string", "description": "ISO datetime with timezone"},
        "end": {"type": "string", "description": "ISO datetime with timezone"},
        "body": {"type": "string", "default": ""},
        "body_format": {
            "type": "string",
            "enum": ["html", "text"],
            "default": "html",
            "description": "Meeting body format. Defaults to html; plain text input is safely converted to HTML.",
        },
        "location": {"type": "string", "default": ""},
    }
    required = ["subject", "attendees", "start", "end"]
    if include_confirm:
        properties["confirmation_id"] = {
            "type": "string",
            "description": "Must exactly match the confirmation_id returned by ews_create_meeting_preview.",
        }
        properties["confirm"] = {
            "type": "boolean",
            "description": "Must be true. The tool refuses to create meetings unless confirm=true.",
        }
        required.extend(["confirmation_id", "confirm"])
    return {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }


def _free_busy_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "attendees": {"type": "array", "items": {"type": "string"}, "minItems": 1},
            "start": {"type": "string", "description": "ISO datetime with timezone"},
            "end": {"type": "string", "description": "ISO datetime with timezone"},
        },
        "required": ["attendees", "start", "end"],
        "additionalProperties": False,
    }


def _find_calendar_events_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "start": {"type": "string", "description": "ISO datetime with timezone"},
            "end": {"type": "string", "description": "ISO datetime with timezone"},
            "subject_contains": {"type": "string", "description": "Optional case-insensitive subject filter."},
            "location_contains": {"type": "string", "description": "Optional case-insensitive location filter."},
            "organizer_email": {"type": "string", "description": "Optional exact organizer email filter."},
            "attendee_email": {"type": "string", "description": "Optional exact attendee or resource email filter."},
            "limit": {"type": "integer", "default": 20, "minimum": 1},
        },
        "required": ["start", "end"],
        "additionalProperties": False,
    }


def _verify_meeting_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "id": {"type": "string", "description": "EWS calendar item id returned by create or search."},
            "changekey": {
                "type": "string",
                "description": "Optional changekey returned by create, search, update, or cancel preview.",
            },
        },
        "required": ["id"],
        "additionalProperties": False,
    }


def _meeting_update_schema(*, include_confirm: bool) -> dict[str, Any]:
    properties: dict[str, Any] = {
        "id": {"type": "string", "description": "Exact EWS calendar item id from ews_find_calendar_events."},
        "changekey": {"type": "string", "description": "Exact changekey returned with the EWS item id."},
        "subject": {"type": "string", "description": "Optional replacement subject."},
        "start": {"type": "string", "description": "Optional replacement ISO datetime with timezone."},
        "end": {"type": "string", "description": "Optional replacement ISO datetime with timezone."},
        "location": {"type": "string", "description": "Optional replacement location."},
        "body": {"type": "string", "description": "Optional replacement body."},
        "body_format": {
            "type": "string",
            "enum": ["html", "text"],
            "default": "html",
            "description": "Format for body updates. Defaults to html; plain text input is safely converted to HTML.",
        },
        "send_meeting_invitations": {
            "type": "boolean",
            "default": True,
            "description": "When true, the confirmed update sends Exchange meeting update notifications.",
        },
    }
    required = ["id", "changekey"]
    if include_confirm:
        properties["confirmation_id"] = {
            "type": "string",
            "description": "Must exactly match the confirmation_id returned by ews_update_meeting_preview.",
        }
        properties["confirm"] = {
            "type": "boolean",
            "description": "Must be true. The tool refuses to update meetings unless confirm=true.",
        }
        required.extend(["confirmation_id", "confirm"])
    return {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }


def _meeting_cancel_schema(*, include_confirm: bool) -> dict[str, Any]:
    properties: dict[str, Any] = {
        "id": {"type": "string", "description": "Exact EWS calendar item id from ews_find_calendar_events."},
        "changekey": {"type": "string", "description": "Exact changekey returned with the EWS item id."},
        "send_meeting_cancellations": {
            "type": "boolean",
            "default": True,
            "description": "When true, send Exchange meeting cancellation notices.",
        },
    }
    required = ["id", "changekey"]
    if include_confirm:
        properties["confirmation_id"] = {
            "type": "string",
            "description": "Must exactly match the confirmation_id returned by ews_cancel_meeting_preview.",
        }
        properties["confirm"] = {
            "type": "boolean",
            "description": "Must be true. The tool refuses to cancel meetings unless confirm=true.",
        }
        required.extend(["confirmation_id", "confirm"])
    return {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }


def _audit_log_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "limit": {"type": "integer", "default": 50, "minimum": 1},
            "action": {
                "type": "string",
                "description": "Optional action filter such as create_meeting, update_meeting, or cancel_meeting.",
            },
            "status": {
                "type": "string",
                "description": "Optional status filter: preview, confirmed, duplicate, in_progress, or error.",
            },
        },
        "additionalProperties": False,
    }


def _resolve_attendees_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "attendees": {
                "type": "array",
                "items": {"type": "string"},
                "minItems": 1,
                "description": "Attendee display names, aliases, or email addresses.",
            },
            "limit": {"type": "integer", "default": 5, "minimum": 1},
        },
        "required": ["attendees"],
        "additionalProperties": False,
    }


def _suggest_schema() -> dict[str, Any]:
    schema = _free_busy_schema()
    schema["properties"].update(
        {
            "rooms": {
                "type": "array",
                "items": {"type": "string"},
                "default": [],
                "description": "Candidate meeting rooms. Supports aliases like 2-11, 2-13, 2-14, 3-1, 3-2, 3-4.",
            },
            "require_room": {
                "type": "boolean",
                "default": False,
                "description": (
                    "When true and rooms is empty, search Exchange room lists when available, "
                    "then fall back to configured static rooms and filter by capacity."
                ),
            },
            "duration_minutes": {"type": "integer", "default": 30, "minimum": 1},
            "limit": {"type": "integer", "default": 5, "minimum": 1},
            "workday_start": {"type": "string", "description": "HH:MM. Omit to use local policy default."},
            "workday_end": {"type": "string", "description": "HH:MM. Omit to use local policy default."},
            "avoid": {
                "type": "array",
                "items": {"type": "string"},
                "description": "HH:MM-HH:MM ranges. Omit to use local policy default.",
            },
        }
    )
    return schema


def _tool_defs() -> list[dict[str, Any]]:
    return [
        {
            "name": "ews_keychain_status",
            "description": (
                "Check whether EWS password credentials are available from environment variables "
                "or macOS Keychain without revealing the password. If missing, returns required_action "
                "and setup_command that must be shown verbatim to the user."
            ),
            "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
        },
        {
            "name": "ews_setup_check",
            "description": (
                "Return whether EWS setup is ready, including env and password/Keychain checks. "
                "When ready is false, show user_message or setup_command and stop before scheduling."
            ),
            "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
        },
        {
            "name": "ews_get_audit_log",
            "description": (
                "Read recent local lifecycle audit entries for meeting preview, confirmed, duplicate, "
                "in-progress, and error actions. Does not read EWS credentials or call Exchange."
            ),
            "inputSchema": _audit_log_schema(),
        },
        {
            "name": "ews_probe",
            "description": "Check that the configured EWS account can connect. Does not read calendar items.",
            "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
        },
        {
            "name": "ews_list_calendar",
            "description": "List upcoming events from the configured user's default calendar.",
            "inputSchema": {
                "type": "object",
                "properties": {"days": {"type": "integer", "default": 7, "minimum": 1}},
                "additionalProperties": False,
            },
        },
        {
            "name": "ews_find_calendar_events",
            "description": (
                "Read-only search for calendar events in a time window. Returns exact EWS id and changekey "
                "metadata for safe preview-confirm update or cancel flows."
            ),
            "inputSchema": _find_calendar_events_schema(),
        },
        {
            "name": "ews_verify_meeting",
            "description": (
                "Verify a calendar item by EWS id and optional changekey. Returns normalized organizer item "
                "status, attendees, rooms/resources, and response_status values when Exchange exposes them."
            ),
            "inputSchema": _verify_meeting_schema(),
        },
        {
            "name": "ews_list_rooms",
            "description": (
                "List Exchange meeting rooms from dynamic room lists, or configured static fallback rooms, "
                "as structured options for user selection."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "attendee_count": {
                        "type": "integer",
                        "minimum": 1,
                        "description": "Optional attendee count used to hide rooms with known insufficient capacity.",
                    },
                    "query": {
                        "type": "string",
                        "description": "Optional text filter matched against room name, email, alias, or room list.",
                    },
                    "room_list": {
                        "type": "string",
                        "description": "Optional Exchange room list name or email to search within.",
                    },
                    "source": {
                        "type": "string",
                        "enum": ["auto", "exchange", "static"],
                        "default": "auto",
                        "description": "auto tries Exchange and falls back to configured rooms; static never requires credentials.",
                    },
                    "limit": {"type": "integer", "default": 100, "minimum": 1},
                },
                "additionalProperties": False,
            },
        },
        {
            "name": "ews_resolve_attendees",
            "description": (
                "Resolve attendee names, aliases, or email addresses against the company Exchange "
                "directory before scheduling. If multiple matches are returned, ask the user which "
                "email to use."
            ),
            "inputSchema": _resolve_attendees_schema(),
        },
        {
            "name": "ews_get_free_busy",
            "description": "Read free/busy blocks for one or more attendee email addresses.",
            "inputSchema": _free_busy_schema(),
        },
        {
            "name": "ews_suggest_slots",
            "description": (
                "Suggest nearest overlapping free meeting slots for multiple attendees and optional "
                "candidate meeting rooms. Omits workday_start, workday_end, and avoid to use local policy defaults."
            ),
            "inputSchema": _suggest_schema(),
        },
        {
            "name": "ews_create_meeting_preview",
            "description": "Preview a meeting invite without creating the event or sending invitations.",
            "inputSchema": _meeting_schema(include_confirm=False),
        },
        {
            "name": "ews_create_meeting_confirmed",
            "description": (
                "Create a meeting and send invitations. Only call after the user explicitly confirms "
                "the exact attendees, time, subject, body, and location. Requires confirm=true and "
                "the confirmation_id returned by ews_create_meeting_preview."
            ),
            "inputSchema": _meeting_schema(include_confirm=True),
        },
        {
            "name": "ews_update_meeting_preview",
            "description": (
                "Preview changes to an existing meeting using exact id and changekey. Does not save "
                "or send meeting updates."
            ),
            "inputSchema": _meeting_update_schema(include_confirm=False),
        },
        {
            "name": "ews_update_meeting_confirmed",
            "description": (
                "Update an existing meeting. Requires confirm=true and the confirmation_id returned by "
                "ews_update_meeting_preview. Supports only subject, start, end, location, and body."
            ),
            "inputSchema": _meeting_update_schema(include_confirm=True),
        },
        {
            "name": "ews_cancel_meeting_preview",
            "description": (
                "Preview cancellation of an existing meeting using exact id and changekey. Does not delete, "
                "move, or send cancellations."
            ),
            "inputSchema": _meeting_cancel_schema(include_confirm=False),
        },
        {
            "name": "ews_cancel_meeting_confirmed",
            "description": (
                "Cancel an existing non-recurring organizer meeting by moving it to trash. Requires "
                "confirm=true and the confirmation_id returned by ews_cancel_meeting_preview."
            ),
            "inputSchema": _meeting_cancel_schema(include_confirm=True),
        },
    ]


def _result_response(request_id: Any, result: Any) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _error_response(request_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


def _tool_error(request_id: Any, message: str) -> dict[str, Any]:
    return _result_response(
        request_id,
        {"content": [{"type": "text", "text": message}], "isError": True},
    )


def _tool_json_error(request_id: Any, payload: dict[str, Any]) -> dict[str, Any]:
    return _result_response(
        request_id,
        {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(payload, ensure_ascii=False, indent=2, default=str),
                }
            ],
            "isError": True,
        },
    )


def _audit_lifecycle_preflight_error(name: Any, arguments: dict[str, Any], payload: dict[str, Any]) -> None:
    action = LIFECYCLE_ACTION_BY_TOOL.get(str(name))
    if not action:
        return
    error_code = str(payload.get("error_code", "") or "")
    record_lifecycle_audit(
        action=action,
        status="error",
        payload={"arguments": arguments, "error": payload},
        error_code=error_code or None,
    )


def _needs_credential_preflight(name: Any, arguments: dict[str, Any]) -> bool:
    if name in {
        "ews_create_meeting_confirmed",
        "ews_update_meeting_confirmed",
        "ews_cancel_meeting_confirmed",
    }:
        if arguments.get("confirm") is not True:
            return False
        confirmation_id = str(arguments.get("confirmation_id", "")).strip()
        if not confirmation_id:
            return False
        try:
            if ConfirmationLedger().completed(confirmation_id) is not None:
                return False
        except EwsToolError:
            return False
    return True


def _suppress_known_warnings() -> None:
    warnings.filterwarnings(
        "ignore",
        message="urllib3 v2 only supports OpenSSL.*",
        category=Warning,
    )
    warnings.filterwarnings(
        "ignore",
        message="Cannot convert value '' on field '_start_timezone'.*",
        category=UserWarning,
    )


if __name__ == "__main__":
    main()
