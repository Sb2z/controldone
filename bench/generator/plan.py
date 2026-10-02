"""Planification globale et déterministe du corpus (SPEC §19.6).

La planification est faite pour l'ensemble des dossiers (dev + holdout) AVANT toute génération,
à partir de (seed, count) uniquement. Générer un split seul reproduit donc exactement le même
plan : le split holdout peut être généré plus tard sans changer le split dev.
"""

from __future__ import annotations

import datetime as dt
import random
from collections import Counter

from .common import rng_for, split_of
from .refdata import CLIENTS, SELLERS

TEMPLATES = ["T1", "T2", "T3", "T4", "T5", "T6", "T7", "T8"]
LAYOUTS = ["L1", "L2", "L3", "L4", "X1", "X2"]
DEGRADATION_SHARES = [("d0", 0.40), ("d1", 0.25), ("d2", 0.20), ("d3", 0.15)]

CONTROLS = (
    [f"A{i}" for i in range(1, 16)] + [f"B{i}" for i in range(1, 6)] + [f"C{i}" for i in range(1, 9)]
    + [f"D{i}" for i in range(1, 10)] + [f"E{i}" for i in range(1, 7)] + [f"F{i}" for i in range(1, 6)]
    + [f"G{i}" for i in range(1, 7)]
)

# Annexe A, colonne « Certain ? »
CERTAIN_ELIGIBLE = {"A1", "A3", "A4", "A5", "A6", "B1", "B2", "B3", "B4", "C1", "C2", "C3", "C4", "C5", "C6", "C8",
                    "D1", "D2", "D3", "D4", "D5", "D6", "D7", "D9", "F3", "G1", "G2", "G4", "G5"}

INJECTIONS = {
    "A1": ["entite_groupe_differente", "entite_tierce"], "A2": ["ref_facture_absente"], "A3": ["devise_differente"],
    "A4": ["valeur_modifiee", "valeur_transposee"], "A5": ["conversion_fausse"], "A6": ["non_converti"],
    "A7": ["ordre_grandeur_incoherent"], "A8": ["incoterm_different"], "A9": ["quantite_differente"],
    "A10": ["masse_differente"], "A11": ["colis_different"], "A12": ["origine_differente"],
    "A13": ["code_sh6_different"], "A14": ["date_anterieure"], "A15": ["reference_produit_absente"],
    "B1": ["taxe_base_taux_incoherente"], "B2": ["somme_taxes_incoherente"], "B3": ["somme_articles_incoherente"],
    "B4": ["nette_superieure_brute"], "B5": ["somme_colis_incoherente"],
    "C1": ["droits_surfactures"], "C2": ["autres_taxes_surfacturees"], "C3": ["tva_refacturee_malgre_autoliquidation"],
    "C4": ["tva_surfacturee"], "C5": ["debours_combines_surfactures"], "C6": ["faf_sur_excedent"],
    "C7": ["mrn_cite_inconnu"], "C8": ["client_facture_different"],
    "D1": ["total_faux"], "D2": ["ligne_hors_grille"], "D3": ["prix_superieur_grille"], "D4": ["faf_hors_grille"],
    "D5": ["ligne_doublee"], "D6": ["magasinage_excessif"], "D7": ["surcharge_non_prevue"], "D8": ["tva_sur_debours"],
    "D9": ["lignes_supplementaires_excessives"],
    "E1": ["avoir_sans_reference"], "E2": ["avoir_excessif"], "E3": ["avoir_double"], "E4": ["avoir_total_faux"],
    "E5": ["avoir_sans_ecart"], "E6": ["avoir_partiel"],
    "F1": ["fichier_double"], "F2": ["numero_reutilise"], "F3": ["mrn_refacture_deux_fois"],
    "F4": ["prestation_refacturee"], "F5": ["facture_sur_deux_declarations"],
    "G1": ["forfait_base_x_taux_faux"], "G2": ["forfait_base_differente"], "G3": ["forfait_codes_distincts"],
    "G4": ["forfait_surfacture"], "G5": ["forfait_unites_au_lieu_articles"], "G6": ["forfait_hors_periode"],
}

