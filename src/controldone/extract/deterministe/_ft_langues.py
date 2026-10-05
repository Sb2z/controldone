"""Vocabulaire multilingue des factures de transitaire et des avoirs (fr, en, de, it, es, nl).

Données seulement (aucune règle propre à un gabarit) : en-têtes de colonnes de tableau, libellés d'en-tête
(numéro, date, client, titres de transport), libellés de totaux, lignes de report (« à reporter », « carried
forward », « Übertrag »…) et renvois vers une annexe. Les textes sont comparés sans accents, en minuscules
(``normalize.text.cle_texte``).
"""

from __future__ import annotations

import re

__all__ = [
    "FIN_TABLEAU",
    "LIB_CLIENT",
    "LIB_DATE",
    "LIB_EMETTEUR",
    "LIB_NUMERO",
    "LIB_TRANSPORT",
    "MOTS_MOIS",
    "RENVOI_ANNEXE",
    "REPORT",
    "TITRE",
    "TITRE_COMPACT",
    "TOTAUX",
    "VOCABULAIRE_COLONNES",
]

# --- en-têtes de colonnes ------------------------------------------------------------------------------------
# rôle -> phrases (mots séparés par une espace, tels que découpés à l'impression ; « . » et « : » finaux
# retirés de chaque mot).

