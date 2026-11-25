"""`python -m rdfx_bot check`: catches typos in config/message files before they bite."""

from __future__ import annotations

from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .config import Config
from .kinds import KINDS
from .scheduler import DAYS, parse_hhmm
from .textutil import render, validate_html


def _html_problems(label: str, text: str) -> list[str]:
    return [f"{label}: {p}" for p in validate_html(render(str(text)))]


def check_config(cfg: Config) -> list[str]:
    problems: list[str] = []

    # schedule
    for entry_id, entry in (cfg.schedule.get("messages") or {}).items():
        where = f"schedule.yaml '{entry_id}'"
        if not isinstance(entry, dict):
            problems.append(f"{where}: must be a block of settings")
            continue
        if entry.get("kind") not in KINDS or entry.get("kind") == "alert":
            problems.append(f"{where}: unknown kind '{entry.get('kind')}'")
        if not entry.get("times"):
            problems.append(f"{where}: no times")
        for value in entry.get("times") or []:
            try:
                parse_hhmm(value)
            except ValueError as exc:
                problems.append(f"{where}: {exc}")
            else:
                if isinstance(value, int):
                    problems.append(f"{where}: put times in quotes, e.g. \"13:00\"")
        if entry.get("tz"):
            try:
                ZoneInfo(str(entry["tz"]))
            except (ZoneInfoNotFoundError, ValueError):
                problems.append(f"{where}: unknown timezone '{entry['tz']}' (use e.g. Europe/London, Asia/Tokyo, America/New_York)")
        for day in entry.get("days") or []:
            if str(day).lower() not in DAYS:
                problems.append(f"{where}: unknown day '{day}'")

    # links
    for key, value in cfg.links.items():
        if value and not cfg.link(key):
            problems.append(f"links.yaml {key}: must start with https://")

    # sessions
    for key in ("asia", "london", "newyork", "overlap"):
        text = ((cfg.messages.get("sessions") or {}).get(key) or {}).get("text")
        if not text:
            problems.append(f"sessions.yaml: missing text for '{key}'")
        else:
            problems += _html_problems(f"sessions.yaml {key}", text)

    # pools
    for pool_name, pool in (cfg.messages.get("funnels") or {}).items():
        problems += _check_pool(f"funnels.yaml {pool_name}", pool, cfg)
    problems += _check_pool("socials.yaml", cfg.messages.get("socials") or {}, cfg)

    # templates
    for file_name in ("templates", "extras"):
        for group, items in (cfg.messages.get(file_name) or {}).items():
            if isinstance(items, dict):
                for key, value in items.items():
                    if isinstance(value, str):
                        problems += _html_problems(f"{file_name}.yaml {group}.{key}", value)
    return problems


def _check_pool(label: str, pool: dict, cfg: Config) -> list[str]:
    problems: list[str] = []
    ids: set[str] = set()
    for entry in pool.get("messages") or []:
        mid = entry.get("id")
        if not mid or not entry.get("text"):
            problems.append(f"{label}: every message needs an id and text")
            continue
        if mid in ids:
            problems.append(f"{label}: duplicate id '{mid}'")
        ids.add(mid)
        problems += _html_problems(f"{label} '{mid}'", entry["text"])
        for button in entry.get("buttons", pool.get("buttons")) or []:
            if button.get("link") not in cfg.links:
                problems.append(f"{label} '{mid}': button link '{button.get('link')}' is not in links.yaml")
    if not ids:
        problems.append(f"{label}: no messages")
    return problems
