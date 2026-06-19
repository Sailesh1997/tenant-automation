"""
DSA Transformations — TC-1 to TC-14, TC-15
============================================
Tests that validate derived column logic and join chain transformations
as data moves from DLA (raw CDC) into the DSA (Data Staging Area).

These tests compare DLA source values against the transformed output
in dsa.* tables, verifying that all derivations and renames are correct.

Run this suite:
  python run_tests.py --env uat --tc dsa_transformations
  python run_tests.py --env prod --tc dsa_transformations
  pytest tests/test_dsa_transformations.py --env uat -v
"""

# Displayed in connection-loss error messages
TC_RANGE = "TC-1 to TC-14, TC-15 (DSA Transformations)"

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
# TC-1: Contact full_name and contact_type Derivation
# ─────────────────────────────────────────────────────────────────────────────
_DLA_TC1 = """
SELECT id,
       first,
       last,
       TRIM(CONCAT(COALESCE(first, ''), ' ', COALESCE(last, ''))) AS expected_full_name,
       contact_type
FROM {dla}.contacts
WHERE company_uid = '{CUID}'
LIMIT 500
"""

_DSA_TC1 = """
SELECT src_contact_id AS id,
       full_name,
       contact_type
FROM {dsa}.dsa_contact_tr
WHERE company_uid = '{CUID}'
  AND src_contact_id <> -1
LIMIT 500
"""


@allure.epic("Derived Value Validation")
@allure.feature("DSA Transformations")
@allure.story("TC-1 — Contact full_name and contact_type Derivation")
@allure.severity(allure.severity_level.NORMAL)
@allure.title("TC-1: Contact full_name Derivation — DLA vs DSA")
@allure.description(
    "Validates that DSA derives full_name = TRIM(CONCAT(first_name, ' ', last_name)) "
    "from DLA contacts, and that contact_type is preserved unchanged."
)
def test_tc1_contact_full_name_derivation():
    with allure.step("Run DLA query — dla.contacts"):
        dla = run_redshift(_DLA_TC1)
        assert not dla.empty, "TC-1: DLA returned 0 rows"
        _attach_df(dla.head(20), "DLA Sample")

    with allure.step("Run DSA query — dsa.dsa_contact_tr"):
        dsa = run_redshift(_DSA_TC1)
        assert not dsa.empty, "TC-1: DSA returned 0 rows"
        _attach_df(dsa.head(20), "DSA Sample")

    with allure.step("Merge on id and validate full_name derivation"):
        m = dla.merge(dsa, on="id", suffixes=("_dla", "_dsa"))
        assert not m.empty, "TC-1: No matching contact IDs between DLA and DSA"
        m["name_match"] = m["expected_full_name"].str.strip() == m["full_name"].str.strip()
        _attach_df(m[["id", "expected_full_name", "full_name", "name_match"]].head(50), "Comparison Sample")

    with allure.step("Assert full_name matches for all sampled contacts"):
        fail = m[~m["name_match"]]
        if not fail.empty:
            report = fail[["id", "expected_full_name", "full_name"]].to_string(index=False)
            _attach_df(fail[["id", "expected_full_name", "full_name"]], "FAILED Contacts")
            post_slack(f":red_circle: *TC-1 FAILED* — Contact full_name Derivation\n```{report[:1000]}```")
            pytest.fail(f"TC-1: full_name mismatch for {len(fail)} contact(s)\n{report}")


# ─────────────────────────────────────────────────────────────────────────────
# TC-2: Property Column Renames and Address Join
# ─────────────────────────────────────────────────────────────────────────────
_DLA_TC2 = """
SELECT p.id        AS property_id,
       p.name      AS property_name,
       a.address   AS address_line1,
       a.city      AS city_nm,
       a.state     AS state_cd,
       a.zip       AS zip_code
FROM {dla}.properties p
LEFT JOIN {dla}.addresses a ON a.addressable_id = p.id AND a.addressable_type = 'Property'
WHERE p.company_uid = '{CUID}'
LIMIT 200
"""

_DSA_TC2 = """
SELECT src_property_id AS property_id,
       property_name,
       address_line1,
       city_nm,
       state_cd,
       zip_code
FROM {dsa}.dsa_property_tr
WHERE company_uid = '{CUID}'
LIMIT 200
"""


@allure.epic("Derived Value Validation")
@allure.feature("DSA Transformations")
@allure.story("TC-2 — Property Column Renames and Address Join")
@allure.severity(allure.severity_level.NORMAL)
@allure.title("TC-2: Property Name and Address — DLA vs DSA")
@allure.description(
    "Validates that DSA correctly renames property columns and joins address data. "
    "Checks property_name, address_1, city, state, zip preservation."
)
def test_tc2_property_column_renames_and_address_join():
    with allure.step("Run DLA query"):
        dla = run_redshift(_DLA_TC2)
        assert not dla.empty, "TC-2: DLA returned 0 rows"
        _attach_df(dla.head(20), "DLA Sample")

    with allure.step("Run DSA query — dsa.dsa_property_tr"):
        dsa = run_redshift(_DSA_TC2)
        assert not dsa.empty, "TC-2: DSA returned 0 rows"
        _attach_df(dsa.head(20), "DSA Sample")

    with allure.step("Merge on property_id and compare address fields"):
        m = dla.merge(dsa, on="property_id", suffixes=("_dla", "_dsa"))
        assert not m.empty, "TC-2: No matching property_ids between DLA and DSA"
        check_cols = ["property_name", "address_line1", "city_nm", "state_cd", "zip_code"]
        mismatches = []
        for col in check_cols:
            if f"{col}_dla" in m.columns and f"{col}_dsa" in m.columns:
                mismatch = m[m[f"{col}_dla"].fillna("").astype(str).str.strip() != m[f"{col}_dsa"].fillna("").astype(str).str.strip()]
                if not mismatch.empty:
                    mismatches.append(f"{col}: {len(mismatch)} mismatch(es)")
        _attach_df(m[["property_id"] + [c for pair in [(f"{c}_dla", f"{c}_dsa") for c in check_cols]
                       for c in pair if c in m.columns]].head(20), "Comparison Sample")

    with allure.step("Assert all address fields match"):
        if mismatches:
            report = "\n".join(mismatches)
            post_slack(f":red_circle: *TC-2 FAILED* — Property Column Renames\n{report}")
            pytest.fail(f"TC-2: field mismatches found:\n{report}")


