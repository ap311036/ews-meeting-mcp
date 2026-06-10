---
name: ews-meeting-mcp
description: Use when scheduling meetings through the local EWS Meeting Agent MCP server, including checking Exchange/EWS availability, suggesting overlapping free slots, previewing invites, and creating meetings after explicit user confirmation.
---

# EWS Meeting Agent

Use the `ews-meeting-mcp` MCP tools to schedule meetings through an on-prem Exchange/EWS calendar.

## Workflow

1. Parse the user's request into attendees, candidate rooms, date range, duration, subject, body, and location.
2. If any attendee is not a complete email address, call `ews_resolve_attendees` first.
3. Use exactly resolved emails for scheduling. If a name has zero matches or multiple matches, show the candidates and ask the user to choose before continuing.
4. If the user needs a meeting room, pass candidate room aliases or emails in `rooms` when calling `ews_suggest_slots`. Supported room aliases include `2-11`, `2-13`, `2-14`, `3-1`, `3-2`, and `3-4`.
5. Show suggested slots with their `available_rooms`. The default scheduling policy starts at `10:00`, ends at `18:00`, and avoids `12:00-14:00`.
6. When the user picks a slot and room, call `ews_create_meeting_preview` with the selected room in `rooms`.
7. Show the exact preview: attendees, rooms, start, end, subject, body, and location.
8. Only after the user explicitly confirms, call `ews_create_meeting_confirmed` with `confirm: true`.

## Safety

- Never call `ews_create_meeting_confirmed` without explicit user confirmation.
- Do not put EWS passwords in prompts or messages. The MCP server reads credentials from `.env` or environment variables.
- Do not add the organizer as an attendee unless the user explicitly asks; Exchange creates the organizer's calendar item automatically.
- If Outlook does not show a newly created meeting immediately, ask the user to sync or restart Outlook before assuming the event is missing.

## Tool Notes

- Use `ews_resolve_attendees` whenever the user gives names, aliases, or mixed name/email attendee lists.
- Scheduling and meeting tools also auto-resolve non-email attendees; if they report ambiguity or not found, ask the user to choose or provide the exact email.
- Use multiple attendee emails and candidate room aliases in one `ews_suggest_slots` call.
- To schedule with a room, pass the selected room in `rooms` to both preview and confirmed meeting tools. The room is sent as an Exchange resource, not as a required attendee.
- Use `ews_get_free_busy` for diagnostics when slot suggestions look surprising.
- Use `ews_list_calendar` to verify whether an event exists on the server calendar.
