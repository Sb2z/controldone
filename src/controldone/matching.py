"""Score-based document matcher for v4.

Mandatory dossier shape:
    1+ goods invoice + 1+ customs declaration + optional prestation invoice

The matcher starts from invoices because the goods invoice is the source of
truth.  Declarations are attached by invoice reference, AWB/LTA, amount, HS and
VAT.  Prestations are then attached to the best declaration through MRN/AWB or
amounts.
"""
from __future__ import annotations

import os
import re
from typing import Dict, Iterable, List, Tuple

from controldone.models import Bundle, Document


def build_bundles_v4(documents: Iterable[Document]) -> List[Bundle]:
    docs = list(documents)
    grouped: Dict[str, List[Document]] = {}
    no_context: List[Document] = []
    for d in docs:
        dossier = (d.extras or {}).get("source_dossier")
        if dossier:
            grouped.setdefault(dossier, []).append(d)
        else:
            no_context.append(d)

    if grouped:
        out: List[Bundle] = []
        for _, group_docs in sorted(grouped.items()):
            out.extend(_build_bundles_unscoped(group_docs))
        if no_context:
            out.extend(_build_bundles_unscoped(no_context))
        return out

    return _build_bundles_unscoped(docs)


def _build_bundles_unscoped(documents: Iterable[Document]) -> List[Bundle]:
    invoices = [d for d in documents if d.kind == "invoice"]
    declarations = [d for d in documents if d.kind == "declaration"]
    prestations = [d for d in documents if d.kind == "prestation"]

    bundles: List[Bundle] = []
    used_decls = set()
    used_presta = set()

    for inv in invoices:
        scored_decls = sorted(
            ((_score_invoice_decl(inv, dec), dec) for dec in declarations),
            key=lambda x: x[0],
            reverse=True,
        )
        matched_decls = []
        for score, dec in scored_decls:
            if score >= 60:
                matched_decls.append(dec)
                used_decls.add(id(dec))
        if not matched_decls and declarations:
            # Keep the most plausible declaration visible instead of silently
            # orphaning the invoice. Validation will mark missing/weak links.
            score, dec = scored_decls[0]
            if score >= 15:
                matched_decls = [dec]
                used_decls.add(id(dec))

        bundle = Bundle(invoices=[inv], declarations=matched_decls)
        bundle.source_files = _sources(bundle.invoices + bundle.declarations)

        presta = _best_prestation_for_bundle(bundle, prestations)
        if presta:
            bundle.prestation = presta
            used_presta.add(id(presta))
            bundle.source_files = _sources(bundle.invoices + bundle.declarations + [presta])
        bundles.append(bundle)

    # Declarations with no invoice are explicit MANQUE_DOC candidates.
    for dec in declarations:
        if id(dec) in used_decls:
            continue
        bundle = Bundle(declarations=[dec], source_files=_sources([dec]))
        presta = _best_prestation_for_bundle(bundle, prestations)
        if presta:
            bundle.prestation = presta
            used_presta.add(id(presta))
            bundle.source_files = _sources([dec, presta])
        bundles.append(bundle)

    # Prestations with no declaration/invoice are also reported.
    for presta in prestations:
        if id(presta) not in used_presta:
            bundles.append(Bundle(prestation=presta, source_files=_sources([presta])))

    return _merge_duplicate_bundles(bundles)


def _score_invoice_decl(inv: Document, dec: Document) -> int:
    inv_sub = (inv.extras or {}).get("source_awb_folder")
    dec_sub = (dec.extras or {}).get("source_awb_folder")
    if inv_sub and dec_sub and inv_sub != dec_sub:
        return 0

    score = 0
    if inv_sub and dec_sub and inv_sub == dec_sub:
        score += 100

    inv_no = _norm_ref(inv.invoice_number)
    decl_refs = [_norm_ref(x) for x in dec.referenced_invoices]
    if inv_no and any(inv_no == r or inv_no in r or r in inv_no for r in decl_refs):
        score += 80

    inv_awb = _norm_ref(inv.awb)
    dec_awbs = [_norm_ref(dec.awb)] + [_norm_ref(x) for x in dec.referenced_awbs]
    if inv_awb and inv_awb in dec_awbs:
        score += 60

    if inv.total_amount is not None and dec.total_amount is not None:
        if _amount_close(inv.total_amount, dec.total_amount):
            score += 35
        elif dec.fx_rate and dec.currency and dec.currency != "EUR":
            eur = inv.total_amount / dec.fx_rate
            if _amount_close(eur, dec.total_amount):
                score += 20

    inv_vat = inv.vat_buyer
    dec_vat = dec.importer.vat or dec.buyer.vat
    if inv_vat and dec_vat and inv_vat == dec_vat:
        score += 20

    inv_hs6 = {_hs6(x) for x in inv.hs_codes if _hs6(x)}
    dec_hs6 = {_hs6(x) for x in dec.hs_codes if _hs6(x)}
    if inv_hs6 and dec_hs6:
        overlap = inv_hs6 & dec_hs6
        if overlap:
            score += min(20, 8 * len(overlap))

    # Filename conventions such as 2878670034_INV_1 / 2878670034_ENT_3.
    inv_key = _leading_ref(inv.source_file)
    dec_key = _leading_ref(dec.source_file)
    if inv_key and inv_key == dec_key:
        score += 70

    return score


