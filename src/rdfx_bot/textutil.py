"""Text helpers: escaping external text and rendering templates for Telegram HTML."""

from __future__ import annotations

import html
import re
from urllib.parse import urlparse

_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f​-‏‪-‮⁦-⁩]")
_WS = re.compile(r"\s+")
_TAG = re.compile(r"<[^>]*>")
_BOLD = re.compile(r"\*\*(.+?)\*\*", re.S)
_PLACEHOLDER = re.compile(r"\{(\w+)\}")

# The only tags Telegram HTML mode accepts (and the ones templates may use).
ALLOWED_TAGS = {"b", "strong", "i", "em", "u", "ins", "s", "strike", "del", "a", "code", "pre", "blockquote", "tg-spoiler"}


def esc(text) -> str:
    """Escape text for Telegram HTML so nothing in it can act as markup."""
    return html.escape(str(text), quote=False)


def esc_attr(text) -> str:
    return html.escape(str(text), quote=True)


def clean(text, max_len: int | None = None) -> str:
    """Tidy untrusted text: drop control characters and tags, collapse whitespace, truncate."""
    value = html.unescape(str(text or ""))
    value = _TAG.sub("", value)
    value = _WS.sub(" ", _CONTROL.sub("", value)).strip()
    if max_len and len(value) > max_len:
        value = value[: max_len - 1].rstrip() + "…"
    return value


def safe_url(url, allowed_domains=None) -> str | None:
    """Return the URL if it is plain https (optionally on an allowed domain), else None."""
    if not isinstance(url, str):
        return None
    url = url.strip()
    if not url or any(ch in url for ch in ' <>"\'\\\n\r\t'):
        return None
    try:
        parsed = urlparse(url)
    except ValueError:
        return None
    if parsed.scheme != "https" or not parsed.hostname:
        return None
    host = parsed.hostname.lower()
    if allowed_domains:
        if not any(host == d.lower() or host.endswith("." + d.lower()) for d in allowed_domains):
            return None
    return url


def md_bold_to_html(text: str) -> str:
    return _BOLD.sub(r"<b>\1</b>", text)


def render(template: str, **values) -> str:
    """Fill {placeholders} in a trusted template.

    **bold** in the template becomes <b>bold</b> first; values are inserted afterwards
    (callers must escape them), so nothing inside a value is ever reinterpreted.
    Unknown {placeholders} are left alone.
    """
    text = md_bold_to_html(template.strip("\n"))
    return _PLACEHOLDER.sub(lambda m: str(values[m.group(1)]) if m.group(1) in values else m.group(0), text)


def strip_html(text: str) -> str:
    return html.unescape(_TAG.sub("", text))


_TAG_FIND = re.compile(r"<(/?)([A-Za-z][A-Za-z0-9-]*)([^<>]*)>")
_ENTITY = re.compile(r"&(#\d+|#x[0-9a-fA-F]+|[A-Za-z]+);")


def validate_html(text: str) -> list[str]:
    """Return a list of problems that would make Telegram reject this HTML ([] = fine)."""
    problems: list[str] = []
    stack: list[str] = []
    for match in _TAG_FIND.finditer(text):
        closing, name, attrs = match.group(1) == "/", match.group(2).lower(), match.group(3)
        if name not in ALLOWED_TAGS:
            problems.append(f"unsupported tag <{name}>")
        elif closing:
            if not stack or stack[-1] != name:
                problems.append(f"closing </{name}> without matching opening tag")
            else:
                stack.pop()
        else:
            if name == "a" and "href" not in attrs:
                problems.append("<a> tag without href")
            stack.append(name)
    for name in stack:
        problems.append(f"<{name}> is never closed")
    leftover = _ENTITY.sub("", _TAG_FIND.sub("", text))
    if "<" in leftover or ">" in leftover:
        problems.append("stray < or > (write &lt; or &gt;)")
    if "&" in leftover:
        problems.append("stray & (write &amp;)")
    return problems
