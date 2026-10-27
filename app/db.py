from contextlib import contextmanager
from pathlib import Path

import psycopg2

from .config import DATABASE_URL


@contextmanager
def get_conn():
    conn = psycopg2.connect(DATABASE_URL)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_schema():
    sql = (Path(__file__).resolve().parent.parent / "sql" / "schema.sql").read_text()
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(sql)
    print("Schema ready.")
