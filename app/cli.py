import argparse
from datetime import date, timedelta
from .db import get_conn, init_schema
from .ingest import update_all
from .symbols import sync_symbols


def main():
    p = argparse.ArgumentParser(prog="stock-signals")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init-db", help="create tables")
    sub.add_parser("sync-symbols", help="load Nifty 100 list into DB")
    u = sub.add_parser("update", help="backfill / fetch new candles up to latest")
    u.add_argument("--only", nargs="*", help="limit to symbols, e.g. TCS.NS INFY.NS")
    sub.add_parser("stats", help="show what's stored")

    b = sub.add_parser("backtest", help="parameter-grid backtests")
    b.add_argument("--years", type=float, default=3, help="evaluate the last N years (default 3)")
    b.add_argument("--start", default=None, help="explicit start date; overrides --years")
    b.add_argument("--end", default=None, help="evaluation end date (default: latest)")
    b.add_argument("--strategies", nargs="*", help="default: all")
    b.add_argument("--only", nargs="*", help="limit to symbols, e.g. TCS.NS")
    b.add_argument("--workers", type=int, default=5, help="number of parallel processes")
    b.add_argument("--cash", type=float, default=100_000)
    b.add_argument("--commission", type=float, default=0.001, help="per side, 0.001 = 0.1%%")
    b.add_argument("--slippage", type=float, default=0.0005)
    b.add_argument("--min-trades", type=int, default=10)
    b.add_argument("--resume", type=int, default=None, help="batch id to continue")
    args = p.parse_args()

    if args.cmd == "init-db":
        init_schema()
    elif args.cmd == "sync-symbols":
        sync_symbols()
    elif args.cmd == "update":
        update_all(args.only)
    elif args.cmd == "stats":
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute("""
                SELECT count(DISTINCT symbol), count(*), min(ts)::date, max(ts)::date
                FROM candles""")
            print("symbols, candles, first, last =", cur.fetchone())
    elif args.cmd == "backtest":
        from .backtest.runner import run_backtest
        start = (date.fromisoformat(args.start) if args.start
                 else date.today() - timedelta(days=round(365.25 * args.years)))
        run_backtest(
            start=start,
            end=date.fromisoformat(args.end) if args.end else None,
            strategies=args.strategies, only=args.only, workers=args.workers,
            cash=args.cash, commission=args.commission, slippage=args.slippage,
            min_trades=args.min_trades, resume=args.resume,
        )


if __name__ == "__main__":
    main()