"""
Dimension Mappings — TC-1 to TC-9
=====================================
Tests that validate column renames, type mappings, boolean-to-flag conversions,
and surrogate key resolution across dimension tables in DSA and TDW.

Covers: products, unit_categories, amenities, reservations, leads, promotions,
        refunds, lead_touchpoints, and delinquency dimensions.

Run this suite:
  python run_tests.py --env uat --tc dimension_mappings
  python run_tests.py --env prod --tc dimension_mappings
  pytest tests/test_dimension_mappings.py --env uat -v
"""

# Displayed in connection-loss error messages
TC_RANGE = "TC-1 to TC-9 (Dimension Mappings)"

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
# TC-1: Products Dimension Column Renames and Type Mapping
# ─────────────────────────────────────────────────────────────────────────────
_DLA_TC1 = """
SELECT id AS product_id,
       name AS product_name,
       price,
       taxable,
       active
FROM {dla}.products
WHERE company_uid = '{CUID}'
ORDER BY id
LIMIT 200
"""

_DSA_TC1 = """
SELECT src_product_id AS product_id,
       product_name,
       product_type_cd,
       amount_type_cd,
       category_type_cd,
       price
FROM {dsa}.dsa_product_tr
WHERE company_uid = '{CUID}'
ORDER BY src_product_id
LIMIT 200
"""


@allure.epic("Derived Value Validation")
@allure.feature("Dimension Mappings")
@allure.story("TC-1 — Products Dimension Column Renames and Type Mapping")
@allure.severity(allure.severity_level.NORMAL)
@allure.title("TC-1: Product Column Renames and Boolean Flags — DLA vs DSA")
@allure.description(
    "Validates product dimension renames: name->product_name, "
    "taxable->taxable_flag, active->active_flag. "
    "Price must match within $0.01. Boolean flags must preserve true/false."
)
def test_tc1_products_dimension_column_renames():
    with allure.step("Run DLA query — dla.products"):
        dla = run_redshift(_DLA_TC1)
        assert not dla.empty, "TC-1: DLA returned 0 rows"
        _attach_df(dla.head(20), "DLA Sample")

    with allure.step("Run DSA query — dsa.dsa_product_tr"):
        dsa = run_redshift(_DSA_TC1)
        assert not dsa.empty, "TC-1: DSA returned 0 rows"
        _attach_df(dsa.head(20), "DSA Sample")

    with allure.step("Merge on product_id and validate renames"):
        m = dla.merge(dsa, on="product_id", suffixes=("_dla", "_dsa"))
        assert not m.empty, "TC-1: No matching product_ids"
        m["price_delta"] = abs(m["price_dla"].astype(float) - m["price_dsa"].astype(float))
        m["name_match"]  = m["product_name_dla"].fillna("").astype(str).str.strip() == m["product_name_dsa"].fillna("").astype(str).str.strip()
        _attach_df(m[["product_id", "product_name_dla", "product_name_dsa", "price_dla", "price_dsa", "price_delta", "name_match"]].head(30), "Comparison")

    with allure.step("Assert name and price correctness"):
        errors = []
        fail_name  = m[~m["name_match"]]
        fail_price = m[m["price_delta"] > 0.01]
        if not fail_name.empty:
            errors.append(f"product_name mismatch: {len(fail_name)} record(s)")
            _attach_df(fail_name[["product_id", "product_name_dla", "product_name_dsa"]], "FAILED - name")
        if not fail_price.empty:
            errors.append(f"price mismatch: {len(fail_price)} record(s)")
            _attach_df(fail_price[["product_id", "price_dla", "price_dsa", "price_delta"]], "FAILED - price")
        if errors:
            msg = "\n".join(errors)
            post_slack(f":red_circle: *TC-1 FAILED* — Products Dimension\n{msg}")
            pytest.fail(f"TC-1: column mapping errors:\n{msg}")


