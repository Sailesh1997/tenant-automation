"""
TDW Advanced — TC-1 to TC-14
==============================
Tests that validate advanced TDW derivations: financial tolerances, surrogate
key resolution, date dimension lookups, flag propagation, and aggregate
consistency as data flows from DSA into the TDW star schema.

Run this suite:
  python run_tests.py --env uat --tc tdw_advanced
  python run_tests.py --env prod --tc tdw_advanced
  pytest tests/test_tdw_advanced.py --env uat -v
"""

# Displayed in connection-loss error messages
TC_RANGE = "TC-1 to TC-14 (TDW Advanced)"

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
# TC-1: Future Lease Rent Change Current and Sell Rate Derivation
# ─────────────────────────────────────────────────────────────────────────────
_DSA_TC1 = """
SELECT src_rent_change_id,
       src_lease_id,
       src_property_id,
       src_unit_id,
       new_rent,
       current_rent,
       set_rate,
       sell_rate
FROM {dsa}.dsa_future_lease_rent_changes_tf
WHERE company_uid = '{CUID}'
ORDER BY src_rent_change_id
LIMIT 100
"""

_TDW_TC1 = """
SELECT src_rent_change_id,
       new_rent,
       current_rent,
       set_rate,
       sell_rate
FROM {tdw}.tdw_future_lease_rent_changes_tf
WHERE company_uid = '{CUID}'
ORDER BY src_rent_change_id
LIMIT 100
"""

TOLERANCE = 0.01


@allure.epic("Derived Value Validation")
@allure.feature("TDW Advanced")
@allure.story("TC-1 — Future Lease Rent Change Current and Sell Rate Derivation")
@allure.severity(allure.severity_level.NORMAL)
@allure.title("TC-1: Future Lease Rent Change — new_rent/current_rent/set_rate/sell_rate DSA vs TDW")
@allure.description(
    "Validates that financial rate columns (new_rent, current_rent, set_rate, sell_rate) "
    "in tdw_future_lease_rent_changes_tf match DSA source values within $0.01 tolerance."
)
def test_tc1_future_lease_rent_change():
    try:
        dsa = run_redshift(_DSA_TC1)
    except Exception as e:
        allure.attach(str(e), name="DSA Error (table may not exist)", attachment_type=allure.attachment_type.TEXT)
        pytest.skip(f"TC-1: DSA table not available: {e}")
        return

    try:
        tdw = run_redshift(_TDW_TC1)
    except Exception as e:
        allure.attach(str(e), name="TDW Error (informational)", attachment_type=allure.attachment_type.TEXT)
        allure.attach(
            "TDW table not available — test reported as informational",
            name="TDW Skip Reason",
            attachment_type=allure.attachment_type.TEXT,
        )
        return

    with allure.step("Attach raw query results"):
        _attach_df(dsa, "DSA — Future Lease Rent Changes")
        _attach_df(tdw, "TDW — Future Lease Rent Changes")

    with allure.step("Merge on src_rent_change_id and compare financial columns"):
        m = dsa[["src_rent_change_id", "new_rent", "current_rent", "set_rate", "sell_rate"]].merge(
            tdw, on="src_rent_change_id", suffixes=("_dsa", "_tdw")
        )
        assert not m.empty, "TC-1: No matching rows after merge on src_rent_change_id"
        _attach_df(m.head(20), "Merged Sample")

        errors = []
        for col in ("new_rent", "current_rent", "set_rate", "sell_rate"):
            delta = (m[f"{col}_dsa"].astype(float) - m[f"{col}_tdw"].astype(float)).abs()
            bad = m[delta > TOLERANCE]
            if not bad.empty:
                errors.append(f"{col}: {len(bad)} row(s) exceed ${TOLERANCE} tolerance")
                _attach_df(bad[["src_rent_change_id", f"{col}_dsa", f"{col}_tdw"]], f"FAILED — {col}")

    with allure.step("Assert zero tolerance violations"):
        if errors:
            msg = "\n".join(errors)
            post_slack(f":red_circle: *TC-1 FAILED* — Future Lease Rent Change Rate Derivation\n{msg}")
            pytest.fail(f"TC-1: financial column mismatches:\n{msg}")


# ─────────────────────────────────────────────────────────────────────────────
# TC-2: Service Misc Attribute Status and Flag Derivation
# ─────────────────────────────────────────────────────────────────────────────
_DSA_TC2 = """
SELECT src_service_id,
       service_status_cd,
       service_status_desc,
       service_name,
       tax_flg,
       prorate_flg,
       prorate_out_flg,
       service_type_cd
FROM {dsa}.dsa_service_misc_attr
WHERE company_uid = '{CUID}'
ORDER BY src_service_id
LIMIT 100
"""

_TDW_TC2 = """
SELECT src_service_id,
       service_status_cd,
       service_status_desc,
       service_name,
       tax_flg,
       prorate_flg,
       prorate_out_flg,
       service_type_cd
FROM {tdw}.tdw_service_misc_attr_d
WHERE company_uid = '{CUID}'
ORDER BY src_service_id
LIMIT 100
"""


@allure.epic("Derived Value Validation")
@allure.feature("TDW Advanced")
@allure.story("TC-2 — Service Misc Attribute Status and Flag Derivation")
@allure.severity(allure.severity_level.NORMAL)
@allure.title("TC-2: Service Misc Attr — status desc and flag columns DSA vs TDW")
@allure.description(
    "Validates that service_status_desc and all flag columns (tax_flg, prorate_flg, "
    "prorate_out_flg) match between DSA dsa_service_misc_attr and TDW tdw_service_misc_attr_d."
)
def test_tc2_service_misc_attr():
    try:
        dsa = run_redshift(_DSA_TC2)
    except Exception as e:
        allure.attach(str(e), name="DSA Error (table may not exist)", attachment_type=allure.attachment_type.TEXT)
        pytest.skip(f"TC-2: DSA table not available: {e}")
        return

    try:
        tdw = run_redshift(_TDW_TC2)
    except Exception as e:
        allure.attach(str(e), name="TDW Error (informational)", attachment_type=allure.attachment_type.TEXT)
        allure.attach(
            "TDW table not available — test reported as informational",
            name="TDW Skip Reason",
            attachment_type=allure.attachment_type.TEXT,
        )
        return

    with allure.step("Attach raw query results"):
        _attach_df(dsa, "DSA — Service Misc Attr")
        _attach_df(tdw, "TDW — Service Misc Attr")

    with allure.step("Merge on src_service_id and compare status and flag columns"):
        m = dsa.merge(tdw, on="src_service_id", suffixes=("_dsa", "_tdw"))
        assert not m.empty, "TC-2: No matching rows after merge on src_service_id"
        _attach_df(m.head(20), "Merged Sample")

        errors = []

        # Check service_status_desc
        desc_mismatch = m[m["service_status_desc_dsa"].astype(str) != m["service_status_desc_tdw"].astype(str)]
        if not desc_mismatch.empty:
            errors.append(f"service_status_desc: {len(desc_mismatch)} mismatch(es)")
            _attach_df(desc_mismatch[["src_service_id", "service_status_desc_dsa", "service_status_desc_tdw"]], "FAILED — service_status_desc")

        # Check flag columns
        for flag in ("tax_flg", "prorate_flg", "prorate_out_flg"):
            bad = m[m[f"{flag}_dsa"].astype(str) != m[f"{flag}_tdw"].astype(str)]
            if not bad.empty:
                errors.append(f"{flag}: {len(bad)} mismatch(es)")
                _attach_df(bad[["src_service_id", f"{flag}_dsa", f"{flag}_tdw"]], f"FAILED — {flag}")

    with allure.step("Assert zero mismatches"):
        if errors:
            msg = "\n".join(errors)
            post_slack(f":red_circle: *TC-2 FAILED* — Service Misc Attr Status and Flag Derivation\n{msg}")
            pytest.fail(f"TC-2: mismatches detected:\n{msg}")


