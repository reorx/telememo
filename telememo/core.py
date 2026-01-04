"""Core business logic coordinating telegram and database operations."""

from dataclasses import dataclass
from typing import Callable, Optional, Union

from . import db
from .telegram import TelegramClient
from .types import ChannelInfo, Config, MessageData


ProgressCallback = Callable[[int, int], None]


@dataclass
class SyncResult:
    """Result of a sync operation."""

    messages_added: int = 0
    messages_updated: int = 0
    messages_unchanged: int = 0
    comments_added: int = 0
    comments_updated: int = 0
    comments_unchanged: int = 0
    is_refresh_mode: bool = False  # True if we used refresh fallback

    @property
    def total_messages(self) -> int:
        return self.messages_added + self.messages_updated + self.messages_unchanged

    @property
    def total_comments(self) -> int:
        return self.comments_added + self.comments_updated + self.comments_unchanged


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
        progress_callback: ProgressCallback | None = None,
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
        full: bool = False,
        limit: int = 100,
        messages_progress_callback: ProgressCallback | None = None,
        comments_progress_callback: ProgressCallback | None = None,
    ) -> SyncResult:
        """Sync messages from a channel with smart updates.

        Default behavior (incremental + refresh fallback):
        1. Try to fetch messages newer than last_sync_message_id
        2. If no new messages found, refresh last N messages (default 100)
        3. Only update records when edit_date is different

        Full sync mode (--full):
        1. Fetch all messages from the beginning
        2. Smart update based on edit_date comparison

        Comment sync:
        - Only fetch comments when message's replies count differs from DB
        - Only update comment records when edit_date differs

        Args:
            channel_name: Channel username
            skip_comments: If True, only sync messages without fetching comments
            full: If True, fetch all messages from the beginning
            limit: Max messages to sync in refresh mode (default 100)
            messages_progress_callback: Callback for message progress
            comments_progress_callback: Callback for comment progress

        Returns:
            SyncResult with counts for added/updated/unchanged messages and comments
        """
        result = SyncResult()

        # Get channel info and ensure channel exists in DB
        channel_info = await self.telegram.get_channel_info(channel_name)
        channel = db.get_or_create_channel(channel_info)

        # Phase 1: Fetch messages from Telegram
        if full:
            # Full mode: fetch all messages
            min_id = 0
            fetch_limit = None
        else:
            # Incremental mode: fetch messages newer than last sync
            min_id = channel.last_sync_message_id or 0
            fetch_limit = None  # No limit for incremental

        # Collect all messages from Telegram
        fetched_messages: list[MessageData] = []
        async for message_data in self.telegram.get_messages(channel_name, min_id=min_id, limit=fetch_limit):
            fetched_messages.append(message_data)
            if messages_progress_callback:
                messages_progress_callback(len(fetched_messages))

        # Fallback: if no new messages and not full mode, refresh last N
        if not fetched_messages and not full:
            result.is_refresh_mode = True
            async for message_data in self.telegram.get_messages(channel_name, limit=limit):
                fetched_messages.append(message_data)
                if messages_progress_callback:
                    messages_progress_callback(len(fetched_messages))

        # Phase 2: Smart save messages
        # Get existing messages from DB for comparison (before save)
        existing_messages: dict[int, db.Message] = {}
        if fetched_messages:
            message_ids = [m.id for m in fetched_messages]
            existing_messages = db.get_messages_by_ids(channel_info.id, message_ids)

            # Smart batch save
            _, added, updated, unchanged = db.save_messages_batch_smart(fetched_messages, existing_messages)
            result.messages_added = added
            result.messages_updated = updated
            result.messages_unchanged = unchanged

            # Update sync status in incremental/full mode (not refresh mode)
            if not result.is_refresh_mode:
                # Find the highest message ID and update sync status
                max_id = max(m.id for m in fetched_messages)
                db.update_channel_sync_status(channel_info.id, max_id)

        # Phase 3: Smart sync comments
        if not skip_comments:
            comments_result = await self._sync_comments_smart(
                channel_name,
                channel_info.id,
                fetched_messages,
                existing_messages,
                progress_callback=comments_progress_callback,
            )
            result.comments_added = comments_result[0]
            result.comments_updated = comments_result[1]
            result.comments_unchanged = comments_result[2]

        return result

    async def _sync_comments_smart(
        self,
        channel_name: str,
        channel_id: int,
        fetched_messages: list[MessageData],
        existing_messages_map: dict[int, db.Message],
        progress_callback: ProgressCallback | None = None,
    ) -> tuple[int, int, int]:
        """Smartly sync comments only when replies count differs.

        Args:
            channel_name: Channel username
            channel_id: Channel ID
            fetched_messages: Messages fetched from Telegram
            existing_messages_map: Dict mapping message_id to Message (pre-save state)
            progress_callback: Optional callback for progress

        Returns:
            (added_count, updated_count, unchanged_count)
        """
        added_total = 0
        updated_total = 0
        unchanged_total = 0

        # Check if channel has a discussion group
        discussion_group_id = await self.telegram.get_discussion_group(channel_name)
        if not discussion_group_id:
            # No discussion group, no comments available
            return (0, 0, 0)

        processed_groups = set()  # Track processed grouped_ids to avoid duplicates
        total_comments_processed = 0

        for msg_data in fetched_messages:
            # Skip messages without replies
            if not msg_data.replies or msg_data.replies <= 0:
                continue

            # Skip if we've already processed this group
            if msg_data.grouped_id and msg_data.grouped_id in processed_groups:
                continue

            if msg_data.grouped_id:
                processed_groups.add(msg_data.grouped_id)

            # Get existing message from pre-save state to compare replies count
            existing_msg = existing_messages_map.get(msg_data.id)

            # Only fetch comments if:
            # 1. Message is new (not in DB before this sync)
            # 2. Replies count is different from before
            should_fetch = existing_msg is None or existing_msg.replies != msg_data.replies

            if not should_fetch:
                continue

            # Fetch comments from Telegram
            fetched_comments = []
            async for comment_data in self.telegram.get_comments(channel_name, msg_data.id):
                fetched_comments.append(comment_data)

            if fetched_comments:
                # Get existing comments from DB for comparison
                existing_comments = db.get_comments_for_message_as_dict(channel_id, msg_data.id)

                # Smart batch save comments
                added, updated, unchanged = db.save_comments_batch_smart(fetched_comments, existing_comments)
                added_total += added
                updated_total += updated
                unchanged_total += unchanged

                total_comments_processed += len(fetched_comments)
                if progress_callback:
                    progress_callback(total_comments_processed)

        return (added_total, updated_total, unchanged_total)

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
            raise ValueError(f'Message {message_id} not found in channel {channel_name}')

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
        progress_callback: ProgressCallback | None = None,
    ) -> int:
        """Dump comments for messages that have replies.

        For grouped messages (albums), the replies field might be on any message
        in the group. This function handles that by tracking processed groups
        and finding the correct message to fetch comments from.

        Args:
            channel_name: Channel username
            messages_with_replies: List of messages that have replies (may include grouped messages)
            progress_callback: Optional callback function(total_comments)

        Returns:
            Number of comments dumped
        """
        # Check if channel has a discussion group
        discussion_group_id = await self.telegram.get_discussion_group(channel_name)
        if not discussion_group_id:
            raise ValueError(
                f'Channel {channel_name} does not have a linked discussion group. '
                'Comments are not available for this channel.'
            )

        total_comments = 0
        processed_groups = set()  # Track processed grouped_ids to avoid duplicates

        # Fetch comments for each message
        for message in messages_with_replies:
            # Skip if we've already processed this group
            if message.grouped_id and message.grouped_id in processed_groups:
                continue

            # For grouped messages, find the one with replies field
            if message.grouped_id:
                processed_groups.add(message.grouped_id)
                # Get all messages in the group
                group_messages = db.get_messages_by_grouped_id(message.channel.id, message.grouped_id)
                # Find the message with replies > 0
                message_with_replies = next((m for m in group_messages if m.replies and m.replies > 0), message)
            else:
                message_with_replies = message

            # Fetch comments for the message that has replies
            batch = []
            batch_size = 100

            async for comment_data in self.telegram.get_comments(channel_name, message_with_replies.id):
                batch.append(comment_data)
                total_comments += 1

                # Save batch when it reaches batch_size
                if len(batch) >= batch_size:
                    db.save_comments_batch(batch)
                    batch.clear()

            # Save remaining comments in batch
            if batch:
                db.save_comments_batch(batch)

            # Report progress
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
