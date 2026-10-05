#!/usr/bin/env python
"""Corpus public de factures électroniques : téléchargement, passage dans le pipeline, exactitude par champ.

Les spécimens publiés sous licence libre (voir ``docs/CORPUS_PUBLIC.md``) sont récupérés dans
``var/corpus_public/`` (ignoré par git : **aucun fichier tiers n'est versionné**). Chaque fichier passe par le
vrai pipeline : réception (type par octets, refus), pages, classement, extracteurs ``structure``, puis le
diagnostic (``controldone diagnostic`` sur un lot d'un seul fichier : contrôles + rapport). Une vérité de
terrain **indépendante** est lue directement dans le XML (lecteur XPath séparé, ci-dessous, qui n'utilise
aucun code de ``controldone``) et comparée aux valeurs produites.

Exemples ::

    python scripts/corpus_public.py fetch
    python scripts/corpus_public.py run --workers 3 --out var/corpus_public/rapport/apres.json
    python scripts/corpus_public.py run --sans-diagnostic --source en16931
    python scripts/corpus_public.py compare var/corpus_public/rapport/avant.json var/corpus_public/rapport/apres.json

Le texte des fichiers est une donnée : rien n'est exécuté ni interprété.
"""

from __future__ import annotations

import argparse
import fnmatch
import io
import json
import logging
import os
import subprocess
import sys
import tempfile
import time
import traceback
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

RACINE = Path(__file__).resolve().parents[1]
DOSSIER = RACINE / "var" / "corpus_public"

# --- sources --------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Source:
    nom: str
    depot: str
    licence: str
    #: motifs (fnmatch, relatifs au dépôt) des fichiers retenus
    inclure: tuple[str, ...]
    #: motifs exclus (documents d'apparence réelle, dossiers hors spécimens)
    exclure: tuple[str, ...] = ()
    #: motifs des fichiers « unitaires » (tests de règles, fragments) : robustesse seulement
    unitaires: tuple[str, ...] = ()

    @property
    def dossier(self) -> Path:
        return DOSSIER / self.nom


SOURCES: tuple[Source, ...] = (
    Source(
        nom="zugferd", depot="https://github.com/ZUGFeRD/corpus", licence="Apache-2.0",
        inclure=("ZUGFeRDv1/*", "ZUGFeRDv2/*", "XML-Rechnung/*", "PEPPOL/*", "fatturaPA/*", "other/*"),
        # unstructured/ : facture réelle d'un hébergeur ; incoming/ : dépôt de factures reçues (réelles) ;
        # FX-With-UBL-REC50304330.pdf : document réel partiellement pseudonymisé (numéros, nom de contact).
        exclure=("unstructured/*", "incoming/*", "ZUGFeRDv2/fail/FX-With-UBL-REC50304330.pdf"),
    ),
    Source(
        nom="en16931", depot="https://github.com/ConnectingEurope/eInvoicing-EN16931", licence="EUPL-1.2",
        inclure=("cii/examples/*", "ubl/examples/*", "test/testfiles/*", "test/cii/*", "edifact/examples/*",
                 "test/Invoice-unit-UBL/*", "test/CreditNote-unit-UBL/*"),
        unitaires=("test/Invoice-unit-UBL/*", "test/CreditNote-unit-UBL/*"),
    ),
    Source(
        nom="peppol", depot="https://github.com/OpenPEPPOL/peppol-bis-invoice-3", licence="pas de fichier LICENSE ; © OpenPeppol AISBL, exemples publiés",
        inclure=("rules/examples/*", "rules/national-examples/*", "rules/unit-*", "rules/snippets/*"),
        unitaires=("rules/unit-*", "rules/snippets/*"),
    ),
    Source(
        nom="facturx", depot="https://github.com/akretion/factur-x", licence="BSD-3-Clause",
        inclure=("tests/fixtures/*",),
    ),
)
EXTENSIONS = {".xml", ".pdf"}


def fetch(sources: list[Source]) -> None:
    DOSSIER.mkdir(parents=True, exist_ok=True)
    for s in sources:
        if (s.dossier / ".git").exists():
            subprocess.run(["git", "-C", str(s.dossier), "pull", "-q", "--depth", "1"], check=False)
        else:
            subprocess.run(["git", "clone", "-q", "--depth", "1", s.depot + ".git", str(s.dossier)], check=True)
        rev = subprocess.run(["git", "-C", str(s.dossier), "log", "-1", "--format=%H %cs"], capture_output=True,
                             text=True, check=False).stdout.strip()
        print(f"{s.nom:9s} {s.depot}  {rev}  ({len(lister(s))} fichiers retenus)")


