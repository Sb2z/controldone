"""Business rules for v4 customs control.

The goods invoice is the source of truth.  The declaration must repeat the same
entity, value/currency and HS families.  The prestation invoice, when present,
must match the duties and taxes of the declaration.
"""
from __future__ import annotations

import re
from typing import Iterable, List, Optional

from controldone.hs import normalize_hs
from controldone.profile import current_profile
from controldone.models import (
    BUNDLE_KO,
    BUNDLE_KO_BLOQUANT,
    BUNDLE_MANQUE_DOC,
    BUNDLE_OK,
    BUNDLE_VERIFY,
    Bundle,
    CheckResult,
    Document,
    SEVERITY_CRITICAL,
    SEVERITY_ERROR,
    SEVERITY_INFO,
    SEVERITY_WARN,
    STATUS_NOK,
    STATUS_OK,
    STATUS_SKIP,
    STATUS_WARN,
)


TOL_AMOUNT_ABS = 1.0
TOL_AMOUNT_REL = 0.02
TOL_DUTY_ABS = 0.50
TOL_DUTY_REL = 0.02


def validate_bundle(bundle: Bundle) -> List[CheckResult]:
    checks: List[CheckResult] = []
    checks.extend(_check_presence(bundle))

    usable_invoices = [inv for inv in bundle.invoices if _usable_invoice(inv)]
    if usable_invoices and bundle.declarations:
        for inv in usable_invoices:
            decl = _best_decl_for_invoice(inv, bundle.declarations)
            checks.extend(_check_entity(inv, decl))
            checks.extend(_check_value_currency(inv, decl))
            checks.extend(_check_hs(inv, decl))

    if bundle.prestation and bundle.declarations:
        checks.extend(_check_prestation(bundle.prestation, bundle.declarations))
    elif not bundle.prestation:
        checks.append(CheckResult(
            code="prestation_optional",
            section="Documents",
            label="Facture de prestation",
            expected="Optionnelle",
            got="Absente",
            status=STATUS_SKIP,
            severity=SEVERITY_INFO,
            comment="Document non obligatoire.",
        ))

    bundle.checks = checks
    bundle.status = status_from_checks(bundle)
    return checks


def status_from_checks(bundle: Bundle) -> str:
    if not any(_usable_invoice(inv) for inv in bundle.invoices) or not bundle.declarations:
        return BUNDLE_MANQUE_DOC
    if any(c.is_blocking for c in bundle.checks):
        return BUNDLE_KO_BLOQUANT
    if any(c.status == STATUS_NOK for c in bundle.checks):
        return BUNDLE_KO
    if any(c.status == STATUS_WARN for c in bundle.checks):
        return BUNDLE_VERIFY
    return BUNDLE_OK


def blocking_reasons(checks: Iterable[CheckResult]) -> str:
    vals = [
        f"{c.label}: {c.comment or c.got}"
        for c in checks
        if c.status in (STATUS_NOK, STATUS_WARN)
    ]
    return " | ".join(vals)


def _check_presence(bundle: Bundle) -> List[CheckResult]:
    usable_invoice_count = sum(1 for inv in bundle.invoices if _usable_invoice(inv))
    unusable = [inv for inv in bundle.invoices if not _usable_invoice(inv)]
    comment = ""
    if not usable_invoice_count:
        if unusable:
            reasons = [inv.extras.get("not_goods_invoice_reason") for inv in unusable if inv.extras]
            reasons = [x for x in reasons if x]
            comment = "Fichier INV present mais non exploitable comme facture marchandise."
            if reasons:
                comment += " " + " ".join(reasons)
        else:
            comment = "Document obligatoire manquant."
    return [
        CheckResult(
            code="doc_invoice_present",
            section="Documents",
            label="Facture marchandise exploitable presente",
            expected=">= 1",
            got=str(usable_invoice_count),
            status=STATUS_OK if usable_invoice_count else STATUS_NOK,
            severity=SEVERITY_CRITICAL,
            comment=comment,
        ),
        CheckResult(
            code="doc_declaration_present",
            section="Documents",
            label="Declaration douaniere presente",
            expected=">= 1",
            got=str(len(bundle.declarations)),
            status=STATUS_OK if bundle.declarations else STATUS_NOK,
            severity=SEVERITY_CRITICAL,
            comment="" if bundle.declarations else "Document obligatoire manquant.",
        ),
    ]


