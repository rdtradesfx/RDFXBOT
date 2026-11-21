"""Plain HTTPS GET used for the free data feeds."""

from __future__ import annotations

import urllib.request

USER_AGENT = "Mozilla/5.0 (compatible; RDFX-Bot/1.0; +https://github.com)"


def http_get(url: str, timeout: int = 20, max_bytes: int = 3_000_000) -> bytes:
    if not url.lower().startswith("https://"):
        raise ValueError("only https:// URLs are allowed")
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/json, application/rss+xml, application/xml;q=0.9, text/xml;q=0.8, */*;q=0.5",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 (https only, checked above)
        data = response.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise ValueError("response too large")
    return data
