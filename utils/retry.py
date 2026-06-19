"""
retry.py — Connection retry utility
=====================================
Shared retry wrapper used by mysql_conn, redshift_conn, and config.
Retries up to MAX_RETRIES times with exponential backoff before giving up.

Only transient connection errors are retried.  SQL/programming errors
(bad column name, syntax error, etc.) are re-raised immediately so tests
fail fast with a clear message instead of burning 60+ seconds on pointless
retries.
"""

import time
import functools


MAX_RETRIES = 5
BASE_DELAY  = 2   # seconds — doubles each attempt: 2, 4, 8, 16, 32


def _is_transient(exc: Exception) -> bool:
    """
    Return True only for errors that indicate a lost or unavailable connection.

    Both mysql-connector-python and psycopg2 use OperationalError /
    InterfaceError for connection-level failures, and ProgrammingError for
    bad SQL (wrong column names, syntax errors, etc.).  We never retry
    ProgrammingErrors — the query is broken and retrying won't help.
    """
    name = type(exc).__name__.lower()
    if "programming" in name:
        return False                        # SQL error — fail immediately
    if "operational" in name or "interface" in name:
        return True
    # MySQL-specific errno codes for broken/lost connections
    code = getattr(exc, "errno", None)
    if code in (2003, 2006, 2013, 2055):   # can't connect / server gone away
        return True
    return False


def with_retry(operation_name: str):
    """
    Decorator factory that wraps a function with retry logic.

    Usage:
        @with_retry("MySQL property discovery")
        def _my_func(): ...

    Transient connection failures are retried with exponential backoff.
    Non-transient errors (bad SQL, etc.) are re-raised immediately.
    After MAX_RETRIES exhausted, raises ConnectionError with a clear message.
    """
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            last_exc = None
            for attempt in range(1, MAX_RETRIES + 1):
                try:
                    return func(*args, **kwargs)
                except Exception as exc:
                    if not _is_transient(exc):
                        raise   # SQL / programming error — don't retry

                    last_exc = exc
                    delay = BASE_DELAY * (2 ** (attempt - 1))   # 2, 4, 8, 16, 32 s
                    print(
                        f"\n[RETRY] {operation_name} — attempt {attempt}/{MAX_RETRIES} failed: {exc}",
                        flush=True,
                    )
                    if attempt < MAX_RETRIES:
                        print(f"[RETRY] Waiting {delay}s before next attempt ...", flush=True)
                        time.sleep(delay)
                    else:
                        print(
                            f"[RETRY] {operation_name} — all {MAX_RETRIES} attempts exhausted.",
                            flush=True,
                        )

            raise ConnectionError(
                f"Connection lost — {operation_name} failed after {MAX_RETRIES} attempts. "
                f"Last error: {last_exc}"
            )
        return wrapper
    return decorator


def retry_call(func, operation_name: str, *args, **kwargs):
    """
    Inline retry helper (no decorator needed).

    Usage:
        result = retry_call(run_mysql, "MySQL TC-01", sql)
    """
    return with_retry(operation_name)(func)(*args, **kwargs)
