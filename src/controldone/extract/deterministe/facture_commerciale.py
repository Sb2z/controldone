"""Extracteur déterministe des factures commerciales (SPEC §5.3.1, §6.3, §7.3).

Sous-types couverts : ``facture``, ``pro_forma``, ``valeur_douane_seulement``, ``facture_integrateur``
(et ``sans_valeur_commerciale`` : mêmes champs). Langues : anglais, français, espagnol (libellés
multilingues ci-dessous, sans accents ni casse). PDF natif, OCR, et tableur (une feuille = une page).

Règles appliquées (pièges §5.3.1) :

- **total** : dernier total libellé payable du document, ou « total pour la douane » s'il existe ; un total
  de page, un sous-total, une ligne de fret / remise ne sont jamais le total général ; une valeur suivie
  d'une unité de masse ou d'un mot de colis, ou précédée d'un libellé de poids, n'est jamais un montant ;
  total absent -> somme des lignes, ``total_origine = reconstruit``, confiance ≤ 0,60 ;
- **TVA acheteur** : lue seulement dans le pavé acheteur (sous le libellé « acheteur / buyer / bill to /
  comprador »…), jamais dans le pavé du vendeur, du transporteur ou du déclarant ;
- **codes marchandise** : lus seulement dans la colonne du code (6 à 10 chiffres, forme imprimée gardée),
  jamais dans un en-tête où figurent téléphone, TVA, SIREN, LTA, numéro de facture ; un code coupé sur
  deux lignes est recollé ;
- **nombres** : formats ``1.234,56``, ``1,234.56``, ``1 234,56``, ``1'234.56`` ; séparateur décimal déduit
  du document ; devises sans décimales (JPY, KRW…) ;
- **devise** : code ISO lu ; le symbole ``$`` seul ne devient ``USD`` que si un code ISO de la page ou le
  pays du vendeur le confirme (§7.4).

Confiance : texte natif bien identifié 0,95 ; OCR fonction des confiances des mots (plafonnée sous 0,90
sans recoupement) ; le recoupement arithmétique (lignes + pieds = total ; quantité × prix = montant)
relève la confiance ; une incohérence la baisse. Mieux vaut une confiance basse qu'une valeur fausse
présentée comme sûre (§8.5).
"""

from __future__ import annotations

import itertools
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from decimal import Decimal

from controldone.extract.base import ExtractionContext, ExtractionResult
from controldone.extract.deterministe import _fc_langues as _L
from controldone.extract.deterministe._fc_regles import (
    chercher_partout,
    codes_devise_libelle,
    devise_symbole,
    nettoyer_colonnes,
    scinder_mots_colles,
)
from controldone.extract.deterministe._mise_en_page import (
    Colonne,
    Fabrique,
    Lecture,
    RangeeTableau,
    Trouve,
    VueDocument,
    VueLigne,
    accepte_entier,
    accepte_masse,
    accepte_montant,
    accepte_reference,
    chercher,
    colonne_droite,
    confiance_mots,
    devise_dans,
    est_bandeau_texte,
    lecture_mots,
    lignes_bandeau,
    lire_montant_mots,
    lire_tableau,
    lire_tva_mots,
    lire_tva_ocr,
    motifs,
    nombres_dans,
    pages_du_document,
    pave,
    reconnaitre_entete,
    separateur_masse,
    valeur_apres,
    vue_document,
)
from controldone.model.champs import ChampsFactureCommerciale, LigneFactureCommerciale, SousTotal
from controldone.model.documents import Document, Page
from controldone.model.enums import Methode, TotalOrigine, TypeDocument, TypeSousTotal, TypeValeur
from controldone.model.valeur import ExtracteurInfo, ValeurSourcee, deriver_somme
from controldone.normalize import (
    DEVISE_INCONNUE,
    DEVISES_SANS_DECIMALES,
    ISO_4217,
    code_marchandise,
    codes_iso_dans_texte,
    country_to_iso2,
    exposant_devise,
    normalize_currency,
    normalize_unit,
    parse_amount,
    parse_date_detail,
    parse_incoterm,
    tva_fr_valide,
)
from controldone.normalize.text import cle_texte

__all__ = ["ExtracteurFactureCommerciale", "extraire_facture_commerciale"]

VERSION = "1.0.0"
INFO = ExtracteurInfo(type="deterministe", id="facture_commerciale_regles", version=VERSION)

# --- vocabulaire (texte sans accents, minuscules) ---------------------------------------------------------

_NO = r"(?:no\b\.?|n\.?\s?[°o2]\.?|nr\.?|nro\.?|num(?:ero|ber)?\.?|#)"
LIB_NUMERO = motifs(
    rf"(?:commercial |proforma |pro[- ]?forma |customs |tax )?invoice\s*{_NO}\s*:?",
    r"(?:commercial |proforma |pro[- ]?forma )?invoice\s*(?:ref(?:erence)?)\.?\s*:?",
    rf"inv\.?\s*{_NO}\s*:?",
    rf"(?:{_NO}|numero)\s*(?:de\s*(?:la\s*)?)?(?:facture|factura)\s*:?",
    rf"(?:facture|factura)(?: (?:commerciale|comercial|pro ?forma|proforma))?\s*{_NO}\s*:?",
)
#: Repli OCR : « Factura nic: » (abréviation de numéro illisible) ; confiance réduite.
LIB_NUMERO_OCR = motifs(r"(?:invoice|facture|factura)\s+(?!date|fecha)[a-z0-9°.]{1,4}\s*:")
LIB_DATE = motifs(
    r"(?:invoice\s*)?date(?:\s*of\s*invoice)?(?:\s*de\s*(?:la\s*)?facture)?\s*:?",
    r"fecha(?:\s*de\s*(?:la\s*)?(?:factura|emision))?\s*:?",
    r"date\s*d'emission\s*:?",
)
LIB_DEVISE = motifs(r"(?:invoice\s*)?currency\s*:?", r"devise\s*:?", r"moneda\s*:?", r"divisa\s*:?", r"monnaie\s*:?")
LIB_INCOTERM = motifs(
    r"incoterms?(?:\s*\(?20\d\d\)?)?\s*:?", r"(?:terms|conditions?)\s*of\s*delivery\s*:?", r"delivery\s*terms\s*:?",
    r"conditions?\s*de\s*livraison\s*:?", r"condici(?:on|ones)\s*de\s*entrega\s*:?", r"trade\s*terms\s*:?",
)
LIB_TRANSPORT = motifs(
    rf"(?:master |house )?(?:b/?l|bill of lading|awb|air ?waybill|mawb|hawb|lta|connaissement|conocimiento"
    rf"|guia aerea|cmr|waybill|lettre de transport(?: aerien)?)\s*{_NO}?\s*:?",
)
_ACH = (r"(?:buyer|bill(?:ed)? to|sold to|invoice(?:d)? to|customer|acheteur|facture a|vendu a|client|comprador"
        r"|facturar a|cliente|importer|importateur|importador|" + _L.ACHETEUR + ")")
_DEST = (r"(?:ship(?:ped)? to|deliver(?:ed|y)? to|consignee|destinataire|livre a|livraison a|enviar a|entregar a"
         r"|consignatario|destinatario|" + _L.DESTINATAIRE + ")")
_VEND = (r"(?:seller|shipper|exporter|vendor|supplier|vendeur|expediteur|exportateur|fournisseur|vendedor"
         r"|exportador|proveedor|remitente|" + _L.VENDEUR + ")")
