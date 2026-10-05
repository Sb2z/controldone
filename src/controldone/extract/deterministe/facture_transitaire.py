"""Extracteur déterministe des factures de transitaire et des avoirs de transitaire (SPEC §5.3.3, §5.3.4).

Entrée : les pages d'un document classé ``facture_transitaire`` ou ``avoir`` (texte natif ou OCR, mots
positionnés de l'ingestion). Sortie : ``ChampsFactureTransitaire`` / ``ChampsAvoir`` dont chaque feuille
est une ``ValeurSourcee`` (page, valeur brute telle qu'imprimée, zone, ancrage, confiance).

Règles générales (aucune règle propre à un gabarit de transitaire) :

- **en-tête** par libellés multilingues (fr, en, de, it, es, nl : ``_ft_langues``) : numéro (libellé
  « N° / No. / Nr. », sinon référence voisine du titre du document), date, références de transport (LTA,
  AWB, BL…), MRN (motif à 18 caractères, OCR tolérant mais confiance basse si corrigé), factures
  commerciales citées, facture d'origine et motif (avoir) ;
- **parties** : le numéro de TVA du client est celui du pavé « client facturé / bill to » (ou d'une entité
  du client) ; celui de l'émetteur est celui de l'en-tête du transitaire (recoupé avec le SIREN du pied de
  page). Les deux ne sont jamais intervertis : en cas de doute la confiance baisse ;
- **tableaux** : en-tête reconnu par vocabulaire, colonnes positionnées, cellules attribuées par segment
  (une suite de mots serrés). Les colonnes « par nature » (droits, autres taxes, TVA import, dédouanement…
  d'un relevé ou d'un tableau par code marchandise) produisent une ligne par montant. Les lettres de statut
  TVA sont lues comme ``marqueur_tva``, jamais comme montants ;
- **nature** de chaque ligne par mots-clés du libellé (tableau de §5.3.3) ; « droits et taxes » sans
  ventilation -> ``debours_combines`` ; droit forfaitaire par article -> ``debours_forfait_petits_envois`` ;
- **totaux** par libellés ; total des débours absent -> somme des lignes de débours
  (``total_origine = reconstruit``, confiance ≤ 0,60) ;
- valeurs non imprimées mais déductibles (taux de TVA d'après la légende des codes, quantité implicite,
  prix unitaire = montant / quantité, TVA = base × taux) : valeurs ``derive`` à confiance plafonnée.

Avant lecture, les glyphes de tampon, de filigrane et d'annotation manuscrite superposés au texte natif sont
retirés (``_ft_nettoyage``). Généralisation à des mises en page inconnues : D-1901 à D-1907.

Une valeur fausse à confiance ≥ 0,90 crée un faux « écart certain » : en OCR, la confiance suit le minimum
des confiances des mots lus, plafonnée sauf recoupement arithmétique (quantité × prix = montant, somme des
lignes = total).
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from controldone.extract.base import ExtractionContext, ExtractionResult
from controldone.extract.deterministe import _ft_langues as L
from controldone.extract.deterministe._ft_nettoyage import retirer_surimpressions
from controldone.extract.deterministe._mise_en_page import (
    PAYS_TVA,
    REP_FISCAL,
    Fabrique,
    Lecture,
    Nombre,
    Segment,
    VueDocument,
    VueLigne,
    VuePage,
    chercher,
    confiance_mots,
    devise_dans,
    est_bandeau_texte,
    lecture_mots,
    lignes_bandeau,
    lire_tva_mots,
    nombres_dans,
    valeur_apres,
    vue_document,
)
from controldone.extract.deterministe._mise_en_page import _page_texte as _page_texte
from controldone.ingest.texte import Ligne, Mot, PageText
from controldone.model.champs import (
    ChampsAvoir,
    ChampsFactureTransitaire,
    LigneFactureTransitaire,
    LigneTableauMrn,
    chemin_complet,
    type_valeur_pour,
)
from controldone.model.documents import Document, Page
from controldone.model.enums import Methode, NatureLigne, QualiteTexte, TotalOrigine, TypeDocument, TypeValeur
from controldone.model.valeur import ExtracteurInfo, ValeurSourcee, confiance_derivee, deriver_somme
from controldone.normalize import normalize_vat, parse_amount, parse_date
from controldone.normalize.fiscal import siren_depuis_tva, tva_fr_valide
from controldone.normalize.natures import nature_libelle
from controldone.normalize.refs import CONFUSION_OCR, norm_ref, norm_ref_transport
from controldone.normalize.text import cle_texte

__all__ = ["ExtracteurFactureTransitaire", "classer_nature"]

VERSION = "1.0.0"

# --- confiances ----------------------------------------------------------------------------------------

#: Valeur lue sous un libellé reconnu ou dans une colonne d'en-tête reconnue (texte natif).
C_LIBELLE = 0.97
#: Valeur repérée par position (numéro voisin du titre, nom de l'émetteur en tête de page…).
C_POSITION = 0.88
#: Valeur d'en-tête recopiée sur une ligne (MRN unique du document rattaché à chaque ligne).
C_RATTACHEMENT = 0.85
#: Plafond des valeurs déduites (non imprimées) : taux d'après légende, quantité implicite, TVA calculée.
C_DEDUITE = 0.6
#: Plafond d'une lecture OCR recoupée arithmétiquement (et lue avec des confiances OCR élevées).
C_OCR_RECOUPEE = 0.92
#: Plafond d'une valeur OCR qui contredit l'arithmétique du document.
C_OCR_INCOHERENTE = 0.6
#: Plafond des montants de ligne d'un tableau dont une rangée illisible a été perdue (D-2505).
C_RANGEE_PERDUE = 0.85

TAUX_TVA_CONNUS = (Decimal("0"), Decimal("2.1"), Decimal("5.5"), Decimal("8.5"), Decimal("10"), Decimal("20"))
_CENT = Decimal("0.01")

# --- nature des lignes (§5.3.3) -----------------------------------------------------------------------------

def classer_nature(libelle: str | None, *, tolerant: bool = False) -> NatureLigne | None:
    """Nature d'une ligne d'après son libellé ; ``None`` si aucun mot-clé n'est reconnu (table unique
    ``normalize.natures``, D-1213). ``tolerant`` : une faute de lecture d'un caractère par mot est admise
    (D-2305) ; réservé à la nature d'une ligne déjà lue, jamais au repérage des rangées."""
    return nature_libelle(libelle, tolerant=tolerant)


# --- vocabulaire des en-têtes de tableau -------------------------------------------------------------------

#: Classes de confusion OCR (caractères souvent pris l'un pour l'autre) pour regrouper les variantes.
_CONFUSION_OCR = CONFUSION_OCR

def consensus_lectures(membres: Sequence[str], compte: Mapping[str, int], meilleur: str) -> str:
    """Vote caractère par caractère sur des lectures de même longueur d'une même référence. Départage
    déterministe (§6.2.12, D-1208) : à égalité de votes, le caractère de ``meilleur`` (lecture la plus
    fréquente), puis l'ordre alphabétique — jamais l'ordre d'itération d'un ensemble."""
    n = min(len(c) for c in membres)
    return "".join(
        max(sorted({c[i] for c in membres}),
            key=lambda ch, i=i: (sum(compte[c] for c in membres if c[i] == ch), ch == meilleur[i]))
        for i in range(n))


_ROLES_TEXTE = {"lib", "libcode", "natflag", "ref", "detail", "transport", "date", "pos"}
_ROLES_NUM = {"qte", "pu", "pu_ttc", "ht", "ttc", "tva", "tva_mt", "cat", "taux", "base_droit", "base_tva"}
#: Rôles des colonnes dont une valeur fait une rangée du tableau.
_ROLES_VALEUR = ("qte", "pu", "pu_ttc", "ht", "ttc", "tva", "tva_mt", "taux")

_VOCABULAIRE: dict[str, list[str]] = L.VOCABULAIRE_COLONNES
_PHRASES: list[tuple[str, tuple[str, ...]]] = sorted(
    ((role, tuple(p.split())) for role, ps in _VOCABULAIRE.items() for p in ps),
    key=lambda x: -sum(len(w) for w in x[1]),
)


#: Mots qui qualifient l'en-tête de colonne qui les précède (« P.U. HT », « Prix (EUR) »).
_QUALIFICATIFS = {"ht", "h.t", "net", "netto", "eur", "€", "(eur)", "(€)", "excl", "hors taxes", "(ht)"}


def _cle_mot(t: str) -> str:
    c = cle_texte(t).strip(":")
    return c if c in (".", "%") else c.rstrip(".").rstrip(",")


@dataclass
class ColonneFt:
    role: str
    x0: float
    x1: float
    libelle: str
    mots: tuple[Mot, ...] = ()

    @property
    def numerique(self) -> bool:
        return self.role in _ROLES_NUM or self.role.startswith("nat:")


def _reconnaitre_entete(li: VueLigne) -> list[ColonneFt] | None:
    mots = li.mots
    if len(mots) < 3 or any(_est_montant_txt(m.texte) for m in mots):
        return None
    cles = [_cle_mot(m.texte) for m in mots]
    cols: list[ColonneFt] = []
    k = 0
    while k < len(mots):
        trouve = None
        if cols and cles[k] in _QUALIFICATIFS and mots[k].x0 - cols[-1].x1 < 0.012 \
                and cols[-1].role not in ("ht", "tva", "tva_mt"):
            # « P.U. HT », « Prix (EUR) » : qualificatif accolé à la colonne précédente, pas une colonne
            c = cols[-1]
            c.x1 = max(c.x1, mots[k].x1)
            c.libelle = f"{c.libelle} {mots[k].texte}"
            c.mots = (*c.mots, mots[k])
            k += 1
            continue
        for role, phr in _PHRASES:
            n = len(phr)
            if k + n > len(mots):
                continue
            if any(mots[a + 1].x0 - mots[a].x1 > 0.03 for a in range(k, k + n - 1)):
                continue
            if tuple(cles[k:k + n]) == phr:
                trouve = (role, n)
                break
        if trouve is None:
            # mot non reconnu : rattaché à la colonne précédente s'il la prolonge (« (… »), sinon ignoré
            if cols and mots[k].x0 - cols[-1].x1 < 0.012:
                c = cols[-1]
                c.x1 = max(c.x1, mots[k].x1)
                c.libelle = f"{c.libelle} {mots[k].texte}"
                c.mots = (*c.mots, mots[k])
            k += 1
            continue
        role, n = trouve
        seq = mots[k:k + n]
        cols.append(ColonneFt(role, min(m.x0 for m in seq), max(m.x1 for m in seq),
                              " ".join(m.texte for m in seq), tuple(seq)))
        k += n
    roles = [c.role for c in cols]
    if len(cols) < 3 or len(set(roles)) < 3:
        return None
    if not any(r in ("lib", "libcode", "ref", "transport") for r in roles):
        return None
    if not any(r in ("ht", "pu", "ttc", "pu_ttc") or r.startswith("nat:") for r in roles):
        return None
    # plusieurs colonnes « montant » (« Montant » … « Total ») : la première est le montant HT, les
    # suivantes un montant TTC (jamais lu comme montant de ligne)
    hts = [c for c in cols if c.role == "ht"]
    for c in hts[1:]:
        if not _deux_tableaux(cols):
            c.role = "ttc"
    return cols


def _deux_tableaux(cols: list[ColonneFt]) -> bool:
    """En-tête de deux tableaux côte à côte (« Item Qty Amount | Item Qty Amount »)."""
    return len(_groupes_colonnes(cols)) > 1


def _groupes_colonnes(cols: list[ColonneFt]) -> list[list[ColonneFt]]:
    """Colonnes regroupées par tableau : un nouveau tableau commence à chaque colonne de libellé répétée,
    à condition que chaque groupe ait sa colonne de montant."""
    groupes: list[list[ColonneFt]] = []
    for c in cols:
        if c.role in ("lib", "libcode") and groupes and any(x.role in ("lib", "libcode") for x in groupes[-1]):
            groupes.append([c])
        elif groupes:
            groupes[-1].append(c)
        else:
            groupes.append([c])
    if len(groupes) > 1 and all(any(x.role in ("ht", "pu") for x in g) for g in groupes):
        return groupes
    return [cols]


# --- reconnaissance des jetons -------------------------------------------------------------------------------

_MONTANT_RE = re.compile(r"^[(\-−–]?[€$£]?\d{1,3}(?:[ \u00a0\u202f\u2009.,'’]?\d{3})*[.,]\d{2}\)?-?€?$")
_ENTIER_RE = re.compile(r"^\d{1,4}$")
_POURCENT_RE = re.compile(r"^(\d{1,2}(?:[.,]\d{1,2})?)\s*%$")
_MARQUEUR_RE = re.compile(r"^[A-Z]$")
#: mention d'exonération imprimée à la place d'un taux de TVA (D-2502)
_EXONERE_RE = re.compile(r"isento|isenta|exento|exenta|esente|exempt|exempted|exonere|exoneree|exo|zw|"
                         r"zwolniony|np|steuerfrei|mwst-frei|befreit|vrijgesteld")
_MRN_RE = re.compile(r"(?<![A-Z0-9])(\d{2}[A-Z]{2}[A-Z0-9]{14})(?![A-Z0-9])")
#: séparateur entre les deux dates d'une période écrite dans un libellé (D-2301)
_RX_SEP_PERIODE = re.compile(r"\s*(?:[-–—]{1,2}|au|to|until|bis|al|a|tot|t/m|hasta)\s*", re.IGNORECASE)
_DATE_RE = re.compile(
    r"\b(\d{1,2}[/.\-]\d{1,2}[/.\-]\d{2,4}|\d{4}-\d{2}-\d{2}|"
    rf"(?:{L.MOTS_MOIS}|fév|aoû|déc)[a-zéûä]*\.? \d{{1,2}},? \d{{4}}|"
    rf"\d{{1,2}}\.? (?:de )?(?:{L.MOTS_MOIS}|märz|mär|fév|aoû|déc)[a-zéûä]*\.? (?:de |del )?\d{{4}})",
    re.IGNORECASE,
)


def _est_montant_txt(t: str) -> bool:
    return bool(_MONTANT_RE.match(t.strip()))


def _dec(v: ValeurSourcee | None) -> Decimal | None:
    if v is None or not v.est_lisible:
        return None
    try:
        return Decimal(v.valeur)  # type: ignore[arg-type]
    except (InvalidOperation, TypeError):
        return None


def _dec_signe(v: ValeurSourcee | None) -> Decimal | None:
    """Valeur avec son signe imprimé (ligne « Gutschrift … -25.00 » d'un relevé, D-2505)."""
    d = _dec(v)
    if d is None or v is None:
        return d
    return -d if v.signe_imprime is not None and getattr(v.signe_imprime, "value", v.signe_imprime) == "negatif" \
        else d


def _arrondi(d: Decimal) -> Decimal:
    return d.quantize(_CENT, rounding=ROUND_HALF_UP)


# --- structures intermédiaires --------------------------------------------------------------------------------


@dataclass
class Lu:
    """Valeur lue (mots d'une page) avec la confiance de base de la règle qui l'a trouvée."""

    lecture: Lecture
    base: float = C_LIBELLE
    brut: str | None = None

    @property
    def texte(self) -> str:
        return self.brut if self.brut is not None else self.lecture.texte


