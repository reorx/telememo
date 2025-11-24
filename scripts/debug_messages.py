#!/usr/bin/env python3
"""Debug script to fetch and inspect messages without saving them.

This script fetches the last N messages from a channel using the Scraper class
with dry_run=True to inspect the data that would be saved without actually
modifying the database.
"""

import asyncio
import sys
from pathlib import Path
from datetime import datetime
from typing import List, Dict
from collections import defaultdict

import click

# Add parent directory to path to import telememo modules
sys.path.insert(0, str(Path(__file__).parent.parent))

from telememo import config
from telememo.core import Scraper
from telememo.types import DisplayMessage, MediaItem, ForwardInfo
from telememo.utils import extract_forward_info, group_messages_to_display


def format_datetime(dt):
    """Format datetime for JSON serialization."""
    if dt is None:
        return None
    if isinstance(dt, datetime):
        return dt.isoformat()
    return str(dt)


def print_display_message(display_msg: DisplayMessage, index: int):
    """Pretty print a DisplayMessage."""
    print("\n" + "=" * 80)
    print(f"Display Message #{index}")
    print("=" * 80)
    print(f"Message ID: {display_msg.id}")
    print(f"Date: {format_datetime(display_msg.date)}")
    print(f"Sender: {display_msg.sender_name} (ID: {display_msg.sender_id})")

    # Determine message type
    msg_type_parts = []
    if display_msg.is_forwarded:
        msg_type_parts.append("Forwarded")
    if display_msg.is_album:
        msg_type_parts.append(f"Album ({len(display_msg.media_items)} items)")
    elif display_msg.media_items:
        msg_type_parts.append(f"Media ({display_msg.media_items[0].media_type})")
    else:
        msg_type_parts.append("Text")

    print(f"Type: {' '.join(msg_type_parts)}")

    # Print text
    if display_msg.text:
        if len(display_msg.text) > 200:
            print(f"Text: {display_msg.text[:200]}... [truncated]")
        else:
            print(f"Text: {display_msg.text}")

    # Print album details
    if display_msg.is_album:
        print(f"\nAlbum Details:")
        print(f"  Grouped ID: {display_msg.grouped_id}")
        print(f"  Media items: {len(display_msg.media_items)}")
        for i, item in enumerate(display_msg.media_items, 1):
            print(f"    {i}. Message ID {item.message_id}: {item.media_type}")

    # Print forward info
    if display_msg.is_forwarded and display_msg.forward_info:
        print(f"\n🔄 Forward Information:")
        fwd = display_msg.forward_info
        if fwd.from_channel_id:
            print(f"  From Channel ID: {fwd.from_channel_id}")
        if fwd.from_channel_name:
            print(f"  From Channel Name: {fwd.from_channel_name}")
        if fwd.from_user_id:
            print(f"  From User ID: {fwd.from_user_id}")
        if fwd.from_user_name:
            print(f"  From User Name: {fwd.from_user_name}")
        if fwd.from_message_id:
            print(f"  Original Message ID: {fwd.from_message_id}")
        if fwd.original_date:
            print(f"  Original Date: {format_datetime(fwd.original_date)}")
        if fwd.post_author:
            print(f"  Post Author: {fwd.post_author}")

    # Print stats
    print(f"\nStatistics:")
    print(f"  Views: {display_msg.views}")
    print(f"  Forwards: {display_msg.forwards_count}")
    print(f"  Replies: {display_msg.replies_count}")

    # Print edit info
    if display_msg.is_edited:
        print(f"  Edited: Yes (at {format_datetime(display_msg.edit_date)})")

    # Print raw message IDs
    print(f"\nRaw Message IDs: {display_msg.raw_message_ids}")
    print("=" * 80)


