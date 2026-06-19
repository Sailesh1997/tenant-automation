"""
Data Quality — TC-1, TC-2, TC-3, TC-4, TC-5, TC-6, TC-7
================================================================
Tests that catch structural issues, null handling, flag mismatches,
distribution drift, and time-based anomalies in the pipeline.

Run this suite:
  python run_tests.py --env uat --tc data_quality
  python run_tests.py --env prod --tc data_quality
  pytest tests/test_data_quality.py --env uat -v
"""

# Displayed in connection-loss error messages
TC_RANGE = "TC-1, TC-2, TC-3, TC-4, TC-5, TC-6, TC-7 (Data Quality)"

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
# TC-1: Payment Method Distribution Per Property
# ─────────────────────────────────────────────────────────────────────────────
_MYSQL_TC1 = """
SELECT property_id,
       method,
       COUNT(*) AS payment_count
FROM {schema}.payments
WHERE property_id IN ({pids})
  AND credit_type = 'payment'
GROUP BY property_id, method
ORDER BY property_id, method
"""

_DLA_TC1 = """
SELECT property_id,
       method,
       COUNT(*) AS payment_count
FROM {dla}.payments
WHERE company_uid   = '{CUID}'
  AND property_id  IN ({pids})
  AND credit_type  = 'payment'
GROUP BY property_id, method
ORDER BY property_id, method
"""


@allure.epic("Derived Value Validation")
@allure.feature("Data Quality")
@allure.story("TC-1 — Payment Method Distribution Per Property")
@allure.severity(allure.severity_level.NORMAL)
@allure.title("TC-1: Payment Method Distribution — MySQL vs DLA")
@allure.description(
    "Checks that the distribution of payment credit_types (payment, refund, etc.) "
    "per property matches exactly between MySQL and DLA. "
    "Drift here means CDC is dropping or misclassifying payment records."
)
def test_tc1_payment_method_distribution():
    with allure.step("Run MySQL query — hummingbird.payments"):
        src = run_mysql(_MYSQL_TC1)
        assert not src.empty, "TC-1: MySQL returned 0 rows"
        _attach_df(src, "MySQL Result")

    with allure.step("Run DLA query — dla.payments"):
        dla = run_redshift(_DLA_TC1)
        assert not dla.empty, "TC-1: DLA returned 0 rows"
        _attach_df(dla, "DLA Result")

    with allure.step("Merge on (property_id, method) and compare counts"):
        m = src.merge(dla, on=["property_id", "method"], suffixes=("_src", "_dla"), how="outer")
        m = m.fillna(0)
        m["delta"] = (m["payment_count_src"].astype(int) - m["payment_count_dla"].astype(int)).abs()
        _attach_df(m[["property_id", "method", "payment_count_src", "payment_count_dla", "delta"]], "Comparison")

    with allure.step("Assert zero delta for all (property_id, method) combos"):
        fail = m[m["delta"] > 0]
        if not fail.empty:
            report = fail.to_string(index=False)
            _attach_df(fail, "FAILED Rows")
            post_slack(f":red_circle: *TC-1 FAILED* — Payment Method Distribution\n```{report}```")
            pytest.fail(f"TC-1: {len(fail)} (property, method) combos have count mismatch\n{report}")


# ─────────────────────────────────────────────────────────────────────────────
# TC-2: Average Days from Lead Created to Converted
# ─────────────────────────────────────────────────────────────────────────────
_MYSQL_TC2 = """
SELECT property_id,
       ROUND(AVG(DATEDIFF(modified, created)), 1) AS avg_days_to_convert
FROM {schema}.leads
WHERE property_id  IN ({pids})
  AND status       = 'converted'
  AND lease_id    IS NOT NULL
GROUP BY property_id
ORDER BY property_id
"""

_DLA_TC2 = """
SELECT property_id,
       ROUND(AVG(DATEDIFF('day', created, modified)), 1) AS avg_days_to_convert
FROM {dla}.leads
WHERE company_uid   = '{CUID}'
  AND property_id  IN ({pids})
  AND status       = 'converted'
  AND lease_id    IS NOT NULL
GROUP BY property_id
ORDER BY property_id
"""

