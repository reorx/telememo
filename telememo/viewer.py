"""TUI message viewer using Rich library."""

import sys
import asyncio
from datetime import datetime
from typing import List, Optional, Dict

from rich.console import Console, Group
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.box import ROUNDED

from . import db, config
from .db import Message, Comment
from .core import Scraper
from .types import DisplayMessage
from .utils import group_messages_to_display


class MessageViewer:
    """Interactive TUI for viewing messages and their comments."""

    def __init__(
        self,
        channel_id: int,
        scraper: Scraper,
        channel_username: str,
        console: Optional[Console] = None
    ):
        self.channel_id = channel_id
        self.channel_username = channel_username
        self.scraper = scraper
        self.console = console or Console()

        # State management
        self.current_page = 0
        self.page_size = 20
        self.current_selection = 0  # Index within current page
        self.focus = "table"  # "table" or "content"
        self.content_scroll_offset = 0

        # Data - now using DisplayMessage instead of Message ORM objects
        self.display_messages: List[DisplayMessage] = []
        self.total_messages = 0
        self.selected_message: Optional[DisplayMessage] = None
        self.selected_comments: List[Comment] = []

        # Get channel info for building URLs
        self.channel = db.get_channel(channel_id)

    async def load_messages(self) -> None:
        """Load messages for current page from database and convert to DisplayMessage."""
        self.total_messages = db.get_message_count(self.channel_id)
        offset = self.current_page * self.page_size

        # Load raw Message ORM objects from database
        db_messages = list(
            Message.select()
            .where(Message.channel == self.channel_id)
            .order_by(Message.date.desc())
            .offset(offset)
            .limit(self.page_size)
        )

        if not db_messages:
            self.display_messages = []
            return

        # Convert ORM objects to dicts
        message_dicts = []
        for msg in db_messages:
            message_dicts.append({
                'id': msg.id,
                'channel': msg.channel.id if hasattr(msg.channel, 'id') else msg.channel,
                'text': msg.text,
                'date': msg.date,
                'sender_id': msg.sender_id,
                'sender_name': msg.sender_name,
                'views': msg.views,
                'forwards': msg.forwards,
                'replies': msg.replies,
                'is_edited': msg.is_edited,
                'edit_date': msg.edit_date,
                'media_type': msg.media_type,
                'has_media': msg.has_media,
                'grouped_id': msg.grouped_id,
            })

        # Fetch raw Telegram messages for forward info
        message_ids = [msg['id'] for msg in message_dicts]
        raw_messages = await self.scraper.get_raw_messages(self.channel_username, message_ids)

        # Create mapping of message_id -> raw_message
        raw_messages_map = {msg.id: msg for msg in raw_messages if msg}

        # Group messages into DisplayMessage objects
        self.display_messages = group_messages_to_display(message_dicts, raw_messages_map)

        # Load first message if available
        if self.display_messages:
            await self.select_message(0)

    async def select_message(self, index: int) -> None:
        """Select a message and load its comments."""
        if 0 <= index < len(self.display_messages):
            self.current_selection = index
            self.selected_message = self.display_messages[index]
            # Load comments for the primary message ID
            self.selected_comments = db.get_comments_for_message(
                self.channel_id, self.selected_message.id
            )
            self.content_scroll_offset = 0

    def build_table(self) -> Table:
        """Build the message table for display."""
        # Calculate current page items
        start_idx = self.current_page * self.page_size + 1
        end_idx = start_idx + len(self.display_messages) - 1

        table = Table(
            show_header=True,
            header_style="bold magenta",
            title=f"Messages (Page {self.current_page + 1}/{self.get_total_pages()}, Items {start_idx}-{end_idx})",
            title_style="bold cyan",
            show_lines=False,
            expand=True,
        )

        # Add columns including new 'T' (Type) column
        table.add_column("T", style="yellow", width=3, no_wrap=True)
        table.add_column("ID", style="cyan", width=10, no_wrap=True)
        table.add_column("Content", style="white", ratio=3, no_wrap=True)
        table.add_column("Date", style="green", width=20, no_wrap=True)
        table.add_column("Comments", style="yellow", width=10, justify="right")

        for i, msg in enumerate(self.display_messages):
            # Build type flags
            type_flags = []
            if msg.is_album:
                type_flags.append("A")
            if msg.is_forwarded:
                type_flags.append("F")
            type_str = ",".join(type_flags) if type_flags else ""

            # Truncate content for table display
            content = msg.text or "(no text)"
            if len(content) > 100:
                content = content[:97] + "..."
            content = content.replace("\n", " ")

            # Format date
            if isinstance(msg.date, str):
                date_str = msg.date[:16]  # Already a string, just truncate
            else:
                date_str = msg.date.strftime("%Y-%m-%d %H:%M")

            # Comment count
            comment_count = str(msg.replies_count or 0)

            # Highlight selected row
            style = "bold reverse" if i == self.current_selection else ""

            table.add_row(
                type_str,
                str(msg.id),
                content,
                date_str,
                comment_count,
                style=style,
            )

        # Add focus indicator to table title
        if self.focus == "table":
            table.title = f"[bold blue]▶[/] {table.title}"

        return table

    def build_content_panel(self) -> Panel:
        """Build the content panel showing message, media items, and comments."""
        if not self.selected_message:
            return Panel(
                "[dim]No message selected[/]",
                title="Content",
                border_style="blue" if self.focus == "content" else "white",
            )

        msg = self.selected_message

        # Build content lines
        lines = []

        # Message header
        lines.append(f"[bold cyan]Message ID: {msg.id}[/]")

        # Format date
        if isinstance(msg.date, str):
            date_display = msg.date[:19]  # Already a string, just truncate
        else:
            date_display = msg.date.strftime('%Y-%m-%d %H:%M:%S')
        lines.append(f"[dim]Date: {date_display}[/]")

        # Add message URL
        if self.channel and self.channel.username:
            msg_url = f"https://t.me/{self.channel.username}/{msg.id}"
            lines.append(f"[dim]URL: {msg_url}[/]")

        if msg.views:
            lines.append(f"[dim]Views: {msg.views}[/]")

        # Show album info
        if msg.is_album:
            lines.append(f"[dim]Album: {len(msg.media_items)} items (Grouped ID: {msg.grouped_id})[/]")

        if msg.is_edited:
            if isinstance(msg.edit_date, str):
                edit_display = msg.edit_date
            else:
                edit_display = msg.edit_date.strftime('%Y-%m-%d %H:%M:%S') if msg.edit_date else "Unknown"
            lines.append(f"[dim italic]Edited: {edit_display}[/]")

        # Show forward information
        if msg.is_forwarded and msg.forward_info:
            fwd = msg.forward_info
            lines.append(f"[dim]Forwarded from:[/]")
            if fwd.from_channel_id:
                lines.append(f"[dim]  Channel ID: {fwd.from_channel_id}[/]")
            if fwd.from_channel_name:
                lines.append(f"[dim]  Channel: {fwd.from_channel_name}[/]")
            if fwd.from_user_id:
                lines.append(f"[dim]  User ID: {fwd.from_user_id}[/]")
            if fwd.from_user_name:
                lines.append(f"[dim]  User: {fwd.from_user_name}[/]")
            if fwd.original_date:
                if isinstance(fwd.original_date, str):
                    orig_date_display = fwd.original_date[:19]
                else:
                    orig_date_display = fwd.original_date.strftime('%Y-%m-%d %H:%M:%S')
                lines.append(f"[dim]  Original Date: {orig_date_display}[/]")

        lines.append("")

        # Message content
        lines.append("[bold]Content:[/]")
        lines.append(msg.text or "[dim](no text)[/]")
        lines.append("")

        # Media items section (if any)
        if msg.media_items:
            lines.append(f"[bold yellow]Media Items ({len(msg.media_items)}):[/]")
            lines.append("")

            for i, media in enumerate(msg.media_items, 1):
                lines.append("┌" + "─" * 58 + "┐")
                lines.append(f"│ [cyan]Media {i} of {len(msg.media_items)}[/]" + " " * (58 - len(f"Media {i} of {len(msg.media_items)}") - 1) + "│")
                lines.append("├" + "─" * 58 + "┤")
                lines.append(f"│ Message ID: {media.message_id}" + " " * (58 - len(f"Message ID: {media.message_id}") - 1) + "│")
                lines.append(f"│ Type: {media.media_type or 'Unknown'}" + " " * (58 - len(f"Type: {media.media_type or 'Unknown'}") - 1) + "│")
                lines.append("└" + "─" * 58 + "┘")
                lines.append("")

        # Comments section
        if self.selected_comments:
            lines.append(f"[bold magenta]Comments ({len(self.selected_comments)}):[/]")
            lines.append("")

            for i, comment in enumerate(self.selected_comments, 1):
                # Box for each comment
                lines.append("┌" + "─" * 58 + "┐")
                lines.append(f"│ [cyan]Comment #{i} (ID: {comment.id})[/]" + " " * (58 - len(f"Comment #{i} (ID: {comment.id})") - 3) + "│")
                lines.append("├" + "─" * 58 + "┤")

                # Format comment date
                if isinstance(comment.date, str):
                    comment_date_display = comment.date[:19]
                else:
                    comment_date_display = comment.date.strftime('%Y-%m-%d %H:%M:%S')
                lines.append(f"│ Date: {comment_date_display}" + " " * (58 - len(f"Date: {comment_date_display}") - 1) + "│")

                if comment.sender_name:
                    sender_line = f"From: {comment.sender_name}"
                    if len(sender_line) > 56:
                        sender_line = sender_line[:54] + ".."
                    lines.append(f"│ {sender_line}" + " " * (58 - len(sender_line) - 1) + "│")

                if comment.is_reply_to_comment:
                    lines.append(f"│ Reply to: #{comment.reply_to_comment_id}" + " " * (58 - len(f"Reply to: #{comment.reply_to_comment_id}") - 1) + "│")

                if comment.is_edited:
                    if isinstance(comment.edit_date, str):
                        comment_edit_display = comment.edit_date[:19]
                    else:
                        comment_edit_display = comment.edit_date.strftime('%Y-%m-%d %H:%M:%S') if comment.edit_date else "Unknown"
                    lines.append(f"│ Edited: {comment_edit_display}" + " " * (58 - len(f"Edited: {comment_edit_display}") - 1) + "│")

                lines.append("├" + "─" * 58 + "┤")

                # Comment text - handle multi-line
                comment_text = comment.text or "(no text)"
                # Split by newlines and wrap
                for text_line in comment_text.split("\n"):
                    if len(text_line) <= 56:
                        lines.append(f"│ {text_line}" + " " * (58 - len(text_line) - 1) + "│")
                    else:
                        # Simple truncation for now
                        lines.append(f"│ {text_line[:54]}.." + " " * 2 + "│")

                lines.append("└" + "─" * 58 + "┘")
                lines.append("")
        else:
            lines.append("[dim]No comments[/]")

        # Apply scroll offset
        visible_lines = lines[self.content_scroll_offset:]
        content_text = "\n".join(visible_lines)

        # Add focus indicator
        title = "Content"
        if self.focus == "content":
            title = f"[bold blue]▶[/] {title} (↑↓ to scroll)"

        return Panel(
            content_text,
            title=title,
            border_style="blue" if self.focus == "content" else "white",
        )

    def build_layout(self) -> Layout:
        """Build the main layout with table and content."""
        layout = Layout()

        layout.split_column(
            Layout(name="table", ratio=1),
            Layout(name="content", ratio=2),
        )

        layout["table"].update(self.build_table())
        layout["content"].update(self.build_content_panel())

        return layout

    def get_total_pages(self) -> int:
        """Calculate total number of pages."""
        if self.total_messages == 0:
            return 1
        return (self.total_messages + self.page_size - 1) // self.page_size

    async def next_message(self) -> None:
        """Move to next message in table."""
        if self.current_selection < len(self.display_messages) - 1:
            await self.select_message(self.current_selection + 1)

    async def prev_message(self) -> None:
        """Move to previous message in table."""
        if self.current_selection > 0:
            await self.select_message(self.current_selection - 1)

    async def next_page(self) -> None:
        """Load next page of messages."""
        if self.current_page < self.get_total_pages() - 1:
            self.current_page += 1
            await self.load_messages()

    async def prev_page(self) -> None:
        """Load previous page of messages."""
        if self.current_page > 0:
            self.current_page -= 1
            await self.load_messages()

    def scroll_content_down(self) -> None:
        """Scroll content panel down."""
        if self.focus == "content":
            self.content_scroll_offset += 1

    def scroll_content_up(self) -> None:
        """Scroll content panel up."""
        if self.focus == "content" and self.content_scroll_offset > 0:
            self.content_scroll_offset -= 1

    def toggle_focus(self) -> None:
        """Switch focus between table and content."""
        self.focus = "content" if self.focus == "table" else "table"

    def get_key(self) -> str:
        """Get a single keypress from stdin."""
        import termios
        import tty
        import select

        # Check if stdin is a TTY
        if not sys.stdin.isatty():
            raise RuntimeError("Viewer requires an interactive terminal")

        fd = sys.stdin.fileno()
        old_settings = termios.tcgetattr(fd)
        try:
            tty.setraw(fd)

            # Wait for input with timeout
            if select.select([sys.stdin], [], [], 0.1)[0]:
                ch = sys.stdin.read(1)

                # Handle escape sequences (arrow keys, etc.)
                if ch == '\x1b':
                    # Check if more characters are available (arrow keys)
                    if select.select([sys.stdin], [], [], 0.01)[0]:
                        ch += sys.stdin.read(2)

                return ch
            else:
                return ''  # No input
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)

    async def run(self) -> None:
        """Run the TUI viewer main loop."""
        # Load initial messages
        await self.load_messages()

        if not self.display_messages:
            self.console.print("[yellow]No messages found in this channel.[/]")
            return

        # Build help text
        help_text = (
            "[dim]Navigation: ↑↓/jk=select | ←→/hl=page | Tab=focus | Esc/q=quit[/]"
        )

        with Live(
            console=self.console,
            screen=True,
            auto_refresh=False,
        ) as live:
            running = True

            while running:
                # Build and display layout
                layout_group = Group(
                    self.build_layout(),
                    Panel(help_text, style="dim", border_style="dim"),
                )
                live.update(layout_group)
                live.refresh()

                # Get keyboard input
                key = self.get_key()

                # Skip if no input
                if not key:
                    await asyncio.sleep(0.01)  # Small delay to prevent CPU spinning
                    continue

                # Handle key presses
                if key in ('q', '\x1b'):  # q or Esc
                    running = False

                elif key == '\t':  # Tab
                    self.toggle_focus()

                elif self.focus == "table":
                    # Table navigation
                    if key in ('\x1b[A', 'k'):  # Up arrow or k
                        await self.prev_message()
                    elif key in ('\x1b[B', 'j'):  # Down arrow or j
                        await self.next_message()
                    elif key in ('\x1b[D', 'h'):  # Left arrow or h
                        await self.prev_page()
                    elif key in ('\x1b[C', 'l'):  # Right arrow or l
                        await self.next_page()

                elif self.focus == "content":
                    # Content scrolling
                    if key in ('\x1b[A', 'k'):  # Up arrow or k
                        self.scroll_content_up()
                    elif key in ('\x1b[B', 'j'):  # Down arrow or j
                        self.scroll_content_down()
