"""Database models and operations using Peewee ORM."""

from datetime import datetime
from pathlib import Path
from typing import List, Optional

from peewee import (
    BooleanField,
    CharField,
    DateTimeField,
    ForeignKeyField,
    IntegerField,
    Model,
    SqliteDatabase,
    TextField,
)

from .types import ChannelInfo, CommentData, MessageData


# Database instance (will be initialized later)
db = SqliteDatabase(None)


class BaseModel(Model):
    """Base model with database binding."""

    class Meta:
        database = db


class Channel(BaseModel):
    """Channel model."""

    id = IntegerField(primary_key=True)
    title = CharField()
    username = CharField(null=True, index=True)
    description = TextField(null=True)
    member_count = IntegerField(null=True)
    created_at = DateTimeField(null=True)
    last_sync_message_id = IntegerField(default=0)
    last_sync_at = DateTimeField(null=True)
    added_at = DateTimeField(default=datetime.now)

    class Meta:
        table_name = 'channels'


class Message(BaseModel):
    """Message model."""

    id = IntegerField()
    channel = ForeignKeyField(Channel, backref='messages', on_delete='CASCADE')
    text = TextField(null=True, index=True)
    date = DateTimeField(index=True)
    sender_id = IntegerField(null=True)
    sender_name = CharField(null=True)
    views = IntegerField(null=True)
    forwards = IntegerField(null=True)
    replies = IntegerField(null=True)
    is_edited = BooleanField(default=False)
    edit_date = DateTimeField(null=True)
    media_type = CharField(null=True)
    has_media = BooleanField(default=False)
    grouped_id = IntegerField(null=True, index=True)
    created_at = DateTimeField(default=datetime.now)

    def __str__(self):
        return f'<Message id={self.id} channel={self.channel_id}>'

    class Meta:
        table_name = 'messages'
        primary_key = False
        indexes = (
            (('channel', 'id'), True),  # Unique constraint on channel + message id
        )


class Comment(BaseModel):
    """Comment model for channel message comments/replies."""

    id = IntegerField()
    parent_message_id = IntegerField(index=True)
    parent_channel = ForeignKeyField(Channel, backref='comments', on_delete='CASCADE')
    discussion_group_id = IntegerField()
    text = TextField(null=True, index=True)
    date = DateTimeField(index=True)
    sender_id = IntegerField(null=True)
    sender_name = CharField(null=True)
    is_edited = BooleanField(default=False)
    edit_date = DateTimeField(null=True)
    is_reply_to_comment = BooleanField(default=False)
    reply_to_comment_id = IntegerField(null=True)
    created_at = DateTimeField(default=datetime.now)

    class Meta:
        table_name = 'comments'
        primary_key = False
        indexes = (
            (('parent_channel', 'parent_message_id', 'id'), True),  # Unique constraint
        )


def init_db(db_path: str) -> None:
    """Initialize database connection and create tables."""
    db.init(db_path)
    db.connect()
    db.create_tables([Channel, Message, Comment])


def close_db() -> None:
    """Close database connection."""
    if not db.is_closed():
        db.close()


def delete_db(db_path: str) -> None:
    """Delete database file."""
    if Path(db_path).exists():
        print(f'Deleting database file {db_path}...')
        Path(db_path).unlink()


def get_or_create_channel(channel_info: ChannelInfo) -> Channel:
    """Get or create a channel from ChannelInfo."""
    channel, created = Channel.get_or_create(
        id=channel_info.id,
        defaults={
            'title': channel_info.title,
            'username': channel_info.username,
            'description': channel_info.description,
            'member_count': channel_info.member_count,
            'created_at': channel_info.created_at,
        },
    )
    if not created:
        # Update channel info if it already exists
        channel.title = channel_info.title
        channel.username = channel_info.username
        channel.description = channel_info.description
        channel.member_count = channel_info.member_count
        channel.save()
    return channel


def save_message(message_data: MessageData, dry_run: bool = False) -> Message | dict:
    """Save or update a message.

    Args:
        message_data: Message data to save
        dry_run: If True, return data dict without saving to database

    Returns:
        Message object if dry_run=False, dict if dry_run=True
    """
    data = {
        'channel': message_data.channel_id,
        'id': message_data.id,
        'text': message_data.text,
        'date': message_data.date,
        'sender_id': message_data.sender_id,
        'sender_name': message_data.sender_name,
        'views': message_data.views,
        'forwards': message_data.forwards,
        'replies': message_data.replies,
        'is_edited': message_data.is_edited,
        'edit_date': message_data.edit_date,
        'media_type': message_data.media_type,
        'has_media': message_data.has_media,
        'grouped_id': message_data.grouped_id,
    }

    if dry_run:
        return data

    message, created = Message.get_or_create(
        channel=message_data.channel_id,
        id=message_data.id,
        defaults=data,
    )
    if not created:
        print('update message', message)
        # Update message if it already exists (e.g., edited message)
        message.text = message_data.text
        message.is_edited = message_data.is_edited
        message.edit_date = message_data.edit_date
        message.views = message_data.views
        message.forwards = message_data.forwards
        message.replies = message_data.replies
        message.update()
    return message


