# EWS Meeting Agent PoC

Small local proof of concept for an internal Outlook/Exchange on-prem calendar agent.

The first phase is intentionally read-only:

- connect to an on-prem EWS endpoint
- list your own upcoming calendar events
- query attendee free/busy
- suggest common meeting slots

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

Use `EWS_AUTH_TYPE=BASIC` only if IT confirms Basic auth is enabled and the endpoint is protected by HTTPS.

## Read-only smoke tests

Run local unit tests:

```bash
env PYTHONPATH=src python3 -m unittest discover -s tests
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

Suggest the nearest overlapping free slots for multiple attendees. By default, `suggest` starts no earlier than `10:00` and avoids `12:00-14:00`:

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

Override the default scheduling rules when needed:

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

- `ews_resolve_attendees(attendees, limit)`
- `ews_get_free_busy(attendees, start, end)`
- `ews_list_my_calendar(start, end)`
- `ews_suggest_meeting_slots(attendees, start, end, duration, constraints)`
- `ews_create_meeting(...)` guarded by human approval
- `ews_update_meeting(...)` guarded by human approval
- `ews_cancel_meeting(...)` guarded by human approval

Do not pass EWS passwords through the LLM. The agent should call a local/internal tool that reads credentials from environment variables, Keychain, Vault, or another secret store.

If a meeting request contains attendee names or aliases instead of complete email addresses, call `ews_resolve_attendees` first and use only the selected resolved emails for availability checks and meeting creation. The scheduling and meeting tools also auto-resolve non-email attendees before calling EWS. If a name is ambiguous or not found, ask the user to choose or provide the exact email before continuing.

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

The server reads EWS credentials from `.env` in the working directory or from environment variables.

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
      "args": ["-y", "ews-meeting-mcp"],
      "cwd": "/path/to/folder/with-env-file"
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

- `ews_probe`
- `ews_list_calendar`
- `ews_get_free_busy`
- `ews_suggest_slots`
- `ews_create_meeting_preview`
- `ews_create_meeting_confirmed`

Agent flow:

```text
User request
-> ews_suggest_slots
-> show candidate slots
-> user chooses one
-> ews_create_meeting_preview
-> user confirms exact invite details
-> ews_create_meeting_confirmed with confirm=true
```

The confirmed tool refuses to create a meeting unless `confirm=true` is passed.

## Skill

A companion skill is included at:

```text
skills/ews-meeting-mcp/SKILL.md
```

Use it as procedural guidance for agents that already have the MCP server configured.