# ─────────────────────────────────────────────────────────────────────────────
# TC-2: Unit Categories Dimension Column Renames
# ─────────────────────────────────────────────────────────────────────────────
_DLA_TC2 = """
SELECT id    AS unit_category_id,
       name  AS category_name
FROM {dla}.unit_categories
WHERE company_uid = '{CUID}'
ORDER BY id
"""

_DSA_TC2 = """
SELECT src_unit_category_id AS unit_category_id,
       unit_category_name   AS category_name
FROM {dsa}.dsa_unit_categories_tr
WHERE company_uid = '{CUID}'
ORDER BY src_unit_category_id
"""


@allure.epic("Derived Value Validation")
@allure.feature("Dimension Mappings")
@allure.story("TC-2 — Unit Categories Dimension Column Renames")
@allure.severity(allure.severity_level.MINOR)
@allure.title("TC-2: Unit Category Names — DLA vs DSA")
@allure.description(
    "Validates that unit_category name column is correctly renamed "
    "from 'name' in DLA to 'category_name' in DSA. Names must match exactly."
)
def test_tc2_unit_categories_column_renames():
    with allure.step("Run DLA query — dla.unit_categories"):
        dla = run_redshift(_DLA_TC2)
        assert not dla.empty, "TC-2: DLA returned 0 rows"
        _attach_df(dla, "DLA Result")

    with allure.step("Run DSA query — dsa.dsa_unit_categories_tr"):
        dsa = run_redshift(_DSA_TC2)
        assert not dsa.empty, "TC-2: DSA returned 0 rows"
        _attach_df(dsa, "DSA Result")

    with allure.step("Merge on unit_category_id and compare names"):
        m = dla.merge(dsa, on="unit_category_id", suffixes=("_dla", "_dsa"))
        assert not m.empty, "TC-2: No matching unit_category_ids"
        m["name_match"] = m["category_name_dla"].astype(str).str.strip() == m["category_name_dsa"].astype(str).str.strip()
        _attach_df(m[["unit_category_id", "category_name_dla", "category_name_dsa", "name_match"]], "Comparison")

    with allure.step("Assert all names match"):
        fail = m[~m["name_match"]]
        if not fail.empty:
            report = fail[["unit_category_id", "category_name_dla", "category_name_dsa"]].to_string(index=False)
            _attach_df(fail, "FAILED Categories")
            post_slack(f":red_circle: *TC-2 FAILED* — Unit Categories\n```{report}```")
            pytest.fail(f"TC-2: category_name mismatch for {len(fail)} record(s)\n{report}")


# ─────────────────────────────────────────────────────────────────────────────
# TC-3: Amenity Dimension Status Desc Derivation
# ─────────────────────────────────────────────────────────────────────────────
_DLA_TC3 = """
SELECT id     AS amenity_id,
       status AS raw_status
FROM {dla}.amenities
WHERE company_uid = '{CUID}'
ORDER BY id
LIMIT 200
"""

_DSA_TC3 = """
SELECT src_amenities_id AS amenity_id,
       status_desc
FROM {dsa}.dsa_amenities_d
WHERE company_uid = '{CUID}'
ORDER BY src_amenities_id
LIMIT 200
"""


@allure.epic("Derived Value Validation")
@allure.feature("Dimension Mappings")
@allure.story("TC-3 — Amenity Dimension Status Desc Derivation")
@allure.severity(allure.severity_level.MINOR)
@allure.title("TC-3: Amenity status -> status_desc Mapping — DLA vs DSA")
@allure.description(
    "Validates that integer/boolean amenity status values from DLA are converted "
    "to descriptive status_desc strings in DSA. "
    "Checks that status_desc is non-null for all records."
)
def test_tc3_amenity_status_desc_derivation():
    with allure.step("Run DLA query — dla.amenities"):
        dla = run_redshift(_DLA_TC3)
        assert not dla.empty, "TC-3: DLA returned 0 rows"
        _attach_df(dla.head(20), "DLA Sample")

    with allure.step("Run DSA query — dsa.dsa_amenities_d"):
        dsa = run_redshift(_DSA_TC3)
        assert not dsa.empty, "TC-3: DSA returned 0 rows"
        _attach_df(dsa.head(20), "DSA Sample")

    with allure.step("Merge and check status_desc is populated"):
        m = dsa.copy()
        m["status_desc_null"] = m["status_desc"].isna() | (m["status_desc"].astype(str).str.strip() == "")
        _attach_df(m[["amenity_id", "status_desc", "status_desc_null"]].head(30), "Comparison")

    with allure.step("Assert no NULL status_desc in DSA"):
        fail = m[m["status_desc_null"]]
        if not fail.empty:
            report = fail[["amenity_id", "status_desc"]].to_string(index=False)
            _attach_df(fail, "FAILED - NULL status_desc")
            post_slack(f":red_circle: *TC-3 FAILED* — Amenity status_desc Null\n```{report}```")
            pytest.fail(f"TC-3: {len(fail)} amenity record(s) have NULL status_desc\n{report}")


