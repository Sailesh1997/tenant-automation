"""
Financial Aggregates — TC-1, TC-2, TC-3, TC-4, TC-5, TC-6, TC-7, TC-8, TC-9
=======================================================================================
Tests that validate financial totals, sums, and rates across MySQL -> DLA -> TDW.

Run this suite:
  python run_tests.py --env uat --tc financial_aggregates
  python run_tests.py --env prod --tc financial_aggregates
  pytest tests/test_financial_aggregates.py --env uat -v
"""

# Displayed in connection-loss error messages
TC_RANGE = "TC-1, TC-2, TC-3, TC-4, TC-5, TC-6, TC-7, TC-8, TC-9 (Financial Aggregates)"

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
# TC-1: Total Invoiced Amount Per Property
# ─────────────────────────────────────────────────────────────────────────────
_MYSQL_TC1 = """
SELECT i.property_id,
       COUNT(*)                   AS invoice_count,
       ROUND(SUM(i.subtotal), 2)  AS total_invoiced
FROM {schema}.invoices i
JOIN {schema}.properties p ON p.id = i.property_id
WHERE p.company_id     = {cid}
  AND i.property_id   IN ({pids})
  AND i.void_date     IS NULL
  AND i.voided_at     IS NULL
GROUP BY i.property_id
ORDER BY i.property_id
"""

_DLA_TC1 = """
SELECT property_id,
       COUNT(*)                   AS invoice_count,
       ROUND(SUM(subtotal), 2)    AS total_invoiced
FROM {dla}.invoices
WHERE company_uid   = '{CUID}'
  AND property_id  IN ({pids})
  AND void_date    IS NULL
  AND voided_at    IS NULL
GROUP BY property_id
ORDER BY property_id
"""


@allure.epic("Derived Value Validation")
@allure.feature("Financial Aggregates")
@allure.story("TC-1 — Total Invoiced Amount Per Property")
@allure.severity(allure.severity_level.CRITICAL)
@allure.title("TC-1: Total Invoiced Amount — MySQL vs DLA")
@allure.description(
    "Sums all non-void invoice subtotals per property and compares MySQL vs DLA. "
    "Pass rule: abs(delta) per property <= invoice_count x 0.99."
)
def test_tc1_total_invoiced_amount():
    with allure.step("Run MySQL query — hummingbird.invoices"):
        src = run_mysql(_MYSQL_TC1)
        assert not src.empty, "TC-1: MySQL returned 0 rows"
        _attach_df(src, "MySQL Result")

    with allure.step("Run DLA query — dla.invoices"):
        dla = run_redshift(_DLA_TC1)
        assert not dla.empty, "TC-1: DLA returned 0 rows"
        _attach_df(dla, "DLA Result")

    with allure.step("Merge on property_id and compute deltas"):
        m = src.merge(dla, on="property_id", suffixes=("_src", "_dla"))
        assert not m.empty, "TC-1: No matching property_ids between MySQL and DLA"
        m["delta"]     = abs(m["total_invoiced_src"].astype(float) - m["total_invoiced_dla"].astype(float))
        m["tolerance"] = m["invoice_count_src"].astype(float) * 0.99
        _attach_df(m[["property_id", "total_invoiced_src", "total_invoiced_dla", "delta", "tolerance"]], "Comparison")

    with allure.step("Assert delta <= tolerance per property"):
        fail = m[m["delta"] > m["tolerance"]]
        if not fail.empty:
            report = fail[["property_id", "total_invoiced_src", "total_invoiced_dla", "delta", "tolerance"]].to_string(index=False)
            _attach_df(fail[["property_id", "total_invoiced_src", "total_invoiced_dla", "delta", "tolerance"]], "FAILED Properties")
            post_slack(f":red_circle: *TC-1 FAILED* — Total Invoiced Amount\n```{report}```")
            pytest.fail(f"TC-1: delta exceeds tolerance for {len(fail)} property(ies)\n{report}")

    allure.attach(
        m[["property_id", "total_invoiced_src", "total_invoiced_dla", "delta"]].to_string(index=False),
        name="Final Summary",
        attachment_type=allure.attachment_type.TEXT,
    )


