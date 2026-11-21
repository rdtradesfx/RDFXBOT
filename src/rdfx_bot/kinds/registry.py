"""The list of message types. Each module in this folder registers itself here."""

from __future__ import annotations

from typing import Callable

from ..context import Context
from ..models import Message

Builder = Callable[[Context], "Message | None"]
KINDS: dict[str, Builder] = {}


def register(name: str):
    """Decorator: @register("my_kind") on a function that takes a Context and returns a Message (or None)."""

    def decorator(func: Builder) -> Builder:
        if name in KINDS:
            raise ValueError(f"message type '{name}' is registered twice")
        KINDS[name] = func
        return func

    return decorator
