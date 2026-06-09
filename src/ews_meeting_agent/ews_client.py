from __future__ import annotations

from datetime import datetime, timedelta
import re
from typing import Any
from zoneinfo import ZoneInfo

from .config import EwsConfig
from .meeting import MeetingRequest
from .scheduler import TimeBlock


class EwsClient:
    def __init__(self, config: EwsConfig) -> None:
        self.config = config
        self._account = None

    @property
    def account(self) -> Any:
        if self._account is None:
            self._account = self._build_account()
        return self._account

    def probe(self) -> dict[str, str]:
        account = self.account
        return {
            "primary_smtp_address": str(account.primary_smtp_address),
            "root_folder": str(account.root),
        }

    def list_calendar(self, start: datetime, end: datetime, *, limit: int = 20) -> list[dict[str, str]]:
        start = self._to_ews_datetime(start)
        end = self._to_ews_datetime(end)
        items = (
            self.account.calendar.view(start=start, end=end)
            .only("subject", "start", "end", "location")
            .order_by("start")
        )
        return [
            {
                "subject": str(item.subject or ""),
                "start": str(item.start),
                "end": str(item.end),
                "location": str(item.location or ""),
            }
            for item in items[:limit]
        ]

    def get_free_busy(self, attendees: list[str], start: datetime, end: datetime) -> list[TimeBlock]:
        start = self._to_ews_datetime(start)
        end = self._to_ews_datetime(end)
        account_tuples = [(email, "Required", False) for email in attendees]
        free_busy_entries = self.account.protocol.get_free_busy_info(
            accounts=account_tuples,
            start=start,
            end=end,
            merged_free_busy_interval=15,
        )

        busy: list[TimeBlock] = []
        for entry in free_busy_entries:
            for event in getattr(entry, "calendar_events", []) or []:
                status = str(getattr(event, "busy_type", "")).lower()
                if status in {"busy", "tentative", "oof", "working_elsewhere"}:
                    busy.append(TimeBlock(event.start, event.end))
        return busy

    def resolve_attendees(self, attendees: list[str], *, limit: int = 5) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        match_limit = max(1, limit)

        for attendee in attendees:
            query = attendee.strip()
            if _looks_like_email(query):
                results.append(
                    {
                        "query": query,
                        "status": "email",
                        "matches": [{"name": query, "email": query, "source": "input"}],
                    }
                )
                continue

            matches = self._resolve_name(query)
            status = _resolution_status(len(matches))
            results.append(
                {
                    "query": query,
                    "status": status,
                    "matches": matches[:match_limit],
                }
            )

        return results

    def create_meeting(self, request: MeetingRequest) -> dict[str, str]:
        request.validate()
        try:
            from exchangelib import CalendarItem
        except ImportError as exc:
            raise RuntimeError(
                "Missing dependency 'exchangelib'. Run: pip install -r requirements.txt"
            ) from exc
        try:
            from exchangelib.items import SEND_TO_ALL_AND_SAVE_COPY
        except ImportError:
            SEND_TO_ALL_AND_SAVE_COPY = "SendToAllAndSaveCopy"

        item = CalendarItem(
            account=self.account,
            folder=self.account.calendar,
            subject=request.subject,
            body=request.body,
            start=self._to_ews_datetime(request.start),
            end=self._to_ews_datetime(request.end),
            location=request.location,
            required_attendees=request.attendees,
        )
        item.save(send_meeting_invitations=SEND_TO_ALL_AND_SAVE_COPY)

        return {
            "id": str(getattr(item, "id", "") or ""),
            "changekey": str(getattr(item, "changekey", "") or ""),
            "subject": str(item.subject or ""),
            "start": str(item.start),
            "end": str(item.end),
        }

    def _build_account(self) -> Any:
        try:
            from exchangelib import Account, Configuration, Credentials, DELEGATE
            from exchangelib.protocol import BaseProtocol, NoVerifyHTTPAdapter
            from exchangelib import BASIC, NTLM
            from exchangelib.winzone import MS_TIMEZONE_TO_IANA_MAP
        except ImportError as exc:
            raise RuntimeError(
                "Missing dependency 'exchangelib'. Run: pip install -r requirements.txt"
            ) from exc

        MS_TIMEZONE_TO_IANA_MAP.setdefault("", self.config.timezone)

        auth_type = {"BASIC": BASIC, "NTLM": NTLM}.get(self.config.auth_type)
        if auth_type is None:
            raise RuntimeError("EWS_AUTH_TYPE must be BASIC or NTLM for this PoC")

        credentials = Credentials(
            username=self.config.username,
            password=self.config.password,
        )
        configuration = Configuration(
            service_endpoint=self.config.endpoint,
            credentials=credentials,
            auth_type=auth_type,
        )

        # Keep TLS verification enabled by default. If the company uses an
        # internal CA, install that CA locally instead of disabling validation.
        if False:
            BaseProtocol.HTTP_ADAPTER_CLS = NoVerifyHTTPAdapter

        return Account(
            primary_smtp_address=self.config.email,
            config=configuration,
            autodiscover=False,
            access_type=DELEGATE,
        )

    def _resolve_name(self, query: str) -> list[dict[str, str]]:
        if not query:
            return []

        resolutions = self.account.protocol.resolve_names(
            [query],
            return_full_contact_data=True,
        )
        matches: list[dict[str, str]] = []
        seen_emails: set[str] = set()
        for resolution in resolutions:
            match = _resolution_to_match(resolution)
            email = match.get("email", "").lower()
            if not email or email in seen_emails:
                continue
            seen_emails.add(email)
            matches.append(match)
        return matches

    def _to_ews_datetime(self, value: datetime) -> Any:
        try:
            from exchangelib import EWSDateTime, EWSTimeZone
        except ImportError as exc:
            raise RuntimeError(
                "Missing dependency 'exchangelib'. Run: pip install -r requirements.txt"
            ) from exc

        target_tz = ZoneInfo(self.config.timezone)
        if value.tzinfo is None:
            local_value = value
        else:
            local_value = value.astimezone(target_tz).replace(tzinfo=None)

        ews_timezone = EWSTimeZone(self.config.timezone)
        return EWSDateTime(
            local_value.year,
            local_value.month,
            local_value.day,
            local_value.hour,
            local_value.minute,
            local_value.second,
            local_value.microsecond,
            tzinfo=ews_timezone,
        )