# ─────────────────────────────────────────────────────────────────────────────
# TC-2: Total Payments Collected Per Property
# ─────────────────────────────────────────────────────────────────────────────
_MYSQL_TC2 = """
SELECT property_id,
       COUNT(*)               AS payment_count,
       ROUND(SUM(amount), 2)  AS total_payments_collected
FROM {schema}.payments
WHERE property_id IN ({pids})
  AND credit_type = 'payment'
GROUP BY property_id
ORDER BY property_id
"""

_DLA_TC2 = """
SELECT property_id,
       COUNT(*)               AS payment_count,
       ROUND(SUM(amount), 2)  AS total_payments_collected
FROM {dla}.payments
WHERE company_uid   = '{CUID}'
  AND property_id  IN ({pids})
  AND credit_type  = 'payment'
GROUP BY property_id
ORDER BY property_id
"""


@allure.epic("Derived Value Validation")
@allure.feature("Financial Aggregates")
@allure.story("TC-2 — Total Payments Collected Per Property")
@allure.severity(allure.severity_level.CRITICAL)
@allure.title("TC-2: Total Payments Collected — MySQL vs DLA")
@allure.description(
    "Sums all payment-type transactions per property and compares MySQL vs DLA. "
    "Pass rule: abs(delta) per property <= payment_count x 0.99."
)
def test_tc2_total_payments_collected():
    with allure.step("Run MySQL query — hummingbird.payments"):
        src = run_mysql(_MYSQL_TC2)
        assert not src.empty, "TC-2: MySQL returned 0 rows"
        _attach_df(src, "MySQL Result")

    with allure.step("Run DLA query — dla.payments"):
        dla = run_redshift(_DLA_TC2)
        assert not dla.empty, "TC-2: DLA returned 0 rows"
        _attach_df(dla, "DLA Result")

    with allure.step("Merge on property_id and compute deltas"):
        m = src.merge(dla, on="property_id", suffixes=("_src", "_dla"))
        assert not m.empty, "TC-2: No matching property_ids between MySQL and DLA"
        m["delta"]     = abs(m["total_payments_collected_src"].astype(float) - m["total_payments_collected_dla"].astype(float))
        m["tolerance"] = m["payment_count_src"].astype(float) * 0.99
        _attach_df(m[["property_id", "total_payments_collected_src", "total_payments_collected_dla", "delta", "tolerance"]], "Comparison")

    with allure.step("Assert delta <= tolerance per property"):
        fail = m[m["delta"] > m["tolerance"]]
        if not fail.empty:
            report = fail[["property_id", "total_payments_collected_src", "total_payments_collected_dla", "delta", "tolerance"]].to_string(index=False)
            _attach_df(fail[["property_id", "total_payments_collected_src", "total_payments_collected_dla", "delta", "tolerance"]], "FAILED Properties")
            post_slack(f":red_circle: *TC-2 FAILED* — Total Payments Collected\n```{report}```")
            pytest.fail(f"TC-2: delta exceeds tolerance for {len(fail)} property(ies)\n{report}")

    allure.attach(
        m[["property_id", "total_payments_collected_src", "total_payments_collected_dla", "delta"]].to_string(index=False),
        name="Final Summary",
        attachment_type=allure.attachment_type.TEXT,
    )


# ─────────────────────────────────────────────────────────────────────────────
# TC-3: Average Rent Per Property  [MySQL -> DLA -> TDW]
# ─────────────────────────────────────────────────────────────────────────────
_MYSQL_TC3 = """
SELECT u.property_id,
       COUNT(l.id)             AS lease_count,
       ROUND(AVG(l.rent), 2)  AS avg_rent
FROM {schema}.leases l
JOIN {schema}.units u ON u.id = l.unit_id
WHERE u.property_id IN ({pids})
  AND l.status = 1
GROUP BY u.property_id
ORDER BY u.property_id
"""

_DLA_TC3 = """
SELECT u.property_id,
       COUNT(l.id)             AS lease_count,
       ROUND(AVG(l.rent), 2)  AS avg_rent
FROM {dla}.leases l
JOIN {dla}.units u ON u.id = l.unit_id
WHERE l.company_uid   = '{CUID}'
  AND u.property_id  IN ({pids})
  AND l.status = 1
GROUP BY u.property_id
ORDER BY u.property_id
"""

