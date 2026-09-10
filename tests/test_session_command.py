"""`telememo session` — tell apart the two ways a session goes wrong.

A schema-version mismatch and a revoked authorization both surface as "sync
doesn't work", but the fixes are opposite (upgrade Telethon vs. log in again).
These cases pin down that the diagnostic reports each one distinctly — and that
it still reports when the session is too new for Telethon to even open.
"""

import sqlite3

import pytest
import telethon
from telethon.sessions.sqlite import CURRENT_VERSION

from telememo import telegram as telegram_module
from telememo.cli import format_session_status
from telememo.telegram import inspect_session, inspect_session_file


def write_session_file(path, version: int) -> None:
    conn = sqlite3.connect(str(path))
    conn.execute('create table version (version integer primary key)')
    conn.execute('insert into version values (?)', (version,))
    conn.commit()
    conn.close()


class Me:
    def __init__(self, id, username, phone):
        self.id = id
        self.username = username
        self.phone = phone


class FakeTelethonClient:
    """Stand-in for TelethonClient that records whether the network was touched."""

    instances = 0
    authorized = True

    def __init__(self, *args, **kwargs):
        type(self).instances += 1
        self.disconnected = False

    async def connect(self):
        pass

    async def is_user_authorized(self):
        return type(self).authorized

    async def get_me(self):
        return Me(id=42, username='reorx', phone='1929')

    async def disconnect(self):
        self.disconnected = True


@pytest.fixture
def fake_client(monkeypatch):
    FakeTelethonClient.instances = 0
    FakeTelethonClient.authorized = True
    monkeypatch.setattr(telegram_module, 'TelethonClient', FakeTelethonClient)
    return FakeTelethonClient


# --- inspect_session_file (local only, never touches the network) -----------


def test_healthy_session_file_is_compatible(tmp_path):
    session = tmp_path / 'telethon.session'
    write_session_file(session, CURRENT_VERSION)

    status = inspect_session_file(str(session))

    assert status.exists is True
    assert status.schema_version == CURRENT_VERSION
    assert status.supported_schema_version == CURRENT_VERSION
    assert status.telethon_version == telethon.__version__
    assert status.compatible is True
    assert status.authorized is None  # not checked at this layer


def test_too_new_session_file_is_incompatible(tmp_path):
    session = tmp_path / 'telethon.session'
    write_session_file(session, CURRENT_VERSION + 1)

    status = inspect_session_file(str(session))

    assert status.exists is True
    assert status.schema_version == CURRENT_VERSION + 1
    assert status.compatible is False


def test_missing_session_file_is_reported_not_raised(tmp_path):
    status = inspect_session_file(str(tmp_path / 'nope.session'))

    assert status.exists is False
    assert status.schema_version is None
    assert status.compatible is True  # nothing known to be wrong


# --- inspect_session (adds the authorization probe) -------------------------


async def test_authorized_session_reports_account(tmp_path, fake_client):
    session = tmp_path / 'telethon.session'
    write_session_file(session, CURRENT_VERSION)

    status = await inspect_session(str(session), api_id=1, api_hash='x')

    assert status.authorized is True
    assert status.user_id == 42
    assert status.username == 'reorx'
    assert fake_client.instances == 1


async def test_revoked_session_reports_unauthorized(tmp_path, fake_client):
    session = tmp_path / 'telethon.session'
    write_session_file(session, CURRENT_VERSION)
    fake_client.authorized = False

    status = await inspect_session(str(session), api_id=1, api_hash='x')

    assert status.authorized is False
    assert status.user_id is None


async def test_incompatible_session_skips_the_network(tmp_path, fake_client):
    """The whole point: this command must work when a client cannot be built."""
    session = tmp_path / 'telethon.session'
    write_session_file(session, CURRENT_VERSION + 1)

    status = await inspect_session(str(session), api_id=1, api_hash='x')

    assert status.compatible is False
    assert status.authorized is None
    assert fake_client.instances == 0


async def test_missing_session_skips_the_network(tmp_path, fake_client):
    status = await inspect_session(str(tmp_path / 'nope.session'), api_id=1, api_hash='x')

    assert status.exists is False
    assert status.authorized is None
    assert fake_client.instances == 0


# --- rendering --------------------------------------------------------------


def test_authorized_output_names_the_account(tmp_path):
    write_session_file(tmp_path / 'telethon.session', CURRENT_VERSION)
    status = inspect_session_file(str(tmp_path / 'telethon.session'))
    status.authorized = True
    status.user_id = 42
    status.username = 'reorx'

    out = format_session_status(status)

    assert 'reorx' in out
    assert '42' in out
    assert str(CURRENT_VERSION) in out


def test_incompatible_output_says_upgrade_telethon(tmp_path):
    write_session_file(tmp_path / 'telethon.session', CURRENT_VERSION + 1)

    out = format_session_status(inspect_session_file(str(tmp_path / 'telethon.session')))

    assert 'upgrade' in out.lower()
    assert str(CURRENT_VERSION + 1) in out


def test_unauthorized_output_says_log_in_again(tmp_path):
    write_session_file(tmp_path / 'telethon.session', CURRENT_VERSION)
    status = inspect_session_file(str(tmp_path / 'telethon.session'))
    status.authorized = False

    out = format_session_status(status)

    assert 'log in' in out.lower()


def test_missing_output_says_no_session_yet(tmp_path):
    out = format_session_status(inspect_session_file(str(tmp_path / 'nope.session')))

    assert 'not found' in out.lower()