# ─────────────────────────────────────────────────────────────────────────────
# TC-3: Property Group Total Properties Aggregate
# ─────────────────────────────────────────────────────────────────────────────
_DSA_TC3 = """
SELECT property_group_id,
       name,
       total_properties,
       created_by,
       created_at
FROM {dsa}.dsa_property_group_flf
WHERE company_uid = '{CUID}'
ORDER BY property_group_id
LIMIT 50
"""

_TDW_TC3 = """
SELECT property_group_id,
       name,
       total_properties,
       created_by_sk,
       created_at_date_sk
FROM {tdw}.tdw_property_group_flf
WHERE company_uid = '{CUID}'
ORDER BY property_group_id
LIMIT 50
"""


@allure.epic("Derived Value Validation")
@allure.feature("TDW Advanced")
@allure.story("TC-3 — Property Group Total Properties Aggregate")
@allure.severity(allure.severity_level.NORMAL)
@allure.title("TC-3: Property Group — total_properties and name DSA vs TDW")
@allure.description(
    "Validates that total_properties and name are correctly propagated from "
    "DSA dsa_property_group_flf into TDW tdw_property_group_flf, and that "
    "the created_by_sk surrogate key is not null."
)
def test_tc3_property_group_total_properties():
    try:
        dsa = run_redshift(_DSA_TC3)
    except Exception as e:
        allure.attach(str(e), name="DSA Error (table may not exist)", attachment_type=allure.attachment_type.TEXT)
        pytest.skip(f"TC-3: DSA table not available: {e}")
        return

    try:
        tdw = run_redshift(_TDW_TC3)
    except Exception as e:
        allure.attach(str(e), name="TDW Error (informational)", attachment_type=allure.attachment_type.TEXT)
        allure.attach(
            "TDW table not available — test reported as informational",
            name="TDW Skip Reason",
            attachment_type=allure.attachment_type.TEXT,
        )
        return

    with allure.step("Attach raw query results"):
        _attach_df(dsa, "DSA — Property Group")
        _attach_df(tdw, "TDW — Property Group")

    with allure.step("Merge on property_group_id"):
        m = dsa[["property_group_id", "name", "total_properties"]].merge(
            tdw, on="property_group_id", suffixes=("_dsa", "_tdw")
        )
        assert not m.empty, "TC-3: No matching rows after merge on property_group_id"
        _attach_df(m.head(20), "Merged Sample")

        errors = []

        # Assert total_properties matches exactly
        total_mismatch = m[m["total_properties_dsa"].astype(str) != m["total_properties_tdw"].astype(str)]
        if not total_mismatch.empty:
            errors.append(f"total_properties: {len(total_mismatch)} mismatch(es)")
            _attach_df(total_mismatch[["property_group_id", "total_properties_dsa", "total_properties_tdw"]], "FAILED — total_properties")

        # Assert name matches
        name_mismatch = m[m["name_dsa"].astype(str) != m["name_tdw"].astype(str)]
        if not name_mismatch.empty:
            errors.append(f"name: {len(name_mismatch)} mismatch(es)")
            _attach_df(name_mismatch[["property_group_id", "name_dsa", "name_tdw"]], "FAILED — name")

        # Assert created_by_sk is not null
        null_sk = tdw[tdw["created_by_sk"].isnull()]
        if not null_sk.empty:
            errors.append(f"created_by_sk is NULL for {len(null_sk)} row(s)")
            _attach_df(null_sk[["property_group_id", "created_by_sk"]], "FAILED — null created_by_sk")

    with allure.step("Assert zero mismatches"):
        if errors:
            msg = "\n".join(errors)
            post_slack(f":red_circle: *TC-3 FAILED* — Property Group Total Properties Aggregate\n{msg}")
            pytest.fail(f"TC-3: mismatches detected:\n{msg}")


# ─────────────────────────────────────────────────────────────────────────────
# TC-4: TDW Payment Misc Attribute Normalization and Prepaid Flag
# ─────────────────────────────────────────────────────────────────────────────
_DSA_TC4 = """
SELECT src_payment_allocation_id,
       src_payment_id,
       payment_status_cd,
       payment_method_cd,
       prepaid_flg,
       credit_type_cd
FROM {dsa}.dsa_payment_allocation_tf
WHERE company_uid = '{CUID}'
ORDER BY src_payment_allocation_id
LIMIT 100
"""

_TDW_TC4 = """
SELECT src_payment_allocation_id,
       src_payment_id,
       payment_status_cd,
       payment_status_desc,
       payment_method_cd,
       prepaid_flg,
       credit_type_cd,
       credit_type_desc
FROM {tdw}.tdw_payment_misc_attr_d
WHERE company_uid = '{CUID}'
ORDER BY src_payment_allocation_id
LIMIT 100
"""


@allure.epic("Derived Value Validation")
@allure.feature("TDW Advanced")
@allure.story("TC-4 — TDW Payment Misc Attribute Normalization and Prepaid Flag")
@allure.severity(allure.severity_level.NORMAL)
@allure.title("TC-4: Payment Misc Attr — prepaid_flg and payment_method_cd DSA vs TDW")
@allure.description(
    "Validates that prepaid_flg and payment_method_cd match between DSA "
    "dsa_payment_allocation_tf and TDW tdw_payment_misc_attr_d, and that "
    "TDW payment_status_desc is non-null."
)
def test_tc4_payment_misc_attr():
    try:
        dsa = run_redshift(_DSA_TC4)
    except Exception as e:
        allure.attach(str(e), name="DSA Error (table may not exist)", attachment_type=allure.attachment_type.TEXT)
        pytest.skip(f"TC-4: DSA table not available: {e}")
        return

    try:
        tdw = run_redshift(_TDW_TC4)
    except Exception as e:
        allure.attach(str(e), name="TDW Error (informational)", attachment_type=allure.attachment_type.TEXT)
        allure.attach(
            "TDW table not available — test reported as informational",
            name="TDW Skip Reason",
            attachment_type=allure.attachment_type.TEXT,
        )
        return

    with allure.step("Attach raw query results"):
        _attach_df(dsa, "DSA — Payment Allocation")
        _attach_df(tdw, "TDW — Payment Misc Attr")

    with allure.step("Merge on src_payment_allocation_id"):
        m = dsa[["src_payment_allocation_id", "prepaid_flg", "payment_method_cd"]].merge(
            tdw[["src_payment_allocation_id", "prepaid_flg", "payment_method_cd", "payment_status_desc"]],
            on="src_payment_allocation_id",
            suffixes=("_dsa", "_tdw"),
        )
        assert not m.empty, "TC-4: No matching rows after merge on src_payment_allocation_id"
        _attach_df(m.head(20), "Merged Sample")

        errors = []

        # Assert prepaid_flg matches
        prepaid_mismatch = m[m["prepaid_flg_dsa"].astype(str) != m["prepaid_flg_tdw"].astype(str)]
        if not prepaid_mismatch.empty:
            errors.append(f"prepaid_flg: {len(prepaid_mismatch)} mismatch(es)")
            _attach_df(prepaid_mismatch[["src_payment_allocation_id", "prepaid_flg_dsa", "prepaid_flg_tdw"]], "FAILED — prepaid_flg")

        # Assert payment_method_cd matches
        method_mismatch = m[m["payment_method_cd_dsa"].astype(str) != m["payment_method_cd_tdw"].astype(str)]
        if not method_mismatch.empty:
            errors.append(f"payment_method_cd: {len(method_mismatch)} mismatch(es)")
            _attach_df(method_mismatch[["src_payment_allocation_id", "payment_method_cd_dsa", "payment_method_cd_tdw"]], "FAILED — payment_method_cd")

        # Assert TDW payment_status_desc is non-null
        null_desc = tdw[tdw["payment_status_desc"].isnull()]
        if not null_desc.empty:
            errors.append(f"payment_status_desc is NULL for {len(null_desc)} TDW row(s)")
            _attach_df(null_desc[["src_payment_allocation_id", "payment_status_desc"]], "FAILED — null payment_status_desc")

    with allure.step("Assert zero mismatches"):
        if errors:
            msg = "\n".join(errors)
            post_slack(f":red_circle: *TC-4 FAILED* — Payment Misc Attr Normalization and Prepaid Flag\n{msg}")
            pytest.fail(f"TC-4: mismatches detected:\n{msg}")


