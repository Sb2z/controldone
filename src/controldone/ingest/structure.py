"""Extracteurs ``structure`` (SPEC §5.1, §5.3.6, §6.3, D-006) : aucune IA, aucune heuristique de mise en page.

- Factures électroniques : Factur-X (XML CII embarqué dans le PDF, lu par ``facturx``), CII D16B et
  UBL 2.1 ``Invoice`` / ``CreditNote`` -> ``ChampsFactureCommerciale``, ``ChampsFactureTransitaire`` ou
  ``ChampsAvoir`` selon le contenu (type de document, libellés des lignes).
- Exports de déclaration XML / CSV : fiches de correspondance versionnées ``config/mappings/<id>.yaml``
  (§5.3.6) ; l'ajout d'un format ne demande pas de code ; une colonne inconnue est ignorée et journalisée.

Chaque ``ValeurSourcee`` porte ``document_id``, ``page`` (1 : le XML est rattaché à la première page du
fichier), ``valeur_brute`` (texte du nœud ou de la cellule), ``chemin`` (chemin du modèle) et, dans
``texte_contexte``, le chemin XPath ou la colonne lue. Méthode ``xml_structure`` / ``csv_structure``,
confiance 1,0 si le document est valide au schéma (XSD pour CII/UBL, colonnes requises pour un CSV),
0,95 sinon (avertissement ``schema_non_valide``).

Le contenu des champs libres (notes, motifs, descriptions) est stocké comme **donnée**, jamais interprété.
"""

from __future__ import annotations

import csv
import hashlib
import logging
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from lxml import etree

from controldone.extract.base import ExtractionContext, ExtractionResult
from controldone.extract.valeurs import valeur_sourcee
from controldone.model import Document, Page
from controldone.model.champs import (
    ChampsAvoir,
    ChampsDeclaration,
    ChampsFactureCommerciale,
    ChampsFactureTransitaire,
    IndiceAutoliquidation,
    chemin_complet,
    type_valeur_pour,
)
from controldone.model.enums import (
    CategorieTaxe,
    Methode,
    NatureLigne,
    PaiementNormalise,
    TauxNature,
    TypeDocument,
    TypeExtracteur,
    TypeIndiceAutoliquidation,
    TypeValeur,
)
from controldone.model.valeur import ExtracteurInfo, ValeurSourcee, deriver_somme
from controldone.normalize import normalize_unit
from controldone.normalize.natures import nature_libelle

from .sniff import MIME_CSV, MIME_PDF, MIME_XML, decoder_texte, detecter_type

__all__ = [
    "VERSION_STRUCTURE",
    "ExtracteurDeclarationExport",
    "ExtracteurFactureXML",
    "FicheCorrespondance",
    "InfoStructure",
    "analyser_contenu_structure",
    "categorie_taxe",
    "charger_fiches",
    "extracteurs",
    "nature_ligne",
    "paiement_normalise",
    "xml_facturx",
]

log = logging.getLogger(__name__)

VERSION_STRUCTURE = "1.0.0"
CONFIANCE_VALIDE = 1.0
CONFIANCE_NON_VALIDE = 0.95

NS_CII = {
    "rsm": "urn:un:unece:uncefact:data:standard:CrossIndustryInvoice:100",
    "ram": "urn:un:unece:uncefact:data:standard:ReusableAggregateBusinessInformationEntity:100",
    "udt": "urn:un:unece:uncefact:data:standard:UnqualifiedDataType:100",
    "qdt": "urn:un:unece:uncefact:data:standard:QualifiedDataType:100",
}
NS_UBL_INV = "urn:oasis:names:specification:ubl:schema:xsd:Invoice-2"
NS_UBL_CN = "urn:oasis:names:specification:ubl:schema:xsd:CreditNote-2"
NS_UBL = {
    "cac": "urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2",
    "cbc": "urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2",
}
_MRN_RE = re.compile(r"\b(\d{2}[A-Z]{2}[A-Z0-9]{14})\b")
#: Codes de type de document (UNTDID 1001) : avoirs.
CODES_AVOIR = {"381", "261", "262", "396", "532"}


def _parser() -> etree.XMLParser:
    return etree.XMLParser(resolve_entities=False, no_network=True, load_dtd=False, huge_tree=False,
                           remove_comments=True, remove_pis=True)


def _xml(contenu: bytes) -> etree._Element | None:
    try:
        return etree.fromstring(contenu, _parser())
    except (etree.XMLSyntaxError, ValueError):
        return None


def _local(tag: Any) -> str:
    return etree.QName(tag).localname if isinstance(tag, str) else ""


# --- Factur-X -------------------------------------------------------------------------------------------


def xml_facturx(pdf: bytes) -> bytes | None:
    """XML CII (ou autre XML de facture) embarqué dans un PDF Factur-X / ZUGFeRD ; ``None`` sinon."""
    if b"/EmbeddedFile" not in pdf and b"/AF" not in pdf and b"EmbeddedFiles" not in pdf:
        return None
    try:
        from facturx import get_facturx_xml_from_pdf

        logging.getLogger("factur-x").setLevel(logging.CRITICAL)
        _nom, xml = get_facturx_xml_from_pdf(pdf, check_xsd=False)
    except Exception:
        return None
    return xml or None


def _schema_valide(racine: etree._Element, flavor: str) -> bool:
    try:
        from facturx import xml_check_xsd

        logging.getLogger("factur-x").setLevel(logging.CRITICAL)
        return bool(xml_check_xsd(racine, flavor=flavor))
    except Exception:
        return False


# --- natures de lignes, catégories de taxes, paiement ----------------------------------------------------

def _norm(t: str) -> str:
    from controldone.normalize.text import sans_accents

    return re.sub(r"\s+", " ", sans_accents(t).lower().replace("’", "'")).strip()


def nature_ligne(libelle: str | None) -> NatureLigne:
    """Nature d'une ligne de facture transitaire d'après son libellé (§5.3.3) ; ``autre_prestation`` sinon
    (table unique ``normalize.natures``, D-1213)."""
    return nature_libelle(libelle) or NatureLigne.autre_prestation


def categorie_taxe(code: str | None, table: dict[str, str] | None = None) -> CategorieTaxe:
    """Catégorie d'une ligne de taxation (§5.3.2). ``table`` (fiche de correspondance) l'emporte.

    Par défaut : ``A00``–``A29`` droits de douane, ``A30``–``A99`` (antidumping, compensateurs…) autres
    taxes, ``B..`` TVA ; autres codes alphanumériques -> autres taxes ; vide -> inconnue.
    """
    if not code:
        return CategorieTaxe.inconnue
    c = re.sub(r"\s", "", code).upper()
    if table:
        for k, v in table.items():
            if re.sub(r"\s", "", str(k)).upper() == c:
                try:
                    return CategorieTaxe(v)
                except ValueError:
                    return CategorieTaxe.inconnue
    m = re.fullmatch(r"([A-Z])(\d{2})", c)
    if m:
        lettre, n = m.group(1), int(m.group(2))
        if lettre == "A":
            return CategorieTaxe.droit if n < 30 else CategorieTaxe.autre_taxe
        if lettre == "B":
            return CategorieTaxe.tva
        return CategorieTaxe.autre_taxe
    t = _norm(code)
    if "tva" in t or "vat" in t:
        return CategorieTaxe.tva
    if "forfait" in t or "flat" in t:
        return CategorieTaxe.forfait_petits_envois
    if "droit" in t or "duty" in t:
        return CategorieTaxe.droit
    return CategorieTaxe.autre_taxe if re.fullmatch(r"[A-Z0-9]{1,4}", c) else CategorieTaxe.inconnue