VOCABULAIRE_COLONNES: dict[str, list[str]] = {
    "pos": ["pos", "position", "lfd nr", "lfd", "item no"],
    "libcode": ["hs code / item", "hs code", "code sh", "code sh / article", "nc / article", "code / item"],
    "lib": ["designation / description", "designation", "description", "libelle", "libelle / description",
            "prestation", "prestations", "item", "intitule", "nature de la prestation", "service", "services",
            "description / designation", "description / libelle",
            # de
            "leistung", "leistungen", "bezeichnung", "beschreibung", "leistungsbeschreibung", "artikel",
            # it
            "descrizione", "voce", "servizio", "servizi", "prestazione", "causale",
            # es
            "concepto", "descripcion", "servicio", "servicios", "detalle",
            # nl
            "omschrijving", "dienst", "diensten", "prestatie", "artikelomschrijving"],
    "natflag": ["nat", "nat."],
    "ref": ["mrn", "ref", "ref / ref", "reference", "references", "reference / detail", "mrn / detail",
            "ref / detail", "mrn / details", "ref / details", "reference / details", "dossier", "ref.",
            "ref. mrn", "mrn / dua", "dua / mrn", "dua", "mrn / dau", "dau", "mrn-nr", "mrn nr", "ref mrn"],
    "detail": ["detail", "details", "periode", "period", "base de calcul", "calcul", "zeitraum", "periodo",
               "periode / period"],
    "transport": ["transport", "lta", "awb", "lta / bl", "awb / bl", "lta / awb", "bl", "connaissement",
                  "ref transport", "lta/awb", "awb / lta", "air waybill", "air waybill / b/l", "awb / b/l",
                  "lta / b/l", "frachtbrief", "lettera di vettura", "conocimiento", "vrachtbrief"],
    "date": ["date", "date de mainlevee", "date mainlevee", "release date", "statement date", "datum", "data",
             "fecha"],
    "qte": ["qte", "qty", "qte/qty", "qte / qty", "quantite", "quantity", "nb", "nombre", "qte/qte",
            "menge", "anzahl", "anz", "q.ta", "qta", "quantita", "cant", "cantidad", "uds", "aantal", "aant"],
    "pu": ["pu", "pu ht", "puht", "pu/unit", "pu / unit", "unit price", "prix unitaire", "prix unit", "p.u",
           "p.u.", "pu/unit price", "unit", "prix",
           "einzelpreis", "e-preis", "preis", "stuckpreis", "prezzo", "prezzo unitario", "prezzo unit",
           "precio", "precio unitario", "precio unit", "prijs", "eenheidsprijs", "stukprijs", "tarif"],
    "ht": ["montant", "montant ht", "montantht", "amount", "ht", "net", "ht/net", "ht / net", "total ht", "total",
           "montant net", "net amount", "amount excl. vat", "montant hors taxes",
           "betrag", "netto", "nettobetrag", "betrag netto", "gesamt netto", "importo", "imponibile",
           "importo netto", "importe", "importe neto", "bedrag", "netto bedrag", "bedrag excl. btw"],
    "ttc": ["montant ttc", "ttc", "total ttc", "brutto", "betrag brutto", "bruttobetrag", "gross",
            "gross amount", "amount incl. vat", "totale", "importo totale", "totale ivato", "importe total",
            "total con iva", "bedrag incl. btw", "totaal"],
    "tva_mt": ["mt tva", "montant tva", "vat amount", "mt. tva", "mwst-betrag", "mwst betrag", "ust-betrag",
               "ust betrag", "importo iva", "cuota iva", "cuota", "btw-bedrag", "btw bedrag", "iva importo"],
    "tva": ["tva", "vat", "tva/vat", "tva / vat", "mwst", "ust", "iva", "btw", "mwst.", "vat/tva"],
    "cat": ["cat. tva", "cat tva", "c", "code tva", "vat code", "statut", "status", "cat", "categorie tva",
            "cod. iva", "cod iva", "codice iva", "steuerschlussel", "steuercode", "mwst-code", "btw-code",
            "btw code", "codigo iva", "cod. tva"],
    "taux": ["%", "taux", "rate", "taux tva", "vat rate", "vat %", "tva %", "tva%", "vat%",
             "mwst %", "mwst%", "mwst-satz", "mwst.-satz", "ust %", "ust-satz", "steuersatz", "satz",
             "aliquota", "aliq", "aliquota iva", "% iva", "iva %", "iva%", "tipo iva", "tipo", "% btw",
             "btw %", "btw%", "btw-tarief", "tarief"],
    "base_droit": ["duty base", "base droits", "base droit", "base des droits", "valeur en douane",
                   "customs value", "base", "zollwert", "valore in dogana", "valor en aduana", "douanewaarde"],
    "base_tva": ["vat base", "base tva"],
    "nat:debours_droits": ["droits", "duty", "duties", "droits de douane", "customs duty", "droit"],
    "nat:debours_autres_taxes": ["autres tx", "autres taxes", "other taxes", "other duties", "autres tx."],
    "nat:debours_tva": ["tva import", "import vat", "tva import.", "tva a l'import", "tva imp"],
    "nat:debours_combines": ["droits et taxes", "duties and taxes", "droits & taxes"],
    "nat:frais_dedouanement": ["dedouan", "dedouanement", "clearance", "customs clearance", "dedouan."],
    "nat:frais_ligne_supplementaire": ["lignes sup", "lignes sup.", "ligne sup", "additional lines",
                                       "add. lines", "lignes supp"],
    "nat:frais_avance_fonds": ["av. fonds", "av fonds", "avance de fonds", "adv. fee", "disbursement fee"],
    "nat:magasinage": ["magasinage", "storage"],
    "nat:transport": ["livraison", "delivery"],
    "nat:manutention": ["manutention", "handling"],
}

# --- titres et libellés d'en-tête --------------------------------------------------------------------------------

_MOTS_TITRE = (
    r"facture|invoice|avoir|credit note|note de credit|releve|statement|facture de debours|"
    r"facture de prestations?|facture / invoice|avoir / credit note|debit note|note de debit|"
    r"rechnung|zollrechnung|gutschrift|fattura|nota di credito|nota credito|factura|abono|"
    r"factura rectificativa|factuur|voorschotfactuur|creditnota|creditfactuur|duty (?:&|and) tax invoice"
)
TITRE = re.compile(rf"^({_MOTS_TITRE})\b")
TITRE_COMPACT = re.compile(
    r"^(facture|invoice|avoir|creditnote|notedecredit|releve|statement|debitnote|notededebit|rechnung|"
    r"gutschrift|fattura|notadicredito|factura|abono|factuur|voorschotfactuur|creditnota)")

