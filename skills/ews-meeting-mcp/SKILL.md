---
name: ews-meeting-mcp
description: Use when scheduling meetings through the local EWS Meeting Agent MCP server, including checking Exchange/EWS availability, suggesting overlapping free slots, previewing invites, and creating meetings after explicit user confirmation.
---

# EWS Meeting Agent

Use the `ews-meeting-mcp` MCP tools to schedule meetings through an on-prem Exchange/EWS calendar.

## Workflow

1. At the start of a scheduling session, call `ews_keychain_status`. If it returns `required_action: "show_setup_command"` or `configured: false`, show its `setup_command` verbatim in a fenced `bash` block and stop. Do not summarize it as "set EWS_PASSWORD or Keychain"; do not continue with EWS tools until the user says they ran it. Then call `ews_keychain_status` again before continuing.
2. Parse the user's request into attendees, candidate rooms, date range, duration, subject, body, and location.
3. If any attendee is not a complete email address, call `ews_resolve_attendees` first.
4. Use exactly resolved emails for scheduling. If a name has zero matches or multiple matches, show the candidates and ask the user to choose before continuing.
5. If the user did not mention rooms, call `ews_list_rooms` with the attendee count if known, then ask whether a meeting room is needed using the returned `options`. Offer the user a choice among the returned room `value`s or "no specific room"; do not rely on a hand-written room list.
6. If the user wants a room but does not choose a specific room, call `ews_suggest_slots` with `require_room: true` and no `rooms`; the tool searches all built-in rooms and filters rooms with known `capacity` below the attendee count. `P` means persons.
7. If the user chooses specific rooms, pass the selected room `value`s or emails in `rooms` when calling `ews_suggest_slots`.
8. Show suggested slots with their `available_rooms`. The default scheduling policy starts at `10:00`, ends at `18:00`, and avoids `12:00-14:00`.
9. When the user picks a slot and room, call `ews_create_meeting_preview` with the selected room in `rooms`.
10. Show the exact preview: attendees, rooms, start, end, subject, body, and location.
11. Only after the user explicitly confirms, call `ews_create_meeting_confirmed` with `confirm: true`.

## Safety

- Never call `ews_create_meeting_confirmed` without explicit user confirmation.
- Do not put EWS passwords in prompts or messages. The MCP server reads credentials from `.env`, environment variables, or macOS Keychain.
- Do not add the organizer as an attendee unless the user explicitly asks; Exchange creates the organizer's calendar item automatically.
- If Outlook does not show a newly created meeting immediately, ask the user to sync or restart Outlook before assuming the event is missing.

## Tool Notes

- Use `ews_resolve_attendees` whenever the user gives names, aliases, or mixed name/email attendee lists.
- Use `ews_keychain_status` before the first EWS operation in a session. It never returns the password. If it returns `setup_command`, show that exact command verbatim.
- If any EWS tool returns `required_action: "show_setup_command"`, show the returned `setup_command` verbatim and do not ask the user for attendee email addresses as a workaround.
- Use `ews_list_rooms` to present structured meeting-room choices before asking the user to choose a room.
- Scheduling and meeting tools also auto-resolve non-email attendees; if they report ambiguity or not found, ask the user to choose or provide the exact email.
- Use multiple attendee emails and candidate room aliases in one `ews_suggest_slots` call.
- Use `require_room: true` when the user wants a room but does not specify which room.
- To schedule with a room, pass the selected room in `rooms` to both preview and confirmed meeting tools. The room is sent as an Exchange resource, not as a required attendee.
- Use `ews_get_free_busy` for diagnostics when slot suggestions look surprising.
- Use `ews_list_calendar` to verify whether an event exists on the server calendar.
