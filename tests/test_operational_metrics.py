"""
Operational Metrics — TC-1, TC-2, TC-3, TC-4, TC-5
=========================================================
Tests that validate counts, rates, and KPIs that measure day-to-day facility
operations (occupancy, lease activity, lead pipeline, void rates, churn).

Run this suite:
  python run_tests.py --env uat --tc operational_metrics
  python run_tests.py --env prod --tc operational_metrics
  pytest tests/test_operational_metrics.py --env uat -v
"""

# Displayed in connection-loss error messages
TC_RANGE = "TC-1, TC-2, TC-3, TC-4, TC-5 (Operational Metrics)"

import pytest
import allure
import pandas as pd

from utils.mysql_conn import run_mysql
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
# TC-1: Active Lease Count Per Property
# ─────────────────────────────────────────────────────────────────────────────
_MYSQL_TC1 = """
SELECT u.property_id,
       COUNT(*) AS active_lease_count
FROM {schema}.leases l
JOIN {schema}.units u ON u.id = l.unit_id
WHERE u.property_id IN ({pids})
  AND l.status = 1
GROUP BY u.property_id
ORDER BY u.property_id
"""

_DLA_TC1 = """
SELECT u.property_id,
       COUNT(*) AS active_lease_count
FROM {dla}.leases l
JOIN {dla}.units  u ON u.id = l.unit_id
WHERE l.company_uid   = '{CUID}'
  AND u.property_id  IN ({pids})
  AND l.status = 1
GROUP BY u.property_id
ORDER BY u.property_id
"""

_TDW_TC1 = """
SELECT COUNT(*) AS active_lease_count
FROM {tdw}.tdw_lease_d
WHERE company_uid       = '{CUID}'
  AND lease_status_desc = 'moved_in'
  AND src_lease_id     <> -1
"""


@allure.epic("Derived Value Validation")
@allure.feature("Operational Counts")
@allure.story("TC-1 — Active Lease Count Per Property")
@allure.severity(allure.severity_level.CRITICAL)
@allure.title("TC-1: Active Lease Count — MySQL vs DLA vs TDW")
@allure.description(
    "Counts status=1 leases per property across MySQL and DLA (must match exactly). "
    "TDW count (lease_status_desc=moved_in) is logged as informational — expected lower by design."
)
def test_tc1_active_lease_count():
    with allure.step("Run MySQL query — hummingbird.leases"):
        src = run_mysql(_MYSQL_TC1)
        assert not src.empty, "TC-1: MySQL returned 0 rows"
        _attach_df(src, "MySQL Result")

    with allure.step("Run DLA query — dla.leases"):
        dla = run_redshift(_DLA_TC1)
        assert not dla.empty, "TC-1: DLA returned 0 rows"
        _attach_df(dla, "DLA Result")

    with allure.step("Run TDW query — tdw.tdw_lease_d (informational only)"):
        try:
            tdw = run_redshift(_TDW_TC1)
            tdw_total = int(tdw["active_lease_count"].iloc[0]) if not tdw.empty else "N/A"
        except Exception as e:
            tdw_total = f"error: {e}"
        allure.attach(
            f"TDW moved_in count: {tdw_total}\n(lower than MySQL/DLA by design — TDW uses moved_in, not status=1)",
            name="TDW Informational",
            attachment_type=allure.attachment_type.TEXT,
        )

    with allure.step("Merge on property_id and compute deltas"):
        m = src.merge(dla, on="property_id", suffixes=("_src", "_dla"))
        assert not m.empty, "TC-1: No matching property_ids between MySQL and DLA"
        m["delta"] = m["active_lease_count_src"].astype(int) - m["active_lease_count_dla"].astype(int)
        summary_note = (
            f"MySQL total : {int(src['active_lease_count'].sum())}\n"
            f"DLA total   : {int(dla['active_lease_count'].sum())}\n"
            f"TDW moved_in: {tdw_total}  (informational)"
        )
        allure.attach(summary_note, name="Layer Totals", attachment_type=allure.attachment_type.TEXT)
        _attach_df(m[["property_id", "active_lease_count_src", "active_lease_count_dla", "delta"]], "Comparison")

    with allure.step("Assert exact count match per property (MySQL == DLA)"):
        fail = m[m["delta"] != 0]
        if not fail.empty:
            report = fail[["property_id", "active_lease_count_src", "active_lease_count_dla", "delta"]].to_string(index=False)
            _attach_df(fail[["property_id", "active_lease_count_src", "active_lease_count_dla", "delta"]], "FAILED Properties")
            post_slack(f":red_circle: *TC-1 FAILED* — Active Lease Count\n```{report}```")
            pytest.fail(f"TC-1: lease count mismatch for {len(fail)} property(ies)\n{report}")