LIB_ACHETEUR = motifs(rf"{_ACH}\b(?:\s*[/&-]\s*{_ACH}\b)*\s*:?") + _L.ACHETEUR_PARENTHESE
LIB_DESTINATAIRE = motifs(rf"{_DEST}\b(?:\s*[/&-]\s*{_DEST}\b)*\s*:?")
LIB_VENDEUR = motifs(rf"{_VEND}\b(?:\s*[/&-]\s*{_VEND}\b)*\s*:?")
LIB_FIN_PAVE = motifs(
    r"(?:buyer|bill(?:ed)? to|sold to|ship(?:ped)? to|consignee|seller|shipper|exporter|notify|acheteur"
    r"|destinataire|vendeur|expediteur|comprador|vendedor|consignatario|livre a|enviar a|" + _L.FIN_PAVE + r")\b",
)
LIB_POIDS_BRUT = motifs(
    r"(?:total\s*)?gross\s*(?:weight|wt)\.?(?:\s*\(?kgs?\)?)?\s*:?", r"g\.?\s*w\.?\s*(?:total)?\s*:",
    r"(?:total\s*)?poids\s*brut(?:\s*total)?\s*:?", r"(?:total\s*)?peso\s*bruto(?:\s*total)?\s*:?",
)
LIB_POIDS_NET = motifs(
    r"(?:total\s*)?net\s*(?:weight|wt)\.?(?:\s*\(?kgs?\)?)?\s*:?", r"n\.?\s*w\.?\s*(?:total)?\s*:",
    r"(?:total\s*)?poids\s*net(?:\s*total)?\s*:?", r"(?:total\s*)?peso\s*neto(?:\s*total)?\s*:?",
)
LIB_COLIS = motifs(
    r"(?:total\s*)?(?:number|no\.?|nbr|nb)\s*of\s*(?:packages|pkgs|cartons|parcels|pieces|colli)\s*:?",
    r"total\s*(?:packages|pkgs|cartons|parcels)\s*:?", r"packages\s*:",
    r"(?:nombre|nb|nbre)\s*(?:total\s*)?(?:de\s*)?colis\s*:?", r"colis\s*:",
    r"(?:numero|n\.?o|cantidad|total)\s*(?:de\s*)?bultos\s*:?", r"bultos\s*:",
)
#: Libellé de colis sans « : », seul dans son segment ; valeur lue à droite seulement.
LIB_COLIS_NU = motifs(r"(?:packages|pkgs|colis|bultos|cartons|nombre de colis|no\.? of packages)$")
_EXCLU_TOTAL = re.compile(
    r"sub-?\s?total|sous-?\s?total|page|report|carried|suma y sigue|weight|poids|peso|wt\b|packages|colis|"
    r"bultos|quantit|qty|cantidad|pieces|cartons|volume|cbm|\b(?:tva|vat|iva)\b|discount|remise|descuento|"
    r"freight|fret|flete|insurance|assurance|seguro|items?\b|lines?\b|articles?\b"
)
LIB_TOTAL_DOUANE = motifs(
    r"(?:total\s*)?(?:value|valeur|valor)\s*(?:for|pour la|pour|para|en)\s*(?:customs|douane|aduana)"
    r"(?:\s*purposes?)?(?:\s*only)?\s*:?",
    r"total\s*(?:for|pour la|pour|para)\s*(?:customs|douane|aduana)(?:\s*purposes?)?\s*:?",
    r"(?:customs|declared)\s*value\s*:?", r"valeur\s*(?:en|declaree en)\s*douane\s*:?", r"valor\s*en\s*aduana\s*:?",
)
LIB_TOTAL = motifs(
    r"(?:grand\s*|invoice\s*|net\s*)?total(?:\s*(?:amount|invoice|value|due|general|a payer|a pagar|facture"
    r"|factura|ttc|cif|fob|cfr|net|to pay|payable|invoice value|importe|credit(?:ed)?|credite|avoir"
    r"|del abono|nota de credito))?(?:\s*\(?[a-z]{3}\)?(?![a-z]))?\s*:?",
    r"montant\s*(?:de\s*l'|total\s*de\s*l')avoir\s*:?", r"credit\s*(?:note\s*)?total\s*:?",
    r"amount\s*(?:due|payable)\s*:?", r"balance\s*due\s*:?", r"net\s*a\s*payer\s*:?", r"montant\s*(?:total|net|du)\s*:?",
    r"importe\s*(?:total|neto)\s*:?", r"valor\s*total\s*:?", r"invoice\s*(?:total|amount|value)\s*:?",
    r"total\s*a\s*(?:payer|pagar)\s*:?",
)
LIB_TOTAL_PAGE = motifs(
    r"(?:page|sheet)\s*total\s*:?", r"total\s*(?:de\s*(?:la\s*)?)?(?:page|pagina|hoja)\s*:?",
    r"(?:carried\s*forward|a\s*reporter|suma\s*y\s*sigue|report)\b",
)
LIB_SOUS_TOTAUX: list[tuple[TypeSousTotal, list[re.Pattern[str]]]] = [
    (TypeSousTotal.marchandises, motifs(
        r"(?:sub-?\s?total|sous-?\s?total|subtotal)(?:\s*\(?(?:goods|marchandises|merchandise|mercancias?|"
        r"productos)\)?)?\s*:?",
        r"(?:goods|merchandise)\s*(?:value|total)\s*:?", r"(?:valeur|total)\s*(?:des\s*)?marchandises\s*:?",
        r"(?:valor|total)\s*(?:de\s*(?:la\s*)?)?mercancias?\s*:?",
    )),
    (TypeSousTotal.fret, motifs(
        r"(?:sea\s*|air\s*|international\s*)?(?:freight|fret|flete|shipping|transport)(?:\s*(?:charges?|costs?|"
        r"cost|fees?))?\s*:?", r"frais\s*de\s*(?:port|transport)\s*:?", r"gastos\s*de\s*(?:envio|transporte)\s*:?",
    )),
    (TypeSousTotal.assurance, motifs(r"(?:insurance|assurance|seguro)(?:\s*(?:charges?|costs?|premium))?\s*:?")),
    (TypeSousTotal.emballage, motifs(
        r"(?:packing|packaging|emballage|embalaje)(?:\s*(?:charges?|costs?|fees?))?\s*:?",
        r"frais\s*d'emballage\s*:?", r"gastos\s*de\s*embalaje\s*:?",
    )),
    (TypeSousTotal.remise, motifs(
        r"(?:discount|remise|rabais|descuento|reduction|rebate|ristourne|bonificacion)\b(?:\s*\(?[\d.,]+\s*%\)?)?"
        r"\s*:?",
    )),
    (TypeSousTotal.autre, motifs(
        r"(?:other\s*charges|handling(?:\s*charges)?|autres\s*frais|otros\s*gastos|frais\s*divers|"
        r"documentation\s*fees?)\s*:?",
    )),
]
_EXCLU_SOUS_TOTAL = re.compile(r"packing\s*list|liste\s*de\s*colisage|lista\s*de\s*empaque|shipped|via\b|terms|"
                               r"poids|weight|peso|document|waybill|frachtbrief|vrachtbrief|lettera di vettura")

VOCAB_COLONNES: dict[str, list[str]] = {
    "numero_ligne": ["#", "no", "n°", "n.o", "nº", "nr", "pos", "line", "ligne", "item no", "n° ligne", "linea"],
    "reference_article": [
        "item ref", "item ref.", "ref", "reference", "referencia", "ref article", "ref. article", "part no",
        "part number", "article", "articulo", "code article", "sku", "product code", "item code", "codigo",
        "item", "material", "cod",
    ],
    "description": [
        "description", "designation", "descripcion", "goods", "description of goods", "goods description",
        "marchandise", "marchandises", "producto", "product", "libelle", "denominacion", "mercancia",
    ],
    "code": [
        "hs code", "hs", "hs-code", "h.s. code", "h.s code", "code sh", "sh", "partida", "partida arancelaria",
        "tariff", "tariff code", "hts", "hts code", "taric", "code nc", "nc", "nomenclature", "commodity code",
        "code douanier", "customs code", "codigo arancelario", "code tarifaire", "code hs", "fraccion",
    ],
    "origine": [
        "orig", "origin", "origine", "country of origin", "pays d'origine", "pays origine", "coo", "pais de origen",
        "origen", "made in", "pays",
    ],
    "quantite": ["qty", "quantity", "qte", "quantite", "cant", "cantidad", "qte.", "quant"],
    "unite": ["unit", "unite", "uni", "ud", "uom", "u/m", "unidad", "um", "u"],
    "masse_nette": [
        "n.w. kg", "n.w kg", "n.w", "net kg", "net weight", "nw", "nw kg", "p. neto", "p neto", "p. net", "p net",
        "poids net", "peso neto", "net wt", "net weight kg", "pds net", "net (kg)", "n.w. (kg)",
    ],
    "masse_brute": [
        "g.w. kg", "g.w kg", "g.w", "gross kg", "gw", "gw kg", "gross weight", "poids brut", "peso bruto", "p. brut",
        "p brut", "p. bruto", "p bruto", "gross wt", "gross weight kg", "pds brut", "gross (kg)", "g.w. (kg)",
    ],
    "prix_unitaire": [
        "unit price", "prix unitaire", "precio unit", "precio unitario", "p.u", "pu", "price", "prix", "precio",
        "unit value", "valeur unitaire", "prix unit", "p. unit", "p unit", "valor unitario",
    ],
    "montant": [
        "amount", "montant", "importe", "total", "line total", "value", "valeur", "total amount", "montant total",
        "valor", "total price", "ext. price", "extended price", "total value", "montant ht", "subtotal", "valor total",
        "importe total",
    ],
}
# corrections d'en-tête où le préfixe d'un mot normalisé ne suffit pas (« p ne… »)
for _t in ("masse_nette", "masse_brute"):
    VOCAB_COLONNES[_t] = [v.replace(".", "") if v.startswith("p.") else v for v in VOCAB_COLONNES[_t]] + \
        [v for v in VOCAB_COLONNES[_t] if v.startswith("p.")]

_FIN_TABLEAU = re.compile(
    r"^(?:sub-?\s?total|sous-?\s?total|subtotal|total|grand total|page total|carried|a reporter|suma y sigue|"
    r"freight|fret|flete|insurance|assurance|seguro|packing|emballage|embalaje|discount|remise|descuento|"
    r"(?:total\s*)?gross|(?:total\s*)?net\s*(?:weight|wt)|(?:total\s*)?poids|(?:total\s*)?peso|number of|"
    r"nombre de|numero de|n\.o de bultos|we hereby|nous certifions|certificamos|declaration|amount due|"
    r"montant total|importe total|valor total|value for customs|valeur pour|valor para|" + _L.FIN_TABLEAU + ")"
)

# --- compléments multilingues (de, it, nl ; D-2001) -----------------------------------------------------------
LIB_NUMERO = LIB_NUMERO + _L.LIB_NUMERO
LIB_DATE = LIB_DATE + _L.LIB_DATE
LIB_DEVISE = LIB_DEVISE + _L.LIB_DEVISE
LIB_INCOTERM = LIB_INCOTERM + _L.LIB_INCOTERM
LIB_TRANSPORT = LIB_TRANSPORT + _L.LIB_TRANSPORT
LIB_POIDS_BRUT = LIB_POIDS_BRUT + _L.LIB_POIDS_BRUT
LIB_POIDS_NET = LIB_POIDS_NET + _L.LIB_POIDS_NET
LIB_COLIS = LIB_COLIS + _L.LIB_COLIS
LIB_TOTAL = LIB_TOTAL + _L.LIB_TOTAL
LIB_TOTAL_DOUANE = LIB_TOTAL_DOUANE + _L.LIB_TOTAL_DOUANE
_EXCLU_TOTAL = re.compile(_EXCLU_TOTAL.pattern + "|" + _L.EXCLU_TOTAL)
LIB_SOUS_TOTAUX = [(typ, mots + _L.SOUS_TOTAUX.get(typ.value, [])) for typ, mots in LIB_SOUS_TOTAUX]
for _t, _libs in _L.COLONNES.items():
    VOCAB_COLONNES[_t] = VOCAB_COLONNES[_t] + [x for x in _libs if x not in VOCAB_COLONNES[_t]]


# --- extracteur -----------------------------------------------------------------------------------------------


