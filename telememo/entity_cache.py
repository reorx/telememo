"""Persistent JSON cache for Telegram entity names.

Saves resolved channel/user id -> display name so forward-source resolution
doesn't have to call ``client.get_entity`` for ids it has already seen.

Schema (small, debuggable):

    {
      "channels": {"123": "Channel Name"},
      "users":    {"42":  "Alice B"}
    }

Atomic save: writes to ``<path>.tmp`` then ``os.replace`` to avoid partial
files on crash. Single asyncio loop, no concurrency guard needed.
"""

import json
import os
from pathlib import Path
from typing import Optional, Tuple


class EntityNameCache:
    """File-backed name cache; in-memory dicts flushed on every set."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._channels: dict[int, str] = {}
        self._users: dict[int, str] = {}
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        with self.path.open('r', encoding='utf-8') as f:
            data = json.load(f)
        for k, v in (data.get('channels') or {}).items():
            self._channels[int(k)] = v
        for k, v in (data.get('users') or {}).items():
            self._users[int(k)] = v

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + '.tmp')
        payload = {
            'channels': {str(k): v for k, v in self._channels.items()},
            'users': {str(k): v for k, v in self._users.items()},
        }
        with tmp.open('w', encoding='utf-8') as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        os.replace(tmp, self.path)

    def get_channel(self, channel_id: int) -> Tuple[bool, Optional[str]]:
        """Returns ``(hit, name)``. ``hit=False`` means key not present."""
        if channel_id in self._channels:
            return True, self._channels[channel_id]
        return False, None

    def get_user(self, user_id: int) -> Tuple[bool, Optional[str]]:
        if user_id in self._users:
            return True, self._users[user_id]
        return False, None

    def set_channel(self, channel_id: int, name: Optional[str]) -> None:
        """Cache a channel name. ``None`` is ignored (we don't negative-cache yet)."""
        if name is None or self._channels.get(channel_id) == name:
            return
        self._channels[channel_id] = name
        self._save()

    def set_user(self, user_id: int, name: Optional[str]) -> None:
        if name is None or self._users.get(user_id) == name:
            return
        self._users[user_id] = name
        self._save()
