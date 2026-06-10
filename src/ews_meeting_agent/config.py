from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import subprocess


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
        endpoint = _required("EWS_ENDPOINT")
        email = _required("EWS_EMAIL")
        username = _required("EWS_USERNAME")
        return cls(
            endpoint=endpoint,
            email=email,
            username=username,
            password=_password(username=username, email=email),
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


def _password(*, username: str, email: str) -> str:
    value = os.environ.get("EWS_PASSWORD")
    if value:
        return value

    service = os.environ.get("EWS_PASSWORD_KEYCHAIN_SERVICE", "ews-meeting-mcp")
    account = os.environ.get("EWS_PASSWORD_KEYCHAIN_ACCOUNT", username or email)
    command = [
        "security",
        "find-generic-password",
        "-s",
        service,
        "-a",
        account,
        "-w",
    ]
    try:
        result = subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
        )
    except (FileNotFoundError, subprocess.CalledProcessError) as error:
        raise RuntimeError(
            "Missing EWS_PASSWORD and failed to read macOS Keychain item "
            f"for service {service!r} and account {account!r}."
        ) from error

    password = result.stdout.strip()
    if not password:
        raise RuntimeError(
            "Missing EWS_PASSWORD and macOS Keychain returned an empty password "
            f"for service {service!r} and account {account!r}."
        )
    return password


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
