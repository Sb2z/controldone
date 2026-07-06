"""Non-regression tests for extraction precision (v4.30).

Each test pins a real-world failure observed on past production batches.
They run on frozen OCR text excerpts so no PDF, Tesseract or network access is
required: `pytest` answers in seconds whether a code change reintroduced one
of the old bugs.

Client-specific values (VAT/SIREN, HS scope, name aliases) come from the
synthetic ``acme`` profile activated by ``conftest.py`` — never real data.
"""
from controldone.adapters.parse_invoice import _find_last_total, _to_float
from controldone.hs import is_in_scope, normalize_hs, normalize_hs_many
from controldone.parsing import (
    _siren_evidence,
    _extract_invoice_line_amount_total,
    _known_identity_vat,
)
from controldone.profile import current_profile
from controldone.validation import _hs_ocr_confusable


# ---------------------------------------------------------------------------
# HS normalisation & profile scope (v4.29 fixes, kept under regression)
# ---------------------------------------------------------------------------

def test_punctuated_hs_is_normalized():
    assert normalize_hs("4202.21.00.90", scope_only=True) == "4202210090"


def test_phone_and_vat_numbers_rejected_as_hs():
    for noise in ("FR12345678901", "7000611907", "9020346860", "7411719000"):
        assert normalize_hs(noise, scope_only=True) is None


def test_scope_hs6_list_accepts_known_codes():
    for code in ("420221", "640351", "640359", "711719", "961519"):
        assert is_in_scope(code), code


def test_out_of_scope_hs6_rejected():
    # 640350 is NOT in the scope list even though 640351/640359 are.
    assert not is_in_scope("640350")
    assert normalize_hs_many(["6403509900"], scope_only=True) == []


# ---------------------------------------------------------------------------
# Entity / VAT identity (v4.30: specific-alias priority, SIREN digit evidence)
# ---------------------------------------------------------------------------

def test_name_alias_maps_to_entity():
    aliases = dict(current_profile().name_aliases)
    assert aliases["CODE"] == "FR00000000002"
    assert aliases["CCODE"] == "FR00000000001"


def test_specific_alias_priority_over_substring():
    # "CCODE" contains "CODE"; the more specific mapping must win.
    assert _known_identity_vat("CCODE - ATELIER TRANSFERTS 1") == "FR00000000001"


def test_siren_digit_evidence_beats_name_guess():
    # Bill To says CODE and the page prints the SAS SIREN inside a noisy VAT
    # ("NETVA:FR00000000200002").  Expected entity: ACME SAS.
    text = "BILLTO CONTACT CODE BOUTIQUE NETVA:FR00000000200002"
    assert _known_identity_vat(text) == "FR00000000002"


def test_siren_evidence_ambiguous_returns_none():
    assert _siren_evidence("000000001 et 000000002") is None


def test_unrelated_vat_not_inferred_as_ours():
    assert _known_identity_vat("DHL AVIATION FRANCE SAS FR99999999999") != "FR00000000001"


# ---------------------------------------------------------------------------
# Amounts (v4.30: KRW totals, weights never read as totals)
# ---------------------------------------------------------------------------

def test_to_float_thousand_separators():
    assert _to_float("7,017,140") == 7017140.0
    assert _to_float("12,50") == 12.5
    assert _to_float("1.234,56") == 1234.56
    assert _to_float("1,234.56") == 1234.56


def test_krw_total_without_decimals():
    # Korea-style invoice: "Total Amount -------- KRW ! 7,017,140"
    text = "1 26AB00000C00000D0000 JACKET SAMPLE TWEED FRA 34 1 7,017,140 7,017,140\nTotal Amount -------- KRW ! 7,017,140"
    val, cur = _find_last_total(text)
    assert val == 7017140.0
    assert cur == "KRW"


def test_weight_line_not_taken_as_total():
    text = "Total Gross Weight 3.00 Kgs\nTOTAL AMOUNT: 801.74"
    val, _ = _find_last_total(text)
    assert val == 801.74


def test_invoice_total_on_next_line():
    # Bordered grid form: OCR puts the amount on the line below the label.
    text = "6. invoice, Total\n801.74,"
    val, _ = _find_last_total(text)
    assert val == 801.74


def test_line_amount_prefers_currency_tagged_value_over_weight():
    # Mixed block: weight 0.58 then value "28.55 CHF" in the same HS block.
    text = "CHF CHF\n6403999390\n0.58\n28.55 CHF\nTOTAL"
    result = _extract_invoice_line_amount_total(text)
    assert result == ("CHF", 28.55)


# ---------------------------------------------------------------------------
# HS OCR-confusion matching (v4.30: WARN instead of false KO)
# ---------------------------------------------------------------------------

def test_hs_confusable_pairs():
    assert _hs_ocr_confusable("640359", "640339")      # 5↔3 fax confusion
    assert _hs_ocr_confusable("840331", "640351")      # 8↔6 and 3↔5
    assert not _hs_ocr_confusable("620342", "610462")  # real mismatch
    assert not _hs_ocr_confusable("640351", "640351")  # identical: not a confusion


def test_hs_confusable_requires_same_length():
    assert not _hs_ocr_confusable("64035", "640351")


# ---------------------------------------------------------------------------
# FX conversion recognition (v4.30: EUR-converted declarations are not errors)
# ---------------------------------------------------------------------------

def test_eur_converted_declaration_is_ok():
    from controldone.models import Document
    from controldone.validation import _check_value_currency
    inv = Document(kind="invoice", currency="CHF", total_amount=950.0)
    decl = Document(kind="declaration", currency="EUR", total_amount=1000.0)
    checks = _check_value_currency(inv, decl)
    by_code = {c.code: c for c in checks}
    assert by_code["currency_match"].status == "OK"
    assert by_code["amount_match"].status == "OK"


def test_unconverted_currency_mismatch_stays_ko():
    from controldone.models import Document
    from controldone.validation import _check_value_currency
    inv = Document(kind="invoice", currency="AED", total_amount=7608.04)
    decl = Document(kind="declaration", currency="EUR", total_amount=5452.00)
    checks = _check_value_currency(inv, decl)
    by_code = {c.code: c for c in checks}
    assert by_code["currency_match"].status == "NOK"
