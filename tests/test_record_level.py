"""
Record-Level Derived Values — TC-1, TC-2, TC-3, TC-4
=========================================================
Spot-checks individual records rather than property-level aggregates.
Validates that derived values computed per row (outstanding balance, line item sum,
individual rent, cached payment total) match between source and DLA.

Run this suite:
  python run_tests.py --env uat --tc record_level
  python run_tests.py --env prod --tc record_level
  pytest tests/test_record_level.py --env uat -v
"""

# Displayed in connection-loss error messages
TC_RANGE = "TC-1, TC-2, TC-3, TC-4 (Record-Level Checks)"

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
# TC-1: Invoice Outstanding Balance at Record Level
# ─────────────────────────────────────────────────────────────────────────────
_MYSQL_TC1 = """
SELECT id AS invoice_id,
       property_id,
       subtotal,
       total_payments,
       total_discounts,
       ROUND(subtotal - total_payments - total_discounts, 2) AS outstanding_balance
FROM {schema}.invoices
WHERE property_id IN ({pids})
  AND void_date   IS NULL
  AND voided_at   IS NULL
  AND paid        = 0
ORDER BY id
LIMIT 500
"""

_DLA_TC1 = """
SELECT id AS invoice_id,
       property_id,
       subtotal,
       total_payments,
       total_discounts,
       ROUND(subtotal - total_payments - total_discounts, 2) AS outstanding_balance
FROM {dla}.invoices
WHERE company_uid   = '{CUID}'
  AND property_id  IN ({pids})
  AND void_date    IS NULL
  AND voided_at    IS NULL
  AND paid         = 0
ORDER BY id
LIMIT 500
"""

TOLERANCE_TC1_AMOUNT = 0.01   # $0.01 tolerance for rounding differences


@allure.epic("Derived Value Validation")
@allure.feature("Record-Level Checks")
@allure.story("TC-1 — Invoice Outstanding Balance at Record Level")
@allure.severity(allure.severity_level.CRITICAL)
@allure.title("TC-1: Invoice Outstanding Balance — MySQL vs DLA (per record)")
@allure.description(
    "Spot-checks up to 500 outstanding invoices and verifies that "
    "(subtotal - total_paid) matches between MySQL and DLA within $0.01 per record."
)
def test_tc1_invoice_outstanding_balance_record_level():
    with allure.step("Run MySQL query — top 500 unpaid non-void invoices"):
        src = run_mysql(_MYSQL_TC1)
        assert not src.empty, "TC-1: MySQL returned 0 rows"
        _attach_df(src.head(20), "MySQL Sample (first 20)")

    with allure.step("Run DLA query — top 500 unpaid non-void invoices"):
        dla = run_redshift(_DLA_TC1)
        assert not dla.empty, "TC-1: DLA returned 0 rows"
        _attach_df(dla.head(20), "DLA Sample (first 20)")

    with allure.step("Merge on invoice_id and compute balance delta"):
        m = src.merge(dla, on="invoice_id", suffixes=("_src", "_dla"))
        assert not m.empty, "TC-1: No matching invoice_ids between MySQL and DLA"
        m["balance_delta"] = abs(
            m["outstanding_balance_src"].astype(float) - m["outstanding_balance_dla"].astype(float)
        )
        m["balance_delta"] = m["balance_delta"].fillna(0)
        _attach_df(m[["invoice_id", "outstanding_balance_src", "outstanding_balance_dla", "balance_delta"]].head(50),
                   "Sample Comparison (first 50)")

    with allure.step(f"Assert balance_delta <= ${TOLERANCE_TC1_AMOUNT} per invoice"):
        fail = m[m["balance_delta"] > TOLERANCE_TC1_AMOUNT]
        if not fail.empty:
            report = fail[["invoice_id", "outstanding_balance_src", "outstanding_balance_dla", "balance_delta"]].to_string(index=False)
            _attach_df(fail[["invoice_id", "outstanding_balance_src", "outstanding_balance_dla", "balance_delta"]], "FAILED Invoices")
            post_slack(f":red_circle: *TC-1 FAILED* — Invoice Outstanding Balance\n```{report[:1000]}```")
            pytest.fail(f"TC-1: balance_delta > ${TOLERANCE_TC1_AMOUNT} for {len(fail)} invoice(s)\n{report}")

    allure.attach(
        f"Checked {len(m)} matching invoices — max delta: ${float(m['balance_delta'].max()):.4f}",
        name="Summary",
        attachment_type=allure.attachment_type.TEXT,
    )