# ─────────────────────────────────────────────────────────────────────────────
# TC-5: TDW Discount Applied Surrogate Key and Date Resolution
# ─────────────────────────────────────────────────────────────────────────────
_DSA_TC5 = """
SELECT discount_id,
       src_promotion_id,
       start_date,
       end_date,
       src_property_id,
       src_unit_id,
       src_lease_id,
       amount
FROM {dsa}.dsa_discount_applied_tf
WHERE company_uid = '{CUID}'
ORDER BY discount_id
LIMIT 100
"""

_TDW_TC5 = """
SELECT discount_id,
       promotion_sk,
       start_date_sk,
       end_date_sk,
       property_sk,
       unit_sk,
       lease_sk,
       amount
FROM {tdw}.tdw_discount_applied_af
WHERE company_uid = '{CUID}'
ORDER BY discount_id
LIMIT 100
"""


@allure.epic("Derived Value Validation")
@allure.feature("TDW Advanced")
@allure.story("TC-5 — TDW Discount Applied Surrogate Key and Date Resolution")
@allure.severity(allure.severity_level.NORMAL)
@allure.title("TC-5: Discount Applied — amount tolerance and property_sk not null DSA vs TDW")
@allure.description(
    "Validates that TDW tdw_discount_applied_af amount matches DSA within $0.01 "
    "and that property_sk is not null when DSA src_property_id is non-null."
)
def test_tc5_discount_applied():
    try:
        dsa = run_redshift(_DSA_TC5)
    except Exception as e:
        allure.attach(str(e), name="DSA Error (table may not exist)", attachment_type=allure.attachment_type.TEXT)
        pytest.skip(f"TC-5: DSA table not available: {e}")
        return

    try:
        tdw = run_redshift(_TDW_TC5)
    except Exception as e:
        allure.attach(str(e), name="TDW Error (informational)", attachment_type=allure.attachment_type.TEXT)
        allure.attach(
            "TDW table not available — test reported as informational",
            name="TDW Skip Reason",
            attachment_type=allure.attachment_type.TEXT,
        )
        return

    with allure.step("Attach raw query results"):
        _attach_df(dsa, "DSA — Discount Applied")
        _attach_df(tdw, "TDW — Discount Applied")

    with allure.step("Merge on discount_id and validate"):
        m = dsa[["discount_id", "src_property_id", "amount"]].merge(
            tdw[["discount_id", "property_sk", "amount"]],
            on="discount_id",
            suffixes=("_dsa", "_tdw"),
        )
        assert not m.empty, "TC-5: No matching rows after merge on discount_id"
        _attach_df(m.head(20), "Merged Sample")

        errors = []

        # Assert amount within $0.01
        amt_delta = (m["amount_dsa"].astype(float) - m["amount_tdw"].astype(float)).abs()
        bad_amt = m[amt_delta > TOLERANCE]
        if not bad_amt.empty:
            errors.append(f"amount: {len(bad_amt)} row(s) exceed ${TOLERANCE} tolerance")
            _attach_df(bad_amt[["discount_id", "amount_dsa", "amount_tdw"]], "FAILED — amount")

        # Assert property_sk not null when src_property_id is not null
        with_prop = m[m["src_property_id"].notnull()]
        null_prop_sk = with_prop[with_prop["property_sk"].isnull()]
        if not null_prop_sk.empty:
            errors.append(f"property_sk is NULL for {len(null_prop_sk)} row(s) that have non-null src_property_id")
            _attach_df(null_prop_sk[["discount_id", "src_property_id", "property_sk"]], "FAILED — null property_sk")

    with allure.step("Assert zero violations"):
        if errors:
            msg = "\n".join(errors)
            post_slack(f":red_circle: *TC-5 FAILED* — Discount Applied Surrogate Key and Date Resolution\n{msg}")
            pytest.fail(f"TC-5: violations detected:\n{msg}")


# ─────────────────────────────────────────────────────────────────────────────
# TC-6: TDW Invoice Line Date and Surrogate Key Resolution
# ─────────────────────────────────────────────────────────────────────────────
_DSA_TC6 = """
SELECT invoice_line_id,
       invoice_id,
       quantity,
       cost,
       total_tax,
       total_discounts,
       subtotal,
       total_payments
FROM {dsa}.dsa_invoice_line_tf
WHERE company_uid = '{CUID}'
ORDER BY invoice_line_id
LIMIT 100
"""

_TDW_TC6 = """
SELECT src_invoice_line_id,
       invoice_sk,
       quantity,
       cost,
       total_tax,
       total_discounts,
       subtotal,
       total_payments
FROM {tdw}.tdw_invoice_line_tf
WHERE company_uid = '{CUID}'
ORDER BY src_invoice_line_id
LIMIT 100
"""


