# EWS Meeting MCP Product Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn `ews-meeting-mcp` from a usable internal PoC into a safer product-grade MCP for Exchange/EWS meeting scheduling.

**Architecture:** Keep the current stdio MCP shape and Python core. Add product-grade behavior in small layers: setup diagnostics and structured errors first, then policy/config, dynamic rooms, meeting lifecycle, audit/confirmation safety, and finally live smoke coverage.

**Tech Stack:** Python stdlib + exchangelib, Node wrapper, `unittest`, Node test runner, GitHub Actions/npm publish.

---

## Ordering Rationale

This ordering follows `karpathy-guidelines`: solve the highest-risk foundations first, keep changes surgical, and define verifiable success criteria before coding.

1. **Setup and error foundations** unblock every other feature and prevent agent misdirection.
2. **Policy/config** removes hard-coded org rules before adding more scheduling behavior.
3. **Dynamic rooms** replaces the most brittle hard-coded product data.
4. **Meeting lifecycle** expands side effects only after diagnostics and confirmation gates are stronger.
5. **Audit and confirmation ids** make side effects traceable and protect against double-send.
6. **Post-create verification and live smoke** prove the system works against real EWS without relying only on unit tests.

## Current State

- Current version: `0.1.12`.
- Current MCP tools: `ews_keychain_status`, `ews_probe`, `ews_list_calendar`, `ews_list_rooms`, `ews_resolve_attendees`, `ews_get_free_busy`, `ews_suggest_slots`, `ews_create_meeting_preview`, `ews_create_meeting_confirmed`.
- Current hard-coded room aliases: `2-11`, `2-13`, `2-14`, `3-1`, `3-2`, `3-4`.
- Current safety: `confirm=true` required for confirmed create; EWS-dependent tools preflight Keychain credentials.

## Verification Gates

Run these after every task unless the task explicitly says otherwise:

```bash
env PYTHONPATH=src python3 -m unittest discover -s tests
node --test tests/test_node_wrapper.mjs
npm --cache .npm-cache pack --dry-run
git diff --check
```

For release tasks also run:

```bash
npm --cache .npm-cache pack --pack-destination /private/tmp
TARBALL=$(ls -t /private/tmp/ews-meeting-mcp-*.tgz | head -n 1)
printf '{"jsonrpc":"2.0","id":1,"method":"initialize"}\n{"jsonrpc":"2.0","id":2,"method":"tools/list"}\n' | EWS_MEETING_AGENT_PYTHON=/opt/homebrew/bin/python3 npm --cache /private/tmp/ews-npm-cache-product exec --yes --package "$TARBALL" -- ews-meeting-mcp
```

---

### Task 1: Setup Check and Structured Errors

**Priority:** P0

**Goal:** Add a single diagnostic tool that explains whether the environment is ready, and make tool errors structured enough for agents to route correctly.

**Files:**
- Create: `src/ews_meeting_mcp/errors.py`
- Modify: `src/ews_meeting_mcp/config.py`
- Modify: `src/ews_meeting_mcp/agent_tools.py`
- Modify: `src/ews_meeting_mcp/mcp_server.py`
- Modify: `tests/test_config.py`
- Modify: `tests/test_mcp_server.py`
- Modify: `README.md`
- Modify: `skills/ews-meeting-mcp/SKILL.md`

- [ ] **Step 1: Write failing tests for structured error payloads**

Add tests proving an EWS-dependent tool called without credentials returns JSON with:

```json
{
  "error_code": "credentials_missing",
  "required_action": "show_setup_command",
  "setup_command": "...",
  "user_message": "..."
}
```

Run:

```bash
env PYTHONPATH=src python3 -m unittest tests.test_mcp_server tests.test_config
```

Expected before implementation: failure because `error_code` is missing.

- [ ] **Step 2: Implement `errors.py`**

Create small helpers only:

```python
class EwsToolError(Exception):
    def __init__(self, error_code: str, message: str, **payload: object) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.payload = {"error_code": error_code, "message": message, **payload}
```

Do not refactor all errors yet. Use this for setup/credential paths first.

- [ ] **Step 3: Add `ews_setup_check`**

