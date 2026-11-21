"""Shared test helpers: a throwaway copy of the real config, fake feeds, a fake sender."""

from __future__ import annotations

import json
import random
import shutil
from datetime import datetime
from email.utils import format_datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from rdfx_bot.config import load_config
from rdfx_bot.context import Context
from rdfx_bot.services.calendar_feed import CalendarService
from rdfx_bot.services.rss import NewsService
from rdfx_bot.state import State
from rdfx_bot.telegram import TelegramError

ROOT = Path(__file__).resolve().parents[1]
UK = ZoneInfo("Europe/London")
UTC = ZoneInfo("UTC")


def uk(year, month, day, hour=0, minute=0, second=0):
    return datetime(year, month, day, hour, minute, second, tzinfo=UK)


def utc(year, month, day, hour=0, minute=0):
    return datetime(year, month, day, hour, minute, tzinfo=UTC)


def no_network(url):
    raise OSError("no network in tests")


class FakeSender:
    def __init__(self, fail=False):
        self.messages = []
        self.fail = fail

    def send(self, message):
        if self.fail:
            raise TelegramError("boom")
        self.messages.append(message)

    @property
    def kinds(self):
        return [m.kind for m in self.messages]


def ff(title, country, date, impact, forecast="", previous=""):
    """One item shaped like the ForexFactory weekly JSON feed."""
    return {"title": title, "country": country, "date": date, "impact": impact, "forecast": forecast, "previous": previous}


def calendar_fetch(items, counter=None):
    def fetch(url):
        if counter is not None:
            counter.append(url)
        return json.dumps(items).encode("utf-8")

    return fetch


def rss_xml(items):
    """items: list of (title, link, datetime|None)."""
    parts = ['<?xml version="1.0" encoding="utf-8"?><rss version="2.0"><channel><title>t</title>']
    for title, link, when in items:
        pub = f"<pubDate>{format_datetime(when)}</pubDate>" if when else ""
        parts.append(f"<item><title><![CDATA[{title}]]></title><link>{link}</link>{pub}</item>")
    parts.append("</channel></rss>")
    return "".join(parts).encode("utf-8")


@pytest.fixture
def cfg(tmp_path):
    for name in ("config", "messages"):
        shutil.copytree(ROOT / name, tmp_path / name)
    (tmp_path / "state").mkdir()
    shutil.copy(ROOT / "events.json", tmp_path / "events.json")
    return load_config(tmp_path)


@pytest.fixture
def make_ctx(cfg):
    def factory(now, calendar_fetcher=None, news_fetcher=None, dry_run=False, seed=1, config=None):
        c = config or cfg
        state = State.load(c.root / str(c.settings.get("state_file", "state/sent.json")))
        return Context(
            now=now,
            cfg=c,
            state=state,
            calendar=CalendarService(c, now, persist=not dry_run, fetch=calendar_fetcher or no_network),
            news=NewsService(c, fetch=news_fetcher or no_network),
            rng=random.Random(seed),
            dry_run=dry_run,
        )

    return factory
