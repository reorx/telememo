# Telememo Configuration File
# Copy this file to ~/.config/telememo/config.py and fill in your values

# Telegram API credentials
# Get these from https://my.telegram.org
TELEGRAM_API_ID = 12345678
TELEGRAM_API_HASH = "your_api_hash_here"

# Your phone number (optional, will be prompted if not set)
# Format: "+1234567890"
PHONE = "+1234567890"

# Default channel to use when -c/--channel-name is not specified
# Can be a username (with or without @) or a numeric channel ID
DEFAULT_CHANNEL = "example_channel"

# Optional: Configure multiple channels with metadata
# This is for your reference and future features
CHANNELS = {
    "tech_news": {
        "id": "@technews",
        "description": "Technology news channel"
    },
    "crypto": {
        "id": -1001234567890,  # Numeric channel ID
        "description": "Crypto updates"
    },
}