Add a tool that returns:

```json
{
  "ready": false,
  "checks": [
    {"name": "env:EWS_ENDPOINT", "ok": true},
    {"name": "env:EWS_EMAIL", "ok": true},
    {"name": "env:EWS_USERNAME", "ok": true},
    {"name": "keychain_or_password", "ok": false, "error_code": "credentials_missing"}
  ],
  "next_action": "show_setup_command"
}
```

It must not call EWS unless the basic env and credentials are present. Add MCP schema with empty input.

- [ ] **Step 4: Update skill and README**

Skill must say: before scheduling, call `ews_setup_check`; if `ready=false`, show `user_message` or `setup_command` and stop.

- [ ] **Step 5: Verify**

Run all verification gates.

**Done when:** Missing credentials never produce a request for attendee emails; agents get `error_code` and next action.

---

### Task 2: Policy and Config File

**Priority:** P0

**Goal:** Move default scheduling policy and built-in rooms out of hard-coded tool logic into a local config layer with safe defaults.

**Files:**
- Create: `src/ews_meeting_mcp/policy.py`
- Create: `tests/test_policy.py`
- Modify: `.env.example`
- Modify: `README.md`
- Modify: `src/ews_meeting_mcp/agent_tools.py`
- Modify: `tests/test_agent_tools.py`

- [ ] **Step 1: Write failing policy tests**

Test defaults:

```python
policy.workday_start == "10:00"
policy.workday_end == "18:00"
policy.avoid == ["12:00-14:00"]
```

Test `EWS_MEETING_POLICY_FILE=/path/policy.json` can override these values.

- [ ] **Step 2: Implement `policy.py`**

Use stdlib `json` and `dataclasses`. No dependency. If the file is missing, use defaults. If JSON is invalid, return a structured config error through setup check.

- [ ] **Step 3: Wire scheduling defaults**

`ews_suggest_slots` default arguments should still work, but when arguments are omitted use policy defaults.

- [ ] **Step 4: Document sample policy**

README sample:

```json
{
  "workday_start": "10:00",
  "workday_end": "18:00",
  "avoid": ["12:00-14:00"],
  "rooms": [
    {"alias": "3-1", "name": "3-1 Meeting Room(12P)", "email": "3-1MeetingRoom@example.com", "capacity": 12}
  ]
}
```

- [ ] **Step 5: Verify**

Run all verification gates.

**Done when:** Existing behavior is unchanged without policy file, and local deployments can override policy without publishing a new npm version.

---

### Task 3: Dynamic Room Directory

**Priority:** P1

**Goal:** Add a dynamic room discovery path while preserving static fallback rooms.

**Files:**
- Modify: `src/ews_meeting_mcp/ews_client.py`
- Modify: `src/ews_meeting_mcp/agent_tools.py`
- Modify: `src/ews_meeting_mcp/mcp_server.py`
- Modify: `tests/test_ews_client.py`
- Modify: `tests/test_agent_tools.py`
- Modify: `tests/test_mcp_server.py`
- Modify: `README.md`
- Modify: `skills/ews-meeting-mcp/SKILL.md`

- [ ] **Step 1: Use EWS room-list APIs first**

Use `account.protocol.get_roomlists()` and `account.protocol.get_rooms(room_list)` as the primary dynamic discovery path. Keep `resolve_names` only for user-provided room searches, not for exhaustive discovery, because it is capped and cannot safely page every room.

- [ ] **Step 2: Write failing tests**

Test this public shape:

```python
ews_list_rooms(
    attendee_count=3,
    query="3-",
    room_list="",
    source="auto",  # auto | exchange | static
    limit=100,
)
```

`source="auto"` tries Exchange room lists when credentials are present and falls back to configured/static rooms if dynamic discovery is unavailable or fails with a recoverable EWS error. `source="static"` must remain credential-free.

- [ ] **Step 3: Implement room directory method**

Return normalized rooms:

```json
{"label": "3-1 Meeting Room(12P)", "value": "3-1MeetingRoom@example.com", "alias": "3-1", "name": "3-1 Meeting Room(12P)", "email": "3-1MeetingRoom@example.com", "capacity": 12, "room_list": "Taipei Rooms", "source": "exchange"}
```