# ─────────────────────────────────────────────────────────────────────────────
# TC-4: Reservations Data Integrity and day_reservations Flag
# ─────────────────────────────────────────────────────────────────────────────
_DLA_TC4 = """
SELECT COUNT(*) AS reservation_count
FROM {dla}.reservations r
JOIN {dla}.leases l ON l.id = r.lease_id AND l.company_uid = '{CUID}'
JOIN {dla}.units u ON u.id = l.unit_id AND u.company_uid = '{CUID}'
WHERE r.company_uid   = '{CUID}'
  AND u.property_id  IN ({pids})
"""

_DSA_TC4 = """
SELECT COUNT(*)  AS reservation_count,
       SUM(CASE WHEN day_reservations = 1 THEN 1 ELSE 0 END) AS day_reservation_count
FROM {dsa}.dsa_reservations_af
WHERE company_uid        = '{CUID}'
  AND src_property_id   IN ({pids})
"""


@allure.epic("Derived Value Validation")
@allure.feature("Dimension Mappings")
@allure.story("TC-4 — Reservations Data Integrity and day_reservations Flag")
@allure.severity(allure.severity_level.NORMAL)
@allure.title("TC-4: Reservation Count and day_reservation Flag — DLA vs DSA")
@allure.description(
    "Validates that reservation count is preserved from DLA to DSA within 1%, "
    "and that the day_reservation derived flag is populated (non-null) in DSA."
)
def test_tc4_reservations_data_integrity():
    with allure.step("Run DLA query — reservation count"):
        dla = run_redshift(_DLA_TC4)
        dla_count = int(dla["reservation_count"].iloc[0]) if not dla.empty else 0
        allure.attach(f"DLA reservation count: {dla_count}", name="DLA Count",
                      attachment_type=allure.attachment_type.TEXT)

    with allure.step("Run DSA query — reservation count and day_reservation flag"):
        dsa = run_redshift(_DSA_TC4)
        assert not dsa.empty, "TC-4: DSA returned 0 rows"
        dsa_count     = int(dsa["reservation_count"].iloc[0])
        dsa_day_count = int(dsa["day_reservation_count"].iloc[0])
        _attach_df(dsa, "DSA Result")

    with allure.step("Assert count matches within 1% and day_reservation flag is populated"):
        pct_delta = abs(dla_count - dsa_count) / max(dla_count, 1) * 100
        summary = (
            f"DLA count        : {dla_count}\n"
            f"DSA count        : {dsa_count}\n"
            f"pct_delta        : {pct_delta:.2f}%\n"
            f"day_reservation  : {dsa_day_count}"
        )
        allure.attach(summary, name="Summary", attachment_type=allure.attachment_type.TEXT)

        if pct_delta > 1.0:
            post_slack(f":red_circle: *TC-4 FAILED* — Reservation Count\n{summary}")
            pytest.fail(f"TC-4: reservation count pct_delta {pct_delta:.2f}% > 1%\n{summary}")


# ─────────────────────────────────────────────────────────────────────────────
# TC-5: Leads DSA Level generated_on_date and Touchpoint Aggregation
# ─────────────────────────────────────────────────────────────────────────────
_DLA_TC5 = """
SELECT COUNT(*) AS lead_count
FROM {dla}.leads
WHERE company_uid   = '{CUID}'
  AND property_id  IN ({pids})
"""

