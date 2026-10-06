"""Vocabulaire multilingue des factures commerciales (fr, en, es, de, it, nl, pt, pl) — données seulement.

Compléments au vocabulaire historique de ``facture_commerciale`` (anglais, français, espagnol) : libellés
d'en-tête (numéro, date, devise, conditions de livraison, titre de transport), pavés des parties (acheteur,
livré à, vendeur), masses, colis, totaux et sous-totaux, en-têtes de colonnes du tableau des lignes et titres
de document (« Handelsrechnung », « Fattura proforma »…). Aucune règle propre à une mise en page : ce sont les
mots usuels des factures dans ces langues. Les textes sont comparés sans accents, en minuscules
(``normalize.text.cle_texte``) ; les mots d'en-tête de colonne sont comparés sans « . » ni « : » finaux.
"""

from __future__ import annotations

import re

__all__ = [
    "ACHETEUR",
    "COLONNES",
    "DESTINATAIRE",
    "EXCLU_TOTAL",
    "FIN_PAVE",
    "FIN_TABLEAU",
    "LIB_COLIS",
    "LIB_DATE",
    "LIB_DEVISE",
    "LIB_INCOTERM",
    "LIB_NUMERO",
    "LIB_POIDS_BRUT",
    "LIB_POIDS_NET",
    "LIB_TOTAL",
    "LIB_TOTAL_DOUANE",
    "LIB_TRANSPORT",
    "PRO_FORMA",
    "SOUS_TOTAUX",
    "TITRE",
    "VENDEUR",
]

_NO = r"(?:no\b\.?|n\.?\s?(?:[°º]|o(?![a-z]))\.?|n\.|nr\.?|nro\.?|num(?:ero|ber|mer)?\.?|#)"


def _m(*expr: str) -> list[re.Pattern[str]]:
    return [re.compile(e) for e in expr]


# --- en-tête ---------------------------------------------------------------------------------------------------

LIB_NUMERO = _m(
    rf"(?:handels|proforma-?|pro-forma-?)?rechnung\s*{_NO}\s*:?",
    r"(?:handels|proforma-?)?rechnungs-?\s*(?:nummer|nr\.?)\s*:?",
    rf"fattura(?:\s*(?:commerciale|proforma|pro-forma))?\s*{_NO}\s*:?",
    r"num(?:ero|\.)?\s*(?:di\s*|della\s*)?fattura\s*:?",
    r"(?:handels|proforma)?factuur\s*-?\s*(?:nummer|nr\.?|no\.?)\s*:?",
    r"invoice\s*number\s*:?",
    # pt / pl (D-2507)
    rf"fatura(?:\s*(?:comercial|pro-?\s?forma))?\s*{_NO}\s*:?",
    r"numero\s*da\s*fatura\s*:?",
    rf"(?:faktura\s*[a-z]+\s*)?faktura(?:\s*(?:eksportowa|handlowa|pro\s*forma|vat))?\s*{_NO}\s*:?",
    rf"(?:fatura\s*[a-z]+\s*)?fatura\s*{_NO}\s*:?",
    r"numer\s*faktury\s*:?",
)
LIB_DATE = _m(
    r"(?:rechnungs|liefer)?datum\s*:?",
    r"data(?:\s*(?:della\s*)?fattura|\s*documento|\s*emissione)?\s*:?",
    r"factuurdatum\s*:?",
    r"(?:issue|invoice)\s*date\s*:?",
    r"date\s*of\s*issue\s*:?",
    r"data\s*(?:da\s*fatura|de\s*emissao)\s*:?",
    r"data\s*wystawienia\s*:?",
    r"data\s*sprzedazy\s*:?",
)
LIB_DEVISE = _m(r"wahrung\s*:?", r"valuta\s*:?", r"munt\s*:?", r"moeda\s*:?", r"waluta(?:\s*faktury)?\s*:?")
LIB_INCOTERM = _m(
    r"lieferbedingung(?:en)?\s*:?",
    r"lieferkonditionen\s*:?",
    r"resa(?:\s*merce)?\s*:?",
    r"condizioni\s*di\s*(?:consegna|resa)\s*:?",
    r"termini\s*di\s*resa\s*:?",
    r"leverings(?:voorwaarden|condities)\s*:?",
    r"terms\s*:",
    r"incoterm\s*:?",
    r"condicoes\s*de\s*entrega\s*:?",
    r"warunki\s*dostawy\s*:?",
)
LIB_TRANSPORT = _m(
    rf"(?:cmr-?\s*)?frachtbrief(?:\s*{_NO})?\s*:?",
    rf"luftfrachtbrief(?:\s*{_NO})?\s*:?",
    rf"konnossement(?:\s*{_NO})?\s*:?",
    rf"polizza\s*di\s*carico(?:\s*{_NO})?\s*:?",
    rf"lettera\s*di\s*vettura(?:\s*aerea)?(?:\s*{_NO})?\s*:?",
    rf"(?:lucht)?vrachtbrief(?:\s*{_NO})?\s*:?",
    rf"cognossement(?:\s*{_NO})?\s*:?",
    r"transport\s*document\s*(?:no\.?)?\s*:?",
    r"ref\.?\s*(?:road|air|sea|ocean|rail)\s*:",
    r"carta\s*de\s*porte(?:\s*aereo)?\s*:?",
    r"conhecimento(?:\s*de\s*embarque)?\s*:?",
    r"guia\s*aerea\s*:?",
    r"(?:lotniczy\s*)?list\s*przewozowy\s*:?",
    r"konosament\s*:?",
)

