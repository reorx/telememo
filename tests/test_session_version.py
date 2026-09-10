"""Guard against a session file written by a newer Telethon.

Telethon stamps a schema version into its sqlite session file and only knows how
to *upgrade* it. When the on-disk version is newer than the running Telethon
(e.g. 1.44 wrote schema v8, then 1.42 opens it), Telethon skips its upgrade path
and blindly unpacks ``select * from sessions``, dying with an opaque
``ValueError: too many values to unpack (expected 5, got 6)``. These tests pin
down the friendly error we raise before that happens.
"""

import sqlite3

import pytest
from telethon.sessions.sqlite import CURRENT_VERSION

from telememo import cli as cli_module
from telememo.telegram import SessionVersionError, TelegramClient, check_session_compatibility


def write_session_file(path, version: int) -> None:
    """Create a minimal telethon-shaped session file stamped with ``version``."""
    conn = sqlite3.connect(str(path))
    conn.execute('create table version (version integer primary key)')
    conn.execute('insert into version values (?)', (version,))
    conn.commit()
    conn.close()


# --- check_session_compatibility -------------------------------------------


def test_newer_session_raises(tmp_path):
    session = tmp_path / 'telethon.session'
    write_session_file(session, CURRENT_VERSION + 1)

    with pytest.raises(SessionVersionError) as exc_info:
        check_session_compatibility(str(session))

    message = str(exc_info.value)
    assert str(session) in message
    assert str(CURRENT_VERSION + 1) in message
    assert str(CURRENT_VERSION) in message


def test_same_version_passes(tmp_path):
    session = tmp_path / 'telethon.session'
    write_session_file(session, CURRENT_VERSION)

    check_session_compatibility(str(session))


def test_older_session_passes(tmp_path):
    """Telethon upgrades older schemas by itself — nothing to warn about."""
    session = tmp_path / 'telethon.session'
    write_session_file(session, CURRENT_VERSION - 1)

    check_session_compatibility(str(session))


def test_missing_session_passes(tmp_path):
    """First run: no file yet, Telethon will create one."""
    check_session_compatibility(str(tmp_path / 'nope.session'))


def test_extension_is_appended_like_telethon(tmp_path):
    """Telethon appends ``.session`` to a name that lacks it; we must look there too."""
    write_session_file(tmp_path / 'telememo_session.session', CURRENT_VERSION + 1)

    with pytest.raises(SessionVersionError):
        check_session_compatibility(str(tmp_path / 'telememo_session'))


def test_non_sqlite_file_passes(tmp_path):
    """Garbage in the session path is Telethon's problem to report, not ours."""
    session = tmp_path / 'telethon.session'
    session.write_text('not a database')

    check_session_compatibility(str(session))


def test_sqlite_without_version_table_passes(tmp_path):
    session = tmp_path / 'telethon.session'
    conn = sqlite3.connect(str(session))
    conn.execute('create table unrelated (x integer)')
    conn.commit()
    conn.close()

    check_session_compatibility(str(session))


def test_in_memory_session_passes():
    check_session_compatibility(':memory:')


# --- TelegramClient wiring --------------------------------------------------


def test_client_init_rejects_newer_session(tmp_path):
    """The check runs before Telethon ever opens the file, so the crash never happens."""
    session = tmp_path / 'telethon.session'
    write_session_file(session, CURRENT_VERSION + 1)

    with pytest.raises(SessionVersionError):
        TelegramClient(api_id=1, api_hash='deadbeef', session_name=str(session))


# --- CLI reporting ----------------------------------------------------------


def test_cli_main_reports_without_traceback(monkeypatch, capsys):
    def boom():
        raise SessionVersionError('session too new')

    monkeypatch.setattr(cli_module, 'cli', boom)

    with pytest.raises(SystemExit) as exc_info:
        cli_module.main()

    assert exc_info.value.code == 1
    assert 'Error: session too new' in capsys.readouterr().err