TOLERANCE_TC2_DAYS = 1.0


@allure.epic("Derived Value Validation")
@allure.feature("Data Quality")
@allure.story("TC-2 — Average Days from Lead Created to Converted")
@allure.severity(allure.severity_level.NORMAL)
@allure.title("TC-2: Avg Lead Conversion Days — MySQL vs DLA (within 1 day)")
@allure.description(
    "Validates that the average time (days) from lead creation to conversion "
    "matches between MySQL and DLA within 1 day. "
    "Timestamp drift in CDC would surface here."
)
def test_tc2_avg_days_lead_to_converted():
    with allure.step("Run MySQL query — hummingbird.leads"):
        src = run_mysql(_MYSQL_TC2)
        assert not src.empty, "TC-2: MySQL returned 0 rows — no converted leads?"
        _attach_df(src, "MySQL Result")

    with allure.step("Run DLA query — dla.leads"):
        dla = run_redshift(_DLA_TC2)
        assert not dla.empty, "TC-2: DLA returned 0 rows"
        _attach_df(dla, "DLA Result")

    with allure.step("Merge on property_id and compute days delta"):
        m = src.merge(dla, on="property_id", suffixes=("_src", "_dla"))
        assert not m.empty, "TC-2: No matching property_ids"
        m["days_delta"] = abs(
            m["avg_days_to_convert_src"].astype(float) - m["avg_days_to_convert_dla"].astype(float)
        )
        _attach_df(m[["property_id", "avg_days_to_convert_src", "avg_days_to_convert_dla", "days_delta"]], "Comparison")

    with allure.step(f"Assert days_delta <= {TOLERANCE_TC2_DAYS} per property"):
        fail = m[m["days_delta"] > TOLERANCE_TC2_DAYS]
        if not fail.empty:
            report = fail[["property_id", "avg_days_to_convert_src", "avg_days_to_convert_dla", "days_delta"]].to_string(index=False)
            _attach_df(fail, "FAILED Properties")
            post_slack(f":red_circle: *TC-2 FAILED* — Avg Days Lead to Converted\n```{report}```")
            pytest.fail(f"TC-2: days_delta > {TOLERANCE_TC2_DAYS} for {len(fail)} property(ies)\n{report}")


# ─────────────────────────────────────────────────────────────────────────────
# TC-3: Non-Void Invoices With Zero Line Items
# ─────────────────────────────────────────────────────────────────────────────
_MYSQL_TC3 = """
SELECT i.property_id,
       COUNT(DISTINCT i.id) AS invoices_with_no_lines
FROM {schema}.invoices i
LEFT JOIN {schema}.invoice_lines il ON il.invoice_id = i.id
WHERE i.property_id IN ({pids})
  AND i.void_date   IS NULL
  AND i.voided_at   IS NULL
  AND il.id         IS NULL
GROUP BY i.property_id
ORDER BY i.property_id
"""

_DLA_TC3 = """
SELECT i.property_id,
       COUNT(DISTINCT i.id) AS invoices_with_no_lines
FROM {dla}.invoices i
LEFT JOIN {dla}.invoice_lines il ON il.invoice_id = i.id
WHERE i.company_uid  = '{CUID}'
  AND i.property_id IN ({pids})
  AND i.void_date   IS NULL
  AND i.voided_at   IS NULL
  AND il.id         IS NULL
GROUP BY i.property_id
ORDER BY i.property_id
"""


