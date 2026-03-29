import os

# Bot token — set BOT_TOKEN env var in production
BOT_TOKEN = os.getenv("BOT_TOKEN", "YOUR_TELEGRAM_BOT_TOKEN_HERE")

# Defaults
DEFAULT_CURRENCY = "USD"
AUTO_LOGOUT_MINUTES = 30
REMINDER_HOUR = 20          # 24h format, in user's local time (UTC+3)
REMINDER_MINUTE = 0
TIMEZONE_OFFSET = 3         # UTC+3

# Exchange rate API (free, no key)
EXCHANGE_RATE_API = "https://api.exchangerate.host/latest"