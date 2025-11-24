"""Command-line interface for Telememo."""

import asyncio
import logging
import os
import sys
from pathlib import Path

import click

from . import color, config, db
from .core import Scraper
from .types import Config
from .viewer import MessageViewer


@click.group()
@click.option(
    "--channel-name", "-c",
    help="Channel username (e.g., @channelname or channelname)"
)
@click.option('--debug', '-d', is_flag=True, help='Enable debug mode')
@click.option('--reset-db', is_flag=True, help='Reset database')
@click.pass_context
def cli(ctx, channel_name: str, debug: bool, reset_db: bool):
    """Telememo - Telegram channel message dumper to SQLite."""
    # Load configuration
    app_config = config.get_config()

    ctx.ensure_object(dict)
    ctx.obj["config"] = app_config

    # Get channel name from CLI or config file
    channel_name = channel_name or config.get_default_channel()
    if not channel_name:
        click.echo("Error: Channel is required. Use -c/--channel-name or set DEFAULT_CHANNEL in config.")
        ctx.exit(1)
    if channel_name.startswith("@"):
        channel_name = channel_name[1:]
    ctx.obj["channel_name"] = channel_name

    # Ensure channel directory exists
    config.ensure_channel_dir(channel_name)

    # Get paths for this channel
    db_path = config.get_db_path(channel_name)
    print(f"db_path: {db_path}")

    # Ensure data directory exists for global session file
    config.ensure_data_dir()
    session_path = config.get_global_session_path()

    # Store session path in context for Scraper to use
    ctx.obj["session_path"] = session_path

    # Initialize database
    db.init_db(str(db_path))

    if debug:
        logging.basicConfig(level=logging.DEBUG)
    ctx.obj["debug"] = debug

    if reset_db:
        db.delete_db(str(db_path))
    ctx.obj["reset_db"] = reset_db


@cli.command()
@click.option("--limit", '-l', type=int, help="Maximum number of messages to dump")
@click.pass_context
def dump_messages(ctx, limit: int):
    """Dump messages from a channel to the database."""
    config = ctx.obj["config"]
    channel_name = ctx.obj.get("channel_name")
    session_path = ctx.obj["session_path"]

    async def run_dump():
        scraper = Scraper(config, session_path)
        await scraper.start()
        # Get or create channel
        await scraper.get_or_create_channel(channel_name)

        click.echo(f"Fetching channel info for {channel_name}...")
        channel_info = await scraper.get_channel_info(channel_name)
        click.echo(f"Channel: {channel_info.title} (@{channel_info.username})")
        click.echo(f"Members: {channel_info.member_count or 'N/A'}")

        click.echo(f"\nDumping messages from {channel_info.title}...")

        def progress_callback(current: int):
            echo_static_line(f"[ Processing message {current}]")

        messages = await scraper.dump_messages(channel_name, limit=limit, progress_callback=progress_callback)
        click.echo()

        click.echo(f"\n✓ Successfully dumped {len(messages)} messages")
        await scraper.stop()

    asyncio.run(run_dump())


@cli.command()
@click.option("--skip-comments", is_flag=True, help="Only sync messages, skip fetching comments")
@click.option("--limit", '-l', type=int, help="Maximum number of new messages to sync")
@click.pass_context
def sync(ctx, skip_comments: bool, limit: int):
    """Sync new messages and their comments from a channel.

    By default, this command syncs both new messages and their comments.
    Use --skip-comments to sync only messages.
    Use --limit to sync only the most recent N new messages.
    """
    config = ctx.obj["config"]
    channel_name = ctx.obj.get("channel_name")
    session_path = ctx.obj["session_path"]

    async def run_sync():
        scraper = Scraper(config, session_path)
        await scraper.start()
        # Get or create channel
        channel = await scraper.get_or_create_channel(channel_name)

        click.echo(f"Syncing from {channel_name}...")

        # Get total message count for progress tracking
        total_messages = await scraper.telegram.get_message_count(channel_name)
        if limit and limit < total_messages:
            total_messages = limit


        def messages_progress_callback(current: int):
            echo_static_line(f"[ Processing message {current}]")

        def comments_progress_callback(current: int):
            echo_static_line(f"[ Processing comment {current}]")

        message_count, comment_count = await scraper.sync_messages_and_comments(
            channel_name,
            skip_comments=skip_comments,
            limit=limit,
            messages_progress_callback=messages_progress_callback,
            comments_progress_callback=comments_progress_callback,
        )
        click.echo()

        # Display summary
        click.echo("\n" + "=" * 50)
        click.echo("Sync Summary:")
        click.echo(f"  Messages: {message_count}")
        if not skip_comments:
            click.echo(f"  Comments: {comment_count}")
        click.echo("=" * 50)

        await scraper.stop()

    asyncio.run(run_sync())


