import os
import time
import mysql.connector
from dotenv import load_dotenv

_MAX_RETRIES = 5
_BASE_DELAY  = 2   # seconds — doubles each attempt: 2, 4, 8, 16, 32

# ── Load environment-specific .env ────────────────────────────────────────────
# ACTIVE_ENV is set by conftest.py (via --env flag) before config is imported.
# Falls back to "uat" so standalone scripts (check_conn.py etc.) still work.
_active_env = os.getenv("ACTIVE_ENV", "uat")
_env_file = os.path.join(os.path.dirname(__file__), "environments", f"{_active_env}.env")
load_dotenv(dotenv_path=_env_file, override=True)

# ── Tenant identity (MySQL side) ─────────────────────────────────────────────
_CUID   = os.getenv("CUID",         "UAT_SANDBOX")
_SCHEMA = os.getenv("MYSQL_SCHEMA", "hummingbird")
_CID    = os.getenv("COMPANY_ID",   "1")

# ── Redshift schema names — configurable per environment ─────────────────────
# These default to "dla", "dsa", "tdw" but can be overridden in any .env file.
# e.g. PROD might use dla_prod / dsa_prod / tdw_prod — just set them in prod.env
_DLA_SCHEMA = os.getenv("DLA_SCHEMA", "dla")
_DSA_SCHEMA = os.getenv("DSA_SCHEMA", "dsa")
_TDW_SCHEMA = os.getenv("TDW_SCHEMA", "tdw")

# ── MySQL connection (needed for property ID discovery) ───────────────────────
MYSQL_CONFIG = {
    "host"           : os.getenv("MYSQL_HOST"),
    "port"           : int(os.getenv("MYSQL_PORT", 3306)),
    "user"           : os.getenv("MYSQL_USER"),
    "password"       : os.getenv("MYSQL_PASSWORD"),
    "database"       : _SCHEMA,
    "connect_timeout": 30,
}

# ── Redshift / DLA / TDW ─────────────────────────────────────────────────────
REDSHIFT_CONFIG = {
    "host"           : os.getenv("REDSHIFT_HOST"),
    "port"           : int(os.getenv("REDSHIFT_PORT", 5439)),
    "dbname"         : os.getenv("REDSHIFT_DBNAME", "dev"),
    "user"           : os.getenv("REDSHIFT_USER"),
    "password"       : os.getenv("REDSHIFT_PASSWORD"),
    "sslmode"        : "require",
    "connect_timeout": 30,
}

# ── Slack ─────────────────────────────────────────────────────────────────────
SLACK_WEBHOOK = os.getenv("SLACK_WEBHOOK", "")


# ── Property ID discovery ─────────────────────────────────────────────────────
def _discover_property_ids() -> str:
    """
    Return a comma-separated list of property IDs for the active tenant.

    Priority:
      1. PROPERTY_IDS env var — explicit override, useful for subset testing
         e.g. PROPERTY_IDS=41,50  runs only those two properties.
      2. Auto-discover from MySQL: SELECT id FROM {schema}.properties
         WHERE company_id = {cid}  — works for any tenant, no manual list needed.
    """
    override = os.getenv("PROPERTY_IDS", "").strip()
    if override:
        return override

    last_exc = None
    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            conn = mysql.connector.connect(**MYSQL_CONFIG)
            cur  = conn.cursor()
            cur.execute(
                f"SELECT id FROM `{_SCHEMA}`.properties WHERE company_id = %s ORDER BY id",
                (_CID,)
            )
            pids = [str(r[0]) for r in cur.fetchall()]
            conn.close()
            break   # success — exit retry loop
        except Exception as e:
            last_exc = e
            delay = _BASE_DELAY * (2 ** (attempt - 1))
            print(
                f"\n[RETRY] MySQL property discovery — attempt {attempt}/{_MAX_RETRIES} failed: {e}",
                flush=True,
            )
            if attempt < _MAX_RETRIES:
                print(f"[RETRY] Waiting {delay}s before next attempt ...", flush=True)
                time.sleep(delay)
            else:
                raise RuntimeError(
                    f"[config] Connection lost — MySQL property ID discovery failed after "
                    f"{_MAX_RETRIES} attempts for schema={_SCHEMA}, company_id={_CID}. "
                    f"Last error: {last_exc}"
                )

    if not pids:
        raise RuntimeError(
            f"[config] No properties found for company_id={_CID} "
            f"in schema={_SCHEMA}. Check COMPANY_ID and MYSQL_SCHEMA in your env file."
        )

    print(f"[config] Auto-discovered {len(pids)} properties "
          f"for {_CUID} (company_id={_CID}): {','.join(pids[:5])}{',...' if len(pids) > 5 else ''}")
    return ",".join(pids)


# ── SQL placeholder values ────────────────────────────────────────────────────
# _pids is resolved once at import time and cached for the session.
_pids = _discover_property_ids()

PARAMS = {
    "CUID"      : _CUID,
    "schema"    : _SCHEMA,       # MySQL source schema  e.g. hummingbird
    "pids"      : _pids,
    "cid"       : _CID,
    "dla"       : _DLA_SCHEMA,   # Redshift DLA schema  e.g. dla  / dla_prod
    "dsa"       : _DSA_SCHEMA,   # Redshift DSA schema  e.g. dsa  / dsa_prod
    "tdw"       : _TDW_SCHEMA,   # Redshift TDW schema  e.g. tdw  / tdw_prod
}

print(
    f"[config] Env={os.getenv('ACTIVE_ENV','uat').upper()} | "
    f"MySQL={_SCHEMA} | DLA={_DLA_SCHEMA} | DSA={_DSA_SCHEMA} | TDW={_TDW_SCHEMA}",
    flush=True,
)


def render(sql: str) -> str:
    """
    Substitute all placeholders in a SQL string.

    Placeholders:
      {CUID}   → company_uid value          e.g. UAT_SANDBOX
      {schema} → MySQL source schema name   e.g. hummingbird
      {pids}   → comma-separated prop IDs   e.g. 41,44,47
      {cid}    → MySQL company_id           e.g. 1
      {dla}    → Redshift DLA schema name   e.g. dla  or dla_prod
      {dsa}    → Redshift DSA schema name   e.g. dsa  or dsa_prod
      {tdw}    → Redshift TDW schema name   e.g. tdw  or tdw_prod
    """
    return (
        sql
        .replace("{CUID}",   PARAMS["CUID"])
        .replace("{schema}", PARAMS["schema"])
        .replace("{pids}",   PARAMS["pids"])
        .replace("{cid}",    str(PARAMS["cid"]))
        .replace("{dla}",    PARAMS["dla"])
        .replace("{dsa}",    PARAMS["dsa"])
        .replace("{tdw}",    PARAMS["tdw"])
    )