def _score_presta_bundle(presta: Document, bundle: Bundle) -> int:
    score = 0
    presta_dossier = (presta.extras or {}).get("source_dossier")
    bundle_dossiers = {
        (d.extras or {}).get("source_dossier")
        for d in bundle.declarations + bundle.invoices
        if (d.extras or {}).get("source_dossier")
    }
    if presta_dossier and bundle_dossiers and presta_dossier not in bundle_dossiers:
        return 0
    if presta_dossier and bundle_dossiers and presta_dossier in bundle_dossiers:
        score += 100

    mrns = {_mrn_prefix(d.mrn) for d in bundle.declarations if d.mrn}
    presta_mrns = {_mrn_prefix(x) for x in presta.referenced_mrns}
    if mrns and presta_mrns and (mrns & presta_mrns):
        score += 90

    awbs = {_norm_ref(bundle.ref_awb_lta)}
    for d in bundle.declarations + bundle.invoices:
        awbs.add(_norm_ref(d.awb))
        awbs.update(_norm_ref(x) for x in d.referenced_awbs)
    presta_awbs = {_norm_ref(presta.awb)}
    presta_awbs.update(_norm_ref(x) for x in presta.referenced_awbs)
    if "" in awbs:
        awbs.remove("")
    if "" in presta_awbs:
        presta_awbs.remove("")
    if awbs and presta_awbs and (awbs & presta_awbs):
        score += 60

    decl_debours = sum((d.dd or 0) + (d.at or 0) + (d.tva or 0) for d in bundle.declarations)
    if presta.total_debours is not None and decl_debours:
        if abs(presta.total_debours - decl_debours) <= 1.0:
            score += 30

    # Same source PDF is a strong but not absolute signal.
    if presta.source_file and presta.source_file in bundle.source_files:
        score += 40

    return score


def _best_prestation_for_bundle(bundle: Bundle, prestations: List[Document]) -> Document | None:
    best = None
    best_score = 0
    for p in prestations:
        score = _score_presta_bundle(p, bundle)
        if score > best_score:
            best = p
            best_score = score
    return best if best_score >= 30 else None


def _merge_duplicate_bundles(bundles: List[Bundle]) -> List[Bundle]:
    by_key: Dict[str, Bundle] = {}
    out: List[Bundle] = []
    for b in bundles:
        key = b.ref_prestation_no or b.ref_awb_lta or b.ref_mrn or "|".join(sorted(b.source_files))
        if key and key in by_key:
            target = by_key[key]
            target.invoices = _doc_dedupe(target.invoices + b.invoices)
            target.declarations = _doc_dedupe(target.declarations + b.declarations)
            target.prestation = target.prestation or b.prestation
            target.source_files = _sources(target.invoices + target.declarations + ([target.prestation] if target.prestation else []))
        else:
            by_key[key] = b
            out.append(b)
    return out


def _doc_dedupe(docs: List[Document]) -> List[Document]:
    seen, out = set(), []
    for d in docs:
        key = (d.kind, d.source_file, tuple(d.source_pages), d.invoice_number, d.mrn)
        if key not in seen:
            seen.add(key)
            out.append(d)
    return out


def _sources(docs: Iterable[Document]) -> List[str]:
    vals = []
    for d in docs:
        if d and d.source_file and d.source_file not in vals:
            vals.append(d.source_file)
    return vals


def _norm_ref(v: str | None) -> str:
    if not v:
        return ""
    return re.sub(r"[^A-Z0-9]", "", str(v).upper())


def _mrn_prefix(v: str | None) -> str:
    return _norm_ref(v)[:15]


def _leading_ref(path: str | None) -> str:
    if not path:
        return ""
    base = os.path.basename(path)
    m = re.match(r"([0-9]{8,12})_", base)
    if m:
        return m.group(1)
    return ""


def _hs6(v: str | None) -> str:
    if not v:
        return ""
    digits = re.sub(r"\D", "", v)
    return digits[:6] if len(digits) >= 6 else ""


def _amount_close(a: float, b: float, abs_tol: float = 1.0, rel_tol: float = 0.01) -> bool:
    diff = abs(a - b)
    if diff <= abs_tol:
        return True
    ref = max(abs(a), abs(b), 1)
    return diff / ref <= rel_tol
