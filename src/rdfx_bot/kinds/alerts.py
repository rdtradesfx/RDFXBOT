"""News alerts: sent when a High/Medium event is 15 minutes (or less) away.

Each event is alerted once (deduped by event id). Events already released are never alerted.
Several events in the same minute become ONE message (set group_same_time: false to split).
"""

from __future__ import annotations

import logging
import math
from datetime import timedelta
from itertools import groupby

from ..context import Context
from ..models import Message, RetryLater
from ..safety import is_blocked
from ..scheduler import DAYS
from ..services.calendar_feed import Event, FeedUnavailable
from ..textutil import render
from .econ_calendar import event_values
from .registry import register

log = logging.getLogger(__name__)


def minutes_text(ctx: Context, start) -> str:
    """'15 minutes' when on time; the real time left if GitHub ran late."""
    remaining = math.ceil((start - ctx.now).total_seconds() / 60)
    remaining = max(1, remaining)
    if remaining == 1:
        return "1 minute"
    if remaining < 60:
        return f"{remaining} minutes"
    hours, mins = divmod(remaining, 60)
    text = f"{hours} hour" + ("s" if hours != 1 else "")
    return f"{text} {mins} minutes" if mins else text


def _message_for(ctx: Context, group: list[Event]) -> Message:
    tpl = ctx.cfg.messages["templates"]["alert"]
    start = group[0].start
    when = {"minutes_text": minutes_text(ctx, start), "time": f"{start.astimezone(ctx.cfg.tz):%H:%M}"}
    if len(group) == 1:
        text = render(str(tpl["single"]), **{**event_values(ctx, group[0], bold_big_movers=False), **when})
    else:
        blocks = "\n\n".join(render(str(tpl["group_event"]), **event_values(ctx, e, bold_big_movers=False)) for e in group)
        text = render(str(tpl["group"]), events=blocks, **when)
    return Message(text=text, kind="alert", dedupe_keys=[e.id for e in group])


def due_alert_messages(ctx: Context) -> list[Message]:
    """Alert messages that should go out on this run (never raises for feed problems)."""
    settings = (ctx.cfg.schedule.get("alerts") or {})
    if not settings.get("enabled", True):
        return []
    day = ctx.today
    active = {str(d).lower() for d in ctx.cfg.settings.get("active_days") or DAYS[:5]}
    if DAYS[day.weekday()] not in active or is_blocked(day, ctx.cfg.settings):
        return []
    try:
        events = ctx.calendar.events()
    except FeedUnavailable:
        log.warning("Alerts skipped: no calendar data available")
        return []

    lead = timedelta(minutes=int(settings.get("lead_minutes", 15)))
    minimum = timedelta(minutes=int(settings.get("min_lead_minutes", 1)))
    due = [
        e
        for e in events
        if ctx.now + minimum <= e.start <= ctx.now + lead and not ctx.state.has_alerted(e.id)
    ]
    due.sort(key=lambda e: (e.start, e.title))
    if not due:
        return []
    if not settings.get("group_same_time", True):
        return [_message_for(ctx, [e]) for e in due]
    return [_message_for(ctx, list(g)) for _t, g in groupby(due, key=lambda e: e.start)]


@register("alert")
def build_next_alert(ctx: Context) -> Message | None:
    """For manual tests: the alert for the next upcoming event (a sample in dry runs if none)."""
    try:
        upcoming = [e for e in ctx.calendar.events() if e.start > ctx.now]
    except FeedUnavailable:
        upcoming = []
    if upcoming:
        first = min(upcoming, key=lambda e: (e.start, e.title))
        group = [e for e in upcoming if e.start == first.start]
        return _message_for(ctx, group)
    if ctx.dry_run:
        sample = Event("sample", "SAMPLE: US CPI y/y", "USD", "High", ctx.now + timedelta(minutes=15), "3.1%", "3.0%")
        return _message_for(ctx, [sample])
    raise RetryLater("no upcoming High/Medium events in the calendar")