_TDW_TC3 = """
SELECT src_property_id AS property_id,
       COUNT(*)              AS lease_count,
       ROUND(AVG(rent), 2)  AS avg_rent
FROM {tdw}.tdw_lease_d
WHERE company_uid       = '{CUID}'
  AND lease_status_desc = 'moved_in'
  AND src_lease_id     <> -1
GROUP BY src_property_id
ORDER BY src_property_id
"""

TOLERANCE_TC3_PCT = 1.0   # allow <=1% avg rent difference


@allure.epic("Derived Value Validation")
@allure.feature("Financial Aggregates")
@allure.story("TC-3 — Average Rent Per Property")
@allure.severity(allure.severity_level.NORMAL)
@allure.title("TC-3: Average Rent — MySQL vs DLA vs TDW (within 1%)")
@allure.description(
    "Computes average rent for active leases (status=1) per property across MySQL, DLA, and TDW. "
    "MySQL == DLA must be within 1%. TDW (moved_in) is logged informational — semantics differ slightly."
)
def test_tc3_average_rent():
    with allure.step("Run MySQL query — hummingbird.leases"):
        src = run_mysql(_MYSQL_TC3)
        assert not src.empty, "TC-3: MySQL returned 0 rows"
        _attach_df(src, "MySQL Result")

    with allure.step("Run DLA query — dla.leases"):
        dla = run_redshift(_DLA_TC3)
        assert not dla.empty, "TC-3: DLA returned 0 rows"
        _attach_df(dla, "DLA Result")

    with allure.step("Run TDW query (informational) — tdw.tdw_lease_d"):
        try:
            tdw = run_redshift(_TDW_TC3)
            _attach_df(tdw, "TDW Result (informational)")
        except Exception as e:
            allure.attach(f"TDW query error: {e}", name="TDW Error", attachment_type=allure.attachment_type.TEXT)

    with allure.step("Merge MySQL vs DLA and compute avg_rent delta"):
        m = src.merge(dla, on="property_id", suffixes=("_src", "_dla"))
        assert not m.empty, "TC-3: No matching property_ids between MySQL and DLA"
        m["pct_delta"] = abs(
            (m["avg_rent_src"].astype(float) - m["avg_rent_dla"].astype(float))
            / m["avg_rent_src"].astype(float).replace(0, float("nan"))
            * 100
        )
        _attach_df(m[["property_id", "avg_rent_src", "avg_rent_dla", "pct_delta"]], "Comparison")

    with allure.step(f"Assert avg_rent pct_delta <= {TOLERANCE_TC3_PCT}% per property"):
        fail = m[m["pct_delta"] > TOLERANCE_TC3_PCT]
        if not fail.empty:
            report = fail[["property_id", "avg_rent_src", "avg_rent_dla", "pct_delta"]].to_string(index=False)
            _attach_df(fail[["property_id", "avg_rent_src", "avg_rent_dla", "pct_delta"]], "FAILED Properties")
            post_slack(f":red_circle: *TC-3 FAILED* — Average Rent\n```{report}```")
            pytest.fail(f"TC-3: avg_rent pct_delta > {TOLERANCE_TC3_PCT}% for {len(fail)} property(ies)\n{report}")


# ─────────────────────────────────────────────────────────────────────────────
# TC-4: Total Outstanding Invoice Balance Per Property
# ─────────────────────────────────────────────────────────────────────────────
_MYSQL_TC4 = """
SELECT property_id,
       ROUND(SUM(subtotal - total_payments - total_discounts), 2) AS outstanding_balance
FROM {schema}.invoices
WHERE property_id IN ({pids})
  AND void_date   IS NULL
  AND voided_at   IS NULL
  AND paid        = 0
GROUP BY property_id
ORDER BY property_id
"""

_DLA_TC4 = """
SELECT property_id,
       ROUND(SUM(subtotal - total_payments - total_discounts), 2) AS outstanding_balance
FROM {dla}.invoices
WHERE company_uid   = '{CUID}'
  AND property_id  IN ({pids})
  AND void_date    IS NULL
  AND voided_at    IS NULL
  AND paid         = 0
GROUP BY property_id
ORDER BY property_id
"""

TOLERANCE_TC4_PCT = 1.0


