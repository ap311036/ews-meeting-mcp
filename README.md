# EWS Meeting Agent PoC

Small local proof of concept for an internal Outlook/Exchange on-prem calendar agent.

The first phase is intentionally read-only:

- connect to an on-prem EWS endpoint
- list your own upcoming calendar events
- query attendee free/busy
- suggest common meeting slots with optional room availability

Creating, updating, or canceling meetings should be added only after the read-only checks pass, and should require explicit human confirmation before sending any invitation.

## Setup

```bash
cd work/ews-meeting-mcp
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

If you already have a virtualenv, update dependencies after pulling a new version:

```bash
source .venv/bin/activate
python -m pip install --upgrade -r requirements.txt
```

Edit `.env`:

```bash
EWS_ENDPOINT=https://mail.company.com/EWS/Exchange.asmx
EWS_EMAIL=your_user@company.com
EWS_USERNAME='DOMAIN\your_user'
EWS_PASSWORD='your-password'
EWS_AUTH_TYPE=NTLM
EWS_TIMEZONE=Asia/Taipei
```

The CLI auto-loads `.env` from the current directory. Environment variables already present in the shell take precedence.

## Local scheduling policy

By default, the MCP scheduling tools look for `ews-meeting-policy.json` in the current working directory. Set `EWS_MEETING_POLICY_FILE` to point at a different file. If no policy file exists, the built-in defaults are unchanged: workday `10:00` to `18:00`, avoid `12:00-14:00`, and fallback room aliases `2-11`, `2-13`, `2-14`, `3-1`, `3-2`, and `3-4`. Live room selection uses Exchange room-list discovery when available, then falls back to these configured rooms.

Example `ews-meeting-policy.json`:

```json
{
  "workday_start": "10:00",
  "workday_end": "18:00",
  "avoid": ["12:00-14:00"],
  "rooms": [
    {
      "alias": "3-1",
      "name": "3-1 Meeting Room(12P)",
      "email": "3-1MeetingRoom@linebank.com.tw",
      "capacity": 12
    }
  ]
}
```

Policy rooms are merged with the default fallback rooms by `alias`. A matching alias overrides the default room, and new aliases are appended.

On macOS, you can keep the password in Keychain instead of `.env` or `mcp.json`:

```bash
read -rsp "EWS password: " EWS_PASSWORD
echo
security add-generic-password -U -s ews-meeting-mcp -a 'DOMAIN\your_user' -w "$EWS_PASSWORD"
unset EWS_PASSWORD
```

Then omit `EWS_PASSWORD`. The tool will read Keychain using:

```bash
EWS_PASSWORD_KEYCHAIN_SERVICE=ews-meeting-mcp
EWS_PASSWORD_KEYCHAIN_ACCOUNT='DOMAIN\your_user'
```

If `EWS_PASSWORD_KEYCHAIN_ACCOUNT` is omitted, `EWS_USERNAME` is used. `EWS_PASSWORD` always takes precedence when it is set.

Use `EWS_AUTH_TYPE=BASIC` only if IT confirms Basic auth is enabled and the endpoint is protected by HTTPS.

## Read-only smoke tests

Run local unit tests:

```bash
env PYTHONPATH=src python3 -m unittest discover -s tests
```

Run opt-in live smoke checks against the configured EWS account:

```bash
npm run live-smoke -- setup
npm run live-smoke -- read-only --attendee someone@company.com
```

The live smoke script is read-only unless you explicitly choose the create/cancel path. This path creates a short live meeting and immediately cancels it, and refuses to run without `--confirm-live`:

```bash
npm run live-smoke -- create-cancel --attendee self@company.com --confirm-live
```

Show configured endpoint and account, without printing the password:

```bash
python -m ews_meeting_agent.cli env
```

Connect and read your mailbox root:

```bash
python -m ews_meeting_agent.cli probe
```

List your own calendar events:

```bash
python -m ews_meeting_agent.cli calendar --days 7
```

If `calendar` fails with `UnknownTimeZone: No time zone found with key CST`, make sure `.env` contains:

```bash
EWS_TIMEZONE=Asia/Taipei
```

Query free/busy for colleagues:

```bash
python -m ews_meeting_agent.cli freebusy \
  --attendee alice@company.com \
  --attendee bob@company.com \
  --start 2026-06-10T09:00:00+08:00 \
  --end 2026-06-10T18:00:00+08:00
