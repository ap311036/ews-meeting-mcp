from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import html
import re


URL_RE = re.compile(r"https?://[^\s<>'\"]+")


@dataclass(frozen=True)
class MeetingRequest:
    subject: str
    attendees: list[str]
    start: datetime
    end: datetime
    body: str = ""
    body_format: str = "html"
    location: str = ""
    rooms: list[str] | None = None

    def validate(self) -> None:
        if not self.subject.strip():
            raise ValueError("subject is required")
        if not self.attendees:
            raise ValueError("at least one attendee is required")
        if self.end <= self.start:
            raise ValueError("end must be after start")
        if self.body_format not in {"html", "text"}:
            raise ValueError("body_format must be html or text")


def build_meeting_preview(request: MeetingRequest, *, confirmed: bool) -> dict[str, object]:
    request.validate()
    return {
        "action": "create_meeting" if confirmed else "dry_run",
        "will_send_invites": confirmed,
        "subject": request.subject,
        "attendees": request.attendees,
        "rooms": request.rooms or [],
        "start": request.start.isoformat(),
        "end": request.end.isoformat(),
        "location": request.location,
        "body": request.body,
        "body_format": request.body_format,
    }


def render_body_for_format(body: str, body_format: str = "html") -> str:
    if body_format == "text":
        return body
    if body_format != "html":
        raise ValueError("body_format must be html or text")
    if not body.strip():
        return ""
    if _looks_like_html(body):
        return body
    return _plain_text_to_html(body)


def _looks_like_html(body: str) -> bool:
    return body.lstrip().startswith("<") and re.search(r"</?[a-zA-Z][^>]*>", body) is not None


def _plain_text_to_html(body: str) -> str:
    normalized = body.replace("\r\n", "\n").replace("\r", "\n")
    paragraphs = re.split(r"\n{2,}", normalized.strip())
    return "\n".join(f"<p>{_link_and_escape(paragraph).replace(chr(10), '<br>')}</p>" for paragraph in paragraphs)


def _link_and_escape(text: str) -> str:
    rendered: list[str] = []
    cursor = 0
    for match in URL_RE.finditer(text):
        rendered.append(html.escape(text[cursor : match.start()]))
        url = match.group(0)
        escaped_url = html.escape(url, quote=True)
        rendered.append(f'<a href="{escaped_url}">{escaped_url}</a>')
        cursor = match.end()
    rendered.append(html.escape(text[cursor:]))
    return "".join(rendered)