@dataclass
class LigneLue:
    page: VuePage
    y: float
    libelle: Lu | None = None
    libelle_entete: bool = False
    nature: NatureLigne = NatureLigne.autre_prestation
    quantite: Lu | None = None
    prix_unitaire: Lu | None = None
    montant_ht: Lu | None = None
    #: montant TVA comprise imprimé (colonne « TTC », « Total c/ IVA ») et prix unitaire TVA comprise
    montant_ttc: Lu | None = None
    pu_ttc: Lu | None = None
    montant_tva: Lu | None = None
    taux_tva: Lu | None = None
    #: la ligne porte une mention d'exonération (« isento », « exempt », « zw. ») au lieu d'un taux
    exoneree: bool = False
    marqueur: Lu | None = None
    mrn: Lu | None = None
    ref_transport: Lu | None = None
    code: Lu | None = None
    base_droit: Lu | None = None
    pourcentage: Lu | None = None
    date_debut: Lu | None = None
    date_fin: Lu | None = None
    natflag: str | None = None
    #: la ligne appartient à un tableau dont une colonne est réservée au MRN de chaque ligne
    colonne_mrn: bool = False
    #: la colonne de références de la ligne porte autre chose qu'un MRN
    ref_autre: bool = False
    #: montant HT illisible : déduit de quantité × prix unitaire
    ht_calcule: bool = False


@dataclass
class EntreeReleve:
    transport: Lu | None
    mrn: Lu | None
    date: Lu | None


@dataclass
class Total:
    cle: str
    lu: Lu
    taux: Decimal | None = None


@dataclass
class LectureTva:
    lu: Lu
    norm: str
    ligne: VueLigne
    page: VuePage
    corrigee: bool = False
    #: numéro libellé comme celui d'un représentant fiscal (« TVA rep. fiscal : FR… ») : pas celui du client
    representant: bool = False


#: Libellé d'un représentant fiscal (D-2504).
_RX_REP_FISCAL = REP_FISCAL


# --- extracteur -------------------------------------------------------------------------------------------------


class ExtracteurFactureTransitaire:
    """Extracteur déterministe ``facture_transitaire`` et ``avoir`` (avoirs émis par un transitaire)."""

    id = "ft_regles"
    version = VERSION
    type = "deterministe"

    def supports(self, document: Document, pages: Sequence[Page]) -> bool:
        if document.type not in (TypeDocument.facture_transitaire, TypeDocument.avoir):
            return False
        return any(p.qualite_texte is not QualiteTexte.illisible and (p.texte or "").strip() for p in pages) or \
            not pages

    def info(self) -> ExtracteurInfo:
        return ExtracteurInfo(type="deterministe", id=self.id, version=self.version)

    def extract(self, document: Document, pages: Sequence[object], context: ExtractionContext) -> ExtractionResult:
        info = self.info()
        sources = list(pages)
        opt = (context.options.get("textes_pages") or context.options.get("pages_texte")) if context.options \
            else None
        if opt:
            par_num = opt if isinstance(opt, dict) else {getattr(p, "numero", i + 1): p for i, p in enumerate(opt)}
            sources = [par_num.get(getattr(p, "numero", None), p) for p in pages]
        utiles = [p for p in sources if (getattr(p, "texte", None) or "") != ""
                  and getattr(p, "qualite_texte", None) is not QualiteTexte.illisible]
        if not utiles:
            return ExtractionResult(extracteur=info, champs=None, avertissements=["aucune_page_lisible"],
                                    partielle=True)
        vue = vue_document([_nettoyer(retirer_surimpressions(_page_texte(p))) for p in utiles],
                           separateur_decimal=context.separateur_decimal)
        td = TypeDocument(document.type)
        ex = _Extraction(td, document.id, info, vue, context)
        champs = ex.executer()
        return ExtractionResult(extracteur=info, champs=champs, avertissements=ex.avertissements,
                                partielle=ex.partielle)


# --- cœur de l'extraction -----------------------------------------------------------------------------------------

_TITRE = L.TITRE
_TITRE_COMPACT = L.TITRE_COMPACT


def _est_titre(cle: str) -> bool:
    """Titre du document (« FACTURE », « CREDIT NOTE »… ; mot coupé par l'OCR toléré : « FACTU RE »)."""
    return bool(_TITRE.match(cle) or (len(cle) <= 40 and _TITRE_COMPACT.match(cle.replace(" ", ""))))


_TITRE_RELEVE = re.compile(r"\breleve\b|\bstatement\b|facture mensuelle|monthly invoice|recapitulati|kontoauszug|"
                           r"sammelrechnung|zestawienie|extrato")

_LIB_NUMERO = L.LIB_NUMERO
_EXCLURE_NUMERO = re.compile(r"\b(tva|vat|siren|siret|eori|tel|fax|iban|client|customer|commande|order|ust|mwst|"
                             r"iva|btw|nif|cif|kunde|kunden|cliente|klant|auftrag|ordine|pedido|bestelling|"
                             r"partita|steuer|codice|kvk|rcs|account|seite|page|pagina|blatt)\b")
_LIB_DATE = L.LIB_DATE
_LIB_DU = L.LIB_DU
_LIB_CLIENT = L.LIB_CLIENT
_LIB_TRANSPORT = L.LIB_TRANSPORT
_LIB_FOURNISSEUR = [re.compile(
    r"(fact\.? fournisseur|facture fournisseur|factures? fournisseurs?|fact\.? fourn\.?|supplier inv(?:oice)?s?\.?|"
    r"commercial inv(?:oice)?s?\.?|facture commerciale|fact\.? commerciale|ref\.? facture fournisseur|"
    r"vendor invoice)\b\s*(n°|no\.?)?\s*:?\s*"
)]
_LIB_ORIGINE = [re.compile(
    r"(facture d'origine|facture origine|facture initiale|original invoice|invoice ref\.?|credited invoice|"
    r"invoice credited|ref\.? facture|facture concernee|facture creditee|related invoice|"
    r"facture d'origine / original invoice|"
    # de / it / es / nl
    r"ursprungsrechnung|ursprungliche rechnung|originalrechnung|bezugsrechnung|zu rechnung|"
    r"fattura (?:di )?(?:origine|riferimento|originale|rettificata)|rif\.? fattura|"
    r"factura (?:original|rectificada|de origen|de referencia)|ref\.? factura|"
    r"oorspronkelijke factuur|originele factuur|oorspr\.? factuur|ref\.? factuur|"
    # pt / pl (D-2501)
    r"fatura (?:de origem|original|corrigida|retificada)|ref\.? fatura|faktura (?:pierwotna|korygowana|"
    r"korygujaca do)|dotyczy faktury|korekta (?:do )?faktury)\b\s*(n°|n\.º|no\.?|nr\.?|n\.)?\s*:?\s*"
)]
_LIB_MOTIF = [re.compile(r"(motif|reason|objet|raison|grund|begrundung|motivo|causale|reden|przyczyna korekty|"
                         r"przyczyna)\b\s*(/\s*reason)?"
                         r"\s*:?\s*")]

_TOTAUX = L.TOTAUX
_FIN_TABLEAU = L.FIN_TABLEAU

