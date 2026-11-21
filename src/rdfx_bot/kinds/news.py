"""Daily market news (07:00): headlines only, with a link to the source."""

from __future__ import annotations

from ..context import Context
from ..models import Message
from ..services.rss import SECTION_ORDER
from ..textutil import esc, esc_attr, render
from .registry import register


@register("news")
def build_news(ctx: Context) -> Message | None:
    tpl = ctx.cfg.messages["templates"]["news"]
    sections = ctx.news.sections(ctx.now)  # raises RetryLater if no feed could be read
    item_tpl = str(tpl.get("headline_item") or '<a href="{url}">{title}</a> ({source})')
    joiner = str(tpl.get("headline_join", "\n   "))
    defaults = tpl.get("defaults") or {}

    values = {}
    for key in SECTION_ORDER:
        headlines = sections.get(key) or []
        if headlines:
            values[key] = joiner.join(
                render(item_tpl, url=esc_attr(h.url), title=esc(h.title), source=esc(h.source)) for h in headlines
            )
        else:
            values[key] = esc(defaults.get(key) or "Nothing major so far, stay patient.")
    return Message(text=render(str(tpl["body"]), **values), kind="news")
