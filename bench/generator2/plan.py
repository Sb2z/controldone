"""Planification du corpus : répartition des injections sur les dossiers, puis choix des attributs
(client, transitaire/famille, présentation de déclaration, dégradation, scénarios).

La planification couvre TOUS les dossiers (dev et holdout) et ne dépend pas du split demandé :
générer `--split holdout` plus tard redonne exactement les mêmes dossiers.
"""

from __future__ import annotations

from .model import FAMCAP, LAYCAP
from .util import rng_for, split_of
from .world import CLIENT_FORWARDERS, CLIENT_SUPPLIERS, SUPPLIERS_BY_ID

CONTROLES = ([f"A{i}" for i in range(1, 16)] + [f"B{i}" for i in range(1, 6)] + [f"C{i}" for i in range(1, 9)]
             + [f"D{i}" for i in range(1, 10)] + [f"E{i}" for i in range(1, 7)] + [f"F{i}" for i in range(1, 6)]
             + [f"G{i}" for i in range(1, 7)])

H1 = {"kind": {"h1"}}
H7 = {"kind": {"h7"}}
FT = {"has_ft": {True}}
SIMPLE = {"structure": {"simple"}}

# code d'injection -> contrôle principal, exigences, groupes exclusifs
INJ = {
    "entite_groupe_differente": ("A1", {**H1, "client": {"CL11", "CL14"}}, {"imp"}),
    "entite_tierce": ("A1", {**H1}, {"imp"}),
    "ref_facture_absente": ("A2", {**H1, "trunc_ref": {False}}, {"refs"}),
    "devise_differente": ("A3", {**H1, **SIMPLE, "foreign": {True}, "decl_mode": {"same"}}, {"val"}),
    "valeur_transposee": ("A4", {**H1, **SIMPLE, "decl_mode": {"same"}, "freight_trap": {False}}, {"val"}),
    "valeur_modifiee": ("A4", {**H1, **SIMPLE, "decl_mode": {"same"}, "freight_trap": {False}}, {"val"}),
    "conversion_fausse": ("A5", {**H1, **SIMPLE, "foreign": {True}, "decl_mode": {"eur"}, "rate_printed": {True}, "freight_trap": {False}}, {"val"}),
    "non_converti": ("A6", {**H1, **SIMPLE, "foreign": {True}, "decl_mode": {"eur"}, "rate_printed": {True}, "freight_trap": {False}}, {"val"}),
    "ordre_grandeur_incoherent": ("A7", {**H1, **SIMPLE, "foreign": {True}, "decl_mode": {"eur"}, "rate_printed": {False}, "freight_trap": {False}}, {"val"}),
    "incoterm_different": ("A8", {**H1}, {"inc"}),
    "quantite_differente": ("A9", {**H1, **SIMPLE, "lay_qty": {True}}, {"qty"}),
    "masse_differente": ("A10", {**H1, **SIMPLE}, {"mass"}),
    "colis_different": ("A11", {**H1, **SIMPLE}, {"colis"}),
    "origine_differente": ("A12", {**H1, **SIMPLE, "ci_hs": {True}, "origin_line": {True}}, {"orig"}),
    "code_sh6_different": ("A13", {**H1, **SIMPLE, "ci_hs": {True}}, {"hs"}),
    "date_anterieure": ("A14", {**H1, "proforma": {False}}, {"date"}),
    "reference_produit_absente": ("A15", {**H1, **SIMPLE, "desig_refs": {True}, "multi_art": {True}}, {"desig"}),
    "taxe_base_taux_incoherente": ("B1", {**H1}, {"tax"}),
    "somme_taxes_incoherente": ("B2", {**H1}, {"tax"}),
    "somme_articles_incoherente": ("B3", {**H1, **SIMPLE}, {"val"}),
    "nette_superieure_brute": ("B4", {**H1, **SIMPLE}, {"mass"}),
    "colis_articles_incoherents": ("B5", {**H1, **SIMPLE, "lay_colis_art": {True}}, {"colis"}),
    "droits_surfactures": ("C1", {**H1, **FT, "cap_ventile": {True}}, {"deb_droit"}),
    "autres_taxes_surfacturees": ("C2", {**H1, **FT, "cap_ventile": {True}, "need_ad": {True}, "foreign": {True}}, {"deb_autre"}),
    "tva_refacturee_malgre_autoliquidation": ("C3", {**H1, **FT, "cap_ventile": {True}, "autoliq": {True}}, {"deb_tva"}),
    "tva_surfacturee": ("C4", {**H1, **FT, "cap_ventile": {True}, "autoliq": {False}}, {"deb_tva"}),
    "debours_combines_surfactures": ("C5", {**H1, **FT, "cap_combine": {True}}, {"deb_comb"}),
    "faf_sur_excedent": ("C6", {**H1, **FT, "cap_ventile": {True}}, {"deb_droit", "faf"}),
    "mrn_cite_inconnu": ("C7", {**H1, **FT}, {"mrnref"}),
    "client_facture_different": ("C8", {**H1, **FT}, {"cli"}),
    "total_faux": ("D1", {**H1, **FT}, {"tot"}),
    "ligne_hors_grille": ("D2", {**H1, **FT}, {"d2"}),
    "prix_superieur_grille": ("D3", {**H1, **FT}, {"dedou"}),
    "faf_hors_grille": ("D4", {**H1, **FT}, {"faf"}),
    "ligne_doublee": ("D5", {**H1, **FT}, {"dup"}),
    "magasinage_excessif": ("D6", {**H1, **FT, "cap_storage": {True}}, {"stor"}),
    "surcharge_non_prevue": ("D7", {**H1, **FT}, {"surch"}),
    "tva_sur_debours": ("D8", {**H1, **FT, "cap_line_vat_debours": {True}}, {"vatdeb"}),
    "lignes_supplementaires_excessives": ("D9", {**H1, **FT}, {"ligsup"}),
    "avoir_sans_reference": ("E1", {**H1, **FT, "cap_avoir": {True}}, {"avoir", "dedou"}),
    "avoir_excessif": ("E2", {**H1, **FT, "cap_avoir": {True}}, {"avoir"}),
    "avoir_double": ("E3", {**H1, **FT, "cap_avoir": {True}}, {"avoir", "dedou"}),
    "avoir_total_faux": ("E4", {**H1, **FT, "cap_avoir": {True}}, {"avoir", "dedou"}),
    "avoir_sans_ecart": ("E5", {**H1, **FT, "cap_avoir": {True}}, {"avoir"}),
    "avoir_partiel": ("E6", {**H1, **FT, "cap_avoir": {True}, "cap_ventile": {True}}, {"avoir", "deb_droit"}),
    "fichier_double": ("F1", {**H1}, {"dupfile"}),
    "numero_reutilise": ("F2", {**H1, **FT}, {"ftnum"}),
    "mrn_refacture_deux_fois": ("F3", {**H1, **FT, "cap_ventile": {True}}, {"ft2"}),
    "prestation_refacturee": ("F4", {**H1, **FT}, {"ft2"}),
    "facture_sur_deux_declarations": ("F5", {**H1, **SIMPLE, "foreign": {False}}, {"val", "ci"}),
    "forfait_base_x_taux_faux": ("G1", {**H7}, {"fdecl"}),
    "forfait_base_differente": ("G2", {**H7}, {"fdecl", "fcodes"}),
    "forfait_codes_distincts": ("G3", {**H7}, {"fcodes"}),
    "forfait_surfacture": ("G4", {**H7, **FT, "cap_ventile": {True}}, {"fft"}),
    "forfait_unites_au_lieu_articles": ("G5", {**H7, **FT, "cap_forfait_base": {True}}, {"fft"}),
    "forfait_hors_periode": ("G6", {**H7}, {"fdate"}),
    "facture_manquante": ("P1", {**H1}, {"P"}),
    "declaration_manquante": ("P1", {**H1}, {"P"}),
    "faux_document_facture": ("P2", {**H1}, {"P"}),
}

