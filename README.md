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

1. Clone the repository:
```bash
git clone <repository-url>
cd telememo
```

2. Install in development mode:
```bash
pip install -e .
```

For development with testing tools:
```bash
pip install -e ".[dev]"
```

## Configuration

Create a `.env` file in the project root with the following variables:

```env
# Telegram API credentials (get from https://my.telegram.org)
TELEGRAM_API_ID=your_api_id
TELEGRAM_API_HASH=your_api_hash

# Optional: Your phone number (will be prompted if not provided)
# PHONE=+1234567890

# Optional: Database path (default: telememo.db)
# DB_PATH=telememo.db

# Optional: Session name (default: telememo_session)
# SESSION_NAME=telememo_session

# Optional: Test channel for integration tests
# TEST_CHANNEL=telegram
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

Your session will be saved locally (in a `.session` file) so you won't need to authenticate again.

## Usage

### Dump channel messages

Dump all messages from a channel:
```bash
telememo dump @channelname
```

Dump with a limit:
```bash
telememo dump @channelname --limit 100
```

### Sync new messages

Fetch only new messages since last sync:
```bash
telememo sync @channelname
```

### Show channel information

```bash
telememo info @channelname
```

### Search messages

Search across all channels:
```bash
telememo search "search term"
```

Search within a specific channel:
```bash
telememo search "search term" --channel channelname --limit 20
```

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
