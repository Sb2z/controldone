"""Construction des données d'un dossier (avant injection) : factures commerciales, déclarations,
factures du transitaire, avoirs, documents support. Montants en Decimal, arrondis ROUND_HALF_UP.
"""

from __future__ import annotations

import csv
from datetime import date
from decimal import Decimal as D
from functools import lru_cache
from pathlib import Path

from .util import (ZERO, add_days, awb_fictif, bl_fictif, cmr_fictif, cur_decimals, lrn_fictif,
                   mrn_fictif, q2, q3, q5, qcur)
from .world import (CATALOG, FALLBACK_RATES, LABELS, REMISE, SUPPLIERS_BY_ID, UNIT_LABELS,
                    fam_lang, poste)

REPO = Path(__file__).resolve().parents[2]

# ---------------------------------------------------------------------------
# Capacités des familles de transitaire et des présentations de déclaration
# ---------------------------------------------------------------------------

FAMCAP = {
    "G1": {"ventile": True, "line_vat": True, "line_vat_debours": True, "storage": True, "avoir": True, "forfait_base": True, "total_debours": True},
    "G2": {"ventile": True, "line_vat": False, "line_vat_debours": False, "storage": True, "avoir": True, "forfait_base": False, "total_debours": True, "statement": True},
    "G3": {"ventile": True, "line_vat": False, "line_vat_debours": False, "storage": True, "avoir": True, "forfait_base": True, "total_debours": True},
    "G4": {"ventile": True, "line_vat": True, "line_vat_debours": True, "storage": True, "avoir": True, "forfait_base": True, "total_debours": True},
    "G5": {"ventile": True, "line_vat": True, "line_vat_debours": False, "storage": True, "avoir": True, "forfait_base": False, "total_debours": True},
    "G6": {"ventile": False, "line_vat": True, "line_vat_debours": False, "storage": False, "avoir": True, "forfait_base": False, "total_debours": False, "combine": True},
    "G7": {"ventile": True, "line_vat": True, "line_vat_debours": True, "storage": True, "avoir": False, "forfait_base": False, "total_debours": True, "structured": "ubl"},
    "G8": {"ventile": True, "line_vat": True, "line_vat_debours": True, "storage": True, "avoir": False, "forfait_base": False, "total_debours": False, "structured": "cii"},
    "G9": {"ventile": True, "line_vat": True, "line_vat_debours": True, "storage": True, "avoir": True, "forfait_base": True, "total_debours": True},
    "G10": {"ventile": True, "line_vat": False, "line_vat_debours": False, "storage": True, "avoir": True, "forfait_base": False, "total_debours": True},
    "G11": {"ventile": True, "line_vat": True, "line_vat_debours": True, "storage": False, "avoir": True, "forfait_base": True, "total_debours": True},
    "G12": {"ventile": True, "line_vat": True, "line_vat_debours": False, "storage": True, "avoir": True, "forfait_base": True, "total_debours": True, "split_invoices": True},
    # --- extension 2.1 (option --ext) ---
    "G13": {"ventile": True, "line_vat": True, "line_vat_debours": True, "storage": True, "avoir": True, "forfait_base": False, "total_debours": True, "vat_inclusive": True},
    "G14": {"ventile": True, "line_vat": False, "line_vat_debours": False, "storage": True, "avoir": True, "forfait_base": True, "total_debours": True, "summary_page": True},
    "G15": {"ventile": True, "line_vat": False, "line_vat_debours": False, "storage": True, "avoir": True, "forfait_base": False, "total_debours": True, "statement": True, "credit_lines": True},
    "G16": {"ventile": True, "line_vat": True, "line_vat_debours": False, "storage": True, "avoir": True, "forfait_base": True, "total_debours": True, "summary_page": True},
}

LAYCAP = {
    "M1": {"qty": True, "colis_art": True, "type_totals": True, "sous_type": "h1", "format": "pdf"},
    "M2": {"qty": True, "colis_art": True, "type_totals": True, "sous_type": "h1", "format": "pdf", "landscape": True},
    "M3": {"qty": False, "colis_art": False, "type_totals": True, "sous_type": "preuve_dedouanement", "format": "pdf"},
    "M4": {"qty": False, "colis_art": True, "type_totals": False, "sous_type": "preuve_dedouanement", "format": "eml"},
    "M5": {"qty": True, "colis_art": True, "type_totals": True, "sous_type": "export_xml", "format": "xml_declaration"},
    "M6": {"qty": True, "colis_art": True, "type_totals": False, "sous_type": "export_csv", "format": "csv_declaration"},
    # --- extension 2.1 (option --ext) ---
    "M7": {"qty": True, "colis_art": True, "type_totals": True, "sous_type": "h1", "format": "pdf"},
    "M8": {"qty": False, "colis_art": True, "type_totals": True, "sous_type": "h1", "format": "pdf", "landscape": True},
    "M9": {"qty": True, "colis_art": True, "type_totals": True, "sous_type": "export_xml", "format": "xml_declaration"},
}

