"""Command-line interface for Telememo."""

import asyncio
import os
from pathlib import Path

import click
from dotenv import load_dotenv

from . import db
from .core import Scraper
from .types import Config

# Load environment variables
load_dotenv()


def load_config() -> Config:
    """Load configuration from environment variables."""
    # Get required API credentials
    api_id = os.getenv("TELEGRAM_API_ID")
    api_hash = os.getenv("TELEGRAM_API_HASH")

    if not api_id or not api_hash:
        raise ValueError(
            "TELEGRAM_API_ID and TELEGRAM_API_HASH must be set in .env file.\n"
            "Get them from https://my.telegram.org"
        )

    return Config(
        api_id=int(api_id),
        api_hash=api_hash,
        phone=os.getenv("PHONE"),  # Optional phone number
        db_path=os.getenv("DB_PATH", "telememo.db"),
        session_name=os.getenv("SESSION_NAME", "telememo_session"),
    )


@click.group()
@click.pass_context
def cli(ctx):
    """Telememo - Telegram channel message dumper to SQLite."""
    # Initialize database
    config = load_config()
    db.init_db(config.db_path)
    ctx.ensure_object(dict)
    ctx.obj["config"] = config


@cli.command()
@click.argument("channel")
@click.option("--limit", type=int, help="Maximum number of messages to dump")
@click.pass_context
def dump(ctx, channel: str, limit: int):
    """Dump messages from a channel to the database.

    CHANNEL can be a username (e.g., @channelname or channelname) or channel ID.
    """
    config = ctx.obj["config"]

    async def run_dump():
        scraper = Scraper(config)
        await scraper.start()

        click.echo(f"Fetching channel info for {channel}...")
        channel_info = await scraper.get_channel_info(channel)
        click.echo(f"Channel: {channel_info.title} (@{channel_info.username})")
        click.echo(f"Members: {channel_info.member_count or 'N/A'}")

        click.echo(f"\nDumping messages from {channel_info.title}...")

        with click.progressbar(length=0, label="Messages dumped") as bar:
            last_count = [0]

            def progress_callback(current, total):
                bar.update(current - last_count[0])
                last_count[0] = current

            count = await scraper.dump_channel(channel, limit=limit, progress_callback=progress_callback)

        click.echo(f"\n✓ Successfully dumped {count} messages")
        await scraper.stop()

    asyncio.run(run_dump())


@cli.command()
@click.argument("channel")
@click.option("--skip-comments", is_flag=True, help="Only sync messages, skip fetching comments")
@click.pass_context
def sync(ctx, channel: str, skip_comments: bool):
    """Sync new messages and their comments from a channel.

    CHANNEL can be a username (e.g., @channelname or channelname) or channel ID.

    By default, this command syncs both new messages and their comments.
    Use --skip-comments to sync only messages.
    """
    config = ctx.obj["config"]

    async def run_sync():
        scraper = Scraper(config)
        await scraper.start()

        click.echo(f"Syncing from {channel}...")

        # Track progress for both phases
        message_last = [0]
        comment_last = [0]
        current_phase = [""]

        def progress_callback(phase, current, total):
            if phase == "messages":
                if current_phase[0] != "messages":
                    click.echo("\nPhase 1: Syncing new messages...")
                    current_phase[0] = "messages"
                if current - message_last[0] >= 10 or current == total:
                    click.echo(f"  {current} new messages synced...")
                    message_last[0] = current
            elif phase == "comments":
                if current_phase[0] != "comments":
                    click.echo(f"\nPhase 2: Fetching comments for {total} new message(s) with replies...")
                    current_phase[0] = "comments"
                if current != comment_last[0]:
                    click.echo(f"  Processing message {current}/{total}...")
                    comment_last[0] = current

        message_count, comment_count = await scraper.sync_messages(
            channel,
            skip_comments=skip_comments,
            progress_callback=progress_callback
        )

        # Display summary
        click.echo("\n" + "=" * 50)
        click.echo("Sync Summary:")
        click.echo(f"  Messages: {message_count} new")
        if not skip_comments:
            click.echo(f"  Comments: {comment_count} new")
        click.echo("=" * 50)

        await scraper.stop()

    asyncio.run(run_sync())