@cli.command(name="dump-comments")
@click.option("--limit", '-l', type=int, help="Number of most recent messages (with comments) to process")
@click.pass_context
def dump_comments(ctx, limit: int):
    """Dump comments for channel messages.

    This command fetches comments for channel posts that have replies.
    The channel must be dumped first using the 'dump' command.

    Use --limit to process only the most recent N messages with comments.
    For example, --limit 10 will dump comments for the last 10 messages that have comments.
    """
    config = ctx.obj["config"]
    channel_name = ctx.obj.get("channel_name")
    session_path = ctx.obj["session_path"]

    async def run_dump_comments():
        scraper = Scraper(config, session_path)
        await scraper.start()
        # Get or create channel
        channel = await scraper.get_or_create_channel(channel_name)

        # Get count of messages with replies (limited if specified)
        messages_with_replies = db.get_messages_with_replies(channel.id, limit=limit)
        if not messages_with_replies:
            click.echo(f"No messages with comments found in {channel.title}")
            await scraper.stop()
            return

        total_messages = len(messages_with_replies)

        click.echo(f"Channel: {channel.title} (@{channel.username})")
        if limit:
            click.echo(f"Processing last {total_messages} messages with comments")
        else:
            click.echo(f"Processing all {total_messages} messages with comments")
        click.echo(f"\nDumping comments from {channel.title}...\n")

        def progress_callback(current: int):
            echo_static_line(f"[ Processing comment {current}]")

        comments = await scraper.dump_comments(channel_name, messages_with_replies, progress_callback=progress_callback)
        click.echo()

        click.echo(f"\n✓ Successfully dumped {comments} comments")
        await scraper.stop()

    asyncio.run(run_dump_comments())


@cli.command(name="show-message-comments")
@click.argument("message_id", type=int)
@click.pass_context
def show_message_comments(ctx, message_id: int):
    """Show a message and its comments.

    MESSAGE_ID is the ID of the message to display with its comments.

    This command fetches and displays a message and all its comments without
    saving to the database. Useful for testing and previewing comment content.
    """
    config = ctx.obj["config"]
    channel_name = ctx.obj.get("channel_name")
    session_path = ctx.obj["session_path"]

    async def run_show_message_comments():
        scraper = Scraper(config, session_path)
        await scraper.start()

        try:
            click.echo(f"Fetching message {message_id} from {channel_name}...")
            message_data, comments = await scraper.get_message_with_comments(channel_name, message_id)

            # Display message
            click.echo(f"\n{'=' * 80}")
            click.echo(f"MESSAGE ID: {message_data.id} (https://t.me/{channel_name}/{message_data.id})")
            click.echo(f"{'=' * 80}")
            click.echo(f"Date: {message_data.date}")
            if message_data.sender_name:
                click.echo(f"From: {message_data.sender_name}")
            if message_data.views:
                click.echo(f"Views: {message_data.views}")
            if message_data.forwards:
                click.echo(f"Forwards: {message_data.forwards}")
            if message_data.replies:
                click.echo(f"Replies: {message_data.replies}")
            if message_data.is_edited:
                click.echo(f"Edited: {message_data.edit_date}")

            click.echo(f"\nText:")
            click.echo(f"{message_data.text or '(no text)'}")

            # Display comments
            if comments:
                click.echo(f"\n{'=' * 80}")
                click.echo(f"COMMENTS ({len(comments)})")
                click.echo(f"{'=' * 80}\n")

                for i, comment in enumerate(comments, 1):
                    click.echo(f"[{i}] Comment ID: {comment.id}")
                    click.echo(f"    Date: {comment.date}")
                    if comment.sender_name:
                        click.echo(f"    From: {comment.sender_name}")
                    if comment.is_reply_to_comment:
                        click.echo(f"    Reply to comment: {comment.reply_to_comment_id}")
                    if comment.is_edited:
                        click.echo(f"    Edited: {comment.edit_date}")

                    click.echo(f"    Text: {comment.text or '(no text)'}")
                    click.echo()
            else:
                click.echo(f"\nNo comments found for this message.")

        except ValueError as e:
            click.echo(f"Error: {e}")
        except Exception as e:
            click.echo(f"Error: {e}")

        await scraper.stop()

    asyncio.run(run_show_message_comments())


