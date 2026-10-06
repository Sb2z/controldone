"""Fiche de correspondance **déduite** d'un export XML de déclaration de format inconnu (SPEC §5.3.6, D-2401).

Un export XML de déclaration dont aucune fiche ``config/mappings/*.yaml`` ne reconnaît la racine était jusqu'ici
« inconnu ». Les exports de logiciels de dédouanement nomment pourtant leurs éléments avec le vocabulaire de la
déclaration (« MRN », « AcceptanceDate », « CommodityCode », « StatisticalValue », « Duty/Base/Rate/Amount »…).
Ce module en déduit une fiche **en mémoire** (même forme qu'une fiche écrite à la main), à partir des seuls noms
d'éléments et d'attributs comparés à des listes fermées de synonymes (fr / en / de / it / es), puis la lecture
suit le chemin habituel (``structure._champs_declaration``).

Règles :

- **articles** : éléments répétés (même chemin) qui portent un code marchandise ; **taxations** : éléments qui
  portent un code de taxe et un montant (rattachés à l'article par un attribut « item / article / position » ou par
  l'article ancêtre) ; **documents** : éléments qui portent un code de document (« N380 ») et une référence ;
- **en-tête** : feuilles et attributs hors de ces groupes ; une partie (importateur, déclarant, représentant) est
  l'élément parent du nom, du numéro de TVA, de l'EORI ;
- la catégorie d'une taxe vient du libellé imprimé dans le fichier (« Flat-rate duty (low value) », « Import
  VAT ») quand il existe, sinon de la table usuelle des codes ; les modes de paiement suivent la nomenclature de
  l'Union (A comptant, E différé, G autoliquidé…).

Une fiche n'est déduite que si le fichier porte un MRN et au moins un article ou une taxation : un XML quelconque
reste inconnu. Les valeurs lues ont la confiance ``CONFIANCE_DEDUITE`` si les recoupements internes du fichier
tiennent (somme des taxes = total, base × taux = montant, nombre d'articles), ``CONFIANCE_DEDUITE_DOUTEUSE``
sinon : une correspondance déduite n'a pas la certitude d'une fiche écrite.

Le contenu du fichier est une **donnée** : seuls des noms d'éléments sont comparés à des listes fermées ; aucun
texte n'est interprété comme une consigne.
"""

from __future__ import annotations

import re
from collections import defaultdict
from decimal import Decimal, InvalidOperation
from typing import Any

from lxml import etree

from controldone.model.champs import ChampsDeclaration
from controldone.normalize.text import sans_accents

__all__ = [
    "CONFIANCE_DEDUITE",
    "CONFIANCE_DEDUITE_DOUTEUSE",
    "FORMAT_DEDUIT",
    "coherence_declaration",
    "correspondance_confirmee",
    "deduire_fiche_declaration",
]

FORMAT_DEDUIT = "xml_declaration_deduit"
#: Confiance des valeurs lues par une fiche déduite dont les recoupements internes tiennent.
CONFIANCE_DEDUITE = 0.95
#: … dont un recoupement échoue (ou qu'aucun recoupement ne confirme) : jamais une valeur d'écart certain.
CONFIANCE_DEDUITE_DOUTEUSE = 0.85


def _cle(nom: str) -> str:
    return re.sub(r"[^a-z0-9]", "", sans_accents(nom).lower())


def _local(tag: Any) -> str:
    return etree.QName(tag).localname if isinstance(tag, str) else ""


def _ens(*noms: str) -> frozenset[str]:
    return frozenset(_cle(n) for n in noms)


# --- vocabulaire (noms d'éléments ou d'attributs, comparés après normalisation) ---------------------------------