GROUPS = {
    "A3": "valeur", "A4": "valeur", "A5": "valeur", "A6": "valeur", "A7": "valeur", "F5": "valeur",
    "A14": "date", "G6": "date",
    "C1": "cdebours", "C2": "cdebours", "C3": "cdebours", "C4": "cdebours", "C5": "cdebours",
    "G1": "g123", "G2": "g123", "G3": "g123", "G4": "g45", "G5": "g45",
    "E1": "avoir", "E2": "avoir", "E5": "avoir", "E6": "avoir",
}

PDF_LAYOUTS = {"L1", "L2", "L3", "L4"}
DETAIL_LAYOUTS = {"L1", "L3", "X1", "X2"}
FPAIR_TEMPLATES = {"T1", "T2", "T3", "T7", "T8"}


def _alloc(n: int, shares: list) -> list:
    raw = [(k, s * n) for k, s in shares]
    base = {k: int(v) for k, v in raw}
    rest = n - sum(base.values())
    order = sorted(raw, key=lambda kv: -(kv[1] - int(kv[1])))
    for k, _ in order[:rest]:
        base[k] += 1
    out = []
    for k, _ in shares:
        out += [k] * base[k]
    return out


def _compat(p: dict, ctl: str) -> bool:
    lay, tpl = p["layout"], p["template"]
    if p["p_error"]:
        return False
    if ctl in p["controls"]:
        return False
    g = GROUPS.get(ctl)
    if g and g in p["groups"]:
        return False
    foreign = p["currency"] != "EUR"
    l4 = lay == "L4"
    if ctl.startswith("G"):
        if not l4:
            return False
        if ctl in ("G4", "G5") and tpl in ("T3",):
            return False
        return True
    if ctl in ("A1", "A8", "A12", "B1", "B2"):
        return True
    if ctl == "A2":
        return not p["trunc_ref"]
    if ctl == "A3":
        return not p["split_invoice"] and not p["freight_trap"] and p["decl_mode"] in ("same", "eur")
    if ctl == "A4":
        return p["decl_mode"] in ("same", "eur") and not p["freight_trap"] and not p["split_invoice"]
    if ctl == "A5":
        return p["decl_mode"] == "converted" and not p["split_invoice"]
    if ctl == "A6":
        return foreign and p["decl_mode"] in ("converted", "same") and not p["split_invoice"] \
            and p["currency"] not in ("JPY", "KRW")
    if ctl == "A7":
        return p["decl_mode"] == "converted_norate"
    if ctl in ("A9",):
        return lay in DETAIL_LAYOUTS
    if ctl in ("A10", "A11"):
        return lay != "L4"
    if ctl == "A13":
        return p["ci_codes"]
    if ctl == "A14":
        return not p["pro_forma"]
    if ctl == "A15":
        return lay in DETAIL_LAYOUTS
    if ctl == "B3":
        return lay in ("L1", "L2", "L3", "X1", "X2")
    if ctl in ("B4", "B5"):
        return lay in DETAIL_LAYOUTS
    if ctl in ("C1", "C2", "C4"):
        if tpl == "T3":
            return False
        if ctl == "C4" and p["autoliq"]:
            return False
        if "D4" in p["controls"]:
            return False
        return True
    if ctl == "C3":
        return tpl != "T3" and p["autoliq"] and "D4" not in p["controls"]
    if ctl == "C5":
        return tpl == "T3" and "D4" not in p["controls"]
    if ctl == "C6":
        return False  # planifié avec une erreur de débours (voir _plan_c6)
    if ctl in ("C7", "C8", "D2", "D3", "D5", "D6", "D7"):
        return True
    if ctl == "D1":
        return tpl != "T7"
    if ctl == "D4":
        return "cdebours" not in p["groups"] and "C6" not in p["controls"]
    if ctl == "D8":
        return tpl in ("T1", "T5", "T6", "T8")
    if ctl == "D9":
        return lay in ("L1", "L2", "L3", "X1", "X2")
    if ctl in ("E1", "E2", "E5"):
        return True
    if ctl in ("E3", "E4"):
        return True
    if ctl == "E6":
        return True
    if ctl == "F1":
        return True
    if ctl == "F5":
        return p["split_invoice"] and p["decl_mode"] in ("same", "eur")
    return False