class _Extraction:
    def __init__(self, td: TypeDocument, document_id: str, info: ExtracteurInfo, vue: VueDocument,
                 context: ExtractionContext) -> None:
        self.td = td
        self.avoir = td is TypeDocument.avoir
        self.document_id = document_id
        self.info = info
        self.vue = vue
        self.ctx = context
        self.fab = Fabrique(td, document_id, info, vue, context.ids)
        self.avertissements: list[str] = []
        self.partielle = False
        self.consommees: set[tuple[int, int]] = set()
        self.champs: ChampsFactureTransitaire | ChampsAvoir = ChampsAvoir() if self.avoir else \
            ChampsFactureTransitaire()
        #: mot -> (segment, page, ligne) : retrouver le segment d'une lecture
        self.index: dict[int, tuple[Segment, VuePage, VueLigne]] = {
            id(m): (s, p, li) for p in vue.pages for li in p.lignes for s in li.segments for m in s.mots
        }

    # --- utilitaires de construction ---

    def _conf(self, lu: Lu) -> float:
        return confiance_mots(lu.lecture, natif=lu.base, plafond_ocr=min(0.88, lu.base))

    def _vs(self, chemin: str, lu: Lu | None, *, type_valeur: TypeValeur | None = None,
            conf: float | None = None) -> ValeurSourcee | None:
        if lu is None:
            return None
        c = self._conf(lu) if conf is None else conf
        montant = self._est_montant(chemin) and type_valeur in (None, TypeValeur.montant)
        if montant and lu.lecture.methode is Methode.ocr and _montant_ocr_suspect(lu.texte):
            c = min(c, 0.7)
        return self.fab.valeur(chemin, lu.lecture, confiance=c, type_valeur=type_valeur, brut=lu.brut,
                               devise="EUR" if montant else None)

    @staticmethod
    def _est_montant(chemin: str) -> bool:
        return type_valeur_pour(chemin) is TypeValeur.montant

    def _derive(self, chemin: str, valeur: str, sources: Sequence[ValeurSourcee], regle: str,
                plafond: float = C_DEDUITE, total_reconstruit: bool = False) -> ValeurSourcee:
        conf = confiance_derivee(sources) if sources else plafond
        tv = type_valeur_pour(chemin)
        return ValeurSourcee(
            id=self.ctx.ids.nouveau(_prefixe_valeur()) if self.ctx.ids is not None else _nouvel_id(),
            chemin=chemin_complet(self.td, chemin), valeur=valeur, type=tv,
            unite="EUR" if tv is TypeValeur.montant else None, document_id=self.document_id,
            extracteur=self.info, methode=Methode.derive, confiance=min(conf, plafond),
            derivee_de=[s.id for s in sources], regle_derivation=regle, ancree=False,
            total_origine=TotalOrigine.reconstruit if total_reconstruit else None,
        )

    def _lu_mots(self, mots: Sequence[Mot], page: VuePage, ligne: VueLigne, base: float = C_LIBELLE,
                 brut: str | None = None) -> Lu:
        return Lu(lecture_mots(mots, page, ligne), base=base, brut=brut)

    # --- pages ---

    def _pages_facture(self) -> list[VuePage]:
        """Pages portant la facture (tableau ou totaux) ; lettres et conditions générales écartées."""
        out = []
        for p in self.vue.pages:
            a_tableau = any(_reconnaitre_entete(li) for li in p.lignes)
            a_total = any(_TOTAUX[1][1].match(li.cle) or re.match(r"^(total|net a payer|amount due)", li.cle)
                          or (_cle_total(li.cle) not in (None, "ignore")
                              and any(_est_montant_txt(m.texte) for m in li.mots))
                          for li in p.lignes)
            if a_tableau or a_total:
                out.append(p)
        return out or list(self.vue.pages)

    # --- orchestration ---

    def executer(self) -> ChampsFactureTransitaire | ChampsAvoir:
        pages = self._pages_facture()
        self.pages = pages
        self.numeros_pages = [p.numero for p in pages]
        tables = self._lire_tableaux(pages)
        mrns = self._mrns(pages)
        self._entete(pages, mrns)
        legende = self._legende(pages)
        totaux = self._totaux(pages)
        self._lignes(tables, mrns, legende, totaux)
        self._totaux_champs(totaux)
        self._coherence()
        return self.champs

    # --- MRN ---

    def _mrns(self, pages: list[VuePage]) -> list[Lu]:
        vus: dict[str, Lu] = {}
        compte: dict[str, int] = {}
        for p in pages:
            for li in p.lignes:
                mots = li.mots
                for k, m in enumerate(mots):
                    t = m.texte.strip(".,;:()[]|")
                    lu = None
                    mm = _MRN_RE.fullmatch(t)
                    if mm:
                        lu = self._lu_mots([m], p, li, brut=t if t != m.texte else None)
                    elif p.methode is Methode.ocr:
                        lu = self._mrn_ocr(mots, k, p, li)
                    elif len(t) > 18:
                        mm = _MRN_RE.search(t)
                        if mm and re.fullmatch(r"[A-Z0-9]*", t):
                            continue
                    if lu is None:
                        continue
                    cle = norm_ref(lu.texte)
                    if cle not in vus:
                        vus[cle] = lu
                    compte[cle] = compte.get(cle, 0) + 1
        # variantes d'un même MRN lues différemment par l'OCR (4/A, 0/O, 1/I…) : la plus fréquente est
        # retenue, avec une confiance basse (lecture contradictoire)
        groupes: dict[str, list[str]] = {}
        for cle in vus:
            groupes.setdefault(cle.translate(_CONFUSION_OCR), []).append(cle)
        self.mrn_variantes: dict[str, Lu] = {}
        out = []
        for membres in groupes.values():
            meilleur = max(membres, key=lambda c: (compte[c], self._conf(vus[c])))
            if len(membres) > 2:
                # vote caractère par caractère sur toutes les lectures (erreurs à des positions différentes)
                consensus = consensus_lectures(membres, compte, meilleur)
                if consensus in vus:
                    meilleur = consensus
            lu = vus[meilleur]
            if len(membres) > 1:
                lu = Lu(lu.lecture, base=min(lu.base, 0.7), brut=lu.brut)
            for c in membres:
                self.mrn_variantes[c] = lu
            out.append(lu)
        return out

    def _mrn_ocr(self, mots: Sequence[Mot], k: int, p: VuePage, li: VueLigne) -> Lu | None:
        """MRN lu par OCR : deux mots soudés, ou confusions O/0, I/1 sur l'année et le pays."""
        t = mots[k].texte.strip(".,;:()[]|")
        candidats = [(t, [mots[k]])]
        if t and len(t) < 18 and k + 1 < len(mots) and mots[k + 1].x0 - mots[k].x1 < 0.02:
            candidats.append((t + mots[k + 1].texte.strip(".,;:()[]|"), [mots[k], mots[k + 1]]))
        for txt, ms in candidats:
            if len(txt) != 18 or not re.fullmatch(r"[A-Z0-9]{18}", txt.upper()):
                continue
            u = txt.upper()
            annee = u[:2].replace("O", "0").replace("I", "1").replace("L", "1").replace("S", "5").replace("B", "8")
            pays = u[2:4].replace("0", "O").replace("1", "I")
            corrige = annee + pays + u[4:]
            if not _MRN_RE.fullmatch(corrige):
                continue
            if corrige == txt and len(ms) == 1:
                return self._lu_mots(ms, p, li)
            brut = " ".join(m.texte for m in ms)
            # corrigé ou soudé : confiance basse (valeur brute = texte tel qu'imprimé)
            return Lu(lecture_mots(ms, p, li), base=0.5, brut=brut)
        return None

    # --- en-tête ---

    def _entete(self, pages: list[VuePage], mrns: list[Lu]) -> None:
        c = self.champs
        pnums = [p.numero for p in pages]
        premiere = pages[0]
        # références de transport (libellées)
        refs_transport: dict[str, Lu] = {}
        for t in chercher(self.vue, _LIB_TRANSPORT, pages=pnums):
            if (t.page.numero, t.ligne.rang) in self.consommees:
                continue
            for lu in self._refs_transport(t):
                refs_transport.setdefault(norm_ref_transport(lu.texte), lu)
        for lu in self._transports_tableaux:
            refs_transport.setdefault(norm_ref_transport(lu.texte), lu)
        for lu in refs_transport.values():
            v = self._vs("refs_transport[]", lu, type_valeur=TypeValeur.reference)
            if v is not None:
                c.definir("refs_transport[]", v)
        for lu in mrns:
            v = self._vs("refs_mrn[]", lu, type_valeur=TypeValeur.reference)
            if v is not None:
                c.definir("refs_mrn[]", v)
        exclus = {norm_ref(lu.texte) for lu in mrns} | set(refs_transport)

        # factures commerciales citées / facture d'origine (avoir)
        refs_fc: list[Lu] = []
        for t in chercher(self.vue, _LIB_FOURNISSEUR, pages=pnums):
            refs_fc.extend(self._liste_refs(t))
        if not self.avoir:
            for lu in refs_fc:
                v = self._vs("refs_facture_commerciale[]", lu, type_valeur=TypeValeur.reference)
                if v is not None:
                    c.definir("refs_facture_commerciale[]", v)
        exclus |= {norm_ref(lu.texte) for lu in refs_fc}
        refs_or: list[Lu] = []
        for t in chercher(self.vue, _LIB_ORIGINE, pages=pnums):
            refs_or.extend(self._liste_refs(t))
        exclus |= {norm_ref(lu.texte) for lu in refs_or}
        if self.avoir:
            for lu in refs_or:
                v = self._vs("refs_facture_origine[]", lu, type_valeur=TypeValeur.reference)
                if v is not None:
                    c.definir("refs_facture_origine[]", v)
            for t in chercher(self.vue, _LIB_MOTIF, pages=pnums):
                lec = valeur_apres(self.vue, t, _accepte_motif, dessous=False)
                if lec is not None:
                    c.definir("motif", self._vs("motif", Lu(lec, base=0.9), type_valeur=TypeValeur.texte))
                    break
        # autres références libellées à ne pas prendre pour le numéro (« Fact. débours FD-… »)
        for t in chercher(self.vue, [re.compile(r"(fact\.? debours|facture de debours|fact\.? prestations|"
                                                r"facture de prestations|related|voir facture)\b\s*:?\s*")],
                          pages=pnums):
            for lu in self._liste_refs(t):
                exclus.add(norm_ref(lu.texte))

        # numéro
        numero = self._numero(premiere, exclus)
        if numero is not None:
            c.definir("numero", self._vs("numero", numero, type_valeur=TypeValeur.reference))
        # date
        date = self._date(premiere, numero)
        if date is not None:
            c.definir("date", self._vs("date", date))
        # parties
        self._parties(premiere, pages)
        # devise
        dev = None
        for p in pages:
            for li in p.lignes:
                d = devise_dans(li.texte)
                if d:
                    k = next((i for i, m in enumerate(li.mots) if d in m.texte), None)
                    if k is not None:
                        dev = Lu(lecture_mots([li.mots[k]], p, li), brut=d)
                        break
            if dev:
                break
        if dev is not None:
            c.definir("devise", self._vs("devise", dev, type_valeur=TypeValeur.devise))
        elif any(any("€" in m.texte for m in li.mots) for p in pages for li in p.lignes):
            c.definir("devise", self._derive("devise", "EUR", [], "symbole_euro", plafond=0.8))
        else:
            c.definir("devise", self._derive("devise", "EUR", [], "devise_par_defaut_transitaire", plafond=0.5))
        # relevé
        if not self.avoir:
            haut = " ".join(li.cle for li in premiere.lignes if li.y0 < 0.2)
            if _TITRE_RELEVE.search(haut) or len(self._releve) >= 2:
                c.est_releve = True  # type: ignore[union-attr]

    def _refs_transport(self, t) -> list[Lu]:
        """Références de transport après un libellé (« LTA / B/L / CMR: X », « AWB / B/L: X, Y ») ; libellé
        seul dans son segment : en-tête d'une colonne de références (lignes alignées en dessous)."""
        mots = [m for m in t.segment.mots[t.apres:] if m.texte not in (":",)]
        if not mots:
            droite = t.ligne.segments[t.segment.rang + 1:t.segment.rang + 2]
            if droite and droite[0].x0 - t.segment.x1 < 0.6 and re.search(r"\d", droite[0].mots[0].texte):
                mots = list(droite[0].mots)
        out: list[Lu] = []
        if mots:
            for groupe in _groupes_virgule(mots):
                r = _accepte_ref_transport(groupe)
                if r is not None:
                    ms = groupe[r[0]:r[1]]
                    out.append(self._lu_mots(ms, t.page, t.ligne, brut=" ".join(m.texte for m in ms).strip(",;")))
            return out[:10]
        # colonne : références alignées sous le libellé, ligne après ligne
        p = t.page
        prec = t.ligne
        for li in p.lignes[t.ligne.rang + 1:t.ligne.rang + 40]:
            if li.y0 - prec.y1 > 3.0 * p.pas_ligne + 0.01:
                break
            segs = [s for s in li.segments if abs(s.x0 - t.segment.x0) < 0.03]
            if not segs:
                break
            r = _accepte_ref_transport(segs[0].mots)
            if r is None or r[0] != 0:
                break
            ms = segs[0].mots[r[0]:r[1]]
            out.append(self._lu_mots(ms, p, li, base=0.95))
            prec = li
        return out[:30]

    def _liste_refs(self, t) -> list[Lu]:
        """Références (une ou plusieurs, séparées par « ; » ou « , ») après un libellé."""
        mots = list(t.segment.mots[t.apres:])
        if not mots:
            segs = t.ligne.segments[t.segment.rang + 1:t.segment.rang + 2]
            mots = list(segs[0].mots) if segs and segs[0].x0 - t.segment.x1 < 0.4 else []
        out: list[Lu] = []
        courant: list[Mot] = []
        for m in [*mots, None]:
            if m is None or (m.texte in (";", ",", "/", "et", "and", "&") and courant):
                if courant:
                    txt = " ".join(x.texte for x in courant).strip(" ;,:")
                    txt = re.sub(r"^(?:n[°º]|no\.?|nr\.?)\s*(?=\w)", "", txt, flags=re.IGNORECASE)
                    if re.search(r"\d", txt) and len(norm_ref(txt)) >= 3 and not _DATE_RE.fullmatch(txt):
                        out.append(Lu(lecture_mots(courant, t.page, t.ligne), brut=txt
                                      if txt != " ".join(x.texte for x in courant) else None))
                    courant = []
                continue
            if m.texte.strip(":") == "":
                continue
            if m.texte.endswith((";", ",")):
                courant.append(m)
                txt = " ".join(x.texte for x in courant).rstrip(";,")
                txt = re.sub(r"^(?:n[°º]|no\.?|nr\.?)\s*(?=\w)", "", txt, flags=re.IGNORECASE)
                if re.search(r"\d", txt):
                    out.append(Lu(lecture_mots(courant, t.page, t.ligne), brut=txt))
                courant = []
                continue
            courant.append(m)
        return out[:10]

    def _numero(self, page: VuePage, exclus: set[str]) -> Lu | None:
        def ok(txt: str) -> bool:
            n = norm_ref(txt)
            return (len(n) >= 4 and bool(re.search(r"\d", n)) and n not in exclus
                    and not _MRN_RE.fullmatch(n) and not _DATE_RE.fullmatch(txt)
                    and not _est_montant_txt(txt) and not _ressemble_tva(txt))

        for t in chercher(self.vue, _LIB_NUMERO, pages=[page.numero]):
            cle = t.segment.cle
            if _EXCLURE_NUMERO.search(cle):
                continue
            if t.ligne.y0 > 0.35:
                continue
            suite = t.segment.mots[t.apres:t.apres + 3]
            pref = _prefixe_numero(suite)
            if pref is not None:
                return self._lu_mots(pref, t.page, t.ligne, brut=" ".join(m.texte.strip(":;,") for m in pref))
            for m_k, m in enumerate(suite[:2]):
                txt = m.texte.strip(":;,")
                if ok(txt) and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9./\-_]*", txt):
                    return self._lu_mots([m], t.page, t.ligne, brut=txt if txt != m.texte else None)
                if m_k == 0 and txt not in ("/", "-"):
                    break
            if t.apres >= len(t.segment.mots):
                droite = t.ligne.segments[t.segment.rang + 1:t.segment.rang + 2]
                if droite:
                    m = droite[0].mots[0]
                    txt = m.texte.strip(":;,")
                    if ok(txt):
                        return self._lu_mots([m], t.page, t.ligne, brut=txt if txt != m.texte else None)
                if not droite or droite[0].x0 - t.segment.x1 >= 0.15:
                    # libellé en tête de colonne (« Nr. | Datum | Btw-nr. ») : la valeur est juste dessous
                    for li in page.lignes[t.ligne.rang + 1:t.ligne.rang + 2]:
                        if li.y0 - t.ligne.y1 > 0.03:
                            break
                        for sg in li.segments:
                            if sg.x1 < t.segment.x0 - 0.01 or sg.x0 > t.segment.x1 + 0.02:
                                continue
                            m = sg.mots[0]
                            txt = m.texte.strip(":;,")
                            if ok(txt) and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9./\-_]*", txt):
                                return self._lu_mots([m], page, li, base=0.93,
                                                     brut=txt if txt != m.texte else None)
        # repli : référence voisine du titre du document
        titres = [(li, s) for li in page.lignes if li.y0 < 0.2 for s in li.segments if _est_titre(s.cle)]
        if not titres:
            return None
        li_t, s_t = titres[0]
        # « FACTURE MDF 84826 » : la référence suit le titre dans le même segment
        mt = _TITRE.match(s_t.cle)
        if mt is not None:
            pos = len(s_t.cle[:mt.end()].split())
            pref = _prefixe_numero(s_t.mots[pos:pos + 3])
            if pref is not None and ok(" ".join(m.texte for m in pref)):
                return self._lu_mots(pref, page, li_t, base=C_POSITION, brut=" ".join(m.texte for m in pref))
        cx, cy = (s_t.x0 + s_t.x1) / 2, (s_t.y0 + s_t.y1) / 2
        meilleur = None
        for li in page.lignes:
            if li.y0 > max(0.22, cy + 0.08) or li.y1 < cy - 0.03:
                continue
            for m in li.mots:
                txt = m.texte.strip(":;,")
                if not (ok(txt) and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9./\-_]*[A-Za-z0-9]", txt)
                        and re.search(r"[A-Za-z]", txt) and re.search(r"\d{3}", txt)):
                    continue
                if _est_tva_contexte(li, m):
                    continue
                d = abs((m.x0 + m.x1) / 2 - cx) + 3 * abs((m.y0 + m.y1) / 2 - cy)
                if meilleur is None or d < meilleur[0]:
                    meilleur = (d, m, li)
        if meilleur is None or meilleur[0] > 0.35:
            return None
        _, m, li = meilleur
        txt = m.texte.strip(":;,")
        return self._lu_mots([m], page, li, base=C_POSITION, brut=txt if txt != m.texte else None)

    def _date(self, page: VuePage, numero: Lu | None) -> Lu | None:
        for t in chercher(self.vue, _LIB_DATE, pages=[page.numero]):
            if t.ligne.y0 > 0.4:
                continue
            lec = valeur_apres(self.vue, t, _accepte_date, dessous=True, lignes_dessous=1)
            if lec is None and t.apres >= len(t.segment.mots):
                # libellé en tête de colonne (« Nr. | Datum | Btw-nr. ») : valeur dessous, au-delà d'un bruit
                # OCR d'une ligne (« < », « : ») — même écart vertical maximal (D-2506)
                lec = valeur_apres(self.vue, t, _accepte_date, droite=False, dessous=True, lignes_dessous=3,
                                   dessous_seul=True)
            if lec is not None:
                return Lu(lec)
        # date dans le segment du numéro (« N° FB-2610049 - 08/09/2026 »), puis « du 03/09/2026 »
        if numero is not None:
            seg = self.index.get(id(numero.lecture.mots[0])) if numero.lecture.mots else None
            if seg is not None:
                r = _accepte_date(seg[0].mots)
                if r is not None:
                    return self._lu_mots(seg[0].mots[r[0]:r[1]], seg[1], seg[2], base=0.92)
                # « No. PFL/26/60695 | 26 Jun 2026 » : date seule dans le segment voisin à droite (D-2506)
                voisins = seg[2].segments[seg[0].rang + 1:seg[0].rang + 2]
                if voisins and voisins[0].x0 - seg[0].x1 < 0.12:
                    r = _accepte_date(voisins[0].mots)
                    if r is not None and r == (0, len(voisins[0].mots)):
                        return self._lu_mots(voisins[0].mots, seg[1], seg[2], base=0.9)
        for t in chercher(self.vue, _LIB_DU, pages=[page.numero]):
            if t.ligne.y0 > 0.3:
                continue
            lec = valeur_apres(self.vue, t, _accepte_date, droite=False, dessous=False)
            if lec is not None:
                return Lu(lec, base=0.92)
        # « Lyon, le 22/08/2026 » : préposition de date au milieu d'un segment de l'en-tête
        for t in chercher(self.vue, _LIB_DU, pages=[page.numero], debut_segment=False):
            if t.ligne.y0 > 0.3 or (t.page.numero, t.ligne.rang) in self.consommees:
                continue
            lec = valeur_apres(self.vue, t, _accepte_date, droite=False, dessous=False)
            if lec is not None:
                return Lu(lec, base=C_POSITION)
        # date seule juste sous le numéro de la facture
        if numero is not None and numero.lecture.mots:
            info = self.index.get(id(numero.lecture.mots[0]))
            if info is not None:
                seg, p, li = info
                for li2 in p.lignes[li.rang + 1:li.rang + 3]:
                    if li2.y0 - li.y1 > 0.03:
                        break
                    for s2 in li2.segments:
                        if s2.x1 < seg.x0 - 0.02 or s2.x0 > seg.x1 + 0.02:
                            continue
                        r = _accepte_date(s2.mots)
                        if r is not None and r == (0, len(s2.mots)):
                            return self._lu_mots(s2.mots[r[0]:r[1]], p, li2, base=C_POSITION)
        return self._date_repli(page)

    def _date_repli(self, page: VuePage) -> Lu | None:
        """Dernier recours (D-2506) : la seule date du haut de la première page qui n'est ni une échéance, ni une
        période, ni l'horodatage d'une télécopie, ni dans un tableau. Valeur de position, confiance plafonnée
        (jamais suffisante pour un écart certain)."""
        trouvees: dict[str, Lu] = {}
        for li in page.lignes:
            if li.y0 > 0.3 or (page.numero, li.rang) in self.consommees:
                continue
            if re.search(r"\b(fax|telecopie|p\.\d{2}/\d{2}|echeance|due|faellig|fallig|scadenza|vencimiento|"
                         r"vervaldatum|vervaldag|termin|vencimento|zahlbar|payable|periode|period|zeitraum|"
                         r"date de mainlevee|release|livraison|delivery|arrivee|arrival|depart|departure)\b", li.cle):
                continue
            for sg in li.segments:
                dms = list(_DATE_RE.finditer(sg.texte))
                if len(dms) != 1:
                    continue
                ms = _mots_de_sous_chaine(sg.mots, dms[0].start(), dms[0].end())
                if not ms or parse_date(dms[0].group(0)) is None:
                    continue
                trouvees.setdefault(parse_date(dms[0].group(0)).isoformat(),  # type: ignore[union-attr]
                                    self._lu_mots(ms, page, li, base=0.7, brut=dms[0].group(0)))
        return next(iter(trouvees.values())) if len(trouvees) == 1 else None

    # --- parties (émetteur / client) ---

    def _parties(self, premiere: VuePage, pages: list[VuePage]) -> None:
        c = self.champs
        tvas = self._tvas(pages)
        entites = {normalize_vat(e.tva) for e in self.ctx.entites if e.tva}
        entites.discard(None)
        label = next((t for t in chercher(self.vue, _LIB_CLIENT, pages=[premiere.numero])
                      if t.ligne.y0 < 0.45 and not re.match(
                          r"(client|cliente|customer|kunde|klant|account)\.? ?(n°|no|nr|code|ref|number|id|nummer|"
                          r"holder|codice|codigo)", t.segment.cle)), None)
        client_tva: LectureTva | None = None
        conf_client = C_LIBELLE
        if label is not None:
            x0 = label.segment.x0
            region = [lt for lt in tvas if lt.page is label.page and label.ligne.y0 - 0.005 <= lt.ligne.y0
                      <= label.ligne.y0 + 0.1 and x0 - 0.03 <= lt.lu.lecture.zone.x0 <= x0 + 0.4]  # type: ignore[union-attr]
            if region:
                # le numéro du représentant fiscal du client n'est pas celui du client (D-2504)
                propres = [lt for lt in region if not lt.representant]
                client_tva = propres[0] if propres else region[0]
                if client_tva.representant:
                    # le numéro propre du client est imprimé plus bas dans le même pavé
                    zr = client_tva.lu.lecture.zone
                    suite = [lt for lt in tvas if lt.page is client_tva.page and not lt.representant
                             and zr is not None and lt.lu.lecture.zone is not None
                             and abs(lt.lu.lecture.zone.x0 - zr.x0) < 0.05
                             and 0 < lt.ligne.y0 - client_tva.ligne.y0 <= 0.06]
                    if suite:
                        client_tva = suite[0]
        ent = [lt for lt in tvas if lt.norm in entites]
        if ent and (client_tva is None or client_tva.norm not in entites):
            client_tva = ent[0]
        autres = [lt for lt in tvas if client_tva is None or lt.norm != client_tva.norm]
        autres = [lt for lt in autres if lt.norm not in entites and not lt.representant]
        siren_pied = _siren_pied(pages)
        emetteur: LectureTva | None = None
        conf_em = C_LIBELLE
        if autres:
            confirme = [lt for lt in autres if siren_pied and siren_depuis_tva(lt.norm) == siren_pied]
            if confirme:
                emetteur = confirme[0]
            else:
                emetteur = min(autres, key=lambda lt: (lt.page.numero, lt.ligne.y0))
                conf_em = 0.93 if (client_tva is not None and label is not None) else 0.85
        if client_tva is None and label is None and len(autres) >= 2 and emetteur is not None:
            # pas de pavé client libellé : l'autre numéro, sous l'en-tête de l'émetteur
            restants = [lt for lt in autres if lt.norm != emetteur.norm]
            if restants:
                client_tva = restants[0]
                conf_client = 0.9 if (siren_pied and siren_depuis_tva(emetteur.norm) == siren_pied) else 0.8
        if client_tva is not None and siren_pied and siren_depuis_tva(client_tva.norm) == siren_pied \
                and client_tva.norm not in entites:
            # le « client » porte le SIREN du pied de page du transitaire : ne pas risquer d'inversion
            conf_client = min(conf_client, 0.5)
        if emetteur is not None and client_tva is not None and emetteur.norm == client_tva.norm:
            emetteur = None
        if emetteur is not None:
            conf = conf_em if not emetteur.corrigee else 0.6
            if emetteur.norm.startswith("FR") and tva_fr_valide(emetteur.norm) is False:
                conf = min(conf, 0.5)
            v = self._vs("emetteur.tva", Lu(emetteur.lu.lecture, base=conf, brut=emetteur.lu.brut),
                         type_valeur=TypeValeur.tva)
            if v is not None and v.valeur != emetteur.norm:
                v = v.model_copy(update={"valeur": emetteur.norm, "confiance": min(v.confiance, 0.6)})
            c.definir("emetteur.tva", v)
        if client_tva is not None and not self.avoir:
            conf = conf_client if not client_tva.corrigee else 0.6
            if client_tva.representant:
                conf = min(conf, 0.6)
            if client_tva.norm.startswith("FR") and tva_fr_valide(client_tva.norm) is False:
                conf = min(conf, 0.5)
            lu_cl = Lu(client_tva.lu.lecture, base=conf, brut=client_tva.lu.brut)
            v = self._vs("client_facture.tva", lu_cl, type_valeur=TypeValeur.tva,
                         conf=_conf_tva_cle_valide(client_tva, conf))
            if v is not None and v.valeur != client_tva.norm:
                v = v.model_copy(update={"valeur": client_tva.norm, "confiance": min(v.confiance, 0.6)})
            c.definir("client_facture.tva", v)
        # noms
        nom_em = self._nom_emetteur(premiere)
        if nom_em is not None:
            c.definir("emetteur.nom", self._vs("emetteur.nom", nom_em, type_valeur=TypeValeur.texte))
        if not self.avoir:
            nom_cl = self._nom_client(premiere, label, client_tva)
            if nom_cl is not None:
                c.definir("client_facture.nom", self._vs("client_facture.nom", nom_cl, type_valeur=TypeValeur.texte))

    def _tvas(self, pages: list[VuePage]) -> list[LectureTva]:
        out: list[LectureTva] = []
        for p in pages:
            for li in p.lignes:
                if re.search(r"\b(iban|bic|swift|rib)\b", li.cle):
                    continue
                mots = li.mots
                k = 0
                while k < len(mots):
                    r = lire_tva_mots(mots[k:])
                    corrigee = False
                    if p.methode is Methode.ocr:
                        r2 = _tva_ocr(mots[k:])
                        if r2 is not None and (r is None or r2[0] <= r[0]):
                            r, corrigee = r2[:3], r2[3]
                    if r is None:
                        break
                    i, j, norm = r
                    ms = mots[k + i:k + j]
                    brut = " ".join(m.texte for m in ms).strip(":;,()")
                    avant = cle_texte(" ".join(m.texte for m in mots[max(0, k + i - 6):k + i]))
                    out.append(LectureTva(Lu(lecture_mots(ms, p, li), brut=brut), norm, li, p, corrigee,
                                          representant=bool(_RX_REP_FISCAL.search(avant))))
                    k += j
        uniques: dict[str, LectureTva] = {}
        for lt in out:
            uniques.setdefault(lt.norm, lt)
        return list(uniques.values())

    def _nom_emetteur(self, page: VuePage) -> Lu | None:
        # bandeaux, filigranes, en-têtes et pieds répétés : jamais le nom de l'émetteur (D-953)
        bandeaux = lignes_bandeau(self.vue, entetes_repetes=False)
        lignes = [li for li in page.lignes if (page.numero, li.rang) not in bandeaux]
        for li in lignes[:4]:
            if li.y0 > 0.12:
                break
            for s in li.segments:
                if _est_titre(s.cle) or not re.search(r"[A-Za-z]{3}", s.texte) or re.search(r"\d{4}", s.texte):
                    continue
                if est_bandeau_texte(s.texte):
                    continue
                if len(s.mots) < 2:
                    continue
                return self._lu_mots(s.mots, page, li, base=0.85)
        return None

    def _nom_client(self, page: VuePage, label, client_tva: LectureTva | None) -> Lu | None:
        if label is not None:
            reste = label.segment.mots[label.apres:]
            if reste and re.search(r"[A-Za-z]{3}", " ".join(m.texte for m in reste)):
                return self._lu_mots(reste, page, label.ligne, base=0.9)
            x0 = label.segment.x0
            for li in page.lignes[label.ligne.rang + 1:label.ligne.rang + 3]:
                for s in li.segments:
                    if abs(s.x0 - x0) < 0.03 and re.search(r"[A-Za-z]{3}", s.texte):
                        return self._lu_mots(s.mots, page, li, base=0.9)
        if client_tva is not None:
            # remonter le pavé aligné sur le numéro de TVA du client
            x0 = client_tva.lu.lecture.zone.x0 if client_tva.lu.lecture.zone else None
            if x0 is None:
                return None
            prec = None
            for li in reversed(page.lignes[:client_tva.ligne.rang]):
                segs = [s for s in li.segments if abs(s.x0 - x0) < 0.03]
                if not segs or client_tva.ligne.y0 - li.y1 > 0.08:
                    break
                prec = (segs[0], li)
            if prec is not None:
                return self._lu_mots(prec[0].mots, page, prec[1], base=0.8)
        return None

    # --- légende des codes TVA ---

    def _legende(self, pages: list[VuePage]) -> dict[str, tuple[Decimal | None, Lu]]:
        out: dict[str, tuple[Decimal | None, Lu]] = {}
        for p in pages:
            for li in p.lignes:
                txt = li.texte
                if "=" not in txt:
                    continue
                for m in re.finditer(r"(?<![\w])([A-Z0-9])\s*=\s*([^;=]*)", txt):
                    code, desc = m.group(1), cle_texte(m.group(2))
                    pc = re.search(r"(\d{1,2}(?:[.,]\d{1,2})?)\s*%", desc)
                    taux: Decimal | None = None
                    if pc:
                        taux = Decimal(pc.group(1).replace(",", "."))
                    elif re.search(r"exon|hors champ|outside|non soumis|debours|disbursement|exempt|zero|"
                                   r"hors tva|not subject|autoliquid|reverse", desc):
                        taux = Decimal("0")
                    mots = [w for w in li.mots if w.texte.startswith(code)][:1] or list(li.mots[:1])
                    out.setdefault(code, (taux, self._lu_mots(mots, p, li, base=0.9)))
        return out

    # --- tableaux ---

    def _lire_tableaux(self, pages: list[VuePage]) -> list[list[LigneLue]]:
        self._transports_tableaux: list[Lu] = []
        self._releve: list[EntreeReleve] = []
        tables: list[list[LigneLue]] = []
        for p in pages:
            k = 0
            while k < len(p.lignes):
                cols = _reconnaitre_entete(p.lignes[k])
                if p.methode is Methode.ocr:
                    # en-tête découpé par l'OCR sur deux lignes voisines (« Désignation » un peu plus bas)
                    fus = _entete_deux_lignes(p, k)
                    if fus is not None and (cols is None or len(fus[0]) > len(cols)):
                        cols = fus[0]
                        self.consommees.add((p.numero, k))
                        k = fus[1]
                if cols is None:
                    k += 1
                    continue
                self.consommees.add((p.numero, k))
                groupes = _groupes_colonnes(cols)
                fin = k + 1
                for i, g in enumerate(groupes):
                    # deux tableaux côte à côte : chacun lit les segments de sa bande horizontale
                    bornes = None if len(groupes) == 1 else (
                        g[0].x0 - 0.02, groupes[i + 1][0].x0 - 0.01 if i + 1 < len(groupes) else 1.01)
                    lignes, k_fin = self._lire_rangees(p, k, g, bornes)
                    fin = max(fin, k_fin)
                    # un tableau qui imprime le MRN sur ses lignes : une ligne sans MRN n'en a pas
                    if any(lg.mrn is not None for lg in lignes) and not any(lg.ref_autre for lg in lignes):
                        for lg in lignes:
                            lg.colonne_mrn = True
                    elif lignes and len(groupes) == 1 and not any(lg.mrn is not None for lg in lignes):
                        section = self._mrn_intertitre(p, k)
                        if section is not None:
                            # tableau groupé par envoi (« Envoi — MRN 26FR… » au-dessus de l'en-tête, D-2503)
                            for lg in lignes:
                                lg.mrn = lg.mrn or section
                                lg.colonne_mrn = True
                    tables.append(lignes)
                k = fin
        return tables

    def _lire_rangees(self, p: VuePage, k_entete: int, cols: list[ColonneFt],
                      bornes: tuple[float, float] | None = None) -> tuple[list[LigneLue], int]:
        lignes: list[LigneLue] = []
        k = k_entete + 1
        prec_y = p.lignes[k_entete].y1
        pas = p.pas_ligne
        pitchs: list[float] = []
        debut_num = min((c.x0 for c in cols if c.numerique), default=1.0)
        # lignes physiques très proches (scan incliné, cellule découpée par l'OCR) : une seule rangée
        seuil_fusion = min(0.45 * pas, 0.009) if p.methode is Methode.ocr else 0.0
        sautees = 0
        lus = 0  # rangées lues (même illisibles : montant brouillé par l'OCR)
        derniers: list[LigneLue] = []
        while k < len(p.lignes):
            li = p.lignes[k]
            if bornes is not None:
                li = _restreindre(li, bornes)
                if not li.segments:
                    break
            if p.methode is Methode.ocr and _ligne_parasite(li) and not re.search(r"\d", li.texte):
                k += 1  # tache, point, trait lus par l'OCR entre deux rangées : ignorés
                continue
            if L.REPORT.search(li.cle) and not _a_libelle_nature(li):
                # « Carried forward / Brought forward », « Übertrag », « Riporto » : report de page, ni
                # ligne ni fin de tableau
                self.consommees.add((p.numero, li.rang))
                prec_y = li.y1
                k += 1
                continue
            ecart = li.y0 - prec_y
            ref = max(pitchs) if pitchs else 2.5 * pas
            if ecart > max(2.2 * ref, 3.0 * pas, 0.03):
                break
            if _FIN_TABLEAU.match(li.cle) or _reconnaitre_entete(li):
                break
            groupe = [li]
            while seuil_fusion and k + len(groupe) < len(p.lignes):
                nxt = p.lignes[k + len(groupe)]
                dy = nxt.y0 - li.y0
                if _FIN_TABLEAU.match(nxt.cle) or dy >= 0.013:
                    break
                bruit = not re.search(r"[A-Za-z0-9]{2}", nxt.texte)
                complementaires = (_a_libelle(nxt, debut_num) and not _a_nombres(nxt, debut_num)
                                   and not _a_libelle(li, debut_num) and _a_nombres(li, debut_num)) or \
                                  (_a_libelle(li, debut_num) and not _a_nombres(li, debut_num)
                                   and not _a_libelle(nxt, debut_num) and _a_nombres(nxt, debut_num))
                if not (dy < seuil_fusion or bruit or complementaires):
                    break
                groupe.append(nxt)
            if len(groupe) > 1:
                segs = sorted((s for g in groupe for s in g.segments), key=lambda s: s.x0)
                li = VueLigne(page=li.page, rang=li.rang, segments=segs, ligne=li.ligne)
            cellules = _attribuer(li, cols)
            a_valeur = any(_contient_nombre(segs) for role, segs in cellules.items()
                           if role in _ROLES_VALEUR or role.startswith("nat:"))
            gauche = any(s.x0 < debut_num - 0.005 for s in li.segments)
            if not a_valeur or not gauche:
                mrn_suite = self._mrn_seul(p, li) if lus and gauche and not a_valeur else None
                if mrn_suite is not None and k + len(groupe) < len(p.lignes) \
                        and _reconnaitre_entete(p.lignes[k + len(groupe)]):
                    mrn_suite = None  # intertitre du tableau suivant (« Envoi — MRN … »), pas une suite (D-2503)
                if mrn_suite is not None and derniers and all(lg.mrn is None for lg in derniers):
                    # ligne de suite qui porte le MRN de la rangée précédente (« [26FR…] » sous le libellé)
                    for lg in derniers:
                        lg.mrn = mrn_suite
                    for g in groupe:
                        self.consommees.add((p.numero, g.rang))
                    prec_y = max(g.y1 for g in groupe)
                    k += len(groupe)
                    continue
                # (une ligne chiffrée sans montant lisible — « 2,5 % x 376,64 » — est une rangée illisible :
                # on ne lit pas au-delà, sauf bruit OCR)
                if lus and gauche and not a_valeur and (not re.search(r"\d", li.texte) or _ligne_parasite(li)) \
                        and self._rangee_suit(p, k + len(groupe), cols, debut_num,
                                                                             bornes, li):
                    # intertitre (« PRESTATIONS ») ou suite de libellé entre deux lignes du tableau
                    k += len(groupe)
                    continue
                if lus and gauche and not a_valeur and p.methode is Methode.ocr \
                        and (_a_libelle_nature(li) or any(_MRN_RE.search(m.texte) for m in li.mots)) \
                        and self._rangee_suit(p, k + len(groupe), cols, debut_num, bornes, li, illisible=True):
                    # rangée OCR dont les montants sont illisibles, entre deux rangées lues : elle est perdue
                    # (document partiel), mais la lecture du tableau continue (D-2505)
                    self.partielle = True
                    if "rangee_illisible" not in self.avertissements:
                        self.avertissements.append("rangee_illisible")
                    k += len(groupe)
                    continue
                if lus or sautees >= 1:
                    break
                sautees += 1
                k += len(groupe)
                continue
            if lignes:
                pitchs.append(li.y0 - lignes[-1].y)
            for g in groupe:
                self.consommees.add((p.numero, g.rang))
            derniers = self._rangee(p, li, cols, cellules)
            lus += 1
            lignes.extend(derniers)
            prec_y = max(g.y1 for g in groupe)
            k += len(groupe)
        return lignes, k

    def _mrn_intertitre(self, p: VuePage, k_entete: int) -> Lu | None:
        """MRN d'un intertitre placé juste au-dessus de l'en-tête d'un tableau (« Envoi — MRN 26FR… »,
        « Shipment 26FR… ») : ligne sans montant qui porte exactement un MRN."""
        if k_entete == 0:
            return None
        li = p.lignes[k_entete - 1]
        if p.lignes[k_entete].y0 - li.y1 > 3.0 * p.pas_ligne or any(_est_montant_txt(m.texte) for m in li.mots):
            return None
        if (p.numero, li.rang) in self.consommees:
            return None
        trouves = [m for m in li.mots if _MRN_RE.fullmatch(m.texte.strip(".,;:()[]|"))]
        if len(trouves) != 1:
            return None
        # un intertitre : le MRN accompagné de mots (« Envoi — MRN … »), sans date ni autre référence chiffrée
        # (une rangée d'un tableau « transport / MRN / date » n'en est pas un)
        autres = [m for m in li.mots if m is not trouves[0]]
        if not any(re.fullmatch(r"[^\W\d_]{3,}", m.texte.strip(".,;:()[]|—-")) for m in autres) \
                or any(re.search(r"\d", m.texte) for m in autres):
            return None
        m = trouves[0]
        t = m.texte.strip(".,;:()[]|")
        return self._lu_mots([m], p, li, base=C_RATTACHEMENT, brut=t if t != m.texte else None)

    def _mrn_seul(self, p: VuePage, li: VueLigne) -> Lu | None:
        """MRN d'une ligne sans montant qui ne porte que des références (suite d'une rangée)."""
        trouves = []
        for m in li.mots:
            t = m.texte.strip(".,;:()[]|")
            if _MRN_RE.fullmatch(t):
                trouves.append(self._lu_mots([m], p, li, brut=t if t != m.texte else None))
            elif re.search(r"\d", t) and not _DATE_RE.search(m.texte):
                return None
        return trouves[0] if len({norm_ref(x.texte) for x in trouves}) == 1 else None

    def _rangee_suit(self, p: VuePage, k: int, cols: list[ColonneFt], debut_num: float,
                     bornes: tuple[float, float] | None, prec: VueLigne, *, illisible: bool = False) -> bool:
        """La ligne ``k`` est une rangée du tableau (libellé à gauche, valeur en colonne), proche de ``prec`` :
        la ligne sans valeur qui les sépare est un intertitre ou une suite de libellé."""
        # lignes parasites (taches, tampon lu par l'OCR : « 4 eas », « es ») sautées
        while k < len(p.lignes) and _ligne_parasite(p.lignes[k]):
            k += 1
        if k >= len(p.lignes):
            return False
        li = p.lignes[k] if bornes is None else _restreindre(p.lignes[k], bornes)
        if not li.segments or li.y0 - prec.y1 > max(3.0 * p.pas_ligne, 0.03):
            return False
        if _FIN_TABLEAU.match(li.cle) or _reconnaitre_entete(li) or (not illisible and any(
                s.x0 >= debut_num - 0.005 for s in prec.segments)):
            return False
        cellules = _attribuer(li, cols)
        a_valeur = any(_contient_nombre(segs) for role, segs in cellules.items()
                       if role in _ROLES_VALEUR or role.startswith("nat:"))
        return a_valeur and any(s.x0 < debut_num - 0.005 for s in li.segments)

    def _rangee(self, p: VuePage, li: VueLigne, cols: list[ColonneFt],
                cellules: dict[str, list[Segment]]) -> list[LigneLue]:
        def lu_segs(segs: list[Segment], base: float = C_LIBELLE) -> Lu | None:
            mots = [m for s in segs for m in s.mots]
            return self._lu_mots(mots, p, li, base=base) if mots else None

        y = li.y0
        lib_segs = cellules.get("lib", []) + cellules.get("libcode", [])
        col_lib = next((c for c in cols if c.role in ("lib", "libcode")), None)
        if col_lib is not None and len(lib_segs) > 1:
            # code d'une colonne sans en-tête reconnu (« A », « E » : code TVA) imprimé avant le libellé
            lib_segs = [sg for sg in lib_segs if not (sg.x1 < col_lib.x0 - 0.003
                                                      and re.fullmatch(r"[A-Z0-9]{1,2}", sg.texte))]
        lib_txt = " ".join(s.texte for s in lib_segs).strip()
        code: Lu | None = None
        lib: Lu | None = None
        mots_lib = [m for s in lib_segs for m in s.mots]
        if mots_lib and re.fullmatch(r"\d{6,10}", re.sub(r"[ .]", "", lib_txt)):
            code = lu_segs(lib_segs)
        elif mots_lib:
            # un MRN collé au libellé (« Désignation   26FR… ») n'en fait pas partie
            mots_lib = [m for m in mots_lib if not _MRN_RE.fullmatch(m.texte.strip(".,;:()[]|"))]
            # signes isolés en bout de libellé (« Droits de douane : » lu par l'OCR) : hors libellé
            while mots_lib and not re.search(r"\w", mots_lib[-1].texte):
                mots_lib.pop()
            while mots_lib and not re.search(r"\w", mots_lib[0].texte):
                mots_lib.pop(0)
            lib = self._lu_mots(mots_lib, p, li) if mots_lib else None
        natflag = " ".join(s.texte for s in cellules.get("natflag", [])).strip() or None
        # MRN, transport, dates, pourcentage sur toute la rangée (colonnes texte)
        mrn = None
        transport = None
        date_rel = None
        dates: list[Lu] = []
        pourcentage = None
        pu_detail: Lu | None = None
        qte_detail: Lu | None = None
        for role in ("ref", "detail", "transport", "date", "lib", "libcode"):
            for s in cellules.get(role, []):
                for m in s.mots:
                    t = m.texte.strip(".,;:()[]|")
                    if mrn is None and _MRN_RE.fullmatch(t):
                        mrn = self._lu_mots([m], p, li, brut=t if t != m.texte else None)
                if role in ("ref", "detail", "date"):
                    for dm in _DATE_RE.finditer(s.texte):
                        ms = _mots_de_sous_chaine(s.mots, dm.start(), dm.end())
                        if ms:
                            dates.append(self._lu_mots(ms, p, li, brut=dm.group(0)))
                    pm = re.search(r"(\d{1,2}(?:[.,]\d{1,2})?)\s*%\s*(x|×|\*|sur|of|de)\b", s.texte)
                    if pm and pourcentage is None:
                        ms = _mots_de_sous_chaine(s.mots, pm.start(1), pm.end(1))
                        if ms:
                            pourcentage = self._lu_mots(ms, p, li, brut=pm.group(1))
                if role == "transport" and transport is None and s.mots:
                    txt = s.texte.strip()
                    if re.search(r"\d{4}", txt) and not _MRN_RE.fullmatch(txt):
                        transport = self._lu_mots(s.mots, p, li)
                if role == "date" and date_rel is None:
                    r = _accepte_date(s.mots)
                    if r is not None:
                        date_rel = self._lu_mots(s.mots[r[0]:r[1]], p, li)
        # colonne de références qui porte autre chose qu'un MRN (détail de calcul, référence interne)
        ref_autre = any(re.search(r"[A-Za-z0-9]", m.texte) and not _MRN_RE.fullmatch(m.texte.strip(".,;:()[]|"))
                        for s in cellules.get("ref", []) for m in s.mots)
        # « 3,00 x 7 » (détail, libellé ou base de calcul) : prix unitaire × quantité, retenus plus bas
        # seulement s'ils redonnent le montant de la ligne
        for role in ("ref", "detail", "date", "lib", "libcode", "base_droit"):
            for s in cellules.get(role, []):
                mx = re.search(r"(?<![\d%.,])(\d{1,6}[.,]\d{2})\s*[x×]\s*(\d{1,4})(?![\d.,])", s.texte)
                if mx and pu_detail is None:
                    ms_pu = _mots_de_sous_chaine(s.mots, mx.start(1), mx.end(1))
                    ms_q = _mots_de_sous_chaine(s.mots, mx.start(2), mx.end(2))
                    if ms_pu and ms_q:
                        pu_detail = self._lu_mots(ms_pu, p, li, base=0.93, brut=mx.group(1))
                        qte_detail = self._lu_mots(ms_q, p, li, base=0.93, brut=mx.group(2))
        if not dates:
            dates = self._periode_libelle(p, li, lib_segs)
        if transport is not None:
            self._transports_tableaux.append(transport)
        if transport is not None or (date_rel is not None and mrn is not None):
            self._releve.append(EntreeReleve(transport, mrn, date_rel))

        base = LigneLue(page=p, y=y, libelle=lib, mrn=mrn, code=code, pourcentage=pourcentage, natflag=natflag,
                        ref_autre=ref_autre)
        if len(dates) == 2:
            base.date_debut, base.date_fin = dates
        # colonnes numériques
        for role, segs in cellules.items():
            if role in _ROLES_TEXTE or role.startswith("nat:"):
                continue
            jetons = _jetons(segs)
            for typ, mots, brut in jetons:
                lu = self._lu_mots(mots, p, li, brut=brut)
                if role == "qte" and typ in ("entier", "nombre", "montant") and base.quantite is None:
                    base.quantite = lu
                elif role == "pu" and typ in ("montant", "nombre") and base.prix_unitaire is None:
                    base.prix_unitaire = lu
                elif role == "ht" and typ in ("montant",):
                    base.montant_ht = lu
                elif role == "ttc" and typ == "montant":
                    base.montant_ttc = lu
                elif role == "pu_ttc" and typ in ("montant", "nombre") and base.pu_ttc is None:
                    base.pu_ttc = lu
                elif role in ("taux", "tva", "cat") and typ == "exonere":
                    base.exoneree = True
                elif role == "ht" and typ == "marqueur" and base.marqueur is None:
                    base.marqueur = lu
                elif role == "base_droit" and typ == "montant":
                    base.base_droit = lu
                elif role in ("tva", "tva_mt", "cat", "taux"):
                    if typ == "montant" and role in ("tva", "tva_mt"):
                        base.montant_tva = lu
                    elif typ == "pourcent" or (typ in ("entier", "nombre") and role == "taux"):
                        base.taux_tva = lu
                    elif typ in ("marqueur", "code") or (typ == "entier" and role in ("cat", "tva")):
                        base.marqueur = base.marqueur or lu
                    elif typ == "code_taux" and brut:
                        mc = re.fullmatch(r"(\d)\s*[-–]\s*(\d{1,2}(?:[.,]\d{1,2})?)\s*%", brut)
                        if mc:
                            base.marqueur = base.marqueur or self._lu_mots(mots, p, li, brut=mc.group(1))
                            base.taux_tva = base.taux_tva or self._lu_mots(mots, p, li, brut=mc.group(2))
        if pu_detail is not None and qte_detail is not None and base.quantite is None \
                and base.prix_unitaire is None and base.montant_ht is not None:
            # « 3,00 x 7 » dans le détail : prix unitaire × quantité, retenus seulement s'ils redonnent le
            # montant de la ligne (sinon le détail décrit autre chose, ex. un forfait par article)
            pu_d, q_d, ht_d = (_montant_lu(x) for x in (pu_detail, qte_detail, base.montant_ht))
            if None not in (pu_d, q_d, ht_d) and _arrondi(pu_d * q_d) == ht_d:  # type: ignore[operator]
                base.prix_unitaire, base.quantite = pu_detail, qte_detail
        if base.montant_ht is None and base.quantite is not None and base.prix_unitaire is not None and \
                lib is not None and any(re.search(r"\w", sg.texte) for sg in cellules.get("ht", [])):
            # montant de la ligne imprimé mais illisible (OCR) : quantité × prix unitaire, valeur déduite
            base.ht_calcule = True
        sorties: list[LigneLue] = []
        if base.montant_ht is not None or base.ht_calcule or base.montant_ttc is not None:
            sorties.append(base)
        nat_cols = [col for col in cols if col.role.startswith("nat:")]
        nat_vals = []
        for col in nat_cols:
            segs = cellules.get(col.role, [])
            jetons = _jetons(segs)
            montants = [(m, b) for t, m, b in jetons if t == "montant"]
            if not montants:
                continue
            mots, brut = montants[-1]
            qte = None
            marq = None
            for t, m2, b2 in jetons:
                if t == "compte":
                    qte = self._lu_mots(m2, p, li, brut=b2)
                elif t == "marqueur":
                    marq = self._lu_mots(m2, p, li, brut=b2)
            nat_vals.append((col, self._lu_mots(mots, p, li, brut=brut), qte, marq))
        lib_nature = classer_nature(lib.texte if lib else None)
        for col, montant, qte, marq in nat_vals:
            nature = NatureLigne(col.role[4:])
            libelle = lib
            entete = False
            if lib is not None and lib_nature is not None and len(nat_vals) == 1 and lib_nature.est_debours \
                    and nature.est_debours:
                nature = lib_nature
            elif lib is not None and lib_nature is None and len(nat_vals) == 1:
                pass
            else:
                libelle = self._lu_mots(col.mots, p, _ligne_de(p, col.mots[0]) or li) if col.mots else None
                entete = True
            ligne = LigneLue(page=p, y=y, libelle=libelle, libelle_entete=entete, nature=nature,
                             quantite=qte, montant_ht=montant, marqueur=marq or base.marqueur, mrn=mrn,
                             code=code, natflag=natflag, ref_autre=ref_autre)
            if nature is NatureLigne.debours_droits and base.base_droit is not None:
                ligne.base_droit = base.base_droit
            sorties.append(ligne)
        for lg in sorties:
            if lg is base or not lg.libelle_entete:
                n = classer_nature(lg.libelle.texte if lg.libelle else None, tolerant=True)
                if lg is base:
                    lg.nature = n or NatureLigne.autre_prestation
        return sorties

    # --- totaux ---

    def _periode_libelle(self, p: VuePage, li: VueLigne, lib_segs: list[Segment]) -> list[Lu]:
        """Période écrite dans le libellé (« Lagergeld (07/03/2026 – 15/03/2026) », « Storage 01/06/2026 to
        05/06/2026 ») sans colonne de dates : exactement deux dates reliées par un séparateur d'intervalle
        (D-2301). Une date isolée ou trois dates ne donnent rien."""
        for s in lib_segs:
            trouvees = list(_DATE_RE.finditer(s.texte))
            if len(trouvees) != 2:
                continue
            entre = s.texte[trouvees[0].end():trouvees[1].start()]
            if not _RX_SEP_PERIODE.fullmatch(entre):
                continue
            out: list[Lu] = []
            for dm in trouvees:
                ms = _mots_de_sous_chaine(s.mots, dm.start(), dm.end())
                if not ms:
                    return []
                out.append(self._lu_mots(ms, p, li, brut=dm.group(0)))
            return out
        return []

    def _totaux(self, pages: list[VuePage]) -> dict[str, Total]:
        out: dict[str, Total] = {}
        for p in pages:
            for k_li, li in enumerate(p.lignes):
                if (p.numero, li.rang) in self.consommees:
                    continue
                if L.REPORT.search(li.cle):
                    continue  # « Carried forward EUR 22 589,44 » : un report, pas un total
                mots = li.mots
                nbs = [n for n in _nombres(mots) if not n.tronque and _est_montant_txt(n.texte)]
                if not nbs:
                    # bloc de totaux « libellé au-dessus, montant en dessous » (« NET À PAYER » / « 1 695,28 € »)
                    tot = self._total_dessous(p, k_li, li)
                    if tot is not None and tot.cle not in out:
                        out[tot.cle] = tot
                    continue
                n = nbs[-1]
                cle = None
                lib_txt = ""
                # libellé : d'abord le texte immédiatement à gauche du montant (bloc de totaux voisin d'un
                # autre pavé sur la même ligne), puis toute la ligne à gauche du montant
                for lib_txt in (_libelle_proche(li, mots[n.i]), _libelle_ligne(mots, n, len(nbs))):
                    if not lib_txt:
                        continue
                    cle = _cle_total(lib_txt)
                    if cle is not None:
                        break
                if cle is None or cle == "ignore":
                    continue
                if self.avoir and cle == "total_ttc" and re.match(r"^total credited excl", lib_txt):
                    cle = "total_ht"
                j = n.j
                brut = n.texte
                lu = self._lu_mots(mots[n.i:j], p, li, brut=brut)
                taux = None
                pc = re.search(r"(\d{1,2}(?:[.,]\d{1,2})?)\s*%", lib_txt)
                if pc:
                    taux = Decimal(pc.group(1).replace(",", "."))
                out[cle] = Total(cle, lu, taux)
        return out

    def _total_dessous(self, p: VuePage, k_li: int, li: VueLigne) -> Total | None:
        """Libellé de total seul sur sa ligne, montant seul juste en dessous, aligné sous le libellé ou à sa
        droite (bloc « à payer » en tête de page)."""
        if not li.segments:
            return None
        s = li.segments[-1]
        cle_s = cle_texte(s.texte).rstrip(" :")
        cle = _cle_total(cle_s, complet=True)
        if cle is None or cle == "ignore":
            return None
        for li2 in p.lignes[k_li + 1:k_li + 3]:
            if li2.y0 - li.y1 > 0.03:
                break
            for s2 in li2.segments:
                if s2.x1 < s.x0 - 0.02 or s2.x0 > s.x1 + 0.25:
                    continue
                nbs = [n for n in _nombres(list(s2.mots)) if not n.tronque and _est_montant_txt(n.texte)]
                pris = {k for n in nbs for k in range(n.i, n.j)}
                reste = [m for k, m in enumerate(s2.mots) if k not in pris]
                if len(nbs) != 1 or any(re.search(r"[A-Za-z]{2}", m.texte) and not _est_devise_txt(m.texte)
                                        for m in reste):
                    continue
                if any(t.x1 <= s2.x0 and t.x1 > s.x0 - 0.02 and re.search(r"[A-Za-z]{3}", t.texte)
                       for t in li2.segments if t is not s2):
                    continue  # un autre libellé précède le montant sur sa ligne : ce n'est pas notre valeur
                n = nbs[0]
                return Total(cle, self._lu_mots(list(s2.mots[n.i:n.j]), p, li2, base=0.93, brut=n.texte))
        return None

    # --- lignes ---

    def _lignes(self, tables: list[list[LigneLue]], mrns: list[Lu], legende: dict, totaux: dict[str, Total]) -> None:
        c = self.champs
        mrn_unique = mrns[0] if len(mrns) == 1 else None
        taux_global = totaux["total_tva"].taux if "total_tva" in totaux else None
        lignes = _sans_renvois_annexe([lg for t in tables for lg in t], tables)
        idx = 0
        for lg in lignes:
            if lg.montant_ht is None and not lg.ht_calcule and lg.montant_ttc is None:
                continue
            pre = f"lignes[{idx}]."
            idx += 1
            vals: dict[str, ValeurSourcee | None] = {}
            ttc_seul = lg.montant_ht is None and not lg.ht_calcule and lg.montant_ttc is not None
            vals["montant_ttc"] = self._vs(pre + "montant_ttc", lg.montant_ttc)
            # libellé d'une colonne « par nature » : l'en-tête imprimé de la colonne (« Droits », « Duty »)
            lib = Lu(lg.libelle.lecture, base=0.9, brut=lg.libelle.brut) if lg.libelle and lg.libelle_entete \
                else lg.libelle
            vals["libelle"] = self._vs(pre + "libelle", lib, type_valeur=TypeValeur.texte)
            vals["montant_ht"] = self._vs(pre + "montant_ht", lg.montant_ht)
            vals["quantite"] = self._vs(pre + "quantite", lg.quantite, type_valeur=TypeValeur.quantite)
            vals["prix_unitaire"] = self._vs(pre + "prix_unitaire", lg.prix_unitaire)
            if vals["montant_ht"] is None and lg.ht_calcule:
                q_vs = self._vs(pre + "quantite", lg.quantite, type_valeur=TypeValeur.quantite)
                pu_vs = self._vs(pre + "prix_unitaire", lg.prix_unitaire)
                q_d, pu_d = _dec(q_vs), _dec(pu_vs)
                vals["montant_ht"] = None if q_d is None or pu_d is None else self._derive(pre + "montant_ht", str(_arrondi(q_d * pu_d)),
                                                  [v for v in (q_vs, pu_vs) if v is not None],
                                                  "quantite × prix_unitaire")
            vals["montant_tva"] = self._vs(pre + "montant_tva", lg.montant_tva)
            vals["taux_tva"] = self._vs(pre + "taux_tva", lg.taux_tva, type_valeur=TypeValeur.taux)
            tx_lu = _dec(vals["taux_tva"])
            if tx_lu is not None and tx_lu > 100:
                vals["taux_tva"] = None  # « 2000 » : virgule perdue par l'OCR, pas un taux
            if ttc_seul:
                self._ligne_ttc(pre, lg, vals)
            vals["marqueur_tva"] = self._vs(pre + "marqueur_tva", lg.marqueur, type_valeur=TypeValeur.code)
            vals["code_marchandise"] = self._vs(pre + "code_marchandise", lg.code, type_valeur=TypeValeur.code)
            vals["base_droit"] = self._vs(pre + "base_droit", lg.base_droit)
            vals["pourcentage"] = self._vs(pre + "pourcentage", lg.pourcentage, type_valeur=TypeValeur.taux)
            vals["date_debut"] = self._vs(pre + "date_debut", lg.date_debut, type_valeur=TypeValeur.date)
            vals["date_fin"] = self._vs(pre + "date_fin", lg.date_fin, type_valeur=TypeValeur.date)
            if lg.mrn is not None:
                canon = self.mrn_variantes.get(norm_ref(lg.mrn.texte))
                if canon is not None and norm_ref(canon.texte) != norm_ref(lg.mrn.texte):
                    lg.mrn = Lu(canon.lecture, base=min(canon.base, 0.7), brut=canon.brut)
                vals["mrn"] = self._vs(pre + "mrn", lg.mrn, type_valeur=TypeValeur.reference)
            elif mrn_unique is not None and not lg.colonne_mrn:
                vals["mrn"] = self._vs(pre + "mrn", Lu(mrn_unique.lecture, base=min(mrn_unique.base, C_RATTACHEMENT),
                                                       brut=mrn_unique.brut), type_valeur=TypeValeur.reference)
            ht = _dec(vals["montant_ht"])
            # quantité / prix unitaire
            q = _dec(vals["quantite"])
            if vals["quantite"] is None:
                vals["quantite"] = self._derive(pre + "quantite", "1", [], "quantite_non_imprimee", plafond=C_DEDUITE)
                q = Decimal(1)
            net_derive = vals["montant_ht"] is not None and vals["montant_ht"].methode is Methode.derive \
                and vals["montant_ht"].regle_derivation == "montant_ttc / (1 + taux_tva)"
            if vals["prix_unitaire"] is None and ht is not None and q and not net_derive:
                pu = ht / q
                if _arrondi(pu) * q == ht:
                    srcs = [v for v in (vals["montant_ht"], vals["quantite"]) if v is not None]
                    vals["prix_unitaire"] = self._derive(pre + "prix_unitaire", str(_arrondi(pu)), srcs,
                                                         "montant_ht / quantite",
                                                         plafond=0.8 if lg.quantite is not None else C_DEDUITE)
            # taux de TVA
            if vals["taux_tva"] is None:
                taux, srcs, regle = self._taux_deduit(lg, vals, legende, taux_global)
                if taux is not None:
                    vals["taux_tva"] = self._derive(pre + "taux_tva", _fmt_taux(taux), srcs, regle)
            if vals["montant_tva"] is None and ht is not None and not ttc_seul:
                tx = _dec(vals["taux_tva"])
                if tx is not None:
                    srcs = [v for v in (vals["montant_ht"], vals["taux_tva"]) if v is not None]
                    vals["montant_tva"] = self._derive(pre + "montant_tva", str(_arrondi(ht * tx / 100)), srcs,
                                                       "montant_ht × taux_tva")
            if "rangee_illisible" in self.avertissements:
                # une rangée du tableau est perdue : toute somme de lignes est incomplète ; aucun montant de
                # ligne ne fonde seul un écart certain (D-2505)
                for k in ("montant_ht", "montant_ttc", "montant_tva"):
                    v = vals.get(k)
                    if v is not None and v.confiance > C_RANGEE_PERDUE:
                        vals[k] = v.model_copy(update={"confiance": C_RANGEE_PERDUE})
            for k, v in vals.items():
                if v is not None:
                    c.definir(pre + k, v)
            ligne: LigneFactureTransitaire = c.obtenir(f"lignes[{idx - 1}]")
            ligne.nature = lg.nature
        if not self.avoir:
            for e in self._releve:
                if e.mrn is None:
                    continue
                k = len(c.tableau_mrn)  # type: ignore[union-attr]
                c.tableau_mrn.append(LigneTableauMrn())  # type: ignore[union-attr]
                for nom, lu, tv in (("ref_transport", e.transport, TypeValeur.reference),
                                    ("mrn", e.mrn, TypeValeur.reference), ("date", e.date, TypeValeur.date)):
                    v = self._vs(f"tableau_mrn[{k}].{nom}", lu, type_valeur=tv)
                    if v is not None:
                        c.definir(f"tableau_mrn[{k}].{nom}", v)

    def _ligne_ttc(self, pre: str, lg: LigneLue, vals: dict[str, ValeurSourcee | None]) -> None:
        """Ligne d'un tableau « TVA comprise » (montant et prix unitaire imprimés TTC, D-2502).

        Seul ce qui est imprimé est exposé : ``montant_ttc`` et le taux. Une ligne exonérée (« isento »,
        « 0 % ») a un montant HT égal au montant imprimé. Pour une ligne taxée, le HT n'est pas imprimé : il
        est **dérivé** (TTC / (1 + taux)), marqué ``derive`` et plafonné à ``C_DEDUITE`` — jamais lu comme
        imprimé ; le prix unitaire HT et la TVA de la ligne ne sont pas fabriqués."""
        ttc = vals["montant_ttc"]
        taux_lu = _montant_lu(lg.taux_tva) if lg.taux_tva is not None else None
        if lg.exoneree or (taux_lu is not None and taux_lu == 0):
            if lg.exoneree and lg.taux_tva is None:
                vals["taux_tva"] = self._derive(pre + "taux_tva", "0", [], "mention_exoneration_imprimee",
                                                plafond=0.9)
            ht_lu = Lu(lg.montant_ttc.lecture, base=min(lg.montant_ttc.base, 0.93), brut=lg.montant_ttc.brut)  # type: ignore[union-attr]
            vals["montant_ht"] = self._vs(pre + "montant_ht", ht_lu)
            if vals["prix_unitaire"] is None and lg.pu_ttc is not None:
                vals["prix_unitaire"] = self._vs(pre + "prix_unitaire",
                                                 Lu(lg.pu_ttc.lecture, base=min(lg.pu_ttc.base, 0.93),
                                                    brut=lg.pu_ttc.brut))
            return
        ttc_d = _dec(ttc)
        if ttc is None or ttc_d is None or taux_lu is None or taux_lu not in TAUX_TVA_CONNUS:
            return
        srcs = [v for v in (ttc, vals.get("taux_tva")) if v is not None]
        net = _arrondi(ttc_d * 100 / (100 + taux_lu))
        vals["montant_ht"] = self._derive(pre + "montant_ht", str(net), srcs, "montant_ttc / (1 + taux_tva)")
        if ttc.signe_imprime is not None:
            vals["montant_ht"] = vals["montant_ht"].model_copy(update={"signe_imprime": ttc.signe_imprime})

    def _taux_deduit(self, lg: LigneLue, vals: dict, legende: dict, taux_global: Decimal | None):
        ht = _dec(vals["montant_ht"])
        tva = _dec(vals["montant_tva"])
        marq = vals.get("marqueur_tva")
        if marq is not None and marq.valeur in legende and legende[marq.valeur][0] is not None:
            return legende[marq.valeur][0], [marq], "legende_codes_tva"
        if tva is not None and ht:
            for t in TAUX_TVA_CONNUS:
                if abs(_arrondi(ht * t / 100) - tva) <= _CENT:
                    return t, [v for v in (vals["montant_ht"], vals["montant_tva"]) if v], "montant_tva / montant_ht"
            return None, [], ""
        if tva is not None and ht == 0 and tva == 0:
            return Decimal(0), [vals["montant_tva"]], "montant_tva_nul"
        if lg.nature.est_debours:
            return Decimal(0), [], "debours_hors_tva"
        if taux_global is not None:
            return taux_global, [], "taux_unique_du_document"
        return None, [], ""

    # --- totaux du document ---

    def _totaux_champs(self, totaux: dict[str, Total]) -> None:
        c = self.champs
        noms = {"total_ht": "total_credite_ht", "total_ttc": "total_credite_ttc", "total_tva": "total_tva"} \
            if self.avoir else {k: k for k in ("total_ht", "total_tva", "total_ttc", "net_a_payer", "acomptes",
                                               "total_debours")}
        for cle, t in totaux.items():
            if cle not in noms:
                continue
            v = self._vs(noms[cle], t.lu)
            if v is None:
                continue
            if cle == "total_debours":
                v = v.model_copy(update={"total_origine": TotalOrigine.imprime})
            c.definir(noms[cle], v)
        lignes: list[LigneFactureTransitaire] = list(c.lignes)
        hts = [lg.montant_ht for lg in lignes if lg.montant_ht is not None]
        if not self.avoir and c.total_debours is None and lignes:  # type: ignore[union-attr]
            deb = [lg.montant_ht for lg in lignes if lg.nature.est_debours and lg.montant_ht is not None]
            if deb:
                v = deriver_somme(chemin_complet(self.td, "total_debours"), deb, document_id=self.document_id,
                                  extracteur=self.info, unite="EUR", regle="somme_lignes_debours",
                                  total_reconstruit=True)
            else:
                v = self._derive("total_debours", "0.00", [], "aucune_ligne_de_debours", plafond=0.5,
                                 total_reconstruit=True)
            c.definir("total_debours", v)
        cle_ht = "total_credite_ht" if self.avoir else "total_ht"
        cle_ttc = "total_credite_ttc" if self.avoir else "total_ttc"
        if c.obtenir(cle_ht) is None and hts:
            c.definir(cle_ht, deriver_somme(chemin_complet(self.td, cle_ht), hts, document_id=self.document_id,
                                            extracteur=self.info, unite="EUR", regle="somme_lignes",
                                            total_reconstruit=True))
        elif c.obtenir(cle_ht) is None and not lignes and not self.avoir:
            # aucune ligne : total HT = total à payer − TVA (ou total des débours seul imprimé)
            net, tva, deb = c.net_a_payer, c.obtenir("total_tva"), c.total_debours  # type: ignore[union-attr]
            if net is not None and tva is not None:
                c.definir(cle_ht, self._derive(cle_ht, str((_dec(net) or 0) - (_dec(tva) or 0)), [net, tva],
                                               "net_a_payer - total_tva", plafond=0.5, total_reconstruit=True))
            elif deb is not None:
                c.definir(cle_ht, self._derive(cle_ht, deb.valeur or "0", [deb], "total_debours_seul",
                                               plafond=0.5, total_reconstruit=True))
        if c.obtenir("total_tva") is None:
            tvas = [lg.montant_tva for lg in lignes if lg.montant_tva is not None]
            if tvas and len(tvas) == len(lignes):
                c.definir("total_tva", deriver_somme(chemin_complet(self.td, "total_tva"), tvas,
                                                     document_id=self.document_id, extracteur=self.info,
                                                     unite="EUR", regle="somme_lignes", total_reconstruit=True))
        if c.obtenir(cle_ttc) is None:
            ht, tva = c.obtenir(cle_ht), c.obtenir("total_tva")
            net = None if self.avoir else c.net_a_payer  # type: ignore[union-attr]
            if ht is not None and tva is not None:
                v = deriver_somme(chemin_complet(self.td, cle_ttc), [ht, tva], document_id=self.document_id,
                                  extracteur=self.info, unite="EUR", regle="total_ht + total_tva",
                                  total_reconstruit=True)
                c.definir(cle_ttc, v)
            elif net is not None:
                c.definir(cle_ttc, self._derive(cle_ttc, net.valeur, [net], "net_a_payer_sans_acompte"))

    # --- recoupements arithmétiques (OCR) ---

    def _coherence(self) -> None:
        """Ajuste la confiance des lectures OCR : recoupées par l'arithmétique -> relevées (plafond 0,92) ;
        contredites -> abaissées. Le texte natif n'est pas modifié (une incohérence y est un constat)."""
        c = self.champs
        lignes: list[LigneFactureTransitaire] = list(c.lignes)
        maj: dict[str, float] = {}

        def ocr(v: ValeurSourcee | None) -> bool:
            return v is not None and v.methode is Methode.ocr

        def relever(vs: Sequence[ValeurSourcee | None]) -> None:
            for v in vs:
                if ocr(v) and v.ancree:  # type: ignore[union-attr]
                    maj[v.id] = max(maj.get(v.id, 0.0), -1.0)  # type: ignore[union-attr]

        def abaisser(vs: Sequence[ValeurSourcee | None]) -> None:
            for v in vs:
                if ocr(v):
                    maj[v.id] = -2.0  # type: ignore[union-attr]

        for lg in lignes:
            q, pu, ht = _dec(lg.quantite), _dec(lg.prix_unitaire), _dec(lg.montant_ht)
            if lg.quantite is not None and lg.prix_unitaire is not None and lg.quantite.methode is not Methode.derive \
                    and lg.prix_unitaire.methode is not Methode.derive and None not in (q, pu, ht):
                if abs(_arrondi(q * pu) - ht) <= _CENT:  # type: ignore[operator]
                    relever([lg.quantite, lg.prix_unitaire, lg.montant_ht])
                else:
                    abaisser([lg.quantite, lg.prix_unitaire, lg.montant_ht])
            tx, tva = _dec(lg.taux_tva), _dec(lg.montant_tva)
            if None not in (tx, tva, ht) and lg.montant_tva.methode is not Methode.derive:  # type: ignore[union-attr]
                if abs(_arrondi(ht * tx / 100) - tva) <= _CENT:  # type: ignore[operator]
                    relever([lg.montant_tva])
                else:
                    abaisser([lg.montant_tva])
        cle_ht = "total_credite_ht" if self.avoir else "total_ht"
        cle_ttc = "total_credite_ttc" if self.avoir else "total_ttc"
        tht, ttva, tttc = c.obtenir(cle_ht), c.obtenir("total_tva"), c.obtenir(cle_ttc)
        hts = [lg.montant_ht for lg in lignes if lg.montant_ht is not None]
        if tht is not None and tht.methode is not Methode.derive and hts:
            s = sum((_dec_signe(v) or Decimal(0)) for v in hts)
            if abs(s - (_dec_signe(tht) or Decimal(0))) <= _CENT:
                relever([tht, *hts])
            else:
                abaisser([tht])
        if None not in (tht, ttva, tttc) and tttc.methode is not Methode.derive:  # type: ignore[union-attr]
            if abs((_dec(tht) or 0) + (_dec(ttva) or 0) - (_dec(tttc) or 0)) <= _CENT:
                relever([tht, ttva, tttc])
            else:
                abaisser([ttva, tttc])
        if not self.avoir:
            td = c.total_debours  # type: ignore[union-attr]
            deb = [lg.montant_ht for lg in lignes if lg.nature.est_debours and lg.montant_ht is not None]
            if td is not None and td.methode is not Methode.derive and deb:
                if abs(sum((_dec_signe(v) or Decimal(0)) for v in deb) - (_dec_signe(td) or Decimal(0))) <= _CENT:
                    relever([td, *deb])
                else:
                    abaisser([td])
                    if any(ocr(v) for v in (td, *deb)):
                        # lecture OCR : des lignes de débours manquent ou sont mal lues ; aucune ne fonde seule
                        # un écart certain (base d'une commission, somme par nature… D-2505)
                        for v in deb:
                            if maj.get(v.id) != -2.0:
                                maj[v.id] = -3.0
            net = c.net_a_payer  # type: ignore[union-attr]
            if net is not None and tttc is not None and net.methode is Methode.ocr \
                    and abs((_dec(net) or 0) - (_dec(tttc) or 0)) <= _CENT:
                relever([net, tttc])
        if not maj:
            return
        for chemin_rel, v in list(_feuilles(c)):
            if v.id not in maj:
                continue
            if maj[v.id] == -2.0:
                nv = v.model_copy(update={"confiance": min(v.confiance, C_OCR_INCOHERENTE)})
            elif maj[v.id] == -3.0:
                nv = v.model_copy(update={"confiance": min(v.confiance, C_RANGEE_PERDUE)})
            elif v.type is TypeValeur.montant and _montant_ocr_suspect(v.valeur_brute):
                continue
            elif v.type is TypeValeur.montant and chemin_rel.startswith("lignes[") \
                    and "rangee_illisible" in self.avertissements:
                continue  # rangée perdue : les montants de ligne restent sous le plafond (D-2505)
            else:
                ocr_min = _conf_ocr_min(v, self.vue)
                if ocr_min is None or ocr_min < 0.9:
                    continue
                nv = v.model_copy(update={"confiance": max(v.confiance, min(C_OCR_RECOUPEE, 0.2 + 0.75 * ocr_min
                                                                            + 0.05))})
            c.definir(chemin_rel, nv)


