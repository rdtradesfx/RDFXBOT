"""The list of message types. Each module in this folder registers itself here."""

from __future__ import annotations

from typing import Callable

from ..context import Context
from ..models import Message

Builder = Callable[[Context], "Message | None"]
KINDS: dict[str, Builder] = {}
# Optional "plan B" builders: used when a message's data is unavailable at the end of its window.
FALLBACKS: dict[str, Builder] = {}


def register(name: str):
    """Decorator: @register("my_kind") on a function that takes a Context and returns a Message (or None)."""

    def decorator(func: Builder) -> Builder:
        if name in KINDS:
            raise ValueError(f"message type '{name}' is registered twice")
        KINDS[name] = func
        return func

    return decorator


def register_fallback(name: str):
    """Decorator: a plan-B message for kind `name`, sent only if the normal one cannot be built in time."""

    def decorator(func: Builder) -> Builder:
        FALLBACKS[name] = func
        return func

    return decorator
