"""Construction d'un dossier complet : documents, injections d'erreurs (§19.5), pièges (§19.3.1),
niveaux attendus calculés mécaniquement, liens attendus, plan de fichiers et dégradations.
"""

from __future__ import annotations

import copy
from datetime import date
from decimal import Decimal as D

from . import model as M
from .model import FAMCAP, LAYCAP, liquide, recompute_decl_totals, to_eur
from .plan import INJ
from .util import (ZERO, add_days, mrn_fictif, mrn_version, q2, q3, qcur, rng_for, s2)
from .ext import EXT_MODES, GESTE_EXT, VAT_INCLUSIVE_FAMILIES
from .world import (CATALOG, LABELS, PRESTATIONS_HORS_GRILLE, SURCHARGES_HORS_GRILLE, fam_lang,
                    poste)

ANNEXE_A = {
    "P1": ["P1"], "P2": ["P2", "P1"], "P4": ["P4"],
    "A1": ["A1"], "A2": ["A2"], "A3": ["A3", "A6"], "A4": ["A4", "A5"], "A5": ["A5", "A4"],
    "A6": ["A6", "A3", "A5"], "A7": ["A7", "A6"], "A8": ["A8"], "A9": ["A9"], "A10": ["A10"],
    "A11": ["A11", "B5"], "A12": ["A12"], "A13": ["A13"], "A14": ["A14"], "A15": ["A15"],
    "B1": ["B1", "B2"], "B2": ["B2", "B1"], "B3": ["B3"], "B4": ["B4", "A10"], "B5": ["B5", "A11"],
    "C1": ["C1", "C5"], "C2": ["C2", "C5"], "C3": ["C3", "C5"], "C4": ["C4", "C5"],
    "C5": ["C5", "C1", "C2", "C3", "C4"], "C6": ["C6", "D4"], "C7": ["C7"], "C8": ["C8"],
    "D1": ["D1"], "D2": ["D2", "D7"], "D3": ["D3"], "D4": ["D4", "C6"], "D5": ["D5"], "D6": ["D6", "D3"],
    "D7": ["D7", "D2", "D3"], "D8": ["D8"], "D9": ["D9", "D3"],
    "E1": ["E1"], "E2": ["E2"], "E3": ["E3", "F1"], "E4": ["E4"], "E5": ["E5"], "E6": ["E6"],
    "F1": ["F1", "E3"], "F2": ["F2"], "F3": ["F3", "C5"], "F4": ["F4", "D5"], "F5": ["F5", "A4"],
    "G1": ["G1", "B1"], "G2": ["G2"], "G3": ["G3", "G2"], "G4": ["G4", "G5", "C1", "C5"], "G5": ["G5", "G4"],
    "G6": ["G6"],
}
CERTAIN_OK = {"A1", "A3", "A4", "A5", "A6", "B1", "B2", "B3", "B4", "C1", "C2", "C3", "C4", "C5", "C6", "C8",
              "D1", "D2", "D3", "D4", "D5", "D6", "D7", "D9", "F3", "G1", "G2", "G4", "G5"}
NATURE = {
    "A1": "aucun", "A2": "aucun", "A3": "aucun", "A4": "ecart_documentaire", "A5": "ecart_documentaire",
    "A6": "ecart_documentaire", "A7": "aucun", "A8": "aucun", "A9": "aucun", "A10": "aucun", "A11": "aucun",
    "A12": "renvoi", "A13": "renvoi", "A14": "aucun", "A15": "aucun",
    "B1": "arithmetique_declaration", "B2": "arithmetique_declaration", "B3": "arithmetique_declaration",
    "B4": "aucun", "B5": "aucun", "C1": "recouvrable", "C2": "recouvrable", "C3": "recouvrable", "C4": "recouvrable",
    "C5": "recouvrable", "C6": "recouvrable", "C7": "aucun", "C8": "aucun",
    "D1": "recouvrable", "D2": "recouvrable", "D3": "recouvrable", "D4": "recouvrable", "D5": "recouvrable",
    "D6": "recouvrable", "D7": "recouvrable", "D8": "recouvrable", "D9": "recouvrable",
    "E1": "aucun", "E2": "aucun", "E3": "aucun", "E4": "aucun", "E5": "aucun", "E6": "recouvrable",
    "F1": "aucun", "F2": "aucun", "F3": "recouvrable", "F4": "recouvrable", "F5": "ecart_documentaire",
    "G1": "arithmetique_declaration", "G2": "arithmetique_declaration", "G3": "renvoi", "G4": "recouvrable",
    "G5": "recouvrable", "G6": "renvoi", "P1": "aucun", "P2": "aucun",
}
COMPOSANTE = {"C1": "droit", "C2": "autre_taxe", "C3": "tva", "C4": "tva", "C5": None, "C6": "prestation",
              "D1": None, "D2": "prestation", "D3": "prestation", "D4": "prestation", "D5": "prestation",
              "D6": "prestation", "D7": "prestation", "D8": "tva", "D9": "prestation", "E6": None,
              "F3": None, "F4": "prestation", "G4": "forfait_petits_envois", "G5": "forfait_petits_envois",
              "A4": "valeur", "A5": "valeur", "A6": "valeur", "F5": "valeur"}

STRUCTURED_FORMATS = {"ubl", "cii", "xml_declaration", "csv_declaration", "xlsx", "eml", "factur_x"}

CONF_CLASSES = [set("0689"), set("358"), set("147")]


def is_confusion(a: str, b: str) -> bool:
    """§8.5.4 : une seule transformation (substitution de classe, zéro final, séparateur)."""
    if a == b:
        return False
    if len(a) == len(b):
        diff = [(x, y) for x, y in zip(a, b) if x != y]
        if len(diff) == 1:
            x, y = diff[0]
            if x.isdigit() and y.isdigit():
                return any(x in c and y in c for c in CONF_CLASSES)
    try:
        da, db = D(a), D(b)
        if da != 0 and db != 0:
            for f in (D(100), D(1000), D(10)):
                if da * f == db or db * f == da:
                    return True
    except Exception:
        pass
    if a.rstrip("0") == b.rstrip("0") and abs(len(a) - len(b)) == 1:
        return True
    return False


MODES = {"d0": ["native"], "d1": ["scan300", "scan250j"],
         "d2": ["skew200", "photo", "lowcontrast", "jpeg150", "tiff200", "rotated"],
         "d3": ["fax", "faxtiff"]}


# Extension 2.1 : nouvelles dégradations, tirées deux fois plus souvent que les anciennes
MODES_EXT = {"d0": ["native"], "d1": ["scan300", "scan250j"],
             "d2": MODES["d2"] + ["skewlow", "skewlow", "overlay", "overlay", "twoup", "twoup", "jpegheavy", "jpegheavy"],
             "d3": MODES["d3"] + ["faxnoise", "faxnoise", "faxnoise"]}


