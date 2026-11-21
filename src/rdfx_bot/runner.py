"""Decides what to send on this run, sends it, and records it."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Callable, Protocol

from .context import Context
from .kinds import KINDS
from .kinds.alerts import due_alert_messages
from .models import Message, RetryLater
from .safety import BlockedDateError, ensure_sendable, is_blocked
from .scheduler import Slot, due_slots
from .telegram import TelegramError

log = logging.getLogger(__name__)


class Sender(Protocol):
    def send(self, message: Message) -> object: ...


class ConsoleSender:
    """Dry-run sender: prints what would be sent, sends nothing."""

    def __init__(self, label: str = "DRY RUN"):
        self.label = label

    def send(self, message: Message) -> None:
        print(f"\n===== [{self.label}] {message.kind or 'message'} =====")
        print(message.text)
        for button in message.buttons:
            print(f"  [button] {button.label} -> {button.url}")
        print("=" * 40)


@dataclass
class RunResult:
    sent: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.failed


def _build(ctx: Context, kind: str) -> Message | None:
    builder = KINDS.get(kind)
    if builder is None:
        log.error("Unknown message type '%s' (check config/schedule.yaml)", kind)
        return None
    return builder(ctx)


def _deliver(ctx: Context, sender: Sender, message: Message, slot: Slot | None, record: bool) -> bool:
    try:
        sender.send(message)
    except BlockedDateError as exc:
        log.error("%s", exc)
        return False
    except TelegramError as exc:
        log.error("Send failed for %s: %s", message.kind, exc)
        return False
    if record and not ctx.dry_run:
        if slot is not None:
            ctx.state.mark_sent(slot.slot_id, ctx.now)
        for key in message.dedupe_keys:
            ctx.state.mark_alerted(key, ctx.now)
        if message.rotation:
            ctx.state.set_rotation(*message.rotation)
        ctx.state.save()  # save straight after every send so a crash can never cause a duplicate
    return True


def run_scheduled(ctx: Context, sender: Sender, sleep: Callable[[float], None] = time.sleep) -> RunResult:
    """Normal run: send whatever is due now (slots + news alerts), once each."""
    result = RunResult()
    settings = ctx.cfg.settings
    if not settings.get("enabled", True) and not ctx.dry_run:
        log.info("Kill switch is on (enabled: false in config/settings.yaml). Nothing sent.")
        return result
    if is_blocked(ctx.today, settings):
        log.info("%s is a blocked date. Nothing sent.", ctx.today.isoformat())
        return result

    gap = float(settings.get("send_gap_seconds", 4))
    first = True

    def pause():
        nonlocal first
        if not first and not ctx.dry_run:
            sleep(gap)
        first = False

    for slot in due_slots(ctx.now, ctx.cfg.schedule, settings, ctx.cfg.tz):
        if ctx.state.has_sent(slot.slot_id):
            continue
        try:
            message = _build(ctx, slot.kind)
        except RetryLater as exc:
            log.warning("%s not sent yet: %s (will retry until its catch-up window closes)", slot.entry_id, exc)
            result.skipped.append(slot.entry_id)
            continue
        except Exception:  # noqa: BLE001 - one broken message must not block the others
            log.exception("Could not build %s", slot.entry_id)
            result.failed.append(slot.entry_id)
            continue
        if message is None:
            result.skipped.append(slot.entry_id)
            continue
        pause()
        if _deliver(ctx, sender, message, slot, record=True):
            result.sent.append(slot.entry_id)
        else:
            result.failed.append(slot.entry_id)

    try:
        alerts = due_alert_messages(ctx)
    except Exception:  # noqa: BLE001
        log.exception("Could not work out news alerts")
        alerts = []
    for message in alerts:
        pause()
        if _deliver(ctx, sender, message, None, record=True):
            result.sent.append("alert")
        else:
            result.failed.append("alert")

    if not ctx.dry_run:
        ctx.state.prune(ctx.now, int(settings.get("retention_days", 14)))
        ctx.state.save()
    if not (result.sent or result.failed):
        log.info("Nothing due at %s UK time.", f"{ctx.now.astimezone(ctx.cfg.tz):%Y-%m-%d %H:%M}")
    return result


def run_manual(ctx: Context, sender: Sender, kind: str) -> RunResult:
    """Send one message type right now (testing). Leaves the sent-history untouched."""
    result = RunResult()
    if not ctx.dry_run:
        if not ctx.cfg.settings.get("enabled", True):
            log.info("Kill switch is on. Nothing sent.")
            return result
        try:
            ensure_sendable(ctx.now, ctx.cfg.settings)
        except BlockedDateError as exc:
            log.error("%s", exc)
            result.failed.append(kind)
            return result
    try:
        message = _build(ctx, kind)
    except RetryLater as exc:
        log.warning("Cannot build %s right now: %s", kind, exc)
        result.skipped.append(kind)
        return result
    if message is None:
        result.skipped.append(kind)
        return result
    if _deliver(ctx, sender, message, None, record=False):
        result.sent.append(kind)
    else:
        result.failed.append(kind)
    return result


def run_preview(ctx: Context, sender: Sender) -> RunResult:
    """Dry run that prints every message type."""
    result = RunResult()
    for kind in sorted(KINDS):
        try:
            message = _build(ctx, kind)
        except RetryLater as exc:
            print(f"\n===== [DRY RUN] {kind}: cannot build right now ({exc}) =====")
            result.skipped.append(kind)
            continue
        except Exception:  # noqa: BLE001
            log.exception("Could not build %s", kind)
            result.failed.append(kind)
            continue
        if message is None:
            result.skipped.append(kind)
            continue
        sender.send(message)
        result.sent.append(kind)
    return result
