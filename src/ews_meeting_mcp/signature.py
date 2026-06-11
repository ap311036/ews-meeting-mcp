from __future__ import annotations

from pathlib import Path
import os
import shlex
from typing import Any

from .config import load_dotenv


DEFAULT_SIGNATURE_FILENAME = "ews-meeting-signature.html"
SIGNATURE_PATH_ENV = "EWS_MEETING_SIGNATURE_HTML_PATH"
SIGNATURE_ENABLED_ENV = "EWS_MEETING_SIGNATURE_ENABLED"

SAMPLE_SIGNATURE_HTML = """<div style="font-family: Arial, Helvetica, sans-serif; color: #777; font-size: 14px; line-height: 1.35;">
  <p style="margin: 0 0 18px 0; color: #111; font-weight: 700;">Best Regards,</p>
  <p style="margin: 0 0 18px 0; color: #111; font-weight: 700;">游敦翔 Snoop Yu</p>
  <p style="margin: 0 0 14px 0;">
    <strong>LINE Bank Taiwan Limited Channel Web</strong><br>
    11492 台北市瑞光路333號3樓及4樓<br>
    <strong>Email</strong> <a href="mailto:snoop.yu@linebank.com.tw" style="color: #006fc9;">snoop.yu@linebank.com.tw</a>
  </p>
  <p style="margin: 0 0 14px 0;">
    <img src="https://example.com/line-bank-logo.png" alt="LINE Bank" width="153" height="28" style="display: block; border: 0;">
  </p>
  <p style="margin: 0; color: #111; font-size: 12px;">
    本電子郵件(包括任何附件)可能包含連線商業銀行股份有限公司機密資料及資訊，僅提供於特定目的之收件者。
    若您非本郵件指定之收件者，請立即回覆郵件以通知寄件者，並請永久刪除原始傳輸內容(包括任何附件)。
    LINE Bank email and any attachments transmitted with it may contain privileged or confidential information of
    LINE Bank Taiwan Limited, and intended solely for the use of the individual or entity to whom they are addressed.
  </p>
</div>
"""


def append_signature(body: str, body_format: str = "html", *, include_signature: bool = True) -> str:
    return apply_signature(body, body_format, include_signature=include_signature)[0]


def apply_signature(
    body: str,
    body_format: str = "html",
    *,
    include_signature: bool = True,
) -> tuple[str, dict[str, Any]]:
    status = signature_status()
    status["included"] = False

    if not include_signature:
        status["reason"] = "disabled_for_request"
        return body, status
    if not status["enabled"]:
        status["reason"] = "disabled_by_environment"
        return body, status
    if body_format == "text":
        status["reason"] = "text_body_format"
        return body, status
    if body_format != "html":
        raise ValueError("body_format must be html or text")
    if not status["configured"]:
        status["reason"] = "signature_file_missing"
        return body, status

    signature_html = _read_signature_html(Path(str(status["path"]))).strip()
    if not signature_html:
        status["configured"] = False
        status["reason"] = "signature_file_empty"
        return body, status

    separator = '<div class="ews-meeting-signature-separator"></div>'
    if body.strip():
        rendered = f"{body}\n{separator}\n{signature_html}"
    else:
        rendered = signature_html
    status["included"] = True
    status["reason"] = "included"
    return rendered, status


def signature_status() -> dict[str, Any]:
    load_dotenv(Path.cwd() / ".env")
    configured_path = os.environ.get(SIGNATURE_PATH_ENV, "").strip()
    path = Path(configured_path).expanduser() if configured_path else Path.cwd() / DEFAULT_SIGNATURE_FILENAME
    exists = path.exists() and path.is_file()
    enabled = _env_bool(os.environ.get(SIGNATURE_ENABLED_ENV), default=True)
    status: dict[str, Any] = {
        "enabled": enabled,
        "configured": enabled and exists and path.stat().st_size > 0,
        "path": str(path),
        "source": "environment" if configured_path else "default_path",
        "env": {
            SIGNATURE_PATH_ENV: str(path),
            SIGNATURE_ENABLED_ENV: "true" if enabled else "false",
        },
    }
    if status["configured"]:
        status["next_action"] = "ready"
        status["user_message"] = "Meeting HTML signature is configured and will be appended by default."
    else:
        status["next_action"] = "create_signature_file"
        status["user_message"] = (
            "Meeting HTML signature is not configured yet. Use ews_signature_setup_guide, "
            f"create {path}, then restart or reload the MCP server."
        )
    return status


def signature_setup_guide() -> dict[str, Any]:
    default_path = Path.cwd() / DEFAULT_SIGNATURE_FILENAME
    quoted_path = shlex.quote(str(default_path))
    setup_command = "\n".join(
        [
            f"cat > {quoted_path} <<'HTML'",
            SAMPLE_SIGNATURE_HTML.rstrip(),
            "HTML",
            f"export {SIGNATURE_PATH_ENV}={quoted_path}",
            f"export {SIGNATURE_ENABLED_ENV}=true",
        ]
    )
    return {
        "default_enabled": True,
        "recommended_path": str(default_path),
        "env": {
            SIGNATURE_PATH_ENV: str(default_path),
            SIGNATURE_ENABLED_ENV: "true",
        },
        "sample_html": SAMPLE_SIGNATURE_HTML,
        "setup_command": setup_command,
        "notes": [
            "Copy sample_html into the recommended path, then edit the name, title, email, logo URL, and disclaimer.",
            "Use an HTTPS logo URL that meeting recipients can access, or replace the img tag with a base64 data URI.",
            f"Set {SIGNATURE_ENABLED_ENV}=false to temporarily stop appending the signature.",
        ],
    }


def _read_signature_html(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _env_bool(value: str | None, *, default: bool) -> bool:
    if value is None or not value.strip():
        return default
    return value.strip().lower() not in {"0", "false", "no", "off"}
