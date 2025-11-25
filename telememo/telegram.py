"""Telegram client wrapper using Telethon."""

from datetime import datetime
from typing import AsyncIterator, List, Optional, Union

from telethon import TelegramClient as TelethonClient
from telethon.tl.functions.channels import GetFullChannelRequest
from telethon.tl.functions.messages import GetDiscussionMessageRequest, GetRepliesRequest
from telethon.tl.types import Channel as TgChannel
from telethon.tl.types import Message as TgMessage
from telethon.tl.types import User

from .types import ChannelInfo, MessageData, CommentData


class TelegramClient:
    """Wrapper for Telethon TelegramClient."""

    def __init__(self, api_id: int, api_hash: str, session_name: str = "telememo_session"):
        """Initialize Telegram client.

        Args:
            api_id: Telegram API ID
            api_hash: Telegram API hash
            session_name: Session file name
        """
        import platform
        self.client = TelethonClient(
            session_name,
            api_id,
            api_hash,
            device_model=f"Telememo on {platform.system()}",
            system_version=platform.release(),
        )
        self._connected = False

    async def start(self, phone: Optional[str] = None) -> None:
        """Start the client and authenticate as user.

        Args:
            phone: Phone number for authentication (optional, will prompt if not provided)
        """
        # Custom password callback that only prompts if 2FA is actually required
        def password_callback():
            import getpass
            password = getpass.getpass('2FA password (press Enter if not enabled): ')
            return password if password else None

        await self.client.start(phone=phone, password=password_callback)
        self._connected = True

    async def disconnect(self) -> None:
        """Disconnect the client."""
        if self._connected:
            await self.client.disconnect()
            self._connected = False

    async def get_channel_info(self, channel: Union[str, int]) -> ChannelInfo:
        """Get channel information.

        Args:
            channel: Channel username (with or without @) or channel ID

        Returns:
            ChannelInfo object
        """
        entity = await self.client.get_entity(channel)
        return self._convert_channel_to_info(entity)

    async def get_messages(
        self,
        channel: Union[str, int],
        limit: Optional[int] = None,
        offset_id: int = 0,
        min_id: int = 0,
        max_id: int = 0,
        reverse: bool = False,
    ) -> AsyncIterator[MessageData]:
        """Get messages from a channel.

        Args:
            channel: Channel username or ID
            limit: Maximum number of messages to retrieve (None for all)
            offset_id: Offset message ID to start from
            min_id: Minimum message ID to retrieve
            max_id: Maximum message ID to retrieve
            reverse: If True, retrieve messages in chronological order

        Yields:
            MessageData objects
        """
        async for message in self.client.iter_messages(
            channel,
            limit=limit,
            offset_id=offset_id,
            min_id=min_id,
            max_id=max_id,
            reverse=reverse,
        ):
            if message:
                yield await self._convert_message_to_data(message)

    async def get_latest_messages(self, channel: Union[str, int], limit: int = 10) -> List[MessageData]:
        """Get the latest messages from a channel.

        Args:
            channel: Channel username or ID
            limit: Number of messages to retrieve

        Returns:
            List of MessageData objects
        """
        messages = []
        async for message_data in self.get_messages(channel, limit=limit):
            messages.append(message_data)
        return messages

    async def get_message_count(self, channel: Union[str, int]) -> int:
        """Get total message count in a channel.

        Args:
            channel: Channel username or ID

        Returns:
            Total message count
        """
        entity = await self.client.get_entity(channel)
        if hasattr(entity, "id"):
            # Get the last message ID which represents the total count
            async for message in self.client.iter_messages(entity, limit=1):
                return message.id if message else 0
        return 0

    def _convert_channel_to_info(self, entity: TgChannel) -> ChannelInfo:
        """Convert Telegram channel entity to ChannelInfo.

        Args:
            entity: Telegram channel entity

        Returns:
            ChannelInfo object
        """
        # Get full channel info for additional details
        full = entity.full if hasattr(entity, "full") else None

        return ChannelInfo(
            id=entity.id,
            title=entity.title,
            username=entity.username if hasattr(entity, "username") else None,
            description=full.about if full and hasattr(full, "about") else None,
            member_count=full.participants_count if full and hasattr(full, "participants_count") else None,
            created_at=entity.date if hasattr(entity, "date") else None,
        )

    async def _convert_message_to_data(self, message: TgMessage) -> MessageData:
        """Convert Telegram message to MessageData.

        Args:
            message: Telegram message object

        Returns:
            MessageData object
        """
        # Get sender information
        sender_id = message.sender_id
        sender_name = None
        if message.sender:
            if isinstance(message.sender, User):
                parts = []
                if message.sender.first_name:
                    parts.append(message.sender.first_name)
                if message.sender.last_name:
                    parts.append(message.sender.last_name)
                sender_name = " ".join(parts) if parts else message.sender.username
            elif hasattr(message.sender, "title"):
                sender_name = message.sender.title

        # Determine media type
        media_type = None
        has_media = message.media is not None
        if has_media and message.media:
            media_type = message.media.__class__.__name__.replace("MessageMedia", "").lower()

        # Get message stats
        views = message.views if hasattr(message, "views") else None
        forwards = message.forwards if hasattr(message, "forwards") else None

        # Get replies count
        replies = None
        if hasattr(message, "replies") and message.replies:
            replies = message.replies.replies

        # Get grouped_id for media albums
        grouped_id = None
        if hasattr(message, "grouped_id"):
            grouped_id = message.grouped_id

        return MessageData(
            id=message.id,
            channel_id=message.peer_id.channel_id,
            text=message.text or None,
            date=message.date,
            sender_id=sender_id,
            sender_name=sender_name,
            views=views,
            forwards=forwards,
            replies=replies,
            is_edited=message.edit_date is not None,
            edit_date=message.edit_date,
            media_type=media_type,
            has_media=has_media,
            grouped_id=grouped_id,
        )

    async def get_discussion_group(self, channel: Union[str, int]) -> Optional[int]:
        """Get the linked discussion group ID for a channel.

        Args:
            channel: Channel username or ID

        Returns:
            Discussion group ID or None if not linked
        """
        entity = await self.client.get_entity(channel)
        # Get full channel information using GetFullChannelRequest
        full_channel = await self.client(GetFullChannelRequest(entity))
        if hasattr(full_channel, "full_chat") and hasattr(full_channel.full_chat, "linked_chat_id"):
            linked_chat_id = full_channel.full_chat.linked_chat_id
            if linked_chat_id:
                return linked_chat_id
        return None

    async def get_comments(
        self,
        channel: Union[str, int],
        message_id: int,
        limit: Optional[int] = None,
    ) -> AsyncIterator[CommentData]:
        """Get comments for a specific message.

        Args:
            channel: Channel username or ID
            message_id: Message ID to get comments for
            limit: Maximum number of comments to retrieve (None for all)

        Yields:
            CommentData objects
        """
        # Get channel entity
        entity = await self.client.get_entity(channel)
        channel_id = entity.id

        # Get the original message to check if it has replies
        original_message = await self.client.get_messages(channel, ids=message_id)
        if not original_message or not original_message.replies:
            # No replies on this message
            return

        if not original_message.replies.channel_id:
            # Replies exist but no discussion group channel
            return

        discussion_group_id = original_message.replies.channel_id

        # Get the discussion message (the linked message in the discussion group)
        try:
            discussion_msg_result = await self.client(GetDiscussionMessageRequest(
                peer=entity,
                msg_id=message_id
            ))
        except Exception:
            # Unable to get discussion message
            return

        if not discussion_msg_result.messages:
            return

        linked_message = discussion_msg_result.messages[0]
        linked_message_id = linked_message.id

        # For grouped messages in the discussion group, find which one has replies
        # The GetDiscussionMessageRequest might return a message in the group that
        # doesn't have the replies field, so we need to check all messages in the group
        if linked_message.grouped_id:
            # Fetch all messages in this group
            group_messages = await self.client.get_messages(
                discussion_group_id,
                limit=10,  # Albums typically have < 10 items
                min_id=max(1, linked_message_id - 10),
                max_id=linked_message_id + 10
            )

            # Find messages with the same grouped_id
            grouped_msgs = [
                msg for msg in group_messages
                if msg and msg.grouped_id == linked_message.grouped_id
            ]

            # Find the one with replies > 0
            for msg in grouped_msgs:
                if msg.replies and msg.replies.replies > 0:
                    linked_message_id = msg.id
                    break

        # Fetch comments using GetRepliesRequest with pagination
        offset_id = 0
        batch_limit = 100
        total_fetched = 0

        while True:
            # Calculate how many to fetch in this batch
            if limit:
                remaining = limit - total_fetched
                if remaining <= 0:
                    break
                current_limit = min(batch_limit, remaining)
            else:
                current_limit = batch_limit

            # Fetch replies
            try:
                replies_result = await self.client(GetRepliesRequest(
                    peer=discussion_group_id,
                    msg_id=linked_message_id,
                    offset_id=offset_id,
                    offset_date=None,
                    add_offset=0,
                    limit=current_limit,
                    max_id=0,
                    min_id=0,
                    hash=0
                ))
            except Exception:
                # Error fetching replies
                break

            if not replies_result.messages:
                break

            # Convert and yield each comment
            for reply_msg in replies_result.messages:
                comment_data = await self._convert_message_to_comment(
                    reply_msg, message_id, channel_id, discussion_group_id
                )
                yield comment_data
                total_fetched += 1

            # Update offset for next batch
            offset_id = replies_result.messages[-1].id

            # Check if we've fetched all messages
            if len(replies_result.messages) < current_limit:
                break

    async def _convert_message_to_comment(
        self, message: TgMessage, parent_message_id: int, parent_channel_id: int, discussion_group_id: int
    ) -> CommentData:
        """Convert Telegram message to CommentData.

        Args:
            message: Telegram message object (comment)
            parent_message_id: Parent message ID
            parent_channel_id: Parent channel ID
            discussion_group_id: Discussion group ID

        Returns:
            CommentData object
        """
        # Get sender information
        sender_id = message.sender_id
        sender_name = None
        if message.sender:
            if isinstance(message.sender, User):
                parts = []
                if message.sender.first_name:
                    parts.append(message.sender.first_name)
                if message.sender.last_name:
                    parts.append(message.sender.last_name)
                sender_name = " ".join(parts) if parts else message.sender.username
            elif hasattr(message.sender, "title"):
                sender_name = message.sender.title

        # Check if this comment is a reply to another comment
        is_reply_to_comment = False
        reply_to_comment_id = None
        if message.reply_to and hasattr(message.reply_to, "reply_to_msg_id"):
            # If reply_to_msg_id is different from parent_message_id, it's a reply to another comment
            if message.reply_to.reply_to_msg_id != parent_message_id:
                is_reply_to_comment = True
                reply_to_comment_id = message.reply_to.reply_to_msg_id

        # Get message text - use message.message attribute for raw text
        text = None
        if hasattr(message, 'message') and message.message:
            text = message.message
        elif hasattr(message, 'text') and message.text:
            text = message.text

        return CommentData(
            id=message.id,
            parent_message_id=parent_message_id,
            parent_channel_id=parent_channel_id,
            discussion_group_id=discussion_group_id,
            text=text,
            date=message.date,
            sender_id=sender_id,
            sender_name=sender_name,
            is_edited=message.edit_date is not None,
            edit_date=message.edit_date,
            is_reply_to_comment=is_reply_to_comment,
            reply_to_comment_id=reply_to_comment_id,
        )

    async def __aenter__(self):
        """Async context manager entry."""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.disconnect()
