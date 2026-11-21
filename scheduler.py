"""Works out which messages are due right now, in UK time.

Nothing here depends on the server's timezone: `now` is converted to Europe/London
and every scheduled time is built as a UK wall-clock time, so GMT/BST changes
are handled automatically.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from .safety import is_blocked

log = logging.getLogger(__name__)

DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
_HHMM = re.compile(r"^(\d{1,2}):(\d{2})$")


@dataclass(frozen=True)
class Slot:
    entry_id: str
    kind: str
    scheduled: datetime  # aware, UK time
    slot_date: date
    slot_id: str
    entry: dict = field(compare=False, hash=False, repr=False, default_factory=dict)


def parse_hhmm(value) -> time:
    """Accept "08:00". Also rescues unquoted times that YAML turned into minutes (780 -> 13:00)."""
    if isinstance(value, int) and not isinstance(value, bool):
        hours, minutes = divmod(value, 60)
    else:
        match = _HHMM.match(str(value).strip())
        if not match:
            raise ValueError(f"'{value}' is not a time like \"08:00\"")
        hours, minutes = int(match.group(1)), int(match.group(2))
    if not (0 <= hours <= 23 and 0 <= minutes <= 59):
        raise ValueError(f"'{value}' is not a valid time")
    return time(hours, minutes)


def local_dt(day: date, at: time, tz: ZoneInfo, offset_minutes: int = 0) -> datetime:
    """A UK wall-clock time on `day`, optionally shifted later by offset_minutes."""
    aware = datetime.combine(day, at, tzinfo=tz)
    return (aware.astimezone(timezone.utc) + timedelta(minutes=offset_minutes)).astimezone(tz)


def due_slots(now: datetime, schedule: dict, settings: dict, tz: ZoneInfo) -> list[Slot]:
    """Slots whose time has come and are still inside their catch-up window.

    Yesterday is checked too, so a late-evening slot delayed past midnight still goes out.
    Blocked dates (slot date or today's date) and days outside active_days never produce slots.
    """
    now_local = now.astimezone(tz)
    if is_blocked(now_local.date(), settings):
        return []
    default_catch = int(schedule.get("catch_up_minutes", 45))
    active = {str(d).lower() for d in settings.get("active_days") or DAYS[:5]}
    slots: list[Slot] = []

    for back in (1, 0):
        day = now_local.date() - timedelta(days=back)
        if is_blocked(day, settings):
            continue
        day_name = DAYS[day.weekday()]
        if day_name not in active:
            continue
        for entry_id, entry in (schedule.get("messages") or {}).items():
            if not isinstance(entry, dict) or not entry.get("enabled", True):
                continue
            allowed_days = entry.get("days")
            if allowed_days is not None and day_name not in {str(d).lower() for d in allowed_days}:
                continue
            try:
                catch_up = timedelta(minutes=int(entry.get("catch_up_minutes", default_catch)))
                offset = int(entry.get("offset_minutes", 0) or 0)
                times = [parse_hhmm(t) for t in (entry.get("times") or [])]
            except (TypeError, ValueError) as exc:
                log.error("Schedule entry '%s' skipped: %s", entry_id, exc)
                continue
            for at in times:
                when = local_dt(day, at, tz, offset)
                if when <= now_local < when + catch_up:
                    slots.append(
                        Slot(
                            entry_id=entry_id,
                            kind=str(entry.get("kind", "")),
                            scheduled=when,
                            slot_date=day,
                            slot_id=f"{entry_id}@{when:%Y-%m-%dT%H:%M}",
                            entry=entry,
                        )
                    )
    slots.sort(key=lambda s: (s.scheduled, s.entry_id))
    return slots
