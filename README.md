# Telememo

Telememo is a Python CLI tool to dump Telegram channel messages to a local SQLite database for easy searching and archival.

## Features

- Dump all messages from Telegram channels to SQLite
- Search messages by text content
- Incremental sync to fetch only new messages
- Built with modern Python async/await
- Lightweight and easy to use

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

# Optional: Configure multiple channels
CHANNELS = {
    "tech_news": {
        "id": "@technews",
        "description": "Technology news channel"
    },
}
```

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

## Usage

### Dump channel messages

Dump all messages from a channel:
```bash
telememo -c @channelname dump-messages
```

Or use the default channel from config:
```bash
telememo dump-messages
```

Dump with a limit:
```bash
telememo -c @channelname dump-messages --limit 100
```

### Sync new messages

Fetch only new messages since last sync:
```bash
telememo -c @channelname sync
```

Full sync re-fetches all messages and overwrites all data columns of existing
rows. If your database was created before columns like `webpage` (link preview)
or `fwd_*` (forward source) were added, run it once to backfill them:
```bash
telememo -c @channelname sync --full
```

### Show channel information

```bash
telememo -c @channelname info
```

### Search messages

Search within a specific channel:
```bash
telememo -c @channelname search "search term" --limit 20
```

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

## Project Structure

```
telememo/
├── telememo/
│   ├── __init__.py
│   ├── types.py      # Pydantic data models
│   ├── db.py         # Database operations (Peewee ORM)
│   ├── telegram.py   # Telegram client wrapper (Telethon)
│   ├── core.py       # Business logic & scraper
│   └── cli.py        # CLI commands (Click)
├── tests/
│   ├── conftest.py
│   └── test_integration.py
├── pyproject.toml
├── claude.md
└── README.md
```

## Development

### Running Tests

Run integration tests:
```bash
pytest tests/
```

Run with verbose output:
```bash
pytest -v tests/
```

Run specific test:
```bash
pytest tests/test_integration.py::test_get_channel_info_and_messages -v
```

### Development Guidelines

See [claude.md](claude.md) for detailed development guidelines and architecture principles.

## Tech Stack

- **Telethon**: Telegram MTProto API client
- **Peewee**: Lightweight SQLite ORM
- **Click**: CLI framework
- **Pydantic**: Data validation
- **pytest**: Testing framework

## License

MIT

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.
