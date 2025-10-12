# Telememo Development Guidelines

## Application Requirements

Telememo is a Python CLI tool to dump Telegram channel messages to a local SQLite database for easy searching.

### Core Features
- Dump all messages from a Telegram channel to SQLite database
- Provide CLI interface for searching and managing messages
- Use user authentication (via phone number) to access Telegram
- Support incremental message synchronization
- Store channel metadata and message content

### Environment Variables
The application uses the following environment variables from `.env`:
- `TELEGRAM_API_ID`: Telegram API ID (from https://my.telegram.org)
- `TELEGRAM_API_HASH`: Telegram API hash (from https://my.telegram.org)
- `PHONE`: (Optional) Your phone number for authentication

## Tech Stack

- **Python 3.10+**: Modern Python with async/await support
- **Telethon**: Telegram client library for accessing Telegram API
- **Peewee**: Lightweight SQLite ORM
- **Click**: CLI framework
- **Pydantic**: Data validation and settings management
- **python-dotenv**: Environment variable management
- **cryptg**: Performance optimization for Telethon

## Architecture Principles

### Lightweight Design
- Keep each module as a single file for simplicity
- Avoid unnecessary abstractions
- Prefer flat structure over nested directories
- Only add complexity when absolutely necessary

### Function Design
- Each low-level function should perform a single, atomic task
- Functions should be testable in isolation
- Encapsulate lengthy code blocks (in try, for, while) into separate functions
- Use clear, descriptive function names

### Error Handling
- **Minimize try-except usage**: Only handle errors in top-level functions
- **Low-level functions**: Should raise exceptions, not catch them
- **CLI layer**: Provide user-friendly error messages
- **Core/business logic**: Let exceptions bubble up

### Code Style
- **No formatters or linters** should be run automatically after code edits
- Follow PEP 8 conventions naturally
- Use type hints for function parameters and return values
- Keep functions short and focused

## Module Responsibilities

### `types.py`
Shared Pydantic models for data validation and type safety:
- `ChannelInfo`: Channel metadata (ID, title, username, description)
- `MessageData`: Message content and metadata
- `Config`: Application configuration

### `db.py`
Database operations using Peewee ORM:
- `Channel` model: Store channel information
- `Message` model: Store message content with full-text search
- Database initialization and connection management
- CRUD operations for channels and messages
- Search functionality for messages

### `telegram.py`
Telegram client wrapper using Telethon:
- `TelegramClient` class wrapping Telethon functionality
- Authentication using user credentials (phone number + code)
- Fetch channel information
- Fetch message history (with pagination)
- Session management
- Handle Telegram API rate limits

### `core.py`
Business logic coordinating telegram and db modules:
- `Scraper` class coordinating operations
- `dump_channel()`: Main function to dump all channel messages
- `sync_messages()`: Incremental sync for new messages
- Process messages and store in database
- Handle message updates and edits

### `cli.py`
Command-line interface using Click:
- `dump`: Dump channel messages to database
- `search`: Search messages by keyword
- `info`: Show channel information
- `sync`: Sync new messages from channel
- User-friendly error messages
- Progress indicators for long operations

## Testing Strategy

### Integration Tests First
- Focus on integration tests that test complete workflows
- Test real interactions between modules
- Use actual SQLite database (in-memory or temporary file)
- Mock only external services (Telegram API)

### Unit Tests Only When Requested
- Don't write unit tests unless explicitly asked
- Integration tests provide better confidence
- Unit tests for specific edge cases or complex logic

### First Integration Test
The first test should verify:
1. Getting channel information using user authentication
2. Fetching the 3 latest messages from a channel
3. Storing messages in the database

### Test Structure
```python
# tests/conftest.py - Setup fixtures
# tests/test_integration.py - Integration tests
```

## Development Workflow

1. **Start with types**: Define Pydantic models first
2. **Database layer**: Implement Peewee models and operations
3. **Telegram layer**: Implement Telethon client wrapper
4. **Core logic**: Coordinate telegram and database
5. **CLI**: Add user-facing commands
6. **Tests**: Write integration tests for each feature

## Data Flow

```
User -> CLI -> Core -> Telegram API
                  |
                  v
                 DB (SQLite)
```

## User Authentication

This project uses **user authentication** (not bot authentication) because:
- **Bot API Limitation**: Telegram bots cannot fetch historical messages from channels. They can only receive new messages sent after they join.
- **User authentication** allows full access to channel history using the MTProto API via Telethon.

Authentication flow:
- Use `TelegramClient` with user phone number
- First time: You'll receive a code via Telegram to verify your identity
- Session is saved locally (in `.session` file) for future use
- You must have access to the channels you want to scrape (either public channels or channels you're a member of)

## Message Storage Strategy

- Store messages incrementally (avoid re-downloading)
- Track last message ID for each channel
- Support message updates/edits
- Include message metadata (date, author, views)
- Enable full-text search on message content
