"""Construction du modèle d'un dossier (valeurs vraies) et injection des erreurs (SPEC §19.5).

Les erreurs de famille A sont injectées dans les paramètres de la déclaration avant sa
construction (les montants dérivés restent cohérents entre eux) ; les erreurs B, G1–G3, G6
modifient des valeurs imprimées de la déclaration ; les erreurs C, D, G4, G5 modifient la
facture du transitaire ; les erreurs E portent sur les avoirs ; F sur des paires de dossiers.
"""

from __future__ import annotations

import datetime as dt
import math
from decimal import Decimal

from .clients import grid_poste
from .common import (D, D0, ZERO_DEC_CURRENCIES, is_confusion_variant, make_awb, make_bl, make_lrn, make_mrn, q0,
                     q2, q3, q5, qcur, rng_for, transpose_digits)
from .model import (FT_LABELS, NATURE_OF_CODE, OFF_GRID, Article, CILine, CommercialInvoice, CreditNote, Declaration,
                    FTLine, ForwarderInvoice, Party, SupportDoc, composante_of)
from .refdata import (CARRIERS, OTHER_TAX_PRODUCTS, PRODUCTS, PRODUCTS_BY_KEY, REF_RATES, SELLERS, SELLERS_BY_KEY,
                      SMALL_PARCEL_PRODUCTS)

PORTS = {"CN": ["Shenzhen", "Ningbo", "Shanghai"], "US": ["Los Angeles", "Newark"], "GB": ["Felixstowe"],
         "JP": ["Osaka"], "KR": ["Busan"], "IN": ["Nhava Sheva"], "TR": ["Izmir"], "VN": ["Haiphong"],
         "CH": ["Genève"], "MA": ["Casablanca"], "TN": ["Radès"], "CA": ["Montréal"], "MX": ["Veracruz"],
         "CL": ["San Antonio"], "CO": ["Cartagena"]}
FR_PLACES = ["Le Havre", "Roissy CDG", "Lyon", "Marseille-Fos"]
ALT_ORIGINS = {"CN": ["VN", "MY", "TH"], "US": ["CN", "MX"], "GB": ["CN", "IN"], "CH": ["DE", "IT"], "VN": ["CN"],
               "IN": ["BD"], "TR": ["CN"], "MX": ["US"], "CA": ["US"], "JP": ["CN", "TH"], "KR": ["CN", "VN"],
               "MA": ["ES"], "TN": ["IT"], "CL": ["PE"], "CO": ["EC"]}
UNIT_SUP = {"C62": "p/st", "PR": "pa", "LTR": "l", "MTR": "m"}
VAT_RATE = Decimal("20")
T_DEBOURS_MIN = Decimal("0.05")


class DossierModel:
    def __init__(self, seed, plan, reg):
        self.seed = seed
        self.plan = plan
        self.reg = reg
        self.r = rng_for(seed, "dossier", plan["id"])
        cl = reg.clients[plan["client"]]
        self.entity = cl["entities"][plan["entity_idx"]]
        self.fw = reg.by_template[plan["template"]]
        self.grid = reg.grids[(plan["client"], self.fw.tid)]
        self.cis = []
        self.decls = []          # toutes les déclarations (y compris versions rectifiées)
        self.final_decls = []    # dernière version par expédition
        self.fts = []
        self.avoirs = []
        self.supports = []
        self.nx = []
        self.shipments = []
        self.errors = []
        self.traps = []
        self.links = []
        self.absent = set()
        self.duplicates = []     # (doc_id original, doc_id copie)
        self.tags = []
        self.ext_mrns = set()    # MRN cités appartenant à un autre dossier
        self.ci_by_id = {}
        self.decl_by_id = {}

    # ------------------------------------------------------------------
    def entity_party(self, ent=None):
        e = ent or self.entity
        return Party(e.name, e.addr, "FR", e.vat, e.siren, e.eori)

    def fw_party(self):
        f = self.fw
        return Party(f.name, f.addr, "FR", f.vat, f.siren, None)

    def has(self, ctl):
        return any(e["control"] == ctl for e in self.plan["errors"])

    def perr(self, ctl):
        for e in self.plan["errors"]:
            if e["control"] == ctl:
                return e
        return None

    def add_error(self, control, injection, documents, amount=None, nature="aucun", composante=None, gap=None,
                  thr=None, whole=False, confusion=False, explicit=True, fields=None, description="",
                  eligible=True, consequence_of=None, exclude_totals=False, other_dossiers=None, key=None,
                  depends_on=None):
        e = {"control": control, "injection": injection, "documents": list(documents), "amount": amount,
             "nature": nature, "composante": composante, "gap": gap, "thr": thr, "whole": whole,
             "confusion": confusion, "explicit": explicit, "fields": fields or [], "description": description,
             "eligible": eligible, "consequence_of": consequence_of, "exclude_totals": exclude_totals,
             "other_dossiers": other_dossiers, "key": key, "depends_on": depends_on}
        self.errors.append(e)
        return e

    def add_trap(self, control, max_level, documents, description):
        if any(e["control"] == control for e in self.errors) or self.has(control):
            return
        if any(t["control"] == control and t["documents"] == documents for t in self.traps):
            return
        self.traps.append({"control": control, "max_level": max_level, "documents": list(documents),
                           "description": description})


# ======================================================================
# Factures commerciales
# ======================================================================

def _rate_units_per_eur(dm, cur):
    if cur == "EUR":
        return Decimal(1)
    base = D(REF_RATES[cur])
    f = Decimal(1) + D(dm.r.uniform(-0.02, 0.02)).quantize(Decimal("0.0001"))
    return base * f


