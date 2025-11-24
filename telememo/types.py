"""Pydantic models for data validation."""

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field


class Config(BaseModel):
    """Application configuration."""

    api_id: int = Field(description="Telegram API ID")
    api_hash: str = Field(description="Telegram API hash")
    phone: Optional[str] = Field(default=None, description="Phone number for authentication (optional)")
    db_path: str = Field(default="telememo.db", description="SQLite database path")
    session_name: str = Field(default="telethon_session.db", description="Telethon session name")


class ChannelInfo(BaseModel):
    """Telegram channel information."""

    id: int = Field(description="Channel ID")
    title: str = Field(description="Channel title")
    username: Optional[str] = Field(default=None, description="Channel username")
    description: Optional[str] = Field(default=None, description="Channel description")
    member_count: Optional[int] = Field(default=None, description="Number of members")
    created_at: Optional[datetime] = Field(default=None, description="Channel creation date")


class MessageData(BaseModel):
    """Telegram message data."""

    id: int = Field(description="Message ID")
    channel_id: int = Field(description="Channel ID this message belongs to")
    text: Optional[str] = Field(default=None, description="Message text content")
    date: datetime = Field(description="Message date")
    sender_id: Optional[int] = Field(default=None, description="Sender user/channel ID")
    sender_name: Optional[str] = Field(default=None, description="Sender name")
    views: Optional[int] = Field(default=None, description="Number of views")
    forwards: Optional[int] = Field(default=None, description="Number of forwards")
    replies: Optional[int] = Field(default=None, description="Number of replies")
    is_edited: bool = Field(default=False, description="Whether message was edited")
    edit_date: Optional[datetime] = Field(default=None, description="Last edit date")
    media_type: Optional[str] = Field(default=None, description="Type of media (photo, video, etc)")
    has_media: bool = Field(default=False, description="Whether message has media")
    grouped_id: Optional[int] = Field(default=None, description="Grouped ID for media albums")


class CommentData(BaseModel):
    """Telegram comment/reply data."""

    id: int = Field(description="Comment message ID")
    parent_message_id: int = Field(description="Parent message ID this comment belongs to")
    parent_channel_id: int = Field(description="Parent channel ID")
    discussion_group_id: int = Field(description="Discussion group ID where comment is stored")
    text: Optional[str] = Field(default=None, description="Comment text content")
    date: datetime = Field(description="Comment date")
    sender_id: Optional[int] = Field(default=None, description="Sender user/channel ID")
    sender_name: Optional[str] = Field(default=None, description="Sender name")
    is_edited: bool = Field(default=False, description="Whether comment was edited")
    edit_date: Optional[datetime] = Field(default=None, description="Last edit date")
    is_reply_to_comment: bool = Field(default=False, description="Whether this is a reply to another comment")
    reply_to_comment_id: Optional[int] = Field(default=None, description="ID of comment this is replying to")


class MediaItem(BaseModel):
    """Individual media item in an album."""

    message_id: int = Field(description="Message ID of this media item")
    media_type: Optional[str] = Field(default=None, description="Type of media (photo, video, etc)")
    has_media: bool = Field(default=False, description="Whether this item has media")


class ForwardInfo(BaseModel):
    """Forward source information."""

    from_channel_id: Optional[int] = Field(default=None, description="Original channel ID")
    from_channel_name: Optional[str] = Field(default=None, description="Original channel name")
    from_user_id: Optional[int] = Field(default=None, description="Original user ID")
    from_user_name: Optional[str] = Field(default=None, description="Original user name")
    from_message_id: Optional[int] = Field(default=None, description="Original message ID")
    original_date: Optional[datetime] = Field(default=None, description="Original message date")
    post_author: Optional[str] = Field(default=None, description="Post author signature")


class DisplayMessage(BaseModel):
    """Message as displayed to users in Telegram, handling album grouping.

    This represents a single message unit from the user's perspective:
    - A standalone text/media message
    - An album of multiple photos/videos shown as one message
    - A forwarded message or album
    """

    # Core identification
    id: int = Field(description="Primary message ID (first in album if grouped)")
    channel_id: int = Field(description="Channel ID this message belongs to")

    # Temporal info
    date: datetime = Field(description="Message date")
    is_edited: bool = Field(default=False, description="Whether message was edited")
    edit_date: Optional[datetime] = Field(default=None, description="Last edit date")

    # Sender info
    sender_id: Optional[int] = Field(default=None, description="Sender user/channel ID")
    sender_name: Optional[str] = Field(default=None, description="Sender name")

    # Content
    text: Optional[str] = Field(default=None, description="Message text content")

    # Media handling
    is_album: bool = Field(default=False, description="Whether this is a media album")
    grouped_id: Optional[int] = Field(default=None, description="Grouped ID for media albums")
    media_items: List[MediaItem] = Field(default_factory=list, description="Media items in this message/album")

    # Forward information
    is_forwarded: bool = Field(default=False, description="Whether this message is forwarded")
    forward_info: Optional[ForwardInfo] = Field(default=None, description="Forward source information")

    # Statistics (aggregated for albums)
    views: Optional[int] = Field(default=None, description="Number of views (max for albums)")
    forwards_count: Optional[int] = Field(default=None, description="Number of forwards (max for albums)")
    replies_count: Optional[int] = Field(default=None, description="Number of replies (sum for albums)")

    # Raw messages that compose this display message
    raw_message_ids: List[int] = Field(default_factory=list, description="Message IDs that compose this display message")