CODES_PAR_CONTROLE: dict = {}
for _code, (_c, _r, _g) in INJ.items():
    CODES_PAR_CONTROLE.setdefault(_c, []).append(_code)

PAIRS = {"numero_reutilise", "mrn_refacture_deux_fois", "facture_sur_deux_declarations"}
EXCLUSIVE = {"facture_manquante", "declaration_manquante", "faux_document_facture"}

# Cible : erreurs par contrôle et par split (avant les erreurs induites)
TARGET = {"dev": 5, "holdout": 2}
TARGET_EXTRA = {"holdout": {"C6", "E5", "G5", "F3", "F5", "A15", "D8"}}
# Contrôles éligibles à « ecart_certain » (Annexe A) : les premières erreurs de chacun sont placées
# dans des dossiers peu dégradés (d0/d1) pour garantir au moins 3 erreurs attendues « ecart_certain ».
CERTAIN_ELIGIBLE = {"A1", "A3", "A4", "A5", "A6", "B1", "B2", "B3", "B4", "C1", "C2", "C3", "C4", "C5", "C6", "C8",
                    "D1", "D2", "D3", "D4", "D5", "D6", "D7", "D9", "F3", "G1", "G2", "G4", "G5"}
CERTAIN_FRIENDLY = {"dev": 4, "holdout": 1}
P_TARGET = {"dev": 2, "holdout": 1}

