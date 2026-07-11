"""
Sends swing scan alerts to a Telegram chat via a bot.

Setup:
1. Message @BotFather on Telegram, send /newbot, follow the prompts.
   You'll get a bot token like: 123456789:AAExampleTokenHere
2. Start a chat with your new bot (search its username, send it any message)
   -- bots can't message you first, so this step is required once.
3. Get your chat ID: open this URL in a browser (after step 2):
       https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates
   Look for "chat":{"id": ...} in the JSON response -- that number is your
   TELEGRAM_CHAT_ID. (For a group chat, add the bot to the group first,
   send a message in the group, then check the same URL.)
4. Store both as env vars / GitHub secrets: TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
"""
import sys
from pathlib import Path

import requests

# Ensure the repo root is importable even if this file is run directly
# (e.g. via an editor's "Run" button) instead of imported by another script.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config

TELEGRAM_API_BASE = "https://api.telegram.org"


def _format_message(setups: list[dict]) -> str:
    lines = ["*Swing Scan Alert*", ""]
    for s in setups:
        lines.append(
            f"*{s['Symbol']}*\n"
            f"Entry: {s['Entry']}  |  RSI: {s['RSI']}  |  Vol x{s['VolSpike']}\n"
            f"Stop: {s['StopLoss']}  |  Target: {s['Target']}\n"
            f"CAR: {s['CAR_Status']}"
        )
        lines.append("")
    return "\n".join(lines).strip()


def send_telegram_alert(setups: list[dict]) -> None:
    """
    Sends one message containing all of today's setups to the configured
    Telegram chat. Raises on failure (auth issues, bad chat id, etc.) so
    the caller can decide how to handle it.
    """
    if not config.TELEGRAM_BOT_TOKEN:
        raise RuntimeError(
            "TELEGRAM_BOT_TOKEN is not set. Add your bot token as a GitHub secret "
            "(or env var locally) before running."
        )
    if not config.TELEGRAM_CHAT_ID:
        raise RuntimeError(
            "TELEGRAM_CHAT_ID is not set. Add your chat id as a GitHub secret "
            "(or env var locally) before running."
        )
    if not setups:
        return

    text = _format_message(setups)
    url = f"{TELEGRAM_API_BASE}/bot{config.TELEGRAM_BOT_TOKEN}/sendMessage"

    resp = requests.post(
        url,
        json={
            "chat_id": config.TELEGRAM_CHAT_ID,
            "text": text,
            "parse_mode": "Markdown",
        },
        timeout=15,
    )

    if not resp.ok:
        raise RuntimeError(f"Telegram API error {resp.status_code}: {resp.text}")

    payload = resp.json()
    if not payload.get("ok"):
        raise RuntimeError(f"Telegram API returned failure: {payload}")

    print(f"Sent Telegram alert for {len(setups)} setup(s).")
