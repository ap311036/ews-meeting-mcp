from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

from .confirmations import default_state_dir
from .errors import EwsToolError


AUDIT_FILENAME = "audit-log.jsonl"
SENSITIVE_KEY_MARKERS = ("password", "passwd", "secret", "token", "env")


class AuditLog:
    def __init__(self, state_dir: Path | None = None) -> None:
        self.state_dir = state_dir or default_state_dir()
        self.path = self.state_dir / AUDIT_FILENAME

    def append(self, entry: dict[str, Any]) -> None:
        self.state_dir.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, ensure_ascii=False, sort_keys=True, default=str))
            handle.write("\n")

    def read(
        self,
        *,
        limit: int = 50,
        action: str | None = None,
        status: str | None = None,
    ) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []

        entries: list[dict[str, Any]] = []
        try:
            with self.path.open("r", encoding="utf-8") as handle:
                for line in handle:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if not isinstance(entry, dict):
                        continue
                    if action and entry.get("action") != action:
                        continue
                    if status and entry.get("status") != status:
                        continue
                    entries.append(entry)
        except OSError as exc:
            raise EwsToolError(
                "audit_log_unavailable",
                f"Could not read audit log at {self.path}: {exc}",
                required_action="repair_audit_log",
                audit_log_path=str(self.path),
                user_message="本機 audit log 無法讀取；請確認狀態目錄權限或先移除損壞的 audit-log.jsonl。",
            ) from exc

        return entries[-max(1, limit) :]


def record_lifecycle_audit(
    *,
    action: str,
    status: str,
    payload: dict[str, Any] | None = None,
    error_code: str | None = None,
    audit_log: AuditLog | None = None,
) -> dict[str, Any] | None:
    try:
        entry = build_audit_entry(
            action=action,
            status=status,
            payload=payload or {},
            error_code=error_code,
        )
        (audit_log or AuditLog()).append(entry)
    except Exception as exc:
        return {
            "error_code": "audit_log_unavailable",
            "message": f"Could not write audit log: {exc}",
            "required_action": "repair_audit_log",
        }
    return None


def build_audit_entry(
    *,
    action: str,
    status: str,
    payload: dict[str, Any],
    error_code: str | None = None,
) -> dict[str, Any]:
    safe_payload = _redact(payload)
    entry: dict[str, Any] = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "action": action,
        "status": status,
    }
    if error_code:
        entry["error_code"] = error_code

    for key in ["confirmation_id", "id", "changekey", "uid", "subject", "start", "end", "location"]:
        value = _first_value(safe_payload, key)
        if value not in (None, ""):
            entry[key] = value

    attendees = _collect_emails(safe_payload, ("attendees", "required_attendees", "optional_attendees"))
    resources = _collect_emails(safe_payload, ("rooms", "resources"))
    if attendees:
        entry["attendees"] = attendees
    if resources:
        entry["resources"] = resources

    return entry


def read_audit_log(*, limit: int = 50, action: str | None = None, status: str | None = None) -> list[dict[str, Any]]:
    return AuditLog().read(limit=limit, action=action, status=status)


def _redact(value: Any) -> Any:
    if isinstance(value, dict):
        redacted: dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key)
            if any(marker in key_text.lower() for marker in SENSITIVE_KEY_MARKERS):
                redacted[key_text] = "[REDACTED]"
            else:
                redacted[key_text] = _redact(item)
        return redacted
    if isinstance(value, list):
        return [_redact(item) for item in value]
    return value


def _first_value(value: Any, key: str) -> Any:
    if isinstance(value, dict):
        if key in value:
            return value[key]
        for item in value.values():
            found = _first_value(item, key)
            if found not in (None, ""):
                return found
    elif isinstance(value, list):
        for item in value:
            found = _first_value(item, key)
            if found not in (None, ""):
                return found
    return None


def _collect_emails(value: Any, keys: tuple[str, ...]) -> list[str]:
    emails: list[str] = []
    seen: set[str] = set()

    def add(email: Any) -> None:
        text = str(email or "").strip()
        if "@" not in text or text in seen:
            return
        seen.add(text)
        emails.append(text)

    def collect_from(item: Any) -> None:
        if isinstance(item, dict):
            if "email" in item:
                add(item.get("email"))
            for child in item.values():
                collect_from(child)
        elif isinstance(item, list):
            for child in item:
                if isinstance(child, str):
                    add(child)
                else:
                    collect_from(child)

    def find_keyed(item: Any) -> None:
        if isinstance(item, dict):
            for key, child in item.items():
                if str(key) in keys:
                    collect_from(child)
                else:
                    find_keyed(child)
        elif isinstance(item, list):
            for child in item:
                find_keyed(child)

    find_keyed(value)
    return emails