@allure.epic("Derived Value Validation")
@allure.feature("Data Quality")
@allure.story("TC-3 — Non-Void Invoices With Zero Line Items")
@allure.severity(allure.severity_level.MINOR)
@allure.title("TC-3: Headerless Invoices — MySQL vs DLA (count match)")
@allure.description(
    "Counts non-void invoices that have no invoice_items records. "
    "These orphan invoice headers indicate data integrity gaps. "
    "MySQL and DLA counts must match exactly."
)
def test_tc3_invoices_with_no_line_items():
    with allure.step("Run MySQL query"):
        src = run_mysql(_MYSQL_TC3)
        # Empty result = no orphan invoices = that's fine
        _attach_df(src if not src.empty else pd.DataFrame({"property_id": [], "invoices_with_no_lines": []}), "MySQL Result")

    with allure.step("Run DLA query"):
        dla = run_redshift(_DLA_TC3)
        _attach_df(dla if not dla.empty else pd.DataFrame({"property_id": [], "invoices_with_no_lines": []}), "DLA Result")

    with allure.step("Compare orphan invoice counts"):
        if src.empty and dla.empty:
            allure.attach("Both MySQL and DLA have zero orphan invoices — PASS", name="Result",
                          attachment_type=allure.attachment_type.TEXT)
            return

        m = src.merge(dla, on="property_id", suffixes=("_src", "_dla"), how="outer").fillna(0)
        m["delta"] = (m["invoices_with_no_lines_src"].astype(int) - m["invoices_with_no_lines_dla"].astype(int)).abs()
        _attach_df(m, "Comparison")

    with allure.step("Assert orphan count matches exactly MySQL vs DLA"):
        fail = m[m["delta"] > 0]
        if not fail.empty:
            report = fail.to_string(index=False)
            _attach_df(fail, "FAILED Properties")
            post_slack(f":red_circle: *TC-3 FAILED* — Orphan Invoice Count Mismatch\n```{report}```")
            pytest.fail(f"TC-3: orphan invoice count mismatch for {len(fail)} property(ies)\n{report}")


# ─────────────────────────────────────────────────────────────────────────────
# TC-4: Contact Status Distribution Across All Layers
# NOTE: TDW uses status_cd / status_desc — NOT a bare 'status' column.
#       MySQL and DLA use status text directly.
# ─────────────────────────────────────────────────────────────────────────────
_MYSQL_TC4 = """
SELECT status,
       COUNT(*) AS contact_count
FROM {schema}.contacts
WHERE company_id = {cid}
GROUP BY status
ORDER BY status
"""

_DLA_TC4 = """
SELECT status,
       COUNT(*) AS contact_count
FROM {dla}.contacts
WHERE company_uid = '{CUID}'
GROUP BY status
ORDER BY status
"""

_TDW_TC4 = """
SELECT status_desc AS status,
       COUNT(*)    AS contact_count
FROM {tdw}.tdw_contact_d
WHERE company_uid  = '{CUID}'
  AND src_contact_id <> -1
GROUP BY status_desc
ORDER BY status_desc
"""


@allure.epic("Derived Value Validation")
@allure.feature("Data Quality")
@allure.story("TC-4 — Contact Status Distribution Across All Layers")
@allure.severity(allure.severity_level.NORMAL)
@allure.title("TC-4: Contact Status Distribution — MySQL vs DLA vs TDW")
@allure.description(
    "Checks that the distribution of contact statuses matches across MySQL, DLA, and TDW. "
    "MySQL and DLA must match exactly. TDW is informational (uses status_desc). "
    "Note: TDW uses status_cd / status_desc columns, not a raw 'status' column."
)
def test_tc4_contact_status_distribution():
    with allure.step("Run MySQL query — hummingbird.contacts"):
        src = run_mysql(_MYSQL_TC4)
        assert not src.empty, "TC-4: MySQL returned 0 rows"
        _attach_df(src, "MySQL Result")

    with allure.step("Run DLA query — dla.contacts"):
        dla = run_redshift(_DLA_TC4)
        assert not dla.empty, "TC-4: DLA returned 0 rows"
        _attach_df(dla, "DLA Result")

    with allure.step("Run TDW query (informational) — tdw.tdw_contact_d"):
        try:
            tdw = run_redshift(_TDW_TC4)
            _attach_df(tdw, "TDW Result (informational)")
        except Exception as e:
            allure.attach(f"TDW query error: {e}", name="TDW Error", attachment_type=allure.attachment_type.TEXT)

    with allure.step("Compare MySQL vs DLA contact status distribution"):
        m = src.merge(dla, on="status", suffixes=("_src", "_dla"), how="outer").fillna(0)
        m["delta"] = (m["contact_count_src"].astype(int) - m["contact_count_dla"].astype(int)).abs()
        _attach_df(m[["status", "contact_count_src", "contact_count_dla", "delta"]], "Comparison")

    with allure.step("Assert contact count matches exactly per status (MySQL == DLA)"):
        fail = m[m["delta"] > 0]
        if not fail.empty:
            report = fail.to_string(index=False)
            _attach_df(fail, "FAILED Statuses")
            post_slack(f":red_circle: *TC-4 FAILED* — Contact Status Distribution\n```{report}```")
            pytest.fail(f"TC-4: {len(fail)} status bucket(s) mismatched\n{report}")


