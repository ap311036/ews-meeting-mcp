from __future__ import annotations

from datetime import datetime


def parse_iso_datetime(value: str) -> datetime:
    text = value.strip()
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    return datetime.fromisoformat(text)
