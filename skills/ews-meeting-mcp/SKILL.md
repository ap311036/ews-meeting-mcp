---
name: ews-meeting-mcp
description: Use when scheduling meetings through the local EWS Meeting Agent MCP server, including checking Exchange/EWS availability, suggesting overlapping free slots, previewing invites, and creating meetings after explicit user confirmation.
---

# EWS Meeting Agent

Use the `ews-meeting-mcp` MCP tools to schedule meetings through an on-prem Exchange/EWS calendar.

## Workflow

1. Parse the user's request into attendees, date range, duration, subject, body, and location.
2. Call `ews_suggest_slots` with all attendees. Pass attendees as email addresses.
3. Show the suggested slots to the user. The default scheduling policy starts at `10:00`, ends at `18:00`, and avoids `12:00-14:00`.
4. When the user picks a slot, call `ews_create_meeting_preview`.
5. Show the exact preview: attendees, start, end, subject, body, and location.
6. Only after the user explicitly confirms, call `ews_create_meeting_confirmed` with `confirm: true`.

## Safety

- Never call `ews_create_meeting_confirmed` without explicit user confirmation.
- Do not put EWS passwords in prompts or messages. The MCP server reads credentials from `.env` or environment variables.
- Do not add the organizer as an attendee unless the user explicitly asks; Exchange creates the organizer's calendar item automatically.
- If Outlook does not show a newly created meeting immediately, ask the user to sync or restart Outlook before assuming the event is missing.

## Tool Notes

- Use multiple attendee emails in one `ews_suggest_slots` call.
- Use `ews_get_free_busy` for diagnostics when slot suggestions look surprising.
- Use `ews_list_calendar` to verify whether an event exists on the server calendar.