@cli.command(name="dump-comments")
@click.argument("channel")
@click.option("--limit", type=int, help="Number of most recent messages (with comments) to process")
@click.pass_context
def dump_comments(ctx, channel: str, limit: int):
    """Dump comments for channel messages.

    CHANNEL can be a username (e.g., @channelname or channelname) or channel ID.

    This command fetches comments for channel posts that have replies.
    The channel must be dumped first using the 'dump' command.

    Use --limit to process only the most recent N messages with comments.
    For example, --limit 10 will dump comments for the last 10 messages that have comments.
    """
    config = ctx.obj["config"]

    async def run_dump_comments():
        scraper = Scraper(config)
        await scraper.start()

        click.echo(f"Fetching channel info for {channel}...")
        channel_info = await scraper.get_channel_info(channel)

        # Check if channel exists in database
        db_channel = db.get_channel(channel_info.id)
        if not db_channel:
            click.echo(
                f"Error: Channel {channel_info.title} not found in database.\n"
                f"Please run 'telememo dump {channel}' first to download messages."
            )
            await scraper.stop()
            return

        # Get count of messages with replies (limited if specified)
        messages_with_replies = db.get_messages_with_replies(db_channel.id, limit=limit)
        if not messages_with_replies:
            click.echo(f"No messages with comments found in {channel_info.title}")
            await scraper.stop()
            return

        total_messages = len(messages_with_replies)

        click.echo(f"Channel: {channel_info.title} (@{channel_info.username})")
        if limit:
            click.echo(f"Processing last {total_messages} messages with comments")
        else:
            click.echo(f"Processing all {total_messages} messages with comments")
        click.echo(f"\nDumping comments from {channel_info.title}...\n")

        last_count = [0]

        def progress_callback(current, total, message_id, comment_count):
            click.echo(f"  [{current}/{total}] Message ID: {message_id} - {comment_count} comments")
            last_count[0] = current

        count = await scraper.dump_comments(channel, limit=limit, progress_callback=progress_callback)

        click.echo(f"\n✓ Successfully dumped {count} comments")
        await scraper.stop()

    asyncio.run(run_dump_comments())


@cli.command(name="show-message-comments")
@click.argument("channel")
@click.argument("message_id", type=int)
@click.pass_context
def show_message_comments(ctx, channel: str, message_id: int):
    """Show a message and its comments.

    CHANNEL can be a username (e.g., @channelname or channelname) or channel ID.
    MESSAGE_ID is the ID of the message to display with its comments.

    This command fetches and displays a message and all its comments without
    saving to the database. Useful for testing and previewing comment content.
    """
    config = ctx.obj["config"]

    async def run_show_message_comments():
        scraper = Scraper(config)
        await scraper.start()

        try:
            click.echo(f"Fetching message {message_id} from {channel}...")
            message_data, comments = await scraper.get_message_with_comments(channel, message_id)

            # Display message
            click.echo(f"\n{'=' * 80}")
            click.echo(f"MESSAGE ID: {message_data.id}")
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
@click.argument("channel")
@click.pass_context
def info(ctx, channel: str):
    """Show channel information.

    CHANNEL can be a username (e.g., @channelname or channelname) or channel ID.
    """
    config = ctx.obj["config"]

    async def run_info():
        scraper = Scraper(config)
        await scraper.start()

        channel_info = await scraper.get_channel_info(channel)

        click.echo(f"\nChannel Information:")
        click.echo(f"  Title: {channel_info.title}")
        click.echo(f"  Username: @{channel_info.username or 'N/A'}")
        click.echo(f"  ID: {channel_info.id}")
        click.echo(f"  Members: {channel_info.member_count or 'N/A'}")
        if channel_info.description:
            click.echo(f"  Description: {channel_info.description}")

        # Check if channel is in database
        db_channel = db.get_channel(channel_info.id)
        if db_channel:
            message_count = db.get_message_count(db_channel.id)
            comment_count = db.get_comment_count(db_channel.id)
            click.echo(f"\nDatabase Status:")
            click.echo(f"  Messages stored: {message_count}")
            click.echo(f"  Comments stored: {comment_count}")
            click.echo(f"  Last sync: {db_channel.last_sync_at or 'Never'}")
            click.echo(f"  Last message ID: {db_channel.last_sync_message_id or 'N/A'}")
        else:
            click.echo(f"\nDatabase Status: Not synced yet")

        await scraper.stop()

    asyncio.run(run_info())


@cli.command()
@click.argument("query")
@click.option("--channel", help="Limit search to specific channel (username or ID)")
@click.option("--limit", type=int, default=50, help="Maximum number of results")
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
def search(ctx, query: str, channel: str, limit: int, target: str, include_comments: bool):
    """Search messages and/or comments by text content.

    QUERY is the search term to look for.

    Examples:
      telememo search "keyword"                    # Search in messages only
      telememo search "keyword" --target comments  # Search in comments only
      telememo search "keyword" --target all       # Search in both
      telememo search "keyword" --include-comments # Show matching messages with their comments
    """
    config = ctx.obj["config"]

    # Resolve channel ID if channel username provided
    channel_id = None
    if channel:
        if channel.startswith("@"):
            channel = channel[1:]
        db_channel = db.get_channel_by_username(channel)
        if db_channel:
            channel_id = db_channel.id
        else:
            click.echo(f"Channel @{channel} not found in database. Run 'dump' first.")
            return

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
            click.echo(f"  Message ID: {msg.id}")
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


if __name__ == "__main__":
    cli()