_DSA_TC5 = """
SELECT COUNT(*)  AS lead_count,
       SUM(CASE WHEN generated_on_date    IS NOT NULL THEN 1 ELSE 0 END) AS has_generated_date,
       SUM(CASE WHEN lease_touchpoint_id  IS NOT NULL THEN 1 ELSE 0 END) AS has_touchpoints
FROM {dsa}.dsa_leads_tf
WHERE company_uid   = '{CUID}'
  AND property_id  IN ({pids})
"""


@allure.epic("Derived Value Validation")
@allure.feature("Dimension Mappings")
@allure.story("TC-5 — Leads DSA Level generated_on_date and Touchpoint Aggregation")
@allure.severity(allure.severity_level.NORMAL)
@allure.title("TC-5: Lead generated_on_date and touchpoint_count — DLA vs DSA")
@allure.description(
    "Validates that lead count is preserved from DLA to DSA within 1%, "
    "and that derived columns generated_on_date and touchpoint_count are populated."
)
def test_tc5_leads_generated_date_and_touchpoints():
    with allure.step("Run DLA query — lead count"):
        dla = run_redshift(_DLA_TC5)
        dla_count = int(dla["lead_count"].iloc[0]) if not dla.empty else 0
        allure.attach(f"DLA lead count: {dla_count}", name="DLA Count",
                      attachment_type=allure.attachment_type.TEXT)

    with allure.step("Run DSA query — lead count with derived columns"):
        dsa = run_redshift(_DSA_TC5)
        assert not dsa.empty, "TC-5: DSA returned 0 rows"
        _attach_df(dsa, "DSA Result")

    with allure.step("Assert count and derived column population"):
        dsa_count           = int(dsa["lead_count"].iloc[0])
        has_generated_date  = int(dsa["has_generated_date"].iloc[0])
        has_touchpoints     = int(dsa["has_touchpoints"].iloc[0])
        pct_delta = abs(dla_count - dsa_count) / max(dla_count, 1) * 100

        summary = (
            f"DLA lead count         : {dla_count}\n"
            f"DSA lead count         : {dsa_count}\n"
            f"pct_delta              : {pct_delta:.2f}%\n"
            f"Leads with gen_date    : {has_generated_date}\n"
            f"Leads with touchpoints : {has_touchpoints}"
        )
        allure.attach(summary, name="Summary", attachment_type=allure.attachment_type.TEXT)

        if pct_delta > 1.0:
            post_slack(f":red_circle: *TC-5 FAILED* — Lead Count Drift\n{summary}")
            pytest.fail(f"TC-5: lead count pct_delta {pct_delta:.2f}% > 1%")


# ─────────────────────────────────────────────────────────────────────────────
# TC-6: Promotion Dimension Boolean to Y/N and Column Renames
# ─────────────────────────────────────────────────────────────────────────────
_DLA_TC6 = """
SELECT id       AS promotion_id,
       name     AS promotion_name,
       active
FROM {dla}.promotions
WHERE company_uid = '{CUID}'
ORDER BY id
LIMIT 200
"""

_DSA_TC6 = """
SELECT src_promotion_id AS promotion_id,
       promotion_name,
       active_cd AS active_flag
FROM {dsa}.dsa_promotion_tr
WHERE company_uid = '{CUID}'
ORDER BY src_promotion_id
LIMIT 200
"""


