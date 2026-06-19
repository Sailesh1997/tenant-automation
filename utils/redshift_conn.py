"""
redshift_conn.py — Redshift query runner with retry
=====================================================
Retries the connection + query up to 5 times with exponential backoff.
On final failure raises ConnectionError which tests catch and report gracefully.
"""

import psycopg2
import psycopg2.extras
import pandas as pd

from config import REDSHIFT_CONFIG, render
from utils.retry import with_retry, MAX_RETRIES


@with_retry("Redshift connection")
def run_redshift(sql: str) -> pd.DataFrame:
    """
    Execute a rendered SQL query against Redshift (DLA / DSA / TDW).
    Returns a DataFrame. Retries up to MAX_RETRIES times on any connection error.
    """
    conn = psycopg2.connect(**REDSHIFT_CONFIG)
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(render(sql))
            rows = cur.fetchall()
            return pd.DataFrame([dict(r) for r in rows]) if rows else pd.DataFrame()
    finally:
        conn.close()


@with_retry("Redshift connectivity check")
def test_redshift_connection() -> str:
    """Returns 'OK' or raises — used for pre-flight checks."""
    conn = psycopg2.connect(**REDSHIFT_CONFIG)
    cur  = conn.cursor()
    cur.execute("SELECT 1")
    conn.close()
    return "OK"
