from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class MeetingRequest:
    subject: str
    attendees: list[str]
    start: datetime
    end: datetime
    body: str = ""
    location: str = ""

    def validate(self) -> None:
        if not self.subject.strip():
            raise ValueError("subject is required")
        if not self.attendees:
            raise ValueError("at least one attendee is required")
        if self.end <= self.start:
            raise ValueError("end must be after start")


def build_meeting_preview(request: MeetingRequest, *, confirmed: bool) -> dict[str, object]:
    request.validate()
    return {
        "action": "create_meeting" if confirmed else "dry_run",
        "will_send_invites": confirmed,
        "subject": request.subject,
        "attendees": request.attendees,
        "start": request.start.isoformat(),
        "end": request.end.isoformat(),
        "location": request.location,
        "body": request.body,
    }

