"""Long-only strategies + the parameter grid for each.

To add a strategy: write a LongOnly subclass and add an entry to STRATEGIES.
"""
import itertools

import backtrader as bt


class LongOnly(bt.Strategy):
    """Enter on should_buy(), exit on should_sell(). Orders fill on the next bar's open."""

    def next(self):
        if not self.position:
            if self.should_buy():
                self.buy()
        elif self.should_sell():
            self.close()

    def should_buy(self):
        raise NotImplementedError

    def should_sell(self):
        raise NotImplementedError


class MACross(LongOnly):
    params = dict(fast=10, slow=30, ma="sma")

    def __init__(self):
        ma = bt.ind.SMA if self.p.ma == "sma" else bt.ind.EMA
        self.cross = bt.ind.CrossOver(ma(period=self.p.fast), ma(period=self.p.slow))

    def should_buy(self):
        return self.cross[0] > 0

    def should_sell(self):
        return self.cross[0] < 0


class RSIStrategy(LongOnly):
    """Mean reversion: buy oversold, sell overbought."""
    params = dict(period=14, oversold=30, overbought=70)

    def __init__(self):
        self.rsi = bt.ind.RSI(period=self.p.period)

    def should_buy(self):
        return self.rsi[0] < self.p.oversold

    def should_sell(self):
        return self.rsi[0] > self.p.overbought


class MACDStrategy(LongOnly):
    """Buy when MACD crosses above its signal line, sell when it crosses below."""
    params = dict(fast=12, slow=26, signal=9)

    def __init__(self):
        macd = bt.ind.MACD(
            period_me1=self.p.fast, period_me2=self.p.slow, period_signal=self.p.signal
        )
        self.cross = bt.ind.CrossOver(macd.macd, macd.signal)

    def should_buy(self):
        return self.cross[0] > 0

    def should_sell(self):
        return self.cross[0] < 0


class BollingerStrategy(LongOnly):
    """Mean reversion: buy below the lower band, sell above the middle band."""
    params = dict(period=20, devfactor=2.0)

    def __init__(self):
        self.bb = bt.ind.BollingerBands(period=self.p.period, devfactor=self.p.devfactor)

    def should_buy(self):
        return self.data.close[0] < self.bb.lines.bot[0]

    def should_sell(self):
        return self.data.close[0] > self.bb.lines.mid[0]


_MA_GRID = {"fast": [5, 10, 15, 20, 30], "slow": [30, 50, 100, 150, 200]}

STRATEGIES = {
    "sma_cross": dict(
        cls=MACross,
        grid={**_MA_GRID, "ma": ["sma"]},
        valid=lambda p: p["fast"] < p["slow"],
    ),
    "ema_cross": dict(
        cls=MACross,
        grid={**_MA_GRID, "ma": ["ema"]},
        valid=lambda p: p["fast"] < p["slow"],
    ),
    "rsi": dict(
        cls=RSIStrategy,
        grid={"period": [7, 10, 14, 21], "oversold": [20, 25, 30, 35],
              "overbought": [65, 70, 75, 80]},
    ),
    "macd": dict(
        cls=MACDStrategy,
        grid={"fast": [8, 12, 16], "slow": [21, 26, 34], "signal": [7, 9, 12]},
    ),
    "bollinger": dict(
        cls=BollingerStrategy,
        grid={"period": [10, 20, 30], "devfactor": [1.5, 2.0, 2.5]},
    ),
}


def param_combinations(name):
    """Every valid combination of the strategy's grid (cartesian product)."""
    spec = STRATEGIES[name]
    keys = list(spec["grid"])
    valid = spec.get("valid", lambda p: True)
    for values in itertools.product(*spec["grid"].values()):
        params = dict(zip(keys, values))
        if valid(params):
            yield params