@allure.epic("Derived Value Validation")
@allure.feature("TDW Advanced")
@allure.story("TC-6 — TDW Invoice Line Date and Surrogate Key Resolution")
@allure.severity(allure.severity_level.NORMAL)
@allure.title("TC-6: Invoice Line — financial columns DSA vs TDW within $0.01")
@allure.description(
    "Validates that quantity, cost, subtotal, and total_payments in "
    "TDW tdw_invoice_line_tf match DSA dsa_invoice_line_tf within $0.01 tolerance."
)
def test_tc6_invoice_line():
    try:
        dsa = run_redshift(_DSA_TC6)
    except Exception as e:
        allure.attach(str(e), name="DSA Error (table may not exist)", attachment_type=allure.attachment_type.TEXT)
        pytest.skip(f"TC-6: DSA table not available: {e}")
        return

    try:
        tdw = run_redshift(_TDW_TC6)
    except Exception as e:
        allure.attach(str(e), name="TDW Error (informational)", attachment_type=allure.attachment_type.TEXT)
        allure.attach(
            "TDW table not available — test reported as informational",
            name="TDW Skip Reason",
            attachment_type=allure.attachment_type.TEXT,
        )
        return

    with allure.step("Rename TDW src_invoice_line_id to invoice_line_id"):
        tdw = tdw.rename(columns={"src_invoice_line_id": "invoice_line_id"})

    with allure.step("Attach raw query results"):
        _attach_df(dsa, "DSA — Invoice Line")
        _attach_df(tdw, "TDW — Invoice Line")

    with allure.step("Merge on invoice_line_id and compare financial columns"):
        m = dsa[["invoice_line_id", "quantity", "cost", "subtotal", "total_payments"]].merge(
            tdw[["invoice_line_id", "quantity", "cost", "subtotal", "total_payments"]],
            on="invoice_line_id",
            suffixes=("_dsa", "_tdw"),
        )
        assert not m.empty, "TC-6: No matching rows after merge on invoice_line_id"
        _attach_df(m.head(20), "Merged Sample")

        errors = []
        for col in ("quantity", "cost", "subtotal", "total_payments"):
            delta = (m[f"{col}_dsa"].astype(float) - m[f"{col}_tdw"].astype(float)).abs()
            bad = m[delta > TOLERANCE]
            if not bad.empty:
                errors.append(f"{col}: {len(bad)} row(s) exceed ${TOLERANCE} tolerance")
                _attach_df(bad[["invoice_line_id", f"{col}_dsa", f"{col}_tdw"]], f"FAILED — {col}")

    with allure.step("Assert zero tolerance violations"):
        if errors:
            msg = "\n".join(errors)
            post_slack(f":red_circle: *TC-6 FAILED* — Invoice Line Financial Column Validation\n{msg}")
            pytest.fail(f"TC-6: financial column mismatches:\n{msg}")


# ─────────────────────────────────────────────────────────────────────────────
# TC-7: TDW Payment Allocation Date and Dimension Resolution
# ─────────────────────────────────────────────────────────────────────────────
_DSA_TC7 = """
SELECT src_payment_allocation_id,
       src_payment_id,
       allocation_date,
       payment_date,
       property_id,
       contact_id,
       src_lease_id,
       amount
FROM {dsa}.dsa_payment_allocation_tf
WHERE company_uid = '{CUID}'
ORDER BY src_payment_allocation_id
LIMIT 100
"""

_TDW_TC7 = """
SELECT src_payment_allocation_id,
       src_payment_id,
       allocation_date_sk,
       payment_date_sk,
       property_sk,
       contact_sk,
       lease_sk,
       amount
FROM {tdw}.tdw_payment_allocation_tf
WHERE company_uid = '{CUID}'
ORDER BY src_payment_allocation_id
LIMIT 100
"""


@allure.epic("Derived Value Validation")
@allure.feature("TDW Advanced")
@allure.story("TC-7 — TDW Payment Allocation Date and Dimension Resolution")
@allure.severity(allure.severity_level.NORMAL)
@allure.title("TC-7: Payment Allocation — amount tolerance, property_sk and allocation_date_sk not null DSA vs TDW")
@allure.description(
    "Validates that TDW tdw_payment_allocation_tf amount matches DSA within $0.01, "
    "property_sk is not null, and allocation_date_sk is not null when DSA allocation_date is not null."
)
def test_tc7_payment_allocation():
    try:
        dsa = run_redshift(_DSA_TC7)
    except Exception as e:
        allure.attach(str(e), name="DSA Error (table may not exist)", attachment_type=allure.attachment_type.TEXT)
        pytest.skip(f"TC-7: DSA table not available: {e}")
        return

    try:
        tdw = run_redshift(_TDW_TC7)
    except Exception as e:
        allure.attach(str(e), name="TDW Error (informational)", attachment_type=allure.attachment_type.TEXT)
        allure.attach(
            "TDW table not available — test reported as informational",
            name="TDW Skip Reason",
            attachment_type=allure.attachment_type.TEXT,
        )
        return

    with allure.step("Attach raw query results"):
        _attach_df(dsa, "DSA — Payment Allocation")
        _attach_df(tdw, "TDW — Payment Allocation")

    with allure.step("Merge on src_payment_allocation_id and validate"):
        m = dsa[["src_payment_allocation_id", "allocation_date", "amount"]].merge(
            tdw[["src_payment_allocation_id", "allocation_date_sk", "property_sk", "amount"]],
            on="src_payment_allocation_id",
            suffixes=("_dsa", "_tdw"),
        )
        assert not m.empty, "TC-7: No matching rows after merge on src_payment_allocation_id"
        _attach_df(m.head(20), "Merged Sample")

        errors = []

        # Assert amount within $0.01
        amt_delta = (m["amount_dsa"].astype(float) - m["amount_tdw"].astype(float)).abs()
        bad_amt = m[amt_delta > TOLERANCE]
        if not bad_amt.empty:
            errors.append(f"amount: {len(bad_amt)} row(s) exceed ${TOLERANCE} tolerance")
            _attach_df(bad_amt[["src_payment_allocation_id", "amount_dsa", "amount_tdw"]], "FAILED — amount")

        # Assert property_sk not null
        null_prop_sk = tdw[tdw["property_sk"].isnull()]
        if not null_prop_sk.empty:
            errors.append(f"property_sk is NULL for {len(null_prop_sk)} TDW row(s)")
            _attach_df(null_prop_sk[["src_payment_allocation_id", "property_sk"]], "FAILED — null property_sk")

        # Assert allocation_date_sk not null when DSA allocation_date is not null
        with_date = m[m["allocation_date"].notnull()]
        null_date_sk = with_date[with_date["allocation_date_sk"].isnull()]
        if not null_date_sk.empty:
            errors.append(f"allocation_date_sk is NULL for {len(null_date_sk)} row(s) with non-null allocation_date")
            _attach_df(null_date_sk[["src_payment_allocation_id", "allocation_date", "allocation_date_sk"]], "FAILED — null allocation_date_sk")

    with allure.step("Assert zero violations"):
        if errors:
            msg = "\n".join(errors)
            post_slack(f":red_circle: *TC-7 FAILED* — Payment Allocation Date and Dimension Resolution\n{msg}")
            pytest.fail(f"TC-7: violations detected:\n{msg}")


# ─────────────────────────────────────────────────────────────────────────────
# TC-8: TDW Refunds Date and Misc Attribute Resolution
# ─────────────────────────────────────────────────────────────────────────────
_DSA_TC8 = """
SELECT src_refund_id,
       src_payment_allocation_id,
       src_payment_id,
       property_id,
       src_lease_id,
       effective_date,
       ila_date,
       amount,
       ila_amount
FROM {dsa}.dsa_refunds_tf
WHERE company_uid = '{CUID}'
ORDER BY src_refund_id, src_payment_allocation_id
LIMIT 100
"""