def _price_in(cur, usd_price, r):
    if cur == "USD":
        v = D(usd_price)
    elif cur == "EUR":
        v = D(usd_price) / D(REF_RATES["USD"])
    else:
        v = D(usd_price) * D(REF_RATES[cur]) / D(REF_RATES["USD"])
    if cur in ZERO_DEC_CURRENCIES:
        return max(Decimal(1), q0(v))
    return max(Decimal("0.05"), q2(v))


def _hs_print(hs10, style):
    if style == "6dot":
        return f"{hs10[:4]}.{hs10[4:6]}"
    if style == "6plain":
        return hs10[:6]
    if style == "8space":
        return f"{hs10[:4]} {hs10[4:6]} {hs10[6:8]}"
    if style == "8dot":
        return f"{hs10[:4]}.{hs10[4:6]}.{hs10[6:8]}"
    return hs10


def _ci_number(seller_key, idx, k, r):
    styles = ["INV-2026-{i:04d}{k}", "SZ26{i:05d}{k}", "FAC/2026/{i:04d}-{k}", "No.2026{i:04d}{k}",
              "{i:04d}{k}/26", "EXP-26-{i:04d}{k}", "F2026{i:04d}{k}"]
    st = styles[sum(map(ord, seller_key)) % len(styles)]
    return st.format(i=idx, k=k)


def make_ci(dm, k, seller, currency, date, n_lines, small=False, big=False, other_tax=False, distinct_min=1,
            dup_codes=False, value_over=False):
    r = dm.r
    p = dm.plan
    lang = seller.lang
    if seller.country == "CH" and r.random() < 0.3:
        lang = "en"
    numstyle = seller.numstyle
    if lang == "fr" and numstyle == "fr":
        numstyle = r.choice(["fr", "frn", "frs"])
    pool = SMALL_PARCEL_PRODUCTS if small else [x.key for x in PRODUCTS]
    keys = []
    if other_tax:
        keys.append(r.choice(OTHER_TAX_PRODUCTS))
    while len(keys) < max(n_lines, distinct_min):
        kk = r.choice(pool)
        if kk not in keys or (len(keys) >= distinct_min and r.random() < 0.08):
            keys.append(kk)
    if dup_codes and len(keys) >= 2:
        keys[-1] = keys[0]
    hs_style = r.choice(["6dot", "6dot", "8space", "10", "6plain", "8dot"]) if p["ci_codes"] else None
    prefix = "".join(ch for ch in seller.key.upper() if ch.isalpha())[:2]
    lines = []
    for i, key in enumerate(keys):
        prod = PRODUCTS_BY_KEY[key]
        price = _price_in(currency, r.uniform(*prod.price), r)
        if small:
            qty = D(r.choice([1, 1, 1, 2, 2, 3]))
        else:
            target = r.uniform(400, 6500) * (3.5 if big else 1.0)
            unit_usd = (prod.price[0] + prod.price[1]) / 2
            qty = max(1, int(target / unit_usd))
            if prod.unit in ("C62", "PR") and qty > 50:
                qty = int(round(qty, -1))
            qty = D(qty)
        amount = qcur(qty * price, currency)
        origin = seller.country
        if prod.other and prod.other[0] in ("A30", "A35"):
            origin = "CN"
        elif r.random() < 0.1 and seller.country in ALT_ORIGINS:
            origin = r.choice(ALT_ORIGINS[seller.country])
        net = q3(qty * D(prod.kg) * D(r.uniform(0.9, 1.1)))
        if net <= 0:
            net = Decimal("0.010")
        gross = q3(net * D(r.uniform(1.05, 1.22)) + D("0.050"))
        ref = f"{prefix}-{r.randint(1000, 9999)}-{r.choice(['A', 'B', 'BK', 'WH', 'X', 'S', 'M'])}"
        desc = {"en": prod.en, "fr": prod.fr, "es": prod.es}[lang]
        lines.append(CILine(i + 1, ref, desc, key, prod.hs10, _hs_print(prod.hs10, hs_style) if hs_style else None,
                            qty, prod.unit, price, amount, origin, net, gross))
    if small and value_over:
        # G6 par valeur : envoi au-delà du seuil de 150 EUR
        f = Decimal(1)
        tot_eur = sum(l.amount for l in lines) / _rate_units_per_eur(dm, currency)
        if tot_eur < 190:
            f = (Decimal(210) / max(tot_eur, Decimal(1))).quantize(Decimal("0.01"))
        for l in lines:
            l.price = qcur(l.price * f, currency)
            l.amount = qcur(l.qty * l.price, currency)
    elif small:
        tot_eur = sum(l.amount for l in lines) / _rate_units_per_eur(dm, currency)
        if tot_eur > 120:
            f = Decimal(110) / tot_eur
            for l in lines:
                l.price = max(Decimal("0.50"), qcur(l.price * f, currency))
                l.amount = qcur(l.qty * l.price, currency)
    goods = sum((l.amount for l in lines), D0)
    footer = {}
    transport_kind = "bl" if sum(l.gross for l in lines) > 400 else "awb"
    if small:
        transport_kind = "awb"
    freight_trap = p["freight_trap"] and k == 0
    has_freight = freight_trap or (not small and r.random() < 0.33)
    if has_freight:
        footer["fret"] = qcur(goods * D(r.uniform(0.03, 0.09)), currency)
    if not freight_trap and not small:
        if has_freight and r.random() < 0.3:
            footer["assurance"] = qcur(goods * D(r.uniform(0.003, 0.008)), currency)
        if r.random() < 0.08:
            footer["emballage"] = qcur(D(r.uniform(20, 120)) * (_rate_units_per_eur(dm, currency)), currency)
        if r.random() < 0.08:
            footer["remise"] = qcur(goods * D(r.uniform(0.02, 0.05)), currency)
    total = goods + footer.get("fret", D0) + footer.get("assurance", D0) + footer.get("emballage", D0) \
        - footer.get("remise", D0)
    if has_freight:
        inc = ("CIF" if "assurance" in footer else "CFR") if transport_kind == "bl" else \
            ("CIP" if "assurance" in footer else "CPT")
        place = r.choice(FR_PLACES)
    elif small:
        inc = r.choice(["DAP", "EXW", "FCA"])
        place = r.choice(FR_PLACES) if inc == "DAP" else r.choice(PORTS.get(seller.country, ["Origin"]))
    else:
        inc = r.choice(["FOB", "FOB", "FAS"]) if transport_kind == "bl" else r.choice(["FCA", "EXW", "FCA"])
        place = r.choice(PORTS.get(seller.country, ["Origin"]))
    gross_total = sum((l.gross for l in lines), D0)
    net_total = sum((l.net for l in lines), D0)
    packages = max(1, int(math.ceil(float(gross_total) / r.uniform(12, 30))))
    if small:
        packages = 1
    tref = make_awb(r) if transport_kind == "awb" else make_bl(r)
    sous_type = "facture"
    if p["pro_forma"] and k == 0:
        sous_type = "pro_forma"
    elif small and r.random() < 0.4:
        sous_type = "facture_integrateur"
    elif r.random() < 0.04:
        sous_type = "valeur_douane_seulement"
    ship = None
    if p["carrier_trap"] and k == 0:
        ship = r.choice([CARRIERS[0], CARRIERS[1], dm.fw.name])
    elif sous_type == "facture_integrateur":
        ship = CARRIERS[0]
    elif r.random() < 0.5:
        ship = {"awb": "Air freight", "bl": "Sea freight"}[transport_kind]
    total_printed = True
    if not footer and not small and r.random() < 0.05 and not any(
            e["control"] in ("A3", "A4", "A5", "A6", "A7", "F5") for e in p["errors"]) and k == 0:
        total_printed = False
    buyer = dm.entity_party()
    consignee = None
    if r.random() < 0.15 and p["client"] == "CL01":
        others = [e for e in dm.reg.clients["CL01"]["entities"] if e is not dm.entity]
        consignee = dm.entity_party(r.choice(others))
    ci = CommercialInvoice(
        doc_id=f"fc{k + 1}", numero=_ci_number(seller.key, p["idx"], k, r), date=date,
        seller=Party(seller.name, seller.addr, seller.country, seller.vat), buyer=buyer, consignee=consignee,
        currency=currency, language=lang, sous_type=sous_type, lines=lines, goods=goods, footer=footer, total=total,
        total_printed=total_printed, incoterm=inc, incoterm_place=place, transport_ref=tref,
        transport_kind=transport_kind, gross_total=gross_total, net_total=net_total, packages=packages,
        shipping_mode=ship, numstyle=numstyle, fmt="pdf", eori_printed=r.random() < 0.3,
        multipage=len(lines) >= 14, payment_terms=r.choice(["T/T 30 days", "T/T in advance", "60 days net",
                                                          "L/C at sight"]),
        seller_key=seller.key)
    return ci


