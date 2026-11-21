"""Shared helper for rotating pools of messages with buttons (funnels and socials)."""

from __future__ import annotations

import logging

from ..context import Context
from ..models import Button, Message
from ..rotation import pick
from ..textutil import render

log = logging.getLogger(__name__)


def resolve_buttons(button_cfgs, ctx: Context) -> list[Button] | None:
    """Turn button config into Buttons. None = this message cannot be sent (a needed link is empty)."""
    buttons: list[Button] = []
    for cfg in button_cfgs or []:
        url = ctx.cfg.link(str(cfg.get("link") or ""))
        if not url:
            if cfg.get("optional"):
                continue
            return None
        buttons.append(Button(label=str(cfg.get("label") or "OPEN"), url=url))
    return buttons or None


def eligible_messages(pool: dict, ctx: Context) -> list[tuple[dict, list[Button]]]:
    """Messages in the pool whose buttons all resolve, paired with those buttons."""
    default_buttons = pool.get("buttons")
    out = []
    for entry in pool.get("messages") or []:
        if not isinstance(entry, dict) or not entry.get("id") or not entry.get("text"):
            continue
        buttons = resolve_buttons(entry.get("buttons", default_buttons), ctx)
        if buttons is not None:
            out.append((entry, buttons))
    return out


def pick_from_pool(pool: dict, rotation_key: str, kind: str, ctx: Context) -> Message | None:
    options = eligible_messages(pool, ctx)
    if not options:
        log.warning("No sendable messages in pool '%s' (check links in config/links.yaml)", rotation_key)
        return None
    by_id = {entry["id"]: (entry, buttons) for entry, buttons in options}
    chosen_id = pick(list(by_id), ctx.state.last_rotation(rotation_key), ctx.rng)
    entry, buttons = by_id[chosen_id]
    return Message(text=render(str(entry["text"])), buttons=buttons, kind=kind, rotation=(rotation_key, chosen_id))
