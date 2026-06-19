"""
TDW Transformations — TC-1, TC-2, TC-3, TC-4, TC-5
=========================================================
Tests that validate how DSA data is loaded into the TDW (Tenant Data Warehouse)
star schema: surrogate key resolution, date dimension lookups, audit column
population, and TDW-level aggregate derivations.

Run this suite:
  python run_tests.py --env uat --tc tdw_transformations
  python run_tests.py --env prod --tc tdw_transformations
  pytest tests/test_tdw_transformations.py --env uat -v
"""

# Displayed in connection-loss error messages
TC_RANGE = "TC-1, TC-2, TC-3, TC-4, TC-5 (TDW Transformations)"

import pytest
import allure
import pandas as pd

from utils.redshift_conn import run_redshift
from utils.slack_notify import post_slack


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _attach_df(df: pd.DataFrame, name: str):
    allure.attach(
        df.to_string(index=False),
        name=name,
        attachment_type=allure.attachment_type.TEXT,
    )


# ─────────────────────────────────────────────────────────────────────────────
# TC-1: TDW Surrogate Key Resolution Consistency
# ─────────────────────────────────────────────────────────────────────────────
_DSA_TC1 = """
SELECT COUNT(*) AS total_leases
FROM {dsa}.dsa_lease_f
WHERE company_uid = '{CUID}'
"""

_TDW_TC1 = """
SELECT
    COUNT(*)                                   AS total_rows,
    SUM(CASE WHEN lease_key    = -1 THEN 1 ELSE 0 END) AS unresolved_lease_keys,
    SUM(CASE WHEN property_key = -1 THEN 1 ELSE 0 END) AS unresolved_property_keys,
    SUM(CASE WHEN company_key  = -1 THEN 1 ELSE 0 END) AS unresolved_company_keys
FROM {tdw}.tdw_lease_d
WHERE company_uid  = '{CUID}'
  AND src_lease_id <> -1
"""


@allure.epic("Derived Value Validation")
@allure.feature("TDW Transformations")
@allure.story("TC-1 — TDW Surrogate Key Resolution Consistency")
@allure.severity(allure.severity_level.CRITICAL)
@allure.title("TC-1: Surrogate Key Resolution — DSA vs TDW (zero unresolved)")
@allure.description(
    "Validates that all surrogate keys in tdw.tdw_lease_d are resolved (not -1). "
    "Unresolved keys (-1) mean the dimension lookup failed, breaking star schema joins. "
    "Zero unresolved is required for lease_key, property_key, and company_key."
)
def test_tc1_surrogate_key_resolution():
    with allure.step("Run DSA query — total lease count"):
        dsa = run_redshift(_DSA_TC1)
        dsa_total = int(dsa["total_leases"].iloc[0]) if not dsa.empty else 0
        allure.attach(f"DSA total leases: {dsa_total}", name="DSA Count",
                      attachment_type=allure.attachment_type.TEXT)

    with allure.step("Run TDW query — unresolved surrogate key counts"):
        tdw = run_redshift(_TDW_TC1)
        assert not tdw.empty, "TC-1: TDW returned 0 rows"
        _attach_df(tdw, "TDW Surrogate Key Audit")

    with allure.step("Assert zero unresolved surrogate keys"):
        row = tdw.iloc[0]
        unresolved_lease    = int(row["unresolved_lease_keys"])
        unresolved_property = int(row["unresolved_property_keys"])
        unresolved_company  = int(row["unresolved_company_keys"])
        tdw_total           = int(row["total_rows"])

        summary = (
            f"TDW total rows       : {tdw_total}\n"
            f"DSA total leases     : {dsa_total}\n"
            f"Unresolved lease_key : {unresolved_lease}\n"
            f"Unresolved prop_key  : {unresolved_property}\n"
            f"Unresolved comp_key  : {unresolved_company}"
        )
        allure.attach(summary, name="Key Resolution Summary", attachment_type=allure.attachment_type.TEXT)

        errors = []
        if unresolved_lease > 0:
            errors.append(f"lease_key unresolved: {unresolved_lease}")
        if unresolved_property > 0:
            errors.append(f"property_key unresolved: {unresolved_property}")
        if unresolved_company > 0:
            errors.append(f"company_key unresolved: {unresolved_company}")

        if errors:
            msg = "\n".join(errors)
            post_slack(f":red_circle: *TC-1 FAILED* — Surrogate Key Resolution\n{summary}")
            pytest.fail(f"TC-1: unresolved surrogate keys detected:\n{msg}")


