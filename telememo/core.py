"""Core business logic coordinating telegram and database operations."""

from typing import Callable, Optional, Union

from . import db
from .telegram import TelegramClient
from .types import ChannelInfo, Config


ProgressCallback = Callable[[int, int], None]

class Scraper:
    """Coordinates scraping operations between Telegram and database."""

    def __init__(self, config: Config, session_path: str = None):
        """Initialize scraper with configuration.

        Args:
            config: Application configuration
            session_path: Path to session file (optional, uses config.session_name if not provided)
        """
        self.config = config
        self.telegram = TelegramClient(
            api_id=config.api_id,
            api_hash=config.api_hash,
            session_name=session_path or config.session_name,
        )

    async def start(self) -> None:
        """Start the Telegram client."""
        await self.telegram.start(self.config.phone)

    async def stop(self) -> None:
        """Stop the Telegram client."""
        await self.telegram.disconnect()

    async def get_channel_info(self, channel_name: str) -> ChannelInfo:
        """Get channel information from Telegram.

        Args:
            channel_name: Channel username

        Returns:
            ChannelInfo object
        """
        return await self.telegram.get_channel_info(channel_name)

    async def get_or_create_channel(self, channel: Union[str, int]) -> db.Channel:
        """Get or create a channel in the database."""
        channel_info = await self.get_channel_info(channel)
        return db.get_or_create_channel(channel_info)

    async def dump_messages(
        self,
        channel_name: str,
        min_id: int = 0,
        limit: Optional[int] = None,
        progress_callback: ProgressCallback|None = None,
        dry_run: bool = False,
    ) -> list:
        """Dump messages from a channel to the database.

        Args:
            channel_name: Channel username
            min_id: Minimum message ID to dump (None for all)
            limit: Maximum number of messages to dump (None for all)
            progress_callback: Optional callback function(current, total) for progress updates
            dry_run: If True, return message data dicts without saving to database

        Returns:
            List of saved Message objects (if dry_run=False) or list of data dicts (if dry_run=True)
        """
        # Get total message count for progress tracking
        total_messages = await self.telegram.get_message_count(channel_name)
        if limit and limit < total_messages:
            total_messages = limit

        # Fetch and store messages
        batch = []
        batch_size = 100
        messages = []
        _count = 0

        async for message_data in self.telegram.get_messages(channel_name, min_id=min_id, limit=limit):
            batch.append(message_data)
            _count += 1

            # Save batch when it reaches batch_size
            if len(batch) >= batch_size:
                messages.extend(db.save_messages_batch(batch, dry_run=dry_run))
                batch.clear()

                # Report progress
                if progress_callback:
                    progress_callback(_count)

        # Save remaining messages in batch
        if batch:
            messages.extend(db.save_messages_batch(batch, dry_run=dry_run))
            if progress_callback:
                progress_callback(_count)

        return messages

    async def update_sync_status(self, channel_name: str):
        """Update the sync status for a channel."""
        channel = db.get_channel_by_username(channel_name)
        latest_messages = await self.telegram.get_latest_messages(channel_name, limit=1)
        if latest_messages:
            db.update_channel_sync_status(channel.id, latest_messages[0].id)

    async def sync_messages_and_comments(
        self,
        channel_name: str,
        skip_comments: bool = False,
        limit: Optional[int] = None,
        messages_progress_callback: ProgressCallback|None = None,
        comments_progress_callback: ProgressCallback|None = None,
    ) -> tuple[int, int]:
        """Sync new messages from a channel since last sync, optionally including comments.

        Args:
            channel_name: Channel username
            skip_comments: If True, only sync messages without fetching comments
            limit: Maximum number of new messages to sync (None for all)
            progress_callback: pass to dump_messages and dump_comments

        Returns:
            Tuple of (message_count, comment_count)
        """
        # Get channel info
        channel_info = await self.telegram.get_channel_info(channel_name)
        channel = db.get_channel(channel_info.id)

        if channel:
            min_id = channel.last_sync_message_id
        else:
            min_id = None

        # Phase 1: Dump messages
        messages = await self.dump_messages(
            channel_name,
            min_id=min_id,
            limit=limit,
            progress_callback=messages_progress_callback,
        )

        # Phase 2: Fetch comments for new messages with replies
        comment_count = 0
        if messages and not skip_comments:
            comment_count = await self.dump_comments(channel_name, messages, progress_callback=comments_progress_callback)

        return (len(messages), comment_count)

    async def get_raw_messages(self, channel_name: str, message_ids: list[int]) -> list:
        """Get raw Telegram message objects for inspection.

        Args:
            channel_name: Channel username
            message_ids: List of message IDs to fetch

        Returns:
            List of raw Telegram message objects
        """
        return await self.telegram.client.get_messages(channel_name, ids=message_ids)

    async def get_message_with_comments(self, channel_name: str, message_id: int):
        """Get a message and its comments without saving to database. For debugging purposes.

        Args:
            channel_name: Channel username
            message_id: Message ID to fetch comments for

        Returns:
            Tuple of (MessageData, List[CommentData])
        """
        # Get the message first
        # When passing a single ID, get_messages returns a single Message object, not a list
        message = await self.telegram.client.get_messages(channel_name, ids=message_id)
        if not message:
            raise ValueError(f"Message {message_id} not found in channel {channel_name}")

        message_data = await self.telegram._convert_message_to_data(message)

        # Get comments
        comments = []
        async for comment_data in self.telegram.get_comments(channel_name, message_id):
            comments.append(comment_data)

        # Sort comments by date
        comments.sort(key=lambda c: c.date)

        return message_data, comments

    async def dump_comments(
        self,
        channel_name: str,
        messages_with_replies: list[db.Message],
        progress_callback: ProgressCallback|None = None,
    ) -> int:
        """Dump comments for messages that have replies.

        Args:
            channel_name: Channel username
            limit: Number of most recent messages (with replies) to process (None for all)
            progress_callback: Optional callback function(total_comments)

        Returns:
            Number of comments dumped
        """
        # Check if channel has a discussion group
        discussion_group_id = await self.telegram.get_discussion_group(channel_name)
        if not discussion_group_id:
            raise ValueError(
                f"Channel {channel_name} does not have a linked discussion group. "
                "Comments are not available for this channel."
            )

        total_messages = len(messages_with_replies)
        total_comments = 0
        processed_messages = 0

        # Fetch comments for each message
        for message in messages_with_replies:
            batch = []
            batch_size = 100
            message_comment_count = 0

            async for comment_data in self.telegram.get_comments(channel_name, message.id):
                batch.append(comment_data)
                total_comments += 1
                message_comment_count += 1

                # Save batch when it reaches batch_size
                if len(batch) >= batch_size:
                    db.save_comments_batch(batch)
                    batch.clear()

            # Save remaining comments in batch
            if batch:
                db.save_comments_batch(batch)

            processed_messages += 1

            # Report progress with message details
            if progress_callback:
                progress_callback(total_comments)

        return total_comments

    async def __aenter__(self):
        """Async context manager entry."""
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.stop()
        await self.stop()