_NO = r"(?:n°|nº|n\.?º|n\.o\.?|no\.?|n\.|num(?:ero)?\.?|number|nr\.?|nummer|nro\.?)"
LIB_NUMERO = [re.compile(
    r"(?:(?:facture|invoice|avoir|credit note|note de credit|releve|statement|rechnung|gutschrift|fattura|"
    r"nota di credito|factura|abono|factuur|creditnota)\s+)?"
    rf"{_NO}(?:\s*/\s*{_NO})?\s*(?:de\s+(?:la\s+)?factura\s*)?:?\s*"
), re.compile(
    r"(?:rechnungsnummer|rechnungs-nr\.?|gutschriftsnummer|numero (?:di |della )?fattura|numero de factura|"
    r"factuurnummer|factuurnr\.?|invoice number|invoice no\.?|numero de facture)\s*:?\s*"
), re.compile(r"(?:invoice|facture|rechnung|fattura|factura|factuur)\s*/\s*"
              r"(?:invoice|facture|rechnung|fattura|factura|factuur)\s*(?:n°|no\.?|nr\.?)?\s*:?\s*")]

LIB_DATE = [re.compile(
    r"(?:date(?: de (?:la )?facture| du releve| de l'avoir| d'emission| of invoice| of issue| facture|"
    r" invoice)?|datum|rechnungsdatum|belegdatum|data(?: (?:della )?fattura| documento| emissione)?|"
    r"fecha(?: (?:de )?(?:la )?factura| de emision| de expedicion)?|factuurdatum|invoice date|date / datum)"
    r"\s*:?\s*"
)]
#: « du 03/09/2026 », « Lyon, le 22/08/2026 », « … del 10 marzo 2026 », « vom 03.09.2026 »
LIB_DU = [re.compile(r"(?:du|le|del|vom|van|de)\s+(?=\d)")]

LIB_CLIENT = [re.compile(
    r"(client factur[ee]|client / bill to|bill to|billed to|invoice to|facture a|factur[ee] a|customer|"
    r"client|destinataire de la facture|sold to|rechnungsempfanger|rechnungsadresse|empfanger|kunde|"
    r"cliente|destinatario|intestatario|spett\.? ?le|facturar a|facturado a|klant|factuuradres|afnemer|"
    r"importer / destinataire|importer|importateur|account)\b\s*:?\s*"
)]
LIB_EMETTEUR = [re.compile(r"(absender|emittente|mittente|emisor|afzender|expediteur|issued by|emis par)\b\s*:?\s*")]

_TRANSPORT_MOTS = (
    r"lta|awb|hawb|mawb|b/l|bl|bol|cmr|air ?waybill|bill of lading|connaissement|lettre de transport|"
    r"ref\.? transport|transport ref\.?|frachtbrief|luftfrachtbrief|konnossement|ladeschein|"
    r"lettera di vettura(?: aerea)?|polizza di carico|conocimiento(?: de embarque)?|carta de porte|guia aerea|"
    r"vrachtbrief|luchtvrachtbrief|cognossement|n° lta|n° awb"
)
LIB_TRANSPORT = [re.compile(
    rf"(?:{_TRANSPORT_MOTS})(?:\s*/\s*(?:{_TRANSPORT_MOTS}))*(?![\w-])\s*(?:n°|no\.?|nr\.?)?\s*:?\s*"
)]

# --- totaux ----------------------------------------------------------------------------------------------------

