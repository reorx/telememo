"""Stored message -> SQLite search -> CLI output, without Telegram or credentials."""

from datetime import datetime, timedelta, timezone

import pytest
from click.testing import CliRunner

from telememo import config, db
from telememo.cli import cli
from telememo.types import ChannelInfo, MessageData, WebPagePreview


@pytest.fixture
def archive(tmp_path, monkeypatch):
    monkeypatch.setenv('XDG_CONFIG_HOME', str(tmp_path / 'config'))
    monkeypatch.setenv('XDG_DATA_HOME', str(tmp_path / 'data'))
    config_dir = config.ensure_config_dir()
    (config_dir / 'config.py').write_text("TELEGRAM_API_ID = 1\nTELEGRAM_API_HASH = 'test'\n")
    channel_dir = config.ensure_channel_dir('archive')
    if not db.db.is_closed():
        db.close_db()
    db.init_db(str(channel_dir / 'channel.db'))
    db.get_or_create_channel(ChannelInfo(id=1, title='Archive', username='archive'))
    db.get_or_create_channel(ChannelInfo(id=2, title='Other', username='other'))
    yield CliRunner()
    db.close_db()


def store(message_id: int, text=None, webpage=None, channel_id=1):
    return db.save_message(MessageData(
        id=message_id,
        channel_id=channel_id,
        date=datetime(2026, 6, 1, tzinfo=timezone.utc) + timedelta(minutes=message_id),
        text=text,
        webpage=webpage,
    ))


def test_default_search_only_matches_body(archive):
    store(1, text='深度杂谈正文')
    store(2, text='分享链接', webpage=WebPagePreview(title='深度杂谈标题'))

    result = archive.invoke(cli, ['-c', 'archive', 'search', '深度杂谈'])

    assert result.exit_code == 0, result.output
    assert 'Message ID: 1 ' in result.output
    assert 'Message ID: 2 ' not in result.output
    assert 'Webpage' not in result.output


@pytest.mark.parametrize('field,value,query', [
    ('title', '巨构主题深度杂谈', '深度杂谈'),
    ('description', '这是犯罪的邀约', '犯罪'),
    ('site_name', '哔哩哔哩', '哔哩'),
    ('author', '多边兽2', '多边兽'),
    ('url', 'https://example.com/preview-target', 'preview-target'),
    ('display_url', 'example.com/display-target', 'display-target'),
])
def test_include_webpage_finds_and_displays_preview_fields(archive, field, value, query):
    store(1, webpage=WebPagePreview(**{field: value}))

    result = archive.invoke(cli, ['-c', 'archive', 'search', query, '--include-webpage'])

    assert result.exit_code == 0, result.output
    assert 'Message ID: 1 ' in result.output
    assert value in result.output
    assert 'Webpage' in result.output


def test_include_webpage_preserves_channel_order_limit_and_unique_results(archive):
    store(1, text='needle')
    store(2, webpage=WebPagePreview(title='needle'))
    store(3, text='needle', webpage=WebPagePreview(description='needle'))
    store(4, webpage=WebPagePreview(title='needle'), channel_id=2)
    store(5, text='unrelated')

    rows = db.search_messages('needle', channel_id=1, limit=2, include_webpage=True)
    assert [row.id for row in rows] == [3, 2]
    assert [(row.channel_id, row.id) for row in db.search_messages('needle', include_webpage=True)] == [
        (2, 4), (1, 3), (1, 2), (1, 1),
    ]

    result = archive.invoke(cli, ['-c', 'archive', 'search', 'needle', '--include-webpage', '--limit', '2'])
    assert result.exit_code == 0, result.output
    assert result.output.count('Message ID:') == 2
    assert result.output.index('Message ID: 3 ') < result.output.index('Message ID: 2 ')
    assert 'Message ID: 4 ' not in result.output


@pytest.mark.parametrize('query', ['has_photo', 'true', 'null'])
def test_include_webpage_does_not_match_json_metadata(archive, query):
    store(1, webpage=WebPagePreview(title='An article', has_photo=True))

    result = archive.invoke(cli, ['-c', 'archive', 'search', query, '--include-webpage'])

    assert result.exit_code == 0, result.output
    assert 'No results found' in result.output


def test_webpage_option_rejects_comments_only_search(archive):
    result = archive.invoke(cli, ['-c', 'archive', 'search', 'keyword', '--comments', '--include-webpage'])

    assert result.exit_code == 2
    assert '--include-webpage cannot be used with --comments' in result.output
