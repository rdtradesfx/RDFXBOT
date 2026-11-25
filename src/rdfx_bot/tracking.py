"""Tracked links: every funnel and social button link carries the id of the message that posted it.

Where you can see the tag:
  * Tally form (mentorship): add a hidden field called  source  (and optionally utm_campaign).
    Tally then records the message id with every application.
  * VIP / any t.me/<username> chat link: the chat opens with a pre-typed message that ends with the tag,
    so when someone DMs you, you can see which post brought them.
  * Websites with analytics (Google Analytics etc.): utm_source / utm_medium / utm_campaign.
  * Instagram, TikTok and YouTube do not report this to you, but the tag is still added.

Settings live in config/settings.yaml under  tracking:  (all optional; built-in defaults below).
"""

from __future__ import annotations

import zlib
from urllib.parse import parse_qsl, quote, urlencode, urlparse, urlunparse

DEFAULTS = {
    "enabled": True,
    "utm_source": "telegram",
    # Pre-typed message for t.me chat links. {ref} = a short code like V-7K2 for the post, {tag} = the full message id.
    "chat_text": "Hi Ryan, I'd like to join RDFX VIP. Ref: {ref}",
    # The hidden-field name Tally records the tag in.
    "tally_field": "source",
}


def tracking_settings(settings: dict) -> dict:
    block = (settings or {}).get("tracking")
    return {**DEFAULTS, **(block if isinstance(block, dict) else {})}


_B36 = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"


def ref_code(prefix: str, tag: str) -> str:
    """A short, stable reference for a message, e.g. V-7K2. The same message id always gives the same code."""
    n = zlib.crc32(tag.encode("utf-8")) % (36**3)
    return f"{prefix}-{_B36[n // 1296]}{_B36[(n // 36) % 36]}{_B36[n % 36]}"


def track_url(url: str, tag: str, medium: str, settings: dict | None = None, ref: str = "") -> str:
    """Add the tag to a link. Returns the link unchanged if tracking is off or anything looks wrong."""
    conf = tracking_settings(settings or {})
    if not conf.get("enabled", True) or not url or not tag:
        return url
    try:
        parts = urlparse(url)
    except ValueError:
        return url
    if parts.scheme != "https" or not parts.netloc:
        return url
    host = parts.netloc.lower().removeprefix("www.")
    query = parse_qsl(parts.query, keep_blank_values=True)
    existing = {k for k, _ in query}

    if host == "t.me":
        if "text" in existing or not parts.path.strip("/") or "/" in parts.path.strip("/"):
            return url  # not a plain username link, or already has a text
        text = str(conf.get("chat_text") or "").replace("{ref}", ref or tag).replace("{tag}", tag).strip()
        if not text:
            return url
        return urlunparse(parts._replace(query=urlencode(query + [("text", text)], quote_via=quote)))

    additions = [
        ("utm_source", str(conf.get("utm_source") or "telegram")),
        ("utm_medium", medium),
        ("utm_campaign", tag),
    ]
    if host.endswith("tally.so"):
        additions.append((str(conf.get("tally_field") or "source"), tag))
    query += [(k, v) for k, v in additions if k not in existing]
    return urlunparse(parts._replace(query=urlencode(query, quote_via=quote)))