```

Suggest 30-minute meeting slots inside business hours:

```bash
python -m ews_meeting_agent.cli suggest \
  --attendee alice@company.com \
  --attendee bob@company.com \
  --start 2026-06-10T09:00:00+08:00 \
  --end 2026-06-12T18:00:00+08:00 \
  --duration-minutes 30
```

Suggest the nearest overlapping free slots for multiple attendees. By default, CLI `suggest` starts no earlier than `10:00` and avoids `12:00-14:00`:

```bash
python -m ews_meeting_agent.cli suggest \
  --attendee alice@company.com \
  --attendee bob@company.com \
  --attendee carol@company.com \
  --start 2026-06-15T09:00:00+08:00 \
  --end 2026-06-19T18:00:00+08:00 \
  --duration-minutes 30 \
  --limit 5
```

Override the default scheduling rules for a single CLI request when needed:

```bash
python -m ews_meeting_agent.cli suggest \
  --attendee alice@company.com \
  --attendee bob@company.com \
  --start 2026-06-15T09:00:00+08:00 \
  --end 2026-06-19T18:00:00+08:00 \
  --duration-minutes 30 \
  --workday-start 10:00 \
  --workday-end 18:00 \
  --avoid 12:00-14:00
```

Preview a meeting invitation without sending anything:

```bash
python -m ews_meeting_agent.cli create-meeting \
  --attendee alice@company.com \
  --attendee bob@company.com \
  --start 2026-06-15T11:00:00+08:00 \
  --end 2026-06-15T11:30:00+08:00 \
  --subject "Project sync" \
  --body "Discuss next steps" \
  --location "Webex"
```

Actually create the meeting and send invitations:

```bash
python -m ews_meeting_agent.cli create-meeting \
  --attendee alice@company.com \
  --attendee bob@company.com \
  --start 2026-06-15T11:00:00+08:00 \
  --end 2026-06-15T11:30:00+08:00 \
  --subject "Project sync" \
  --body "Discuss next steps" \
  --location "Webex" \
  --confirm
