"""Economic calendar for today (08:30)."""

from __future__ import annotations

import re

from ..context import Context
from ..models import Button, Message, RetryLater
from ..services.calendar_feed import Event, FeedUnavailable
from ..textutil import esc, render
from ._extras import extra
from .registry import register, register_fallback


def flag_for(ctx: Context, currency: str) -> str:
    flags = (ctx.cfg.sources.get("calendar") or {}).get("currencies") or {}
    return str(flags.get(currency) or "🌐")


def impact_emoji(ctx: Context, impact: str) -> str:
    impacts = (ctx.cfg.sources.get("calendar") or {}).get("impacts") or {}
    for name, emoji in impacts.items():
        if str(name).lower() == impact.lower():
            return str(emoji)
    return "⚪"


def is_big_mover(ctx: Context, title: str) -> bool:
    words = (ctx.cfg.sources.get("calendar") or {}).get("highlight_keywords") or []
    return any(re.search(rf"(?<!\w){re.escape(str(w))}(?!\w)", title, re.IGNORECASE) for w in words)


def figure(ctx: Context, value: str) -> str:
    empty = str(ctx.cfg.messages["templates"]["calendar"].get("empty_value", "—"))
    return esc(value) if value else esc(empty)


def event_values(ctx: Context, event: Event, bold_big_movers: bool = True) -> dict:
    title = esc(event.title)
    if bold_big_movers and is_big_mover(ctx, event.title):
        title = f"<b>{title}</b>"
    return {
        "flag": flag_for(ctx, event.currency),
        "impact": impact_emoji(ctx, event.impact),
        "title": title,
        "time": f"{event.start.astimezone(ctx.cfg.tz):%H:%M}",
        "forecast": figure(ctx, event.forecast),
        "previous": figure(ctx, event.previous),
    }


@register("calendar")
def build_calendar(ctx: Context) -> Message | None:
    tpl = ctx.cfg.messages["templates"]["calendar"]
    try:
        events = ctx.calendar.events_on(ctx.today)
    except FeedUnavailable as exc:
        raise RetryLater(str(exc)) from None
    if not ctx.calendar.feed_is_current() and ctx.calendar.status != "stale":
        # Only manual events are available. An incomplete list must not pose as "nothing today".
        raise RetryLater("calendar feed unavailable (only manual events found)")

    header = render(str(tpl["header"]))
    if not events:
        body = esc(str(tpl["empty_body"]))
        return Message(text=f"{header}\n\n{body}", kind="calendar")

    joiner = str(tpl.get("event_join", "\n"))
    blocks = [render(str(tpl["event_block"]), **event_values(ctx, e)).strip() for e in events]
    footer = render(str(tpl["footer"]))
    return Message(text=f"{header.strip()}\n\n{joiner.join(blocks)}\n\n{footer}", kind="calendar")


DEFAULT_FALLBACK = """📅 RDFX | ECONOMIC CALENDAR

Today's calendar could not be loaded right now.

Check the calendar for today's high-impact events before you trade.

Remember: High-impact news can increase spreads, volatility and slippage."""


@register_fallback("calendar")
def build_calendar_fallback(ctx: Context) -> Message | None:
    """Plan B when the feed is down for the whole window: say so, with one button to a live calendar."""
    url = ctx.cfg.link("CALENDAR_URL") or "https://www.forexfactory.com/calendar"
    label = extra(ctx, "calendar", "fallback_button", "OPEN CALENDAR")
    return Message(
        text=render(extra(ctx, "calendar", "fallback", DEFAULT_FALLBACK)),
        buttons=[Button(label, url)],
        kind="calendar",
    )
