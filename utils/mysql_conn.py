"""
mysql_conn.py — MySQL query runner with retry
==============================================
Retries the connection + query up to 5 times with exponential backoff.
On final failure raises ConnectionError which tests catch and report gracefully.
"""

import mysql.connector
import pandas as pd

from config import MYSQL_CONFIG, render
from utils.retry import with_retry, MAX_RETRIES


@with_retry("MySQL connection")
def run_mysql(sql: str) -> pd.DataFrame:
    """
    Execute a rendered SQL query against the source MySQL DB.
    Returns a DataFrame. Retries up to MAX_RETRIES times on any connection error.
    """
    conn = mysql.connector.connect(**MYSQL_CONFIG)
    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute(render(sql))
        rows = cursor.fetchall()
        return pd.DataFrame(rows) if rows else pd.DataFrame()
    finally:
        cursor.close()
        conn.close()


@with_retry("MySQL connectivity check")
def test_mysql_connection() -> str:
    """Returns 'OK' or raises — used for pre-flight checks."""
    conn = mysql.connector.connect(**MYSQL_CONFIG)
    cur  = conn.cursor()
    cur.execute("SELECT 1")
    conn.close()
    return "OK"