# ======================================================================
# Déclarations
# ======================================================================

def _rate_print(dm, cur, sens):
    upe = _rate_units_per_eur(dm, cur)
    if sens == "devise_par_eur":
        printed = q5(upe)
        return printed, Decimal(1) / printed
    printed = q5(Decimal(1) / upe)
    return printed, printed


def _conv(amount, eur_per_unit):
    return q2(amount * eur_per_unit)


def _alloc_to(values, target, quant):
    """Répartit `target` proportionnellement à `values`, au quantum près, somme exacte."""
    tot = sum(values, D0)
    if tot == 0:
        out = [D0] * len(values)
        out[-1] = target
        return out
    out = [(v * target / tot).quantize(quant) for v in values]
    out[-1] += target - sum(out, D0)
    return out


def build_declaration(dm, doc_id, ship_lines, cis, decl_cur_mode, rate_sens, layout, date, target_inv_cur,
                      mrn=None, version=1, importer=None, euro_round=False, group_by_code=True, shipment=0,
                      ci_currency=None):
    """ship_lines : [(ci, line)] couverts ; target_inv_cur : montant déclaré dans la devise de la facture."""
    r = dm.r
    p = dm.plan
    cur_inv = ci_currency or cis[0].currency
    rate_printed, eur_per_unit = None, Decimal(1)
    if decl_cur_mode == "eur":
        dcur = "EUR"
    elif decl_cur_mode == "same":
        dcur = cur_inv
        rate_printed, eur_per_unit = _rate_print(dm, cur_inv, rate_sens)
    elif decl_cur_mode == "converted":
        dcur = "EUR"
        rate_printed, eur_per_unit = _rate_print(dm, cur_inv, rate_sens)
    else:  # converted_norate
        dcur = "EUR"
        eur_per_unit = Decimal(1) / _rate_units_per_eur(dm, cur_inv)
    conv_needed = decl_cur_mode in ("converted", "converted_norate")
    quant_inv = Decimal(1) if cur_inv in ZERO_DEC_CURRENCIES else Decimal("0.01")
    # regroupement des lignes en articles
    groups = []
    for ci, l in ship_lines:
        g = None
        if group_by_code:
            g = next((g for g in groups if g["hs10"] == l.hs10), None)
        if g is None:
            g = {"hs10": l.hs10, "lines": [], "cis": []}
            groups.append(g)
        g["lines"].append(l)
        if ci.numero not in g["cis"]:
            g["cis"].append(ci.numero)
    amounts_inv = _alloc_to([sum((l.amount for l in g["lines"]), D0) for g in groups], target_inv_cur, quant_inv)
    if conv_needed:
        total_decl = _conv(target_inv_cur, eur_per_unit)
        art_amounts = _alloc_to(amounts_inv, total_decl, Decimal("0.01"))
    else:
        total_decl = target_inv_cur
        art_amounts = amounts_inv
    packages_total = sum({id(ci): ci.packages for ci, _ in ship_lines}.values()) if len(
        {id(ci) for ci, _ in ship_lines}) > 1 else cis[0].packages
    if p["split_invoice"]:
        packages_total = max(1, int(math.ceil(float(sum(l.gross for _, l in ship_lines)) / 20)))
    pk = _alloc_to([sum((l.gross for l in g["lines"]), D0) for g in groups], D(packages_total), Decimal(1))
    pk = [int(x) for x in pk]
    for i in range(len(pk)):
        if pk[i] < 0:
            pk[-1] += pk[i]
            pk[i] = 0
    articles = []
    for i, g in enumerate(groups):
        prod = PRODUCTS_BY_KEY[g["lines"][0].product]
        desc = prod.fr.upper()
        refs = [l.ref for l in g["lines"]]
        if p["refs_in_designation"]:
            desc = f"{desc} REF {', '.join(refs)}"
        unit = prod.unit
        qsum = sum((l.qty for l in g["lines"]), D0)
        amount = art_amounts[i]
        amount_eur = amount if dcur == "EUR" else _conv(amount, eur_per_unit)
        origin = g["lines"][0].origin
        articles.append(Article(
            no=i + 1, hs10=g["hs10"], desc=desc, origin=origin,
            pref_origin=None, pref_code="100", regime="4000", amount=amount, stat_value=amount_eur,
            net=sum((l.net for l in g["lines"]), D0), gross=sum((l.gross for l in g["lines"]), D0),
            qty_sup=qsum if unit in UNIT_SUP else None, unit_sup=UNIT_SUP.get(unit), packages=pk[i],
            invoice_refs=list(g["cis"]), line_refs=refs, qty_total=qsum))
    mrn = mrn or make_mrn(r, date.year)
    importer = importer or dm.entity_party()
    decl = Declaration(
        doc_id=doc_id, layout=layout, sous_type={"L1": "h1", "L2": "preuve_dedouanement", "L3": "dau_cases",
                                                 "L4": "h7", "X1": "export_xml", "X2": "export_csv"}[layout],
        mrn=mrn, lrn=make_lrn(r), version=version, date=date, importer=importer, declarant=dm.fw_party(),
        currency=dcur, total_invoiced=total_decl, rate_printed=rate_printed,
        rate_sens=rate_sens if rate_printed is not None else None, eur_per_unit=eur_per_unit,
        incoterm=cis[0].incoterm, incoterm_place=cis[0].incoterm_place, pays_exp=cis[0].seller.country,
        gross_total=sum((a.gross for a in articles), D0), packages_total=packages_total, articles=articles,
        taxes=[], doc_refs=[], autoliq=p["autoliq"], euro_round=euro_round, shipment=shipment,
        ci_ids=[ci.doc_id for ci in cis])
    for ci in cis:
        decl.doc_refs.append(("N325" if ci.sous_type == "pro_forma" else "N380", ci.numero))
    tk = cis[0].transport_kind
    decl.doc_refs.append(("N740" if tk == "awb" else "N705", cis[0].transport_ref))
    if decl.autoliq:
        decl.doc_refs.append(("FR7" if layout == "L4" else "1008", importer.vat))
    compute_taxes(dm, decl)
    return decl


