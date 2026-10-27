import os
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", None)
INTERVAL = os.getenv("INTERVAL", "1d")
HISTORY_START = os.getenv("HISTORY_START", "2010-01-01")
OVERLAP_DAYS = int(os.getenv("OVERLAP_DAYS", "5"))
REQUEST_DELAY = float(os.getenv("REQUEST_DELAY", "0.5"))
API_KEY = os.getenv("API_KEY")

if not DATABASE_URL:
    raise SystemExit("DATABASE_URL is not set. Copy .env.example to .env and fill in your Supabase connection string.")