def lister(s: Source) -> list[tuple[str, bool]]:
    """(chemin relatif, unitaire) des fichiers retenus d'une source."""
    out = []
    if not s.dossier.exists():
        return out
    for p in sorted(s.dossier.rglob("*")):
        if not p.is_file() or ".git" in p.parts or p.suffix.lower() not in EXTENSIONS:
            continue
        rel = p.relative_to(s.dossier).as_posix()
        if not any(fnmatch.fnmatch(rel, m) for m in s.inclure):
            continue
        if any(fnmatch.fnmatch(rel, m) for m in s.exclure):
            continue
        out.append((rel, any(fnmatch.fnmatch(rel, m) for m in s.unitaires)))
    return out


# --- vérité de terrain : lecteur XPath indépendant ------------------------------------------------------------


def _L(*noms: str) -> str:
    return "/".join(f"*[local-name()='{n}']" for n in noms)


def _t(el: Any) -> str | None:
    if el is None:
        return None
    s = (el if isinstance(el, str) else "".join(el.itertext())).strip()
    return s or None


def _un(base: Any, xp: str) -> str | None:
    r = base.xpath(xp)
    return _t(r[0]) if r else None


def _dec(s: str | None) -> Decimal | None:
    if s is None:
        return None
    try:
        return Decimal(s.strip())
    except InvalidOperation:
        return None


def _date(s: str | None) -> str | None:
    if not s:
        return None
    s = s.strip()
    if len(s) == 8 and s.isdigit():
        return f"{s[:4]}-{s[4:6]}-{s[6:]}"
    return s[:10] if len(s) >= 10 and s[4] == "-" else s


def _montant_devise(base: Any, xp: str, devise: str | None) -> str | None:
    """Montant dont ``currencyID`` est la devise de facture (BT-110 et non BT-111)."""
    els = base.xpath(xp)
    if not els:
        return None
    for e in els:
        if devise and e.get("currencyID") == devise:
            return _t(e)
    sans = [e for e in els if not e.get("currencyID")]
    return _t(sans[0] if sans else els[0])


def profil_depuis_guideline(g: str | None, syntaxe: str) -> str:
    if syntaxe == "zf1":
        niveau = (g or "").rsplit(":", 1)[-1].upper() or "?"
        return f"ZUGFeRD1-{niveau}"
    gl = (g or "").lower()
    if "xrechnung" in gl or "xeinkauf" in gl:
        return "XRechnung"
    if "minimum" in gl:
        return "MINIMUM"
    if "basicwl" in gl:
        return "BASIC WL"
    if "basic" in gl:
        return "BASIC"
    if "extended" in gl:
        return "EXTENDED"
    if "peppol" in gl:
        return "PEPPOL BIS 3"
    if "en16931" in gl:
        return "EN16931"
    return "autre"


