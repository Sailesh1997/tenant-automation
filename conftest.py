"""
conftest.py - Global pytest configuration

  - Adds --env flag (uat | prod)
  - Loads the correct environment file before any test module imports config
  - Runs pre-flight checks once before the suite starts (master process only)
  - Writes Allure environment.properties including CDC lag info
  - Catches connection failures and reports them as clean test failures
"""

import sys
import os

import pytest
import allure
from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(__file__))


def pytest_addoption(parser):
    parser.addoption(
        "--env",
        action="store",
        default="uat",
        choices=["uat", "prod"],
        help="Target environment: uat (default) or prod",
    )


def pytest_configure(config):
    env      = config.getoption("--env", default="uat")
    env_file = os.path.join(os.path.dirname(__file__), "environments", f"{env}.env")

    if not os.path.exists(env_file):
        raise FileNotFoundError(
            f"Environment file not found: {env_file}\n"
            f"Create environments/{env}.env to continue."
        )

    os.environ["ACTIVE_ENV"] = env
    load_dotenv(dotenv_path=env_file, override=True)

    # Pre-flight runs only in the master process.
    # With pytest-xdist each worker also calls pytest_configure,
    # but workers have 'workerinput' set — we skip pre-flight there.
    is_worker = hasattr(config, "workerinput")

    if not is_worker:
        from utils.preflight import run as run_preflight
        cdc_info, preflight_errors = run_preflight()
        if preflight_errors:
            pytest.exit(
                f"Pre-flight failed — resolve DB errors and re-run.\n"
                + "\n".join(f"  • {e}" for e in preflight_errors),
                returncode=1,
            )
    else:
        cdc_info = {}

    allure_dir = config.getoption("--alluredir", default=None)
    if allure_dir and not is_worker:
        os.makedirs(allure_dir, exist_ok=True)
        _write_allure_env(allure_dir, env, cdc_info)

    if hasattr(config, "_metadata"):
        config._metadata["Environment"]  = env.upper()
        config._metadata["Company UID"]  = os.getenv("CUID", "N/A")
        config._metadata["MySQL Schema"] = os.getenv("MYSQL_SCHEMA", "N/A")
        config._metadata["Redshift DB"]  = os.getenv("REDSHIFT_DBNAME", "N/A")


def pytest_runtest_call(item):
    """Convert ConnectionError into a readable test failure message."""
    try:
        item.runtest()
    except ConnectionError as exc:
        tc_range = getattr(item.module, "TC_RANGE", None)
        msg = (
            f"Connection lost — {tc_range} could not be performed.\n\nDetail: {exc}"
            if tc_range
            else f"Connection lost — {item.name} could not be performed.\n\nDetail: {exc}"
        )
        try:
            allure.attach(
                str(exc),
                name="Connection Error Detail",
                attachment_type=allure.attachment_type.TEXT,
            )
        except Exception:
            pass
        pytest.fail(msg, pytrace=False)


def _write_allure_env(allure_dir, env, cdc_info=None):
    """Write environment.properties for the Allure Overview panel."""
    props = {
        "Environment"   : env.upper(),
        "Company_UID"   : os.getenv("CUID",          "N/A"),
        "MySQL_Schema"  : os.getenv("MYSQL_SCHEMA",   "N/A"),
        "MySQL_Host"    : os.getenv("MYSQL_HOST",     "N/A"),
        "Redshift_Host" : os.getenv("REDSHIFT_HOST",  "N/A"),
        "Redshift_DB"   : os.getenv("REDSHIFT_DBNAME","N/A"),
        "DLA_Schema"    : os.getenv("DLA_SCHEMA",     "dla"),
        "DSA_Schema"    : os.getenv("DSA_SCHEMA",     "dsa"),
        "TDW_Schema"    : os.getenv("TDW_SCHEMA",     "tdw"),
    }

    if cdc_info:
        props["CDC_Last_Ran"]  = str(cdc_info.get("last_cdc_ran", "N/A"))
        props["CDC_Lag_Hours"] = str(cdc_info.get("lag_hours",    "N/A"))
        props["CDC_Status"]    = str(cdc_info.get("status",       "N/A"))

    with open(os.path.join(allure_dir, "environment.properties"), "w") as f:
        for key, value in props.items():
            f.write(f"{key}={value}\n")