_ENTETE: dict[str, frozenset[str]] = {
    "mrn": _ens("MRN", "MovementReferenceNumber", "MasterReferenceNumber"),
    "lrn": _ens("LRN", "LocalReferenceNumber", "LocalReference", "ReferenceLocale"),
    "version": _ens("Version", "VersionNumber", "Rang", "AmendmentNumber"),
    "date_acceptation": _ens(
        "AcceptanceDate",
        "DateOfAcceptance",
        "AcceptedOn",
        "DateAcceptation",
        "AccepteeLe",
        "Annahmedatum",
        "DataAccettazione",
        "FechaAdmision",
        "FechaAceptacion",
    ),
    "devise_facture": _ens(
        "InvoiceCurrency",
        "CurrencyOfInvoice",
        "MonnaieFacture",
        "MonnaieFacturation",
        "DeviseFacture",
        "Rechnungswaehrung",
        "Rechnungswahrung",
        "ValutaFattura",
        "MonedaFactura",
    ),
    "montant_total_facture": _ens(
        "InvoiceTotal",
        "TotalInvoiceAmount",
        "TotalAmountInvoiced",
        "InvoiceAmount",
        "MontantTotalFacture",
        "TotalFacture",
        "MontantFacture",
        "Rechnungsbetrag",
        "ImportoFattura",
        "ImporteFactura",
    ),
    "taux_change": _ens(
        "ExchangeRate",
        "RateOfExchange",
        "TauxChange",
        "TauxDeChange",
        "Wechselkurs",
        "TassoCambio",
        "TipoCambio",
    ),
    "masse_brute_totale": _ens(
        "GrossMass",
        "TotalGrossMass",
        "GrossWeight",
        "TotalGrossWeight",
        "MasseBrute",
        "MasseBruteTotale",
        "PoidsBrut",
        "Rohmasse",
        "MassaLorda",
        "MasaBruta",
    ),
    "nombre_colis_total": _ens(
        "Packages",
        "TotalPackages",
        "NumberOfPackages",
        "Colis",
        "NombreColis",
        "Packstuecke",
        "Packstucke",
        "Colli",
        "Bultos",
    ),
    "nombre_articles": _ens(
        "ItemCount",
        "NumberOfItems",
        "TotalItems",
        "NombreArticles",
        "NombrePositions",
        "AnzahlPositionen",
        "NumeroArticoli",
        "NumeroPartidas",
    ),
    "pays_expedition": _ens(
        "DispatchCountry",
        "CountryOfDispatch",
        "CountryOfExport",
        "PaysExpedition",
        "PaysProvenance",
        "Versendungsland",
        "PaeseSpedizione",
        "PaisExpedicion",
    ),
    "pays_destination": _ens("DestinationCountry", "CountryOfDestination", "PaysDestination"),
    "total_droits_taxes": _ens(
        "TotalDutiesAndTaxes",
        "TotalDutiesTaxes",
        "TotalDroitsEtTaxes",
        "TotalDroitsTaxes",
        "SummeAbgaben",
        "TotaleDaziImposte",
        "TotalDerechosImpuestos",
    ),
    "total_a_payer": _ens(
        "TotalPayable",
        "TotalToPay",
        "AmountPayable",
        "TotalAPayer",
        "TotalAAcquitter",
        "ZuZahlen",
        "TotaleDaPagare",
        "TotalAPagar",
    ),
}
#: Conditions de livraison : élément dont le texte ou l'attribut « code » est l'Incoterm, l'attribut « place » le lieu.
_LIVRAISON = _ens(
    "DeliveryTerms",
    "TermsOfDelivery",
    "Incoterm",
    "Incoterms",
    "ConditionsLivraison",
    "Livraison",
    "Lieferbedingungen",
    "CondizioniConsegna",
    "CondicionesEntrega",
)
_ATTR_INCOTERM = _ens("code", "incoterm", "terms")
_ATTR_LIEU = _ens("place", "lieu", "location", "ort", "luogo", "lugar")
#: Sens du taux de change : attribut de l'élément du taux.
_ATTR_SENS = _ens("basis", "expression", "direction", "sens", "quotation", "base")