#: Titre du document (début de segment) : jamais le nom du vendeur.
TITRE = re.compile(
    r"\b(invoice|facture|factura|pro ?-?forma|proforma|commercial|comercial|commerciale|page|valeur|value|valor|"
    r"document|documento|handelsrechnung|rechnung|proformarechnung|fattura|handelsfactuur|factuur|"
    r"proformafactuur|fatura|faktura|eksportowa)\b"
)
#: Mention de pro forma dans un titre (« PROFORMA INVOICE », « Fattura proforma », « Proforma-Rechnung »).
PRO_FORMA = re.compile(r"\bpro\s*-?\s*forma|proforma")

# --- parties ---------------------------------------------------------------------------------------------------

ACHETEUR = (
    r"rechnungsempfanger|rechnungsadresse|kaufer|kunde|auftraggeber|intestatario|acquirente|committente|"
    r"factuuradres|koper|klant|afnemer|faturar a|faturado a|adquirente|nabywca|platnik"
)
DESTINATAIRE = (
    r"lieferadresse|lieferanschrift|warenempfanger|empfanger|destinatario merce|luogo di consegna|"
    r"indirizzo di consegna|afleveradres|leveradres|ontvanger|geadresseerde|entregar a|"
    r"local de entrega|odbiorca|miejsce dostawy"
)
VENDEUR = (
    r"verkaufer|lieferant|exporteur|venditore|fornitore|esportatore|mittente|verkoper|leverancier|"
    r"fornecedor|exportador|sprzedawca|eksporter|dostawca"
)
FIN_PAVE = rf"{ACHETEUR}|{DESTINATAIRE}|{VENDEUR}|to \(buyer\)"
#: Libellés de pavé acheteur entre parenthèses (« TO (BUYER): »).
ACHETEUR_PARENTHESE = _m(r"to\s*\(\s*(?:buyer|customer|consignee)\s*\)\s*:?")

# --- masses et colis -------------------------------------------------------------------------------------------

