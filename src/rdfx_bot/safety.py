"""The hard 'never send on these dates' block.

25 December is hard-coded here on purpose: removing it from config/settings.yaml
does NOT unblock it. There is no --force flag and no setting that bypasses this.
"""

from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

ALWAYS_BLOCKED = {(12, 25)}
BLOCK_TZ = ZoneInfo("Europe/London")  # the block always uses the UK date


class BlockedDateError(RuntimeError):
    """Raised when something tries to send on a blocked date."""


def is_blocked(day: date, settings: dict | None) -> bool:
    if (day.month, day.day) in ALWAYS_BLOCKED:
        return True
    for raw in (settings or {}).get("blocked_dates") or []:
        text = str(raw).strip()
        if text == day.isoformat() or text == day.strftime("%m-%d"):
            return True
    return False


def uk_now() -> datetime:
    return datetime.now(BLOCK_TZ)


def ensure_sendable(now: datetime, settings: dict | None) -> None:
    """Raise BlockedDateError if the UK date of `now` is blocked."""
    uk_day = now.astimezone(BLOCK_TZ).date()
    if is_blocked(uk_day, settings):
        raise BlockedDateError(f"Sending is blocked on {uk_day.isoformat()} (UK date)")
