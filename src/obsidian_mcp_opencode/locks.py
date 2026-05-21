from __future__ import annotations

import asyncio


class LockRegistry:
    """Per-key asyncio.Lock cache. Thread-safe enough for a single asyncio loop."""

    def __init__(self) -> None:
        self._locks: dict[str, asyncio.Lock] = {}

    def lock_for(self, key: str) -> asyncio.Lock:
        """Return the lock for key, creating it if needed."""

        lock = self._locks.get(key)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[key] = lock
        return lock