def print_message_data(message_data_dict, raw_message=None):
    """Pretty print message data and highlight forward information."""
    print("\n" + "=" * 80)
    print(f"Message ID: {message_data_dict['id']}")
    print(f"Channel: {message_data_dict['channel']}")
    print(f"Date: {format_datetime(message_data_dict['date'])}")
    print(f"Sender: {message_data_dict['sender_name']} (ID: {message_data_dict['sender_id']})")

    # Print text (truncate if too long)
    text = message_data_dict.get('text')
    if text:
        if len(text) > 200:
            print(f"Text: {text[:200]}... [truncated]")
        else:
            print(f"Text: {text}")
    else:
        print("Text: (empty)")

    # Print stats
    print(f"Views: {message_data_dict.get('views')}")
    print(f"Forwards (count): {message_data_dict.get('forwards')}")
    print(f"Replies: {message_data_dict.get('replies')}")

    # Print media info
    if message_data_dict.get('has_media'):
        print(f"Media Type: {message_data_dict.get('media_type')}")
        print(f"Grouped ID: {message_data_dict.get('grouped_id')}")

    # Print edit info
    if message_data_dict.get('is_edited'):
        print(f"Edited: Yes (at {format_datetime(message_data_dict.get('edit_date'))})")

    # Check for forward information in raw message
    if raw_message and hasattr(raw_message, 'fwd_from') and raw_message.fwd_from:
        print("\n🔄 FORWARD INFORMATION DETECTED:")
        fwd = raw_message.fwd_from
        print(f"  Raw fwd_from object: {fwd}")

        # Print available attributes
        if hasattr(fwd, 'from_id'):
            print(f"  from_id: {fwd.from_id}")
        if hasattr(fwd, 'from_name'):
            print(f"  from_name: {fwd.from_name}")
        if hasattr(fwd, 'date'):
            print(f"  original_date: {fwd.date}")
        if hasattr(fwd, 'channel_post'):
            print(f"  channel_post (original msg ID): {fwd.channel_post}")
        if hasattr(fwd, 'post_author'):
            print(f"  post_author: {fwd.post_author}")

        print("  ⚠️  This forward information is NOT currently being saved to the database!")
    else:
        print("\n✓ Not a forwarded message")

    print("=" * 80)


async def fetch_and_inspect(channel_name: str, limit: int, show_display_messages: bool):
    """Main function to fetch and inspect messages."""
    print(f"Fetching last {limit} messages from @{channel_name}...")
    print(f"Mode: DRY RUN (no database modifications)\n")

    # Load configuration
    try:
        app_config = config.get_config()
    except ValueError as e:
        print(f"Error: {e}")
        sys.exit(1)

    # Get global session path
    config.ensure_data_dir()
    session_path = config.get_global_session_path()

    # Initialize Scraper
    scraper = Scraper(app_config, session_path)

    try:
        # Start the scraper (connects to Telegram)
        await scraper.start()
        print("✓ Connected to Telegram\n")

        # Get channel info
        channel_info = await scraper.get_channel_info(channel_name)
        print(f"Channel: {channel_info.title} (@{channel_info.username})")
        print(f"Channel ID: {channel_info.id}")
        print(f"Members: {channel_info.member_count or 'N/A'}\n")

        # Fetch messages with dry_run=True (no database modifications)
        message_dicts = await scraper.dump_messages(
            channel_name,
            limit=limit,
            dry_run=True
        )

        print(f"✓ Fetched {len(message_dicts)} raw messages\n")

        # Get raw messages to inspect forward information
        message_ids = [msg['id'] for msg in message_dicts]
        raw_messages = await scraper.get_raw_messages(channel_name, message_ids)

        # Create a mapping of message_id -> raw_message
        raw_messages_map = {msg.id: msg for msg in raw_messages if msg}

        if show_display_messages:
            # Group messages into display messages
            display_messages = group_messages_to_display(message_dicts, raw_messages_map)

            print(f"✓ Grouped into {len(display_messages)} display messages\n")

            # Print each display message
            for i, display_msg in enumerate(display_messages, 1):
                print_display_message(display_msg, i)

            # Summary
            print("\n" + "=" * 80)
            print("SUMMARY")
            print("=" * 80)
            print(f"Total raw messages fetched: {len(message_dicts)}")
            print(f"Total display messages: {len(display_messages)}")

            # Count message types
            text_only = sum(1 for m in display_messages if not m.media_items)
            with_media = sum(1 for m in display_messages if m.media_items and not m.is_album)
            albums = sum(1 for m in display_messages if m.is_album)
            forwarded = sum(1 for m in display_messages if m.is_forwarded)

            print(f"\nMessage Types:")
            print(f"  Text only: {text_only}")
            print(f"  With media: {with_media}")
            print(f"  Albums: {albums}")
            print(f"  Forwarded: {forwarded}")

        else:
            # Print raw messages
            forward_count = 0
            for message_dict in message_dicts:
                raw_message = raw_messages_map.get(message_dict['id'])

                # Track forwards
                if raw_message and hasattr(raw_message, 'fwd_from') and raw_message.fwd_from:
                    forward_count += 1

                # Print the data
                print_message_data(message_dict, raw_message)

            # Summary
            print("\n" + "=" * 80)
            print("SUMMARY")
            print("=" * 80)
            print(f"Total messages fetched: {len(message_dicts)}")
            print(f"Forwarded messages: {forward_count}")
            if forward_count > 0:
                print(f"\n⚠️  {forward_count} messages have forward information that is not being saved!")
                print("   Consider adding fields to the database schema to capture:")
                print("   - is_forwarded (boolean)")
                print("   - forward_from_channel_id, forward_from_channel_name")
                print("   - forward_from_user_id, forward_from_user_name")
                print("   - forward_from_message_id")
                print("   - forward_from_date")
            else:
                print("\n✓ No forwarded messages in this batch")

    finally:
        await scraper.stop()
        print("\n✓ Disconnected from Telegram")


