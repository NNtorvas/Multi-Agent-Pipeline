import os
import logging
import psycopg2
from contextlib import contextmanager

DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql://pipeline:pipeline@localhost:5432/pipeline"
)


@contextmanager
def _conn():
    conn = psycopg2.connect(DATABASE_URL)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS reports (
                    id              SERIAL PRIMARY KEY,
                    created_at      TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                    report_markdown TEXT NOT NULL,
                    status          VARCHAR(50) NOT NULL
                )
            """
            )
    logging.info("[db] Table 'reports' ensured")


def save_report(report_markdown: str, status: str) -> int:
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO reports (report_markdown, status)"
                " VALUES (%s, %s) RETURNING id",
                (report_markdown, status),
            )
            row_id: int = cur.fetchone()[0]
    logging.info("[db] Saved report id=%d status=%s", row_id, status)
    return row_id


def get_all_reports() -> list[tuple]:
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, created_at, status FROM reports ORDER BY created_at DESC"
            )
            return cur.fetchall()


def get_report_by_id(report_id: int) -> tuple | None:
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, created_at, report_markdown, status"
                " FROM reports WHERE id = %s",
                (report_id,),
            )
            return cur.fetchone()
