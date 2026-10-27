"""Run one backtest, compute metrics, and grid-search every strategy for one symbol."""
import math
from datetime import date, timedelta

import backtrader as bt
import numpy as np
import pandas as pd

from ..db import get_conn
from .strategies import STRATEGIES, param_combinations

RISK_FREE = 0.065     # annual, approximate Indian risk-free rate
TRADING_DAYS = 252
WARMUP_DAYS = 400     # calendar days loaded before `start` so indicators are warm
MIN_EVAL_BARS = 250   # skip stocks with < ~1 year of data inside the window


class EquityCurve(bt.Analyzer):
    def start(self):
        self._dates, self._values = [], []

    def next(self):
        self._dates.append(self.strategy.datetime.date(0))
        self._values.append(self.strategy.broker.getvalue())

    def get_analysis(self):
        return {"dates": self._dates, "values": self._values}


class TradeLog(bt.Analyzer):
    def start(self):
        self._trades = []

    def notify_trade(self, trade):
        if trade.isclosed:
            self._trades.append((self.strategy.datetime.date(0), trade.pnlcomm))

    def get_analysis(self):
        return self._trades


def load_candles(symbol, interval, start, end):
    """Daily candles as a tz-naive IST-dated DataFrame (with warm-up history before `start`)."""
    q = """SELECT ts, open, high, low, close, volume FROM candles
           WHERE symbol = %s AND interval = %s AND ts >= %s AND ts < %s ORDER BY ts"""
    lo = start - timedelta(days=WARMUP_DAYS)
    hi = (end + timedelta(days=1)) if end else date(2100, 1, 1)
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(q, (symbol, interval, lo, hi))
        rows = cur.fetchall()
    df = pd.DataFrame(rows, columns=["ts", "open", "high", "low", "close", "volume"])
    if df.empty:
        return df
    idx = pd.to_datetime(df.pop("ts"), utc=True).dt.tz_convert("Asia/Kolkata")
    df.index = pd.DatetimeIndex(idx.dt.tz_localize(None).dt.normalize())
    df = df[~df.index.duplicated(keep="last")].astype(float)
    df = df[(df[["open", "high", "low", "close"]] > 0).all(axis=1)]
    return df


def run_single(df, name, params, cash, commission, slippage):
    cerebro = bt.Cerebro(stdstats=False)
    cerebro.adddata(bt.feeds.PandasData(dataname=df))
    cerebro.addstrategy(STRATEGIES[name]["cls"], **params)
    cerebro.broker.setcash(cash)
    cerebro.broker.setcommission(commission=commission)
    if slippage:
        cerebro.broker.set_slippage_perc(slippage)
    cerebro.addsizer(bt.sizers.PercentSizer, percents=95, retint=True)
    cerebro.addanalyzer(EquityCurve, _name="equity")
    cerebro.addanalyzer(TradeLog, _name="trades")
    strat = cerebro.run()[0]
    return strat.analyzers.equity.get_analysis(), strat.analyzers.trades.get_analysis()


def compute_metrics(equity, trades, cash, close, eval_start):
    """Metrics over the evaluation window only (warm-up bars are excluded, and
    equity is rebased to `cash`), so every parameter set is compared on the same dates."""
    dates = equity["dates"]
    idx = next((i for i, d in enumerate(dates) if d >= eval_start), None)
    if idx is None or len(dates) - idx < MIN_EVAL_BARS:
        return None, None
    dates = dates[idx:]
    v = np.asarray(equity["values"][idx:], dtype=float)
    v = v / v[0] * cash

    final = float(v[-1])
    years = (dates[-1] - dates[0]).days / 365.25
    cagr = ((final / cash) ** (1 / years) - 1) * 100 if years > 0 and final > 0 else None

    daily = np.diff(v) / v[:-1]
    excess = daily - RISK_FREE / TRADING_DAYS
    sd = excess.std(ddof=1)
    sharpe = float(excess.mean() / sd * math.sqrt(TRADING_DAYS)) if sd > 0 else None

    drawdown = (v - np.maximum.accumulate(v)) / np.maximum.accumulate(v)

    pnls = [float(p) for d, p in trades if d >= dates[0]]
    wins = sum(p for p in pnls if p > 0)
    losses = -sum(p for p in pnls if p < 0)

    c = close.loc[pd.Timestamp(dates[0]):pd.Timestamp(dates[-1])]
    metrics = {
        "bars": int(len(v)),
        "final_value": round(final, 2),
        "total_return_pct": round(float((final / cash - 1) * 100), 2),
        "cagr_pct": None if cagr is None else round(float(cagr), 2),
        "sharpe": None if sharpe is None else round(sharpe, 3),
        "max_drawdown_pct": round(float(drawdown.min()) * 100, 2),
        "num_trades": len(pnls),
        "win_rate_pct": round(sum(p > 0 for p in pnls) / len(pnls) * 100, 2) if pnls else None,
        "profit_factor": round(float(wins / losses), 3) if losses > 0 else None,
        "buy_hold_return_pct": round(float(c.iloc[-1] / c.iloc[0] - 1) * 100, 2),
    }
    keep = list(range(0, len(v), 5))          # weekly sampling keeps the stored curve small
    if keep[-1] != len(v) - 1:
        keep.append(len(v) - 1)
    curve = {
        "dates": [dates[i].isoformat() for i in keep],
        "values": [round(float(v[i])) for i in keep],
    }
    return metrics, curve


def backtest_symbol(symbol, interval, start, end, cash, commission, slippage,
                    min_trades, strategies, df=None):
    """Try every parameter combination of every strategy on one stock.

    Returns (symbol, results, best_curves). Runs inside a worker process.
    `df` can be passed in (tests); otherwise candles are loaded from the DB.
    """
    if df is None:
        df = load_candles(symbol, interval, start, end)
    if len(df) < MIN_EVAL_BARS + 50:
        return symbol, [], []

    results, best_curves = [], []
    for name in strategies:
        best = None
        for params in param_combinations(name):
            equity, trades = run_single(df, name, params, cash, commission, slippage)
            m, curve = compute_metrics(equity, trades, cash, df["close"], start)
            if m is None:
                continue
            results.append({"strategy": name, "params": params, **m})
            if m["sharpe"] is not None and m["num_trades"] >= min_trades:
                if best is None or m["sharpe"] > best[0]:
                    best = (m["sharpe"], params, curve)
        if best:
            best_curves.append({"strategy": name, "params": best[1], "curve": best[2]})
    return symbol, results, best_curves