"""Part A acceptance tests (single-DB mode, forward fields, TelegramService).

Telegram is fully mocked — no network, no credentials required.
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from telethon.errors import SessionPasswordNeededError
from telethon.sessions import StringSession

from telememo import db
from telememo.service import TelegramService
from telememo.telegram import convert_message_to_data
from telememo.types import ChannelInfo, MessageData
from telememo.utils import group_messages_to_display


IS_FILTERED_FIELDS = {'messages': [{'name': 'is_filtered', 'type': 'BOOLEAN', 'default': 0}]}


class Obj:
    """Minimal attribute bag whose hasattr() reflects only the keys we set."""

    def __init__(self, **kw):
        self.__dict__.update(kw)


@pytest.fixture
def mem_db():
    """Fresh in-memory DB with the condenser is_filtered extension column."""
    if not db.db.is_closed():
        db.close_db()
    db.init_db(':memory:', optional_fields=IS_FILTERED_FIELDS)
    yield
    db.close_db()


def _md(channel_id, mid, dt, text='x', **extra):
    return MessageData(id=mid, channel_id=channel_id, text=text, date=dt, **extra)


def _row(md: MessageData) -> dict:
    from telememo.service import _message_data_to_row

    return _message_data_to_row(md)


def _raw(mid, date, channel_id=1, text='t', fwd_from=None, forward=None):
    kw = dict(
        id=mid,
        peer_id=Obj(channel_id=channel_id),
        text=text,
        date=date,
        sender=None,
        sender_id=None,
        media=None,
        views=1,
        forwards=0,
        edit_date=None,
    )
    if fwd_from is not None:
        kw['fwd_from'] = fwd_from
    if forward is not None:
        kw['forward'] = forward
    return Obj(**kw)


# --- A1: single-DB mode + optional_fields ----------------------------------


def test_single_db_cross_channel_ordering(mem_db):
    db.get_or_create_channel(ChannelInfo(id=1, title='A'))
    db.get_or_create_channel(ChannelInfo(id=2, title='B'))
    base = datetime(2026, 6, 1, tzinfo=timezone.utc)
    db.save_messages_batch_smart(
        [
            _md(1, 10, base + timedelta(minutes=1)),
            _md(2, 20, base + timedelta(minutes=2)),
            _md(1, 11, base + timedelta(minutes=3)),
        ],
        {},
    )
    rows = list(db.Message.select().order_by(db.Message.date.desc()))
    assert [(r.channel_id, r.id) for r in rows] == [(1, 11), (2, 20), (1, 10)]


def test_optional_field_added_and_idempotent(mem_db):
    cols = db._existing_columns('messages')
    assert 'is_filtered' in cols
    # Re-applying is a no-op (does not raise on the existing column).
    db.apply_optional_fields(IS_FILTERED_FIELDS)
    assert 'is_filtered' in db._existing_columns('messages')


def test_is_filtered_preserved_on_incremental_update(mem_db):
    db.get_or_create_channel(ChannelInfo(id=1, title='A'))
    dt = datetime(2026, 6, 1, tzinfo=timezone.utc)
    db.save_message_smart(_md(1, 10, dt, text='hello'), None)
    # condenser writes the extension column directly
    db.db.execute_sql('UPDATE messages SET is_filtered=1 WHERE channel_id=? AND id=?', (1, 10))

    # telememo incremental edit (edit_date changes) must not clear is_filtered
    edited = _md(1, 10, dt, text='hello edited', is_edited=True, edit_date=dt + timedelta(hours=1))
    _, status = db.save_message_smart(edited, db.get_message_by_id(1, 10))
    assert status == 'updated'

    cur = db.db.execute_sql('SELECT is_filtered, text FROM messages WHERE channel_id=? AND id=?', (1, 10))
    is_filtered, text = cur.fetchone()
    assert is_filtered == 1
    assert text == 'hello edited'


# --- A2/A3: forward fields land in DB + DisplayMessage from stored columns ---


def test_convert_message_extracts_forward():
    dt = datetime(2026, 6, 1, tzinfo=timezone.utc)
    fwd = Obj(from_id=Obj(channel_id=555), date=dt, channel_post=999, post_author='auth')
    md = convert_message_to_data(_raw(5, dt, fwd_from=fwd))
    assert md.is_forwarded is True
    assert md.fwd_from_channel_id == 555
    assert md.fwd_from_message_id == 999
    assert md.fwd_post_author == 'auth'
    assert md.fwd_original_date == dt


def test_convert_message_resolves_visible_channel_name():
    """Visible-channel forwards pick the name from message.forward.chat.title."""
    dt = datetime(2026, 6, 1, tzinfo=timezone.utc)
    fwd = Obj(from_id=Obj(channel_id=555), date=dt, channel_post=999)
    forward = Obj(chat=Obj(title='Origin Chan'), sender=None)
    md = convert_message_to_data(_raw(5, dt, fwd_from=fwd, forward=forward))
    assert md.fwd_from_channel_id == 555
    assert md.fwd_from_channel_name == 'Origin Chan'


def test_convert_message_resolves_visible_user_name():
    """Visible-user forwards build the name from message.forward.sender."""
    dt = datetime(2026, 6, 1, tzinfo=timezone.utc)
    fwd = Obj(from_id=Obj(user_id=42), date=dt)
    forward = Obj(chat=None, sender=Obj(first_name='Alice', last_name='B', username='ab'))
    md = convert_message_to_data(_raw(5, dt, fwd_from=fwd, forward=forward))
    assert md.fwd_from_user_id == 42
    assert md.fwd_from_user_name == 'Alice B'


def test_convert_message_keeps_hidden_sender_name():
    """Hidden forwards (no visible entity) still fall back to fwd_from.from_name."""
    dt = datetime(2026, 6, 1, tzinfo=timezone.utc)
    fwd = Obj(from_name='Anon', date=dt)
    md = convert_message_to_data(_raw(5, dt, fwd_from=fwd))
    assert md.is_forwarded is True
    assert md.fwd_from_user_name == 'Anon'


def test_forward_fields_persist_and_display(mem_db):
    db.get_or_create_channel(ChannelInfo(id=1, title='A'))
    dt = datetime(2026, 6, 1, tzinfo=timezone.utc)
    md = _md(1, 10, dt, text='fwd', is_forwarded=True, fwd_from_channel_name='Origin', fwd_from_message_id=999)
    db.save_message_smart(md, None)

    row = db.get_message_by_id(1, 10)
    assert bool(row.is_forwarded) is True
    assert row.fwd_from_channel_name == 'Origin'

    displays = group_messages_to_display([_row(md)])
    assert len(displays) == 1
    assert displays[0].is_forwarded is True
    assert displays[0].forward_info.from_channel_name == 'Origin'


def test_convert_message_extracts_webpage():
    from telethon.tl.types import MessageMediaWebPage, WebPage, WebPageEmpty

    dt = datetime(2026, 6, 1, tzinfo=timezone.utc)
    wp = WebPage(
        id=1,
        url='https://example.com/post',
        display_url='example.com/post',
        hash=0,
        site_name='Example',
        title='A Title',
        description='A description',
        photo=Obj(),  # any non-None photo -> has_photo True
    )
    raw = _raw(7, dt, text='see https://example.com/post')
    raw.media = MessageMediaWebPage(webpage=wp)

    md = convert_message_to_data(raw)
    assert md.media_type == 'webpage'
    assert md.webpage is not None
    assert md.webpage.url == 'https://example.com/post'
    assert md.webpage.title == 'A Title'
    assert md.webpage.site_name == 'Example'
    assert md.webpage.has_photo is True

    # An unresolved preview (empty/pending) carries no metadata -> no webpage.
    raw.media = MessageMediaWebPage(webpage=WebPageEmpty(id=0))
    assert convert_message_to_data(raw).webpage is None


def test_webpage_persists_and_displays(mem_db):
    from telememo.types import WebPagePreview

    db.get_or_create_channel(ChannelInfo(id=1, title='A'))
    dt = datetime(2026, 6, 1, tzinfo=timezone.utc)
    wp = WebPagePreview(url='https://x.com', title='T', site_name='X', has_photo=True)
    md = _md(1, 20, dt, text='look', webpage=wp)
    db.save_message_smart(md, None)

    # Stored as JSON text in the native column.
    row = db.get_message_by_id(1, 20)
    import json

    assert json.loads(row.webpage)['title'] == 'T'

    # Carried onto the DisplayMessage.
    displays = group_messages_to_display([_row(md)])
    assert displays[0].webpage is not None
    assert displays[0].webpage.url == 'https://x.com'
    assert displays[0].webpage.has_photo is True


def test_album_grouping_from_rows():
    dt = datetime(2026, 6, 1, tzinfo=timezone.utc)
    a = _md(1, 10, dt, text=None, grouped_id=777, has_media=True, media_type='photo')
    b = _md(1, 11, dt, text='caption', grouped_id=777, has_media=True, media_type='photo')
    displays = group_messages_to_display([_row(a), _row(b)])
    assert len(displays) == 1
    assert displays[0].is_album is True
    assert len(displays[0].media_items) == 2
    assert displays[0].text == 'caption'


# --- A4/A5: TelegramService step login --------------------------------------


@pytest.mark.asyncio
async def test_step_login_ok():
    fake = MagicMock()
    fake.send_code_request = AsyncMock(return_value=Obj(phone_code_hash='HASH'))
    fake.sign_in = AsyncMock(return_value=None)
    fake.session.save = MagicMock(return_value='SESSIONSTR')

    svc = TelegramService(api_id=1, api_hash='h', client=fake)
    assert await svc.send_code('+100') == 'HASH'

    res = await svc.sign_in_code('+100', '12345', 'HASH')
    assert res.status == 'ok'
    assert res.session == 'SESSIONSTR'
    assert svc.is_authorized is True


@pytest.mark.asyncio
async def test_step_login_requires_2fa():
    fake = MagicMock()
    fake.send_code_request = AsyncMock(return_value=Obj(phone_code_hash='HASH'))
    fake.sign_in = AsyncMock(side_effect=SessionPasswordNeededError(request=None))
    fake.session.save = MagicMock(return_value='SESSIONSTR')

    svc = TelegramService(api_id=1, api_hash='h', client=fake)
    res = await svc.sign_in_code('+100', '12345', 'HASH')
    assert res.status == '2fa_required'
    assert res.session is None
    assert svc.is_authorized is False

    fake.sign_in = AsyncMock(return_value=None)
    res2 = await svc.sign_in_2fa('pw')
    assert res2.status == 'ok'
    assert res2.session == 'SESSIONSTR'
    assert svc.is_authorized is True


def test_session_roundtrip():
    s = StringSession().save()
    svc = TelegramService(api_id=12345, api_hash='abc', session=s)
    assert svc.export_session() == s


# --- A4/A5: backfill, subscribe, media --------------------------------------


@pytest.mark.asyncio
async def test_backfill_respects_since_days(mem_db):
    now = datetime.now(timezone.utc)
    entity = Obj(id=1, title='A', username='a', date=None)
    msgs = [
        _raw(30, now - timedelta(days=1)),
        _raw(29, now - timedelta(days=2)),
        _raw(28, now - timedelta(days=10)),  # older than 7-day cutoff
    ]

    async def fake_iter(entity, offset_id=0):
        for m in msgs:
            yield m

    fake = MagicMock()
    fake.get_entity = AsyncMock(return_value=entity)
    fake.iter_messages = MagicMock(side_effect=lambda entity, offset_id=0: fake_iter(entity, offset_id))

    svc = TelegramService(1, 'h', client=fake)
    got = [dm async for dm in svc.backfill(channel='a', since_days=7)]

    assert {dm.id for dm in got} == {30, 29}
    assert db.get_message_count(1) == 2


@pytest.mark.asyncio
async def test_backfill_pages_older_with_offset_and_limit(mem_db):
    """offset_id pages further back (strictly-older) and max_messages caps the pull;
    a backward fetch must not downgrade the sync watermark."""
    now = datetime.now(timezone.utc)
    entity = Obj(id=1, title='A', username='a', date=None)
    # full history newest-first: ids 50..41
    history = [_raw(mid, now - timedelta(days=51 - mid)) for mid in range(50, 40, -1)]

    async def fake_iter(entity, offset_id=0):
        for m in history:
            if offset_id and m.id >= offset_id:
                continue  # Telethon's offset_id yields only messages older than it
            yield m

    fake = MagicMock()
    fake.get_entity = AsyncMock(return_value=entity)
    fake.iter_messages = MagicMock(side_effect=lambda entity, offset_id=0: fake_iter(entity, offset_id))

    db.get_or_create_channel(ChannelInfo(id=1, title='A'))
    db.update_channel_sync_status(1, 50)  # we already synced up to the newest

    svc = TelegramService(1, 'h', client=fake)
    # already have 50..46; page 3 older than 46 -> 45, 44, 43
    got = [dm async for dm in svc.backfill(channel='a', offset_id=46, max_messages=3)]

    assert [dm.id for dm in got] == [45, 44, 43]
    assert db.get_channel(1).last_sync_message_id == 50  # backward fetch left the watermark alone


@pytest.mark.asyncio
async def test_subscribe_persists_and_dispatches(mem_db):
    db.get_or_create_channel(ChannelInfo(id=1, title='A'))
    captured = {}

    def add_handler(cb, event):
        captured['cb'] = cb

    fake = MagicMock()
    fake.add_event_handler = MagicMock(side_effect=add_handler)

    svc = TelegramService(1, 'h', client=fake)
    received = []

    async def on_msg(dm):
        received.append(dm)

    await svc.subscribe([1], on_message=on_msg)

    now = datetime.now(timezone.utc)
    await captured['cb'](Obj(message=_raw(100, now)))

    assert db.get_message_by_id(1, 100) is not None
    assert len(received) == 1
    assert received[0].id == 100


@pytest.mark.asyncio
async def test_subscribe_handles_new_and_edited(mem_db):
    """subscribe wires both NewMessage and MessageEdited; an edit updates text in place."""
    from telethon import events

    db.get_or_create_channel(ChannelInfo(id=1, title='A'))
    handlers = {}

    def add_handler(cb, event):
        handlers[type(event).__name__] = cb

    fake = MagicMock()
    fake.add_event_handler = MagicMock(side_effect=add_handler)

    svc = TelegramService(1, 'h', client=fake)
    received = []

    async def on_msg(dm):
        received.append(dm)

    await svc.subscribe([1], on_message=on_msg)
    assert {'NewMessage', 'MessageEdited'} <= set(handlers)
    assert handlers['NewMessage'] is handlers['MessageEdited']  # one handler, both events

    now = datetime.now(timezone.utc)
    await handlers['NewMessage'](Obj(message=_raw(100, now, text='original')))
    assert db.get_message_by_id(1, 100).text == 'original'

    # an edit on the same id (newer edit_date) updates the stored text in place
    edited = _raw(100, now, text='EDITED')
    edited.edit_date = now + timedelta(minutes=5)
    await handlers['MessageEdited'](Obj(message=edited))

    assert db.get_message_by_id(1, 100).text == 'EDITED'
    assert [dm.id for dm in received] == [100, 100]  # dispatched for the new + the edit


@pytest.mark.asyncio
async def test_get_media_thumb_and_full():
    raw = Obj(media=Obj(), file=Obj(mime_type='image/png'))
    fake = MagicMock()
    fake.get_messages = AsyncMock(return_value=raw)
    fake.download_media = AsyncMock(return_value=b'thumbbytes')

    async def fake_download(media):
        for c in (b'a', b'b'):
            yield c

    fake.iter_download = MagicMock(side_effect=lambda media: fake_download(media))

    svc = TelegramService(1, 'h', client=fake)

    stream, mime = await svc.get_media('a', 100, thumb=True)
    assert mime == 'image/jpeg'
    assert b''.join([c async for c in stream]) == b'thumbbytes'

    stream, mime = await svc.get_media('a', 100, thumb=False)
    assert mime == 'image/png'
    assert b''.join([c async for c in stream]) == b'ab'
