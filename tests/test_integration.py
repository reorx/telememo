"""Integration tests for Telememo."""

import pytest

from telememo import db
from telememo.core import Scraper


@pytest.mark.asyncio
async def test_get_channel_info_and_messages(test_config, test_channel):
    """Test getting channel info and fetching 3 latest messages.

    This integration test verifies:
    1. Getting channel information using bot credentials
    2. Fetching the 3 latest messages from a channel
    3. Storing messages in the database
    """
    # Create scraper instance
    scraper = Scraper(test_config)

    # Start the scraper (connects to Telegram)
    await scraper.start()

    # Test 1: Get channel information
    channel_info = await scraper.get_channel_info(test_channel)

    assert channel_info is not None
    assert channel_info.id > 0
    assert channel_info.title is not None
    assert len(channel_info.title) > 0

    print(f"\nChannel Info:")
    print(f"  Title: {channel_info.title}")
    print(f"  ID: {channel_info.id}")
    print(f"  Username: @{channel_info.username or 'N/A'}")

    # Test 2: Fetch 3 latest messages
    messages = await scraper.telegram.get_latest_messages(test_channel, limit=3)

    assert messages is not None
    assert len(messages) > 0
    assert len(messages) <= 3

    print(f"\nFetched {len(messages)} messages:")
    for i, msg in enumerate(messages, 1):
        print(f"  Message {i}:")
        print(f"    ID: {msg.id}")
        print(f"    Date: {msg.date}")
        print(f"    Text: {msg.text[:50] if msg.text else 'No text'}...")

    # Test 3: Store channel and messages in database
    # Store channel info
    db_channel = db.get_or_create_channel(channel_info)
    assert db_channel is not None
    assert db_channel.id == channel_info.id

    # Store messages
    for message in messages:
        db_message = db.save_message(message)
        assert db_message is not None
        assert db_message.id == message.id

    # Verify messages are stored
    stored_messages = db.get_latest_messages(channel_info.id, limit=3)
    assert len(stored_messages) > 0
    assert len(stored_messages) <= 3

    # Verify message count
    message_count = db.get_message_count(channel_info.id)
    assert message_count == len(messages)

    print(f"\n✓ Successfully stored {message_count} messages in database")

    # Cleanup
    await scraper.stop()


@pytest.mark.asyncio
async def test_dump_channel_limited(test_config, test_channel):
    """Test dumping a limited number of messages from a channel."""
    scraper = Scraper(test_config)
    await scraper.start()

    # Dump only 5 messages
    count = await scraper.dump_messages(test_channel, limit=5)

    assert count > 0
    assert count <= 5

    print(f"\n✓ Dumped {count} messages")

    # Verify in database
    channel_info = await scraper.get_channel_info(test_channel)
    db_channel = db.get_channel(channel_info.id)
    assert db_channel is not None

    message_count = db.get_message_count(channel_info.id)
    assert message_count == count

    await scraper.stop()


@pytest.mark.asyncio
async def test_search_messages(test_config, test_channel):
    """Test searching messages in the database."""
    scraper = Scraper(test_config)
    await scraper.start()

    # First, dump some messages
    await scraper.dump_messages(test_channel, limit=10)

    # Get channel info
    channel_info = await scraper.get_channel_info(test_channel)

    # Search for messages
    # We search for common words that are likely to appear
    results = db.search_messages("the", channel_id=channel_info.id, limit=5)

    print(f"\nSearch results: {len(results)} messages found")

    for msg in results:
        print(f"  Message {msg.id}: {msg.text[:50] if msg.text else 'No text'}...")

    await scraper.stop()