class ExtracteurFactureCommerciale:
    """Extracteur ``deterministe`` des factures commerciales (texte natif, OCR, tableur)."""

    id = INFO.id
    version = VERSION
    type = "deterministe"

    def supports(self, document: Document, pages: Sequence[Page]) -> bool:
        t = getattr(document.type, "value", document.type)
        if t != TypeDocument.facture_commerciale.value:
            return False
        return any((getattr(p, "texte", "") or "").strip() for p in pages) and not all(
            (getattr(p, "texte", "") or "").lstrip().startswith("<") for p in pages
        )

    def extract(self, document: Document, pages: Sequence[Page], context: ExtractionContext) -> ExtractionResult:
        choisies = pages_du_document(document, pages, context.options)
        vue = vue_document(choisies, separateur_decimal=context.separateur_decimal)
        champs, avert = extraire_facture_commerciale(vue, document_id=document.id, ids=context.ids)
        return ExtractionResult(extracteur=INFO, champs=champs, avertissements=avert,
                                partielle=not any(p.lignes for p in vue.pages))


# --- extraction -----------------------------------------------------------------------------------------------


@dataclass
class _Etat:
    vue: VueDocument
    fab: Fabrique
    champs: ChampsFactureCommerciale = field(default_factory=ChampsFactureCommerciale)
    avert: list[str] = field(default_factory=list)
    devise: str | None = None
    lignes_tableau: set[tuple[int, int]] = field(default_factory=set)  # (page, rang) des lignes du tableau
    entetes: set[tuple[int, int]] = field(default_factory=set)
    fin_tableau: dict[int, int] = field(default_factory=dict)  # page -> rang de la 1re ligne après le tableau
    #: en-tête du tableau des lignes par page : (ligne, colonnes nettoyées) ; codes de devise des colonnes
    entetes_tab: dict[int, tuple[VueLigne, list[Colonne]]] = field(default_factory=dict)
    codes_entete: list[tuple[str, Lecture]] = field(default_factory=list)


def extraire_facture_commerciale(
    vue: VueDocument, *, document_id: str, ids=None,
) -> tuple[ChampsFactureCommerciale, list[str]]:
    """Champs d'une facture commerciale à partir de sa vue (pages du document)."""
    fab = Fabrique(TypeDocument.facture_commerciale, document_id, INFO, vue, ids)
    e = _Etat(vue=vue, fab=fab)
    _reperer_entetes(e)
    _devise(e)
    _separateur_par_devise(e)
    _entete(e)
    _tableau(e)
    _parties(e)
    _pied(e)
    return e.champs, e.avert


def _premier(vue: VueDocument, libelles, accepte, *, exclure=None, pages=None, dessous=True) -> Lecture | None:
    for t in chercher(vue, libelles, pages=pages, exclure=exclure):
        lec = valeur_apres(vue, t, accepte, dessous=dessous)
        if lec is not None:
            return lec
    return None


# --- devise -----------------------------------------------------------------------------------------------


def _accepte_devise(mots) -> tuple[int, int] | None:
    for k, m in enumerate(mots[:3]):
        t = m.texte.strip(":;,()")
        if t.upper() in ISO_4217 and (t.isupper() or len(mots) == 1):
            return k, k + 1
        code = normalize_currency(t)
        if code and code != DEVISE_INCONNUE:
            return k, k + 1
        if t in ("$", "¥", "kr"):
            return k, k + 1
    return None


def _devise(e: _Etat) -> None:
    vue = e.vue
    lec = _premier(vue, LIB_DEVISE, _accepte_devise)
    codes_page = codes_iso_dans_texte(vue.texte)
    code_lu = None
    if lec is not None:
        code_lu = normalize_currency(lec.texte, codes_iso_page=codes_page)
    # devise imprimée à côté des totaux (indice de recoupement)
    codes_totaux = []
    for t in chercher(vue, LIB_TOTAL + LIB_TOTAL_DOUANE, exclure=_EXCLU_TOTAL):
        lt = valeur_apres(vue, t, accepte_montant(vue, None))
        if lt is not None:
            c = devise_dans(lt.texte)
            if c:
                codes_totaux.append(c)
    indices = _devise_indices(e, codes_page)
    if code_lu and code_lu != DEVISE_INCONNUE:
        conf = confiance_mots(lec)
        if codes_totaux and all(c == code_lu for c in codes_totaux):
            conf = max(conf, 0.97 if lec.methode is not Methode.ocr else 0.93)
        elif codes_totaux and any(c != code_lu for c in codes_totaux):
            conf = min(conf, 0.6)
        elif indices and set(indices) != {code_lu}:
            conf = min(conf, 0.6)  # en-tête de colonne ou libellé de total dans une autre devise
        elif lec.methode is Methode.ocr and conf >= C_OCR_DEVISE_MIN and (
            indices or _code_seul_relu(vue.texte, code_lu, codes_page)
        ):
            # D-2308 : le code du libellé « devise » est relu ailleurs (en-tête de colonne, total, ou seul code
            # ISO de la page imprimé sur deux lignes) : deux lectures concordantes en deux endroits.
            conf = max(conf, 0.9)
        e.champs.devise = e.fab.valeur("devise", lec, confiance=conf)
        e.devise = code_lu
        return
    # pas de libellé : code ISO à côté du total
    inconnue: Lecture | None = None
    for t in reversed(chercher(vue, LIB_TOTAL_DOUANE + LIB_TOTAL, exclure=_EXCLU_TOTAL)):
        lt = valeur_apres(vue, t, accepte_montant(vue, None))
        if lt is None:
            continue
        for m in lt.mots:
            c = normalize_currency(m.texte, codes_iso_page=codes_page)
            if (c and c != DEVISE_INCONNUE and m.texte.strip("()-").isupper()) or (c and m.texte in ("€", "£")):
                lecd = Lecture((m,), lt.page, lt.methode, contexte=lt.contexte)
                conf = min(confiance_mots(lecd), 0.9)
                if lecd.methode is Methode.ocr and conf >= C_OCR_DEVISE_MIN and _code_seul_relu(
                        vue.texte, c, codes_page):
                    conf = 0.9  # D-2308 : seul code ISO du document, relu sur une autre ligne
                e.champs.devise = e.fab.valeur("devise", lecd, confiance=conf)
                e.devise = c
                return
            if c == DEVISE_INCONNUE and inconnue is None:
                inconnue = Lecture((m,), lt.page, lt.methode, contexte=lt.contexte)
    if _devise_par_indices(e, indices):
        return
    if inconnue is not None:  # symbole ambigu (« $ », « ¥ ») sans code ISO qui le résolve
        e.champs.devise = e.fab.valeur("devise", inconnue, confiance=0.3)
        return
    if lec is not None:  # « $ » non confirmé
        e.champs.devise = e.fab.valeur("devise", lec, confiance=0.3)


def _code_seul_relu(texte: str, code: str, codes_page) -> bool:
    """``code`` est le seul code ISO de devise imprimé sur le document et figure, en mot entier, sur au moins
    deux lignes distinctes (D-2308)."""
    if set(codes_page or ()) != {code}:
        return False
    motif = re.compile(rf"(?<![A-Z]){re.escape(code)}(?![A-Z])")
    return sum(1 for ligne in texte.splitlines() if motif.search(ligne)) >= 2


def _devise_indices(e: _Etat, codes_page) -> dict[str, list[tuple[str, Lecture]]]:
    """Devises imprimées hors libellé « devise » (D-2003) : code accolé au libellé d'une colonne de prix ou de
    montant, code dans le libellé ou la valeur d'un total (« TOTAL CNY », « Total due (INR) », « USD 1,234.00 »),
    symbole univoque à côté du total (€, £, ₩, ₹, ₺ ; ¥ et $ seulement si un seul code ISO compatible est
    imprimé). Retourne {code: [(source, lecture)]}."""
    out: dict[str, list[tuple[str, Lecture]]] = {}

    def ajouter(code: str | None, source: str, lec: Lecture) -> None:
        if code and code in ISO_4217:
            out.setdefault(code, []).append((source, lec))

    for code, lec in e.codes_entete:
        ajouter(code if code in ISO_4217 else devise_symbole(code, codes_page), "entete", lec)
    vue = e.vue
    for t in chercher(vue, LIB_TOTAL + LIB_TOTAL_DOUANE, exclure=_EXCLU_TOTAL):
        for m in t.segment.mots:
            for c in codes_devise_libelle([m]):
                ajouter(c, "total", lecture_mots([m], t.page, t.ligne))
        lt = valeur_apres(vue, t, accepte_montant(vue, None))
        if lt is None:
            continue
        for m in lt.mots:
            for c in codes_devise_libelle([m]):
                ajouter(c, "total", Lecture((m,), lt.page, lt.methode, contexte=lt.contexte))
            sym = re.match(r"^[(\-]?(US\$|[€£₩₹₺¥$])", m.texte)
            if sym:
                ajouter(devise_symbole(sym.group(1), codes_page), "symbole",
                        Lecture((m,), lt.page, lt.methode, contexte=lt.contexte))
    return out


#: Confiance OCR minimale (``confiance_mots``) des mots d'un code de devise lu à deux endroits (D-2308).
C_OCR_DEVISE_MIN = 0.65


def _devise_par_indices(e: _Etat, indices: dict[str, list[tuple[str, Lecture]]]) -> bool:
    """Devise sans libellé : un seul code parmi les indices -> retenu (0,90 ; 0,95 si deux sources distinctes,
    en-tête de colonne et total ; OCR 0,85 / 0,90) ; plusieurs codes -> celui du total, 0,60."""
    if not indices:
        return False
    if len(indices) == 1:
        code, srcs = next(iter(indices.items()))
        conf_haute = len({s for s, _ in srcs}) >= 2
    else:
        totaux = {c for c, srcs in indices.items() if any(s == "total" for s, _ in srcs)}
        if len(totaux) != 1:
            return False
        code = totaux.pop()
        srcs = indices[code]
        conf_haute = None
    lec = next((x for s, x in srcs if s == "total"), srcs[0][1])
    ocr = any(x.methode is Methode.ocr for _, x in srcs)
    if conf_haute is None:
        conf = 0.6
    elif ocr:
        c_mots = confiance_mots(lec)
        # D-2308 : deux lectures concordantes du même code ISO à deux endroits distincts (en-tête de colonne et
        # total) se confirment : 0,90 comme annoncé (D-2003), au lieu du plafond d'une lecture OCR isolée.
        conf = 0.9 if conf_haute and c_mots >= C_OCR_DEVISE_MIN else min(0.85, max(c_mots, 0.6))
    else:
        conf = 0.95 if conf_haute else 0.9
    v = e.fab.valeur("devise", lec, confiance=conf)
    if v is not None and v.valeur != code:  # symbole (¥, $) résolu par le code ISO imprimé ailleurs
        v = v.model_copy(update={"valeur": code, "confiance": min(conf, 0.85)})
    e.champs.devise = v
    e.devise = code
    return True