def _add_error(p: dict, ctl: str, rng: random.Random, **opts):
    inj = INJECTIONS[ctl]
    choice = inj[0] if len(inj) == 1 else rng.choice(inj)
    if ctl == "A1":
        choice = "entite_groupe_differente" if p["client"] == "CL01" and rng.random() < 0.7 else "entite_tierce"
    e = {"control": ctl, "injection": choice}
    e.update(opts)
    p["errors"].append(e)
    p["controls"].append(ctl)
    g = GROUPS.get(ctl)
    if g:
        p["groups"].append(g)
    # effets sur la composition
    if ctl == "C2":
        p["autres_taxes"] = True
    if ctl == "D6":
        p["storage"] = True
    if ctl == "D7":
        p["transport"] = True
    if ctl == "D9":
        p["min_articles"] = max(p["min_articles"], 6)
    if ctl in ("B4", "B5"):
        p["min_articles"] = max(p["min_articles"], 2)
    if ctl == "A15":
        p["refs_in_designation"] = True
    if ctl == "A13":
        p["ci_codes"] = True
    if ctl.startswith("E"):
        p["avoir"] = True
    if ctl == "G3":
        p["min_articles"] = max(p["min_articles"], 3)
    return e


def build_plan(seed: int, count: int) -> list:
    ids = [f"BX{i:04d}" for i in range(1, count + 1)]
    plans = []
    for idx, did in enumerate(ids):
        plans.append({"id": did, "idx": idx + 1, "split": split_of(did)})

    for split in ("dev", "holdout"):
        sub = [p for p in plans if p["split"] == split]
        _assign_structure(seed, split, sub)
        _assign_formats(seed, split, sub)

    from .clients import build_registry
    from .refdata import TEMPLATE_TO_FORWARDER
    reg = build_registry(seed)

    def hors_grille(p):
        g = reg.grids[(p["client"], TEMPLATE_TO_FORWARDER[p["template"]])]
        return g["prestations_hors_grille"]

    for split in ("dev", "holdout"):
        sub = [p for p in plans if p["split"] == split]
        _assign_errors(seed, split, sub, hors_grille)

    for p in plans:
        p["controls"] = sorted(set(p["controls"]))
        p["groups"] = sorted(set(p["groups"]))
    return plans


# ---------------------------------------------------------------------------
# Structure : gabarit, mise en page, dégradation, client, devise, scénarios
# ---------------------------------------------------------------------------

def _assign_formats(seed: int, split: str, sub: list):
    """Formats de facture commerciale répartis exactement : UBL 5 %, CII 4 %, XLSX 6 %."""
    r = rng_for(seed, "plan-formats", split)
    n = len(sub)
    cands = [p for p in sub if p["layout"] != "L4"]
    r.shuffle(cands)
    k_ubl, k_cii, k_x = round(0.05 * n), round(0.04 * n), round(0.065 * n)
    for p in cands[:k_ubl]:
        p["ci_format"] = "ubl"
    for p in cands[k_ubl:k_ubl + k_cii]:
        p["ci_format"] = "cii"
    for p in cands[k_ubl + k_cii:k_ubl + k_cii + k_x]:
        p["ci_format"] = "xlsx"