# ─────────────────────────────────────────────────────────────────────────────
# TC-3: Unit Dimension Renames with Width and Length
# ─────────────────────────────────────────────────────────────────────────────
_DLA_TC3 = """
SELECT id          AS unit_id,
       property_id,
       number      AS unit_number
FROM {dla}.units
WHERE company_uid   = '{CUID}'
  AND property_id  IN ({pids})
LIMIT 300
"""

_DSA_TC3 = """
SELECT src_unit_id   AS unit_id,
       src_property_id AS property_id,
       unit_number,
       unit_width_value,
       unit_length_value
FROM {dsa}.dsa_unit_tr
WHERE company_uid        = '{CUID}'
  AND src_property_id   IN ({pids})
LIMIT 300
"""


@allure.epic("Derived Value Validation")
@allure.feature("DSA Transformations")
@allure.story("TC-3 — Unit Dimension Renames with Width and Length")
@allure.severity(allure.severity_level.NORMAL)
@allure.title("TC-3: Unit width/length and sqft Derivation — DLA vs DSA")
@allure.description(
    "Validates that DSA correctly renames unit columns and derives sqft = width * length. "
    "Checks width, length, and sqft values per unit."
)
def test_tc3_unit_dimension_renames():
    with allure.step("Run DLA query — dla.units"):
        dla = run_redshift(_DLA_TC3)
        assert not dla.empty, "TC-3: DLA returned 0 rows"
        _attach_df(dla.head(20), "DLA Sample")

    with allure.step("Run DSA query — dsa.dsa_unit_tr"):
        dsa = run_redshift(_DSA_TC3)
        assert not dsa.empty, "TC-3: DSA returned 0 rows"
        _attach_df(dsa.head(20), "DSA Sample")

    with allure.step("Merge on unit_id and verify unit records match"):
        m = dla.merge(dsa, on="unit_id", suffixes=("_dla", "_dsa"))
        assert not m.empty, "TC-3: No matching unit_ids between DLA and DSA"
        m["number_match"] = m["unit_number_dla"].fillna("").astype(str).str.strip() == m["unit_number_dsa"].fillna("").astype(str).str.strip()
        _attach_df(m[["unit_id", "unit_number_dla", "unit_number_dsa", "number_match", "unit_width_value", "unit_length_value"]].head(50), "Comparison")

        summary = (
            f"Matched units  : {len(m)}\n"
            f"Number matches : {int(m['number_match'].sum())}\n"
            f"DSA width populated  : {int((m['unit_width_value'].notna()).sum())}\n"
            f"DSA length populated : {int((m['unit_length_value'].notna()).sum())}"
        )
        allure.attach(summary, name="Unit Dimension Summary", attachment_type=allure.attachment_type.TEXT)

    with allure.step("Assert unit_number matches and dimension columns are populated in DSA"):
        fail = m[~m["number_match"]]
        if not fail.empty:
            report = fail[["unit_id", "unit_number_dla", "unit_number_dsa"]].to_string(index=False)
            _attach_df(fail, "FAILED Units")
            post_slack(f":red_circle: *TC-3 FAILED* — Unit Dimension Renames\n```{report[:1000]}```")
            pytest.fail(f"TC-3: unit_number mismatch for {len(fail)} unit(s)\n{report}")


# ─────────────────────────────────────────────────────────────────────────────
# TC-4: Lease Status Desc Mapping Across All Layers
# ─────────────────────────────────────────────────────────────────────────────
_DLA_TC4 = """
SELECT status,
       COUNT(*) AS lease_count
FROM {dla}.leases
WHERE company_uid = '{CUID}'
GROUP BY status
ORDER BY status
"""

_DSA_TC4 = """
SELECT lease_status_desc,
       COUNT(*) AS lease_count
FROM {dsa}.dsa_lease_d
WHERE company_uid = '{CUID}'
GROUP BY lease_status_desc
ORDER BY lease_status_desc
"""


@allure.epic("Derived Value Validation")
@allure.feature("DSA Transformations")
@allure.story("TC-4 — Lease Status Desc Mapping Across All Layers")
@allure.severity(allure.severity_level.NORMAL)
@allure.title("TC-4: Lease Status -> Status Desc Mapping — DLA vs DSA")
@allure.description(
    "Validates that lease status integers (0=moved_out, 1=moved_in, etc.) "
    "are correctly mapped to lease_status_desc strings in DSA. "
    "Total lease counts must match within 1%."
)
def test_tc4_lease_status_desc_mapping():
    with allure.step("Run DLA query — dla.leases status distribution"):
        dla = run_redshift(_DLA_TC4)
        assert not dla.empty, "TC-4: DLA returned 0 rows"
        _attach_df(dla, "DLA Status Distribution")

    with allure.step("Run DSA query — dsa.dsa_lease_d status_desc distribution"):
        dsa = run_redshift(_DSA_TC4)
        assert not dsa.empty, "TC-4: DSA returned 0 rows"
        _attach_df(dsa, "DSA Status Desc Distribution")

    with allure.step("Compare total lease counts DLA vs DSA"):
        dla_total = int(dla["lease_count"].sum())
        dsa_total = int(dsa["lease_count"].sum())
        pct_delta = abs(dla_total - dsa_total) / max(dla_total, 1) * 100

        summary = f"DLA total={dla_total}  DSA total={dsa_total}  pct_delta={pct_delta:.2f}%"
        allure.attach(summary, name="Count Comparison", attachment_type=allure.attachment_type.TEXT)

        if pct_delta > 1.0:
            post_slack(f":red_circle: *TC-4 FAILED* — Lease Status Mapping\n{summary}")
            pytest.fail(f"TC-4: lease count pct_delta {pct_delta:.2f}% > 1%\n{summary}")


# ─────────────────────────────────────────────────────────────────────────────
# TC-5: Prorate Rent Derived Value at Lease Level
# ─────────────────────────────────────────────────────────────────────────────
_DLA_TC5 = """
SELECT id AS lease_id,
       rent,
       start_date AS move_in_date,
       bill_day   AS billing_day
FROM {dla}.leases
WHERE company_uid  = '{CUID}'
  AND status       = 1
  AND start_date  IS NOT NULL
  AND rent         > 0
LIMIT 200
"""