@cli.command()
@click.option('--init-data', is_flag=True, help='init channel data in db')
@click.pass_context
def info(ctx, init_data):
    """Show channel information."""
    config = ctx.obj["config"]
    channel_name = ctx.obj.get("channel_name")
    session_path = ctx.obj["session_path"]

    async def run_info():
        scraper = Scraper(config, session_path)
        await scraper.start()

        channel_info = await scraper.get_channel_info(channel_name)

        click.echo(f"\nChannel Information:")
        click.echo(f"  Title: {channel_info.title}")
        click.echo(f"  Username: @{channel_info.username or 'N/A'}")
        click.echo(f"  ID: {channel_info.id}")
        click.echo(f"  Members: {channel_info.member_count or 'N/A'}")
        if channel_info.description:
            click.echo(f"  Description: {channel_info.description}")

        # Check if channel is in database
        channel = db.get_channel(channel_info.id)
        if channel:
            message_count = db.get_message_count(channel.id)
            comment_count = db.get_comment_count(channel.id)
            click.echo(f"\nDatabase Status:")
            click.echo(f"  Messages stored: {message_count}")
            click.echo(f"  Comments stored: {comment_count}")
            click.echo(f"  Last sync: {channel.last_sync_at or 'Never'}")
            click.echo(f"  Last message ID: {channel.last_sync_message_id or 'N/A'}")
        else:
            if init_data:
                db.get_or_create_channel(channel_info)
            click.echo(f"\nDatabase Status: Not synced yet")

        await scraper.stop()

    asyncio.run(run_info())


@cli.command()
@click.argument("query")
@click.option("--limit", '-l', type=int, default=50, help="Maximum number of results")
@click.option(
    "--target",
    type=click.Choice(["messages", "comments", "all"], case_sensitive=False),
    default="messages",
    help="What to search: messages, comments, or all (default: messages)",
)
@click.option(
    "--include-comments",
    is_flag=True,
    help="When searching messages, also show their comments",
)
@click.pass_context
def search(ctx, query: str, limit: int, target: str, include_comments: bool):
    """Search messages and/or comments by text content.

    QUERY is the search term to look for.

    Examples:
      telememo -c @channel search "keyword"           # Search in specific channel
      telememo search "keyword"                       # Search in all channels
      telememo search "keyword" --target comments     # Search in comments only
      telememo search "keyword" --target all          # Search in both
      telememo search "keyword" --include-comments    # Show matching messages with their comments
    """
    config = ctx.obj["config"]

    channel_name = ctx.obj.get("channel_name")

    # Resolve channel ID if channel username provided
    channel = db.get_channel_by_username(channel_name)
    if not channel:
        click.echo(f"Channel @{channel_name} not found in database. Run 'dump' first.")
        ctx.exit(1)
        return

    channel_id = channel.id

    # Search based on target
    message_results = []
    comment_results = []

    if target in ["messages", "all"]:
        message_results = db.search_messages(query, channel_id=channel_id, limit=limit)

    if target in ["comments", "all"]:
        comment_results = db.search_comments(query, channel_id=channel_id, limit=limit)

    # Display results
    if not message_results and not comment_results:
        click.echo(f"No results found matching '{query}'")
        return

    # Display message results
    if message_results:
        click.echo(f"Found {len(message_results)} message(s) matching '{query}':\n")
        for msg in message_results:
            channel_obj = db.get_channel(msg.channel.id)
            click.echo(f"[{msg.date}] {channel_obj.title} (@{channel_obj.username})")
            click.echo(f"  Message ID: {msg.id} (https://t.me/{channel_name}/{msg.id})")
            if msg.sender_name:
                click.echo(f"  From: {msg.sender_name}")

            # Display message text (truncate if too long)
            text = msg.text or ""
            if len(text) > 200:
                text = text[:200] + "..."
            click.echo(f"  {text}")

            if msg.views:
                click.echo(f"  Views: {msg.views}")
            if msg.replies:
                click.echo(f"  Comments: {msg.replies}")

            # Show comments if requested
            if include_comments:
                comments = db.get_comments_for_message(msg.channel.id, msg.id)
                if comments:
                    click.echo(f"  Comments ({len(comments)}):")
                    for comment in comments[:5]:  # Show first 5 comments
                        comment_text = comment.text or ""
                        if len(comment_text) > 100:
                            comment_text = comment_text[:100] + "..."
                        sender = comment.sender_name or "Unknown"
                        click.echo(f"    - [{comment.date}] {sender}: {comment_text}")
                    if len(comments) > 5:
                        click.echo(f"    ... and {len(comments) - 5} more comments")

            click.echo()

    # Display comment results
    if comment_results:
        click.echo(f"Found {len(comment_results)} comment(s) matching '{query}':\n")
        for comment in comment_results:
            channel_obj = db.get_channel(comment.parent_channel.id)
            click.echo(f"[{comment.date}] {channel_obj.title} (@{channel_obj.username})")
            click.echo(f"  Comment on Message ID: {comment.parent_message_id}")
            click.echo(f"  Comment ID: {comment.id}")
            if comment.sender_name:
                click.echo(f"  From: {comment.sender_name}")

            # Display comment text (truncate if too long)
            text = comment.text or ""
            if len(text) > 200:
                text = text[:200] + "..."
            click.echo(f"  {text}")

            click.echo()


