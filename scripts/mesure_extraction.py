#!/usr/bin/env python
"""Mesure de l'exactitude d'extraction sur le banc (outil partagé, SPEC §19.4 « exactitude par champ »).

Pour chaque dossier du split choisi, les documents de vérité (``truth.json`` -> ``documents[]``) du type
demandé sont extraits comme dans le pipeline : texte des pages par l'ingestion
(``controldone.ingest.pages.extraire_pages``, cache disque conseillé), puis extracteur ``structure`` ou
``deterministe`` qui accepte le document. Les champs obtenus sont comparés à ``truth_values`` :

- comparaison normalisée (références sans ponctuation, codes, dates ISO, textes sans accents) ; montants à
  0,005 près, masses à 0,0005 près ;
- listes (``articles[]``, ``taxations[]``, ``lignes[]``) alignées par clé (numéro d'article, type de taxe…)
  puis par rang ;
- résultats : exactitude par champ, par groupe (mise en page / gabarit × dégradation), écarts détaillés et
  **calibration** des confiances (part des valeurs correctes parmi celles de confiance ≥ 0,90).

Exemples ::

    python scripts/mesure_extraction.py --type declaration
    python scripts/mesure_extraction.py --type declaration --groupe L3/d2 --ecarts 50
    python scripts/mesure_extraction.py --type facture_commerciale --dossiers BX0001,BX0002 --json out.json

Les champs comparés par type sont dans ``CHAMPS`` (champs obligatoires de §19.3.1, plus des champs
« extra » signalés comme tels) ; chaque équipe peut compléter la table de son type.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import unicodedata
from collections import Counter, defaultdict
from collections.abc import Iterable
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

RACINE = Path(__file__).resolve().parents[1]
if str(RACINE / "src") not in sys.path:
    sys.path.insert(0, str(RACINE / "src"))

# --- champs comparés ------------------------------------------------------------------------------------------
# (chemin vérité, genre de comparaison, obligatoire). Pour une liste : clé « liste[] » -> sous-champs.
# Genres : montant, masse, decimal, entier, ref, code, date, texte, enum, bool, refs_docs, liste.

CHAMPS: dict[str, dict[str, Any]] = {
    "declaration": {
        "scalaires": [
            ("mrn", "ref", True),
            ("date_acceptation", "date", True),
            ("importateur.tva", "ref", True),
            ("devise_facture", "code", True),
            ("montant_total_facture", "montant", True),
            ("taux_change", "decimal", True),
            ("taux_change_sens", "enum", True),
            ("incoterm", "code", True),
            ("nombre_articles", "entier", True),
            ("total_a_payer", "montant", True),
            ("documents_references", "refs_docs", True),
            ("indices_autoliquidation", "bool", True),
            ("lrn", "ref", False),
            ("version", "entier", False),
            ("importateur.nom", "texte", False),
            ("declarant.tva", "ref", False),
            ("pays_expedition", "code", False),
            ("incoterm_lieu", "texte", False),
            ("masse_brute_totale", "masse", False),
            ("nombre_colis_total", "entier", False),
            ("total_droits_taxes", "montant", False),
        ],
        "listes": {
            "articles": {
                "cle": ["numero_article"],
                "champs": [
                    ("code_marchandise", "code", True),
                    ("pays_origine", "code", True),
                    ("masse_nette", "masse", True),
                    ("masse_brute", "masse", True),
                    ("numero_article", "entier", False),
                    ("montant_facture_article", "montant", False),
                    ("valeur_statistique", "montant", False),
                    ("nombre_colis", "entier", False),
                    ("quantite_unite_supplementaire", "decimal", False),
                ],
            },
            "taxations": {
                "cle": ["article", "type_taxe"],
                "champs": [
                    ("article", "entier", True),
                    ("type_taxe", "code", True),
                    ("categorie", "enum", True),
                    ("base_montant", "montant", True),
                    ("base_quantite", "decimal", True),
                    ("taux", "decimal", True),
                    ("montant", "montant", True),
                    # ``mode_paiement`` n'est pas comparé : la vérité porte la lettre canonique (A/E/G) alors que
                    # certaines éditions impriment un statut chiffré (0/1/7) ; ``paiement_normalise`` fait foi.
                    ("paiement_normalise", "enum", True),
                    ("taux_nature", "enum", False),
                ],
            },
        },
    },
    "facture_commerciale": {
        "scalaires": [
            ("numero", "ref", True),
            ("date", "date", True),
            ("devise", "code", True),
            ("total_facture", "montant", True),
            ("total_imprime", "bool_valeur", True),
            ("acheteur.tva", "ref", True),
            ("incoterm", "code", True),
            ("masse_brute_totale", "masse", True),
            ("nombre_colis", "entier", True),
            ("masse_nette_totale", "masse", False),
            ("ref_transport", "ref", False),
            ("incoterm_lieu", "texte", False),
            ("acheteur.nom", "texte", False),
            ("vendeur.nom", "texte", False),
            ("sous_totaux", "sous_totaux", False),
        ],
        "listes": {
            "lignes": {
                "cle": ["numero_ligne"],
                "champs": [
                    ("code_marchandise_imprime", "code", True),
                    ("quantite", "decimal", True),
                    ("unite", "code", True),
                    ("montant_ligne", "montant", True),
                    ("pays_origine", "code", True),
                    ("prix_unitaire", "montant", False),
                    ("masse_nette", "masse", False),
                    ("masse_brute", "masse", False),
                    ("reference_article", "ref", False),
                ],
            },
        },
    },
    "document_support": {
        # vérité : ``ref_transport`` (maître ou maison), masses et colis des titres de transport et listes de
        # colisage, ``refs_facture`` ; lettres, conditions générales et courriels n'ont que leur sous-type
        "scalaires": [
            ("ref_transport", "ref_transport_support", True),
            ("masse_brute", "masse", True),
            ("nombre_colis", "entier", True),
            ("masse_taxable", "masse", True),
            ("refs_facture", "refs", True),
        ],
        "listes": {},
    },
    "facture_transitaire": {
        "scalaires": [
            ("numero", "ref", True),
            ("date", "date", True),
            ("emetteur.tva", "ref", True),
            ("client_facture.tva", "ref", True),
            ("refs_mrn", "refs", True),
            ("refs_transport", "refs", True),
            ("total_debours", "montant", True),
            ("total_ht", "montant", True),
            ("total_tva", "montant", True),
            ("total_ttc", "montant", True),
        ],
        "listes": {
            "lignes": {
                # lignes d'un relevé : l'ordre imprimé (colonnes par nature) n'est pas celui de la vérité
                "cle": [],
                "apparier": "contenu",
                "champs": [
                    ("nature", "enum", True),
                    ("libelle", "libelle", True),
                    ("quantite", "decimal", True),
                    ("prix_unitaire", "montant", True),
                    ("montant_ht", "montant", True),
                    ("taux_tva", "decimal", True),
                    ("montant_tva", "montant", True),
                    ("mrn", "ref", True),
                ],
            },
        },
    },
    "avoir": {
        "scalaires": [
            ("numero", "ref", True),
            ("date", "date", True),
            ("refs_facture_origine", "refs", True),
            ("total_credite_ttc", "montant", True),
        ],
        "listes": {
            "lignes": {
                "cle": [],
                "apparier": "contenu",
                "champs": [("nature", "enum", True), ("montant_ht", "montant", True)],
            }
        },
    },
}


# Valeurs « virtuelles » : champ de vérité porté autrement par le modèle (type, chemin générique) -> lecture.
def _virtuel_fc_total_imprime(champs: Any, _chemin: str) -> tuple[Any, float | None, str | None]:
    v = getattr(champs, "total_facture", None)
    if v is None:
        return None, None, None
    return (v.total_origine is None or v.total_origine.value == "imprime"), None, None


def _virtuel_fc_unite(champs: Any, chemin: str) -> tuple[Any, float | None, str | None]:
    try:
        q = champs.obtenir(chemin.rsplit(".", 1)[0] + ".quantite")
    except Exception:
        return None, None, None
    return (None, None, None) if q is None else (q.unite, q.confiance, q.unite_brute)


def _virtuel_fc_sous_totaux(champs: Any, _chemin: str) -> tuple[Any, float | None, str | None]:
    lus = {
        st.type.value: st.montant.valeur
        for st in getattr(champs, "sous_totaux", [])
        if st.montant is not None and st.montant.valeur is not None and st.type.value != "marchandises"
    }
    return lus, None, None


def _virtuel_support_ref(champs: Any, _chemin: str) -> tuple[Any, float | None, str | None]:
    lus = [v for v in (champs.ref_transport_maitre, champs.ref_transport_maison) if v is not None]
    return ([v.valeur for v in lus] or None), (max(v.confiance for v in lus) if lus else None), None


VIRTUELS: dict[tuple[str, str], Any] = {
    ("facture_commerciale", "total_imprime"): _virtuel_fc_total_imprime,
    ("facture_commerciale", "lignes[].unite"): _virtuel_fc_unite,
    ("facture_commerciale", "sous_totaux"): _virtuel_fc_sous_totaux,
    ("document_support", "ref_transport"): _virtuel_support_ref,
}

# Correspondances vérité -> modèle quand les noms diffèrent (type, chemin vérité) -> chemin modèle.
ALIAS: dict[tuple[str, str], str] = {
    ("facture_commerciale", "lignes[].quantite"): "lignes[].quantite",
}


# --- normalisation et comparaison -------------------------------------------------------------------------------


def _sans_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))


def _ref(x: Any) -> str:
    return re.sub(r"[^A-Z0-9]", "", _sans_accents(str(x)).upper())


def _dec(x: Any) -> Decimal | None:
    if x is None or x == "":
        return None
    try:
        return Decimal(str(x))
    except InvalidOperation:
        return None


def egal(genre: str, vrai: Any, lu: Any) -> bool:
    if genre == "sous_totaux":
        # lignes de pied hors marchandises (le sous-total des marchandises n'est pas une charge de pied ; certaines
        # vérités le portent, la lecture ne le compare pas)
        return {k: _dec(x) for k, x in (vrai or {}).items() if k != "marchandises"} == {
            k: _dec(x) for k, x in (lu or {}).items() if k != "marchandises"
        }
    if vrai is None or vrai == "":
        return lu is None or lu == ""
    if lu is None or lu == "":
        return False
    if genre in ("montant", "decimal", "masse"):
        a, b = _dec(vrai), _dec(lu)
        if a is None or b is None:
            return False
        tol = {"montant": Decimal("0.005"), "masse": Decimal("0.0005"), "decimal": Decimal("0.0000005")}[
            genre
        ]
        return abs(a - b) <= tol
    if genre == "entier":
        try:
            return int(Decimal(str(vrai))) == int(Decimal(str(lu)))
        except (InvalidOperation, ValueError):
            return False
    if genre in ("ref", "code", "enum"):
        return _ref(vrai) == _ref(lu)
    if genre == "date":
        return str(vrai)[:10] == str(lu)[:10]
    if genre == "texte":
        return " ".join(_sans_accents(str(vrai)).casefold().split()) == " ".join(
            _sans_accents(str(lu)).casefold().split()
        )
    if genre in ("bool", "bool_valeur"):
        return bool(vrai) == bool(lu)
    if genre == "sous_totaux":
        # lignes de pied hors marchandises (le sous-total des marchandises n'est pas une charge de pied ; certaines
        # vérités le portent, la lecture ne le compare pas)
        return {k: _dec(x) for k, x in (vrai or {}).items() if k != "marchandises"} == {
            k: _dec(x) for k, x in (lu or {}).items() if k != "marchandises"
        }
    if genre == "ref_transport_support":  # la vérité est la référence maître OU maison
        return any(_ref(vrai) == _ref(x) for x in (lu if isinstance(lu, list) else [lu]))
    if genre == "libelle":
        return _libelle_compatible(vrai, lu)
    return str(vrai) == str(lu)


def _libelle_compatible(a: Any, b: Any) -> bool:
    """Libellé de ligne : égalité sans accents ni ponctuation, inclusion (libellé bilingue), ou abréviation
    d'en-tête de colonne imprimée (« Av. fonds » / « Frais d'avance de fonds », « Autres tx »)."""
    x, y = (re.sub(r"[^a-z0-9 ]", " ", _sans_accents(str(v)).casefold()).split() for v in (a, b))
    xs, ys = " ".join(x), " ".join(y)
    if not xs or not ys:
        return False
    if xs == ys or xs in ys or ys in xs:
        return True
    court, long_ = (x, y) if len(xs) <= len(ys) else (y, x)

    def abrege(w: str, w2: str) -> bool:
        it = iter(w2)
        return w2.startswith(w) or (w[0] == w2[0] and all(ch in it for ch in w))

    return all(any(abrege(w, w2) for w2 in long_) for w in court)


@dataclass
class Comparaison:
    dossier: str
    doc_id: str
    groupe: str
    champ: str  # chemin générique (``articles[].masse_brute``)
    chemin: str  # chemin réel
    obligatoire: bool
    vrai: Any
    lu: Any
    confiance: float | None
    brut: str | None
    statut: str  # correct | absent | faux | absent_ok

    def to_dict(self) -> dict:
        return self.__dict__


# --- lecture des valeurs extraites --------------------------------------------------------------------------------


def _valeur(champs: Any, chemin: str, *, signe_imprime: bool = True) -> tuple[Any, float | None, str | None]:
    try:
        v = champs.obtenir(chemin)
    except Exception:
        return None, None, None
    if v is None:
        return None, None, None
    if hasattr(v, "valeur") and hasattr(v, "confiance"):
        valeur = v.valeur
        signe = getattr(v, "signe_imprime", None)
        if (
            signe_imprime
            and valeur is not None
            and signe is not None
            and getattr(signe, "value", signe) == "negatif"
        ):
            valeur = f"-{valeur}"  # la vérité porte le signe imprimé ; le modèle le porte à part (§5.2)
        return valeur, v.confiance, v.valeur_brute
    if hasattr(v, "value"):  # énumération
        return v.value, None, None
    return v, None, None


def _comparer_doc(type_doc: str, champs: Any, verite: dict, base: dict) -> list[Comparaison]:
    spec = CHAMPS[type_doc]
    out: list[Comparaison] = []

    def ajouter(
        champ: str,
        chemin: str,
        genre: str,
        obl: bool,
        vrai: Any,
        lu: Any,
        conf: float | None,
        brut: str | None,
    ) -> None:
        if vrai is None and lu is None:
            statut = "absent_ok"
        elif egal(genre, vrai, lu):
            statut = "correct"
        elif lu is None:
            statut = "absent"
        else:
            statut = "faux"
        out.append(
            Comparaison(
                **base,
                champ=champ,
                chemin=chemin,
                obligatoire=obl,
                vrai=vrai,
                lu=lu,
                confiance=conf,
                brut=brut,
                statut=statut,
            )
        )

    for chemin, genre, obl in spec["scalaires"]:
        if chemin not in verite:
            continue
        vrai = verite[chemin]
        if champs is None:
            ajouter(chemin, chemin, genre, obl, vrai, None, None, None)
            continue
        if genre == "refs_docs":
            lus = set()
            confs = []
            for d in getattr(champs, chemin, []) or []:
                tc = d.type_code.valeur if d.type_code else None
                rf = d.reference.valeur if d.reference else None
                lus.add((_ref(tc), _ref(rf)))
                confs += [x.confiance for x in (d.type_code, d.reference) if x is not None]
            vrais = {(_ref(x.get("type_code")), _ref(x.get("reference"))) for x in vrai or []}
            lu_txt = sorted(f"{a}:{b}" for a, b in lus)
            statut_ok = lus == vrais
            out.append(
                Comparaison(
                    **base,
                    champ=chemin,
                    chemin=chemin,
                    obligatoire=obl,
                    vrai=sorted(f"{a}:{b}" for a, b in vrais),
                    lu=lu_txt or None,
                    confiance=min(confs) if confs else None,
                    brut=None,
                    statut="correct" if statut_ok else ("absent" if not lus else "faux"),
                )
            )
            continue
        if genre == "bool":
            liste = getattr(champs, chemin, None) or []
            lu = bool(liste)
            confs = [i.valeur.confiance for i in liste if getattr(i, "valeur", None) is not None]
            out.append(
                Comparaison(
                    **base,
                    champ=chemin,
                    chemin=chemin,
                    obligatoire=obl,
                    vrai=bool(vrai),
                    lu=lu,
                    confiance=max(confs) if confs else None,
                    brut=None,
                    statut="correct" if bool(vrai) == lu else "faux",
                )
            )
            continue
        if genre == "refs":
            liste = getattr(champs, chemin, None) or []
            lus = {_ref(v.valeur) for v in liste if v is not None and v.valeur}
            vrais = {_ref(x) for x in vrai or []}
            confs = [v.confiance for v in liste if v is not None]
            out.append(
                Comparaison(
                    **base,
                    champ=chemin,
                    chemin=chemin,
                    obligatoire=obl,
                    vrai=sorted(vrais),
                    lu=sorted(lus) or None,
                    confiance=min(confs) if confs else None,
                    brut=None,
                    statut="correct" if lus == vrais else ("absent" if not lus else "faux"),
                )
            )
            continue
        virtuel = VIRTUELS.get((type_doc, chemin))
        lu, conf, brut = (
            virtuel(champs, chemin) if virtuel else _valeur(champs, chemin, signe_imprime=type_doc != "avoir")
        )
        ajouter(chemin, chemin, genre, obl, vrai, lu, conf, brut)

    if type_doc == "declaration" and isinstance(verite.get("totaux_par_type"), dict):
        # D-3101 : totaux imprimés par code de taxe, comparés code par code (champ non obligatoire).
        lus_code = {}
        for t in (getattr(champs, "totaux_par_code", None) or []) if champs is not None else []:
            code = getattr(t.type_taxe, "valeur", None)
            if code and t.montant is not None and code not in lus_code:
                lus_code[code] = t.montant
        for code, vrai in sorted(verite["totaux_par_type"].items()):
            v = lus_code.get(code)
            ajouter(
                "totaux_par_code[].montant",
                f"totaux_par_code[{code}].montant",
                "montant",
                False,
                vrai,
                v.valeur if v is not None else None,
                v.confiance if v is not None else None,
                v.valeur_brute if v is not None else None,
            )

    for nom, lspec in spec["listes"].items():
        vrais = verite.get(nom)
        if vrais is None:
            continue
        lus = list(getattr(champs, nom, []) or []) if champs is not None else []
        paires = (
            _aligner_contenu(vrais, lus)
            if lspec.get("apparier") == "contenu"
            else _aligner(vrais, lus, lspec["cle"], type_doc, nom)
        )
        for iv, il in paires:
            v = vrais[iv]
            for sous, genre, obl in lspec["champs"]:
                if sous not in v:
                    continue
                chemin = f"{nom}[{il}].{sous}" if il is not None else f"{nom}[?].{sous}"
                if il is None or champs is None:
                    ajouter(f"{nom}[].{sous}", chemin, genre, obl, v[sous], None, None, None)
                else:
                    virtuel = VIRTUELS.get((type_doc, f"{nom}[].{sous}"))
                    lu, conf, brut = (
                        virtuel(champs, f"{nom}[{il}].{sous}")
                        if virtuel
                        else _valeur(champs, f"{nom}[{il}].{sous}", signe_imprime=type_doc != "avoir")
                    )
                    ajouter(f"{nom}[].{sous}", chemin, genre, obl, v[sous], lu, conf, brut)
        en_trop = len(lus) - sum(1 for _iv, il in paires if il is not None)
        if en_trop > 0:
            out.append(
                Comparaison(
                    **base,
                    champ=f"{nom}[] (en trop)",
                    chemin=nom,
                    obligatoire=False,
                    vrai=len(vrais),
                    lu=len(lus),
                    confiance=None,
                    brut=None,
                    statut="faux",
                )
            )
    return out


def _cle_lue(element: Any, champs_cle: list[str]) -> tuple:
    out = []
    for c in champs_cle:
        v = getattr(element, c, None)
        v = getattr(v, "valeur", v)
        out.append(_ref(v) if v is not None else None)
    return tuple(out)


def _aligner(
    vrais: list[dict], lus: list[Any], champs_cle: list[str], type_doc: str, nom: str
) -> list[tuple[int, int | None]]:
    """Paires (index vérité, index lu). Par clé (avec rang d'occurrence) puis par rang pour le reste."""
    libres = set(range(len(lus)))
    paires: dict[int, int] = {}
    if champs_cle:
        occ_l: dict[tuple, list[int]] = defaultdict(list)
        for i, e in enumerate(lus):
            occ_l[_cle_lue(e, champs_cle)].append(i)
        occ_v: Counter = Counter()
        for iv, v in enumerate(vrais):
            k = tuple(_ref(v.get(c)) if v.get(c) is not None else None for c in champs_cle)
            rang = occ_v[k]
            occ_v[k] += 1
            cands = occ_l.get(k, [])
            if rang < len(cands) and cands[rang] in libres:
                paires[iv] = cands[rang]
                libres.discard(cands[rang])
    for iv in range(len(vrais)):
        if iv in paires:
            continue
        if iv in libres and iv < len(lus):
            paires[iv] = iv
            libres.discard(iv)
    return [(iv, paires.get(iv)) for iv in range(len(vrais))]


def _aligner_contenu(vrais: list[dict], lus: list[Any]) -> list[tuple[int, int | None]]:
    """Appariement glouton par contenu (montant HT, nature, MRN, libellé) puis par rang pour le reste."""

    def lu_de(e: Any, nom: str) -> Any:
        v = getattr(e, nom, None)
        return getattr(v, "valeur", getattr(v, "value", v))

    scores = []
    for iv, v in enumerate(vrais):
        for il, e in enumerate(lus):
            sc = 0
            if v.get("montant_ht") is not None and egal("montant", v["montant_ht"], lu_de(e, "montant_ht")):
                sc += 4
            if v.get("nature") and egal("enum", v["nature"], lu_de(e, "nature")):
                sc += 2
            if v.get("mrn") and egal("ref", v["mrn"], lu_de(e, "mrn")):
                sc += 1
            if (
                v.get("libelle")
                and lu_de(e, "libelle")
                and _libelle_compatible(v["libelle"], lu_de(e, "libelle"))
            ):
                sc += 1
            if sc >= 3:
                scores.append((-sc, iv, il))
    paires: dict[int, int] = {}
    pris: set[int] = set()
    for _sc, iv, il in sorted(scores):
        if iv in paires or il in pris:
            continue
        paires[iv] = il
        pris.add(il)
    libres = [i for i in range(len(lus)) if i not in pris]
    for iv in range(len(vrais)):
        if iv not in paires and libres and iv < len(lus) and iv in libres:
            paires[iv] = iv
            libres.remove(iv)
    return [(iv, paires.get(iv)) for iv in range(len(vrais))]


# --- extraction d'un dossier ------------------------------------------------------------------------------------


def _groupe(type_doc: str, truth: dict, doc: dict, par: str | None = None) -> str:
    if par:  # --par langue|sous_type|format|degradation|langue+degradation…
        return "/".join(
            str(doc.get(k) if k != "template" else doc.get("transitaire_template")) for k in par.split("+")
        )
    if type_doc == "declaration":
        lay = truth.get("declaration_layout") or doc.get("sous_type") or "?"
    else:
        lay = doc.get("transitaire_template") or doc.get("sous_type") or doc.get("format") or "?"
    return f"{lay}/{doc.get('degradation', '?')}"


def _extracteurs(type_doc: str, force: str | None) -> list[Any]:
    out: list[Any] = []
    try:
        from controldone.ingest.structure import extracteurs as ext_structure

        out.extend(ext_structure())
    except Exception:
        pass
    try:
        from controldone.extract.deterministe import EXTRACTEURS_DETERMINISTES

        e = EXTRACTEURS_DETERMINISTES.get(type_doc)
        if e is not None:
            out.append(e)
        # extracteur imposé publié sous un autre type (ex. ft_regles traite aussi les avoirs de transitaire)
        out.extend(x for x in EXTRACTEURS_DETERMINISTES.values() if force and x.id == force and x not in out)
    except Exception as ex:  # pragma: no cover
        print(f"registre déterministe indisponible : {ex}", file=sys.stderr)
    if force:
        out = [e for e in out if e.id == force]
    rang = {"structure": 0, "deterministe": 1, "llm": 2}
    return sorted(out, key=lambda e: (rang.get(str(getattr(e, "type", "")), 9), e.id))


def mesurer_dossier(args: dict) -> dict:
    """Extrait et compare les documents d'un dossier (exécuté dans un processus de travail)."""
    from controldone.extract.base import ExtractionContext
    from controldone.ids import IdGenerator
    from controldone.ingest.pages import OptionsPages, extraire_pages
    from controldone.ingest.sniff import detecter_type
    from controldone.model.documents import Document, Fichier, PageRef
    from controldone.model.enums import TypeDocument

    dossier = Path(args["dossier"])
    type_doc = args["type"]
    truth = json.loads((dossier / "truth.json").read_text("utf-8"))
    opts = OptionsPages(cache_dir=args.get("cache") or None, ocr=not args.get("sans_ocr"))
    extracteurs = _extracteurs(type_doc, args.get("extracteur"))
    comparaisons: list[dict] = []
    erreurs: list[str] = []
    durees: list[float] = []
    pages_par_fichier: dict[str, Any] = {}
    for doc in truth.get("documents", []):
        if doc.get("type") != type_doc:
            continue
        groupe = _groupe(type_doc, truth, doc, args.get("par"))
        if args.get("degradation") and doc.get("degradation") not in args["degradation"]:
            continue
        if args.get("groupe") and not re.fullmatch(args["groupe"].replace("*", ".*"), groupe):
            continue
        if args.get("formats") and doc.get("format") not in args["formats"]:
            continue
        chemin = dossier / doc["file"]
        base = {"dossier": truth.get("dossier_id", dossier.name), "doc_id": doc["doc_id"], "groupe": groupe}
        verite = truth.get("truth_values", {}).get(doc["doc_id"], {})
        t0 = time.perf_counter()
        champs = None
        try:
            contenu = chemin.read_bytes()
            mime = detecter_type(contenu)
            if doc["file"] not in pages_par_fichier:
                import hashlib

                fichier = Fichier(
                    nom_original=chemin.name,
                    chemin_relatif=doc["file"],
                    sha256=hashlib.sha256(contenu).hexdigest(),
                    taille=len(contenu),
                    type_mime=mime,
                )
                pages_par_fichier[doc["file"]] = (
                    fichier,
                    extraire_pages(contenu, fichier=fichier, type_mime=mime, options=opts),
                )
            fichier, extraites = pages_par_fichier[doc["file"]]
            numeros = set(doc.get("pages") or [])
            sel = [pe for pe in extraites if not numeros or pe.page.numero in numeros]
            document = Document(
                type=TypeDocument(type_doc),
                sous_type=doc.get("sous_type"),
                pages=[
                    PageRef(fichier_id=fichier.id, numero=pe.page.numero, qualite_texte=pe.page.qualite_texte)
                    for pe in sel
                ],
            )
            pages = [pe.page for pe in sel]
            ctx = ExtractionContext(
                contenu_fichier=contenu,
                type_mime=mime,
                ids=IdGenerator.deterministe(1),
                options={"textes_pages": {pe.page.numero: pe.texte for pe in sel}},
            )
            for e in extracteurs:
                if e.supports(document, pages):
                    r = e.extract(document, pages, ctx)
                    if r.champs is not None:
                        champs = r.champs
                        break
        except Exception as ex:
            erreurs.append(f"{base['dossier']}/{doc['doc_id']}: {type(ex).__name__}: {ex}")
        durees.append(time.perf_counter() - t0)
        comparaisons.extend(c.to_dict() for c in _comparer_doc(type_doc, champs, verite, base))
    return {"comparaisons": comparaisons, "erreurs": erreurs, "durees": durees}


# --- rapport ---------------------------------------------------------------------------------------------------------


def _pct(a: int, b: int) -> str:
    return f"{100 * a / b:6.1f} %" if b else "     — "


def rapport(
    comps: list[dict], *, ecarts: int, par_groupe: bool, tous: bool, cles: Iterable[str] | None = None
) -> str:
    lignes: list[str] = []
    sel = [c for c in comps if tous or c["obligatoire"] or c["champ"].endswith("(en trop)") is False]
    # 1. par champ
    stats: dict[str, Counter] = defaultdict(Counter)
    obligatoire: dict[str, bool] = {}
    for c in sel:
        stats[c["champ"]][c["statut"]] += 1
        obligatoire[c["champ"]] = c["obligatoire"]
    lignes.append("Exactitude par champ (correct = valeur égale ou absente des deux côtés)")
    lignes.append(f"{'champ':44} {'oblig.':>6} {'n':>6} {'exact.':>8} {'absent':>7} {'faux':>6}")
    for champ in sorted(stats, key=lambda k: (not obligatoire[k], k)):
        s = stats[champ]
        n = sum(s.values())
        ok = s["correct"] + s["absent_ok"]
        lignes.append(
            f"{champ:44} {'oui' if obligatoire[champ] else '':>6} {n:6d} {_pct(ok, n):>8} "
            f"{s['absent']:7d} {s['faux']:6d}"
        )
    # 2. par groupe (champs obligatoires)
    grp: dict[str, Counter] = defaultdict(Counter)
    docs_grp: dict[str, set] = defaultdict(set)
    for c in comps:
        if not c["obligatoire"]:
            continue
        grp[c["groupe"]][c["statut"]] += 1
        docs_grp[c["groupe"]].add((c["dossier"], c["doc_id"]))
    lignes.append("")
    lignes.append("Exactitude des champs obligatoires par groupe (mise en page / dégradation)")
    lignes.append(f"{'groupe':16} {'docs':>5} {'valeurs':>8} {'exact.':>8} {'absent':>7} {'faux':>6}")
    for g in sorted(grp):
        s = grp[g]
        n = sum(s.values())
        lignes.append(
            f"{g:16} {len(docs_grp[g]):5d} {n:8d} {_pct(s['correct'] + s['absent_ok'], n):>8} "
            f"{s['absent']:7d} {s['faux']:6d}"
        )
    if par_groupe:
        lignes.append("")
        lignes.append("Exactitude par champ et par groupe")
        groupes = sorted(grp)
        lignes.append(f"{'champ':40} " + " ".join(f"{g[:9]:>9}" for g in groupes))
        mat: dict[tuple[str, str], Counter] = defaultdict(Counter)
        for c in sel:
            mat[(c["champ"], c["groupe"])][c["statut"]] += 1
        for champ in sorted(stats, key=lambda k: (not obligatoire[k], k)):
            cells = []
            for g in groupes:
                s = mat.get((champ, g))
                if not s:
                    cells.append(f"{'':>9}")
                    continue
                n = sum(s.values())
                cells.append(f"{100 * (s['correct'] + s['absent_ok']) / n:8.1f}%")
            lignes.append(f"{champ[:40]:40} " + " ".join(cells))
    # 2 bis. champs clés (*) de §5.3 : leur confiance conditionne un « écart certain »
    if cles:
        cles = sorted(set(cles))
        grp_cles: dict[str, Counter] = defaultdict(Counter)
        for c in comps:
            if c["champ"] in cles:
                grp_cles[c["groupe"]][c["statut"]] += 1
                grp_cles["(tous)"][c["statut"]] += 1
        lignes.append("")
        lignes.append(f"Champs clés ({', '.join(cles)}) par groupe")
        lignes.append(f"{'groupe':16} {'valeurs':>8} {'exact.':>8} {'absent':>7} {'faux':>6}")
        for g in sorted(grp_cles, key=lambda g: (g == "(tous)", g)):
            s_ = grp_cles[g]
            n = sum(s_.values())
            lignes.append(
                f"{g:16} {n:8d} {_pct(s_['correct'] + s_['absent_ok'], n):>8} {s_['absent']:7d} "
                f"{s_['faux']:6d}"
            )
    # 3. calibration
    lignes.append("")
    lignes.append("Calibration des confiances (valeurs lues, toutes comparaisons)")
    lignes.append(f"{'confiance':12} {'valeurs':>8} {'correctes':>10} {'fausses':>8} {'exact.':>8}")
    tranches = [(0.9, 1.01, "≥ 0,90"), (0.8, 0.9, "0,80–0,90"), (0.5, 0.8, "0,50–0,80"), (0.0, 0.5, "< 0,50")]
    for a, b, nom in tranches:
        cs = [
            c
            for c in comps
            if c["confiance"] is not None
            and c["lu"] is not None
            and a <= c["confiance"] < b
            and c["statut"] in ("correct", "faux")
            and not c["champ"].endswith("(en trop)")
        ]
        ok = sum(1 for c in cs if c["statut"] == "correct")
        lignes.append(f"{nom:12} {len(cs):8d} {ok:10d} {len(cs) - ok:8d} {_pct(ok, len(cs)):>8}")
    hauts = [
        c for c in comps if c["confiance"] is not None and c["confiance"] >= 0.9 and c["statut"] == "faux"
    ]
    if hauts:
        lignes.append("")
        lignes.append(f"Valeurs fausses de confiance ≥ 0,90 ({len(hauts)}) :")
        for c in hauts[: max(ecarts, 20)]:
            lignes.append(
                f"  {c['dossier']}/{c['doc_id']} [{c['groupe']}] {c['chemin']}: vrai={c['vrai']!r} "
                f"lu={c['lu']!r} conf={c['confiance']} brut={c['brut']!r}"
            )
    # 4. écarts
    if ecarts:
        lignes.append("")
        faux = [c for c in sel if c["statut"] in ("faux", "absent")]
        lignes.append(f"Écarts ({len(faux)}, {min(ecarts, len(faux))} affichés) :")
        for c in faux[:ecarts]:
            lignes.append(
                f"  {c['dossier']}/{c['doc_id']} [{c['groupe']}] {c['chemin']} ({c['statut']}): "
                f"vrai={c['vrai']!r} lu={c['lu']!r} conf={c['confiance']} brut={c['brut']!r}"
            )
    return "\n".join(lignes)


def _dossiers(corpus: Path, split: str, liste: str | None, limite: int | None) -> list[Path]:
    racine = corpus / split
    ds = sorted(p for p in racine.iterdir() if (p / "truth.json").exists())
    if liste:
        voulus = {x.strip() for x in liste.split(",") if x.strip()}
        ds = [d for d in ds if d.name in voulus]
    return ds[:limite] if limite else ds


def main(argv: Iterable[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--type", required=True, choices=sorted(CHAMPS))
    ap.add_argument("--corpus", default=str(RACINE / "bench" / "corpus"))
    ap.add_argument(
        "--split", default="dev", choices=["dev"], help="seul le split dev est lisible par le moteur"
    )
    ap.add_argument("--dossiers", help="liste BX0001,BX0002…")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--groupe", help="filtre de groupe, ex. L3/d2 ou 'L1/*'")
    ap.add_argument("--formats", help="formats de vérité retenus, ex. pdf_natif,pdf_scan")
    ap.add_argument("--degradation", help="dégradations retenues, ex. d0,d1")
    ap.add_argument(
        "--par",
        help="clé de groupe : langue, sous_type, format, degradation, template "
        "(combinables : langue+degradation) ; défaut : mise en page/dégradation",
    )
    ap.add_argument("--extracteur", help="identifiant d'extracteur imposé")
    ap.add_argument(
        "--cache", default=os.environ.get("CONTROLDONE_PAGES_CACHE_DIR", str(RACINE / "var/cache/pages"))
    )
    ap.add_argument("--sans-ocr", action="store_true")
    ap.add_argument("--workers", type=int, default=1)
    ap.add_argument("--ecarts", type=int, default=40, help="nombre d'écarts listés")
    ap.add_argument("--par-groupe", action="store_true", help="matrice champ × groupe")
    ap.add_argument("--tous", action="store_true", help="inclure les champs non obligatoires dans les écarts")
    ap.add_argument("--json", help="écrire toutes les comparaisons dans ce fichier")
    a = ap.parse_args(list(argv) if argv is not None else None)
    dossiers = _dossiers(Path(a.corpus), a.split, a.dossiers, a.limit)
    taches = [
        {
            "dossier": str(d),
            "type": a.type,
            "cache": a.cache,
            "sans_ocr": a.sans_ocr,
            "groupe": a.groupe,
            "formats": set(a.formats.split(",")) if a.formats else None,
            "extracteur": a.extracteur,
            "degradation": set(a.degradation.split(",")) if a.degradation else None,
            "par": a.par,
        }
        for d in dossiers
    ]
    t0 = time.perf_counter()
    if a.workers > 1:
        with ProcessPoolExecutor(a.workers) as ex:
            resultats = list(ex.map(mesurer_dossier, taches))
    else:
        resultats = [mesurer_dossier(t) for t in taches]
    comps = [c for r in resultats for c in r["comparaisons"]]
    erreurs = [e for r in resultats for e in r["erreurs"]]
    durees = [d for r in resultats for d in r["durees"]]
    print(
        f"{len(dossiers)} dossiers, {len({(c['dossier'], c['doc_id']) for c in comps})} documents "
        f"« {a.type} », {len(comps)} comparaisons, {time.perf_counter() - t0:.1f} s"
        + (f" (extraction moyenne {sum(durees) / len(durees):.2f} s/doc)" if durees else "")
    )
    print()
    try:
        from controldone.model.champs import CHAMPS_CLES
        from controldone.model.enums import TypeDocument

        cles = CHAMPS_CLES.get(TypeDocument(a.type), frozenset())
    except Exception:
        cles = frozenset()
    print(rapport(comps, ecarts=a.ecarts, par_groupe=a.par_groupe, tous=a.tous, cles=cles))
    if erreurs:
        print()
        print(f"Erreurs ({len(erreurs)}) :")
        for e in erreurs[:30]:
            print(f"  {e}")
    if a.json:
        Path(a.json).write_text(json.dumps(comps, ensure_ascii=False, indent=1, default=str), "utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