_PARTIES: dict[str, frozenset[str]] = {
    "importateur": _ens(
        "Importer",
        "Importateur",
        "Consignee",
        "Destinataire",
        "Einfuehrer",
        "Einfuhrer",
        "Importatore",
        "Importador",
    ),
    "declarant": _ens("Declarant", "Anmelder", "Dichiarante", "Declarante"),
    "representant": _ens(
        "FiscalRepresentative",
        "RepresentantFiscal",
        "Representative",
        "Representant",
        "TaxRepresentative",
        "Fiskalvertreter",
        "RappresentanteFiscale",
        "RepresentanteFiscal",
    ),
}
_PARTIE_CHAMPS: dict[str, frozenset[str]] = {
    "nom": _ens("Name", "Nom", "RaisonSociale", "CompanyName", "Firma", "Denominazione", "Nombre"),
    "tva": _ens(
        "VATNumber",
        "VAT",
        "VATId",
        "VATNo",
        "TVA",
        "NumeroTVA",
        "TVAIntracom",
        "UStIdNr",
        "PartitaIVA",
        "NIF",
    ),
    "eori": _ens("EORI", "EORINumber", "NumeroEORI"),
}

_ARTICLE: dict[str, frozenset[str]] = {
    "code_marchandise": _ens(
        "CommodityCode",
        "HSCode",
        "CNCode",
        "CodeNC",
        "TaricCode",
        "GoodsCode",
        "CodeMarchandise",
        "Nomenclature",
        "Warennummer",
        "CodiceMerce",
        "CodigoMercancia",
    ),
    "description": _ens(
        "Description",
        "GoodsDescription",
        "Designation",
        "Libelle",
        "Warenbezeichnung",
        "Descrizione",
        "Descripcion",
    ),
    "pays_origine": _ens(
        "Origin",
        "CountryOfOrigin",
        "OriginCountry",
        "Origine",
        "PaysOrigine",
        "Ursprungsland",
        "PaeseOrigine",
        "PaisOrigen",
    ),
    "code_preference": _ens(
        "Preference", "PreferenceCode", "Preference", "Praeferenz", "Preferenza", "Preferencia"
    ),
    "regime": _ens("Procedure", "ProcedureCode", "Regime", "Verfahren", "Regimen"),
    "montant_facture_article": _ens(
        "InvoicedAmount",
        "InvoiceAmount",
        "AmountInvoiced",
        "ItemPrice",
        "MontantFacture",
        "PrixArticle",
        "Rechnungsbetrag",
        "ImportoFatturato",
        "ImporteFacturado",
    ),
    "valeur_statistique": _ens(
        "StatisticalValue", "ValeurStatistique", "StatistischerWert", "ValoreStatistico", "ValorEstadistico"
    ),
    "masse_nette": _ens(
        "NetMass", "NetWeight", "MasseNette", "PoidsNet", "Eigenmasse", "MassaNetta", "MasaNeta"
    ),
    "masse_brute": _ens(
        "GrossMass", "GrossWeight", "MasseBrute", "PoidsBrut", "Rohmasse", "MassaLorda", "MasaBruta"
    ),
    "quantite_unite_supplementaire": _ens(
        "SupplementaryUnits",
        "SupplementaryQuantity",
        "SupplementaryUnit",
        "UnitesSupplementaires",
        "QuantiteSupplementaire",
        "BesondereMasseinheit",
        "UnitaSupplementari",
    ),
    "nombre_colis": _ens(
        "Packages", "NumberOfPackages", "Colis", "NombreColis", "Packstuecke", "Colli", "Bultos"
    ),
}
#: Numéro d'article : attribut ou élément enfant.
_NUMERO_ARTICLE = _ens(
    "seq",
    "number",
    "no",
    "num",
    "numero",
    "rang",
    "position",
    "itemnumber",
    "itemno",
    "sequence",
    "sequencenumber",
    "pos",
    "line",
    "linenumber",
)

