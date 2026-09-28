# Telememo

Telememo dumps Telegram channel messages and their comments to a local SQLite database for searching and archival. It works as a CLI, and as a Python library you can embed in a long-running application.

## Features

- Dump a channel's full history, then keep it up to date with incremental sync
- Comments from the channel's linked discussion group
- Edits are picked up on sync; unchanged rows are left alone
- Forward source, link preview and media dimensions stored with each message
- Albums (several photos/videos sent together) shown as one message
- Search messages and comments by text
- Terminal viewer for browsing messages and comments
- Session diagnostics that never trigger a login code
- Library API with step-by-step login, history backfill, realtime subscription and on-demand media streaming

Media files are not downloaded; only their type and dimensions are recorded.

## Requirements

- Python 3.10 or higher
- Telegram API credentials (API ID and API hash from https://my.telegram.org)
- Your Telegram account (phone number) for authentication

## Installation

Install from PyPI:
```bash
pip install telememo
```

Or as an isolated CLI tool with [uv](https://docs.astral.sh/uv/):
```bash
uv tool install telememo
```

### From source (development)

1. Clone the repository:
```bash
git clone https://github.com/reorx/telememo
cd telememo
```

2. Install dependencies, including the test tools:
```bash
uv sync --extra dev
```

3. Point the global `telememo` command at your checkout, so the CLI you use day
   to day is the code you are editing:
```bash
uv tool install --force --editable .
```

**Re-run step 3 after changing `[project.scripts]` or `dependencies` in
`pyproject.toml`.** Editable mode keeps *source* changes live, but the console
script and the resolved dependencies are snapshots taken at install time. Skip
it and the global `telememo` silently keeps the old entry point — or an old
Telethon, while `uv run telememo` inside the repo uses the new one. Two Telethon
versions sharing one session file is how you get
`ValueError: too many values to unpack`: the newer one upgrades
`~/.local/share/telememo/telethon.session` to a schema the older one cannot
read. `telememo session` diagnoses exactly that.

## Configuration

Create a configuration file at `~/.config/telememo/config.py`:

```bash
mkdir -p ~/.config/telememo
cp config.example.py ~/.config/telememo/config.py
```

Edit `~/.config/telememo/config.py` with your credentials:

```python
# Telegram API credentials (get from https://my.telegram.org)
TELEGRAM_API_ID = 12345678
TELEGRAM_API_HASH = "your_api_hash_here"

# Your phone number (optional, will be prompted if not set)
PHONE = "+1234567890"

# Default channel to use when -c/--channel-name is not specified
DEFAULT_CHANNEL = "example_channel"
```

The configuration file is the only source of settings; environment variables are
not read.

### Getting Telegram API Credentials

1. Visit https://my.telegram.org
2. Log in with your phone number
3. Go to "API development tools"
4. Create a new application
5. Copy your `api_id` and `api_hash`

### Authentication

**Important**: Telememo uses **user authentication**, not bot authentication, because Telegram bots cannot access historical channel messages.

When you run the CLI for the first time, you'll be prompted to:
1. Enter your phone number (in international format, e.g., +1234567890)
2. Enter the verification code sent to your Telegram app
3. Optionally enter your 2FA password if enabled

Your session will be saved locally in `~/.local/share/telememo/telethon.session` so you won't need to authenticate again. This session file is shared across all channels.

If commands start failing with an authentication or session error, run `telememo session` (see [Check session status](#check-session-status)) to find out which of the two causes it is.

### Where data is stored

| Path | Content |
|---|---|
| `~/.config/telememo/config.py` | Configuration |
| `~/.local/share/telememo/telethon.session` | Telegram session, shared by all channels |
| `~/.local/share/telememo/channels/<channel>/channel.db` | One SQLite database per channel |

`XDG_CONFIG_HOME` and `XDG_DATA_HOME` are honoured.

## Usage

Global options go **before** the subcommand:

```bash
telememo [-c CHANNEL] [--debug] [--reset-db] <command> [options]
```

Without `-c`, `DEFAULT_CHANNEL` from the configuration is used.

| Command | What it does |
|---|---|
| `sync` | Fetch new messages and comments, pick up edits |
| `dump-messages` | One-off dump of channel messages |
| `dump-comments` | One-off dump of comments for stored messages |
| `search` | Search stored messages or comments |
| `info` | Show channel information and what is stored locally |
| `viewer` | Browse messages and comments in the terminal |
| `show-message-comments` | Fetch one message with its comments, without storing them |
| `session` | Diagnose the Telegram session |

### Sync

```bash
telememo -c @channelname sync
```

`sync` is the command for everyday use. It fetches messages newer than the last
sync. When there are none, it re-fetches the latest 100 messages instead, to
pick up edits. A stored message is rewritten only when its edit date changed.
Comments are fetched for new messages and for messages whose reply count
changed.

| Option | Effect |
|---|---|
| `--skip-comments` | Sync messages only |
| `--limit N` | How many recent messages to re-fetch when there is nothing new (default 100) |
| `--full` | Re-fetch the whole channel and overwrite all data columns of stored rows |

Run `sync --full` once if your database was created before columns like
`webpage` (link preview) or `fwd_*` (forward source) were added. The columns are
added automatically when the database is opened, and the full sync fills them:

```bash
telememo -c @channelname sync --full
```

### Dump

Dump all messages of a channel, or only the latest N:
```bash
telememo -c @channelname dump-messages
telememo -c @channelname dump-messages --limit 100
```

Dump comments for the messages already stored (the channel needs a linked
discussion group). `--limit` restricts it to the latest N messages that have
comments:
```bash
telememo -c @channelname dump-comments --limit 10
```

### Search

Search is a substring match on the text.

```bash
telememo -c @channelname search "keyword" --limit 20
telememo -c @channelname search "keyword" --comments           # search comments instead
telememo -c @channelname search "keyword" --include-comments   # show matching messages with their comments
```

### Show channel information

```bash
telememo -c @channelname info
```

### Viewer

```bash
telememo -c @channelname viewer
```

| Key | Action |
|---|---|
| `↑` `↓` or `j` `k` | Previous / next message |
| `←` `→` or `h` `l` | Previous / next page |
| `Tab` | Switch focus between the message list and the content |
| `Esc` or `q` | Quit |

The viewer reads from the local database but also connects to Telegram, so it
needs a working session.

### Check session status

```bash
telememo session
```

Reports the session file, its schema version, and whether Telegram still honours
the stored login. It connects but never logs in, so running it never sends you a
verification code.

Use it to tell apart the two independent ways a session stops working — they look
the same from the outside but have opposite fixes:

| Output | Meaning | Fix |
|---|---|---|
| `Compatible: NO` | The file was written by a newer Telethon than the one installed, which can only *upgrade* an older schema | Upgrade Telethon (`uv sync`, or `uv tool upgrade telememo`) |
| `Authorized: NO` | Telegram revoked the session (terminated from another device, or long inactivity) | Run `telememo sync` and log in again |

Exits non-zero when either check fails, so it works in a health check.

## Use as a library

`telememo.service.TelegramService` is a facade for applications that stay
connected: it logs in step by step instead of prompting, takes and returns the
session as a string, and does not read `~/.config/telememo/config.py`.

```python
from telememo import db
from telememo.service import TelegramService

db.init_db('app.db')  # one database for all channels

async def on_message(message):  # a DisplayMessage; called for new and edited messages
    print(message.id, message.text)

async with TelegramService(api_id, api_hash, session=saved_session) as service:
    if not service.is_authorized:
        code_hash = await service.send_code(phone)
        result = await service.sign_in_code(phone, code, code_hash)
        if result.status == '2fa_required':
            result = await service.sign_in_2fa(password)
        saved_session = result.session  # store it, encrypted, on your side

    channel = await service.resolve_channel('@channelname')
    async for message in service.backfill('@channelname', since_days=7):
        ...
    await service.subscribe([channel.id], on_message=on_message)
```

Also available: `get_media()` and `get_channel_photo()` stream media from
Telegram on demand without writing to disk, and
`db.init_db(path, optional_fields=...)` lets the application add its own columns
to telememo's tables, which telememo never overwrites.

## Project Structure

```
telememo/
├── telememo/
│   ├── cli.py           # CLI commands (Click)
│   ├── core.py          # Scraper: dump and sync for the CLI
│   ├── service.py       # TelegramService: facade for embedding
│   ├── telegram.py      # Telethon wrapper, message conversion, session checks
│   ├── db.py            # Peewee models and database operations
│   ├── types.py         # Pydantic data models
│   ├── utils.py         # Forward info, album grouping
│   ├── entity_cache.py  # Name cache for forward sources
│   ├── viewer.py        # Terminal viewer (Rich)
│   ├── config.py        # Configuration and paths
│   └── color.py         # Terminal colors
├── scripts/             # Debugging helpers
├── tests/
├── kb/                  # Docs, known issues, backlog
├── AGENTS.md            # Development guidelines
└── pyproject.toml
```

## Development

### Running Tests

```bash
uv run pytest
```

Telegram is mocked in these tests, so they need no credentials and no network.

`tests/test_integration.py` talks to the real Telegram API with the credentials
from your configuration file, and is skipped unless you opt in:

```bash
ALLOW_LOGIN=1 uv run pytest tests/test_integration.py
```

### Development Guidelines

See [AGENTS.md](AGENTS.md) for the module map and the rules to follow, and
[kb/docs/message-pipeline.md](kb/docs/message-pipeline.md) (in Chinese) for how
messages are stored, synced and displayed.

## Tech Stack

- **Telethon**: Telegram MTProto API client
- **Peewee**: Lightweight SQLite ORM
- **Click**: CLI framework
- **Pydantic**: Data validation
- **Rich** and **readchar**: Terminal viewer
- **pytest**: Testing framework

## License

MIT

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.