def paiement_normalise(mode: str | None, table: dict[str, str] | None = None) -> PaiementNormalise:
    """Mode de paiement normalisé (§5.3.2) : table de la fiche, sinon libellés usuels."""
    if not mode:
        return PaiementNormalise.inconnu
    brut = mode.strip()
    if table:
        for k, v in table.items():
            if str(k).strip().upper() == brut.upper():
                try:
                    return PaiementNormalise(v)
                except ValueError:
                    return PaiementNormalise.inconnu
    t = _norm(brut)
    if "autoliquid" in t or "reverse" in t:
        return PaiementNormalise.autoliquide
    if "differ" in t or "report" in t or "deferred" in t or "credit d'enlevement" in t:
        return PaiementNormalise.differe
    if "garant" in t or "guarantee" in t:
        return PaiementNormalise.garanti
    if "comptant" in t or "cash" in t or "immediat" in t or "especes" in t or "virement" in t:
        return PaiementNormalise.comptant
    return PaiementNormalise.inconnu


# --- fiches de correspondance des exports de déclaration (§5.3.6) ----------------------------------------


@dataclass
class FicheCorrespondance:
    """Fiche ``config/mappings/<format_id>.yaml`` (voir ``config/mappings/README.md``)."""

    format_id: str
    version: str
    type: str  # "xml" | "csv"
    sous_type: str
    detection: dict[str, Any]
    entete: dict[str, Any]
    listes: dict[str, Any]
    tables: dict[str, dict[str, str]] = field(default_factory=dict)
    constantes: dict[str, str] = field(default_factory=dict)
    espaces_noms: dict[str, str] = field(default_factory=dict)
    csv: dict[str, Any] = field(default_factory=dict)
    devise_par_defaut: str | None = None
    source: str | None = None

    @classmethod
    def depuis_dict(cls, d: dict[str, Any], source: str | None = None) -> FicheCorrespondance:
        manquants = [k for k in ("format_id", "type", "detection") if k not in d]
        if manquants:
            raise ValueError(f"fiche de correspondance incomplète : {manquants}")
        if d["type"] not in ("xml", "csv"):
            raise ValueError("type de fiche : xml ou csv")
        fiche = cls(
            format_id=str(d["format_id"]), version=str(d.get("version", "1.0.0")), type=d["type"],
            sous_type=d.get("sous_type") or ("export_xml" if d["type"] == "xml" else "export_csv"),
            detection=dict(d.get("detection") or {}), entete=dict(d.get("entete") or {}),
            listes=dict(d.get("listes") or {}), tables={k: dict(v or {}) for k, v in (d.get("tables") or {}).items()},
            constantes=dict(d.get("constantes") or {}),
            espaces_noms=dict((d.get("xml") or {}).get("espaces_noms") or {}), csv=dict(d.get("csv") or {}),
            devise_par_defaut=d.get("devise_par_defaut"), source=source,
        )
        fiche._verifier_chemins()
        return fiche

    def _verifier_chemins(self) -> None:
        """Chaque chemin cible doit exister dans le modèle ``ChampsDeclaration`` (erreur de fiche sinon)."""
        valides = {f.chemin for f in ChampsDeclaration.feuilles()}
        for chemin in list(self.entete) + list(self.constantes):
            if chemin not in valides:
                raise ValueError(f"{self.format_id} : champ inconnu du modèle : {chemin}")
        for nom, spec in self.listes.items():
            if "source" not in spec and "type_enregistrement" not in spec:
                raise ValueError(f"{self.format_id} : liste {nom} sans source")
            for chemin in [*(spec.get("champs") or {}), *(spec.get("enumerations") or {})]:
                if f"{nom}[].{chemin}" not in valides:
                    raise ValueError(f"{self.format_id} : champ inconnu du modèle : {nom}[].{chemin}")

    # --- détection ---

    def reconnait(self, contenu: bytes, mime: str) -> bool:
        det = self.detection
        if self.type == "xml":
            if mime != MIME_XML:
                return False
            racine = _xml(contenu)
            if racine is None:
                return False
            if det.get("racine") and _local(racine.tag) != det["racine"]:
                return False
            ns = etree.QName(racine.tag).namespace
            if det.get("espace_noms") and ns != det["espace_noms"]:
                return False
            return not (det.get("marqueur")
                        and not re.search(det["marqueur"], contenu[:4096].decode("utf-8", "ignore")))
        if mime != MIME_CSV:
            return False
        texte = decoder_texte(contenu) or ""
        entete = self._lire_csv(texte)[0]
        requis = det.get("colonnes_requises") or []
        return bool(entete) and all(c in entete for c in requis) and (
            not det.get("marqueur") or bool(re.search(det["marqueur"], texte[:4096])))

    def _lire_csv(self, texte: str) -> tuple[list[str], list[dict[str, str]], list[int]]:
        """(colonnes, enregistrements, numéros de ligne). En mode ``multi_enregistrements`` (une ligne
        ``#TYPE;col…`` déclare les colonnes du type), chaque enregistrement porte ``__type__`` et les
        colonnes sont notées ``TYPE.col``."""
        sep = self.csv.get("separateur") or ";"
        lignes = texte.lstrip("\ufeff").replace("\r\n", "\n").replace("\r", "\n").split("\n")
        rangs = list(csv.reader(lignes, delimiter=sep, quotechar=self.csv.get("guillemet", '"')))
        if not rangs:
            return [], [], []
        out: list[dict[str, str]] = []
        numeros: list[int] = []
        if self.csv.get("multi_enregistrements"):
            colonnes: dict[str, list[str]] = {}
            vues: list[str] = []
            for i, r in enumerate(rangs, start=1):
                if not r or not any(c.strip() for c in r):
                    continue
                tete = r[0].strip()
                if tete.startswith("#"):
                    t = tete[1:].strip()
                    colonnes[t] = [c.strip() for c in r[1:]]
                    vues.extend(f"{t}.{c}" for c in colonnes[t] if f"{t}.{c}" not in vues)
                    continue
                cols = colonnes.get(tete)
                if cols is None:
                    continue
                d = {cols[j]: r[j + 1].strip() for j in range(min(len(cols), len(r) - 1))}
                d["__type__"] = tete
                out.append(d)
                numeros.append(i)
            return vues, out, numeros
        entete = [c.strip() for c in rangs[0]]
        for i, r in enumerate(rangs[1:], start=2):
            if not any(c.strip() for c in r):
                continue
            out.append({entete[j]: r[j].strip() for j in range(min(len(entete), len(r)))})
            numeros.append(i)
        return entete, out, numeros


def _dossier_fiches() -> Path:
    from controldone.config import get_settings

    return Path(get_settings().config_dir) / "mappings"


@lru_cache(maxsize=8)
def _charger_fiches_cache(dossier: str) -> tuple[FicheCorrespondance, ...]:
    fiches = []
    for p in sorted(Path(dossier).glob("*.yaml")):
        try:
            d = yaml.safe_load(p.read_text("utf-8"))
            if isinstance(d, dict) and "format_id" in d:
                fiches.append(FicheCorrespondance.depuis_dict(d, source=p.name))
        except (OSError, yaml.YAMLError, ValueError) as e:
            log.error("fiche_correspondance_invalide fichier=%s erreur=%s", p.name, type(e).__name__)
    return tuple(fiches)


def charger_fiches(dossier: str | Path | None = None) -> tuple[FicheCorrespondance, ...]:
    """Fiches de correspondance de ``config/mappings`` (ou ``dossier``)."""
    return _charger_fiches_cache(str(dossier or _dossier_fiches()))


# --- analyse d'un contenu structuré (sert aussi au classement) -------------------------------------------


@dataclass
class InfoStructure:
    """Résultat de l'analyse d'un fichier structuré."""

    format: str  # "cii", "ubl", "facturx" ou format_id d'une fiche
    type: TypeDocument
    sous_type: str | None
    confiance: float
    xml: bytes | None = None
    fiche: FicheCorrespondance | None = None
    schema_valide: bool = True


def _cii_libelles(racine: etree._Element) -> tuple[list[str], int]:
    libs = [_txt(x) for x in racine.xpath(
        ".//ram:IncludedSupplyChainTradeLineItem/ram:SpecifiedTradeProduct/ram:Name", namespaces=NS_CII)]
    codes = len(racine.xpath(".//ram:SpecifiedTradeProduct/ram:DesignatedProductClassification/ram:ClassCode | "
                             ".//ram:SpecifiedTradeProduct/ram:OriginTradeCountry/ram:ID", namespaces=NS_CII))
    return [x for x in libs if x], codes