# ─────────────────────────────────────────────────────────────────────────────
# TC-2: Lead Conversion Rate Per Property
# ─────────────────────────────────────────────────────────────────────────────
_MYSQL_TC2 = """
SELECT property_id,
       COUNT(*) AS total_leads,
       SUM(CASE WHEN status = 'converted' THEN 1 ELSE 0 END) AS converted_leads,
       ROUND(
           100.0 * SUM(CASE WHEN status = 'converted' THEN 1 ELSE 0 END) / COUNT(*),
           2
       ) AS conversion_rate_pct
FROM {schema}.leads
WHERE property_id IN ({pids})
GROUP BY property_id
ORDER BY property_id
"""

_DLA_TC2 = """
SELECT property_id,
       COUNT(*) AS total_leads,
       SUM(CASE WHEN status = 'converted' THEN 1 ELSE 0 END) AS converted_leads,
       ROUND(
           100.0 * SUM(CASE WHEN status = 'converted' THEN 1 ELSE 0 END) / COUNT(*),
           2
       ) AS conversion_rate_pct
FROM {dla}.leads
WHERE company_uid  = '{CUID}'
  AND property_id IN ({pids})
GROUP BY property_id
ORDER BY property_id
"""

TOLERANCE_TC2_PPT = 0.5


@allure.epic("Derived Value Validation")
@allure.feature("Operational Rates")
@allure.story("TC-2 — Lead Conversion Rate Per Property")
@allure.severity(allure.severity_level.NORMAL)
@allure.title("TC-2: Lead Conversion Rate — MySQL vs DLA (within 0.5 ppt)")
@allure.description(
    "Checks that the percentage of leads reaching 'converted' status per property "
    "matches between MySQL and DLA within 0.5 percentage points."
)
def test_tc2_lead_conversion_rate():
    with allure.step("Run MySQL query — hummingbird.leads"):
        src = run_mysql(_MYSQL_TC2)
        assert not src.empty, "TC-2: MySQL returned 0 rows"
        _attach_df(src, "MySQL Result")

    with allure.step("Run DLA query — dla.leads"):
        dla = run_redshift(_DLA_TC2)
        assert not dla.empty, "TC-2: DLA returned 0 rows"
        _attach_df(dla, "DLA Result")

    with allure.step("Merge on property_id and compute rate delta"):
        m = src.merge(dla, on="property_id", suffixes=("_src", "_dla"))
        assert not m.empty, "TC-2: No matching property_ids between MySQL and DLA"
        m["rate_delta"] = abs(
            m["conversion_rate_pct_src"].astype(float) - m["conversion_rate_pct_dla"].astype(float)
        )
        _attach_df(
            m[["property_id", "total_leads_src", "total_leads_dla",
               "conversion_rate_pct_src", "conversion_rate_pct_dla", "rate_delta"]],
            "Comparison"
        )

    with allure.step(f"Assert rate delta <= {TOLERANCE_TC2_PPT} ppt per property"):
        fail = m[m["rate_delta"] > TOLERANCE_TC2_PPT]
        if not fail.empty:
            report = fail[["property_id", "total_leads_src", "total_leads_dla",
                           "conversion_rate_pct_src", "conversion_rate_pct_dla", "rate_delta"]].to_string(index=False)
            _attach_df(fail[["property_id", "total_leads_src", "total_leads_dla",
                              "conversion_rate_pct_src", "conversion_rate_pct_dla", "rate_delta"]], "FAILED Properties")
            post_slack(f":red_circle: *TC-2 FAILED* — Lead Conversion Rate\n```{report}```")
            pytest.fail(f"TC-2: conversion rate delta > {TOLERANCE_TC2_PPT}ppt for {len(fail)} property(ies)\n{report}")

    allure.attach(
        m[["property_id", "conversion_rate_pct_src", "conversion_rate_pct_dla", "rate_delta"]].to_string(index=False),
        name="Final Summary",
        attachment_type=allure.attachment_type.TEXT,
    )