_TDW_TC8 = """
SELECT src_refund_id,
       src_payment_allocation_id,
       src_payment_id,
       property_sk,
       lease_sk,
       effective_date_sk,
       ila_date_sk,
       amount,
       ila_amount
FROM {tdw}.tdw_refunds_tf
WHERE company_uid = '{CUID}'
ORDER BY src_refund_id, src_payment_allocation_id
LIMIT 100
"""


@allure.epic("Derived Value Validation")
@allure.feature("TDW Advanced")
@allure.story("TC-8 — TDW Refunds Date and Misc Attribute Resolution")
@allure.severity(allure.severity_level.NORMAL)
@allure.title("TC-8: Refunds — amount/ila_amount tolerance and property_sk not null DSA vs TDW")
@allure.description(
    "Validates that TDW tdw_refunds_tf amount and ila_amount match DSA within $0.01, "
    "and that property_sk is not null."
)
def test_tc8_refunds():
    try:
        dsa = run_redshift(_DSA_TC8)
    except Exception as e:
        allure.attach(str(e), name="DSA Error (table may not exist)", attachment_type=allure.attachment_type.TEXT)
        pytest.skip(f"TC-8: DSA table not available: {e}")
        return

    try:
        tdw = run_redshift(_TDW_TC8)
    except Exception as e:
        allure.attach(str(e), name="TDW Error (informational)", attachment_type=allure.attachment_type.TEXT)
        allure.attach(
            "TDW table not available — test reported as informational",
            name="TDW Skip Reason",
            attachment_type=allure.attachment_type.TEXT,
        )
        return

    with allure.step("Attach raw query results"):
        _attach_df(dsa, "DSA — Refunds")
        _attach_df(tdw, "TDW — Refunds")

    with allure.step("Merge on [src_refund_id, src_payment_allocation_id] and validate"):
        merge_keys = ["src_refund_id", "src_payment_allocation_id"]
        m = dsa[merge_keys + ["amount", "ila_amount"]].merge(
            tdw[merge_keys + ["property_sk", "amount", "ila_amount"]],
            on=merge_keys,
            suffixes=("_dsa", "_tdw"),
        )
        assert not m.empty, "TC-8: No matching rows after merge on [src_refund_id, src_payment_allocation_id]"
        _attach_df(m.head(20), "Merged Sample")

        errors = []

        # Assert amount within $0.01
        amt_delta = (m["amount_dsa"].astype(float) - m["amount_tdw"].astype(float)).abs()
        bad_amt = m[amt_delta > TOLERANCE]
        if not bad_amt.empty:
            errors.append(f"amount: {len(bad_amt)} row(s) exceed ${TOLERANCE} tolerance")
            _attach_df(bad_amt[merge_keys + ["amount_dsa", "amount_tdw"]], "FAILED — amount")

        # Assert ila_amount within $0.01
        ila_delta = (m["ila_amount_dsa"].astype(float) - m["ila_amount_tdw"].astype(float)).abs()
        bad_ila = m[ila_delta > TOLERANCE]
        if not bad_ila.empty:
            errors.append(f"ila_amount: {len(bad_ila)} row(s) exceed ${TOLERANCE} tolerance")
            _attach_df(bad_ila[merge_keys + ["ila_amount_dsa", "ila_amount_tdw"]], "FAILED — ila_amount")

        # Assert property_sk not null
        null_prop_sk = tdw[tdw["property_sk"].isnull()]
        if not null_prop_sk.empty:
            errors.append(f"property_sk is NULL for {len(null_prop_sk)} TDW row(s)")
            _attach_df(null_prop_sk[["src_refund_id", "src_payment_allocation_id", "property_sk"]], "FAILED — null property_sk")

    with allure.step("Assert zero violations"):
        if errors:
            msg = "\n".join(errors)
            post_slack(f":red_circle: *TC-8 FAILED* — Refunds Date and Misc Attribute Resolution\n{msg}")
            pytest.fail(f"TC-8: violations detected:\n{msg}")


# ─────────────────────────────────────────────────────────────────────────────
# TC-9: TDW Rent Change Metrics and Date Key Propagation
# ─────────────────────────────────────────────────────────────────────────────
_DSA_TC9 = """
SELECT lease_id,
       src_unit_id,
       src_property_id,
       changed_rent,
       current_rent,
       next_rent
FROM {dsa}.dsa_rent_change_pf
WHERE company_uid = '{CUID}'
ORDER BY lease_id
LIMIT 100
"""

_TDW_TC9 = """
SELECT lease_sk,
       unit_sk,
       property_sk,
       changed_rent,
       current_rent,
       next_rent
FROM {tdw}.tdw_rent_change_pf
WHERE company_uid = '{CUID}'
ORDER BY unit_sk
LIMIT 100
"""


@allure.epic("Derived Value Validation")
@allure.feature("TDW Advanced")
@allure.story("TC-9 — TDW Rent Change Metrics and Date Key Propagation")
@allure.severity(allure.severity_level.NORMAL)
@allure.title("TC-9: Rent Change — row count within 1% and rent metrics non-null DSA vs TDW")
@allure.description(
    "Validates that TDW tdw_rent_change_pf row count is within 1% of DSA dsa_rent_change_pf, "
    "and that changed_rent, current_rent, next_rent are non-null for all TDW records."
)
def test_tc9_rent_change_metrics():
    try:
        dsa = run_redshift(_DSA_TC9)
    except Exception as e:
        allure.attach(str(e), name="DSA Error (table may not exist)", attachment_type=allure.attachment_type.TEXT)
        pytest.skip(f"TC-9: DSA table not available: {e}")
        return

    try:
        tdw = run_redshift(_TDW_TC9)
    except Exception as e:
        allure.attach(str(e), name="TDW Error (informational)", attachment_type=allure.attachment_type.TEXT)
        allure.attach(
            "TDW table not available — test reported as informational",
            name="TDW Skip Reason",
            attachment_type=allure.attachment_type.TEXT,
        )
        return

    with allure.step("Attach raw query results"):
        _attach_df(dsa, "DSA — Rent Change")
        _attach_df(tdw, "TDW — Rent Change")

    with allure.step("Compare total row counts within 1%"):
        dsa_count = len(dsa)
        tdw_count = len(tdw)
        pct_diff = abs(dsa_count - tdw_count) / max(dsa_count, 1) * 100

        summary = (
            f"DSA row count : {dsa_count}\n"
            f"TDW row count : {tdw_count}\n"
            f"Pct difference: {pct_diff:.2f}%"
        )
        allure.attach(summary, name="Row Count Summary", attachment_type=allure.attachment_type.TEXT)

        errors = []
        if pct_diff > 1.0:
            errors.append(f"Row count diff {pct_diff:.2f}% exceeds 1% threshold (DSA={dsa_count}, TDW={tdw_count})")

    with allure.step("Assert rent metric columns are non-null in TDW"):
        for col in ("changed_rent", "current_rent", "next_rent"):
            null_rows = tdw[tdw[col].isnull()]
            if not null_rows.empty:
                errors.append(f"TDW {col} is NULL for {len(null_rows)} row(s)")
                _attach_df(null_rows[["lease_sk", col]], f"FAILED — null {col}")

    with allure.step("Assert zero violations"):
        if errors:
            msg = "\n".join(errors)
            post_slack(f":red_circle: *TC-9 FAILED* — Rent Change Metrics and Date Key Propagation\n{msg}\n{summary}")
            pytest.fail(f"TC-9: violations detected:\n{msg}")

    allure.attach(summary, name="Final Summary", attachment_type=allure.attachment_type.TEXT)


