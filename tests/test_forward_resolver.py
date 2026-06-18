"""EntityNameCache + resolve_forward_entity_names — the cache layer that fills
forward source names without re-hitting Telegram for every ingest."""

from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest

from telememo.entity_cache import EntityNameCache
from telememo.telegram import resolve_forward_entity_names
from telememo.types import MessageData


class Obj:
    """Minimal attribute bag matching test_part_a's helper style."""

    def __init__(self, **kw):
        self.__dict__.update(kw)


def _fwd_md(*, channel_id=None, channel_name=None, user_id=None, user_name=None):
    dt = datetime(2026, 6, 1, tzinfo=timezone.utc)
    return MessageData(
        id=1,
        channel_id=999,
        date=dt,
        is_forwarded=True,
        fwd_from_channel_id=channel_id,
        fwd_from_channel_name=channel_name,
        fwd_from_user_id=user_id,
        fwd_from_user_name=user_name,
    )


# --- EntityNameCache file-backed round-trip --------------------------------


def test_cache_round_trip(tmp_path):
    path = tmp_path / 'cache.json'
    c = EntityNameCache(path)
    c.set_channel(123, 'Origin')
    c.set_user(42, 'Alice B')

    reloaded = EntityNameCache(path)
    assert reloaded.get_channel(123) == (True, 'Origin')
    assert reloaded.get_user(42) == (True, 'Alice B')


def test_cache_miss_returns_not_hit(tmp_path):
    c = EntityNameCache(tmp_path / 'cache.json')
    assert c.get_channel(999) == (False, None)
    assert c.get_user(999) == (False, None)


def test_cache_skips_none_values(tmp_path):
    """``None`` is not stored (no negative caching in this rev)."""
    path = tmp_path / 'cache.json'
    c = EntityNameCache(path)
    c.set_channel(7, None)
    assert c.get_channel(7) == (False, None)
    # Nothing persisted -> file may or may not exist; reload still empty.
    reloaded = EntityNameCache(path)
    assert reloaded.get_channel(7) == (False, None)


# --- resolve_forward_entity_names cascade ---------------------------------


@pytest.mark.asyncio
async def test_resolver_skips_non_forward(tmp_path):
    cache = EntityNameCache(tmp_path / 'c.json')
    client = AsyncMock()
    md = MessageData(id=1, channel_id=1, date=datetime(2026, 6, 1, tzinfo=timezone.utc), is_forwarded=False)
    await resolve_forward_entity_names(md, client, cache, allow_network=True)
    client.get_entity.assert_not_awaited()


@pytest.mark.asyncio
async def test_resolver_primes_cache_when_name_already_known(tmp_path):
    """Extraction-filled names feed the cache so siblings need no client call."""
    cache = EntityNameCache(tmp_path / 'c.json')
    client = AsyncMock()
    md = _fwd_md(channel_id=555, channel_name='Origin')
    await resolve_forward_entity_names(md, client, cache, allow_network=True)
    client.get_entity.assert_not_awaited()
    assert cache.get_channel(555) == (True, 'Origin')


@pytest.mark.asyncio
async def test_resolver_cache_hit_skips_client(tmp_path):
    cache = EntityNameCache(tmp_path / 'c.json')
    cache.set_channel(555, 'Cached Name')
    client = AsyncMock()
    md = _fwd_md(channel_id=555)
    await resolve_forward_entity_names(md, client, cache, allow_network=True)
    client.get_entity.assert_not_awaited()
    assert md.fwd_from_channel_name == 'Cached Name'


@pytest.mark.asyncio
async def test_resolver_network_fallback_for_channel(tmp_path):
    cache = EntityNameCache(tmp_path / 'c.json')
    client = AsyncMock()
    client.get_entity.return_value = Obj(title='Resolved Chan')
    md = _fwd_md(channel_id=555)
    await resolve_forward_entity_names(md, client, cache, allow_network=True)
    client.get_entity.assert_awaited_once_with(555)
    assert md.fwd_from_channel_name == 'Resolved Chan'
    assert cache.get_channel(555) == (True, 'Resolved Chan')


@pytest.mark.asyncio
async def test_resolver_network_fallback_for_user(tmp_path):
    cache = EntityNameCache(tmp_path / 'c.json')
    client = AsyncMock()
    client.get_entity.return_value = Obj(first_name='Alice', last_name='B', username='ab')
    md = _fwd_md(user_id=42)
    await resolve_forward_entity_names(md, client, cache, allow_network=True)
    client.get_entity.assert_awaited_once_with(42)
    assert md.fwd_from_user_name == 'Alice B'
    assert cache.get_user(42) == (True, 'Alice B')


@pytest.mark.asyncio
async def test_resolver_no_network_when_disallowed(tmp_path):
    """Realtime path: cache miss must leave the name None, never call the client."""
    cache = EntityNameCache(tmp_path / 'c.json')
    client = AsyncMock()
    md = _fwd_md(channel_id=555)
    await resolve_forward_entity_names(md, client, cache, allow_network=False)
    client.get_entity.assert_not_awaited()
    assert md.fwd_from_channel_name is None