FORFAIT_UNITAIRE = D("3.00")
FORFAIT_DEBUT = date(2026, 7, 1)
FORFAIT_FIN = date(2028, 7, 1)


@lru_cache(maxsize=1)
def bce_table() -> dict:
    tab: dict = {}
    p = REPO / "ref" / "taux_bce.csv"
    if not p.is_file():
        return tab
    with p.open(encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            tab.setdefault(row["devise"], []).append((row["date"], D(row["devise_par_eur"])))
    for k in tab:
        tab[k].sort()
    return tab


def bce_rate(devise: str, d: date) -> D:
    rows = bce_table().get(devise)
    if not rows:
        return D(FALLBACK_RATES[devise])
    iso = d.isoformat()
    best = rows[0][1]
    for dt, r in rows:
        if dt <= iso:
            best = r
        else:
            break
    return best


def eur_per_unit(rate: D, sens: str) -> D:
    return (D(1) / rate) if sens == "devise_par_eur" else rate


def to_eur(amount: D, rate: D, sens: str) -> D:
    if sens == "devise_par_eur":
        return q2(D(amount) / rate)
    return q2(D(amount) * rate)


# ---------------------------------------------------------------------------
# Facture commerciale
# ---------------------------------------------------------------------------

def _ci_number(rng, sup_id: str, d: date) -> str:
    n = rng.randint(100, 9999)
    styles = {
        "S_CN1": f"SFT{d.year % 100}{d.month:02d}-{n:04d}", "S_CN2": f"NIH-{d.year}-{n:05d}",
        "S_JP": f"OPO/{d.year}/{n:04d}", "S_KR": f"BME{d.year % 100}{n:05d}", "S_IN": f"PNT/EXP/{n:04d}/{d.year % 100}-{(d.year + 1) % 100}",
        "S_TR": f"IHM{d.year}{n:06d}", "S_GB": f"SPT-INV-{n:05d}", "S_CH1": f"RE-{d.year}-{n:04d}",
        "S_CH2": f"FT {n}/{d.year}", "S_CH3": f"GI-{d.year % 100}-{n:04d}", "S_AW": f"ODH {d.year}.{n:04d}",
        "S_MX": f"FMX-{n:05d}-{d.year % 100}", "S_US": f"OMS{n:06d}",
        "S_PT": f"FT PIC{d.year}/{n:04d}", "S_PL": f"FV/{n:04d}/{d.year}/EXP",
    }
    return styles[sup_id]


def make_ci(ctx, rng, *, doc_id, sup_id, devise, d_ci: date, lines_spec, incoterm, transport, h7=False,
            proforma=False, freight_trap=False):
    sup = SUPPLIERS_BY_ID[sup_id]
    sp = ctx["spec"]
    ent = ctx["entity"]
    fx = D(1) if devise == "EUR" else bce_rate(devise, d_ci)
    dec = cur_decimals(devise)
    lines = []
    for i, (prod, qty) in enumerate(lines_spec, 1):
        base_eur = prod["price"] * D(str(round(rng.uniform(0.85, 1.25), 3)))
        if dec == 0:
            pu = D(int((base_eur * fx).to_integral_value()))
            if pu < 1:
                pu = D(1)
        else:
            pu = (base_eur * fx).quantize(D("0.01") if base_eur * fx >= 1 else D("0.0001"))
            if pu <= 0:
                pu = D("0.01")
        amount = qcur(qty * pu, devise)
        origin = sup["pays"]
        if rng.random() < 0.18 and sup["pays"] in ("CH", "AW", "MX", "GB", "US"):
            origin = rng.choice(["CN", "VN", "TW", "IN", "TH"])
        if prod["ref"].endswith("-B") and lines and lines[-1]["ref"] == prod["ref"][:-2]:
            origin = lines[-1]["origin"]
        net = q3(qty * prod["kg"])
        if net <= 0:
            net = D("0.010")
        gross = q3(net * D(str(round(rng.uniform(1.04, 1.22), 3))))
        lines.append({"no": i, "ref": prod["ref"], "hs10": prod["hs"], "desc": prod["desc"].get(sup["lang"], prod["desc"]["en"]),
                      "desc_fr": prod["desc"]["fr"], "qty": D(qty), "unit": prod["unit"],
                      "unit_raw": rng.choice(UNIT_LABELS[prod["unit"]].get(sup["lang"], UNIT_LABELS[prod["unit"]]["en"])),
                      "pu": pu, "amount": amount, "origin": origin, "net": net, "gross": gross,
                      "duty": prod["duty"], "ad": prod["ad"] if (prod["ad"] and origin == "CN") else None})
    goods = sum((ln["amount"] for ln in lines), ZERO)
    sub = {"marchandises": goods}
    if incoterm in ("CFR", "CIF", "CPT", "CIP", "DAP", "DDP") or freight_trap:
        sub["fret"] = qcur(goods * D(str(round(rng.uniform(0.03, 0.09), 3))), devise)
        if incoterm in ("CIF", "CIP") and not h7:
            sub["assurance"] = qcur(goods * D("0.004") + (1 if dec == 0 else D("0.5")), devise)
    if rng.random() < 0.15 and not h7:
        sub["emballage"] = qcur(goods * D("0.01") + (D(150) if dec == 0 and devise == "JPY" else D(5)), devise)
    if rng.random() < 0.10 and not h7:
        sub["remise"] = qcur(goods * D("0.02"), devise)
    total = goods + sub.get("fret", ZERO) + sub.get("assurance", ZERO) + sub.get("emballage", ZERO) - sub.get("remise", ZERO)
    total = qcur(total, devise)
    net_t = q3(sum((ln["net"] for ln in lines), ZERO))
    gross_t = q3(sum((ln["gross"] for ln in lines), ZERO))
    colis = 1 if h7 else max(1, min(60, int(gross_t / D(rng.choice([8, 15, 25, 40]))) + rng.randint(0, 3)))
    layout = sp.get("ci_layout_override") or rng.choice(sup["layouts"])
    if proforma and layout in ("CU", "CK"):
        layout = "CG" if sup["lang"] == "en" else rng.choice([x for x in sup["layouts"] if x not in ("CU", "CK")] or ["CA"])
    hs_digits = rng.choice([6, 8, 10, 10, 8]) if sp["attrs"].get("ci_hs", True) else 0
    if sp["attrs"].get("hs6_trap"):
        hs_digits = 6
    ci = {
        "doc_id": doc_id, "kind": "ci", "type": "facture_commerciale",
        "sous_type": "pro_forma" if proforma else "facture",
        "layout": layout, "lang": sup["lang"], "supplier": sup,
        "numero": _ci_number(rng, sup_id, d_ci), "date": d_ci, "devise": devise,
        "acheteur": {"nom": ent["raison_sociale"], "adresse": ent["adresse"], "tva": ent["tva"], "siren": ent["siren"]},
        "eori": ent["eori"] if rng.random() < 0.5 else None,
        "lines": lines, "sub": sub, "total": total, "total_printed": True,
        "incoterm": incoterm, "incoterm_lieu": sup["port"] if incoterm in ("FOB", "FCA", "EXW") else "Lyon" if ctx["client"]["client_id"] == "CL11" else "Le Havre",
        "ref_transport": transport["ref"] if rng.random() < 0.85 or True else None,
        "transport": transport, "net_total": net_t, "gross_total": gross_t, "colis": colis,
        "hs_digits": hs_digits, "hs_style": rng.choice(["dots", "plain", "space", "dot4"]),
        "origin_mode": "line" if rng.random() < 0.8 else "header",
        "carrier_mention": None, "h7": h7,
        "payment_terms": rng.choice(["T/T 30 days", "Net 60", "100% T/T in advance", "L/C at sight"]),
    }
    if ci["origin_mode"] == "header" and len({ln["origin"] for ln in lines}) > 1:
        ci["origin_mode"] = "line"
    return ci


# ---------------------------------------------------------------------------
# Déclaration
# ---------------------------------------------------------------------------

def customs_rate(rng, devise: str, d: date, sens: str) -> D:
    base = bce_rate(devise, d.replace(day=1))
    r = base * D(str(round(1 + rng.uniform(-0.004, 0.004), 5)))
    if sens == "devise_par_eur":
        return q5(r)
    return q5(D(1) / r)


def make_decl(ctx, rng, *, doc_id, cis, lines_sel=None, d_acc: date, decl_mode: str, rate_printed: bool,
              sens: str, autoliq: bool, h7=False, declared_goods_only=False, mrn=None, version=1):
    """cis : factures couvertes ; lines_sel : sous-ensemble de lignes (facture répartie)."""
    sp = ctx["spec"]
    ent = ctx["entity"]
    fwd = ctx["forwarder"]
    ci0 = cis[0]
    devise_ci = ci0["devise"]
    foreign = devise_ci != "EUR"
    rate = None
    if foreign and (rate_printed or decl_mode == "eur"):
        rate = customs_rate(rng, devise_ci, d_acc, sens)
    if foreign and decl_mode == "eur" and not rate_printed:
        rate_hidden = customs_rate(rng, devise_ci, d_acc, "devise_par_eur")
    else:
        rate_hidden = None
    devise_decl = "EUR" if decl_mode == "eur" else devise_ci
    # Lignes couvertes
    all_lines = []
    for ci in cis:
        for ln in ci["lines"]:
            if lines_sel is None or (ci["doc_id"], ln["no"]) in lines_sel:
                all_lines.append((ci, ln))
    # Montants hors lignes (fret, assurance…) répartis au prorata
    goods = sum((ln["amount"] for _, ln in all_lines), ZERO)
    if lines_sel is None and not declared_goods_only:
        total_ccy = sum((ci["total"] for ci in cis), ZERO)
    else:
        total_ccy = goods
    # Regroupement en articles (code + origine)
    groups: dict = {}
    order = []
    for ci, ln in all_lines:
        key = (ln["hs10"], ln["origin"]) if not h7 else (ln["hs10"], ln["origin"], ln["no"], ci["doc_id"])
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append((ci, ln))
    arts = []
    for i, key in enumerate(order, 1):
        lns = [ln for _, ln in groups[key]]
        units = {ln["unit"] for ln in lns}
        amt_ccy = sum((ln["amount"] for ln in lns), ZERO)
        arts.append({"no": i, "hs10": key[0], "origin": key[1], "lines": lns,
                     "refs": [ln["ref"] for ln in lns], "desc": lns[0]["desc_fr"],
                     "amt_goods": amt_ccy, "qty": sum((ln["qty"] for ln in lns), ZERO) if len(units) == 1 else None,
                     "qty_unit": lns[0]["unit"] if len(units) == 1 else None,
                     "net": q3(sum((ln["net"] for ln in lns), ZERO)), "gross": q3(sum((ln["gross"] for ln in lns), ZERO)),
                     "duty": lns[0]["duty"], "ad": lns[0]["ad"], "pref": "100", "regime": "4000",
                     "regime_c": rng.choice(["000", "000", "F15"]) if not h7 else "000"})
    # Montant facturé par article (devise de la déclaration), somme = total déclaré
    dec_ccy = cur_decimals(devise_ci)
    if devise_decl == "EUR" and foreign:
        total_decl = to_eur(total_ccy, rate, sens)
    else:
        total_decl = total_ccy
    acc = ZERO
    for j, a in enumerate(arts):
        share = a["amt_goods"] / goods if goods else D(1) / len(arts)
        if j == len(arts) - 1:
            a["amount"] = total_decl - acc
        else:
            a["amount"] = q2(total_decl * share) if devise_decl == "EUR" or dec_ccy == 2 else qcur(total_decl * share, devise_ci)
            acc += a["amount"]
    # Valeur en EUR (base des droits)
    eur_rate_for_base = None
    if foreign:
        eur_rate_for_base = eur_per_unit(rate, sens) if rate else (D(1) / rate_hidden if rate_hidden else D(1) / bce_rate(devise_ci, d_acc))
    for a in arts:
        if devise_decl == "EUR":
            v_eur = a["amount"]
        else:
            v_eur = q2(a["amount"] * eur_rate_for_base) if foreign else a["amount"]
        adj = D("0")
        if ci0["incoterm"] in ("EXW", "FCA", "FOB") and not h7:
            adj = D(str(round(rng.uniform(0.02, 0.07), 3)))
        a["stat_value"] = q2(v_eur * (1 + adj))
    # Taux imprimé : seulement si rate_printed. En mode « eur » sans taux imprimé, la conversion a bien
    # été faite (taux calculé ci-dessus, aléa consommé à l'identique) mais le taux n'est PAS imprimé
    # (A7 : ordre de grandeur au taux indicatif seulement).
    printed_rate = rate if rate_printed else None
    # Taxations
    taxes = []
    euro_round = sp["attrs"].get("duty_euro_round", False)
    pay_mode_droits = rng.choice(["E", "E", "A"])
    if not h7:
        for a in arts:
            base = a["stat_value"]
            calc = q2(base * a["duty"] / 100)
            m = D(int(calc.to_integral_value(rounding="ROUND_HALF_UP"))) if euro_round else calc
            a00 = {"article": a["no"], "type": "A00", "cat": "droit", "base": base, "base_qty": None, "base_unit": None,
                   "rate": a["duty"], "nature": "ad_valorem", "montant": m, "a_payer": m, "mode": pay_mode_droits}
            taxes.append(a00)
            ad_m = ZERO
            if a["ad"]:
                adm = q2(base * a["ad"] / 100)
                taxes.append({"article": a["no"], "type": "A30", "cat": "autre_taxe", "base": base, "base_qty": None, "base_unit": None,
                              "rate": a["ad"], "nature": "ad_valorem", "montant": adm, "a_payer": adm, "mode": pay_mode_droits})
                ad_m = adm
            vbase = q2(base + m + ad_m)
            vm = q2(vbase * D(20) / 100)
            taxes.append({"article": a["no"], "type": "B00", "cat": "tva", "base": vbase, "base_qty": None, "base_unit": None,
                          "rate": D(20), "nature": "ad_valorem", "montant": vm, "a_payer": ZERO if autoliq else vm,
                          "mode": "G" if autoliq else pay_mode_droits})
    else:
        n = len(arts)
        fm = q2(FORFAIT_UNITAIRE * n)
        taxes.append({"article": None, "type": "FPE", "cat": "forfait_petits_envois", "base": None, "base_qty": D(n),
                      "base_unit": "article", "rate": FORFAIT_UNITAIRE, "nature": "specifique", "montant": fm, "a_payer": fm,
                      "mode": pay_mode_droits})
        tot_val = sum((a["stat_value"] for a in arts), ZERO)
        vbase = q2(tot_val + fm)
        vm = q2(vbase * D(20) / 100)
        taxes.append({"article": None, "type": "B00", "cat": "tva", "base": vbase, "base_qty": None, "base_unit": None,
                      "rate": D(20), "nature": "ad_valorem", "montant": vm, "a_payer": ZERO if autoliq else vm,
                      "mode": "G" if autoliq else pay_mode_droits})
    # Colis par article
    colis_total = sum((ci["colis"] for ci in cis), 0) if lines_sel is None else max(1, int(sum((ci["colis"] for ci in cis), 0) * len(all_lines) / max(1, sum(len(ci["lines"]) for ci in cis))))
    rem = colis_total
    for j, a in enumerate(arts):
        if j == len(arts) - 1:
            a["colis"] = rem
        else:
            c = max(0, min(rem, int(colis_total * (a["gross"] / max(sum((x["gross"] for x in arts), ZERO), D("0.001"))))))
            a["colis"] = c
            rem -= c
    gross_total = q3(sum((a["gross"] for a in arts), ZERO))
    tr = ci0["transport"]
    refs = []
    inv_code = "N325" if ci0["sous_type"] == "pro_forma" else "N380"
    for ci in cis:
        num = ci["numero"]
        if sp["attrs"].get("trunc_ref"):
            digits = "".join(ch for ch in num if ch.isalnum())
            num = digits[-max(6, len(digits) - 3):]
        refs.append({"code": inv_code, "ref": num})
    refs.append({"code": tr["code"], "ref": tr["ref"]})
    if autoliq:
        refs.append({"code": "1008" if not h7 else "FR7", "ref": ent["tva"]})
    dec = {
        "doc_id": doc_id, "kind": "dec", "type": "declaration", "layout": sp["layout"],
        "sous_type": "h7" if h7 and LAYCAP[sp["layout"]]["sous_type"] in ("h1",) else LAYCAP[sp["layout"]]["sous_type"],
        "h7": h7, "mrn": mrn or mrn_fictif(rng, d_acc.year), "lrn": lrn_fictif(rng), "version": version,
        "numero_declaration": f"{d_acc.year % 100}{rng.randint(100000, 999999)}", "date": d_acc,
        "importateur": {"nom": ent["raison_sociale"], "tva": ent["tva"], "eori": ent["eori"]},
        "declarant": {"nom": fwd["nom"], "tva": fwd["tva"]},
        "devise": devise_decl, "montant": total_decl, "rate": printed_rate, "sens": sens if printed_rate else None,
        "devise_taux": devise_ci if printed_rate else None,
        "incoterm": ci0["incoterm"], "incoterm_lieu": ci0["incoterm_lieu"], "pays_exp": ci0["supplier"]["pays"],
        "gross_total": gross_total, "colis_total": colis_total, "n_articles": len(arts),
        "refs": refs, "autoliq": autoliq, "articles": arts, "taxes": taxes, "cis": [ci["doc_id"] for ci in cis],
        "transport": tr, "desig_refs": sp["attrs"].get("desig_refs", False),
    }
    recompute_decl_totals(dec)
    return dec


def recompute_decl_totals(dec, keep_override=True):
    tt: dict = {}
    for t in dec["taxes"]:
        tt[t["type"]] = tt.get(t["type"], ZERO) + t["montant"]
    dec["type_totals"] = tt
    dec["total_droits_taxes"] = q2(sum((t["montant"] for t in dec["taxes"]), ZERO))
    dec["total_a_payer"] = q2(sum((t["a_payer"] for t in dec["taxes"]), ZERO))
    for k, v in (dec.get("overrides") or {}).items():
        if k == "type_totals":
            dec["type_totals"] = {**dec["type_totals"], **v}
        else:
            dec[k] = v


def liquide(dec) -> dict:
    out = {"droit": ZERO, "autre_taxe": ZERO, "tva": ZERO, "forfait_petits_envois": ZERO}
    for t in dec["taxes"]:
        if t["cat"] == "tva" and dec["autoliq"]:
            continue
        out[t["cat"]] += t["a_payer"]
    return out


# ---------------------------------------------------------------------------
# Facture du transitaire
# ---------------------------------------------------------------------------

def _label(fam, nature, rng=None, idx=0):
    lang = fam_lang(fam)
    labs = LABELS[lang][nature]
    return labs[idx % len(labs)]


def ft_line(fam, nature, ht, *, qty=D(1), pu=None, mrn=None, ref_transport=None, libelle=None, vat_rate=None,
            date_debut=None, date_fin=None, base_info=None):
    deb = nature.startswith("debours")
    return {"nature": nature, "libelle": libelle or _label(fam, nature), "qty": D(qty), "pu": pu if pu is not None else ht,
            "ht": ht, "vat_rate": (ZERO if deb else D(20)) if vat_rate is None else vat_rate, "mrn": mrn,
            "ref_transport": ref_transport, "date_debut": date_debut, "date_fin": date_fin, "base_info": base_info}


def faf_amount(grid, base: D) -> D:
    p = poste(grid, "frais_avance_fonds")
    v = q2(D(p["pourcentage"]) * base / 100)
    if p["minimum"] is not None and v < D(p["minimum"]):
        v = D(p["minimum"])
    if p["maximum"] is not None and v > D(p["maximum"]):
        v = D(p["maximum"])
    return v


def faf_base(grid, lines, mrn) -> D:
    p = poste(grid, "frais_avance_fonds")
    tot = ZERO
    for ln in lines:
        if not ln["nature"].startswith("debours") or (mrn is not None and ln["mrn"] not in (mrn, None)):
            continue
        if p["base_pourcentage"] == "debours_hors_tva" and ln["nature"] == "debours_tva":
            continue
        tot += ln["ht"]
    return tot


def make_ft(ctx, rng, *, doc_id, decls, d_ft: date, opts: dict):
    """Facture du transitaire couvrant une ou plusieurs déclarations (lignes rattachées par MRN)."""
    fam = ctx["spec"]["family"]
    grid = ctx["grid"]
    cap = FAMCAP[fam]
    ent = ctx["entity"]
    fwd = ctx["forwarder"]
    lines = []
    for dec in decls:
        mrn = dec["mrn"]
        tref = dec["transport"]["ref"]
        liq = liquide(dec)
        pd = poste(grid, "frais_dedouanement")
        lines.append(ft_line(fam, "frais_dedouanement", D(pd["prix"]), mrn=mrn, ref_transport=tref))
        pl = poste(grid, "frais_ligne_supplementaire")
        extra = max(0, dec["n_articles"] - int(pl["inclus"]))
        if extra > 0:
            lines.append(ft_line(fam, "frais_ligne_supplementaire", q2(D(pl["prix"]) * extra), qty=D(extra), pu=D(pl["prix"]), mrn=mrn))
        # Débours
        if cap.get("combine"):
            tot = liq["droit"] + liq["autre_taxe"] + liq["tva"] + liq["forfait_petits_envois"]
            if tot > 0:
                lines.append(ft_line(fam, "debours_combines", q2(tot), mrn=mrn))
        else:
            if liq["droit"] > 0:
                v = liq["droit"]
                if opts.get("round_trap") and dec["n_articles"] >= 2 and v > 1:
                    v = v - D("0.03")
                lines.append(ft_line(fam, "debours_droits", q2(v), mrn=mrn))
            if liq["autre_taxe"] > 0:
                lines.append(ft_line(fam, "debours_autres_taxes", q2(liq["autre_taxe"]), mrn=mrn))
            if liq["forfait_petits_envois"] > 0:
                ftax = next(t for t in dec["taxes"] if t["cat"] == "forfait_petits_envois")
                base_info = None
                if cap["forfait_base"]:
                    base_info = (ftax["rate"], int(ftax["base_qty"]))
                lines.append(ft_line(fam, "debours_forfait_petits_envois", q2(liq["forfait_petits_envois"]), mrn=mrn,
                                     qty=D(int(ftax["base_qty"])) if base_info else D(1),
                                     pu=ftax["rate"] if base_info else q2(liq["forfait_petits_envois"]), base_info=base_info))
            if liq["tva"] > 0:
                lines.append(ft_line(fam, "debours_tva", q2(liq["tva"]), mrn=mrn))
        lines.append(ft_line(fam, "frais_avance_fonds", ZERO, mrn=mrn))  # calculé à la finalisation
        if opts.get("storage") and cap["storage"]:
            pm = poste(grid, "magasinage")
            days = opts["storage_days"]
            fr = int(pm["franchise_jours"])
            billed = max(0, days - fr)
            d0 = add_days(dec["date"], -days + 1)
            if billed > 0:
                lines.append(ft_line(fam, "magasinage", q2(D(pm["prix"]) * billed), qty=D(billed), pu=D(pm["prix"]), mrn=mrn,
                                     date_debut=d0, date_fin=dec["date"]))
    if opts.get("delivery"):
        p = poste(grid, "transport")
        if p.get("unite_base") == "kg":      # extension 2.1 : tarif au kg (masse brute déclarée, arrondie au kg supérieur)
            kg = _kg(decls)
            lines.append(ft_line(fam, "transport", q2(D(p["prix"]) * kg), qty=kg, pu=D(p["prix"]),
                                 mrn=decls[0]["mrn"] if len(decls) > 1 else None))
        else:
            lines.append(ft_line(fam, "transport", D(p["prix"]), mrn=decls[0]["mrn"] if len(decls) > 1 else None))
    if opts.get("manut") and poste(grid, "manutention"):
        p = poste(grid, "manutention")
        if p.get("unite_base") == "kg":
            kg = _kg(decls)
            lines.append(ft_line(fam, "manutention", q2(D(p["prix"]) * kg), qty=kg, pu=D(p["prix"])))
        else:
            lines.append(ft_line(fam, "manutention", D(p["prix"])))
    if opts.get("surch") and any(p["nature"] == "surcharge" for p in grid["postes"]):
        p = poste(grid, "surcharge")
        lines.append(ft_line(fam, "surcharge", D(p["prix"]), libelle=p["libelles_reconnus"][0]))
    if opts.get("dossier_fee"):
        p = poste(grid, "autre_prestation")
        lines.append(ft_line(fam, "autre_prestation", D(p["prix"])))
    if opts.get("discount"):
        if opts.get("credit_line"):          # extension 2.1 (G15) : ligne d'avoir intégrée au relevé
            amt, lib = opts["credit_line"]
            lines.append(ft_line(fam, "autre_prestation", amt, libelle=lib, pu=amt))
        else:
            lines.append(ft_line(fam, "autre_prestation", D("-10.00"), libelle=REMISE[fam_lang(fam)], pu=D("-10.00")))
    num = ft_number(rng, fam, d_ft)
    ft = {"doc_id": doc_id, "kind": "ft", "type": "facture_transitaire", "family": fam, "lang": ctx["fwd_lang"],
          "numero": num, "date": d_ft, "emetteur": {"nom": fwd["nom"], "tva": fwd["tva"], "adresse": fwd["adresse"]},
          "client": {"nom": ent["raison_sociale"], "tva": ent["tva"], "adresse": ent["adresse"]},
          "refs_mrn": [d["mrn"] for d in decls], "refs_transport": [d["transport"]["ref"] for d in decls],
          "refs_ci": [c for d in decls for c in d["cis"]], "lines": lines, "decls": [d["doc_id"] for d in decls],
          "est_releve": len(decls) > 1 and cap.get("statement", False), "faf_mode": "grid", "faf_overrides": {},
          "total_overrides": {}, "transport_ref_style": opts.get("transport_ref_style", "raw"),
          "title_kind": "facture"}
    return ft


def _kg(decls) -> D:
    tot = sum((d["gross_total"] for d in decls), ZERO)
    return D(int(tot.to_integral_value(rounding="ROUND_CEILING")))


def ft_number(rng, fam, d: date) -> str:
    n = rng.randint(1000, 99999)
    styles = {
        "G1": f"FLT-{d.year}-{n:05d}", "G2": f"PFL/{d.year % 100}/{n:05d}", "G3": f"RG {d.year}-{n:05d}",
        "G4": f"{n}/{d.year}/SI", "G5": f"FT{d.year % 100}-{n:05d}", "G6": f"DMF{d.year}{n:05d}",
        "G7": f"VF-{d.year}-{n:06d}", "G8": f"PTD{d.year % 100}{n:06d}", "G9": f"MDF {n:05d}",
        "G10": f"CCB-INV-{n:05d}", "G11": f"NEB{d.year % 100}{d.month:02d}{n:05d}", "G12": f"SE-{d.year}-{n:05d}",
        "G13": f"FT {d.year}/{n:05d}", "G14": f"FV/{n:05d}/{d.month:02d}/{d.year}", "G15": f"ZP-{d.year % 100}-{n:06d}",
        "G16": f"HTD{d.year}-{n:05d}",
    }
    return styles[fam]


def finalize_ft(ft, grid, decl_by_id):
    """FAF par MRN (sauf surcharge explicite), TVA, totaux. Les totaux imprimés faux (D1) sont
    appliqués après coup via total_overrides."""
    fam = ft["family"]
    for ln in ft["lines"]:
        if ln["nature"] == "frais_avance_fonds":
            if ln.get("fixed"):
                continue
            base = faf_base(grid, ft["lines"], ln["mrn"])
            v = faf_amount(grid, base)
            v = v + ft["faf_overrides"].get(ln["mrn"], ZERO)
            ln["ht"] = v
            ln["pu"] = v
            ln["faf_base"] = base
    ft["lines"] = [ln for ln in ft["lines"] if not (ln["nature"] == "frais_avance_fonds" and ln["ht"] == 0)]
    cap = FAMCAP[fam]
    for ln in ft["lines"]:
        ln["vat"] = q2(ln["ht"] * ln["vat_rate"] / 100)
        ln["ttc"] = ln["ht"] + ln["vat"]
    deb = [ln for ln in ft["lines"] if ln["nature"].startswith("debours")]
    ft["total_debours"] = q2(sum((ln["ht"] for ln in deb), ZERO))
    ft["total_ht"] = q2(sum((ln["ht"] for ln in ft["lines"]), ZERO))
    if cap["line_vat"]:
        ft["total_tva"] = q2(sum((ln["vat"] for ln in ft["lines"]), ZERO))
    else:
        taxable = sum((ln["ht"] for ln in ft["lines"] if ln["vat_rate"] > 0), ZERO)
        ft["total_tva"] = q2(taxable * D(20) / 100) + q2(sum((ln["vat"] for ln in ft["lines"] if ln["vat_rate"] == 0), ZERO))
    ft["total_ttc"] = ft["total_ht"] + ft["total_tva"]
    ft["net"] = ft["total_ttc"]
    ft["calc_totals"] = {k: ft[k] for k in ("total_debours", "total_ht", "total_tva", "total_ttc")}
    for k, v in ft["total_overrides"].items():
        ft[k] = v
    if "total_ttc" in ft["total_overrides"] or "total_ht" in ft["total_overrides"]:
        ft["net"] = ft["total_ttc"]


def make_avoir(ctx, rng, *, doc_id, ft, d_av: date, lines, with_ref=True, motif=""):
    fam = ft["family"]
    for ln in lines:
        ln["vat"] = q2(ln["ht"] * ln["vat_rate"] / 100)
    tht = q2(sum((ln["ht"] for ln in lines), ZERO))
    ttva = q2(sum((ln["vat"] for ln in lines), ZERO))
    n = rng.randint(100, 9999)
    num = {"G1": f"AV-FLT-{n:05d}", "G2": f"CN/{d_av.year % 100}/{n:05d}", "G3": f"GS {d_av.year}-{n:04d}",
           "G4": f"NC {n}/{d_av.year}", "G5": f"AB{d_av.year % 100}-{n:05d}", "G6": f"AVDMF{n:05d}",
           "G9": f"MDF-AV {n:05d}", "G10": f"CCB-CN-{n:05d}", "G11": f"NEBCN{n:06d}", "G12": f"SE-CN-{n:05d}",
           "G13": f"NC {d_av.year}/{n:05d}", "G14": f"FK/{n:05d}/{d_av.year}", "G15": f"ZP-GS-{n:06d}", "G16": f"HTD-AV-{n:05d}"}.get(fam, f"AV-{n}")
    return {"doc_id": doc_id, "kind": "av", "type": "avoir", "family": fam, "lang": ft["lang"], "numero": num, "date": d_av,
            "emetteur": ft["emetteur"], "client": ft["client"], "refs_facture_origine": [ft["numero"]] if with_ref else [],
            "refs_mrn": list(ft["refs_mrn"][:1]), "refs_transport": list(ft["refs_transport"][:1]),
            "lines": lines, "total_ht": tht, "total_tva": ttva, "total_ttc": tht + ttva, "motif": motif,
            "total_overrides": {}, "title_kind": "avoir"}


def transport_for(rng, mode=None):
    mode = mode or rng.choice(["air", "air", "sea", "road"])
    if mode == "air":
        return {"mode": "air", "ref": awb_fictif(rng), "code": "N740"}
    if mode == "sea":
        return {"mode": "sea", "ref": bl_fictif(rng), "code": "N705"}
    return {"mode": "road", "ref": cmr_fictif(rng), "code": "N730"}


def pick_lines(rng, sector: str, n: int, h7: bool, need_ad=False, need_multi_art=False):
    cat = CATALOG[sector]
    prods = rng.sample(cat, min(n, len(cat)))
    if need_ad and not any(p["ad"] for p in prods):
        adp = [p for p in cat if p["ad"]]
        if adp:
            prods[0] = rng.choice(adp)
    if need_ad:
        prods.sort(key=lambda p: 0 if p["ad"] else 1)
    out = []
    for p in prods:
        if h7:
            q = rng.randint(1, 4) if p["unit"] != "KGM" else D(str(rng.choice(["0.5", "1", "2"])))
        elif p["unit"] == "KGM":
            q = rng.choice([50, 120, 250, 500, 1000, 2500, 5000])
        else:
            q = rng.choice([10, 24, 50, 100, 120, 200, 250, 500, 1000, 2000, 5000]) if p["price"] < 5 else rng.choice([2, 5, 10, 12, 20, 24, 50, 100, 150])
        out.append((p, D(q)))
    if need_multi_art and len(out) >= 1:
        # deux lignes de même code et même origine : un article à deux références
        p0 = out[0][0]
        twin = dict(p0)
        twin["ref"] = p0["ref"] + "-B"
        twin["desc"] = {k: v + (" (variant B)" if k == "en" else " (variante B)" if k == "fr" else " B") for k, v in p0["desc"].items()}
        out.insert(1, (twin, out[0][1]))
    return out
