"""Correcteur du banc (SPEC §19.4, §19.7, §19.8).

Ne dépend que des contrats JSON : ``truth.json`` (Annexe B) et ``findings.json`` (Annexe C).
"""

from __future__ import annotations

import json
import math
import re
import unicodedata
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Iterable

from .controles import CONTROLES_INTER_DOSSIERS, equivalents, ordre_cle
from .formulations import Formulations, charger_formulations

SCHEMA_METRICS = "controldone.bench.metrics/1.0.0"
VERSION_CORRECTEUR = "1.0.0"

NIVEAUX_CONSTAT = ("ecart_certain", "a_verifier")
RANG_NIVEAU = {"conforme": 0, "a_verifier": 1, "ecart_certain": 2}
Z_95 = 1.959963984540054

# Seuils §19.7
SEUIL_PRECISION_GLOBALE = 0.97
SEUIL_PRECISION_CONTROLE = 0.95
MIN_CONSTATS_CONTROLE = 10
MIN_CONSTATS_PETIT_ECHANTILLON = 30
# Alertes non bloquantes §19.7
ALERTE_COUT_MOYEN_EUR = Decimal("0.30")
ALERTE_DUREE_P95_S = Decimal("300")
ALERTE_BRUIT_PAR_DOSSIER = 1.5

TOL_MONTANT_MIN = Decimal("0.05")
TOL_MONTANT_PCT = Decimal("0.01")
TOL_EXTRACTION_MONTANT = Decimal("0.005")


# ---------------------------------------------------------------------------
# Utilitaires
# ---------------------------------------------------------------------------

class _Invalide:
    """Montant présent mais illisible (compte comme « porte un montant »)."""

    def __repr__(self) -> str:  # pragma: no cover
        return "<montant invalide>"


MONTANT_INVALIDE = _Invalide()


def parse_montant(v: Any) -> Decimal | _Invalide | None:
    if v is None:
        return None
    if isinstance(v, bool):
        return MONTANT_INVALIDE
    try:
        d = Decimal(str(v).strip().replace(" ", ""))
    except (InvalidOperation, ValueError):
        return MONTANT_INVALIDE
    if not d.is_finite():
        return MONTANT_INVALIDE
    return d


def wilson_borne_basse(succes: int, n: int, z: float = Z_95) -> float | None:
    """Borne basse de l'intervalle de Wilson (95 % par défaut). ``None`` si n = 0."""
    if n <= 0:
        return None
    p = succes / n
    z2 = z * z
    centre = p + z2 / (2 * n)
    marge = z * math.sqrt(p * (1 - p) / n + z2 / (4 * n * n))
    return max(0.0, (centre - marge) / (1 + z2 / n))


def ratio(num: int, den: int) -> float | None:
    return None if den == 0 else num / den


def _r(x: float | None, nd: int = 4) -> float | None:
    return None if x is None else round(x, nd)


def norm_chemin(p: str | None) -> str:
    if not p:
        return ""
    s = str(p).replace("\\", "/").strip()
    while s.startswith("./"):
        s = s[2:]
    s = s.lstrip("/")
    if s.startswith("docs/"):
        s = s[5:]
    return s


def norm_ref(v: Any) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(v).upper())


# ---------------------------------------------------------------------------
# Chargement
# ---------------------------------------------------------------------------

@dataclass
class DocVerite:
    dossier_id: str
    doc_id: str
    type: str | None
    file: str
    pages: tuple[int, ...]


@dataclass
class DocProduit:
    dossier_id: str
    document_id: str
    type: str | None
    file: str
    pages: tuple[int, ...] | None  # None = fichier entier


@dataclass
class Constat:
    dossier_id: str
    finding_id: str
    controle_id: str
    niveau: str
    montant_brut: Any
    montant: Decimal | _Invalide | None
    raisons: tuple[str, ...]
    documents: tuple[str, ...]
    brut: dict
    # rempli par l'appariement
    erreur: "Erreur | None" = None
    classe: str | None = None
    motif: str | None = None
    piege: str | None = None
    montant_correct: bool | None = None


@dataclass
class Erreur:
    dossier_id: str
    error_id: str
    control_id: str
    accepted: tuple[str, ...]
    expected_level: str
    montant_brut: Any
    montant: Decimal | _Invalide | None
    nature: str | None
    documents: tuple[str, ...]
    other_dossiers: tuple[str, ...]
    constat: Constat | None = None


@dataclass
class Piege:
    dossier_id: str
    trap_id: str
    control_id: str
    max_level: str
    documents: tuple[str, ...]


@dataclass
class Dossier:
    dossier_id: str
    truth: dict
    docs_verite: dict[str, DocVerite]
    findings: dict | None = None
    statut_findings: str = "absent"  # ok | absent | illisible
    docs_produits: dict[str, DocProduit] = field(default_factory=dict)


def _pages(v: Any) -> tuple[int, ...] | None:
    if v is None:
        return None
    out: list[int] = []
    if isinstance(v, (list, tuple)):
        for x in v:
            if isinstance(x, dict):
                x = x.get("numero", x.get("page"))
            try:
                out.append(int(x))
            except (TypeError, ValueError):
                continue
    elif isinstance(v, int):
        out.append(v)
    return tuple(out)