def compute_taxes(dm, decl, keep_mp=None):
    r = dm.r
    p = dm.plan
    mp_main = keep_mp or (dm.__dict__.setdefault("_mp_main", r.choice(["E", "E", "E", "A"])))
    paiement = {"E": "differe", "A": "comptant", "G": "autoliquide"}
    taxes = []
    if decl.layout == "L4":
        n = len(decl.articles)
        tot_eur = sum((a.stat_value for a in decl.articles), D0)
        forf = Decimal(3) * n
        taxes.append(Tax(None, "FPE", "forfait_petits_envois", "Droit forfaitaire petits envois", None, D(n),
                         "article", Decimal("3.00"), "specifique", q2(forf), mp_main, paiement[mp_main]))
        base_tva = q2(tot_eur + forf)
        mp_tva = "G" if decl.autoliq else mp_main
        taxes.append(Tax(None, "B00", "tva", "TVA", base_tva, None, None, VAT_RATE, "ad_valorem",
                         q2(base_tva * VAT_RATE / 100), mp_tva, paiement[mp_tva]))
    else:
        for a in decl.articles:
            prod = PRODUCTS_BY_KEY[_product_of(a)]
            base = a.stat_value
            rate = D(prod.duty)
            duty = base * rate / 100
            duty = q0(duty) if decl.euro_round else q2(duty)
            taxes.append(Tax(a.no, "A00", "droit", "Droits de douane", base, None, None, rate, "ad_valorem", duty,
                             mp_main, paiement[mp_main]))
            other_total = D0
            if prod.other and (prod.other[0] == "X01" or a.origin == "CN"):
                code, label, cat, taux, ub = prod.other
                if ub:
                    qb = a.qty_sup or a.net
                    m = q2(qb * D(taux))
                    taxes.append(Tax(a.no, code, cat, label, None, qb, ub, D(taux), "specifique", m, mp_main,
                                     paiement[mp_main]))
                else:
                    m = q2(base * D(taux) / 100)
                    taxes.append(Tax(a.no, code, cat, label, base, None, None, D(taux), "ad_valorem", m, mp_main,
                                     paiement[mp_main]))
                other_total += m
            base_tva = q2(base + duty + other_total)
            mp_tva = "G" if decl.autoliq else mp_main
            taxes.append(Tax(a.no, "B00", "tva", "TVA", base_tva, None, None, VAT_RATE, "ad_valorem",
                             q2(base_tva * VAT_RATE / 100), mp_tva, paiement[mp_tva]))
    decl.taxes = taxes
    recompute_decl_totals(decl)


