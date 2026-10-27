import hmac
import threading
from datetime import datetime, timezone

from fastapi import BackgroundTasks, Depends, FastAPI, Header, HTTPException

from .config import API_KEY
from .db import get_conn
from .ingest import update_all

if not API_KEY:
    raise RuntimeError("API_KEY is not set in .env")

app = FastAPI(title="stock-signals")

# In-memory state, so run uvicorn with a single worker (the default).
_lock = threading.Lock()
_state = {
    "running": False,
    "started_at": None,
    "finished_at": None,
    "last_result": None,
    "last_error": None,
}


def _now():
    return datetime.now(timezone.utc).isoformat()


def require_key(x_api_key: str = Header(default="")):
    if not hmac.compare_digest(x_api_key.encode(), API_KEY.encode()):
        raise HTTPException(status_code=401, detail="Invalid API key")


def _run_update():
    try:
        result = update_all()
        with _lock:
            _state["last_result"] = result
            _state["last_error"] = None
    except (Exception, SystemExit) as e:  # SystemExit: raised when no symbols exist
        with _lock:
            _state["last_error"] = str(e)
    finally:
        with _lock:
            _state["running"] = False
            _state["finished_at"] = _now()


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/update", status_code=202, dependencies=[Depends(require_key)])
def trigger_update(background: BackgroundTasks):
    with _lock:
        if _state["running"]:
            raise HTTPException(status_code=409, detail="Update already running")
        _state.update(running=True, started_at=_now(), finished_at=None)
    background.add_task(_run_update)
    return {"status": "started"}


@app.get("/update/status", dependencies=[Depends(require_key)])
def update_status():
    with _lock:
        return dict(_state)


@app.get("/stats", dependencies=[Depends(require_key)])
def stats():
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT count(DISTINCT symbol), count(*), min(ts)::date, max(ts)::date FROM candles"
        )
        symbols, candles, first, last = cur.fetchone()
    return {"symbols": symbols, "candles": candles, "first": first, "last": last}