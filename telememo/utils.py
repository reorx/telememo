"""Utility functions for message grouping and display formatting."""

from typing import Dict, List
from collections import defaultdict

from telememo.types import DisplayMessage, MediaItem, ForwardInfo


def extract_forward_info(raw_message) -> ForwardInfo | None:
    """Extract forward information from a raw Telegram message.

    Args:
        raw_message: Raw Telethon message object

    Returns:
        ForwardInfo object if message is forwarded, None otherwise
    """
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
    """Group raw message dicts into DisplayMessages based on grouped_id.

    This function converts database Message records into DisplayMessage objects,
    grouping album messages by their grouped_id and extracting forward information
    from raw Telegram messages.

    Args:
        message_dicts: List of message dictionaries (from database queries)
        raw_messages_map: Dict mapping message_id -> raw Telethon message object

    Returns:
        List of DisplayMessage objects sorted by date (most recent first)
    """
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