@allure.epic("Derived Value Validation")
@allure.feature("Financial Aggregates")
@allure.story("TC-4 — Total Outstanding Invoice Balance Per Property")
@allure.severity(allure.severity_level.CRITICAL)
@allure.title("TC-4: Outstanding Invoice Balance — MySQL vs DLA (within 1%)")
@allure.description(
    "Sums (subtotal - total_payments) for non-void under-paid invoices per property. "
    "Validates that unpaid AR balances replicate correctly from MySQL to DLA."
)
def test_tc4_outstanding_invoice_balance():
    with allure.step("Run MySQL query — hummingbird.invoices"):
        src = run_mysql(_MYSQL_TC4)
        assert not src.empty, "TC-4: MySQL returned 0 rows"
        _attach_df(src, "MySQL Result")

    with allure.step("Run DLA query — dla.invoices"):
        dla = run_redshift(_DLA_TC4)
        assert not dla.empty, "TC-4: DLA returned 0 rows"
        _attach_df(dla, "DLA Result")

    with allure.step("Merge on property_id and compute delta"):
        m = src.merge(dla, on="property_id", suffixes=("_src", "_dla"))
        assert not m.empty, "TC-4: No matching property_ids between MySQL and DLA"
        m["pct_delta"] = abs(
            (m["outstanding_balance_src"].astype(float) - m["outstanding_balance_dla"].astype(float))
            / m["outstanding_balance_src"].astype(float).replace(0, float("nan"))
            * 100
        )
        _attach_df(m[["property_id", "outstanding_balance_src", "outstanding_balance_dla", "pct_delta"]], "Comparison")

    with allure.step(f"Assert pct_delta <= {TOLERANCE_TC4_PCT}% per property"):
        fail = m[m["pct_delta"] > TOLERANCE_TC4_PCT]
        if not fail.empty:
            report = fail[["property_id", "outstanding_balance_src", "outstanding_balance_dla", "pct_delta"]].to_string(index=False)
            _attach_df(fail[["property_id", "outstanding_balance_src", "outstanding_balance_dla", "pct_delta"]], "FAILED Properties")
            post_slack(f":red_circle: *TC-4 FAILED* — Outstanding Invoice Balance\n```{report}```")
            pytest.fail(f"TC-4: pct_delta > {TOLERANCE_TC4_PCT}% for {len(fail)} property(ies)\n{report}")


# ─────────────────────────────────────────────────────────────────────────────
# TC-5: Refund Rate Per Property
# ─────────────────────────────────────────────────────────────────────────────
_MYSQL_TC5 = """
SELECT property_id,
       COUNT(*)  AS total_payments,
       SUM(CASE WHEN credit_type = 'refund' THEN 1 ELSE 0 END) AS refund_count,
       ROUND(
           100.0 * SUM(CASE WHEN credit_type = 'refund' THEN 1 ELSE 0 END) / COUNT(*),
           2
       ) AS refund_rate_pct
FROM {schema}.payments
WHERE property_id IN ({pids})
GROUP BY property_id
ORDER BY property_id
"""

_DLA_TC5 = """
SELECT property_id,
       COUNT(*)  AS total_payments,
       SUM(CASE WHEN credit_type = 'refund' THEN 1 ELSE 0 END) AS refund_count,
       ROUND(
           100.0 * SUM(CASE WHEN credit_type = 'refund' THEN 1 ELSE 0 END) / COUNT(*),
           2
       ) AS refund_rate_pct
FROM {dla}.payments
WHERE company_uid   = '{CUID}'
  AND property_id  IN ({pids})
GROUP BY property_id
ORDER BY property_id
"""

TOLERANCE_TC5_PPT = 0.5