LIB_POIDS_BRUT = _m(
    r"(?:gesamt)?bruttogewicht\s*:?",
    r"brutogewicht\s*:?",
    r"(?:totale\s*)?peso\s*lordo(?:\s*totale)?\s*:?",
    r"total\s*g\.?\s*w\.?\s*:",
    r"gross\s*:?(?=\s*\d[\d.,' ]*\s*kgs?\b)",
    r"masa\s*brutto\s*:?",
    r"waga\s*brutto\s*:?",
)
LIB_POIDS_NET = _m(
    r"(?:gesamt)?nettogewicht\s*:?",
    r"(?:totale\s*)?peso\s*netto(?:\s*totale)?\s*:?",
    r"total\s*n\.?\s*w\.?\s*:",
    r"net\s*:?(?=\s*\d[\d.,' ]*\s*kgs?\b)",
    r"(?:total\s*)?peso\s*liquido(?:\s*total)?\s*:?",
    r"masa\s*netto\s*:?",
    r"waga\s*netto\s*:?",
)
LIB_COLIS = _m(
    r"(?:anzahl\s*(?:der\s*)?)?packstucke\s*:?",
    r"(?:anzahl\s*)?kolli\s*:?",
    r"(?:numero\s*|n\.\s*)?colli\s*:?",
    r"aantal\s*colli\s*:?",
    r"(?:aantal\s*)?pakketten\s*:?",
    r"(?:numero\s*de\s*|n\.?o\s*de\s*)?volumes\s*:",
    r"liczba\s*(?:opakowan|paczek|sztuk\s*ladunku)\s*:?",
)

# --- totaux ------------------------------------------------------------------------------------------------------

LIB_TOTAL = _m(
    r"(?:rechnungs|gesamt|end|brutto)betrag(?:\s*\(?[a-z]{3}\)?(?![a-z]))?\s*:?",
    r"(?:rechnungs|gesamt)summe(?:\s*\(?[a-z]{3}\)?(?![a-z]))?\s*:?",
    r"zu\s*zahlen\s*:?",
    r"zahlbetrag\s*:?",
    r"totale(?:\s*(?:fattura|documento|generale|da\s*pagare|complessivo))?(?:\s*\(?[a-z]{3}\)?(?![a-z]))?\s*:?",
    r"totaal(?:bedrag)?(?:\s*(?:te\s*betalen|factuur))?(?:\s*\(?[a-z]{3}\)?(?![a-z]))?\s*:?",
    r"factuurbedrag(?:\s*\(?[a-z]{3}\)?(?![a-z]))?\s*:?",
    r"te\s*betalen\s*:?",
    r"total\s*due(?:\s*\(?[a-z]{3}\)?(?![a-z]))?\s*:?",
    r"razem(?:\s*do\s*zaplaty)?(?:\s*\(?[a-z]{3}\)?(?![a-z]))?\s*:?",
    r"do\s*zaplaty\s*:?",
    r"total\s*(?:da\s*fatura|a\s*pagar)(?:\s*\(?[a-z]{3}\)?(?![a-z]))?\s*:?",
)
LIB_TOTAL_DOUANE = _m(
    r"zollwert\s*:?",
    r"valore\s*(?:in\s*dogana|doganale)\s*:?",
    r"douanewaarde\s*:?",
)
#: Ajouts à l'exclusion des libellés de total (masses, colis, sous-totaux, frais de pied).
EXCLU_TOTAL = (
    r"zwischensumme|warenwert|totale merc[ei]|subtotaal|subtotale|imponibile|gewicht|\bpeso\b|colli|"
    r"packstucke|aantal|menge|quantita|fracht|vracht|trasporto|\bnolo\b|versicherung|assicurazione|"
    r"verzekering|rabatt|skonto|sconto|korting|verpackung|imball|verpakking|positionen|mercadorias|"
    r"frete|seguro|embalagem|desconto|towarow|ubezpieczenie|opakowan|rabat|upust|masa|liczba|"
    r"contravalor|rownowartosc|equivalent|countervalue|indicativ"
)

