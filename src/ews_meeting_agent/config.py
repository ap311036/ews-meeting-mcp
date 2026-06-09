from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path


@dataclass(frozen=True)
class EwsConfig:
    endpoint: str
    email: str
    username: str
    password: str
    auth_type: str = "NTLM"
    timezone: str = "Asia/Taipei"

    @classmethod
    def from_env(cls) -> "EwsConfig":
        load_dotenv(Path.cwd() / ".env")
        return cls(
            endpoint=_required("EWS_ENDPOINT"),
            email=_required("EWS_EMAIL"),
            username=_required("EWS_USERNAME"),
            password=_required("EWS_PASSWORD"),
            auth_type=os.environ.get("EWS_AUTH_TYPE", "NTLM").upper(),
            timezone=os.environ.get("EWS_TIMEZONE", "Asia/Taipei"),
        )

    def redacted(self) -> dict[str, str]:
        return {
            "EWS_ENDPOINT": self.endpoint,
            "EWS_EMAIL": self.email,
            "EWS_USERNAME": self.username,
            "EWS_PASSWORD": "***",
            "EWS_AUTH_TYPE": self.auth_type,
            "EWS_TIMEZONE": self.timezone,
        }


def _required(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def load_dotenv(path: Path) -> None:
    if not path.exists():
        return

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        name, value = line.split("=", 1)
        name = name.strip()
        value = value.strip()
        if not name or name in os.environ:
            continue

        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        os.environ[name] = value