_TAXE: dict[str, frozenset[str]] = {
    "type_taxe": _ens("type", "code", "TaxType", "DutyType", "TaxCode", "CodeTaxe", "TypeTaxe", "Abgabenart"),
    "base_montant": _ens(
        "Base",
        "TaxBase",
        "Assiette",
        "BaseImposition",
        "Bemessungsgrundlage",
        "BaseImponibile",
        "BaseImponible",
        "BaseAmount",
    ),
    "base_quantite": _ens("BaseQuantity", "QuantityBase", "AssietteQuantite", "BaseQuantite"),
    "taux": _ens("Rate", "Taux", "TaxRate", "DutyRate", "Quotite", "Satz", "Aliquota", "Tipo"),
    "montant": _ens("Amount", "Montant", "TaxAmount", "DutyAmount", "Betrag", "Importo", "Importe"),
    "montant_a_payer": _ens(
        "Payable", "AmountPayable", "APayer", "Exigible", "ZuZahlen", "DaPagare", "APagar"
    ),
    "mode_paiement": _ens(
        "Payment",
        "PaymentMethod",
        "MethodOfPayment",
        "MP",
        "ModePaiement",
        "Paiement",
        "Zahlungsart",
        "Pagamento",
        "Pago",
    ),
}
#: Rattachement d'une taxation à un article (attribut de l'élément de la taxe).
_ATTR_ARTICLE_TAXE = _ens(
    "item", "article", "position", "itemseq", "itemnumber", "pos", "line", "positionnumber"
)
_LIBELLE_TAXE = _ens("label", "libelle", "description", "name", "bezeichnung")
_ATTR_UNITE = _ens("unit", "unite", "unitcode", "uom", "einheit", "unita", "unidad")
_ATTR_DEVISE = _ens("currency", "currencyid", "devise", "monnaie", "waehrung", "valuta", "moneda")

_DOC_CODE = _ens("type", "code", "typecode", "documenttype", "codedocument")
_DOC_REF = _ens("reference", "ref", "number", "numero", "id", "referencedocument")

_CODE_TAXE_RE = re.compile(r"^(?:[A-Z]\d{2}|[A-Z]{3})$")
_CODE_DOC_RE = re.compile(r"^(?:[NCYUX]\d{3}|1008|FR7)$")
_MRN_RE = re.compile(r"^\d{2}[A-Z]{2}[A-Z0-9]{14}$")
_CODE_NC_RE = re.compile(r"^\d{8}(?:\d{2})?$")

#: Catégorie d'après le libellé imprimé (ordre significatif) — mêmes notions que l'extracteur des PDF.
_CATEGORIES_LIBELLE: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(r"forfait|petits? envois?|faible valeur|low.?value|flat.?rate|pauschal"),
        "forfait_petits_envois",
    ),
    (re.compile(r"\b(?:tva|vat|iva|btw|mwst|einfuhrumsatzsteuer|import sales tax)\b"), "tva"),
    (
        re.compile(
            r"dumping|compensat|countervail|specifique|specific|accise|excise|additionnel|additional|autre"
        ),
        "autre_taxe",
    ),
    (re.compile(r"droits?( de douane)?\b|customs dut|\bdut(?:y|ies)\b|\bzoll\b|\bdazi|\barancel"), "droit"),
)
#: Modes de paiement (lettres de la nomenclature de l'Union).
_PAIEMENT_UE = {
    "A": "comptant",
    "B": "comptant",
    "C": "comptant",
    "D": "comptant",
    "H": "comptant",
    "E": "differe",
    "G": "autoliquide",
}


# --- outils ---------------------------------------------------------------------------------------------------


class _Arbre:
    def __init__(self, racine: etree._Element) -> None:
        self.racine = racine
        self.ns = etree.QName(racine.tag).namespace
        self.prefixe = "d:" if self.ns else ""

    def nom(self, el: etree._Element) -> str:
        return f"{self.prefixe}{_local(el.tag)}"

    def chemin(self, el: etree._Element, depuis: etree._Element | None = None) -> str:
        """Chemin XPath (relatif à ``depuis``, la racine par défaut) : suite de noms locaux préfixés."""
        depuis = self.racine if depuis is None else depuis
        parties = []
        courant = el
        while courant is not None and courant is not depuis:
            parties.append(self.nom(courant))
            courant = courant.getparent()
        if courant is None:
            raise ValueError("élément hors de la base")
        return "/".join(reversed(parties)) or "."

    def signature(self, el: etree._Element) -> tuple[str, ...]:
        return (*(_local(a.tag) for a in reversed(list(el.iterancestors()))), _local(el.tag))


