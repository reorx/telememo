"""Configuration and path management for Telememo.

This module handles:
- Loading configuration from ~/.config/telememo/config.py
- Fallback to environment variables
- Path management for data and session files
- Directory creation
"""

import importlib.util
import os
import sys
from pathlib import Path
from typing import Optional

from .types import Config


def get_config_dir() -> Path:
    """Get the configuration directory path.

    Uses XDG_CONFIG_HOME if set, otherwise defaults to ~/.config/telememo/
    """
    if config_home := os.getenv("XDG_CONFIG_HOME"):
        return Path(config_home) / "telememo"
    return Path.home() / ".config" / "telememo"


def get_data_dir() -> Path:
    """Get the data directory path.

    Uses XDG_DATA_HOME if set, otherwise defaults to ~/.local/share/telememo/
    """
    if data_home := os.getenv("XDG_DATA_HOME"):
        return Path(data_home) / "telememo"
    return Path.home() / ".local" / "share" / "telememo"


def get_channel_dir(channel_id: str) -> Path:
    """Get the directory path for a specific channel's data.

    Args:
        channel_id: Channel username or ID

    Returns:
        Path to ~/.local/share/telememo/channels/<channel_id>/
    """
    # Sanitize channel_id to be filesystem-safe
    # Remove @ prefix if present, and replace invalid characters
    clean_id = channel_id.lstrip("@").replace("/", "_").replace("\\", "_")
    return get_data_dir() / "channels" / clean_id


def get_db_path(channel_id: str) -> Path:
    """Get the database file path for a channel.

    Args:
        channel_id: Channel username or ID

    Returns:
        Path to channel.db file
    """
    return get_channel_dir(channel_id) / "channel.db"


def get_session_path(channel_id: str) -> str:
    """Get the session file path for a channel.

    DEPRECATED: Use get_global_session_path() instead.
    This function is kept for backward compatibility only.

    Args:
        channel_id: Channel username or ID

    Returns:
        Path to session file (Telethon won't add .session when name ends with .db)
    """
    # Return as string - Telethon won't add .session extension when name ends with .db
    return str(get_channel_dir(channel_id) / "telethon")


def get_global_session_path() -> str:
    """Get the global session file path for all channels.

    Returns:
        Path to global session file at ~/.local/share/telememo/telethon.session
    """
    return str(get_data_dir() / "telethon.session")


def ensure_config_dir() -> Path:
    """Create the configuration directory if it doesn't exist.

    Returns:
        Path to the config directory
    """
    config_dir = get_config_dir()
    config_dir.mkdir(parents=True, exist_ok=True)
    return config_dir


def ensure_data_dir() -> Path:
    """Create the data directory if it doesn't exist.

    Returns:
        Path to the data directory
    """
    data_dir = get_data_dir()
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir


def ensure_channel_dir(channel_id: str) -> Path:
    """Create the channel data directory if it doesn't exist.

    Args:
        channel_id: Channel username or ID

    Returns:
        Path to the channel directory
    """
    channel_dir = get_channel_dir(channel_id)
    channel_dir.mkdir(parents=True, exist_ok=True)
    return channel_dir


def load_user_config() -> Optional[dict]:
    """Load user configuration from ~/.config/telememo/config.py

    Returns:
        Dictionary with configuration values, or None if file doesn't exist
    """
    config_file = get_config_dir() / "config.py"

    if not config_file.exists():
        return None

    # Load the config.py file as a module
    spec = importlib.util.spec_from_file_location("telememo_user_config", config_file)
    if spec is None or spec.loader is None:
        raise ValueError(f"Cannot load config from {config_file}")

    config_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(config_module)

    # Extract configuration values
    config_dict = {}
    for attr in dir(config_module):
        if not attr.startswith("_"):  # Skip private attributes
            config_dict[attr] = getattr(config_module, attr)

    return config_dict


def get_config() -> Config:
    """Get application configuration.

    Priority order:
    1. ~/.config/telememo/config.py
    2. Environment variables
    3. Default values

    Returns:
        Config object with all configuration

    Raises:
        ValueError: If required configuration is missing
    """
    # Load user config file
    user_config = load_user_config()

    # Get API credentials from config file
    if not user_config or "TELEGRAM_API_ID" not in user_config:
        raise ValueError(
            "Telegram API credentials not found. "
            f"Please create {get_config_dir() / 'config.py'} with your configuration. "
            f"See config.example.py for the template."
        )

    api_id = user_config["TELEGRAM_API_ID"]
    api_hash = user_config["TELEGRAM_API_HASH"]
    phone = user_config.get("PHONE")

    # Legacy fields for Config compatibility (not used in new path system)
    db_path = "telememo.db"
    session_name = "telethon_session.db"

    return Config(
        api_id=int(api_id),
        api_hash=api_hash,
        phone=phone,
        db_path=db_path,
        session_name=session_name,
    )


def get_default_channel() -> Optional[str]:
    """Get the default channel from user configuration.

    Returns:
        Default channel ID/username, or None if not configured
    """
    user_config = load_user_config()
    if user_config:
        return user_config.get("DEFAULT_CHANNEL")
    return None


def list_channels() -> dict:
    """Get all configured channels from user configuration.

    Returns:
        Dictionary of channel configurations, or empty dict if not configured
    """
    user_config = load_user_config()
    if user_config and "CHANNELS" in user_config:
        return user_config["CHANNELS"]
    return {}