def _looks_like_email(value: str) -> bool:
    return re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", value) is not None


def _resolution_status(match_count: int) -> str:
    if match_count == 0:
        return "not_found"
    if match_count == 1:
        return "resolved"
    return "ambiguous"


def _resolution_to_match(resolution: Any) -> dict[str, str]:
    mailbox = resolution[0] if isinstance(resolution, tuple) else resolution
    contact = resolution[1] if isinstance(resolution, tuple) and len(resolution) > 1 else None

    name = (
        getattr(mailbox, "name", None)
        or getattr(contact, "display_name", None)
        or getattr(contact, "complete_name", None)
        or ""
    )
    email = (
        getattr(mailbox, "email_address", None)
        or getattr(contact, "email_address", None)
        or _first_contact_email(contact)
        or ""
    )
    source = "directory"
    return {
        "name": str(name or email),
        "email": str(email),
        "source": source,
    }


def _first_contact_email(contact: Any) -> str:
    if contact is None:
        return ""

    email_addresses = getattr(contact, "email_addresses", None)
    if isinstance(email_addresses, dict):
        for value in email_addresses.values():
            if value:
                return str(value)
    if isinstance(email_addresses, (list, tuple)):
        for value in email_addresses:
            if value:
                return str(value)
    return ""


def default_window(days: int, timezone_name: str = "Asia/Taipei") -> tuple[datetime, datetime]:
    now = datetime.now(ZoneInfo(timezone_name))
    return now, now + timedelta(days=days)