def _usable_invoice(inv: Document) -> bool:
    return not bool((inv.extras or {}).get("not_goods_invoice"))


def _check_entity(inv: Document, decl: Document) -> List[CheckResult]:
    our_vats = current_profile().our_vats
    inv_vat = _norm_vat(inv.vat_buyer)
    inferred_vat, inferred_label = _expected_vat_from_invoice_identity(inv)
    if inv_vat in our_vats:
        expected_vat = inv_vat
    elif inferred_vat:
        expected_vat = inferred_vat
    else:
        expected_vat = inv_vat
    decl_vat = _norm_vat(decl.importer.vat or decl.buyer.vat)
    decl_our_vats = _our_vats_on_declaration(decl)
    decl_has_both_our_vats = our_vats.issubset(decl_our_vats)
    checks = []
    if not expected_vat:
        if decl_vat in our_vats or decl_has_both_our_vats:
            got = " + ".join(sorted(decl_our_vats)) if decl_our_vats else decl_vat
            checks.append(CheckResult(
                code="tva_scope",
                section="Entite",
                label="TVA facture dans le scope",
                expected=", ".join(sorted(our_vats)),
                got=f"Facture non lue / declaration {got}",
                status=STATUS_WARN,
                severity=SEVERITY_WARN,
                comment="OK - a controler: TVA facture non lue par OCR, mais la declaration reprend une TVA du scope.",
            ))
            return checks
        checks.append(CheckResult(
            code="tva_scope",
            section="Entite",
            label="TVA facture dans le scope",
            expected=", ".join(sorted(our_vats)),
            got="Absente sur facture",
            status=STATUS_NOK,
            severity=SEVERITY_CRITICAL,
            comment="Impossible de prouver que la facture marchandise nous concerne.",
        ))
        return checks

    in_scope = expected_vat in our_vats
    got_label = inv_vat if inv_vat in our_vats else f"{inferred_label} -> {inferred_vat}" if inferred_vat else inv_vat
    if not in_scope and decl_vat in our_vats and _amounts_match(inv, decl):
        # The invoice carries an out-of-scope VAT (often the broker's, captured
        # by OCR) but the declaration is ours and the amounts match exactly:
        # this is our dossier with an unread invoice identity, not an
        # out-of-scope invoice.
        checks.append(CheckResult(
            code="tva_scope",
            section="Entite",
            label="TVA facture dans le scope",
            expected=", ".join(sorted(our_vats)),
            got=got_label,
            status=STATUS_WARN,
            severity=SEVERITY_WARN,
            comment=(
                "OK - a controler: TVA lue sur la facture hors scope (broker"
                " probable), mais declaration du scope et montants identiques."
            ),
        ))
        return checks
    checks.append(CheckResult(
        code="tva_scope",
        section="Entite",
        label="TVA facture dans le scope",
        expected=", ".join(sorted(our_vats)),
        got=got_label,
        status=STATUS_OK if in_scope else STATUS_NOK,
        severity=SEVERITY_CRITICAL,
        comment=(
            "TVA facture inferée depuis le nom du Bill To."
            if in_scope and expected_vat == inferred_vat and inv_vat != inferred_vat
            else ("" if in_scope else "Nous ne sommes pas concernes par cette facture.")
        ),
    ))
    if in_scope:
        if decl_has_both_our_vats:
            checks.append(CheckResult(
                code="tva_match_decl",
                section="Entite",
                label="TVA declaration = TVA facture",
                expected=expected_vat,
                got=" + ".join(sorted(decl_our_vats)),
                status=STATUS_WARN,
                severity=SEVERITY_WARN,
                comment="OK - a controler: la declaration contient les deux TVA du scope.",
            ))
            return checks
        if decl_vat == expected_vat:
            mismatch_comment = ""
        elif decl_vat in our_vats:
            mismatch_comment = (
                "Entites du scope differentes: la facture identifie "
                f"{expected_vat} mais la declaration porte {decl_vat}."
            )
        else:
            mismatch_comment = "Erreur entite broker."
        checks.append(CheckResult(
            code="tva_match_decl",
            section="Entite",
            label="TVA declaration = TVA facture",
            expected=expected_vat,
            got=decl_vat or "Absente",
            status=STATUS_OK if decl_vat == expected_vat else STATUS_NOK,
            severity=SEVERITY_CRITICAL,
            comment=mismatch_comment,
        ))
    return checks