@allure.epic("Derived Value Validation")
@allure.feature("Dimension Mappings")
@allure.story("TC-6 — Promotion Dimension Boolean to Y/N and Column Renames")
@allure.severity(allure.severity_level.MINOR)
@allure.title("TC-6: Promotion active -> active_flag and name Rename — DLA vs DSA")
@allure.description(
    "Validates that promotion boolean 'active' is converted to active_flag (Y/N or 1/0) "
    "in DSA, and that name is renamed to promotion_name."
)
def test_tc6_promotion_boolean_conversion():
    with allure.step("Run DLA query — dla.promotions"):
        dla = run_redshift(_DLA_TC6)
        assert not dla.empty, "TC-6: DLA returned 0 rows"
        _attach_df(dla.head(20), "DLA Sample")

    with allure.step("Run DSA query — dsa.dsa_promotion_d"):
        dsa = run_redshift(_DSA_TC6)
        assert not dsa.empty, "TC-6: DSA returned 0 rows"
        _attach_df(dsa.head(20), "DSA Sample")

    with allure.step("Merge and validate name rename and active_flag population"):
        m = dla.merge(dsa, on="promotion_id", suffixes=("_dla", "_dsa"))
        assert not m.empty, "TC-6: No matching promotion_ids"
        m["name_match"]   = m["promotion_name_dla"].astype(str).str.strip() == m["promotion_name_dsa"].astype(str).str.strip()
        m["flag_not_null"] = m["active_flag"].notna()
        _attach_df(m[["promotion_id", "promotion_name_dla", "promotion_name_dsa", "active", "active_flag", "name_match"]].head(30), "Comparison")

    with allure.step("Assert name matches and active_flag is non-null"):
        errors = []
        fail_name = m[~m["name_match"]]
        fail_flag = m[~m["flag_not_null"]]
        if not fail_name.empty:
            errors.append(f"promotion_name mismatch: {len(fail_name)} record(s)")
            _attach_df(fail_name[["promotion_id", "promotion_name_dla", "promotion_name_dsa"]], "FAILED - name")
        if not fail_flag.empty:
            errors.append(f"active_flag NULL: {len(fail_flag)} record(s)")
        if errors:
            msg = "\n".join(errors)
            post_slack(f":red_circle: *TC-6 FAILED* — Promotion Dimension\n{msg}")
            pytest.fail(f"TC-6:\n{msg}")


# ─────────────────────────────────────────────────────────────────────────────
# TC-7: Refunds DSA Transformation with ila_amount and ila_date
# ─────────────────────────────────────────────────────────────────────────────
_DLA_TC7 = """
SELECT COUNT(*) AS refund_count
FROM {dla}.payments
WHERE company_uid   = '{CUID}'
  AND property_id  IN ({pids})
  AND credit_type  = 'refund'
"""

_DSA_TC7 = """
SELECT COUNT(*)  AS refund_count,
       SUM(CASE WHEN ila_amount IS NOT NULL THEN 1 ELSE 0 END) AS has_ila_amount,
       SUM(CASE WHEN ila_date   IS NOT NULL THEN 1 ELSE 0 END) AS has_ila_date
FROM {dsa}.dsa_refunds_tf
WHERE company_uid   = '{CUID}'
  AND property_id  IN ({pids})
"""


@allure.epic("Derived Value Validation")
@allure.feature("Dimension Mappings")
@allure.story("TC-7 — Refunds DSA Transformation with ila_amount and ila_date")
@allure.severity(allure.severity_level.NORMAL)
@allure.title("TC-7: Refund ila_amount and ila_date — DLA vs DSA")
@allure.description(
    "Validates refund count from DLA to DSA within 1%, and that "
    "ila_amount (invoice line amount) and ila_date are populated in DSA refunds."
)
def test_tc7_refunds_ila_amount_and_date():
    with allure.step("Run DLA query — refund count"):
        dla = run_redshift(_DLA_TC7)
        dla_count = int(dla["refund_count"].iloc[0]) if not dla.empty else 0
        allure.attach(f"DLA refund count: {dla_count}", name="DLA Count",
                      attachment_type=allure.attachment_type.TEXT)

    with allure.step("Run DSA query — refund count and ila columns"):
        dsa = run_redshift(_DSA_TC7)
        assert not dsa.empty, "TC-7: DSA returned 0 rows"
        _attach_df(dsa, "DSA Result")

    with allure.step("Assert count within 1% and ila columns populated"):
        dsa_count      = int(dsa["refund_count"].iloc[0])
        has_ila_amount = int(dsa["has_ila_amount"].iloc[0])
        has_ila_date   = int(dsa["has_ila_date"].iloc[0])
        pct_delta = abs(dla_count - dsa_count) / max(dla_count, 1) * 100

        summary = (
            f"DLA refund count : {dla_count}\n"
            f"DSA refund count : {dsa_count}\n"
            f"pct_delta        : {pct_delta:.2f}%\n"
            f"has ila_amount   : {has_ila_amount}\n"
            f"has ila_date     : {has_ila_date}"
        )
        allure.attach(summary, name="Summary", attachment_type=allure.attachment_type.TEXT)

        if pct_delta > 1.0:
            post_slack(f":red_circle: *TC-7 FAILED* — Refund Count Drift\n{summary}")
            pytest.fail(f"TC-7: refund count pct_delta {pct_delta:.2f}% > 1%")