def verite(xml: bytes) -> dict[str, Any] | None:
    """Champs EN 16931 lus dans le XML, ou ``None`` si ce n'est pas une facture CII / UBL / ZUGFeRD 1."""
    from lxml import etree

    try:
        racine = etree.fromstring(xml, etree.XMLParser(resolve_entities=False, no_network=True, load_dtd=False))
    except (etree.XMLSyntaxError, ValueError):
        return None
    nom = etree.QName(racine).localname
    ns = etree.QName(racine).namespace or ""
    v: dict[str, Any] = {}
    if nom == "CrossIndustryInvoice" or (nom == "CrossIndustryDocument" and "ferd" in ns):
        zf1 = nom == "CrossIndustryDocument"
        doc = "HeaderExchangedDocument" if zf1 else "ExchangedDocument"
        ctx = "SpecifiedExchangedDocumentContext" if zf1 else "ExchangedDocumentContext"
        tr = "SpecifiedSupplyChainTradeTransaction" if zf1 else "SupplyChainTradeTransaction"
        ag = "ApplicableSupplyChainTradeAgreement" if zf1 else "ApplicableHeaderTradeAgreement"
        st = "ApplicableSupplyChainTradeSettlement" if zf1 else "ApplicableHeaderTradeSettlement"
        sm = "SpecifiedTradeSettlementMonetarySummation" if zf1 else "SpecifiedTradeSettlementHeaderMonetarySummation"
        lst = "SpecifiedSupplyChainTradeSettlement" if zf1 else "SpecifiedLineTradeSettlement"
        lsm = "SpecifiedTradeSettlementMonetarySummation" if zf1 else "SpecifiedTradeSettlementLineMonetarySummation"
        v["syntaxe"] = "zf1" if zf1 else "cii"
        v["guideline"] = _un(racine, _L(ctx, "GuidelineSpecifiedDocumentContextParameter", "ID"))
        v["numero"] = _un(racine, _L(doc, "ID"))
        v["type_code"] = _un(racine, _L(doc, "TypeCode"))
        v["date"] = _date(_un(racine, _L(doc, "IssueDateTime", "DateTimeString")))
        reg = _L(tr, st)
        devise = _un(racine, f"{reg}/{_L('InvoiceCurrencyCode')}")
        v["devise"] = devise
        som = f"{reg}/{_L(sm)}"
        v["bt109"] = _un(racine, f"{som}/{_L('TaxBasisTotalAmount')}")
        v["bt110"] = _montant_devise(racine, f"{som}/{_L('TaxTotalAmount')}", devise)
        v["bt112"] = _un(racine, f"{som}/{_L('GrandTotalAmount')}")
        v["bt113"] = _un(racine, f"{som}/{_L('TotalPrepaidAmount')}")
        v["bt114"] = _un(racine, f"{som}/{_L('RoundingAmount')}")
        v["bt115"] = _un(racine, f"{som}/{_L('DuePayableAmount')}")
        tva = f"{_L('SpecifiedTaxRegistration')}/*[local-name()='ID'][@schemeID='VA']"
        v["tva_vendeur"] = _un(racine, f"{_L(tr, ag, 'SellerTradeParty')}/{tva}")
        v["tva_acheteur"] = _un(racine, f"{_L(tr, ag, 'BuyerTradeParty')}/{tva}")
        lignes = racine.xpath(_L(tr, "IncludedSupplyChainTradeLineItem"))
        # ZUGFeRD 1.0 admet des « lignes » de texte seul (ni article ni montant) : ce ne sont pas des lignes
        # de facture (BG-25), elles ne sont pas comptées.
        lignes = [lg for lg in lignes if lg.xpath(f"{_L(lst, lsm, 'LineTotalAmount')} | {_L('SpecifiedTradeProduct')}")]
        v["lignes"] = [_un(lg, _L(lst, lsm, "LineTotalAmount")) for lg in lignes]
        v["remises_frais"] = [
            (_un(e, _L("ChargeIndicator", "Indicator")), _un(e, _L("ActualAmount")))
            for e in racine.xpath(f"{reg}/{_L('SpecifiedTradeAllowanceCharge')}")
        ] + [("true", _un(e, _L("AppliedAmount"))) for e in racine.xpath(f"{reg}/{_L('SpecifiedLogisticsServiceCharge')}")]
    elif nom in ("Invoice", "CreditNote") and "oasis" in ns:
        v["syntaxe"] = "ubl"
        v["guideline"] = _un(racine, _L("CustomizationID"))
        v["numero"] = _un(racine, _L("ID"))
        v["type_code"] = _un(racine, _L("InvoiceTypeCode") if nom == "Invoice" else _L("CreditNoteTypeCode")) or (
            "380" if nom == "Invoice" else "381")
        v["date"] = _date(_un(racine, _L("IssueDate")))
        devise = _un(racine, _L("DocumentCurrencyCode"))
        v["devise"] = devise
        lmt = _L("LegalMonetaryTotal")
        v["bt109"] = _un(racine, f"{lmt}/{_L('TaxExclusiveAmount')}")
        v["bt110"] = _montant_devise(racine, _L("TaxTotal", "TaxAmount"), devise)
        v["bt112"] = _un(racine, f"{lmt}/{_L('TaxInclusiveAmount')}")
        v["bt113"] = _un(racine, f"{lmt}/{_L('PrepaidAmount')}")
        v["bt114"] = _un(racine, f"{lmt}/{_L('PayableRoundingAmount')}")
        v["bt115"] = _un(racine, f"{lmt}/{_L('PayableAmount')}")
        tva = ("*[local-name()='Party']/*[local-name()='PartyTaxScheme']"
               "[*[local-name()='TaxScheme']/*[local-name()='ID']='VAT']/*[local-name()='CompanyID']")
        v["tva_vendeur"] = _un(racine, f"{_L('AccountingSupplierParty')}/{tva}")
        v["tva_acheteur"] = _un(racine, f"{_L('AccountingCustomerParty')}/{tva}")
        lignes = racine.xpath(_L("InvoiceLine") if nom == "Invoice" else _L("CreditNoteLine"))
        v["lignes"] = [_un(lg, _L("LineExtensionAmount")) for lg in lignes]
        v["remises_frais"] = [(_un(e, _L("ChargeIndicator")), _un(e, _L("Amount")))
                              for e in racine.xpath(_L("AllowanceCharge"))]
    else:
        return None
    v["profil"] = profil_depuis_guideline(v["guideline"], v["syntaxe"])
    return v


