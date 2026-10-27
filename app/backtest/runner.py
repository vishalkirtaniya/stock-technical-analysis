"""Run the full grid search for many stocks in parallel and store results in Postgres."""
import os
import time
from concurrent.futures import ProcessPoolExecutor, as_completed

from psycopg2.extras import Json, execute_values

from ..db import get_conn
from .engine import backtest_symbol
from .strategies import STRATEGIES
import traceback

RESULT_COLS = ["bars", "final_value", "total_return_pct", "cagr_pct", "sharpe",
               "max_drawdown_pct", "num_trades", "win_rate_pct", "profit_factor",
               "buy_hold_return_pct"]

INSERT_SQL = f"""
    INSERT INTO backtest_results
        (batch_id, symbol, strategy, params, {", ".join(RESULT_COLS)})
    VALUES %s
"""


def _save_symbol(batch_id, symbol, results, curves):
    rows = [
        (batch_id, symbol, r["strategy"], Json(r["params"]), *[r[c] for c in RESULT_COLS])
        for r in results
    ]
    with get_conn() as conn, conn.cursor() as cur:
        # one transaction per symbol: a symbol is either fully saved or not at all
        cur.execute("DELETE FROM backtest_results WHERE batch_id = %s AND symbol = %s",
                    (batch_id, symbol))
        if rows:
            execute_values(cur, INSERT_SQL, rows, page_size=500)
        for c in curves:
            cur.execute(
                """SELECT id FROM backtest_results
                   WHERE batch_id = %s AND symbol = %s AND strategy = %s AND params = %s::jsonb""",
                (batch_id, symbol, c["strategy"], Json(c["params"])),
            )
            row = cur.fetchone()
            if row:
                cur.execute(
                    "INSERT INTO backtest_equity (result_id, curve) VALUES (%s, %s) "
                    "ON CONFLICT (result_id) DO UPDATE SET curve = EXCLUDED.curve",
                    (row[0], Json(c["curve"])),
                )

def _lower_priority():
    """Run workers at low priority so the machine stays responsive (Linux/macOS)."""
    try:
        os.nice(10)
    except (AttributeError, OSError):
        pass

def run_backtest(start, end=None, strategies=None, only=None, workers=5,
                 cash=100_000.0, commission=0.001, slippage=0.0005,
                 min_trades=10, resume=None, interval="1d"):
    strategies = strategies or list(STRATEGIES)
    unknown = [s for s in strategies if s not in STRATEGIES]
    if unknown:
        raise SystemExit(f"Unknown strategies {unknown}. Available: {list(STRATEGIES)}")

    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT symbol FROM stocks WHERE active ORDER BY symbol")
        symbols = [r[0] for r in cur.fetchall()]
        if only:
            symbols = [s for s in symbols if s in only]

        if resume:
            batch_id = resume
            cur.execute("UPDATE backtest_batches SET status = 'running', finished_at = NULL "
                        "WHERE id = %s RETURNING id", (batch_id,))
            if not cur.fetchone():
                raise SystemExit(f"Batch {batch_id} not found")
            cur.execute("SELECT DISTINCT symbol FROM backtest_results WHERE batch_id = %s",
                        (batch_id,))
            done = {r[0] for r in cur.fetchall()}
            symbols = [s for s in symbols if s not in done]
            print(f"Resuming batch {batch_id}: {len(done)} symbols already done")
        else:
            cur.execute(
                """INSERT INTO backtest_batches
                   (interval, start_date, end_date, initial_cash, commission, slippage, strategies)
                   VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id""",
                (interval, start, end, cash, commission, slippage, strategies),
            )
            batch_id = cur.fetchone()[0]

    if not symbols:
        raise SystemExit("No symbols to process.")
        print(f"{workers} workers, window {start} -> {end or 'latest'}")

    # runs limited to some stocks/strategies are "partial": they never replace a full run
    partial = bool(only) or set(strategies) != set(STRATEGIES)
    t0, failed = time.time(), []
    try:
        with ProcessPoolExecutor(max_workers=workers, initializer=_lower_priority) as pool:
            futures = {
                pool.submit(backtest_symbol, s, interval, start, end, cash, commission,
                            slippage, min_trades, strategies): s
                for s in symbols
            }
            for i, fut in enumerate(as_completed(futures), 1):
                symbol = futures[fut]
                try:
                    _, results, curves = fut.result()
                    _save_symbol(batch_id, symbol, results, curves)
                    note = f"{len(results)} runs" if results else "skipped (not enough data)"
                except Exception as e:
                    failed.append(symbol)
                    note = f"FAILED: {e}"
                print(f"[{i}/{len(symbols)}] {symbol:<18} {note}  ({time.time() - t0:.0f}s)")
    except BaseException:
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute("UPDATE backtest_batches SET status = 'failed' WHERE id = %s", (batch_id,))
        print(f"\nInterrupted. Continue later with: python -m app.cli backtest --resume {batch_id}")
        raise

    with get_conn() as conn, conn.cursor() as cur:
        status = "failed" if failed else ("partial" if partial else "completed")
        cur.execute("UPDATE backtest_batches SET status = %s, finished_at = now() WHERE id = %s",
                    (status, batch_id))
        if status == "completed":
            # keep equity curves only for the latest completed batch
            cur.execute(
                """DELETE FROM backtest_equity e USING backtest_results r
                   WHERE r.id = e.result_id AND r.batch_id <> %s""", (batch_id,))
    print(f"\nBatch {batch_id} {status} in {time.time() - t0:.0f}s. Failed: {failed or 'none'}")
    if failed:
        print(f"Retry the failures with: python -m app.cli backtest --resume {batch_id}")
    return batch_id