def _amounts_match(inv: Document, decl: Document) -> bool:
    return (
        inv.total_amount is not None
        and decl.total_amount is not None
        and _close(inv.total_amount, decl.total_amount)
    )


def _check_refs(inv: Document, decl: Document) -> List[CheckResult]:
    inv_no = _norm_ref(inv.invoice_number)
    refs = [_norm_ref(x) for x in decl.referenced_invoices]
    ok_ref = bool(inv_no and any(inv_no == r or inv_no in r or r in inv_no for r in refs))
    awb_ok = bool(_norm_ref(inv.awb) and _norm_ref(inv.awb) in {_norm_ref(decl.awb), *[_norm_ref(x) for x in decl.referenced_awbs]})
    return [
        CheckResult(
            code="invoice_ref_match",
            section="References",
            label="Reference facture sur declaration",
            expected=inv.invoice_number or "",
            got=", ".join(decl.referenced_invoices) or "",
            status=STATUS_OK if ok_ref else (STATUS_WARN if inv.invoice_number else STATUS_SKIP),
            severity=SEVERITY_WARN,
            comment="" if ok_ref else "Reference facture non retrouvee explicitement.",
        ),
        CheckResult(
            code="awb_match",
            section="References",
            label="AWB/LTA",
            expected=inv.awb or "",
            got=decl.awb or ", ".join(decl.referenced_awbs),
            status=STATUS_OK if awb_ok else (STATUS_SKIP if not inv.awb else STATUS_NOK),
            severity=SEVERITY_ERROR,
        ),
    ]