@allure.epic("Derived Value Validation")
@allure.feature("Financial Aggregates")
@allure.story("TC-5 — Refund Rate Per Property")
@allure.severity(allure.severity_level.NORMAL)
@allure.title("TC-5: Refund Rate — MySQL vs DLA (within 0.5 ppt)")
@allure.description(
    "Checks refund_count / total_payments percentage per property matches MySQL vs DLA "
    "within 0.5 percentage points."
)
def test_tc5_refund_rate():
    with allure.step("Run MySQL query — hummingbird.payments"):
        src = run_mysql(_MYSQL_TC5)
        assert not src.empty, "TC-5: MySQL returned 0 rows"
        _attach_df(src, "MySQL Result")

    with allure.step("Run DLA query — dla.payments"):
        dla = run_redshift(_DLA_TC5)
        assert not dla.empty, "TC-5: DLA returned 0 rows"
        _attach_df(dla, "DLA Result")

    with allure.step("Merge on property_id and compute rate delta"):
        m = src.merge(dla, on="property_id", suffixes=("_src", "_dla"))
        assert not m.empty, "TC-5: No matching property_ids between MySQL and DLA"
        m["rate_delta"] = abs(
            m["refund_rate_pct_src"].astype(float) - m["refund_rate_pct_dla"].astype(float)
        )
        _attach_df(m[["property_id", "refund_rate_pct_src", "refund_rate_pct_dla", "rate_delta"]], "Comparison")

    with allure.step(f"Assert rate_delta <= {TOLERANCE_TC5_PPT} ppt per property"):
        fail = m[m["rate_delta"] > TOLERANCE_TC5_PPT]
        if not fail.empty:
            report = fail[["property_id", "refund_rate_pct_src", "refund_rate_pct_dla", "rate_delta"]].to_string(index=False)
            _attach_df(fail, "FAILED Properties")
            post_slack(f":red_circle: *TC-5 FAILED* — Refund Rate\n```{report}```")
            pytest.fail(f"TC-5: rate_delta > {TOLERANCE_TC5_PPT}ppt for {len(fail)} property(ies)\n{report}")


# ─────────────────────────────────────────────────────────────────────────────
# TC-6: Lease Rent Aggregate Stability DLA to TDW
# ─────────────────────────────────────────────────────────────────────────────
_DLA_TC6 = """
SELECT SUM(rent) AS total_rent_dla
FROM {dla}.leases
WHERE company_uid = '{CUID}'
  AND status = 1
"""

_TDW_TC6 = """
SELECT SUM(rent) AS total_rent_tdw
FROM {tdw}.tdw_lease_d
WHERE company_uid       = '{CUID}'
  AND lease_status_desc = 'moved_in'
  AND src_lease_id     <> -1
"""

TOLERANCE_TC6_PCT = 2.0


@allure.epic("Derived Value Validation")
@allure.feature("Financial Aggregates")
@allure.story("TC-6 — Lease Rent Aggregate Stability DLA to TDW")
@allure.severity(allure.severity_level.NORMAL)
@allure.title("TC-6: Total Rent Aggregate — DLA (TDW informational)")
@allure.description(
    "Validates total active rent is present in DLA (status=1). "
    "TDW comparison is informational only — tdw_lease_d is a dimension table "
    "and does not currently carry a rent column."
)
def test_tc6_lease_rent_aggregate_stability():
    with allure.step("Run DLA query — dla.leases active rent"):
        dla = run_redshift(_DLA_TC6)
        assert not dla.empty, "TC-6: DLA returned 0 rows"
        dla_total = float(dla["total_rent_dla"].iloc[0])
        assert dla_total > 0, "TC-6: DLA total rent is 0 — unexpected"
        _attach_df(dla, "DLA Result")

    with allure.step("Run TDW query (informational) — tdw.tdw_lease_d"):
        try:
            tdw = run_redshift(_TDW_TC6)
            if not tdw.empty and tdw["total_rent_tdw"].iloc[0] is not None:
                tdw_total = float(tdw["total_rent_tdw"].iloc[0])
                pct_delta = abs(dla_total - tdw_total) / max(dla_total, 0.01) * 100
                summary = (
                    f"DLA total_rent={dla_total:.2f}  "
                    f"TDW total_rent={tdw_total:.2f}  "
                    f"pct_delta={pct_delta:.2f}%"
                )
                allure.attach(summary, name="DLA vs TDW Comparison", attachment_type=allure.attachment_type.TEXT)
        except Exception as e:
            allure.attach(
                f"TDW rent column not available: {e}",
                name="TDW Informational (skipped)",
                attachment_type=allure.attachment_type.TEXT,
            )