def _separateur_par_devise(e: _Etat) -> None:
    """Devise sans décimales (JPY, KRW…) : « 79,028 » groupe les milliers, donc l'autre signe est décimal."""
    if e.vue.separateur_decimal is not None or e.devise not in DEVISES_SANS_DECIMALES:
        return
    texte = e.vue.texte
    if re.search(r"(?<![\d.,])\d{1,3},\d{3}(?![\d])", texte):
        e.vue.separateur_decimal = "."
    elif re.search(r"(?<![\d.,])\d{1,3}\.\d{3}(?![\d])", texte):
        e.vue.separateur_decimal = ","


# --- en-tête --------------------------------------------------------------------------------------------------


def _accepte_date(mots) -> tuple[int, int] | None:
    meilleur = None
    for j in range(1, min(len(mots), 5) + 1):
        txt = " ".join(m.texte for m in mots[:j])
        d = parse_date_detail(txt)
        if d is not None and re.search(r"\d", txt):
            meilleur = (0, j)
    if meilleur is None:
        return None
    # retirer les mots de fin qui n'appartiennent pas à la date
    i, j = meilleur
    while j > 1 and parse_date_detail(" ".join(m.texte for m in mots[:j - 1])) == parse_date_detail(
            " ".join(m.texte for m in mots[:j])):
        j -= 1
    return i, j


def _accepte_incoterm(mots) -> tuple[int, int] | None:
    if not mots:
        return None
    t = mots[0].texte.strip(":;,()").upper()
    inc = parse_incoterm(t)
    if inc is None or not re.fullmatch(r"[A-Z]{3}", t):
        return None
    return 0, len(mots)


def _entete(e: _Etat) -> None:
    vue, fab, ch = e.vue, e.fab, e.champs
    lec = _premier(vue, LIB_NUMERO, _accepte_numero)
    if lec is not None:
        ch.numero = fab.valeur("numero", lec, confiance=_conf_ref(lec))
    else:
        lec = _premier(vue, LIB_NUMERO_OCR, accepte_reference, dessous=False)
        if lec is not None:
            ch.numero = fab.valeur("numero", lec, confiance=min(0.7, _conf_ref(lec)))
    lec = _premier(vue, LIB_DATE, _accepte_date)
    if lec is not None:
        d = parse_date_detail(lec.texte)
        conf = confiance_mots(lec)
        # jour/mois inversables : sûr seulement sur un document français ou espagnol (ordre JJ/MM)
        if d is not None and d.ambigu and not re.search(r"\b(facture|factura|fecha)\b", cle_texte(vue.texte)):
            conf = min(conf, 0.7)
        ch.date = fab.valeur("date", lec, confiance=conf)
    lec = _premier(vue, LIB_INCOTERM, _accepte_incoterm)
    if lec is not None:
        code = Lecture(lec.mots[:1], lec.page, lec.methode, contexte=lec.contexte)
        ch.incoterm = fab.valeur("incoterm", code, confiance=confiance_mots(lec, plafond_ocr=0.9))
        mots_lieu = list(lec.mots[1:])
        # mention de version (« (Incoterms® 2020) », « Incoterms 2020 ») : hors du lieu
        k_fin = next((k for k, m in enumerate(mots_lieu) if m.texte.startswith("(")
                      or cle_texte(m.texte).startswith("incoterm")), len(mots_lieu))
        mots_lieu = mots_lieu[:k_fin]
        if mots_lieu:
            lieu = Lecture(tuple(mots_lieu), lec.page, lec.methode, contexte=lec.contexte)
            ch.incoterm_lieu = fab.valeur("incoterm_lieu", lieu)
    else:
        _incoterm_libre(e)
    lec = _premier(vue, LIB_TRANSPORT, accepte_reference)
    if lec is not None:
        ch.ref_transport = fab.valeur("ref_transport", lec, confiance=_conf_ref(lec))


def _accepte_numero(mots) -> tuple[int, int] | None:
    """Numéro de facture : référence, précédée d'un préfixe de 2 à 4 capitales séparé par une espace
    (« FT 4800/2026 », « ODH 2026.3681 », D-2001)."""
    if len(mots) >= 2 and re.fullmatch(r"[A-Z]{2,4}", mots[0].texte):
        r = accepte_reference(mots[1:])
        if r is not None and r[0] == 0:
            return 0, r[1] + 1
    return accepte_reference(mots)


def _conf_ref(lec: Lecture) -> float:
    """Référence alphanumérique : sur OCR, O/0, I/1, S/5… sont fréquents -> plafond plus bas."""
    if lec.methode is not Methode.ocr:
        return 0.95
    c = confiance_mots(lec, plafond_ocr=0.85)
    if re.search(r"[A-Za-z]", lec.texte) and re.search(r"\d", lec.texte):
        c = min(c, 0.8)
    return c


_INCOTERM_LIBRE = re.compile(r"\b(EXW|FCA|FAS|FOB|CFR|CIF|CPT|CIP|DAP|DPU|DDP|DAT|DAF|DES|DEQ|DDU)\b")


def _incoterm_libre(e: _Etat) -> None:
    """Incoterm sans libellé : code en majuscules suivi d'un lieu, une seule fois dans le document."""
    trouves = []
    for li in e.vue.lignes():
        for s in li.segments:
            for k, m in enumerate(s.mots):
                if _INCOTERM_LIBRE.fullmatch(m.texte.strip(",;:()")):
                    trouves.append((li, s, k))
    codes = {s.mots[k].texte.strip(",;:()") for _, s, k in trouves}
    if len(codes) != 1:
        return
    li, s, k = trouves[0]
    page = e.vue.page(li.page)
    assert page is not None
    lec = lecture_mots(s.mots[k:k + 1], page, li)
    e.champs.incoterm = e.fab.valeur("incoterm", lec, confiance=min(0.7, confiance_mots(lec)))


# --- parties -------------------------------------------------------------------------------------------------


def _parties(e: _Etat) -> None:
    vue, fab, ch = e.vue, e.fab, e.champs
    # étiquette « TVA acheteur » explicite (tableur, formulaire)
    for t in chercher(vue, motifs(r"(?:buyer|customer|acheteur|client|comprador|cliente)(?:'s)?\s*(?:vat|tva|iva)")):
        lec = valeur_apres(vue, t, lambda ms: (lambda r: (r[0], r[1]) if r else None)(lire_tva_mots(ms)))
        if lec is not None:
            _tva_partie(e, "acheteur", lec)
            break
    bandeaux = lignes_bandeau(vue)
    pavés = chercher(vue, LIB_ACHETEUR, pages=[vue.pages[0].numero] if vue.pages else None)
    for t in pavés:
        if _sous_champ(t) or (t.page.numero, t.ligne.rang) in bandeaux:
            continue
        lignes = [(li, ms) for li, ms in pave(t, fin=LIB_FIN_PAVE, exclus=e.entetes | bandeaux)]
        if not lignes:
            continue
        if ch.acheteur.nom is None:
            li0, mots0 = lignes[0]
            if not re.search(r"(vat|tva|iva)\b", cle_texte(" ".join(m.texte for m in mots0))) \
                    and _nom_plausible(mots0):
                page = vue.page(li0.page)
                lec_nom = lecture_mots(mots0, page, li0)
                ch.acheteur.nom = fab.valeur("acheteur.nom", lec_nom, type_valeur=TypeValeur.texte,
                                             confiance=min(_plafond_nom(t), confiance_mots(lec_nom)))
            adr = [lecture_mots(ms, vue.page(li.page), li) for li, ms in lignes[1:]
                   if not re.search(r"(vat|tva|iva|eori|siren|siret|tel|phone|fax|e-?mail)\b",
                                    cle_texte(" ".join(m.texte for m in ms)))]
            if adr:
                ch.acheteur.adresse = fab.valeur("acheteur.adresse", adr[0], type_valeur=TypeValeur.texte)
        for li, ms in lignes:
            if ch.acheteur.tva is None:
                r = lire_tva_ocr(ms)
                if r is not None:
                    _tva_partie(e, "acheteur", lecture_mots(ms[r[0]:r[1]], vue.page(li.page), li),
                                corrigee=r[2] if r[3] else None)
            if ch.acheteur.eori is None:
                eo = _eori(ms)
                if eo is not None:
                    lec = lecture_mots(ms[eo[0]:eo[1]], vue.page(li.page), li)
                    ch.acheteur.eori = fab.valeur("acheteur.eori", lec, confiance=_conf_ref(lec))
                    ch.eori_importateur = fab.valeur("eori_importateur", lec, confiance=_conf_ref(lec))
        if ch.acheteur.nom is not None:
            break
    for t in chercher(vue, LIB_DESTINATAIRE, pages=[vue.pages[0].numero] if vue.pages else None):
        if _sous_champ(t) or (t.page.numero, t.ligne.rang) in bandeaux:
            continue
        lignes = pave(t, fin=LIB_FIN_PAVE, exclus=e.entetes | bandeaux)
        if not lignes:
            continue
        li0, mots0 = lignes[0]
        if _nom_plausible(mots0):
            lec_nom = lecture_mots(mots0, vue.page(li0.page), li0)
            ch.destinataire.nom = fab.valeur("destinataire.nom", lec_nom, type_valeur=TypeValeur.texte,
                                             confiance=min(_plafond_nom(t), confiance_mots(lec_nom)))
        for li, ms in lignes:
            r = lire_tva_mots(ms)
            if r is not None:
                lec = lecture_mots(ms[r[0]:r[1]], vue.page(li.page), li)
                ch.destinataire.tva = fab.valeur("destinataire.tva", lec, confiance=_conf_tva(lec))
                break
        break
    _vendeur(e)


