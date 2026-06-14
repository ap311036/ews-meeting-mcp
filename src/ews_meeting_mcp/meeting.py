from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
import html
import re
from typing import Any


URL_RE = re.compile(r"https?://[^\s<>'\"]+")
WEEKDAY_VALUES = ("MO", "TU", "WE", "TH", "FR", "SA", "SU")


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
    recurrence: dict[str, Any] | None = None

    def validate(self) -> None:
        if not self.subject.strip():
            raise ValueError("subject is required")
        if not self.attendees:
            raise ValueError("at least one attendee is required")
        if self.end <= self.start:
            raise ValueError("end must be after start")
        if self.body_format not in {"html", "text"}:
            raise ValueError("body_format must be html or text")
        if self.recurrence is not None:
            normalize_recurrence(self.recurrence)


def build_meeting_preview(request: MeetingRequest, *, confirmed: bool) -> dict[str, object]:
    request.validate()
    preview: dict[str, object] = {
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
    if request.recurrence is not None:
        preview["recurrence"] = normalize_recurrence(request.recurrence)
    return preview


def normalize_recurrence(recurrence: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(recurrence, dict):
        raise ValueError("recurrence must be an object")
    recurrence_type = str(recurrence.get("type", "")).strip().lower()
    if recurrence_type != "weekly":
        raise ValueError("recurrence.type must be weekly")

    try:
        interval = int(recurrence.get("interval", 1))
    except (TypeError, ValueError) as exc:
        raise ValueError("recurrence.interval must be an integer") from exc
    if interval < 1:
        raise ValueError("recurrence.interval must be at least 1")

    weekdays = recurrence.get("weekdays")
    if not isinstance(weekdays, list) or not weekdays:
        raise ValueError("recurrence.weekdays must contain at least one weekday")
    normalized_weekdays: list[str] = []
    seen: set[str] = set()
    for weekday in weekdays:
        value = str(weekday).strip().upper()
        if value not in WEEKDAY_VALUES:
            raise ValueError("recurrence.weekdays must use MO, TU, WE, TH, FR, SA, or SU")
        if value not in seen:
            seen.add(value)
            normalized_weekdays.append(value)

    recurrence_range = recurrence.get("range")
    if not isinstance(recurrence_range, dict):
        raise ValueError("recurrence.range is required")
    range_type = str(recurrence_range.get("type", "")).strip().lower()
    normalized_range: dict[str, Any] = {"type": range_type}
    if range_type == "end_date":
        end_date = str(recurrence_range.get("end_date", "")).strip()
        if not end_date:
            raise ValueError("recurrence.range.end_date is required")
        try:
            date.fromisoformat(end_date)
        except ValueError as exc:
            raise ValueError("recurrence.range.end_date must be YYYY-MM-DD") from exc
        normalized_range["end_date"] = end_date
    elif range_type == "numbered":
        try:
            count = int(recurrence_range.get("count"))
        except (TypeError, ValueError) as exc:
            raise ValueError("recurrence.range.count must be an integer") from exc
        if count < 1:
            raise ValueError("recurrence.range.count must be at least 1")
        normalized_range["count"] = count
    elif range_type == "no_end":
        pass
    else:
        raise ValueError("recurrence.range.type must be end_date, numbered, or no_end")

    return {
        "type": "weekly",
        "interval": interval,
        "weekdays": normalized_weekdays,
        "range": normalized_range,
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
