"""High-level, storage-agnostic Telegram facade (Part A4).

`TelegramService` wraps Telethon for programmatic, long-lived use by an embedding
application (condenser):

- programmatic step-by-step auth (code + optional 2FA) instead of interactive start
- recent-N-days backfill via offset_date
- realtime ``events.NewMessage`` subscription
- on-demand media streaming (no disk persistence)

Session state travels in and out as a Telethon StringSession string; persisting
and encrypting it is the caller's responsibility. The facade does NOT depend on
telememo's ``~/.config/telememo/config.py`` — it is constructed from plain params.

Telememo principle: low-level helpers raise; only these long-running orchestration
methods catch ``FloodWaitError`` to back off (the one sanctioned exception).
"""

import asyncio
import platform
from datetime import datetime, timedelta, timezone
from typing import AsyncIterator, Awaitable, Callable, Optional, Union

from telethon import TelegramClient as TelethonClient
from telethon import events
from telethon.errors import FloodWaitError, SessionPasswordNeededError
from telethon.sessions import StringSession

from . import db
from .telegram import convert_channel_to_info, convert_message_to_data
from .types import ChannelInfo, DisplayMessage, MessageData, SignInResult
from .utils import group_messages_to_display


OnMessage = Callable[[DisplayMessage], Awaitable[None]]


def _normalize_handle(handle: Union[str, int]) -> Union[str, int]:
    """Normalize a channel handle for ``get_entity``.

    Accepts ``@username``, a bare username, a ``t.me/...`` link, or a numeric id
    (as int or str). Telethon resolves usernames and t.me links directly; we only
    coerce numeric strings to int so id lookups work.
    """
    if isinstance(handle, int):
        return handle
    h = handle.strip()
    if h.lstrip('-').isdigit():
        return int(h)
    return h


def _message_data_to_row(md: MessageData) -> dict:
    """Project a MessageData onto the dict shape group_messages_to_display expects."""
    return {
        'id': md.id,
        'channel': md.channel_id,
        'text': md.text,
        'date': md.date,
        'sender_id': md.sender_id,
        'sender_name': md.sender_name,
        'views': md.views,
        'forwards': md.forwards,
        'replies': md.replies,
        'is_edited': md.is_edited,
        'edit_date': md.edit_date,
        'media_type': md.media_type,
        'has_media': md.has_media,
        'grouped_id': md.grouped_id,
        'webpage': md.webpage,
        'is_forwarded': md.is_forwarded,
        'fwd_from_channel_id': md.fwd_from_channel_id,
        'fwd_from_channel_name': md.fwd_from_channel_name,
        'fwd_from_user_id': md.fwd_from_user_id,
        'fwd_from_user_name': md.fwd_from_user_name,
        'fwd_from_message_id': md.fwd_from_message_id,
        'fwd_original_date': md.fwd_original_date,
        'fwd_post_author': md.fwd_post_author,
    }


def _persist_messages(channel_id: int, batch: list[MessageData]) -> None:
    """Smart-save a batch of messages (native columns only; extension columns untouched)."""
    existing = db.get_messages_by_ids(channel_id, [m.id for m in batch])
    db.save_messages_batch_smart(batch, existing)