def _nom_plausible(mots) -> bool:
    """Un nom de partie : au moins trois lettres, ni un bandeau, ni un libellé « clé : valeur » d'en-tête."""
    txt = " ".join(m.texte for m in mots)
    if not re.search(r"[^\W\d_]{3}", txt) or est_bandeau_texte(txt):
        return False
    return not txt.rstrip().endswith(":")


def _plafond_nom(t: Trouve) -> float:
    """Plafond de confiance d'un nom lu dans un pavé : 0,90 ; 0,80 quand une colonne de droite s'intercale
    avec le pavé (structure ambiguë, D-951)."""
    if t.page.geometrie and not t.ligne.segments[t.segment.rang + 1:] and colonne_droite(
            t.page, t.ligne, t.segment.x0, t.segment.x1) is not None:
        return 0.8
    return 0.9


_SOUS_CHAMP = re.compile(r"^(?:'s\s*)?(?:address|adresse|direccion|vat|tva|iva|name|nom|nombre|eori|tel|phone|"
                         r"fax|e-?mail|contact|country|pays|pais|city|ville|ciudad|ref|reference|no\b|n°|number)")


def _sous_champ(t: Trouve) -> bool:
    """« Buyer address », « Buyer VAT No. » : libellé d'un sous-champ, pas l'ouverture du pavé."""
    reste = cle_texte(" ".join(m.texte for m in t.segment.mots[t.apres:]))
    return bool(_SOUS_CHAMP.match(reste))


def _eori(mots) -> tuple[int, int] | None:
    for k, m in enumerate(mots):
        if re.fullmatch(r"[A-Z]{2}[0-9A-Z]{8,15}", m.texte.strip(":;,")) and k > 0 and "eori" in cle_texte(
                mots[k - 1].texte):
            return k, k + 1
    return None


def _conf_tva(lec: Lecture) -> float:
    """Une TVA française dont la clé est valide est un recoupement fort, même lue par OCR."""
    from controldone.normalize import normalize_vat

    norm = normalize_vat(lec.texte) or ""
    if norm.startswith("FR"):
        if tva_fr_valide(norm):
            return 0.97 if lec.methode is not Methode.ocr else max(0.92, min(0.95, confiance_mots(lec) + 0.1))
        return min(0.5, confiance_mots(lec))
    return confiance_mots(lec, plafond_ocr=0.8)


def _tva_partie(e: _Etat, partie: str, lec: Lecture, corrigee: str | None = None) -> None:
    """TVA d'une partie. ``corrigee`` : forme corrigée des confusions OCR (clé française vérifiée) ; la
    valeur brute reste celle lue, la confiance est plafonnée à 0,85."""
    from controldone.normalize import extraire_siren

    v = e.fab.valeur(f"{partie}.tva", lec, confiance=_conf_tva(lec))
    if corrigee is not None and v is not None:
        v = v.model_copy(update={"valeur": corrigee, "confiance": min(0.85, max(confiance_mots(lec), 0.6))})
    getattr(e.champs, partie).tva = v
    if partie == "acheteur" and v is not None and v.valeur and v.valeur.startswith("FR") and extraire_siren(v.valeur):
        sv = e.fab.valeur("acheteur.siren", lec, confiance=v.confiance)
        if sv is not None and corrigee is not None:
            sv = sv.model_copy(update={"valeur": extraire_siren(corrigee)})
        e.champs.acheteur.siren = sv


def _vendeur(e: _Etat) -> None:
    vue, fab, ch = e.vue, e.fab, e.champs
    if not vue.pages:
        return
    p = vue.pages[0]
    t_ach = chercher(vue, LIB_ACHETEUR, pages=[p.numero])
    limite = t_ach[0].ligne.rang if t_ach else min(len(p.lignes), 6)
    bandeaux = lignes_bandeau(vue, entetes_repetes=False)
    t_v = [t for t in chercher(vue, LIB_VENDEUR, pages=[p.numero]) if (p.numero, t.ligne.rang) not in bandeaux]
    # un libellé « vendeur » placé après le pavé acheteur (« Expediteur: » d'un transitaire en pied) n'ouvre pas
    # le pavé de l'émetteur
    t_v = t_v if t_v and t_v[0].ligne.rang < (t_ach[0].ligne.rang if t_ach else 99) else []
    if t_v:
        lignes = pave(t_v[0], fin=LIB_FIN_PAVE, exclus=e.entetes | bandeaux)
    else:
        # sans libellé : premières lignes de la page, bandeaux et en-têtes répétés exclus (D-953)
        lignes = [(li, list(li.segments[0].mots)) for li in p.lignes[:limite]
                  if li.segments and (p.numero, li.rang) not in bandeaux]
    titre = _L.TITRE
    for li, ms in lignes:
        # un titre collé au nom (« Société X   INVOICE ») : on garde les mots qui le précèdent
        k_titre = next((k for k, m in enumerate(ms) if titre.search(cle_texte(m.texte))), None)
        if k_titre == 0 and not t_v and len(li.segments) > 1 and ms and ms[0] is li.segments[0].mots[0]:
            # titre à gauche, nom de l'émetteur à droite (« HANDELSFACTUUR   Société X N.V. », D-2004)
            ms = list(li.segments[1].mots)
            k_titre = next((k for k, m in enumerate(ms) if titre.search(cle_texte(m.texte))), None)
            if any(m.texte.endswith(":") for m in ms):
                k_titre = 0
        if k_titre is not None:
            ms = ms[:k_titre]
        txt = cle_texte(" ".join(m.texte for m in ms))
        if not ms or not re.search(r"[a-z]{3}", txt) or re.match(r"^[\d\W]", txt):
            continue
        # couple « Date: … » ou identifiant (« CHE-000.000.001 MWST ») : pas un nom (D-2004)
        pas_un_nom = not t_v and (re.fullmatch(r"[^\W\d_][\w.\-/]*:", ms[0].texte) is not None
                                  or sum(c.isdigit() for c in txt) * 2 > sum(c.isalnum() for c in txt))
        if ch.vendeur.nom is None and not pas_un_nom and _nom_plausible(ms):
            lec_v = lecture_mots(ms, p, li)
            # sans libellé « vendeur », le nom est présumé (première ligne de l'en-tête)
            ch.vendeur.nom = fab.valeur("vendeur.nom", lec_v, type_valeur=TypeValeur.texte,
                                        confiance=min(0.9 if t_v else 0.8, confiance_mots(lec_v)))
        r = lire_tva_mots(ms)
        if r is not None and ch.vendeur.tva is None:
            lec = lecture_mots(ms[r[0]:r[1]], p, li)
            ch.vendeur.tva = fab.valeur("vendeur.tva", lec, confiance=_conf_tva(lec))


# --- tableau des lignes -------------------------------------------------------------------------------------


def _reperer_entetes(e: _Etat) -> None:
    """En-tête du tableau des lignes de chaque page (première ligne reconnue), colonnes nettoyées (mots soudés,
    code de devise accolé au libellé d'une colonne de prix, D-2002) ; codes de devise lus dans l'en-tête ou sur
    la ligne juste dessous (« (USD) » sous « UNIT PRICE »)."""
    for p in e.vue.pages:
        for li in p.lignes:
            li_s = scinder_mots_colles(li)
            cols = reconnaitre_entete(li_s, VOCAB_COLONNES)
            if not cols or not ({"montant", "quantite"} & {c.type for c in cols}):
                continue
            cols, codes = nettoyer_colonnes(cols, li_s.mots)
            e.entetes_tab[p.numero] = (li, cols)
            mots_codes = [m for m in li.mots if m.texte.strip("():") in codes]
            if li.rang + 1 < len(p.lignes):
                dessous = p.lignes[li.rang + 1]
                if dessous.mots and len(codes_devise_libelle(dessous.mots)) == len(dessous.mots):
                    mots_codes += list(dessous.mots)
            for m in mots_codes:
                ligne = li if m in li.mots else p.lignes[li.rang + 1]
                e.codes_entete.append((m.texte.strip("():"), lecture_mots([m], p, ligne)))
            break


def _est_debut(cellules) -> bool:
    mont = cellules.get("montant", [])
    if mont and any(re.search(r"\d", m.texte) for m in mont):
        return True
    num = cellules.get("numero_ligne", [])
    if bool(num) and bool(re.fullmatch(r"\d{1,3}\.?", num[0].texte)) and len(cellules) >= 3:
        return True
    # rangée dont le montant est illisible (OCR) : référence d'article et quantité lues (D-2009)
    ref = [m.texte.strip("|[]") for m in cellules.get("reference_article", [])]
    qte = cellules.get("quantite", [])
    return (any(re.search(r"\d", t) and re.search(r"[A-Za-z]", t) and len(t) >= 4 for t in ref[:1])
            and bool(qte) and bool(re.fullmatch(r"\d[\d.,' ]*", qte[0].texte)))


def _a_chiffre(r: RangeeTableau, typ: str) -> bool:
    return any(re.search(r"\d", m.texte) for m in r.mots(typ))


def _recoller_montants(rs: list[RangeeTableau]) -> list[RangeeTableau]:
    """Rangée ouverte sur sa référence et sa quantité dont le montant est imprimé (lu par l'OCR) une ligne plus
    bas, seul : la ligne du montant est rattachée à la rangée au lieu d'en ouvrir une (D-2009)."""
    out: list[RangeeTableau] = []
    for r in rs:
        seul = {t for t, ms in r.cellules.items() if any(re.search(r"\w", m.texte) for m in ms)} <= {
            "montant", "prix_unitaire", "inconnue"}
        if out and seul and _a_chiffre(r, "montant") and not _a_chiffre(out[-1], "montant") \
                and _a_chiffre(out[-1], "quantite"):
            prec = out[-1]
            for typ, ms in r.cellules.items():
                prec.cellules.setdefault(typ, []).extend(ms)
            prec.lignes.extend(r.lignes)
            continue
        out.append(r)
    return out


