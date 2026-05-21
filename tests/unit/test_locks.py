from __future__ import annotations

import asyncio

import pytest

from obsidian_mcp_opencode.locks import LockRegistry

pytestmark = pytest.mark.asyncio

CONCURRENT_WORKER_COUNT = 2


async def test_same_key_returns_same_lock_instance() -> None:
    registry = LockRegistry()

    assert registry.lock_for("alpha") is registry.lock_for("alpha")


async def test_same_key_serializes_coroutines() -> None:
    registry = LockRegistry()
    events: list[str] = []

    async def worker(name: str) -> None:
        async with registry.lock_for("shared"):
            events.append(f"start:{name}")
            await asyncio.sleep(0.01)
            events.append(f"end:{name}")

    await asyncio.gather(worker("a"), worker("b"))

    assert events in [
        ["start:a", "end:a", "start:b", "end:b"],
        ["start:b", "end:b", "start:a", "end:a"],
    ]


async def test_different_keys_can_run_concurrently() -> None:
    registry = LockRegistry()
    started = asyncio.Event()
    finished: list[str] = []

    async def worker(name: str, key: str) -> None:
        async with registry.lock_for(key):
            finished.append(f"entered:{name}")
            if len(finished) == CONCURRENT_WORKER_COUNT:
                started.set()
            await started.wait()
            finished.append(f"exited:{name}")

    await asyncio.wait_for(
        asyncio.gather(worker("a", "one"), worker("b", "two")),
        timeout=0.5,
    )

    assert finished[:2] in (["entered:a", "entered:b"], ["entered:b", "entered:a"])
