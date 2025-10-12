"""Database models and operations using Peewee ORM."""

from datetime import datetime
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

from .types import ChannelInfo, MessageData

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
    created_at = DateTimeField(default=datetime.now)

    class Meta:
        table_name = "messages"
        primary_key = False
        indexes = (
            (("channel", "id"), True),  # Unique constraint on channel + message id
        )


def init_db(db_path: str) -> None:
    """Initialize database connection and create tables."""
    db.init(db_path)
    db.connect()
    db.create_tables([Channel, Message])


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


def save_messages_batch(messages: List[MessageData]) -> int:
    """Save multiple messages in a batch."""
    count = 0
    with db.atomic():
        for message_data in messages:
            save_message(message_data)
            count += 1
    return count


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
