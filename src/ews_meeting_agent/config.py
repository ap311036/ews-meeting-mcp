from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import shlex
import subprocess
from typing import Any

from .errors import EwsToolError


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
        raise EwsToolError(
            "credentials_missing",
            f"Missing required environment variable: {name}",
            required_action="fix_mcp_env",
            setup_command=_env_setup_command([name]),
            user_message=(
                f"EWS setup is missing {name}. Add it to the MCP environment or .env "
                "before scheduling meetings."
            ),
        )
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
        raise EwsToolError(
            "credentials_missing",
            "Missing EWS_PASSWORD and failed to read macOS Keychain item "
            f"for service {service!r} and account {account!r}.",
            required_action="show_setup_command",
            setup_command=_keychain_setup_command(service=service, account=account),
            user_message=_keychain_user_message(service=service, account=account),
        ) from error

    password = result.stdout.strip()
    if not password:
        raise EwsToolError(
            "credentials_missing",
            "Missing EWS_PASSWORD and macOS Keychain returned an empty password "
            f"for service {service!r} and account {account!r}.",
            required_action="show_setup_command",
            setup_command=_keychain_setup_command(service=service, account=account),
            user_message=_keychain_user_message(service=service, account=account),
        )
    return password


def setup_check() -> dict[str, Any]:
    load_dotenv(Path.cwd() / ".env")
    checks: list[dict[str, Any]] = []
    missing_env: list[str] = []
    for name in ["EWS_ENDPOINT", "EWS_EMAIL", "EWS_USERNAME"]:
        ok = bool(os.environ.get(name))
        check: dict[str, Any] = {"name": f"env:{name}", "ok": ok}
        if not ok:
            check["error_code"] = "credentials_missing"
            missing_env.append(name)
        checks.append(check)

    if missing_env:
        setup_command = _env_setup_command(missing_env)
        return {
            "ready": False,
            "checks": [*checks, _password_check_without_keychain_lookup()],
            "error_code": "credentials_missing",
            "next_action": "fix_mcp_env",
            "required_action": "fix_mcp_env",
            "setup_command": setup_command,
            "user_message": (
                "EWS setup is missing required environment variables: "
                f"{', '.join(missing_env)}. Add them to the MCP environment or .env before scheduling meetings.\n\n"
                f"```bash\n{setup_command}\n```"
            ),
        }

    credential_status = keychain_status()
    password_check: dict[str, Any] = {
        "name": "keychain_or_password",
        "ok": bool(credential_status.get("configured")),
        "source": credential_status.get("source", "missing"),
    }
    if not credential_status.get("configured"):
        password_check["error_code"] = "credentials_missing"
    checks.append(password_check)

    if credential_status.get("configured"):
        return {
            "ready": True,
            "checks": checks,
            "next_action": "ready",
            "user_message": "EWS setup is ready.",
        }

    payload = {
        "ready": False,
        "checks": checks,
        "error_code": "credentials_missing",
        "next_action": credential_status.get("required_action", "show_setup_command"),
    }
    for key in ["required_action", "setup_command", "user_message"]:
        if key in credential_status:
            payload[key] = credential_status[key]
    return payload


def keychain_status() -> dict[str, Any]:
    load_dotenv(Path.cwd() / ".env")
    username = os.environ.get("EWS_USERNAME", "")
    email = os.environ.get("EWS_EMAIL", "")
    service = os.environ.get("EWS_PASSWORD_KEYCHAIN_SERVICE", "ews-meeting-mcp")
    account = os.environ.get("EWS_PASSWORD_KEYCHAIN_ACCOUNT", username or email)

    status: dict[str, Any] = {
        "configured": False,
        "source": "missing",
        "service": service,
        "account": account,
    }
    if os.environ.get("EWS_PASSWORD"):
        status.update({"configured": True, "source": "environment"})
        return status

    if not account:
        status["message"] = (
            "Set EWS_USERNAME or EWS_PASSWORD_KEYCHAIN_ACCOUNT before checking Keychain."
        )
        status["error_code"] = "credentials_missing"
        status["required_action"] = "fix_mcp_env"
        status["setup_command"] = _env_setup_command(["EWS_USERNAME"])
        status["user_message"] = (
            "EWS setup is missing EWS_USERNAME or EWS_PASSWORD_KEYCHAIN_ACCOUNT. "
            "Set one of them before checking Keychain."
        )
        return status

    try:
        result = _run_keychain_lookup(service=service, account=account)
    except (FileNotFoundError, subprocess.CalledProcessError):
        _add_keychain_setup(status, service=service, account=account)
        return status

    if result.stdout.strip():
        status.update({"configured": True, "source": "keychain"})
    else:
        _add_keychain_setup(status, service=service, account=account)
    return status


def _run_keychain_lookup(*, service: str, account: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            "security",
            "find-generic-password",
            "-s",
            service,
            "-a",
            account,
            "-w",
        ],
        check=True,
        capture_output=True,
        text=True,
    )


def _keychain_setup_command(*, service: str, account: str) -> str:
    quoted_service = shlex.quote(service)
    quoted_account = shlex.quote(account)
    return "\n".join(
        [
            'printf "EWS password: "',
            "stty -echo",
            "read EWS_PASSWORD",
            "stty echo",
            'printf "\\n"',
            (
                "security add-generic-password -U "
                f"-s {quoted_service} -a {quoted_account} -w \"$EWS_PASSWORD\""
            ),
            "unset EWS_PASSWORD",
        ]
    )


def _env_setup_command(names: list[str]) -> str:
    return "\n".join(f"export {name}=..." for name in names)


def _password_check_without_keychain_lookup() -> dict[str, Any]:
    if os.environ.get("EWS_PASSWORD"):
        return {"name": "keychain_or_password", "ok": True, "source": "environment"}

    account = os.environ.get("EWS_PASSWORD_KEYCHAIN_ACCOUNT") or os.environ.get("EWS_USERNAME") or os.environ.get("EWS_EMAIL")
    if account:
        return {
            "name": "keychain_or_password",
            "ok": False,
            "checked": False,
            "source": "not_checked",
            "message": "Keychain lookup is skipped until required EWS environment variables are configured.",
        }

    return {"name": "keychain_or_password", "ok": False, "source": "missing", "error_code": "credentials_missing"}


def _keychain_user_message(*, service: str, account: str) -> str:
    setup_command = _keychain_setup_command(service=service, account=account)
    return (
        "EWS 密碼還沒有設定在 macOS Keychain。請顯示並執行下面這段指令，"
        "讓使用者在終端機輸入密碼。不要要求使用者把密碼貼到聊天或 mcp.json。\n\n"
        f"```bash\n{setup_command}\n```"
    )


def _add_keychain_setup(status: dict[str, Any], *, service: str, account: str) -> None:
    setup_command = _keychain_setup_command(service=service, account=account)
    status["error_code"] = "credentials_missing"
    status["required_action"] = "show_setup_command"
    status["setup_command"] = setup_command
    status["user_message"] = _keychain_user_message(service=service, account=account)


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