def _est_fin(li: VueLigne) -> bool:
    return any(_FIN_TABLEAU.match(s.cle) for s in li.segments)


def _tableau(e: _Etat) -> None:
    vue = e.vue
    colonnes_prec: list[Colonne] | None = None
    rangees: list[RangeeTableau] = []
    for p in vue.pages:
        trouve = e.entetes_tab.get(p.numero)
        if trouve is None:
            continue
        li, cols = trouve
        e.entetes.add((p.numero, li.rang))
        colonnes_prec = cols
        rs, fin = lire_tableau(p, li.rang, cols, est_debut=_est_debut, est_fin=_est_fin)
        rs = _recoller_montants(rs)
        e.fin_tableau[p.numero] = fin
        for r in rs:
            for x in r.lignes:
                e.lignes_tableau.add((p.numero, x.rang))
        rangees.extend(rs)
    if colonnes_prec is None:
        rangees = _rangees_sans_entete(e)
        if not rangees:
            e.avert.append("tableau_lignes_non_reconnu")
            return
        e.avert.append("tableau_lu_sans_entete")
        for k, r in enumerate(rangees):
            ln = _ligne(e, r, k)
            for nom, v in list(ln):
                if isinstance(v, ValeurSourcee):  # colonnes présumées : jamais une lecture sûre
                    setattr(ln, nom, v.model_copy(update={"confiance": min(v.confiance, 0.6)}))
            e.champs.lignes.append(ln)
        return
    for k, r in enumerate(rangees):
        e.champs.lignes.append(_ligne(e, r, k))
    _origine_document(e)


def _accepte_pays(mots) -> tuple[int, int] | None:
    """Pays : code entre parenthèses (« China (CN) »), sinon nom ou code reconnu (un à trois mots)."""
    for k, m in enumerate(mots[:6]):
        mm = re.fullmatch(r"\(([A-Z]{2})\)[.,;]?", m.texte)
        if mm and country_to_iso2(mm.group(1)):
            return k, k + 1
    for n in (3, 2, 1):
        if len(mots) >= n and country_to_iso2(" ".join(m.texte for m in mots[:n]).strip(".,;")):
            return 0, n
    return None


def _origine_document(e: _Etat) -> None:
    """Facture sans colonne d'origine : une origine déclarée pour toute la facture (« Country of origin: China
    (CN) », « Ursprungsland: … ») est reportée sur chaque ligne (lecture ancrée sur cette mention ; confiance
    plafonnée à 0,85 : la mention peut ne pas couvrir toutes les lignes, D-2008)."""
    if not e.champs.lignes or any(ln.pays_origine is not None for ln in e.champs.lignes):
        return
    if any(c.type == "origine" for _li, cols in e.entetes_tab.values() for c in cols):
        return
    lec = _premier(e.vue, _L.LIB_ORIGINE_DOC, _accepte_pays, dessous=False)
    if lec is None:
        return
    lec = Lecture(tuple(m for m in lec.mots), lec.page, lec.methode, contexte=lec.contexte,
                  texte_force=lec.texte.strip("().,;"))
    for k, ln in enumerate(e.champs.lignes):
        v = e.fab.valeur(f"lignes[{k}].pays_origine", lec, confiance=min(0.85, confiance_mots(lec)))
        if v is not None and v.valeur:
            ln.pays_origine = v


_BRUIT = re.compile(r"^[|_—–\-~.,:;'\"“”‘’°*()\[\]{}]+$")


def _rangees_sans_entete(e: _Etat) -> list[RangeeTableau]:
    """Repli quand l'en-tête du tableau est illisible : une ligne d'article est reconnue à sa forme
    (n° de ligne en tête, montant en fin, quantité × prix = montant ou code marchandise présent) et ses
    cellules sont attribuées de droite à gauche. Les valeurs ainsi lues ont une confiance ≤ 0,60."""
    out: list[RangeeTableau] = []
    for p in e.vue.pages:
        for li in p.lignes:
            if _est_fin(li) or (p.numero, li.rang) in e.entetes:
                continue
            mots = [m for m in li.mots if not _BRUIT.match(m.texte)]
            if len(mots) < 4:
                continue
            m0 = re.fullmatch(r"\W{0,2}(\d{1,3})\W{0,2}", mots[0].texte)
            if not m0:
                continue
            nombres = [n for n in nombres_dans(mots) if not n.tronque and n.i > 0]
            if len(nombres) < 2:
                continue
            mt, pu = nombres[-1], nombres[-2]
            if mt.j < len(mots) - 1:
                continue  # le montant termine la ligne
            if (e.devise is None or exposant_devise(e.devise) > 0) and not re.search(r"\d[.,]\d{2}\)?$", mt.texte):
                continue  # séparateur décimal perdu par l'OCR : montant illisible
            v_mt = lire_montant_mots(mots[mt.i:mt.j], vue=e.vue, devise=e.devise)
            v_pu = lire_montant_mots(mots[pu.i:pu.j], vue=e.vue, devise=e.devise)
            cellules: dict[str, list] = {"numero_ligne": [mots[0]], "montant": list(mots[mt.i:mt.j]),
                                         "prix_unitaire": list(mots[pu.i:pu.j])}
            fin_desc = pu.i
            coherent = False
            for q in reversed(nombres[:-2]):
                v_q = lire_montant_mots(mots[q.i:q.j], vue=e.vue, devise=None, rejeter_masse=False)
                if v_q and v_mt and v_pu and abs(v_q[2] * v_pu[2] - v_mt[2]) <= Decimal("0.011"):
                    cellules["quantite"] = list(mots[q.i:q.j])
                    if q.j < pu.i and re.fullmatch(r"[A-Za-z]{1,6}\.?", mots[q.j].texte):
                        cellules["unite"] = [mots[q.j]]
                    fin_desc = q.i
                    coherent = True
                    break
            k = 1
            if k < fin_desc and re.search(r"\d", mots[k].texte) and re.search(r"[A-Za-z]", mots[k].texte) \
                    and "-" in mots[k].texte:
                cellules["reference_article"] = [mots[k]]
                k += 1
            reste = list(mots[k:fin_desc])
            if reste and re.fullmatch(r"\(?[A-Z]{2}\)?", reste[-1].texte) and country_to_iso2(reste[-1].texte.strip("()")):
                cellules["origine"] = [reste.pop()]
            code: list = []
            while reste and re.fullmatch(r"[\d.\s\-/]+", reste[-1].texte):
                code.insert(0, reste.pop())
            if code and code_marchandise(" ".join(m.texte for m in code)):
                cellules["code"] = code
            elif code:
                reste.extend(code)
            if reste:
                cellules["description"] = reste
            if not (coherent or "code" in cellules):
                continue
            out.append(RangeeTableau(cellules, [li], p))
    return out


def _lec_cellule(r: RangeeTableau, typ: str, *, premiere_ligne: bool = False) -> Lecture | None:
    mots = r.mots(typ)
    if premiere_ligne:
        mots = [m for m in mots if m in r.lignes[0].mots]
    if not mots:
        return None
    li = next((x for x in r.lignes if mots[0] in x.mots), r.lignes[0])
    return lecture_mots(mots, r.page, li)


def _quantite_sous_unite(e: _Etat, r: RangeeTableau) -> float | None:
    """En-tête de quantité illisible (OCR) mais colonne d'unité reconnue : « 50 kg » lu sous « Eenh. » donne la
    quantité et l'unité (confiance plafonnée à 0,85, D-2009). Retourne le plafond, ``None`` sans changement."""
    entete = e.entetes_tab.get(r.page.numero)
    if entete is None:
        return None
    types = {c.type for c in entete[1]}
    if "quantite" in types or "unite" not in types:
        return None
    mots = [m for m in r.mots("unite") if m in r.lignes[0].mots]
    nb = nombres_dans(mots)
    if not nb or nb[0].i != 0 or nb[0].tronque:
        return None
    r.cellules["quantite"] = list(mots[:nb[0].j])
    r.cellules["unite"] = list(mots[nb[0].j:])
    return 0.85


def _sans_filets(r: RangeeTableau) -> None:
    """OCR : filets de tableau lus comme du texte (« | », « [ », « _ ») retirés des cellules (« 1'000 | kg »,
    « TW | ») (D-2009)."""
    if r.page.methode is not Methode.ocr:
        return
    for typ, ms in list(r.cellules.items()):
        r.cellules[typ] = [m for m in ms if not _BRUIT.match(m.texte)]