def xml_de_pdf(contenu: bytes) -> tuple[str | None, bytes | None]:
    """Pièce jointe XML d'un PDF (lecture indépendante de ``controldone``)."""
    try:
        from pypdf import PdfReader

        logging.getLogger("pypdf").setLevel(logging.CRITICAL)
        r = PdfReader(io.BytesIO(contenu))
        pieces = [(a.name, a.content) for a in r.attachment_list]
    except Exception:
        return None, None
    preferes = ["factur-x.xml", "zugferd-invoice.xml", "xrechnung.xml"]
    pieces.sort(key=lambda p: preferes.index(p[0].lower()) if p[0].lower() in preferes else 9)
    for nom, data in pieces:
        if nom.lower().endswith(".xml") and data and verite(data) is not None:
            return nom, data
    return None, None


# --- comparaison -----------------------------------------------------------------------------------------------

CREDIT = {"381", "261", "262", "396", "532"}
CHAMPS = ("type", "numero", "date", "devise", "bt112_total", "bt109_ht", "bt110_tva", "bt115_net", "tva_vendeur",
          "tva_acheteur", "nb_lignes", "montants_lignes", "remises_frais")


def _norm_tva(s: str | None) -> str | None:
    return "".join(c for c in s.upper() if c.isalnum()) if s else None


def attendu(gt: dict[str, Any]) -> dict[str, Any]:
    tot = _dec(gt["bt112"])
    credit = gt["type_code"] in CREDIT or (tot is not None and tot < 0)
    e: dict[str, Any] = {
        "type": "avoir" if credit else "facture",
        "numero": gt["numero"], "date": gt["date"], "devise": (gt["devise"] or "").upper() or None,
        "bt112_total": _dec(gt["bt112"]), "bt109_ht": _dec(gt["bt109"]), "bt110_tva": _dec(gt["bt110"]),
        "bt115_net": _dec(gt["bt115"]), "tva_vendeur": _norm_tva(gt["tva_vendeur"]),
        "tva_acheteur": _norm_tva(gt["tva_acheteur"]),
        "nb_lignes": len(gt["lignes"]),
        "montants_lignes": sorted(abs(d) for d in (_dec(x) for x in gt["lignes"]) if d is not None),
        "remises_frais": sorted(abs(d) for d in (_dec(m) for _c, m in gt["remises_frais"]) if d is not None),
    }
    return e


def _val(v: Any) -> Any:
    return None if v is None else v.valeur