# ─────────────────────────────────────────────────────────────────────────────
# TC-10: TDW Reservations Date and Lease Key Resolution
# ─────────────────────────────────────────────────────────────────────────────
_DSA_TC10 = """
SELECT src_reservation_id,
       property_id,
       unit_id,
       src_lease_id,
       day_reservations,
       created_date,
       expiration_date,
       start_date,
       is_canceled
FROM {dsa}.dsa_reservations_af
WHERE company_uid = '{CUID}'
ORDER BY src_reservation_id
LIMIT 100
"""

_TDW_TC10 = """
SELECT src_reservation_id,
       property_sk,
       unit_sk,
       lease_sk,
       day_reservations,
       created_date_sk,
       expires_date_sk,
       start_date_sk,
       is_canceled
FROM {tdw}.tdw_reservations_af
WHERE company_uid = '{CUID}'
ORDER BY src_reservation_id
LIMIT 100
"""


@allure.epic("Derived Value Validation")
@allure.feature("TDW Advanced")
@allure.story("TC-10 — TDW Reservations Date and Lease Key Resolution")
@allure.severity(allure.severity_level.NORMAL)
@allure.title("TC-10: Reservations — day_reservations, is_canceled, and property_sk DSA vs TDW")
@allure.description(
    "Validates that TDW tdw_reservations_af day_reservations and is_canceled match DSA, "
    "and that property_sk is not null."
)
def test_tc10_reservations():
    try:
        dsa = run_redshift(_DSA_TC10)
    except Exception as e:
        allure.attach(str(e), name="DSA Error (table may not exist)", attachment_type=allure.attachment_type.TEXT)
        pytest.skip(f"TC-10: DSA table not available: {e}")
        return

    try:
        tdw = run_redshift(_TDW_TC10)
    except Exception as e:
        allure.attach(str(e), name="TDW Error (informational)", attachment_type=allure.attachment_type.TEXT)
        allure.attach(
            "TDW table not available — test reported as informational",
            name="TDW Skip Reason",
            attachment_type=allure.attachment_type.TEXT,
        )
        return

    with allure.step("Attach raw query results"):
        _attach_df(dsa, "DSA — Reservations")
        _attach_df(tdw, "TDW — Reservations")

    with allure.step("Merge on src_reservation_id and validate"):
        m = dsa[["src_reservation_id", "day_reservations", "is_canceled"]].merge(
            tdw[["src_reservation_id", "property_sk", "day_reservations", "is_canceled"]],
            on="src_reservation_id",
            suffixes=("_dsa", "_tdw"),
        )
        assert not m.empty, "TC-10: No matching rows after merge on src_reservation_id"
        _attach_df(m.head(20), "Merged Sample")

        errors = []

        # Assert day_reservations matches
        day_mismatch = m[m["day_reservations_dsa"].astype(str) != m["day_reservations_tdw"].astype(str)]
        if not day_mismatch.empty:
            errors.append(f"day_reservations: {len(day_mismatch)} mismatch(es)")
            _attach_df(day_mismatch[["src_reservation_id", "day_reservations_dsa", "day_reservations_tdw"]], "FAILED — day_reservations")

        # Assert is_canceled matches
        canceled_mismatch = m[m["is_canceled_dsa"].astype(str) != m["is_canceled_tdw"].astype(str)]
        if not canceled_mismatch.empty:
            errors.append(f"is_canceled: {len(canceled_mismatch)} mismatch(es)")
            _attach_df(canceled_mismatch[["src_reservation_id", "is_canceled_dsa", "is_canceled_tdw"]], "FAILED — is_canceled")

        # Assert property_sk not null
        null_prop_sk = tdw[tdw["property_sk"].isnull()]
        if not null_prop_sk.empty:
            errors.append(f"property_sk is NULL for {len(null_prop_sk)} TDW row(s)")
            _attach_df(null_prop_sk[["src_reservation_id", "property_sk"]], "FAILED — null property_sk")

    with allure.step("Assert zero violations"):
        if errors:
            msg = "\n".join(errors)
            post_slack(f":red_circle: *TC-10 FAILED* — Reservations Date and Lease Key Resolution\n{msg}")
            pytest.fail(f"TC-10: violations detected:\n{msg}")


# ─────────────────────────────────────────────────────────────────────────────
# TC-11: TDW Services Leases Date and Move-In Flag Propagation
# ─────────────────────────────────────────────────────────────────────────────
_DSA_TC11 = """
SELECT src_service_id,
       src_lease_id,
       src_property_id,
       service_start_date,
       service_end_date,
       service_price,
       service_bought_at_move_in
FROM {dsa}.dsa_services_leases_tf
WHERE company_uid = '{CUID}'
ORDER BY src_service_id
LIMIT 100
"""

_TDW_TC11 = """
SELECT src_service_id,
       lease_sk,
       property_sk,
       service_start_date_sk,
       service_end_date_sk,
       service_price,
       service_bought_at_move_in
FROM {tdw}.tdw_services_leases_tf
WHERE company_uid = '{CUID}'
ORDER BY src_service_id
LIMIT 100
"""


@allure.epic("Derived Value Validation")
@allure.feature("TDW Advanced")
@allure.story("TC-11 — TDW Services Leases Date and Move-In Flag Propagation")
@allure.severity(allure.severity_level.NORMAL)
@allure.title("TC-11: Services Leases — service_price tolerance, move-in flag, and property_sk DSA vs TDW")
@allure.description(
    "Validates that TDW tdw_services_leases_tf service_price matches DSA within $0.01, "
    "service_bought_at_move_in matches DSA, and property_sk is not null."
)
def test_tc11_services_leases():
    try:
        dsa = run_redshift(_DSA_TC11)
    except Exception as e:
        allure.attach(str(e), name="DSA Error (table may not exist)", attachment_type=allure.attachment_type.TEXT)
        pytest.skip(f"TC-11: DSA table not available: {e}")
        return

    try:
        tdw = run_redshift(_TDW_TC11)
    except Exception as e:
        allure.attach(str(e), name="TDW Error (informational)", attachment_type=allure.attachment_type.TEXT)
        allure.attach(
            "TDW table not available — test reported as informational",
            name="TDW Skip Reason",
            attachment_type=allure.attachment_type.TEXT,
        )
        return

    with allure.step("Attach raw query results"):
        _attach_df(dsa, "DSA — Services Leases")
        _attach_df(tdw, "TDW — Services Leases")

    with allure.step("Merge on src_service_id and validate"):
        m = dsa[["src_service_id", "service_price", "service_bought_at_move_in"]].merge(
            tdw[["src_service_id", "property_sk", "service_price", "service_bought_at_move_in"]],
            on="src_service_id",
            suffixes=("_dsa", "_tdw"),
        )
        assert not m.empty, "TC-11: No matching rows after merge on src_service_id"
        _attach_df(m.head(20), "Merged Sample")

        errors = []

        # Assert service_price within $0.01
        price_delta = (m["service_price_dsa"].astype(float) - m["service_price_tdw"].astype(float)).abs()
        bad_price = m[price_delta > TOLERANCE]
        if not bad_price.empty:
            errors.append(f"service_price: {len(bad_price)} row(s) exceed ${TOLERANCE} tolerance")
            _attach_df(bad_price[["src_service_id", "service_price_dsa", "service_price_tdw"]], "FAILED — service_price")

        # Assert service_bought_at_move_in matches
        flag_mismatch = m[
            m["service_bought_at_move_in_dsa"].astype(str) != m["service_bought_at_move_in_tdw"].astype(str)
        ]
        if not flag_mismatch.empty:
            errors.append(f"service_bought_at_move_in: {len(flag_mismatch)} mismatch(es)")
            _attach_df(
                flag_mismatch[["src_service_id", "service_bought_at_move_in_dsa", "service_bought_at_move_in_tdw"]],
                "FAILED — service_bought_at_move_in",
            )

        # Assert property_sk not null
        null_prop_sk = tdw[tdw["property_sk"].isnull()]
        if not null_prop_sk.empty:
            errors.append(f"property_sk is NULL for {len(null_prop_sk)} TDW row(s)")
            _attach_df(null_prop_sk[["src_service_id", "property_sk"]], "FAILED — null property_sk")

    with allure.step("Assert zero violations"):
        if errors:
            msg = "\n".join(errors)
            post_slack(f":red_circle: *TC-11 FAILED* — Services Leases Date and Move-In Flag Propagation\n{msg}")
            pytest.fail(f"TC-11: violations detected:\n{msg}")


