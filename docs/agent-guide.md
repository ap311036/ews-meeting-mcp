# Agent Guide

Use this guide when wiring EWS Meeting MCP into an assistant or coding agent.

## Available Tools

- `ews_setup_check()`
- `ews_keychain_status()`
- `ews_get_audit_log(limit, action, status)`
- `ews_probe()`
- `ews_list_rooms(attendee_count, query, room_list, source, limit)`
- `ews_resolve_attendees(attendees, limit)`
- `ews_get_free_busy(attendees, start, end)`
- `ews_list_calendar(days)`
- `ews_find_calendar_events(start, end, subject_contains, location_contains, organizer_email, attendee_email, limit)`
- `ews_verify_meeting(id, changekey)`
- `ews_suggest_slots(attendees, rooms, require_room, start, end, duration_minutes, constraints)`
- `ews_create_meeting_preview(...)`
- `ews_create_meeting_confirmed(...)`, guarded by human approval and `confirmation_id`
- `ews_update_meeting_preview(...)`
- `ews_update_meeting_confirmed(...)`, guarded by human approval and `confirmation_id`
- `ews_cancel_meeting_preview(...)`
- `ews_cancel_meeting_confirmed(...)`, guarded by human approval and `confirmation_id`

## Session Setup

Do not pass EWS passwords through the LLM.

At the start of a scheduling session, call `ews_setup_check`. If it returns `ready: false`, show the returned `user_message` as-is, or show `setup_command` verbatim in a fenced shell block, and stop. Do not ask for attendee emails or continue scheduling as a workaround. After the user says they ran the setup command or fixed the environment, call `ews_setup_check` again before continuing.

`ews_setup_check` reports machine-readable setup failures such as `error_code: "credentials_missing"` and `next_action: "show_setup_command"` or `next_action: "fix_mcp_env"`. It also reports malformed local policy JSON as `error_code: "policy_invalid_json"` with `required_action: "fix_policy_file"`.

`ews_keychain_status` remains available when you only need to inspect whether the password is coming from `EWS_PASSWORD` or macOS Keychain without revealing it.

The MCP server also preflights credential-required EWS tools. If an agent accidentally calls `ews_resolve_attendees`, `ews_get_free_busy`, `ews_suggest_slots`, or another live EWS tool before credentials are available, the server returns a structured setup payload instead of continuing. Preview calls that need directory resolution can also return the same structured setup payload from inside the tool.

## Attendee Resolution

If a meeting request contains attendee names or aliases instead of complete email addresses, call `ews_resolve_attendees` first and use only the selected resolved emails for availability checks and meeting creation.

The scheduling and meeting tools also auto-resolve non-email attendees before calling EWS. If a name is ambiguous or not found, ask the user to choose or provide the exact email before continuing.

## Room Selection

If the user needs to choose a room, call `ews_list_rooms` first and present its structured `options`.

By default, `source: "auto"` tries Exchange dynamic room lists via EWS and falls back to configured policy rooms when credentials or room-list discovery are unavailable.

Use `source: "static"` for a credential-free list from local policy/configured rooms. Use `source: "exchange"` when the user explicitly needs live Exchange room lists and should see a structured recoverable error if discovery fails.

Dynamic room options use the room email as `value`. Static fallback options keep aliases such as `3-1` as `value` for compatibility.

If a meeting requires a specific room, pass candidate room values or emails to `ews_suggest_slots` in `rooms`. If the user wants any suitable room, call `ews_suggest_slots` with `require_room: true` and omit `rooms`; the tool uses dynamic Exchange rooms when available, then falls back to configured rooms, and filters rooms with known capacity below the attendee count.

Room name suffixes such as `(6P)` mean six persons. Suggestions include `available_rooms`, and the selected room should be passed to the preview and confirmed meeting tools in `rooms` so Exchange books it as a resource.

## New Meeting Flow

```text
User request
-> ews_suggest_slots
-> show candidate slots
-> user chooses one
-> ews_create_meeting_preview
-> show exact invite details plus confirmation_id
-> user confirms exact invite details
-> ews_create_meeting_confirmed with confirm=true and confirmation_id
```

