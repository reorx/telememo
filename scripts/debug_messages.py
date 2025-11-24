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


def format_datetime(dt):
    """Format datetime for JSON serialization."""
    if dt is None:
        return None
    if isinstance(dt, datetime):
        return dt.isoformat()
    return str(dt)


def extract_forward_info(raw_message) -> ForwardInfo | None:
    """Extract forward information from a raw Telegram message."""
    if not raw_message or not hasattr(raw_message, 'fwd_from') or not raw_message.fwd_from:
        return None

    fwd = raw_message.fwd_from
    forward_info = ForwardInfo()

    # Extract channel info
    if hasattr(fwd, 'from_id'):
        from_id = fwd.from_id
        # Check if it's a channel
        if hasattr(from_id, 'channel_id'):
            forward_info.from_channel_id = from_id.channel_id
            # Try to get channel name if available
            if hasattr(raw_message, 'forward_header') and hasattr(raw_message.forward_header, 'from_name'):
                forward_info.from_channel_name = raw_message.forward_header.from_name
        # Check if it's a user
        elif hasattr(from_id, 'user_id'):
            forward_info.from_user_id = from_id.user_id

    # Extract from_name (hidden forward source)
    if hasattr(fwd, 'from_name') and fwd.from_name:
        forward_info.from_user_name = fwd.from_name

    # Extract original date
    if hasattr(fwd, 'date'):
        forward_info.original_date = fwd.date

    # Extract original message ID
    if hasattr(fwd, 'channel_post'):
        forward_info.from_message_id = fwd.channel_post

    # Extract post author
    if hasattr(fwd, 'post_author') and fwd.post_author:
        forward_info.post_author = fwd.post_author

    return forward_info


def group_messages_to_display(message_dicts: List[Dict], raw_messages_map: Dict) -> List[DisplayMessage]:
    """Group raw message dicts into DisplayMessages based on grouped_id."""

    # Group messages by grouped_id
    grouped = defaultdict(list)
    standalone = []

    for msg_dict in message_dicts:
        grouped_id = msg_dict.get('grouped_id')
        if grouped_id:
            grouped[grouped_id].append(msg_dict)
        else:
            standalone.append(msg_dict)

    display_messages = []

    # Process grouped messages (albums)
    for grouped_id, group in grouped.items():
        # Sort by message ID to get proper order
        group.sort(key=lambda m: m['id'])
        first_msg = group[0]

        # Collect media items
        media_items = []
        for msg in group:
            media_items.append(MediaItem(
                message_id=msg['id'],
                media_type=msg.get('media_type'),
                has_media=msg.get('has_media', False)
            ))

        # Get forward info from first message
        raw_message = raw_messages_map.get(first_msg['id'])
        forward_info = extract_forward_info(raw_message)

        # Aggregate stats
        views_list = [msg.get('views') for msg in group if msg.get('views')]
        forwards_list = [msg.get('forwards') for msg in group if msg.get('forwards')]
        replies_list = [msg.get('replies') for msg in group if msg.get('replies')]

        max_views = max(views_list) if views_list else None
        max_forwards = max(forwards_list) if forwards_list else None
        total_replies = sum(replies_list) if replies_list else None

        display_msg = DisplayMessage(
            id=first_msg['id'],
            channel_id=first_msg['channel'],
            date=first_msg['date'],
            is_edited=any(msg.get('is_edited', False) for msg in group),
            edit_date=first_msg.get('edit_date'),
            sender_id=first_msg.get('sender_id'),
            sender_name=first_msg.get('sender_name'),
            text=first_msg.get('text'),  # Usually only first message has text
            is_album=True,
            grouped_id=grouped_id,
            media_items=media_items,
            is_forwarded=forward_info is not None,
            forward_info=forward_info,
            views=max_views,
            forwards_count=max_forwards,
            replies_count=total_replies,
            raw_message_ids=[msg['id'] for msg in group]
        )
        display_messages.append(display_msg)

    # Process standalone messages
    for msg_dict in standalone:
        raw_message = raw_messages_map.get(msg_dict['id'])
        forward_info = extract_forward_info(raw_message)

        # Add media item if message has media
        media_items = []
        if msg_dict.get('has_media'):
            media_items.append(MediaItem(
                message_id=msg_dict['id'],
                media_type=msg_dict.get('media_type'),
                has_media=True
            ))

        display_msg = DisplayMessage(
            id=msg_dict['id'],
            channel_id=msg_dict['channel'],
            date=msg_dict['date'],
            is_edited=msg_dict.get('is_edited', False),
            edit_date=msg_dict.get('edit_date'),
            sender_id=msg_dict.get('sender_id'),
            sender_name=msg_dict.get('sender_name'),
            text=msg_dict.get('text'),
            is_album=False,
            grouped_id=None,
            media_items=media_items,
            is_forwarded=forward_info is not None,
            forward_info=forward_info,
            views=msg_dict.get('views'),
            forwards_count=msg_dict.get('forwards'),
            replies_count=msg_dict.get('replies'),
            raw_message_ids=[msg_dict['id']]
        )
        display_messages.append(display_msg)

    # Sort by date (most recent first)
    display_messages.sort(key=lambda m: m.date, reverse=True)

    return display_messages


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
@click.argument('channel_name')
def main(show_display_messages: bool, limit: int, channel_name: str):
    """Debug script to fetch and inspect Telegram channel messages.

    CHANNEL_NAME: Channel username (with or without @)

    Examples:
        python debug_messages.py telememo_test
        python debug_messages.py --show-display-messages telememo_test
        python debug_messages.py --limit 100 telememo_test
    """
    # Remove @ prefix if present
    channel_name = channel_name.lstrip('@')

    # Run the async function
    asyncio.run(fetch_and_inspect(channel_name, limit, show_display_messages))


if __name__ == "__main__":
    main()