```

The `--confirm` flag is intentionally required. Without it, the command only prints a dry-run preview and does not call EWS to create the event.

## Agent boundary

Available and recommended tools for the agent:

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
- `ews_create_meeting_confirmed(...)` guarded by human approval and `confirmation_id`
- `ews_update_meeting_preview(...)`
- `ews_update_meeting_confirmed(...)` guarded by human approval and `confirmation_id`
- `ews_cancel_meeting_preview(...)`
- `ews_cancel_meeting_confirmed(...)` guarded by human approval and `confirmation_id`

Do not pass EWS passwords through the LLM. At the start of a scheduling session, the agent should call `ews_setup_check`. If it returns `ready: false`, show the returned `user_message` as-is, or show `setup_command` verbatim in a fenced shell block, and stop. Do not ask for attendee emails or continue scheduling as a workaround. After the user says they ran the setup command or fixed the environment, call `ews_setup_check` again before continuing.

`ews_setup_check` reports machine-readable setup failures such as `error_code: "credentials_missing"` and `next_action: "show_setup_command"` or `next_action: "fix_mcp_env"`. It also reports malformed local policy JSON as `error_code: "policy_invalid_json"` with `required_action: "fix_policy_file"`. `ews_keychain_status` remains available when you only need to inspect whether the password is coming from `EWS_PASSWORD` or macOS Keychain without revealing it.

The MCP server also preflights credential-required EWS tools. If an agent accidentally calls `ews_resolve_attendees`, `ews_get_free_busy`, `ews_suggest_slots`, or another live EWS tool before credentials are available, the server returns a structured setup payload instead of continuing. Preview calls that need directory resolution can also return the same structured setup payload from inside the tool.

If a meeting request contains attendee names or aliases instead of complete email addresses, call `ews_resolve_attendees` first and use only the selected resolved emails for availability checks and meeting creation. The scheduling and meeting tools also auto-resolve non-email attendees before calling EWS. If a name is ambiguous or not found, ask the user to choose or provide the exact email before continuing.

If the user needs to choose a room, call `ews_list_rooms` first and present its structured `options`. By default, `source: "auto"` tries Exchange dynamic room lists via EWS and falls back to configured policy rooms when credentials or room-list discovery are unavailable. Use `source: "static"` for a credential-free list from local policy/configured rooms, or `source: "exchange"` when the user explicitly needs live Exchange room lists and should see a structured recoverable error if discovery fails. Dynamic room options use the room email as `value`; static fallback options keep aliases such as `3-1` as `value` for compatibility. If a meeting requires a specific room, pass candidate room values or emails to `ews_suggest_slots` in `rooms`. If the user wants any suitable room, call `ews_suggest_slots` with `require_room: true` and omit `rooms`; the tool uses dynamic Exchange rooms when available, then falls back to configured rooms, and filters rooms with known capacity below the attendee count. Room name suffixes such as `(6P)` mean six persons. Suggestions include `available_rooms`, and the selected room should be passed to the preview and confirmed meeting tools in `rooms` so Exchange books it as a resource.

For new meetings, call `ews_create_meeting_preview`, show the exact invite details and returned `confirmation_id`, then call `ews_create_meeting_confirmed` only after explicit user approval with `confirm: true` and the same `confirmation_id`. Confirmed create, update, and cancel operations are recorded in a small local confirmation ledger under `EWS_MEETING_AGENT_STATE_DIR` when set, or the user's local state/cache directory otherwise. The ledger stores operation metadata only, not passwords. If a confirmed tool returns `error_code: "duplicate_confirmation"`, treat the prior operation as already handled, inspect `prior_result`, and do not retry blindly.

Lifecycle-sensitive preview, confirmed, duplicate, in-progress, and structured error outcomes are also appended to a local JSON Lines audit log named `audit-log.jsonl` in the same state directory. The audit log stores meeting metadata such as confirmation id, item id/changekey/uid, subject, time, location, attendees, resources, and structured error codes; it does not store EWS passwords or raw environment values. Use `ews_get_audit_log(limit, action, status)` to inspect recent entries without reading the file manually. Audit write failures are best-effort warnings and do not block meeting preview/create/update/cancel operations.

After a confirmed create or update, call `ews_verify_meeting` with the returned EWS item `id` and `changekey` when available. It reads the organizer calendar item and returns normalized attendees, rooms/resources, and `response_status` values. Room response status can be `unknown` immediately after creation if Exchange has not exposed the room mailbox response yet; treat that as pending/unknown, not as verification failure.

For meetings that already exist, start with `ews_find_calendar_events` over a narrow time window. Use the exact `id` and `changekey` from one search result; do not infer an item from subject text when multiple candidates are possible. To change a meeting, call `ews_update_meeting_preview` with the exact item metadata and only supported fields (`subject`, `start`, `end`, `location`, `body`), show the returned `current_event`, `proposed_event`, `warnings`, and `confirmation_id`, then call `ews_update_meeting_confirmed` only after explicit user approval with `confirm: true` and the matching `confirmation_id`. To cancel a meeting, use the same preview-confirm pattern with `ews_cancel_meeting_preview` and `ews_cancel_meeting_confirmed`; confirmed cancel moves the item to trash and sends meeting cancellations by default. The first cancel implementation is intentionally limited to non-recurring organizer meetings when Exchange exposes those fields.

## MCP server

This package includes a dependency-light stdio MCP server:

```bash
cd ~/work/ews-meeting-mcp
source .venv/bin/activate
env PYTHONPATH=src python -m ews_meeting_agent.mcp_server
```

Example MCP config:

```json
{
  "mcpServers": {
    "ews-meeting-mcp": {
      "command": "/Users/snoopyu/work/ews-meeting-mcp/.venv/bin/python",
      "args": ["-m", "ews_meeting_agent.mcp_server"],
      "cwd": "/Users/snoopyu/work/ews-meeting-mcp",
      "env": {
        "PYTHONPATH": "src"
      }
    }
  }
}
```

The server reads EWS credentials from `.env` in the working directory, from environment variables, or from macOS Keychain when `EWS_PASSWORD` is not set.

## npx / npm package

The npm wrapper starts the MCP server by default:

```bash
npx ews-meeting-mcp
```

It can also run the Python CLI:

```bash
npx ews-meeting-mcp --cli env
npx ews-meeting-mcp --cli suggest \
  --attendee alice@company.com \
  --attendee bob@company.com \
  --start 2026-06-15T09:00:00+08:00 \
  --end 2026-06-19T18:00:00+08:00