def obtenu(doc: Any) -> dict[str, Any]:
    """Valeurs produites par le pipeline, ramenées aux mêmes clés (``n/a`` : champ absent du modèle)."""
    t = doc.type.value
    c = doc.champs
    o: dict[str, Any] = {"type": {"facture_commerciale": "facture", "facture_transitaire": "facture"}.get(t, t)}
    if c is None:
        return o
    na = "n/a"
    o["numero"] = _val(getattr(c, "numero", None))
    o["date"] = _val(getattr(c, "date", None))
    o["devise"] = _val(getattr(c, "devise", None))
    if t == "facture_commerciale":
        o["bt112_total"] = _val(c.total_facture)
        o["bt109_ht"] = o["bt110_tva"] = o["bt115_net"] = na
        o["tva_vendeur"], o["tva_acheteur"] = _val(c.vendeur.tva), _val(c.acheteur.tva)
        o["montants_lignes"] = [_val(lg.montant_ligne) for lg in c.lignes]
        o["remises_frais"] = [_val(s.montant) for s in c.sous_totaux]
    elif t == "facture_transitaire":
        o["bt112_total"], o["bt109_ht"], o["bt110_tva"] = _val(c.total_ttc), _val(c.total_ht), _val(c.total_tva)
        o["bt115_net"] = _val(c.net_a_payer)
        o["tva_vendeur"], o["tva_acheteur"] = _val(c.emetteur.tva), _val(c.client_facture.tva)
        o["montants_lignes"] = [_val(lg.montant_ht) for lg in c.lignes]
        o["remises_frais"] = na
    elif t == "avoir":
        o["bt112_total"], o["bt109_ht"], o["bt110_tva"] = (_val(c.total_credite_ttc), _val(c.total_credite_ht),
                                                          _val(c.total_tva))
        o["bt115_net"] = na
        o["tva_vendeur"], o["tva_acheteur"] = _val(c.emetteur.tva), na
        o["montants_lignes"] = [_val(lg.montant_ht) for lg in c.lignes]
        o["remises_frais"] = na
    else:
        return o
    o["nb_lignes"] = len(c.lignes)
    o["montants_lignes"] = sorted(d for d in (_dec(x) for x in o["montants_lignes"]) if d is not None)
    if o["remises_frais"] != na:
        o["remises_frais"] = sorted(d for d in (_dec(x) for x in o["remises_frais"]) if d is not None)
    return o


def comparer(att: dict[str, Any], obt: dict[str, Any]) -> dict[str, str]:
    """Par champ : ``ok``, ``faux``, ``manquant`` (attendu non produit), ``n/a`` (rien d'attendu ou hors modèle)."""
    r = {}
    for k in CHAMPS:
        a, o = att.get(k), obt.get(k)
        if o == "n/a" or a is None or (k in ("montants_lignes", "remises_frais") and not a):
            r[k] = "n/a"
            continue
        if o is None:
            r[k] = "manquant"
            continue
        if k.startswith("bt"):
            ok = _dec(o) is not None and _dec(o) == abs(a)
        elif k in ("tva_vendeur", "tva_acheteur"):
            ok = _norm_tva(o) == a
        else:
            ok = o == a
        r[k] = "ok" if ok else "faux"
    return r


# --- exécution d'un fichier ---------------------------------------------------------------------------------


class _Capture(logging.Handler):
    def __init__(self) -> None:
        super().__init__(logging.WARNING)
        self.erreurs: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        msg = record.getMessage()
        if "en_erreur" in msg or "erreur_interne" in msg:
            exc = next((p.split("=", 1)[1] for p in msg.split() if p.startswith("exception=")), "?")
            self.erreurs.append(f"{msg.split()[0]}:{exc}")


