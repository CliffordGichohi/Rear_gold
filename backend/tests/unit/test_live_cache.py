import asyncio

from gold_intel.api.live_cache import AsyncTtlCache


async def test_live_cache_coalesces_concurrent_factories() -> None:
    cache = AsyncTtlCache[str, int](ttl_seconds=30, max_entries=1)
    calls = 0

    async def factory() -> int:
        nonlocal calls
        calls += 1
        await asyncio.sleep(0)
        return 42

    values = await asyncio.gather(
        cache.get_or_create("same", factory),
        cache.get_or_create("same", factory),
        cache.get_or_create("same", factory),
    )

    assert values == [42, 42, 42]
    assert calls == 1
