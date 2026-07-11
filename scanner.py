import sqlite3
import sys
import pandas as pd
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import config
from utils.sheets_logger import update_swing_dashboard
from utils.telegram_notifier import send_telegram_alert

MARKET_ZONE = ZoneInfo(config.MARKET_TZ)


# ---------------------------------------------------------------------------
# Technical indicator helpers
# ---------------------------------------------------------------------------

def calculate_rsi(closes: pd.Series, period: int = config.RSI_PERIOD) -> float:
    """
    Wilder's RSI, computed from a close-price series ordered oldest -> newest.
    Returns NaN if there isn't enough history.
    """
    if len(closes) < period + 1:
        return float("nan")

    delta = closes.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)

    # Wilder smoothing = EWM with alpha = 1/period, no adjustment
    avg_gain = gain.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()

    rs = avg_gain / avg_loss.replace(0, float("nan"))
    rsi = 100 - (100 / (1 + rs))

    latest = rsi.iloc[-1]
    if pd.isna(latest):
        # avg_loss was 0 -> price only went up -> RSI is 100
        return 100.0 if avg_gain.iloc[-1] > 0 else float("nan")
    return round(float(latest), 2)


def calculate_volume_multiple(volumes: pd.Series, lookback: int = config.VOL_LOOKBACK) -> float:
    """
    Today's volume vs the average volume of the prior `lookback` sessions
    (today excluded from the baseline average).
    """
    if len(volumes) < lookback + 1:
        return float("nan")

    today_vol = float(volumes.iloc[-1])
    baseline = volumes.iloc[-(lookback + 1):-1]
    avg_vol = baseline.mean()

    if not avg_vol or pd.isna(avg_vol) or avg_vol == 0:
        return float("nan")

    return round(today_vol / avg_vol, 2)


# ---------------------------------------------------------------------------
# Cumulative Average Rule (CAR)
# ---------------------------------------------------------------------------

def calculate_car_status(symbol: str, today_ist: datetime) -> str:
    """
    Computes the Cumulative Average Rule mathematically via database lookups.
    Finds the 52-week high, computes expanding averages, and tracks the 10-day slope.
    Anchored strictly to Indian Standard Time (IST).
    """
    start_date_ist = (today_ist - timedelta(days=config.CAR_LOOKBACK_DAYS)).strftime('%Y-%m-%d 00:00:00')

    conn = sqlite3.connect(config.DATABASE)
    try:
        df = pd.read_sql_query("""
            SELECT trade_date, open, high, low, close, volume
            FROM price_history
            WHERE symbol = ? AND trade_date >= ?
            ORDER BY trade_date ASC
        """, conn, params=(symbol, start_date_ist))
    except Exception as e:
        print(f"CAR processing error for {symbol}: {e}")
        return "ERROR"
    finally:
        conn.close()

    if len(df) < 20:
        return "Short History"

    idx_52w_high = df['high'].idxmax()
    post_high_df = df.loc[idx_52w_high:].copy()

    if len(post_high_df) < 10:
        return "Avoid/Hold"

    post_high_df['cum_avg'] = post_high_df['close'].expanding().mean()
    last_10_averages = post_high_df['cum_avg'].tail(10).values

    is_rising_consistently = all(
        last_10_averages[i] > last_10_averages[i - 1] for i in range(1, 10)
    )

    return "Buy/Average Out" if is_rising_consistently else "Avoid/Hold"


# ---------------------------------------------------------------------------
# Scanner
# ---------------------------------------------------------------------------

def run_early_breakout_swing_scanner():
    print("\n" + "=" * 60)
    print("RUNNING SWING SCANNER W/ CUMULATIVE AVERAGE RULE (CAR)")
    print("=" * 60)

    today_ist = datetime.now(MARKET_ZONE)
    lookback_date_ist = (today_ist - timedelta(days=config.SCAN_LOOKBACK_DAYS)).strftime('%Y-%m-%d 00:00:00')

    conn = sqlite3.connect(config.DATABASE)
    try:
        df_pool = pd.read_sql_query("""
            SELECT symbol, trade_date, open, high, low, close, volume
            FROM price_history
            WHERE trade_date >= ?
            ORDER BY symbol ASC, trade_date ASC
        """, conn, params=(lookback_date_ist,))
    finally:
        conn.close()

    if df_pool.empty:
        print("No price data found in the lookback window. Check that market.db is populated.")
        return []

    df_pool.columns = [col.lower() for col in df_pool.columns]

    min_rows_needed = config.RSI_PERIOD + 1
    valid_setups = []

    for symbol, group in df_pool.groupby('symbol'):
        if len(group) < min_rows_needed:
            continue

        group = group.sort_values('trade_date')
        latest_bar = group.iloc[-1]
        close = float(latest_bar['close'])
        symbol_upper = str(symbol).upper()

        # --- Real technical filters ---
        rsi_val = calculate_rsi(group['close'])
        vol_mult = calculate_volume_multiple(group['volume'])

        if pd.isna(rsi_val) or pd.isna(vol_mult):
            continue

        is_breakout_setup = rsi_val >= config.RSI_MIN and vol_mult >= config.VOL_MULT_MIN

        if not is_breakout_setup:
            continue

        # Cross-verify with the macro CAR filter
        car_rating = calculate_car_status(symbol_upper, today_ist)

        if car_rating != "Buy/Average Out":
            continue

        stop_loss = round(close * (1 - config.STOP_LOSS_PCT), 2)
        target = round(close * (1 + config.TARGET_PCT), 2)
        today_formatted = today_ist.strftime('%Y-%m-%d')

        valid_setups.append({
            "ScanDate": today_formatted,
            "Symbol": symbol_upper,
            "Entry": round(close, 2),
            "StopLoss": stop_loss,
            "Target": target,
            "RSI": rsi_val,
            "VolSpike": vol_mult,
            "CAR_Status": car_rating,
        })

    top_setups = sorted(valid_setups, key=lambda x: x['RSI'], reverse=True)[:config.TOP_N]
    print(f"Filter complete. Found {len(top_setups)} high-probability breakout setups "
          f"(out of {len(valid_setups)} that cleared CAR).")
    return top_setups


def main():
    setups = run_early_breakout_swing_scanner()

    for s in setups:
        print(f"{s['Symbol']} | Entry: {s['Entry']} | RSI: {s['RSI']} | "
              f"Vol x{s['VolSpike']} | CAR: {s['CAR_Status']} -> Target: {s['Target']}")

    if setups:
        sheets_failed = False
        try:
            update_swing_dashboard(setups)
        except Exception as e:
            print(f"Failed to push results to Google Sheets: {e}")
            sheets_failed = True

        telegram_failed = False
        try:
            send_telegram_alert(setups)
        except Exception as e:
            print(f"Failed to send Telegram alert: {e}")
            telegram_failed = True

        if sheets_failed or telegram_failed:
            sys.exit(1)
    else:
        print("No setups identified today; nothing pushed to Google Sheets or Telegram.")


if __name__ == "__main__":
    main()