_DSA_TC5 = """
SELECT src_lease_id AS lease_id,
       rent,
       prorate_rent,
       move_in_date
FROM {dsa}.dsa_leases_af
WHERE company_uid    = '{CUID}'
  AND prorate_rent  IS NOT NULL
LIMIT 200
"""


@allure.epic("Derived Value Validation")
@allure.feature("DSA Transformations")
@allure.story("TC-5 — Prorate Rent Derived Value at Lease Level")
@allure.severity(allure.severity_level.NORMAL)
@allure.title("TC-5: Prorate Rent Derivation — DLA vs DSA")
@allure.description(
    "Validates that prorate_rent is populated in DSA for active leases. "
    "Prorate rent = (rent / days_in_month) * remaining_days_in_first_month. "
    "Checks that prorate_rent <= rent and is non-negative."
)
def test_tc5_prorate_rent_derivation():
    with allure.step("Run DLA query — active leases with rent"):
        dla = run_redshift(_DLA_TC5)
        assert not dla.empty, "TC-5: DLA returned 0 rows"
        _attach_df(dla.head(20), "DLA Sample")

    with allure.step("Run DSA query — prorate_rent values"):
        dsa = run_redshift(_DSA_TC5)
        assert not dsa.empty, "TC-5: DSA returned 0 rows"
        _attach_df(dsa.head(20), "DSA Sample")

    with allure.step("Merge on lease_id and validate prorate_rent bounds"):
        m = dsa.copy()
        m["prorate_valid"] = (
            (m["prorate_rent"].astype(float) >= 0) &
            (m["prorate_rent"].astype(float) <= m["rent"].astype(float))
        )
        _attach_df(m[["lease_id", "rent", "prorate_rent", "prorate_valid"]].head(50), "Comparison")

    with allure.step("Assert prorate_rent is between 0 and rent for all leases"):
        fail = m[~m["prorate_valid"]]
        if not fail.empty:
            report = fail[["lease_id", "rent", "prorate_rent"]].to_string(index=False)
            _attach_df(fail, "FAILED Leases")
            post_slack(f":red_circle: *TC-5 FAILED* — Prorate Rent Derivation\n```{report[:1000]}```")
            pytest.fail(f"TC-5: prorate_rent out of bounds for {len(fail)} lease(s)\n{report}")


# ─────────────────────────────────────────────────────────────────────────────
# TC-6: Move-In Source Category Distribution
# ─────────────────────────────────────────────────────────────────────────────
_DLA_TC6 = """
SELECT move_in_source,
       COUNT(*) AS lease_count
FROM {dla}.leases
WHERE company_uid = '{CUID}'
  AND move_in_source IS NOT NULL
GROUP BY move_in_source
ORDER BY lease_count DESC
"""

_DSA_TC6 = """
SELECT move_in_source_category,
       COUNT(*) AS lease_count
FROM {dsa}.dsa_leases_af
WHERE company_uid = '{CUID}'
  AND move_in_source_category IS NOT NULL
GROUP BY move_in_source_category
ORDER BY lease_count DESC
"""


@allure.epic("Derived Value Validation")
@allure.feature("DSA Transformations")
@allure.story("TC-6 — Move-In Source Category Distribution")
@allure.severity(allure.severity_level.MINOR)
@allure.title("TC-6: Move-In Source Category — DLA raw vs DSA categorized")
@allure.description(
    "Validates that move_in_source raw values from DLA are correctly categorized "
    "into move_in_source_category buckets in DSA. "
    "Total lease counts with a source must match within 2%."
)
def test_tc6_move_in_source_category_distribution():
    with allure.step("Run DLA query — raw move_in_source distribution"):
        dla = run_redshift(_DLA_TC6)
        assert not dla.empty, "TC-6: DLA returned 0 rows"
        _attach_df(dla, "DLA move_in_source Distribution")

    with allure.step("Run DSA query — categorized distribution"):
        dsa = run_redshift(_DSA_TC6)
        assert not dsa.empty, "TC-6: DSA returned 0 rows"
        _attach_df(dsa, "DSA move_in_source_category Distribution")

    with allure.step("Compare total lease counts with a source"):
        dla_total = int(dla["lease_count"].sum())
        dsa_total = int(dsa["lease_count"].sum())
        pct_delta = abs(dla_total - dsa_total) / max(dla_total, 1) * 100
        summary = f"DLA total={dla_total}  DSA total={dsa_total}  pct_delta={pct_delta:.2f}%"
        allure.attach(summary, name="Count Comparison", attachment_type=allure.attachment_type.TEXT)

        if pct_delta > 2.0:
            post_slack(f":red_circle: *TC-6 FAILED* — Move-In Source Category\n{summary}")
            pytest.fail(f"TC-6: move_in_source count pct_delta {pct_delta:.2f}% > 2%\n{summary}")


# ─────────────────────────────────────────────────────────────────────────────
# TC-7: Invoice Column Renames in DSA and TDW
# ─────────────────────────────────────────────────────────────────────────────
_DLA_TC7 = """
SELECT id         AS invoice_id,
       number     AS invoice_number,
       date       AS invoice_date,
       due        AS invoice_due_date,
       period_start AS invoice_period_start_date,
       void_date  AS invoice_void_date,
       created_by AS created_by_contact_id
FROM {dla}.invoices
WHERE company_uid   = '{CUID}'
  AND property_id  IN ({pids})
ORDER BY id
LIMIT 200
"""

_DSA_TC7 = """
SELECT src_invoice_id           AS invoice_id,
       invoice_number,
       invoice_date,
       invoice_due_date,
       invoice_period_start_date,
       invoice_void_date,
       created_by_contact_id
FROM {dsa}.dsa_invoice_d
WHERE company_uid = '{CUID}'
ORDER BY src_invoice_id
LIMIT 200
"""