# --- fonctions auxiliaires -----------------------------------------------------------------------------------------


def _prefixe_valeur():
    from controldone.ids import Prefixe

    return Prefixe.valeur


def _nouvel_id() -> str:
    from controldone.ids import Prefixe, nouvel_id

    return nouvel_id(Prefixe.valeur)


def _fmt_taux(t: Decimal) -> str:
    return str(t.normalize()) if t != t.to_integral_value() else str(int(t))


def _feuilles(c) -> list[tuple[str, ValeurSourcee]]:
    from controldone.model.champs import chemin_relatif

    return [(chemin_relatif(v.chemin), v) for v in c.iter_valeurs()]


def _conf_ocr_min(v: ValeurSourcee, vue: VueDocument) -> float | None:
    if v.zone is None or v.page is None:
        return None
    p = vue.page(v.page)
    if p is None:
        return None
    cs = [m.confiance for m in p.texte.mots_dans(v.zone, recouvrement=0.6) if m.confiance is not None]
    return min(cs) if cs else None


#: Confiance OCR minimale des mots d'un numéro de TVA dont la clé confirme la lecture (D-2302).
C_OCR_TVA_CLE_MIN = 0.6


def _conf_tva_cle_valide(lt: LectureTva, conf_attribution: float) -> float | None:
    """Numéro de TVA français lu par OCR dont la **clé de contrôle** est juste (D-2302) : la clé (modulo 97)
    détecte toute substitution d'un chiffre et toute permutation de deux chiffres voisins, elle confirme donc
    la lecture des caractères. La confiance est alors celle de l'attribution du numéro (pavé libellé ou non),
    plafonnée comme une lecture OCR recoupée (``C_OCR_RECOUPEE``). ``None`` (règle ordinaire) sinon : texte natif, numéro
    corrigé, clé fausse ou non vérifiable, mots OCR peu sûrs."""
    lec = lt.lu.lecture
    if lec is None or lec.methode is not Methode.ocr or lt.corrigee or tva_fr_valide(lt.norm) is not True:
        return None
    c = lec.confiance_ocr
    if c is None or c < C_OCR_TVA_CLE_MIN:
        return None
    return min(conf_attribution, C_OCR_RECOUPEE)