def _texte(el: etree._Element) -> str:
    return "".join(el.itertext()).strip() if len(el) == 0 else (el.text or "").strip()


def _enfants(el: etree._Element) -> list[etree._Element]:
    return [x for x in el if isinstance(x.tag, str)]


def _attr(el: etree._Element, cles: frozenset[str]) -> str | None:
    for a in el.attrib:
        if _cle(_local(a)) in cles:
            return _local(a)
    return None


def _enfant(el: etree._Element, cles: frozenset[str]) -> etree._Element | None:
    for x in _enfants(el):
        if _cle(_local(x.tag)) in cles:
            return x
    return None


def _groupes(arbre: _Arbre, critere) -> list[etree._Element]:
    """Éléments qui satisfont ``critere`` ; tous ceux qui partagent la signature (chemin) du premier."""
    par_sig: dict[tuple[str, ...], list[etree._Element]] = defaultdict(list)
    for el in arbre.racine.iter():
        if isinstance(el.tag, str) and el is not arbre.racine and critere(el):
            par_sig[arbre.signature(el)].append(el)
    if not par_sig:
        return []
    sig = max(par_sig, key=lambda s: (len(par_sig[s]), -len(s)))
    # tous les éléments de cette signature (y compris ceux qui ne portent pas tous les champs)
    return [el for el in arbre.racine.iter() if isinstance(el.tag, str) and arbre.signature(el) == sig]


def _est_article(el: etree._Element) -> bool:
    code = _enfant(el, _ARTICLE["code_marchandise"])
    return code is not None and bool(_CODE_NC_RE.match(re.sub(r"[ .]", "", _texte(code))))


def _code_taxe_de(el: etree._Element) -> tuple[str, str] | None:
    """(« @attr » ou « Enfant », valeur) du code de taxe d'un élément."""
    a = _attr(el, _TAXE["type_taxe"])
    if a is not None and _CODE_TAXE_RE.match((el.get(a) or "").strip()):
        return f"@{a}", el.get(a).strip()
    x = _enfant(el, _TAXE["type_taxe"])
    if x is not None and _CODE_TAXE_RE.match(_texte(x)):
        return _local(x.tag), _texte(x)
    return None


def _est_taxe(el: etree._Element) -> bool:
    return (
        _code_taxe_de(el) is not None
        and _enfant(el, _TAXE["montant"]) is not None
        and (
            _enfant(el, _TAXE["taux"]) is not None
            or _enfant(el, _TAXE["base_montant"]) is not None
            or _enfant(el, _TAXE["base_quantite"]) is not None
        )
    )


#: Élément d'un total par code de taxe (« TypeTotal », « TotalParType », « total », « Summe ») : D-3101.
_TOTAL_RE = re.compile(r"total|summe|somma|suma|recap")
_NOMBRE_RE = re.compile(r"^-?\d+(?:[.,]\d+)?$")


def _est_total_code(el: etree._Element, codes: set[str]) -> bool:
    """Feuille qui porte un code de taxe des taxations lues (attribut) et un seul nombre, sous un nom de total :
    total imprimé du code (D-3101). Jamais une ligne de taxation."""
    if len(_enfants(el)) or not _TOTAL_RE.search(_cle(_local(el.tag))):
        return False
    a = _attr(el, _TAXE["type_taxe"])
    return (
        a is not None
        and (el.get(a) or "").strip() in codes
        and bool(_NOMBRE_RE.match(_texte(el).replace(" ", "")))
    )


def _est_document(el: etree._Element) -> bool:
    if _est_taxe(el) or _est_article(el):
        return False
    a = _attr(el, _DOC_CODE)
    if (
        a is not None
        and _CODE_DOC_RE.match((el.get(a) or "").strip())
        and (_texte(el) or _enfant(el, _DOC_REF) is not None or _attr(el, _DOC_REF))
    ):
        return True
    x = _enfant(el, _DOC_CODE)
    return x is not None and bool(_CODE_DOC_RE.match(_texte(x))) and _enfant(el, _DOC_REF) is not None


