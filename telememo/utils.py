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


def forward_info_from_row(row: Dict) -> ForwardInfo | None:
    """Build ForwardInfo from a stored message row's fwd_* columns.

    Used when assembling DisplayMessages directly from the database (A2 landed
    the forward fields), so no raw Telethon message is required.

    Args:
        row: Message dict with the fwd_* columns (from a DB query)

    Returns:
        ForwardInfo if the row is a forward, None otherwise
    """
    if not row.get('is_forwarded'):
        return None
    return ForwardInfo(
        from_channel_id=row.get('fwd_from_channel_id'),
        from_channel_name=row.get('fwd_from_channel_name'),
        from_user_id=row.get('fwd_from_user_id'),
        from_user_name=row.get('fwd_from_user_name'),
        from_message_id=row.get('fwd_from_message_id'),
        original_date=row.get('fwd_original_date'),
        post_author=row.get('fwd_post_author'),
    )


def _resolve_forward_info(msg_dict: Dict, raw_messages_map: Dict | None) -> ForwardInfo | None:
    """Pick the forward source: from raw message if available, else stored columns."""
    if raw_messages_map is not None:
        return extract_forward_info(raw_messages_map.get(msg_dict['id']))
    return forward_info_from_row(msg_dict)


def group_messages_to_display(message_dicts: List[Dict], raw_messages_map: Dict | None = None) -> List[DisplayMessage]:
    """Group raw message dicts into DisplayMessages based on grouped_id.

    This function converts database Message records into DisplayMessage objects,
    grouping album messages by their grouped_id and attaching forward information.

    Args:
        message_dicts: List of message dictionaries (from database queries)
        raw_messages_map: Optional dict mapping message_id -> raw Telethon message.
            When provided, forward info is extracted from the raw messages.
            When None, forward info is read from each row's stored fwd_* columns.

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
            media_items.append(
                MediaItem(message_id=msg['id'], media_type=msg.get('media_type'), has_media=msg.get('has_media', False))
            )

        # Get forward info from first message (raw message or stored columns)
        forward_info = _resolve_forward_info(first_msg, raw_messages_map)

        # Find message with text (usually the last message in the group)
        text = None
        for msg in reversed(group):  # Check from last to first
            if msg.get('text'):
                text = msg['text']
                break

        # Link preview, if any message in the album carried one (rare for albums)
        webpage = next((msg.get('webpage') for msg in group if msg.get('webpage')), None)

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
            text=text,  # Text from the message that has it (usually last)
            is_album=True,
            grouped_id=grouped_id,
            media_items=media_items,
            webpage=webpage,
            is_forwarded=forward_info is not None,
            forward_info=forward_info,
            views=max_views,
            forwards_count=max_forwards,
            replies_count=total_replies,
            raw_message_ids=[msg['id'] for msg in group],
        )
        display_messages.append(display_msg)

    # Process standalone messages
    for msg_dict in standalone:
        forward_info = _resolve_forward_info(msg_dict, raw_messages_map)

        # Add media item if message has media
        media_items = []
        if msg_dict.get('has_media'):
            media_items.append(
                MediaItem(message_id=msg_dict['id'], media_type=msg_dict.get('media_type'), has_media=True)
            )

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
            webpage=msg_dict.get('webpage'),
            is_forwarded=forward_info is not None,
            forward_info=forward_info,
            views=msg_dict.get('views'),
            forwards_count=msg_dict.get('forwards'),
            replies_count=msg_dict.get('replies'),
            raw_message_ids=[msg_dict['id']],
        )
        display_messages.append(display_msg)

    # Sort by date (most recent first)
    display_messages.sort(key=lambda m: m.date, reverse=True)

    return display_messages
