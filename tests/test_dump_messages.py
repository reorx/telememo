"""Tests for `dump-messages` re-running over messages that are already stored.

Root cause covered: db.save_message() built an UPDATE query without executing it,
so a second dump left the old row in place (and printed a debug line to stdout).

Telegram is fully mocked — no network, no credentials required.
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from telememo import core, db
from telememo.types import ChannelInfo, Config, MessageData, WebPagePreview


IS_FILTERED_FIELDS = {'messages': [{'name': 'is_filtered', 'type': 'BOOLEAN', 'default': 0}]}

DT = datetime(2026, 6, 1, tzinfo=timezone.utc)


@pytest.fixture
def mem_db():
    """Fresh in-memory DB with a condenser-style extension column."""
    if not db.db.is_closed():
        db.close_db()
    db.init_db(':memory:', optional_fields=IS_FILTERED_FIELDS)
    db.get_or_create_channel(ChannelInfo(id=1, title='A'))
    yield
    db.close_db()


@pytest.fixture
def scraper(monkeypatch):
    """Scraper whose Telegram client is a mock; feed it with `_serve`."""
    monkeypatch.setattr(core, 'TelegramClient', MagicMock())
    return core.Scraper(Config(api_id=1, api_hash='hash'))


def _md(mid, **extra):
    extra.setdefault('text', 'x')
    return MessageData(id=mid, channel_id=1, date=DT, **extra)


def _serve(scraper, message_datas):
    """Make the mocked Telegram client yield the given messages."""

    async def get_messages(channel_name, min_id=0, limit=None):
        for message_data in message_datas:
            yield message_data

    scraper.telegram.get_messages = get_messages
    scraper.telegram.get_message_count = AsyncMock(return_value=len(message_datas))


async def test_redump_updates_existing_message(mem_db, scraper):
    _serve(scraper, [_md(10, text='old', views=1, replies=0)])
    await scraper.dump_messages('chan')

    edited = _md(10, text='new', views=99, replies=3, is_edited=True, edit_date=DT + timedelta(hours=1))
    _serve(scraper, [edited])
    await scraper.dump_messages('chan')

    assert db.get_message_count(1) == 1
    row = db.get_message_by_id(1, 10)
    assert row.text == 'new'
    assert row.views == 99
    assert row.replies == 3
    assert row.is_edited is True


async def test_redump_refreshes_counters_of_never_edited_message(mem_db, scraper):
    _serve(scraper, [_md(10, views=1, forwards=0, replies=0)])
    await scraper.dump_messages('chan')

    _serve(scraper, [_md(10, views=50, forwards=2, replies=4)])
    await scraper.dump_messages('chan')

    row = db.get_message_by_id(1, 10)
    assert (row.views, row.forwards, row.replies) == (50, 2, 4)


async def test_redump_backfills_all_data_columns(mem_db, scraper):
    _serve(scraper, [_md(10)])
    await scraper.dump_messages('chan')

    full = _md(
        10,
        sender_name='alice',
        media_type='photo',
        has_media=True,
        media_width=640,
        media_height=480,
        webpage=WebPagePreview(url='https://example.com', title='Example'),
        is_forwarded=True,
        fwd_from_channel_id=555,
        fwd_from_channel_name='src',
    )
    _serve(scraper, [full])
    await scraper.dump_messages('chan')

    row = db.get_message_by_id(1, 10)
    assert row.sender_name == 'alice'
    assert (row.media_type, row.media_width, row.media_height) == ('photo', 640, 480)
    assert 'example.com' in row.webpage
    assert row.is_forwarded is True
    assert row.fwd_from_channel_name == 'src'


async def test_redump_keeps_extension_columns(mem_db, scraper):
    _serve(scraper, [_md(10, text='old')])
    await scraper.dump_messages('chan')
    db.db.execute_sql('UPDATE messages SET is_filtered = 1 WHERE channel_id = 1 AND id = 10')

    _serve(scraper, [_md(10, text='new')])
    await scraper.dump_messages('chan')

    text, is_filtered = db.db.execute_sql(
        'SELECT text, is_filtered FROM messages WHERE channel_id = 1 AND id = 10'
    ).fetchone()
    assert text == 'new'
    assert is_filtered == 1


async def test_redump_mixes_new_and_existing_messages(mem_db, scraper):
    _serve(scraper, [_md(10, text='old')])
    await scraper.dump_messages('chan')

    _serve(scraper, [_md(11, text='fresh'), _md(10, text='new')])
    messages = await scraper.dump_messages('chan')

    assert [m.id for m in messages] == [11, 10]
    assert db.get_message_count(1) == 2
    assert db.get_message_by_id(1, 10).text == 'new'
    assert db.get_message_by_id(1, 11).text == 'fresh'


async def test_redump_prints_nothing(mem_db, scraper, capsys):
    _serve(scraper, [_md(10, text='old')])
    await scraper.dump_messages('chan')
    _serve(scraper, [_md(10, text='new')])
    await scraper.dump_messages('chan')

    assert capsys.readouterr().out == ''


async def test_dry_run_does_not_touch_existing_message(mem_db, scraper):
    _serve(scraper, [_md(10, text='old')])
    await scraper.dump_messages('chan')

    _serve(scraper, [_md(10, text='new')])
    rows = await scraper.dump_messages('chan', dry_run=True)

    assert rows[0]['text'] == 'new'
    assert db.get_message_by_id(1, 10).text == 'old'