def _dans(el: etree._Element, ens: set[etree._Element] | frozenset[etree._Element]) -> bool:
    """``el`` est dans un groupe ou sous l'un de ses éléments. ``ens`` est un **ensemble** construit une fois par
    l'appelant : le reconstruire à chaque appel rendait la déduction quadratique (REV2-01, déni de service par un
    XML de quelques Mo)."""
    return el in ens or any(a in ens for a in el.iterancestors())


def _valeurs_sens(brut: str) -> dict[str, str]:
    """``valeurs`` du sens du taux d'après le libellé de l'attribut (« CURRENCY_PER_EUR » -> devise_par_eur)."""
    s = _cle(brut)
    if s.startswith("eur"):
        return {brut: "eur_par_devise"}
    if s.endswith(("eur", "euro")):
        return {brut: "devise_par_eur"}
    return {}


def _categorie_libelle(libelle: str) -> str | None:
    t = sans_accents(libelle).lower()
    for rx, cat in _CATEGORIES_LIBELLE:
        if rx.search(t):
            return cat
    return None


# --- déduction --------------------------------------------------------------------------------------------------


def deduire_fiche_declaration(racine: etree._Element | None) -> dict[str, Any] | None:
    """Fiche (dictionnaire au format ``config/mappings``) déduite des noms d'éléments, ou ``None`` si le fichier
    n'a pas la forme d'une déclaration (MRN et au moins un article ou une taxation)."""
    if racine is None or not isinstance(racine.tag, str):
        return None
    arbre = _Arbre(racine)
    articles = _groupes(arbre, _est_article)
    taxes = _groupes(arbre, _est_taxe)
    documents = _groupes(arbre, _est_document)
    if not articles and not taxes:
        return None
    groupes = frozenset(articles + taxes + documents)
    ens_articles = frozenset(articles)

    entete: dict[str, Any] = {}

    def poser(chemin: str, spec: Any) -> None:
        entete.setdefault(chemin, spec)

    for el in racine.iter():
        if not isinstance(el.tag, str) or el is racine or _dans(el, groupes):
            continue
        k = _cle(_local(el.tag))
        parent = el.getparent()
        kp = _cle(_local(parent.tag)) if parent is not None and parent is not racine else ""
        partie = next((p for p, cles in _PARTIES.items() if kp in cles), None)
        texte = _texte(el) if len(el) == 0 else ""
        if partie is not None:
            champ = next((c for c, cles in _PARTIE_CHAMPS.items() if k in cles), None)
            if champ is not None and texte:
                poser(f"{partie}.{champ}", arbre.chemin(el))
            continue
        if any(k in c for c in _PARTIES.values()):
            # partie dont le nom est le texte de l'élément et les identifiants des attributs
            p = next(p for p, cles in _PARTIES.items() if k in cles)
            if texte:
                poser(f"{p}.nom", arbre.chemin(el))
            for a in el.attrib:
                champ = next((c for c, cles in _PARTIE_CHAMPS.items() if _cle(_local(a)) in cles), None)
                if champ is not None and champ != "nom":
                    poser(f"{p}.{champ}", f"{arbre.chemin(el)}/@{_local(a)}")
            continue
        if k in _LIVRAISON:
            a_code = _attr(el, _ATTR_INCOTERM)
            a_lieu = _attr(el, _ATTR_LIEU)
            if a_code is not None:
                poser("incoterm", f"{arbre.chemin(el)}/@{a_code}")
            elif texte:
                poser("incoterm", arbre.chemin(el))
            if a_lieu is not None:
                poser("incoterm_lieu", f"{arbre.chemin(el)}/@{a_lieu}")
            continue
        if not texte:
            continue
        chemin = next((c for c, cles in _ENTETE.items() if k in cles), None)
        if chemin is None:
            continue
        if chemin == "mrn" and not _MRN_RE.match(texte.upper()):
            continue
        if chemin == "taux_change":
            poser(chemin, arbre.chemin(el))
            a = _attr(el, _ATTR_SENS)
            if a is not None and _valeurs_sens(el.get(a) or ""):
                poser(
                    "taux_change_sens",
                    {"source": f"{arbre.chemin(el)}/@{a}", "valeurs": _valeurs_sens(el.get(a) or "")},
                )
            continue
        a_dev = _attr(el, _ATTR_DEVISE)
        if chemin in ("montant_total_facture", "total_droits_taxes", "total_a_payer") and a_dev is not None:
            poser(chemin, {"source": arbre.chemin(el), "source_unite": f"{arbre.chemin(el)}/@{a_dev}"})
            continue
        poser(chemin, arbre.chemin(el))
    if "mrn" not in entete:
        return None

    listes: dict[str, Any] = {}
    tables: dict[str, dict[str, str]] = {"paiement": dict(_PAIEMENT_UE)}
    if articles:
        art = articles[0]
        champs: dict[str, Any] = {}
        a_num = _attr(art, _NUMERO_ARTICLE)
        if a_num is not None:
            champs["numero_article"] = f"@{a_num}"
        else:
            x = _enfant(art, _NUMERO_ARTICLE)
            if x is not None:
                champs["numero_article"] = arbre.chemin(x, art)
        # union des enfants de tous les articles (un champ facultatif peut manquer au premier)
        vus: dict[str, etree._Element] = {}
        for a in articles:
            for x in _enfants(a):
                vus.setdefault(_cle(_local(x.tag)), x)
        for k, x in vus.items():
            champ = next((c for c, cles in _ARTICLE.items() if k in cles), None)
            if champ is None or champ in champs:
                continue
            rel = arbre.chemin(x, x.getparent())
            a_u = _attr(x, _ATTR_UNITE)
            if champ == "quantite_unite_supplementaire" and a_u is not None:
                champs[champ] = {"source": rel, "source_unite": f"{rel}/@{a_u}"}
            elif champ in ("montant_facture_article", "valeur_statistique") and _attr(x, _ATTR_DEVISE):
                champs[champ] = {"source": rel, "source_unite": f"{rel}/@{_attr(x, _ATTR_DEVISE)}"}
            else:
                champs[champ] = rel
        listes["articles"] = {"source": arbre.chemin(art), "champs": champs}
    if taxes:
        tx = taxes[0]
        champs = {}
        code = _code_taxe_de(tx)
        if code is not None:
            champs["type_taxe"] = code[0]
        a_art = _attr(tx, _ATTR_ARTICLE_TAXE)
        if a_art is not None:
            champs["article"] = f"@{a_art}"
        elif articles and _dans(tx, ens_articles):
            art = next(a for a in tx.iterancestors() if a in ens_articles)
            num = listes["articles"]["champs"].get("numero_article")
            if isinstance(num, str):
                champs["article"] = f"ancestor::{arbre.nom(art)}[1]/{num}"
        vus = {}
        for t in taxes:
            for x in _enfants(t):
                vus.setdefault(_cle(_local(x.tag)), x)
        for k, x in vus.items():
            champ = next((c for c, cles in _TAXE.items() if k in cles), None)
            if champ is None or champ in champs:
                continue
            rel = arbre.chemin(x, x.getparent())
            if champ == "base_montant" and _attr(x, _ATTR_UNITE) and not _attr(x, _ATTR_DEVISE):
                champ = "base_quantite"  # assiette exprimée dans une unité (kg, litres, articles)
            if champ == "base_quantite":
                a_u = _attr(x, _ATTR_UNITE)
                champs[champ] = {"source": rel, "source_unite": f"{rel}/@{a_u}"} if a_u else rel
                if a_u:
                    champs["base_unite"] = f"{rel}/@{a_u}"
            else:
                champs[champ] = rel
        listes["taxations"] = {"source": arbre.chemin(tx), "champs": champs}
        # catégorie par code d'après les libellés imprimés dans le fichier
        a_lib = _attr(tx, _LIBELLE_TAXE)
        par_code: dict[str, set[str]] = defaultdict(set)
        for t in taxes:
            c = _code_taxe_de(t)
            lib = t.get(a_lib) if a_lib else None
            if lib is None:
                x = _enfant(t, _LIBELLE_TAXE)
                lib = _texte(x) if x is not None else None
            if c is not None and lib:
                cat = _categorie_libelle(lib)
                if cat:
                    par_code[c[1]].add(cat)
        cats = {code: next(iter(cs)) for code, cs in par_code.items() if len(cs) == 1}
        if cats:
            tables["categorie"] = cats
        # totaux imprimés par code de taxe (D-3101), hors des groupes déjà reconnus
        codes = {c[1] for t in taxes if (c := _code_taxe_de(t)) is not None}
        totaux = [
            el for el in _groupes(arbre, lambda el: _est_total_code(el, codes)) if not _dans(el, groupes)
        ]
        if totaux:
            a_code = _attr(totaux[0], _TAXE["type_taxe"])
            listes["totaux_par_code"] = {
                "source": arbre.chemin(totaux[0]),
                "champs": {"type_taxe": f"@{a_code}", "montant": "."},
            }
    if documents:
        d0 = documents[0]
        champs = {}
        a_code = _attr(d0, _DOC_CODE)
        if a_code is not None:
            champs["type_code"] = f"@{a_code}"
        else:
            x = _enfant(d0, _DOC_CODE)
            if x is not None:
                champs["type_code"] = arbre.chemin(x, d0)
        x = _enfant(d0, _DOC_REF)
        a_ref = _attr(d0, _DOC_REF)
        champs["reference"] = arbre.chemin(x, d0) if x is not None else (f"@{a_ref}" if a_ref else ".")
        listes["documents_references"] = {"source": arbre.chemin(documents[0]), "champs": champs}

    fiche: dict[str, Any] = {
        "format_id": FORMAT_DEDUIT,
        "version": "1.0.0",
        "type": "xml",
        "sous_type": "export_xml",
        "detection": {"racine": _local(racine.tag), **({"espace_noms": arbre.ns} if arbre.ns else {})},
        "entete": entete,
        "listes": listes,
        "tables": tables,
        "devise_par_defaut": "EUR",
    }
    if arbre.ns:
        fiche["xml"] = {"espaces_noms": {"d": arbre.ns}}
    return fiche