def save_messages_batch(message_datas: List[MessageData], dry_run: bool = False) -> List[Message] | List[dict]:
    """Save multiple messages in a batch.

    Args:
        message_datas: List of message data to save
        dry_run: If True, return list of data dicts without saving to database

    Returns:
        List of Message objects if dry_run=False, list of dicts if dry_run=True
    """
    if dry_run:
        return [save_message(message_data, dry_run=True) for message_data in message_datas]

    messages = []
    with db.atomic():
        for message_data in message_datas:
            message = save_message(message_data)
            messages.append(message)
    return messages


def update_channel_sync_status(channel_id: int, last_message_id: int) -> None:
    """Update channel's last sync message ID and timestamp."""
    Channel.update(last_sync_message_id=last_message_id, last_sync_at=datetime.now()).where(
        Channel.id == channel_id
    ).execute()


def get_channel(channel_id: int) -> Optional[Channel]:
    """Get a channel by ID."""
    try:
        return Channel.get_by_id(channel_id)
    except Channel.DoesNotExist:
        return None


def get_channel_by_username(username: str) -> Optional[Channel]:
    """Get a channel by username."""
    try:
        return Channel.get(Channel.username == username)
    except Channel.DoesNotExist:
        return None


def search_messages(query: str, channel_id: Optional[int] = None, limit: int = 50) -> List[Message]:
    """Search messages by text content."""
    q = Message.select().where(Message.text.contains(query))
    if channel_id:
        q = q.where(Message.channel == channel_id)
    return list(q.order_by(Message.date.desc()).limit(limit))


def get_latest_messages(channel_id: int, limit: int = 10) -> List[Message]:
    """Get the latest messages from a channel."""
    return list(Message.select().where(Message.channel == channel_id).order_by(Message.date.desc()).limit(limit))


def get_message_count(channel_id: int) -> int:
    """Get total message count for a channel."""
    return Message.select().where(Message.channel == channel_id).count()


def save_comment(comment_data: CommentData) -> Comment:
    """Save or update a comment."""
    try:
        # Try to get existing comment
        comment = Comment.get(
            (Comment.parent_channel == comment_data.parent_channel_id)
            & (Comment.parent_message_id == comment_data.parent_message_id)
            & (Comment.id == comment_data.id)
        )
        # Update existing comment using UPDATE query
        Comment.update(
            text=comment_data.text,
            is_edited=comment_data.is_edited,
            edit_date=comment_data.edit_date,
            discussion_group_id=comment_data.discussion_group_id,
        ).where(
            (Comment.parent_channel == comment_data.parent_channel_id)
            & (Comment.parent_message_id == comment_data.parent_message_id)
            & (Comment.id == comment_data.id)
        ).execute()
        # Refresh the comment object
        comment.text = comment_data.text
        comment.is_edited = comment_data.is_edited
        comment.edit_date = comment_data.edit_date
        comment.discussion_group_id = comment_data.discussion_group_id
        return comment
    except Comment.DoesNotExist:
        # Create new comment
        comment = Comment.create(
            id=comment_data.id,
            parent_message_id=comment_data.parent_message_id,
            parent_channel=comment_data.parent_channel_id,
            discussion_group_id=comment_data.discussion_group_id,
            text=comment_data.text,
            date=comment_data.date,
            sender_id=comment_data.sender_id,
            sender_name=comment_data.sender_name,
            is_edited=comment_data.is_edited,
            edit_date=comment_data.edit_date,
            is_reply_to_comment=comment_data.is_reply_to_comment,
            reply_to_comment_id=comment_data.reply_to_comment_id,
        )
        return comment


def save_comments_batch(comments: List[CommentData]) -> int:
    """Save multiple comments in a batch."""
    count = 0
    with db.atomic():
        for comment_data in comments:
            save_comment(comment_data)
            count += 1
    return count


def get_comments_for_message(channel_id: int, message_id: int) -> List[Comment]:
    """Get all comments for a specific message."""
    return list(
        Comment.select()
        .where((Comment.parent_channel == channel_id) & (Comment.parent_message_id == message_id))
        .order_by(Comment.date.asc())
    )


