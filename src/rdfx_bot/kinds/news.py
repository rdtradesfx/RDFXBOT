"""Daily market news (07:00): headlines only, no links, plus what to watch today per section."""

from __future__ import annotations

from ..context import Context
from ..models import Message, RetryLater
from ..services.rss import SECTION_ORDER
from ..textutil import esc, esc_attr, render
from ._extras import extra
from .econ_calendar import impact_emoji
from .registry import register, register_fallback

# Which currency's calendar events matter to each section (gold is priced in dollars).
WATCH_CURRENCY = {"usd": "USD", "gold": "USD", "eur": "EUR", "gbp": "GBP", "aud": "AUD"}

DEFAULT_FALLBACK = """**📰 RDFX | DAILY MARKET NEWS**

Good morning.

Our headline feeds are unavailable right now, so there is no briefing this morning.

Check your usual sources before you trade and keep an eye on today's economic releases."""


def _watch_line(ctx: Context, section: str, limit: int | None = None, line_key: str = "watch_line", default_line: str = "📌 Watch today: {events}") -> str:
    """'📌 Watch today: 🔴 US CPI y/y (13:30 UK)' from today's High/Medium events, or '' if none/unavailable."""
    currency = WATCH_CURRENCY.get(section)
    try:
        events = ctx.calendar.events_on(ctx.today)
    except Exception:  # noqa: BLE001 - the calendar being down must never break the news
        return ""
    if limit is None:
        limit = int((ctx.cfg.sources.get("news") or {}).get("watch_max_events", 2))
    upcoming = [e for e in events if e.currency == currency and e.start >= ctx.now]
    upcoming.sort(key=lambda e: (e.impact != "High", e.start))
    if not upcoming or limit <= 0:
        return ""
    event_tpl = extra(ctx, "news", "watch_event", "{impact} {title} ({time} UK)")
    parts = [
        render(
            event_tpl,
            impact=impact_emoji(ctx, e.impact),
            title=esc(e.title),
            time=f"{e.start.astimezone(ctx.cfg.tz):%H:%M}",
        )
        for e in sorted(upcoming[:limit], key=lambda e: e.start)
    ]
    return render(extra(ctx, "news", line_key, default_line), events=" · ".join(parts))


# One bullet per market, always in this order. Every market is shown, even with no headline.
DEFAULT_MARKETS = {
    "usd": {"label": "🇺🇸 USD", "none": "Latest developments affecting the dollar: nothing major so far, stay patient."},
    "gold": {"label": "🥇 GOLD", "none": "Latest developments affecting gold: nothing major so far, stay patient."},
    "eur": {"label": "🇪🇺 EUR", "none": "Latest developments affecting the euro: nothing major so far, stay patient."},
    "gbp": {"label": "🇬🇧 GBP", "none": "Latest developments affecting the pound: nothing major so far, stay patient."},
    "aud": {"label": "🇦🇺 AUD", "none": "Latest developments affecting the Aussie dollar: nothing major so far, stay patient."},
}
DEFAULT_ORDER = ["usd", "gold", "eur", "gbp", "aud"]
DEFAULT_LINE = "• {label}: **{text}**"
DEFAULT_BODY = (
    "**🚨 RDFX | DAILY MARKET NEWS 🚨🗞️**\n\n**WHAT'S MOVING THE MARKETS? 🌎**\n\n"
    "Good morning team.\nHere's your latest market news briefing:\n\n{sections}\n\n"
    "Keep an eye on today's major economic releases and potential volatility."
)


@register("news")
def build_news(ctx: Context) -> Message | None:
    tpl = ctx.cfg.messages["templates"]["news"]
    sections = ctx.news.sections(ctx.now)  # raises RetryLater if no feed could be read
    item_tpl = str(tpl.get("headline_item") or "{title} ({source})")
    line_tpl = str(tpl.get("line") or DEFAULT_LINE)
    markets = {k: {**v, **((tpl.get("markets") or {}).get(k) or {})} for k, v in DEFAULT_MARKETS.items()}
    order = [k for k in (tpl.get("order") or DEFAULT_ORDER) if k in markets]

    lines = []
    for key in order:
        label = str(markets[key]["label"])
        headlines = sections.get(key) or []
        if headlines:
            for h in headlines:
                text = render(item_tpl, url=esc_attr(h.url), title=esc(h.title), source=esc(h.source))
                lines.append(render(line_tpl, label=label, text=text))
        else:
            lines.append(render(line_tpl, label=label, text=str(markets[key]["none"])))
    return Message(text=render(str(tpl.get("body") or DEFAULT_BODY), sections="\n\n".join(lines)), kind="news")


@register_fallback("news")
def build_news_fallback(ctx: Context) -> Message | None:
    return Message(text=render(extra(ctx, "news", "fallback", DEFAULT_FALLBACK)), kind="news")
