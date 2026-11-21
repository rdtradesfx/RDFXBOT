"""Economic calendar: free ForexFactory weekly JSON feed + manual overrides.

Rules:
  * fetched at most once an hour (cached in state/calendar_cache.json);
  * only High / Medium impact events in the configured currencies are kept;
  * if the feed is down the last good copy is reused (up to max_stale_hours);
  * if there is nothing at all, FeedUnavailable is raised and callers skip or retry.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

from ..config import Config
from ..net import http_get
from ..textutil import clean

log = logging.getLogger(__name__)


class FeedUnavailable(RuntimeError):
    """No calendar data is available (feed down, no usable cache, no overrides)."""


@dataclass(frozen=True)
class Event:
    id: str
    title: str
    currency: str
    impact: str  # "High" or "Medium"
    start: datetime  # aware, UK time
    forecast: str = ""
    previous: str = ""
    source: str = "feed"


def make_event_id(currency: str, title: str, start: datetime) -> str:
    raw = f"{currency}|{title}|{start.astimezone(timezone.utc).isoformat()}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]  # noqa: S324 (not security-related)


def parse_dt(value, naive_tz) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=naive_tz)
    return parsed


def _canonical_impact(value, impacts: dict) -> str | None:
    wanted = str(value or "").strip().lower()
    for name in impacts:
        if str(name).lower() == wanted:
            return str(name)
    return None


def parse_events(raw: list, calendar_cfg: dict, tz) -> list[Event]:
    """Turn raw feed items into Events, keeping only configured impacts/currencies."""
    currencies = {str(k).upper() for k in (calendar_cfg.get("currencies") or {})}
    impacts = calendar_cfg.get("impacts") or {}
    events: list[Event] = []
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, dict):
            continue
        currency = str(item.get("country") or item.get("currency") or "").strip().upper()
        impact = _canonical_impact(item.get("impact"), impacts)
        start = parse_dt(item.get("date") or item.get("datetime"), timezone.utc)
        title = clean(item.get("title"), 120)
        if currency not in currencies or impact is None or start is None or not title:
            continue
        start = start.astimezone(tz)
        events.append(
            Event(
                id=make_event_id(currency, title, start),
                title=title,
                currency=currency,
                impact=impact,
                start=start,
                forecast=clean(item.get("forecast"), 30),
                previous=clean(item.get("previous"), 30),
            )
        )
    return events


def _event_to_dict(event: Event) -> dict:
    return {
        "title": event.title,
        "currency": event.currency,
        "impact": event.impact,
        "datetime": event.start.astimezone(timezone.utc).isoformat(),
        "forecast": event.forecast,
        "previous": event.previous,
    }


class CalendarService:
    def __init__(self, cfg: Config, now: datetime, persist: bool = True, fetch: Callable[[str], bytes] | None = None):
        self.cfg = cfg
        self.now = now
        self.persist = persist
        self._fetch = fetch or http_get
        self._events: list[Event] | None = None
        self.status = "not loaded"

    # -- public --------------------------------------------------------------
    def events(self) -> list[Event]:
        if self._events is None:
            self._events = self._load()
        return self._events

    def feed_is_current(self) -> bool:
        """True when the events come from the feed (fresh or cached), not just overrides/stale."""
        self.events()
        return self.status in ("live", "cached")

    def events_on(self, day: date) -> list[Event]:
        tz = self.cfg.tz
        return [e for e in self.events() if e.start.astimezone(tz).date() == day]

    # -- loading -------------------------------------------------------------
    def _cfg(self) -> dict:
        return self.cfg.sources.get("calendar") or {}

    def _load(self) -> list[Event]:
        feed_events, status = self._load_feed()
        overrides = self._load_overrides()
        if feed_events is None and not overrides:
            self.status = "down"
            raise FeedUnavailable("economic calendar feed unavailable and no cached copy or manual events")
        self.status = status if feed_events is not None else "overrides-only"
        merged: dict[str, Event] = {}
        for event in list(feed_events or []) + overrides:
            merged[event.id] = event
        return sorted(merged.values(), key=lambda e: (e.start, e.title))

    def _cache_path(self) -> Path:
        return self.cfg.root / (self._cfg().get("cache_file") or "state/calendar_cache.json")

    def _read_cache(self) -> dict:
        try:
            data = json.loads(self._cache_path().read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def _write_cache(self, cache: dict) -> None:
        if not self.persist:
            return
        path = self._cache_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(cache, indent=1, sort_keys=True) + "\n", encoding="utf-8")

    @staticmethod
    def _stamp(value) -> datetime | None:
        try:
            return datetime.fromisoformat(value) if value else None
        except (TypeError, ValueError):
            return None

    def _events_from_cache(self, cache: dict) -> list[Event]:
        return parse_events(cache.get("events") or [], self._cfg(), self.cfg.tz)

    def _load_feed(self) -> tuple[list[Event] | None, str]:
        cfg = self._cfg()
        cache = self._read_cache()
        now_utc = self.now.astimezone(timezone.utc)
        fetched_at = self._stamp(cache.get("fetched_at"))
        last_attempt = self._stamp(cache.get("last_attempt"))
        refresh = timedelta(minutes=int(cfg.get("refresh_minutes", 60)))
        retry = timedelta(minutes=int(cfg.get("retry_minutes", 15)))
        max_stale = timedelta(hours=int(cfg.get("max_stale_hours", 48)))

        if fetched_at and now_utc - fetched_at < refresh and cache.get("last_ok", True):
            return self._events_from_cache(cache), "cached"

        recently_failed = bool(last_attempt and cache.get("last_ok") is False and now_utc - last_attempt < retry)
        if not recently_failed:
            try:
                data = json.loads(self._fetch(str(cfg.get("url") or "")).decode("utf-8"))
                if not isinstance(data, list):
                    raise ValueError("feed is not a list")
                events = parse_events(data, cfg, self.cfg.tz)
                self._write_cache(
                    {
                        "fetched_at": now_utc.isoformat(timespec="seconds"),
                        "last_attempt": now_utc.isoformat(timespec="seconds"),
                        "last_ok": True,
                        "events": [_event_to_dict(e) for e in events],
                    }
                )
                return events, "live"
            except Exception as exc:  # noqa: BLE001 - a feed problem must never crash the run
                log.warning("Calendar feed unavailable (%s). Using last good copy if there is one.", type(exc).__name__)
                cache["last_attempt"] = now_utc.isoformat(timespec="seconds")
                cache["last_ok"] = False
                self._write_cache(cache)

        if fetched_at and now_utc - fetched_at <= max_stale:
            return self._events_from_cache(cache), "stale"
        return None, "down"

    def _load_overrides(self) -> list[Event]:
        path = self.cfg.root / (self._cfg().get("overrides_file") or "events.json")
        if not path.exists():
            return []
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            log.warning("events.json is not valid JSON, ignoring it")
            return []
        items = data.get("events") if isinstance(data, dict) else data
        impacts = self._cfg().get("impacts") or {}
        tz = self.cfg.tz
        events: list[Event] = []
        for item in items if isinstance(items, list) else []:
            if not isinstance(item, dict):
                continue
            title = clean(item.get("title"), 120)
            currency = str(item.get("currency") or "").strip().upper()
            impact = _canonical_impact(item.get("impact"), impacts)
            start = parse_dt(item.get("datetime"), tz)
            if not (title and currency and impact and start):
                log.warning("Skipping an events.json entry that is missing title/currency/impact/datetime")
                continue
            start = start.astimezone(tz)
            events.append(
                Event(
                    id=make_event_id(currency, title, start),
                    title=title,
                    currency=currency,
                    impact=impact,
                    start=start,
                    forecast=clean(item.get("forecast"), 30),
                    previous=clean(item.get("previous"), 30),
                    source="manual",
                )
            )
        return events