TOTAUX: list[tuple[str, re.Pattern[str]]] = [
    ("ignore", re.compile(
        r"^((total|sous-total|subtotal) (des )?(prestations|services|frais|fees|charges)\b|"
        r"summe (der )?leistungen|leistungen (gesamt|netto)|totale (servizi|prestazioni|competenze)|"
        r"total (servicios|honorarios)|base imponible|totaal (diensten|kosten)|"
        r"carried forward|brought forward|a reporter|reporte?s? de la page|ubertrag|uebertrag|riporto|"
        r"da riportare|suma y sigue|suma anterior|saldo anterior|over te brengen|overgebracht|van vorige)")),
    ("total_debours", re.compile(
        r"^(total (des )?debours|total disbursements?|debours / disbursements|total debours / disbursements|"
        r"debours|disbursements|total customs disbursements|total (des )?droits et taxes|"
        r"total duties (and|&) taxes|summe (der )?auslagen|auslagen (gesamt|total)|summe zollabgaben|"
        r"di cui anticipazioni|totale anticipazioni|anticipazioni|total suplidos|suplidos|"
        r"totaal voorschotten|voorschotten|totaal douanerechten)\b")),
    ("total_ht", re.compile(
        r"^(total ht|total h\.t\.?|total excl\.? vat|total net|total hors taxes?|montant ht|total before vat|"
        r"total credited excl\.? vat|net credited|total net credited|subtotal|sous-total ht|"
        r"nettobetrag( gesamt)?|gesamtbetrag netto|summe netto|netto gesamt|gesamt netto|"
        r"totale imponibile|imponibile totale|totale netto|total sin iva|total neto|total base imponible total|"
        r"totaal excl\.?( btw)?|totaal exclusief btw|subtotaal|netto totaal)\b")),
    ("acomptes", re.compile(r"^(acomptes?|deja regle|deposit|already paid|advance payment|paiement recu|"
                            r"anzahlung|acconto|anticipo recibido|aanbetaling)\b")),
    ("net_a_payer", re.compile(
        r"^(net a payer|amount due|reste a payer|balance due|net to pay|montant a payer|total due|"
        r"zahlbetrag|zu zahlen|netto a pagare|totale da pagare|da pagare|importe a pagar|total a pagar|"
        r"te betalen)\b")),
    ("total_ttc", re.compile(
        r"^(total ttc|total t\.t\.c\.?|total incl\.? vat|ttc|total gross|gross|total credited|"
        r"total a payer|total general|grand total|montant ttc|total invoice|invoice total|"
        r"rechnungsbetrag|gesamtbetrag( brutto)?|bruttobetrag|endbetrag|gutschriftsbetrag|"
        r"totale documento|totale fattura|totale nota di credito|totale generale|"
        r"total factura|importe total|total abono|total con iva|"
        r"totaal incl\.?( btw)?|totaal inclusief btw|factuurbedrag|totaalbedrag|totaal creditnota)\b")),
    # la TVA « à l'importation » (« IVA de importación », « Einfuhrumsatzsteuer ») est un débours, pas la TVA
    # de la facture
    ("total_tva", re.compile(r"^(total tva|total vat|tva|vat|montant tva|vat amount|mwst|ust|umsatzsteuer|"
                             r"totale iva|iva|total iva|cuota iva|btw|totaal btw)\b"
                             r"(?!.*\b(import|importation|importacion|importazione|einfuhr|invoer|douane|dogana|"
                             r"aduana|customs)\b)")),
]

FIN_TABLEAU = re.compile(
    r"^(total|sous-total|subtotal|net a payer|amount due|debours / disbursements|tva \d|vat \d|ttc|"
    r"codes? tva|vat status|conditions|montants? negatifs?|summe|gesamt|nettobetrag|rechnungsbetrag|"
    r"mwst \d|totale|imponibile|iva \d|base imponible|totaal|subtotaal|btw \d)"
)

#: Ligne de report d'un tableau sur plusieurs pages : ni une ligne de facture, ni un total.
REPORT = re.compile(
    r"\b(carried forward|brought forward|a reporter|reporte?s? de la page(?: precedente)?|"
    r"ubertrag|uebertrag|riporto|da riportare|suma y sigue|suma anterior|saldo anterior|"
    r"over te brengen|transport van vorige pagina|van vorige pagina)\b")

#: Libellé d'une ligne qui renvoie au détail d'une annexe (« Suplidos según anexo »).
RENVOI_ANNEXE = re.compile(
    r"\b(annexe|annex|anexo|anlage|allegato|bijlage|appendix|see attached|ci-joint|siehe|vedi|zie)\b")

MOTS_MOIS = (
    "janvier|janv|fevrier|fevr|fev|mars|avril|avr|mai|juin|juillet|juil|aout|aou|septembre|sept|octobre|"
    "novembre|decembre|january|february|march|april|may|june|july|august|september|october|november|december|"
    "jan|feb|mar|apr|jun|jul|aug|sep|oct|nov|dec|"
    "enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|setiembre|octubre|noviembre|diciembre|"
    "januar|februar|marz|juni|juli|oktober|dezember|"
    "gennaio|febbraio|aprile|maggio|giugno|luglio|settembre|ottobre|dicembre|"
    "januari|februari|maart|mei|augustus"
)