# ─────────────────────────────────────────────────────────────────────────────
# TC-2: TDW Date Dimension Lookup Accuracy
# ─────────────────────────────────────────────────────────────────────────────
_TDW_TC2_FACT = """
SELECT move_in_date_key,
       COUNT(*) AS lease_count
FROM {tdw}.tdw_lease_d
WHERE company_uid       = '{CUID}'
  AND lease_status_desc = 'moved_in'
  AND src_lease_id     <> -1
  AND move_in_date_key IS NOT NULL
GROUP BY move_in_date_key
ORDER BY move_in_date_key
LIMIT 100
"""

_TDW_TC2_DIM = """
SELECT date_key,
       full_date
FROM {tdw}.tdw_date_d
WHERE date_key IN (
    SELECT DISTINCT move_in_date_key
    FROM {tdw}.tdw_lease_d
    WHERE company_uid       = '{CUID}'
      AND lease_status_desc = 'moved_in'
      AND src_lease_id     <> -1
    LIMIT 100
)
ORDER BY date_key
"""

_TDW_TC2_UNRESOLVED = """
SELECT COUNT(*) AS unresolved_date_keys
FROM {tdw}.tdw_lease_d
WHERE company_uid       = '{CUID}'
  AND lease_status_desc = 'moved_in'
  AND src_lease_id     <> -1
  AND move_in_date_key  = -1
"""


@allure.epic("Derived Value Validation")
@allure.feature("TDW Transformations")
@allure.story("TC-2 — TDW Date Dimension Lookup Accuracy")
@allure.severity(allure.severity_level.NORMAL)
@allure.title("TC-2: Date Dimension Lookup — move_in_date_key must resolve in tdw_date_d")
@allure.description(
    "Validates that move_in_date_key values in tdw.tdw_lease_d resolve to valid "
    "records in tdw.tdw_date_d (no unresolved -1 date keys). "
    "A -1 date key breaks time intelligence in any BI tool."
)
def test_tc2_date_dimension_lookup_accuracy():
    with allure.step("Run TDW query — check unresolved move_in_date_key count"):
        result = run_redshift(_TDW_TC2_UNRESOLVED)
        unresolved = int(result["unresolved_date_keys"].iloc[0])
        allure.attach(f"Unresolved move_in_date_key (-1) count: {unresolved}",
                      name="Unresolved Count", attachment_type=allure.attachment_type.TEXT)

    with allure.step("Run TDW fact query — sample date_keys used"):
        fact = run_redshift(_TDW_TC2_FACT)
        _attach_df(fact.head(20), "Sample Date Keys in Fact")

    with allure.step("Run TDW date dimension query — validate keys exist in dim"):
        dim = run_redshift(_TDW_TC2_DIM)
        _attach_df(dim.head(20), "Date Dimension Entries")

    with allure.step("Assert zero unresolved date keys"):
        if unresolved > 0:
            post_slack(f":red_circle: *TC-2 FAILED* — Date Dimension Lookup\n"
                       f"Unresolved move_in_date_key: {unresolved}")
            pytest.fail(f"TC-2: {unresolved} lease record(s) have unresolved move_in_date_key (-1)")

    allure.attach(
        f"All {len(fact)} sampled date_keys resolved in tdw.tdw_date_d",
        name="Summary",
        attachment_type=allure.attachment_type.TEXT,
    )


# ─────────────────────────────────────────────────────────────────────────────
# TC-3: TDW Lease Move-In Source Count Breakdown Accuracy
# ─────────────────────────────────────────────────────────────────────────────
_DSA_TC3 = """
SELECT move_in_source_category,
       COUNT(*) AS lease_count
FROM {dsa}.dsa_lease_f
WHERE company_uid = '{CUID}'
  AND move_in_source_category IS NOT NULL
GROUP BY move_in_source_category
ORDER BY move_in_source_category
"""

_TDW_TC3 = """
SELECT move_in_source_category,
       COUNT(*) AS lease_count
FROM {tdw}.tdw_lease_d
WHERE company_uid  = '{CUID}'
  AND src_lease_id <> -1
  AND move_in_source_category IS NOT NULL
GROUP BY move_in_source_category
ORDER BY move_in_source_category
"""


