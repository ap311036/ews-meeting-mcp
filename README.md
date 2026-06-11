# EWS Meeting MCP

[![npm](https://img.shields.io/npm/v/ews-meeting-mcp?color=blue)](https://www.npmjs.com/package/ews-meeting-mcp)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Node.js >=18](https://img.shields.io/badge/node-%3E%3D18-339933)](package.json)
[![Python](https://img.shields.io/badge/python-3.x-3776AB)](pyproject.toml)

<p align="center">
  <img src="https://raw.githubusercontent.com/ap311036/ews-meeting-mcp/master/docs/assets/ews-meeting-mcp-demo.gif" alt="EWS Meeting MCP demo showing a safe Exchange scheduling flow with setup checks, room-aware slot suggestions, preview confirmation, verification, and audit logging" width="960">
</p>

The MCP server for safely scheduling Outlook meetings on on-prem Exchange EWS.

EWS Meeting MCP gives coding assistants and desktop agents a safe, structured way to read Outlook availability, discover rooms, suggest meeting slots, and create, update, or cancel meetings only after an explicit human confirmation step.

It is built for companies where calendar access is sensitive infrastructure: regulated teams, internal networks, strict security review, legacy Exchange deployments, and organizations that cannot simply hand a cloud agent broad Microsoft 365 permissions. Credentials stay local, write operations are previewed before they touch Exchange, and every confirmed lifecycle action can be traced through a local audit trail.

```bash
npx ews-meeting-mcp
```

## Why This Exists

Many teams still run calendar infrastructure through on-prem Exchange/EWS. General-purpose agents can reason about scheduling, but they should not receive raw passwords, guess attendee addresses, or send calendar invitations without a reviewable checkpoint.

This is not a generic Outlook wrapper or a Microsoft Graph-first calendar connector. It is designed for the stricter enterprise case: local EWS access, room resources, explicit human approval, duplicate-send protection, and audit-friendly meeting lifecycle tools.

This project wraps Exchange calendar operations in a small MCP surface with:

- **Room-aware scheduling**: finds overlapping attendee availability and filters meeting rooms by Exchange discovery or local policy.
- **Human-in-the-loop writes**: create, update, and cancel operations require a preview plus a matching `confirmation_id`.
- **Local-first credential handling**: reads `.env`, shell environment, or macOS Keychain without passing passwords through the model.
- **Structured recovery**: setup failures return machine-readable error codes and user-facing setup commands.
- **Auditability**: lifecycle previews, confirmed actions, duplicate confirmations, in-progress states, and structured errors are written to a local JSONL audit log.
- **Agent-ready instructions**: the MCP server exposes tool descriptions and initialization guidance, and the repo includes a companion skill for agents that support skills.

## What Agents Can Do

| Capability | Tooling | Safety posture |
| --- | --- | --- |
| Check setup and credentials | `ews_setup_check`, `ews_keychain_status` | Never returns the EWS password |
| Set up meeting signatures | `ews_signature_setup_guide` | Returns copyable HTML sample and local env guidance |
| Read calendar availability | `ews_list_calendar`, `ews_get_free_busy`, `ews_find_calendar_events` | Read-only |
| Resolve people and rooms | `ews_resolve_attendees`, `ews_list_rooms` | Uses Exchange directory when available |
| Suggest slots | `ews_suggest_slots` | Applies local workday, avoid windows, and room capacity |
| Create meetings | `ews_create_meeting_preview`, `ews_create_meeting_confirmed` | Requires preview, explicit approval, and matching confirmation id |
| Update meetings | `ews_update_meeting_preview`, `ews_update_meeting_confirmed` | Requires exact EWS item metadata and matching confirmation id |
| Cancel meetings | `ews_cancel_meeting_preview`, `ews_cancel_meeting_confirmed` | Requires exact EWS item metadata and matching confirmation id |
| Verify and audit | `ews_verify_meeting`, `ews_get_audit_log` | Confirms server-side state without exposing credentials |

## Documentation

- [Usage Guide](docs/usage.md): local setup, Keychain, scheduling policy, smoke checks, CLI examples, MCP config, and npm wrapper details.
- [Agent Guide](docs/agent-guide.md): tool contracts, setup checks, attendee resolution, room selection, preview-confirm flows, audit log, and verification rules.
- [Publishing](docs/publishing.md): npm package and GitHub Actions release checklist.

## Quick Start

### 1. Configure EWS

Create a `.env` file in the working directory or provide equivalent environment variables:

```bash
EWS_ENDPOINT=https://mail.company.com/EWS/Exchange.asmx
EWS_EMAIL=your_user@company.com
EWS_USERNAME='DOMAIN\your_user'
EWS_AUTH_TYPE=NTLM
EWS_TIMEZONE=Asia/Taipei
```

Use `EWS_AUTH_TYPE=BASIC` only if IT confirms Basic auth is enabled and the endpoint is protected by HTTPS.

### 2. Store the Password

For local development, `EWS_PASSWORD` works:

```bash
EWS_PASSWORD='your-password'
```

On macOS, Keychain is safer than storing the password in `.env` or MCP client config:

```bash
read -rsp "EWS password: " EWS_PASSWORD
echo
security add-generic-password -U -s ews-meeting-mcp -a 'DOMAIN\your_user' -w "$EWS_PASSWORD"
unset EWS_PASSWORD
```

Then configure:

```bash
EWS_PASSWORD_KEYCHAIN_SERVICE=ews-meeting-mcp
EWS_PASSWORD_KEYCHAIN_ACCOUNT='DOMAIN\your_user'
```

If `EWS_PASSWORD_KEYCHAIN_ACCOUNT` is omitted, `EWS_USERNAME` is used. `EWS_PASSWORD` always takes precedence when it is set.

### 3. Add the MCP Server

For an npm-installed MCP client:

```json
{
  "mcpServers": {
    "ews-meeting-mcp": {
      "command": "npx",
      "args": ["-y", "ews-meeting-mcp@0.1.21"],
      "env": {
        "EWS_ENDPOINT": "https://mail.company.com/EWS/Exchange.asmx",
        "EWS_EMAIL": "your_user@company.com",
        "EWS_USERNAME": "DOMAIN\\your_user",
        "EWS_PASSWORD_KEYCHAIN_SERVICE": "ews-meeting-mcp",
        "EWS_AUTH_TYPE": "NTLM",
        "EWS_TIMEZONE": "Asia/Taipei"
      }
    }
  }
}
```

For a local checkout:

```json
{
  "mcpServers": {
    "ews-meeting-mcp": {
      "command": "/path/to/ews-meeting-mcp/.venv/bin/python",
      "args": ["-m", "ews_meeting_mcp.mcp_server"],
      "cwd": "/path/to/ews-meeting-mcp",
      "env": {
        "PYTHONPATH": "src"
      }
    }
  }
}
```

### Optional: Add an Outlook-Style Signature

Meeting invites append a configured HTML signature by default. Ask the MCP tool for a copyable starter template:

```text
ews_signature_setup_guide
```

Save the returned `sample_html` as `ews-meeting-signature.html` in the MCP working directory, then edit the name, email, title, logo URL, and disclaimer. You can also point to a different file:

```bash
EWS_MEETING_SIGNATURE_HTML_PATH=/path/to/ews-meeting-signature.html
EWS_MEETING_SIGNATURE_ENABLED=true
```

Use an HTTPS logo URL recipients can access, or replace the `<img>` source with a base64 data URI. Set `EWS_MEETING_SIGNATURE_ENABLED=false` to temporarily stop appending the signature.

### 4. Verify Setup

```bash
npx ews-meeting-mcp --cli env
npx ews-meeting-mcp --cli probe
```

The first command prints the configured endpoint and account without printing the password. The second command validates that the account can connect to EWS.

## Agent Workflow

Scheduling should follow this shape:

```text
user request
-> ews_setup_check
-> ews_signature_setup_guide, if the user needs help creating the optional HTML signature
-> ews_resolve_attendees, if names or aliases are provided
-> ews_list_rooms, if a room may be needed
-> ews_suggest_slots
-> user chooses a slot and room
-> ews_create_meeting_preview
-> show exact invite details and confirmation_id
-> user explicitly confirms
-> ews_create_meeting_confirmed with confirm=true and the same confirmation_id
-> ews_verify_meeting, when item id and changekey are available
```

Existing meeting changes should use exact calendar metadata:

```text
user asks to update or cancel a meeting
-> ews_find_calendar_events with the narrowest known time window
-> user chooses one exact event, if more than one candidate exists
-> ews_update_meeting_preview or ews_cancel_meeting_preview
-> show current/proposed details, warnings, and confirmation_id
-> user explicitly confirms
-> matching confirmed tool with confirm=true and the same confirmation_id
```

Agents should never infer an event from subject text when multiple candidates are possible.

## Safety Model

EWS Meeting MCP is designed around a simple rule: reads may be automated, writes must be reviewable.

- Confirmed create, update, and cancel tools refuse to run unless `confirm=true` is passed.
- Confirmed tools require the exact `confirmation_id` returned by the matching preview.
- Confirmed update and cancel tools also require the exact EWS `id` and `changekey` from `ews_find_calendar_events` or a prior verified result.
- Duplicate confirmed requests return `error_code: "duplicate_confirmation"` with prior result metadata instead of calling EWS again.
- In-progress confirmations return `error_code: "confirmation_in_progress"` and should not be blindly retried.
- Preview tools never save, move, delete, or send Exchange notifications.
- The local confirmation ledger and audit log store operation metadata, not EWS passwords.

If `ews_setup_check` returns `ready: false`, an agent should show the returned `user_message` or `setup_command` verbatim and stop. It should not ask for attendee emails or continue scheduling as a workaround.

## Scheduling Policy

By default, scheduling tools look for `ews-meeting-policy.json` in the current working directory. Set `EWS_MEETING_POLICY_FILE` to point at a different file.

If no policy file exists, built-in defaults are used:

- workday: `10:00` to `18:00`
- avoid: `12:00-14:00`
- fallback rooms: `2-11`, `2-13`, `2-14`, `3-1`, `3-2`, `3-4`

Live room selection uses Exchange room-list discovery when available, then falls back to configured rooms.

Example policy:

```json
{
  "workday_start": "10:00",
  "workday_end": "18:00",
  "avoid": ["12:00-14:00"],
  "rooms": [
    {
      "alias": "3-1",
      "name": "3-1 Meeting Room(12P)",
      "email": "3-1MeetingRoom@company.com",
      "capacity": 12
    }
  ]
}
```

Policy rooms are merged with the default fallback rooms by `alias`. A matching alias overrides the default room, and new aliases are appended.

## CLI Usage

The npm wrapper starts the MCP server by default:

```bash
npx ews-meeting-mcp
```

Pass `--cli` to run the Python CLI through the same package:

```bash
npx ews-meeting-mcp --cli env
npx ews-meeting-mcp --cli calendar --days 7
```

Suggest a 30-minute meeting slot:

```bash
npx ews-meeting-mcp --cli suggest \
  --attendee alice@company.com \
  --attendee bob@company.com \
  --start 2026-06-15T09:00:00+08:00 \
  --end 2026-06-19T18:00:00+08:00 \
  --duration-minutes 30 \
  --limit 5
```

Preview a meeting invitation without sending anything:

```bash
npx ews-meeting-mcp --cli create-meeting \
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
npx ews-meeting-mcp --cli create-meeting \
  --attendee alice@company.com \
  --attendee bob@company.com \
  --start 2026-06-15T11:00:00+08:00 \
  --end 2026-06-15T11:30:00+08:00 \
  --subject "Project sync" \
  --body "Discuss next steps" \
  --location "Webex" \
  --confirm
```

The `--confirm` flag is intentionally required. Without it, the command prints a dry-run preview and does not call EWS to create the event.

## Local Development

For detailed setup, smoke tests, CLI examples, and MCP client configuration, see the [Usage Guide](docs/usage.md).

The short development loop is:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
npm test
```

Run the MCP server from a checkout:

```bash
env PYTHONPATH=src python -m ews_meeting_mcp.mcp_server
```

## Companion Skill

The repo includes a companion skill for agents that support skills:

```text
skills/ews-meeting-mcp/SKILL.md
```

See the [Agent Guide](docs/agent-guide.md) for the same workflow in plain Markdown.

## Troubleshooting

Operational troubleshooting lives in the [Usage Guide](docs/usage.md). For agent behavior, setup-check handling, and lifecycle safety, see the [Agent Guide](docs/agent-guide.md).

## Release

See [Publishing](docs/publishing.md).

## License

MIT
