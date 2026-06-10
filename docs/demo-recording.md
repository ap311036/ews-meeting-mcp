# 60-Second Loom Demo

Use this as a safe recording script for a GitHub README, launch post, or directory submission.

The goal is to show the real repo and a realistic terminal flow without exposing any internal mailbox, room, endpoint, or company data.

## Setup

Open two windows side by side:

- Browser: GitHub README at the top of the repo.
- Terminal: this repo checkout.

Optional terminal command:

```bash
python3 scripts/demo_recording.py
```

Use `--fast` if you want to rehearse quickly:

```bash
python3 scripts/demo_recording.py --fast
```

## Storyboard

### 0-5s: Title

Show the README headline and say:

> This is EWS Meeting MCP: the MCP server for safely scheduling Outlook meetings on on-prem Exchange EWS.

### 5-15s: The Problem

Show the paragraph about strict enterprises and say:

> In security-conscious companies, calendar access is sensitive infrastructure. You often cannot give a cloud agent broad Microsoft 365 permissions, and many teams still run critical scheduling through on-prem Exchange.

### 15-25s: The Ask

Switch to terminal and start the demo script. Say:

> Here is the kind of request an agent can handle: find a 30-minute slot for Alice and Bob this week, with a six-person meeting room.

### 25-40s: The Tool Flow

Let the terminal show:

- `ews_setup_check`
- `ews_resolve_attendees`
- `ews_list_rooms`
- `ews_suggest_slots`

Say:

> The server checks local setup, resolves people through Exchange, finds meeting rooms, and suggests slots. Reads are automated, but credentials stay local.

### 40-52s: Preview Before Write

Pause on the preview payload and say:

> Before anything is sent, the agent must show an exact preview: attendees, room, time, subject, and a confirmation id. No invitation has been created yet.

### 52-60s: Confirm, Verify, Audit

Let the script finish and say:

> Only after explicit confirmation does it create the meeting, verify the calendar item, and record an audit entry. That is the safety boundary enterprises need for agent-driven scheduling.

## Closing Line

Use this for the final screen or post text:

> Credentials stay local. Writes require confirmation. Built for strict enterprise Exchange environments.

## Safe Example Prompt

```text
Find a 30-minute slot for Alice and Bob this week, with a six-person room. Use a safe preview before sending any invitation.
```

## Suggested Post Copy

```text
I built EWS Meeting MCP: the MCP server for safely scheduling Outlook meetings on on-prem Exchange EWS.

It is for teams where calendar access is sensitive infrastructure:
- credentials stay local
- attendee and room lookup use Exchange/EWS
- room-aware slot suggestions
- create/update/cancel require preview + explicit confirmation
- confirmed actions are verifiable and audit-friendly

npx ews-meeting-mcp
https://github.com/ap311036/ews-meeting-mcp
```
