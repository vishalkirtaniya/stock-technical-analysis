"""Load the Nifty 100 constituents into the `stocks` table.

Primary source: official NSE index CSV.
Fallback: data/nifty100.csv (needs a 'Symbol' column; 'Company Name',
'Industry', 'ISIN Code' optional) so you can maintain the list by hand.
"""
import io
from pathlib import Path

import pandas as pd
import requests

from .db import get_conn

URLS = [
    "https://nsearchives.nseindia.com/content/indices/ind_nifty100list.csv",
    "https://niftyindices.com/IndexConstituent/ind_nifty100list.csv",
]
FALLBACK = Path(__file__).resolve().parent.parent / "data" / "nifty100.csv"
HEADERS = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"}


def _download():
    for url in URLS:
        try:
            r = requests.get(url, headers=HEADERS, timeout=20)
            r.raise_for_status()
            print(f"Fetched constituents from {url}")
            return pd.read_csv(io.StringIO(r.text))
        except Exception as e:
            print(f"  could not fetch {url}: {e}")
    return None


def sync_symbols():
    df = _download()
    if df is None:
        if not FALLBACK.exists():
            raise SystemExit(
                f"NSE download failed and {FALLBACK} not found. "
                "Download the Nifty 100 CSV from niftyindices.com and save it there."
            )
        print(f"Using fallback file {FALLBACK}")
        df = pd.read_csv(FALLBACK)

    df.columns = [c.strip() for c in df.columns]
    rows = []
    for _, r in df.iterrows():
        nse = str(r["Symbol"]).strip()
        rows.append((
            f"{nse}.NS", nse,
            r.get("Company Name"), r.get("Industry"), r.get("ISIN Code"),
        ))

    with get_conn() as conn, conn.cursor() as cur:
        # anything not in the new list gets deactivated, not deleted
        cur.execute("UPDATE stocks SET active = FALSE")
        for row in rows:
            cur.execute(
                """
                INSERT INTO stocks (symbol, nse_symbol, name, industry, isin, active)
                VALUES (%s, %s, %s, %s, %s, TRUE)
                ON CONFLICT (symbol) DO UPDATE SET
                    name = EXCLUDED.name, industry = EXCLUDED.industry,
                    isin = EXCLUDED.isin, active = TRUE
                """,
                row,
            )
    print(f"{len(rows)} symbols synced.")
