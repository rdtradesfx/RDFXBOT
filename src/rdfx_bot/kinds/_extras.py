"""Wording for the automatic extras (messages/extras.yaml), with built-in defaults if a line is missing."""

from __future__ import annotations

from ..context import Context


def extra(ctx: Context, group: str, key: str, default: str) -> str:
    value = ((ctx.cfg.messages.get("extras") or {}).get(group) or {}).get(key)
    return str(value) if value else default