class TelegramService:
    """Programmatic, long-lived Telegram facade (see module docstring)."""

    # ---- construction / lifecycle ----
    def __init__(
        self,
        api_id: int,
        api_hash: str,
        session: Optional[str] = None,
        client: Optional[TelethonClient] = None,
    ):
        """Build the facade.

        Args:
            api_id / api_hash: Telegram app credentials (my.telegram.org).
            session: Telethon StringSession string; None means not yet logged in.
            client: Optional pre-built client, mainly for testing/injection.
        """
        self.api_id = api_id
        self.api_hash = api_hash
        if client is not None:
            self.client = client
        else:
            self.client = TelethonClient(
                StringSession(session),
                api_id,
                api_hash,
                device_model=f'Condenser on {platform.system()}',
                system_version=platform.release(),
            )
        self._authorized = False
        self._phone: Optional[str] = None
        self._subscription_handler = None
        self._subscribed_chats: list[int] = []

    async def connect(self) -> None:
        """Establish the connection without triggering interactive auth."""
        await self.client.connect()
        self._authorized = await self.client.is_user_authorized()

    async def disconnect(self) -> None:
        """Disconnect the underlying client."""
        await self.client.disconnect()

    @property
    def is_authorized(self) -> bool:
        """Cached authorization flag (refreshed on connect / sign-in)."""
        return self._authorized

    # ---- step login (replaces interactive client.start) ----
    async def send_code(self, phone: str) -> str:
        """Request a login code; returns ``phone_code_hash`` for the sign-in step."""
        self._phone = phone
        result = await self.client.send_code_request(phone)
        return result.phone_code_hash

    async def sign_in_code(self, phone: str, code: str, phone_code_hash: str) -> SignInResult:
        """Submit the login code.

        Returns ``SignInResult(status='ok', session=...)`` on success, or
        ``SignInResult(status='2fa_required')`` if a 2FA password is needed next.
        """
        try:
            await self.client.sign_in(phone=phone, code=code, phone_code_hash=phone_code_hash)
        except SessionPasswordNeededError:
            return SignInResult(status='2fa_required')
        self._authorized = True
        return SignInResult(status='ok', session=self.export_session())

    async def sign_in_2fa(self, password: str) -> SignInResult:
        """Submit the 2FA password after ``sign_in_code`` reported '2fa_required'."""
        await self.client.sign_in(password=password)
        self._authorized = True
        return SignInResult(status='ok', session=self.export_session())

    def export_session(self) -> str:
        """Export the current StringSession string (for the caller to encrypt + store)."""
        return self.client.session.save()

    # ---- channels ----
    async def resolve_channel(self, handle: Union[str, int]) -> ChannelInfo:
        """Resolve ``@username`` / t.me link / id to ChannelInfo."""
        entity = await self.client.get_entity(_normalize_handle(handle))
        return convert_channel_to_info(entity)

    # ---- backfill (recent N days via offset_date) ----
    async def backfill(
        self,
        channel: Union[str, int],
        since_days: Optional[int] = None,
        since_date: Optional[datetime] = None,
        persist: bool = True,
        batch_size: int = 100,
        offset_id: int = 0,
        max_messages: Optional[int] = None,
    ) -> AsyncIterator[DisplayMessage]:
        """Backfill messages, newest-first, stopping past the cutoff or the count limit.

        The cutoff is ``since_date`` if given, else ``now - since_days`` days. With
        neither, all messages are pulled. ``offset_id`` starts iteration just *below* a
        known message id (Telethon yields strictly-older messages) — pass the oldest
        stored id to page further back into history. ``max_messages`` caps how many are
        pulled. When ``persist`` is True, messages are stored through telememo's smart
        batch save (native columns only).

        Yields grouped DisplayMessage objects (albums merged).
        """
        cutoff = since_date
        if cutoff is None and since_days is not None:
            cutoff = datetime.now(timezone.utc) - timedelta(days=since_days)

        entity = await self.client.get_entity(_normalize_handle(channel))
        channel_id = entity.id
        if persist:
            db.get_or_create_channel(convert_channel_to_info(entity))

        batch: list[MessageData] = []
        max_id = 0

        async for md in self._iter_backfill(entity, cutoff, offset_id=offset_id, max_messages=max_messages):
            batch.append(md)
            max_id = max(max_id, md.id)
            if len(batch) >= batch_size:
                if persist:
                    _persist_messages(channel_id, batch)
                for dm in group_messages_to_display([_message_data_to_row(m) for m in batch]):
                    yield dm
                batch = []

        if batch:
            if persist:
                _persist_messages(channel_id, batch)
            for dm in group_messages_to_display([_message_data_to_row(m) for m in batch]):
                yield dm

        # Only a top-of-feed fetch advances the sync watermark; a backward (offset_id)
        # historical fetch must not downgrade it to an older id.
        if persist and max_id and not offset_id:
            db.update_channel_sync_status(channel_id, max_id)

    async def _iter_backfill(
        self,
        entity,
        cutoff: Optional[datetime],
        offset_id: int = 0,
        max_messages: Optional[int] = None,
    ) -> AsyncIterator[MessageData]:
        """Iterate messages newest-first from ``offset_id``, stopping at the cutoff or count.

        Retries with FloodWait backoff (the sanctioned exception for this layer).
        """
        yielded = 0
        while True:
            try:
                got_any = False
                async for message in self.client.iter_messages(entity, offset_id=offset_id):
                    if message is None:
                        continue
                    got_any = True
                    offset_id = message.id
                    if cutoff is not None and message.date < cutoff:
                        return
                    yield convert_message_to_data(message)
                    yielded += 1
                    if max_messages is not None and yielded >= max_messages:
                        return
                # Exhausted the channel.
                if not got_any:
                    return
                return
            except FloodWaitError as e:
                await asyncio.sleep(e.seconds + 1)
                # loop continues from the last offset_id

    # ---- realtime subscribe ----
    async def subscribe(
        self,
        channels: list[int],
        on_message: Optional[OnMessage] = None,
        persist: bool = True,
    ) -> None:
        """Register a realtime ``NewMessage`` listener for ``channels``.

        New messages are persisted (when ``persist``) and passed to ``on_message``
        as a single-message DisplayMessage. Returns immediately; events fire on the
        shared event loop while the client stays connected.
        """
        self._subscribed_chats = list(channels)

        async def handler(event):
            await self._handle_new_message(event.message, on_message, persist)

        self._subscription_handler = handler
        self.client.add_event_handler(handler, events.NewMessage(chats=channels))

    async def update_subscription(self, channels: list[int]) -> None:
        """Adjust the set of chats the realtime listener watches."""
        if self._subscription_handler is not None:
            self.client.remove_event_handler(self._subscription_handler)
        self._subscribed_chats = list(channels)
        self.client.add_event_handler(self._subscription_handler, events.NewMessage(chats=channels))

    async def unsubscribe(self) -> None:
        """Remove the realtime listener (e.g. when no channels remain enabled)."""
        if self._subscription_handler is not None:
            self.client.remove_event_handler(self._subscription_handler)
            self._subscription_handler = None
        self._subscribed_chats = []

    @property
    def is_listening(self) -> bool:
        """Whether a realtime NewMessage handler is currently registered."""
        return self._subscription_handler is not None

    async def _handle_new_message(self, message, on_message: Optional[OnMessage], persist: bool) -> None:
        """Convert + persist + dispatch a single realtime message."""
        md = convert_message_to_data(message)
        if persist:
            existing = db.get_message_by_id(md.channel_id, md.id)
            db.save_message_smart(md, existing)
        if on_message is not None:
            displays = group_messages_to_display([_message_data_to_row(md)])
            if displays:
                await on_message(displays[0])

    # ---- media proxy (on-demand, no disk persistence) ----
    async def get_media(
        self, channel: Union[str, int], message_id: int, thumb: bool = False
    ) -> tuple[AsyncIterator[bytes], str]:
        """Return ``(byte_stream, mime_type)`` for a message's media.

        ``thumb=True`` returns the largest available thumbnail (jpeg). Full media is
        streamed via ``iter_download``; nothing is written to disk.
        """
        message = await self.client.get_messages(_normalize_handle(channel), ids=message_id)
        if not message or not message.media:
            raise ValueError(f'message {message_id} in {channel} has no media')

        if thumb:
            data = await self.client.download_media(message, file=bytes, thumb=-1)

            async def thumb_stream() -> AsyncIterator[bytes]:
                yield data

            return thumb_stream(), 'image/jpeg'

        mime = message.file.mime_type if message.file and message.file.mime_type else 'application/octet-stream'

        async def media_stream() -> AsyncIterator[bytes]:
            async for chunk in self.client.iter_download(message.media):
                yield chunk

        return media_stream(), mime

    async def get_channel_photo(self, channel: Union[str, int]) -> Optional[tuple[bytes, str]]:
        """Return ``(jpeg_bytes, mime)`` for a channel's profile photo, or ``None`` if it has none.

        Downloads the small variant; buffered fully (avatars are tiny) and never written to disk.
        """
        entity = await self.client.get_entity(_normalize_handle(channel))
        data = await self.client.download_profile_photo(entity, file=bytes, download_big=False)
        if data is None:
            return None
        return data, 'image/jpeg'

    async def __aenter__(self):
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.disconnect()
