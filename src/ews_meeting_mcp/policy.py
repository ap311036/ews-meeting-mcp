from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from .config import load_dotenv
from .errors import EwsToolError


POLICY_FILE_ENV = "EWS_MEETING_POLICY_FILE"
DEFAULT_POLICY_FILE = "ews-meeting-policy.json"

DEFAULT_WORKDAY_START = "10:00"
DEFAULT_WORKDAY_END = "18:00"
DEFAULT_AVOID = ["12:00-14:00"]

DEFAULT_ROOMS = [
    {"alias": "2-11", "name": "2-11 Meeting Room", "email": "2-11MeetingRoom@example.com"},
    {"alias": "2-13", "name": "2-13 Meeting Room", "email": "2-13MeetingRoom@example.com"},
    {"alias": "2-14", "name": "2-14 Meeting Room", "email": "2-14MeetingRoom@example.com"},
    {
        "alias": "3-1",
        "name": "3-1 Meeting Room(12P)",
        "email": "3-1MeetingRoom@example.com",
        "capacity": 12,
    },
    {
        "alias": "3-2",
        "name": "3-2 Meeting Room(6P)",
        "email": "3-2MeetingRoom@example.com",
        "capacity": 6,
    },
    {
        "alias": "3-4",
        "name": "3-4 Meeting Room(6P)",
        "email": "3-4MeetingRoom@example.com",
        "capacity": 6,
    },
]


@dataclass(frozen=True)
class MeetingPolicy:
    workday_start: str
    workday_end: str
    avoid: List[str]
    rooms: List[Dict[str, Any]]


def load_policy(path: Optional[str] = None) -> MeetingPolicy:
    load_dotenv(Path.cwd() / ".env")
    policy_path = _policy_path(path)
    if not os.path.exists(policy_path):
        return _default_policy()

    try:
        with open(policy_path, "r", encoding="utf-8") as handle:
            raw_policy = json.load(handle)
    except json.JSONDecodeError as error:
        raise EwsToolError(
            "policy_invalid_json",
            f"Invalid JSON in EWS meeting policy file: {policy_path}",
            required_action="fix_policy_file",
            next_action="fix_policy_file",
            policy_file=policy_path,
            user_message=(
                f"EWS meeting policy file is not valid JSON: {policy_path}. "
                "Fix or remove the file before scheduling meetings."
            ),
        ) from error

    if not isinstance(raw_policy, dict):
        raw_policy = {}

    return MeetingPolicy(
        workday_start=_string_value(raw_policy.get("workday_start"), DEFAULT_WORKDAY_START),
        workday_end=_string_value(raw_policy.get("workday_end"), DEFAULT_WORKDAY_END),
        avoid=_string_list(raw_policy.get("avoid"), DEFAULT_AVOID),
        rooms=_merge_rooms(_default_rooms(), _policy_rooms(raw_policy.get("rooms"))),
    )


def _policy_path(path: Optional[str]) -> str:
    if path:
        return path
    configured = os.environ.get(POLICY_FILE_ENV)
    if configured:
        return configured
    return os.path.join(os.getcwd(), DEFAULT_POLICY_FILE)


def _default_policy() -> MeetingPolicy:
    return MeetingPolicy(
        workday_start=DEFAULT_WORKDAY_START,
        workday_end=DEFAULT_WORKDAY_END,
        avoid=list(DEFAULT_AVOID),
        rooms=_default_rooms(),
    )


def _default_rooms() -> List[Dict[str, Any]]:
    return [dict(room) for room in DEFAULT_ROOMS]


def _string_value(value: object, default: str) -> str:
    return value if isinstance(value, str) and value else default


def _string_list(value: object, default: List[str]) -> List[str]:
    if not isinstance(value, list):
        return list(default)
    strings = [item for item in value if isinstance(item, str)]
    return strings


def _policy_rooms(value: object) -> List[Dict[str, Any]]:
    if not isinstance(value, list):
        return []

    rooms: List[Dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        alias = item.get("alias")
        name = item.get("name")
        email = item.get("email")
        if not isinstance(alias, str) or not isinstance(name, str) or not isinstance(email, str):
            continue
        room: Dict[str, Any] = {"alias": alias, "name": name, "email": email}
        capacity = item.get("capacity")
        if isinstance(capacity, int):
            room["capacity"] = capacity
        rooms.append(room)
    return rooms


def _merge_rooms(defaults: List[Dict[str, Any]], policy_rooms: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    merged = [dict(room) for room in defaults]
    index_by_alias = {str(room.get("alias", "")).lower(): index for index, room in enumerate(merged)}

    for room in policy_rooms:
        alias_key = str(room["alias"]).lower()
        if alias_key in index_by_alias:
            merged[index_by_alias[alias_key]] = dict(room)
            continue
        index_by_alias[alias_key] = len(merged)
        merged.append(dict(room))
    return merged
