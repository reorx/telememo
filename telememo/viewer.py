"""TUI message viewer using Rich library."""

import sys
from datetime import datetime
from typing import List, Optional, Tuple

from rich.console import Console, Group
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from . import db
from .db import Message, Comment


class MessageViewer:
    """Interactive TUI for viewing messages and their comments."""

    def __init__(self, channel_id: int, console: Optional[Console] = None):
        self.channel_id = channel_id
        self.console = console or Console()

        # State management
        self.current_page = 0
        self.page_size = 20
        self.current_selection = 0  # Index within current page
        self.focus = "table"  # "table" or "content"
        self.content_scroll_offset = 0

        # Data
        self.messages: List[Message] = []
        self.total_messages = 0
        self.selected_message: Optional[Message] = None
        self.selected_comments: List[Comment] = []

        # Get channel info for building URLs
        self.channel = db.get_channel(channel_id)

        # Load initial data
        self.load_messages()

    def load_messages(self) -> None:
        """Load messages for current page from database."""
        self.total_messages = db.get_message_count(self.channel_id)
        offset = self.current_page * self.page_size

        self.messages = list(
            Message.select()
            .where(Message.channel == self.channel_id)
            .order_by(Message.date.desc())
            .offset(offset)
            .limit(self.page_size)
        )

        # Load first message if available
        if self.messages:
            self.select_message(0)

    def select_message(self, index: int) -> None:
        """Select a message and load its comments."""
        if 0 <= index < len(self.messages):
            self.current_selection = index
            self.selected_message = self.messages[index]
            self.selected_comments = db.get_comments_for_message(
                self.channel_id, self.selected_message.id
            )
            self.content_scroll_offset = 0

    def build_table(self) -> Table:
        """Build the message table for display."""
        # Calculate current page items
        start_idx = self.current_page * self.page_size + 1
        end_idx = start_idx + len(self.messages) - 1

        table = Table(
            show_header=True,
            header_style="bold magenta",
            title=f"Messages (Page {self.current_page + 1}/{self.get_total_pages()}, Items {start_idx}-{end_idx})",
            title_style="bold cyan",
            show_lines=False,
            expand=True,
        )

        table.add_column("ID", style="cyan", width=10, no_wrap=True)
        table.add_column("Content", style="white", ratio=3, no_wrap=True)
        table.add_column("Date", style="green", width=20, no_wrap=True)
        table.add_column("Comments", style="yellow", width=10, justify="right")

        for i, msg in enumerate(self.messages):
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
            comment_count = str(msg.replies or 0)

            # Highlight selected row
            style = "bold reverse" if i == self.current_selection else ""

            table.add_row(
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
        """Build the content panel showing message and comments."""
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
        if msg.is_edited:
            if isinstance(msg.edit_date, str):
                edit_display = msg.edit_date
            else:
                edit_display = msg.edit_date.strftime('%Y-%m-%d %H:%M:%S') if msg.edit_date else "Unknown"
            lines.append(f"[dim italic]Edited: {edit_display}[/]")
        lines.append("")

        # Message content
        lines.append("[bold]Content:[/]")
        lines.append(msg.text or "[dim](no text)[/]")
        lines.append("")

        # Comments section
        if self.selected_comments:
            lines.append(f"[bold magenta]Comments ({len(self.selected_comments)}):[/]")
            lines.append("─" * 80)

            for i, comment in enumerate(self.selected_comments, 1):
                lines.append(f"[cyan]Comment #{i} (ID: {comment.id})[/]")

                # Format comment date
                if isinstance(comment.date, str):
                    comment_date_display = comment.date[:19]
                else:
                    comment_date_display = comment.date.strftime('%Y-%m-%d %H:%M:%S')
                lines.append(f"[dim]Date: {comment_date_display}[/]")

                if comment.sender_name:
                    lines.append(f"[dim]From: {comment.sender_name}[/]")
                if comment.is_reply_to_comment:
                    lines.append(f"[dim]Reply to: #{comment.reply_to_comment_id}[/]")
                if comment.is_edited:
                    if isinstance(comment.edit_date, str):
                        comment_edit_display = comment.edit_date
                    else:
                        comment_edit_display = comment.edit_date.strftime('%Y-%m-%d %H:%M:%S') if comment.edit_date else "Unknown"
                    lines.append(f"[dim italic]Edited: {comment_edit_display}[/]")
                lines.append("")
                lines.append(comment.text or "[dim](no text)[/]")
                lines.append("─" * 80)
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

    def next_message(self) -> None:
        """Move to next message in table."""
        if self.current_selection < len(self.messages) - 1:
            self.select_message(self.current_selection + 1)

    def prev_message(self) -> None:
        """Move to previous message in table."""
        if self.current_selection > 0:
            self.select_message(self.current_selection - 1)

    def next_page(self) -> None:
        """Load next page of messages."""
        if self.current_page < self.get_total_pages() - 1:
            self.current_page += 1
            self.load_messages()

    def prev_page(self) -> None:
        """Load previous page of messages."""
        if self.current_page > 0:
            self.current_page -= 1
            self.load_messages()

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

    def run(self) -> None:
        """Run the TUI viewer main loop."""
        if not self.messages:
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
                    continue

                # Handle key presses
                if key in ('q', '\x1b'):  # q or Esc
                    running = False

                elif key == '\t':  # Tab
                    self.toggle_focus()

                elif self.focus == "table":
                    # Table navigation
                    if key in ('\x1b[A', 'k'):  # Up arrow or k
                        self.prev_message()
                    elif key in ('\x1b[B', 'j'):  # Down arrow or j
                        self.next_message()
                    elif key in ('\x1b[D', 'h'):  # Left arrow or h
                        self.prev_page()
                    elif key in ('\x1b[C', 'l'):  # Right arrow or l
                        self.next_page()

                elif self.focus == "content":
                    # Content scrolling
                    if key in ('\x1b[A', 'k'):  # Up arrow or k
                        self.scroll_content_up()
                    elif key in ('\x1b[B', 'j'):  # Down arrow or j
                        self.scroll_content_down()