def _product_of(article):
    for p in PRODUCTS:
        if p.hs10 == article.hs10:
            return p.key
    return PRODUCTS[0].key


def recompute_decl_totals(decl):
    cat = {}
    for t in decl.taxes:
        cat[t.code] = cat.get(t.code, D0) + t.montant
    decl.cat_totals = cat
    decl.total_droits_taxes = sum((t.montant for t in decl.taxes), D0)
    decl.total_a_payer = sum((t.montant for t in decl.taxes if t.paiement != "autoliquide"), D0)
    decl.n_articles_printed = len(decl.articles)


# ======================================================================
# Facture du transitaire
# ======================================================================

def _lbl(code, lang):
    return FT_LABELS[code][lang]


def _marker(template, kind):
    m = {"T1": ("E", "N"), "T2": ("Z", "S"), "T3": ("0", "1"), "T4": ("D", "T"), "T5": ("E", "N"),
         "T6": ("E", "N"), "T7": ("E", "S"), "T8": ("D", "N")}[template]
    return m[0] if kind == "debours" else m[1]


def debours_lines(dm, decl, template, lang, tref):
    lines = []
    liq = decl.liquide()
    mk = _marker(template, "debours")
    if template == "T3":
        tot = sum(liq.values(), D0)
        lines.append(FTLine("debours_combines", "COMBINES", _lbl("COMBINES", lang), Decimal(1), tot, tot, D0, D0, mk,
                            mrn=decl.mrn, ref_transport=tref))
        return lines
    if template == "T2" and decl.layout != "L4":
        for a in decl.articles:
            duty = sum((t.montant for t in decl.taxes if t.article == a.no and t.categorie == "droit"), D0)
            base = next((t.base_montant for t in decl.taxes if t.article == a.no and t.code == "A00"), None)
            lines.append(FTLine("debours_droits", "DROITS", _lbl("DROITS", lang), Decimal(1), duty, duty, D0, D0, mk,
                                mrn=decl.mrn, ref_transport=tref, hs=a.hs10, base_droit=base, article=a.no))
            oth = sum((t.montant for t in decl.taxes if t.article == a.no and t.categorie == "autre_taxe"), D0)
            if oth:
                lines.append(FTLine("debours_autres_taxes", "AUTRES", _lbl("AUTRES", lang), Decimal(1), oth, oth, D0,
                                    D0, mk, mrn=decl.mrn, ref_transport=tref, hs=a.hs10, article=a.no))
            if not decl.autoliq:
                tv = next((t for t in decl.taxes if t.article == a.no and t.categorie == "tva"), None)
                if tv:
                    lines.append(FTLine("debours_tva", "TVA", _lbl("TVA", lang), Decimal(1), tv.montant, tv.montant,
                                        D0, D0, mk, mrn=decl.mrn, ref_transport=tref, hs=a.hs10,
                                        base_tva=tv.base_montant, article=a.no))
        return lines
    if liq["forfait_petits_envois"]:
        n = next(t.base_quantite for t in decl.taxes if t.categorie == "forfait_petits_envois")
        rate = next(t.taux for t in decl.taxes if t.categorie == "forfait_petits_envois")
        lines.append(FTLine("debours_forfait_petits_envois", "FORFAIT", _lbl("FORFAIT", lang), n, rate,
                            liq["forfait_petits_envois"], D0, D0, mk, mrn=decl.mrn, ref_transport=tref,
                            detail=f"{rate} x {n}"))
    if liq["droit"]:
        lines.append(FTLine("debours_droits", "DROITS", _lbl("DROITS", lang), Decimal(1), liq["droit"], liq["droit"],
                            D0, D0, mk, mrn=decl.mrn, ref_transport=tref))
    if liq["autre_taxe"]:
        codes = sorted({t.code for t in decl.taxes if t.categorie == "autre_taxe"})
        lines.append(FTLine("debours_autres_taxes", "AUTRES", _lbl("AUTRES", lang), Decimal(1), liq["autre_taxe"],
                            liq["autre_taxe"], D0, D0, mk, mrn=decl.mrn, ref_transport=tref,
                            detail=" + ".join(codes)))
    if liq["tva"]:
        lines.append(FTLine("debours_tva", "TVA", _lbl("TVA", lang), Decimal(1), liq["tva"], liq["tva"], D0, D0, mk,
                            mrn=decl.mrn, ref_transport=tref))
    return lines


def _presta(dm, code, lang, template, qty, price, mrn=None, tref=None, detail="", nature=None, libelle=None):
    ht = q2(qty * price)
    tva = q2(ht * VAT_RATE / 100)
    return FTLine(nature or NATURE_OF_CODE[code], code, libelle or _lbl(code, lang), D(qty), price, ht, VAT_RATE, tva,
                  _marker(template, "presta"), mrn=mrn, ref_transport=tref, detail=detail)


def faf_amount(grid, base):
    pst = grid_poste(grid, "AVANCE_FONDS")
    pct = D(pst["pourcentage"])
    v = q2(pct * base / 100)
    if pst["minimum"] is not None:
        v = max(v, D(pst["minimum"]))
    if pst["maximum"] is not None:
        v = min(v, D(pst["maximum"]))
    return v


