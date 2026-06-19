"""
preflight.py - Pre-flight connection and schema verification
Runs once before the test suite starts.

Checks:
  1. MySQL connection and required tables          (CRITICAL — aborts suite on failure)
  2. Redshift DLA connection and required tables   (CRITICAL — aborts suite on failure)
  3. Redshift DSA / TDW tables                     (WARNING  — logs but does not abort)
  4. CDC lag — how long ago the pipeline last ran  (INFO/WARNING — never aborts)

Returns a tuple: (cdc_info dict, list[str] of critical error messages).
The caller (conftest.py) is responsible for calling pytest.exit() if errors exist.
"""

import psycopg2
import mysql.connector

from config import MYSQL_CONFIG, REDSHIFT_CONFIG, PARAMS


CDC_LAG_WARNING_HOURS = 6

MYSQL_TABLES_REQUIRED = [
    "invoices", "payments", "leases", "units",
    "leads", "contacts", "properties"
]

DLA_TABLES_REQUIRED = [
    "invoices", "payments", "leases", "units", "leads", "contacts"
]

DSA_TABLES_REQUIRED = [
    "dsa_invoice_f", "dsa_lease_f", "dsa_unit_d", "dsa_contact_f"
]

TDW_TABLES_REQUIRED = [
    "tdw_lease_d", "tdw_contact_d", "tdw_date_d"
]


def _line(char="=", width=60):
    print(char * width, flush=True)


def _header(msg, char="=", width=60):
    _line(char, width)
    print(f"  {msg}", flush=True)
    _line(char, width)
    print("", flush=True)


def _check_tables(cur, schema, required):
    """Return a sorted list of missing table names for a given schema."""
    placeholders = ", ".join(["%s"] * len(required))
    cur.execute(
        f"SELECT table_name FROM information_schema.tables "
        f"WHERE table_schema = %s AND table_name IN ({placeholders})",
        [schema] + required,
    )
    found = {row[0] for row in cur.fetchall()}
    return sorted(set(required) - found)


def check_mysql():
    """Return a list of critical error strings (empty = OK)."""
    schema = PARAMS["schema"]
    try:
        conn = mysql.connector.connect(**MYSQL_CONFIG)
        cur  = conn.cursor()
        missing = _check_tables(cur, schema, MYSQL_TABLES_REQUIRED)
        conn.close()
        if missing:
            return [f"Schema '{schema}' is missing tables: {missing}"]
        return []
    except mysql.connector.Error as e:
        return [f"Cannot connect to MySQL: {e}"]


def check_redshift():
    """
    Check DLA (critical), DSA and TDW (warnings only).

    Returns:
        critical_errors : list[str]   — DLA failures that should abort the suite
        warnings        : list[str]   — DSA / TDW issues that are informational only
    """
    dla = PARAMS["dla"]
    dsa = PARAMS["dsa"]
    tdw = PARAMS["tdw"]

    critical_errors = []
    warnings        = []

    try:
        conn = psycopg2.connect(**REDSHIFT_CONFIG)
        cur  = conn.cursor()

        # DLA — critical
        missing = _check_tables(cur, dla, DLA_TABLES_REQUIRED)
        if missing:
            critical_errors.append(f"Schema '{dla}' is missing tables: {missing}")

        # DSA — warning only
        missing = _check_tables(cur, dsa, DSA_TABLES_REQUIRED)
        if missing:
            warnings.append(f"Schema '{dsa}' is missing tables (WARNING): {missing}")

        # TDW — warning only
        missing = _check_tables(cur, tdw, TDW_TABLES_REQUIRED)
        if missing:
            warnings.append(f"Schema '{tdw}' is missing tables (WARNING): {missing}")

        conn.close()

    except psycopg2.Error as e:
        critical_errors.append(f"Cannot connect to Redshift: {e}")

    return critical_errors, warnings


