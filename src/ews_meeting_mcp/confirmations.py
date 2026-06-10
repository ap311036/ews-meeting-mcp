from __future__ import annotations

from datetime import datetime, timezone
from contextlib import contextmanager
import json
import os
from pathlib import Path
from typing import Any

from .errors import EwsToolError


LEDGER_FILENAME = "confirmation-ledger.json"


def confirmation_id(action: str, payload: dict[str, Any]) -> str:
    import hashlib

    canonical = json.dumps(
        {"action": action, "payload": payload},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def default_state_dir() -> Path:
    configured = (
        os.environ.get("EWS_MEETING_MCP_STATE_DIR", "").strip()
        or os.environ.get("EWS_MEETING_AGENT_STATE_DIR", "").strip()
    )
    if configured:
        return Path(configured).expanduser()

    xdg_state_home = os.environ.get("XDG_STATE_HOME", "").strip()
    if xdg_state_home:
        return Path(xdg_state_home).expanduser() / "ews-meeting-mcp"

    if os.name == "posix" and os.uname().sysname == "Darwin":
        return Path.home() / "Library" / "Application Support" / "ews-meeting-mcp"

    return Path.home() / ".local" / "state" / "ews-meeting-mcp"


class ConfirmationLedger:
    def __init__(self, state_dir: Path | None = None) -> None:
        self.state_dir = state_dir or default_state_dir()
        self.path = self.state_dir / LEDGER_FILENAME

    def completed(self, id: str) -> dict[str, Any] | None:
        with self._locked():
            entry = self._load().get("completed", {}).get(id)
        return dict(entry) if isinstance(entry, dict) else None

    def reserve(self, *, id: str, action: str) -> None:
        with self._locked():
            data = self._load()
            completed = data.setdefault("completed", {})
            pending = data.setdefault("pending", {})
            if not isinstance(completed, dict):
                completed = {}
                data["completed"] = completed
            if not isinstance(pending, dict):
                pending = {}
                data["pending"] = pending

            existing_completed = completed.get(id)
            if isinstance(existing_completed, dict):
                raise _duplicate_confirmation(id, existing_completed)

            existing_pending = pending.get(id)
            if isinstance(existing_pending, dict):
                raise EwsToolError(
                    "confirmation_in_progress",
                    "This confirmation_id is already reserved by another in-flight operation.",
                    required_action="wait_or_check_calendar",
                    next_action="wait_or_check_calendar",
                    confirmation_id=id,
                    reserved_at=existing_pending.get("reserved_at"),
                    user_message=(
                        "這個 confirmation_id 正在處理中。請稍等一下或檢查行事曆，"
                        "不要直接重送同一個邀請或更新。"
                    ),
                )

            pending[id] = {
                "confirmation_id": id,
                "action": action,
                "reserved_at": datetime.now(timezone.utc).isoformat(),
            }
            self._save(data)

    def release(self, id: str) -> None:
        with self._locked():
            data = self._load()
            pending = data.get("pending")
            if isinstance(pending, dict) and id in pending:
                del pending[id]
                self._save(data)

    def record_completed(self, *, id: str, action: str, result: dict[str, Any]) -> dict[str, Any]:
        with self._locked():
            data = self._load()
            completed = data.setdefault("completed", {})
            pending = data.setdefault("pending", {})
            if not isinstance(completed, dict):
                completed = {}
                data["completed"] = completed
            if not isinstance(pending, dict):
                pending = {}
                data["pending"] = pending
            entry = {
                "confirmation_id": id,
                "action": action,
                "completed_at": datetime.now(timezone.utc).isoformat(),
                "result": _json_safe(result),
            }
            completed[id] = entry
            pending.pop(id, None)
            self._save(data)
        return dict(entry)

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"version": 1, "completed": {}, "pending": {}}
        try:
            with self.path.open("r", encoding="utf-8") as handle:
                data = json.load(handle)
        except (OSError, json.JSONDecodeError) as exc:
            raise EwsToolError(
                "confirmation_ledger_unavailable",
                f"Could not read confirmation ledger at {self.path}: {exc}",
                required_action="repair_confirmation_ledger",
                next_action="repair_confirmation_ledger",
                ledger_path=str(self.path),
                user_message=(
                    "本機 confirmation ledger 無法讀取；為避免重複送出會議邀請，"
                    "請先修復或移除這個 ledger 檔案後再重試。"
                ),
            ) from exc
        if not isinstance(data, dict):
            return {"version": 1, "completed": {}, "pending": {}}
        data.setdefault("version", 1)
        if not isinstance(data.get("completed"), dict):
            data["completed"] = {}
        if not isinstance(data.get("pending"), dict):
            data["pending"] = {}
        return data

    def _save(self, data: dict[str, Any]) -> None:
        try:
            self.state_dir.mkdir(parents=True, exist_ok=True)
            tmp_path = self.path.with_suffix(".tmp")
            with tmp_path.open("w", encoding="utf-8") as handle:
                json.dump(data, handle, ensure_ascii=False, indent=2, sort_keys=True, default=str)
                handle.write("\n")
            tmp_path.replace(self.path)
        except OSError as exc:
            raise EwsToolError(
                "confirmation_ledger_unavailable",
                f"Could not write confirmation ledger at {self.path}: {exc}",
                required_action="repair_confirmation_ledger",
                next_action="repair_confirmation_ledger",
                ledger_path=str(self.path),
                user_message=(
                    "本機 confirmation ledger 無法寫入；為避免重複送出會議邀請，"
                    "請先修復 ledger 目錄權限後再重試。"
                ),
            ) from exc

    @contextmanager
    def _locked(self) -> Any:
        try:
            self.state_dir.mkdir(parents=True, exist_ok=True)
            lock_path = self.state_dir / f"{LEDGER_FILENAME}.lock"
            lock = lock_path.open("a+", encoding="utf-8")
        except OSError as exc:
            raise EwsToolError(
                "confirmation_ledger_unavailable",
                f"Could not open confirmation ledger lock in {self.state_dir}: {exc}",
                required_action="repair_confirmation_ledger",
                next_action="repair_confirmation_ledger",
                ledger_path=str(self.path),
                user_message=(
                    "本機 confirmation ledger 無法鎖定；為避免重複送出會議邀請，"
                    "請先修復 ledger 目錄權限後再重試。"
                ),
            ) from exc

        with lock:
            try:
                import fcntl

                fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            except ImportError:
                pass
            try:
                yield
            finally:
                try:
                    import fcntl

                    fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
                except ImportError:
                    pass


def _json_safe(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False, default=str))


def _duplicate_confirmation(id: str, entry: dict[str, Any]) -> EwsToolError:
    return EwsToolError(
        "duplicate_confirmation",
        "This confirmation_id was already completed. Do not retry the Exchange operation blindly.",
        required_action="do_not_retry",
        next_action="treat_as_already_handled",
        confirmation_id=id,
        prior_result=entry.get("result"),
        completed_at=entry.get("completed_at"),
        user_message="這個 confirmation_id 已經成功處理過；請視為已處理，不要直接重送邀請或更新。",
    )
