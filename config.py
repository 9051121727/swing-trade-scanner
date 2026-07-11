"""
Central configuration for the swing trade scanner.
Values can be overridden via environment variables (useful for GitHub Actions secrets/vars).
"""
import os

# --- Database ---
DATABASE = os.environ.get("MARKET_DB_PATH", "market.db")

# --- Timezone ---
MARKET_TZ = "Asia/Kolkata"

# --- Scanner thresholds ---
RSI_PERIOD = int(os.environ.get("RSI_PERIOD", 14))
RSI_MIN = float(os.environ.get("RSI_MIN", 60))
VOL_MULT_MIN = float(os.environ.get("VOL_MULT_MIN", 1.5))
VOL_LOOKBACK = int(os.environ.get("VOL_LOOKBACK", 20))  # rolling avg volume window

STOP_LOSS_PCT = float(os.environ.get("STOP_LOSS_PCT", 0.0325))   # 3.25% below entry
TARGET_PCT = float(os.environ.get("TARGET_PCT", 0.065))          # 6.5% above entry

CAR_LOOKBACK_DAYS = int(os.environ.get("CAR_LOOKBACK_DAYS", 365))
SCAN_LOOKBACK_DAYS = int(os.environ.get("SCAN_LOOKBACK_DAYS", 90))  # needs to be > RSI_PERIOD + VOL_LOOKBACK + buffer

TOP_N = int(os.environ.get("TOP_N", 5))

# --- Google Sheets ---
GOOGLE_SHEET_ID = os.environ.get("SHEET_ID", "")
GOOGLE_WORKSHEET_NAME = os.environ.get("WORKSHEET_NAME", "Swing Dashboard")
GOOGLE_CREDENTIALS_JSON = os.environ.get("GOOGLE_CREDENTIALS_JSON", "")  # raw JSON string (from GitHub secret)

# --- Telegram ---
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