def deep_inspect_telethon_object(obj, name="", indent=0, max_depth=10, visited=None):
    """Recursively inspect and display all attributes of a Telethon object.

    Args:
        obj: The object to inspect
        name: Name of the current object/attribute
        indent: Current indentation level
        max_depth: Maximum recursion depth to prevent infinite loops
        visited: Set of already visited object IDs to prevent circular references
    """
    if visited is None:
        visited = set()

    if max_depth <= 0:
        print(f"{' ' * indent}... (max depth reached)")
        return

    # Get object ID to track visited objects
    obj_id = id(obj)
    if obj_id in visited and not isinstance(obj, (str, int, float, bool, type(None))):
        print(f"{' ' * indent}... (circular reference)")
        return

    visited.add(obj_id)

    prefix = ' ' * indent
    type_name = type(obj).__name__

    # Handle None
    if obj is None:
        print(f"{prefix}{name}: None")
        return

    # Handle primitive types
    if isinstance(obj, (str, int, float, bool)):
        if isinstance(obj, str) and len(obj) > 100:
            print(f"{prefix}{name}: {repr(obj[:100])}... ({type_name}, length={len(obj)})")
        else:
            print(f"{prefix}{name}: {repr(obj)} ({type_name})")
        return

    # Handle bytes
    if isinstance(obj, bytes):
        if len(obj) > 32:
            print(f"{prefix}{name}: {obj[:32].hex()}... ({type_name}, length={len(obj)} bytes)")
        else:
            print(f"{prefix}{name}: {obj.hex()} ({type_name}, {len(obj)} bytes)")
        return

    # Handle datetime
    if isinstance(obj, datetime):
        print(f"{prefix}{name}: {obj.isoformat()} ({type_name})")
        return

    # Handle lists
    if isinstance(obj, list):
        print(f"{prefix}{name}: ({type_name}, length={len(obj)})")
        for i, item in enumerate(obj):
            if i >= 20:  # Limit list items to prevent overwhelming output
                print(f"{prefix}  ... ({len(obj) - 20} more items)")
                break
            deep_inspect_telethon_object(item, f"[{i}]", indent + 2, max_depth - 1, visited)
        return

    # Handle dictionaries
    if isinstance(obj, dict):
        print(f"{prefix}{name}: ({type_name}, keys={len(obj)})")
        for key, value in obj.items():
            deep_inspect_telethon_object(value, f"[{repr(key)}]", indent + 2, max_depth - 1, visited)
        return

    # Handle complex objects (Telethon objects, etc.)
    print(f"{prefix}{name}: ({type_name})")

    # Get all attributes (excluding private ones and methods)
    try:
        attrs = [attr for attr in dir(obj) if not attr.startswith('_') and not callable(getattr(obj, attr, None))]
    except Exception:
        attrs = []

    if not attrs:
        # Try to get __dict__ directly
        try:
            if hasattr(obj, '__dict__'):
                for key, value in obj.__dict__.items():
                    if not key.startswith('_'):
                        deep_inspect_telethon_object(value, key, indent + 2, max_depth - 1, visited)
            else:
                print(f"{prefix}  (no inspectable attributes)")
        except Exception as e:
            print(f"{prefix}  (error accessing attributes: {e})")
    else:
        # Inspect each attribute
        for attr in attrs:
            try:
                value = getattr(obj, attr)
                deep_inspect_telethon_object(value, attr, indent + 2, max_depth - 1, visited)
            except Exception as e:
                print(f"{prefix}  {attr}: (error: {e})")