# --- recoupements -------------------------------------------------------------------------------------------------


def _d(v: Any) -> Decimal | None:
    if v is None or getattr(v, "valeur", None) is None:
        return None
    try:
        return Decimal(str(v.valeur))
    except (InvalidOperation, ValueError):
        return None


def correspondance_confirmee(ok: int, ko: int) -> bool:
    """La correspondance déduite est confirmée si des recoupements tiennent et que les échecs restent rares : une
    anomalie de la déclaration elle-même (un montant faux, que les contrôles doivent relever) ne doit pas faire
    douter de la lecture de tout le fichier ; une correspondance fausse fait échouer la plupart des recoupements."""
    return ok > 0 and ko <= max(1, ok // 4)


def coherence_declaration(champs: ChampsDeclaration) -> tuple[int, int]:
    """(recoupements vérifiés, recoupements en échec) des valeurs lues : somme des montants de taxes = total des
    droits et taxes ; base × taux = montant (ad valorem, montant arrondi au centime ou à l'euro) ; nombre
    d'articles annoncé = articles lus."""
    ok = ko = 0
    total = _d(champs.total_droits_taxes)
    montants = [_d(t.montant) for t in champs.taxations]
    if total is not None and montants and all(m is not None for m in montants):
        if abs(sum(montants) - total) <= Decimal("0.01") * max(1, len(montants)):
            ok += 1
        else:
            ko += 1
    for t in champs.taxations:
        b, r, m = _d(t.base_montant), _d(t.taux), _d(t.montant)
        if b is None or r is None or m is None or t.base_quantite is not None:
            continue
        calcule = b * r / 100
        if abs(calcule - m) <= Decimal("0.011") + abs(m) * Decimal("0.0005") or (
            m == m.to_integral_value() and abs(calcule - m) < 1
        ):  # montant arrondi à l'euro
            ok += 1
        else:
            ko += 1
    n = _d(champs.nombre_articles)
    if n is not None and champs.articles:
        if n == len(champs.articles):
            ok += 1
        else:
            ko += 1
    return ok, ko
