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
@click.pass_context
def sync(ctx, channel: str):
    """Sync new messages from a channel.

    CHANNEL can be a username (e.g., @channelname or channelname) or channel ID.
    """
    config = ctx.obj["config"]

    async def run_sync():
        scraper = Scraper(config)
        await scraper.start()

        click.echo(f"Syncing messages from {channel}...")

        last_count = [0]

        def progress_callback(count):
            if count - last_count[0] >= 10:
                click.echo(f"  {count} new messages synced...")
                last_count[0] = count

        count = await scraper.sync_messages(channel, progress_callback=progress_callback)
        click.echo(f"✓ Synced {count} new messages")

        await scraper.stop()

    asyncio.run(run_sync())


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
            click.echo(f"\nDatabase Status:")
            click.echo(f"  Messages stored: {db.get_message_count(db_channel.id)}")
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
@click.pass_context
def search(ctx, query: str, channel: str, limit: int):
    """Search messages by text content.

    QUERY is the search term to look for in messages.
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

    results = db.search_messages(query, channel_id=channel_id, limit=limit)

    if not results:
        click.echo(f"No messages found matching '{query}'")
        return

    click.echo(f"Found {len(results)} message(s) matching '{query}':\n")

    for msg in results:
        channel = db.get_channel(msg.channel.id)
        click.echo(f"[{msg.date}] {channel.title} (@{channel.username})")
        click.echo(f"  ID: {msg.id}")
        if msg.sender_name:
            click.echo(f"  From: {msg.sender_name}")

        # Display message text (truncate if too long)
        text = msg.text or ""
        if len(text) > 200:
            text = text[:200] + "..."
        click.echo(f"  {text}")

        if msg.views:
            click.echo(f"  Views: {msg.views}")
        click.echo()


if __name__ == "__main__":
    cli()
