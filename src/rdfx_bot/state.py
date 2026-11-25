"""The small 'what have I already sent' memory (state/sent.json)."""

from __future__ import annotations

import json
import logging
import os
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

log = logging.getLogger(__name__)


class State:
    def __init__(self, path: Path, data: dict | None = None):
        self.path = Path(path)
        data = data or {}
        self.sent: dict[str, str] = dict(data.get("sent") or {})
        self.alerts: dict[str, str] = dict(data.get("alerts") or {})
        self.rotation: dict[str, str] = dict(data.get("rotation") or {})
        self.notices: dict[str, str] = dict(data.get("notices") or {})  # failure notices already sent to the owner

    @classmethod
    def load(cls, path: Path) -> "State":
        path = Path(path)
        if not path.exists():
            return cls(path)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise ValueError("state file is not a JSON object")
            return cls(path, data)
        except (ValueError, OSError) as exc:
            backup = path.with_suffix(".corrupt")
            log.error("State file unreadable (%s). Keeping a copy as %s and starting fresh.", type(exc).__name__, backup.name)
            try:
                os.replace(path, backup)
            except OSError:
                pass
            return cls(path)

    # -- slots ---------------------------------------------------------------
    def has_sent(self, slot_id: str) -> bool:
        return slot_id in self.sent

    def mark_sent(self, slot_id: str, now: datetime) -> None:
        self.sent[slot_id] = now.isoformat(timespec="seconds")

    # -- alerts --------------------------------------------------------------
    def has_alerted(self, event_id: str) -> bool:
        return event_id in self.alerts

    def mark_alerted(self, event_id: str, now: datetime) -> None:
        self.alerts[event_id] = now.isoformat(timespec="seconds")

    # -- rotation ------------------------------------------------------------
    def last_rotation(self, pool: str) -> str | None:
        return self.rotation.get(pool)

    def set_rotation(self, pool: str, message_id: str) -> None:
        self.rotation[pool] = message_id

    # -- owner notices -----------------------------------------------------------
    def has_noticed(self, key: str) -> bool:
        return key in self.notices

    def mark_noticed(self, key: str, now: datetime) -> None:
        self.notices[key] = now.isoformat(timespec="seconds")

    # -- housekeeping --------------------------------------------------------
    def prune(self, now: datetime, days: int = 14) -> None:
        cutoff = now - timedelta(days=days)
        for table in (self.sent, self.alerts, self.notices):
            for key, stamp in list(table.items()):
                try:
                    if datetime.fromisoformat(stamp) < cutoff:
                        del table[key]
                except (TypeError, ValueError):
                    del table[key]

    def to_dict(self) -> dict:
        return {"alerts": self.alerts, "notices": self.notices, "rotation": self.rotation, "sent": self.sent}

    def save(self) -> None:
        """Write atomically so a crash can never leave a half-written file."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(self.to_dict(), indent=2, sort_keys=True) + "\n"
        fd, tmp = tempfile.mkstemp(dir=self.path.parent, prefix=".state-", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(payload)
            os.replace(tmp, self.path)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)