# ─────────────────────────────────────────────────────────────────────────────
# TC-5: Invoice Paid Flag Matches Actual Payment Coverage
# ─────────────────────────────────────────────────────────────────────────────
_MYSQL_TC5 = """
SELECT property_id,
       COUNT(*)  AS invoice_count,
       SUM(CASE WHEN total_payments >= subtotal THEN 1 ELSE 0 END) AS fully_paid_count,
       SUM(CASE WHEN paid = 1                   THEN 1 ELSE 0 END) AS paid_flag_count,
       SUM(CASE
               WHEN (total_payments >= subtotal AND paid != 1)
                 OR (total_payments < subtotal  AND paid  = 1)
               THEN 1 ELSE 0 END) AS flag_mismatch_count
FROM {schema}.invoices
WHERE property_id IN ({pids})
  AND void_date   IS NULL
  AND voided_at   IS NULL
GROUP BY property_id
ORDER BY property_id
"""

_DLA_TC5 = """
SELECT property_id,
       COUNT(*)  AS invoice_count,
       SUM(CASE WHEN total_payments >= subtotal THEN 1 ELSE 0 END) AS fully_paid_count,
       SUM(CASE WHEN paid = 1                   THEN 1 ELSE 0 END) AS paid_flag_count,
       SUM(CASE
               WHEN (total_payments >= subtotal AND paid != 1)
                 OR (total_payments < subtotal  AND paid  = 1)
               THEN 1 ELSE 0 END) AS flag_mismatch_count
FROM {dla}.invoices
WHERE company_uid   = '{CUID}'
  AND property_id  IN ({pids})
  AND void_date    IS NULL
  AND voided_at    IS NULL
GROUP BY property_id
ORDER BY property_id
"""


@allure.epic("Derived Value Validation")
@allure.feature("Data Quality")
@allure.story("TC-5 — Invoice Paid Flag Matches Actual Payment Coverage")
@allure.severity(allure.severity_level.CRITICAL)
@allure.title("TC-5: Invoice Paid Flag Consistency — MySQL vs DLA")
@allure.description(
    "Validates that the paid flag on invoice headers matches whether total_paid >= subtotal. "
    "A non-zero flag_mismatch_count means derived 'paid' flags are inconsistent. "
    "Both MySQL and DLA mismatch counts are checked and must match each other."
)
def test_tc5_invoice_paid_flag_consistency():
    with allure.step("Run MySQL query"):
        src = run_mysql(_MYSQL_TC5)
        assert not src.empty, "TC-5: MySQL returned 0 rows"
        _attach_df(src, "MySQL Result")

    with allure.step("Run DLA query"):
        dla = run_redshift(_DLA_TC5)
        assert not dla.empty, "TC-5: DLA returned 0 rows"
        _attach_df(dla, "DLA Result")

    with allure.step("Merge and check flag_mismatch_count"):
        m = src.merge(dla, on="property_id", suffixes=("_src", "_dla"))
        assert not m.empty, "TC-5: No matching property_ids"
        m["mismatch_delta"] = (
            m["flag_mismatch_count_src"].astype(int) - m["flag_mismatch_count_dla"].astype(int)
        ).abs()
        _attach_df(
            m[["property_id", "flag_mismatch_count_src", "flag_mismatch_count_dla", "mismatch_delta"]],
            "Comparison"
        )

    with allure.step("Assert flag_mismatch_count is identical in MySQL and DLA"):
        fail = m[m["mismatch_delta"] > 0]
        if not fail.empty:
            report = fail.to_string(index=False)
            _attach_df(fail, "FAILED Properties")
            post_slack(f":red_circle: *TC-5 FAILED* — Paid Flag Mismatch\n```{report}```")
            pytest.fail(f"TC-5: paid flag mismatch count differs for {len(fail)} property(ies)\n{report}")

    with allure.step("Report any existing flag inconsistencies in MySQL source"):
        src_mismatches = src[src["flag_mismatch_count"] > 0]
        if not src_mismatches.empty:
            allure.attach(
                f"WARNING: MySQL already has {int(src_mismatches['flag_mismatch_count'].sum())} "
                f"invoice(s) where paid flag != actual payment coverage.\n"
                + src_mismatches.to_string(index=False),
                name="Source Data Warning",
                attachment_type=allure.attachment_type.TEXT,
            )