# ─────────────────────────────────────────────────────────────────────────────
# TC-3: Occupancy Rate Per Property
# ─────────────────────────────────────────────────────────────────────────────
_MYSQL_TC3 = """
SELECT u.property_id,
       COUNT(DISTINCT u.id)                                         AS total_units,
       COUNT(DISTINCT CASE WHEN l.status = 1 THEN l.unit_id END)   AS occupied_units,
       ROUND(
           100.0 * COUNT(DISTINCT CASE WHEN l.status = 1 THEN l.unit_id END)
                 / COUNT(DISTINCT u.id),
           2
       ) AS occupancy_rate_pct
FROM {schema}.units u
LEFT JOIN {schema}.leases l ON l.unit_id = u.id
WHERE u.property_id IN ({pids})
GROUP BY u.property_id
ORDER BY u.property_id
"""

_DLA_TC3 = """
SELECT u.property_id,
       COUNT(DISTINCT u.id)                                         AS total_units,
       COUNT(DISTINCT CASE WHEN l.status = 1 THEN l.unit_id END)   AS occupied_units,
       ROUND(
           100.0 * COUNT(DISTINCT CASE WHEN l.status = 1 THEN l.unit_id END)
                 / COUNT(DISTINCT u.id),
           2
       ) AS occupancy_rate_pct
FROM {dla}.units u
LEFT JOIN {dla}.leases l ON l.unit_id = u.id
WHERE u.company_uid   = '{CUID}'
  AND u.property_id  IN ({pids})
GROUP BY u.property_id
ORDER BY u.property_id
"""

TOLERANCE_TC3_PPT = 1.0


@allure.epic("Derived Value Validation")
@allure.feature("Operational Rates")
@allure.story("TC-3 — Occupancy Rate Per Property")
@allure.severity(allure.severity_level.CRITICAL)
@allure.title("TC-3: Occupancy Rate — MySQL vs DLA (within 1.0 ppt)")
@allure.description(
    "Checks that the ratio of occupied units to total units per property matches "
    "between MySQL and DLA within 1.0 percentage point. "
    "The most important operational metric for a storage facility."
)
def test_tc3_occupancy_rate():
    with allure.step("Run MySQL query — hummingbird.units + leases"):
        src = run_mysql(_MYSQL_TC3)
        assert not src.empty, "TC-3: MySQL returned 0 rows"
        _attach_df(src, "MySQL Result")

    with allure.step("Run DLA query — dla.units + dla.leases"):
        dla = run_redshift(_DLA_TC3)
        assert not dla.empty, "TC-3: DLA returned 0 rows"
        _attach_df(dla, "DLA Result")

    with allure.step("Merge on property_id and compute rate delta"):
        m = src.merge(dla, on="property_id", suffixes=("_src", "_dla"))
        assert not m.empty, "TC-3: No matching property_ids between MySQL and DLA"
        m["rate_delta"] = abs(
            m["occupancy_rate_pct_src"].astype(float) - m["occupancy_rate_pct_dla"].astype(float)
        )
        _attach_df(
            m[["property_id", "total_units_src", "total_units_dla",
               "occupied_units_src", "occupied_units_dla",
               "occupancy_rate_pct_src", "occupancy_rate_pct_dla", "rate_delta"]],
            "Comparison"
        )

    with allure.step(f"Assert rate delta <= {TOLERANCE_TC3_PPT} ppt per property"):
        fail = m[m["rate_delta"] > TOLERANCE_TC3_PPT]
        if not fail.empty:
            report = fail[["property_id", "total_units_src", "total_units_dla",
                           "occupied_units_src", "occupied_units_dla",
                           "occupancy_rate_pct_src", "occupancy_rate_pct_dla", "rate_delta"]].to_string(index=False)
            _attach_df(fail[["property_id", "total_units_src", "total_units_dla",
                              "occupied_units_src", "occupied_units_dla",
                              "occupancy_rate_pct_src", "occupancy_rate_pct_dla", "rate_delta"]], "FAILED Properties")
            post_slack(f":red_circle: *TC-3 FAILED* — Occupancy Rate\n```{report}```")
            pytest.fail(f"TC-3: occupancy rate delta > {TOLERANCE_TC3_PPT}ppt for {len(fail)} property(ies)\n{report}")

    allure.attach(
        m[["property_id", "total_units_src", "occupied_units_src",
           "occupancy_rate_pct_src", "occupancy_rate_pct_dla", "rate_delta"]].to_string(index=False),
        name="Final Summary",
        attachment_type=allure.attachment_type.TEXT,
    )