def search_comments(query: str, channel_id: Optional[int] = None, limit: int = 50) -> List[Comment]:
    """Search comments by text content."""
    q = Comment.select().where(Comment.text.contains(query))
    if channel_id:
        q = q.where(Comment.parent_channel == channel_id)
    return list(q.order_by(Comment.date.desc()).limit(limit))


def get_messages_by_grouped_id(channel_id: int, grouped_id: int) -> List[Message]:
    """Get all messages that belong to the same group (album).

    Args:
        channel_id: Channel ID
        grouped_id: The grouped_id that identifies the album

    Returns:
        List of messages in the group, ordered by ID
    """
    return list(
        Message.select()
        .where((Message.channel == channel_id) & (Message.grouped_id == grouped_id))
        .order_by(Message.id)
    )


def get_messages_with_replies(channel_id: int, limit: Optional[int] = None) -> List[Message]:
    """Get messages that have replies (comments).

    For grouped messages (albums), if ANY message in the group has replies,
    ALL messages in that group are returned. This is because in albums,
    the message with text and the message with the replies field might be different.

    Args:
        channel_id: Channel ID
        limit: Maximum number of messages to return (most recent first)

    Returns:
        List of messages ordered by message ID descending (most recent first)
    """
    # Get all grouped_ids that have at least one message with replies
    grouped_ids_with_replies = [
        msg.grouped_id
        for msg in Message.select(Message.grouped_id)
        .where((Message.channel == channel_id) & (Message.grouped_id.is_null(False)) & (Message.replies > 0))
        .distinct()
    ]

    # Build query to get:
    # 1. All messages with replies (grouped or not)
    # 2. All messages in groups that have replies
    conditions = [(Message.channel == channel_id) & (Message.replies > 0)]

    if grouped_ids_with_replies:
        conditions.append((Message.channel == channel_id) & (Message.grouped_id.in_(grouped_ids_with_replies)))

    # Combine conditions with OR
    from peewee import reduce
    import operator

    combined_condition = reduce(operator.or_, conditions)

    query = Message.select().where(combined_condition).order_by(Message.id.desc()).distinct()

    if limit:
        query = query.limit(limit)

    return list(query)


def get_comment_count(channel_id: int) -> int:
    """Get total comment count for a channel."""
    return Comment.select().where(Comment.parent_channel == channel_id).count()