SOUS_TOTAUX: dict[str, list[re.Pattern[str]]] = {
    "marchandises": _m(
        r"warenwert\s*:?",
        r"zwischensumme\s*:?",
        r"summe\s*(?:der\s*)?positionen\s*:?",
        r"total(?:e)?\s*merc[ei]\s*:?",
        r"subtotale\s*:?",
        r"subtotaal\s*:?",
        r"goederenwaarde\s*:?",
        r"total\s*(?:das\s*)?mercadorias\s*:?",
        r"valor\s*(?:das\s*)?mercadorias\s*:?",
        r"wartosc\s*towarow\s*:?",
        r"razem\s*towary\s*:?",
    ),
    "fret": _m(
        r"fracht(?:kosten)?\s*:?",
        r"transportkosten\s*:?",
        r"(?:spese\s*di\s*)?trasporto\s*:?",
        r"nolo\s*:?",
        r"vracht(?:kosten)?\s*:?",
        r"verzendkosten\s*:?",
        r"frete\s*:?",
        r"koszty?\s*transportu\s*:?",
    ),
    "assurance": _m(
        r"(?:transport)?versicherung\s*:?", r"assicurazione\s*:?", r"verzekering\s*:?", r"ubezpieczenie\s*:?"
    ),
    "emballage": _m(
        r"verpackung(?:skosten)?\s*:?",
        r"imball(?:o|aggio)\s*:?",
        r"verpakking(?:skosten)?\s*:?",
        r"embalagem\s*:?",
        r"opakowanie\s*:?",
        r"koszty?\s*opakowania\s*:?",
    ),
    "remise": _m(
        r"(?:rabatt|skonto|nachlass|sconto|korting|desconto|rabat|upust)\b(?:\s*\(?[\d.,]+\s*%\)?)?\s*:?"
    ),
    "autre": _m(r"nebenkosten\s*:?", r"altre\s*spese\s*:?", r"overige\s*kosten\s*:?"),
}

#: Ajout à la ligne de fin du tableau des lignes.
FIN_TABLEAU = (
    r"warenwert|zwischensumme|rechnungsbetrag|gesamtbetrag|summe|fracht|versicherung|verpackung|rabatt|"
    r"totale|imballo|sconto|trasporto|assicurazione|subtotaal|totaal|vracht|verzekering|korting|"
    r"nettogewicht|bruttogewicht|peso netto|peso lordo|brutogewicht|lieferbedingungen|resa\b|"
    r"leveringsvoorwaarden|condiciones de entrega|total mercadorias|valor das mercadorias|frete|"
    r"desconto|embalagem|condicoes de entrega|wartosc towarow|ubezpieczenie|opakowanie|rabat|upust|"
    r"razem|do zaplaty|warunki dostawy|masa netto|masa brutto|peso liquido"
)

# --- colonnes du tableau des lignes ---------------------------------------------------------------------------

COLONNES: dict[str, list[str]] = {
    "numero_ligne": ["lfd. nr", "lfd nr", "lp"],
    "reference_article": [
        "art.-nr",
        "art.nr",
        "art-nr",
        "artikelnr",
        "artikel-nr",
        "artikelnummer",
        "artikel",
        "teilenummer",
        "codice",
        "cod. articolo",
        "codice articolo",
        "articolo",
        "artnr",
        "sku",
        "part no",
        "item code",
        "indeks",
        "symbol",
        "ref.",
        "referencia",
        "codigo do artigo",
    ],
    "description": [
        "bezeichnung",
        "beschreibung",
        "warenbezeichnung",
        "artikelbezeichnung",
        "descrizione",
        "descrizione merce",
        "omschrijving",
        "artikelomschrijving",
        "description of goods",
        "goods description",
        "designation",
        "descricao",
        "designacao",
        "nazwa towaru",
        "nazwa",
        "opis",
        "opis towaru",
    ],
    "code": [
        "zolltarifnr",
        "zolltarifnummer",
        "zolltarif",
        "zolltarif-nr",
        "warennummer",
        "warentarifnummer",
        "tarifnummer",
        "statistische warennummer",
        "hs-nr",
        "voce doganale",
        "codice doganale",
        "codice nc",
        "nomenclatura",
        "codice hs",
        "gn-code",
        "gn code",
        "goederencode",
        "tariefcode",
        "hs-code",
        "hs code",
        "fraccion arancelaria",
        "codigo arancelario",
        "n° tarif douanier",
        "no tarif douanier",
        "tarif douanier",
        "tariff no",
        "tariff number",
        "hs no",
        "h.s code",
        "h.s. code",
        "hs/taric",
        "taric code",
        "codigo pautal",
        "codigo aduaneiro",
        "nomenclatura combinada",
        "kod cn",
        "kod hs",
        "kod taryfy",
        "pcn",
    ],
    "origine": [
        "ursprung",
        "ursprungsland",
        "herkunft",
        "herkunftsland",
        "paese di origine",
        "paese origine",
        "oorsprong",
        "land van oorsprong",
        "c/o",
        "coo",
        "pais origen",
        "origem",
        "pais de origem",
        "pochodzenie",
        "kraj pochodzenia",
    ],
    "quantite": ["menge", "anzahl", "q.ta", "qta", "quantita", "aantal", "qte", "qtd", "quantidade", "ilosc"],
    "unite": ["einh", "einheit", "me", "u.m", "eenh", "eenheid", "uom", "unidad", "un", "j.m", "jm"],
    "prix_unitaire": [
        "einzelpreis",
        "stuckpreis",
        "preis",
        "e-preis",
        "prezzo",
        "prezzo unit",
        "prezzo unitario",
        "prijs",
        "stukprijs",
        "eenheidsprijs",
        "precio unitario",
        "precio unit",
        "preco unit",
        "preco unitario",
        "cena jedn",
        "cena jednostkowa",
        "cena",
    ],
    "montant": [
        "gesamtpreis",
        "betrag",
        "gesamtbetrag",
        "gesamt",
        "importo",
        "importo totale",
        "bedrag",
        "totaalbedrag",
        "line total",
        "importe",
        "amount",
        "wartosc",
        "wartosc netto",
        "kwota",
    ],
    "masse_nette": ["nettogewicht", "peso netto", "netto kg"],
    "masse_brute": ["bruttogewicht", "peso lordo", "brutogewicht", "brutto kg"],
}

