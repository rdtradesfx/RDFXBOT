"""Sending messages through the Telegram Bot API.

Safety rules baked in:
  * The blocked-date check runs inside send(), using the real UK clock, so no
    caller (schedule, manual run, test button) can get around it.
  * The bot token only ever lives in memory. It is never logged, and any error
    text is redacted before it leaves this module.
"""

from __future__ import annotations

import json
import logging
import re
import time
import urllib.error
import urllib.request
from datetime import datetime
from typing import Callable

from .models import Message
from .safety import ensure_sendable, uk_now
from .textutil import strip_html

log = logging.getLogger(__name__)

API = "https://api.telegram.org"
MAX_LEN = 4000  # Telegram's hard limit is 4096; stay safely under it
_TOKEN_SHAPE = re.compile(r"\d{6,}:[A-Za-z0-9_-]{20,}")


class TelegramError(RuntimeError):
    """Sending failed. The text never contains the bot token."""


def redact(text: str, secrets=()) -> str:
    for secret in secrets:
        if secret:
            text = text.replace(secret, "***")
    return _TOKEN_SHAPE.sub("***", text)


def split_text(text: str, limit: int = MAX_LEN) -> list[str]:
    """Split a long message on blank lines so each part fits Telegram's limit."""
    if len(text) <= limit:
        return [text]
    parts: list[str] = []
    current = ""
    for block in text.split("\n\n"):
        candidate = f"{current}\n\n{block}" if current else block
        if len(candidate) <= limit:
            current = candidate
            continue
        if current:
            parts.append(current)
        current = block
        while len(current) > limit:
            parts.append(current[:limit])
            current = current[limit:]
    if current:
        parts.append(current)
    return parts


def _default_post(url: str, payload: dict, timeout: int) -> tuple[int, dict]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        try:
            body = json.loads(exc.read().decode("utf-8"))
        except Exception:  # noqa: BLE001
            body = {}
        return exc.code, body


class TelegramClient:
    def __init__(
        self,
        token: str,
        chat_id: str,
        settings: dict | None = None,
        clock: Callable[[], datetime] = uk_now,
        post: Callable[[str, dict, int], tuple[int, dict]] = _default_post,
        sleep: Callable[[float], None] = time.sleep,
    ):
        if not token or not chat_id:
            raise TelegramError("TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID must both be set")
        self._token = token
        self._chat_id = chat_id
        self._settings = settings or {}
        self._clock = clock
        self._post = post
        self._sleep = sleep

    def _redact(self, text: str) -> str:
        return redact(text, (self._token, self._chat_id))

    def send(self, message: Message) -> int | None:
        """Send one message. Returns the Telegram message id."""
        ensure_sendable(self._clock(), self._settings)  # hard date block, cannot be bypassed
        parts = split_text(message.text)
        message_id = None
        for index, part in enumerate(parts):
            payload: dict = {
                "chat_id": self._chat_id,
                "text": part,
                "parse_mode": "HTML",
                "link_preview_options": {"is_disabled": True},
            }
            if message.buttons and index == len(parts) - 1:
                payload["reply_markup"] = {
                    "inline_keyboard": [[{"text": b.label, "url": b.url}] for b in message.buttons]
                }
            message_id = self._send_payload(payload)
        return message_id

    def _send_payload(self, payload: dict) -> int | None:
        url = f"{API}/bot{self._token}/sendMessage"
        for attempt in range(1, 5):
            try:
                status, body = self._post(url, payload, 20)
            except Exception as exc:  # noqa: BLE001 - never let a URL/token leak via the traceback
                raise TelegramError(self._redact(f"network error ({type(exc).__name__})")) from None
            if status == 200 and body.get("ok"):
                return (body.get("result") or {}).get("message_id")
            description = str(body.get("description") or f"HTTP {status}")
            if status == 429 and attempt < 4:
                wait = int((body.get("parameters") or {}).get("retry_after", 2))
                self._sleep(min(max(wait, 1), 30))
                continue
            if status >= 500 and attempt < 4:
                self._sleep(2 * attempt)
                continue
            if status == 400 and "parse entities" in description.lower() and payload.get("parse_mode"):
                log.warning("Telegram could not read the formatting; resending as plain text")
                payload = {k: v for k, v in payload.items() if k != "parse_mode"}
                payload["text"] = strip_html(payload["text"])
                continue
            raise TelegramError(self._redact(f"Telegram refused the message (HTTP {status}): {description}"))
        raise TelegramError("Telegram did not accept the message after several tries")
