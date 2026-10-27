CREATE TABLE IF NOT EXISTS stocks (
    symbol     TEXT PRIMARY KEY,          -- Yahoo symbol, e.g. RELIANCE.NS
    nse_symbol TEXT NOT NULL,             -- e.g. RELIANCE
    name       TEXT,
    industry   TEXT,
    isin       TEXT,
    active     BOOLEAN NOT NULL DEFAULT TRUE,
    added_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS candles (
    symbol     TEXT NOT NULL REFERENCES stocks(symbol),
    interval   TEXT NOT NULL,             -- '1d', '1h', '15m' ...
    ts         TIMESTAMPTZ NOT NULL,      -- candle start time (UTC)
    open       DOUBLE PRECISION NOT NULL,
    high       DOUBLE PRECISION NOT NULL,
    low        DOUBLE PRECISION NOT NULL,
    close      DOUBLE PRECISION NOT NULL,
    adj_close  DOUBLE PRECISION,
    volume     BIGINT,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (symbol, interval, ts)
);

CREATE INDEX IF NOT EXISTS idx_candles_ts ON candles (interval, ts);

-- Supabase exposes the public schema through its Data API (anon key).
-- Turn on Row Level Security with no policies so nobody can read/write these
-- tables through that API. Our backend connects directly as the `postgres`
-- role, which bypasses RLS, so it is unaffected.
ALTER TABLE stocks  ENABLE ROW LEVEL SECURITY;
ALTER TABLE candles ENABLE ROW LEVEL SECURITY;

-- ===================== Step 3: backtesting =====================

CREATE TABLE IF NOT EXISTS backtest_batches (
    id           BIGSERIAL PRIMARY KEY,
    interval     TEXT NOT NULL,
    start_date   DATE NOT NULL,
    end_date     DATE,
    initial_cash DOUBLE PRECISION NOT NULL,
    commission   DOUBLE PRECISION NOT NULL,
    slippage     DOUBLE PRECISION NOT NULL,
    strategies   TEXT[] NOT NULL,
    status       TEXT NOT NULL DEFAULT 'running',   -- running | completed | partial | failed
    started_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at  TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS backtest_results (
    id                  BIGSERIAL PRIMARY KEY,
    batch_id            BIGINT NOT NULL REFERENCES backtest_batches(id) ON DELETE CASCADE,
    symbol              TEXT NOT NULL REFERENCES stocks(symbol),
    strategy            TEXT NOT NULL,
    params              JSONB NOT NULL,
    bars                INT,
    final_value         DOUBLE PRECISION,   -- portfolio value at the end (starts at initial_cash)
    total_return_pct    DOUBLE PRECISION,
    cagr_pct            DOUBLE PRECISION,
    sharpe              DOUBLE PRECISION,
    max_drawdown_pct    DOUBLE PRECISION,
    num_trades          INT,
    win_rate_pct        DOUBLE PRECISION,
    profit_factor       DOUBLE PRECISION,
    buy_hold_return_pct DOUBLE PRECISION,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_bt_results_lookup
    ON backtest_results (batch_id, symbol, strategy);

-- Portfolio value over time (weekly points). Only stored for the best run of each
-- (symbol, strategy) and only for the latest full batch, to keep the database small.
CREATE TABLE IF NOT EXISTS backtest_equity (
    result_id BIGINT PRIMARY KEY REFERENCES backtest_results(id) ON DELETE CASCADE,
    curve     JSONB NOT NULL            -- {"dates": [...], "values": [...]}
);

-- Best parameters per (symbol, strategy) from the latest completed batch.
-- Ranking rule: highest Sharpe among runs with at least 10 trades. Change it here.
CREATE OR REPLACE VIEW best_params AS
SELECT DISTINCT ON (r.symbol, r.strategy) r.*
FROM backtest_results r
WHERE r.batch_id = (SELECT max(id) FROM backtest_batches WHERE status = 'completed')
  AND r.num_trades >= 10
  AND r.sharpe IS NOT NULL
ORDER BY r.symbol, r.strategy, r.sharpe DESC;

-- Without this, Supabase would expose the view through its public API and skip RLS
ALTER VIEW best_params SET (security_invoker = on);

ALTER TABLE backtest_batches ENABLE ROW LEVEL SECURITY;
ALTER TABLE backtest_results ENABLE ROW LEVEL SECURITY;
ALTER TABLE backtest_equity  ENABLE ROW LEVEL SECURITY;