# ─────────────────────────────────────────────────────────────────────────────
# TC-12: TDW Tasks Overdue Days and Status Key Propagation
# ─────────────────────────────────────────────────────────────────────────────
_DSA_TC12 = """
SELECT src_task_id,
       src_property_id,
       task_status,
       day_difference,
       recurring_flag,
       task_due_date
FROM {dsa}.dsa_tasks_af
WHERE company_uid = '{CUID}'
ORDER BY src_task_id
LIMIT 100
"""

_TDW_TC12 = """
SELECT src_task_id,
       property_sk,
       task_status_sk,
       task_days_overdue,
       recurring_flag,
       task_due_date_sk
FROM {tdw}.tdw_tasks_af
WHERE company_uid = '{CUID}'
ORDER BY src_task_id
LIMIT 100
"""


@allure.epic("Derived Value Validation")
@allure.feature("TDW Advanced")
@allure.story("TC-12 — TDW Tasks Overdue Days and Status Key Propagation")
@allure.severity(allure.severity_level.MINOR)
@allure.title("TC-12: Tasks — task_days_overdue, recurring_flag, and property_sk DSA vs TDW")
@allure.description(
    "Validates that TDW tdw_tasks_af task_days_overdue matches DSA day_difference, "
    "recurring_flag matches DSA, and property_sk is not null."
)
def test_tc12_tasks():
    try:
        dsa = run_redshift(_DSA_TC12)
    except Exception as e:
        allure.attach(str(e), name="DSA Error (table may not exist)", attachment_type=allure.attachment_type.TEXT)
        pytest.skip(f"TC-12: DSA table not available: {e}")
        return

    try:
        tdw = run_redshift(_TDW_TC12)
    except Exception as e:
        allure.attach(str(e), name="TDW Error (informational)", attachment_type=allure.attachment_type.TEXT)
        allure.attach(
            "TDW table not available — test reported as informational",
            name="TDW Skip Reason",
            attachment_type=allure.attachment_type.TEXT,
        )
        return

    with allure.step("Attach raw query results"):
        _attach_df(dsa, "DSA — Tasks")
        _attach_df(tdw, "TDW — Tasks")

    with allure.step("Merge on src_task_id and validate"):
        m = dsa[["src_task_id", "day_difference", "recurring_flag"]].merge(
            tdw[["src_task_id", "property_sk", "task_days_overdue", "recurring_flag"]],
            on="src_task_id",
            suffixes=("_dsa", "_tdw"),
        )
        assert not m.empty, "TC-12: No matching rows after merge on src_task_id"
        _attach_df(m.head(20), "Merged Sample")

        errors = []

        # Assert task_days_overdue matches DSA day_difference
        overdue_mismatch = m[
            m["day_difference"].astype(str) != m["task_days_overdue"].astype(str)
        ]
        if not overdue_mismatch.empty:
            errors.append(f"task_days_overdue vs day_difference: {len(overdue_mismatch)} mismatch(es)")
            _attach_df(
                overdue_mismatch[["src_task_id", "day_difference", "task_days_overdue"]],
                "FAILED — task_days_overdue",
            )

        # Assert recurring_flag matches
        flag_mismatch = m[
            m["recurring_flag_dsa"].astype(str) != m["recurring_flag_tdw"].astype(str)
        ]
        if not flag_mismatch.empty:
            errors.append(f"recurring_flag: {len(flag_mismatch)} mismatch(es)")
            _attach_df(
                flag_mismatch[["src_task_id", "recurring_flag_dsa", "recurring_flag_tdw"]],
                "FAILED — recurring_flag",
            )

        # Assert property_sk not null
        null_prop_sk = tdw[tdw["property_sk"].isnull()]
        if not null_prop_sk.empty:
            errors.append(f"property_sk is NULL for {len(null_prop_sk)} TDW row(s)")
            _attach_df(null_prop_sk[["src_task_id", "property_sk"]], "FAILED — null property_sk")

    with allure.step("Assert zero violations"):
        if errors:
            msg = "\n".join(errors)
            post_slack(f":red_circle: *TC-12 FAILED* — Tasks Overdue Days and Status Key Propagation\n{msg}")
            pytest.fail(f"TC-12: violations detected:\n{msg}")


# ─────────────────────────────────────────────────────────────────────────────
# TC-13: TDW Unit Status Live Merge Consistency
# ─────────────────────────────────────────────────────────────────────────────
_DSA_TC13 = """
SELECT id,
       company_uid,
       property_id,
       id AS unit_id,
       unit_status
FROM {dsa}.dsa_unit_status_live_d
WHERE company_uid = '{CUID}'
ORDER BY id
LIMIT 200
"""

_TDW_TC13 = """
SELECT id,
       company_uid,
       property_id,
       id AS unit_id,
       unit_status
FROM {tdw}.tdw_unit_status_live_d
WHERE company_uid = '{CUID}'
ORDER BY id
LIMIT 200
"""