#: Origine déclarée pour toute la facture (sans colonne d'origine) : « COUNTRY OF ORIGIN: China (CN) ».
LIB_ORIGINE_DOC = _m(
    r"(?:country\s*of\s*origin|origin\s*of\s*(?:the\s*)?goods|made\s*in)\s*:?",
    r"(?:pays\s*d'origine|origine\s*des\s*marchandises)\s*:?",
    r"(?:pais\s*de\s*origen|origen\s*de\s*las?\s*mercancias?)\s*:?",
    r"(?:ursprungsland|warenursprung|ursprung\s*der\s*waren?)\s*:?",
    r"(?:paese\s*d'origine|origine\s*(?:della\s*)?merce)\s*:?",
    r"(?:land\s*van\s*oorsprong|oorsprong\s*(?:van\s*de\s*)?goederen)\s*:?",
    r"(?:pais\s*de\s*origem|origem\s*(?:das\s*)?mercadorias)\s*:?",
    r"kraj\s*pochodzenia(?:\s*towarow)?\s*:?",
)

# --- avoir fournisseur (de, it, nl) ----------------------------------------------------------------------------
AVOIR_NUMERO = _m(
    rf"gutschrift(?:s)?\s*(?:{_NO}|nummer)\s*:?",
    r"gutschriftsnummer\s*:?",
    rf"nota\s*(?:di\s*)?credito\s*(?:{_NO}|n\.)\s*:?",
    rf"credit\s*nota\s*(?:{_NO}|nummer)\s*:?",
    rf"creditnota\s*(?:{_NO}|nummer)\s*:?",
    rf"creditfactuur\s*(?:{_NO}|nummer)\s*:?",
)
AVOIR_ORIGINE = _m(
    rf"(?:ursprungs|bezugs|ursprungliche\s*)rechnung(?:\s*{_NO})?\s*:?",
    rf"zu\s*rechnung(?:\s*{_NO})?\s*:?",
    rf"fattura\s*(?:originale|di\s*riferimento|rif\.?)(?:\s*{_NO})?\s*:?",
    rf"rif\.?\s*fattura(?:\s*{_NO})?\s*:?",
    rf"(?:oorspronkelijke|originele)\s*factuur(?:\s*{_NO})?\s*:?",
    rf"betreft\s*factuur(?:\s*{_NO})?\s*:?",
    rf"fatura\s*(?:de\s*origem|original|corrigida|retificada)(?:\s*{_NO})?\s*:?",
    rf"faktura\s*(?:pierwotna|korygowana)(?:\s*{_NO})?\s*:?",
    rf"dotyczy\s*faktury(?:\s*{_NO})?\s*:?",
)
AVOIR_MOTIF = _m(r"(?:grund|begrundung|causale|reden)\s*:?")
