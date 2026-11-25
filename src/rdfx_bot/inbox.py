"""The private chat with the bot owner.

OUT: if a scheduled post fails, or plan B had to be used, the bot messages you privately.
IN:  the only thing it reads is /myid (it replies with your Telegram ID, so you can put it in
     config/settings.yaml as admin_chat_id). Everything else sent to the bot is ignored.

Anyone can ask /myid, but they only ever get their OWN id back.
"""

from __future__ import annotations

import logging
import os

from .context import Context
from .telegram import TelegramClient, TelegramError

log = logging.getLogger(__name__)


def admin_id(cfg) -> str:
    """The owner's Telegram ID: the TELEGRAM_ADMIN_CHAT_ID secret if set, else admin_chat_id in config/settings.yaml."""
    return os.environ.get("TELEGRAM_ADMIN_CHAT_ID", "").strip() or str(cfg.settings.get("admin_chat_id") or "").strip()


def process_inbox(ctx: Context, client: TelegramClient) -> int:
    """Answer /myid and /start in private chats. Returns how many replies were sent. Never raises."""
    try:
        updates = client.get_updates()
    except TelegramError as exc:
        log.warning("Could not check the private chat: %s", exc)
        return 0
    replies = 0
    for update in updates:
        message = update.get("message") or {}
        chat = message.get("chat") or {}
        command = str(message.get("text") or "").strip().lower().split("@")[0].split(" ")[0]
        try:
            if chat.get("type") == "private" and command in ("/myid", "/start"):
                who = (message.get("from") or {}).get("id", "")
                if client.send_private(chat.get("id"), f"Your Telegram ID is: {who}\n\nPut it in config/settings.yaml as admin_chat_id to get failure notices."):
                    replies += 1
        except Exception:  # noqa: BLE001
            log.exception("Could not answer a private message")
        finally:
            if isinstance(update.get("update_id"), int):
                try:
                    client.get_updates(offset=update["update_id"] + 1, limit=1)
                except TelegramError as exc:
                    log.warning("Could not acknowledge a private message: %s", exc)
    return replies


# -- failure notices -----------------------------------------------------------------------
def notify_owner(ctx: Context, client: TelegramClient | None, key: str, text: str) -> None:
    """Message the owner once per key per day (a problem that repeats every 5 minutes must not spam you)."""
    owner = admin_id(ctx.cfg)
    if client is None or not owner or ctx.dry_run:
        return
    stamp = f"{ctx.today.isoformat()}:{key}"
    if ctx.state.has_noticed(stamp):
        return
    if client.send_private(owner, text):
        ctx.state.mark_noticed(stamp, ctx.now)
        ctx.state.save()


def notify_run_problems(ctx: Context, client: TelegramClient | None, result) -> None:
    if ctx.cfg.settings.get("failure_notices", True) is False:
        return
    for entry in result.failed:
        notify_owner(ctx, client, f"failed:{entry}", f"⚠️ RDFX bot: '{entry}' failed to post. It keeps retrying while its window is open. Check the Actions log if it keeps happening.")
    for entry in getattr(result, "warnings", []):
        notify_owner(ctx, client, f"warn:{entry}", f"ℹ️ RDFX bot: {entry}")