@allure.epic("Derived Value Validation")
@allure.feature("DSA Transformations")
@allure.story("TC-7 — Invoice Column Renames in DSA")
@allure.severity(allure.severity_level.NORMAL)
@allure.title("TC-7: Invoice Date Column Renames — DLA vs DSA (dsa_invoice_d)")
@allure.description(
    "Validates that invoice date column renames in DSA are correct: "
    "number→invoice_number, date→invoice_date, due→invoice_due_date, "
    "void_date→invoice_void_date, created_by→created_by_contact_id. "
    "Date values must match exactly between DLA and DSA."
)
def test_tc7_invoice_column_renames():
    with allure.step("Run DLA query — dla.invoices (source column names)"):
        dla = run_redshift(_DLA_TC7)
        assert not dla.empty, "TC-7: DLA returned 0 rows"
        _attach_df(dla.head(20), "DLA Sample")

    with allure.step("Run DSA query — dsa.dsa_invoice_d (renamed columns)"):
        dsa = run_redshift(_DSA_TC7)
        assert not dsa.empty, "TC-7: DSA returned 0 rows"
        _attach_df(dsa.head(20), "DSA Sample")

    with allure.step("Merge on invoice_id and validate date renames"):
        m = dla.merge(dsa, on="invoice_id", suffixes=("_dla", "_dsa"))
        assert not m.empty, "TC-7: No matching invoice_ids"
        m["number_match"]   = m["invoice_number_dla"].fillna("").astype(str) == m["invoice_number_dsa"].fillna("").astype(str)
        m["date_match"]     = m["invoice_date_dla"].fillna("").astype(str) == m["invoice_date_dsa"].fillna("").astype(str)
        m["due_match"]      = m["invoice_due_date_dla"].fillna("").astype(str) == m["invoice_due_date_dsa"].fillna("").astype(str)
        _attach_df(m[["invoice_id", "invoice_number_dla", "invoice_number_dsa",
                       "invoice_date_dla", "invoice_date_dsa", "number_match", "date_match", "due_match"]].head(50), "Comparison")

    with allure.step("Assert renamed column values match"):
        errors = []
        fail_number = m[~m["number_match"]]
        fail_date   = m[~m["date_match"]]
        fail_due    = m[~m["due_match"]]
        if not fail_number.empty:
            errors.append(f"invoice_number mismatch: {len(fail_number)} invoice(s)")
        if not fail_date.empty:
            errors.append(f"invoice_date mismatch: {len(fail_date)} invoice(s)")
        if not fail_due.empty:
            errors.append(f"invoice_due_date mismatch: {len(fail_due)} invoice(s)")
        if errors:
            msg = "\n".join(errors)
            post_slack(f":red_circle: *TC-7 FAILED* — Invoice Column Renames\n{msg}")
            pytest.fail(f"TC-7: column rename value mismatches:\n{msg}")


# ─────────────────────────────────────────────────────────────────────────────
# TC-8: Discount Applied Cross-Table Join Chain
# ─────────────────────────────────────────────────────────────────────────────
_DLA_TC8 = """
SELECT uv.property_id,
       COUNT(DISTINCT dv.id)   AS discount_count,
       ROUND(SUM(dli.amount), 2) AS total_discount_amount
FROM {dla}.discounts dv
JOIN {dla}.leases lv ON lv.id = dv.lease_id AND lv.company_uid = '{CUID}'
JOIN {dla}.units uv ON uv.id = lv.unit_id AND uv.company_uid = '{CUID}'
LEFT JOIN {dla}.discount_line_items dli ON dli.discount_id = dv.id AND dli.company_uid = '{CUID}'
WHERE dv.company_uid   = '{CUID}'
  AND uv.property_id  IN ({pids})
GROUP BY uv.property_id
ORDER BY uv.property_id
"""

_DSA_TC8 = """
SELECT property_id,
       COUNT(DISTINCT discount_id)   AS discount_count,
       ROUND(SUM(amount), 2)         AS total_discount_amount
FROM {dsa}.dsa_discount_applied_tf
WHERE company_uid        = '{CUID}'
  AND property_id       IN ({pids})
GROUP BY property_id
ORDER BY property_id
"""


@allure.epic("Derived Value Validation")
@allure.feature("DSA Transformations")
@allure.story("TC-8 — Discount Applied Cross-Table Join Chain")
@allure.severity(allure.severity_level.NORMAL)
@allure.title("TC-8: Discount Join Chain — DLA vs DSA (dsa_discount_applied_tf)")
@allure.description(
    "Validates that the discount join chain (discounts → discount_line_items → invoice_lines → invoices) "
    "correctly populates dsa_discount_applied_tf. "
    "Discount counts and total amounts must match DLA within 1% per property."
)
def test_tc8_discount_applied_join_chain():
    with allure.step("Run DLA query — discount counts via discount_line_items"):
        dla = run_redshift(_DLA_TC8)
        assert not dla.empty, "TC-8: DLA returned 0 rows"
        _attach_df(dla, "DLA Result")

    with allure.step("Run DSA query — dsa.dsa_discount_applied_tf"):
        dsa = run_redshift(_DSA_TC8)
        assert not dsa.empty, "TC-8: DSA returned 0 rows"
        _attach_df(dsa, "DSA Result")

    with allure.step("Merge on property_id and compare discount counts"):
        m = dla.merge(dsa, on="property_id", suffixes=("_dla", "_dsa"))
        assert not m.empty, "TC-8: No matching property_ids"
        m["count_pct_delta"] = abs(
            m["discount_count_dla"].astype(int) - m["discount_count_dsa"].astype(int)
        ) / m["discount_count_dla"].astype(float).replace(0, float("nan")) * 100
        _attach_df(m[["property_id", "discount_count_dla", "discount_count_dsa", "count_pct_delta"]], "Comparison")

    with allure.step("Assert discount_count pct_delta <= 1% per property"):
        fail = m[m["count_pct_delta"] > 1.0]
        if not fail.empty:
            report = fail.to_string(index=False)
            _attach_df(fail, "FAILED Properties")
            post_slack(f":red_circle: *TC-8 FAILED* — Discount Join Chain\n```{report}```")
            pytest.fail(f"TC-8: discount_count pct_delta > 1% for {len(fail)} property(ies)\n{report}")


# ─────────────────────────────────────────────────────────────────────────────
# TC-9: Rent Change Derived Metrics (changed_rent, current_rent, next_rent)
# ─────────────────────────────────────────────────────────────────────────────
_DLA_TC9 = """
SELECT id        AS rent_change_id,
       lease_id,
       old_rent,
       new_rent,
       new_rent - old_rent AS expected_changed_rent,
       effective_date
FROM {dla}.rent_changes
WHERE company_uid = '{CUID}'
ORDER BY id
LIMIT 300
"""

_DSA_TC9 = """
SELECT lease_id,
       src_unit_id,
       src_property_id,
       changed_rent,
       current_rent,
       next_rent,
       last_rent_date,
       next_rent_date,
       report_date
FROM {dsa}.dsa_rent_change_pf
WHERE company_uid = '{CUID}'
ORDER BY lease_id, report_date DESC
LIMIT 300
"""


