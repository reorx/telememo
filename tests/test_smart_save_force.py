"""Tests for force-update semantics of smart save (sync --full backfill).

Covers two root causes:
1. save_message_smart short-circuits to 'unchanged' when edit_date is unchanged,
   so `sync --full` can never backfill columns added later (webpage, fwd_*).
2. The UPDATE branch only wrote a subset of columns, silently dropping
   fwd_*/media_*/sender_* data even when edit_date did change.
"""

from datetime import datetime, timedelta, timezone

import pytest

from telememo import db
from telememo.types import ChannelInfo, MessageData, WebPagePreview


IS_FILTERED_FIELDS = {'messages': [{'name': 'is_filtered', 'type': 'BOOLEAN', 'default': 0}]}


@pytest.fixture
def mem_db():
    """Fresh in-memory DB with a condenser-style extension column."""
    if not db.db.is_closed():
        db.close_db()
    db.init_db(':memory:', optional_fields=IS_FILTERED_FIELDS)
    db.get_or_create_channel(ChannelInfo(id=1, title='A'))
    yield
    db.close_db()


DT = datetime(2026, 6, 1, tzinfo=timezone.utc)


def _md(mid, **extra):
    extra.setdefault('text', 'x')
    return MessageData(id=mid, channel_id=1, date=DT, **extra)


def _full_md(mid, **extra):
    """MessageData carrying webpage + forward + media data."""
    return _md(
        mid,
        sender_id=42,
        sender_name='alice',
        media_type='photo',
        has_media=True,
        media_width=640,
        media_height=480,
        webpage=WebPagePreview(url='https://example.com', title='Example'),
        is_forwarded=True,
        fwd_from_channel_id=555,
        fwd_from_channel_name='src',
        fwd_from_message_id=999,
        fwd_original_date=DT - timedelta(days=1),
        fwd_post_author='auth',
        **extra,
    )


def test_force_backfills_webpage_and_forward_columns(mem_db):
    # Old row: ingested before webpage/fwd_* columns existed (all NULL/default)
    db.save_message_smart(_md(10), None)

    # Re-fetch with full data; edit_date unchanged (both None)
    _, status = db.save_message_smart(_full_md(10), db.get_message_by_id(1, 10), force=True)
    assert status == 'updated'

    row = db.get_message_by_id(1, 10)
    assert row.is_forwarded
    assert row.fwd_from_channel_id == 555
    assert row.fwd_from_channel_name == 'src'
    assert row.fwd_from_message_id == 999
    assert row.fwd_post_author == 'auth'
    assert row.media_width == 640
    assert row.media_height == 480
    assert row.sender_name == 'alice'
    assert row.webpage and 'example.com' in row.webpage


def test_no_force_unchanged_when_edit_date_same(mem_db):
    db.save_message_smart(_md(10), None)

    _, status = db.save_message_smart(_full_md(10), db.get_message_by_id(1, 10))
    assert status == 'unchanged'

    row = db.get_message_by_id(1, 10)
    assert not row.is_forwarded
    assert row.webpage is None


def test_normal_update_writes_all_columns(mem_db):
    db.save_message_smart(_md(10), None)

    # Edited message now carries forward/media data: UPDATE must not drop it
    edited = _full_md(10, text='edited', is_edited=True, edit_date=DT + timedelta(hours=1))
    _, status = db.save_message_smart(edited, db.get_message_by_id(1, 10))
    assert status == 'updated'

    row = db.get_message_by_id(1, 10)
    assert row.text == 'edited'
    assert row.is_forwarded
    assert row.fwd_from_channel_id == 555
    assert row.media_width == 640
    assert row.sender_name == 'alice'


def test_batch_smart_force_counts_updated(mem_db):
    db.save_messages_batch_smart([_md(10), _md(11)], {})

    existing = db.get_messages_by_ids(1, [10, 11, 12])
    _, added, updated, unchanged = db.save_messages_batch_smart(
        [_full_md(10), _full_md(11), _full_md(12)], existing, force=True
    )
    assert (added, updated, unchanged) == (1, 2, 0)
    assert db.get_message_by_id(1, 11).is_forwarded


def test_force_preserves_extension_columns(mem_db):
    db.save_message_smart(_md(10), None)
    db.db.execute_sql('UPDATE messages SET is_filtered=1 WHERE channel_id=? AND id=?', (1, 10))

    db.save_message_smart(_full_md(10), db.get_message_by_id(1, 10), force=True)

    cur = db.db.execute_sql('SELECT is_filtered FROM messages WHERE channel_id=? AND id=?', (1, 10))
    assert cur.fetchone()[0] == 1