def traiter_fichier(tache: tuple[str, str, bool, str | None]) -> dict[str, Any]:
    source, rel, unitaire, sortie_diag = tache
    chemin = DOSSIER / source / rel
    contenu = chemin.read_bytes()
    res: dict[str, Any] = {"source": source, "fichier": rel, "unitaire": unitaire, "taille": len(contenu),
                           "exceptions": [], "temps": {}}
    # vérité de terrain
    if chemin.suffix.lower() == ".pdf":
        piece, xml = xml_de_pdf(contenu)
        res["piece_jointe"] = piece
    else:
        xml = contenu
    gt = verite(xml) if xml else None
    if gt is not None:
        res["verite"] = {k: (str(v) if isinstance(v, Decimal) else v) for k, v in gt.items()}
        res["profil"] = gt["profil"]
    res["format"] = "pdf" if chemin.suffix.lower() == ".pdf" else "xml"

    from controldone.extract.base import ExtractionContext
    from controldone.ids import IdGenerator
    from controldone.ingest.structure import ExtracteurFactureXML, analyser_contenu_structure
    from controldone.model import Document
    from controldone.model.enums import TypeDocument
    from controldone.pipeline import OptionsPipeline, controler_lot, preparer_lot
    from controldone.referentiel_io import charger_profil_client

    capture = _Capture()
    logging.getLogger().addHandler(capture)
    try:
        # 1. extracteur structure appelé directement (une exception ici serait avalée par le pipeline)
        t0 = time.perf_counter()
        try:
            from controldone.ingest.sniff import detecter_type

            mime = detecter_type(contenu, chemin.name)
            res["mime"] = mime
            # au-delà de la limite de réception (§20.3), le pipeline ne lit jamais le fichier
            info = analyser_contenu_structure(contenu, mime) if len(contenu) <= 50 * 1024 * 1024 else None
            res["structure"] = None if info is None else {"format": info.format, "type": info.type.value,
                                                          "schema_valide": info.schema_valide,
                                                          "motif": getattr(info, "motif", None)}
            if info is not None and info.type in (TypeDocument.facture_commerciale, TypeDocument.avoir,
                                                  TypeDocument.facture_transitaire):
                doc = Document(type=info.type, pages=[])
                ExtracteurFactureXML().extract(doc, [], ExtractionContext(
                    contenu_fichier=contenu, type_mime=mime, ids=IdGenerator.deterministe(1)))
        except Exception as e:
            res["exceptions"].append(f"structure:{type(e).__name__}")
            res["trace"] = traceback.format_exc(limit=6)
        res["temps"]["structure"] = round(time.perf_counter() - t0, 3)
        # 2. pipeline (réception -> pages -> classement -> extraction -> regroupement)
        t0 = time.perf_counter()
        options = OptionsPipeline(seed=1, llm=False)
        profil = charger_profil_client(None)
        prepare = None
        try:
            prepare = preparer_lot(chemin, profil, options=options)
        except Exception as e:
            res["exceptions"].append(f"pipeline:{type(e).__name__}")
            res["trace"] = traceback.format_exc(limit=8)
        res["temps"]["preparation"] = round(time.perf_counter() - t0, 3)
        if prepare is not None:
            res["fichiers_refuses"] = [f.motif_refus for f in prepare.fichiers.values() if f.motif_refus]
            res["non_lus"] = [n.motif for n in prepare.non_lus]
            res["pages"] = sum(len(p) for p in prepare.pages.values())
            docs = list(prepare.documents.values())
            res["documents"] = [{"type": d.type.value, "sous_type": d.sous_type, "confiance": d.confiance_classement,
                                 "motif": d.motif_non_exploitable} for d in docs]
            factures = [d for d in docs if d.type.value in ("facture_commerciale", "facture_transitaire", "avoir")]
            if factures:
                d = factures[0]
                methodes = Counter(v.methode.value for v in (d.champs.iter_valeurs() if d.champs else []))
                res["methodes"] = dict(methodes)
                confs = [v.confiance for v in (d.champs.iter_valeurs() if d.champs else []) if v.valeur is not None]
                res["confiance_min"] = min(confs) if confs else None
                if gt is not None:
                    att = attendu(gt)
                    obt = obtenu(d)
                    res["comparaison"] = comparer(att, obt)
                    res["obtenu"] = {k: (v if isinstance(v, str) or v is None else str(v)) for k, v in obt.items()}
                    res["ecarts"] = {k: [str(att.get(k)), str(obt.get(k))] for k, s in res["comparaison"].items()
                                     if s in ("faux", "manquant")}
            elif gt is not None:
                autre = docs[0].type.value if docs else "aucun"
                res["comparaison"] = comparer(attendu(gt), {"type": autre})
                res["ecarts"] = {"type": [attendu(gt)["type"], autre]}
            # 3. diagnostic : contrôles + rapport (équivalent de ``controldone diagnostic <fichier>``)
            t0 = time.perf_counter()
            try:
                resultats = controler_lot(prepare, options=options)
                res["dossiers"] = len(resultats)
                res["constats"] = sorted(f"{c.controle_id}:{c.niveau.value}" for r in resultats for c in r.constats)
                if sortie_diag:
                    from controldone.rapport import generer_rapport

                    out = Path(sortie_diag) / source / rel.replace("/", "__")
                    generer_rapport(resultats, profil, out, non_lus=prepare.non_lus)
            except Exception as e:
                res["exceptions"].append(f"diagnostic:{type(e).__name__}")
                res["trace"] = traceback.format_exc(limit=8)
            res["temps"]["diagnostic"] = round(time.perf_counter() - t0, 3)
    finally:
        logging.getLogger().removeHandler(capture)
    res["erreurs_isolees"] = capture.erreurs
    return res