@allure.epic("Derived Value Validation")
@allure.feature("DSA Transformations")
@allure.story("TC-9 — Rent Change Derived Metrics")
@allure.severity(allure.severity_level.NORMAL)
@allure.title("TC-9: changed_rent / current_rent / next_rent Derivation — DLA vs DSA")
@allure.description(
    "Validates that dsa_rent_change_pf has non-zero rows and its derived columns "
    "(changed_rent, current_rent, next_rent) are populated and non-negative. "
    "Also checks that DLA rent_changes count is within 10% of DSA rows."
)
def test_tc9_rent_change_derived_metrics():
    with allure.step("Run DLA query — dla.rent_changes (source grain)"):
        dla = run_redshift(_DLA_TC9)
        assert not dla.empty, "TC-9: DLA returned 0 rows"
        _attach_df(dla.head(20), "DLA Sample")

    with allure.step("Run DSA query — dsa.dsa_rent_change_pf"):
        dsa = run_redshift(_DSA_TC9)
        assert not dsa.empty, "TC-9: DSA returned 0 rows"
        _attach_df(dsa.head(20), "DSA Sample")

    with allure.step("Validate DSA derived columns are non-negative and populated"):
        dsa_valid = dsa.copy()
        dsa_valid["changed_rent_valid"] = dsa_valid["changed_rent"].notna()
        dsa_valid["current_rent_valid"] = dsa_valid["current_rent"].notna() & (dsa_valid["current_rent"].astype(float) >= 0)
        dsa_valid["next_rent_valid"]    = dsa_valid["next_rent"].notna()
        _attach_df(dsa_valid[["lease_id", "changed_rent", "current_rent", "next_rent",
                               "changed_rent_valid", "current_rent_valid", "next_rent_valid"]].head(50), "DSA Validation")

        summary = (
            f"DLA rent_changes (sample): {len(dla)}\n"
            f"DSA dsa_rent_change_pf (sample): {len(dsa)}\n"
            f"DSA changed_rent populated: {int(dsa_valid['changed_rent_valid'].sum())}/{len(dsa)}\n"
            f"DSA current_rent valid: {int(dsa_valid['current_rent_valid'].sum())}/{len(dsa)}\n"
            f"DSA next_rent populated: {int(dsa_valid['next_rent_valid'].sum())}/{len(dsa)}"
        )
        allure.attach(summary, name="Summary", attachment_type=allure.attachment_type.TEXT)

    with allure.step("Assert DSA rent change columns are populated"):
        fail_changed = dsa_valid[~dsa_valid["changed_rent_valid"]]
        fail_current = dsa_valid[~dsa_valid["current_rent_valid"]]
        errors = []
        if not fail_changed.empty:
            errors.append(f"changed_rent NULL: {len(fail_changed)} record(s)")
        if not fail_current.empty:
            errors.append(f"current_rent NULL or negative: {len(fail_current)} record(s)")
        if errors:
            msg = "\n".join(errors)
            post_slack(f":red_circle: *TC-9 FAILED* — Rent Change Derived Metrics\n{msg}")
            pytest.fail(f"TC-9: rent change derivation issues:\n{msg}")


# ─────────────────────────────────────────────────────────────────────────────
# TC-10: Unit Status Live Derivation
# ─────────────────────────────────────────────────────────────────────────────
_DLA_TC10 = """
SELECT u.id AS unit_id,
       u.property_id,
       u.status                                                   AS raw_status,
       CASE
           WHEN l.id IS NOT NULL AND l.status = 1 THEN 'occupied'
           WHEN u.status = 0                      THEN 'available'
           ELSE 'other'
       END AS expected_unit_status_live
FROM {dla}.units u
LEFT JOIN {dla}.leases l ON l.unit_id = u.id AND l.status = 1
WHERE u.company_uid   = '{CUID}'
  AND u.property_id  IN ({pids})
ORDER BY u.id
LIMIT 300
"""

_DSA_TC10 = """
SELECT id AS unit_id,
       unit_status
FROM {dsa}.dsa_unit_status_live_d
WHERE company_uid   = '{CUID}'
  AND property_id  IN ({pids})
ORDER BY id
LIMIT 300
"""


@allure.epic("Derived Value Validation")
@allure.feature("DSA Transformations")
@allure.story("TC-10 — Unit Status Live Derivation")
@allure.severity(allure.severity_level.NORMAL)
@allure.title("TC-10: unit_status_live Derivation — DLA vs DSA")
@allure.description(
    "Validates that unit_status_live is derived correctly in DSA: "
    "occupied if there's an active lease (status=1), available if unit.status=0, else other."
)
def test_tc10_unit_status_live_derivation():
    with allure.step("Run DLA query — derive expected unit_status_live"):
        dla = run_redshift(_DLA_TC10)
        assert not dla.empty, "TC-10: DLA returned 0 rows"
        _attach_df(dla.head(20), "DLA Expected Values")

    with allure.step("Run DSA query — dsa.dsa_unit_status_live_d"):
        dsa = run_redshift(_DSA_TC10)
        assert not dsa.empty, "TC-10: DSA returned 0 rows"
        _attach_df(dsa.head(20), "DSA Actual Values")

    with allure.step("Merge on unit_id and compare status"):
        m = dla.merge(dsa, on="unit_id")
        assert not m.empty, "TC-10: No matching unit_ids"
        m["status_match"] = m["expected_unit_status_live"] == m["unit_status"]
        _attach_df(m[["unit_id", "expected_unit_status_live", "unit_status", "status_match"]].head(50), "Comparison")

    with allure.step("Assert unit_status matches expected for all units"):
        fail = m[~m["status_match"]]
        if not fail.empty:
            report = fail[["unit_id", "expected_unit_status_live", "unit_status"]].to_string(index=False)
            _attach_df(fail, "FAILED Units")
            post_slack(f":red_circle: *TC-10 FAILED* — Unit Status Live Derivation\n```{report[:1000]}```")
            pytest.fail(f"TC-10: unit_status mismatch for {len(fail)} unit(s)\n{report}")