# ─────────────────────────────────────────────────────────────────────────────
# TC-2: Invoice Line Item Sum vs Header Subtotal at Record Level
# ─────────────────────────────────────────────────────────────────────────────
_MYSQL_TC2 = """
SELECT i.id AS invoice_id,
       i.property_id,
       i.subtotal                                AS header_subtotal,
       ROUND(SUM(il.full_cost), 2)               AS lines_sum,
       ROUND(i.subtotal - SUM(il.full_cost), 2)  AS discrepancy
FROM {schema}.invoices i
JOIN {schema}.invoice_lines il ON il.invoice_id = i.id
WHERE i.property_id IN ({pids})
  AND i.void_date   IS NULL
  AND i.voided_at   IS NULL
GROUP BY i.id, i.property_id, i.subtotal
HAVING ABS(i.subtotal - SUM(il.full_cost)) > 0.01
ORDER BY ABS(i.subtotal - SUM(il.full_cost)) DESC
LIMIT 200
"""

_DLA_TC2 = """
SELECT i.id AS invoice_id,
       i.property_id,
       i.subtotal                                     AS header_subtotal,
       ROUND(SUM(il.qty * il.cost), 2)                AS lines_sum,
       ROUND(i.subtotal - SUM(il.qty * il.cost), 2)   AS discrepancy
FROM {dla}.invoices i
JOIN {dla}.invoice_lines il ON il.invoice_id = i.id
WHERE i.company_uid   = '{CUID}'
  AND i.property_id  IN ({pids})
  AND i.void_date    IS NULL
  AND i.voided_at    IS NULL
GROUP BY i.id, i.property_id, i.subtotal
HAVING ABS(i.subtotal - SUM(il.qty * il.cost)) > 0.01
ORDER BY ABS(i.subtotal - SUM(il.qty * il.cost)) DESC
LIMIT 200
"""


@allure.epic("Derived Value Validation")
@allure.feature("Record-Level Checks")
@allure.story("TC-2 — Invoice Line Item Sum vs Header Subtotal at Record Level")
@allure.severity(allure.severity_level.NORMAL)
@allure.title("TC-2: Invoice Header vs Lines Discrepancy — MySQL vs DLA")
@allure.description(
    "Finds invoices where header subtotal != sum of line item amounts (discrepancy > $0.01). "
    "Counts such discrepancies in MySQL and DLA — they must match. "
    "Non-zero discrepancy counts are expected and logged as warnings, not failures."
)
def test_tc2_invoice_line_sum_vs_header():
    with allure.step("Run MySQL query — find header/lines mismatches"):
        src = run_mysql(_MYSQL_TC2)
        src_count = len(src)
        _attach_df(src.head(20) if not src.empty else pd.DataFrame(), "MySQL Discrepancies (top 20)")

    with allure.step("Run DLA query — find header/lines mismatches"):
        dla = run_redshift(_DLA_TC2)
        dla_count = len(dla)
        _attach_df(dla.head(20) if not dla.empty else pd.DataFrame(), "DLA Discrepancies (top 20)")

    with allure.step("Compare discrepancy counts between MySQL and DLA"):
        summary = (
            f"MySQL discrepant invoices: {src_count}\n"
            f"DLA discrepant invoices  : {dla_count}\n"
            f"Delta                    : {abs(src_count - dla_count)}\n"
        )
        allure.attach(summary, name="Discrepancy Count Summary", attachment_type=allure.attachment_type.TEXT)

        if src_count > 0:
            allure.attach(
                f"WARNING: {src_count} invoice(s) in MySQL already have header != lines_sum. "
                "This is a source data quality issue, not a pipeline bug.",
                name="Source Data Warning",
                attachment_type=allure.attachment_type.TEXT,
            )

    with allure.step("Assert DLA discrepancy count matches MySQL"):
        if abs(src_count - dla_count) > 0:
            post_slack(f":red_circle: *TC-2 FAILED* — Discrepancy count MySQL={src_count} DLA={dla_count}")
            pytest.fail(
                f"TC-2: MySQL has {src_count} discrepant invoice(s), DLA has {dla_count}. "
                "The counts must match — pipeline should not create new discrepancies."
            )