def _assign_structure(seed: int, split: str, sub: list):
    n = len(sub)
    r = rng_for(seed, "plan-structure", split)
    n_l4 = max(6, round(0.09 * n))
    others = n - n_l4
    lay = ["L4"] * n_l4
    for i, l in enumerate(["L1", "L2", "L3", "X1", "X2"]):
        lay += [l] * (others // 5 + (1 if i < others % 5 else 0))
    r.shuffle(lay)
    tpl = [TEMPLATES[i % 8] for i in range(n)]
    r.shuffle(tpl)
    # réparation des incompatibilités gabarit/mise en page
    def bad(t, l):
        return (t == "T6" and l in ("X1", "X2")) or (t == "T4" and l == "L4")
    for _ in range(50):
        changed = False
        for i in range(n):
            if bad(tpl[i], lay[i]):
                for j in range(n):
                    if not bad(tpl[j], lay[i]) and not bad(tpl[i], lay[j]):
                        tpl[i], tpl[j] = tpl[j], tpl[i]
                        changed = True
                        break
        if not changed:
            break
    deg = _alloc(n, DEGRADATION_SHARES)
    r.shuffle(deg)

    base = dt.date(2026, 1, 12)
    for i, p in enumerate(sub):
        pr = rng_for(seed, "plan-dossier", p["id"])
        p["layout"] = lay[i]
        p["template"] = tpl[i]
        p["degradation"] = deg[i]
        cands = [c["client_id"] for c in CLIENTS if p["template"] in c["templates"]]
        if p["layout"] == "L4" and "CL04" in cands:
            p["client"] = "CL04"
        else:
            p["client"] = pr.choice(cands)
        p["entity_idx"] = pr.choice([0, 0, 1, 2]) if p["client"] == "CL01" else 0
        # date de base (facture commerciale)
        if p["layout"] == "L4":
            p["base_date"] = (dt.date(2026, 7, 3) + dt.timedelta(days=pr.randint(0, 70))).isoformat()
        else:
            p["base_date"] = (base + dt.timedelta(days=pr.randint(0, 235))).isoformat()
        # devise
        roll = pr.random()
        if p["layout"] == "L4":
            sellers = [s for s in SELLERS if s.country in ("CN", "US", "GB", "VN", "TR", "IN")]
        else:
            sellers = SELLERS
        if roll < 0.06 and p["layout"] != "L4":
            cur = pr.choice(["JPY", "KRW"])
            seller = next(s for s in SELLERS if cur in s.currencies)
        elif roll < 0.55:
            choices = [(s, c) for s in sellers for c in s.currencies if c not in ("EUR", "JPY", "KRW")]
            seller, cur = pr.choice(choices)
        else:
            choices = [s for s in sellers if "EUR" in s.currencies]
            seller = pr.choice(choices)
            cur = "EUR"
        p["seller"] = seller.key
        p["currency"] = cur
        if cur == "EUR":
            p["decl_mode"] = "eur"
        else:
            m = pr.random()
            if p["layout"] in ("L2", "L4") and m < 0.45:
                p["decl_mode"] = "converted_norate"
            elif m < 0.55:
                p["decl_mode"] = "same"
            else:
                p["decl_mode"] = "converted"
        p["rate_sens"] = pr.choice(["devise_par_eur", "eur_par_devise"])
        p["autoliq"] = pr.random() < (0.5 if p["layout"] == "L4" else 0.44)
        p["merged"] = p["template"] == "T6" or pr.random() < 0.22
        p["n_ci"] = 1
        p["split_invoice"] = False
        p["n_decl"] = 1
        if p["template"] == "T4":
            p["n_decl"] = pr.choice([3, 3, 4, 4, 5, 6, 8])
        elif p["layout"] != "L4":
            x = pr.random()
            if x < 0.15:
                p["n_ci"] = 2
            elif x < 0.25 and p["template"] not in ("T5",):
                p["split_invoice"] = True
                p["n_decl"] = 2
        p["avoir"] = False
        p["eml"] = pr.random() < 0.06
        p["packing"] = pr.random() < 0.4
        p["awb"] = pr.random() < 0.55
        p["autres_taxes"] = p["layout"] != "L4" and pr.random() < 0.14
        p["storage"] = pr.random() < 0.25
        p["transport"] = pr.random() < 0.55
        p["surcharges"] = pr.random() < 0.35
        p["rectificative"] = (p["template"] not in ("T4", "T6") and not p["split_invoice"]
                              and p["layout"] in ("L1", "L3", "X1") and pr.random() < 0.12)
        p["complementaire"] = (p["template"] in ("T1", "T2", "T8") and p["n_decl"] == 1 and pr.random() < 0.16)
        p["refs_in_designation"] = p["layout"] in DETAIL_LAYOUTS and pr.random() < 0.25
        p["ci_codes"] = pr.random() < 0.88
        p["pro_forma"] = pr.random() < 0.06
        p["carrier_trap"] = pr.random() < 0.10
        p["freight_trap"] = (p["decl_mode"] in ("same", "eur") and not p["split_invoice"] and p["n_ci"] == 1
                             and pr.random() < 0.06)
        p["round_trap"] = p["template"] != "T3" and pr.random() < 0.08
        p["trunc_ref"] = pr.random() < 0.07
        p["euro_round"] = p["layout"] in ("L1", "L3", "X2") and pr.random() < 0.18
        p["ci_format"] = "pdf"
        p["min_articles"] = 1
        p["p_error"] = None
        p["clean"] = False
        p["errors"] = []
        p["controls"] = []
        p["groups"] = []
        p["fpair"] = None


# ---------------------------------------------------------------------------
# Erreurs
# ---------------------------------------------------------------------------

TARGET = {"dev": 5, "holdout": 2}
TARGET_OVERRIDE = {
    "C5": {"dev": 4, "holdout": 2}, "C6": {"dev": 3, "holdout": 2}, "E5": {"dev": 3, "holdout": 2},
    "E6": {"dev": 4, "holdout": 2}, "G3": {"dev": 4, "holdout": 2}, "G4": {"dev": 4, "holdout": 2},
    "C7": {"dev": 4, "holdout": 2}, "A4": {"dev": 6, "holdout": 3}, "C1": {"dev": 6, "holdout": 2},
    "D3": {"dev": 6, "holdout": 2}, "C2": {"dev": 6, "holdout": 2}, "C4": {"dev": 6, "holdout": 2}, "E2": {"dev": 6, "holdout": 2},
    "E5": {"dev": 8, "holdout": 3}, "E6": {"dev": 6, "holdout": 2}, "E1": {"dev": 8, "holdout": 3},
}


def _assign_errors(seed: int, split: str, sub: list, hors_grille=None):
    r = rng_for(seed, "plan-errors", split)
    n = len(sub)
    order = list(sub)
    r.shuffle(order)

    # 1) erreurs P (documents manquants / non exploitables)
    p_targets = {"dev": [("P1", "facture_manquante")] * 3 + [("P1", "declaration_manquante")] * 3
                 + [("P2", "faux_document_facture")] * 5,
                 "holdout": [("P1", "facture_manquante"), ("P1", "declaration_manquante"),
                             ("P1", "facture_manquante"), ("P2", "faux_document_facture"),
                             ("P2", "faux_document_facture")]}[split]
    pool = [p for p in order if p["layout"] not in ("L4",) and p["template"] not in ("T4", "T6")
            and not p["split_invoice"] and p["n_ci"] == 1 and not p["rectificative"]]
    for (ctl, inj), p in zip(p_targets, pool):
        p["p_error"] = inj
        p["errors"].append({"control": ctl, "injection": inj})
        p["controls"].append(ctl)

    # 2) paires F2/F3/F4 (dossier B plus récent, même client, même transitaire, même split)
    f_needs = {"dev": ["F2", "F2", "F2", "F2", "F3", "F3", "F3", "F3", "F4", "F4", "F4", "F4", "F2"],
               "holdout": ["F2", "F2", "F3", "F3", "F4", "F4"]}[split]
    used_b = set()
    for k, ctl in enumerate(f_needs):
        bs = [p for p in order if not p["p_error"] and p["template"] in FPAIR_TEMPLATES and p["id"] not in used_b
              and p["layout"] != "L4" and p["n_decl"] == 1 and p["fpair"] is None]
        if not bs:
            continue
        b = bs[(k * 7) % len(bs)]
        As = [p for p in order if p is not b and not p["p_error"] and p["fpair"] is None and p["n_decl"] == 1
              and p["template"] in FPAIR_TEMPLATES and p["layout"] != "L4" and p["id"] not in used_b]
        if not As:
            continue
        a = As[(k * 11) % len(As)]
        b["client"] = a["client"]
        b["template"] = a["template"]
        b["entity_idx"] = a["entity_idx"]
        if b["layout"] in ("X1", "X2") and b["template"] == "T6":
            b["template"] = "T1"
        ad = dt.date.fromisoformat(a["base_date"])
        bd = ad + dt.timedelta(days=r.randint(18, 50))
        if bd > dt.date(2026, 9, 20):
            ad = dt.date(2026, 7, 1)
            a["base_date"] = ad.isoformat()
            bd = ad + dt.timedelta(days=r.randint(18, 50))
        b["base_date"] = bd.isoformat()
        a["fpair"] = {"role": "A", "partner": b["id"]}
        b["fpair"] = {"role": "B", "partner": a["id"], "kind": ctl}
        b["complementaire"] = False
        a["complementaire"] = False
        used_b.add(b["id"])
        used_b.add(a["id"])
        _add_error(b, ctl, r, partner=a["id"])
        a["round_trap"] = False

    # 3) dossiers sans erreur (≥ 25 %) : choisis hors L4 en holdout et hors dossiers déjà marqués
    clean_target = round(0.29 * n)
    cands = [p for p in order if not p["errors"] and not (split == "holdout" and p["layout"] == "L4")
             and not (p["fpair"] and p["fpair"]["role"] == "B")]
    # garder assez de dossiers L4 non propres pour la famille G
    l4_dev = [p for p in cands if p["layout"] == "L4"]
    keep_l4 = 12 if split == "dev" else 99
    skip = set(x["id"] for x in l4_dev[: keep_l4])
    cands = [p for p in cands if p["id"] not in skip]
    for p in cands[:clean_target]:
        p["clean"] = True

    def pick(ctl: str, prefer_certain: bool, extra=None):
        cands = [p for p in order if not p["clean"] and _compat(p, ctl) and (extra is None or extra(p))]
        if not cands:
            return None
        def key(p):
            k_deg = 0 if (not prefer_certain or p["degradation"] in ("d0", "d1")) else 1
            k_grid = 0
            if prefer_certain and ctl in ("D2",) and hors_grille is not None:
                k_grid = 0 if hors_grille(p) == "interdites" else 1
            return (k_grid, k_deg, len(p["errors"]), sub_rank[p["id"]])
        cands.sort(key=key)
        return cands[0]

    sub_rank = {p["id"]: i for i, p in enumerate(order)}

    # 4) contrôles G en premier (contraints aux L4), puis E, C6, puis le reste
    seq = ["G1", "G2", "G3", "G4", "G5", "G6", "E6", "E1", "E2", "E5", "E3", "E4", "C6", "F5"] + \
          [c for c in CONTROLS if c not in ("G1", "G2", "G3", "G4", "G5", "G6", "E6", "E1", "E2", "E5", "E3", "E4",
                                            "C6", "F5", "F2", "F3", "F4")]
    for ctl in seq:
        tgt = TARGET_OVERRIDE.get(ctl, TARGET)[split]
        have = sum(1 for p in sub for e in p["errors"] if e["control"] == ctl)
        for k in range(have, tgt):
            prefer = ctl in CERTAIN_ELIGIBLE and k < (3 if split == "dev" else 1)
            if ctl == "C6":
                p = pick("C1", prefer, extra=lambda q: q["template"] != "T3") or pick("C4", prefer)
                if p is None:
                    continue
                main = "C1" if _compat(p, "C1") else ("C4" if _compat(p, "C4") else "C3")
                _add_error(p, main, r, big=True)
                p["errors"].append({"control": "C6", "injection": "faf_sur_excedent", "via": main})
                p["controls"].append("C6")
                p["big_debours"] = True
                continue
            if ctl in ("E3", "E4"):
                p = pick(ctl, False, extra=lambda q: q["avoir"]) or pick(ctl, False)
                if p is None:
                    continue
                _add_error(p, ctl, r)
                continue
            p = pick(ctl, prefer)
            if p is not None and prefer:
                p.setdefault("strong", []).append(ctl)
                if ctl == "D7":
                    p["transport"] = True
                    p["surcharges"] = True
            if p is None and ctl == "F5":
                cands = [q for q in order if not q["clean"] and not q["p_error"] and q["n_decl"] == 1
                         and q["n_ci"] == 1 and q["template"] not in ("T4", "T5") and q["layout"] != "L4"
                         and q["decl_mode"] in ("same", "eur") and "valeur" not in q["groups"]
                         and not q["fpair"] and not q["rectificative"]]
                if cands:
                    p = cands[0]
                    p["split_invoice"] = True
                    p["n_decl"] = 2
                    p["complementaire"] = False
            if p is None:
                continue
            if ctl == "E6":
                if "D3" not in p["controls"]:
                    _add_error(p, "D3", r, for_avoir=True)
                _add_error(p, "E6", r, target="D3")
                continue
            _add_error(p, ctl, r)