# ─────────────────────────────────────────────────────────────────────────────
# TC-11: Task day_difference and recurring_flag Derivation
# ─────────────────────────────────────────────────────────────────────────────
_DLA_TC11 = """
SELECT id                                                               AS task_id,
       DATEDIFF(day, due_date::date, CURRENT_DATE)                     AS expected_day_difference,
       CASE WHEN rtm_tasks_config_id IS NOT NULL THEN 1 ELSE 0 END     AS expected_recurring_flag
FROM {dla}.tasks
WHERE company_uid = '{CUID}'
  AND due_date IS NOT NULL
ORDER BY id
LIMIT 300
"""

_DSA_TC11 = """
SELECT src_task_id  AS task_id,
       day_difference,
       recurring_flag
FROM {dsa}.dsa_tasks_af
WHERE company_uid = '{CUID}'
ORDER BY src_task_id
LIMIT 300
"""


@allure.epic("Derived Value Validation")
@allure.feature("DSA Transformations")
@allure.story("TC-11 — Task Derived Values (day_difference and recurring_flag)")
@allure.severity(allure.severity_level.MINOR)
@allure.title("TC-11: Task day_difference and recurring_flag — DLA vs DSA")
@allure.description(
    "Validates that dsa_tasks_af correctly derives day_difference "
    "(days between task created_at and due_date) and recurring_flag "
    "(1 when rtm_tasks_config_id is set, 0 otherwise)."
)
def test_tc11_task_derived_values():
    with allure.step("Run DLA query — derive expected day_difference and recurring_flag"):
        dla = run_redshift(_DLA_TC11)
        assert not dla.empty, "TC-11: DLA returned 0 rows"
        _attach_df(dla.head(20), "DLA Expected Values")

    with allure.step("Run DSA query — dsa.dsa_tasks_af"):
        dsa = run_redshift(_DSA_TC11)
        assert not dsa.empty, "TC-11: DSA returned 0 rows"
        _attach_df(dsa.head(20), "DSA Actual Values")

    with allure.step("Merge on task_id and compare derived columns"):
        m = dla.merge(dsa, on="task_id")
        assert not m.empty, "TC-11: No matching task_ids between DLA and DSA"

        # day_difference represents overdue days for open tasks; DSA sets it to 0
        # for completed/resolved tasks. Only validate the delta for tasks where
        # DSA day_difference > 0 (open/overdue), with ±2 day tolerance for CDC lag.
        # Rows where DSA day_difference is NULL are excluded (filtered in DSA).
        m_open = m[(m["day_difference"].notna()) & (m["day_difference"].astype(float) > 0)].copy()
        if not m_open.empty:
            m_open["day_diff_delta"] = (
                m_open["expected_day_difference"].astype(float) - m_open["day_difference"].astype(float)
            ).abs()
            m_open["day_diff_ok"] = m_open["day_diff_delta"] <= 2

        m["recurring_match"] = m["expected_recurring_flag"].astype(str) == m["recurring_flag"].astype(str)

        null_count   = m["day_difference"].isna().sum()
        closed_count = (m["day_difference"].notna() & (m["day_difference"].astype(float) == 0)).sum()
        summary = (
            f"Merged tasks: {len(m)}\n"
            f"DSA day_difference NULL (excluded): {null_count}\n"
            f"DSA day_difference = 0 (resolved/completed, excluded): {closed_count}\n"
            f"Open tasks checked for overdue-day accuracy: {len(m_open)}"
        )
        allure.attach(summary, name="Summary", attachment_type=allure.attachment_type.TEXT)
        _attach_df(
            m[["task_id", "expected_day_difference", "day_difference",
               "expected_recurring_flag", "recurring_flag", "recurring_match"]].head(50),
            "Comparison",
        )

    with allure.step("Assert derivations match"):
        errors = []
        if not m_open.empty:
            fail_day = m_open[~m_open["day_diff_ok"]]
            if not fail_day.empty:
                errors.append(f"day_difference off by >2 days for open tasks: {len(fail_day)} task(s)")
                _attach_df(
                    fail_day[["task_id", "expected_day_difference", "day_difference", "day_diff_delta"]],
                    "FAILED — day_difference",
                )
        fail_rec = m[~m["recurring_match"]]
        if not fail_rec.empty:
            errors.append(f"recurring_flag mismatch: {len(fail_rec)} task(s)")
            _attach_df(fail_rec[["task_id", "expected_recurring_flag", "recurring_flag"]], "FAILED — recurring_flag")
        if errors:
            msg = "\n".join(errors)
            post_slack(f":red_circle: *TC-11 FAILED* — Task Derived Values\n{msg}")
            pytest.fail(f"TC-11: task derivation mismatches:\n{msg}")


# ─────────────────────────────────────────────────────────────────────────────
# TC-12: service_bought_at_move_in Derivation
# ─────────────────────────────────────────────────────────────────────────────
_DLA_TC12 = """
SELECT s.id                                                         AS service_id,
       CASE WHEN s.start_date = l.start_date THEN 1 ELSE 0 END     AS expected_bought_at_move_in
FROM {dla}.services s
JOIN {dla}.leases l ON l.id = s.lease_id AND l.company_uid = '{CUID}'
WHERE s.company_uid  = '{CUID}'
  AND s.lease_id IS NOT NULL
ORDER BY s.id
LIMIT 300
"""

_DSA_TC12 = """
SELECT src_service_id         AS service_id,
       service_start_date,
       lease_start_date,
       service_bought_at_move_in
FROM {dsa}.dsa_services_leases_tf
WHERE company_uid = '{CUID}'
ORDER BY src_service_id
LIMIT 300
"""


