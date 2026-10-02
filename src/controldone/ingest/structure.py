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

_NATURES: list[tuple[NatureLigne, re.Pattern[str]]] = [
    (NatureLigne.frais_avance_fonds, re.compile(
        r"avance de fonds|frais d'avance|advance (?:fee|of funds)|disbursement fee|commission (?:sur|de) debours|"
        r"frais financiers|anticipo de fondos|frais de debours")),
    (NatureLigne.debours_combines, re.compile(
        r"droits? (?:et|&) taxes|duties (?:and|&) taxes|duty (?:and|&) tax|derechos e impuestos|"
        r"droits et tva|taxes et droits")),
    (NatureLigne.debours_forfait_petits_envois, re.compile(
        r"droit forfaitaire|forfait (?:petits? envois|par article)|flat[- ]rate duty|flat duty|"
        r"low[- ]value (?:consignment )?duty|derecho (?:a tanto alzado|fijo)")),
    (NatureLigne.debours_tva, re.compile(
        r"tva (?:a l')?import|import vat|vat on import|tva (?:douane|import|sur importation|debours)|"
        r"iva (?:de )?importacion|^tva\b|\btva avancee")),
    (NatureLigne.debours_autres_taxes, re.compile(
        r"accises?|excise|anti-?dumping|compensat|autres? taxes?|other (?:taxes|duties)|octroi de mer|"
        r"taxe (?:speciale|additionnelle|interieure)|impuestos especiales")),
    (NatureLigne.debours_droits, re.compile(
        r"droits? de douane|customs dut(?:y|ies)|\bduty\b|\bduties\b|\bdroits?\b|aranceles?|derechos de aduana")),
    (NatureLigne.frais_ligne_supplementaire, re.compile(
        r"lignes? supplementaires?|articles? supplementaires?|additional (?:lines?|items?|articles?)|"
        r"ligne(?:s)? (?:de )?(?:declaration )?sup|extra (?:lines?|items?)|partida adicional")),
    (NatureLigne.frais_dedouanement, re.compile(
        r"dedouanement|customs clearance|clearance|formalites? (?:de )?douan|declaration en douane|"
        r"despacho (?:de )?aduan|customs (?:formalities|entry|declaration)|representation en douane")),
    (NatureLigne.magasinage, re.compile(r"magasinage|storage|entreposage|almacenaje|stockage|demurrage")),
    (NatureLigne.manutention, re.compile(r"manutention|handling|manipulacion")),
    (NatureLigne.surcharge, re.compile(
        r"surcharge|carburant|\bfuel\b|surete|security|haute saison|peak season|recargo")),
    (NatureLigne.transport, re.compile(
        r"transport|livraison|enlevement|delivery|pick-? ?up|acheminement|\bfret\b|freight|camionnage|"
        r"\bentrega\b|recogida")),
]


def _norm(t: str) -> str:
    from controldone.normalize.text import sans_accents

    return re.sub(r"\s+", " ", sans_accents(t).lower().replace("’", "'")).strip()