def _ubl_libelles(racine: etree._Element) -> tuple[list[str], int]:
    libs = [_txt(x) for x in racine.xpath(".//cac:InvoiceLine/cac:Item/cbc:Name | .//cac:CreditNoteLine/cac:Item/cbc:Name",
                                          namespaces=NS_UBL)]
    codes = len(racine.xpath(".//cac:Item/cac:CommodityClassification/cbc:ItemClassificationCode | "
                             ".//cac:Item/cac:OriginCountry/cbc:IdentificationCode", namespaces=NS_UBL))
    return [x for x in libs if x], codes


def est_facture_transitaire(libelles: Sequence[str], nb_codes_marchandise: int) -> bool:
    """Facture de transitaire si les lignes décrivent des débours ou des prestations de dédouanement
    (et non des marchandises avec code SH / origine). Un nom de transporteur ne compte pas (§5.3.3)."""
    if not libelles:
        return False
    natures = [nature_ligne(x) for x in libelles]
    debours = sum(1 for n in natures if n.est_debours)
    douane = sum(1 for n in natures if n in (NatureLigne.frais_dedouanement, NatureLigne.frais_avance_fonds,
                                              NatureLigne.frais_ligne_supplementaire, NatureLigne.magasinage))
    if nb_codes_marchandise >= max(1, len(libelles) // 2):
        return False
    return debours >= 1 or douane >= 1


def analyser_contenu_structure(contenu: bytes, mime: str | None = None,
                               fiches: Iterable[FicheCorrespondance] | None = None) -> InfoStructure | None:
    """Reconnaît un fichier structuré : Factur-X, CII, UBL, export de déclaration (fiche). ``None`` sinon."""
    mime = mime or detecter_type(contenu)
    fiches = tuple(fiches) if fiches is not None else charger_fiches()
    fmt = None
    xml = contenu
    if mime == MIME_PDF:
        xml = xml_facturx(contenu)
        if xml is None:
            return None
        fmt = "facturx"
    elif mime == MIME_CSV:
        for f in fiches:
            if f.type == "csv" and f.reconnait(contenu, mime):
                return InfoStructure(format=f.format_id, type=TypeDocument.declaration, sous_type=f.sous_type,
                                     confiance=0.99, fiche=f)
        return None
    elif mime != MIME_XML:
        return None
    racine = _xml(xml)
    if racine is None:
        return None
    nom = _local(racine.tag)
    ns = etree.QName(racine.tag).namespace
    if nom == "CrossIndustryInvoice":
        code = _txt_first(racine, "rsm:ExchangedDocument/ram:TypeCode", NS_CII)
        libs, codes = _cii_libelles(racine)
        valide = _schema_valide(racine, "factur-x")
        fmt = fmt or "cii"
    elif nom in ("Invoice", "CreditNote") and ns in (NS_UBL_INV, NS_UBL_CN):
        code = "381" if nom == "CreditNote" else (_txt_first(racine, "cbc:InvoiceTypeCode", NS_UBL) or "380")
        libs, codes = _ubl_libelles(racine)
        valide = _schema_valide(racine, "ubl-2.1-creditnote" if nom == "CreditNote" else "ubl-2.1-invoice")
        fmt = fmt or "ubl"
    else:
        for f in fiches:
            if f.type == "xml" and f.reconnait(xml, MIME_XML):
                return InfoStructure(format=f.format_id, type=TypeDocument.declaration, sous_type=f.sous_type,
                                     confiance=0.99, xml=xml, fiche=f)
        return None
    if code in CODES_AVOIR:
        t, st = TypeDocument.avoir, None
    elif est_facture_transitaire(libs, codes):
        t, st = TypeDocument.facture_transitaire, None
    else:
        t, st = TypeDocument.facture_commerciale, ("pro_forma" if code == "325" else "facture")
    return InfoStructure(format=fmt, type=t, sous_type=st, confiance=0.98 if valide else 0.9, xml=xml,
                         schema_valide=valide)


# --- outils XPath -------------------------------------------------------------------------------------------


def _txt(el: Any) -> str:
    if el is None:
        return ""
    if isinstance(el, str):
        return el.strip()
    return "".join(el.itertext()).strip()


def _txt_first(base: etree._Element, xp: str, ns: dict[str, str]) -> str | None:
    r = base.xpath(xp, namespaces=ns)
    if not r:
        return None
    v = _txt(r[0])
    return v or None


def _chemin_xpath(el: etree._Element) -> str:
    """Chemin lisible d'un nœud (``/Invoice/InvoiceLine[2]/ID``, noms locaux, rang si répété) pour
    ``texte_contexte``."""
    try:
        parties = []
        courant = el
        while courant is not None and isinstance(courant.tag, str):
            nom = _local(courant.tag)
            parent = courant.getparent()
            if parent is not None:
                freres = [x for x in parent if isinstance(x.tag, str) and x.tag == courant.tag]
                if len(freres) > 1:
                    nom = f"{nom}[{freres.index(courant) + 1}]"
            parties.append(nom)
            courant = parent
        return "/" + "/".join(reversed(parties))
    except (ValueError, AttributeError):
        return ""


# --- construction des valeurs -------------------------------------------------------------------------------


class _Constructeur:
    def __init__(self, document: Document, type_doc: TypeDocument, extracteur: ExtracteurInfo, methode: Methode,
                 confiance: float, ctx: ExtractionContext, separateur_decimal: str = ".",
                 format_date: str | None = None):
        self.document = document
        self.type_doc = type_doc
        self.extracteur = extracteur
        self.methode = methode
        self.confiance = confiance
        self.ctx = ctx
        self.sep = separateur_decimal
        self.format_date = format_date
        self.page = document.pages[0].numero if document.pages else 1

    def vs(self, chemin: str, brut: str | None, contexte: str | None, *, devise: str | None = None,
           page: int | None = None, sep: str | None = None) -> ValeurSourcee | None:
        if brut is None or not str(brut).strip():
            return None
        brut = str(brut).strip()
        tv = type_valeur_pour(chemin)
        v = valeur_sourcee(
            type_document=self.type_doc, chemin=chemin, brut=brut, document_id=self.document.id,
            page=page or self.page, extracteur=self.extracteur, methode=self.methode, confiance=self.confiance,
            texte_contexte=contexte, separateur_decimal=sep or self.sep, devise=devise,
            id_valeur=self.ctx.ids.nouveau("vs") if self.ctx.ids is not None else None,
        )
        if tv is TypeValeur.date and v.valeur is None:
            iso = _date_structuree(brut, self.format_date)
            if iso:
                v = v.model_copy(update={"valeur": iso, "confiance": self.confiance})
        return v


def _date_structuree(brut: str, fmt: str | None) -> str | None:
    b = brut.strip()
    if fmt:
        try:
            return datetime.strptime(b, fmt).date().isoformat()
        except ValueError:
            pass
    if re.fullmatch(r"\d{8}", b):  # format 102 (AAAAMMJJ)
        try:
            return datetime.strptime(b, "%Y%m%d").date().isoformat()
        except ValueError:
            return None
    m = re.match(r"(\d{4}-\d{2}-\d{2})", b)
    return m.group(1) if m else None


def _definir(champs, chemin: str, v: ValeurSourcee | None) -> None:
    if v is None:
        return
    if chemin.endswith("[]"):
        liste = champs.obtenir(chemin[:-2])
        idx = len(liste) if isinstance(liste, list) else 0
        tete, _, _ = v.chemin.rpartition("[]")
        v = v.model_copy(update={"chemin": f"{tete}[{idx}]"})
    champs.definir(chemin, v)


def _extracteur_info(id_: str) -> ExtracteurInfo:
    return ExtracteurInfo(type=TypeExtracteur.structure, id=id_, version=VERSION_STRUCTURE)


# --- notes (texte libre stocké comme donnée ; seuls des motifs fermés en sont lus) -------------------------

_RX_MASSE_BRUTE = re.compile(r"gross weight\s*:?\s*([\d.,]+\s*kg)|poids brut\s*:?\s*([\d.,\s]+\s*kg)", re.I)
_RX_MASSE_NETTE = re.compile(r"net weight\s*:?\s*([\d.,]+\s*kg)|poids net\s*:?\s*([\d.,\s]+\s*kg)", re.I)
_RX_COLIS = re.compile(r"(?:packages|colis|bultos)\s*:?\s*(\d+)", re.I)
_RX_POURCENT = re.compile(r"(\d+(?:[.,]\d+)?)\s?%")
_RX_PERIODE = re.compile(r"(\d{2}/\d{2}/\d{4})\s*(?:-|au|to)\s*(\d{2}/\d{2}/\d{4})")
_RX_MOTIF = re.compile(r"^\s*(?:motif|reason|motivo)\s*:\s*(.+)$", re.I)
_TRANSPORT_NOMS = re.compile(r"\b(?:b/?l|lta|awb|bill of lading|air ?way ?bill|connaissement|cmr|hawb|mawb)\b", re.I)


def _premier(rx: re.Pattern[str], texte: str) -> str | None:
    m = rx.search(texte)
    if not m:
        return None
    return next((g for g in m.groups() if g), None)


def _sous_total_type(raison: str | None, charge: bool):
    from controldone.model.enums import TypeSousTotal

    t = _norm(raison or "")
    if not charge or re.search(r"discount|remise|descuento|rabais|allowance", t):
        return TypeSousTotal.remise
    if re.search(r"freight|fret|flete|transport|shipping", t):
        return TypeSousTotal.fret
    if re.search(r"insurance|assurance|seguro", t):
        return TypeSousTotal.assurance
    if re.search(r"packing|emballage|embalaje|packaging", t):
        return TypeSousTotal.emballage
    return TypeSousTotal.autre


def _champs_notes_fc(c, champs: ChampsFactureCommerciale, notes: list[tuple[str, str]]) -> None:
    for texte, cx in notes:
        for chemin, rx in (("masse_brute_totale", _RX_MASSE_BRUTE), ("masse_nette_totale", _RX_MASSE_NETTE),
                           ("nombre_colis", _RX_COLIS)):
            if champs.obtenir(chemin) is None:
                _definir(champs, chemin, c.vs(chemin, _premier(rx, texte), cx))


def _champs_notes_ligne_fc(c, champs, p: str, notes: list[tuple[str, str]]) -> None:
    for texte, cx in notes:
        _definir(champs, f"{p}.masse_brute", c.vs(f"{p}.masse_brute", _premier(_RX_MASSE_BRUTE, texte), cx))
        _definir(champs, f"{p}.masse_nette", c.vs(f"{p}.masse_nette", _premier(_RX_MASSE_NETTE, texte), cx))


def _notes(lec, base, xp: str) -> list[tuple[str, str]]:
    return [(_txt(e), _chemin_xpath(e)) for e in lec.tous(base, xp) if _txt(e)]


# --- CII ----------------------------------------------------------------------------------------------------

_CII_HDR = "rsm:SupplyChainTradeTransaction/ram:ApplicableHeaderTradeAgreement"
_CII_DEL = "rsm:SupplyChainTradeTransaction/ram:ApplicableHeaderTradeDelivery"
_CII_SET = "rsm:SupplyChainTradeTransaction/ram:ApplicableHeaderTradeSettlement"
_CII_SUM = f"{_CII_SET}/ram:SpecifiedTradeSettlementHeaderMonetarySummation"


class _Lecteur:
    """Lecture XPath avec chemin de contexte et attribut ``currencyID`` / ``unitCode``."""

    def __init__(self, racine: etree._Element, ns: dict[str, str]):
        self.racine = racine
        self.ns = ns

    def un(self, base: etree._Element | None, xp: str) -> tuple[str | None, str | None, etree._Element | None]:
        base = self.racine if base is None else base
        r = base.xpath(xp, namespaces=self.ns)
        if not r:
            return None, None, None
        el = r[0]
        if isinstance(el, str):
            parent = getattr(el, "getparent", lambda: None)()
            nom_attr = getattr(el, "attrname", None)
            ctx_ = f"{_chemin_xpath(parent)}/@{_local(nom_attr) if nom_attr else ''}" if parent is not None else xp
            return el.strip() or None, ctx_, None
        v = _txt(el)
        return (v or None), _chemin_xpath(el), el

    def tous(self, base: etree._Element | None, xp: str) -> list[etree._Element]:
        base = self.racine if base is None else base
        return [e for e in base.xpath(xp, namespaces=self.ns) if not isinstance(e, str)]


def _partie(c: _Constructeur, lec: _Lecteur, champs, prefixe: str, base_xp: str, *, ubl: bool) -> None:
    if ubl:
        noms = ("cac:Party/cac:PartyLegalEntity/cbc:RegistrationName", "cac:Party/cac:PartyName/cbc:Name")
        tva_xp = "cac:Party/cac:PartyTaxScheme/cbc:CompanyID"
        adr = "cac:Party/cac:PostalAddress"
        siren_xp = "cac:Party/cac:PartyLegalEntity/cbc:CompanyID"
    else:
        noms = ("ram:Name",)
        tva_xp = "ram:SpecifiedTaxRegistration/ram:ID[@schemeID='VA']"
        adr = "ram:PostalTradeAddress"
        siren_xp = "ram:SpecifiedLegalOrganization/ram:ID"
    bases = lec.tous(None, base_xp)
    if not bases:
        return
    b = bases[0]
    for xp in noms:
        v, ctx_, _ = lec.un(b, xp)
        if v:
            _definir(champs, f"{prefixe}.nom", c.vs(f"{prefixe}.nom", v, ctx_))
            break
    v, ctx_, _ = lec.un(b, tva_xp)
    _definir(champs, f"{prefixe}.tva", c.vs(f"{prefixe}.tva", v, ctx_))
    v, ctx_, _ = lec.un(b, siren_xp)
    if v and re.fullmatch(r"\d{9}|\d{14}", re.sub(r"\s", "", v)):
        _definir(champs, f"{prefixe}.siren", c.vs(f"{prefixe}.siren", v, ctx_))
    adresses = lec.tous(b, adr)
    if adresses:
        parties = [_txt(x) for x in adresses[0] if _txt(x)]
        if parties:
            _definir(champs, f"{prefixe}.adresse",
                     c.vs(f"{prefixe}.adresse", ", ".join(parties), _chemin_xpath(adresses[0])))


def _total_imprime(v: ValeurSourcee | None) -> ValeurSourcee | None:
    from controldone.model.enums import TotalOrigine

    return v.model_copy(update={"total_origine": TotalOrigine.imprime}) if v is not None else None


def _quantite(c: _Constructeur, chemin: str, lu: tuple) -> ValeurSourcee | None:
    q, cx, el = lu
    v = c.vs(chemin, q, cx)
    if v is not None and el is not None and el.get("unitCode"):
        v = v.model_copy(update={"unite": el.get("unitCode"), "unite_brute": el.get("unitCode")})
    return v


def _remplir_fc(c: _Constructeur, champs: ChampsFactureCommerciale, d: dict[str, Any]) -> None:
    """``d`` : valeurs lues (``(brut, contexte, élément)``) communes à CII et UBL."""
    devise = d["devise"]
    _definir(champs, "numero", c.vs("numero", *d["numero"][:2]))
    _definir(champs, "date", c.vs("date", *d["date"][:2]))
    _definir(champs, "devise", c.vs("devise", *d["devise_lu"][:2]))
    _definir(champs, "total_facture", _total_imprime(c.vs("total_facture", *d["total"][:2], devise=devise)))
    _definir(champs, "incoterm", c.vs("incoterm", *d["incoterm"][:2]))
    _definir(champs, "incoterm_lieu", c.vs("incoterm_lieu", *d["incoterm_lieu"][:2]))
    for brut, cx, nom in d["refs_doc"]:
        if brut and champs.ref_transport is None and (not nom or _TRANSPORT_NOMS.search(nom)):
            _definir(champs, "ref_transport", c.vs("ref_transport", brut, cx))
    for k, (raison, montant, charge, cx_r, cx_m) in enumerate(d["frais"]):
        champs.definir(f"sous_totaux[{k}].type", _sous_total_type(raison[0] if raison else None, charge))
        if raison and raison[0]:
            _definir(champs, f"sous_totaux[{k}].libelle", c.vs(f"sous_totaux[{k}].libelle", raison[0], cx_r))
        _definir(champs, f"sous_totaux[{k}].montant", c.vs(f"sous_totaux[{k}].montant", montant, cx_m, devise=devise))
    _champs_notes_fc(c, champs, d["notes"])
    for i, lg in enumerate(d["lignes"]):
        p = f"lignes[{i}]"
        for rel in ("numero_ligne", "reference_article", "description", "code_marchandise_imprime", "pays_origine"):
            _definir(champs, f"{p}.{rel}", c.vs(f"{p}.{rel}", *lg[rel][:2]))
        _definir(champs, f"{p}.quantite", _quantite(c, f"{p}.quantite", lg["quantite"]))
        _definir(champs, f"{p}.prix_unitaire", c.vs(f"{p}.prix_unitaire", *lg["prix_unitaire"][:2], devise=devise))
        _definir(champs, f"{p}.montant_ligne", c.vs(f"{p}.montant_ligne", *lg["montant"][:2], devise=devise))
        _champs_notes_ligne_fc(c, champs, p, lg["notes"])


def _lire_cii(lec: _Lecteur) -> dict[str, Any]:
    hdr, dl, st, sm = _CII_HDR, _CII_DEL, _CII_SET, _CII_SUM
    total = lec.un(None, f"{sm}/ram:GrandTotalAmount")
    if total[0] is None:
        total = lec.un(None, f"{sm}/ram:DuePayableAmount")
    devise_lu = lec.un(None, f"{st}/ram:InvoiceCurrencyCode")
    d: dict[str, Any] = {
        "numero": lec.un(None, "rsm:ExchangedDocument/ram:ID"),
        "date": lec.un(None, "rsm:ExchangedDocument/ram:IssueDateTime/udt:DateTimeString"),
        "devise_lu": devise_lu, "devise": (devise_lu[0] or "").upper() or None, "total": total,
        "incoterm": lec.un(None, f"{hdr}/ram:ApplicableTradeDeliveryTerms/ram:DeliveryTypeCode"),
        "incoterm_lieu": lec.un(None, f"{hdr}/ram:ApplicableTradeDeliveryTerms/ram:RelevantTradeLocation/ram:Name"),
        "notes": _notes(lec, None, "rsm:ExchangedDocument/ram:IncludedNote/ram:Content"),
        "refs_doc": [], "frais": [], "lignes": [],
        "refs_origine": [lec.un(x, ".") for x in lec.tous(None, f"{st}/ram:InvoiceReferencedDocument/ram:IssuerAssignedID")],
        "totaux": {
            "ht": lec.un(None, f"{sm}/ram:TaxBasisTotalAmount"), "tva": lec.un(None, f"{sm}/ram:TaxTotalAmount"),
            "ttc": lec.un(None, f"{sm}/ram:GrandTotalAmount"), "net": lec.un(None, f"{sm}/ram:DuePayableAmount"),
            "acomptes": lec.un(None, f"{sm}/ram:TotalPrepaidAmount"),
        },
        "vendeur": f"{hdr}/ram:SellerTradeParty", "acheteur": f"{hdr}/ram:BuyerTradeParty",
        "destinataire": f"{dl}/ram:ShipToTradeParty",
    }
    for el in lec.tous(None, f"{hdr}/ram:AdditionalReferencedDocument"):
        brut, cx, _ = lec.un(el, "ram:IssuerAssignedID")
        d["refs_doc"].append((brut, cx, lec.un(el, "ram:Name")[0]))
    for el in lec.tous(None, f"{st}/ram:SpecifiedTradeAllowanceCharge"):
        charge = (lec.un(el, "ram:ChargeIndicator/udt:Indicator")[0] or "").strip().lower() == "true"
        raison = lec.un(el, "ram:Reason")
        montant, cx_m, _ = lec.un(el, "ram:ActualAmount")
        d["frais"].append((raison, montant, charge, raison[1], cx_m))
    for el in lec.tous(None, "rsm:SupplyChainTradeTransaction/ram:IncludedSupplyChainTradeLineItem"):
        d["lignes"].append({
            "numero_ligne": lec.un(el, "ram:AssociatedDocumentLineDocument/ram:LineID"),
            "reference_article": lec.un(el, "ram:SpecifiedTradeProduct/ram:SellerAssignedID"),
            "description": lec.un(el, "ram:SpecifiedTradeProduct/ram:Name"),
            "libelle": lec.un(el, "ram:SpecifiedTradeProduct/ram:Name"),
            "code_marchandise_imprime": lec.un(el, "ram:SpecifiedTradeProduct/ram:DesignatedProductClassification/ram:ClassCode"),
            "code_marchandise": lec.un(el, "ram:SpecifiedTradeProduct/ram:DesignatedProductClassification/ram:ClassCode"),
            "pays_origine": lec.un(el, "ram:SpecifiedTradeProduct/ram:OriginTradeCountry/ram:ID"),
            "quantite": lec.un(el, "ram:SpecifiedLineTradeDelivery/ram:BilledQuantity"),
            "prix_unitaire": lec.un(el, "ram:SpecifiedLineTradeAgreement/ram:NetPriceProductTradePrice/ram:ChargeAmount"),
            "montant": lec.un(el, "ram:SpecifiedLineTradeSettlement/ram:SpecifiedTradeSettlementLineMonetarySummation/"
                                  "ram:LineTotalAmount"),
            "taux_tva": lec.un(el, "ram:SpecifiedLineTradeSettlement/ram:ApplicableTradeTax/ram:RateApplicablePercent"),
            "marqueur_tva": lec.un(el, "ram:SpecifiedLineTradeSettlement/ram:ApplicableTradeTax/ram:CategoryCode"),
            "notes": _notes(lec, el, "ram:AssociatedDocumentLineDocument/ram:IncludedNote/ram:Content"),
        })
    return d


def _lire_ubl(lec: _Lecteur, credit: bool) -> dict[str, Any]:
    ligne_xp = "cac:CreditNoteLine" if credit else "cac:InvoiceLine"
    qte_xp = "cbc:CreditedQuantity" if credit else "cbc:InvoicedQuantity"
    total = lec.un(None, "cac:LegalMonetaryTotal/cbc:TaxInclusiveAmount")
    if total[0] is None:
        total = lec.un(None, "cac:LegalMonetaryTotal/cbc:PayableAmount")
    devise_lu = lec.un(None, "cbc:DocumentCurrencyCode")
    d: dict[str, Any] = {
        "numero": lec.un(None, "cbc:ID"), "date": lec.un(None, "cbc:IssueDate"),
        "devise_lu": devise_lu, "devise": (devise_lu[0] or "").upper() or None, "total": total,
        "incoterm": lec.un(None, "cac:DeliveryTerms/cbc:ID | cac:Delivery/cac:DeliveryTerms/cbc:ID"),
        "incoterm_lieu": lec.un(None, "cac:DeliveryTerms/cac:DeliveryLocation/cbc:ID | "
                                      "cac:DeliveryTerms/cac:DeliveryLocation/cac:Address/cbc:CityName"),
        "notes": _notes(lec, None, "cbc:Note"),
        "refs_doc": [], "frais": [], "lignes": [],
        "refs_origine": [lec.un(x, ".") for x in lec.tous(None, "cac:BillingReference/cac:InvoiceDocumentReference/cbc:ID")],
        "totaux": {
            "ht": lec.un(None, "cac:LegalMonetaryTotal/cbc:TaxExclusiveAmount"),
            "tva": lec.un(None, "cac:TaxTotal/cbc:TaxAmount"),
            "ttc": lec.un(None, "cac:LegalMonetaryTotal/cbc:TaxInclusiveAmount"),
            "net": lec.un(None, "cac:LegalMonetaryTotal/cbc:PayableAmount"),
            "acomptes": lec.un(None, "cac:LegalMonetaryTotal/cbc:PrepaidAmount"),
        },
        "vendeur": "cac:AccountingSupplierParty", "acheteur": "cac:AccountingCustomerParty",
        "destinataire": None,
    }
    for el in lec.tous(None, "cac:AdditionalDocumentReference"):
        brut, cx, _ = lec.un(el, "cbc:ID")
        nom = lec.un(el, "cbc:DocumentDescription")[0] or lec.un(el, "cbc:DocumentType")[0]
        d["refs_doc"].append((brut, cx, nom))
    for el in lec.tous(None, "cac:AllowanceCharge"):
        charge = (lec.un(el, "cbc:ChargeIndicator")[0] or "").strip().lower() == "true"
        raison = lec.un(el, "cbc:AllowanceChargeReason")
        montant, cx_m, _ = lec.un(el, "cbc:Amount")
        d["frais"].append((raison, montant, charge, raison[1], cx_m))
    for el in lec.tous(None, ligne_xp):
        d["lignes"].append({
            "numero_ligne": lec.un(el, "cbc:ID"),
            "reference_article": lec.un(el, "cac:Item/cac:SellersItemIdentification/cbc:ID"),
            "description": lec.un(el, "cac:Item/cbc:Name"),
            "libelle": lec.un(el, "cac:Item/cbc:Name"),
            "code_marchandise_imprime": lec.un(el, "cac:Item/cac:CommodityClassification/cbc:ItemClassificationCode"),
            "code_marchandise": lec.un(el, "cac:Item/cac:CommodityClassification/cbc:ItemClassificationCode"),
            "pays_origine": lec.un(el, "cac:Item/cac:OriginCountry/cbc:IdentificationCode"),
            "quantite": lec.un(el, qte_xp),
            "prix_unitaire": lec.un(el, "cac:Price/cbc:PriceAmount"),
            "montant": lec.un(el, "cbc:LineExtensionAmount"),
            "taux_tva": lec.un(el, "cac:Item/cac:ClassifiedTaxCategory/cbc:Percent"),
            "marqueur_tva": lec.un(el, "cac:Item/cac:ClassifiedTaxCategory/cbc:ID"),
            "notes": _notes(lec, el, "cbc:Note"),
        })
    return d


def _champs_facture(c: _Constructeur, lec: _Lecteur, d: dict[str, Any], type_doc: TypeDocument, *, ubl: bool):
    if type_doc is TypeDocument.facture_commerciale:
        champs = ChampsFactureCommerciale()
        _partie(c, lec, champs, "vendeur", d["vendeur"], ubl=ubl)
        _partie(c, lec, champs, "acheteur", d["acheteur"], ubl=ubl)
        if d["destinataire"]:
            _partie(c, lec, champs, "destinataire", d["destinataire"], ubl=ubl)
        _remplir_fc(c, champs, d)
        return champs
    champs = ChampsFactureTransitaire() if type_doc is TypeDocument.facture_transitaire else ChampsAvoir()
    _definir(champs, "numero", c.vs("numero", *d["numero"][:2]))
    _definir(champs, "date", c.vs("date", *d["date"][:2]))
    _partie(c, lec, champs, "emetteur", d["vendeur"], ubl=ubl)
    if isinstance(champs, ChampsFactureTransitaire):
        _partie(c, lec, champs, "client_facture", d["acheteur"], ubl=ubl)
    _definir(champs, "devise", c.vs("devise", *d["devise_lu"][:2]))
    _remplir_ft(c, champs, d)
    return champs


def _remplir_ft(c: _Constructeur, champs, d: dict[str, Any]) -> None:
    devise = d["devise"]
    debours: list[ValeurSourcee] = []
    mrns: list[tuple[str, str]] = []

    def ajouter_mrn(m: str, cx: str) -> None:
        if m not in [x for x, _ in mrns]:
            mrns.append((m, cx))

    for brut, cx, _nom in d["refs_doc"]:
        if not brut:
            continue
        m = _MRN_RE.search(brut.upper())
        if m:
            ajouter_mrn(m.group(1), cx)
        else:
            _definir(champs, "refs_transport[]", c.vs("refs_transport[]", brut, cx))
    for i, lg in enumerate(d["lignes"]):
        p = f"lignes[{i}]"
        lib = lg["libelle"][0]
        nature = nature_ligne(lib)
        champs.definir(f"{p}.nature", nature)
        _definir(champs, f"{p}.libelle", c.vs(f"{p}.libelle", *lg["libelle"][:2]))
        _definir(champs, f"{p}.quantite", _quantite(c, f"{p}.quantite", lg["quantite"]))
        _definir(champs, f"{p}.prix_unitaire", c.vs(f"{p}.prix_unitaire", *lg["prix_unitaire"][:2], devise=devise))
        _definir(champs, f"{p}.montant_ht", c.vs(f"{p}.montant_ht", *lg["montant"][:2], devise=devise))
        for rel in ("taux_tva", "marqueur_tva", "code_marchandise"):
            _definir(champs, f"{p}.{rel}", c.vs(f"{p}.{rel}", *lg[rel][:2]))
        sources_mrn = [(lib or "", lg["libelle"][1]), *lg["notes"]]
        for texte, cx in sources_mrn:
            m = _MRN_RE.search(texte.upper())
            if m and champs.obtenir(f"{p}.mrn") is None:
                _definir(champs, f"{p}.mrn", c.vs(f"{p}.mrn", m.group(1), cx))
                ajouter_mrn(m.group(1), cx)
        for texte, cx in lg["notes"]:
            reste = _MRN_RE.sub(" ", texte.upper())
            pct = _RX_POURCENT.search(reste)
            if pct and champs.obtenir(f"{p}.pourcentage") is None:
                _definir(champs, f"{p}.pourcentage", c.vs(f"{p}.pourcentage", pct.group(1), cx,
                                                         sep="," if "," in pct.group(1) else "."))
            per = _RX_PERIODE.search(texte)
            if per:
                _definir(champs, f"{p}.date_debut", c.vs(f"{p}.date_debut", per.group(1), cx))
                _definir(champs, f"{p}.date_fin", c.vs(f"{p}.date_fin", per.group(2), cx))
        mt = champs.obtenir(f"{p}.montant_ht")
        if nature.est_debours and mt is not None:
            debours.append(mt)
    for mrn, cx in mrns:
        _definir(champs, "refs_mrn[]", c.vs("refs_mrn[]", mrn, cx))
    t = d["totaux"]
    if isinstance(champs, ChampsFactureTransitaire):
        _definir(champs, "total_ht", c.vs("total_ht", *t["ht"][:2], devise=devise))
        _definir(champs, "total_tva", c.vs("total_tva", *t["tva"][:2], devise=devise))
        _definir(champs, "total_ttc", c.vs("total_ttc", *t["ttc"][:2], devise=devise))
        _definir(champs, "net_a_payer", c.vs("net_a_payer", *t["net"][:2], devise=devise))
        ac = t["acomptes"]
        if ac[0] and re.sub(r"[0.,\s]", "", ac[0]):
            _definir(champs, "acomptes", c.vs("acomptes", *ac[:2], devise=devise))
        if debours:
            total = deriver_somme(chemin_complet(c.type_doc, "total_debours"), debours, document_id=c.document.id,
                                  extracteur=c.extracteur, unite=devise, regle="somme_lignes_debours",
                                  total_reconstruit=True)
            champs.total_debours = total.model_copy(update={"page": c.page})
    else:
        for brut, cx, _ in d["refs_origine"]:
            _definir(champs, "refs_facture_origine[]", c.vs("refs_facture_origine[]", brut, cx))
        _definir(champs, "total_credite_ht", c.vs("total_credite_ht", *t["ht"][:2], devise=devise))
        _definir(champs, "total_tva", c.vs("total_tva", *t["tva"][:2], devise=devise))
        _definir(champs, "total_credite_ttc", c.vs("total_credite_ttc", *t["ttc"][:2], devise=devise))
        for texte, cx in d["notes"]:
            m = _RX_MOTIF.match(texte)
            if m and champs.motif is None:
                _definir(champs, "motif", c.vs("motif", m.group(1), cx))


# --- exports de déclaration -----------------------------------------------------------------------------------


def _spec(spec: Any) -> dict[str, Any]:
    if isinstance(spec, str):
        return {"source": spec}
    return dict(spec or {})


def _champs_declaration(c: _Constructeur, fiche: FicheCorrespondance, contenu: bytes,
                        avert: list[str]) -> ChampsDeclaration:
    champs = ChampsDeclaration()
    devise_defaut = fiche.devise_par_defaut
    if fiche.type == "xml":
        racine = _xml(contenu)
        if racine is None:
            raise ValueError("xml illisible")
        lec = _Lecteur(racine, fiche.espaces_noms)

        def lire(base, src: str):
            return lec.un(base, src)

        def bases_liste(spec) -> list[tuple[Any, str]]:
            return [(el, _chemin_xpath(el)) for el in lec.tous(None, spec["source"])]

        connus = _noms_xml_connus(fiche)
        for el in racine.iter():
            if isinstance(el.tag, str) and not len(el) and _local(el.tag) not in connus and _txt(el):
                avert.append(f"element_ignore:{_local(el.tag)}")
    else:
        texte = decoder_texte(contenu) or ""
        entete, rangs, numeros = fiche._lire_csv(texte)
        connues = _colonnes_csv_connues(fiche)
        for col in entete:
            if col and col not in connues:
                avert.append(f"colonne_ignoree:{col}")
                # nom de colonne lu dans le document : jamais en clair dans les journaux (RS-12)
                log.info("colonne_inconnue format=%s longueur=%d empreinte=%s", fiche.format_id, len(col),
                         hashlib.sha256(col.encode("utf-8")).hexdigest()[:12])
        col_type = "__type__" if fiche.csv.get("multi_enregistrements") else fiche.csv.get("colonne_type")

        def lire(base, src: str):
            rang, n = base
            v = rang.get(src)
            return (v or None), f"{fiche.format_id}:ligne {n}:{src}", None

        def bases_liste(spec) -> list[tuple[Any, str]]:
            out, vus = [], set()
            filtre = spec.get("type_enregistrement")
            cle = spec.get("cle")
            for r, n in zip(rangs, numeros, strict=True):
                if filtre is not None and col_type and r.get(col_type) != str(filtre):
                    continue
                if cle:
                    k = tuple(r.get(x, "") for x in ([cle] if isinstance(cle, str) else cle))
                    if not any(k) or k in vus:
                        continue
                    vus.add(k)
                out.append(((r, n), f"ligne {n}"))
            return out

    # en-tête
    def premiere_base(spec: dict[str, Any]):
        if fiche.type == "xml":
            return None
        filtre = spec.get("type_enregistrement", fiche.csv.get("type_entete"))
        for r, n in zip(rangs, numeros, strict=True):
            if filtre is not None and col_type and r.get(col_type) != str(filtre):
                continue
            if r.get(spec["source"]):
                return (r, n)
        return (rangs[0], numeros[0]) if rangs else ({}, 0)

    devise_lue: str | None = None
    for chemin, brute in sorted(fiche.entete.items(), key=lambda kv: kv[0] != "devise_facture"):
        spec = _spec(brute)
        base = premiere_base(spec)
        val, ctx_, _ = lire(base, spec["source"])
        unite = spec.get("unite")
        if spec.get("source_unite"):
            unite = lire(base, spec["source_unite"])[0] or unite
        if unite is None and type_valeur_pour(chemin) is TypeValeur.montant:
            unite = devise_lue if chemin in ("montant_total_facture",) else (spec.get("unite") or devise_defaut)
        v = c.vs(chemin, val, ctx_, devise=unite)
        _definir(champs, chemin, v)
        if chemin == "devise_facture" and v is not None:
            devise_lue = v.valeur
    for chemin, constante in fiche.constantes.items():
        v = ValeurSourcee(
            chemin=chemin_complet(TypeDocument.declaration, chemin), valeur=str(constante),
            type=type_valeur_pour(chemin), valeur_brute=f"{fiche.format_id}:{constante}",
            document_id=c.document.id, page=c.page, texte_contexte=f"fiche {fiche.format_id} v{fiche.version}",
            extracteur=c.extracteur, methode=c.methode, confiance=c.confiance, ancree=True,
        )
        champs.definir(chemin, v)

    # listes
    for nom, spec_l in fiche.listes.items():
        spec_l = dict(spec_l)
        for i, (base, _ctx) in enumerate(bases_liste(spec_l)):
            p = f"{nom}[{i}]"
            for rel, brute in (spec_l.get("champs") or {}).items():
                spec = _spec(brute)
                val, ctx_, _ = lire(base, spec["source"])
                unite = spec.get("unite")
                if spec.get("source_unite"):
                    unite = lire(base, spec["source_unite"])[0] or unite
                tv = type_valeur_pour(rel)
                if unite is None and tv is TypeValeur.montant:
                    unite = (devise_lue if rel == "montant_facture_article" else None) or devise_defaut
                v = c.vs(f"{p}.{rel}", val, ctx_, devise=unite if tv is TypeValeur.montant else None)
                if v is not None and tv is TypeValeur.quantite and unite:
                    u = normalize_unit(unite)
                    v = v.model_copy(update={"unite": u.code, "unite_brute": u.brut})
                _definir(champs, f"{p}.{rel}", v)
            objet = champs.obtenir(p)
            for rel, brute in (spec_l.get("enumerations") or {}).items():
                val = lire(base, _spec(brute)["source"])[0]
                if objet is None or val is None:
                    continue
                cible = type(objet).model_fields.get(rel)
                if cible is None:
                    continue
                for enum in (TauxNature, CategorieTaxe, PaiementNormalise, NatureLigne):
                    if enum.__name__ in str(cible.annotation):
                        try:
                            setattr(objet, rel, enum(val.strip()))
                        except ValueError:
                            avert.append(f"enumeration_inconnue:{rel}")
                        break
    _deriver_declaration(champs, fiche)
    _indices_autoliquidation(c, champs)
    return champs


def _noms_xml_connus(fiche: FicheCorrespondance) -> set[str]:
    noms: set[str] = set()

    def ajouter(src: str) -> None:
        for seg in re.split(r"[/|@\[\]=' ]+", src):
            if seg and seg not in (".", ".."):
                noms.add(seg.split(":")[-1])

    for spec in list(fiche.entete.values()):
        s = _spec(spec)
        ajouter(s["source"])
        if s.get("source_unite"):
            ajouter(s["source_unite"])
    for spec_l in fiche.listes.values():
        ajouter(spec_l.get("source", ""))
        for spec in [*(spec_l.get("champs") or {}).values(), *(spec_l.get("enumerations") or {}).values()]:
            s = _spec(spec)
            ajouter(s["source"])
            if s.get("source_unite"):
                ajouter(s["source_unite"])
    noms.update(fiche.detection.get("ignorer", []) or [])
    return noms


def _colonnes_csv_connues(fiche: FicheCorrespondance) -> set[str]:
    multi = bool(fiche.csv.get("multi_enregistrements"))
    type_entete = fiche.csv.get("type_entete")
    cols = set(fiche.detection.get("ignorer", []) or [])
    if fiche.csv.get("colonne_type"):
        cols.add(fiche.csv["colonne_type"])

    def nom(src: str, spec: dict[str, Any], defaut: str | None) -> str:
        t = spec.get("type_enregistrement", defaut)
        return f"{t}.{src}" if multi and t else src

    for spec in fiche.entete.values():
        sp = _spec(spec)
        cols.add(nom(sp["source"], sp, type_entete))
        if sp.get("source_unite"):
            cols.add(nom(sp["source_unite"], sp, type_entete))
    for spec_l in fiche.listes.values():
        t = spec_l.get("type_enregistrement")
        if isinstance(spec_l.get("cle"), str):
            cols.add(f"{t}.{spec_l['cle']}" if multi and t else spec_l["cle"])
        for spec in [*(spec_l.get("champs") or {}).values(), *(spec_l.get("enumerations") or {}).values()]:
            sp = _spec(spec)
            cols.add(f"{t}.{sp['source']}" if multi and t else sp["source"])
            if sp.get("source_unite"):
                cols.add(f"{t}.{sp['source_unite']}" if multi and t else sp["source_unite"])
    return cols


def _deriver_declaration(champs: ChampsDeclaration, fiche: FicheCorrespondance) -> None:
    t_cat = fiche.tables.get("categorie")
    t_pai = fiche.tables.get("paiement")
    for t in champs.taxations:
        t.categorie = categorie_taxe(t.type_taxe.valeur if t.type_taxe else None, t_cat)
        t.paiement_normalise = paiement_normalise(
            (t.mode_paiement.valeur_brute or t.mode_paiement.valeur) if t.mode_paiement else None, t_pai)
        if t.taux is not None and t.taux_nature is None:
            if t.base_quantite is not None and t.base_montant is None:
                t.taux_nature = TauxNature.specifique
            else:
                t.taux_nature = TauxNature.ad_valorem


def _indices_autoliquidation(c: _Constructeur, champs: ChampsDeclaration) -> None:
    """Indices lus (§5.3.2) : code 1008 suivi d'un numéro de TVA, référence FR7, paiement TVA non comptant."""
    for ref in champs.documents_references:
        code = (ref.type_code.valeur if ref.type_code else "") or ""
        refv = (ref.reference.valeur_brute if ref.reference else "") or ""
        if code.strip() == "1008" or re.search(r"\b1008\b", code):
            k = len(champs.indices_autoliquidation)
            tva = None
            if ref.reference is not None:
                tva = c.vs(f"indices_autoliquidation[{k}].tva", ref.reference.valeur_brute,
                           ref.reference.texte_contexte)
            champs.indices_autoliquidation.append(IndiceAutoliquidation(
                type=TypeIndiceAutoliquidation.code_1008, valeur=ref.type_code, tva=tva))
        elif re.match(r"^\s*FR7", refv.upper()) or re.search(r"\bFR7\b", code.upper()):
            champs.indices_autoliquidation.append(IndiceAutoliquidation(
                type=TypeIndiceAutoliquidation.reference_fr7, valeur=ref.reference or ref.type_code))
    for t in champs.taxations:
        if t.categorie is CategorieTaxe.tva and t.paiement_normalise is PaiementNormalise.autoliquide and t.mode_paiement:
            champs.indices_autoliquidation.append(IndiceAutoliquidation(
                type=TypeIndiceAutoliquidation.mode_paiement_tva, valeur=t.mode_paiement))


# --- extracteurs ---------------------------------------------------------------------------------------------


def _contenu_et_mime(ctx: ExtractionContext) -> tuple[bytes | None, str | None]:
    contenu = ctx.contenu_fichier
    if contenu is None:
        return None, None
    mime = ctx.type_mime
    if mime is None or mime not in (MIME_PDF, MIME_XML, MIME_CSV):
        mime = detecter_type(contenu)
    return contenu, mime


class ExtracteurFactureXML:
    """Factur-X, CII D16B, UBL 2.1 -> facture commerciale, facture de transitaire ou avoir."""

    id = "structure_facture_xml"
    version = VERSION_STRUCTURE
    type = "structure"

    def supports(self, document: Document, pages: Sequence[Page]) -> bool:
        # Un XML est lu tel quel (page = texte brut) ; un PDF peut être un Factur-X (vérifié à l'extraction).
        return document.type in (TypeDocument.facture_commerciale, TypeDocument.facture_transitaire,
                                 TypeDocument.avoir)

    def extract(self, document: Document, pages: Sequence[Page], context: ExtractionContext) -> ExtractionResult:
        info_ex = _extracteur_info(self.id)
        contenu, mime = _contenu_et_mime(context)
        if contenu is None or mime not in (MIME_PDF, MIME_XML):
            return ExtractionResult(extracteur=info_ex)
        info = analyser_contenu_structure(contenu, mime, fiches=())
        if info is None or info.xml is None or info.format not in ("cii", "ubl", "facturx"):
            return ExtractionResult(extracteur=info_ex)
        racine = _xml(info.xml)
        if racine is None:
            return ExtractionResult(extracteur=info_ex, avertissements=["xml_illisible"])
        avert = [] if info.schema_valide else ["schema_non_valide"]
        conf = CONFIANCE_VALIDE if info.schema_valide else CONFIANCE_NON_VALIDE
        # Le type retenu est celui du document classé (le classement l'a tiré du même XML).
        type_doc = document.type
        c = _Constructeur(document, type_doc, info_ex, Methode.xml_structure, conf, context)
        nom = _local(racine.tag)
        if nom == "CrossIndustryInvoice":
            lec = _Lecteur(racine, NS_CII)
            champs = _champs_facture(c, lec, _lire_cii(lec), type_doc, ubl=False)
        else:
            lec = _Lecteur(racine, {**NS_UBL, "inv": etree.QName(racine.tag).namespace})
            champs = _champs_facture(c, lec, _lire_ubl(lec, credit=(nom == "CreditNote")), type_doc, ubl=True)
        return ExtractionResult(extracteur=info_ex, champs=champs, avertissements=avert)


class ExtracteurDeclarationExport:
    """Exports de déclaration XML / CSV décrits par une fiche de correspondance (§5.3.6)."""

    id = "structure_declaration_export"
    version = VERSION_STRUCTURE
    type = "structure"

    def __init__(self, fiches: Iterable[FicheCorrespondance] | None = None) -> None:
        self._fiches = tuple(fiches) if fiches is not None else None

    @property
    def fiches(self) -> tuple[FicheCorrespondance, ...]:
        return self._fiches if self._fiches is not None else charger_fiches()

    def supports(self, document: Document, pages: Sequence[Page]) -> bool:
        return document.type is TypeDocument.declaration

    def extract(self, document: Document, pages: Sequence[Page], context: ExtractionContext) -> ExtractionResult:
        info_ex = _extracteur_info(self.id)
        contenu, mime = _contenu_et_mime(context)
        if contenu is None or mime not in (MIME_XML, MIME_CSV):
            return ExtractionResult(extracteur=info_ex)
        fiche = next((f for f in self.fiches if f.reconnait(contenu, mime)), None)
        if fiche is None:
            return ExtractionResult(extracteur=info_ex)
        methode = Methode.xml_structure if fiche.type == "xml" else Methode.csv_structure
        sep = fiche.csv.get("separateur_decimal", ".") if fiche.type == "csv" else (
            fiche.detection.get("separateur_decimal") or ".")
        c = _Constructeur(document, TypeDocument.declaration, info_ex, methode, CONFIANCE_VALIDE, context,
                          separateur_decimal=sep, format_date=fiche.csv.get("format_date") or fiche.detection.get(
                              "format_date"))
        avert: list[str] = []
        try:
            champs = _champs_declaration(c, fiche, contenu, avert)
        except (ValueError, KeyError) as e:
            return ExtractionResult(extracteur=info_ex, avertissements=[f"export_illisible:{type(e).__name__}"],
                                    partielle=True)
        return ExtractionResult(extracteur=info_ex, champs=champs,
                                avertissements=[f"fiche:{fiche.format_id}@{fiche.version}", *sorted(set(avert))])


def extracteurs() -> list[Any]:
    """Extracteurs ``structure`` publiés par l'ingestion."""
    return [ExtracteurFactureXML(), ExtracteurDeclarationExport()]


# Alias pour l'export des types utiles.
__all__ += ["est_facture_transitaire"]