LAYOUTS = list(LAYCAP)


def _merge(req: dict, new: dict):
    out = {k: set(v) for k, v in req.items()}
    for k, v in new.items():
        if k in out:
            inter = out[k] & set(v)
            if not inter:
                return None
            out[k] = inter
        else:
            out[k] = set(v)
    return out


def resolve(req: dict, rng):
    """Choisit (client, famille, layout) compatibles ; None si impossible."""
    clients = sorted(req.get("client", {"CL11", "CL12", "CL13", "CL14"}))
    kind = next(iter(req["kind"])) if "kind" in req else None
    opts = []
    for cid in clients:
        if kind == "h7" and cid == "CL12":
            continue
        if "need_ad" in req and not any(SUPPLIERS_BY_ID[s]["pays"] == "CN" for s in CLIENT_SUPPLIERS[cid]):
            continue
        fams = CLIENT_FORWARDERS[cid]
        if "family" in req:
            fams = [f for f in fams if f in req["family"]]
        for fam in fams:
            cap = FAMCAP[fam]
            ok = True
            for k, v in req.items():
                if k.startswith("cap_"):
                    if bool(cap.get(k[4:], False)) not in v:
                        ok = False
            if kind == "h7" and fam in ("G2",):
                ok = False
            if not ok:
                continue
            for lay in LAYOUTS:
                lc = LAYCAP[lay]
                if any(k.startswith("lay_") and bool(lc.get(k[4:], False)) not in v for k, v in req.items()):
                    continue
                if "layout" in req and lay not in req["layout"]:
                    continue
                if kind == "h7" and lay == "M2":
                    continue
                opts.append((cid, fam, lay))
    if not opts:
        return None
    return opts