```

On first run, the wrapper creates a Python virtualenv in the user's cache directory and installs `requirements.txt`. To use an existing Python or venv instead:

```bash
EWS_MEETING_AGENT_PYTHON=/path/to/.venv/bin/python npx ews-meeting-mcp
```

To control the bootstrap cache location:

```bash
EWS_MEETING_AGENT_CACHE_DIR=/path/to/cache npx ews-meeting-mcp
```

MCP config for an npm-published package:

```json
{
  "mcpServers": {
    "ews-meeting-mcp": {
      "command": "npx",
      "args": ["-y", "ews-meeting-mcp@0.1.13"],
      "env": {
        "EWS_ENDPOINT": "https://mail.company.com/EWS/Exchange.asmx",
        "EWS_EMAIL": "your_user@company.com",
        "EWS_USERNAME": "DOMAIN\\your_user",
        "EWS_PASSWORD_KEYCHAIN_SERVICE": "ews-meeting-mcp",
        "EWS_MEETING_POLICY_FILE": "/Users/snoopyu/work/ews-meeting-policy.json",
        "EWS_AUTH_TYPE": "NTLM",
        "EWS_TIMEZONE": "Asia/Taipei"
      }
    }
  }
}
```

Publish checklist:

```bash
npm pack --dry-run
npm login
npm publish --access public
```

GitHub Actions release flow:

1. Create an npm automation token with publish access.
2. Add it to the GitHub repository secrets as `NPM_TOKEN`.
3. Bump `package.json` version locally.
4. Commit and push to `master`.
5. Create and push a matching tag, for example:

```bash
git tag v0.1.1
git push origin master v0.1.1
```

The workflow validates Python tests, Node wrapper tests, and `npm pack --dry-run` before publishing. It also checks that `vX.Y.Z` matches `package.json` version and skips publishing if that version already exists on npm.

You can also run the workflow manually from GitHub Actions. Manual runs validate by default; set `publish=true` to publish.

Before publishing, choose the final npm package name. For internal company use, prefer a scoped name or a private registry, for example `@your-org/ews-meeting-mcp`.

Available MCP tools:

- `ews_setup_check`
- `ews_keychain_status`
- `ews_get_audit_log`
- `ews_probe`
- `ews_list_calendar`
- `ews_find_calendar_events`
- `ews_verify_meeting`
- `ews_get_free_busy`
- `ews_suggest_slots`
- `ews_create_meeting_preview`
- `ews_create_meeting_confirmed`
- `ews_update_meeting_preview`
- `ews_update_meeting_confirmed`
- `ews_cancel_meeting_preview`
- `ews_cancel_meeting_confirmed`

Agent flow:

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

Existing meeting update/cancel flow:

```text
User asks to change or cancel an existing meeting
-> ews_find_calendar_events with a narrow time window and filters
-> user chooses one exact event if there is more than one candidate
-> ews_update_meeting_preview or ews_cancel_meeting_preview
-> show current/proposed details or cancellation target plus confirmation_id
-> user confirms exact action
-> matching confirmed tool with confirm=true and confirmation_id
```

Confirmed tools refuse to create, update, or cancel meetings unless `confirm=true` is passed. Create, update, and cancel confirmations also require the exact `confirmation_id` from the matching preview. If a confirmed operation already completed, the duplicate confirmation guard returns `error_code: "duplicate_confirmation"` with prior result metadata instead of calling EWS again.

## Skill

A companion skill is included at:

```text
skills/ews-meeting-mcp/SKILL.md
```

Use it as procedural guidance for agents that already have the MCP server configured.
