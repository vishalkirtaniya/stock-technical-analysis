import logging
import os
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import requests

API_URL = os.environ["API_URL"].rstrip("/")
API_KEY = os.environ["API_KEY"]
HOUR = int(os.getenv("SCHEDULE_HOUR", "18"))
MINUTE = int(os.getenv("SCHEDULE_MINUTE", "0"))
RUN_ON_START = os.getenv("RUN_ON_START", "false").lower() == "true"

IST = ZoneInfo("Asia/Kolkata")
HEADERS = {"X-API-Key": API_KEY}

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("scheduler")


def next_run(now):
    """Next Mon-Fri occurrence of HOUR:MINUTE in IST."""
    t = now.replace(hour=HOUR, minute=MINUTE, second=0, microsecond=0)
    if t <= now:
        t += timedelta(days=1)
    while t.weekday() >= 5:  # skip Sat/Sun
        t += timedelta(days=1)
    return t


def trigger_update():
    for attempt in range(1, 4):
        try:
            r = requests.post(f"{API_URL}/update", headers=HEADERS, timeout=30)
            if r.status_code == 202:
                log.info("Update started")
                return True
            if r.status_code == 409:
                log.info("Update already running, nothing to do")
                return False
            log.error("Unexpected response %s: %s", r.status_code, r.text)
        except requests.RequestException as e:
            log.error("Request failed (attempt %d/3): %s", attempt, e)
        time.sleep(60 * attempt)
    log.error("Giving up for today")
    return False


def wait_for_finish(timeout=3 * 3600):
    deadline = time.time() + timeout
    while time.time() < deadline:
        time.sleep(30)
        try:
            s = requests.get(f"{API_URL}/update/status", headers=HEADERS, timeout=30).json()
        except requests.RequestException as e:
            log.warning("Status check failed: %s", e)
            continue
        if not s["running"]:
            if s["last_error"]:
                log.error("Update failed: %s", s["last_error"])
            else:
                log.info("Update finished: %s", s["last_result"])
            return
    log.warning("Timed out waiting for update to finish")


def main():
    log.info("Scheduler up. Target: %s, daily at %02d:%02d IST (Mon-Fri)", API_URL, HOUR, MINUTE)
    if RUN_ON_START and trigger_update():
        wait_for_finish()
    while True:
        target = next_run(datetime.now(IST))
        log.info("Next run at %s", target.isoformat())
        while datetime.now(IST) < target:
            time.sleep(min(60, max(1, (target - datetime.now(IST)).total_seconds())))
        if trigger_update():
            wait_for_finish()


if __name__ == "__main__":
    main()