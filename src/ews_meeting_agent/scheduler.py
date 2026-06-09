from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, time, timedelta


@dataclass(frozen=True, order=True)
class TimeBlock:
    start: datetime
    end: datetime

    def __post_init__(self) -> None:
        if self.end <= self.start:
            raise ValueError("TimeBlock end must be after start")


def suggest_slots(
    busy_blocks: list[TimeBlock],
    window_start: datetime,
    window_end: datetime,
    duration: timedelta,
    *,
    workday_start: time = time(9, 0),
    workday_end: time = time(18, 0),
    excluded_windows: list[tuple[time, time]] | None = None,
    step: timedelta = timedelta(minutes=15),
    limit: int = 5,
) -> list[TimeBlock]:
    if window_end <= window_start:
        raise ValueError("window_end must be after window_start")
    if duration <= timedelta(0):
        raise ValueError("duration must be positive")
    if step <= timedelta(0):
        raise ValueError("step must be positive")

    exclusions = excluded_windows or []
    for exclusion_start, exclusion_end in exclusions:
        if exclusion_end <= exclusion_start:
            raise ValueError("excluded window end must be after start")

    merged_busy = merge_blocks(
        block for block in busy_blocks if block.end > window_start and block.start < window_end
    )
    candidates: list[TimeBlock] = []
    cursor = window_start

    while cursor + duration <= window_end and len(candidates) < limit:
        if _inside_workday(cursor, cursor + duration, workday_start, workday_end):
            candidate = TimeBlock(cursor, cursor + duration)
            if not any(overlaps(candidate, busy) for busy in merged_busy) and not _overlaps_exclusion(
                candidate,
                exclusions,
            ):
                candidates.append(candidate)
        cursor += step

    return candidates


def merge_blocks(blocks: Iterable[TimeBlock]) -> list[TimeBlock]:
    sorted_blocks = sorted(blocks)
    if not sorted_blocks:
        return []

    merged = [sorted_blocks[0]]
    for block in sorted_blocks[1:]:
        previous = merged[-1]
        if block.start <= previous.end:
            merged[-1] = TimeBlock(previous.start, max(previous.end, block.end))
        else:
            merged.append(block)
    return merged


def overlaps(left: TimeBlock, right: TimeBlock) -> bool:
    return left.start < right.end and right.start < left.end


def parse_time_range(value: str) -> tuple[time, time]:
    start_text, separator, end_text = value.partition("-")
    if not separator:
        raise ValueError("time range must use HH:MM-HH:MM format")
    return time.fromisoformat(start_text), time.fromisoformat(end_text)


def _inside_workday(
    start: datetime,
    end: datetime,
    workday_start: time,
    workday_end: time,
) -> bool:
    if start.date() != end.date():
        return False
    return workday_start <= start.timetz().replace(tzinfo=None) and end.timetz().replace(
        tzinfo=None
    ) <= workday_end


def _overlaps_exclusion(candidate: TimeBlock, exclusions: list[tuple[time, time]]) -> bool:
    if not exclusions:
        return False

    candidate_start = candidate.start.timetz().replace(tzinfo=None)
    candidate_end = candidate.end.timetz().replace(tzinfo=None)
    return any(
        candidate_start < exclusion_end and exclusion_start < candidate_end
        for exclusion_start, exclusion_end in exclusions
    )
