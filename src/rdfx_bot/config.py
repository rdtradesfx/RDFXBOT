"""Loading the YAML configuration and message files."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

log = logging.getLogger(__name__)

DEFAULT_ROOT = Path(__file__).resolve().parents[2]
MESSAGE_FILES = ("sessions", "funnels", "socials", "templates")
OPTIONAL_MESSAGE_FILES = ("extras",)  # automatic extras; built-in wording is used if the file is missing


class ConfigError(Exception):
    """A config file is missing or not valid. The message says which one."""


def load_yaml(path: Path) -> dict:
    try:
        with open(path, encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
    except FileNotFoundError as exc:
        raise ConfigError(f"Missing file: {path.name}") from exc
    except yaml.YAMLError as exc:
        raise ConfigError(f"{path.name} is not valid YAML: {exc}") from exc
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ConfigError(f"{path.name} must contain a set of 'key: value' entries")
    return data


def clean_link(value) -> str:
    """Return a usable https link, or '' if the link is empty/invalid."""
    if not isinstance(value, str):
        return ""
    value = value.strip()
    if value.lower().startswith("https://") and " " not in value and "<" not in value:
        return value
    if value:
        log.warning("Ignoring link that is not a valid https:// URL")
    return ""


@dataclass
class Config:
    root: Path
    settings: dict
    schedule: dict
    links: dict
    sources: dict
    messages: dict

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(str(self.settings.get("timezone") or "Europe/London"))

    def link(self, key: str) -> str:
        return clean_link(self.links.get(key))


def load_config(root: Path | str | None = None) -> Config:
    base = Path(root or os.environ.get("RDFX_ROOT") or DEFAULT_ROOT)
    messages = {name: load_yaml(base / "messages" / f"{name}.yaml") for name in MESSAGE_FILES}
    for name in OPTIONAL_MESSAGE_FILES:
        path = base / "messages" / f"{name}.yaml"
        messages[name] = load_yaml(path) if path.exists() else {}
    return Config(
        root=base,
        settings=load_yaml(base / "config" / "settings.yaml"),
        schedule=load_yaml(base / "config" / "schedule.yaml"),
        links=load_yaml(base / "config" / "links.yaml"),
        sources=load_yaml(base / "config" / "sources.yaml"),
        messages=messages,
    )