def charger_corpus(corpus: Path, split: str) -> dict[str, Dossier]:
    racine = corpus / split
    if not racine.is_dir():
        raise FileNotFoundError(f"Split introuvable : {racine}")
    dossiers: dict[str, Dossier] = {}
    for d in sorted(p for p in racine.iterdir() if p.is_dir()):
        tf = d / "truth.json"
        if not tf.is_file():
            continue
        truth = json.loads(tf.read_text(encoding="utf-8"))
        did = truth.get("dossier_id") or d.name
        docs = {}
        for doc in truth.get("documents", []) or []:
            docs[doc["doc_id"]] = DocVerite(
                dossier_id=did, doc_id=doc["doc_id"], type=doc.get("type"),
                file=norm_chemin(doc.get("file")), pages=_pages(doc.get("pages")) or ())
        dossiers[did] = Dossier(dossier_id=did, truth=truth, docs_verite=docs)
    return dossiers


def charger_findings(run: Path, dossiers: dict[str, Dossier]) -> None:
    for did, dos in dossiers.items():
        fp = run / did / "findings.json"
        if not fp.is_file():
            dos.statut_findings = "absent"
            continue
        try:
            data = json.loads(fp.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise ValueError("racine non objet")
        except (ValueError, OSError):
            dos.statut_findings = "illisible"
            continue
        dos.findings = data
        dos.statut_findings = "ok"
        for doc in data.get("documents", []) or []:
            if not isinstance(doc, dict) or not doc.get("document_id"):
                continue
            dos.docs_produits[str(doc["document_id"])] = DocProduit(
                dossier_id=did, document_id=str(doc["document_id"]), type=doc.get("type"),
                file=norm_chemin(doc.get("file")), pages=_pages(doc.get("pages")))


# ---------------------------------------------------------------------------
# Correspondance des documents (§19.4 point 1)
# ---------------------------------------------------------------------------

def correspond(p: DocProduit, t: DocVerite) -> bool:
    """Même dossier, même fichier (relatif à docs/), ≥ 50 % des pages de t dans p."""
    if p.dossier_id != t.dossier_id or p.file != t.file or not p.file:
        return False
    if not t.pages or p.pages is None:
        return True
    communes = len(set(t.pages) & set(p.pages))
    return 2 * communes >= len(set(t.pages))


def recouvrement(p: DocProduit, t: DocVerite) -> float:
    if not correspond(p, t):
        return 0.0
    if not t.pages or p.pages is None:
        return 1.0
    return len(set(t.pages) & set(p.pages)) / len(set(t.pages))


def meilleur_produit(t: DocVerite, produits: Iterable[DocProduit]) -> DocProduit | None:
    """Document produit correspondant le mieux à t (recouvrement, puis pages en trop, puis id)."""
    meilleurs = []
    for p in produits:
        r = recouvrement(p, t)
        if r <= 0:
            continue
        en_trop = 0 if p.pages is None else len(set(p.pages) - set(t.pages))
        meilleurs.append((-r, en_trop, p.document_id, p))
    if not meilleurs:
        return None
    meilleurs.sort(key=lambda x: x[:3])
    return meilleurs[0][3]


class Index:
    """Résolution des identifiants de documents produits et de vérité."""

    def __init__(self, dossiers: dict[str, Dossier]):
        self.dossiers = dossiers
        self.global_produits: dict[str, list[DocProduit]] = {}
        for dos in dossiers.values():
            for p in dos.docs_produits.values():
                self.global_produits.setdefault(p.document_id, []).append(p)

    def docs_constat(self, c: Constat) -> list[DocProduit]:
        dos = self.dossiers[c.dossier_id]
        out: list[DocProduit] = []
        for did in c.documents:
            if did in dos.docs_produits:
                out.append(dos.docs_produits[did])
            else:  # document d'un autre dossier (contrôles F)
                out.extend(self.global_produits.get(did, []))
        return out

    def docs_verite(self, dossier_id: str, refs: Iterable[str]) -> list[DocVerite]:
        out: list[DocVerite] = []
        for ref in refs:
            ref = str(ref)
            did, doc = dossier_id, ref
            m = re.match(r"^(BX[0-9]{4})[/:](.+)$", ref)
            if m:
                did, doc = m.group(1), m.group(2)
            dos = self.dossiers.get(did)
            if dos and doc in dos.docs_verite:
                out.append(dos.docs_verite[doc])
        return out


def chevauchement(produits: list[DocProduit], verites: list[DocVerite]) -> bool:
    return any(correspond(p, t) for p in produits for t in verites)


# ---------------------------------------------------------------------------
# Extraction des constats / erreurs / pièges
# ---------------------------------------------------------------------------

def constats_du_dossier(dos: Dossier) -> list[Constat]:
    if not dos.findings:
        return []
    out: list[Constat] = []
    for i, f in enumerate(dos.findings.get("constats", []) or []):
        if not isinstance(f, dict):
            continue
        niveau = f.get("niveau")
        if niveau not in NIVEAUX_CONSTAT:
            continue
        brut_m = f.get("montant_en_jeu")
        out.append(Constat(
            dossier_id=dos.dossier_id,
            finding_id=str(f.get("finding_id") or f"{dos.dossier_id}#{i}"),
            controle_id=str(f.get("controle_id") or ""),
            niveau=niveau,
            montant_brut=brut_m,
            montant=parse_montant(brut_m),
            raisons=tuple(str(r) for r in (f.get("raisons") or [])),
            documents=tuple(str(d) for d in (f.get("documents_concernes") or [])),
            brut=f,
        ))
    return out


def erreurs_du_dossier(dos: Dossier) -> list[Erreur]:
    out = []
    for e in dos.truth.get("injected_errors", []) or []:
        ctrl = str(e.get("control_id"))
        acc = tuple(e.get("accepted_control_ids") or ()) or equivalents(ctrl)
        out.append(Erreur(
            dossier_id=dos.dossier_id, error_id=str(e.get("error_id")), control_id=ctrl,
            accepted=tuple(str(a) for a in acc), expected_level=str(e.get("expected_level")),
            montant_brut=e.get("expected_amount_eur"),
            montant=parse_montant(e.get("expected_amount_eur")),
            nature=e.get("amount_nature"),
            documents=tuple(str(d) for d in (e.get("documents") or [])),
            other_dossiers=tuple(str(d) for d in (e.get("other_dossiers") or [])),
        ))
    return out


def pieges_du_dossier(dos: Dossier) -> list[Piege]:
    return [Piege(dossier_id=dos.dossier_id, trap_id=str(t.get("trap_id")),
                  control_id=str(t.get("control_id")), max_level=str(t.get("max_level")),
                  documents=tuple(str(d) for d in (t.get("documents") or [])))
            for t in dos.truth.get("traps", []) or []]


# ---------------------------------------------------------------------------
# Appariement (§19.4 points 2 à 5)
# ---------------------------------------------------------------------------

def ecart_montant(c: Constat, e: Erreur) -> Decimal | None:
    if isinstance(c.montant, Decimal) and isinstance(e.montant, Decimal):
        return abs(c.montant - e.montant)
    return None


def tolerance_montant(attendu: Decimal) -> Decimal:
    return max(TOL_MONTANT_MIN, TOL_MONTANT_PCT * abs(attendu))


def est_candidat(c: Constat, e: Erreur, index: Index) -> bool:
    meme_dossier = c.dossier_id == e.dossier_id
    inter = (e.control_id in CONTROLES_INTER_DOSSIERS and c.dossier_id in e.other_dossiers)
    if not (meme_dossier or inter):
        return False
    if c.controle_id not in e.accepted:
        return False
    produits = index.docs_constat(c)
    verites = index.docs_verite(e.dossier_id, e.documents)
    if chevauchement(produits, verites):
        return True
    if inter and not meme_dossier:
        # Les doc_id de e désignent les documents du dossier de l'erreur. Pour un constat posé
        # dans l'autre dossier, on accepte un document de ce dossier qui correspond à un
        # document de vérité du même type que l'un des documents de e.
        types = {t.type for t in verites if t.type}
        autres = [t for t in index.dossiers[c.dossier_id].docs_verite.values() if t.type in types]
        return chevauchement(produits, autres)
    return False


def apparier(constats: list[Constat], erreurs: list[Erreur], index: Index) -> None:
    candidats = []
    for c in constats:
        for e in erreurs:
            if est_candidat(c, e, index):
                d = ecart_montant(c, e)
                # Départage à écart de montant égal (D-901 bis, SPEC §19.4-3) : constat du
                # contrôle principal de l'erreur, puis niveau ecart_certain, puis identifiants.
                cle = ((0, d) if d is not None else (1, Decimal(0)),
                       0 if c.controle_id == e.control_id else 1,
                       0 if c.niveau == "ecart_certain" else 1,
                       e.error_id, c.finding_id, c.dossier_id)
                candidats.append((cle, c, e))
    candidats.sort(key=lambda x: x[0])
    for _, c, e in candidats:
        if c.erreur is None and e.constat is None:
            c.erreur, e.constat = e, c


def montant_correct(c: Constat, e: Erreur, constats_dossier: list[Constat]) -> bool:
    if isinstance(e.montant, Decimal) and isinstance(c.montant, Decimal):
        return abs(c.montant - e.montant) <= tolerance_montant(e.montant)
    if e.montant is None and c.montant is None:
        return True
    if (e.nature == "recouvrable" and c.montant is None and e.montant is not None
            and "doublon_composantes" in c.raisons):
        return any(o is not c and o.erreur is not None and isinstance(o.montant, Decimal)
                   for o in constats_dossier)
    return False


def _piege_pour(c: Constat, pieges: list[Piege], index: Index) -> Piege | None:
    trouves = []
    produits = index.docs_constat(c)
    for t in pieges:
        if t.dossier_id != c.dossier_id:
            continue
        if c.controle_id not in equivalents(t.control_id):
            continue
        if not chevauchement(produits, index.docs_verite(t.dossier_id, t.documents)):
            continue
        trouves.append((RANG_NIVEAU.get(t.max_level, 0), t.trap_id, t))
    if not trouves:
        return None
    trouves.sort(key=lambda x: x[:2])
    return trouves[0][2]


def classer(constats: list[Constat], erreurs: list[Erreur], pieges: list[Piege],
            index: Index) -> None:
    par_dossier: dict[str, list[Constat]] = {}
    for c in constats:
        par_dossier.setdefault(c.dossier_id, []).append(c)
    for c in constats:
        if c.erreur is not None:
            e = c.erreur
            c.montant_correct = montant_correct(c, e, par_dossier[c.dossier_id])
            if c.niveau == "ecart_certain":
                if c.montant_correct:
                    c.classe = "vp_certain"
                else:
                    c.classe, c.motif = "fp_certain", "montant_incorrect"
            else:
                c.classe = "vp_a_verifier"
            continue
        # Constat non apparié à une erreur.
        t = _piege_pour(c, pieges, index)
        if t is not None and RANG_NIVEAU[c.niveau] > RANG_NIVEAU.get(t.max_level, 0):
            c.piege = t.trap_id
            c.classe = "fp_certain" if c.niveau == "ecart_certain" else "fp_a_verifier"
            c.motif = "piege"
            continue
        neutre = _neutre(c, erreurs, index)
        if neutre:
            c.classe, c.motif = neutre
            continue
        if t is not None:  # niveau toléré par le piège (a_verifier sur piège a_verifier)
            c.piege, c.classe, c.motif = t.trap_id, "piege_tolere", "piege"
            continue
        c.classe = "fp_certain" if c.niveau == "ecart_certain" else "fp_a_verifier"
        c.motif = "non_apparie"


def _neutre(c: Constat, erreurs: list[Erreur], index: Index) -> tuple[str, str] | None:
    """Constats non appariés exclus de la précision (ni VP ni FP), voir README."""
    for e in erreurs:
        if e.constat is None or not est_candidat(c, e, index):
            continue
        autre = e.constat
        # Occurrence miroir F3–F5 : l'erreur est déjà appariée à un constat d'un autre
        # dossier cité par l'erreur.
        if (e.control_id in CONTROLES_INTER_DOSSIERS and autre.dossier_id != c.dossier_id):
            return ("miroir_inter_dossiers", e.error_id)
        # Doublon de composantes (§8.6) : montant null + raison doublon_composantes alors
        # qu'un autre constat apparié du même dossier porte le montant.
        if (c.montant is None and "doublon_composantes" in c.raisons
                and e.nature == "recouvrable" and autre.dossier_id == c.dossier_id
                and isinstance(autre.montant, Decimal)):
            return ("redondant_doublon_composantes", e.error_id)
    return None


# ---------------------------------------------------------------------------
# Métriques de contrôle
# ---------------------------------------------------------------------------

def _compteurs() -> dict[str, int]:
    return {k: 0 for k in (
        "n_erreurs", "n_erreurs_certain", "appariees", "appariees_certain_a_certain", "fn",
        "vp_certain", "fp_certain", "fp_certain_non_apparie", "fp_certain_montant",
        "fp_certain_piege", "surclassement", "sous_classement", "appariees_attendu_certain",
        "vp_detection", "appariees_avec_montant", "montant_correct",
        "n_constats", "n_constats_certain", "n_constats_a_verifier",
        "vp_certain_constats", "vp_detection_constats", "fp_a_verifier", "violations_pieges",
        "neutres", "erreurs_p1")}


def _finaliser(c: dict[str, int]) -> dict[str, Any]:
    out: dict[str, Any] = dict(c)
    den = c["vp_certain"] + c["fp_certain"]
    out["precision_certain"] = _r(ratio(c["vp_certain"], den))
    out["precision_certain_wilson_bas"] = _r(wilson_borne_basse(c["vp_certain"], den))
    den_c = c["vp_certain_constats"] + c["fp_certain"]
    out["precision_certain_constats"] = _r(ratio(c["vp_certain_constats"], den_c))
    out["rappel"] = _r(ratio(c["appariees"], c["n_erreurs"]))
    out["rappel_certain"] = _r(ratio(c["appariees_certain_a_certain"], c["n_erreurs_certain"]))
    out["precision_detection"] = _r(ratio(c["vp_detection_constats"], c["n_constats"]))
    out["exactitude_montant"] = _r(ratio(c["montant_correct"], c["appariees_avec_montant"]))
    out["taux_surclassement"] = _r(ratio(c["surclassement"], c["vp_certain"]))
    out["taux_sous_classement"] = _r(ratio(c["sous_classement"], c["appariees_attendu_certain"]))
    out.pop("erreurs_p1", None)
    return out


def metriques_controles(constats: list[Constat], erreurs: list[Erreur], n_dossiers: int):
    glob = _compteurs()
    par: dict[str, dict[str, int]] = {}

    def cp(ctrl: str) -> dict[str, int]:
        return par.setdefault(ctrl, _compteurs())

    for e in erreurs:
        for cpt in (glob, cp(e.control_id)):
            cpt["n_erreurs"] += 1
            if e.expected_level == "ecart_certain":
                cpt["n_erreurs_certain"] += 1
            c = e.constat
            if c is None:
                cpt["fn"] += 1
                continue
            cpt["appariees"] += 1
            cpt["vp_detection"] += 1
            if e.expected_level == "ecart_certain":
                cpt["appariees_attendu_certain"] += 1
                if c.niveau == "ecart_certain":
                    cpt["appariees_certain_a_certain"] += 1
                else:
                    cpt["sous_classement"] += 1
            if e.montant is not None:
                cpt["appariees_avec_montant"] += 1
                if c.montant_correct:
                    cpt["montant_correct"] += 1
            if c.classe == "vp_certain":
                cpt["vp_certain"] += 1
                if e.expected_level == "a_verifier":
                    cpt["surclassement"] += 1

    for c in constats:
        for cpt in (glob, cp(c.controle_id)):
            cpt["n_constats"] += 1
            cpt["n_constats_certain" if c.niveau == "ecart_certain" else "n_constats_a_verifier"] += 1
            if c.erreur is not None:
                cpt["vp_detection_constats"] += 1
            if c.classe == "vp_certain":
                cpt["vp_certain_constats"] += 1
            if c.classe == "fp_certain":
                cpt["fp_certain"] += 1
                cpt[{"montant_incorrect": "fp_certain_montant", "piege": "fp_certain_piege"}
                    .get(c.motif or "", "fp_certain_non_apparie")] += 1
            if c.classe == "fp_a_verifier":
                cpt["fp_a_verifier"] += 1
            if c.motif == "piege" and c.classe in ("fp_certain", "fp_a_verifier"):
                cpt["violations_pieges"] += 1
            if c.classe in ("miroir_inter_dossiers", "redondant_doublon_composantes",
                            "piege_tolere"):
                cpt["neutres"] += 1

    g = _finaliser(glob)
    g["n_dossiers"] = n_dossiers
    g["bruit_a_verifier_par_dossier"] = _r(ratio(glob["fp_a_verifier"], n_dossiers))
    par_ctrl = {k: _finaliser(par[k]) for k in sorted(par, key=ordre_cle)}
    return g, par_ctrl


# ---------------------------------------------------------------------------
# Extraction par champ
# ---------------------------------------------------------------------------

CHAMPS_OBLIGATOIRES: dict[str, tuple[tuple[str, ...], dict[str, tuple[str, ...]]]] = {
    "facture_commerciale": (
        ("numero", "date", "devise", "total_facture", "total_imprime", "acheteur.tva",
         "incoterm", "masse_brute_totale", "nombre_colis"),
        {"lignes": ("code_marchandise_imprime", "quantite", "unite", "montant_ligne",
                    "pays_origine")}),
    "declaration": (
        ("mrn", "date_acceptation", "importateur.tva", "devise_facture", "montant_total_facture",
         "taux_change", "taux_change_sens", "incoterm", "nombre_articles",
         "documents_references", "indices_autoliquidation", "total_a_payer"),
        {"articles": ("code_marchandise", "pays_origine", "masse_nette", "masse_brute"),
         "taxations": ("article", "type_taxe", "categorie", "base_montant", "base_quantite",
                       "taux", "montant", "paiement_normalise")}),
    "facture_transitaire": (
        ("numero", "date", "emetteur.tva", "client_facture.tva", "refs_mrn", "refs_transport",
         "total_debours", "total_ht", "total_tva", "total_ttc"),
        {"lignes": ("nature", "libelle", "quantite", "prix_unitaire", "montant_ht", "taux_tva",
                    "montant_tva", "mrn")}),
    "avoir": (
        ("numero", "date", "refs_facture_origine", "total_credite_ttc"),
        {"lignes": ("nature", "montant_ht")}),
}

CHAMPS_MONTANT = {"total_facture", "montant_ligne", "montant_total_facture", "total_a_payer",
                  "base_montant", "montant", "prix_unitaire", "montant_ht", "montant_tva",
                  "total_debours", "total_ht", "total_tva", "total_ttc", "total_credite_ttc"}
CHAMPS_REFERENCE = {"numero", "mrn", "acheteur.tva", "importateur.tva", "emetteur.tva",
                    "client_facture.tva", "refs_mrn", "refs_transport", "documents_references",
                    "refs_facture_origine"}
CHAMPS_CODE = {"code_marchandise_imprime", "code_marchandise"}

_ABSENT = object()


def _deballer(v: Any) -> Any:
    if isinstance(v, dict) and "valeur" in v:
        return v["valeur"]
    return v


def _get(obj: Any, chemin: str, prefixe: str | None = None) -> Any:
    """Valeur par chemin pointé : clé à plat, clé préfixée par le type, ou imbrication."""
    if not isinstance(obj, dict):
        return _ABSENT
    for cle in (chemin, f"{prefixe}.{chemin}" if prefixe else None):
        if cle and cle in obj:
            return _deballer(obj[cle])
    cur: Any = obj
    for part in chemin.split("."):
        cur = _deballer(cur)
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return _ABSENT
    return _deballer(cur)


def _get_liste(obj: Any, liste: str, i: int, champ: str, prefixe: str | None) -> Any:
    if not isinstance(obj, dict):
        return _ABSENT
    for base in (liste, f"{prefixe}.{liste}" if prefixe else None):
        if not base:
            continue
        for cle in (f"{base}[{i}].{champ}",):
            if cle in obj:
                return _deballer(obj[cle])
        lst = _deballer(obj.get(base, _ABSENT))
        if isinstance(lst, list):
            if i < len(lst):
                return _get(_deballer(lst[i]), champ)
            return _ABSENT
    return _ABSENT


def _sans_accents(s: str) -> str:
    s = unicodedata.normalize("NFKD", s)
    return "".join(c for c in s if not unicodedata.combining(c))


def _bool(v: Any) -> bool | None:
    if isinstance(v, bool):
        return v
    if isinstance(v, (int,)) and v in (0, 1):
        return bool(v)
    if isinstance(v, str):
        s = v.strip().lower()
        if s in ("true", "vrai", "oui", "yes", "1"):
            return True
        if s in ("false", "faux", "non", "no", "0"):
            return False
    return None


def _norm_scalaire(champ: str, v: Any) -> Any:
    feuille = champ.split(".")[-1]
    if champ in CHAMPS_REFERENCE or feuille in ("mrn", "numero"):
        return norm_ref(v)
    if champ in CHAMPS_CODE:
        return re.sub(r"[^0-9]", "", str(v))
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return Decimal(str(v))
    s = re.sub(r"\s+", " ", _sans_accents(str(v))).strip()
    if re.fullmatch(r"-?[0-9]+(\.[0-9]+)?", s):
        return Decimal(s)
    return s.casefold()


def valeurs_egales(champ: str, vrai: Any, produit: Any) -> bool:
    if produit is _ABSENT:
        return False
    if vrai is None:
        return produit is None or produit == "" or produit == []
    if produit is None:
        return False
    if isinstance(vrai, bool):
        return _bool(produit) is vrai
    if isinstance(vrai, list):
        if not isinstance(produit, list):
            produit = [produit]
        a = sorted(str(_norm_scalaire(champ, _deballer(x))) for x in vrai)
        b = sorted(str(_norm_scalaire(champ, _deballer(x))) for x in produit)
        return a == b
    feuille = champ.split(".")[-1]
    if feuille in CHAMPS_MONTANT or isinstance(vrai, (int, float)):
        dv, dp = parse_montant(vrai), parse_montant(produit)
        if isinstance(dv, Decimal) and isinstance(dp, Decimal):
            tol = TOL_EXTRACTION_MONTANT if feuille in CHAMPS_MONTANT else Decimal(0)
            return abs(dv - dp) <= tol
    nv, np_ = _norm_scalaire(champ, vrai), _norm_scalaire(champ, produit)
    if isinstance(nv, Decimal) and not isinstance(np_, Decimal):
        dp = parse_montant(produit)
        return isinstance(dp, Decimal) and dp == nv
    return nv == np_


def metriques_extraction(dossiers: dict[str, Dossier]) -> dict[str, Any]:
    compte: dict[str, list[int]] = {}
    n_dossiers = 0
    for dos in dossiers.values():
        if not dos.findings or not isinstance(dos.findings.get("valeurs"), dict):
            continue
        n_dossiers += 1
        valeurs = dos.findings["valeurs"]
        produits = list(dos.docs_produits.values())
        for doc_id, tv in (dos.truth.get("truth_values") or {}).items():
            t = dos.docs_verite.get(doc_id)
            if t is None or t.type not in CHAMPS_OBLIGATOIRES or not isinstance(tv, dict):
                continue
            p = meilleur_produit(t, produits)
            pv = valeurs.get(p.document_id, {}) if p else {}
            scalaires, listes = CHAMPS_OBLIGATOIRES[t.type]
            for ch in scalaires:
                vrai = _get(tv, ch)
                if vrai is _ABSENT:
                    continue
                ok = valeurs_egales(ch, vrai, _get(pv, ch, t.type))
                c = compte.setdefault(f"{t.type}.{ch}", [0, 0])
                c[0] += 1
                c[1] += int(ok)
            for liste, champs in listes.items():
                lignes = tv.get(liste)
                if not isinstance(lignes, list):
                    continue
                for i, ligne in enumerate(lignes):
                    if not isinstance(ligne, dict):
                        continue
                    for ch in champs:
                        if ch not in ligne:
                            continue
                        ok = valeurs_egales(ch, ligne[ch], _get_liste(pv, liste, i, ch, t.type))
                        c = compte.setdefault(f"{t.type}.{liste}[].{ch}", [0, 0])
                        c[0] += 1
                        c[1] += int(ok)
    champs = {k: {"n": n, "corrects": ok, "exactitude": _r(ratio(ok, n))}
              for k, (n, ok) in sorted(compte.items())}
    tot_n = sum(v[0] for v in compte.values())
    tot_ok = sum(v[1] for v in compte.values())
    return {"n_dossiers_evalues": n_dossiers, "global": {"n": tot_n, "corrects": tot_ok,
            "exactitude": _r(ratio(tot_ok, tot_n))}, "champs": champs}


# ---------------------------------------------------------------------------
# Regroupement (F1 des liens)
# ---------------------------------------------------------------------------

_CLES_SOURCE = ("from", "de", "source", "source_id", "source_document_id", "document_source",
                "document_id_source")
_CLES_CIBLE = ("to", "vers", "cible", "target", "cible_id", "document_cible", "document_id")


def _paire_lien(lien: dict) -> tuple[str | None, str | None]:
    src = next((str(lien[k]) for k in _CLES_SOURCE if lien.get(k)), None)
    cib = next((str(lien[k]) for k in _CLES_CIBLE if lien.get(k) and k not in _CLES_SOURCE),
               None)
    return src, cib


def metriques_regroupement(dossiers: dict[str, Dossier]) -> dict[str, Any]:
    tp = fp = fn = 0
    modes: dict[str, int] = {}
    for dos in dossiers.values():
        attendus = dos.truth.get("expected_links") or []
        if dos.findings is None:
            fn += len(attendus)
            continue
        produits = list(dos.docs_produits.values())
        corr = {tid: meilleur_produit(t, produits) for tid, t in dos.docs_verite.items()}
        liens = [l for l in (dos.findings.get("liens") or []) if isinstance(l, dict)]
        paires_prod = set()
        noeuds_prod = set()
        mode_paires = bool(liens) and all(_paire_lien(l)[0] for l in liens)
        for l in liens:
            src, cib = _paire_lien(l)
            if cib:
                noeuds_prod.add(cib)
            if src and cib and src != cib:
                paires_prod.add(frozenset((src, cib)))
        if mode_paires or not liens:
            modes["paires"] = modes.get("paires", 0) + 1
            attendues = set()
            n_inmappables = 0
            for el in attendus:
                a, b = corr.get(el.get("from")), corr.get(el.get("to"))
                if a is None or b is None or a.document_id == b.document_id:
                    n_inmappables += 1
                else:
                    attendues.add(frozenset((a.document_id, b.document_id)))
            tp += len(attendues & paires_prod)
            fp += len(paires_prod - attendues)
            fn += len(attendues - paires_prod) + n_inmappables
        else:
            # Liens sans document source (forme de l'Annexe C) : F1 sur l'ensemble des
            # documents rattachés.
            modes["documents"] = modes.get("documents", 0) + 1
            attendus_noeuds = set()
            n_inmappables = 0
            for el in attendus:
                for tid in (el.get("from"), el.get("to")):
                    p = corr.get(tid)
                    if p is None:
                        n_inmappables += 1
                    else:
                        attendus_noeuds.add(p.document_id)
            tp += len(attendus_noeuds & noeuds_prod)
            fp += len(noeuds_prod - attendus_noeuds)
            fn += len(attendus_noeuds - noeuds_prod) + n_inmappables
    p = ratio(tp, tp + fp)
    r = ratio(tp, tp + fn)
    f1 = None if p is None or r is None or (p + r) == 0 else 2 * p * r / (p + r)
    return {"vp": tp, "fp": fp, "fn": fn, "precision": _r(p), "rappel": _r(r), "f1": _r(f1),
            "modes": modes}


# ---------------------------------------------------------------------------
# Coût et durée
# ---------------------------------------------------------------------------

def statistiques(valeurs: list[Decimal]) -> dict[str, Any]:
    if not valeurs:
        return {"n": 0, "moyenne": None, "mediane": None, "p95": None, "max": None}
    v = sorted(valeurs)
    n = len(v)
    moyenne = sum(v, Decimal(0)) / n
    mediane = v[n // 2] if n % 2 else (v[n // 2 - 1] + v[n // 2]) / 2
    p95 = v[max(0, math.ceil(Decimal("0.95") * n) - 1)]  # rang le plus proche
    q = Decimal("0.0001")
    return {"n": n, "moyenne": moyenne.quantize(q), "mediane": mediane.quantize(q),
            "p95": p95.quantize(q), "max": v[-1].quantize(q)}


def metriques_execution(dossiers: dict[str, Dossier]) -> tuple[dict, dict, dict]:
    couts: list[Decimal] = []
    durees: list[Decimal] = []
    versions: dict[str, set] = {"version_moteur": set(), "version_regles": set(),
                                "modele_llm": set()}
    for dos in dossiers.values():
        ex = (dos.findings or {}).get("execution") or {}
        if not isinstance(ex, dict):
            continue
        c = parse_montant(ex.get("cout_ia_eur"))
        if isinstance(c, Decimal):
            couts.append(c)
        d = parse_montant(ex.get("duree_s"))
        if isinstance(d, Decimal):
            durees.append(d)
        for k in versions:
            if ex.get(k) is not None:
                versions[k].add(str(ex[k]))
    sc, sd = statistiques(couts), statistiques(durees)
    s = lambda x: None if x is None else str(x)  # noqa: E731
    cout = {"n": sc["n"], "moyenne_eur": s(sc["moyenne"]), "mediane_eur": s(sc["mediane"]),
            "p95_eur": s(sc["p95"]), "max_eur": s(sc["max"])}
    duree = {"n": sd["n"], "moyenne_s": s(sd["moyenne"]), "mediane_s": s(sd["mediane"]),
             "p95_s": s(sd["p95"]), "max_s": s(sd["max"])}
    execution = {k: sorted(v) for k, v in versions.items()}
    execution["version_correcteur"] = VERSION_CORRECTEUR
    return cout, duree, execution


# ---------------------------------------------------------------------------
# Garde-fous de texte et seuil bloquant
# ---------------------------------------------------------------------------

def verifier_textes(dossiers: dict[str, Dossier], formulations: Formulations) -> dict[str, list]:
    interdites: list[dict] = []
    renvois: list[dict] = []
    for dos in dossiers.values():
        if not dos.findings:
            continue
        for expr in formulations.chercher(dos.findings.get("avertissement")):
            interdites.append({"dossier_id": dos.dossier_id, "finding_id": None,
                               "champ": "avertissement", "expression": expr})
        for i, f in enumerate(dos.findings.get("constats", []) or []):
            if not isinstance(f, dict):
                continue
            fid = str(f.get("finding_id") or f"{dos.dossier_id}#{i}")
            for champ in ("libelle", "prochaine_action"):
                for expr in formulations.chercher(f.get(champ)):
                    interdites.append({"dossier_id": dos.dossier_id, "finding_id": fid,
                                       "champ": champ, "expression": expr})
            est_renvoi = f.get("renvoi") is True or f.get("nature_montant") == "renvoi"
            if est_renvoi and f.get("montant_en_jeu") is not None:
                renvois.append({"dossier_id": dos.dossier_id, "finding_id": fid,
                                "montant_en_jeu": str(f.get("montant_en_jeu"))})
    return {"formulations_interdites": interdites, "renvois_avec_montant": renvois}


def evaluer_gate(glob: dict, par_ctrl: dict, textes: dict[str, list]) -> dict[str, Any]:
    motifs: list[str] = []
    pc = glob["precision_certain"]
    if pc is not None and pc < SEUIL_PRECISION_GLOBALE:
        motifs.append(f"1. precision_certain globale {pc:.4f} < {SEUIL_PRECISION_GLOBALE}")
    for ctrl, m in par_ctrl.items():
        if m["n_constats_certain"] >= MIN_CONSTATS_CONTROLE:
            p = m["precision_certain_constats"]
            if p is not None and p < SEUIL_PRECISION_CONTROLE:
                motifs.append(f"2. {ctrl} : precision_certain {p:.4f} < "
                              f"{SEUIL_PRECISION_CONTROLE} ({m['n_constats_certain']} constats "
                              "ecart_certain produits)")
    if glob["n_constats_certain"] < MIN_CONSTATS_PETIT_ECHANTILLON and glob["fp_certain"] > 0:
        motifs.append(f"3. petit échantillon ({glob['n_constats_certain']} constats "
                      f"ecart_certain < {MIN_CONSTATS_PETIT_ECHANTILLON}) et "
                      f"{glob['fp_certain']} FP certain (tolérance zéro)")
    p1 = par_ctrl.get("P1")
    if p1 and p1["n_erreurs"] > 0 and (p1["rappel"] or 0) < 1.0:
        motifs.append(f"4. rappel P1 {p1['rappel']:.4f} < 1,0 ({p1['fn']} document(s) "
                      "manquant(s) non signalé(s))")
    for h in textes["formulations_interdites"]:
        motifs.append(f"5. formulation interdite « {h['expression']} » dans {h['champ']} "
                      f"({h['dossier_id']}{'/' + h['finding_id'] if h['finding_id'] else ''})")
    for h in textes["renvois_avec_montant"]:
        motifs.append(f"5. note de renvoi avec montant {h['montant_en_jeu']} "
                      f"({h['dossier_id']}/{h['finding_id']})")
    return {"passe": not motifs, "motifs": motifs}


def alertes(glob: dict, cout: dict, duree: dict) -> list[str]:
    out = []
    if cout["moyenne_eur"] is not None and Decimal(cout["moyenne_eur"]) > ALERTE_COUT_MOYEN_EUR:
        out.append(f"coût IA moyen {cout['moyenne_eur']} EUR > {ALERTE_COUT_MOYEN_EUR} EUR")
    if duree["p95_s"] is not None and Decimal(duree["p95_s"]) > ALERTE_DUREE_P95_S:
        out.append(f"durée p95 {duree['p95_s']} s > {ALERTE_DUREE_P95_S} s")
    b = glob.get("bruit_a_verifier_par_dossier")
    if b is not None and b > ALERTE_BRUIT_PAR_DOSSIER:
        out.append(f"bruit a_verifier non apparié {b} par dossier > {ALERTE_BRUIT_PAR_DOSSIER}")
    return out


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

def details(constats: list[Constat], erreurs: list[Erreur]) -> list[dict]:
    out = []
    for c in sorted(constats, key=lambda c: (c.dossier_id, c.finding_id)):
        e = c.erreur
        out.append({
            "dossier_id": c.dossier_id, "finding_id": c.finding_id,
            "error_id": e.error_id if e else None, "controle_id": c.controle_id,
            "niveau": c.niveau, "classe": c.classe, "motif": c.motif, "trap_id": c.piege,
            "montant_correct": c.montant_correct,
            "surclassement": bool(e and c.classe == "vp_certain"
                                  and e.expected_level == "a_verifier"),
            "sous_classement": bool(e and e.expected_level == "ecart_certain"
                                    and c.niveau == "a_verifier"),
        })
    for e in sorted(erreurs, key=lambda e: e.error_id):
        if e.constat is None:
            out.append({"dossier_id": e.dossier_id, "finding_id": None, "error_id": e.error_id,
                        "controle_id": e.control_id, "niveau": None, "classe": "fn",
                        "motif": None, "trap_id": None, "montant_correct": None,
                        "surclassement": False, "sous_classement": False})
    return out


def scorer(corpus: Path, split: str, run: Path, formulations: Formulations | None = None,
           run_id: str | None = None) -> dict[str, Any]:
    formulations = formulations or charger_formulations()
    dossiers = charger_corpus(corpus, split)
    charger_findings(run, dossiers)
    index = Index(dossiers)
    constats = [c for d in dossiers.values() for c in constats_du_dossier(d)]
    erreurs = [e for d in dossiers.values() for e in erreurs_du_dossier(d)]
    pieges = [t for d in dossiers.values() for t in pieges_du_dossier(d)]
    apparier(constats, erreurs, index)
    classer(constats, erreurs, pieges, index)
    glob, par_ctrl = metriques_controles(constats, erreurs, len(dossiers))
    textes = verifier_textes(dossiers, formulations)
    cout, duree, execution = metriques_execution(dossiers)
    gate = evaluer_gate(glob, par_ctrl, textes)
    absents = sorted(d for d, x in dossiers.items() if x.statut_findings == "absent")
    illisibles = sorted(d for d, x in dossiers.items() if x.statut_findings == "illisible")
    hors_corpus = sorted(p.name for p in run.iterdir()
                         if p.is_dir() and (p / "findings.json").is_file()
                         and p.name not in dossiers) if run.is_dir() else []
    return {
        "schema": SCHEMA_METRICS,
        "run_id": run_id or run.name,
        "split": split,
        "execution": execution,
        "global": glob,
        "par_controle": par_ctrl,
        "extraction_par_champ": metriques_extraction(dossiers),
        "regroupement": metriques_regroupement(dossiers),
        "cout": cout,
        "duree": duree,
        "gate": gate,
        "alertes": alertes(glob, cout, duree),
        "garde_fous": {**textes, "source_formulations": formulations.source},
        "dossiers": {"n": len(dossiers), "findings_absents": absents,
                     "findings_illisibles": illisibles, "findings_hors_corpus": hors_corpus},
        "details": details(constats, erreurs),
    }