def _ligne_de(p: VuePage, mot: Mot) -> VueLigne | None:
    for li in p.lignes:
        if any(m is mot for m in li.mots):
            return li
    return None


def _mots_de_sous_chaine(mots: Sequence[Mot], debut: int, fin: int) -> list[Mot]:
    """Mots d'un segment couvrant la sous-chaîne [debut, fin) de son texte (mots joints par une espace)."""
    out, pos = [], 0
    for m in mots:
        a, b = pos, pos + len(m.texte)
        if b > debut and a < fin:
            out.append(m)
        pos = b + 1
    return out


def _est_tva_contexte(li: VueLigne, m: Mot) -> bool:
    mots = li.mots
    k = next((i for i, x in enumerate(mots) if x is m), -1)
    avant = cle_texte(" ".join(x.texte for x in mots[max(0, k - 3):k]))
    return bool(re.search(r"(tva|vat|siren|siret|rcs|eori|iban)\W*$", avant))


def _siren_pied(pages: list[VuePage]) -> str | None:
    for p in pages:
        for li in p.lignes:
            m = re.search(r"\b(?:rcs|siren|siret)\b[^\d]{0,40}?(\d{3}\s?\d{3}\s?\d{3})", li.cle)
            if m:
                return re.sub(r"\s", "", m.group(1))
    return None


