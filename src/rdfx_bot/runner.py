"""Decides what to send on this run, sends it, and records it."""

from __future__ import annotations

import logging
import time
from datetime import timedelta
from dataclasses import dataclass, field
from typing import Callable, Protocol

from .context import Context
from .kinds import FALLBACKS, KINDS
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
    warnings: list[str] = field(default_factory=list)  # things the owner should hear about (plan B used, ...)

    @property
    def ok(self) -> bool:
        return not self.failed


def _build(ctx: Context, kind: str) -> Message | None:
    builder = KINDS.get(kind)
    if builder is None:
        log.error("Unknown message type '%s' (check config/schedule.yaml)", kind)
        return None
    return builder(ctx)


def _in_final_window(ctx: Context, slot: Slot) -> bool:
    """True in the last `fallback_minutes` (default 15) of a slot's catch-up window."""
    schedule = ctx.cfg.schedule
    catch_up = int(slot.entry.get("catch_up_minutes", schedule.get("catch_up_minutes", 45)))
    final = int(schedule.get("fallback_minutes", 15))
    if final <= 0:
        return False
    return ctx.now >= slot.scheduled + timedelta(minutes=max(catch_up - final, 0))


def _fallback(ctx: Context, slot: Slot, reason: Exception) -> Message | None:
    """Plan-B message if the data is still missing near the end of the window (news, calendar)."""
    builder = FALLBACKS.get(slot.kind)
    if builder is None or not _in_final_window(ctx, slot):
        return None
    try:
        message = builder(ctx)
    except Exception:  # noqa: BLE001
        log.exception("Could not build the fallback for %s", slot.entry_id)
        return None
    if message is not None:
        log.warning("%s: data still unavailable (%s). Sending the plan-B message instead of nothing.", slot.entry_id, reason)
    return message


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
            message = _fallback(ctx, slot, exc)
            if message is None:
                log.warning("%s not sent yet: %s (will retry until its catch-up window closes)", slot.entry_id, exc)
                result.skipped.append(slot.entry_id)
                continue
            result.warnings.append(f"'{slot.entry_id}' data was unavailable all window, so the plan-B message was posted instead ({exc}).")
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


def run_preview(ctx: Context, sender: Sender, sleep: Callable[[float], None] = time.sleep) -> RunResult:
    """Prints (dry run) or really sends (live test) one of every message type, then a summary."""
    result = RunResult()
    reasons: dict[str, str] = {}
    live = not ctx.dry_run
    if live:
        if not ctx.cfg.settings.get("enabled", True):
            log.info("Kill switch is on. Nothing sent.")
            return result
        try:
            ensure_sendable(ctx.now, ctx.cfg.settings)
        except BlockedDateError as exc:
            log.error("%s", exc)
            result.failed.append("all")
            return result
    gap = float(ctx.cfg.settings.get("send_gap_seconds", 4))
    first = True
    for kind in sorted(KINDS):
        try:
            message = _build(ctx, kind)
        except RetryLater as exc:
            print(f"\n===== {kind}: cannot build right now ({exc}) =====")
            reasons[kind] = f"cannot build: {exc}"
            result.skipped.append(kind)
            continue
        except Exception as exc:  # noqa: BLE001
            log.exception("Could not build %s", kind)
            reasons[kind] = f"error: {type(exc).__name__}"
            result.failed.append(kind)
            continue
        if message is None:
            reasons[kind] = "nothing to send"
            result.skipped.append(kind)
            continue
        if live and not first:
            sleep(gap)
        first = False
        try:
            sender.send(message)
        except (TelegramError, BlockedDateError) as exc:
            log.error("Send failed for %s: %s", kind, exc)
            reasons[kind] = "send failed"
            result.failed.append(kind)
            continue
        result.sent.append(kind)
    print("\n===== SUMMARY =====")
    for kind in sorted(KINDS):
        if kind in result.sent:
            print(f"OK       {kind}")
        else:
            print(f"MISSING  {kind}: {reasons.get(kind, 'not built')}")
            result.warnings.append(f"{kind}: {reasons.get(kind, 'not built')}")
    return result