# ─────────────────────────────────────────────────────────────────────────────
# TC-7: Net Revenue Per Property
# ─────────────────────────────────────────────────────────────────────────────
_MYSQL_TC7 = """
SELECT inv.property_id,
       inv.gross_invoiced,
       COALESCE(ref.total_refunds, 0)                                AS total_refunds,
       ROUND(inv.gross_invoiced - COALESCE(ref.total_refunds, 0), 2) AS net_revenue
FROM (
    SELECT property_id,
           ROUND(SUM(subtotal), 2) AS gross_invoiced
    FROM {schema}.invoices
    WHERE property_id IN ({pids})
      AND void_date  IS NULL
      AND voided_at  IS NULL
    GROUP BY property_id
) inv
LEFT JOIN (
    SELECT property_id,
           ROUND(SUM(amount), 2) AS total_refunds
    FROM {schema}.payments
    WHERE property_id IN ({pids})
      AND credit_type = 'refund'
    GROUP BY property_id
) ref ON ref.property_id = inv.property_id
ORDER BY inv.property_id
"""

_DLA_TC7 = """
SELECT inv.property_id,
       inv.gross_invoiced,
       COALESCE(ref.total_refunds, 0)                                AS total_refunds,
       ROUND(inv.gross_invoiced - COALESCE(ref.total_refunds, 0), 2) AS net_revenue
FROM (
    SELECT property_id,
           ROUND(SUM(subtotal), 2) AS gross_invoiced
    FROM {dla}.invoices
    WHERE company_uid   = '{CUID}'
      AND property_id  IN ({pids})
      AND void_date    IS NULL
      AND voided_at    IS NULL
    GROUP BY property_id
) inv
LEFT JOIN (
    SELECT property_id,
           ROUND(SUM(amount), 2) AS total_refunds
    FROM {dla}.payments
    WHERE company_uid   = '{CUID}'
      AND property_id  IN ({pids})
      AND credit_type   = 'refund'
    GROUP BY property_id
) ref ON ref.property_id = inv.property_id
ORDER BY inv.property_id
"""

TOLERANCE_TC7_PCT = 1.0


@allure.epic("Derived Value Validation")
@allure.feature("Financial Aggregates")
@allure.story("TC-7 — Net Revenue Per Property")
@allure.severity(allure.severity_level.CRITICAL)
@allure.title("TC-7: Net Revenue (gross - refunds) — MySQL vs DLA (within 1%)")
@allure.description(
    "Calculates net revenue as gross_invoiced minus total_refunds per property. "
    "Validates that the revenue calculation survives the MySQL -> DLA CDC pipeline."
)
def test_tc7_net_revenue():
    with allure.step("Run MySQL query"):
        src = run_mysql(_MYSQL_TC7)
        assert not src.empty, "TC-7: MySQL returned 0 rows"
        _attach_df(src, "MySQL Result")

    with allure.step("Run DLA query"):
        dla = run_redshift(_DLA_TC7)
        assert not dla.empty, "TC-7: DLA returned 0 rows"
        _attach_df(dla, "DLA Result")

    with allure.step("Merge and compute net_revenue delta"):
        m = src.merge(dla, on="property_id", suffixes=("_src", "_dla"))
        assert not m.empty, "TC-7: No matching property_ids"
        m["pct_delta"] = abs(
            (m["net_revenue_src"].astype(float) - m["net_revenue_dla"].astype(float))
            / m["net_revenue_src"].astype(float).replace(0, float("nan"))
            * 100
        )
        _attach_df(m[["property_id", "net_revenue_src", "net_revenue_dla", "pct_delta"]], "Comparison")

    with allure.step(f"Assert pct_delta <= {TOLERANCE_TC7_PCT}% per property"):
        fail = m[m["pct_delta"] > TOLERANCE_TC7_PCT]
        if not fail.empty:
            report = fail[["property_id", "net_revenue_src", "net_revenue_dla", "pct_delta"]].to_string(index=False)
            _attach_df(fail, "FAILED Properties")
            post_slack(f":red_circle: *TC-7 FAILED* — Net Revenue\n```{report}```")
            pytest.fail(f"TC-7: pct_delta > {TOLERANCE_TC7_PCT}% for {len(fail)} property(ies)\n{report}")