def check_cdc_lag():
    """
    Return a dict with last CDC run time and lag.
    Uses modified_at from dla.invoices and dla.payments only
    (dla.leases has no timestamp columns).
    """
    cuid = PARAMS["CUID"]
    dla  = PARAMS["dla"]

    sql = f"""
        SELECT
            MAX(last_updated)                                     AS last_cdc_ran,
            DATEDIFF('hour', MAX(last_updated), GETDATE())        AS lag_hours
        FROM (
            SELECT MAX(modified_at) AS last_updated
            FROM {dla}.invoices
            WHERE company_uid = '{cuid}'

            UNION ALL

            SELECT MAX(modified_at)
            FROM {dla}.payments
            WHERE company_uid = '{cuid}'
        ) t
    """

    try:
        conn = psycopg2.connect(**REDSHIFT_CONFIG)
        cur  = conn.cursor()
        cur.execute(sql)
        row = cur.fetchone()
        conn.close()

        if not row or row[0] is None:
            return {
                "last_cdc_ran" : "No data found in DLA",
                "lag_hours"    : None,
                "status"       : "UNKNOWN",
            }

        last_ran  = row[0]
        lag_hours = float(row[1]) if row[1] is not None else None
        status    = "WARNING" if lag_hours and lag_hours > CDC_LAG_WARNING_HOURS else "OK"

        return {
            "last_cdc_ran" : last_ran.strftime("%Y-%m-%d %H:%M UTC"),
            "lag_hours"    : lag_hours,
            "status"       : status,
        }

    except Exception as e:
        return {
            "last_cdc_ran" : f"Query failed: {e}",
            "lag_hours"    : None,
            "status"       : "UNKNOWN",
        }


def run():
    """
    Execute all pre-flight checks and print results.

    Returns:
        (cdc_info, critical_errors)
            cdc_info       : dict  — CDC lag details for the Allure environment panel
            critical_errors: list  — non-empty means the suite should be aborted;
                                     the caller must call pytest.exit() — NOT sys.exit()
    """
    _header("Pre-Flight Checks")

    critical_errors = []

    # MySQL
    print("[CHECK] MySQL — connection and schema ...", flush=True)
    mysql_errors = check_mysql()
    if mysql_errors:
        for e in mysql_errors:
            print(f"        FAIL  {e}", flush=True)
        critical_errors.extend(mysql_errors)
    else:
        print(f"        OK    schema='{PARAMS['schema']}' — all tables found\n", flush=True)

    # Redshift
    print("[CHECK] Redshift — connection and schemas ...", flush=True)
    rs_critical, rs_warnings = check_redshift()

    if rs_critical:
        for e in rs_critical:
            print(f"        FAIL  {e}", flush=True)
        critical_errors.extend(rs_critical)
    else:
        print(
            f"        OK    "
            f"dla='{PARAMS['dla']}'  "
            f"dsa='{PARAMS['dsa']}'  "
            f"tdw='{PARAMS['tdw']}' — DLA tables found\n",
            flush=True,
        )

    for w in rs_warnings:
        print(f"        WARN  {w}", flush=True)
    if rs_warnings:
        print("", flush=True)

    # CDC lag
    print("[CHECK] CDC pipeline — last run timestamp ...", flush=True)
    cdc = check_cdc_lag()

    if cdc["status"] == "OK":
        print(
            f"        OK    Last CDC ran: {cdc['last_cdc_ran']} "
            f"({cdc['lag_hours']}h ago)\n",
            flush=True,
        )
    elif cdc["status"] == "WARNING":
        print(
            f"        WARN  Last CDC ran: {cdc['last_cdc_ran']} "
            f"({cdc['lag_hours']}h ago)\n"
            f"              Lag exceeds {CDC_LAG_WARNING_HOURS}h — delta failures may reflect "
            f"stale data, not pipeline bugs.\n",
            flush=True,
        )
    else:
        print(f"        INFO  {cdc['last_cdc_ran']}\n", flush=True)

    if critical_errors:
        _header("PRE-FLIGHT FAILED — suite aborted", char="!")
        print("  Resolve the errors above and re-run.\n", flush=True)
    else:
        _header("Pre-Flight Passed — starting tests")

    return cdc, critical_errors