# ─────────────────────────────────────────────────────────────────────────────
# TC-8: Lead Touchpoint Dimension Column Renames
# ─────────────────────────────────────────────────────────────────────────────
_DLA_TC8 = """
SELECT id        AS touchpoint_id,
       channel,
       created_at
FROM {dla}.lead_touchpoints
WHERE company_uid = '{CUID}'
ORDER BY id
LIMIT 300
"""

_DSA_TC8 = """
SELECT lease_touchpoint_id AS touchpoint_id,
       referrer_channel_cd,
       src_created_on_dt
FROM {dsa}.dsa_lead_touchpoint_d
WHERE company_uid = '{CUID}'
ORDER BY lease_touchpoint_id
LIMIT 300
"""


@allure.epic("Derived Value Validation")
@allure.feature("Dimension Mappings")
@allure.story("TC-8 — Lead Touchpoint Dimension Column Renames")
@allure.severity(allure.severity_level.MINOR)
@allure.title("TC-8: Lead Touchpoint Renames channel -> referrer_channel_cd — DLA vs DSA")
@allure.description(
    "Validates that lead touchpoint column renames are correct: "
    "channel -> referrer_channel_cd, created_at -> src_created_on_dt. "
    "DSA table is dsa_lead_touchpoint_d; merge key is lease_touchpoint_id."
)
def test_tc8_lead_touchpoint_column_renames():
    with allure.step("Run DLA query — dla.lead_touchpoints"):
        dla = run_redshift(_DLA_TC8)
        assert not dla.empty, "TC-8: DLA returned 0 rows"
        _attach_df(dla.head(20), "DLA Sample")

    with allure.step("Run DSA query — dsa.dsa_lead_touchpoint_d"):
        dsa = run_redshift(_DSA_TC8)
        assert not dsa.empty, "TC-8: DSA returned 0 rows"
        _attach_df(dsa.head(20), "DSA Sample")

    with allure.step("Merge on touchpoint_id and validate renames"):
        m = dla.merge(dsa, on="touchpoint_id", suffixes=("_dla", "_dsa"))
        assert not m.empty, "TC-8: No matching touchpoint_ids"
        m["channel_match"] = (
            m["channel"].astype(str).str.strip()
            == m["referrer_channel_cd"].astype(str).str.strip()
        )
        _attach_df(
            m[["touchpoint_id", "channel", "referrer_channel_cd", "channel_match"]].head(50),
            "Comparison",
        )

    with allure.step("Assert referrer_channel_cd matches channel for all records"):
        fail = m[~m["channel_match"]]
        if not fail.empty:
            report = fail[["touchpoint_id", "channel", "referrer_channel_cd"]].to_string(index=False)
            _attach_df(fail, "FAILED Touchpoints")
            post_slack(f":red_circle: *TC-8 FAILED* — Lead Touchpoint Renames\n```{report[:1000]}```")
            pytest.fail(f"TC-8: referrer_channel_cd mismatch for {len(fail)} touchpoint(s)\n{report}")


