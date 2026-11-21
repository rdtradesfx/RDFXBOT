"""Small data types shared by every message module."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Button:
    label: str
    url: str


@dataclass
class Message:
    """One Telegram message, ready to send."""

    text: str  # Telegram HTML
    buttons: list[Button] = field(default_factory=list)
    kind: str = ""
    # Event ids covered by this message (alerts); recorded as sent so they never repeat.
    dedupe_keys: list[str] = field(default_factory=list)
    # (pool name, message id) recorded after sending so the next pick avoids a repeat.
    rotation: tuple[str, str] | None = None


class RetryLater(Exception):
    """Data is not available right now (e.g. a feed is down). Try again on the next run."""