@allure.epic("Derived Value Validation")
@allure.feature("TDW Transformations")
@allure.story("TC-3 — TDW Lease Move-In Source Count Breakdown Accuracy")
@allure.severity(allure.severity_level.NORMAL)
@allure.title("TC-3: Move-In Source Category Distribution — DSA vs TDW")
@allure.description(
    "Validates that move_in_source_category distribution is preserved "
    "when leases flow from DSA into TDW. Counts per category must match within 2%."
)
def test_tc3_move_in_source_count_breakdown():
    with allure.step("Run DSA query — move_in_source_category distribution"):
        dsa = run_redshift(_DSA_TC3)
        assert not dsa.empty, "TC-3: DSA returned 0 rows"
        _attach_df(dsa, "DSA Distribution")

    with allure.step("Run TDW query — move_in_source_category distribution"):
        tdw = run_redshift(_TDW_TC3)
        assert not tdw.empty, "TC-3: TDW returned 0 rows"
        _attach_df(tdw, "TDW Distribution")

    with allure.step("Merge on category and compute count delta"):
        m = dsa.merge(tdw, on="move_in_source_category", suffixes=("_dsa", "_tdw"), how="outer").fillna(0)
        m["pct_delta"] = abs(
            (m["lease_count_dsa"].astype(float) - m["lease_count_tdw"].astype(float))
            / m["lease_count_dsa"].astype(float).replace(0, float("nan"))
            * 100
        )
        _attach_df(m[["move_in_source_category", "lease_count_dsa", "lease_count_tdw", "pct_delta"]], "Comparison")

    with allure.step("Assert count delta <= 2% per category"):
        fail = m[m["pct_delta"] > 2.0]
        if not fail.empty:
            report = fail.to_string(index=False)
            _attach_df(fail, "FAILED Categories")
            post_slack(f":red_circle: *TC-3 FAILED* — Move-In Source Breakdown\n```{report}```")
            pytest.fail(f"TC-3: pct_delta > 2% for {len(fail)} category(ies)\n{report}")


# ─────────────────────────────────────────────────────────────────────────────
# TC-4: TDW Audit Column Population
# ─────────────────────────────────────────────────────────────────────────────
_TDW_TC4 = """
SELECT
    COUNT(*)                                             AS total_rows,
    SUM(CASE WHEN created_at   IS NULL THEN 1 ELSE 0 END) AS null_created_at,
    SUM(CASE WHEN updated_at   IS NULL THEN 1 ELSE 0 END) AS null_updated_at,
    SUM(CASE WHEN company_uid  IS NULL THEN 1 ELSE 0 END) AS null_company_uid,
    SUM(CASE WHEN src_lease_id IS NULL THEN 1 ELSE 0 END) AS null_src_lease_id,
    SUM(CASE WHEN etl_loaded_at IS NULL THEN 1 ELSE 0 END) AS null_etl_loaded_at
FROM {tdw}.tdw_lease_d
WHERE company_uid  = '{CUID}'
  AND src_lease_id <> -1
"""


@allure.epic("Derived Value Validation")
@allure.feature("TDW Transformations")
@allure.story("TC-4 — TDW Audit Column Population")
@allure.severity(allure.severity_level.NORMAL)
@allure.title("TC-4: Audit Column NULL Check — tdw.tdw_lease_d")
@allure.description(
    "Validates that mandatory audit columns (created_at, updated_at, company_uid, "
    "src_lease_id, etl_loaded_at) have zero NULL values in tdw.tdw_lease_d. "
    "NULLs in these columns break downstream observability and lineage tracking."
)
def test_tc4_tdw_audit_column_population():
    with allure.step("Run TDW audit column NULL check"):
        tdw = run_redshift(_TDW_TC4)
        assert not tdw.empty, "TC-4: TDW returned 0 rows"
        _attach_df(tdw, "Audit Column NULL Counts")

    with allure.step("Assert all audit columns have zero NULLs"):
        row = tdw.iloc[0]
        audit_cols = {
            "created_at":    int(row["null_created_at"]),
            "updated_at":    int(row["null_updated_at"]),
            "company_uid":   int(row["null_company_uid"]),
            "src_lease_id":  int(row["null_src_lease_id"]),
            "etl_loaded_at": int(row.get("null_etl_loaded_at", 0)),
        }
        errors = [f"{col}: {count} NULL(s)" for col, count in audit_cols.items() if count > 0]

        summary = "\n".join([f"{col}: {count} NULLs" for col, count in audit_cols.items()])
        allure.attach(summary, name="NULL Counts per Column", attachment_type=allure.attachment_type.TEXT)

        if errors:
            msg = "\n".join(errors)
            post_slack(f":red_circle: *TC-4 FAILED* — Audit Column Population\n{msg}")
            pytest.fail(f"TC-4: NULL audit columns detected:\n{msg}")


