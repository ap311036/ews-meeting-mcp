# Usage Guide

This guide contains the operational details that are intentionally kept out of the product-style README.

## Local Setup

```bash
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

Use `EWS_AUTH_TYPE=BASIC` only if IT confirms Basic auth is enabled and the endpoint is protected by HTTPS.

## macOS Keychain

You can keep the password in Keychain instead of `.env` or `mcp.json`:

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

## Scheduling Policy

By default, MCP scheduling tools look for `ews-meeting-policy.json` in the current working directory. Set `EWS_MEETING_POLICY_FILE` to point at a different file.

If no policy file exists, the built-in defaults are:

- workday: `10:00` to `18:00`
- avoid: `12:00-14:00`
- fallback room aliases: `2-11`, `2-13`, `2-14`, `3-1`, `3-2`, and `3-4`

Live room selection uses Exchange room-list discovery when available, then falls back to configured rooms.

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
      "email": "3-1MeetingRoom@example.com",
      "capacity": 12
    }
  ]
}
```

Policy rooms are merged with the default fallback rooms by `alias`. A matching alias overrides the default room, and new aliases are appended.

## CLI Smoke Checks

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

## Python CLI

Show configured endpoint and account, without printing the password:

```bash
python -m ews_meeting_mcp.cli env
```

Connect and read your mailbox root:

```bash
python -m ews_meeting_mcp.cli probe
```

List your own calendar events:

```bash
python -m ews_meeting_mcp.cli calendar --days 7
```

If `calendar` fails with `UnknownTimeZone: No time zone found with key CST`, make sure `.env` contains:

```bash
EWS_TIMEZONE=Asia/Taipei
```

Query free/busy for colleagues:

```bash
python -m ews_meeting_mcp.cli freebusy \
  --attendee alice@company.com \
  --attendee bob@company.com \
  --start 2026-06-10T09:00:00+08:00 \
  --end 2026-06-10T18:00:00+08:00
```

Suggest 30-minute meeting slots inside business hours:

```bash
python -m ews_meeting_mcp.cli suggest \
  --attendee alice@company.com \
  --attendee bob@company.com \
  --start 2026-06-10T09:00:00+08:00 \
  --end 2026-06-12T18:00:00+08:00 \
  --duration-minutes 30
```

Suggest the nearest overlapping free slots for multiple attendees. By default, CLI `suggest` starts no earlier than `10:00` and avoids `12:00-14:00`:

```bash
python -m ews_meeting_mcp.cli suggest \
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
python -m ews_meeting_mcp.cli suggest \
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
python -m ews_meeting_mcp.cli create-meeting \
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
python -m ews_meeting_mcp.cli create-meeting \
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

## MCP Server

This package includes a dependency-light stdio MCP server:

```bash
source .venv/bin/activate
env PYTHONPATH=src python -m ews_meeting_mcp.mcp_server
```

Example MCP config for a local checkout:

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

The server reads EWS credentials from `.env` in the working directory, environment variables, or macOS Keychain when `EWS_PASSWORD` is not set.

## NPM Package

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

On first run, the wrapper creates a Python virtualenv in the user's cache directory and installs `requirements.txt`. To use an existing Python or virtualenv instead:

```bash
EWS_MEETING_MCP_PYTHON=/path/to/.venv/bin/python npx ews-meeting-mcp
```

To control the bootstrap cache location:

```bash
EWS_MEETING_MCP_CACHE_DIR=/path/to/cache npx ews-meeting-mcp
```

The older `EWS_MEETING_AGENT_PYTHON` and `EWS_MEETING_AGENT_CACHE_DIR` names are still accepted for compatibility.

MCP config for an npm-published package:

```json
{
  "mcpServers": {
    "ews-meeting-mcp": {
      "command": "npx",
      "args": ["-y", "ews-meeting-mcp@0.1.19"],
      "env": {
        "EWS_ENDPOINT": "https://mail.company.com/EWS/Exchange.asmx",
        "EWS_EMAIL": "your_user@company.com",
        "EWS_USERNAME": "DOMAIN\\your_user",
        "EWS_PASSWORD_KEYCHAIN_SERVICE": "ews-meeting-mcp",
        "EWS_MEETING_POLICY_FILE": "/path/to/ews-meeting-policy.json",
        "EWS_AUTH_TYPE": "NTLM",
        "EWS_TIMEZONE": "Asia/Taipei"
      }
    }
  }
}
```