def faf_base(grid, debours_lines_):
    pst = grid_poste(grid, "AVANCE_FONDS")
    if pst["base_pourcentage"] == "debours_hors_tva":
        return sum((l.montant_ht for l in debours_lines_ if l.nature != "debours_tva"), D0)
    return sum((l.montant_ht for l in debours_lines_), D0)


def prestation_lines(dm, decl, template, lang, tref, first=True, n_articles=None):
    g = dm.grid
    p = dm.plan
    r = dm.r
    out = []
    dd = grid_poste(g, "DEDOUANEMENT")
    out.append(_presta(dm, "DEDOUANEMENT", lang, template, 1, D(dd["prix"]), mrn=decl.mrn, tref=tref))
    ls = grid_poste(g, "LIGNE_SUP")
    n_art = n_articles if n_articles is not None else len(decl.articles)
    q = max(0, n_art - ls["inclus"])
    if q > 0:
        out.append(_presta(dm, "LIGNE_SUP", lang, template, q, D(ls["prix"]), mrn=decl.mrn, tref=tref,
                           detail=f"{n_art} art. - {ls['inclus']} inclus"))
    if first:
        od = grid_poste(g, "OUVERTURE_DOSSIER")
        if od and dm.__dict__.setdefault("_ouv", r.random() < 0.6):
            out.append(_presta(dm, "OUVERTURE_DOSSIER", lang, template, 1, D(od["prix"]), mrn=decl.mrn, tref=tref))
        if p["storage"]:
            mg = grid_poste(g, "MAGASINAGE")
            fr = mg["franchise_jours"]
            total_days = fr + r.randint(2, 7)
            fin = decl.date
            debut = fin - dt.timedelta(days=total_days - 1)
            days = total_days - fr
            l = _presta(dm, "MAGASINAGE", lang, template, days, D(mg["prix"]), mrn=decl.mrn, tref=tref,
                        detail=f"{debut.isoformat()} > {fin.isoformat()}")
            l.date_debut, l.date_fin = debut, fin
            out.append(l)
        if p["transport"]:
            tp = grid_poste(g, "TRANSPORT")
            out.append(_presta(dm, "TRANSPORT", lang, template, 1, D(tp["prix"]), mrn=decl.mrn, tref=tref))
            if p["surcharges"]:
                fu = grid_poste(g, "SURCHARGE_CARBURANT")
                amt = q2(D(tp["prix"]) * D(fu["pourcentage"]) / 100)
                out.append(_presta(dm, "SURCHARGE_CARBURANT", lang, template, 1, amt, mrn=decl.mrn, tref=tref,
                                   detail=f"{fu['pourcentage']} %"))
        if p["surcharges"]:
            su = grid_poste(g, "SURCHARGE_SURETE")
            out.append(_presta(dm, "SURCHARGE_SURETE", lang, template, 1, D(su["prix"]), mrn=decl.mrn, tref=tref))
        if dm.__dict__.setdefault("_manut", r.random() < 0.3):
            mn = grid_poste(g, "MANUTENTION")
            out.append(_presta(dm, "MANUTENTION", lang, template, 1, D(mn["prix"]), mrn=decl.mrn, tref=tref))
    return out


def make_faf_line(dm, template, lang, deb_lines, mrn=None, tref=None):
    base = faf_base(dm.grid, deb_lines)
    amt = faf_amount(dm.grid, base)
    pst = grid_poste(dm.grid, "AVANCE_FONDS")
    l = _presta(dm, "AVANCE_FONDS", lang, template, 1, amt, mrn=mrn, tref=tref,
                detail=f"{pst['pourcentage']} % x {base} (min {pst['minimum']})")
    l.base_droit = None
    return l


def ft_number(dm, k=0, prefix=None):
    p = dm.plan
    seq = 10000 + p["idx"] * 7 + k
    pre = prefix or dm.fw.prefix
    if dm.fw.template == "T4":
        return f"{pre}-2026-{p['idx']:04d}{k}"
    return f"{pre}-26{seq:05d}"


# ======================================================================
# Construction complète
# ======================================================================