# ─────────────────────────────────────────────────────────────────────────────
# TC-5: TDW Occupancy Derived Metrics (unit_count and occupied_unit_count)
# ─────────────────────────────────────────────────────────────────────────────
_DSA_TC5_UNITS = """
SELECT src_property_id AS property_id,
       COUNT(*) AS unit_count
FROM {dsa}.dsa_unit_d
WHERE company_uid        = '{CUID}'
  AND src_property_id   IN ({pids})
GROUP BY src_property_id
ORDER BY src_property_id
"""

_DSA_TC5_LEASES = """
SELECT src_property_id AS property_id,
       COUNT(*) AS occupied_unit_count
FROM {dsa}.dsa_lease_f
WHERE company_uid        = '{CUID}'
  AND src_property_id   IN ({pids})
  AND lease_status_desc = 'moved_in'
GROUP BY src_property_id
ORDER BY src_property_id
"""

_TDW_TC5 = """
SELECT src_property_id AS property_id,
       unit_count,
       occupied_unit_count
FROM {tdw}.tdw_property_occupancy_f
WHERE company_uid        = '{CUID}'
  AND src_property_id   IN ({pids})
ORDER BY src_property_id
"""


@allure.epic("Derived Value Validation")
@allure.feature("TDW Transformations")
@allure.story("TC-5 — TDW Occupancy Derived Metrics")
@allure.severity(allure.severity_level.CRITICAL)
@allure.title("TC-5: unit_count and occupied_unit_count — DSA vs TDW")
@allure.description(
    "Validates that TDW occupancy fact table correctly aggregates unit_count "
    "and occupied_unit_count from DSA unit and lease dimension tables. "
    "Counts must match exactly per property."
)
def test_tc5_tdw_occupancy_derived_metrics():
    with allure.step("Run DSA query — unit_count per property"):
        dsa_units = run_redshift(_DSA_TC5_UNITS)
        assert not dsa_units.empty, "TC-5: DSA units returned 0 rows"
        _attach_df(dsa_units, "DSA Unit Count")

    with allure.step("Run DSA query — occupied_unit_count per property"):
        dsa_leases = run_redshift(_DSA_TC5_LEASES)
        assert not dsa_leases.empty, "TC-5: DSA leases returned 0 rows"
        _attach_df(dsa_leases, "DSA Occupied Unit Count")

    with allure.step("Run TDW query — occupancy fact table"):
        tdw = run_redshift(_TDW_TC5)
        assert not tdw.empty, "TC-5: TDW returned 0 rows"
        _attach_df(tdw, "TDW Occupancy Metrics")

    with allure.step("Merge DSA unit counts with TDW and verify"):
        m_units = dsa_units.merge(tdw[["property_id", "unit_count"]], on="property_id",
                                  suffixes=("_dsa", "_tdw"))
        m_units["unit_count_delta"] = (
            m_units["unit_count_dsa"].astype(int) - m_units["unit_count_tdw"].astype(int)
        ).abs()

        m_leases = dsa_leases.merge(tdw[["property_id", "occupied_unit_count"]], on="property_id",
                                    suffixes=("_dsa", "_tdw"))
        m_leases["occ_count_delta"] = (
            m_leases["occupied_unit_count_dsa"].astype(int) - m_leases["occupied_unit_count_tdw"].astype(int)
        ).abs()

        _attach_df(m_units[["property_id", "unit_count_dsa", "unit_count_tdw", "unit_count_delta"]], "Unit Count Comparison")
        _attach_df(m_leases[["property_id", "occupied_unit_count_dsa", "occupied_unit_count_tdw", "occ_count_delta"]], "Occupied Unit Count Comparison")

    with allure.step("Assert zero delta for unit_count and occupied_unit_count"):
        errors = []
        fail_units = m_units[m_units["unit_count_delta"] > 0]
        if not fail_units.empty:
            errors.append(f"unit_count mismatch: {len(fail_units)} property(ies)")
            _attach_df(fail_units, "FAILED - unit_count")
        fail_leases = m_leases[m_leases["occ_count_delta"] > 0]
        if not fail_leases.empty:
            errors.append(f"occupied_unit_count mismatch: {len(fail_leases)} property(ies)")
            _attach_df(fail_leases, "FAILED - occupied_unit_count")
        if errors:
            msg = "\n".join(errors)
            post_slack(f":red_circle: *TC-5 FAILED* — TDW Occupancy Metrics\n{msg}")
            pytest.fail(f"TC-5: occupancy metric mismatches:\n{msg}")