Use room email as `value` for dynamic rooms. Static aliases may remain accepted for compatibility.

- [ ] **Step 4: Update MCP schema**

`ews_list_rooms` accepts:

```json
{"attendee_count": 3, "source": "auto", "query": "3-", "room_list": "optional", "limit": 100}
```

- [ ] **Step 5: Verify**

Run all verification gates.

**Done when:** Agents can ask for current meeting-room candidates without depending only on package hard-coding.

---

### Task 4: Meeting Lookup, Update, and Cancel

**Priority:** P1

**Goal:** Add safe lifecycle tools for meetings already created by the organizer.

**Files:**
- Modify: `src/ews_meeting_mcp/ews_client.py`
- Modify: `src/ews_meeting_mcp/agent_tools.py`
- Modify: `src/ews_meeting_mcp/mcp_server.py`
- Modify: `tests/test_ews_client.py`
- Modify: `tests/test_agent_tools.py`
- Modify: `tests/test_mcp_server.py`
- Modify: `README.md`
- Modify: `skills/ews-meeting-mcp/SKILL.md`

- [ ] **Step 1: Write failing schemas tests**

Add tools:

```text
ews_find_calendar_events
ews_update_meeting_preview
ews_update_meeting_confirmed
ews_cancel_meeting_preview
ews_cancel_meeting_confirmed
```

Confirmed tools require `confirm=true`.

- [ ] **Step 2: Implement read-only find with stable item metadata**

Use `account.calendar.view(start, end)` for windowed calendar lookup because it unfolds recurring occurrences. Return `id`, `changekey`, `uid`, `subject`, `start`, `end`, `location`, `organizer`, `required_attendees`, `resources`, `is_meeting`, `is_cancelled`, and recurrence/type metadata when exchangelib exposes it.

Support filters: `subject_contains`, `location_contains`, `organizer_email`, `attendee_email`, and `limit`.

- [ ] **Step 3: Implement previews without EWS side effects**

Preview tools return before/after payloads but never save/delete.

- [ ] **Step 4: Implement confirmed cancel first**

Fetch with exact `id` and `changekey`. For the first implementation, restrict confirmed cancel to non-recurring organizer meetings. Use `move_to_trash(send_meeting_cancellations=...)`, not permanent delete.

- [ ] **Step 5: Implement confirmed update with a small field set**

Fetch with exact `id` and `changekey`, then save only `subject`, `start`, `end`, `location`, and `body` at first. Defer attendee/resource replacement until live smoke verifies Exchange invite semantics.

Use exact EWS item id or a unique search result id. If a search is ambiguous, return `error_code: ambiguous_meeting` with candidates.

- [ ] **Step 6: Verify**

Run all verification gates.

**Done when:** Users can safely change/cancel meetings with preview-confirm flow.

---

### Task 5: Confirmation Id and Anti-Duplicate Send

**Priority:** P1

**Goal:** Prevent accidental repeated sends when an agent retries a confirmed create/update/cancel call.

**Files:**
- Create: `src/ews_meeting_mcp/confirmations.py`
- Create: `tests/test_confirmations.py`
- Modify: `src/ews_meeting_mcp/agent_tools.py`
- Modify: `src/ews_meeting_mcp/mcp_server.py`
- Modify: `tests/test_agent_tools.py`
- Modify: `README.md`
- Modify: `skills/ews-meeting-mcp/SKILL.md`

- [ ] **Step 1: Write failing confirmation tests**

Preview returns a deterministic `confirmation_id` derived from action, subject, attendees, rooms, start, end, body, location.

- [ ] **Step 2: Require confirmation id in confirmed tools**

Confirmed tools require the same `confirmation_id` returned by preview. If missing/mismatched, return `error_code: confirmation_mismatch`.

- [ ] **Step 3: Add lightweight local sent ledger**

Use `EWS_MEETING_AGENT_STATE_DIR` or user cache. Record completed confirmation ids. Replays return `error_code: duplicate_confirmation` and the original result metadata when available.

