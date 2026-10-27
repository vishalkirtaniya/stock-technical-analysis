# stock-signals

Nifty 100 data pipeline -> backtesting -> strategy signals -> ML prediction.

## Status

- [x] Step 1-2: Yahoo Finance -> Supabase (PostgreSQL), incremental updates
- [ ] Step 3: Backtrader parameter-grid backtesting
- [ ] Step 4: Scheduled strategy runs with best parameters
- [ ] Step 5: ML model
- [ ] Step 6: Backend + frontend

## Setup

```bash
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env     # paste your Supabase Session pooler connection string
```

## Usage

```bash
python -m app.cli init-db                    # create tables
python -m app.cli sync-symbols               # load Nifty 100 list
python -m app.cli update --only TCS.NS       # test with one stock
python -m app.cli update                     # backfill / fetch new candles
python -m app.cli stats                      # what's stored
```

Running `update` again only fetches candles after the last stored one.

## Layout

```
app/
  config.py    env settings
  db.py        Postgres connection + schema init
  symbols.py   Nifty 100 constituents -> stocks table
  ingest.py    Yahoo Finance -> candles table (incremental upsert)
  cli.py       command line entry point
sql/schema.sql tables + RLS
data/          optional fallback nifty100.csv
```
# stock-technical-analysis
