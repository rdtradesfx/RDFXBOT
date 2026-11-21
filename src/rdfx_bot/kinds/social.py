"""Social follow reminders, rotating, with inline buttons.

Wording: messages/socials.yaml. Links: config/links.yaml.
Messages needing an empty link (e.g. TikTok) are skipped automatically.
"""

from __future__ import annotations

from ..context import Context
from ..models import Message
from ._pool import pick_from_pool
from .registry import register


@register("social")
def build_social(ctx: Context) -> Message | None:
    return pick_from_pool(ctx.cfg.messages.get("socials") or {}, "social", "social", ctx)