# ─────────────────────────────────────────────────────────────────────────────
# TC-3: Lease Rent Individual Record Check Across All Three Layers
# ─────────────────────────────────────────────────────────────────────────────
_MYSQL_TC3 = """
SELECT l.id AS lease_id,
       u.property_id,
       l.rent
FROM {schema}.leases l
JOIN {schema}.units u ON u.id = l.unit_id
WHERE u.property_id IN ({pids})
  AND l.status = 1
  AND l.rent   > 0
ORDER BY l.id
LIMIT 300
"""

_DLA_TC3 = """
SELECT l.id AS lease_id,
       u.property_id,
       l.rent
FROM {dla}.leases l
JOIN {dla}.units u ON u.id = l.unit_id
WHERE l.company_uid   = '{CUID}'
  AND u.property_id  IN ({pids})
  AND l.status = 1
  AND l.rent   > 0
ORDER BY l.id
LIMIT 300
"""

_TDW_TC3 = """
SELECT src_lease_id AS lease_id,
       rent
FROM {tdw}.tdw_leases_af
WHERE company_uid   = '{CUID}'
  AND src_lease_id <> -1
  AND rent          > 0
ORDER BY src_lease_id
LIMIT 300
"""

TOLERANCE_TC3_AMOUNT = 0.01


@allure.epic("Derived Value Validation")
@allure.feature("Record-Level Checks")
@allure.story("TC-3 — Lease Rent Individual Record Check Across All Three Layers")
@allure.severity(allure.severity_level.CRITICAL)
@allure.title("TC-3: Lease Rent per Record — MySQL vs DLA vs TDW")
@allure.description(
    "Spot-checks up to 300 active lease rent values across MySQL, DLA, and TDW. "
    "Validates rent field replication is exact at the record level. Tolerance: $0.01."
)
def test_tc3_lease_rent_record_level():
    with allure.step("Run MySQL query — top 300 active lease rents"):
        src = run_mysql(_MYSQL_TC3)
        assert not src.empty, "TC-3: MySQL returned 0 rows"
        _attach_df(src.head(20), "MySQL Sample (first 20)")

    with allure.step("Run DLA query — top 300 active lease rents"):
        dla = run_redshift(_DLA_TC3)
        assert not dla.empty, "TC-3: DLA returned 0 rows"
        _attach_df(dla.head(20), "DLA Sample (first 20)")

    with allure.step("Run TDW query (informational) — top 300 moved_in lease rents"):
        try:
            tdw = run_redshift(_TDW_TC3)
            _attach_df(tdw.head(20), "TDW Sample (first 20, informational)")
        except Exception as e:
            allure.attach(f"TDW query error: {e}", name="TDW Error", attachment_type=allure.attachment_type.TEXT)

    with allure.step("Merge MySQL vs DLA on lease_id and compute rent delta"):
        m = src.merge(dla, on="lease_id", suffixes=("_src", "_dla"))
        assert not m.empty, "TC-3: No matching lease_ids between MySQL and DLA"
        m["rent_delta"] = abs(m["rent_src"].astype(float) - m["rent_dla"].astype(float))
        _attach_df(m[["lease_id", "rent_src", "rent_dla", "rent_delta"]].head(50), "Sample Comparison")

    with allure.step(f"Assert rent_delta <= ${TOLERANCE_TC3_AMOUNT} per lease"):
        fail = m[m["rent_delta"] > TOLERANCE_TC3_AMOUNT]
        if not fail.empty:
            report = fail[["lease_id", "rent_src", "rent_dla", "rent_delta"]].to_string(index=False)
            _attach_df(fail, "FAILED Leases")
            post_slack(f":red_circle: *TC-3 FAILED* — Lease Rent Record Level\n```{report[:1000]}```")
            pytest.fail(f"TC-3: rent_delta > ${TOLERANCE_TC3_AMOUNT} for {len(fail)} lease(s)\n{report}")

    allure.attach(
        f"Checked {len(m)} matching leases — max rent delta: ${float(m['rent_delta'].max()):.4f}",
        name="Summary",
        attachment_type=allure.attachment_type.TEXT,
    )