def _parse_datetime(value) -> datetime | None:
    """Parse a value into a datetime object.

    Handles datetime objects, strings from SQLite, and None.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    # Parse string from SQLite (format: '2025-11-24 13:15:52+00:00')
    from datetime import timezone

    s = str(value).replace(' ', 'T')  # Normalize to ISO format
    # Handle timezone suffix
    if s.endswith('+00:00'):
        s = s[:-6]
        return datetime.fromisoformat(s).replace(tzinfo=timezone.utc)
    elif '+' in s or s.endswith('Z'):
        return datetime.fromisoformat(s.replace('Z', '+00:00'))
    else:
        return datetime.fromisoformat(s)


def should_update_record(new_edit_date: datetime | None, existing_edit_date) -> bool:
    """Return True if record should be updated based on edit_date comparison.

    Skip update if both are NULL (message was never edited).
    Handles type mismatch between datetime objects and strings from SQLite.
    """
    new_dt = _parse_datetime(new_edit_date)
    existing_dt = _parse_datetime(existing_edit_date)

    if new_dt is None and existing_dt is None:
        return False

    if new_dt is None or existing_dt is None:
        # One is None, the other is not
        return True

    return new_dt != existing_dt


def get_messages_by_ids(channel_id: int, message_ids: list[int]) -> dict[int, Message]:
    """Get multiple messages by their IDs.

    Returns:
        Dict mapping message_id to Message object
    """
    if not message_ids:
        return {}
    messages = Message.select().where((Message.channel == channel_id) & (Message.id.in_(message_ids)))
    return {msg.id: msg for msg in messages}


def save_message_smart(message_data: MessageData, existing: Message | None) -> tuple[Message, str]:
    """Smart save: only update if edit_date changed (skip if both NULL).

    Args:
        message_data: New message data from Telegram
        existing: Existing message from DB (if any)

    Returns:
        (message, status) where status is 'added', 'updated', or 'unchanged'
    """
    if existing is None:
        # New message - insert
        message = Message.create(
            channel=message_data.channel_id,
            id=message_data.id,
            text=message_data.text,
            date=message_data.date,
            sender_id=message_data.sender_id,
            sender_name=message_data.sender_name,
            views=message_data.views,
            forwards=message_data.forwards,
            replies=message_data.replies,
            is_edited=message_data.is_edited,
            edit_date=message_data.edit_date,
            media_type=message_data.media_type,
            has_media=message_data.has_media,
            grouped_id=message_data.grouped_id,
        )
        return message, 'added'

    # Check if we should update
    if should_update_record(message_data.edit_date, existing.edit_date):
        # Update existing message using UPDATE query (can't use save() with composite PK)
        Message.update(
            text=message_data.text,
            is_edited=message_data.is_edited,
            edit_date=message_data.edit_date,
            views=message_data.views,
            forwards=message_data.forwards,
            replies=message_data.replies,
        ).where((Message.channel == message_data.channel_id) & (Message.id == message_data.id)).execute()
        # Update the existing object to reflect changes
        existing.text = message_data.text
        existing.is_edited = message_data.is_edited
        existing.edit_date = message_data.edit_date
        existing.views = message_data.views
        existing.forwards = message_data.forwards
        existing.replies = message_data.replies
        return existing, 'updated'

    return existing, 'unchanged'


def save_messages_batch_smart(
    message_datas: list[MessageData], existing_messages: dict[int, Message]
) -> tuple[list[Message], int, int, int]:
    """Batch save messages with smart comparison.

    Args:
        message_datas: List of message data from Telegram
        existing_messages: Dict mapping message_id to existing Message

    Returns:
        (messages, added_count, updated_count, unchanged_count)
    """
    messages = []
    added = 0
    updated = 0
    unchanged = 0

    with db.atomic():
        for msg_data in message_datas:
            existing = existing_messages.get(msg_data.id)
            message, status = save_message_smart(msg_data, existing)
            messages.append(message)
            if status == 'added':
                added += 1
            elif status == 'updated':
                updated += 1
            else:
                unchanged += 1

    return messages, added, updated, unchanged


def get_comments_for_message_as_dict(channel_id: int, message_id: int) -> dict[int, Comment]:
    """Get comments as dict mapping comment_id -> Comment."""
    comments = Comment.select().where(
        (Comment.parent_channel == channel_id) & (Comment.parent_message_id == message_id)
    )
    return {c.id: c for c in comments}


def save_comment_smart(comment_data: CommentData, existing: Comment | None) -> tuple[Comment, str]:
    """Smart save: only update if edit_date changed (skip if both NULL).

    Returns:
        (comment, status) where status is 'added', 'updated', or 'unchanged'
    """
    if existing is None:
        # New comment - insert
        comment = Comment.create(
            id=comment_data.id,
            parent_message_id=comment_data.parent_message_id,
            parent_channel=comment_data.parent_channel_id,
            discussion_group_id=comment_data.discussion_group_id,
            text=comment_data.text,
            date=comment_data.date,
            sender_id=comment_data.sender_id,
            sender_name=comment_data.sender_name,
            is_edited=comment_data.is_edited,
            edit_date=comment_data.edit_date,
            is_reply_to_comment=comment_data.is_reply_to_comment,
            reply_to_comment_id=comment_data.reply_to_comment_id,
        )
        return comment, 'added'

    # Check if we should update
    if should_update_record(comment_data.edit_date, existing.edit_date):
        # Update using UPDATE query (can't use save() with composite PK)
        Comment.update(
            text=comment_data.text,
            is_edited=comment_data.is_edited,
            edit_date=comment_data.edit_date,
            discussion_group_id=comment_data.discussion_group_id,
        ).where(
            (Comment.parent_channel == comment_data.parent_channel_id)
            & (Comment.parent_message_id == comment_data.parent_message_id)
            & (Comment.id == comment_data.id)
        ).execute()
        # Update the existing object to reflect changes
        existing.text = comment_data.text
        existing.is_edited = comment_data.is_edited
        existing.edit_date = comment_data.edit_date
        existing.discussion_group_id = comment_data.discussion_group_id
        return existing, 'updated'

    return existing, 'unchanged'


def save_comments_batch_smart(
    comments: list[CommentData], existing_comments: dict[int, Comment]
) -> tuple[int, int, int]:
    """Batch save comments with smart comparison.

    Returns:
        (added_count, updated_count, unchanged_count)
    """
    added = 0
    updated = 0
    unchanged = 0

    with db.atomic():
        for comment_data in comments:
            existing = existing_comments.get(comment_data.id)
            _, status = save_comment_smart(comment_data, existing)
            if status == 'added':
                added += 1
            elif status == 'updated':
                updated += 1
            else:
                unchanged += 1

    return added, updated, unchanged


def get_message_by_id(channel_id: int, message_id: int) -> Message | None:
    """Get a single message by its ID."""
    try:
        return Message.get((Message.channel == channel_id) & (Message.id == message_id))
    except Message.DoesNotExist:
        return None