# ─────────────────────────────────────────────────────────────────────────────
# TC-8: Revenue Per Occupied Unit Per Property
# ─────────────────────────────────────────────────────────────────────────────
_MYSQL_TC8 = """
SELECT inv.property_id,
       inv.gross_invoiced,
       COALESCE(occ.occupied_units, 0) AS occupied_units,
       ROUND(inv.gross_invoiced / NULLIF(COALESCE(occ.occupied_units, 0), 0), 2) AS revenue_per_occ_unit
FROM (
    SELECT property_id,
           ROUND(SUM(subtotal), 2) AS gross_invoiced
    FROM {schema}.invoices
    WHERE property_id IN ({pids})
      AND void_date   IS NULL
      AND voided_at   IS NULL
    GROUP BY property_id
) inv
LEFT JOIN (
    SELECT u.property_id,
           COUNT(DISTINCT CASE WHEN l.status = 1 THEN l.unit_id END) AS occupied_units
    FROM {schema}.leases l
    JOIN {schema}.units u ON u.id = l.unit_id
    WHERE u.property_id IN ({pids})
    GROUP BY u.property_id
) occ ON occ.property_id = inv.property_id
ORDER BY inv.property_id
"""

_DLA_TC8 = """
SELECT inv.property_id,
       inv.gross_invoiced,
       COALESCE(occ.occupied_units, 0) AS occupied_units,
       ROUND(inv.gross_invoiced / NULLIF(COALESCE(occ.occupied_units, 0), 0), 2) AS revenue_per_occ_unit
FROM (
    SELECT property_id,
           ROUND(SUM(subtotal), 2) AS gross_invoiced
    FROM {dla}.invoices
    WHERE company_uid   = '{CUID}'
      AND property_id  IN ({pids})
      AND void_date    IS NULL
      AND voided_at    IS NULL
    GROUP BY property_id
) inv
LEFT JOIN (
    SELECT u.property_id,
           COUNT(DISTINCT CASE WHEN l.status = 1 THEN l.unit_id END) AS occupied_units
    FROM {dla}.leases l
    JOIN {dla}.units u ON u.id = l.unit_id
    WHERE l.company_uid   = '{CUID}'
      AND u.property_id  IN ({pids})
    GROUP BY u.property_id
) occ ON occ.property_id = inv.property_id
ORDER BY inv.property_id
"""

TOLERANCE_TC8_PCT = 2.0


@allure.epic("Derived Value Validation")
@allure.feature("Financial Aggregates")
@allure.story("TC-8 — Revenue Per Occupied Unit Per Property")
@allure.severity(allure.severity_level.NORMAL)
@allure.title("TC-8: Revenue Per Occupied Unit — MySQL vs DLA (within 2%)")
@allure.description(
    "Portfolio benchmark: gross invoice revenue divided by occupied unit count per property. "
    "Validates both revenue and occupancy replicate consistently."
)
def test_tc8_revenue_per_occupied_unit():
    with allure.step("Run MySQL query"):
        src = run_mysql(_MYSQL_TC8)
        assert not src.empty, "TC-8: MySQL returned 0 rows"
        _attach_df(src, "MySQL Result")

    with allure.step("Run DLA query"):
        dla = run_redshift(_DLA_TC8)
        assert not dla.empty, "TC-8: DLA returned 0 rows"
        _attach_df(dla, "DLA Result")

    with allure.step("Merge and compute delta"):
        m = src.merge(dla, on="property_id", suffixes=("_src", "_dla"))
        assert not m.empty, "TC-8: No matching property_ids"
        m["pct_delta"] = abs(
            (m["revenue_per_occ_unit_src"].astype(float) - m["revenue_per_occ_unit_dla"].astype(float))
            / m["revenue_per_occ_unit_src"].astype(float).replace(0, float("nan"))
            * 100
        )
        _attach_df(m[["property_id", "revenue_per_occ_unit_src", "revenue_per_occ_unit_dla", "pct_delta"]], "Comparison")

    with allure.step(f"Assert pct_delta <= {TOLERANCE_TC8_PCT}% per property"):
        fail = m[m["pct_delta"] > TOLERANCE_TC8_PCT]
        if not fail.empty:
            report = fail[["property_id", "revenue_per_occ_unit_src", "revenue_per_occ_unit_dla", "pct_delta"]].to_string(index=False)
            _attach_df(fail, "FAILED Properties")
            post_slack(f":red_circle: *TC-8 FAILED* — Revenue Per Occupied Unit\n```{report}```")
            pytest.fail(f"TC-8: pct_delta > {TOLERANCE_TC8_PCT}% for {len(fail)} property(ies)\n{report}")


