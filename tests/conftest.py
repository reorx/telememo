"""Pytest configuration and fixtures."""

import tempfile
from pathlib import Path

import pytest

from telememo import config, db
from telememo.types import Config


@pytest.fixture
def test_db():
    """Create a temporary test database."""
    # Create a temporary database file
    temp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    temp_db.close()

    # Initialize database
    db.init_db(temp_db.name)

    yield temp_db.name

    # Cleanup
    db.close_db()
    Path(temp_db.name).unlink(missing_ok=True)


@pytest.fixture
def test_config(test_db, tmp_path):
    """Create test configuration."""
    try:
        # Load config from ~/.config/telememo/config.py
        app_config = config.get_config()
    except ValueError:
        pytest.skip("Missing configuration file at ~/.config/telememo/config.py for integration tests")

    # Use a temporary session file for tests
    test_session = tmp_path / "test_session.session"

    return Config(
        api_id=app_config.api_id,
        api_hash=app_config.api_hash,
        phone=app_config.phone,
        db_path=test_db,
        session_name=str(test_session),
    )


@pytest.fixture
def test_channel():
    """Get test channel from config or use default."""
    # For integration tests, use the default channel from config or a default
    # The user must have access to this channel
    default = config.get_default_channel()
    return default if default else "telegram"  # Default to @telegram channel
