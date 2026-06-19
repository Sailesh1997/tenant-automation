"""Quick connectivity check for MySQL and Redshift before running tests."""
import mysql.connector
import psycopg2
from dotenv import load_dotenv
import os

load_dotenv()

# ── MySQL ─────────────────────────────────────────────────────────────────────
print("Connecting to MySQL...", flush=True)
try:
    conn = mysql.connector.connect(
        host=os.getenv("MYSQL_HOST"),
        port=int(os.getenv("MYSQL_PORT", 3306)),
        user=os.getenv("MYSQL_USER"),
        password=os.getenv("MYSQL_PASSWORD"),
        connect_timeout=15,
    )
    cur = conn.cursor()
    cur.execute("SHOW DATABASES")
    dbs = [r[0] for r in cur.fetchall()]
    print(f"  MySQL OK. Databases: {dbs}")

    # Check if hummingbird schema exists and has invoices
    for db in dbs:
        if db in ("information_schema", "performance_schema", "mysql", "sys"):
            continue
        try:
            cur.execute(f"SELECT COUNT(*) FROM `{db}`.invoices LIMIT 1")
            cnt = cur.fetchone()[0]
            print(f"  {db}.invoices -> {cnt} rows")
        except Exception:
            pass
    conn.close()
except Exception as e:
    print(f"  MySQL FAILED: {e}")

# ── Redshift ──────────────────────────────────────────────────────────────────
print("\nConnecting to Redshift...", flush=True)
try:
    conn = psycopg2.connect(
        host=os.getenv("REDSHIFT_HOST"),
        port=int(os.getenv("REDSHIFT_PORT", 5439)),
        dbname=os.getenv("REDSHIFT_DBNAME", "dev"),
        user=os.getenv("REDSHIFT_USER"),
        password=os.getenv("REDSHIFT_PASSWORD"),
        sslmode="require",
        connect_timeout=15,
    )
    cur = conn.cursor()
    cur.execute("""
        SELECT table_schema, table_name
        FROM information_schema.tables
        WHERE table_schema IN ('dla','tdw','dsa','customer_redshift')
        ORDER BY table_schema, table_name
    """)
    tables = cur.fetchall()
    print(f"  Redshift OK. Tables: {[f'{s}.{t}' for s,t in tables]}")

    # Check company_uids in dla.invoices
    try:
        cur.execute("SELECT DISTINCT company_uid, COUNT(*) FROM dla.invoices GROUP BY company_uid LIMIT 10")
        rows = cur.fetchall()
        print(f"  dla.invoices company_uid counts: {rows}")
    except Exception as e:
        print(f"  dla.invoices probe failed: {e}")

    conn.close()
except Exception as e:
    print(f"  Redshift FAILED: {e}")