# ─────────────────────────────────────────────────────────────────────────────
# TC-9: Discount Rate Per Property
# ─────────────────────────────────────────────────────────────────────────────
_MYSQL_TC9 = """
SELECT i.property_id,
       COUNT(DISTINCT i.id)  AS invoice_count,
       COUNT(DISTINCT CASE WHEN d.id IS NOT NULL THEN i.id END) AS discounted_invoices,
       ROUND(
           100.0 * COUNT(DISTINCT CASE WHEN d.id IS NOT NULL THEN i.id END)
               / NULLIF(COUNT(DISTINCT i.id), 0),
           2
       ) AS discount_rate_pct
FROM {schema}.invoices i
LEFT JOIN {schema}.discounts d ON d.lease_id = i.lease_id
WHERE i.property_id IN ({pids})
  AND i.void_date   IS NULL
  AND i.voided_at   IS NULL
GROUP BY i.property_id
ORDER BY i.property_id
"""

_DLA_TC9 = """
SELECT i.property_id,
       COUNT(DISTINCT i.id)  AS invoice_count,
       COUNT(DISTINCT CASE WHEN d.id IS NOT NULL THEN i.id END) AS discounted_invoices,
       ROUND(
           100.0 * COUNT(DISTINCT CASE WHEN d.id IS NOT NULL THEN i.id END)
               / NULLIF(COUNT(DISTINCT i.id), 0),
           2
       ) AS discount_rate_pct
FROM {dla}.invoices i
LEFT JOIN {dla}.discounts d ON d.lease_id = i.lease_id
WHERE i.company_uid   = '{CUID}'
  AND i.property_id  IN ({pids})
  AND i.void_date    IS NULL
  AND i.voided_at    IS NULL
GROUP BY i.property_id
ORDER BY i.property_id
"""

TOLERANCE_TC9_PPT = 0.5


@allure.epic("Derived Value Validation")
@allure.feature("Financial Aggregates")
@allure.story("TC-9 — Discount Rate Per Property")
@allure.severity(allure.severity_level.NORMAL)
@allure.title("TC-9: Discount Rate — MySQL vs DLA (within 0.5 ppt)")
@allure.description(
    "Checks the percentage of non-void invoices that have a discount applied per property. "
    "Validates discount linkage is preserved in DLA."
)
def test_tc9_discount_rate():
    with allure.step("Run MySQL query"):
        src = run_mysql(_MYSQL_TC9)
        assert not src.empty, "TC-9: MySQL returned 0 rows"
        _attach_df(src, "MySQL Result")

    with allure.step("Run DLA query"):
        dla = run_redshift(_DLA_TC9)
        assert not dla.empty, "TC-9: DLA returned 0 rows"
        _attach_df(dla, "DLA Result")

    with allure.step("Merge and compute rate delta"):
        m = src.merge(dla, on="property_id", suffixes=("_src", "_dla"))
        assert not m.empty, "TC-9: No matching property_ids"
        m["rate_delta"] = abs(
            m["discount_rate_pct_src"].astype(float) - m["discount_rate_pct_dla"].astype(float)
        )
        _attach_df(m[["property_id", "discount_rate_pct_src", "discount_rate_pct_dla", "rate_delta"]], "Comparison")

    with allure.step(f"Assert rate_delta <= {TOLERANCE_TC9_PPT} ppt per property"):
        fail = m[m["rate_delta"] > TOLERANCE_TC9_PPT]
        if not fail.empty:
            report = fail[["property_id", "discount_rate_pct_src", "discount_rate_pct_dla", "rate_delta"]].to_string(index=False)
            _attach_df(fail, "FAILED Properties")
            post_slack(f":red_circle: *TC-9 FAILED* — Discount Rate\n```{report}```")
            pytest.fail(f"TC-9: rate_delta > {TOLERANCE_TC9_PPT}ppt for {len(fail)} property(ies)\n{report}")