# --- rapport -----------------------------------------------------------------------------------------------


def _pct(n: int, d: int) -> str:
    return f"{n}/{d} ({100 * n / d:.1f} %)" if d else "-"


def resume(resultats: list[dict[str, Any]]) -> str:
    lignes: list[str] = []
    w = lignes.append
    n = len(resultats)
    w(f"Fichiers : {n} (dont unitaires {sum(r['unitaire'] for r in resultats)}), "
      f"avec vérité XML : {sum('verite' in r for r in resultats)}")
    exc = Counter(e for r in resultats for e in r["exceptions"])
    iso = Counter(e for r in resultats for e in r.get("erreurs_isolees", []))
    w(f"Exceptions non gérées : {sum(exc.values())} {dict(exc)}")
    w(f"Erreurs isolées par le pipeline (journal) : {sum(iso.values())} {dict(iso)}")
    w(f"Refus à la réception : {dict(Counter(m for r in resultats for m in r.get('fichiers_refuses', [])))}")
    w(f"Non lus : {dict(Counter(m for r in resultats for m in r.get('non_lus', [])))}")
    w(f"Format structuré reconnu : {dict(Counter((r.get('structure') or {}).get('format', '-') for r in resultats))}")
    w(f"Classement (premier document) : "
      f"{dict(Counter((r.get('documents') or [{'type': 'aucun'}])[0]['type'] for r in resultats))}")
    w(f"Classement (fichiers avec vérité) : "
      f"{dict(Counter((r.get('documents') or [{'type': 'aucun'}])[0]['type'] for r in resultats if 'verite' in r))}")
    w(f"Schéma valide (structure) : "
      f"{dict(Counter(str((r.get('structure') or {}).get('schema_valide')) for r in resultats if r.get('structure')))}")
    temps = [r["temps"].get("preparation", 0) + r["temps"].get("diagnostic", 0) for r in resultats]
    if temps:
        ts = sorted(temps)
        w(f"Temps par fichier (préparation + diagnostic) : médiane {ts[len(ts) // 2]:.2f} s, "
          f"p95 {ts[int(len(ts) * 0.95) - 1]:.2f} s, max {ts[-1]:.2f} s, total {sum(ts):.0f} s")
    par_fmt = defaultdict(list)
    for r in resultats:
        par_fmt[r["format"]].append(r["temps"].get("preparation", 0))
    w("Temps de préparation médian : " + ", ".join(
        f"{k} {sorted(v)[len(v) // 2]:.2f} s" for k, v in sorted(par_fmt.items())))
    # exactitude
    comp = [r for r in resultats if "comparaison" in r]

    def table(groupe) -> None:
        groupes: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for r in comp:
            groupes[groupe(r)].append(r)
        w("")
        w("| groupe | n | " + " | ".join(CHAMPS) + " |")
        w("|---|---|" + "---|" * len(CHAMPS))
        for g in sorted(groupes):
            cellules = []
            for k in CHAMPS:
                st = [r["comparaison"][k] for r in groupes[g]]
                ok, tot = st.count("ok"), sum(1 for s in st if s != "n/a")
                cellules.append(f"{ok}/{tot}" if tot else "-")
            w(f"| {g} | {len(groupes[g])} | " + " | ".join(cellules) + " |")

    w("")
    w("Exactitude globale par champ (ok / attendus) :")
    for k in CHAMPS:
        st = [r["comparaison"][k] for r in comp]
        tot = sum(1 for s in st if s != "n/a")
        w(f"  {k:16s} {_pct(st.count('ok'), tot):>22s}   manquant {st.count('manquant'):3d}  faux {st.count('faux'):3d}")
    w("\nPar source :")
    table(lambda r: r["source"])
    w("\nPar profil :")
    table(lambda r: r.get("profil", "?"))
    w("\nPar syntaxe / contenant :")
    table(lambda r: f"{r['verite']['syntaxe']}/{r['format']}")
    return "\n".join(lignes)