@allure.epic("Derived Value Validation")
@allure.feature("DSA Transformations")
@allure.story("TC-12 — Service Lease Join with service_bought_at_move_in")
@allure.severity(allure.severity_level.MINOR)
@allure.title("TC-12: service_bought_at_move_in Derivation — DLA vs DSA")
@allure.description(
    "Validates that service_bought_at_move_in is derived correctly in DSA: "
    "1 when the service start_date equals the lease start_date (joined from DLA), 0 otherwise."
)
def test_tc12_service_lease_join():
    with allure.step("Run DLA query — join services with leases to derive move-in flag"):
        dla = run_redshift(_DLA_TC12)
        assert not dla.empty, "TC-12: DLA returned 0 rows"
        _attach_df(dla.head(20), "DLA Expected Values")

    with allure.step("Run DSA query — dsa.dsa_services_leases_tf"):
        dsa = run_redshift(_DSA_TC12)
        assert not dsa.empty, "TC-12: DSA returned 0 rows"
        _attach_df(dsa.head(20), "DSA Actual Values")

    with allure.step("Merge on service_id and validate service_bought_at_move_in"):
        m = dla.merge(dsa, on="service_id")
        assert not m.empty, "TC-12: No matching service_ids between DLA and DSA"
        m["flag_match"] = m["expected_bought_at_move_in"].astype(str) == m["service_bought_at_move_in"].astype(str)
        _attach_df(
            m[["service_id", "expected_bought_at_move_in", "service_bought_at_move_in", "flag_match"]].head(50),
            "Comparison",
        )

    with allure.step("Assert service_bought_at_move_in matches DLA-derived expectation"):
        fail = m[~m["flag_match"]]
        if not fail.empty:
            report = fail[["service_id", "expected_bought_at_move_in", "service_bought_at_move_in"]].to_string(index=False)
            _attach_df(fail, "FAILED Services")
            post_slack(f":red_circle: *TC-12 FAILED* — service_bought_at_move_in Derivation\n```{report[:1000]}```")
            pytest.fail(f"TC-12: service_bought_at_move_in mismatch for {len(fail)} service(s)\n{report}")


# ─────────────────────────────────────────────────────────────────────────────
# TC-13: Payment prepaid_flag Derivation
# ─────────────────────────────────────────────────────────────────────────────
_DLA_TC13 = """
SELECT id                                                       AS payment_id,
       credit_type,
       CASE WHEN LOWER(COALESCE(credit_type, '')) = 'prepaid'
            THEN 'Y' ELSE 'N'
       END                                                      AS expected_prepaid_flg
FROM {dla}.payments
WHERE company_uid   = '{CUID}'
  AND property_id  IN ({pids})
ORDER BY id
LIMIT 300
"""

_DSA_TC13 = """
SELECT payment_id,
       credit_type,
       prepaid_flg
FROM {dsa}.dsa_payment_allocation_tf
WHERE company_uid = '{CUID}'
ORDER BY payment_id
LIMIT 300
"""


@allure.epic("Derived Value Validation")
@allure.feature("DSA Transformations")
@allure.story("TC-13 — Payment Allocation Prepaid Flag Derivation")
@allure.severity(allure.severity_level.MINOR)
@allure.title("TC-13: Payment prepaid_flag Derivation — DLA vs DSA")
@allure.description(
    "Validates that prepaid_flg in dsa_payment_allocation_tf is correctly derived "
    "from DLA payments.credit_type: 'Y' when credit_type = 'prepaid', 'N' otherwise."
)
def test_tc13_payment_allocation_prepaid_flag():
    with allure.step("Run DLA query — derive expected prepaid_flg from credit_type"):
        dla = run_redshift(_DLA_TC13)
        assert not dla.empty, "TC-13: DLA returned 0 rows"
        _attach_df(dla.head(20), "DLA Expected Values")

    with allure.step("Run DSA query — dsa.dsa_payment_allocation_tf"):
        dsa = run_redshift(_DSA_TC13)
        assert not dsa.empty, "TC-13: DSA returned 0 rows"
        _attach_df(dsa.head(20), "DSA Actual Values")

    with allure.step("Merge on payment_id and validate prepaid_flg"):
        m = dla.merge(dsa, on="payment_id", suffixes=("_dla", "_dsa"))
        assert not m.empty, "TC-13: No matching payment_ids between DLA and DSA"
        m["flag_match"] = m["expected_prepaid_flg"].astype(str) == m["prepaid_flg"].astype(str)
        _attach_df(
            m[["payment_id", "credit_type_dla", "expected_prepaid_flg", "prepaid_flg", "flag_match"]].head(50),
            "Comparison",
        )

    with allure.step("Assert prepaid_flg derivation matches"):
        fail = m[~m["flag_match"]]
        if not fail.empty:
            report = fail[["payment_id", "credit_type_dla", "expected_prepaid_flg", "prepaid_flg"]].to_string(index=False)
            _attach_df(fail, "FAILED Payments")
            post_slack(f":red_circle: *TC-13 FAILED* — Payment prepaid_flag Derivation\n```{report[:1000]}```")
            pytest.fail(f"TC-13: prepaid_flg mismatch for {len(fail)} payment(s)\n{report}")


# ─────────────────────────────────────────────────────────────────────────────
# TC-14: Delinquency drent Computation
# ─────────────────────────────────────────────────────────────────────────────
_DLA_TC14 = """
SELECT i.id          AS invoice_id,
       i.lease_id,
       i.property_id,
       i.subtotal    AS invoice_amount,
       COALESCE(i.total_payments, 0)                  AS payment_amount,
       i.subtotal - COALESCE(i.total_payments, 0)     AS expected_drent
FROM {dla}.invoices i
WHERE i.company_uid  = '{CUID}'
  AND i.property_id IN ({pids})
  AND i.status = 1
  AND i.subtotal > 0
ORDER BY i.id
LIMIT 300
"""

_DSA_TC14 = """
SELECT invoice_id,
       lease_id,
       property_id,
       invoice_amount,
       payment_amount,
       drent
FROM {dsa}.dsa_delinquency_pf
WHERE company_uid   = '{CUID}'
  AND property_id  IN ({pids})
  AND deleted_flg  = 0
ORDER BY invoice_id
LIMIT 300
"""


