# Telememo

Dumps Telegram channel messages and comments into local SQLite for search and archival. Published to PyPI as `telememo`; the version lives in `telememo/__init__.py`.

It has two entry points that share the same storage and conversion code:

- **CLI** (`cli.py` → `core.Scraper`): interactive login, session kept in a file, one database per channel.
- **Library** (`service.TelegramService`): embedded by the condenser app. Step-by-step login, session passed in and out as a `StringSession` string, one database for all channels, realtime subscription, on-demand media streaming. It never reads telememo's config file.

## Commands

```bash
uv sync --extra dev                 # install, including test tools
uv run pytest                       # Telegram is mocked; needs no credentials
uv run telememo -c <channel> sync   # global options go before the subcommand
```

- Subcommands: `sync`, `dump-messages`, `dump-comments`, `search`, `info`, `viewer`, `show-message-comments`, `session`.
- `tests/test_integration.py` only runs with `ALLOW_LOGIN=1` and logs in to real Telegram. Do not run it unless asked.
- After changing `dependencies` or `[project.scripts]`, re-run `uv tool install --force --editable .`, or the global `telememo` keeps the old snapshot (see README).

## Paths

- Config: `~/.config/telememo/config.py`, template in `config.example.py`. Required: `TELEGRAM_API_ID`, `TELEGRAM_API_HASH`. Optional: `PHONE`, `DEFAULT_CHANNEL`.
- Data: `~/.local/share/telememo/telethon.session` (one session for all channels) and `channels/<channel>/channel.db`.
- Both honour `XDG_CONFIG_HOME` / `XDG_DATA_HOME`.

## Modules

All in `telememo/`, one file per module.

| Module | Role |
|---|---|
| `types.py` | Pydantic models shared across modules |
| `config.py` | Loads the config file, resolves data paths |
| `db.py` | Peewee models (`Channel`, `Message`, `Comment`), column migration, save and search |
| `telegram.py` | `TelegramClient` (Telethon wrapper used by the CLI), raw message → `MessageData`, forward name resolution, session file diagnostics |
| `core.py` | `Scraper`: dump, sync and comment fetching for the CLI |
| `service.py` | `TelegramService`: the facade for embedding applications |
| `entity_cache.py` | JSON cache of channel/user id → name, for forward sources |
| `utils.py` | Forward info extraction, grouping rows into `DisplayMessage` |
| `viewer.py` | Rich TUI for browsing messages and comments |
| `cli.py` | Click commands; `main()` turns known setup failures into messages |
| `color.py` | ANSI color helpers |

`scripts/debug_messages.py` prints raw Telethon messages next to their converted forms.

## Rules

### Data

- Messages are keyed by `(channel, id)` and comments by `(parent_channel, parent_message_id, id)`. The models have no single primary key, so `instance.save()` does not work: write with `Model.update(...).where(...)`.
- A new `Message` column must be added in all of: `db.Message`, `types.MessageData`, `db._message_row` (shared by insert and update), `telegram.convert_message_to_data`, and the row dicts in `service._message_data_to_row` and `viewer.load_messages`. `init_db` adds the column to existing databases; only `sync --full` fills it for existing rows.
- An embedder can declare extension columns through `init_db(optional_fields=...)`. They are not in the Peewee models and telememo's writes must never touch them.
- `save_message_smart` rewrites an existing row only when `edit_date` changed. `force=True` (used by `sync --full` and `dump-messages`) rewrites unconditionally.
- An album is several rows sharing `grouped_id`. The caption and the `replies` counter may sit on any row of the group.
- Search is a substring `LIKE`; there is no full-text index.

### Telegram

- User authentication only. Bots cannot read channel history.
- The session file's schema is tied to the Telethon version (1.44+ writes schema v8, which older versions cannot open). Never point an older Telethon at the shared session file. `telememo session` reports the state without logging in.
- The realtime handler resolves forward names from the cache only (`allow_network=False`). Only backfill may call `get_entity`, because only backfill retries on FloodWait.

### Code

- Keep the package flat: one file per module, no new abstraction layers.
- Low-level functions raise; errors are handled in the CLI layer. The one sanctioned exception is `FloodWaitError` backoff in `service.py`.
- Models used by more than one module go in `types.py`. Use type hints.
- Do not run formatters or linters after edits.

### Tests

- Test whole workflows against real SQLite (`:memory:` or a temp file) and mock only Telethon. Write narrow unit tests only when asked.
- Tests must never touch the real session file or the network.

## Documentation

- `kb/docs/message-pipeline.md` — the three message forms (raw, stored, displayed), album merging, where forward names come from, the three sync modes, what the embedding service adds. Read it before changing ingest, sync, or display grouping.
- `kb/known-issues.md` — open defects and leftovers. Check it before building on an existing CLI command or the viewer, and update it when you find or fix a problem.
- `kb/todo.md` — the user's backlog of ideas.
