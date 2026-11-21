"""Funnel messages: 1-1 mentorship and VIP, rotating, each with an inline button.

Wording: messages/funnels.yaml. Links: config/links.yaml.
"""

from __future__ import annotations

from ..context import Context
from ..models import Message
from ._pool import pick_from_pool
from .registry import register


def _funnel(pool_name: str, kind: str):
    def build(ctx: Context) -> Message | None:
        pool = (ctx.cfg.messages.get("funnels") or {}).get(pool_name) or {}
        return pick_from_pool(pool, kind, kind, ctx)

    return build


register("funnel_mentorship")(_funnel("mentorship", "funnel_mentorship"))
register("funnel_vip")(_funnel("vip", "funnel_vip"))