def nature_ligne(libelle: str | None) -> NatureLigne:
    """Nature d'une ligne de facture transitaire d'après son libellé (§5.3.3) ; ``autre_prestation`` sinon."""
    if not libelle:
        return NatureLigne.autre_prestation
    t = _norm(libelle)
    for nature, rx in _NATURES:
        if rx.search(t):
            return nature
    return NatureLigne.autre_prestation


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
            for chemin in (spec.get("champs") or {}):
                if f"{nom}[].{chemin}" not in valides and f"{nom}[]" != f"{nom}[].{chemin}":
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
        sep = self.csv.get("separateur") or ";"
        lignes = texte.lstrip("﻿").replace("\r\n", "\n").replace("\r", "\n").split("\n")
        lecteur = csv.reader(lignes, delimiter=sep, quotechar=self.csv.get("guillemet", '"'))
        rangs = list(lecteur)
        if not rangs:
            return [], [], []
        entete = [c.strip() for c in rangs[0]]
        out, numeros = [], []
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
    """Chemin lisible d'un nœud (``/Invoice/cac:InvoiceLine[2]/cbc:ID``) pour ``texte_contexte``."""
    try:
        return el.getroottree().getpath(el)
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
           page: int | None = None) -> ValeurSourcee | None:
        if brut is None or not str(brut).strip():
            return None
        brut = str(brut).strip()
        tv = type_valeur_pour(chemin)
        v = valeur_sourcee(
            type_document=self.type_doc, chemin=chemin, brut=brut, document_id=self.document.id,
            page=page or self.page, extracteur=self.extracteur, methode=self.methode, confiance=self.confiance,
            texte_contexte=contexte, separateur_decimal=self.sep, devise=devise,
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
    if v is not None:
        champs.definir(chemin, v)


def _extracteur_info(id_: str) -> ExtracteurInfo:
    return ExtracteurInfo(type=TypeExtracteur.structure, id=id_, version=VERSION_STRUCTURE)


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
            return el.strip() or None, xp, None
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


def _champs_facture_cii(c: _Constructeur, lec: _Lecteur, type_doc: TypeDocument):
    ns_hdr = _CII_HDR
    devise_brut, devise_ctx, _ = lec.un(None, f"{_CII_SET}/ram:InvoiceCurrencyCode")
    devise = (devise_brut or "").upper() or None
    num, num_ctx, _ = lec.un(None, "rsm:ExchangedDocument/ram:ID")
    date, date_ctx, _ = lec.un(None, "rsm:ExchangedDocument/ram:IssueDateTime/udt:DateTimeString")
    if type_doc is TypeDocument.facture_commerciale:
        champs = ChampsFactureCommerciale()
        _definir(champs, "numero", c.vs("numero", num, num_ctx))
        _definir(champs, "date", c.vs("date", date, date_ctx))
        _partie(c, lec, champs, "vendeur", f"{ns_hdr}/ram:SellerTradeParty", ubl=False)
        _partie(c, lec, champs, "acheteur", f"{ns_hdr}/ram:BuyerTradeParty", ubl=False)
        _partie(c, lec, champs, "destinataire", f"{_CII_DEL}/ram:ShipToTradeParty", ubl=False)
        _definir(champs, "devise", c.vs("devise", devise_brut, devise_ctx))
        total, t_ctx, _ = lec.un(None, f"{_CII_SUM}/ram:GrandTotalAmount")
        if total is None:
            total, t_ctx, _ = lec.un(None, f"{_CII_SUM}/ram:DuePayableAmount")
        v = c.vs("total_facture", total, t_ctx, devise=devise)
        if v is not None:
            from controldone.model.enums import TotalOrigine

            v = v.model_copy(update={"total_origine": TotalOrigine.imprime})
        _definir(champs, "total_facture", v)
        inc, i_ctx, _ = lec.un(None, f"{ns_hdr}/ram:ApplicableTradeDeliveryTerms/ram:DeliveryTypeCode")
        _definir(champs, "incoterm", c.vs("incoterm", inc, i_ctx))
        for i, ligne in enumerate(lec.tous(None, "rsm:SupplyChainTradeTransaction/ram:IncludedSupplyChainTradeLineItem")):
            p = f"lignes[{i}]"
            for rel, xp in (
                ("numero_ligne", "ram:AssociatedDocumentLineDocument/ram:LineID"),
                ("reference_article", "ram:SpecifiedTradeProduct/ram:SellerAssignedID"),
                ("description", "ram:SpecifiedTradeProduct/ram:Name"),
                ("code_marchandise_imprime", "ram:SpecifiedTradeProduct/ram:DesignatedProductClassification/ram:ClassCode"),
                ("pays_origine", "ram:SpecifiedTradeProduct/ram:OriginTradeCountry/ram:ID"),
            ):
                val, cx, _ = lec.un(ligne, xp)
                _definir(champs, f"{p}.{rel}", c.vs(f"{p}.{rel}", val, cx))
            q, cx, el = lec.un(ligne, "ram:SpecifiedLineTradeDelivery/ram:BilledQuantity")
            if q is not None and el is not None:
                v = c.vs(f"{p}.quantite", q, cx)
                if v is not None and el.get("unitCode"):
                    v = v.model_copy(update={"unite": el.get("unitCode"), "unite_brute": el.get("unitCode")})
                _definir(champs, f"{p}.quantite", v)
            pu, cx, _ = lec.un(ligne, "ram:SpecifiedLineTradeAgreement/ram:NetPriceProductTradePrice/ram:ChargeAmount")
            _definir(champs, f"{p}.prix_unitaire", c.vs(f"{p}.prix_unitaire", pu, cx, devise=devise))
            mt, cx, _ = lec.un(ligne, "ram:SpecifiedLineTradeSettlement/"
                                      "ram:SpecifiedTradeSettlementLineMonetarySummation/ram:LineTotalAmount")
            _definir(champs, f"{p}.montant_ligne", c.vs(f"{p}.montant_ligne", mt, cx, devise=devise))
        return champs
    # facture transitaire / avoir
    champs = ChampsFactureTransitaire() if type_doc is TypeDocument.facture_transitaire else ChampsAvoir()
    _definir(champs, "numero", c.vs("numero", num, num_ctx))
    _definir(champs, "date", c.vs("date", date, date_ctx))
    _partie(c, lec, champs, "emetteur", f"{ns_hdr}/ram:SellerTradeParty", ubl=False)
    if isinstance(champs, ChampsFactureTransitaire):
        _partie(c, lec, champs, "client_facture", f"{ns_hdr}/ram:BuyerTradeParty", ubl=False)
    _definir(champs, "devise", c.vs("devise", devise_brut, devise_ctx))
    lignes = []
    for el in lec.tous(None, "rsm:SupplyChainTradeTransaction/ram:IncludedSupplyChainTradeLineItem"):
        lignes.append({
            "libelle": lec.un(el, "ram:SpecifiedTradeProduct/ram:Name"),
            "quantite": lec.un(el, "ram:SpecifiedLineTradeDelivery/ram:BilledQuantity"),
            "prix_unitaire": lec.un(el, "ram:SpecifiedLineTradeAgreement/ram:NetPriceProductTradePrice/ram:ChargeAmount"),
            "montant_ht": lec.un(el, "ram:SpecifiedLineTradeSettlement/ram:SpecifiedTradeSettlementLineMonetarySummation/"
                                     "ram:LineTotalAmount"),
            "taux_tva": lec.un(el, "ram:SpecifiedLineTradeSettlement/ram:ApplicableTradeTax/ram:RateApplicablePercent"),
            "marqueur_tva": lec.un(el, "ram:SpecifiedLineTradeSettlement/ram:ApplicableTradeTax/ram:CategoryCode"),
            "code_marchandise": lec.un(el, "ram:SpecifiedTradeProduct/ram:DesignatedProductClassification/ram:ClassCode"),
        })
    totaux = {
        "ht": lec.un(None, f"{_CII_SUM}/ram:TaxBasisTotalAmount"),
        "tva": lec.un(None, f"{_CII_SUM}/ram:TaxTotalAmount"),
        "ttc": lec.un(None, f"{_CII_SUM}/ram:GrandTotalAmount"),
        "net": lec.un(None, f"{_CII_SUM}/ram:DuePayableAmount"),
        "acomptes": lec.un(None, f"{_CII_SUM}/ram:TotalPrepaidAmount"),
    }
    refs_origine = [lec.un(x, ".") for x in lec.tous(None, f"{_CII_SET}/ram:InvoiceReferencedDocument/ram:IssuerAssignedID")]
    refs_doc = [lec.un(x, ".") for x in lec.tous(None, f"{_CII_HDR}/ram:AdditionalReferencedDocument/ram:IssuerAssignedID")]
    _remplir_ft(c, champs, lignes, totaux, refs_origine, refs_doc, devise)
    return champs


def _remplir_ft(c: _Constructeur, champs, lignes, totaux, refs_origine, refs_doc, devise) -> None:
    debours: list[ValeurSourcee] = []
    mrns: list[str] = []
    for i, lg in enumerate(lignes):
        p = f"lignes[{i}]"
        lib = lg["libelle"][0]
        nature = nature_ligne(lib)
        champs.definir(f"{p}.nature", nature)
        _definir(champs, f"{p}.libelle", c.vs(f"{p}.libelle", lib, lg["libelle"][1]))
        q, cx, el = lg["quantite"]
        v = c.vs(f"{p}.quantite", q, cx)
        if v is not None and el is not None and el.get("unitCode"):
            v = v.model_copy(update={"unite": el.get("unitCode"), "unite_brute": el.get("unitCode")})
        _definir(champs, f"{p}.quantite", v)
        for rel in ("prix_unitaire", "montant_ht"):
            _definir(champs, f"{p}.{rel}", c.vs(f"{p}.{rel}", lg[rel][0], lg[rel][1], devise=devise))
        for rel in ("taux_tva", "marqueur_tva", "code_marchandise"):
            _definir(champs, f"{p}.{rel}", c.vs(f"{p}.{rel}", lg[rel][0], lg[rel][1]))
        if lib:
            m = _MRN_RE.search(lib.upper())
            if m:
                _definir(champs, f"{p}.mrn", c.vs(f"{p}.mrn", m.group(1), lg["libelle"][1]))
                if m.group(1) not in mrns:
                    mrns.append(m.group(1))
        mt = champs.obtenir(f"{p}.montant_ht")
        if nature.est_debours and mt is not None:
            debours.append(mt)
    for brut, cx, _ in refs_doc:
        if not brut:
            continue
        m = _MRN_RE.search(brut.upper())
        if m and m.group(1) not in mrns:
            mrns.append(m.group(1))
        elif not m and isinstance(champs, ChampsFactureTransitaire | ChampsAvoir):
            _definir(champs, "refs_transport[]", c.vs("refs_transport[]", brut, cx))
    for mrn in mrns:
        _definir(champs, "refs_mrn[]", c.vs("refs_mrn[]", mrn, "MRN cité"))
    if isinstance(champs, ChampsFactureTransitaire):
        _definir(champs, "total_ht", c.vs("total_ht", totaux["ht"][0], totaux["ht"][1], devise=devise))
        _definir(champs, "total_tva", c.vs("total_tva", totaux["tva"][0], totaux["tva"][1], devise=devise))
        _definir(champs, "total_ttc", c.vs("total_ttc", totaux["ttc"][0], totaux["ttc"][1], devise=devise))
        _definir(champs, "net_a_payer", c.vs("net_a_payer", totaux["net"][0], totaux["net"][1], devise=devise))
        ac = totaux["acomptes"]
        if ac[0] and re.sub(r"[0.,\s]", "", ac[0]):
            _definir(champs, "acomptes", c.vs("acomptes", ac[0], ac[1], devise=devise))
        if debours:
            total = deriver_somme(chemin_complet(c.type_doc, "total_debours"), debours, document_id=c.document.id,
                                  extracteur=c.extracteur, unite=devise, regle="somme_lignes_debours",
                                  total_reconstruit=True)
            champs.total_debours = total.model_copy(update={"page": c.page, "confiance": min(
                total.confiance, 1.0)})
    else:
        for brut, cx, _ in refs_origine:
            _definir(champs, "refs_facture_origine[]", c.vs("refs_facture_origine[]", brut, cx))
        _definir(champs, "total_credite_ht", c.vs("total_credite_ht", totaux["ht"][0], totaux["ht"][1], devise=devise))
        _definir(champs, "total_tva", c.vs("total_tva", totaux["tva"][0], totaux["tva"][1], devise=devise))
        _definir(champs, "total_credite_ttc", c.vs("total_credite_ttc", totaux["ttc"][0], totaux["ttc"][1],
                                                   devise=devise))


# --- UBL ----------------------------------------------------------------------------------------------------


def _champs_facture_ubl(c: _Constructeur, lec: _Lecteur, type_doc: TypeDocument, credit: bool):
    devise_brut, devise_ctx, _ = lec.un(None, "cbc:DocumentCurrencyCode")
    devise = (devise_brut or "").upper() or None
    num, num_ctx, _ = lec.un(None, "cbc:ID")
    date, date_ctx, _ = lec.un(None, "cbc:IssueDate")
    ligne_xp = "cac:CreditNoteLine" if credit else "cac:InvoiceLine"
    qte_xp = "cbc:CreditedQuantity" if credit else "cbc:InvoicedQuantity"
    if type_doc is TypeDocument.facture_commerciale:
        champs = ChampsFactureCommerciale()
        _definir(champs, "numero", c.vs("numero", num, num_ctx))
        _definir(champs, "date", c.vs("date", date, date_ctx))
        _partie(c, lec, champs, "vendeur", "cac:AccountingSupplierParty", ubl=True)
        _partie(c, lec, champs, "acheteur", "cac:AccountingCustomerParty", ubl=True)
        dests = lec.tous(None, "cac:Delivery/cac:DeliveryParty")
        if dests:
            v, cx, _ = lec.un(dests[0], "cac:PartyName/cbc:Name")
            _definir(champs, "destinataire.nom", c.vs("destinataire.nom", v, cx))
        _definir(champs, "devise", c.vs("devise", devise_brut, devise_ctx))
        total, t_ctx, _ = lec.un(None, "cac:LegalMonetaryTotal/cbc:TaxInclusiveAmount")
        if total is None:
            total, t_ctx, _ = lec.un(None, "cac:LegalMonetaryTotal/cbc:PayableAmount")
        v = c.vs("total_facture", total, t_ctx, devise=devise)
        if v is not None:
            from controldone.model.enums import TotalOrigine

            v = v.model_copy(update={"total_origine": TotalOrigine.imprime})
        _definir(champs, "total_facture", v)
        inc, i_ctx, _ = lec.un(None, "cac:Delivery/cac:DeliveryTerms/cbc:ID | cac:DeliveryTerms/cbc:ID")
        _definir(champs, "incoterm", c.vs("incoterm", inc, i_ctx))
        for i, ligne in enumerate(lec.tous(None, ligne_xp)):
            p = f"lignes[{i}]"
            for rel, xp in (
                ("numero_ligne", "cbc:ID"),
                ("reference_article", "cac:Item/cac:SellersItemIdentification/cbc:ID"),
                ("description", "cac:Item/cbc:Name"),
                ("code_marchandise_imprime", "cac:Item/cac:CommodityClassification/cbc:ItemClassificationCode"),
                ("pays_origine", "cac:Item/cac:OriginCountry/cbc:IdentificationCode"),
            ):
                val, cx, _ = lec.un(ligne, xp)
                _definir(champs, f"{p}.{rel}", c.vs(f"{p}.{rel}", val, cx))
            q, cx, el = lec.un(ligne, qte_xp)
            if q is not None and el is not None:
                v = c.vs(f"{p}.quantite", q, cx)
                if v is not None and el.get("unitCode"):
                    v = v.model_copy(update={"unite": el.get("unitCode"), "unite_brute": el.get("unitCode")})
                _definir(champs, f"{p}.quantite", v)
            pu, cx, _ = lec.un(ligne, "cac:Price/cbc:PriceAmount")
            _definir(champs, f"{p}.prix_unitaire", c.vs(f"{p}.prix_unitaire", pu, cx, devise=devise))
            mt, cx, _ = lec.un(ligne, "cbc:LineExtensionAmount")
            _definir(champs, f"{p}.montant_ligne", c.vs(f"{p}.montant_ligne", mt, cx, devise=devise))
        return champs
    champs = ChampsFactureTransitaire() if type_doc is TypeDocument.facture_transitaire else ChampsAvoir()
    _definir(champs, "numero", c.vs("numero", num, num_ctx))
    _definir(champs, "date", c.vs("date", date, date_ctx))
    _partie(c, lec, champs, "emetteur", "cac:AccountingSupplierParty", ubl=True)
    if isinstance(champs, ChampsFactureTransitaire):
        _partie(c, lec, champs, "client_facture", "cac:AccountingCustomerParty", ubl=True)
    _definir(champs, "devise", c.vs("devise", devise_brut, devise_ctx))
    lignes = []
    for el in lec.tous(None, ligne_xp):
        lignes.append({
            "libelle": lec.un(el, "cac:Item/cbc:Name"),
            "quantite": lec.un(el, qte_xp),
            "prix_unitaire": lec.un(el, "cac:Price/cbc:PriceAmount"),
            "montant_ht": lec.un(el, "cbc:LineExtensionAmount"),
            "taux_tva": lec.un(el, "cac:Item/cac:ClassifiedTaxCategory/cbc:Percent"),
            "marqueur_tva": lec.un(el, "cac:Item/cac:ClassifiedTaxCategory/cbc:ID"),
            "code_marchandise": lec.un(el, "cac:Item/cac:CommodityClassification/cbc:ItemClassificationCode"),
        })
    totaux = {
        "ht": lec.un(None, "cac:LegalMonetaryTotal/cbc:TaxExclusiveAmount"),
        "tva": lec.un(None, "cac:TaxTotal/cbc:TaxAmount"),
        "ttc": lec.un(None, "cac:LegalMonetaryTotal/cbc:TaxInclusiveAmount"),
        "net": lec.un(None, "cac:LegalMonetaryTotal/cbc:PayableAmount"),
        "acomptes": lec.un(None, "cac:LegalMonetaryTotal/cbc:PrepaidAmount"),
    }
    refs_origine = [lec.un(x, ".") for x in lec.tous(None, "cac:BillingReference/cac:InvoiceDocumentReference/cbc:ID")]
    refs_doc = [lec.un(x, ".") for x in lec.tous(None, "cac:AdditionalDocumentReference/cbc:ID")]
    _remplir_ft(c, champs, lignes, totaux, refs_origine, refs_doc, devise)
    return champs


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
                log.info("colonne_inconnue format=%s colonne=%s", fiche.format_id, col)
        col_type = fiche.csv.get("colonne_type")

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
            if filtre is not None and fiche.csv.get("colonne_type") and r.get(fiche.csv["colonne_type"]) != str(filtre):
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
                if unite is None and type_valeur_pour(rel) is TypeValeur.montant:
                    unite = (devise_lue if rel == "montant_facture_article" else None) or devise_defaut
                _definir(champs, f"{p}.{rel}", c.vs(f"{p}.{rel}", val, ctx_, devise=unite))
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
        ajouter(spec_l["source"])
        for spec in (spec_l.get("champs") or {}).values():
            s = _spec(spec)
            ajouter(s["source"])
            if s.get("source_unite"):
                ajouter(s["source_unite"])
    noms.update(fiche.detection.get("ignorer", []) or [])
    return noms


def _colonnes_csv_connues(fiche: FicheCorrespondance) -> set[str]:
    cols = set(fiche.detection.get("ignorer", []) or [])
    if fiche.csv.get("colonne_type"):
        cols.add(fiche.csv["colonne_type"])
    for spec in fiche.entete.values():
        s = _spec(spec)
        cols.add(s["source"])
        if s.get("source_unite"):
            cols.add(s["source_unite"])
    for spec_l in fiche.listes.values():
        if isinstance(spec_l.get("cle"), str):
            cols.add(spec_l["cle"])
        for spec in (spec_l.get("champs") or {}).values():
            s = _spec(spec)
            cols.add(s["source"])
            if s.get("source_unite"):
                cols.add(s["source_unite"])
    return cols


def _deriver_declaration(champs: ChampsDeclaration, fiche: FicheCorrespondance) -> None:
    t_cat = fiche.tables.get("categorie")
    t_pai = fiche.tables.get("paiement")
    for t in champs.taxations:
        t.categorie = categorie_taxe(t.type_taxe.valeur if t.type_taxe else None, t_cat)
        t.paiement_normalise = paiement_normalise(
            (t.mode_paiement.valeur_brute or t.mode_paiement.valeur) if t.mode_paiement else None, t_pai)
        if t.taux is not None:
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
            champs = _champs_facture_cii(c, _Lecteur(racine, NS_CII), type_doc)
        else:
            ns = {**NS_UBL, "inv": etree.QName(racine.tag).namespace}
            champs = _champs_facture_ubl(c, _Lecteur(racine, ns), type_doc, credit=(nom == "CreditNote"))
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