def _check_value_currency(inv: Document, decl: Document) -> List[CheckResult]:
    checks = []
    if not inv.currency or not decl.currency:
        invoice_missing_only = not inv.currency and bool(decl.currency)
        checks.append(CheckResult(
            code="currency_match",
            section="Valeur devise",
            label="Devise",
            expected=inv.currency or "A renseigner facture",
            got=decl.currency or "A renseigner declaration",
            status=STATUS_WARN if invoice_missing_only else STATUS_NOK,
            severity=SEVERITY_WARN if invoice_missing_only else SEVERITY_CRITICAL,
            comment=(
                "OK - a controler: devise facture non lue par OCR, devise presente sur declaration."
                if invoice_missing_only
                else "Devise absente sur un document."
            ),
        ))
    else:
        same_cur = inv.currency == decl.currency
        # French declarations legitimately convert the invoice currency to
        # EUR.  When the EUR amount matches the invoice amount at the
        # indicative FX rate, this is a correct conversion, not an error.
        fx_converted_ok = False
        fx_note = ""
        if (not same_cur and decl.currency == "EUR"
                and inv.total_amount is not None and decl.total_amount is not None):
            rate = current_profile().fx_rates.get(inv.currency)
            if rate:
                est_eur = inv.total_amount / rate
                if _close(est_eur, decl.total_amount, abs_tol=2.0, rel_tol=0.25):
                    fx_converted_ok = True
                    fx_note = (
                        f"Declaration en EUR coherente avec la facture {inv.currency}"
                        f" (~{est_eur:.2f} EUR au taux indicatif)."
                    )
        # Same amount on both sides with different currencies: the invoice
        # currency was almost certainly misread (parser EUR default), not a
        # customs error.  Review warning instead of blocking KO.
        currency_misread = (
            not same_cur and not fx_converted_ok
            and inv.total_amount is not None and decl.total_amount is not None
            and _close(inv.total_amount, decl.total_amount)
        )
        cur_ok = same_cur or fx_converted_ok
        if currency_misread:
            checks.append(CheckResult(
                code="currency_match",
                section="Valeur devise",
                label="Devise",
                expected=inv.currency,
                got=decl.currency,
                status=STATUS_WARN,
                severity=SEVERITY_WARN,
                comment=(
                    "OK - a controler: meme montant des deux cotes, la devise facture"
                    " est probablement mal lue par OCR."
                ),
            ))
        else:
            checks.append(CheckResult(
                code="currency_match",
                section="Valeur devise",
                label="Devise",
                expected=inv.currency,
                got=decl.currency,
                status=STATUS_OK if cur_ok else STATUS_NOK,
                severity=SEVERITY_CRITICAL,
                comment=fx_note if cur_ok else ("" if same_cur else "Erreur de devise probable."),
            ))
        if fx_converted_ok:
            checks.append(CheckResult(
                code="amount_match",
                section="Valeur devise",
                label="Montant facture",
                expected=_money(inv.total_amount, inv.currency),
                got=_money(decl.total_amount, decl.currency),
                status=STATUS_OK,
                severity=SEVERITY_CRITICAL,
                comment=fx_note,
            ))
            return checks

    if inv.total_amount is None or decl.total_amount is None:
        invoice_missing_only = inv.total_amount is None and decl.total_amount is not None
        checks.append(CheckResult(
            code="amount_match",
            section="Valeur devise",
            label="Montant facture",
            expected=_money(inv.total_amount, inv.currency),
            got=_money(decl.total_amount, decl.currency),
            status=STATUS_WARN if invoice_missing_only else STATUS_NOK,
            severity=SEVERITY_WARN if invoice_missing_only else SEVERITY_CRITICAL,
            comment=(
                "OK - a controler: montant facture non lu par OCR, montant present sur declaration."
                if invoice_missing_only
                else "Montant absent sur un document."
            ),
        ))
    else:
        ok = _close(inv.total_amount, decl.total_amount)
        # A total rebuilt by summing OCR-read lines is a lower-bound estimate:
        # missed rows make it undershoot.  Review warning, not blocking KO.
        partial_line_sum = (
            not ok
            and bool((inv.extras or {}).get("total_estimated_from_lines"))
            and inv.total_amount < decl.total_amount
        )
        if partial_line_sum:
            checks.append(CheckResult(
                code="amount_match",
                section="Valeur devise",
                label="Montant facture",
                expected=_money(inv.total_amount, inv.currency),
                got=_money(decl.total_amount, decl.currency),
                status=STATUS_WARN,
                severity=SEVERITY_WARN,
                comment=(
                    "OK - a controler: total facture estime en sommant les lignes"
                    " lues par OCR (lecture probablement partielle)."
                ),
            ))
        else:
            checks.append(CheckResult(
                code="amount_match",
                section="Valeur devise",
                label="Montant facture",
                expected=_money(inv.total_amount, inv.currency),
                got=_money(decl.total_amount, decl.currency),
                status=STATUS_OK if ok else STATUS_NOK,
                severity=SEVERITY_CRITICAL,
                comment="" if ok else _amount_comment(inv, decl),
            ))

    return checks


def _check_hs(inv: Document, decl: Document) -> List[CheckResult]:
    inv_hs = _dedupe([hs for x in inv.hs_codes if (hs := normalize_hs(x, scope_only=True))])
    decl_hs = _dedupe([hs for x in decl.hs_codes if (hs := normalize_hs(x, scope_only=False))])
    if not inv_hs:
        if decl_hs:
            return [CheckResult(
                code="hs_present_invoice",
                section="HS",
                label="HS presents sur facture",
                expected="Au moins 1",
                got="Facture non lue / declaration: " + ", ".join(decl_hs),
                status=STATUS_WARN,
                severity=SEVERITY_WARN,
                comment="OK - a controler: HS facture non lu par OCR, HS present sur declaration.",
            )]
        return [CheckResult(
            code="hs_present_invoice",
            section="HS",
            label="HS presents sur facture",
            expected="Au moins 1",
            got="0",
            status=STATUS_NOK,
            severity=SEVERITY_CRITICAL,
            comment="La facture ne contient pas de HS exploitable.",
        )]
    if not decl_hs:
        return [CheckResult(
            code="hs_present_decl",
            section="HS",
            label="HS presents sur declaration",
            expected=", ".join(inv_hs),
            got="0",
            status=STATUS_NOK,
            severity=SEVERITY_CRITICAL,
        )]

    decl_hs6 = {x[:6] for x in decl_hs}
    missing = [hs for hs in inv_hs if hs[:6] not in decl_hs6]
    # OCR confuses visually-similar digits on faxed invoices (6↔8, 3↔5, 0↔9…).
    # An invoice HS absent from the declaration but OCR-confusable with a
    # declared HS6 is downgraded to a warning for human review, not a hard KO.
    ocr_suspect = [
        hs for hs in missing
        if any(_hs_ocr_confusable(hs[:6], d6) for d6 in decl_hs6)
    ]
    hard_missing = [hs for hs in missing if hs not in ocr_suspect]
    if hard_missing:
        status = STATUS_NOK
        comment = "HS manquants: " + ", ".join(hard_missing)
        if ocr_suspect:
            comment += " | HS facture probablement mal lus par OCR: " + ", ".join(ocr_suspect)
    elif ocr_suspect:
        status = STATUS_WARN
        comment = (
            "OK - a controler: HS facture probablement mal lus par OCR "
            "(proches d'un HS declare): " + ", ".join(ocr_suspect)
        )
    else:
        status = STATUS_OK
        comment = ""
    return [CheckResult(
        code="hs_subset_6digit",
        section="HS",
        label="Chaque HS facture repris en declaration (6 digits)",
        expected=", ".join(inv_hs),
        got=", ".join(decl_hs),
        status=status,
        severity=SEVERITY_CRITICAL if status == STATUS_NOK else SEVERITY_WARN,
        comment=comment,
    )]