# ─────────────────────────────────────────────────────────────────────────────
# TC-6: Delinquency Rate Per Property
# ─────────────────────────────────────────────────────────────────────────────
_MYSQL_TC6 = """
SELECT i.property_id,
       COUNT(*) AS total_unpaid,
       SUM(CASE WHEN i.due < CURDATE() THEN 1 ELSE 0 END) AS overdue_count,
       ROUND(100.0 * SUM(CASE WHEN i.due < CURDATE() THEN 1 ELSE 0 END) / COUNT(*), 2) AS delinquency_rate_pct
FROM {schema}.invoices i
JOIN {schema}.properties p ON p.id = i.property_id
WHERE p.company_id = {cid}
  AND i.property_id IN ({pids})
  AND i.void_date IS NULL
  AND i.voided_at IS NULL
  AND i.paid = 0
GROUP BY i.property_id
ORDER BY i.property_id
"""

_DLA_TC6 = """
SELECT property_id,
       COUNT(*) AS total_unpaid,
       SUM(CASE WHEN due < CURRENT_DATE THEN 1 ELSE 0 END) AS overdue_count,
       ROUND(100.0 * SUM(CASE WHEN due < CURRENT_DATE THEN 1 ELSE 0 END) / COUNT(*), 2) AS delinquency_rate_pct
FROM {dla}.invoices
WHERE company_uid   = '{CUID}'
  AND property_id  IN ({pids})
  AND void_date    IS NULL
  AND voided_at    IS NULL
  AND paid          = 0
GROUP BY property_id
ORDER BY property_id
"""

TOLERANCE_TC6_PPT = 0.5


@allure.epic("Derived Value Validation")
@allure.feature("Data Quality")
@allure.story("TC-6 — Delinquency Rate Per Property")
@allure.severity(allure.severity_level.CRITICAL)
@allure.title("TC-6: Delinquency Rate — MySQL vs DLA (within 0.5 ppt)")
@allure.description(
    "Checks the percentage of overdue, unpaid, non-void invoices per property matches "
    "between MySQL and DLA within 0.5 percentage points."
)
def test_tc6_delinquency_rate():
    with allure.step("Run MySQL query"):
        src = run_mysql(_MYSQL_TC6)
        assert not src.empty, "TC-6: MySQL returned 0 rows"
        _attach_df(src, "MySQL Result")

    with allure.step("Run DLA query"):
        dla = run_redshift(_DLA_TC6)
        assert not dla.empty, "TC-6: DLA returned 0 rows"
        _attach_df(dla, "DLA Result")

    with allure.step("Merge and compute delinquency rate delta"):
        m = src.merge(dla, on="property_id", suffixes=("_src", "_dla"))
        assert not m.empty, "TC-6: No matching property_ids"
        m["rate_delta"] = abs(
            m["delinquency_rate_pct_src"].astype(float) - m["delinquency_rate_pct_dla"].astype(float)
        )
        _attach_df(m[["property_id", "delinquency_rate_pct_src", "delinquency_rate_pct_dla", "rate_delta"]], "Comparison")

    with allure.step(f"Assert rate_delta <= {TOLERANCE_TC6_PPT} ppt per property"):
        fail = m[m["rate_delta"] > TOLERANCE_TC6_PPT]
        if not fail.empty:
            report = fail[["property_id", "delinquency_rate_pct_src", "delinquency_rate_pct_dla", "rate_delta"]].to_string(index=False)
            _attach_df(fail, "FAILED Properties")
            post_slack(f":red_circle: *TC-6 FAILED* — Delinquency Rate\n```{report}```")
            pytest.fail(f"TC-6: rate_delta > {TOLERANCE_TC6_PPT}ppt for {len(fail)} property(ies)\n{report}")