_CHIFFRES_OCR = str.maketrans({"O": "0", "o": "0", "D": "0", "Q": "0", "I": "1", "l": "1", "|": "1", "i": "1",
                                "S": "5", "s": "5", "B": "8", "Z": "2", "z": "2", "T": "7", "G": "6", "A": "4"})


def _tva_ocr(mots: Sequence[Mot]) -> tuple[int, int, str, bool] | None:
    """Numéro de TVA français lu par l'OCR, éventuellement corrigé (« FRO7000909341 », « FA69000455337 »,
    « FR680004585 70 ») : retenu seulement si la clé de contrôle est valide. Renvoie (i, j, forme, corrigé)."""
    for k, m in enumerate(mots):
        t = re.sub(r"^(?:tva|vat|n°)[.:]?", "", m.texte.strip(":;,()"), flags=re.IGNORECASE)
        mm = re.match(r"^([A-Z]{2})([0-9A-Za-z]*)$", t)
        if not mm or (mm.group(1) in PAYS_TVA and mm.group(1) != "FR"):
            continue
        if mm.group(1) != "FR" and not re.fullmatch(r"F[A-Z]|[A-Z]R", mm.group(1)):
            continue
        corps = mm.group(2)
        j = k + 1
        while j < len(mots) and len(corps) < 11 and re.fullmatch(r"[0-9A-Za-z]{1,11}", mots[j].texte.strip(":;,()")):
            corps += mots[j].texte.strip(":;,()")
            j += 1
        if len(corps) != 11:
            continue
        corrige = corps.translate(_CHIFFRES_OCR)
        if not corrige.isdigit() or not tva_fr_valide("FR" + corrige):
            continue
        return k, j, "FR" + corrige, corrige != corps or mm.group(1) != "FR" or j > k + 1
    return None