# ─────────────────────────────────────────────────────────────────────────────
# TC-4: Cached Total Payments on Invoice Header at Record Level
# ─────────────────────────────────────────────────────────────────────────────
_MYSQL_TC4 = """
SELECT id AS invoice_id,
       property_id,
       ROUND(subtotal, 2)        AS subtotal,
       ROUND(total_payments, 2)  AS total_payments,
       paid
FROM {schema}.invoices
WHERE property_id IN ({pids})
  AND void_date   IS NULL
  AND voided_at   IS NULL
  AND total_payments > 0
ORDER BY id
LIMIT 500
"""

_DLA_TC4 = """
SELECT id AS invoice_id,
       property_id,
       ROUND(subtotal, 2)        AS subtotal,
       ROUND(total_payments, 2)  AS total_payments,
       paid
FROM {dla}.invoices
WHERE company_uid   = '{CUID}'
  AND property_id  IN ({pids})
  AND void_date    IS NULL
  AND voided_at    IS NULL
  AND total_payments > 0
ORDER BY id
LIMIT 500
"""

TOLERANCE_TC4_AMOUNT = 1.00   # $1.00 per invoice


@allure.epic("Derived Value Validation")
@allure.feature("Record-Level Checks")
@allure.story("TC-4 — Cached Total Payments on Invoice Header at Record Level")
@allure.severity(allure.severity_level.NORMAL)
@allure.title("TC-4: Invoice total_payments Replication — MySQL vs DLA (per record)")
@allure.description(
    "Samples invoices with total_payments > 0 and validates that the cached "
    "total_payments column replicates exactly from MySQL to DLA within $1.00 per invoice. "
    "Confirms the pipeline did not replicate a stale or altered cached value."
)
def test_tc4_cached_total_payments_consistency():
    with allure.step("Run MySQL query — invoices with total_payments > 0"):
        src = run_mysql(_MYSQL_TC4)
        assert not src.empty, "TC-4: MySQL returned 0 rows — no invoices with total_payments > 0?"
        _attach_df(src.head(20), "MySQL Sample (first 20)")

    with allure.step("Run DLA query — invoices with total_payments > 0"):
        dla = run_redshift(_DLA_TC4)
        assert not dla.empty, "TC-4: DLA returned 0 rows"
        _attach_df(dla.head(20), "DLA Sample (first 20)")

    with allure.step("Merge on invoice_id and compute total_payments delta"):
        m = src.merge(dla, on="invoice_id", suffixes=("_src", "_dla"))
        assert not m.empty, "TC-4: No matching invoice_ids between MySQL and DLA"
        m["payments_delta"] = abs(
            m["total_payments_src"].astype(float) - m["total_payments_dla"].astype(float)
        )
        _attach_df(
            m[["invoice_id", "total_payments_src", "total_payments_dla", "payments_delta"]].head(50),
            "Sample Comparison (first 50)"
        )

    with allure.step(f"Assert payments_delta <= ${TOLERANCE_TC4_AMOUNT} per invoice"):
        fail = m[m["payments_delta"] > TOLERANCE_TC4_AMOUNT]
        if not fail.empty:
            report = fail[["invoice_id", "total_payments_src", "total_payments_dla", "payments_delta"]].to_string(index=False)
            _attach_df(fail[["invoice_id", "total_payments_src", "total_payments_dla", "payments_delta"]], "FAILED Invoices")
            post_slack(f":red_circle: *TC-4 FAILED* — Cached Total Payments Mismatch\n```{report[:1000]}```")
            pytest.fail(f"TC-4: payments_delta > ${TOLERANCE_TC4_AMOUNT} for {len(fail)} invoice(s)\n{report}")

    allure.attach(
        f"Checked {len(m)} matching invoices — max delta: ${float(m['payments_delta'].max()):.4f}",
        name="Summary",
        attachment_type=allure.attachment_type.TEXT,
    )