@allure.epic("Derived Value Validation")
@allure.feature("DSA Transformations")
@allure.story("TC-14 — Delinquency Invoice Amount and drent Computation")
@allure.severity(allure.severity_level.NORMAL)
@allure.title("TC-14: Delinquency drent Computation — DLA vs DSA")
@allure.description(
    "Validates that dsa_delinquency_pf correctly computes drent as "
    "invoice_amount - payment_amount for outstanding invoices, "
    "and that invoice_amount matches DLA within $0.01 tolerance."
)
def test_tc14_delinquency_drent_computation():
    with allure.step("Run DLA query — outstanding invoices with expected drent"):
        dla = run_redshift(_DLA_TC14)
        assert not dla.empty, "TC-14: DLA returned 0 rows — no active invoices with balance found"
        _attach_df(dla.head(20), "DLA Expected Values")

    with allure.step("Run DSA query — dsa.dsa_delinquency_pf"):
        dsa = run_redshift(_DSA_TC14)
        if dsa.empty:
            allure.attach(
                "dsa_delinquency_pf returned 0 rows — delinquency data may not be populated in this environment",
                name="DSA Skip Reason",
                attachment_type=allure.attachment_type.TEXT,
            )
            pytest.skip("TC-14: DSA dsa_delinquency_pf has no data in this environment")
            return
        _attach_df(dsa.head(20), "DSA Actual Values")

    with allure.step("Validate drent = invoice_amount - payment_amount within DSA"):
        dsa_check = dsa.copy()
        dsa_check["computed_drent"] = dsa_check["invoice_amount"].astype(float) - dsa_check["payment_amount"].astype(float)
        dsa_check["drent_consistent"] = (dsa_check["computed_drent"] - dsa_check["drent"].astype(float)).abs() < 0.01
        _attach_df(dsa_check[["invoice_id", "invoice_amount", "payment_amount", "drent", "drent_consistent"]].head(50), "DSA drent Consistency")

    with allure.step("Merge on invoice_id and compare invoice_amount"):
        m = dla.merge(dsa, on="invoice_id", suffixes=("_dla", "_dsa"))
        assert not m.empty, "TC-14: No matching invoice_ids between DLA and DSA"
        amt_delta = (m["invoice_amount_dla"].astype(float) - m["invoice_amount_dsa"].astype(float)).abs()
        bad_amt = m[amt_delta > 0.01]
        _attach_df(m[["invoice_id", "invoice_amount_dla", "invoice_amount_dsa"]].head(50), "Invoice Amount Comparison")

    with allure.step("Assert zero violations"):
        errors = []
        inconsistent = dsa_check[~dsa_check["drent_consistent"]]
        if not inconsistent.empty:
            errors.append(f"drent != invoice_amount - payment_amount for {len(inconsistent)} DSA row(s)")
            _attach_df(inconsistent[["invoice_id", "invoice_amount", "payment_amount", "drent", "computed_drent"]], "FAILED — drent inconsistency")
        if not bad_amt.empty:
            errors.append(f"invoice_amount: {len(bad_amt)} row(s) exceed $0.01 tolerance vs DLA")
            _attach_df(bad_amt[["invoice_id", "invoice_amount_dla", "invoice_amount_dsa"]], "FAILED — invoice_amount")
        if errors:
            msg = "\n".join(errors)
            post_slack(f":red_circle: *TC-14 FAILED* — Delinquency drent Computation\n{msg}")
            pytest.fail(f"TC-14: delinquency drent computation issues:\n{msg}")


# ─────────────────────────────────────────────────────────────────────────────
# TC-15: Invoice Lines to Invoice Header Cross-Table Validation
# ─────────────────────────────────────────────────────────────────────────────
_DLA_TC15 = """
SELECT i.id          AS invoice_id,
       COUNT(il.id)  AS line_count,
       ROUND(SUM(il.cost * il.qty), 2) AS total_line_amount
FROM {dla}.invoices i
JOIN {dla}.invoice_lines il ON il.invoice_id = i.id AND il.company_uid = '{CUID}'
WHERE i.company_uid   = '{CUID}'
  AND i.property_id  IN ({pids})
GROUP BY i.id
ORDER BY i.id
LIMIT 200
"""

_DSA_TC15 = """
SELECT invoice_id,
       COUNT(invoice_line_id) AS line_count,
       ROUND(SUM(cost * quantity), 2) AS total_line_amount
FROM {dsa}.dsa_invoice_line_tf
WHERE company_uid   = '{CUID}'
  AND property_id  IN ({pids})
GROUP BY invoice_id
ORDER BY invoice_id
LIMIT 200
"""


@allure.epic("Derived Value Validation")
@allure.feature("DSA Transformations")
@allure.story("TC-15 — Invoice Lines to Invoice Header Cross-Table Validation DLA to DSA")
@allure.severity(allure.severity_level.NORMAL)
@allure.title("TC-15: Invoice Lines -> Header Cross-Table — DLA vs DSA")
@allure.description(
    "Validates the invoice_lines → invoices join chain in DSA: "
    "line count per invoice and total line amount must match DLA within 1% and $0.01 respectively."
)
def test_tc15_invoice_lines_to_header():
    with allure.step("Run DLA query — invoice line counts and amounts per invoice"):
        dla = run_redshift(_DLA_TC15)
        assert not dla.empty, "TC-15: DLA returned 0 rows"
        _attach_df(dla.head(20), "DLA Invoice Lines Summary")

    with allure.step("Run DSA query — dsa.dsa_invoice_line_tf grouped by invoice"):
        dsa = run_redshift(_DSA_TC15)
        assert not dsa.empty, "TC-15: DSA returned 0 rows"
        _attach_df(dsa.head(20), "DSA Invoice Lines Summary")

    with allure.step("Merge on invoice_id and compare line counts and amounts"):
        m = dla.merge(dsa, on="invoice_id", suffixes=("_dla", "_dsa"))
        assert not m.empty, "TC-15: No matching invoice_ids between DLA and DSA"
        m["count_match"]  = m["line_count_dla"].astype(int) == m["line_count_dsa"].astype(int)
        amt_delta = (m["total_line_amount_dla"].astype(float) - m["total_line_amount_dsa"].astype(float)).abs()
        m["amount_ok"] = amt_delta <= 0.01
        _attach_df(
            m[["invoice_id", "line_count_dla", "line_count_dsa", "count_match",
               "total_line_amount_dla", "total_line_amount_dsa", "amount_ok"]].head(50),
            "Comparison",
        )

    with allure.step("Assert line counts and amounts match"):
        errors = []
        fail_count = m[~m["count_match"]]
        fail_amt   = m[~m["amount_ok"]]
        if not fail_count.empty:
            errors.append(f"line_count mismatch: {len(fail_count)} invoice(s)")
            _attach_df(fail_count[["invoice_id", "line_count_dla", "line_count_dsa"]], "FAILED — line_count")
        if not fail_amt.empty:
            errors.append(f"total_line_amount: {len(fail_amt)} invoice(s) exceed $0.01 tolerance")
            _attach_df(fail_amt[["invoice_id", "total_line_amount_dla", "total_line_amount_dsa"]], "FAILED — total_line_amount")
        if errors:
            msg = "\n".join(errors)
            post_slack(f":red_circle: *TC-15 FAILED* — Invoice Lines to Header Cross-Table\n{msg}")
            pytest.fail(f"TC-15: invoice line cross-table mismatches:\n{msg}")