_BORDS_GRILLE = "|[]{}¦"


def _nettoyer(pt: PageText) -> PageText:
    """Page OCR : traits de grille de tableau lus comme caractères (« | », « [ ») retirés des mots ; un mot
    réduit à un trait disparaît. Le texte de la page (ancrage) est inchangé : un mot nettoyé reste une
    sous-chaîne du texte lu."""
    if pt.source != "ocr":
        return pt
    lignes = []
    for li in pt.lignes:
        mots = []
        for m in li.mots:
            t = m.texte.strip(_BORDS_GRILLE)
            if not t or not t.strip("_—-"):
                if t and t in "-—":
                    mots.append(m)
                continue
            mots.append(m if t == m.texte else Mot(t, m.x0, m.y0, m.x1, m.y1, m.confiance, m.taille))
        # « 534, 06 » : décimales détachées par l'OCR -> un seul nombre (non ancré : valeur reconstituée)
        fusion: list[Mot] = []
        for m in mots:
            if fusion and re.fullmatch(r"\(?-?\d[\d .]*[.,]", fusion[-1].texte) and re.fullmatch(r"\d{2}\)?", m.texte) \
                    and m.x0 - fusion[-1].x1 < 0.012:
                a = fusion.pop()
                m = Mot(a.texte + m.texte, a.x0, min(a.y0, m.y0), m.x1, max(a.y1, m.y1),
                        min(x for x in (a.confiance, m.confiance) if x is not None) if (a.confiance or m.confiance)
                        else None, a.taille)
            fusion.append(m)
        mots = fusion
        if mots:
            lignes.append(Ligne(texte=" ".join(x.texte for x in mots), mots=tuple(mots)))
    return PageText(numero=pt.numero, texte=pt.texte, lignes=lignes, qualite=pt.qualite, source=pt.source,
                    score_natif=pt.score_natif, score_ocr=pt.score_ocr, rotation=pt.rotation,
                    desinclinaison=pt.desinclinaison, largeur=pt.largeur, hauteur=pt.hauteur, feuille=pt.feuille)


def _montant_lu(lu: Lu) -> Decimal | None:
    m = parse_amount(lu.texte.replace("\u202f", " "))
    return m.valeur if m else None


def _montant_ocr_suspect(brut: str | None) -> bool:
    """Montant OCR de 1 000 ou plus imprimé sans séparateur de milliers : l'OCR a pu lire le séparateur
    (espace fine, glyphe de remplacement) comme un chiffre (« 1 559,80 » -> « 10559,80 »). Une lecture
    recoupée par l'arithmétique peut l'être à tort (erreur systématique sur toutes les lignes)."""
    if not brut:
        return False
    t = brut.strip("()-− ")
    m = re.match(r"^(\d+)(?:[.,]\d{1,2})?$", t.replace(" ", ""))
    return bool(m) and len(m.group(1)) >= 4 and not re.search(r"\d[ .,'’\u202f\u00a0]\d{3}", t)


