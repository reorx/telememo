# Telememo Development Guidelines

## Application Requirements

Telememo is a Python CLI tool to dump Telegram channel messages to a local SQLite database for easy searching.

### Core Features
- Dump all messages from a Telegram channel to SQLite database
- Provide CLI interface for searching and managing messages
- Use user authentication (via phone number) to access Telegram
- Support incremental message synchronization
- Store channel metadata and message content

### Configuration
The application uses a Python configuration file at `~/.config/telememo/config.py`:
- `TELEGRAM_API_ID`: Telegram API ID (from https://my.telegram.org)
- `TELEGRAM_API_HASH`: Telegram API hash (from https://my.telegram.org)
- `PHONE`: (Optional) Your phone number for authentication
- `DEFAULT_CHANNEL`: (Optional) Default channel to use
- `CHANNELS`: (Optional) Multiple channel configurations

Data files are stored in `~/.local/share/telememo/`:
- `telethon.session`: Global Telegram session file (shared across all channels)
- `channels/<channel_id>/channel.db`: SQLite database for each channel

## Tech Stack

- **Python 3.10+**: Modern Python with async/await support
- **Telethon**: Telegram client library for accessing Telegram API
- **Peewee**: Lightweight SQLite ORM
- **Click**: CLI framework
- **Pydantic**: Data validation and settings management
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

### `config.py`
Configuration and path management:
- Load configuration from `~/.config/telememo/config.py`
- Manage paths for data and session files
- Per-channel directory structure
- XDG Base Directory Specification compliance

### `types.py`
Shared Pydantic models for data validation and type safety:
- `Config`: Application configuration
- `ChannelInfo`: Channel metadata (ID, title, username, description)
- `MessageData`: Message content and metadata (one-to-one with database records)
- `CommentData`: Comment/reply data for messages with discussions
- `MediaItem`: Individual media item in an album
- `ForwardInfo`: Forward source information (channel/user, original date, message ID)
- `DisplayMessage`: Message as displayed to users (grouping albums, with forward info)

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
- `dump_messages()`: Main function to dump all channel messages
- `sync_messages_and_comments()`: Incremental sync for new messages
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

### Message Ingestion (Telegram → Database)
```
Telegram API (Raw Messages)
    ↓
TelegramClient._convert_message_to_data()
    ↓
MessageData (Pydantic)
    ↓
db.save_message() / db.save_messages_batch()
    ↓
Database (Message table)
```

### Message Display (Database → Viewer)
```
Database (Message table)
    ↓
MessageData (from DB query)
    ↓
group_messages_to_display() [groups albums by grouped_id]
    ↓
DisplayMessage (user perspective)
    ↓
Viewer / UI
```

### Overall Flow
```
User -> CLI -> Core (Scraper) -> Telegram API
                  |                     ↓
                  |              Raw Telegram Messages
                  |                     ↓
                  |              MessageData (Pydantic)
                  ↓                     ↓
              Viewer ← DisplayMessage ← DB (SQLite)
```

## Message Types and Conversions

Telememo uses different message representations at different stages of the data pipeline to match the appropriate abstraction level for each layer.

### Message Type Hierarchy

#### 1. **Raw Telegram Messages** (Telethon API objects)
- **Source**: Directly from Telegram API via Telethon
- **Characteristics**:
  - Native Telethon message objects with full API details
  - Album photos/videos are separate messages with the same `grouped_id`
  - Forward information in `fwd_from` attribute
  - Contains all raw API fields and nested objects
- **Usage**: Initial data retrieval, debugging, forward info extraction

#### 2. **MessageData** (Pydantic model, `types.py`)
- **Source**: Converted from raw Telegram messages
- **Characteristics**:
  - One-to-one mapping with database `Message` table records
  - Flattened structure with essential fields only
  - Each album item is a separate MessageData object
  - Stores `grouped_id` for album grouping
  - **Does NOT include forward source info** (limitation to be addressed)
- **Usage**: Data validation, database storage, internal data passing
- **Conversion**: `TelegramClient._convert_message_to_data(raw_message) -> MessageData`

#### 3. **DisplayMessage** (Pydantic model, `types.py`)
- **Source**: Grouped from MessageData objects (or database Message records)
- **Characteristics**:
  - **User perspective**: Represents messages as users see them in Telegram
  - **Album grouping**: Multiple photos/videos grouped into one display unit
  - **Forward information**: Includes `ForwardInfo` with source details
  - Aggregated statistics (max views/forwards, sum replies)
  - Contains list of `MediaItem` objects for albums
- **Usage**: UI rendering, message viewer, user-facing displays
- **Conversion**: `group_messages_to_display(message_dicts, raw_messages_map) -> List[DisplayMessage]`

### Key Differences

| Aspect | Raw Telegram | MessageData | DisplayMessage |
|--------|-------------|-------------|----------------|
| **Abstraction** | API native | Database record | User perspective |
| **Album handling** | Separate messages | Separate records | Grouped as one |
| **Forward info** | Yes (`fwd_from`) | No (not stored) | Yes (`ForwardInfo`) |
| **Data source** | Telegram API | Conversion/DB | Grouping logic |
| **Purpose** | API interaction | Storage layer | Display layer |
| **Count example** | 8 messages (4+2 albums + 2 text) | 8 records | 4 display messages |

### Conversion Functions

#### Telegram API → MessageData
```python
# In telegram.py
async def _convert_message_to_data(self, message: TgMessage) -> MessageData:
    """Convert raw Telegram message to MessageData for storage."""
    # Extracts: id, text, date, sender, views, media_type, grouped_id, etc.
    # Note: Does NOT extract forward information (to be added)
```

#### MessageData → DisplayMessage
```python
# In scripts/debug_messages.py (to be moved to a utility module)
def group_messages_to_display(
    message_dicts: List[Dict],
    raw_messages_map: Dict
) -> List[DisplayMessage]:
    """Group MessageData into DisplayMessages by grouped_id.

    Process:
    1. Group messages by grouped_id (albums)
    2. Keep standalone messages separate
    3. Extract forward info from raw messages
    4. Aggregate statistics (max views/forwards, sum replies)
    5. Create DisplayMessage with MediaItem list
    """
```

#### Extract Forward Info
```python
# In scripts/debug_messages.py (to be moved to telegram.py)
def extract_forward_info(raw_message) -> ForwardInfo | None:
    """Extract forward source information from raw Telegram message.

    Extracts:
    - from_channel_id, from_channel_name
    - from_user_id, from_user_name
    - from_message_id (original message ID)
    - original_date
    - post_author (signature)
    """
```

### Album Message Grouping

When Telegram users send multiple photos/videos together, they appear as a single message with a media grid. However, the API returns each media item as a separate message:

**User sees:** 1 message with 3 photos
**API returns:** 3 messages with same `grouped_id`
**Database stores:** 3 `Message` records with same `grouped_id`
**Viewer displays:** 1 `DisplayMessage` with 3 `MediaItem` objects

### Forward Message Handling

Forwarded messages contain information about the original source:

**Raw message:** `message.fwd_from` attribute with `PeerChannel`, `channel_post`, `date`, etc.
**MessageData:** ⚠️ Forward info NOT currently stored (needs database schema update)
**DisplayMessage:** `ForwardInfo` object with extracted forward details

### Future Improvements

1. **Store forward information in database**:
   - Add forward-related fields to `Message` table
   - Update `MessageData` to include forward info
   - Modify `_convert_message_to_data()` to extract forward info

2. **Move conversion utilities to proper module**:
   - Move `group_messages_to_display()` from debug script to utility module
   - Move `extract_forward_info()` to `telegram.py` or utilities

3. **Enhance viewer to use DisplayMessage**:
   - Update message viewer to group albums
   - Display forward source information
   - Show media grid for albums

## User Authentication

This project uses **user authentication** (not bot authentication) because:
- **Bot API Limitation**: Telegram bots cannot fetch historical messages from channels. They can only receive new messages sent after they join.
- **User authentication** allows full access to channel history using the MTProto API via Telethon.

Authentication flow:
- Use `TelegramClient` with user phone number
- First time: You'll receive a code via Telegram to verify your identity
- Session is saved locally (in `telethon_session.db` file in the channel's data directory) for future use
- You must have access to the channels you want to scrape (either public channels or channels you're a member of)

## Message Storage Strategy

- Store messages incrementally (avoid re-downloading)
- Track last message ID for each channel
- Support message updates/edits
- Include message metadata (date, author, views)
- Enable full-text search on message content