def plan_corpus(seed: int, count: int, prefix: str = "GX", all_holdout: bool = False,
                per_control: int | None = None) -> list[dict]:
    """prefix : préfixe des identifiants (GX = corpus_g2) ; all_holdout : tous les dossiers en holdout
    (jeu d'évaluation vierge), sinon règle sha256 % 5 de §19.2."""
    ids = [f"{prefix}{i:04d}" for i in range(1, count + 1)]
    sof = (lambda _d: "holdout") if all_holdout else split_of
    rng = rng_for(seed, "plan")
    slots = {d: {"inj": [], "req": {}, "grps": set(), "partner_of": [], "role": None} for d in ids}
    by_split = {"dev": [d for d in ids if sof(d) == "dev"], "holdout": [d for d in ids if sof(d) == "holdout"]}
    clean = set()
    for s, pool in by_split.items():
        p = list(pool)
        rng.shuffle(p)
        n_clean = max(2, int(len(p) * 0.20))
        clean.update(p[:n_clean])

    # Tâches : (split, code)
    tasks = []
    for s in ("dev", "holdout"):
        if not by_split[s]:
            continue
        for ctrl in CONTROLES:
            n = (per_control or TARGET[s]) + (1 if ctrl in TARGET_EXTRA.get(s, set()) else 0)
            codes = CODES_PAR_CONTROLE[ctrl]
            for k in range(n):
                tasks.append((s, codes[k % len(codes)], k))
        for k in range(P_TARGET[s]):
            tasks.append((s, ["facture_manquante", "declaration_manquante"][k % 2], k))
            tasks.append((s, "faux_document_facture", k))

    def contrainte(code):
        req = INJ[code][1]
        return -(len(req) + (5 if code in PAIRS else 0) + (3 if code in EXCLUSIVE else 0) + (4 if "kind" in req and "h7" in req["kind"] else 0))

    rng.shuffle(tasks)
    tasks.sort(key=lambda t: contrainte(t[1]))
    maxn = {"dev": 3, "holdout": 4}

    def try_assign(did, code, extra_req=None):
        sl = slots[did]
        ctrl, req, grps = INJ[code]
        if sl["grps"] & grps or (code in EXCLUSIVE and sl["inj"]) or ("P" in sl["grps"]):
            return False
        if sl["inj"] and any(c in EXCLUSIVE for c in sl["inj"]):
            return False
        m = _merge(sl["req"], req)
        if m is None:
            return False
        if extra_req:
            m = _merge(m, extra_req)
            if m is None:
                return False
        if resolve(m, rng) is None:
            return False
        sl["req"] = m
        sl["grps"] |= grps
        sl["inj"].append(code)
        return True

    for s, code, k in tasks:
        nf = CERTAIN_FRIENDLY[s] if per_control is None else max(1, per_control - 1)
        extra = {"deg_ok": {True}} if (INJ[code][0] in CERTAIN_ELIGIBLE and k < nf) else None
        pool = [d for d in by_split[s] if d not in clean]
        cand = [d for d in pool if len(slots[d]["inj"]) < maxn[s] and not (code in EXCLUSIVE and slots[d]["inj"])]
        rng.shuffle(cand)
        cand.sort(key=lambda d: (len(slots[d]["inj"]) + len(slots[d]["partner_of"]),))
        done = False
        for d in cand:
            if code in PAIRS:
                # dossier partenaire A (même split, même client/transitaire) qui porte la première occurrence
                partners = [p for p in by_split[s] if p != d and not any(c in EXCLUSIVE for c in slots[p]["inj"])
                            and not slots[p]["partner_of"] and slots[p]["role"] is None]
                rng.shuffle(partners)
                ok = False
                for p in partners:
                    snapshot = ({k: set(v) for k, v in slots[d]["req"].items()}, set(slots[d]["grps"]), list(slots[d]["inj"]))
                    if not try_assign(d, code, extra):
                        break
                    # le partenaire partage client et famille ; F5 : facture en EUR, structure simple
                    preq = {"kind": {"h1"}, "has_ft": {True}, **(extra or {})}
                    if code == "facture_sur_deux_declarations":
                        preq.update({"foreign": {False}, "structure": {"simple"}})
                        if "val" in slots[p]["grps"]:
                            slots[d]["req"], slots[d]["grps"], slots[d]["inj"] = snapshot
                            continue
                    m = _merge(slots[p]["req"], preq)
                    if m is not None:
                        common = _merge(m, {k: v for k, v in slots[d]["req"].items() if k in ("client",)})
                    else:
                        common = None
                    opts_d = resolve(slots[d]["req"], rng)
                    opts_p = resolve(common, rng) if common is not None else None
                    pairs_ok = []
                    if opts_d and opts_p:
                        sd = {(c, f) for c, f, _ in opts_d}
                        sp = {(c, f) for c, f, _ in opts_p}
                        pairs_ok = sorted(sd & sp)
                    if not pairs_ok:
                        slots[d]["req"], slots[d]["grps"], slots[d]["inj"] = snapshot
                        continue
                    cid, fam = rng.choice(pairs_ok)
                    slots[d]["req"]["client"] = {cid}
                    slots[d]["req"]["family"] = {fam}
                    common["client"] = {cid}
                    common["family"] = {fam}
                    slots[p]["req"] = common
                    slots[p]["role"] = "partner"
                    slots[d]["partner_of"].append((code, p))
                    ok = True
                    break
                if ok:
                    done = True
                    break
            else:
                if try_assign(d, code, extra):
                    done = True
                    break
        if not done:
            # en dernier recours : un dossier « propre » du même split
            for d in [x for x in by_split[s] if x in clean and not slots[x]["inj"] and slots[x]["role"] is None]:
                if code not in PAIRS and try_assign(d, code, extra):
                    clean.discard(d)
                    done = True
                    break
        if not done:
            raise RuntimeError(f"Impossible de placer {code} dans {s}")

    specs = []
    for d in ids:
        sl = slots[d]
        r = rng_for(seed, "attrs", d)
        specs.append(choose_attrs(d, sl, r, clean, sof(d)))
    return specs


