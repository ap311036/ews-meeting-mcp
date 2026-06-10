from __future__ import annotations

import json
import sys
import traceback
import warnings
from typing import Any, Callable

from . import agent_tools


SERVER_INFO = {"name": "ews-meeting-mcp", "version": "0.1.10"}

TOOL_HANDLERS: dict[str, Callable[..., Any]] = {
    "ews_keychain_status": agent_tools.ews_keychain_status,
    "ews_probe": agent_tools.ews_probe,
    "ews_list_calendar": agent_tools.ews_list_calendar,
    "ews_list_rooms": agent_tools.ews_list_rooms,
    "ews_resolve_attendees": agent_tools.ews_resolve_attendees,
    "ews_get_free_busy": agent_tools.ews_get_free_busy,
    "ews_suggest_slots": agent_tools.ews_suggest_slots,
    "ews_create_meeting_preview": agent_tools.ews_create_meeting_preview,
    "ews_create_meeting_confirmed": agent_tools.ews_create_meeting_confirmed,
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
                    "Resolve non-email attendee names with ews_resolve_attendees before scheduling. "
                    "Use ews_suggest_slots with resolved email addresses and candidate rooms when a room "
                    "is needed. Before sending invitations, show the preview from "
                    "ews_create_meeting_preview and ask the user to confirm."
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

    try:
        result = handler(**arguments)
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
        "location": {"type": "string", "default": ""},
    }
    required = ["subject", "attendees", "start", "end"]
    if include_confirm:
        properties["confirm"] = {
            "type": "boolean",
            "description": "Must be true. The tool refuses to create meetings unless confirm=true.",
        }
        required.append("confirm")
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
                "description": "When true and rooms is empty, search all built-in rooms and filter by capacity.",
            },
            "duration_minutes": {"type": "integer", "default": 30, "minimum": 1},
            "limit": {"type": "integer", "default": 5, "minimum": 1},
            "workday_start": {"type": "string", "default": "10:00"},
            "workday_end": {"type": "string", "default": "18:00"},
            "avoid": {
                "type": "array",
                "items": {"type": "string"},
                "default": ["12:00-14:00"],
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
                "or macOS Keychain without revealing the password."
            ),
            "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
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
            "name": "ews_list_rooms",
            "description": "List built-in meeting room choices as structured options for user selection.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "attendee_count": {
                        "type": "integer",
                        "minimum": 1,
                        "description": "Optional attendee count used to hide rooms with known insufficient capacity.",
                    }
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
                "candidate meeting rooms. Defaults to 10:00-18:00 and avoids 12:00-14:00."
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
                "the exact attendees, time, subject, body, and location. Requires confirm=true."
            ),
            "inputSchema": _meeting_schema(include_confirm=True),
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
