"""Trading session messages: Asia, London, New York and the overlap.

The wording lives in messages/sessions.yaml.
"""

from __future__ import annotations

import logging

from ..context import Context
from ..models import Message
from ..textutil import render
from .registry import register

log = logging.getLogger(__name__)


def _session(key: str):
    def build(ctx: Context) -> Message | None:
        data = (ctx.cfg.messages.get("sessions") or {}).get(key)
        if not isinstance(data, dict) or not data.get("text"):
            log.error("messages/sessions.yaml has no text for '%s'", key)
            return None
        return Message(text=render(str(data["text"])), kind=key)

    return build


for _key in ("asia", "london", "newyork", "overlap"):
    register(_key)(_session(_key))