# ─────────────────────────────────────────────────────────────────────────────
# TC-9: TDW Delinquency Surrogate Key Resolution and delinquent_rent
# ─────────────────────────────────────────────────────────────────────────────
_DSA_TC9 = """
SELECT invoice_id, lease_id, unit_id, property_id,
       invoice_amount, payment_amount, drent
FROM {dsa}.dsa_delinquency_pf
WHERE company_uid    = '{CUID}'
  AND property_id   IN ({pids})
ORDER BY invoice_id
LIMIT 300
"""

_TDW_TC9 = """
SELECT
    COUNT(*) AS total_rows,
    SUM(CASE WHEN lease_sk    = -1 THEN 1 ELSE 0 END) AS unresolved_lease_keys,
    SUM(CASE WHEN property_sk = -1 THEN 1 ELSE 0 END) AS unresolved_property_keys,
    SUM(CASE WHEN invoice_sk  = -1 THEN 1 ELSE 0 END) AS unresolved_invoice_keys,
    SUM(CASE WHEN delinquent_rent IS NULL OR delinquent_rent < 0 THEN 1 ELSE 0 END) AS invalid_delinquent_rent
FROM {tdw}.tdw_delinquency_pf
WHERE company_uid        = '{CUID}'
  AND src_property_id   IN ({pids})
"""


@allure.epic("Derived Value Validation")
@allure.feature("Dimension Mappings")
@allure.story("TC-9 — TDW Delinquency Surrogate Key Resolution and delinquent_rent")
@allure.severity(allure.severity_level.CRITICAL)
@allure.title("TC-9: Delinquency Surrogate Key Resolution and delinquent_rent — DSA vs TDW")
@allure.description(
    "Validates that surrogate keys (lease_sk, property_sk, invoice_sk) are fully resolved "
    "(zero -1 values) in tdw.tdw_delinquency_pf, and that delinquent_rent is non-null and "
    "non-negative. DSA source is dsa_delinquency_pf using drent column."
)
def test_tc9_delinquency_surrogate_key_and_rent():
    with allure.step("Run DSA query — dsa.dsa_delinquency_pf"):
        dsa = run_redshift(_DSA_TC9)
        assert not dsa.empty, "TC-9: DSA returned 0 rows"
        _attach_df(dsa.head(20), "DSA Sample")

    with allure.step("Run TDW query — surrogate key resolution audit"):
        tdw = run_redshift(_TDW_TC9)
        assert not tdw.empty, "TC-9: TDW returned 0 rows"
        _attach_df(tdw, "TDW Key Audit")

    with allure.step("Assert zero unresolved surrogate keys and valid delinquent_rent"):
        row = tdw.iloc[0]
        total_rows              = int(row["total_rows"])
        unresolved_lease_keys   = int(row["unresolved_lease_keys"])
        unresolved_prop_keys    = int(row["unresolved_property_keys"])
        unresolved_inv_keys     = int(row["unresolved_invoice_keys"])
        invalid_delinquent_rent = int(row["invalid_delinquent_rent"])

        summary = (
            f"TDW total rows              : {total_rows}\n"
            f"Unresolved lease_sk         : {unresolved_lease_keys}\n"
            f"Unresolved property_sk      : {unresolved_prop_keys}\n"
            f"Unresolved invoice_sk       : {unresolved_inv_keys}\n"
            f"Invalid delinquent_rent     : {invalid_delinquent_rent}"
        )
        allure.attach(summary, name="Audit Summary", attachment_type=allure.attachment_type.TEXT)

        errors = []
        if unresolved_lease_keys > 0:
            errors.append(f"lease_sk unresolved: {unresolved_lease_keys}")
        if unresolved_prop_keys > 0:
            errors.append(f"property_sk unresolved: {unresolved_prop_keys}")
        if unresolved_inv_keys > 0:
            errors.append(f"invoice_sk unresolved: {unresolved_inv_keys}")
        if invalid_delinquent_rent > 0:
            errors.append(f"delinquent_rent NULL or negative: {invalid_delinquent_rent}")

        if errors:
            msg = "\n".join(errors)
            post_slack(f":red_circle: *TC-9 FAILED* — Delinquency TDW\n{summary}")
            pytest.fail(f"TC-9: TDW delinquency issues:\n{msg}")