def _ligne(e: _Etat, r: RangeeTableau, k: int) -> LigneFactureCommerciale:
    fab = e.fab
    ln = LigneFactureCommerciale()
    base = f"lignes[{k}]"
    _sans_filets(r)
    plafond_q = _quantite_sous_unite(e, r)
    lec = _lec_cellule(r, "numero_ligne", premiere_ligne=True)
    if lec is not None and re.fullmatch(r"\d{1,4}\.?", lec.texte):
        ln.numero_ligne = fab.valeur(f"{base}.numero_ligne", lec, type_valeur=TypeValeur.entier)
    lec = _lec_cellule(r, "reference_article", premiere_ligne=True)
    if lec is not None:
        ln.reference_article = fab.valeur(f"{base}.reference_article", lec, confiance=_conf_ref(lec))
    _deborder(r, "code", "description")
    lec = _lec_cellule(r, "description")
    if lec is not None:
        ln.description = fab.valeur(f"{base}.description", lec, type_valeur=TypeValeur.texte)
    lec = _lec_cellule(r, "code")
    if lec is not None:
        ln.code_marchandise_imprime = _code(e, lec, f"{base}.code_marchandise_imprime", r)
    lec = _lec_cellule(r, "origine", premiere_ligne=True)
    if lec is not None and country_to_iso2(lec.texte.strip("()")):
        ln.pays_origine = fab.valeur(f"{base}.pays_origine", lec, confiance=confiance_mots(lec, plafond_ocr=0.9))
    # quantité (+ unité si colonne voisine)
    lq = _lec_cellule(r, "quantite", premiere_ligne=True)
    lu = _lec_cellule(r, "unite", premiere_ligne=True)
    if lq is not None:
        nb = nombres_dans(lq.mots)
        if nb and not nb[0].tronque:
            mots = list(lq.mots[nb[0].i:])
            lecq = Lecture(tuple(mots), lq.page, lq.methode, contexte=lq.contexte)
            vq = fab.valeur(f"{base}.quantite", lecq)
            if vq is not None and lu is not None and len(lu.mots) == 1 and vq.unite is None:
                un = _unite(lu.texte, ocr=lu.methode is Methode.ocr)
                if un.connue or not re.search(r"\d", lu.texte):
                    vq = vq.model_copy(update={"unite": un.code, "unite_brute": un.brut})
            if vq is not None and vq.unite == "inconnue" and vq.unite_brute and lq.methode is Methode.ocr:
                un = _unite(vq.unite_brute, ocr=True)
                if un.connue:
                    vq = vq.model_copy(update={"unite": un.code, "confiance": min(vq.confiance, 0.8)})
            if vq is not None and (vq.unite == "inconnue" or (lu is not None and vq.unite is None)):
                # unité imprimée mais non reconnue : la quantité (valeur + unité) est douteuse
                vq = vq.model_copy(update={"confiance": min(vq.confiance, 0.6)})
            if vq is not None and plafond_q is not None:
                vq = vq.model_copy(update={"confiance": min(vq.confiance, plafond_q)})
            ln.quantite = vq
    for typ, chemin in (("masse_nette", "masse_nette"), ("masse_brute", "masse_brute")):
        lec = _lec_cellule(r, typ, premiere_ligne=True)
        if lec is not None and not lec.texte.endswith("…") and nombres_dans(lec.mots):
            sep, presume = separateur_masse(e.vue, lec.texte)
            ln_v = fab.valeur(f"{base}.{chemin}", lec, separateur=sep,
                              confiance=min(confiance_mots(lec), 0.7) if presume else None)
            setattr(ln, chemin, ln_v)
    lp = _lec_cellule(r, "prix_unitaire", premiere_ligne=True)
    if lp is not None:
        res = lire_montant_mots(lp.mots, vue=e.vue, devise=e.devise)
        if res is not None:
            lec = Lecture(lp.mots[res[0]:res[1]], lp.page, lp.methode, contexte=lp.contexte)
            ln.prix_unitaire = fab.valeur(f"{base}.prix_unitaire", lec, devise=e.devise)
    lm = _lec_cellule(r, "montant", premiere_ligne=True)
    plafond_mt = None
    if (lm is None or not re.search(r"\d", lm.texte)) and len(r.lignes) > 1:
        lm = _lec_cellule(r, "montant")  # montant imprimé sous la ligne de la rangée (D-2009)
        plafond_mt = 0.85
    if lm is not None:
        res = lire_montant_mots(lm.mots, vue=e.vue, devise=e.devise)
        if res is not None:
            lec = Lecture(lm.mots[res[0]:res[1]], lm.page, lm.methode, contexte=lm.contexte)
            ln.montant_ligne = fab.valeur(f"{base}.montant_ligne", lec, devise=e.devise)
            if plafond_mt is not None and ln.montant_ligne is not None:
                ln.montant_ligne = ln.montant_ligne.model_copy(
                    update={"confiance": min(ln.montant_ligne.confiance, plafond_mt)})
    _recouper_ligne(ln)
    return ln


def _unite(texte: str, *, ocr: bool = False):
    """Unité normalisée ; une unité tronquée à l'impression (« pai… », « pai.. » en OCR) est reconnue si
    tous les libellés qui la prolongent désignent la même unité ; en OCR, une lecture à une lettre près
    d'un libellé d'au moins 3 lettres (« pes » pour « pcs ») est admise si elle est sans ambiguïté."""
    from controldone.normalize import units as _u

    t = texte.strip(",;:|[]")
    un = normalize_unit(t.strip("."))
    if un.connue:
        return un
    table = getattr(_u, "_UNITES", {})
    tronque = t.endswith("…") or (ocr and t.endswith(".."))
    base = cle_texte(t.replace("…", "").rstrip("."))
    if tronque and len(base) >= 2:
        codes = {code for lib, code in table.items() if lib.startswith(base)}
        if len(codes) == 1:
            return type(un)(code=codes.pop(), brut=texte)
    if ocr and len(base) >= 3:
        codes = {code for lib, code in table.items() if len(lib) == len(base) and len(lib) >= 3
                 and sum(a != b for a, b in zip(lib, base, strict=True)) == 1}
        if len(codes) == 1:
            return type(un)(code=codes.pop(), brut=texte)
    return un


def _deborder(r: RangeeTableau, typ: str, vers: str) -> None:
    """Mots alphabétiques débordant d'une colonne de texte (description longue) dans la colonne ``typ``
    (code) : rendus à la colonne ``vers``."""
    mots = r.cellules.get(typ, [])
    garde = [m for m in mots if re.search(r"\d", m.texte)]
    if len(garde) == len(mots):
        return
    rendus = [m for m in mots if m not in garde]
    r.cellules[typ] = garde
    r.cellules.setdefault(vers, []).extend(rendus)
    r.cellules[vers].sort(key=lambda m: (round(m.y0, 3), m.x0))


def _code_sans_debord(r: RangeeTableau, mots: list) -> tuple[list, bool]:
    """Chiffres d'une désignation voisine débordant dans la colonne du code (« Taladro 18 V | 8467.21 »,
    « Martillo 500 g 8205.20.00.00 », D-2007) : sur la première ligne de la rangée, seul le dernier groupe de
    mots contigus (même segment, sans mot d'une autre colonne entre eux) est gardé ; à défaut de code valide,
    le plus long suffixe qui forme un code de 6, 8 ou 10 chiffres. Retourne (mots, vrai si des mots sont écartés)."""
    li0 = r.lignes[0]
    premiers = [m for m in mots if m in li0.mots]
    suite = [m for m in mots if m not in li0.mots]
    if len(premiers) >= 2:
        ordre = li0.mots
        pos = {id(m): k for k, m in enumerate(ordre)}
        seg = {id(m): s.rang for s in li0.segments for m in s.mots}
        groupes: list[list] = [[premiers[0]]]
        for a, b in itertools.pairwise(premiers):
            if pos[id(b)] == pos[id(a)] + 1 and seg[id(a)] == seg[id(b)]:
                groupes[-1].append(b)
            else:
                groupes.append([b])
        if len(groupes) > 1:
            premiers = groupes[-1]
    garde = premiers + suite
    if code_marchandise(" ".join(m.texte for m in garde)) is None:
        for k in range(1, len(premiers)):
            essai = premiers[k:] + suite
            if code_marchandise(" ".join(m.texte for m in essai)) is not None:
                garde = essai
                break
    return garde, len(garde) < len(mots)


def _code(e: _Etat, lec: Lecture, chemin: str, r: RangeeTableau | None = None) -> ValeurSourcee | None:
    """Code marchandise imprimé : chiffres et ponctuation, 6 à 10 chiffres ; un code coupé sur deux lignes
    physiques est recollé (valeur non ancrée, confiance réduite)."""
    mots = [m for m in lec.mots if re.fullmatch(r"[\d.\s\-/]+", m.texte)]
    if not mots:
        return e.fab.valeur(chemin, lec, confiance=min(0.3, confiance_mots(lec)))
    plafond = 1.0
    if r is not None:
        mots, ecartes = _code_sans_debord(r, mots)
        if ecartes:
            plafond = 0.85
    lec2 = Lecture(tuple(mots), lec.page, lec.methode, contexte=lec.contexte)
    chiffres = re.sub(r"\D", "", lec2.texte)
    conf = min(plafond, confiance_mots(lec2, plafond_ocr=0.85))
    if code_marchandise(lec2.texte) is None:
        conf = min(conf, 0.3)
        if len(chiffres) == 9:
            conf = min(conf, 0.2)  # zéro final perdu : jamais reconstitué ici (§7.4)
    return e.fab.valeur(chemin, lec2, confiance=conf, type_valeur=TypeValeur.code)


def _dec(v: ValeurSourcee | None) -> Decimal | None:
    if v is None or v.valeur is None:
        return None
    try:
        return Decimal(v.valeur)
    except Exception:
        return None


def _recouper_ligne(ln: LigneFactureCommerciale) -> None:
    q, pu, mt = _dec(ln.quantite), _dec(ln.prix_unitaire), _dec(ln.montant_ligne)
    if q is None or pu is None or mt is None:
        return
    # recoupement strict : montant = quantité × prix au centime près (un prix unitaire arrondi qui
    # n'explique le montant qu'à l'arrondi près ne relève pas la confiance)
    ok = abs(q * pu - mt) <= Decimal("0.011")
    if not ok and ln.prix_unitaire.methode is Methode.ocr and re.fullmatch(r"\d+", ln.prix_unitaire.valeur_brute or ""):
        # séparateur décimal du prix perdu par l'OCR (« 485 » pour « 4.85 ») : le prix qui redonne exactement le
        # montant est retenu, confiance plafonnée à 0,60 (D-2009) ; montant et quantité inchangés
        for k in (1, 2, 3, 4):
            cand = pu.scaleb(-k)
            if q != 0 and abs(q * cand - mt) <= Decimal("0.0051"):
                ln.prix_unitaire = ln.prix_unitaire.model_copy(update={"valeur": str(cand), "confiance": min(
                    ln.prix_unitaire.confiance, 0.6)})
                return
    exp = pu.as_tuple().exponent
    demi = Decimal(1).scaleb(exp if isinstance(exp, int) else -2) / 2
    if not ok and abs(q * pu - mt) <= q * demi + Decimal("0.011"):
        return
    for nom in ("quantite", "prix_unitaire", "montant_ligne"):
        v: ValeurSourcee = getattr(ln, nom)
        if nom == "quantite" and v.unite == "inconnue":
            continue  # l'unité reste douteuse : le recoupement ne porte que sur le nombre
        if ok:
            c = max(v.confiance, 0.97 if v.methode is not Methode.ocr else 0.92) if v.ancree else v.confiance
        else:
            c = min(v.confiance, 0.8)
        setattr(ln, nom, v.model_copy(update={"confiance": c}))


