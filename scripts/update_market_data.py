"""
Daily incremental market data updater using yfinance.

For every symbol already tracked in price_history, this pulls any new daily
bars since that symbol's last stored date and appends them. Safe to run
repeatedly -- it only ever adds rows for (symbol, date) pairs it doesn't
already have.

Usage:
    python scripts/update_market_data.py
"""
import sqlite3
import sys
import time
from pathlib import Path
from datetime import datetime, timedelta, date
from zoneinfo import ZoneInfo

import pandas as pd
import yfinance as yf

# Ensure the repo root (parent of this scripts/ folder) is importable,
# regardless of the working directory this script is launched from.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config

MARKET_ZONE = ZoneInfo(config.MARKET_TZ)
YF_SUFFIX = ".NS"       # NSE suffix for Yahoo Finance tickers
BATCH_SIZE = 50         # tickers per yfinance request, to stay well under rate limits
BATCH_PAUSE_SECONDS = 2


def get_tracked_symbols_and_last_dates(conn) -> dict:
    """Returns {symbol: last_trade_date_str} for everything already in price_history."""
    df = pd.read_sql_query(
        "SELECT symbol, MAX(trade_date) AS last_date FROM price_history GROUP BY symbol",
        conn,
    )
    return dict(zip(df["symbol"], df["last_date"]))


def _chunk(items, size):
    items = list(items)
    for i in range(0, len(items), size):
        yield items[i:i + size]


def _extract_symbol_frame(data: pd.DataFrame, yf_symbol: str, single_ticker: bool) -> pd.DataFrame:
    if single_ticker:
        return data
    if isinstance(data.columns, pd.MultiIndex) and yf_symbol in data.columns.levels[0]:
        return data[yf_symbol]
    return pd.DataFrame()


def fetch_and_update(conn, symbols_last: dict, today: date) -> int:
    if not symbols_last:
        print("No symbols found in price_history -- nothing to update.")
        return 0

    oldest_last_date = min(symbols_last.values())
    start = datetime.strptime(oldest_last_date, "%Y-%m-%d %H:%M:%S").date() + timedelta(days=1)
    end = today + timedelta(days=1)  # yfinance's `end` is exclusive

    if start >= end:
        print("All symbols already up to date.")
        return 0

    print(f"Downloading up to {len(symbols_last)} tickers, {start} -> {today} ...")

    rows_added = 0
    cur = conn.cursor()
    symbols = list(symbols_last.keys())

    for batch_num, batch_symbols in enumerate(_chunk(symbols, BATCH_SIZE), start=1):
        tickers = [f"{sym}{YF_SUFFIX}" for sym in batch_symbols]
        single_ticker = len(tickers) == 1
        print(f"  Batch {batch_num}: {len(tickers)} tickers")

        try:
            data = yf.download(
                tickers=tickers,
                start=start.isoformat(),
                end=end.isoformat(),
                group_by="ticker",
                auto_adjust=False,
                threads=True,
                progress=False,
            )
        except Exception as e:
            print(f"    Batch download failed: {e} -- skipping this batch")
            continue

        for symbol in batch_symbols:
            yf_symbol = f"{symbol}{YF_SUFFIX}"
            sym_df = _extract_symbol_frame(data, yf_symbol, single_ticker)

            if sym_df is None or sym_df.empty or "Close" not in sym_df.columns:
                continue

            sym_df = sym_df.dropna(subset=["Close"])
            last_date = datetime.strptime(symbols_last[symbol], "%Y-%m-%d %H:%M:%S").date()

            for idx, row in sym_df.iterrows():
                trade_date = idx.date() if hasattr(idx, "date") else idx
                if trade_date <= last_date:
                    continue
                try:
                    cur.execute(
                        """INSERT INTO price_history
                           (symbol, trade_date, open, high, low, close, volume)
                           VALUES (?, ?, ?, ?, ?, ?, ?)""",
                        (
                            symbol,
                            trade_date.strftime("%Y-%m-%d 00:00:00"),
                            float(row["Open"]),
                            float(row["High"]),
                            float(row["Low"]),
                            float(row["Close"]),
                            int(row["Volume"]) if pd.notna(row["Volume"]) else 0,
                        ),
                    )
                    rows_added += 1
                except Exception as e:
                    print(f"    {symbol} {trade_date}: insert failed ({e})")

        conn.commit()
        if batch_num * BATCH_SIZE < len(symbols):
            time.sleep(BATCH_PAUSE_SECONDS)

    return rows_added


def main():
    today = datetime.now(MARKET_ZONE).date()
    conn = sqlite3.connect(config.DATABASE)
    # Ensure the price_history table exists before doing anything else
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS price_history (
            symbol TEXT,
            trade_date TEXT,
            open REAL,
            high REAL,
            low REAL,
            close REAL,
            volume INTEGER,
            PRIMARY KEY (symbol, trade_date)
        )
    """)
    conn.commit()
    try:
        symbols_last = get_tracked_symbols_and_last_dates(conn)
        rows_added = fetch_and_update(conn, symbols_last, today)
        print(f"Done. {rows_added} new row(s) added across {len(symbols_last)} symbols.")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
