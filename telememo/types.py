"""Pydantic models for data validation."""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class Config(BaseModel):
    """Application configuration."""

    api_id: int = Field(description="Telegram API ID")
    api_hash: str = Field(description="Telegram API hash")
    phone: Optional[str] = Field(default=None, description="Phone number for authentication (optional)")
    db_path: str = Field(default="telememo.db", description="SQLite database path")
    session_name: str = Field(default="telememo_session", description="Telethon session name")


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