def build_core(seed, plan, reg, plans_by_id, _depth=0):
    dm = DossierModel(seed, plan, reg)
    r = dm.r
    p = plan
    seller0 = SELLERS_BY_KEY[p["seller"]]
    base_date = dt.date.fromisoformat(p["base_date"])
    layout = p["layout"]
    small = layout == "L4"

    def perr_opt(ctl):
        return dm.perr(ctl)

    g6 = perr_opt("G6")
    g6_by_date = bool(g6) and r.random() < 0.5
    if g6 and g6_by_date:
        base_date = dt.date(2026, 6, r.randint(3, 24))
    a14 = perr_opt("A14")

    # ---------------------------------------------------------- expéditions
    n_ship = p["n_decl"] if p["template"] == "T4" else 1
    n_art_min = p["min_articles"]
    if p["split_invoice"]:
        n_art_min = max(n_art_min, 2)
    for s in range(n_ship):
        if s == 0:
            seller, cur, mode = seller0, p["currency"], p["decl_mode"]
            sdate = base_date
        else:
            seller = r.choice([x for x in SELLERS if "EUR" in x.currencies or "USD" in x.currencies])
            cur = "EUR" if "EUR" in seller.currencies and r.random() < 0.5 else (
                "USD" if "USD" in seller.currencies else "EUR")
            mode = "eur" if cur == "EUR" else r.choice(["same", "converted"])
            sdate = base_date + dt.timedelta(days=r.randint(1, 20))
        n_cis = p["n_ci"] if s == 0 else 1
        cis = []
        for c in range(n_cis):
            kci = len(dm.cis)
            if small:
                nl = r.randint(max(1, n_art_min), max(n_art_min, 4))
            else:
                nl = r.randint(max(2, n_art_min), max(n_art_min, 7))
                if r.random() < 0.07 and s == 0 and c == 0:
                    nl = r.randint(15, 24)
            ci = make_ci(dm, kci, seller, cur, sdate - dt.timedelta(days=c * r.randint(0, 3)), nl, small=small,
                         big=p.get("big_debours", False) and s == 0, other_tax=p["autres_taxes"] and s == 0 and c == 0,
                         distinct_min=n_art_min if s == 0 else 1, dup_codes=dm.has("G3"),
                         value_over=bool(g6) and not g6_by_date)
            if c > 0:
                # deuxième facture : même vendeur, même transport, même incoterm
                ci.transport_ref = cis[0].transport_ref
                ci.transport_kind = cis[0].transport_kind
                ci.incoterm, ci.incoterm_place = cis[0].incoterm, cis[0].incoterm_place
                ci.footer = {}
                ci.total = ci.goods
                ci.total_printed = True
            if p["ci_format"] != "pdf" and s == 0 and c == 0:
                ci.fmt = p["ci_format"]
            cis.append(ci)
            dm.cis.append(ci)
            dm.ci_by_id[ci.doc_id] = ci
        dm.shipments.append({"cis": cis, "mode": mode, "decls": []})

    # ---------------------------------------------------------- déclarations
    dk = 0
    for s, sh in enumerate(dm.shipments):
        cis = sh["cis"]
        mode = sh["mode"]
        ddate = max(ci.date for ci in cis) + dt.timedelta(days=r.randint(1, 4) if small else r.randint(2, 10))
        if s == 0 and a14:
            ddate = cis[0].date - dt.timedelta(days=r.randint(4, 25))
        lines_all = [(ci, l) for ci in cis for l in ci.lines]
        targets = []
        if p["split_invoice"] and s == 0:
            ci = cis[0]
            kk = max(1, len(ci.lines) // 2)
            parts = [lines_all[:kk], lines_all[kk:]]
            # montant de chaque partie : lignes + pied réparti
            quant = Decimal(1) if ci.currency in ZERO_DEC_CURRENCIES else Decimal("0.01")
            vals = _alloc_to([sum(l.amount for _, l in part) for part in parts], ci.total, quant)
            targets = list(zip(parts, vals))
        else:
            tgt = sum((ci.total for ci in cis), D0)
            if p["freight_trap"] and s == 0:
                tgt = sum((ci.goods for ci in cis), D0)
            targets = [(lines_all, tgt)]
        for j, (part, tgt) in enumerate(targets):
            dk += 1
            doc_id = f"dec{dk}"
            dd = ddate + dt.timedelta(days=j * r.randint(3, 9))
            importer = None
            if p["rectificative"] and s == 0:
                v1 = build_declaration(dm, doc_id, part, cis, mode, p["rate_sens"], layout, dd,
                                       qcur(tgt * Decimal("1.06"), cis[0].currency),
                                       euro_round=p["euro_round"], shipment=s)
                dm.decls.append(v1)
                dm.decl_by_id[v1.doc_id] = v1
                dk += 1
                doc_id = f"dec{dk}"
                dd = dd + dt.timedelta(days=r.randint(3, 9))
                mrn2 = v1.mrn[:15] + "".join(r.choice("ABCDEFGHJKLMNPQRSTUVWXYZ23456789") for _ in range(3))
                d = build_declaration(dm, doc_id, part, cis, mode, p["rate_sens"], layout, dd, tgt, mrn=mrn2,
                                      version=2, euro_round=p["euro_round"], shipment=s)
                d.lrn = v1.lrn
                # le taux imprimé reste celui de la première version
                sh["v1"] = v1
                dm.tags.append("version_rectificative")
            else:
                d = build_declaration(dm, doc_id, part, cis, mode, p["rate_sens"], layout, dd, tgt,
                                      euro_round=p["euro_round"], shipment=s,
                                      group_by_code=not dm.has("G3"))
            dm.decls.append(d)
            dm.final_decls.append(d)
            dm.decl_by_id[d.doc_id] = d
            sh["decls"].append(d)

    # ---------------------------------------------------------- injections A / B / G sur la déclaration
    from . import inject
    inject.inject_declaration(dm)

    # ---------------------------------------------------------- facture(s) transitaire
    build_forwarder_invoices(dm)
    inject.inject_forwarder(dm)

    # ---------------------------------------------------------- croisements F
    if p.get("fpair") and p["fpair"]["role"] == "B" and _depth == 0:
        partner = build_core(seed, plans_by_id[p["fpair"]["partner"]], reg, plans_by_id, _depth=1)
        inject.inject_fpair(dm, partner)

    # ---------------------------------------------------------- avoirs
    inject.build_avoirs(dm)

    # ---------------------------------------------------------- documents support et non exploitables
    build_supports(dm)
    inject.inject_p_and_f1(dm)
    return dm


def build_forwarder_invoices(dm):
    p = dm.plan
    r = dm.r
    tpl = p["template"]
    lang = dm.fw.lang
    client = dm.entity_party()
    decls = dm.final_decls
    last_decl_date = max(d.date for d in decls)
    fdate = last_decl_date + dt.timedelta(days=r.randint(1, 9))
    trefs = []
    for sh in dm.shipments:
        tr = sh["cis"][0].transport_ref
        if tr not in trefs:
            trefs.append(tr)
    if tpl == "T4":
        fdate = dt.date(last_decl_date.year, last_decl_date.month, 28) if last_decl_date.day <= 28 else last_decl_date
        lines = []
        for i, d in enumerate(decls):
            tref = dm.shipments[d.shipment]["cis"][0].transport_ref
            deb = debours_lines(dm, d, tpl, lang, tref)
            pre = prestation_lines(dm, d, tpl, lang, tref, first=(i == 0))
            pre.insert(1, make_faf_line(dm, tpl, lang, deb, mrn=d.mrn, tref=tref))
            lines += deb + pre
        ft = ForwarderInvoice("ft1", "releve", tpl, ft_number(dm), fdate, dm.fw_party(), client, trefs,
                              [d.mrn for d in decls], [ci.numero for ci in dm.cis], lines, lang, est_releve=True,
                              decl_ids=[d.doc_id for d in decls])
        ft.period = (dt.date(fdate.year, fdate.month, 1), fdate)
        ft.recompute()
        dm.fts.append(ft)
        return
    deb_all, pre_all = [], []
    for i, d in enumerate(decls):
        tref = dm.shipments[d.shipment]["cis"][0].transport_ref
        deb_all += debours_lines(dm, d, tpl, lang, tref)
        pre_all += prestation_lines(dm, d, tpl, lang, tref, first=(i == 0))
    mrns = [d.mrn for d in decls]
    mrn_for_faf = decls[0].mrn if len(decls) == 1 else None
    if tpl == "T5":
        ft_d = ForwarderInvoice("ft1", "debours", tpl, ft_number(dm, 0, "FD"), fdate, dm.fw_party(), client, trefs,
                                mrns, [ci.numero for ci in dm.cis], deb_all, lang, decl_ids=[d.doc_id for d in decls])
        faf = make_faf_line(dm, tpl, lang, deb_all, mrn=mrn_for_faf)
        pre_all.insert(1, faf)
        ft_p = ForwarderInvoice("ft2", "prestations", tpl, ft_number(dm, 1, "FP"), fdate, dm.fw_party(), client, trefs,
                                mrns, [ci.numero for ci in dm.cis], pre_all, lang, decl_ids=[d.doc_id for d in decls])
        ft_d.total_debours_printed = True
        ft_d.recompute()
        ft_p.recompute()
        dm.fts += [ft_d, ft_p]
        return
    compl = p["complementaire"] and len(decls) == 1
    compl_lines = []
    if compl:
        tv = [l for l in deb_all if l.nature == "debours_tva"]
        au = [l for l in deb_all if l.nature == "debours_autres_taxes"]
        compl_lines = tv or au
        if not compl_lines:
            compl = False
        else:
            deb_all = [l for l in deb_all if l not in compl_lines]
    faf = make_faf_line(dm, tpl, lang, deb_all + compl_lines, mrn=mrn_for_faf)
    pre_all.insert(1, faf)
    ft = ForwarderInvoice("ft1", "facture", tpl, ft_number(dm), fdate, dm.fw_party(), client, trefs, mrns,
                          [ci.numero for ci in dm.cis], deb_all + pre_all, lang, decl_ids=[d.doc_id for d in decls])
    ft.total_debours_printed = tpl != "T3"
    if tpl == "T1" and r.random() < 0.12:
        ft.acompte = Decimal(r.choice(["100.00", "150.00", "200.00"]))
    ft.recompute()
    dm.fts.append(ft)
    if compl:
        ft2 = ForwarderInvoice("ft2", "complementaire", tpl, ft_number(dm, 1), fdate + dt.timedelta(days=r.randint(5, 20)),
                               dm.fw_party(), client, trefs, mrns, [ci.numero for ci in dm.cis], compl_lines, lang,
                               decl_ids=[d.doc_id for d in decls])
        ft2.dossier_ref = ft.numero
        ft2.recompute()
        dm.fts.append(ft2)
        dm.tags.append("facture_complementaire")


# ======================================================================
# Documents support
# ======================================================================

def build_supports(dm):
    p = dm.plan
    r = dm.r
    k = 0
    for s, sh in enumerate(dm.shipments):
        ci = sh["cis"][0]
        if p["awb"] or (p["merged"] and p["template"] != "T6" and not p["packing"]):
            k += 1
            dm.supports.append(SupportDoc(f"sup{k}", "titre_transport", "en", {
                "kind": ci.transport_kind, "ref": ci.transport_ref, "shipper": ci.seller, "consignee": ci.buyer,
                "packages": sum(c.packages for c in sh["cis"]) if len(sh["cis"]) > 1 else ci.packages,
                "gross": sum((c.gross_total for c in sh["cis"]), D0), "agent": dm.fw.name,
                "date": ci.date + dt.timedelta(days=1), "ci": ci.doc_id, "shipment": s,
                "origin_port": r.choice(PORTS.get(ci.seller.country, ["Origin"])),
                "dest": r.choice(FR_PLACES)}))
        if p["packing"] and s == 0:
            k += 1
            dm.supports.append(SupportDoc(f"sup{k}", "liste_colisage", ci.language, {
                "ci": ci.doc_id, "ref": ci.numero, "lines": ci.lines, "packages": ci.packages,
                "gross": ci.gross_total, "net": ci.net_total, "date": ci.date, "seller": ci.seller,
                "buyer": ci.buyer, "transport_ref": ci.transport_ref}))
    if p["eml"]:
        k += 1
        dm.supports.append(SupportDoc(f"sup{k}", "courriel", "fr", {
            "from": "contact@fournisseur-demo.invalid", "to": "import@client-demo.invalid",
            "subject": f"Documents envoi {dm.cis[0].numero if dm.cis else ''}",
            "date": dm.cis[0].date if dm.cis else dt.date(2026, 7, 1), "ci": dm.cis[0].doc_id if dm.cis else None}))
        dm.tags.append("courriel")