def _ressemble_tva(txt: str) -> bool:
    """Numéro de TVA (pays européen + 8 à 12 chiffres, sans tiret ni barre)."""
    t = txt.strip(":;,()")
    if re.search(r"[-/]", t):
        return False
    n = norm_ref(t)
    return n[:2] in PAYS_TVA and bool(re.fullmatch(r"[0-9A-Z]{2}\d{7,12}", n[2:]))


_PREFIXE_TOTAL = re.compile(
    r"^.*?(?=(total|totale|totaal|summe|sous-total|subtotal|net a payer|amount due|debours|disbursements|tva|vat|"
    r"ttc|gross|acompte|deposit|reste a payer|balance due|rechnungsbetrag|nettobetrag|mwst|iva|btw|"
    r"di cui|base imponible)\b)")


def _est_devise_txt(t: str) -> bool:
    return cle_texte(t).strip(".:") in ("eur", "euro", "euros", "€")


def _cle_total(lib_txt: str, *, complet: bool = False) -> str | None:
    """Clé du total reconnu par son libellé ; ``complet`` : le libellé entier doit être reconnu."""
    for k, motif in _TOTAUX:
        m = motif.match(lib_txt)
        if m and (not complet or len(lib_txt) - m.end() <= 4):
            return k
    return None


def _libelle_proche(li: VueLigne, mot_nombre: Mot) -> str:
    """Texte immédiatement à gauche d'un montant : le début de son segment, sinon le segment précédent
    (et ceux qui le touchent), sans symbole ni code de devise."""
    segs = li.segments
    k = next((i for i, s in enumerate(segs) if any(m is mot_nombre for m in s.mots)), None)
    if k is None:
        return ""
    s = segs[k]
    avant = [m for m in s.mots[:next(i for i, m in enumerate(s.mots) if m is mot_nombre)]
             if not _est_devise_txt(m.texte)]
    if avant:
        return cle_texte(" ".join(m.texte for m in avant))
    if k == 0:
        return ""
    groupe = [segs[k - 1]]
    for j in range(k - 2, -1, -1):
        if groupe[0].x0 - segs[j].x1 > 0.03:
            break
        groupe.insert(0, segs[j])
    mots = [m for g in groupe for m in g.mots]
    if any(_est_montant_txt(m.texte) for m in mots):
        return ""
    return cle_texte(" ".join(m.texte for m in mots))


def _libelle_ligne(mots: Sequence[Mot], n: Nombre, nb_nombres: int) -> str:
    """Texte de la ligne à gauche du montant ; préfixe étranger retiré (« Optique SARL   Total HT »)."""
    lib_mots = mots[:n.i]
    lib_txt = cle_texte(" ".join(m.texte for m in lib_mots))
    if lib_mots and lib_mots[0].x0 < 0.5 and nb_nombres == 1:
        lib_txt = _PREFIXE_TOTAL.sub("", lib_txt)
    return lib_txt


def _sans_renvois_annexe(lignes: list[LigneLue], tables: list[list[LigneLue]]) -> list[LigneLue]:
    """Une ligne qui renvoie au détail d'une annexe (« Suplidos según anexo », « Disbursements as per
    annex ») n'est pas une ligne de plus quand ce détail est lu : elle est écartée si son montant est égal à
    la somme des lignes d'un autre tableau du document (le détail de l'annexe)."""
    out = []
    for lg in lignes:
        lib = cle_texte(lg.libelle.texte) if lg.libelle is not None else ""
        ht = _montant_lu(lg.montant_ht) if lg.montant_ht is not None else None
        if ht is not None and L.RENVOI_ANNEXE.search(lib):
            autres = [t for t in tables if t and all(x is not lg for x in t)]
            if any(sum((_montant_lu(x.montant_ht) or Decimal(0)) for x in t if x.montant_ht is not None) == abs(ht)
                   for t in autres):
                continue
        out.append(lg)
    return out


def _entete_deux_lignes(p: VuePage, k: int) -> tuple[list[ColonneFt], int] | None:
    """En-tête de tableau lu par l'OCR sur deux lignes très proches dont les mots ne se recouvrent pas :
    colonnes de la ligne fusionnée, et rang de la seconde ligne."""
    if k + 1 >= len(p.lignes):
        return None
    a, b = p.lignes[k], p.lignes[k + 1]
    if abs(b.y0 - a.y0) > min(0.5 * p.pas_ligne, 0.012):
        return None
    if any(min(sa.x1, sb.x1) - max(sa.x0, sb.x0) > 0 for sa in a.segments for sb in b.segments):
        return None
    segs = sorted([*a.segments, *b.segments], key=lambda sg: sg.x0)
    cols = _reconnaitre_entete(VueLigne(page=a.page, rang=a.rang, segments=segs, ligne=a.ligne))
    return (cols, k + 1) if cols is not None else None


def _ligne_parasite(li: VueLigne) -> bool:
    """Ligne faite de fragments courts sans montant (bruit OCR d'un tampon ou d'une tache)."""
    return bool(li.segments) and all(len(sg.texte) <= 5 for sg in li.segments) and \
        not any(_est_montant_txt(m.texte) for m in li.mots) and len(li.texte) <= 16


def _restreindre(li: VueLigne, bornes: tuple[float, float]) -> VueLigne:
    """La ligne réduite aux segments dont le début tombe dans la bande ``bornes`` (tableaux côte à côte)."""
    a, b = bornes
    segs = [s for s in li.segments if a <= s.x0 < b]
    return VueLigne(page=li.page, rang=li.rang, segments=segs, ligne=li.ligne)


def _a_libelle_nature(li: VueLigne) -> bool:
    """La ligne porte un libellé de prestation ou de débours reconnu (ce n'est pas un simple report)."""
    return any(classer_nature(s.texte) is not None for s in li.segments)


def _a_libelle(li: VueLigne, debut_num: float) -> bool:
    return any(s.x1 < debut_num and re.search(r"[A-Za-zÀ-ÿ]{3}", s.texte) for s in li.segments)


def _a_nombres(li: VueLigne, debut_num: float) -> bool:
    return any(s.x0 >= debut_num - 0.02 and re.search(r"\d", s.texte) for s in li.segments)


def _contient_nombre(segs: list[Segment]) -> bool:
    return any(re.search(r"\d", s.texte) for s in segs)


def _jetons(segs: list[Segment]) -> list[tuple[str, list[Mot], str | None]]:
    """Jetons d'une cellule numérique : montant, entier, pourcentage, marqueur (lettre), compte « (2) »,
    code « 1 - 20 % » (marqueur chiffre + taux)."""
    out: list[tuple[str, list[Mot], str | None]] = []
    for s in segs:
        mots = list(s.mots)
        nombres = _nombres(mots)
        pris: set[int] = set()
        for n in nombres:
            ms = mots[n.i:n.j]
            txt = n.texte
            if n.tronque:
                pris.update(range(n.i, n.j))
                continue
            suite = mots[n.j].texte if n.j < len(mots) else ""
            if re.fullmatch(r"\(\d{1,4}\)", txt):
                out.append(("compte", ms, txt.strip("()")))
            elif suite == "%" or txt.endswith("%"):
                if suite == "%":
                    ms = mots[n.i:n.j + 1]
                    pris.add(n.j)
                out.append(("pourcent", ms, txt.rstrip("%").strip()))
            elif _est_montant_txt(txt):
                out.append(("montant", ms, None))
            elif re.fullmatch(r"\d{1,2}", txt) and suite in ("-", "–") and n.j + 1 < len(mots):
                out.append(("code", ms, None))
                pris.add(n.j)
            elif re.fullmatch(r"\d{1,6}", txt):
                out.append(("entier", ms, None))
            elif re.fullmatch(r"\d{1,3}(?:[ \u00a0\u202f\u2009'’]\d{3})+", txt):
                # quantité entière à séparateur de milliers (« 3 988 kg », « 1'250 ») (D-2505)
                out.append(("entier", ms, None))
            elif re.fullmatch(r"\d+[.,]\d+", txt):
                out.append(("nombre", ms, None))
            pris.update(range(n.i, n.j))
        for k, m in enumerate(mots):
            if k in pris:
                continue
            t = m.texte.strip(".,;:")
            mc = re.fullmatch(r"(\d)\s*[-–]\s*(\d{1,2}(?:[.,]\d{1,2})?)\s*%", t)
            if mc:
                # code de statut et taux soudés : « 1-20% »
                out.append(("code_taux", [m], t))
            elif _EXONERE_RE.fullmatch(cle_texte(t)):
                out.append(("exonere", [m], t))
            elif _MARQUEUR_RE.fullmatch(t):
                out.append(("marqueur", [m], t if t != m.texte else None))
            elif _POURCENT_RE.fullmatch(t):
                out.append(("pourcent", [m], _POURCENT_RE.fullmatch(t).group(1)))  # type: ignore[union-attr]
    # ordre de lecture (gauche -> droite)
    out.sort(key=lambda x: x[1][0].x0)
    return out


def _est_num_segment(s: Segment) -> bool:
    return all(re.fullmatch(r"[(\-−–]?[€$£]?\d[\d.,'’\u00a0\u202f\u2009]*\)?-?%?€?|[A-Z]|%|[-–]|\(\d+\)|\d+%|€|EUR",
                            m.texte) for m in s.mots)


#: Montant suivi du symbole euro sans espace (« 60,87€ »).
_NUM_EURO_COLLE = re.compile(r"^[(\-−–]?\d{1,3}(?:[.,'’]?\d{3})*[.,]\d{2}\)?€$")
_NUM_ESPACE_FINE = re.compile(r"^[(\-−–]?\d{1,3}(?:[\u00a0\u202f\u2009]\d{3})+(?:[.,]\d{1,3})?\)?-?$")


def _nombres(mots: Sequence[Mot]):
    """``nombres_dans`` + nombres d'un seul mot à séparateur de milliers « espace fine » (« 6 997,76 »)."""
    out = []
    k = 0
    while k < len(mots):
        if _NUM_ESPACE_FINE.match(mots[k].texte) or _NUM_EURO_COLLE.match(mots[k].texte):
            out.append(Nombre(k, k + 1, mots[k].texte))
            k += 1
            continue
        j = k
        while j < len(mots) and not (_NUM_ESPACE_FINE.match(mots[j].texte) or _NUM_EURO_COLLE.match(mots[j].texte)):
            j += 1
        out.extend(Nombre(n.i + k, n.j + k, n.texte, n.tronque) for n in nombres_dans(mots[k:j]))
        k = j
    return out


def _scinder_par_colonne(segments: Sequence[Segment], cols: list[ColonneFt]) -> list[Segment]:
    """Un segment numérique qui déborde sur plusieurs colonnes (« 95,00 A 20,00% » : montant, code et taux
    serrés) est découpé mot par mot selon la colonne qui contient chaque mot."""
    out: list[Segment] = []
    for s in segments:
        if len(s.mots) < 2 or not _est_num_segment(s):
            out.append(s)
            continue

        def colonne(m: Mot) -> int | None:
            cx = (m.x0 + m.x1) / 2
            dedans = [i for i, c in enumerate(cols) if c.x0 - 0.012 <= cx <= c.x1 + 0.012]
            return dedans[0] if len(dedans) == 1 else None

        idx = [colonne(m) for m in s.mots]
        if None in idx or len(set(idx)) < 2 or idx != sorted(idx):
            out.append(s)
            continue
        groupes: list[list[Mot]] = []
        prec = None
        for m, i in zip(s.mots, idx, strict=True):
            if i != prec:
                groupes.append([])
                prec = i
            groupes[-1].append(m)
        out.extend(Segment(tuple(g), s.page, s.ligne, s.rang) for g in groupes)
    return out


def _attribuer(li: VueLigne, cols: list[ColonneFt]) -> dict[str, list[Segment]]:
    """Attribue chaque segment d'une ligne à une colonne : texte -> colonne dont le bord gauche le précède
    (alignement à gauche) ; nombres / lettres -> colonne de plus grand recouvrement, sinon la plus proche."""
    out: dict[str, list[Segment]] = {}
    for s in _scinder_par_colonne(li.segments, cols):
        if _est_num_segment(s):
            meilleur, score = None, None
            for c in cols:
                rec = min(s.x1, c.x1) - max(s.x0, c.x0)
                cle = (1, rec) if rec > 0 else (0, -max(c.x0 - s.x1, s.x0 - c.x1))
                if score is None or cle > score:
                    meilleur, score = c, cle
        else:
            avant = [c for c in cols if c.x0 <= s.x0 + 0.015]
            meilleur = avant[-1] if avant else cols[0]
            if meilleur.numerique and avant:
                # texte sous une colonne numérique (rare) : la dernière colonne texte qui le précède
                txt = [c for c in avant if not c.numerique]
                if txt and s.x1 < meilleur.x0:
                    meilleur = txt[-1]
        out.setdefault(meilleur.role, []).append(s)
    return out


def _accepte_date(mots: Sequence[Mot]) -> tuple[int, int] | None:
    txt = " ".join(m.texte for m in mots)
    m = _DATE_RE.search(txt)
    if not m or parse_date(m.group(0)) is None:
        return None
    ms = _mots_de_sous_chaine(mots, m.start(), m.end())
    if not ms:
        return None
    i = next(k for k, x in enumerate(mots) if x is ms[0])
    return i, i + len(ms)


def _accepte_ref_transport(mots: Sequence[Mot]) -> tuple[int, int] | None:
    """Référence de transport : mots consécutifs alphanumériques (espaces, barres, tirets admis)."""
    j = 0
    while j < len(mots) and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9/\-.]*|/|-", mots[j].texte):
        j += 1
    while j > 0 and mots[j - 1].texte in ("/", "-"):
        j -= 1
    if j == 0:
        return None
    txt = "".join(m.texte for m in mots[:j])
    if len(re.sub(r"\D", "", txt)) < 5 or _MRN_RE.fullmatch(norm_ref(txt)):
        return None
    return 0, j


def _prefixe_numero(mots: Sequence[Mot]) -> list[Mot] | None:
    """Numéro imprimé en deux mots, préfixe alphabétique court puis partie chiffrée (« RG 2026-46020 »,
    « MDF 84826 ») ; ``None`` sinon."""
    if len(mots) < 2:
        return None
    a, b = mots[0].texte.strip(":;,"), mots[1].texte.strip(":;,")
    if re.fullmatch(r"[A-Z]{2,4}", a) and re.fullmatch(r"\d[\dA-Za-z./\-_]{2,}", b) and \
            mots[1].x0 - mots[0].x1 < 0.02 and not _DATE_RE.fullmatch(b) and not _est_montant_txt(b):
        return list(mots[:2])
    return None


def _groupes_virgule(mots: Sequence[Mot]) -> list[list[Mot]]:
    """Mots découpés en groupes aux virgules et points-virgules (« 999-31884510, 999-31884510 »)."""
    groupes: list[list[Mot]] = [[]]
    for m in mots:
        if m.texte in (",", ";", "et", "and", "&", "und", "e", "y", "en"):
            groupes.append([])
            continue
        t = m.texte.rstrip(",;")
        if t != m.texte:
            groupes[-1].append(Mot(t, m.x0, m.y0, m.x1, m.y1, m.confiance, m.taille) if t else m)
            groupes.append([])
        else:
            groupes[-1].append(m)
    return [g for g in groupes if g]


def _accepte_motif(mots: Sequence[Mot]) -> tuple[int, int] | None:
    return (0, len(mots)) if mots and re.search(r"[A-Za-z]{3}", " ".join(m.texte for m in mots)) else None