# Digit pairs Tesseract routinely swaps on degraded scans.
_OCR_CONFUSABLE = {
    "0": "689",
    "1": "47",
    "2": "7",
    "3": "58",
    "4": "19",
    "5": "368",
    "6": "0589",
    "7": "12",
    "8": "0356",
    "9": "047",
}


def _hs_ocr_confusable(a: str, b: str) -> bool:
    """True when two HS6 differ only by 1-2 OCR-confusable digits."""
    if len(a) != len(b) or a == b:
        return False
    diffs = [(x, y) for x, y in zip(a, b) if x != y]
    if not 1 <= len(diffs) <= 2:
        return False
    return all(y in _OCR_CONFUSABLE.get(x, "") for x, y in diffs)


def _check_preference(inv: Document, decl: Document) -> List[CheckResult]:
    prefs = [ln.preference for ln in decl.lines if ln.preference]
    if not prefs:
        return [CheckResult(
            code="preference_consistency",
            section="Preference",
            label="Preference declaration",
            expected="Renseignee si applicable",
            got="Absente",
            status=STATUS_SKIP,
            severity=SEVERITY_CRITICAL,
        )]
    return [CheckResult(
        code="preference_consistency",
        section="Preference",
        label="Preference declaration",
        expected="Coherente",
        got=", ".join(_dedupe(prefs)),
        status=STATUS_OK,
        severity=SEVERITY_CRITICAL,
    )]


def _check_weight(inv: Document, decl: Document) -> List[CheckResult]:
    checks = []
    if decl.net_weight_kg is not None and decl.gross_weight_kg is not None:
        checks.append(CheckResult(
            code="weight_net_lte_gross",
            section="Poids",
            label="Poids net <= poids brut",
            expected=f"<= {decl.gross_weight_kg}",
            got=str(decl.net_weight_kg),
            status=STATUS_OK if decl.net_weight_kg <= decl.gross_weight_kg + 0.001 else STATUS_WARN,
            severity=SEVERITY_WARN,
        ))
    return checks


def _check_prestation(presta: Document, decls: List[Document]) -> List[CheckResult]:
    expected = _declaration_customs_total(decls)
    got = _prestation_customs_total(presta)
    if expected is None:
        return [CheckResult(
            code="presta_debours_vs_decl",
            section="Prestation",
            label="Debours prestation = droits/taxes declaration",
            expected="Montant droits/taxes declaration",
            got=_money(got, "EUR") if got is not None else "Absent",
            status=STATUS_NOK,
            severity=SEVERITY_CRITICAL,
            comment="Montant droits/taxes non extrait sur la declaration.",
        )]
    if got is None:
        return [CheckResult(
            code="presta_debours_vs_decl",
            section="Prestation",
            label="Debours prestation = droits/taxes declaration",
            expected=_money(expected, "EUR"),
            got="Absent",
            status=STATUS_NOK,
            severity=SEVERITY_CRITICAL,
            comment="Montant debours non extrait sur la facture de prestation.",
        )]
    ok = _close(expected, got, abs_tol=TOL_DUTY_ABS, rel_tol=TOL_DUTY_REL)
    return [CheckResult(
        code="presta_debours_vs_decl",
        section="Prestation",
        label="Debours prestation = droits/taxes declaration",
        expected=_money(expected, "EUR"),
        got=_money(got, "EUR"),
        status=STATUS_OK if ok else STATUS_NOK,
        severity=SEVERITY_CRITICAL,
        comment="" if ok else "Ecart entre les droits/taxes de la declaration et la facture de prestation.",
    )]