async def inspect_single_message(channel_name: str, message_id: int):
    """Fetch and deeply inspect a single message with full raw Telethon structure.

    Args:
        channel_name: Channel username
        message_id: The message ID to inspect
    """
    print(f"Inspecting message ID {message_id} from @{channel_name}...")
    print(f"Mode: DEEP INSPECTION (raw Telethon structure)\n")

    # Load configuration
    try:
        app_config = config.get_config()
    except ValueError as e:
        print(f"Error: {e}")
        sys.exit(1)

    # Get global session path
    config.ensure_data_dir()
    session_path = config.get_global_session_path()

    # Initialize Scraper
    scraper = Scraper(app_config, session_path)

    try:
        # Start the scraper (connects to Telegram)
        await scraper.start()
        print("✓ Connected to Telegram\n")

        # Get channel info
        channel_info = await scraper.get_channel_info(channel_name)
        print(f"Channel: {channel_info.title} (@{channel_info.username})")
        print(f"Channel ID: {channel_info.id}\n")

        # Fetch the single message using raw Telethon API
        raw_messages = await scraper.telegram.client.get_messages(
            channel_name,
            ids=message_id
        )

        # Check if message was found
        if not raw_messages or raw_messages is None:
            print(f"✗ Message {message_id} not found in channel {channel_name}")
            return

        # Handle both single message and list responses
        if isinstance(raw_messages, list):
            if len(raw_messages) == 0 or raw_messages[0] is None:
                print(f"✗ Message {message_id} not found in channel {channel_name}")
                return
            raw_message = raw_messages[0]
        else:
            raw_message = raw_messages

        if raw_message is None:
            print(f"✗ Message {message_id} not found in channel {channel_name}")
            return

        print("=" * 80)
        print(f"INSPECTING MESSAGE ID: {message_id}")
        print("=" * 80)

        # Basic information
        print("\n📋 BASIC INFORMATION:")
        print("=" * 80)
        print(f"Message ID: {raw_message.id}")
        print(f"Date: {raw_message.date}")
        if hasattr(raw_message, 'message') and raw_message.message:
            msg_text = raw_message.message
            if len(msg_text) > 300:
                print(f"Text: {msg_text[:300]}...")
                print(f"     (truncated, total length: {len(msg_text)})")
            else:
                print(f"Text: {msg_text}")
        else:
            print("Text: (empty)")

        # Type information
        print(f"\nObject Type: {type(raw_message)}")
        print(f"Object Module: {type(raw_message).__module__}")

        # Raw repr
        print("\n📦 RAW REPR:")
        print("=" * 80)
        try:
            print(repr(raw_message))
        except Exception as e:
            print(f"(error getting repr: {e})")

        # Deep inspection
        print("\n🔍 COMPLETE ATTRIBUTE INSPECTION:")
        print("=" * 80)
        deep_inspect_telethon_object(raw_message, "message", indent=0, max_depth=8)

        print("\n" + "=" * 80)
        print("✓ Inspection complete")
        print("=" * 80)

    finally:
        await scraper.stop()
        print("\n✓ Disconnected from Telegram")


@click.command()
@click.option(
    '--show-display-messages',
    is_flag=True,
    help='Group messages by album and show as DisplayMessages (user perspective)'
)
@click.option(
    '--limit', '-l',
    default=50,
    type=int,
    help='Maximum number of messages to fetch (default: 50)'
)
@click.option(
    '--inspect-message',
    type=int,
    help='Inspect a specific message ID with full raw Telethon structure'
)
@click.argument('channel_name')
def main(show_display_messages: bool, limit: int, inspect_message: int, channel_name: str):
    """Debug script to fetch and inspect Telegram channel messages.

    CHANNEL_NAME: Channel username (with or without @)

    Examples:
        python debug_messages.py telememo_test
        python debug_messages.py --show-display-messages telememo_test
        python debug_messages.py --limit 100 telememo_test
        python debug_messages.py --inspect-message 123 telememo_test
    """
    # Remove @ prefix if present
    channel_name = channel_name.lstrip('@')

    # Run the appropriate async function
    if inspect_message:
        asyncio.run(inspect_single_message(channel_name, inspect_message))
    else:
        asyncio.run(fetch_and_inspect(channel_name, limit, show_display_messages))


if __name__ == "__main__":
    main()