For new meetings, call `ews_create_meeting_preview`, show the exact invite details and returned `confirmation_id`, then call `ews_create_meeting_confirmed` only after explicit user approval with `confirm: true` and the same `confirmation_id`.

Recurring meetings are supported only during creation. Pass a structured `recurrence` object to both preview and confirmed create calls, and show the preview `recurrence` before asking for confirmation. Weekly Monday/Wednesday means:

```json
{
  "type": "weekly",
  "interval": 1,
  "weekdays": ["MO", "WE"],
  "range": {"type": "numbered", "count": 10}
}
```

Business days mean Monday through Friday, without holiday or makeup-day handling. "Every business day until 7/26" means:

```json
{
  "type": "weekly",
  "interval": 1,
  "weekdays": ["MO", "TU", "WE", "TH", "FR"],
  "range": {"type": "end_date", "end_date": "2026-07-26"}
}
```

If the user says only "every Monday and Wednesday" without an end date, occurrence count, or explicit no-end choice, ask for one before previewing.

Confirmed create, update, and cancel operations are recorded in a small local confirmation ledger under `EWS_MEETING_MCP_STATE_DIR` when set, or the user's local state/cache directory otherwise. The older `EWS_MEETING_AGENT_STATE_DIR` name is still accepted for compatibility. The ledger stores operation metadata only, not passwords.

If a confirmed tool returns `error_code: "duplicate_confirmation"`, treat the prior operation as already handled, inspect `prior_result`, and do not retry blindly.

## Meeting Body Handling

Meeting bodies default to `body_format: "html"`. If the body is plain text, the tool safely converts it to simple HTML, preserves line breaks, escapes raw markup, and turns `http://` or `https://` URLs such as PRD or Wiki links into clickable anchors.

Agents may pass intentional HTML directly, or set `body_format: "text"` when a plain text body is explicitly required.

## Audit Log

Lifecycle-sensitive preview, confirmed, duplicate, in-progress, and structured error outcomes are appended to a local JSON Lines audit log named `audit-log.jsonl` in the same state directory.

The audit log stores meeting metadata such as confirmation id, item id/changekey/uid, subject, time, location, attendees, resources, and structured error codes. It does not store EWS passwords or raw environment values.

Use `ews_get_audit_log(limit, action, status)` to inspect recent entries without reading the file manually. Audit write failures are best-effort warnings and do not block meeting preview/create/update/cancel operations.

## Verification

After a confirmed create or update, call `ews_verify_meeting` with the returned EWS item `id` and `changekey` when available.

It reads the organizer calendar item and returns normalized attendees, rooms/resources, and `response_status` values. Room response status can be `unknown` immediately after creation if Exchange has not exposed the room mailbox response yet; treat that as pending/unknown, not as verification failure.

## Existing Meeting Update or Cancel Flow

```text
User asks to change or cancel an existing meeting
-> ews_find_calendar_events with a narrow time window and filters
-> user chooses one exact event if there is more than one candidate
-> ews_update_meeting_preview or ews_cancel_meeting_preview
-> show current/proposed details or cancellation target plus confirmation_id
-> user confirms exact action
-> matching confirmed tool with confirm=true and confirmation_id
```

For meetings that already exist, start with `ews_find_calendar_events` over a narrow time window.

Use the exact `id` and `changekey` from one search result. Do not infer an item from subject text when multiple candidates are possible.

To change a meeting, call `ews_update_meeting_preview` with the exact item metadata and only supported fields: `subject`, `start`, `end`, `location`, and `body`. Show the returned `current_event`, `proposed_event`, `warnings`, and `confirmation_id`, then call `ews_update_meeting_confirmed` only after explicit user approval with `confirm: true` and the matching `confirmation_id`.

To cancel a meeting, use the same preview-confirm pattern with `ews_cancel_meeting_preview` and `ews_cancel_meeting_confirmed`. Confirmed cancel moves the item to trash and sends meeting cancellations by default. The first cancel implementation is intentionally limited to non-recurring organizer meetings when Exchange exposes those fields.

## Companion Skill

A companion skill is included at:

```text
skills/ews-meeting-mcp/SKILL.md
```

Use it as procedural guidance for agents that already have the MCP server configured.