def choose_attrs(did: str, sl: dict, rng, clean: set, split: str) -> dict:
    req = sl["req"]
    inj = sl["inj"]
    kind = next(iter(req["kind"])) if "kind" in req else ("h7" if rng.random() < 0.10 else "h1")
    req = {**req, "kind": {kind}}
    opts = resolve(req, rng)
    # poids : préférer la diversité des familles et des présentations
    cid, fam, lay = rng.choice(opts)
    if kind == "h7" and "family" not in req:
        h7opts = [o for o in opts if o[1] == "G11"]
        if h7opts and rng.random() < 0.6:
            cid, fam, lay = rng.choice(h7opts)

    def pick(key, default):
        if key in req:
            return sorted(req[key], key=str)[0] if len(req[key]) == 1 else rng.choice(sorted(req[key], key=str))
        return default

    foreign = pick("foreign", rng.random() < 0.55)
    decl_mode = pick("decl_mode", rng.choice(["same", "same", "eur"]) if foreign else "same")
    if not foreign:
        decl_mode = "same"
    rate_printed = pick("rate_printed", True if decl_mode == "eur" else (rng.random() < 0.85))
    if decl_mode == "eur" and "rate_printed" not in req:
        rate_printed = rng.random() < 0.88
    structure = pick("structure", rng.choices(["simple", "multi_ci", "split_decl"], [0.80, 0.10, 0.10])[0] if kind == "h1" else "simple")
    if fam == "G2" and kind == "h1" and "structure" not in req:
        structure = "statement"
    attrs = {
        "foreign": foreign, "decl_mode": decl_mode, "rate_printed": rate_printed,
        "sens": rng.choice(["devise_par_eur", "devise_par_eur", "eur_par_devise"]),
        "autoliq": pick("autoliq", rng.random() < 0.42),
        "has_ft": pick("has_ft", rng.random() < 0.93),
        "structure": structure,
        "proforma": pick("proforma", rng.random() < 0.08),
        "freight_trap": pick("freight_trap", (rng.random() < 0.10) and not any(INJ[c][0] in ("A4", "A5", "A6", "A7", "A3", "B3", "F5") for c in inj)),
        "desig_refs": pick("desig_refs", rng.random() < 0.5),
        "multi_art": pick("multi_art", rng.random() < 0.15),
        "ci_hs": pick("ci_hs", rng.random() < 0.88),
        "origin_line": pick("origin_line", True),
        "trunc_ref": pick("trunc_ref", rng.random() < 0.10),
        "need_ad": pick("need_ad", rng.random() < 0.10),
        "duty_euro_round": rng.random() < 0.08,
        "rectif": rng.random() < 0.06 and kind == "h1" and structure == "simple" and not any(INJ[c][0][0] in "BC" or c in ("fichier_double",) for c in inj),
        "complementary": rng.random() < 0.06 and kind == "h1" and fam not in ("G2",) and not any(INJ[c][0] in ("F3", "F4", "C1", "C2", "C3", "C4", "C5", "C6", "E6") for c in inj),
        "storage": pick("storage", rng.random() < 0.3),
        "delivery": rng.random() < 0.55, "manut": rng.random() < 0.4, "surch": rng.random() < 0.35,
        "dossier_fee": rng.random() < 0.45, "round_trap": rng.random() < 0.12,
        "merged": rng.random() < 0.32, "hidden_instr": rng.random() < 0.04,
        "carrier_mention": rng.random() < 0.10, "hs6_trap": False,
        "avoir_trap": rng.random() < 0.05,
        "support_docs": rng.random() < 0.45,
    }
    if any(c == "magasinage_excessif" for c in inj):
        attrs["storage"] = True
    if not attrs["ci_hs"]:
        attrs["hs6_trap"] = False
    else:
        attrs["hs6_trap"] = rng.random() < 0.12 and not any(INJ[c][0] in ("A13", "A12") for c in inj)
    if attrs["proforma"]:
        attrs["proforma"] = not any(INJ[c][0] == "A14" for c in inj)
    if attrs["need_ad"] and (kind == "h7" or not foreign):
        attrs["need_ad"] = False
    # Fournisseur
    sups = [s for s in CLIENT_SUPPLIERS[cid]
            if (("EUR" in SUPPLIERS_BY_ID[s]["devises"]) if not foreign else any(dv != "EUR" for dv in SUPPLIERS_BY_ID[s]["devises"]))]
    if attrs["need_ad"]:
        sups = [s for s in CLIENT_SUPPLIERS[cid] if SUPPLIERS_BY_ID[s]["pays"] == "CN"] or sups
        if not foreign:
            attrs["foreign"] = foreign = True
            if "foreign" in req:
                raise RuntimeError("need_ad et facture EUR incompatibles")
    if not sups:
        sups = CLIENT_SUPPLIERS[cid]
    sup = rng.choice(sorted(sups))
    devs = [dv for dv in SUPPLIERS_BY_ID[sup]["devises"] if (dv != "EUR") == foreign]
    if not devs:
        # fournisseur sans devise compatible : on force la devise EUR (ou la première devise étrangère)
        devs = ["EUR"] if not foreign else [dv for dv in SUPPLIERS_BY_ID[sup]["devises"] if dv != "EUR"] or ["USD"]
    attrs["supplier"] = sup
    attrs["devise"] = rng.choice(devs)
    if attrs["devise"] == "EUR":
        attrs["foreign"] = False
        attrs["decl_mode"] = "same"
    deg = rng.choices(["d0", "d1", "d2", "d3"], [0.26, 0.20, 0.31, 0.23])[0]
    if "deg_ok" in req:
        deg = rng.choices(["d0", "d1"], [0.6, 0.4])[0]
    return {"dossier_id": did, "split": split, "client_id": cid, "kind": kind, "family": fam, "layout": lay,
            "deg": deg, "attrs": attrs, "injections": list(inj), "partners": list(sl["partner_of"]),
            "role": sl["role"], "clean": did in clean and not inj}