# ─────────────────────────────────────────────────────────────────────────────
# TC-4: Void Invoice Rate Per Property
# ─────────────────────────────────────────────────────────────────────────────
_MYSQL_TC4 = """
SELECT property_id,
       COUNT(*)  AS total_invoices,
       SUM(CASE WHEN void_date IS NOT NULL OR voided_at IS NOT NULL THEN 1 ELSE 0 END) AS void_count,
       ROUND(
           100.0 * SUM(CASE WHEN void_date IS NOT NULL OR voided_at IS NOT NULL THEN 1 ELSE 0 END) / COUNT(*),
           2
       ) AS void_rate_pct
FROM {schema}.invoices
WHERE property_id IN ({pids})
GROUP BY property_id
ORDER BY property_id
"""

_DLA_TC4 = """
SELECT property_id,
       COUNT(*)  AS total_invoices,
       SUM(CASE WHEN void_date IS NOT NULL OR voided_at IS NOT NULL THEN 1 ELSE 0 END) AS void_count,
       ROUND(
           100.0 * SUM(CASE WHEN void_date IS NOT NULL OR voided_at IS NOT NULL THEN 1 ELSE 0 END) / COUNT(*),
           2
       ) AS void_rate_pct
FROM {dla}.invoices
WHERE company_uid   = '{CUID}'
  AND property_id  IN ({pids})
GROUP BY property_id
ORDER BY property_id
"""

TOLERANCE_TC4_PPT = 0.5


@allure.epic("Derived Value Validation")
@allure.feature("Operational Rates")
@allure.story("TC-4 — Void Invoice Rate Per Property")
@allure.severity(allure.severity_level.NORMAL)
@allure.title("TC-4: Void Invoice Rate — MySQL vs DLA (within 0.5 ppt)")
@allure.description(
    "Checks the percentage of voided invoices (void_date IS NOT NULL) per property "
    "matches between MySQL and DLA within 0.5 percentage points."
)
def test_tc4_void_invoice_rate():
    with allure.step("Run MySQL query — hummingbird.invoices"):
        src = run_mysql(_MYSQL_TC4)
        assert not src.empty, "TC-4: MySQL returned 0 rows"
        _attach_df(src, "MySQL Result")

    with allure.step("Run DLA query — dla.invoices"):
        dla = run_redshift(_DLA_TC4)
        assert not dla.empty, "TC-4: DLA returned 0 rows"
        _attach_df(dla, "DLA Result")

    with allure.step("Merge on property_id and compute rate delta"):
        m = src.merge(dla, on="property_id", suffixes=("_src", "_dla"))
        assert not m.empty, "TC-4: No matching property_ids between MySQL and DLA"
        m["rate_delta"] = abs(
            m["void_rate_pct_src"].astype(float) - m["void_rate_pct_dla"].astype(float)
        )
        _attach_df(m[["property_id", "void_rate_pct_src", "void_rate_pct_dla", "rate_delta"]], "Comparison")

    with allure.step(f"Assert rate_delta <= {TOLERANCE_TC4_PPT} ppt per property"):
        fail = m[m["rate_delta"] > TOLERANCE_TC4_PPT]
        if not fail.empty:
            report = fail[["property_id", "void_rate_pct_src", "void_rate_pct_dla", "rate_delta"]].to_string(index=False)
            _attach_df(fail, "FAILED Properties")
            post_slack(f":red_circle: *TC-4 FAILED* — Void Invoice Rate\n```{report}```")
            pytest.fail(f"TC-4: rate_delta > {TOLERANCE_TC4_PPT}ppt for {len(fail)} property(ies)\n{report}")


