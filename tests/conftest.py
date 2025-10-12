"""Pytest configuration and fixtures."""

import os
import tempfile
from pathlib import Path

import pytest
from dotenv import load_dotenv

from telememo import db
from telememo.types import Config

# Load environment variables for tests
load_dotenv()


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
def test_config(test_db):
    """Create test configuration."""
    api_id = os.getenv("TELEGRAM_API_ID")
    api_hash = os.getenv("TELEGRAM_API_HASH")

    if not all([api_id, api_hash]):
        pytest.skip("Missing required environment variables for integration tests")

    return Config(
        api_id=int(api_id),
        api_hash=api_hash,
        phone=os.getenv("PHONE"),  # Optional phone number
        db_path=test_db,
        # Use default session_name ("telememo_session") to reuse CLI's authenticated session
    )


@pytest.fixture
def test_channel():
    """Get test channel from environment or use default."""
    # For integration tests, we'll use the channel specified in env or a default
    # The bot must be a member of this channel
    return os.getenv("TEST_CHANNEL", "telegram")  # Default to @telegram channel
