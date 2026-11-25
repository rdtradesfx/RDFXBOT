"""Trusted RSS/Atom headlines, sorted into the USD / GOLD / GBP sections.

Only headline + link + source name are ever used (never article text), and every
piece of external text is cleaned before it can reach a message.
"""

from __future__ import annotations

import logging
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Callable

from ..config import Config
from ..models import RetryLater
from ..net import http_get
from ..textutil import clean, safe_url

log = logging.getLogger(__name__)

# Order matters: on a tie the earlier section wins (a war headline goes to gold, not the dollar).
SECTION_ORDER = ["gold", "usd", "eur", "gbp", "aud"]


@dataclass(frozen=True)
class Headline:
    title: str
    url: str
    source: str
    published: datetime  # aware UTC
    auto_section: str | None = None


def _local(tag) -> str:
    return tag.rsplit("}", 1)[-1] if isinstance(tag, str) else ""


def _parse_date(text: str | None) -> datetime | None:
    if not text or not text.strip():
        return None
    text = text.strip()
    parsed = None
    try:
        parsed = parsedate_to_datetime(text)
    except (TypeError, ValueError, IndexError):
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
    if parsed is None:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def parse_feed(data: bytes, feed: dict, max_title: int = 160) -> list[Headline]:
    """Parse RSS 2.0 or Atom. Raises ValueError/ParseError for unusable data."""
    data = data.lstrip(b"\xef\xbb\xbf \r\n\t")
    if b"<!ENTITY" in data:  # blocks "billion laughs" style XML tricks
        raise ValueError("unsafe XML")
    root = ET.fromstring(data)
    domains = feed.get("domains") or []
    headlines: list[Headline] = []
    for node in root.iter():
        if _local(node.tag) not in ("item", "entry"):
            continue
        title = link = published = None
        for child in node:
            name = _local(child.tag)
            if name == "title":
                title = child.text
            elif name == "link":
                link = (child.text or "").strip() or child.attrib.get("href")
            elif name in ("pubDate", "published", "updated", "date") and published is None:
                published = child.text
        when = _parse_date(published)
        url = safe_url(link, domains or None)
        text = clean(title, max_title)
        if not (text and url and when):
            continue
        headlines.append(Headline(text, url, str(feed.get("name") or "Source"), when, feed.get("auto_section")))
    return headlines


def _compile(words: list[str], exact: bool) -> list[tuple[str, re.Pattern]]:
    flags = 0 if exact else re.IGNORECASE
    return [(w, re.compile(rf"(?<!\w){re.escape(str(w))}(?!\w)", flags)) for w in words or []]


def classify(headline: Headline, rules: dict) -> str | None:
    """Pick the best section for a headline, or None if it does not fit any."""
    best = None  # (score, -first_position, -order_index, section)
    for index, section in enumerate(SECTION_ORDER):
        rule = (rules.get(section) or {})
        patterns = _compile(rule.get("keywords"), False) + _compile(rule.get("keywords_exact"), True)
        positions = []
        for _word, pattern in patterns:
            match = pattern.search(headline.title)
            if match:
                positions.append(match.start())
        if not positions:
            continue
        candidate = (len(positions), -min(positions), -index, section)
        if best is None or candidate > best:
            best = candidate
    if best:
        return best[3]
    if headline.auto_section in SECTION_ORDER:
        return headline.auto_section
    return None


class NewsService:
    def __init__(self, cfg: Config, fetch: Callable[[str], bytes] | None = None):
        self.cfg = cfg
        self._fetch = fetch or http_get
        self._cache: list[Headline] | None = None

    def _news_cfg(self) -> dict:
        return self.cfg.sources.get("news") or {}

    def headlines(self) -> list[Headline]:
        if self._cache is not None:
            return self._cache
        news = self._news_cfg()
        max_title = int(news.get("title_max_chars", 160))
        collected: list[Headline] = []
        worked = 0
        for feed in news.get("feeds") or []:
            if not isinstance(feed, dict) or feed.get("enabled", True) is False:
                continue
            try:
                items = parse_feed(self._fetch(str(feed.get("url") or "")), feed, max_title)
                collected.extend(items)
                worked += 1
                log.info("News feed '%s': %d headlines read", feed.get("name"), len(items))
            except Exception as exc:  # noqa: BLE001 - one broken feed must not stop the others
                log.warning("News feed '%s' unavailable (%s)", feed.get("name"), type(exc).__name__)
        if worked == 0:
            raise RetryLater("no news feed could be read")
        self._cache = collected
        return collected

    def sections(self, now: datetime) -> dict[str, list[Headline]]:
        news = self._news_cfg()
        hours = int(news.get("max_age_hours", 24))
        if now.astimezone(self.cfg.tz).weekday() == 0:  # Monday: the weekend is quiet, look further back
            hours = max(hours, int(news.get("monday_max_age_hours", 72)))
        oldest = now.astimezone(timezone.utc) - timedelta(hours=hours)
        newest = now.astimezone(timezone.utc) + timedelta(hours=1)
        exclude = _compile(news.get("exclude_keywords"), False)
        default_limit = int(news.get("max_per_section", 1))
        limits = news.get("limits") or {}
        rules = news.get("sections") or {}
        themes = news.get("themes") or {}

        def cap(section: str) -> int:
            return int(limits.get(section, default_limit))

        def norm(h: Headline) -> str:
            return re.sub(r"\W+", " ", h.title.lower()).strip()

        result: dict[str, list[Headline]] = {s: [] for s in SECTION_ORDER}
        in_section: dict[str, set[str]] = {s: set() for s in SECTION_ORDER}
        used: set[str] = set()  # a headline already shown anywhere is not shown under a different market by keyword
        fresh_list: list[Headline] = []
        seen: set[str] = set()
        for headline in sorted(self.headlines(), key=lambda h: h.published, reverse=True):
            if not (oldest <= headline.published <= newest):
                continue
            if any(p.search(headline.title) for _w, p in exclude):
                continue
            if norm(headline) in seen:
                continue
            seen.add(norm(headline))
            fresh_list.append(headline)

        def add(section: str, headline: Headline) -> bool:
            if len(result[section]) >= cap(section) or norm(headline) in in_section[section]:
                return False
            result[section].append(headline)
            in_section[section].add(norm(headline))
            used.add(norm(headline))
            return True

        # 1) Themes first: a war or similar event that moves several markets is shown under each of them
        #    (for example gold AND the dollar), ahead of routine pair forecasts.
        for headline in fresh_list:
            for _name, theme in themes.items():
                patterns = _compile((theme or {}).get("keywords"), False)
                if any(p.search(headline.title) for _w, p in patterns):
                    for section in (theme or {}).get("sections") or []:
                        if section in result:
                            add(section, headline)
        # 2) Everything else goes to the one market it is about.
        for headline in fresh_list:
            if norm(headline) in used:
                continue
            section = classify(headline, rules)
            if section is not None:
                add(section, headline)
        # 3) Optional looser match, only for a market still empty (off unless loose_keywords are set).
        for section in SECTION_ORDER:
            if result[section]:
                continue
            patterns = _compile((rules.get(section) or {}).get("loose_keywords"), False)
            for headline in fresh_list:
                if norm(headline) not in used and any(p.search(headline.title) for _w, p in patterns):
                    add(section, headline)
        fresh = len(fresh_list)
        log.info(
            "News: %d fresh headlines in the last %dh -> GOLD %d, USD %d, EUR %d, GBP %d, AUD %d",
            fresh, hours, len(result["gold"]), len(result["usd"]), len(result["eur"]), len(result["gbp"]), len(result["aud"]),
        )
        return result