- [ ] **Step 4: Verify**

Run all verification gates.

**Done when:** Retried confirmed calls cannot silently create duplicate meetings.

---

### Task 6: Audit Log

**Priority:** P2

**Goal:** Record side-effect attempts and outcomes without storing passwords.

**Files:**
- Create: `src/ews_meeting_mcp/audit.py`
- Create: `tests/test_audit.py`
- Modify: `src/ews_meeting_mcp/agent_tools.py`
- Modify: `.gitignore`
- Modify: `README.md`

- [ ] **Step 1: Write failing audit tests**

Confirmed create/update/cancel writes a JSONL event with timestamp, action, confirmation id, attendees, rooms, start/end, result status, and EWS item id when available.

- [ ] **Step 2: Implement audit writer**

Default path under user cache; override with `EWS_MEETING_AUDIT_FILE`.

- [ ] **Step 3: Verify no secrets**

Tests assert password-like env values never appear in audit output.

- [ ] **Step 4: Verify**

Run all verification gates.

**Done when:** Every confirmed side effect is traceable without leaking credentials.

---

### Task 7: Post-Create Verification and Room Response

**Priority:** P2

**Goal:** After create/update, provide a way to verify the calendar item and inspect room response status.

**Files:**
- Modify: `src/ews_meeting_mcp/ews_client.py`
- Modify: `src/ews_meeting_mcp/agent_tools.py`
- Modify: `src/ews_meeting_mcp/mcp_server.py`
- Modify: `tests/test_ews_client.py`
- Modify: `tests/test_agent_tools.py`
- Modify: `tests/test_mcp_server.py`
- Modify: `README.md`

- [ ] **Step 1: Write failing tests**

Add tool:

```text
ews_verify_meeting
```

It accepts EWS item id and returns organizer item status, attendees, rooms, and response status when available.

- [ ] **Step 2: Implement minimal verification**

Fetch by item id and return normalized fields. If room response is not available immediately, return `response_status: "unknown"` instead of failing.

- [ ] **Step 3: Verify**

Run all verification gates.

**Done when:** After sending, the agent can verify the event and report room acceptance state if Exchange exposes it.

---

### Task 8: Live Smoke Suite

**Priority:** P2

**Goal:** Provide manual, opt-in live EWS checks that prove the published package works against real Exchange without accidentally sending real invites.

**Files:**
- Create: `scripts/live_smoke.py`
- Create: `tests/test_live_smoke_script.py`
- Modify: `README.md`
- Modify: `package.json`

- [ ] **Step 1: Write script tests**

Test CLI argument parsing and dry-run defaults without calling EWS.

- [ ] **Step 2: Implement script**

Commands:

```bash
python scripts/live_smoke.py setup
python scripts/live_smoke.py read-only --attendee someone@company.com
python scripts/live_smoke.py create-cancel --attendee self@company.com --confirm-live
```

Default must be read-only. Create/cancel requires `--confirm-live`.

- [ ] **Step 3: Verify**

Run all verification gates.

**Done when:** Maintainers can validate a release against real EWS intentionally and safely.

---

## Release Strategy

- Use patch releases for each stable increment: `0.1.13`, `0.1.14`, ...
- Keep `master` and `develop` synchronized after each publish.
- Do not mark the product-hardening goal complete until every task above has tests, docs, MCP schema, and smoke verification.

## Completion Audit Checklist

- [ ] `ews_setup_check` exists and is documented.
- [ ] Structured error codes exist for credential/setup, ambiguity, EWS auth failure, EWS timeout, invalid time range, confirmation mismatch, duplicate confirmation.
- [ ] Policy/config file support exists with tests.
- [ ] Dynamic room discovery exists with static fallback.
- [ ] Meeting find/update/cancel tools exist with preview-confirm flow.
- [ ] Confirmation ids prevent duplicate side effects.
- [ ] Audit log records confirmed side effects without secrets.
- [ ] Meeting verification reports item and room response status where available.
- [ ] Live smoke suite exists and is read-only by default.
- [ ] Full Python tests, Node tests, pack dry-run, tarball smoke, and npm publish verification pass.
