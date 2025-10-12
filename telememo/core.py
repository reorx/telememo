"""Core business logic coordinating telegram and database operations."""

from typing import Callable, Optional, Union

from . import db
from .telegram import TelegramClient
from .types import ChannelInfo, Config


class Scraper:
    """Coordinates scraping operations between Telegram and database."""

    def __init__(self, config: Config):
        """Initialize scraper with configuration.

        Args:
            config: Application configuration
        """
        self.config = config
        self.telegram = TelegramClient(
            api_id=config.api_id,
            api_hash=config.api_hash,
            session_name=config.session_name,
        )

    async def start(self) -> None:
        """Start the Telegram client."""
        await self.telegram.start(self.config.phone)

    async def stop(self) -> None:
        """Stop the Telegram client."""
        await self.telegram.disconnect()

    async def get_channel_info(self, channel: Union[str, int]) -> ChannelInfo:
        """Get channel information from Telegram.

        Args:
            channel: Channel username or ID

        Returns:
            ChannelInfo object
        """
        return await self.telegram.get_channel_info(channel)

    async def dump_channel(
        self,
        channel: Union[str, int],
        limit: Optional[int] = None,
        progress_callback: Optional[Callable[[int, int], None]] = None,
    ) -> int:
        """Dump all messages from a channel to the database.

        Args:
            channel: Channel username or ID
            limit: Maximum number of messages to dump (None for all)
            progress_callback: Optional callback function(current, total) for progress updates

        Returns:
            Number of messages dumped
        """
        # Get and store channel info
        channel_info = await self.telegram.get_channel_info(channel)
        db_channel = db.get_or_create_channel(channel_info)

        # Get total message count for progress tracking
        total_messages = await self.telegram.get_message_count(channel)
        if limit and limit < total_messages:
            total_messages = limit

        # Fetch and store messages
        count = 0
        batch = []
        batch_size = 100

        async for message_data in self.telegram.get_messages(channel, limit=limit):
            batch.append(message_data)
            count += 1

            # Save batch when it reaches batch_size
            if len(batch) >= batch_size:
                db.save_messages_batch(batch)
                batch.clear()

                # Report progress
                if progress_callback:
                    progress_callback(count, total_messages)

        # Save remaining messages in batch
        if batch:
            db.save_messages_batch(batch)
            if progress_callback:
                progress_callback(count, total_messages)

        # Update channel sync status
        if count > 0:
            # Get the latest message to update sync status
            latest_messages = db.get_latest_messages(db_channel.id, limit=1)
            if latest_messages:
                db.update_channel_sync_status(db_channel.id, latest_messages[0].id)

        return count

    async def sync_messages(
        self,
        channel: Union[str, int],
        progress_callback: Optional[Callable[[int], None]] = None,
    ) -> int:
        """Sync new messages from a channel since last sync.

        Args:
            channel: Channel username or ID
            progress_callback: Optional callback function(new_messages) for progress updates

        Returns:
            Number of new messages synced
        """
        # Get channel info
        channel_info = await self.telegram.get_channel_info(channel)
        db_channel = db.get_channel(channel_info.id)

        if not db_channel:
            # Channel not in database, do full dump
            return await self.dump_channel(channel, progress_callback=progress_callback)

        # Get messages since last sync
        min_id = db_channel.last_sync_message_id
        count = 0
        batch = []
        batch_size = 100

        async for message_data in self.telegram.get_messages(channel, min_id=min_id):
            batch.append(message_data)
            count += 1

            # Save batch when it reaches batch_size
            if len(batch) >= batch_size:
                db.save_messages_batch(batch)
                batch.clear()

                # Report progress
                if progress_callback:
                    progress_callback(count)

        # Save remaining messages in batch
        if batch:
            db.save_messages_batch(batch)
            if progress_callback:
                progress_callback(count)

        # Update channel sync status
        if count > 0:
            latest_messages = db.get_latest_messages(db_channel.id, limit=1)
            if latest_messages:
                db.update_channel_sync_status(db_channel.id, latest_messages[0].id)

        return count

    async def get_latest_messages(self, channel: Union[str, int], limit: int = 3):
        """Get the latest messages from a channel (for testing).

        Args:
            channel: Channel username or ID
            limit: Number of messages to retrieve

        Returns:
            List of MessageData objects
        """
        return await self.telegram.get_latest_messages(channel, limit=limit)

    async def __aenter__(self):
        """Async context manager entry."""
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.stop()
