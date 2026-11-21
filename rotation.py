"""Random-but-never-the-same-twice-in-a-row picking."""

from __future__ import annotations

import random


def pick(ids: list[str], last: str | None, rng: random.Random) -> str:
    """Pick one id at random, avoiding `last` whenever there is more than one choice."""
    if not ids:
        raise ValueError("nothing to pick from")
    choices = [i for i in ids if i != last] if len(ids) > 1 else list(ids)
    return rng.choice(choices)
