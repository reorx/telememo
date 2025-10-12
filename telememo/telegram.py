"""Telegram client wrapper using Telethon."""

from datetime import datetime
from typing import AsyncIterator, List, Optional, Union

from telethon import TelegramClient as TelethonClient
from telethon.tl.types import Channel as TgChannel
from telethon.tl.types import Message as TgMessage
from telethon.tl.types import User

from .types import ChannelInfo, MessageData


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
        )

    async def __aenter__(self):
        """Async context manager entry."""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.disconnect()