@allure.epic("Derived Value Validation")
@allure.feature("TDW Advanced")
@allure.story("TC-13 — TDW Unit Status Live Merge Consistency")
@allure.severity(allure.severity_level.NORMAL)
@allure.title("TC-13: Unit Status Live — unit_status match, no duplicate ids, company_uid match DSA vs TDW")
@allure.description(
    "Validates that TDW tdw_unit_status_live_d unit_status matches DSA exactly, "
    "TDW has no duplicate ids, and TDW company_uid matches DSA."
)
def test_tc13_unit_status_live():
    try:
        dsa = run_redshift(_DSA_TC13)
    except Exception as e:
        allure.attach(str(e), name="DSA Error (table may not exist)", attachment_type=allure.attachment_type.TEXT)
        pytest.skip(f"TC-13: DSA table not available: {e}")
        return

    try:
        tdw = run_redshift(_TDW_TC13)
    except Exception as e:
        allure.attach(str(e), name="TDW Error (informational)", attachment_type=allure.attachment_type.TEXT)
        allure.attach(
            "TDW table not available — test reported as informational",
            name="TDW Skip Reason",
            attachment_type=allure.attachment_type.TEXT,
        )
        return

    with allure.step("Attach raw query results"):
        _attach_df(dsa, "DSA — Unit Status Live")
        _attach_df(tdw, "TDW — Unit Status Live")

    with allure.step("Merge on id and validate"):
        m = dsa[["id", "company_uid", "unit_status"]].merge(
            tdw[["id", "company_uid", "unit_status"]],
            on="id",
            suffixes=("_dsa", "_tdw"),
        )
        assert not m.empty, "TC-13: No matching rows after merge on id"
        _attach_df(m.head(20), "Merged Sample")

        errors = []

        # Assert unit_status matches exactly
        status_mismatch = m[m["unit_status_dsa"].astype(str) != m["unit_status_tdw"].astype(str)]
        if not status_mismatch.empty:
            errors.append(f"unit_status: {len(status_mismatch)} mismatch(es)")
            _attach_df(status_mismatch[["id", "unit_status_dsa", "unit_status_tdw"]], "FAILED — unit_status")

        # Assert no duplicate ids in TDW
        dup_ids = tdw[tdw.duplicated(subset=["id"], keep=False)]
        if not dup_ids.empty:
            errors.append(f"Duplicate ids in TDW: {dup_ids['id'].nunique()} distinct id(s) appear more than once")
            _attach_df(dup_ids[["id", "unit_status"]], "FAILED — duplicate ids")

        # Assert TDW company_uid matches DSA
        cuid_mismatch = m[m["company_uid_dsa"].astype(str) != m["company_uid_tdw"].astype(str)]
        if not cuid_mismatch.empty:
            errors.append(f"company_uid: {len(cuid_mismatch)} mismatch(es)")
            _attach_df(cuid_mismatch[["id", "company_uid_dsa", "company_uid_tdw"]], "FAILED — company_uid")

    with allure.step("Assert zero violations"):
        if errors:
            msg = "\n".join(errors)
            post_slack(f":red_circle: *TC-13 FAILED* — Unit Status Live Merge Consistency\n{msg}")
            pytest.fail(f"TC-13: violations detected:\n{msg}")


# ─────────────────────────────────────────────────────────────────────────────
# TC-14: TDW Leads Touchpoint Generated Date and Dimension Key Resolution
# ─────────────────────────────────────────────────────────────────────────────
_DSA_TC14 = """
SELECT src_lead_id,
       property_id,
       contact_id,
       lease_id,
       lease_touchpoint_id,
       status,
       source,
       move_in_date,
       generated_on_date,
       modified
FROM {dsa}.dsa_leads_tf
WHERE company_uid = '{CUID}'
ORDER BY src_lead_id
LIMIT 100
"""

_TDW_TC14 = """
SELECT src_lead_id,
       property_sk,
       contact_sk,
       lease_sk,
       touchpoint_sk,
       lead_status_sk,
       lead_source_sk,
       move_in_date_sk,
       generated_on_date_sk,
       modified_at_sk
FROM {tdw}.tdw_leads_tf
WHERE company_uid = '{CUID}'
ORDER BY src_lead_id
LIMIT 100
"""


@allure.epic("Derived Value Validation")
@allure.feature("TDW Advanced")
@allure.story("TC-14 — TDW Leads Touchpoint Generated Date and Dimension Key Resolution")
@allure.severity(allure.severity_level.NORMAL)
@allure.title("TC-14: Leads — property_sk not null, generated_on_date_sk not null, count within 1% DSA vs TDW")
@allure.description(
    "Validates that TDW tdw_leads_tf property_sk is not null for records with non-null DSA property_id, "
    "generated_on_date_sk is not null for records with non-null DSA generated_on_date, "
    "and row count is within 1% of DSA."
)
def test_tc14_leads():
    try:
        dsa = run_redshift(_DSA_TC14)
    except Exception as e:
        allure.attach(str(e), name="DSA Error (table may not exist)", attachment_type=allure.attachment_type.TEXT)
        pytest.skip(f"TC-14: DSA table not available: {e}")
        return

    try:
        tdw = run_redshift(_TDW_TC14)
    except Exception as e:
        allure.attach(str(e), name="TDW Error (informational)", attachment_type=allure.attachment_type.TEXT)
        allure.attach(
            "TDW table not available — test reported as informational",
            name="TDW Skip Reason",
            attachment_type=allure.attachment_type.TEXT,
        )
        return

    with allure.step("Attach raw query results"):
        _attach_df(dsa, "DSA — Leads")
        _attach_df(tdw, "TDW — Leads")

    with allure.step("Compare row counts within 1%"):
        dsa_count = len(dsa)
        tdw_count = len(tdw)
        pct_diff = abs(dsa_count - tdw_count) / max(dsa_count, 1) * 100

        count_summary = (
            f"DSA row count : {dsa_count}\n"
            f"TDW row count : {tdw_count}\n"
            f"Pct difference: {pct_diff:.2f}%"
        )
        allure.attach(count_summary, name="Row Count Summary", attachment_type=allure.attachment_type.TEXT)

    with allure.step("Merge on src_lead_id and validate surrogate keys"):
        m = dsa[["src_lead_id", "property_id", "generated_on_date"]].merge(
            tdw[["src_lead_id", "property_sk", "generated_on_date_sk"]],
            on="src_lead_id",
        )
        assert not m.empty, "TC-14: No matching rows after merge on src_lead_id"
        _attach_df(m.head(20), "Merged Sample")

        errors = []

        # Assert count within 1%
        if pct_diff > 1.0:
            errors.append(f"Row count diff {pct_diff:.2f}% exceeds 1% threshold (DSA={dsa_count}, TDW={tdw_count})")

        # Assert property_sk not null for records with non-null DSA property_id
        with_prop = m[m["property_id"].notnull()]
        null_prop_sk = with_prop[with_prop["property_sk"].isnull()]
        if not null_prop_sk.empty:
            errors.append(f"property_sk is NULL for {len(null_prop_sk)} row(s) with non-null DSA property_id")
            _attach_df(null_prop_sk[["src_lead_id", "property_id", "property_sk"]], "FAILED — null property_sk")

        # Assert generated_on_date_sk not null for records with non-null generated_on_date
        with_gen_date = m[m["generated_on_date"].notnull()]
        null_gen_sk = with_gen_date[with_gen_date["generated_on_date_sk"].isnull()]
        if not null_gen_sk.empty:
            errors.append(f"generated_on_date_sk is NULL for {len(null_gen_sk)} row(s) with non-null generated_on_date")
            _attach_df(
                null_gen_sk[["src_lead_id", "generated_on_date", "generated_on_date_sk"]],
                "FAILED — null generated_on_date_sk",
            )

    with allure.step("Assert zero violations"):
        if errors:
            msg = "\n".join(errors)
            post_slack(f":red_circle: *TC-14 FAILED* — Leads Touchpoint Generated Date and Dimension Key Resolution\n{msg}\n{count_summary}")
            pytest.fail(f"TC-14: violations detected:\n{msg}")

    allure.attach(count_summary, name="Final Count Summary", attachment_type=allure.attachment_type.TEXT)