# ─────────────────────────────────────────────────────────────────────────────
# TC-7: Average Days to Pay Per Property
# ─────────────────────────────────────────────────────────────────────────────
_MYSQL_TC7 = """
SELECT property_id,
       ROUND(AVG(DATEDIFF(modified_at, created_at)), 1) AS avg_days_to_pay
FROM {schema}.invoices
WHERE property_id IN ({pids})
  AND void_date   IS NULL
  AND voided_at   IS NULL
  AND paid        = 1
  AND modified_at > created_at
GROUP BY property_id
ORDER BY property_id
"""

_DLA_TC7 = """
SELECT property_id,
       ROUND(AVG(DATEDIFF('day', created_at, modified_at)), 1) AS avg_days_to_pay
FROM {dla}.invoices
WHERE company_uid   = '{CUID}'
  AND property_id  IN ({pids})
  AND void_date    IS NULL
  AND voided_at    IS NULL
  AND paid         = 1
  AND modified_at  > created_at
GROUP BY property_id
ORDER BY property_id
"""

TOLERANCE_TC7_DAYS = 1.0


@allure.epic("Derived Value Validation")
@allure.feature("Data Quality")
@allure.story("TC-7 — Average Days to Pay Per Property")
@allure.severity(allure.severity_level.NORMAL)
@allure.title("TC-7: Avg Days to Pay — MySQL vs DLA (within 1 day)")
@allure.description(
    "Calculates average days between invoice creation and payment date per property. "
    "Validates that timestamp values survive CDC correctly. Tolerance: 1 day."
)
def test_tc7_avg_days_to_pay():
    with allure.step("Run MySQL query"):
        src = run_mysql(_MYSQL_TC7)
        assert not src.empty, "TC-7: MySQL returned 0 rows"
        _attach_df(src, "MySQL Result")

    with allure.step("Run DLA query"):
        dla = run_redshift(_DLA_TC7)
        assert not dla.empty, "TC-7: DLA returned 0 rows"
        _attach_df(dla, "DLA Result")

    with allure.step("Merge on property_id and compute days delta"):
        m = src.merge(dla, on="property_id", suffixes=("_src", "_dla"))
        assert not m.empty, "TC-7: No matching property_ids"
        m["days_delta"] = abs(
            m["avg_days_to_pay_src"].astype(float) - m["avg_days_to_pay_dla"].astype(float)
        )
        _attach_df(m[["property_id", "avg_days_to_pay_src", "avg_days_to_pay_dla", "days_delta"]], "Comparison")

    with allure.step(f"Assert days_delta <= {TOLERANCE_TC7_DAYS} per property"):
        fail = m[m["days_delta"] > TOLERANCE_TC7_DAYS]
        if not fail.empty:
            report = fail[["property_id", "avg_days_to_pay_src", "avg_days_to_pay_dla", "days_delta"]].to_string(index=False)
            _attach_df(fail, "FAILED Properties")
            post_slack(f":red_circle: *TC-7 FAILED* — Avg Days to Pay\n```{report}```")
            pytest.fail(f"TC-7: days_delta > {TOLERANCE_TC7_DAYS} for {len(fail)} property(ies)\n{report}")
