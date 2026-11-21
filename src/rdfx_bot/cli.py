"""Command line: run | send | preview | check."""

from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import datetime

from .checks import check_config
from .config import ConfigError, load_config
from .context import Context
from .kinds import KINDS
from .runner import ConsoleSender, run_manual, run_preview, run_scheduled
from .safety import uk_now
from .services.calendar_feed import CalendarService
from .services.rss import NewsService
from .state import State
from .telegram import TelegramClient, TelegramError, redact


class _RedactFilter(logging.Filter):
    """Belt and braces: scrub the secrets from any log line."""

    def filter(self, record: logging.LogRecord) -> bool:
        secrets = [os.environ.get("TELEGRAM_BOT_TOKEN", ""), os.environ.get("TELEGRAM_CHAT_ID", "")]
        record.msg = redact(record.getMessage(), secrets)
        record.args = ()
        return True


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="rdfx_bot", description="RDFX Telegram bot")
    parser.add_argument("--root", help="repo folder (default: this repo)")
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="send whatever is due right now (this is what the schedule runs)")
    run.add_argument("--dry-run", action="store_true", help="print instead of sending; changes nothing")
    run.add_argument("--now", help="pretend it is this UK time, e.g. 2026-11-23T08:00 (dry runs only)")

    send = sub.add_parser("send", help="send one message type right now (testing)")
    send.add_argument("kind", choices=sorted(KINDS))
    send.add_argument("--dry-run", action="store_true")

    sub.add_parser("preview", help="dry run: print every message type")
    sub.add_parser("check", help="check the config and message files for mistakes")
    return parser


def _build_context(cfg, now: datetime, dry_run: bool) -> Context:
    state = State.load(cfg.root / str(cfg.settings.get("state_file") or "state/sent.json"))
    return Context(
        now=now,
        cfg=cfg,
        state=state,
        calendar=CalendarService(cfg, now, persist=not dry_run),
        news=NewsService(cfg),
        dry_run=dry_run,
    )


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    for handler in logging.getLogger().handlers:
        handler.addFilter(_RedactFilter())
    args = _parser().parse_args(argv)

    try:
        cfg = load_config(args.root)
    except ConfigError as exc:
        print(f"CONFIG ERROR: {exc}", file=sys.stderr)
        return 2

    if args.command == "check":
        problems = check_config(cfg)
        if problems:
            print("Problems found:")
            for problem in problems:
                print(f"  - {problem}")
            return 1
        print("All config and message files look good.")
        return 0

    dry_run = args.command == "preview" or getattr(args, "dry_run", False)
    now = uk_now()
    if getattr(args, "now", None):
        if not dry_run:
            print("--now can only be used with --dry-run", file=sys.stderr)
            return 2
        try:
            now = datetime.fromisoformat(args.now)
        except ValueError:
            print("--now must look like 2026-11-23T08:00", file=sys.stderr)
            return 2
        now = now.replace(tzinfo=cfg.tz) if now.tzinfo is None else now.astimezone(cfg.tz)
    now = now.astimezone(cfg.tz)

    ctx = _build_context(cfg, now, dry_run)

    if dry_run:
        sender = ConsoleSender()
    else:
        try:
            sender = TelegramClient(
                os.environ.get("TELEGRAM_BOT_TOKEN", "").strip(),
                os.environ.get("TELEGRAM_CHAT_ID", "").strip(),
                cfg.settings,
            )
        except TelegramError as exc:
            print(f"SETUP ERROR: {exc}. Add them under Settings > Secrets and variables > Actions.", file=sys.stderr)
            return 2

    if args.command == "preview":
        result = run_preview(ctx, sender)
    elif args.command == "send":
        result = run_manual(ctx, sender, args.kind)
    else:
        result = run_scheduled(ctx, sender)

    logging.getLogger(__name__).info(
        "Done. sent=%s skipped=%s failed=%s", result.sent or "-", result.skipped or "-", result.failed or "-"
    )
    return 0 if result.ok else 1