@cli.command()
@click.pass_context
def viewer(ctx):
    """Launch TUI viewer for browsing messages and comments.

    The viewer provides an interactive interface to browse messages with keyboard navigation:
    - ↑↓ or j/k: Navigate messages
    - ←→ or h/l: Navigate pages
    - Tab: Switch focus between message list and content
    - Esc or q: Exit viewer
    """
    import asyncio
    from .core import Scraper

    app_config = ctx.obj["config"]
    channel_name = ctx.obj.get("channel_name")

    # Try to find channel by username first
    channel = db.get_channel_by_username(channel_name)

    if not channel:
        click.echo(f"Channel '{channel_name}' not found in database.")
        click.echo(f"Please run 'telememo dump {channel_name}' first to download messages.")
        ctx.exit(1)

    # Check if channel has messages
    message_count = db.get_message_count(channel.id)
    if message_count == 0:
        click.echo(f"No messages found for channel: {channel.title}")
        click.echo(f"Please run 'telememo dump {channel_name}' first to download messages.")
        ctx.exit(1)

    # Run viewer with async support
    asyncio.run(_run_viewer_async(app_config, channel.id, channel_name))


async def _run_viewer_async(app_config, channel_id: int, channel_name: str):
    """Async wrapper to run the viewer with Telegram client."""
    from .core import Scraper
    from telememo import config as cfg

    # Get global session path
    cfg.ensure_data_dir()
    session_path = cfg.get_global_session_path()

    # Initialize Scraper for fetching raw messages
    scraper = Scraper(app_config, session_path)

    try:
        # Start the scraper (connects to Telegram)
        await scraper.start()

        # Create and run viewer
        viewer_app = MessageViewer(channel_id, scraper, channel_name)
        await viewer_app.run()

    finally:
        # Stop the scraper when viewer exits
        await scraper.stop()


def echo_static_line(s):
    # \r returns cursor to start of line
    # end='' prevents newline
    # flush=True ensures immediate output
    sys.stdout.write(f'\r{color.yellow(s)}')
    sys.stdout.flush()


@cli.command()
def echo_test():
    import time
    print('echo_test 0')
    for i in range(5):
        echo_static_line(f"Processing message {i}")

    print('echo_test 1')
    for i in range(5):
        echo_static_line(f"Processing message {i}")
        time.sleep(1)


if __name__ == "__main__":
    cli()