# ─────────────────────────────────────────────────────────────────────────────
# TC-5: Lease Churn Rate Per Property
# ─────────────────────────────────────────────────────────────────────────────
_MYSQL_TC5 = """
SELECT u.property_id,
       COUNT(DISTINCT l.id)                                             AS total_leases,
       COUNT(DISTINCT CASE WHEN l.status = 0 THEN l.id END)            AS moved_out_leases,
       ROUND(
           100.0 * COUNT(DISTINCT CASE WHEN l.status = 0 THEN l.id END)
                 / NULLIF(COUNT(DISTINCT l.id), 0),
           2
       ) AS churn_rate_pct
FROM {schema}.leases l
JOIN {schema}.units u ON u.id = l.unit_id
WHERE u.property_id IN ({pids})
GROUP BY u.property_id
ORDER BY u.property_id
"""

_DLA_TC5 = """
SELECT u.property_id,
       COUNT(DISTINCT l.id)                                             AS total_leases,
       COUNT(DISTINCT CASE WHEN l.status = 0 THEN l.id END)            AS moved_out_leases,
       ROUND(
           100.0 * COUNT(DISTINCT CASE WHEN l.status = 0 THEN l.id END)
                 / NULLIF(COUNT(DISTINCT l.id), 0),
           2
       ) AS churn_rate_pct
FROM {dla}.leases l
JOIN {dla}.units u ON u.id = l.unit_id
WHERE l.company_uid   = '{CUID}'
  AND u.property_id  IN ({pids})
GROUP BY u.property_id
ORDER BY u.property_id
"""

TOLERANCE_TC5_PPT = 0.5


@allure.epic("Derived Value Validation")
@allure.feature("Operational Rates")
@allure.story("TC-5 — Lease Churn Rate Per Property")
@allure.severity(allure.severity_level.NORMAL)
@allure.title("TC-5: Lease Churn Rate — MySQL vs DLA (within 0.5 ppt)")
@allure.description(
    "Checks the percentage of leases with status=0 (moved-out) per property matches "
    "between MySQL and DLA within 0.5 percentage points."
)
def test_tc5_lease_churn_rate():
    with allure.step("Run MySQL query — hummingbird.leases"):
        src = run_mysql(_MYSQL_TC5)
        assert not src.empty, "TC-5: MySQL returned 0 rows"
        _attach_df(src, "MySQL Result")

    with allure.step("Run DLA query — dla.leases"):
        dla = run_redshift(_DLA_TC5)
        assert not dla.empty, "TC-5: DLA returned 0 rows"
        _attach_df(dla, "DLA Result")

    with allure.step("Merge on property_id and compute rate delta"):
        m = src.merge(dla, on="property_id", suffixes=("_src", "_dla"))
        assert not m.empty, "TC-5: No matching property_ids"
        m["rate_delta"] = abs(
            m["churn_rate_pct_src"].astype(float) - m["churn_rate_pct_dla"].astype(float)
        )
        _attach_df(m[["property_id", "churn_rate_pct_src", "churn_rate_pct_dla", "rate_delta"]], "Comparison")

    with allure.step(f"Assert rate_delta <= {TOLERANCE_TC5_PPT} ppt per property"):
        fail = m[m["rate_delta"] > TOLERANCE_TC5_PPT]
        if not fail.empty:
            report = fail[["property_id", "churn_rate_pct_src", "churn_rate_pct_dla", "rate_delta"]].to_string(index=False)
            _attach_df(fail, "FAILED Properties")
            post_slack(f":red_circle: *TC-5 FAILED* — Lease Churn Rate\n```{report}```")
            pytest.fail(f"TC-5: rate_delta > {TOLERANCE_TC5_PPT}ppt for {len(fail)} property(ies)\n{report}")