class Dossier:
    def __init__(self, world, spec, seed, registry):
        self.world = world
        self.spec = spec
        self.seed = seed
        self.did = spec["dossier_id"]
        self.rng = rng_for(seed, self.did, "build")
        self.registry = registry
        self.docs: dict = {}
        self.order: list = []
        self.errors: list = []
        self.traps: list = []
        self.links: list = []
        self.tags: list = []
        self.removed: set = set()
        cl = world["clients"][spec["client_id"]]
        self.client = cl
        ents = cl["entites"]
        self.entity = ents[0] if len(ents) == 1 else self.rng.choice(ents)
        # Dossiers appariés (F2, F3, F5) : même entité importatrice que le dossier partenaire, sinon
        # une pièce copiée du partenaire créerait un écart d'entité (A1/C8) non injecté.
        # Le tirage ci-dessus est conservé pour ne pas décaler l'aléa.
        for _code, pid in spec.get("partners", []):
            if pid in registry:
                self.entity = registry[pid].entity
                break
        self.forwarder = world["forwarders"][spec["family"]]
        self.grid = world["grids"][(spec["client_id"], spec["family"])]
        self.ctx = {"spec": spec, "client": cl, "entity": self.entity, "forwarder": self.forwarder,
                    "grid": self.grid, "fwd_lang": self.forwarder["lang"]}
        self.attrs = spec["attrs"]
        self.inj = list(spec["injections"])
        self.notes: dict = {}

    # ------------------------------------------------------------------
    def add(self, doc):
        self.docs[doc["doc_id"]] = doc
        self.order.append(doc["doc_id"])
        return doc

    def has(self, code):
        return code in self.inj

    def ctrl_in(self, *ctrls):
        return any(INJ[c][0] in ctrls for c in self.inj)

    # ------------------------------------------------------------------
    def build(self):
        rng = self.rng
        sp = self.spec
        a = self.attrs
        h7 = sp["kind"] == "h7"
        # Dates
        if h7:
            d_ci = date(2026, 7, 2) + __import__("datetime").timedelta(days=rng.randint(0, 75))
            if self.has("forfait_hors_periode") and rng.random() < 0.5:
                d_ci = date(2026, 6, 3) + __import__("datetime").timedelta(days=rng.randint(0, 18))
                self.notes["g6_variant"] = "date"
        else:
            d_ci = date(2026, 1, 8) + __import__("datetime").timedelta(days=rng.randint(0, 240))
        self.d_ci = d_ci
        sector = self.client["secteur"]
        n_ship = 1
        if a["structure"] == "statement":
            n_ship = rng.choice([3, 4, 4, 5])      # relevé : souvent plus d'une page (reports « carried forward »)
        self.shipments = []
        for k in range(n_ship):
            self.shipments.append(self._make_shipment(k, d_ci if k == 0 else add_days(d_ci, rng.randint(-20, 10)), sector, h7))
        if sp.get("ext") and self.entity.get("fiscal_rep"):
            for sh in self.shipments:
                for d_ in sh["decls"]:
                    d_["fiscal_rep"] = self.entity["fiscal_rep"]
        # Injections sur les déclarations
        self._inject_decl()
        # Version rectifiée (piège)
        if a.get("rectif") and not h7:
            self._rectif()
        # Factures du transitaire
        self.fts = []
        if a["has_ft"]:
            self._make_fts()
        self._total_faux()
        self._inject_post()
        self._c6()
        self._partners()
        self._exclusive()
        self._support_docs()
        self._traps()
        self._links()
        self._assign_modes()
        return self

    # ------------------------------------------------------------------
    def _make_shipment(self, k, d_ci, sector, h7):
        rng = self.rng
        a = self.attrs
        sp = self.spec
        sup = a["supplier"]
        devise = a["devise"]
        n_lines = rng.randint(1, 3) if h7 else rng.randint(1, 6)
        if a["structure"] == "split_decl" or (h7 and (self.has("forfait_base_differente") or self.has("forfait_codes_distincts"))):
            n_lines = max(n_lines, 3 if h7 else 2)
        if self.has("quantite_differente") or self.has("masse_differente"):
            n_lines = max(n_lines, 1)
        lines_spec = M.pick_lines(rng, sector, n_lines, h7, need_ad=a.get("need_ad") and k == 0,
                                  need_multi_art=(a.get("multi_art") and not h7 and k == 0))
        if sp.get("ext") and sp.get("ci_layout_override") == "CM" and not h7 and k == 0:
            lines_spec = self._expand_cm(lines_spec)
        if h7 and k == 0:
            if self.has("forfait_codes_distincts"):
                p0 = lines_spec[0][0]
                p1 = dict(lines_spec[1][0])
                p1["hs"] = p0["hs"]
                lines_spec[1] = (p1, lines_spec[1][1])
            elif self.has("forfait_base_differente"):
                p0 = lines_spec[0][0]
                p1 = dict(lines_spec[1][0])
                alt = p0["hs"][:6] + ("9000" if p0["hs"][6:] != "9000" else "1000")
                p1["hs"] = alt
                lines_spec[1] = (p1, lines_spec[1][1])
            if self.has("forfait_unites_au_lieu_articles"):
                p, q = lines_spec[0]
                lines_spec[0] = (p, D(max(int(q), 3)))
            if self.has("forfait_hors_periode") and self.notes.get("g6_variant") != "date":
                self.notes["g6_variant"] = "valeur"
        incoterm = rng.choice(["EXW", "FCA", "FOB", "FOB", "CFR", "CIF", "CPT", "CIP", "DAP"]) if not h7 else rng.choice(["DAP", "DDP", "CPT"])
        transport = M.transport_for(rng, "air" if h7 else None)
        proforma = a.get("proforma") and k == 0
        cis = []
        ci_ids = ["fc1"] if k == 0 else [f"fc{k + 1}"]
        if a["structure"] == "multi_ci" and k == 0:
            ci_ids = ["fc1", "fc2"]
        for j, cid in enumerate(ci_ids):
            if j == 0:
                ls = lines_spec
            else:
                ls = M.pick_lines(rng, sector, rng.randint(1, 3), h7)
            ci = M.make_ci(self.ctx, rng, doc_id=cid, sup_id=sup, devise=devise, d_ci=add_days(d_ci, j), lines_spec=ls,
                           incoterm=incoterm, transport=transport, h7=h7, proforma=proforma and j == 0,
                           freight_trap=a.get("freight_trap") and k == 0)
            f5 = [pid for code, pid in self.spec["partners"] if code == "facture_sur_deux_declarations"]
            if f5 and k == 0 and j == 0:
                # même facture commerciale que dans le dossier partenaire (copie reçue une seconde fois)
                A = self.registry[f5[0]]
                ci = copy.deepcopy(A.ci1)
                ci["doc_id"] = cid
                ci["layout"] = A.ci1["layout"] if A.ci1["layout"] not in ("CU", "CK") else "CA"
                incoterm = ci["incoterm"]
                transport = ci["transport"]
            if h7 and self.notes.get("g6_variant") == "valeur" and k == 0:
                self._inflate_h7_value(ci)
            if j > 0:
                ci["numero"] = cis[0]["numero"][:-1] + str((int(cis[0]["numero"][-1]) + 1) % 10) if cis[0]["numero"][-1].isdigit() else cis[0]["numero"] + "-2"
            if a.get("carrier_mention") and j == 0 and k == 0:
                ci["carrier_mention"] = self.forwarder["nom"]
            if self.has("origine_differente") or self.has("code_sh6_different"):
                ci["origin_mode"] = "line"
                if ci["hs_digits"] == 0:
                    ci["hs_digits"] = 8
            if a.get("hs6_trap"):
                ci["hs_digits"] = 6
            if not a.get("ci_hs", True):
                ci["hs_digits"] = 0
            if sp.get("ext"):
                self._ext_ci_features(ci)
            self.add(ci)
            cis.append(ci)
        # Déclarations
        d_acc = add_days(max(c["date"] for c in cis), rng.randint(2, 21))
        if h7 and self.notes.get("g6_variant") == "date":
            d_acc = min(d_acc, date(2026, 6, 29))
        if h7 and self.notes.get("g6_variant") != "date" and d_acc < M.FORFAIT_DEBUT:
            d_acc = M.FORFAIT_DEBUT
        decls = []
        dk = len([d for d in self.docs.values() if d["kind"] == "dec"])
        if a["structure"] == "split_decl" and k == 0 and len(cis[0]["lines"]) >= 2:
            lns = cis[0]["lines"]
            cut = max(1, len(lns) // 2)
            sel1 = {(cis[0]["doc_id"], ln["no"]) for ln in lns[:cut]}
            sel2 = {(cis[0]["doc_id"], ln["no"]) for ln in lns[cut:]}
            for i, sel in enumerate((sel1, sel2)):
                dec = M.make_decl(self.ctx, rng, doc_id=f"dec{dk + i + 1}", cis=cis, lines_sel=sel,
                                  d_acc=add_days(d_acc, 3 * i), decl_mode=a["decl_mode"], rate_printed=a["rate_printed"],
                                  sens=a["sens"], autoliq=a["autoliq"], h7=h7)
                self.add(dec)
                decls.append(dec)
            self.tags.append("facture_sur_plusieurs_declarations")
        else:
            dec = M.make_decl(self.ctx, rng, doc_id=f"dec{dk + 1}", cis=cis, d_acc=d_acc, decl_mode=a["decl_mode"],
                              rate_printed=a["rate_printed"], sens=a["sens"], autoliq=a["autoliq"], h7=h7,
                              declared_goods_only=a.get("freight_trap") and k == 0)
            self.add(dec)
            decls.append(dec)
        if len(cis) > 1:
            self.tags.append("plusieurs_factures_une_declaration")
        return {"cis": cis, "decls": decls}

    def _inflate_h7_value(self, ci):
        """G6 variante valeur : envoi de plus de 150 EUR (quantités relevées)."""
        devise = ci["devise"]
        fx = D(1) if devise == "EUR" else M.bce_rate(devise, ci["date"])
        target = D(220) * fx
        while ci["total"] < target:
            for ln in ci["lines"]:
                ln["qty"] = ln["qty"] * 2
                ln["amount"] = qcur(ln["qty"] * ln["pu"], devise)
                ln["net"] = q3(ln["net"] * 2)
                ln["gross"] = q3(ln["gross"] * 2)
            goods = sum((ln["amount"] for ln in ci["lines"]), ZERO)
            fret = ci["sub"].get("fret", ZERO)
            if "fret" in ci["sub"]:
                ci["sub"]["fret"] = fret
            ci["sub"]["marchandises"] = goods
            ci["total"] = qcur(goods + ci["sub"].get("fret", ZERO), devise)
            ci["net_total"] = q3(sum((ln["net"] for ln in ci["lines"]), ZERO))
            ci["gross_total"] = q3(sum((ln["gross"] for ln in ci["lines"]), ZERO))

    # ------------------------------------------------------------------
    @property
    def ci1(self):
        return self.docs["fc1"]

    @property
    def dec1(self):
        return self.shipments[0]["decls"][0]

    def err(self, code, docs, amount=None, fields=None, desc="", level_info=None, ctrl=None):
        ctrl = ctrl or INJ[code][0]
        e = {"code": code, "ctrl": ctrl, "docs": list(docs), "amount": amount, "fields": fields or [],
             "desc": desc, "li": level_info or {}}
        self.errors.append(e)
        return e

    def trap(self, ctrl, docs, max_level, desc):
        self.traps.append({"ctrl": ctrl, "docs": list(docs), "max": max_level, "desc": desc})

    # ------------------------------------------------------------------
    def _inject_decl(self):
        rng = self.rng
        ci = self.ci1
        dec = self.dec1
        devise = ci["devise"]
        if self.has("entite_groupe_differente"):
            others = [e for e in self.client["entites"] if e["tva"] != self.entity["tva"]]
            o = rng.choice(others)
            dec["importateur"] = {"nom": o["raison_sociale"], "tva": o["tva"], "eori": o["eori"]}
            self.notes["ft_client_override"] = o
            self.err("entite_groupe_differente", ["fc1", dec["doc_id"]], None, [f"{dec['doc_id']}.importateur.tva"],
                     "La déclaration indique comme importateur une autre entité du groupe que l'acheteur de la facture.",
                     {"nonnum": True})
        if self.has("entite_tierce"):
            t = rng.choice(self.world["tiers"])
            dec["importateur"] = {"nom": t["raison_sociale"], "tva": t["tva"], "eori": t["eori"]}
            self.err("entite_tierce", ["fc1", dec["doc_id"]], None, [f"{dec['doc_id']}.importateur.tva"],
                     "La déclaration indique un importateur extérieur au client.", {"nonnum": True})
        if self.has("ref_facture_absente"):
            dec["refs"] = [r for r in dec["refs"] if r["code"] not in ("N380", "N325")]
            self.err("ref_facture_absente", ["fc1", dec["doc_id"]], None, [f"{dec['doc_id']}.documents_references"],
                     "La déclaration ne cite pas la facture commerciale.")
        if self.has("devise_differente"):
            choices = [c for c in ("USD", "GBP", "CHF", "CNY") if c != dec["devise"]]
            nd = rng.choice(choices)
            dec["devise"] = nd
            if dec["rate"] is not None:
                dec["devise_taux"] = nd
            self.err("devise_differente", ["fc1", dec["doc_id"]], None, [f"{dec['doc_id']}.devise_facture"],
                     f"Devise déclarée {nd} au lieu de {devise} (montant identique).", {"nonnum": True})
        if self.has("valeur_transposee") or self.has("valeur_modifiee") or self.has("somme_articles_incoherente"):
            self._inject_value()
        if self.has("conversion_fausse"):
            correct = dec["montant"]
            f = rng.choice([D("1.04"), D("0.93"), D("1.12"), D("0.88"), D("1.006"), D("0.994"), D("1.25")])
            new = q2(correct * f)
            if abs(new - correct) <= max(D(1), correct * D("0.001")):
                new = correct + D("12.00")
            self._set_decl_amount(dec, new, proportional=True)
            amt = new - to_eur(ci["total"], dec["rate"], dec["sens"])
            seuil = max(D(5), abs(correct) * D("0.005"))
            self.err("conversion_fausse", ["fc1", dec["doc_id"]], amt, [f"{dec['doc_id']}.montant_total_facture"],
                     "Montant converti en EUR différent du total facture × taux imprimé.",
                     {"abs": abs(amt), "seuil": seuil, "conf": (str(correct), str(new))})
        if self.has("non_converti"):
            arts_ccy = []
            for art in dec["articles"]:
                arts_ccy.append(art["amt_goods"])
            new = ci["total"]
            dec["montant"] = q2(new)
            tot_goods = sum(arts_ccy, ZERO)
            acc = ZERO
            for j, art in enumerate(dec["articles"]):
                if j == len(dec["articles"]) - 1:
                    art["amount"] = q2(new) - acc
                else:
                    art["amount"] = q2(new * art["amt_goods"] / tot_goods)
                    acc += art["amount"]
            amt = q2(new) - to_eur(ci["total"], dec["rate"], dec["sens"])
            self.err("non_converti", ["fc1", dec["doc_id"]], amt, [f"{dec['doc_id']}.montant_total_facture"],
                     f"Montant en {devise} repris tel quel comme montant en EUR.",
                     {"abs": abs(amt), "seuil": max(D(5), abs(amt) * D("0.005")), "iso_needed": True})
        if self.has("ordre_grandeur_incoherent"):
            f = rng.choice([D("0.45"), D("1.75"), D("2.10"), D("0.40")])
            new = q2(dec["montant"] * f)
            self._set_decl_amount(dec, new, proportional=True)
            self.err("ordre_grandeur_incoherent", ["fc1", dec["doc_id"]], None, [f"{dec['doc_id']}.montant_total_facture"],
                     "Montant EUR déclaré hors de la bande indicative (aucun taux imprimé).")
        if self.has("incoterm_different"):
            alt = [x for x in ("EXW", "FCA", "FOB", "CIF", "DAP", "CPT") if x != dec["incoterm"]]
            dec["incoterm"] = rng.choice(alt)
            self.err("incoterm_different", ["fc1", dec["doc_id"]], None, [f"{dec['doc_id']}.incoterm"], "Incoterm différent.")
        if self.has("quantite_differente"):
            cand = [ar for ar in dec["articles"] if ar["qty"] is not None]
            art = cand[0]
            old = art["qty"]
            if art["qty_unit"] in ("C62", "PR"):
                art["qty"] = old + rng.choice([5, 10, 12, 20, 50, 100])
            else:
                art["qty"] = q3(old * D("1.08") + 5)
            self.err("quantite_differente", ["fc1", dec["doc_id"]], None, [f"{dec['doc_id']}.articles[{art['no'] - 1}].quantite_unite_supplementaire"],
                     f"Quantité de l'article {art['no']} : {old} sur la facture, {art['qty']} sur la déclaration.")
        if self.has("masse_differente"):
            art = max(dec["articles"], key=lambda x: x["gross"])
            dlt = max(D("6"), q3(dec["gross_total"] * D("0.08")))
            art["gross"] = q3(art["gross"] + dlt)
            dec["gross_total"] = q3(dec["gross_total"] + dlt)
            self.err("masse_differente", ["fc1", dec["doc_id"]], None, [f"{dec['doc_id']}.masse_brute_totale"],
                     f"Masse brute déclarée supérieure de {dlt} kg à celle de la facture.")
        if self.has("colis_different"):
            k = rng.choice([1, 2, 3, 5, 10])
            dec["colis_total"] += k
            dec["articles"][0]["colis"] += k
            self.err("colis_different", ["fc1", dec["doc_id"]], None, [f"{dec['doc_id']}.nombre_colis_total"],
                     f"Nombre de colis déclaré supérieur de {k}.")
        if self.has("origine_differente"):
            art = dec["articles"][-1]
            alt = [c for c in ("VN", "TH", "MY", "ID", "TW", "BD", "KH") if c != art["origin"]]
            art["origin"] = rng.choice(alt)
            self.err("origine_differente", ["fc1", dec["doc_id"]], None, [f"{dec['doc_id']}.articles[{art['no'] - 1}].pays_origine"],
                     f"Pays d'origine de l'article {art['no']} différent de la facture.")
        if self.has("code_sh6_different"):
            art = dec["articles"][0]
            used = {x["hs10"][:4] for x in dec["articles"]}
            pool = [p["hs"] for cat in CATALOG.values() for p in cat if p["hs"][:4] not in used]
            pool = sorted(set(pool))
            art["hs10"] = rng.choice(pool)
            self.err("code_sh6_different", ["fc1", dec["doc_id"]], None, [f"{dec['doc_id']}.articles[0].code_marchandise"],
                     "Code marchandise de l'article 1 différent (6 premiers chiffres) du code imprimé sur la facture.")
        if self.has("date_anterieure"):
            dec["date"] = add_days(ci["date"], -rng.randint(4, 25))
            self.err("date_anterieure", ["fc1", dec["doc_id"]], None, [f"{dec['doc_id']}.date_acceptation"],
                     "Date d'acceptation antérieure à la date de la facture.")
        if self.has("reference_produit_absente"):
            art = next(ar for ar in dec["articles"] if len(ar["refs"]) >= 2)
            hidden = art["refs"][-1]
            art["refs_printed"] = art["refs"][:-1]
            self.err("reference_produit_absente", ["fc1", dec["doc_id"]], None, [],
                     f"La référence {hidden} de la facture n'apparaît dans aucune désignation de la déclaration.")
        # Famille B
        if self.has("taxe_base_taux_incoherente"):
            t = next(t for t in dec["taxes"] if t["type"] == "A00" and t["montant"] > 0) if any(t["type"] == "A00" and t["montant"] > 0 for t in dec["taxes"]) else next(t for t in dec["taxes"] if t["type"] == "B00")
            calc = q2(t["base"] * t["rate"] / 100)
            big = rng.random() < 0.75
            dlt = rng.choice([D("10.00"), D("27.40"), D("90.00"), D("4.50"), D("18.20")]) if big else rng.choice([D("1.40"), D("2.10")])
            new = calc + dlt
            while new in (calc.to_integral_value(rounding="ROUND_FLOOR"), calc.to_integral_value(rounding="ROUND_CEILING"), calc.to_integral_value(rounding="ROUND_HALF_UP")):
                new += D("0.37")
            t["montant"] = new
            if t["a_payer"] != 0:
                t["a_payer"] = new
            recompute_decl_totals(dec)
            amt = new - calc
            self.err("taxe_base_taux_incoherente", [dec["doc_id"]], amt, [f"{dec['doc_id']}.taxations.montant"],
                     f"Montant de taxe {t['type']} (article {t['article']}) différent de base × taux imprimés.",
                     {"abs": abs(amt), "seuil": D(1)})
        if self.has("somme_taxes_incoherente"):
            dlt = rng.choice([D("20.00"), D("50.00"), D("100.00"), D("7.30"), D("1.60")])
            if LAYCAP[dec["layout"]]["type_totals"]:
                code = "A00" if dec["type_totals"].get("A00", ZERO) > 0 else "B00"
                sign = rng.choice([1, -1])
                printed = dec["type_totals"][code] + sign * dlt
                if printed < 0:
                    printed = dec["type_totals"][code] + dlt
                amt = printed - dec["type_totals"][code]
                dec.setdefault("overrides", {})["type_totals"] = {code: printed}
                fld = f"{dec['doc_id']}.total_{code}"
            else:
                sign = -1 if dec["total_a_payer"] - dlt > 0 and self.rng.random() < 0.5 else 1
                amt = sign * dlt
                dec.setdefault("overrides", {})["total_a_payer"] = dec["total_a_payer"] + amt
                dec["overrides"]["total_droits_taxes"] = dec["total_droits_taxes"] + amt
                fld = f"{dec['doc_id']}.total_a_payer"
            recompute_decl_totals(dec)
            self.err("somme_taxes_incoherente", [dec["doc_id"]], amt, [fld], "Total imprimé différent de la somme des taxes.",
                     {"abs": abs(amt), "seuil": D(1)})
        if self.has("nette_superieure_brute"):
            art = dec["articles"][0]
            tm = max(D("0.5"), art["gross"] * D("0.005"))
            dlt = q3(max(tm * 4, D("3")))
            art["net"] = q3(art["gross"] + dlt)
            self.err("nette_superieure_brute", [dec["doc_id"]], None, [f"{dec['doc_id']}.articles[0].masse_nette"],
                     "Masse nette de l'article 1 supérieure à sa masse brute.", {"nonnum": True})
        if self.has("colis_articles_incoherents"):
            k = rng.choice([1, 2, 4])
            dec["articles"][-1]["colis"] += k
            self.err("colis_articles_incoherents", [dec["doc_id"]], None, [f"{dec['doc_id']}.articles.nombre_colis"],
                     "Somme des colis par article différente du total imprimé.", ctrl="B5")
        # Famille G (déclaration)
        if self.spec["kind"] == "h7":
            ftax = next(t for t in dec["taxes"] if t["cat"] == "forfait_petits_envois")
            if self.has("forfait_base_differente"):
                n = dec["n_articles"]
                base = len({ar["hs10"][:6] for ar in dec["articles"]})
                if base == n:
                    base = n + 1
                ftax["base_qty"] = D(base)
                ftax["montant"] = q2(ftax["rate"] * base)
                ftax["a_payer"] = ftax["montant"]
                self._fix_h7_vat(dec)
                amt = q2((D(base) - D(n)) * ftax["rate"])
                self.err("forfait_base_differente", [dec["doc_id"]], amt, [f"{dec['doc_id']}.taxations.base_quantite"],
                         f"Base du forfait {base} articles pour {n} articles déclarés.", {"abs": abs(amt), "seuil": D(1)})
            if self.has("forfait_base_x_taux_faux"):
                calc = q2(ftax["base_qty"] * ftax["rate"])
                big = rng.random() < 0.8
                dlt = rng.choice([D("3.00"), D("6.00"), D("9.00")]) if big else D("1.50")
                ftax["montant"] = calc + dlt
                ftax["a_payer"] = ftax["montant"]
                self._fix_h7_vat(dec)
                self.err("forfait_base_x_taux_faux", [dec["doc_id"]], dlt, [f"{dec['doc_id']}.taxations.montant"],
                         "Montant du forfait différent de nombre d'articles × montant unitaire.", {"abs": dlt, "seuil": D(1)})
            if self.has("forfait_codes_distincts"):
                self.err("forfait_codes_distincts", [dec["doc_id"]], None, [],
                         "Base du forfait égale au nombre d'articles mais différente du nombre de codes distincts.")
            if self.has("forfait_hors_periode"):
                v = self.notes.get("g6_variant")
                self.err("forfait_hors_periode", [dec["doc_id"]], None, [],
                         "Forfait petits envois sur une déclaration acceptée avant le 1er juillet 2026." if v == "date"
                         else "Forfait petits envois sur un envoi de valeur supérieure à 150 EUR.")
            recompute_decl_totals(dec)

    def _fix_h7_vat(self, dec):
        ftax = next(t for t in dec["taxes"] if t["cat"] == "forfait_petits_envois")
        vat = next(t for t in dec["taxes"] if t["cat"] == "tva")
        tot_val = sum((a["stat_value"] for a in dec["articles"]), ZERO)
        vat["base"] = q2(tot_val + ftax["montant"])
        vat["montant"] = q2(vat["base"] * vat["rate"] / 100)
        vat["a_payer"] = ZERO if dec["autoliq"] else vat["montant"]
        recompute_decl_totals(dec)

    def _set_decl_amount(self, dec, new, proportional=False):
        old = dec["montant"]
        dec["montant"] = new
        arts = dec["articles"]
        if proportional and old:
            acc = ZERO
            for j, art in enumerate(arts):
                if j == len(arts) - 1:
                    art["amount"] = new - acc
                else:
                    art["amount"] = q2(art["amount"] * new / old)
                    acc += art["amount"]
        else:
            big = max(arts, key=lambda x: x["amount"])
            big["amount"] = big["amount"] + (new - old)

    def _inject_value(self):
        rng = self.rng
        ci = self.ci1
        dec = self.dec1
        devise = dec["devise"]
        total = ci["total"]
        dec_digits = 0 if devise in ("JPY", "KRW") else 2
        tv = max(D(1), total * D("0.001"))
        sv = max(D(5), total * D("0.005"))
        footers = [v for k, v in ci["sub"].items() if k != "marchandises"]

        def explained(dl):
            return any(abs(abs(dl) - f) <= tv for f in footers) or (footers and abs(abs(dl) - sum(footers)) <= tv)

        def eur(x):
            if devise == "EUR":
                return q2(x)
            if dec["rate"] is None:
                return None
            return to_eur(x, dec["rate"], dec["sens"])

        if self.has("valeur_transposee"):
            s = str(qcur(total, devise)).replace(".", "")
            cands = []
            for i in range(len(s) - 1 - dec_digits):
                if s[i] != s[i + 1]:
                    t = s[:i] + s[i + 1] + s[i] + s[i + 2:]
                    if t[0] == "0":
                        continue
                    new = D(t) / (D(10) ** dec_digits)
                    dl = new - total
                    if abs(dl) > tv and not explained(dl):
                        cands.append((abs(dl) < 3 * sv, i, new))
            if cands:
                big = [c for c in cands if not c[0]]
                pool = big if (big and rng.random() < 0.8) else cands
                new = rng.choice(pool)[2]
            else:
                new = total + (D(90) if dec_digits else D(9000))
            dl = new - total
            self._set_decl_amount(dec, new)
            a_eur = eur(dl)
            self.err("valeur_transposee", ["fc1", dec["doc_id"]], a_eur, [f"{dec['doc_id']}.montant_total_facture"],
                     "Deux chiffres adjacents permutés dans le montant total facturé déclaré.",
                     {"abs": abs(dl), "seuil": sv})
        if self.has("valeur_modifiee"):
            variant = rng.choice(["pct", "pct", "pct", "small", "conf"])
            if variant == "pct":
                f = rng.choice([D("1.03"), D("0.95"), D("1.10"), D("0.90"), D("1.15")])
                new = qcur(total * f, devise)
            elif variant == "small":
                new = qcur(total + max(tv * D("1.6"), D(2)), devise)
            else:
                s = str(qcur(total, devise))
                new = None
                for i, ch in enumerate(s):
                    if ch in "0689" and i < len(s) - 3 and i > 0:
                        rep = {"6": "8", "8": "6", "0": "8", "9": "8"}[ch]
                        cand = D(s[:i] + rep + s[i + 1:])
                        if abs(cand - total) > tv:
                            new = cand
                            break
                if new is None:
                    new = qcur(total * D("1.07"), devise)
                    variant = "pct"
            dl = new - total
            if explained(dl):
                new = new + (D("13.00") if dec_digits else D(1300))
                dl = new - total
            self._set_decl_amount(dec, new)
            self.err("valeur_modifiee", ["fc1", dec["doc_id"]], eur(dl), [f"{dec['doc_id']}.montant_total_facture"],
                     f"Montant total facturé déclaré modifié ({variant}).",
                     {"abs": abs(dl), "seuil": sv, "conf": (str(qcur(total, devise)), str(new))})
        if self.has("somme_articles_incoherente"):
            art = dec["articles"][0]
            dl = rng.choice([D("25.00"), D("100.00"), D("8.40"), D("250.00"), D("1.70")])
            if dec_digits == 0:
                dl = dl * 100
            art["amount"] = art["amount"] + dl
            amt = eur(-dl)
            self.err("somme_articles_incoherente", [dec["doc_id"]], amt,
                     [f"{dec['doc_id']}.articles[0].montant_facture_article"],
                     "Somme des montants facturés des articles différente du montant total facturé.",
                     {"abs": abs(dl), "seuil": D(1)})

    # ------------------------------------------------------------------
    # Extension 2.1 (spec["ext"]) : jamais appelé sans --ext
    def _expand_cm(self, lines_spec):
        """Facture multipage : chaque produit décliné en variantes (taille, coloris), 22 à 45 lignes."""
        rng = self.rng
        suffixes = ["S", "M", "L", "XL", "BK", "WH", "RD", "BL", "GR"]
        out = []
        for p, q in lines_spec:
            n = rng.randint(4, 8)
            for j in range(n):
                v = dict(p)
                v["ref"] = f"{p['ref']}-{suffixes[j % len(suffixes)]}"
                v["desc"] = {kk: f"{vv} / {suffixes[j % len(suffixes)]}" for kk, vv in p["desc"].items()}
                qq = D(max(1, int(q) // n + rng.randint(0, 3))) if p["unit"] != "KGM" else D(max(5, int(q) // n))
                out.append((v, qq))
                if len(out) >= 45:
                    return out
        base_n = len(out)
        while len(out) < 22:
            p, q = out[len(out) % base_n]
            v = dict(p)
            v["ref"] = p["ref"] + str(len(out))
            out.append((v, q))
        return out

    def _ext_ci_features(self, ci):
        rng = self.rng
        ent = self.entity
        ci["ext"] = True
        if ci["layout"] in ("CF", "CG", "CU", "CK"):    # présentations sans emplacement pour ces mentions
            return
        if ent.get("ship_to_sister"):
            sis = [e for e in self.client["entites"] if e["tva"] != ent["tva"]]
            if sis:
                o = rng.choice(sis)
                ci["destinataire"] = {"nom": o["raison_sociale"], "adresse": o["adresse"]}
        if ent.get("vat_spaced"):
            t = ent["tva"]
            ci["acheteur"] = {**ci["acheteur"], "tva_affichee": f"{t[:2]} {t[2:4]} {t[4:7]} {t[7:10]} {t[10:]}"}
        if ent.get("trade_name"):
            ci["acheteur"] = {**ci["acheteur"], "nom_affiche": f"{ent['trade_name']} ({ent['raison_sociale']})"}
        if self.attrs.get("multi_cur"):
            dev = ci["devise"]
            other = "EUR" if dev != "EUR" else rng.choice(["USD", "CHF", "PLN", "GBP"])
            if dev != "EUR":
                r = M.bce_rate(dev, ci["date"])           # unités de devise pour 1 EUR
                val = q2(ci["total"] / r)
            else:
                r = M.bce_rate(other, ci["date"])
                val = q2(ci["total"] * r)
            ci["equiv"] = {"devise": other, "montant": val, "taux": r}

    def _credit_line(self):
        rng = self.rng
        amt = -rng.choice([D("12.00"), D("18.50"), D("25.00"), D("40.00")])
        prev = f"ZP-{self.d_ci.year % 100}-{rng.randint(100000, 999999)}"
        return (amt, f"Gutschrift zu Rechnung {prev}")

    def _rectif(self):
        """Piège : version initiale (taxes erronées) et version rectifiée ; seule la dernière compte."""
        dec = self.dec1
        v1 = copy.deepcopy(dec)
        v1["doc_id"] = "dec0"
        v1["version"] = 1
        for t in v1["taxes"]:
            if t["type"] == "A00" and t["montant"] > 0:
                t["base"] = q2(t["base"] * D("1.10"))
                t["montant"] = q2(t["base"] * t["rate"] / 100)
                t["a_payer"] = t["montant"]
        recompute_decl_totals(v1)
        v1["date"] = add_days(dec["date"], -2)
        dec["mrn"] = mrn_version(dec["mrn"], self.rng)
        dec["version"] = 2
        v1["mrn"] = v1["mrn"]
        self.docs["dec0"] = v1
        self.order.insert(self.order.index(dec["doc_id"]), "dec0")
        self.notes["rectif"] = True
        self.tags.append("declaration_rectificative")

    # ------------------------------------------------------------------
    def _ft_opts(self, rng):
        a = self.attrs
        return {"storage": a.get("storage"), "storage_days": rng.randint(4, 14), "delivery": a.get("delivery"),
                "manut": a.get("manut"), "surch": a.get("surch"), "dossier_fee": a.get("dossier_fee"),
                "discount": self.spec["family"] in ("G6", "G15") and self.rng.random() < 0.6,
                "credit_line": self._credit_line() if self.spec["family"] == "G15" else None,
                "round_trap": a.get("round_trap") and not self.ctrl_in("C1", "C5", "C6", "E6"),
                "transport_ref_style": rng.choice(["raw", "raw", "spaced", "slashed"])}

    def _make_fts(self):
        rng = self.rng
        fam = self.spec["family"]
        all_decls = [d for sh in self.shipments for d in sh["decls"]]
        d_ft = add_days(max(d["date"] for d in all_decls), rng.randint(1, 12))
        opts = self._ft_opts(rng)
        if self.has("magasinage_excessif"):
            pm = poste(self.grid, "magasinage")
            opts["storage"] = True
            opts["storage_days"] = int(pm["franchise_jours"]) + rng.randint(3, 9)
        ft = M.make_ft(self.ctx, rng, doc_id="ft1", decls=all_decls, d_ft=d_ft, opts=opts)
        if opts["round_trap"] and any(ln["nature"] == "debours_droits" and ln["ht"] != liquide(self.dec1)["droit"] for ln in ft["lines"]):
            self.notes["round_trap"] = True
        if opts.get("discount"):
            self.notes["discount"] = True
        if "ft_client_override" in self.notes:
            o = self.notes["ft_client_override"]
            ft["client"] = {"nom": o["raison_sociale"], "tva": o["tva"], "adresse": o["adresse"]}
        self.add(ft)
        self.fts.append(ft)
        self._inject_ft(ft)
        M.finalize_ft(ft, self.grid, None)
        self._post_ft_errors(ft)
        # Facture complémentaire légitime (piège)
        if self.attrs.get("complementary") and not FAMCAP[fam].get("split_invoices") and FAMCAP[fam]["ventile"]:
            self._complementary(ft)
        # Familles à deux factures (débours / prestations)
        if FAMCAP[fam].get("split_invoices"):
            self._split_invoices(ft)

    def _complementary(self, ft):
        rng = self.rng
        dl = next((ln for ln in ft["lines"] if ln["nature"] == "debours_droits" and ln["ht"] > 40), None)
        if dl is None:
            return
        part = q2(dl["ht"] * D("0.3"))
        dl["ht"] = dl["ht"] - part
        dl["pu"] = dl["ht"]
        ft2 = copy.deepcopy(ft)
        ft2["doc_id"] = "ft2"
        ft2["numero"] = M.ft_number(rng, ft["family"], ft["date"])
        ft2["date"] = add_days(ft["date"], rng.randint(5, 20))
        ft2["lines"] = [M.ft_line(ft["family"], "debours_droits", part, mrn=dl["mrn"])]
        ft2["title_kind"] = "complementaire"
        ft2["total_overrides"] = {}
        for f in (ft, ft2):
            for ln in f["lines"]:
                if ln["nature"] == "frais_avance_fonds":
                    ln["fixed"] = True
            M.finalize_ft(f, self.grid, None)
        self.add(ft2)
        self.fts.append(ft2)
        self.notes["complementary"] = True
        self.tags.append("facture_complementaire")

    def _split_invoices(self, ft):
        rng = self.rng
        deb = [ln for ln in ft["lines"] if ln["nature"].startswith("debours")]
        srv = [ln for ln in ft["lines"] if not ln["nature"].startswith("debours")]
        if not deb or not srv:
            return
        ft2 = copy.deepcopy(ft)
        ft2["doc_id"] = "ft2"
        ft2["numero"] = M.ft_number(rng, ft["family"], ft["date"])
        ft["lines"] = deb
        ft["title_kind"] = "debours"
        ft2["lines"] = copy.deepcopy(srv)
        ft2["title_kind"] = "prestations"
        for f in (ft, ft2):
            for ln in f["lines"]:
                if ln["nature"] == "frais_avance_fonds":
                    ln["fixed"] = True
            f["total_overrides"] = {}
            M.finalize_ft(f, self.grid, None)
        # Les erreurs D portant sur des prestations visent la facture de prestations
        for e in self.errors:
            if e["ctrl"][0] == "D" and e["ctrl"] not in ("D8",):
                e["docs"] = ["ft2" if x == "ft1" else x for x in e["docs"]]
        self.add(ft2)
        self.fts.append(ft2)
        self.tags.append("factures_debours_et_prestations_separees")

    def _inject_ft(self, ft):
        rng = self.rng
        dec = self.dec1
        fam = ft["family"]
        lang = fam_lang(fam)
        mrn = dec["mrn"]

        def find(nature, m=mrn):
            return next((ln for ln in ft["lines"] if ln["nature"] == nature and ln["mrn"] in (m, None)), None)

        self.notes["excess"] = {}
        if self.has("droits_surfactures") or self.has("faf_sur_excedent") or self.has("avoir_partiel"):
            ln = find("debours_droits")
            if ln is None:
                liq = liquide(dec)
                ln = M.ft_line(fam, "debours_droits", liq["droit"], mrn=mrn)
                ft["lines"].insert(2, ln)
            if self.has("faf_sur_excedent"):
                p = poste(self.grid, "frais_avance_fonds")
                pct = D(p["pourcentage"])
                base = M.faf_base(self.grid, ft["lines"], mrn)
                mn = D(p["minimum"])
                mx = D(p["maximum"]) if p["maximum"] else None
                need = (mn + D("1.00")) * 100 / pct - base
                dl = max(D(150), q2(need) + D(40), q2(ln["ht"] * D("0.25")))
                if mx is not None and pct * (base + dl) / 100 > mx:
                    # sous le plafond : le FAF doit varier avec l'excédent
                    if pct * base / 100 >= mx - 2:
                        dl = D(150)
                    else:
                        dl = max(D(5), q2((mx - D("0.5")) * 100 / pct - base))
                dl = q2(dl)
            elif self.has("avoir_partiel"):
                dl = rng.choice([D("120.00"), D("85.50"), D("300.00")])
            else:
                big = rng.random() < 0.8
                dl = rng.choice([D("45.00"), D("118.60"), D("250.00"), D("12.90"), q2(ln["ht"] * D("0.2") + 5)]) if big else rng.choice([D("1.80"), D("2.40")])
            ln["ht"] = ln["ht"] + dl
            ln["pu"] = ln["ht"]
            self.notes["excess"]["droit"] = dl
        if self.has("autres_taxes_surfacturees"):
            ln = find("debours_autres_taxes")
            dl = rng.choice([D("35.00"), D("64.10"), D("150.00"), D("2.20")])
            ln["ht"] += dl
            ln["pu"] = ln["ht"]
            self.notes["excess"]["autre_taxe"] = dl
        if self.has("tva_refacturee_malgre_autoliquidation"):
            vat = q2(sum((t["montant"] for t in dec["taxes"] if t["cat"] == "tva"), ZERO))
            ft["lines"].insert(len([x for x in ft["lines"] if x["nature"].startswith(("frais_dedouanement", "frais_ligne", "debours"))]),
                               M.ft_line(fam, "debours_tva", vat, mrn=mrn))
            self.notes["excess"]["tva"] = vat
            self.notes["c3"] = vat
        if self.has("tva_surfacturee"):
            ln = find("debours_tva")
            dl = rng.choice([D("40.00"), D("96.30"), D("210.00"), D("1.90")])
            ln["ht"] += dl
            ln["pu"] = ln["ht"]
            self.notes["excess"]["tva"] = dl
        if self.has("debours_combines_surfactures"):
            ln = find("debours_combines")
            dl = rng.choice([D("55.00"), D("130.00"), D("18.75"), D("2.30")])
            ln["ht"] += dl
            ln["pu"] = ln["ht"]
            self.notes["excess"]["combine"] = dl
        if self.has("mrn_cite_inconnu"):
            alien = mrn_fictif(rng, dec["date"].year)
            ft["refs_mrn"] = ft["refs_mrn"] + [alien]
            self.notes["alien_mrn"] = alien
        if self.has("client_facture_different"):
            others = [e for e in self.client["entites"] if e["tva"] != ft["client"]["tva"]]
            if others and rng.random() < 0.6:
                o = rng.choice(others)
                ft["client"] = {"nom": o["raison_sociale"], "tva": o["tva"], "adresse": o["adresse"]}
            else:
                t = rng.choice(self.world["tiers"])
                ft["client"] = {"nom": t["raison_sociale"], "tva": t["tva"], "adresse": t["adresse"]}
        if self.has("ligne_hors_grille"):
            lib = rng.choice(PRESTATIONS_HORS_GRILLE[lang])
            amt = rng.choice([D("18.00"), D("25.00"), D("35.00"), D("49.90"), D("75.00")])
            ft["lines"].append(M.ft_line(fam, "autre_prestation", amt, libelle=lib))
            self.notes["d2"] = amt
        avoir_trap = (self.attrs.get("avoir_trap") and not self.has("prix_superieur_grille") and FAMCAP[fam]["avoir"]
                      and not self.ctrl_in("E1", "E2", "E3", "E4", "E5", "E6"))
        self.notes["avoir_trap"] = avoir_trap
        if self.has("prix_superieur_grille") or self.has("avoir_sans_reference") or self.has("avoir_double") or self.has("avoir_total_faux") or avoir_trap:
            ln = find("frais_dedouanement")
            if self.has("prix_superieur_grille"):
                big = rng.random() < 0.8
                dl = rng.choice([D("5.00"), D("10.00"), D("15.00"), D("20.00")]) if big else rng.choice([D("0.20"), D("0.25")])
            else:
                dl = rng.choice([D("10.00"), D("15.00"), D("20.00")])
            ln["pu"] = ln["pu"] + dl
            ln["ht"] = q2(ln["pu"] * ln["qty"])
            self.notes["d3"] = dl
        if self.has("faf_hors_grille"):
            big = rng.random() < 0.8
            dl = rng.choice([D("5.00"), D("8.50"), D("12.00"), D("25.00")]) if big else D("0.20")
            ft["faf_overrides"][mrn] = dl
            self.notes["d4"] = dl
        if self.has("ligne_doublee"):
            ln = find("frais_dedouanement")
            src = next((x for x in ft["lines"] if x["nature"] in ("transport", "manutention", "autre_prestation") and x["ht"] > 0), ln)
            dup = dict(src)
            ft["lines"].insert(ft["lines"].index(src) + 1, dup)
            self.notes["d5"] = src["ht"]
        if self.has("magasinage_excessif"):
            ln = find("magasinage")
            pm = poste(self.grid, "magasinage")
            days = (ln["date_fin"] - ln["date_debut"]).days + 1
            ln["qty"] = D(days)
            ln["ht"] = q2(ln["pu"] * ln["qty"])
            self.notes["d6"] = q2(D(pm["prix"]) * int(pm["franchise_jours"]))
        if self.has("surcharge_non_prevue"):
            amt = rng.choice([D("15.00"), D("22.50"), D("35.00"), D("45.00")])
            ft["lines"].append(M.ft_line(fam, "surcharge", amt, libelle=SURCHARGES_HORS_GRILLE[lang]))
            self.notes["d7"] = amt
        if self.has("tva_sur_debours"):
            ln = find("debours_droits") or find("debours_autres_taxes") or find("debours_tva") or find("debours_forfait_petits_envois")
            ln["vat_rate"] = D(20)
            self.notes["d8_line"] = ln
        if self.has("lignes_supplementaires_excessives"):
            pl = poste(self.grid, "frais_ligne_supplementaire")
            k = rng.choice([1, 2, 3])
            ln = find("frais_ligne_supplementaire")
            if ln is None:
                ln = M.ft_line(fam, "frais_ligne_supplementaire", ZERO, qty=D(0), pu=D(pl["prix"]), mrn=mrn)
                ft["lines"].insert(1, ln)
            ln["qty"] = ln["qty"] + k
            ln["ht"] = q2(ln["qty"] * D(pl["prix"]))
            self.notes["d9"] = q2(D(pl["prix"]) * k)
        # Petits envois
        if self.has("forfait_surfacture"):
            ln = find("debours_forfait_petits_envois")
            dl = rng.choice([D("6.00"), D("9.00"), D("12.00")])
            ln["ht"] += dl
            ln["base_info"] = None
            ln["qty"] = D(1)
            ln["pu"] = ln["ht"]
            self.notes["g4"] = dl
        if self.has("forfait_unites_au_lieu_articles"):
            ln = find("debours_forfait_petits_envois")
            ftax = next(t for t in dec["taxes"] if t["cat"] == "forfait_petits_envois")
            units = int(sum((ln_["qty"] for ci in dec["cis"] for ln_ in self.docs[ci]["lines"]), ZERO))
            base = int(ftax["base_qty"])
            if units <= base:
                units = base + 2
            ln["base_info"] = (ftax["rate"], units)
            ln["qty"] = D(units)
            ln["pu"] = ftax["rate"]
            ln["ht"] = q2(ftax["rate"] * units) + (ftax["montant"] - q2(ftax["rate"] * ftax["base_qty"]))
            self.notes["g5"] = q2((units - base) * ftax["rate"])

    def _post_ft_errors(self, ft):
        """Erreurs C/D/G de la facture transitaire, montants calculés après finalisation."""
        dec = self.dec1
        dd = [ft["doc_id"], dec["doc_id"]]
        ex = self.notes["excess"]
        mrn_ok = True
        if "droit" in ex and (self.has("droits_surfactures") or self.has("faf_sur_excedent") or self.has("avoir_partiel")):
            # avoir_partiel : l'écart C1 reste dû (montant net de l'avoir, fixé dans _inject_post)
            self.err("droits_surfactures",
                     dd, ex["droit"], [f"{ft['doc_id']}.lignes.montant_ht"], "Droits refacturés supérieurs aux droits liquidés.",
                     {"abs": ex["droit"], "seuil": D(1), "links": mrn_ok, "gross": ex["droit"]}, ctrl="C1")
        if "autre_taxe" in ex:
            self.err("autres_taxes_surfacturees", dd, ex["autre_taxe"], [], "Autres taxes refacturées supérieures aux montants liquidés.",
                     {"abs": ex["autre_taxe"], "seuil": D(1)})
        if self.has("tva_refacturee_malgre_autoliquidation"):
            self.err("tva_refacturee_malgre_autoliquidation", dd, ex["tva"], [f"{dec['doc_id']}.indices_autoliquidation"],
                     "TVA à l'importation refacturée alors que la déclaration indique l'autoliquidation.",
                     {"abs": ex["tva"], "seuil": D(1)})
        if self.has("tva_surfacturee"):
            self.err("tva_surfacturee", dd, ex["tva"], [], "TVA à l'importation refacturée supérieure à la TVA liquidée.",
                     {"abs": ex["tva"], "seuil": D(1)})
        if "combine" in ex:
            self.err("debours_combines_surfactures", dd, ex["combine"], [], "Montant « droits et taxes » refacturé supérieur au total liquidé.",
                     {"abs": ex["combine"], "seuil": D(1)})
        if self.has("mrn_cite_inconnu"):
            self.err("mrn_cite_inconnu", [ft["doc_id"]], None, [f"{ft['doc_id']}.refs_mrn"], "MRN cité sans déclaration correspondante dans le dossier.")
        if self.has("client_facture_different"):
            self.err("client_facture_different", [ft["doc_id"], dec["doc_id"]], None, [f"{ft['doc_id']}.client_facture.tva"],
                     "La facture du transitaire est adressée à une autre entité que l'importateur.", {"nonnum": True})
        if self.has("ligne_hors_grille"):
            lvl_ok = self.grid["prestations_hors_grille"] == "interdites"
            self.err("ligne_hors_grille", [ft["doc_id"]], self.notes["d2"], [], "Prestation absente de la grille tarifaire.",
                     {"abs": self.notes["d2"], "seuil": D("0.10"), "force_av": not lvl_ok})
        if self.has("prix_superieur_grille"):
            self.err("prix_superieur_grille", [ft["doc_id"]], self.notes["d3"], [], "Frais de dédouanement supérieurs à la grille.",
                     {"abs": self.notes["d3"], "seuil": D("0.10")})
        if self.has("faf_hors_grille"):
            self.err("faf_hors_grille", [ft["doc_id"]], self.notes["d4"], [], "Frais d'avance de fonds supérieurs au calcul de la grille.",
                     {"abs": self.notes["d4"], "seuil": D("0.10")})
        if self.has("ligne_doublee"):
            self.err("ligne_doublee", [ft["doc_id"]], self.notes["d5"], [], "Ligne de prestation facturée deux fois dans la même facture.",
                     {"abs": self.notes["d5"], "seuil": D("0.10")})
        if self.has("magasinage_excessif"):
            self.err("magasinage_excessif", [ft["doc_id"]], self.notes["d6"], [], "Jours de franchise de magasinage facturés.",
                     {"abs": self.notes["d6"], "seuil": D("0.10")})
        if self.has("surcharge_non_prevue"):
            lvl_ok = self.grid["prestations_hors_grille"] == "interdites"
            self.err("surcharge_non_prevue", [ft["doc_id"]], self.notes["d7"], [], "Surcharge absente de la grille.",
                     {"abs": self.notes["d7"], "seuil": D("0.10"), "force_av": not lvl_ok})
        if self.has("tva_sur_debours"):
            ln = self.notes["d8_line"]
            self.err("tva_sur_debours", [ft["doc_id"]], ln["vat"], [], "TVA facturée sur une ligne de débours.")
        if self.has("lignes_supplementaires_excessives"):
            self.err("lignes_supplementaires_excessives", [ft["doc_id"], dec["doc_id"]], self.notes["d9"], [],
                     "Lignes supplémentaires facturées au-delà du nombre d'articles de la déclaration.",
                     {"abs": self.notes["d9"], "seuil": D("0.10")})
        if self.has("forfait_surfacture"):
            self.err("forfait_surfacture", dd, self.notes["g4"], [], "Forfait petits envois refacturé supérieur au forfait liquidé.",
                     {"abs": self.notes["g4"], "seuil": D(1)})
        if self.has("forfait_unites_au_lieu_articles"):
            self.err("forfait_unites_au_lieu_articles", dd, self.notes["g5"], [],
                     "Le transitaire a compté des unités au lieu d'articles pour le forfait.", {"abs": self.notes["g5"], "seuil": D(1)})

    # ------------------------------------------------------------------
    def _c6(self):
        """C6 : FAF calculé sur des débours en écart (induit par tout excédent de débours, net des avoirs)."""
        if not self.fts:
            return
        dec = self.dec1
        ex = {}
        for e in self.errors:
            if e["ctrl"] in ("C1", "C2", "C3", "C4", "C5") and e["amount"] is not None and e["amount"] > 0:
                # excédent BRUT : un avoir partiel crédite les droits, pas le FAF calculé sur l'excédent
                ex[e["ctrl"]] = e["li"].get("gross", e["amount"])
        if not ex:
            if self.has("faf_sur_excedent"):
                raise RuntimeError(f"{self.did}: C6 sans excédent")
            return
        faf_ft = next((f for f in self.fts if any(ln["nature"] == "frais_avance_fonds" and ln["mrn"] == dec["mrn"] for ln in f["lines"])), None)
        if faf_ft is None:
            return
        faf = next(ln for ln in faf_ft["lines"] if ln["nature"] == "frais_avance_fonds" and ln["mrn"] == dec["mrn"])
        p = poste(self.grid, "frais_avance_fonds")
        excess_base = sum(ex.values(), ZERO)
        if p["base_pourcentage"] == "debours_hors_tva":
            excess_base -= ex.get("C3", ZERO) + ex.get("C4", ZERO)
        retained = M.faf_amount(self.grid, faf["faf_base"] - excess_base)
        billed = faf["ht"] - faf_ft["faf_overrides"].get(dec["mrn"], ZERO)
        exc = billed - retained
        docs = sorted({self.fts[0]["doc_id"], faf_ft["doc_id"]}) + [dec["doc_id"]]
        if exc > D("0.01"):
            self.err("faf_sur_excedent", docs, exc, [f"{faf_ft['doc_id']}.lignes.frais_avance_fonds"],
                     "Frais d'avance de fonds calculés sur des débours refacturés en écart.",
                     {"abs": exc, "seuil": D("0.10"), "depends_certain": True}, ctrl="C6")
        else:
            # (2.1) FAF au plafond de la grille : l'excédent injecté ne change pas le FAF -> pas de C6, piège
            # (chemin jamais atteint par les corpus 2.0.x, qui levaient une erreur ici)
            self.trap("C6", docs, "conforme", "FAF au minimum (ou au plafond) : l'excédent de débours ne change pas le FAF.")

    def _total_faux(self):
        if not self.has("total_faux") or not self.fts:
            return
        fam = self.spec["family"]
        ft = self.fts[-1] if FAMCAP[fam].get("split_invoices") and len(self.fts) > 1 else self.fts[0]
        which = self.rng.choice(["total_ht", "total_ttc"])
        dl = self.rng.choice([D("10.00"), D("25.00"), D("100.00"), D("4.60"), D("1.50")])
        ft["total_overrides"] = {which: ft["calc_totals"][which] + dl}
        if which == "total_ht":
            ft["total_overrides"]["total_ttc"] = ft["calc_totals"]["total_ttc"] + dl
        M.finalize_ft(ft, self.grid, None)
        self.err("total_faux", [ft["doc_id"]], dl, [f"{ft['doc_id']}.{which}"], f"{which} imprimé différent de la somme des lignes.",
                 {"abs": dl, "seuil": D(1)})

    def _inject_post(self):
        rng = self.rng
        if not self.fts:
            return
        ft = self.fts[0]
        fam = ft["family"]
        lang = fam_lang(fam)
        srv_ft = self.fts[-1] if FAMCAP[fam].get("split_invoices") and len(self.fts) > 1 else ft
        d_av = add_days(ft["date"], rng.randint(12, 60))

        def av_line(nature, amt, lib=None):
            ln = M.ft_line(fam, nature, amt, libelle=lib)
            return ln

        dd = None
        # Avoir partiel d'un excédent de droits (E6)
        if self.has("avoir_partiel"):
            dl = self.notes["excess"]["droit"]
            p = q2(dl * self.rng.choice([D("0.4"), D("0.5"), D("0.6")]))
            av = M.make_avoir(self.ctx, rng, doc_id="av1", ft=ft, d_av=d_av, lines=[av_line("debours_droits", p)],
                              motif="Régularisation partielle droits de douane")
            self.add(av)
            reste = dl - p
            for e in self.errors:
                if e["ctrl"] == "C1":
                    e["amount"] = reste
                    e["li"]["abs"] = reste
                    e["desc"] += f" Avoir partiel de {p} déjà reçu."
            self.err("avoir_partiel", ["av1", ft["doc_id"]], reste, [], "Écart de droits couvert partiellement par un avoir.",
                     {"abs": reste})
            self.notes["e6_reste"] = reste
            self.tags.append("avoir")
        # Avoir sans référence (E1) qui solde un écart de prix
        if self.has("avoir_sans_reference"):
            av = M.make_avoir(self.ctx, rng, doc_id="av1", ft=srv_ft, d_av=d_av,
                              lines=[av_line("frais_dedouanement", self.notes["d3"])], with_ref=False,
                              motif="Ajustement tarif dédouanement")
            self.add(av)
            self.err("avoir_sans_reference", ["av1"], None, [], "Avoir sans référence de facture d'origine (seulement MRN et LTA).")
            self.trap("D3", [srv_ft["doc_id"]], "a_verifier", "Écart de prix soldé par un avoir rattaché seulement par le MRN.")
            self.tags.append("avoir")
        if self.has("avoir_excessif"):
            ln = next(x for x in srv_ft["lines"] if x["nature"] == "frais_dedouanement")
            amt = q2(ln["ht"] * 2)
            av = M.make_avoir(self.ctx, rng, doc_id="av1", ft=srv_ft, d_av=d_av, lines=[av_line("frais_dedouanement", amt)],
                              motif="Annulation frais de dédouanement")
            self.add(av)
            self.err("avoir_excessif", ["av1", srv_ft["doc_id"]], None, [], f"Avoir de {amt} sur des frais facturés {ln['ht']}.")
            self.err("avoir_excessif", ["av1", srv_ft["doc_id"]], None, [], "Reliquat d'avoir sans écart ouvert correspondant.", ctrl="E5")
            self.tags.append("avoir")
        if self.has("avoir_double") or self.has("avoir_total_faux") or self.notes.get("avoir_trap"):
            av = M.make_avoir(self.ctx, rng, doc_id="av1", ft=srv_ft, d_av=d_av, lines=[av_line("frais_dedouanement", self.notes["d3"])],
                              motif="Rectification tarif")
            if self.has("avoir_total_faux"):
                dl = self.rng.choice([D("10.00"), D("5.00"), D("20.00")])
                av["total_overrides"] = {"total_ttc": av["total_ttc"] + dl, "total_ht": av["total_ht"] + dl}
                self.err("avoir_total_faux", ["av1"], None, [], "Total de l'avoir différent de la somme de ses lignes.")
            self.add(av)
            if self.has("avoir_double"):
                av2 = copy.deepcopy(av)
                av2["doc_id"] = "av1b"
                self.add(av2)
                self.notes["av_double"] = True
                self.err("avoir_double", ["av1", "av1b"], None, [], "Même avoir reçu deux fois (deux fichiers).")
            if not self.has("prix_superieur_grille"):
                self.trap("D3", [srv_ft["doc_id"]], "conforme", "Écart de prix entièrement soldé par un avoir.")
            self.tags.append("avoir")
        if self.has("avoir_sans_ecart"):
            p = poste(self.grid, "autre_prestation")
            amt = q2(D(p["prix"]) / 2) if p else D("10.00")
            av = M.make_avoir(self.ctx, rng, doc_id="av1", ft=srv_ft, d_av=d_av,
                              lines=[av_line("autre_prestation", amt, {"fr": "Geste commercial", "en": "Goodwill credit", "de": "Kulanzgutschrift", "it": "Abbuono commerciale", "es": "Abono comercial", "nl": "Coulancecredit", **GESTE_EXT}[lang])],
                              motif="Geste commercial")
            self.add(av)
            self.err("avoir_sans_ecart", ["av1", srv_ft["doc_id"]], None, [], "Avoir sans écart ouvert correspondant.")
            self.tags.append("avoir")
        # F4 : seconde facture du même émetteur répétant une prestation
        if self.has("prestation_refacturee"):
            src = next(x for x in srv_ft["lines"] if x["nature"] == "frais_dedouanement")
            ft3 = copy.deepcopy(srv_ft)
            ft3["doc_id"] = "ft3" if "ft2" in self.docs else "ft2"
            ft3["numero"] = M.ft_number(rng, fam, ft["date"])
            ft3["date"] = add_days(ft["date"], rng.randint(8, 30))
            p = poste(self.grid, "transport")
            ft3["lines"] = [dict(src), M.ft_line(fam, "transport", D(p["prix"]))]
            ft3["total_overrides"] = {}
            ft3["title_kind"] = "complement_prestations"
            M.finalize_ft(ft3, self.grid, None)
            self.add(ft3)
            self.fts.append(ft3)
            self.err("prestation_refacturee", [srv_ft["doc_id"], ft3["doc_id"]], src["ht"], [],
                     "Frais de dédouanement refacturés sur une seconde facture pour le même MRN.",
                     {"other": [self.did]})
        if self.has("fichier_double"):
            self.notes["dupfile"] = True

    # ------------------------------------------------------------------
    def _partners(self):
        rng = self.rng
        for code, pid in self.spec["partners"]:
            A = self.registry[pid]
            if code == "numero_reutilise":
                ft = self.fts[0]
                ft["numero"] = A.fts[0]["numero"]
                self.err("numero_reutilise", [ft["doc_id"]], None, [f"{ft['doc_id']}.numero"],
                         f"Numéro de facture du transitaire déjà utilisé dans {pid} pour un autre contenu.", {"other": [pid]})
            elif code == "mrn_refacture_deux_fois":
                Afts = A.fts[0]
                Adec = A.dec1
                fam = self.spec["family"]
                lines = [dict(ln, vat_rate=ZERO) for f in A.fts for ln in f["lines"]
                         if ln["nature"].startswith("debours") and ln["mrn"] in (Adec["mrn"], None)]
                if not lines:
                    liq = liquide(Adec)
                    lines = [M.ft_line(fam, "debours_droits", q2(liq["droit"] + liq["autre_taxe"]), mrn=Adec["mrn"])]
                ftx = {**copy.deepcopy(self.fts[0]), "doc_id": "ftx", "numero": M.ft_number(rng, fam, self.fts[0]["date"]),
                       "date": add_days(max(Afts["date"], self.fts[0]["date"]), rng.randint(3, 20)),
                       "refs_mrn": [Adec["mrn"]], "refs_transport": [Adec["transport"]["ref"]], "refs_ci": [],
                       "lines": lines, "total_overrides": {}, "faf_overrides": {}, "title_kind": "debours", "decls": []}
                ftx["client"] = copy.deepcopy(Afts["client"])
                M.finalize_ft(ftx, self.grid, None)
                self.add(ftx)
                amt = ftx["total_debours"]
                self.notes["f3_other_ft_deg"] = A.docs[Afts["doc_id"]]["deg"]
                self.err("mrn_refacture_deux_fois", ["ftx"], amt, ["ftx.refs_mrn"],
                         f"Débours du MRN {Adec['mrn']} déjà refacturés dans {pid}.",
                         {"abs": amt, "seuil": D(1), "other": [pid], "other_deg": A.docs[Afts['doc_id']]["deg"]})
                for c in ("C7", "P4", "C1", "C4", "C5", "C3"):
                    self.trap(c, ["ftx"], "a_verifier", "Facture de débours d'un autre envoi rangée dans ce dossier.")
                self.tags.append("refacturation_mrn_autre_dossier")
            elif code == "facture_sur_deux_declarations":
                ci = self.ci1
                dec = self.dec1
                amt = q2(A.dec1["montant"] + dec["montant"] - ci["total"])
                self.err("facture_sur_deux_declarations", ["fc1", dec["doc_id"]], amt, [],
                         f"La facture {ci['numero']} est aussi déclarée dans {pid} (MRN {A.dec1['mrn']}).", {"other": [pid]})
                self.trap("F1", ["fc1"], "a_verifier", "Copie de la facture commerciale déjà présente dans un autre dossier.")
                self.tags.append("facture_commerciale_sur_deux_dossiers")

    def _rebase_ft_debours(self, ft, dec):
        liq = liquide(dec)
        nat2cat = {"debours_droits": "droit", "debours_autres_taxes": "autre_taxe", "debours_tva": "tva",
                   "debours_forfait_petits_envois": "forfait_petits_envois"}
        for ln in list(ft["lines"]):
            if ln["nature"] in nat2cat:
                v = liq[nat2cat[ln["nature"]]]
                if v <= 0:
                    ft["lines"].remove(ln)
                else:
                    ln["ht"] = q2(v)
                    ln["pu"] = ln["ht"]
            elif ln["nature"] == "debours_combines":
                ln["ht"] = q2(sum(liq.values(), ZERO))
                ln["pu"] = ln["ht"]
        for cat, nat in (("droit", "debours_droits"), ("tva", "debours_tva"), ("autre_taxe", "debours_autres_taxes")):
            if liq[cat] > 0 and not any(x["nature"] in (nat, "debours_combines") for x in ft["lines"]) and FAMCAP[ft["family"]]["ventile"]:
                ft["lines"].insert(1, M.ft_line(ft["family"], nat, q2(liq[cat]), mrn=dec["mrn"]))
        for ln in ft["lines"]:
            ln.pop("fixed", None)
        M.finalize_ft(ft, self.grid, None)

    def _exclusive(self):
        if self.has("facture_manquante"):
            for d in [x for x in self.order if self.docs[x]["kind"] == "ci"]:
                self.removed.add(d)
            dec = self.dec1
            self.err("facture_manquante", [dec["doc_id"]], None, [], "Aucune facture commerciale dans le dossier.")
        if self.has("declaration_manquante"):
            for d in [x for x in self.order if self.docs[x]["kind"] == "dec"]:
                self.removed.add(d)
            docs = ["fc1"] + ([self.fts[0]["doc_id"]] if self.fts else [])
            self.err("declaration_manquante", docs, None, [], "Aucune déclaration dans le dossier.")
        if self.has("faux_document_facture"):
            ci = self.ci1
            for d in [x for x in self.order if self.docs[x]["kind"] == "ci"]:
                self.removed.add(d)
            fake = {"doc_id": "x1", "kind": "fake", "type": "document_non_exploitable", "sous_type": "pre_alerte",
                    "lang": "en", "ci": ci, "layout": "XPA"}
            self.add(fake)
            self.err("faux_document_facture", ["x1"], None, [], "Document intitulé « invoice » qui est une pré-alerte d'expédition.")
            self.err("faux_document_facture", [self.dec1["doc_id"]], None, [], "Aucune facture commerciale exploitable.", ctrl="P1")

    def _support_docs(self):
        rng = self.rng
        if not self.attrs.get("support_docs") or self.spec["kind"] == "h7" and rng.random() < 0.5:
            return
        ci = self.ci1
        k = 1
        if rng.random() < 0.6:
            self.add({"doc_id": f"sup{k}", "kind": "sup", "type": "document_support", "sous_type": "liste_colisage",
                      "lang": ci["lang"], "ci": ci, "layout": "PL"})
            k += 1
        if rng.random() < 0.5:
            self.add({"doc_id": f"sup{k}", "kind": "sup", "type": "document_support", "sous_type": "titre_transport",
                      "lang": "en", "ci": ci, "layout": "AWB"})
            k += 1
        if self.fts and rng.random() < 0.35:
            self.add({"doc_id": f"sup{k}", "kind": "sup", "type": "document_support", "sous_type": "lettre_accompagnement",
                      "lang": fam_lang(self.spec["family"]), "ft": self.fts[0], "layout": "LTR"})
            k += 1
        if self.fts and rng.random() < 0.25:
            self.add({"doc_id": f"sup{k}", "kind": "sup", "type": "document_support", "sous_type": "conditions_generales",
                      "lang": fam_lang(self.spec["family"]), "ft": self.fts[0], "layout": "CGV"})

    # ------------------------------------------------------------------
    def _traps(self):
        a = self.attrs
        present = [d for d in self.order if d not in self.removed]
        has = lambda d: d in present  # noqa: E731
        dec = self.dec1
        ft = self.fts[0] if self.fts else None
        if self.notes.get("round_trap") and ft:
            self.trap("C1", [ft["doc_id"], dec["doc_id"]], "conforme", "Écart d'arrondi de 0,03 EUR entre droits liquidés et droits refacturés.")
        if a["decl_mode"] == "eur" and dec["rate"] is not None and not self.ctrl_in("A3", "A4", "A5", "A6", "A7", "B3", "F5") and not a.get("freight_trap") and has("fc1"):
            self.trap("A5", ["fc1", dec["doc_id"]], "conforme", "Conversion légitime en EUR au taux imprimé.")
        if dec["rate"] is not None and dec.get("sens") == "eur_par_devise" and not self.ctrl_in("A3", "A4", "A5", "A6", "A7", "B3", "F5") and not a.get("freight_trap") and has("fc1"):
            self.trap("A4", ["fc1", dec["doc_id"]], "conforme", "Taux imprimé dans le sens « 1 unité de devise = x EUR ».")
        if dec["autoliq"] and ft and not self.has("tva_refacturee_malgre_autoliquidation"):
            self.trap("C3", [ft["doc_id"], dec["doc_id"]], "conforme", "TVA autoliquidée non refacturée.")
        if self.notes.get("complementary"):
            self.trap("F3", ["ft1", "ft2"], "conforme", "Facture complémentaire légitime (somme = droits liquidés).")
            self.trap("C1", ["ft1", "ft2", dec["doc_id"]], "conforme", "Facture initiale + complémentaire = droits liquidés.")
        if a.get("freight_trap") and has("fc1"):
            self.trap("A4", ["fc1", dec["doc_id"]], "a_verifier", "Le fret de pied de facture explique l'écart entre total facture et montant déclaré.")
            self.trap("A5", ["fc1", dec["doc_id"]], "a_verifier", "Le fret de pied de facture explique l'écart.")
        if has("fc1") and self.ci1["hs_digits"] == 6 and not self.ctrl_in("A13"):
            self.trap("A13", ["fc1", dec["doc_id"]], "conforme", "Codes à 6 chiffres sur la facture, 10 chiffres sur la déclaration.")
        if has("fc1") and self.ci1["sous_type"] == "pro_forma":
            self.trap("P2", ["fc1"], "conforme", "Facture pro forma acceptée comme référence.")
            self.trap("A14", ["fc1", dec["doc_id"]], "conforme", "Pro forma exclue du contrôle de chronologie.")
        if a.get("trunc_ref") and has("fc1") and not self.has("ref_facture_absente"):
            self.trap("A2", ["fc1", dec["doc_id"]], "conforme", "Référence de facture tronquée mais compatible.")
        if has("fc1") and self.ci1.get("carrier_mention"):
            self.trap("C8", ["fc1"], "conforme", "Transitaire cité comme mode d'expédition sur la facture commerciale.")
            self.trap("D2", ["fc1"], "conforme", "Transitaire cité comme mode d'expédition sur la facture commerciale.")
        if self.notes.get("rectif") and ft:
            self.trap("C1", [ft["doc_id"], dec["doc_id"], "dec0"], "conforme", "Version rectifiée : seule la dernière version compte.")
            self.trap("C5", [ft["doc_id"], dec["doc_id"], "dec0"], "conforme", "Version rectifiée : ne pas additionner les versions.")
        if a.get("duty_euro_round") and not self.has("taxe_base_taux_incoherente"):
            self.trap("B1", [dec["doc_id"]], "conforme", "Droits arrondis à l'euro (tolérance T_TAXE_LIGNE).")
        if self.notes.get("discount") and ft:
            self.trap("D2", [ft["doc_id"]], "conforme", "Remise commerciale négative : pas une prestation hors grille.")
            self.trap("D1", [ft["doc_id"]], "conforme", "Ligne de remise négative incluse dans les totaux.")
        if ft and ft.get("transport_ref_style") in ("spaced", "slashed") and not self.has("mrn_cite_inconnu"):
            self.trap("C7", [ft["doc_id"]], "conforme", "Référence de transport imprimée avec espaces ou barres.")
        if self.spec["kind"] == "h7" and not self.ctrl_in("G2", "G3"):
            self.trap("G2", [dec["doc_id"]], "conforme", "Base du forfait = nombre d'articles.")
            self.trap("G3", [dec["doc_id"]], "conforme", "Base du forfait = nombre de codes distincts.")
        if self.ctrl_in("A1") and ft:
            self.trap("C8", [ft["doc_id"]], "a_verifier", "Transitaire facturant l'entité importatrice déclarée.")
        if self.spec.get("ext"):
            self._ext_traps(ft, dec, has)

    def _ext_traps(self, ft, dec, has):
        ci = self.ci1 if has("fc1") else None
        if self.entity.get("fiscal_rep"):
            if ci:
                self.trap("A1", ["fc1", dec["doc_id"]], "conforme",
                          "Importateur suisse : n° TVA FR obtenu via un représentant fiscal (TVA du représentant aussi imprimée).")
            if ft:
                self.trap("C8", [ft["doc_id"]], "conforme", "Facture adressée à l'importateur « c/o » son représentant fiscal.")
        if ci and ci.get("destinataire"):
            self.trap("A1", ["fc1", dec["doc_id"]], "conforme", "Livré à une autre entité du groupe ; facturé à l'importateur.")
        if ci and (ci["acheteur"].get("tva_affichee") or ci["acheteur"].get("nom_affiche")):
            self.trap("A1", ["fc1", dec["doc_id"]], "conforme", "Acheteur sous son enseigne ou TVA imprimée avec espaces.")
        if ci and ci.get("equiv"):
            self.trap("A3", ["fc1", dec["doc_id"]], "conforme", "Contre-valeur indicative dans une autre devise sur la facture.")
        if ci and ci["layout"] == "CM" and len(ci["lines"]) > 20:
            self.trap("A4", ["fc1", dec["doc_id"]], "conforme", "Facture multipage : les totaux de page ne sont pas le total.")
        for f in self.fts:
            fam = f["family"]
            if fam in VAT_INCLUSIVE_FAMILIES:
                self.trap("D1", [f["doc_id"]], "conforme", "Lignes de prestation exprimées TTC (TVA incluse).")
            if FAMCAP[fam].get("summary_page"):
                self.trap("D1", [f["doc_id"]], "conforme", "Totaux sur une page récapitulative séparée.")
            if any(ln.get("pu") is not None and ln["nature"] in ("transport", "manutention") and ln["qty"] > 1
                   and poste(self.grid, ln["nature"]) and poste(self.grid, ln["nature"]).get("unite_base") == "kg"
                   for ln in f["lines"]):
                self.trap("D3", [f["doc_id"]], "conforme", "Prestation tarifée au kg : quantité = masse brute arrondie.")

    def _links(self):
        present = [d for d in self.order if d not in self.removed]
        for sh in self.shipments:
            for dec in sh["decls"]:
                if dec["doc_id"] not in present:
                    continue
                for c in dec["cis"]:
                    if c in present:
                        self.links.append({"from": c, "to": dec["doc_id"], "role": "declaration"})
            for ci in sh["cis"]:
                pass
        if "dec0" in present and "fc1" in present:
            self.links.append({"from": "fc1", "to": "dec0", "role": "declaration"})
        for ft in self.fts:
            if ft["doc_id"] not in present:
                continue
            for dec in [d for sh in self.shipments for d in sh["decls"]]:
                if dec["doc_id"] in present and dec["mrn"] in ft["refs_mrn"] or (dec["doc_id"] in present and any(ln["mrn"] == dec["mrn"] for ln in ft["lines"])):
                    self.links.append({"from": ft["doc_id"], "to": dec["doc_id"], "role": "facture_transitaire"})
        for d in present:
            doc = self.docs[d]
            if doc["kind"] == "av":
                origin = next((f for f in self.fts if f["numero"] in doc["refs_facture_origine"] or f["refs_mrn"][:1] == doc["refs_mrn"]), None)
                if origin:
                    self.links.append({"from": d, "to": origin["doc_id"], "role": "avoir"})
            if doc["kind"] == "sup":
                tgt = self.dec1["doc_id"] if self.dec1["doc_id"] in present else "fc1"
                self.links.append({"from": d, "to": tgt, "role": "support"})
        # dédoublonnage
        seen = set()
        out = []
        for ln in self.links:
            k = (ln["from"], ln["to"], ln["role"])
            if k not in seen:
                seen.add(k)
                out.append(ln)
        self.links = out

    # ------------------------------------------------------------------
    def _assign_modes(self):
        rng = rng_for(self.seed, self.did, "modes")
        cls = self.spec["deg"]
        order = ["d0", "d1", "d2", "d3"]
        present = [d for d in self.order if d not in self.removed]
        pdfable = []
        for d in present:
            doc = self.docs[d]
            fmt = doc_format(doc)
            doc["format_base"] = fmt
            if fmt in STRUCTURED_FORMATS:
                doc["deg"] = "d0"
                doc["mode"] = "structured"
                continue
            pdfable.append(d)
            if rng.random() < 0.65:
                c = cls
            else:
                c = order[rng.randint(0, order.index(cls))]
            doc["deg"] = c
            doc["mode"] = rng.choice(MODES_EXT[c] if self.spec.get("ext") else MODES[c])
        if pdfable and not any(self.docs[d]["deg"] == cls for d in pdfable):
            d = rng.choice(pdfable)
            self.docs[d]["deg"] = cls
            self.docs[d]["mode"] = rng.choice(MODES_EXT[cls] if self.spec.get("ext") else MODES[cls])
        # copies : même contenu, autre dégradation possible
        if "av1b" in present:
            self.docs["av1b"]["mode"] = rng.choice(MODES["d1"] + MODES["d2"])
            self.docs["av1b"]["deg"] = "d1" if self.docs["av1b"]["mode"] in MODES["d1"] else "d2"
        self.deg_dossier = max((self.docs[d]["deg"] for d in present), key=order.index) if present else "d0"


def doc_format(doc) -> str:
    k = doc["kind"]
    if k == "ci":
        return {"CU": "ubl", "CK": "xlsx"}.get(doc["layout"], "pdf")
    if k == "dec":
        return LAYCAP[doc["layout"]]["format"]
    if k == "ft":
        return FAMCAP[doc["family"]].get("structured") or "pdf"
    return "pdf"


# ---------------------------------------------------------------------------
# Niveaux attendus (§19.3.1, règle mécanique)
# ---------------------------------------------------------------------------

def expected_level(dos: Dossier, e: dict) -> str:
    ctrl = e["ctrl"]
    li = e["li"]
    if ctrl not in CERTAIN_OK or li.get("force_av"):
        return "a_verifier"
    # 2.1 : lignes de prestation TTC (G13) -> montant HT dérivé (§8.5.1-4), au mieux à vérifier
    if ctrl in ("C6", "D2", "D3", "D4", "D5", "D6", "D7", "D9") and any(
            dos.docs.get(d, {}).get("family") in VAT_INCLUSIVE_FAMILIES for d in e["docs"]):
        return "a_verifier"
    # (2) qualité des documents
    for d in e["docs"]:
        doc = dos.docs.get(d)
        if doc is None:
            return "a_verifier"
        if doc.get("final_format") in STRUCTURED_FORMATS or doc.get("format_base") in STRUCTURED_FORMATS:
            continue
        if doc.get("deg") not in ("d0", "d1"):
            return "a_verifier"
    if li.get("other_deg") and li["other_deg"] not in ("d0", "d1"):
        return "a_verifier"
    # (3) ampleur
    if not li.get("nonnum"):
        if "abs" not in li or "seuil" not in li:
            return "a_verifier"
        if abs(li["abs"]) < 3 * li["seuil"]:
            return "a_verifier"
    # (4) substitution de classe de confusion
    if li.get("conf") and is_confusion(*li["conf"]):
        return "a_verifier"
    # (5) liens explicites
    if not links_explicit(dos, e):
        return "a_verifier"
    if li.get("depends_certain"):
        dep = [x for x in dos.errors if x["ctrl"] in ("C1", "C2", "C3", "C4", "C5") and x is not e]
        if not dep or any(expected_level(dos, x) != "ecart_certain" for x in dep):
            return "a_verifier"
    if li.get("iso_needed"):
        ci = dos.docs.get("fc1")
        if ci is None or ci.get("deg") not in ("d0",) and ci.get("format_base") not in STRUCTURED_FORMATS:
            return "a_verifier"
    return "ecart_certain"


def links_explicit(dos: Dossier, e: dict) -> bool:
    ctrl = e["ctrl"]
    fam = ctrl[0]
    if fam == "A":
        dec = next((dos.docs[d] for d in e["docs"] if dos.docs[d]["kind"] == "dec"), None)
        ci = next((dos.docs[d] for d in e["docs"] if dos.docs[d]["kind"] == "ci"), None)
        if dec is None or ci is None:
            return False
        cite = any(r["code"] in ("N380", "N325") for r in dec["refs"])
        return cite
    if fam in ("C", "G", "F") and ctrl not in ("G1", "G2", "G3", "G6"):
        for d in e["docs"]:
            doc = dos.docs[d]
            if doc["kind"] == "ft" and not doc["refs_mrn"]:
                return False
        return True
    return True