# --- pied : totaux, sous-totaux, masses, colis ---------------------------------------------------------------


@dataclass
class _Candidat:
    lecture: Lecture
    valeur: Decimal
    classe: str  # douane | payable | page | sous_total:<type>
    trouve: Trouve


def _candidats(e: _Etat) -> list[_Candidat]:
    vue = e.vue
    out: list[_Candidat] = []
    acc = accepte_montant(vue, e.devise)
    vus: set[tuple[int, int, int]] = set()

    def ajouter(t: Trouve, classe: str) -> None:
        cle = (t.page.numero, t.ligne.rang, t.segment.rang)
        if cle in vus or (t.page.numero, t.ligne.rang) in e.lignes_tableau or (t.page.numero, t.ligne.rang) in e.entetes:
            return
        lec = valeur_apres(vue, t, acc, lignes_dessous=1, marge_dessous=0.4, dessous_seul=True)
        if lec is None:
            return
        res = lire_montant_mots(lec.mots, vue=vue, devise=e.devise)
        if res is None:
            return
        vus.add(cle)
        out.append(_Candidat(lec, res[2], classe, t))

    for t in chercher(vue, LIB_TOTAL_PAGE):
        ajouter(t, "page")
    for t in chercher(vue, LIB_TOTAL_DOUANE):
        ajouter(t, "douane")
    for typ, mots in LIB_SOUS_TOTAUX:
        for t in chercher(vue, mots, exclure=_EXCLU_SOUS_TOTAL):
            ajouter(t, f"sous_total:{typ.value}")
    for t in chercher(vue, LIB_TOTAL, exclure=_EXCLU_TOTAL):
        ajouter(t, "payable")
    out.sort(key=lambda c: (c.trouve.page.numero, c.trouve.ligne.rang, c.trouve.segment.rang))
    return out


def _pied(e: _Etat) -> None:
    vue, fab, ch = e.vue, e.fab, e.champs
    cands = _candidats(e)
    # sous-totaux (lignes de pied)
    vus_types: set[str] = set()
    for c in cands:
        if not c.classe.startswith("sous_total:"):
            continue
        typ = TypeSousTotal(c.classe.split(":", 1)[1])
        k = len(ch.sous_totaux)
        lib = lecture_mots(c.trouve.segment.mots[: max(1, c.trouve.apres)], c.trouve.page, c.trouve.ligne)
        st = SousTotal(type=typ,
                       libelle=fab.valeur(f"sous_totaux[{k}].libelle", lib, type_valeur=TypeValeur.texte),
                       montant=fab.valeur(f"sous_totaux[{k}].montant", c.lecture, devise=e.devise,
                                          type_valeur=TypeValeur.montant))
        ch.sous_totaux.append(st)
        vus_types.add(typ.value)
    # total général
    douane = [c for c in cands if c.classe == "douane"]
    payables = [c for c in cands if c.classe == "payable"]
    retenu = douane[-1] if douane else (payables[-1] if payables else None)
    somme_lignes = _somme_lignes(ch)
    if retenu is not None:
        conf = _confiance_total(e, retenu, payables, somme_lignes, cands)
        v = fab.valeur("total_facture", retenu.lecture, confiance=conf, devise=e.devise,
                       type_valeur=TypeValeur.montant)
        if v is not None:
            v = v.model_copy(update={"total_origine": TotalOrigine.imprime})
        ch.total_facture = v
    elif somme_lignes is not None:
        sources = [ln.montant_ligne for ln in ch.lignes if ln.montant_ligne is not None]
        ch.total_facture = deriver_somme(
            "facture_commerciale.total_facture", sources, document_id=fab.document_id, extracteur=INFO,
            unite=e.devise, total_reconstruit=True, regle="somme_lignes",
            id_valeur=fab.ids.nouveau("vs") if fab.ids is not None else None,
        )
        e.avert.append("total_reconstruit")
    # masses et colis (hors tableau)
    exclure_tab = {(p, r) for p, r in e.lignes_tableau} | e.entetes
    for chemin, libs, champ_ligne in (("masse_brute_totale", LIB_POIDS_BRUT, "masse_brute"),
                                      ("masse_nette_totale", LIB_POIDS_NET, "masse_nette")):
        lec = _premier_hors(e, libs, accepte_masse(vue), exclure_tab, partout=True)
        if lec is not None:
            sep, presume = separateur_masse(vue, lec.texte)
            conf = _conf_masse(e, lec, champ_ligne, sep)
            if presume:
                conf = min(conf, 0.7)
            setattr(ch, chemin, fab.valeur(chemin, lec, confiance=conf, separateur=sep))
    lec = _premier_hors(e, LIB_COLIS, accepte_entier, exclure_tab)
    if lec is None:
        # libellé nu, seul dans son segment (« Packages   12 ») : valeur à droite seulement (D-950)
        for t in chercher(e.vue, LIB_COLIS_NU):
            if (t.page.numero, t.ligne.rang) in exclure_tab:
                continue
            lec = valeur_apres(e.vue, t, accepte_entier, dessous=False)
            if lec is not None:
                break
    if lec is not None:
        ch.nombre_colis = fab.valeur("nombre_colis", lec, type_valeur=TypeValeur.entier)


def _premier_hors(e: _Etat, libelles, accepte, exclus, *, partout: bool = False) -> Lecture | None:
    for t in chercher(e.vue, libelles):
        if (t.page.numero, t.ligne.rang) in exclus:
            continue
        lec = valeur_apres(e.vue, t, accepte, lignes_dessous=1)
        if lec is not None:
            return lec
    if partout:
        # libellé au milieu d'un segment (« Net weight: 1.0 kg Gross weight: 1.2 kg », D-2005) : valeur dans le
        # reste du segment seulement
        for t in chercher_partout(e.vue, libelles):
            if (t.page.numero, t.ligne.rang) in exclus or t.apres == 0:
                continue
            lec = valeur_apres(e.vue, t, accepte, droite=False, dessous=False)
            if lec is not None:
                return lec
    return None


def _conf_masse(e: _Etat, lec: Lecture, champ: str, sep: str | None) -> float:
    conf = confiance_mots(lec)
    vals = [_dec(getattr(ln, champ)) for ln in e.champs.lignes]
    if vals and all(v is not None for v in vals):
        from controldone.normalize import parse_weight_kg

        tot = parse_weight_kg(lec.texte, separateur_decimal=sep)
        if tot is not None and abs(sum(vals) - tot) <= Decimal("0.0015") * len(vals):  # type: ignore[arg-type]
            conf = max(conf, 0.95 if lec.methode is not Methode.ocr else 0.92)
    return conf


def _somme_lignes(ch: ChampsFactureCommerciale) -> Decimal | None:
    if not ch.lignes:
        return None
    vals = [_dec(ln.montant_ligne) for ln in ch.lignes]
    if any(v is None for v in vals):
        return None
    return sum(vals, Decimal(0))  # type: ignore[arg-type]


def _confiance_total(e: _Etat, retenu: _Candidat, payables: list[_Candidat], somme: Decimal | None,
                     cands: list[_Candidat]) -> float:
    lec = retenu.lecture
    natif = lec.methode is not Methode.ocr
    conf = 0.95 if natif else confiance_mots(lec)
    total = retenu.valeur
    # recoupement : lignes (+ pieds) = total, ou sous-total marchandises + pieds = total
    pieds = Decimal(0)
    marchandises = None
    for c in cands:
        if not c.classe.startswith("sous_total:"):
            continue
        typ = c.classe.split(":", 1)[1]
        signe_neg = parse_amount(c.lecture.texte) is not None and parse_amount(c.lecture.texte).negatif
        if typ == "marchandises":
            marchandises = c.valeur
        elif typ == "remise" or signe_neg:
            pieds -= c.valeur
        else:
            pieds += c.valeur
    tol = Decimal("0.011")
    coherent = None
    bases = [b for b in (somme, marchandises) if b is not None]
    if bases:
        coherent = any(abs(b + pieds - total) <= tol or abs(b - total) <= tol for b in bases)
        if somme is not None and marchandises is not None and abs(somme - marchandises) > tol:
            coherent = coherent and abs(marchandises + pieds - total) <= tol
    if coherent:
        conf = 0.98 if natif else max(min(0.95, conf + 0.1), 0.92) if (lec.confiance_ocr or 0) >= 0.5 else conf
    elif coherent is False:
        conf = min(conf, 0.85 if natif else 0.6)
    else:
        conf = min(conf, 0.92 if natif else 0.8)
    if retenu.classe == "payable" and len({c.valeur for c in payables}) > 1 and not coherent:
        conf = min(conf, 0.75)
    if e.devise is None:
        conf = min(conf, 0.85)
    if not natif and not coherent and _separateur_decimal_douteux(lec.texte, total, e.devise):
        conf = min(conf, 0.8)
    return conf



def _separateur_decimal_douteux(texte: str, valeur: Decimal, devise: str | None) -> bool:
    """Montant OCR ≥ 1000 lu sans séparateur décimal pour une devise à décimales (ou inconnue) : le
    séparateur a pu être perdu (facteur 100). Seul un recoupement arithmétique à la même échelle (somme des
    lignes, sous-total) autorise alors une confiance > 0,80 (§8.5.1 condition 3)."""
    if devise is not None and exposant_devise(devise) == 0:
        return False
    if abs(valeur) < 1000:
        return False
    n = exposant_devise(devise) if devise is not None else 2
    return re.search(rf"\d[.,]\s?\d{{{n}}}\D*$", texte.strip()) is None
