"""Database models and operations using Peewee ORM."""

from datetime import datetime
from typing import List, Optional

from peewee import (
    BooleanField, CharField, DateTimeField, ForeignKeyField, IntegerField, Model, SqliteDatabase,
    TextField
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
        table_name = "channels"


class Message(BaseModel):
    """Message model."""

    id = IntegerField()
    channel = ForeignKeyField(Channel, backref="messages", on_delete="CASCADE")
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

    class Meta:
        table_name = "messages"
        primary_key = False
        indexes = (
            (("channel", "id"), True),  # Unique constraint on channel + message id
        )


class Comment(BaseModel):
    """Comment model for channel message comments/replies."""

    id = IntegerField()
    parent_message_id = IntegerField(index=True)
    parent_channel = ForeignKeyField(Channel, backref="comments", on_delete="CASCADE")
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
        table_name = "comments"
        primary_key = False
        indexes = (
            (("parent_channel", "parent_message_id", "id"), True),  # Unique constraint
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


def get_or_create_channel(channel_info: ChannelInfo) -> Channel:
    """Get or create a channel from ChannelInfo."""
    channel, created = Channel.get_or_create(
        id=channel_info.id,
        defaults={
            "title": channel_info.title,
            "username": channel_info.username,
            "description": channel_info.description,
            "member_count": channel_info.member_count,
            "created_at": channel_info.created_at,
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


def save_message(message_data: MessageData) -> Message:
    """Save or update a message."""
    message, created = Message.get_or_create(
        channel=message_data.channel_id,
        id=message_data.id,
        defaults={
            "text": message_data.text,
            "date": message_data.date,
            "sender_id": message_data.sender_id,
            "sender_name": message_data.sender_name,
            "views": message_data.views,
            "forwards": message_data.forwards,
            "replies": message_data.replies,
            "is_edited": message_data.is_edited,
            "edit_date": message_data.edit_date,
            "media_type": message_data.media_type,
            "has_media": message_data.has_media,
            "grouped_id": message_data.grouped_id,
        },
    )
    if not created:
        # Update message if it already exists (e.g., edited message)
        message.text = message_data.text
        message.is_edited = message_data.is_edited
        message.edit_date = message_data.edit_date
        message.views = message_data.views
        message.forwards = message_data.forwards
        message.replies = message_data.replies
        message.save()
    return message


def save_messages_batch(message_datas: List[MessageData]) -> List[Message]:
    """Save multiple messages in a batch."""
    messages = []
    with db.atomic():
        for message_data in message_datas:
            message = save_message(message_data)
            messages.append(message)
    return messages


def update_channel_sync_status(channel_id: int, last_message_id: int) -> None:
    """Update channel's last sync message ID and timestamp."""
    channel = Channel.get_by_id(channel_id)
    channel.last_sync_message_id = last_message_id
    channel.last_sync_at = datetime.now()
    channel.save()


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
    return list(
        Message.select()
        .where(Message.channel == channel_id)
        .order_by(Message.date.desc())
        .limit(limit)
    )


def get_message_count(channel_id: int) -> int:
    """Get total message count for a channel."""
    return Message.select().where(Message.channel == channel_id).count()


def save_comment(comment_data: CommentData) -> Comment:
    """Save or update a comment."""
    try:
        # Try to get existing comment
        comment = Comment.get(
            (Comment.parent_channel == comment_data.parent_channel_id) &
            (Comment.parent_message_id == comment_data.parent_message_id) &
            (Comment.id == comment_data.id)
        )
        # Update existing comment using UPDATE query
        Comment.update(
            text=comment_data.text,
            is_edited=comment_data.is_edited,
            edit_date=comment_data.edit_date,
            discussion_group_id=comment_data.discussion_group_id
        ).where(
            (Comment.parent_channel == comment_data.parent_channel_id) &
            (Comment.parent_message_id == comment_data.parent_message_id) &
            (Comment.id == comment_data.id)
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
        .where(
            (Comment.parent_channel == channel_id) &
            (Comment.parent_message_id == message_id)
        )
        .order_by(Comment.date.asc())
    )


def search_comments(query: str, channel_id: Optional[int] = None, limit: int = 50) -> List[Comment]:
    """Search comments by text content."""
    q = Comment.select().where(Comment.text.contains(query))
    if channel_id:
        q = q.where(Comment.parent_channel == channel_id)
    return list(q.order_by(Comment.date.desc()).limit(limit))


def get_messages_with_replies(channel_id: int, limit: Optional[int] = None) -> List[Message]:
    """Get messages that have replies (comments).

    Args:
        channel_id: Channel ID
        limit: Maximum number of messages to return (most recent first)

    Returns:
        List of messages ordered by message ID descending (most recent first)
    """
    query = (
        Message.select()
        .where(
            (Message.channel == channel_id) &
            (Message.replies > 0)
        )
        .order_by(Message.id.desc())
    )

    if limit:
        query = query.limit(limit)

    return list(query)


def get_comment_count(channel_id: int) -> int:
    """Get total comment count for a channel."""
    return Comment.select().where(Comment.parent_channel == channel_id).count()