def _declaration_customs_total(decls: List[Document]) -> Optional[float]:
    vals = []
    for d in decls:
        parts = [d.dd, d.at, d.tva]
        if any(v is not None for v in parts):
            parts_total = sum(v or 0 for v in parts)
            # Delta IE sometimes exposes the article total (TG) even when one
            # tax component, usually AT, was not parsed from the liquidation
            # table.  For the prestation check we need the payable customs
            # total, so keep TG when it is the more complete amount.
            if d.tg is not None and d.tg > parts_total + TOL_DUTY_ABS:
                vals.append(d.tg)
            else:
                vals.append(parts_total)
        elif d.tg is not None:
            vals.append(d.tg)
    return round(sum(vals), 2) if vals else None


def _prestation_customs_total(presta: Document) -> Optional[float]:
    if presta.total_debours is not None:
        return presta.total_debours
    parts = [presta.dd, presta.at, presta.tva]
    if any(v is not None for v in parts):
        return round(sum(v or 0 for v in parts), 2)
    return None


def _money_check(code: str, section: str, label: str, expected: Optional[float],
                 got: Optional[float], severity: str) -> CheckResult:
    if got is None:
        return CheckResult(code, section, label, _money(expected, "EUR"), "Absent", STATUS_SKIP, severity)
    ok = expected is not None and _close(expected, got, abs_tol=TOL_DUTY_ABS, rel_tol=TOL_DUTY_REL)
    return CheckResult(code, section, label, _money(expected, "EUR"), _money(got, "EUR"), STATUS_OK if ok else STATUS_NOK, severity)


def _best_decl_for_invoice(inv: Document, decls: List[Document]) -> Document:
    inv_no = _norm_ref(inv.invoice_number)
    inv_awb = _norm_ref(inv.awb)
    inv_sub = (inv.extras or {}).get("source_awb_folder")
    best = None
    best_score = -1
    for d in decls:
        score = 0
        dec_sub = (d.extras or {}).get("source_awb_folder")
        if inv_sub and dec_sub and inv_sub == dec_sub:
            score += 100
        refs = [_norm_ref(x) for x in d.referenced_invoices]
        if inv_no and any(inv_no == r or inv_no in r or r in inv_no for r in refs):
            score += 80
        dec_awbs = {_norm_ref(d.awb), *[_norm_ref(x) for x in d.referenced_awbs]}
        if inv_awb and inv_awb in dec_awbs:
            score += 80
        if inv.total_amount is not None and d.total_amount is not None and _close(inv.total_amount, d.total_amount):
            score += 20
        if score > best_score:
            best_score = score
            best = d
    return best or decls[0]


def _fx_sanity(inv: Document, decl: Document) -> CheckResult:
    if inv.total_amount is None or not inv.currency:
        return CheckResult("currency_fx_sanity", "Valeur devise", "Ordre de grandeur devise", status=STATUS_SKIP)
    rate = current_profile().fx_rates.get(inv.currency)
    if not rate:
        return CheckResult("currency_fx_sanity", "Valeur devise", "Ordre de grandeur devise", got=inv.currency, status=STATUS_SKIP)
    if decl.currency == inv.currency:
        return CheckResult("currency_fx_sanity", "Valeur devise", "Ordre de grandeur devise", expected=inv.currency, got=decl.currency, status=STATUS_OK)
    if decl.currency == "EUR" and decl.total_amount is not None and _close(inv.total_amount, decl.total_amount, abs_tol=1.0, rel_tol=0.05):
        return CheckResult(
            "currency_fx_sanity", "Valeur devise", "Ordre de grandeur devise",
            expected=f"{inv.total_amount:.2f} {inv.currency} ~= {inv.total_amount / rate:.2f} EUR",
            got=f"{decl.total_amount:.2f} EUR",
            status=STATUS_NOK,
            severity=SEVERITY_CRITICAL,
            comment="Montant etranger semble repris comme EUR sans conversion.",
        )
    return CheckResult("currency_fx_sanity", "Valeur devise", "Ordre de grandeur devise", status=STATUS_WARN, severity=SEVERITY_WARN)