def run(args: argparse.Namespace) -> int:
    sources = [s for s in SOURCES if not args.source or s.nom in args.source]
    taches = []
    for s in sources:
        for rel, unitaire in lister(s):
            if args.filtre and args.filtre not in rel:
                continue
            if any(fnmatch.fnmatch(rel, m) for m in args.exclure or ()):
                continue
            if args.sans_unitaires and unitaire:
                continue
            taches.append((s.nom, rel, unitaire, None if args.sans_diagnostic else args.diag_out))
    if not taches:
        print("Aucun fichier : lancer d'abord `python scripts/corpus_public.py fetch`.", file=sys.stderr)
        return 2
    os.environ.setdefault("CONTROLDONE_PAGES_CACHE_DIR", str(RACINE / "var" / "cache" / "pages"))
    debut = time.perf_counter()
    if args.workers > 1:
        with ProcessPoolExecutor(args.workers) as ex:
            resultats = list(ex.map(traiter_fichier, taches, chunksize=4))
    else:
        resultats = [traiter_fichier(t) for t in taches]
    duree = time.perf_counter() - debut
    texte = resume(resultats) + f"\n\nDurée totale : {duree:.0f} s ({args.workers} processus)"
    print(texte)
    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(resultats, ensure_ascii=False, indent=1, default=str), "utf-8")
        out.with_suffix(".md").write_text(texte + "\n", "utf-8")
    if args.ecarts:
        for r in resultats:
            if r.get("ecarts") or r["exceptions"]:
                print(r["source"], r["fichier"], r.get("profil"), r["exceptions"], r.get("ecarts"))
    return 0


def compare(args: argparse.Namespace) -> int:
    avant = {(r["source"], r["fichier"]): r for r in json.loads(Path(args.avant).read_text("utf-8"))}
    apres = {(r["source"], r["fichier"]): r for r in json.loads(Path(args.apres).read_text("utf-8"))}
    print("| champ | avant | après |\n|---|---|---|")
    for k in CHAMPS:
        cel = []
        for jeu in (avant, apres):
            st = [r["comparaison"][k] for r in jeu.values() if "comparaison" in r]
            tot = sum(1 for s in st if s != "n/a")
            cel.append(_pct(st.count("ok"), tot))
        print(f"| {k} | {cel[0]} | {cel[1]} |")
    regress = [(c, k) for c, r in apres.items() if c in avant and "comparaison" in r and "comparaison" in avant[c]
               for k in CHAMPS if avant[c]["comparaison"][k] == "ok" and r["comparaison"][k] in ("faux", "manquant")]
    hors_modele = sum(1 for c, r in apres.items() if c in avant and "comparaison" in r and "comparaison" in avant[c]
                      for k in CHAMPS if avant[c]["comparaison"][k] == "ok" and r["comparaison"][k] == "n/a")
    print(f"\nRégressions (ok avant, faux ou manquant après) : {len(regress)} ; "
          f"devenus hors modèle (n/a, ex. facture à total négatif reclassée avoir) : {hors_modele}")
    for c, k in regress[:40]:
        print("  ", c, k)
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sous = p.add_subparsers(dest="cmd", required=True)
    f = sous.add_parser("fetch", help="cloner / mettre à jour les dépôts dans var/corpus_public/")
    f.add_argument("--source", action="append")
    r = sous.add_parser("run", help="passer chaque fichier dans le pipeline et mesurer l'exactitude")
    r.add_argument("--source", action="append")
    r.add_argument("--filtre")
    r.add_argument("--exclure", action="append", help="motif fnmatch de fichiers à ne pas traiter")
    r.add_argument("--workers", type=int, default=3)
    r.add_argument("--out", default=str(DOSSIER / "rapport" / "resultats.json"))
    r.add_argument("--diag-out", default=str(Path(tempfile.gettempdir()) / "corpus_public_diag"))
    r.add_argument("--sans-diagnostic", action="store_true", help="contrôles exécutés, rapport non écrit")
    r.add_argument("--sans-unitaires", action="store_true")
    r.add_argument("--ecarts", action="store_true", help="afficher les écarts fichier par fichier")
    c = sous.add_parser("compare", help="tableau avant / après de deux résultats JSON")
    c.add_argument("avant")
    c.add_argument("apres")
    args = p.parse_args(argv)
    if args.cmd == "fetch":
        fetch([s for s in SOURCES if not args.source or s.nom in args.source])
        return 0
    if args.cmd == "compare":
        return compare(args)
    return run(args)


if __name__ == "__main__":
    sys.exit(main())
