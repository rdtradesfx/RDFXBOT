"""Everything a message module needs, bundled in one object."""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import datetime

from .config import Config
from .services.calendar_feed import CalendarService
from .services.rss import NewsService
from .state import State


@dataclass
class Context:
    now: datetime  # aware, UK time
    cfg: Config
    state: State
    calendar: CalendarService
    news: NewsService
    rng: random.Random = field(default_factory=random.Random)
    dry_run: bool = False

    @property
    def today(self):
        return self.now.astimezone(self.cfg.tz).date()