def _amount_comment(inv: Document, decl: Document) -> str:
    if inv.currency != decl.currency:
        return "La devise de declaration ne reprend pas celle de la facture."
    return "Ecart de montant entre facture marchandise et declaration."


def _norm_vat(v: Optional[str]) -> str:
    return re.sub(r"\s+", "", v or "").upper()


def _our_vats_on_declaration(decl: Document) -> set[str]:
    return current_profile().our_vats_in_text(
        decl.text,
        decl.importer.vat,
        decl.buyer.vat,
        decl.declarant.vat,
    )


def _expected_vat_from_invoice_identity(inv: Document) -> tuple[str, str]:
    """Infer our expected VAT from the invoice's Bill To identity.

    This is deliberately narrower than a generic text search: we first inspect
    parsed buyer/importer names, then look around common billing labels in raw
    text.  The inferred VAT is only accepted if the declaration repeats the
    matching number.
    """
    candidates = " ".join(
        x for x in [
            inv.buyer.name,
            inv.importer.name,
            inv.extras.get("bill_to") if inv.extras else None,
            inv.extras.get("ship_to") if inv.extras else None,
        ]
        if x
    ).upper()
    raw = (inv.text or "").upper()
    bill_context = _label_context(raw, ("BILL TO", "BIEL TO", "BILLED TO", "INVOICE TO", "SOLD TO", "ACHETEUR", "CLIENT"))
    ship_context = _label_context(raw, ("SHIP TO", "DESTINATAIRE", "IMPORTATEUR", "ULTIMATE CONSIGNEE"))
    searchable = f"{candidates}\n{bill_context}"

    # Bill To is authoritative.  Only fall back to Ship To if Bill To did not
    # identify one of our entities.  The mapping (names, addresses, SIREN
    # digit evidence) lives on the active client profile.
    profile = current_profile()
    for context, label in ((searchable, "Bill To"), (ship_context, "Ship To")):
        vat = profile.identity_vat(context)
        if vat:
            entity = profile.entity_label_by_vat.get(vat) or profile.entity_name
            return vat, f"{entity} ({label})"
    return "", ""


def _billing_context(text: str) -> str:
    if not text:
        return ""
    contexts = []
    labels = (
        "BILL TO", "BILLED TO", "INVOICE TO", "SHIP TO", "SOLD TO",
        "ACHETEUR", "DESTINATAIRE", "IMPORTATEUR", "CLIENT",
        "DIRECTION FISCALE DU CLIENT", "DIRECCION FISCAL DEL CLIENTE",
    )
    for label in labels:
        idx = text.find(label)
        if idx >= 0:
            contexts.append(text[idx: idx + 500])
    return "\n".join(contexts)


def _label_context(text: str, labels: Iterable[str], width: int = 650) -> str:
    contexts = []
    for label in labels:
        idx = text.find(label)
        if idx >= 0:
            contexts.append(text[idx: idx + width])
    return "\n".join(contexts)


def _norm_ref(v: Optional[str]) -> str:
    return re.sub(r"[^A-Z0-9]", "", v or "").upper()


def _mrn_prefix(v: Optional[str]) -> str:
    return _norm_ref(v)[:15]


def _digits(v: Optional[str]) -> str:
    return re.sub(r"\D", "", v or "")


def _money(v: Optional[float], cur: Optional[str]) -> str:
    if v is None:
        return ""
    return f"{v:.2f} {cur or ''}".strip()


def _close(a: float, b: float, abs_tol: float = TOL_AMOUNT_ABS, rel_tol: float = TOL_AMOUNT_REL) -> bool:
    diff = abs(a - b)
    if diff <= abs_tol:
        return True
    return diff / max(abs(a), abs(b), 1) <= rel_tol


def _dedupe(values: Iterable[str]) -> List[str]:
    seen, out = set(), []
    for v in values:
        if v and v not in seen:
            seen.add(v)
            out.append(v)
    return out
