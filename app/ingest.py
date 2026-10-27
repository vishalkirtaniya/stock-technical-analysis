"""Fetch candles from Yahoo Finance into PostgreSQL.

Incremental: for each symbol we look up the latest stored candle and only
request data from (last_ts - OVERLAP_DAYS) onward. First run = full history.
Upserts make it safe to re-run any time.
"""
import time
from datetime import timedelta

import pandas as pd
import yfinance as yf
from psycopg2.extras import execute_values

from .config import HISTORY_START, INTERVAL, OVERLAP_DAYS, REQUEST_DELAY
from .db import get_conn

COLS = ["open", "high", "low", "close", "adj_close", "volume"]


def _last_ts(cur, symbol, interval):
    cur.execute(
        "SELECT max(ts) FROM candles WHERE symbol = %s AND interval = %s",
        (symbol, interval),
    )
    return cur.fetchone()[0]


def _fetch(symbol, start, retries=3):
    for attempt in range(1, retries + 1):
        try:
            df = yf.Ticker(symbol).history(
                start=start, interval=INTERVAL, auto_adjust=False, actions=False
            )
            break
        except Exception as e:
            if attempt == retries:
                raise
            wait = 2 ** attempt
            print(f"  retry {attempt}/{retries} for {symbol} in {wait}s ({e})")
            time.sleep(wait)

    if df is None or df.empty:
        return pd.DataFrame(columns=COLS)

    df = df.rename(columns=lambda c: c.strip().lower().replace(" ", "_"))
    if "adj_close" not in df:
        df["adj_close"] = df["close"]

    idx = pd.to_datetime(df.index)
    idx = idx.tz_localize("Asia/Kolkata") if idx.tz is None else idx
    df.index = idx.tz_convert("UTC")

    df = df[COLS].dropna(subset=["open", "high", "low", "close"])
    df["volume"] = df["volume"].fillna(0).astype("int64")
    return df


def _upsert(cur, symbol, df):
    rows = [
        (symbol, INTERVAL, ts.to_pydatetime(), float(r.open), float(r.high),
         float(r.low), float(r.close), float(r.adj_close), int(r.volume))
        for ts, r in df.iterrows()
    ]
    execute_values(
        cur,
        """
        INSERT INTO candles
            (symbol, interval, ts, open, high, low, close, adj_close, volume)
        VALUES %s
        ON CONFLICT (symbol, interval, ts) DO UPDATE SET
            open = EXCLUDED.open, high = EXCLUDED.high, low = EXCLUDED.low,
            close = EXCLUDED.close, adj_close = EXCLUDED.adj_close,
            volume = EXCLUDED.volume, updated_at = now()
        """,
        rows,
        page_size=1000,
    )
    return len(rows)


def update_all(only=None):
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT symbol FROM stocks WHERE active ORDER BY symbol")
        symbols = [r[0] for r in cur.fetchall()]
    if only:
        symbols = [s for s in symbols if s in only]
    if not symbols:
        raise SystemExit("No symbols found. Run: python -m app.cli sync-symbols")

    total, failed = 0, []
    for i, symbol in enumerate(symbols, 1):
        try:
            with get_conn() as conn, conn.cursor() as cur:
                last = _last_ts(cur, symbol, INTERVAL)
                start = (last - timedelta(days=OVERLAP_DAYS)).date() if last else HISTORY_START
                df = _fetch(symbol, start)
                n = _upsert(cur, symbol, df) if not df.empty else 0
            total += n
            mode = "update" if last else "backfill"
            print(f"[{i}/{len(symbols)}] {symbol:<18} {mode:<8} {n} rows")
        except Exception as e:
            failed.append(symbol)
            print(f"[{i}/{len(symbols)}] {symbol:<18} FAILED: {e}")
        time.sleep(REQUEST_DELAY)

    print(f"\nDone. {total} rows written. Failed: {failed or 'none'}")
    return {"symbols": len(symbols), "rows_written": total, "failed": failed}
