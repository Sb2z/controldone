"""Extracteur déterministe des déclarations en douane **imprimées** (PDF natif ou scanné), SPEC §5.3.2.

Principe : aucune coordonnée propre à un gabarit. L'extracteur travaille sur les mots positionnés de
l'ingestion (``PageText`` : texte, boîtes normalisées 0–1, confiance OCR par mot) :

1. **Libellés** : chaque ligne est parcourue à la recherche de libellés connus (fr/en), comparés après
   normalisation (minuscules, sans accents ni ponctuation) avec une tolérance aux fautes d'OCR
   (``difflib``). Les chevauchements sont résolus au profit du libellé le plus long et le plus sûr.
2. **Valeurs** : la valeur d'un libellé est lue **à sa droite** (jusqu'au libellé suivant, un « | » ou un
   grand blanc) ou, pour les formulaires à cases, **sous le libellé**, dans la colonne de la case
   (de son bord gauche jusqu'au libellé voisin). Chaque champ a un validateur de forme (MRN, date,
   montant, pays…) qui choisit la sous-chaîne retenue.
3. **Articles** : soit des **blocs** ouverts par « Article n » (impression par articles, formulaire à
   cases), soit un **tableau** (en-tête avec colonnes code / origine / montants). Les cellules d'un
   tableau sont attribuées par **position de colonne** (recouvrement avec l'en-tête), jamais par ordre :
   la colonne « mode de paiement / statut » (petits entiers ou lettres) n'est jamais lue comme un montant.
4. **Taxes** : tableaux « type / base / taux / montant / MP » (dans un bloc d'article ou au niveau de la
   déclaration) et colonnes droits / TVA d'un tableau d'articles condensé. La catégorie vient du libellé
   imprimé (ligne, récapitulatif « Total droits (A00) ») puis d'une table de codes usuels ; la légende des
   modes de paiement imprimée sur la page (« A = comptant ; E = … ») prime sur la table par défaut.
5. **Confiance** : texte natif 0,97 ; OCR : fonction de la confiance minimale des mots lus, plafonnée par la
   qualité de la page. Une confusion lettre/chiffre corrigée par la forme (MRN, TVA, code marchandise)
   baisse la confiance au lieu d'être silencieuse. Les recoupements arithmétiques (base × taux = montant,
   sommes) confirment ou rendent douteuses les lectures OCR. Rien n'est inventé : absent -> ``None``.
"""

from __future__ import annotations

import difflib
import re
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from itertools import pairwise
from typing import Any

from controldone.extract.base import ExtractionContext, ExtractionResult
from controldone.extract.deterministe._declaration_generique import (
    ancre_article,
    date_en_lettres,
    date_prose_acceptation,
    ligne_taxe_prose,
    segments_libelles,
)
from controldone.extract.deterministe._mise_en_page import est_bandeau_texte, separer_libelle_tva
from controldone.extract.valeurs import valeur_sourcee
from controldone.ids import IdGenerator, Prefixe
from controldone.model.champs import (
    ArticleDeclaration,
    ChampsDeclaration,
    IndiceAutoliquidation,
    TaxationDeclaration,
    chemin_complet,
)
from controldone.model.documents import Document, Page
from controldone.model.enums import (
    CategorieTaxe,
    Methode,
    PaiementNormalise,
    QualiteTexte,
    TauxChangeSens,
    TauxNature,
    TypeDocument,
    TypeIndiceAutoliquidation,
    TypeValeur,
)
from controldone.model.valeur import ExtracteurInfo, ValeurSourcee, Zone
from controldone.normalize import (
    DEVISES_SANS_DECIMALES,
    INCOTERMS,
    INCOTERMS_ANCIENS,
    ISO2,
    ISO_4217,
    normalize_unit,
    siren_luhn_valide,
    tva_fr_valide,
)
from controldone.normalize.refs import norm_alnum
from controldone.normalize.text import sans_accents

__all__ = ["EXTRACTEUR_ID", "VERSION", "ExtracteurDeclaration"]

EXTRACTEUR_ID = "declaration_regles"
VERSION = "1.0.0"
INFO = ExtracteurInfo(type="deterministe", id=EXTRACTEUR_ID, version=VERSION)
TD = TypeDocument.declaration

# --- confiance -------------------------------------------------------------------------------------------

CONF_NATIF = 0.97
#: Ligne de taxation lue sans son code (sous-ligne d'un tableau condensé) : jamais une valeur sûre.
PLAFOND_CODE_ILLISIBLE = 0.85
#: Ligne d'un tableau de liquidation dont le code est illisible, gardée pour sa cohérence arithmétique (D-1805).
PLAFOND_LIGNE_SANS_CODE = 0.75
CONF_NATIF_FAIBLE = 0.93
#: Confiance d'un sens de taux déduit (§8.7).
CONF_SENS_DERIVE = 0.85
#: Plafond d'une lecture OCR contredite par un recoupement arithmétique.
PLAFOND_INCOHERENT = 0.80
#: Plafond d'une lecture OCR isolée (non recoupée) : sous ``C_MIN_CERTAIN`` (0,90, §8.3).
PLAFOND_OCR_SEUL = 0.89
#: Plafond d'une relecture (séparateur décimal perdu par l'OCR, rétabli par recoupement).
PLAFOND_REPARE = 0.80
#: Confiance accordée à une lecture OCR confirmée par un recoupement arithmétique.
CONF_CONFIRMEE = 0.93

# --- libellés (fr / en), clés internes -> variantes imprimées ----------------------------------------------

LIBELLES: dict[str, tuple[str, ...]] = {
    "mrn": ("MRN", "Bureau de destination / MRN", "Master reference number", "N° MRN"),
    "lrn": ("LRN", "LRN (référence déclarant)", "Référence locale", "Réf. int", "Ref. interne",
            "Numéro de référence", "Local reference number", "LRN (declarant reference)", "Local reference",
            "Your reference", "Lokale Referenz", "Riferimento locale", "Referencia local"),
    "date_acceptation": ("Date d'acceptation", "Accepté le", "Acceptation", "Date of acceptance",
                         "Acceptance date", "Accepted on", "Date de mainlevée", "Mainlevée le",
                        "Annahmedatum", "Datum der Annahme", "Data di accettazione", "Fecha de aceptación", "Fecha de admisión"),
    "version": ("Version", "Rang"),
    "type_declaration": ("Type de déclaration", "Declaration type"),
    "importateur": ("Importateur", "Destinataire / Importateur", "Destinataire / importateur", "Importat",
                    "Importer", "Consignee / Importer", "Importer / Consignee",
                   "Einführer", "Importatore", "Importador"),
    "declarant": ("Déclarant / représentant", "Déclarant / représentant (indirect)",
                  "Déclarant / représentant (direct)", "Déclarant", "Declarant", "Declarant / representative",
                  "Déclarant / Représentant",
                 "Anmelder", "Dichiarante", "Declarante"),
    "expediteur": ("Expéditeur / Exportateur", "Exportateur", "Consignor / Exporter", "Exporter"),
    "tva_importateur": ("TVA imp", "TVA importateur", "Importer VAT", "N° TVA importateur", "N° de TVA importateur",
                        "Numéro de TVA importateur", "Importer VAT number", "Importer VAT No"),
    "tva": ("N° TVA", "TVA", "VAT", "VAT No", "N° de TVA", "TVA intracom"),
    "eori": ("EORI", "N° EORI", "EORI No"),
    "pays_expedition": ("Pays d'expédition", "Pays exp", "Country of dispatch", "Country of export",
                        "Pays de provenance",
                       "Versendungsland", "Paese di spedizione", "País de expedición"),
    "incoterm": ("Conditions de livraison", "Incoterm", "Delivery terms", "Terms of delivery", "Livraison",
                "Lieferbedingungen", "Condizioni di consegna", "Condiciones de entrega"),
    "devise_facture": ("Monnaie de facturation", "Invoice currency", "Devise de facturation",
                      "Rechnungswährung", "Valuta di fatturazione", "Moneda de facturación"),
    "devise_et_montant": ("Monnaie et montant total facturé", "Currency and total amount invoiced",
                          "Invoice currency / total", "Invoice currency and total", "Monnaie / montant facturé",
                          "Monnaie et montant facturé", "Devise / montant facturé", "Currency / invoice total",
                          "Facturation", "Invoicing"),
    "montant_total_facture": ("Montant total facturé", "Valeur fac", "Valeur intrinsèque totale",
                              "Total amount invoiced", "Total invoice amount", "Valeur facturée totale",
                              "Montant facturé total", "Montant total de la facture", "Total invoiced amount",
                              "Total facturé", "Invoice total amount",
                             "Gesamtrechnungsbetrag", "Importo totale fatturato", "Importe total facturado"),
    "taux_change": ("Taux de change", "Taux", "Exchange rate", "Rate of exchange",
                   "Wechselkurs", "Tasso di cambio", "Tipo de cambio"),
    "masse_brute_totale": ("Masse brute totale", "Masse brute totale (kg)", "Poids brut", "Poids brut total",
                           "Total gross mass", "Gross mass total", "Total gross weight",
                          "Gesamtrohmasse", "Massa lorda totale", "Masa bruta total"),
    #: masse brute totale et nombre de colis sous un même libellé (« Gross mass / packages : 3 037 kg / 60 »)
    "masse_et_colis": ("Masse brute totale / colis", "Masse brute / colis", "Poids brut / colis",
                       "Gross mass / packages", "Gross weight / packages", "Total gross mass / packages",
                       "Rohmasse / Packstücke", "Massa lorda / colli", "Masa bruta / bultos"),
    "nombre_colis_total": ("Nombre total de colis", "Total des colis", "Total packages", "Number of packages",
                          "Anzahl der Packstücke", "Numero di colli", "Número de bultos"),
    "colis": ("Colis", "Packages", "Nombre de colis"),
    "nombre_articles": ("Nombre d'articles", "Nb articles", "Articles", "Nombre d'articles (positions)",
                        "Number of items", "Total items",
                       "Anzahl der Positionen", "Numero di articoli", "Número de partidas"),
    "documents": ("Documents produits", "Documents produits / références", "Docs", "Documents",
                  "Mentions spéciales / Documents produits", "Documents produced", "Supporting documents"),
    "ref_fiscale": ("Référence fiscale complémentaire", "Additional fiscal reference"),
    "total_droits_taxes": ("Total des droits et taxes", "Total droits et taxes", "Total duties and taxes",
                           "TOTAL DROITS ET TAXES",
                          "Summe der Abgaben", "Totale dazi e imposte", "Total derechos e impuestos"),
    "total_a_payer": ("Total à payer ou à garantir", "Total à payer", "TOTAL A PAYER", "Total to be paid",
                      "Total payable", "Amount payable",
                     "Zu zahlender Betrag", "Totale da pagare", "Total a pagar"),
    "recapitulatif": ("Récapitulatif des droits et taxes", "Données comptables", "Summary of duties and taxes"),
    "calcul_impositions": ("Calcul des impositions", "Calculation of taxes"),
    "lieu_date": ("Lieu et date", "Place and date"),
    "taxes_declaration": ("Impositions au niveau de la déclaration", "Taxes au niveau de la déclaration",
                          "Impositions globales", "Declaration-level taxes", "Taxes at declaration level",
                          "Duties and taxes at declaration level"),
    # articles
    "article": ("Article", "Article n°", "Colis et désignation - article", "Item", "Item No"),
    "code_marchandise": ("Code marchandise", "Code des marchandises", "Commodity code", "Code NC",
                        "Warennummer", "Codice merce", "Código de mercancía"),
    "pays_origine": ("Origine", "Pays origine", "Pays d'origine", "Country of origin", "Origin",
                    "Ursprungsland", "Paese di origine", "País de origen"),
    "regime": ("Régime", "Procedure", "Procédure"),
    "preference": ("Préférence", "Preference", "Préf.", "Pref."),
    "designation": ("Désignation", "Description", "Designation",
                   "Warenbezeichnung", "Descrizione", "Descripción"),
    "montant_facture_article": ("Montant facturé", "Prix de l'article", "Item price", "Invoiced amount",
                                "Invoice amount", "Amount invoiced", "Montant de la facture"),
    "valeur_statistique": ("Valeur statistique", "Statistical value",
                          "Statistischer Wert", "Valore statistico", "Valor estadístico"),
    "masse_nette": ("Masse nette", "Masse nette (kg)", "Net mass", "Poids net",
                   "Eigenmasse", "Massa netta", "Masa neta"),
    "masse_brute": ("Masse brute", "Masse brute (kg)", "Gross mass",
                   "Rohmasse", "Massa lorda", "Masa bruta"),
    "unites_supplementaires": ("Unités supplémentaires", "Supplementary units", "Quantité supplémentaire",
                               "Quantité", "Quantity"),
}

#: Composantes d'un libellé dans une rubrique composée (« Colis / articles », « LRN / rang ») et lecture de chacune.
_COMPOSANTS: dict[str, tuple[str, ...]] = {
    "masse_brute_totale": ("masse",), "masse_brute": ("masse",), "masse_et_colis": ("masse", "colis"),
    "nombre_colis_total": ("colis",), "colis": ("colis",), "nombre_articles": ("articles",), "lrn": ("lrn",),
    "version": ("version",), "mrn": ("mrn",),
}
_CHAMPS_COMPOSANTS: dict[str, tuple[str, str]] = {
    "masse": ("masse_brute_totale", "v_masse"), "colis": ("nombre_colis_total", "v_colis"),
    "articles": ("nombre_articles", "v_petit_entier"), "lrn": ("lrn", "v_ref"), "version": ("version", "v_petit_entier"),
    "mrn": ("mrn", "v_mrn"),
}

#: Libellés qui ferment un bloc d'article (zones de niveau déclaration).
TERMINATEURS = frozenset({"documents", "total_droits_taxes", "total_a_payer", "recapitulatif", "lieu_date",
                          "ref_fiscale", "taxes_declaration"})
#: Libellés qui ferment le pavé d'une partie (importateur, déclarant).
_STOP_PARTIE = frozenset(LIBELLES) - {"tva", "eori", "tva_importateur"}

# --- colonnes de tableaux --------------------------------------------------------------------------------

COLONNES: dict[str, tuple[str, ...]] = {
    "numero": ("N", "N°", "Pos.", "Pos", "Art.", "No", "Item", "Item No", "Posizione", "Partida"),
    "code": ("Code", "Code marchandise", "Commodity code", "Code NC", "HS code", "Warennummer", "Codice merce",
             "Código mercancía", "Code SH"),
    "designation": ("Désignation", "Description", "Libellé", "Designation", "Warenbezeichnung", "Descrizione",
                    "Descripción"),
    "origine": ("Or", "Origine", "Origin", "Pays origine", "Country of origin", "Ursprung", "Origen"),
    "preference": ("Pf", "Préf.", "Pref.", "Préférence", "Preference", "Präferenz", "Preferenza", "Preferencia"),
    "regime": ("Rég.", "Régime", "Proc.", "Procedure", "Procédure", "Verfahren", "Regime", "Régimen"),
    "montant_facture": ("Mt facturé", "Montant facturé", "Invoice amount", "Mt fact", "Invoiced amount",
                        "Rechnungsbetrag", "Importo fatturato", "Importe facturado"),
    "valeur": ("Valeur (EUR)", "Valeur", "Value (EUR)", "Value"),
    "valeur_statistique": ("Val. stat.", "Valeur stat.", "Valeur statistique", "Stat. value", "Statistical value",
                           "Statistischer Wert", "Valore statistico", "Valor estadístico"),
    "quantite": ("Qté", "Qty", "Quantité", "Quantity", "Qté sup.", "Qty sup.", "Supp. units", "Supplementary units",
                 "Unités sup.", "Unités supplémentaires", "Besondere Maßeinheit", "Unità supplementari"),
    "masse_brute": ("Masse brute kg", "Masse brute", "Gross mass kg", "Gross mass", "Poids brut", "Brut kg", "Brut",
                    "Gross kg", "Gross", "Rohmasse", "Brutto", "Massa lorda", "Masa bruta", "Peso bruto"),
    "masse_nette": ("Masse nette kg", "Masse nette", "Net mass kg", "Net mass", "Net kg", "Net", "Poids net",
                    "Eigenmasse", "Netto", "Massa netta", "Masa neta", "Peso neto"),
    "colis": ("Colis", "Packages", "Pkgs", "Nombre de colis", "Packstücke", "Colli", "Bultos"),
    "base_droits": ("Base droits", "Duty base"),
    "taux_droits": ("Tx", "Duty rate"),
    "droits": ("Droits", "Duty", "Duties"),
    "base_tva": ("Base TVA", "VAT base"),
    "tva": ("TVA", "VAT"),
    "statut": ("St", "Statut", "Status"),
    "type": ("Type", "Tax", "Taxe", "Code taxe", "Abgabe", "Tributo", "Impuesto"),
    "base": ("Base d'imposition", "Base", "Tax base", "Basis", "Assiette", "Bemessungsgrundlage", "Base imponibile",
             "Base imponible"),
    "taux": ("Quotité", "Taux", "Rate"),
    "montant": ("Montant", "Montant EUR", "Amount", "Amount EUR"),
    "a_payer": ("À payer", "Payable", "Amount payable", "To pay", "Exigible", "Zu zahlen",
                "Da pagare", "A pagar"),
    "mp": ("MP", "Mode de paiement", "MOP", "Payment", "Paiement", "Mode paiement", "Zahlungsart", "Pagamento",
           "Pago"),
    "reference": ("Référence", "Reference"),
}

# --- formes ------------------------------------------------------------------------------------------------

#: Nombre imprimé : milliers séparés par une espace (normale, insécable, fine) ou sans séparateur ; décimales
#: après « , » ou « . » (une espace parasite d'OCR après la virgule est tolérée).
_NUM = (r"(?:\d{1,3}(?:[ \u00a0\u202f\u2009'’]\d{3})+(?:[.,]\d{1,6})?"  # 1 234,56 ; 1'234.56
        r"|\d{1,3}(?:,\d{3})+(?:\.\d{1,6})?"  # 1,234,567.89 ; 1,250,000
        r"|\d{1,3}(?:\.\d{3})+(?:,\d{1,6})?"  # 1.234.567,89
        r"|\d+(?:[.,] ?\d{1,6})?)")  # 1234,56 ; 4,7 ; « 4946, 06 » (OCR)
_NUM_RE = re.compile(rf"(?<![\w.,]){_NUM}(?![\d])")
_DATE_RE = re.compile(r"(?<!\d)(\d{1,2})\s?[/.\-]\s?(\d{1,2})\s?[/.\-]\s?(\d{4}|\d{2})(?!\d)")
_DATE_ISO_RE = re.compile(r"(?<!\d)(\d{4})-(\d{2})-(\d{2})(?!\d)")
_TAUX_LIB_RE = re.compile(
    rf"(?<![\d.,])1\s*([A-Z]{{3}})\s*[=:\-–]\s*({_NUM})\s*([A-Z]{{3}})\b"
)
#: Même expression, codes devant les nombres : « EUR 1 = CHF 0.91106 ».
_TAUX_LIB_INV_RE = re.compile(
    rf"\b([A-Z]{{3}})\s*1(?![\d.,])\s*[=:]\s*([A-Z]{{3}})\s*({_NUM})(?![\d])"
)
_CODE_TAXE_RE = re.compile(r"^[A-Z][0-9OoIlSZQ]{2}$|^[A-Z]{3}$")
_MOTS_NON_TAXE = frozenset({"EUR", "TVA", "VAT", "MRN", "LRN", "USD", "TOT", "DES", "LES", "AND", "THE", "REF",
                            "TYP", "TAX"})
_CODE_DOC_RE = re.compile(r"^([NCYU][0-9O]{3})(?::(.*))?$")
_BOITE_RE = re.compile(r"^(?:\d{1,2}[a-z]?|[A-Z])$")
_SEPARATEURS = frozenset({"|", "¦", ";"})
#: Section « Documents produits / références » (clé sans espaces ni accents) et fin de section.
_SECTION_DOCS_RE = re.compile(r"^(?:documents?produits|documentsreferences|producedocuments|documentsproduced)")
_FIN_SECTION_DOCS_RE = re.compile(r"^(?:article|art\d|item|designation|recapitulatif|total)")
#: Ligne de forfait « petits envois » lue hors tableau (D-811).
_FORFAIT_LIBELLE_RE = re.compile(r"forfait\w*\s+petits?\s+envois?|flat.?rate|low.?value.*dut")
_ARTICLES_RE = re.compile(r"(?i)^(?:articles?|article\(s\)|art\.?|items?|item\(s\))$")
_DECIMAL_RE = re.compile(r"\d{1,6}[,.]\d{2}")
#: Nombre imprimé avec un zéro de tête suivi d'un chiffre (« 036,48 ») : premier groupe de milliers perdu.
_ZERO_TETE_RE = re.compile(r"0+\d*?[1-9]")  # « 000 » / « 0,00 » (zéro) n'en est pas
#: Mot « colis » (clé normalisée) : « 63 colis », « 60 packages » (fr / en / de / it / es).
_MOTS_COLIS_RE = re.compile(r"colis|packages?|pkgs?|packstucke?|colli|bultos")
#: Libellé imprimé du type de document -> code (clé sans espaces ni accents, en début de reste de ligne).
_LIBELLES_DOCS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"^(?:facturecommerciale|commercialinvoice|facturacomercial)"), "N380"),
    (re.compile(r"^(?:facture)?proforma"), "N325"),
    (re.compile(r"^(?:connaissement|billoflading|conocimiento)"), "N705"),
    (re.compile(r"^(?:lta|lettredetransportaerien|airwaybill|awb)$|^lettredetransportaerien"), "N740"),
)

#: Confusions lettre -> chiffre et chiffre -> lettre (corrections imposées par la forme, §8.5.4).
_VERS_CHIFFRE = str.maketrans({"O": "0", "D": "0", "Q": "0", "I": "1", "L": "1", "|": "1", "S": "5", "B": "8",
                               "Z": "2", "G": "6", "T": "7", "A": "4"})
_VERS_LETTRE = str.maketrans({"0": "O", "1": "I", "5": "S", "8": "B", "2": "Z", "6": "G", "4": "A", "7": "T"})

#: Catégorie d'une taxe d'après son libellé imprimé (ordre significatif).
_CATEGORIES_LIBELLE: tuple[tuple[re.Pattern[str], CategorieTaxe], ...] = (
    (re.compile(r"\b(tva|vat|taxe sur la valeur|iva)\b"), CategorieTaxe.tva),
    (re.compile(r"forfait|petits? envois?|faible valeur|low.?value|flat.?rate"), CategorieTaxe.forfait_petits_envois),
    (re.compile(r"dumping|compensat|countervail|specifique|specific|accise|excise|additionnel|additional|autre"),
     CategorieTaxe.autre_taxe),
    (re.compile(r"droits?( de douane)?\b|customs dut|\bdut(y|ies)\b|droit tiers|third.country"), CategorieTaxe.droit),
)
#: Codes usuels (repli quand aucun libellé n'est imprimé pour le code).
_CATEGORIES_CODE: dict[str, CategorieTaxe] = {
    "A00": CategorieTaxe.droit, "A10": CategorieTaxe.droit, "A20": CategorieTaxe.droit,
    "A30": CategorieTaxe.autre_taxe, "A35": CategorieTaxe.autre_taxe, "A40": CategorieTaxe.autre_taxe,
    "A45": CategorieTaxe.autre_taxe, "B00": CategorieTaxe.tva,
}
#: Modes de paiement usuels (lettres de la nomenclature de l'Union) ; la légende imprimée prime.
_PAIEMENT_DEFAUT: dict[str, PaiementNormalise] = {
    "A": PaiementNormalise.comptant, "B": PaiementNormalise.comptant, "C": PaiementNormalise.comptant,
    "D": PaiementNormalise.comptant, "H": PaiementNormalise.comptant, "E": PaiementNormalise.differe,
    "G": PaiementNormalise.autoliquide,
}
_SENS_PAIEMENT: tuple[tuple[re.Pattern[str], PaiementNormalise], ...] = (
    (re.compile(r"autoliq|atvai|reverse|postponed|report"), PaiementNormalise.autoliquide),
    (re.compile(r"differ|deferred|credit d.enlevement"), PaiementNormalise.differe),
    (re.compile(r"garant|guarantee|caution"), PaiementNormalise.garanti),
    (re.compile(r"comptant|cash|immediat|especes"), PaiementNormalise.comptant),
)


def _apres_separateurs(toks: Sequence[_Tok], i: int) -> int | None:
    """Indice du premier mot à partir de ``i`` qui n'est pas un séparateur de colonne (``None`` si aucun)."""
    while i < len(toks) and toks[i].t in _SEPARATEURS:
        i += 1
    return i if i < len(toks) else None


def _cle(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", sans_accents(s).lower())


def _ratio(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, a, b, autojunk=False).ratio()


def _seuil(n: int) -> float:
    if n <= 4:
        return 1.01  # exact seulement
    if n <= 7:
        return 0.88
    return 0.82


def _indexer(table: dict[str, tuple[str, ...]]) -> tuple[dict[str, list[tuple[str, str]]], int]:
    index: dict[str, list[tuple[str, str]]] = {}
    lmax = 0
    for cle, variantes in table.items():
        for v in variantes:
            k = _cle(v)
            if not k:
                continue
            lmax = max(lmax, len(k))
            index.setdefault(k[:2], []).append((cle, k))
    return index, lmax


_INDEX_LIB, _LMAX_LIB = _indexer(LIBELLES)
_INDEX_COL, _LMAX_COL = _indexer(COLONNES)


# --- structures de travail ---------------------------------------------------------------------------------


@dataclass(eq=False)
class _Tok:
    t: str
    k: str
    x0: float
    y0: float
    x1: float
    y1: float
    conf: float | None
    page: int
    li: int = 0
    pos: int = 0
    #: hauteur / largeur de la page : convertit une hauteur relative en largeur relative
    aspect: float = 1.414

    @property
    def cx(self) -> float:
        return (self.x0 + self.x1) / 2

    @property
    def h(self) -> float:
        return max(self.y1 - self.y0, 1e-4)

    @property
    def hx(self) -> float:
        """Hauteur du mot exprimée en fraction de la **largeur** de la page."""
        return self.h * self.aspect


@dataclass(eq=False)
class _Ligne:
    page: int
    idx: int
    toks: list[_Tok]

    @property
    def y0(self) -> float:
        return min(t.y0 for t in self.toks)

    @property
    def y1(self) -> float:
        return max(t.y1 for t in self.toks)

    @property
    def texte(self) -> str:
        return " ".join(t.t for t in self.toks)


@dataclass(eq=False)
class _Hit:
    cle: str
    ligne: _Ligne
    i: int
    j: int
    score: float

    @property
    def toks(self) -> list[_Tok]:
        return self.ligne.toks[self.i:self.j]

    @property
    def x0(self) -> float:
        return min(t.x0 for t in self.toks)

    @property
    def x1(self) -> float:
        return max(t.x1 for t in self.toks)

    @property
    def y1(self) -> float:
        return max(t.y1 for t in self.toks)


@dataclass(eq=False)
class _Span:
    """Suite de mots d'une même ligne (ou d'une même cellule) et leur texte joint par une espace."""

    toks: list[_Tok]
    score_libelle: float = 1.0

    @property
    def texte(self) -> str:
        return " ".join(t.t for t in self.toks)

    @property
    def vide(self) -> bool:
        return not self.toks

    def offsets(self) -> list[tuple[int, int]]:
        out, p = [], 0
        for t in self.toks:
            out.append((p, p + len(t.t)))
            p += len(t.t) + 1
        return out

    def sous(self, debut: int, fin: int) -> _Span:
        sel = [t for t, (a, b) in zip(self.toks, self.offsets(), strict=True) if a < fin and b > debut]
        return _Span(sel, self.score_libelle)

    def depuis(self, toks: Sequence[_Tok]) -> _Span:
        return _Span(list(toks), self.score_libelle)


@dataclass
class _Lu:
    """Résultat d'un validateur : sous-chaîne retenue, valeur normalisée, pénalité, données annexes."""

    span: _Span
    brut: str
    valeur: str | None
    penalite: float = 0.0
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class _InfoPage:
    numero: int
    texte: str
    methode: Methode
    plafond: float
    geometrie: bool


@dataclass
class _Colonne:
    cle: str
    x0: float
    x1: float


# --- lecture des nombres -------------------------------------------------------------------------------------


def _decimal(brut: str, sep: str) -> tuple[Decimal | None, bool]:
    """Nombre imprimé -> Decimal ; second élément : lecture ambiguë (séparateur incertain)."""
    s = re.sub(r"[\s   ]", "", brut)
    s = s.replace("'", "").replace("’", "")
    if not s or not re.fullmatch(r"[\d.,]+", s) or not s[0].isdigit():
        return None, False
    ambigu = False
    if "," in s and "." in s:
        dec = "," if s.rfind(",") > s.rfind(".") else "."
        mil = "." if dec == "," else ","
        s = s.replace(mil, "").replace(dec, ".")
    elif "," in s or "." in s:
        c = "," if "," in s else "."
        if s.count(c) > 1:
            s = s.replace(c, "")
        else:
            entier, frac = s.split(c)
            if c != sep and len(frac) == 3 and len(entier) <= 3:
                s = entier + frac  # séparateur de milliers probable
                ambigu = True
            else:
                s = f"{entier}.{frac}"
    try:
        return Decimal(s), ambigu
    except InvalidOperation:
        return None, False


def _nombres(span: _Span) -> list[re.Match[str]]:
    return list(_NUM_RE.finditer(span.texte))


def _a_decimales(m: re.Match[str]) -> bool:
    return bool(re.search(r"[.,] ?\d{1,6}$", m.group(0)))


# --- extracteur ----------------------------------------------------------------------------------------------


class ExtracteurDeclaration:
    """Déclarations imprimées (H1 par articles, preuve de dédouanement condensée, formulaire à cases, H7)."""

    id = EXTRACTEUR_ID
    version = VERSION
    type = "deterministe"

    def supports(self, document: Document, pages: Sequence[Page]) -> bool:
        if TypeDocument(document.type) is not TD:
            return False
        if document.sous_type in ("export_xml", "export_csv"):
            return False
        return any(p.texte.strip() for p in self._pages_du_document(document, pages))

    @staticmethod
    def _pages_du_document(document: Document, pages: Sequence[Page]) -> list[Page]:
        if not document.pages:
            return list(pages)
        refs = {(r.fichier_id, r.numero) for r in document.pages}
        sel = [p for p in pages if (p.fichier_id, p.numero) in refs]
        if not sel:
            numeros = {r.numero for r in document.pages}
            sel = [p for p in pages if p.numero in numeros]
        return sorted(sel or list(pages), key=lambda p: p.numero)

    def extract(self, document: Document, pages: Sequence[Page], context: ExtractionContext) -> ExtractionResult:
        sel = self._pages_du_document(document, pages)
        textes = context.options.get("textes_pages") or {}
        positionnes = []
        for p in sel:
            pt = textes.get(p.numero)
            if pt is None:
                from controldone.ingest.decoupage import texte_positionne

                pt = texte_positionne(p)
            positionnes.append(pt)
        lecteur = _Lecteur(document, positionnes, context)
        champs = lecteur.extraire()
        return ExtractionResult(extracteur=INFO, champs=champs, avertissements=lecteur.avertissements,
                                partielle=lecteur.partielle)


class _Lecteur:
    def __init__(self, document: Document, pages_texte: Sequence[Any], context: ExtractionContext) -> None:
        self.document = document
        self.context = context
        self.ids: IdGenerator = context.ids
        self.avertissements: list[str] = []
        self.partielle = False
        self.pages: dict[int, _InfoPage] = {}
        self.lignes: list[_Ligne] = []
        for pt in pages_texte:
            self._charger_page(pt)
        self.textes = {n: p.texte for n, p in self.pages.items()}
        self.sep = self._separateur()
        self.hits = self._detecter_libelles()
        self.hits_par_ligne: dict[int, list[_Hit]] = {}
        for h in self.hits:
            self.hits_par_ligne.setdefault(h.ligne.idx, []).append(h)
        for hs in self.hits_par_ligne.values():
            hs.sort(key=lambda h: h.i)
        self.champs = ChampsDeclaration()
        self.lignes_blocs: set[int] = set()
        self.lignes_tableaux: set[int] = set()
        self.legende: dict[str, tuple[PaiementNormalise, bool]] = {}
        self.libelles_codes: dict[str, str] = {}
        self.codes_colonnes: dict[str, tuple[str, _Span]] = {}
        self.vs_articles: dict[int, ValeurSourcee] = {}
        self._reparees: set[str] = set()
        #: Lignes de taxation dont le code n'a pas été lu (sous-ligne d'un tableau condensé) : plafonnées.
        self._codes_illisibles: list[TaxationDeclaration] = []
        #: Lignes d'un tableau de liquidation sans code lisible, gardées pour leur cohérence base × taux = montant
        #: (D-1805) : plafonnées plus bas encore (leur rattachement à un article est lui-même une lecture OCR).
        self._lignes_sans_code: list[TaxationDeclaration] = []
        self._mt_generique = False

    # --- chargement -------------------------------------------------------------------------------------

    def _charger_page(self, pt: Any) -> None:
        numero = int(pt.numero)
        qualite = QualiteTexte(pt.qualite) if pt.qualite else QualiteTexte.natif
        ocr = getattr(pt, "source", "natif") == "ocr" or qualite is QualiteTexte.ocr
        if qualite is QualiteTexte.illisible and not pt.texte.strip():
            self.avertissements.append(f"page_illisible:{numero}")
            self.partielle = True
            return
        plafond = 1.0
        if ocr:
            s = pt.score_ocr if pt.score_ocr is not None else 0.7
            plafond = 0.95 if s >= 0.86 else 0.88 if s >= 0.78 else 0.75 if s >= 0.68 else 0.55
            if qualite is QualiteTexte.illisible:
                plafond = min(plafond, 0.45)
        methode = Methode.ocr if ocr else Methode.texte_natif
        lignes_src = list(pt.lignes)
        geometrie = any(m.x1 > 0 for li in lignes_src for m in li.mots)
        info = _InfoPage(numero, pt.texte, methode, plafond, geometrie)
        if not ocr and qualite is QualiteTexte.natif_faible:
            info.plafond = CONF_NATIF_FAIBLE
        self.pages[numero] = info
        aspect = 1.414
        if getattr(pt, "largeur", None) and getattr(pt, "hauteur", None):
            aspect = float(pt.hauteur) / float(pt.largeur)
        n_lignes = max(1, len(lignes_src))
        largeur = max((len(li.texte) for li in lignes_src), default=1) or 1
        for k, li in enumerate(lignes_src):
            toks: list[_Tok] = []
            pos_car = 0
            for m in li.mots:
                if not m.texte:
                    continue
                if geometrie:
                    x0, y0, x1, y1 = m.x0, m.y0, m.x1, m.y1
                else:  # texte sans géométrie : boîtes synthétiques (ordre de lecture conservé)
                    x0, x1 = pos_car / largeur, (pos_car + len(m.texte)) / largeur
                    y0, y1 = k / n_lignes, (k + 0.8) / n_lignes
                    pos_car += len(m.texte) + 1
                toks.append(_Tok(m.texte, _cle(m.texte), x0, y0, x1, y1, m.confiance, numero, aspect=aspect))
            if toks:
                ligne = _Ligne(numero, len(self.lignes), toks)
                for p, t in enumerate(toks):
                    t.li, t.pos = ligne.idx, p
                self.lignes.append(ligne)

    def _separateur(self) -> str:
        texte = "\n".join(p.texte for p in self.pages.values())
        virgules = len(re.findall(r"\d,\d{2}(?!\d)", texte))
        points = len(re.findall(r"\d\.\d{2}(?!\d)", texte))
        return "." if points > virgules else ","

    # --- libellés ---------------------------------------------------------------------------------------

    def _detecter_libelles(self) -> list[_Hit]:
        hits: list[_Hit] = []
        for ligne in self.lignes:
            cands = _candidats(ligne.toks, _INDEX_LIB, _LMAX_LIB)
            for score, cle, i, j in _resoudre(cands):
                if _credible(ligne.toks, i, j):
                    hits.append(_Hit(cle, ligne, i, j, score))
        hits.sort(key=lambda h: (h.ligne.idx, h.i))
        return hits

    def _hits(self, cles: Iterable[str], lignes: set[int] | None = None) -> list[_Hit]:
        cs = set(cles)
        return [h for h in self.hits if h.cle in cs and (lignes is None or h.ligne.idx in lignes)]

    def _boite_avant(self, h: _Hit) -> _Tok | None:
        """Numéro de case collé devant le libellé (« 22 Monnaie… », « A Bureau… »)."""
        if h.i > 0:
            t = h.ligne.toks[h.i - 1]
            ecart = h.toks[0].x0 - t.x1
            if _BOITE_RE.match(t.t) and ecart < 1.2 * h.toks[0].hx:
                avant = h.ligne.toks[h.i - 2] if h.i > 1 else None
                if avant is None or t.x0 - avant.x1 > ecart:
                    return t
        return None

    def _droite(self, h: _Hit, *, coupure: bool = True) -> _Span:
        """Mots à droite du libellé : jusqu'au libellé suivant (et son numéro de case), un séparateur ou,
        si ``coupure``, un grand blanc entre deux mots de la valeur."""
        toks = h.ligne.toks
        suivants = [x for x in self.hits_par_ligne.get(h.ligne.idx, []) if x.i >= h.j]
        fin = suivants[0].i if suivants else len(toks)
        if suivants and self._boite_avant(suivants[0]) is not None:
            fin -= 1
        elif suivants and fin > h.j:
            # Seul mot entre deux libellés de cases : un numéro de case collé au libellé suivant (« 35 Masse
            # brute (kg) 38 Masse nette (kg) » lu par OCR), pas une valeur (D-712).
            entre = [t for t in toks[h.j:fin] if _cle(t.t) not in ("", "kg", "kgs")]
            nxt = suivants[0].toks[0]
            if len(entre) == 1 and re.fullmatch(r"\d{1,2}", entre[0].t) and nxt.x0 - entre[0].x1 < 1.5 * nxt.hx:
                fin = toks.index(entre[0])
        sel = list(toks[h.j:max(h.j, fin)])
        while sel and not _cle(sel[0].t) and sel[0].t not in _SEPARATEURS:
            sel = sel[1:]  # « : », « … »
        out: list[_Tok] = []
        for t in sel:
            if t.t in _SEPARATEURS:
                break
            if coupure and out and t.x0 - out[-1].x1 > max(0.04, 3 * t.hx):
                break
            out.append(t)
        return _Span(out, h.score)

    def _plage(self, h: _Hit) -> tuple[float, float]:
        boite = self._boite_avant(h)
        gauche = (boite.x0 if boite else h.x0) - 0.012
        suivants = [x for x in self.hits_par_ligne.get(h.ligne.idx, []) if x.i >= h.j]
        if suivants:
            s = suivants[0]
            b = self._boite_avant(s)
            droite = (b.x0 if b else s.x0) - 0.004
        else:
            droite = 1.0
        return gauche, droite

    def _dessous(self, h: _Hit, *, max_lignes: int = 1, dy_max: float = 0.035, partie: bool = False
                 ) -> list[_Span]:
        """Lignes sous le libellé, dans la colonne de la case (formulaires à cases, pavés)."""
        gauche, droite = self._plage(h)
        out: list[_Span] = []
        bas = h.y1
        for ligne in self.lignes[h.ligne.idx + 1:]:
            if ligne.page != h.ligne.page:
                break
            if ligne.y0 - bas > dy_max:
                break
            libs = [x for x in self.hits_par_ligne.get(ligne.idx, []) if gauche - 0.01 <= x.x0 <= droite]
            if partie:
                # En-tête à deux colonnes : un libellé imprimé nettement à droite du pavé (et séparé de son
                # texte par un grand blanc) ouvre la colonne voisine ; il borne le pavé au lieu de le fermer,
                # et les lignes de cette colonne qui s'intercalent sont ignorées (D-951).
                for x in sorted(libs, key=lambda x: x.x0):
                    if x.cle in _STOP_PARTIE and x.x0 > max(h.x1 + 0.05, gauche + 0.15) and all(
                            x.x0 - t.x1 > 0.04 for t in ligne.toks if t.x1 <= x.x0):
                        droite = min(droite, x.x0 - 0.004)
                        break
                libs = [x for x in libs if x.x0 <= droite]
            toks = [t for t in ligne.toks if t.cx >= gauche and t.cx <= droite and t.x0 >= gauche - 0.01]
            if not toks:
                continue
            if partie and any(x.cle in _STOP_PARTIE for x in libs):
                break
            if not partie and libs:
                break  # rangée de libellés de cases
            out.append(_Span(toks, h.score))
            bas = ligne.y1
            if len(out) >= max_lignes:
                break
        return out

    def _lire(self, cles: Sequence[str], validateur: Callable[[_Span], _Lu | None], *,
              lignes: set[int] | None = None, dessous: bool = True) -> _Lu | None:
        for h in self._hits(cles, lignes):
            lu = validateur(self._droite(h))
            if lu is None:
                lu = validateur(self._droite(h, coupure=False))
            if lu is None and dessous:
                for sp in self._dessous(h):
                    lu = validateur(sp)
                    if lu is not None:
                        break
            if lu is not None:
                lu.extra.setdefault("hit", h)
                return lu
        return None

    # --- confiance et valeurs sourcées --------------------------------------------------------------------

    def _confiance(self, span: _Span, penalite: float = 0.0) -> float:
        if not span.toks:
            return 0.0
        info = self.pages.get(span.toks[0].page)
        if info is None:
            return 0.0
        if info.methode is Methode.texte_natif:
            c = min(CONF_NATIF, info.plafond)
        else:
            confs = [t.conf if t.conf is not None else 0.5 for t in span.toks]
            cmin = min(confs)
            c = 0.30 + 0.65 * cmin
            c = min(c, info.plafond, PLAFOND_OCR_SEUL)
            c -= (1.0 - span.score_libelle) * 0.5
        return max(0.0, min(1.0, c - penalite))

    def _methode(self, span: _Span) -> Methode:
        info = self.pages.get(span.toks[0].page) if span.toks else None
        return info.methode if info else Methode.ocr

    def _est_ocr(self, vs: ValeurSourcee | None) -> bool:
        return vs is not None and vs.methode is Methode.ocr

    def _vs(self, chemin: str, lu: _Lu | None, *, type_valeur: TypeValeur | None = None,
            unite: str | None = None, unite_brute: str | None = None, conf: float | None = None
            ) -> ValeurSourcee | None:
        if lu is None or lu.span.vide or lu.valeur is None:
            return None
        span = lu.span
        page = span.toks[0].page
        z = Zone(x0=_b(min(t.x0 for t in span.toks)), y0=_b(min(t.y0 for t in span.toks)),
                 x1=_b(max(t.x1 for t in span.toks)), y1=_b(max(t.y1 for t in span.toks)))
        ligne = self.lignes[span.toks[0].li]
        c = self._confiance(span, lu.penalite) if conf is None else conf
        vs = valeur_sourcee(
            type_document=TD, chemin=chemin, brut=lu.brut, document_id=self.document.id, page=page,
            extracteur=INFO, methode=self._methode(span), confiance=c, textes_pages=self.textes,
            zone=z if self.pages[page].geometrie else None, texte_contexte=ligne.texte[:200],
            type_valeur=type_valeur, separateur_decimal=self.sep, id_valeur=self.ids.nouveau(Prefixe.valeur),
        )
        maj: dict[str, Any] = {"valeur": lu.valeur, "confiance": round(max(0.0, min(1.0, c)), 4)}
        if unite is not None:
            maj["unite"] = unite
        if unite_brute is not None:
            maj["unite_brute"] = unite_brute
        return vs.model_copy(update=maj)

    def _copie(self, vs: ValeurSourcee | None, chemin: str) -> ValeurSourcee | None:
        if vs is None:
            return None
        return vs.model_copy(update={"id": self.ids.nouveau(Prefixe.valeur), "chemin": chemin_complet(TD, chemin)})

    def _definir(self, chemin: str, vs: ValeurSourcee | None) -> None:
        if vs is not None:
            self.champs.definir(chemin, vs)

    # --- validateurs ----------------------------------------------------------------------------------------

    def v_texte(self, span: _Span) -> _Lu | None:
        utiles = [k for k, t in enumerate(span.toks) if t.k]
        if not utiles:
            return None
        sp = span.depuis(span.toks[utiles[0]:utiles[-1] + 1])
        return _Lu(sp, sp.texte, sp.texte)

    def _v_motif(self, span: _Span, motif: str) -> _Lu | None:
        m = re.search(rf"(?<![\w,.]){motif}(?![\w,])", span.texte)
        if m is None:
            return None
        return _Lu(span.sous(m.start(), m.end()), m.group(0), m.group(0))

    def v_mrn(self, span: _Span) -> _Lu | None:
        toks = span.toks
        for i in range(len(toks)):
            for n in (1, 2):
                if i + n > len(toks):
                    break
                sel = toks[i:i + n]
                brut = " ".join(x.t for x in sel)
                net = re.sub(r"[^A-Za-z0-9]", "", brut).upper()
                if len(net) != 18:
                    continue
                corr = net[:2].translate(_VERS_CHIFFRE) + net[2:4].translate(_VERS_LETTRE) + net[4:]
                if not re.fullmatch(r"\d{2}[A-Z]{2}[A-Z0-9]{14}", corr):
                    continue
                if not net[:4].isalnum() or (n == 2 and not sel[0].t[:2].isdigit()):
                    continue
                pen = 0.0 if corr == net else 0.12
                brut_net = brut.strip(".,:;")
                return _Lu(span.depuis(sel), brut_net, corr, pen)
        return None

    def v_ref(self, span: _Span) -> _Lu | None:
        for t in span.toks:
            net = t.t.strip(".,:;")
            if len(re.sub(r"[^A-Za-z0-9]", "", net)) >= 4 and re.search(r"\d", net):
                return _Lu(span.depuis([t]), net, net)
        return None

    def v_date(self, span: _Span) -> _Lu | None:
        s = span.texte
        m = _DATE_RE.search(s)
        if m:
            j, mo, a = int(m.group(1)), int(m.group(2)), m.group(3)
            an = int(a) if len(a) == 4 else 2000 + int(a)
            if 1 <= j <= 31 and 1 <= mo <= 12 and 1990 <= an <= 2100:
                try:
                    from datetime import date

                    d = date(an, mo, j)
                except ValueError:
                    return None
                return _Lu(span.sous(m.start(), m.end()), m.group(0), d.isoformat())
            return None
        m = _DATE_ISO_RE.search(s)
        if m:
            from datetime import date

            try:
                d = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            except ValueError:
                return None
            return _Lu(span.sous(m.start(), m.end()), m.group(0), d.isoformat())
        dl = date_en_lettres(s)  # « 18 août 2026 », « 11 Mar 2026 » (D-1804)
        if dl is not None:
            return _Lu(span.sous(dl[0], dl[1]), s[dl[0]:dl[1]], dl[2])
        return None

    def v_pays(self, span: _Span) -> _Lu | None:
        for t in span.toks[:3]:
            net = t.t.strip(".,:;()")
            if re.fullmatch(r"[A-Za-z]{2}", net) and net.upper() in ISO2:
                return _Lu(span.depuis([t]), net, net.upper(), 0.0 if net.isupper() else 0.1)
        return None

    def v_devise(self, span: _Span) -> _Lu | None:
        for t in span.toks[:3]:
            net = t.t.strip(".,:;()")
            if re.fullmatch(r"[A-Z]{3}", net) and net in ISO_4217:
                return _Lu(span.depuis([t]), net, net)
        return None

    def v_incoterm(self, span: _Span) -> _Lu | None:
        for k, t in enumerate(span.toks[:3]):
            net = t.t.strip(".,:;()").upper()
            if net in INCOTERMS or net in INCOTERMS_ANCIENS:
                lieu = span.depuis(span.toks[k + 1:])
                lu = _Lu(span.depuis([t]), t.t.strip(".,:;()"), net)
                if not lieu.vide:
                    lu.extra["lieu"] = _Lu(lieu, lieu.texte, lieu.texte)
                return lu
        return None

    def _lu_nombre(self, span: _Span, m: re.Match[str], *, entier: bool = False) -> _Lu | None:
        brut = m.group(0)
        d, ambigu = _decimal(brut, self.sep)
        if d is None:
            return None
        if entier and d != d.to_integral_value():
            return None
        pen = 0.15 if ambigu else 0.0
        if _ZERO_TETE_RE.match(brut):
            pen += 0.25  # « 036,48 » : groupe de milliers dont le premier chiffre est perdu (D-1805)
        if " " in brut and re.search(r"[.,] \d", brut):
            pen += 0.05  # virgule suivie d'une espace (lecture OCR recollée)
        valeur = str(int(d)) if entier else str(d)
        debut = m.start()
        signe = re.search(r"[-−–]\s?$", span.texte[:debut])
        if signe and (signe.start() == 0 or span.texte[signe.start() - 1] in " :("):
            debut = signe.start()  # signe imprimé conservé dans la valeur brute (§5.2)
        return _Lu(span.sous(debut, m.end()), span.texte[debut:m.end()], valeur, pen)

    def v_entier(self, span: _Span) -> _Lu | None:
        for m in _nombres(span):
            if _a_decimales(m):
                return None
            lu = self._lu_nombre(span, m, entier=True)
            if lu is not None:
                return lu
        return None

    def v_colis(self, span: _Span) -> _Lu | None:
        """Nombre de colis : « 63 colis » / « 60 packages » dans le segment (après une masse « 3 037,7 kg / »),
        sinon premier entier du segment."""
        lu = self._nombre_devant_colis(span.toks)
        if lu is not None:
            return lu
        lu = self.v_entier(span)
        if lu is not None and not all(re.fullmatch(r"\W*\d+\W*", t.t) and not re.search(r"\d[-/.]\d", t.t)
                                      for t in lu.span.toks):
            return None  # nombre pris dans une référence (« CMR-FX-554972 », « 999-72400624 »)
        return lu

    @staticmethod
    def _nombre_devant_colis(toks: Sequence[_Tok]) -> _Lu | None:
        for n in range(1, len(toks)):
            if _MOTS_COLIS_RE.fullmatch(toks[n].k) and re.fullmatch(r"\d{1,6}", toks[n - 1].t) and (
                    n < 2 or not re.fullmatch(r"\d{1,3}", toks[n - 2].t)):
                return _Lu(_Span([toks[n - 1]]), toks[n - 1].t, str(int(toks[n - 1].t)))
        return None

    def _apres_barre(self, span: _Span) -> _Lu | None:
        """« 3 037,727 kg / 60 » : entier imprimé après la barre qui suit la masse."""
        for k, t in enumerate(span.toks):
            if t.t == "/" and k + 1 < len(span.toks) and re.fullmatch(r"\d{1,6}", span.toks[k + 1].t):
                return _Lu(span.depuis([span.toks[k + 1]]), span.toks[k + 1].t, str(int(span.toks[k + 1].t)))
        return None

    def _colis_en_clair(self, lignes: set[int]) -> _Lu | None:
        """En-tête sans libellé de colis lisible : « 63 colis » imprimé seul (sous « Masse brute totale /
        colis »). Une seule occurrence dans l'en-tête, sinon rien."""
        trouves = []
        for idx in sorted(lignes):
            lu = self._nombre_devant_colis(self.lignes[idx].toks)
            if lu is not None:
                trouves.append(lu)
        return trouves[0] if len({x.valeur for x in trouves}) == 1 else None

    def v_petit_entier(self, span: _Span) -> _Lu | None:
        lu = self.v_entier(span)
        if lu is not None and lu.valeur is not None and len(lu.valeur) <= 3:
            return lu
        return None

    def v_masse(self, span: _Span) -> _Lu | None:
        # « 38 Masse nette (kg) » à droite de « 35 Masse brute (kg) » : numéro de la case voisine dont le
        # libellé n'a pas été reconnu (lecture OCR), pas une masse (D-712).
        toks = list(span.toks)
        while toks and _cle(toks[0].t) in ("", "kg", "kgs"):
            toks = toks[1:]  # « (kg) » resté après le libellé
        if len(toks) > 1 and re.fullmatch(r"\d{1,2}", toks[0].t) and re.match(r"[^\W\d_]{3,}", toks[1].t):
            return None
        for m in _nombres(span):
            lu = self._lu_nombre(span, m)
            if lu is None or lu.valeur is None:
                continue
            reste = span.texte[m.end():].strip().lower()
            if reste.startswith(("kg", "kgs")):
                lu.extra["unite"] = "kg"
            lu.valeur = str(Decimal(lu.valeur).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP))
            return lu
        return None

    def v_montant(self, span: _Span) -> _Lu | None:
        """Dernier montant à décimales du segment (les références « (DE 14 16) » sont ignorées)."""
        ms = [m for m in _nombres(span) if _a_decimales(m)]
        if not ms:
            return None
        return self._lu_nombre(span, ms[-1])

    def v_montant_devise(self, span: _Span, devise_connue: str | None = None) -> _Lu | None:
        """Montant accompagné d'un code ISO de devise (avant ou après) ; montant entier admis pour une devise
        sans décimales."""
        toks = span.toks
        devs = [(k, t.t.strip(".,:;()")) for k, t in enumerate(toks)
                if re.fullmatch(r"[A-Z]{3}", t.t.strip(".,:;()")) and t.t.strip(".,:;()") in ISO_4217]
        for m in _nombres(span):
            sous = span.sous(m.start(), m.end())
            if sous.vide:
                continue
            a, b = toks.index(sous.toks[0]), toks.index(sous.toks[-1])
            dev = next((d for k, d in devs if k == b + 1), None) or next((d for k, d in devs if k == a - 1), None)
            dev = dev or devise_connue
            if not _a_decimales(m) and dev not in DEVISES_SANS_DECIMALES:
                continue
            lu = self._lu_nombre(span, m)
            if lu is None:
                continue
            if dev:
                lu.extra["devise"] = dev
                tok_dev = next((toks[k] for k, d in devs if k in (a - 1, b + 1) and d == dev), None)
                if tok_dev is not None:
                    lu.extra["devise_span"] = span.depuis([tok_dev])
            return lu
        return None

    def v_taux(self, span: _Span) -> _Lu | None:
        s = span.texte
        m = _TAUX_LIB_RE.search(s)
        gn = 2
        if m is None:
            m = _TAUX_LIB_INV_RE.search(s)
            if m is not None and (m.group(1) in ISO_4217 and m.group(2) in ISO_4217):
                gn = 3
            else:
                m = None
        if m:
            g, num, d = (m.group(1), m.group(2), m.group(3)) if gn == 2 else (m.group(1), m.group(3), m.group(2))
            dval, ambigu = _decimal(num, self.sep)
            if dval is None or dval == 0:
                return None
            if g == "EUR" and d != "EUR":
                sens, devise = TauxChangeSens.devise_par_eur, d
            elif d == "EUR" and g != "EUR":
                sens, devise = TauxChangeSens.eur_par_devise, g
            else:
                sens, devise = None, None
            lu = _Lu(span.sous(m.start(gn), m.end(gn)), num, str(dval), 0.15 if ambigu else 0.0)
            lu.extra.update(sens=sens, devise=devise, expr=_Lu(span.sous(m.start(), m.end()), m.group(0),
                                                               sens.value if sens else None))
            return lu
        for mm in _nombres(span):
            frac = re.search(r"[.,] ?(\d+)$", mm.group(0))
            if frac and len(frac.group(1)) >= 4:
                return self._lu_nombre(span, mm)
        return None

    def v_tva(self, span: _Span) -> _Lu | None:
        for t in span.toks:
            lu = _tva(t)
            if lu is not None:
                return _Lu(span.depuis([t]), lu[0], lu[1], lu[2])
        return None

    def v_eori(self, span: _Span) -> _Lu | None:
        for t in span.toks:
            net = re.sub(r"[^A-Za-z0-9]", "", t.t).upper()
            if not re.fullmatch(r"[A-Z]{2}[A-Z0-9]{8,15}", net):
                continue
            corps = net[2:].translate(_VERS_CHIFFRE) if net.startswith("FR") else net[2:]
            pen = 0.0 if corps == net[2:] else 0.08
            val = net[:2] + corps
            if net.startswith("FR"):
                if not corps.isdigit() or len(corps) not in (14, 15):
                    continue
                if not siren_luhn_valide(corps[:9]):
                    pen += 0.25
            return _Lu(span.depuis([t]), t.t.strip(".,:;"), val, pen)
        return None

    def v_code_marchandise(self, span: _Span) -> _Lu | None:
        groupe = _code_groupes(span.toks)
        if groupe is not None:  # « 8207 70 37 00 » : code imprimé par groupes de chiffres (D-950)
            i, j, chiffres = groupe
            sel = span.toks[i:j]
            return _Lu(span.depuis(sel), " ".join(t.t for t in sel).strip(".,:;"), chiffres)
        for t in span.toks:
            net = t.t.strip(".,:;")
            chiffres = re.sub(r"[ .]", "", net)
            corr = chiffres.upper().translate(_VERS_CHIFFRE)
            if len(corr) in (8, 10) and corr.isdigit() and sum(c.isdigit() for c in chiffres) >= len(chiffres) - 2:
                pen = 0.0 if corr == chiffres else 0.15
                return _Lu(span.depuis([t]), net, corr, pen)
        return None

    def v_quantite(self, span: _Span) -> _Lu | None:
        ms = _nombres(span)
        if not ms:
            return None
        m = ms[0]
        lu = self._lu_nombre(span, m)
        if lu is None:
            return None
        reste = span.texte[m.end():].strip().split(" ")[0] if span.texte[m.end():].strip() else ""
        if reste and not re.match(r"^[\d|]", reste):
            sp = span.sous(m.start(), m.end() + 1 + len(reste))
            u = normalize_unit(reste)
            lu = _Lu(sp, f"{m.group(0)} {reste}", lu.valeur, lu.penalite,
                     {"unite": u.code if u.connue else None, "unite_brute": reste})
        return lu

    # --- extraction -------------------------------------------------------------------------------------------

    def extraire(self) -> ChampsDeclaration:
        if not self.lignes:
            return self.champs
        self._lire_legende()
        self._codes_recapitulatif()
        blocs = self._blocs_articles()
        tableaux_articles = self._tableaux_articles(blocs)
        liste = [] if blocs or tableaux_articles else self._articles_en_liste()
        self._taxes_niveau_declaration()
        taxes_prose = self._taxes_prose_hors_articles()
        entete = {li.idx for li in self.lignes} - self.lignes_blocs - self.lignes_tableaux
        self._entete(entete)
        self._parties(entete)
        self._documents()
        for numero_vs, debut, fin in blocs:
            self._article_bloc(numero_vs, debut, fin)
        for tab in tableaux_articles:
            self._article_tableau(*tab)
        for item in liste:
            self._article_liste(*item)
        for idx, plages in taxes_prose:
            self._taxe_prose(self.lignes[idx], plages, None)
        self._forfait_sans_entete()
        self._totaux()
        self._indices()
        self._sens_taux_derive()
        self._coherence()
        self._recouper_montant_generique()
        for tx in self._lignes_sans_code:
            for vs in (tx.article, tx.base_montant, tx.base_quantite, tx.taux, tx.montant, tx.montant_a_payer):
                if vs is not None and vs.confiance > PLAFOND_LIGNE_SANS_CODE:
                    self._remplacer(vs, PLAFOND_LIGNE_SANS_CODE)
        for tx in self._codes_illisibles:
            for vs in (tx.base_montant, tx.base_quantite, tx.taux, tx.montant):
                if vs is not None and vs.confiance > PLAFOND_CODE_ILLISIBLE:
                    self._remplacer(vs, PLAFOND_CODE_ILLISIBLE)
        return self.champs

    # --- en-tête -----------------------------------------------------------------------------------------------

    def _entete(self, lignes: set[int]) -> None:
        c = self.champs
        lu = self._lire(["mrn"], self.v_mrn, lignes=lignes)
        if lu is None:  # repli : MRN imprimé sans libellé reconnu (forme stricte seulement)
            for ligne in self.lignes:
                essai = self.v_mrn(_Span(ligne.toks))
                if essai is not None and essai.penalite == 0:
                    essai.penalite = 0.05
                    lu = essai
                    break
        if lu is not None:
            lu.penalite += self._penalite_mrn(lu.valeur or "")
        c.mrn = self._vs("mrn", lu)
        c.lrn = self._vs("lrn", self._lire(["lrn"], self.v_ref, lignes=lignes))
        date_lue = self._lire(["date_acceptation"], self.v_date, lignes=lignes)
        if date_lue is None:
            date_lue = self._date_prose(lignes)
        c.date_acceptation = self._vs("date_acceptation", date_lue)
        c.version = self._vs("version", self._lire(["version"], self.v_petit_entier, lignes=lignes, dessous=False))
        c.pays_expedition = self._vs("pays_expedition", self._lire(["pays_expedition"], self.v_pays, lignes=lignes))
        inc = self._lire(["incoterm"], self.v_incoterm, lignes=lignes)
        c.incoterm = self._vs("incoterm", inc)
        if inc is not None and "lieu" in inc.extra:
            c.incoterm_lieu = self._vs("incoterm_lieu", inc.extra["lieu"], type_valeur=TypeValeur.texte)
        dev = self._lire(["devise_facture"], self.v_devise, lignes=lignes)
        devise = dev.valeur if dev else None
        mt = self._lire(["montant_total_facture", "devise_et_montant"],
                        lambda sp: self.v_montant_devise(sp, devise), lignes=lignes)
        if mt is None:
            mt = self._montant_facture_entete(lignes, devise)
        if dev is None and mt is not None and "devise_span" in mt.extra:
            d = mt.extra["devise"]
            dev = _Lu(mt.extra["devise_span"], d, d)
            devise = d
        c.devise_facture = self._vs("devise_facture", dev)
        if mt is not None and devise and mt.extra.get("devise") not in (None, devise):
            mt.penalite += 0.2  # devise du montant différente de la monnaie de facturation imprimée
        c.montant_total_facture = self._vs("montant_total_facture", mt, unite=devise)
        self._mt_generique = mt is not None and bool(mt.extra.get("libelle_generique"))
        tx = self._lire(["taux_change"], self.v_taux, lignes=lignes)
        if tx is None:  # « 1 EUR = 0,92905 CHF » imprimé seul, sans libellé (D-2403)
            tx = self._taux_sans_libelle(lignes)
        if tx is not None:
            c.taux_change = self._vs("taux_change", tx, unite=tx.extra.get("devise"))
            expr: _Lu | None = tx.extra.get("expr")
            if expr is not None and expr.valeur is not None:
                c.taux_change_sens = self._vs("taux_change_sens", expr, type_valeur=TypeValeur.enumeration)
        masse = self._lire(["masse_brute_totale"], self.v_masse, lignes=lignes)
        if masse is None:
            masse = self._lire(["masse_et_colis"], self.v_masse, lignes=lignes)
        c.masse_brute_totale = self._vs("masse_brute_totale", masse)
        colis = self._lire(["nombre_colis_total", "colis"], self.v_colis, lignes=lignes)
        if colis is None:
            colis = self._lire(["masse_et_colis"], lambda sp: self._nombre_devant_colis(sp.toks)
                               or self._apres_barre(sp), lignes=lignes)
        if colis is None:
            colis = self._colis_en_clair(lignes)
        c.nombre_colis_total = self._vs("nombre_colis_total", colis)
        c.nombre_articles = self._vs("nombre_articles",
                                     self._lire(["nombre_articles"], self.v_petit_entier, lignes=lignes))
        # Rubriques composées (« Colis / articles … 7 / 12 », « LRN / rang … LRN… / 1 », « Masse brute / colis /
        # articles 3 649,3 kg — 60 colis — 4 article(s) ») : valeurs lues dans l'ordre des libellés (D-2402).
        for champ, lu in self._composites(lignes).items():
            setattr(c, champ, self._vs(champ, lu))

    def _taux_sans_libelle(self, lignes: set[int]) -> _Lu | None:
        """Expression complète d'un taux de change (« 1 EUR = 0,92905 CHF », « 1 USD = 0,8399 EUR ») sur une ligne
        de l'en-tête, sans libellé : retenue si elle est unique et si l'euro est l'une des deux devises."""
        trouves = []
        for idx in sorted(lignes):
            lu = self.v_taux(_Span(self.lignes[idx].toks))
            if lu is not None and lu.extra.get("sens") is not None:
                trouves.append(lu)
        if len({x.valeur for x in trouves}) != 1:
            return None
        lu = trouves[0]
        lu.penalite += 0.02
        return lu

    def _composites(self, lignes: set[int]) -> dict[str, _Lu]:
        """Libellés enchaînés par « / » suivis d'autant de valeurs séparées par « / » ou « — » : chaque valeur est
        lue avec le validateur de son libellé, dans l'ordre. Rien n'est retenu si les nombres de libellés et de
        valeurs diffèrent, ou si une valeur ne passe pas son validateur."""
        out: dict[str, _Lu] = {}
        for idx in sorted(lignes):
            hs = self.hits_par_ligne.get(idx, [])
            toks = self.lignes[idx].toks
            a = 0
            while a < len(hs):
                chaine = [hs[a]]
                while a + 1 < len(hs) and hs[a + 1].i == chaine[-1].j + 1 and toks[chaine[-1].j].t == "/":
                    a += 1
                    chaine.append(hs[a])
                a += 1
                comps = [x for h in chaine for x in _COMPOSANTS.get(h.cle, ("",))]
                if len(comps) < 2 or "" in comps:
                    continue
                fin_lib = chaine[-1].j
                suite = [x for x in hs if x.i >= fin_lib]
                fin = len(toks)
                for x in suite:  # rubrique voisine (colonne de droite) : libellé précédé d'un grand blanc
                    if x.i > fin_lib and toks[x.i].x0 - toks[x.i - 1].x1 > max(0.04, 3 * toks[x.i].hx):
                        fin = x.i
                        break
                valeurs = [t for t in toks[fin_lib:fin] if t.t not in _SEPARATEURS]
                while valeurs and not _cle(valeurs[0].t) and valeurs[0].t not in ("/", "—", "–"):
                    valeurs = valeurs[1:]  # points de conduite, « : »
                parts: list[list[_Tok]] = [[]]
                for t in valeurs:
                    if t.t in ("/", "—", "–", "-"):
                        parts.append([])
                    else:
                        parts[-1].append(t)
                if len(parts) != len(comps) or any(not p for p in parts):
                    continue
                lus: dict[str, _Lu] = {}
                for comp, p in zip(comps, parts, strict=True):
                    champ, nom_validateur = _CHAMPS_COMPOSANTS[comp]
                    lu = getattr(self, nom_validateur)(_Span(p, min(h.score for h in chaine)))
                    if lu is None:
                        break
                    lus[champ] = lu
                else:
                    for champ, lu in lus.items():
                        out.setdefault(champ, lu)
        return out

    def _date_prose(self, lignes: set[int]) -> _Lu | None:
        """Date d'acceptation écrite dans une phrase (« … acceptée par la douane le 18 août 2026 », « released by
        customs on 11 Mar 2026 ») quand aucun libellé de date n'est lu. Première phrase de ce genre (D-1804)."""
        for idx in sorted(lignes):
            sp = _Span(self.lignes[idx].toks)
            pos = date_prose_acceptation(sp.texte)
            if pos is None:
                continue
            lu = self.v_date(sp.sous(*pos))
            if lu is not None:
                lu.penalite += 0.02  # date lue dans une phrase : jamais au-dessus d'une date sous libellé
                return lu
        return None

    def _montant_facture_entete(self, lignes: set[int], devise: str | None) -> _Lu | None:
        """Libellé générique « Montant facturé » / « Invoice amount » imprimé dans l'**en-tête** (hors blocs et
        tableaux d'articles) : c'est le montant total facturé (DE 14 06) d'une mise en page qui n'emploie pas
        le libellé « total ». Retenu seulement s'il est unique dans l'en-tête et imprimé avant le premier
        article (sinon, ce peut être le montant d'un article dont le bloc n'a pas été reconnu) (D-950)."""
        hits = self._hits(["montant_facture_article"], lignes)
        if len(hits) != 1:
            return None
        h = hits[0]
        debut_articles = min(self.lignes_blocs | self.lignes_tableaux, default=None)
        if debut_articles is None or h.ligne.idx >= debut_articles:
            return None
        lu = self.v_montant_devise(self._droite(h), devise)
        if lu is None:
            for sp in self._dessous(h):
                lu = self.v_montant_devise(sp, devise)
                if lu is not None:
                    break
        if lu is not None:
            lu.extra["hit"] = h
            lu.extra["libelle_generique"] = True
        return lu

    def _penalite_mrn(self, valeur: str) -> float:
        """Plusieurs lectures du MRN dans le document : désaccord -> lecture douteuse."""
        lectures = set()
        for ligne in self.lignes:
            for t in ligne.toks:
                net = re.sub(r"[^A-Za-z0-9]", "", t.t).upper()
                if len(net) == 18 and re.fullmatch(r"\d{2}[A-Z]{2}[A-Z0-9]{14}", net):
                    lectures.add(net)
        autres = {x for x in lectures if x != valeur and x[:4] == valeur[:4]
                  and sum(a != b for a, b in zip(x, valeur, strict=True)) <= 3}
        return 0.3 if autres else 0.0

    # --- parties ------------------------------------------------------------------------------------------------

    def _bloc_partie(self, h: _Hit) -> list[_Span]:
        lignes: list[_Span] = []
        droite = self._droite(h)
        if not droite.vide:
            lignes.append(droite)
        lignes.extend(self._dessous(h, max_lignes=4, dy_max=0.03, partie=True))
        return lignes

    def _partie(self, cle: str, chemin: str, lignes: set[int]) -> None:
        for h in self._hits([cle], lignes):
            bloc = self._bloc_partie(h)
            if not bloc:
                continue
            nom = None
            tva = eori = None
            for sp in bloc:
                libs = [x for x in self.hits_par_ligne.get(sp.toks[0].li, []) if x.toks[0] in sp.toks]
                if libs and libs[0].cle in ("tva", "eori"):
                    reste = self._droite(libs[0])
                    if libs[0].cle == "tva":
                        tva = tva or self.v_tva(reste)
                    else:
                        eori = eori or self.v_eori(reste)
                    continue
                if sp.toks and sp.toks[0].k in ("tva", "vat", "eori", "ntva"):
                    reste = sp.depuis(sp.toks[1:])
                    if sp.toks[0].k == "eori":
                        eori = eori or self.v_eori(reste)
                    else:
                        tva = tva or self.v_tva(reste)
                    continue
                colle = next((t for t in sp.toks if separer_libelle_tva(t.t) is not None), None)
                if colle is not None:  # « N° TVAFR15000100008 » : libellé collé au numéro (D-952)
                    tva = tva or self.v_tva(sp.depuis([colle]))
                    continue
                if nom is None:
                    lu = self.v_texte(sp)
                    if lu is not None and not _tva(lu.span.toks[0]) and not est_bandeau_texte(lu.brut):
                        nom = lu
            # « Importateur: Nom SA  TVA: FR…  EORI: FR… » : identifiants imprimés sur la ligne du libellé, avant
            # le libellé d'une autre rubrique
            for x in self.hits_par_ligne.get(h.ligne.idx, []) if h.i == 0 else ():
                if x.i < h.j:
                    continue
                if x.cle == "tva":
                    tva = tva or self.v_tva(self._droite(x))
                elif x.cle == "eori":
                    eori = eori or self.v_eori(self._droite(x))
                elif x.cle in _STOP_PARTIE:
                    break
            self._definir(f"{chemin}.nom", self._vs(f"{chemin}.nom", nom, type_valeur=TypeValeur.texte))
            self._definir(f"{chemin}.tva", self._vs(f"{chemin}.tva", tva))
            self._definir(f"{chemin}.eori", self._vs(f"{chemin}.eori", eori))
            return

    def _parties(self, lignes: set[int]) -> None:
        self._partie("importateur", "importateur", lignes)
        self._partie("declarant", "declarant", lignes)
        tva = self._lire(["tva_importateur"], self.v_tva, lignes=lignes, dessous=False)
        if tva is not None:
            self.champs.importateur.tva = self._vs("importateur.tva", tva)
        if self.champs.importateur.eori is None:
            eori = self._lire(["eori"], self.v_eori, lignes=lignes, dessous=False)
            self.champs.importateur.eori = self._vs("importateur.eori", eori)

    # --- documents produits ----------------------------------------------------------------------------------

    def _documents(self) -> None:
        vus: set[tuple[str, str]] = set()
        k = 0
        exclues = self.lignes_blocs | self.lignes_tableaux
        dans_section = False
        for ligne in self.lignes:
            if ligne.idx in exclues:
                continue
            toks = ligne.toks
            cle_ligne = _cle(" ".join(t.t for t in toks))
            if _SECTION_DOCS_RE.search(cle_ligne):
                dans_section = True
                continue
            if dans_section and (_FIN_SECTION_DOCS_RE.match(cle_ligne) or not cle_ligne):
                dans_section = False
            libelle_lu = self._document_par_libelle(toks) if dans_section else None
            for i, t in enumerate(toks):
                net = t.t.strip(".,;")
                code = ref_toks = None
                m = _CODE_DOC_RE.match(net)
                pen = 0.0
                if m:
                    code = m.group(1)
                    if "O" in code:
                        code, pen = code.replace("O", "0"), 0.15
                    if m.group(2):
                        ref_toks = [t]
                    elif (j := _apres_separateurs(toks, i + 1)) is not None:
                        # « N380 | FAC/2026/0129-0 » : un séparateur de colonne lu entre le code et la référence ;
                        # « N380 Facture commerciale FAC-0129 » : colonne « nature » imprimée entre les deux
                        ref_toks = _reference_apres_nature(toks, j)
                elif i == 0 and libelle_lu is not None:
                    # « FAC/2026/0060-0   Facture commerciale » (colonne des codes perdue) : code déduit du
                    # libellé imprimé du type de document, dans la section « Documents produits » (D-804).
                    code, ref_toks, pen = libelle_lu[0], [t], 0.10
                elif net in ("1008", "FR7") and (j := _apres_separateurs(toks, i + 1)) is not None \
                        and _tva(_reference_apres_nature(toks, j)[-1]) is not None:
                    code, ref_toks = net, _reference_apres_nature(toks, j)[-1:]
                elif re.match(r"^(1008|FR7):", net) and _tva(_Tok(net.split(":", 1)[1], "", 0, 0, 0, 0, None, 0)):
                    code, ref_toks = net.split(":", 1)[0], [t]
                if not code or not ref_toks:
                    continue
                rt = ref_toks[0]
                ref_brut = rt.t.split(":", 1)[1] if rt is t and ":" in rt.t else " ".join(x.t for x in ref_toks)
                ref_brut = ref_brut.strip(";,")
                if not re.search(r"[A-Za-z0-9]{2}", ref_brut) or _CODE_DOC_RE.match(ref_brut):
                    continue
                cle_ref = (code, norm_alnum(ref_brut))
                if cle_ref in vus:
                    continue
                vus.add(cle_ref)
                sp = _Span([t])
                if rt is t:
                    code_lu = _Lu(sp, net.split(":", 1)[0], code, pen)
                    ref_lu = _Lu(sp, ref_brut, ref_brut)
                else:
                    code_lu = _Lu(sp, net, code, pen)
                    ref_lu = _Lu(_Span(list(ref_toks)), ref_brut, ref_brut)
                if code in ("1008", "FR7"):
                    tv = _tva(_Tok(ref_brut, "", 0, 0, 0, 0, None, 0))
                    if tv is not None:
                        ref_lu = _Lu(ref_lu.span, tv[0], tv[1], tv[2])
                if libelle_lu is not None and not m and code == libelle_lu[0]:
                    code_lu = _Lu(libelle_lu[1], libelle_lu[1].texte, code, pen)
                self._definir(f"documents_references[{k}].type_code",
                              self._vs(f"documents_references[{k}].type_code", code_lu))
                self._definir(f"documents_references[{k}].reference",
                              self._vs(f"documents_references[{k}].reference", ref_lu))
                k += 1

    @staticmethod
    def _document_par_libelle(toks: Sequence[_Tok]) -> tuple[str, _Span] | None:
        """Ligne « <référence> <libellé du type de document> » : (code déduit du libellé, mots du libellé).
        La référence (premier mot) doit contenir un chiffre ; le libellé suit immédiatement."""
        if len(toks) < 2 or not re.search(r"\d", toks[0].t) or _CODE_DOC_RE.match(toks[0].t.strip(".,;")):
            return None
        reste = [t for t in toks[1:] if t.t not in _SEPARATEURS]
        cle = _cle(" ".join(t.t for t in reste))
        for rx, code in _LIBELLES_DOCS:
            if rx.match(cle):
                return code, _Span(reste)
        return None

    # --- légende des modes de paiement, libellés des codes de taxe ---------------------------------------------

    def _lire_legende(self) -> None:
        for ligne in self.lignes:
            texte = ligne.texte
            cle = sans_accents(texte).lower()
            if not re.search(r"paiement|payment|\bmp\b|\bst\b|statut", cle):
                continue
            corps = re.split(r":", texte, maxsplit=1)
            if len(corps) < 2:
                continue
            trouves: dict[str, tuple[PaiementNormalise, bool]] = {}
            for item in re.split(r"[;/]|\s(?=[A-Z0-9©®ÀÉ]\s*=)", corps[1]):
                m = re.match(r"\s*([A-Z0-9©®ÀÉ])\s*(?:=|:|-)?\s+(.+)$", item.strip())
                if not m:
                    continue
                code = sans_accents({"©": "0", "®": "0"}.get(m.group(1), m.group(1)))
                sens = sans_accents(m.group(2)).lower()
                touches = sorted((mm.start(), pn) for motif, pn in _SENS_PAIEMENT if (mm := motif.search(sens)))
                if touches:
                    pn = touches[0][1]  # premier sens cité dans l'élément de légende
                    tva_seule = pn is PaiementNormalise.autoliquide or bool(re.search(r"\btva\b|\bvat\b", sens))
                    trouves.setdefault(code, (pn, tva_seule))
            if len(trouves) >= 2:
                for code, v in trouves.items():
                    self.legende.setdefault(code, v)

    def _paiement(self, code: str | None, categorie: CategorieTaxe) -> PaiementNormalise:
        if not code:
            return PaiementNormalise.inconnu
        if code in self.legende:
            pn, tva_seule = self.legende[code]
            if tva_seule and categorie is not CategorieTaxe.tva and pn is PaiementNormalise.autoliquide:
                return PaiementNormalise.inconnu
            return pn
        if code.isalpha():
            return _PAIEMENT_DEFAUT.get(code, PaiementNormalise.inconnu)
        return PaiementNormalise.inconnu

    def _codes_recapitulatif(self) -> None:
        """Libellés imprimés des codes de taxe (récapitulatif « Total A00 Droits de douane », « Total TVA
        (B00) »), et code de chaque colonne d'un tableau condensé (« droits » -> A00, « tva » -> B00)."""
        for ligne in self.lignes:
            # tableau récapitulatif « Type | Libellé | Montant » : « FPE Droit forfaitaire petits envois 6,00 »
            toks = ligne.toks
            if len(toks) >= 3 and (code0 := _code_taxe(_Span(toks[:1]))) is not None and code0.penalite == 0 \
                    and re.fullmatch(r"[^\W\d_]{3,}", toks[1].t) and _NUM_RE.fullmatch(toks[-1].t):
                mots = [t.t for t in toks[1:-1] if re.fullmatch(r"[^\W\d_][\w'’().-]*", t.t)]
                if len(mots) == len(toks) - 2:
                    self.libelles_codes.setdefault(code0.valeur or "", " ".join(mots))
        for ligne in self.lignes:
            texte = ligne.texte
            for m in re.finditer(r"\b([A-Z][0-9O]{2}|[A-Z]{3})\b", texte):
                code = m.group(1).replace("O", "0") if m.group(1)[0] != "O" else m.group(1)
                if code in _MOTS_NON_TAXE or not re.fullmatch(r"[A-Z]\d{2}|FPE|[A-Z]{3}", code):
                    continue
                avant = texte[:m.start()]
                # « Total A00 : 54,62 Total B00 : 513,53 TOTAL DROITS ET TAXES … » : le libellé d'un code s'arrête au
                # « total » suivant et ne commence pas par son montant
                apres = re.split(r"(?i)\btotal\b", texte[m.end():])[0]
                if re.match(r"\s*:?\s*[\d.,\s]+(?:[A-Z]{3})?\s*$", apres):
                    apres = ""
                if not re.search(r"total", avant, re.I):
                    continue
                libelle = re.sub(r"[\d\s.,()]+$", "", apres).strip(" :()")
                if not libelle or len(libelle) < 3:
                    libelle = re.sub(r"(?i)^\s*total\s*", "", avant).strip(" :(")
                if libelle:
                    self.libelles_codes.setdefault(code, libelle)
                cl = sans_accents(libelle).lower()
                for col, motif in (("tva", r"\btva\b|\bvat\b"), ("droits", r"^droits?\b|duty|duties")):
                    if re.search(motif, cl) and col not in self.codes_colonnes:
                        tok = [t for t in ligne.toks if m.group(1) in t.t]
                        if tok:
                            self.codes_colonnes[col] = (code, _Span(tok[:1]))

    def _categorie(self, code: str | None, libelle: str | None) -> CategorieTaxe:
        for lib in (libelle, self.libelles_codes.get(code or "")):
            if lib:
                cl = sans_accents(lib).lower()
                for motif, cat in _CATEGORIES_LIBELLE:
                    if motif.search(cl):
                        return cat
        if code:
            if code not in _CATEGORIES_CODE and re.fullmatch(r"X\d{2}", code):
                return CategorieTaxe.autre_taxe  # codes X.. : accises et taxes nationales (« autres taxes »)
            return _CATEGORIES_CODE.get(code, CategorieTaxe.inconnue)
        return CategorieTaxe.inconnue

    # --- blocs d'articles ---------------------------------------------------------------------------------------

    def _blocs_articles(self) -> list[tuple[ValeurSourcee | None, int, int]]:
        ancres: list[tuple[int, _Lu]] = []
        vues: set[int] = set()
        for h in self._hits(["article"]):
            if h.ligne.idx in vues:
                continue
            lu = self.v_petit_entier(self._droite(h))
            if lu is None:
                for sp in self._dessous(h):
                    lu = self.v_petit_entier(sp)
                    if lu is not None:
                        break
            if lu is None:
                continue
            if self._en_tete_tableau(h.ligne):
                continue  # « Item | Commodity code | Origin … » : en-tête d'un tableau d'articles, pas un bloc
            # un vrai bloc annonce un code marchandise : sous son libellé, ou imprimé seul sur la ligne d'ancrage
            # juste après le numéro (« Article 1 — 2102109000 — origine CN … », D-2403)
            if not self._code_dans(h.ligne.idx, h.ligne.idx + 4) and self._code_ancre(h, lu) is None:
                continue
            vues.add(h.ligne.idx)
            if ancres and ancres[-1][1].valeur == lu.valeur and h.ligne.idx - ancres[-1][0] <= 3:
                continue  # même article annoncé deux fois (« article 1 » puis case « Article n° »)
            ancres.append((h.ligne.idx, lu))
        blocs = []
        n = len(self.lignes)
        for k, (debut, lu) in enumerate(ancres):
            limite = ancres[k + 1][0] if k + 1 < len(ancres) else n
            fin = limite
            for idx in range(debut + 1, limite):
                if any(x.cle in TERMINATEURS for x in self.hits_par_ligne.get(idx, [])):
                    fin = idx
                    break
            numero = self._vs(f"articles[{k}].numero_article", lu)
            blocs.append((numero, debut, fin))
            self.lignes_blocs.update(range(debut, fin))
        return blocs

    def _en_tete_tableau(self, ligne: _Ligne) -> bool:
        cles = {c.cle for c in self._colonnes(ligne)}
        return ("code" in cles and "origine" in cles and bool(
            {"montant_facture", "valeur", "base_droits", "masse_nette", "masse_brute"} & cles)) or \
            self._entete_taxes(ligne) is not None

    def _code_ancre(self, h: _Hit, numero: _Lu) -> _Lu | None:
        """Code marchandise sans libellé sur la ligne d'ancrage d'un bloc : premier mot qui suit le numéro
        d'article (au plus un tiret entre les deux), de forme stricte (8 ou 10 chiffres imprimés tels quels)."""
        toks = h.ligne.toks
        if not numero.span.toks or numero.span.toks[-1] not in toks:
            return None
        k = toks.index(numero.span.toks[-1]) + 1
        while k < len(toks) and toks[k].t in ("—", "–", "-", ":", "|"):
            k += 1
        if k >= len(toks):
            return None
        net = toks[k].t.strip(".,:;")
        if re.fullmatch(r"\d{8}(?:\d{2})?", net):
            return _Lu(_Span([toks[k]], h.score), net, net)
        cg = _code_groupes(toks[k:k + 4])
        if cg is not None and cg[0] == 0:
            sel = toks[k:k + cg[1]]
            return _Lu(_Span(sel, h.score), " ".join(t.t for t in sel), cg[2])
        return None

    def _code_dans(self, debut: int, fin: int) -> bool:
        for ligne in self.lignes[debut:fin]:
            if any(h.cle == "code_marchandise" for h in self.hits_par_ligne.get(ligne.idx, [])):
                return True
        return False

    def _article_bloc(self, numero: ValeurSourcee | None, debut: int, fin: int) -> None:
        k = len(self.champs.articles)
        base = f"articles[{k}]"
        lignes = set(range(debut, fin))
        if numero is not None:
            numero = numero.model_copy(update={"chemin": f"declaration.{base}.numero_article"})
            self.champs.definir(f"{base}.numero_article", numero)
        else:
            self.champs.articles.append(ArticleDeclaration())
        art = self.champs.articles[k]
        code = self._lire(["code_marchandise"], self.v_code_marchandise, lignes=lignes)
        if code is None:  # code imprimé sans libellé sur la ligne d'ancrage (D-2403)
            h = next((x for x in self._hits(["article"], {debut})), None)
            lu_num = self.v_petit_entier(self._droite(h)) if h is not None else None
            code = self._code_ancre(h, lu_num) if lu_num is not None else None
        art.code_marchandise = self._vs(f"{base}.code_marchandise", code)
        art.pays_origine = self._vs(f"{base}.pays_origine", self._lire(["pays_origine"], self.v_pays, lignes=lignes))
        art.regime = self._vs(f"{base}.regime",
                              self._lire(["regime"], lambda sp: self._v_motif(sp, r"\d{4}(?: \d{3})?"),
                                         lignes=lignes), type_valeur=TypeValeur.texte)
        art.code_preference = self._vs(f"{base}.code_preference",
                                       self._lire(["preference"], lambda sp: self._v_motif(sp, r"\d{3}"),
                                                  lignes=lignes), type_valeur=TypeValeur.texte)
        des = self._lire(["designation"], self.v_texte, lignes=lignes)
        if des is None:
            h = next((x for x in self._hits(["article"], lignes)), None)
            if h is not None:
                for sp in self._dessous(h):
                    des = self.v_texte(sp)
                    break
        art.description = self._vs(f"{base}.description", des, type_valeur=TypeValeur.texte)
        devise = self.champs.devise_facture.valeur if self.champs.devise_facture else None
        mt = self._lire(["montant_facture_article"], lambda sp: self.v_montant_devise(sp, devise), lignes=lignes)
        art.montant_facture_article = self._vs(f"{base}.montant_facture_article", mt,
                                               unite=(mt.extra.get("devise") if mt else None) or devise)
        vst = self._lire(["valeur_statistique"], lambda sp: self.v_montant_devise(sp, "EUR"), lignes=lignes)
        art.valeur_statistique = self._vs(f"{base}.valeur_statistique", vst, unite="EUR")
        art.masse_nette = self._vs(f"{base}.masse_nette", self._lire(["masse_nette"], self.v_masse, lignes=lignes),
                                   unite="KGM")
        art.masse_brute = self._vs(f"{base}.masse_brute", self._lire(["masse_brute"], self.v_masse, lignes=lignes),
                                   unite="KGM")
        q = self._lire(["unites_supplementaires"], self.v_quantite, lignes=lignes)
        if q is not None:
            art.quantite_unite_supplementaire = self._vs(f"{base}.quantite_unite_supplementaire", q,
                                                         unite=q.extra.get("unite"),
                                                         unite_brute=q.extra.get("unite_brute"))
        colis = self._lire(["colis"], self.v_entier, lignes=lignes, dessous=False)
        if colis is None:  # « 22 colis » : nombre imprimé devant le mot
            dans_libelle = {id(t) for h in self.hits if h.ligne.idx in lignes and h.cle != "colis" for t in h.toks}
            for idx in range(debut, fin):
                toks = self.lignes[idx].toks
                for n in range(1, len(toks)):
                    seul = n + 1 == len(toks) or toks[n + 1].x0 - toks[n].x1 > 3 * toks[n].hx
                    if toks[n].k in ("colis", "packages") and id(toks[n]) not in dans_libelle and seul \
                            and re.fullmatch(r"\d{1,6}", toks[n - 1].t):
                        colis = _Lu(_Span([toks[n - 1]]), toks[n - 1].t, str(int(toks[n - 1].t)))
                        break
                if colis is not None:
                    break
        art.nombre_colis = self._vs(f"{base}.nombre_colis", colis)
        if numero is not None:
            self.vs_articles[k] = numero
        for idx in range(debut, fin):
            cols = self._entete_taxes(self.lignes[idx])
            if cols:
                self._lignes_taxes(cols, idx, fin, numero)

    # --- tableaux ------------------------------------------------------------------------------------------------

    def _colonnes(self, ligne: _Ligne) -> list[_Colonne]:
        toks_l = ligne.toks
        # un intitulé de colonne en plusieurs mots est d'un seul tenant : « Taxe   Base » séparés par un blanc de
        # colonne sont deux colonnes, pas « Tax base » (D-2404)
        cands = [c for c in _candidats(toks_l, _INDEX_COL, _LMAX_COL)
                 if all(b.x0 - a.x1 <= max(0.02, 2.5 * a.hx) for a, b in pairwise(toks_l[c[3]:c[4]]))]
        choix = _resoudre(cands)
        cols: list[_Colonne] = []
        for _score, cle, i, j in sorted(choix, key=lambda c: c[2]):
            toks = ligne.toks[i:j]
            cols.append(_Colonne(cle, min(t.x0 for t in toks), max(t.x1 for t in toks)))
        # mots non reconnus de l'en-tête (« (EUR) », « kg ») : rattachés à la colonne de gauche
        couverts = {k for _s, _c, i, j in choix for k in range(i, j)}
        for k, t in enumerate(ligne.toks):
            if k in couverts or not cols:
                continue
            gauche = [c for c in cols if c.x1 <= t.x0 + 1e-6]
            if gauche:
                c = max(gauche, key=lambda c: c.x1)
                if t.x0 - c.x1 < 0.03:
                    c.x1 = max(c.x1, t.x1)
        return cols

    def _entete_taxes(self, ligne: _Ligne) -> list[_Colonne] | None:
        cols = self._colonnes(ligne)
        cles = {c.cle for c in cols}
        if "type" in cles and "montant" in cles and ({"base", "taux"} & cles):
            return cols
        return None

    def _cellules(self, ligne: _Ligne, cols: list[_Colonne], types: dict[str, str]) -> dict[str, _Span]:
        """Attribue les mots d'une ligne aux colonnes de l'en-tête. Les mots rapprochés forment un groupe
        (« 2 394,81 », « 2 article(s) », une désignation) attribué en bloc à la colonne dont l'en-tête le
        recouvre ; à défaut, chaque mot va à la colonne compatible la plus proche."""
        cells: dict[str, list[_Tok]] = {}
        groupes: list[list[_Tok]] = []
        for t in ligne.toks:
            if groupes and t.x0 - groupes[-1][-1].x1 <= 1.5 * t.hx:
                groupes[-1].append(t)
            else:
                groupes.append([t])

        def compatible(g: list[_Tok], c: _Colonne) -> bool:
            genre = types.get(c.cle, "texte")
            if genre == "code" and len(g) > 1:
                cg = _code_groupes(g)
                if cg is not None and cg[0] == 0 and cg[1] == len(g):
                    return True  # code marchandise imprimé par groupes (D-950)
            return _compatible(g[0], genre) if genre != "nombre" else any(_compatible(t, genre) for t in g)

        for g in groupes:
            gx0, gx1 = g[0].x0, g[-1].x1
            recouvertes = [c for c in cols if min(gx1, c.x1) - max(gx0, c.x0) > 0]
            justes = [c for c in recouvertes if compatible(g, c)]
            if justes and (len(recouvertes) == 1 or len(g) == 1):
                c = max(justes, key=lambda c: min(gx1, c.x1) - max(gx0, c.x0))
                cells.setdefault(c.cle, []).extend(g)
                continue
            precedent: _Colonne | None = None
            for t in g:  # mot par mot
                if precedent is not None and types.get(precedent.cle, "texte") == "texte" and not any(
                        min(t.x1, c.x1) - max(t.x0, c.x0) > 0 for c in cols):
                    cells.setdefault(precedent.cle, []).append(t)  # suite d'un texte (désignation)
                    continue
                meilleur, cout_min = None, 9.0
                for c in cols:
                    recouvrement = min(t.x1, c.x1) - max(t.x0, c.x0)
                    dist = 0.0 if recouvrement > 0 else max(c.x0 - t.x1, t.x0 - c.x1)
                    cout = dist + (0.0 if _compatible(t, types.get(c.cle, "texte")) else 0.5)
                    if cout < cout_min:
                        meilleur, cout_min = c, cout
                if meilleur is not None and cout_min < 0.25:
                    cells.setdefault(meilleur.cle, []).append(t)
                    precedent = meilleur
        return {k: _Span(sorted(v, key=lambda t: t.x0)) for k, v in cells.items()}

    def _lignes_taxes(self, cols: list[_Colonne], debut: int, fin: int, article: ValeurSourcee | None) -> None:
        types = {"type": "code_taxe", "base": "nombre", "taux": "nombre", "montant": "nombre", "mp": "mp",
                 "designation": "texte", "a_payer": "nombre", "numero": "entier"}
        # Deux tableaux côte à côte sous un même en-tête répété (« Taxe Base Taux Montant MP | Taxe Base … ») :
        # chaque moitié de ligne est lue avec ses propres colonnes, de gauche à droite (D-2404).
        blocs = _blocs_colonnes(cols)
        manquees = 0
        for idx in range(debut + 1, min(fin, len(self.lignes))):
            ligne_entiere = self.lignes[idx]
            if ligne_entiere.page != self.lignes[debut].page:
                break
            if re.match(r"(?i)\s*(?:total|totaux|summe|totale)\b", ligne_entiere.texte):
                break  # ligne de totaux (« Total A00: 13,00 Total B00: … ») : fin du tableau
            if len(blocs) > 1:
                lues = 0
                for cols_b, x0, x1 in blocs:
                    sous = [t for t in ligne_entiere.toks if x0 <= t.cx < x1]
                    if not sous:
                        continue
                    r = self._ligne_taxe(_Ligne(ligne_entiere.page, idx, sous), cols_b, types, article, 0)
                    lues += r == 0
                if lues:
                    manquees = 0
                    continue
                manquees += 1
                mots = any(len(re.sub(r"[^A-Za-z0-9]", "", t.t)) >= 3 for t in ligne_entiere.toks)
                if manquees > 1 or self.hits_par_ligne.get(idx) or (mots and not re.search(r"\d", ligne_entiere.texte)):
                    break
                continue
            r = self._ligne_taxe(ligne_entiere, cols, types, article, manquees)
            if r < 0:
                break
            manquees = r

    def _ligne_taxe(self, ligne: _Ligne, cols: list[_Colonne], types: dict[str, str], article: ValeurSourcee | None,
                    manquees: int) -> int:
        """Une ligne d'un tableau de taxes : 0 si une taxation est lue, ``manquees`` (inchangé) pour une ligne
        parasite ignorée, ``manquees + 1`` pour une ligne manquée tolérée, -1 pour la fin du tableau."""
        idx = ligne.idx
        cells = self._cellules(ligne, cols, types)
        code_sp = cells.get("type")
        code_lu = _code_taxe(code_sp, ligne) if code_sp else None
        if code_lu is None:
            code_lu = _code_taxe(_Span(ligne.toks[:1]), ligne)
        illisible = False
        if code_lu is None:
            if _parasite(ligne):
                return manquees
            # seulement dans un tableau de liquidation à colonne « article » : chaque ligne y porte son
            # rattachement, une ligne sans code ne décale pas les autres
            illisible = (article is not None or any(c.cle == "numero" for c in cols)) \
                and _ligne_taxe_chiffree(cells)
        if code_lu is None and not illisible:
            manquees += 1
            mots = any(len(re.sub(r"[^A-Za-z0-9]", "", t.t)) >= 3 for t in ligne.toks)
            if manquees > 1 or self.hits_par_ligne.get(idx) or (mots and not re.search(r"\d", ligne.texte)):
                return -1  # fin du tableau (une ligne illisible d'OCR est tolérée)
            return manquees
        self.lignes_tableaux.add(idx)
        libelle = cells.get("designation")
        if libelle is None and code_sp is not None and len(code_sp.toks) > 1:
            libelle = code_sp.depuis(code_sp.toks[1:])  # « A00 Customs duty » : code et libellé dans la cellule
        rattache = article
        if article is None and any(c.cle == "numero" for c in cols):  # liquidation à colonne « article »
            num = self.v_petit_entier(cells["numero"]) if "numero" in cells else None
            if num is None:
                num = self._numero_un_ocr(ligne, cols)
            if num is not None:
                rattache = self._vs(f"taxations[{len(self.champs.taxations)}].article", num)
        self._taxation(rattache, code_lu, libelle.texte if libelle else None, cells.get("base"),
                       cells.get("taux"), cells.get("montant"), cells.get("mp"), a_payer=cells.get("a_payer"))
        if illisible:
            # Ligne du tableau dont le code est illisible (OCR : « ae », « 00 ») mais dont base, taux et
            # montant sont imprimés : gardée (une somme des lignes lues incomplète fausserait C5 sans le dire),
            # code absent, confiance plafonnée (jamais une valeur clé d'un écart certain) (D-1805).
            self._lignes_sans_code.append(self.champs.taxations[-1])
            self.avertissements.append("code_taxe_illisible")
        return 0

    def _numero_un_ocr(self, ligne: _Ligne, cols: list[_Colonne]) -> _Lu | None:
        """OCR : numéro d'article « 1 » lu « I », « l » ou « | » dans la colonne des numéros (premier mot de la
        ligne, sous l'en-tête). Lecture corrigée par la forme : pénalité, jamais une valeur sûre (D-1805)."""
        col = next((c for c in cols if c.cle == "numero"), None)
        if col is None or not ligne.toks or self.pages[ligne.page].methode is not Methode.ocr:
            return None
        t = ligne.toks[0]
        if t.t in ("I", "l", "|", "i", "!") and t.x0 >= col.x0 - 0.005 and t.x1 <= col.x1 + 0.005:
            return _Lu(_Span([t]), t.t, "1", 0.25)
        return None

    def _taxation(self, article: ValeurSourcee | None, code: _Lu | None, libelle: str | None,
                  base: _Span | None, taux: _Span | None, montant: _Span | None, mp: _Span | None,
                  *, categorie: CategorieTaxe | None = None, taux_nature: TauxNature | None = None,
                  a_payer: _Span | None = None) -> None:
        k = len(self.champs.taxations)
        p = f"taxations[{k}]"
        tx = TaxationDeclaration()
        self.champs.taxations.append(tx)
        tx.article = self._copie(article, f"{p}.article")
        tx.type_taxe = self._vs(f"{p}.type_taxe", code, type_valeur=TypeValeur.code)
        cat = categorie or self._categorie(code.valeur if code else None, libelle)
        tx.categorie = cat
        if base is not None and not base.vide:
            ms = _nombres(base)
            if ms:
                m = ms[0]
                reste = base.texte[m.end():].strip()
                lu = self._lu_nombre(base, m)
                monnaie = re.match(r"([A-Z]{3})\b", reste)
                if lu is not None and reste and re.match(r"[A-Za-z]", reste) and not (
                        monnaie and monnaie.group(1) in ISO_4217):  # « 357,52 EUR » : base en montant
                    unite_brute = reste.split(" ")[0]
                    tx.base_quantite = self._vs(f"{p}.base_quantite", lu, type_valeur=TypeValeur.decimal)
                    u = normalize_unit(unite_brute.replace("(s)", ""))
                    tx.base_unite = self._vs(f"{p}.base_unite", _Lu(base.sous(m.end() + 1, len(base.texte)),
                                                                    unite_brute, u.code if u.connue
                                                                    else unite_brute),
                                             type_valeur=TypeValeur.unite)
                elif lu is not None:
                    tx.base_montant = self._vs(f"{p}.base_montant", lu, unite="EUR", type_valeur=TypeValeur.montant)
        if taux is not None and not taux.vide:
            ms = _nombres(taux)
            if ms and not taux.texte.endswith("…"):
                m = ms[0]
                lu = self._lu_nombre(taux, m)
                reste = taux.texte[m.end():].strip()
                if lu is not None:
                    if reste.startswith("%"):
                        lu = _Lu(taux.sous(m.start(), m.end() + 2), taux.texte[m.start():m.end() + 2].strip(),
                                 lu.valeur, lu.penalite)
                        tx.taux_nature = TauxNature.ad_valorem
                    elif re.match(r"[A-Z]{3}\s*/", reste):
                        tx.taux_nature = TauxNature.specifique
                    elif taux_nature is not None:
                        tx.taux_nature = taux_nature
                    elif tx.base_quantite is not None:
                        tx.taux_nature = TauxNature.specifique
                    else:
                        tx.taux_nature = TauxNature.ad_valorem
                    tx.taux = self._vs(f"{p}.taux", lu, type_valeur=TypeValeur.taux,
                                       unite="%" if tx.taux_nature is TauxNature.ad_valorem else None)
            elif ms and taux.texte.endswith("…"):
                tx.taux_nature = TauxNature.specifique if tx.base_quantite is not None else taux_nature
                self.avertissements.append("taux_tronque")
        if tx.taux is None and tx.base_quantite is not None and tx.taux_nature is None:
            tx.taux_nature = TauxNature.specifique
        if tx.taux is None and tx.taux_nature is None and cat is CategorieTaxe.tva and tx.base_montant is not None:
            tx.taux_nature = TauxNature.ad_valorem  # colonne TVA sans taux imprimé : la TVA est ad valorem
        repare = None
        if montant is not None and not montant.vide and self.sep == ",":
            # Lectures OCR d'un montant de colonne (D-712) : virgule lue « / » ou « | » (« 31/87 ») ; chiffre
            # de la colonne de statut collé au montant (« 929,527 » quand la colonne St est vide).
            txt = montant.texte.strip()
            m_rep = re.fullmatch(r"(\d{1,3}(?:[ .]?\d{3})*) ?[/|] ?(\d{2})", txt)
            m_col = re.fullmatch(r"(\d{1,3}(?:[ .]?\d{3})*),(\d{2})\d", txt) if mp is None or mp.vide else None
            m_ok = m_rep or m_col
            if m_ok:
                valeur = Decimal(re.sub(r"[ .]", "", m_ok.group(1)) + "." + m_ok.group(2))
                repare = _Lu(montant, txt, str(valeur), 0.15)
        if repare is not None:
            tx.montant = self._vs(f"{p}.montant", repare, unite="EUR", type_valeur=TypeValeur.montant)
        elif montant is not None and not montant.vide:
            ms = [m for m in _nombres(montant) if _a_decimales(m)] or _nombres(montant)
            if ms:
                tx.montant = self._vs(f"{p}.montant", self._lu_nombre(montant, ms[-1]), unite="EUR",
                                      type_valeur=TypeValeur.montant)
        if a_payer is not None and not a_payer.vide:  # colonne « À payer » (DE 14 03 042), distincte du montant
            ms = [m for m in _nombres(a_payer) if _a_decimales(m)] or _nombres(a_payer)
            if ms:
                tx.montant_a_payer = self._vs(f"{p}.montant_a_payer", self._lu_nombre(a_payer, ms[-1]), unite="EUR",
                                              type_valeur=TypeValeur.montant)
        if mp is not None and not mp.vide:
            # « É » / « À » : lettre du mode lue avec un accent par l'OCR
            tok = next((t for t in mp.toks if re.fullmatch(r"[A-Z0-9©]", sans_accents(t.t.strip(".,")))), None)
            if tok is None:
                # mode de paiement imprimé en toutes lettres (« Comptant », « Autoliquidation », « Deferred ») :
                # sens d'après le libellé, sans code (D-950)
                mot, sens = None, None
                for t in mp.toks:  # premier mot qui dit le mode (« (paiement différé) », « (payé comptant) »)
                    net = t.t.strip(".,()[]")
                    if not re.fullmatch(r"[^\W\d_]{4,}", net):
                        continue
                    cle_mot = sans_accents(net).lower()
                    sens = next((pn for motif, pn in _SENS_PAIEMENT if motif.match(cle_mot)), None)
                    if sens is not None:
                        mot = t
                        break
                if mot is not None and sens is not None and not (
                        sens is PaiementNormalise.autoliquide and cat is not CategorieTaxe.tva):
                    tx.mode_paiement = self._vs(f"{p}.mode_paiement", _Lu(mp.depuis([mot]), mot.t.strip(".,()[]"),
                                                                          mot.t.strip(".,()[]")),
                                                type_valeur=TypeValeur.code)
                    tx.paiement_normalise = sens
            if tok is not None:
                code_mp = {"©": "0"}.get(tok.t.strip(".,"), sans_accents(tok.t.strip(".,")))
                pen_mp = 0.1 if code_mp != tok.t.strip(".,") and tok.t.strip(".,") != "©" else 0.0
                leg = self.legende.get(code_mp)
                hors_portee = leg is not None and leg[1] and cat is not CategorieTaxe.tva
                if not hors_portee:  # « 7 = TVA autoliquidée » ne dit rien du paiement des droits
                    tx.mode_paiement = self._vs(f"{p}.mode_paiement", _Lu(mp.depuis([tok]), tok.t.strip(".,"),
                                                                          code_mp, pen_mp), type_valeur=TypeValeur.code)
                    tx.paiement_normalise = self._paiement(code_mp, cat)

    # --- articles en liste, taxations en prose (récapitulatif texte : courriel, certificat) -------------------

    def _articles_en_liste(self) -> list[tuple[int, tuple[int, int, int], int]]:
        """Articles d'un récapitulatif en texte : ligne d'ancrage « [1] 8467210000 Désignation » puis lignes de
        couples « libellé valeur » et de taxations en prose, jusqu'à l'ancre suivante, un libellé de niveau
        déclaration (documents, totaux, impositions globales) ou une ligne de totaux (D-1803)."""
        ancres = []
        for ligne in self.lignes:
            a = ancre_article(ligne.toks)
            if a is not None:
                ancres.append((ligne.idx, a))
        out = []
        for k, (debut, a) in enumerate(ancres):
            limite = ancres[k + 1][0] if k + 1 < len(ancres) else len(self.lignes)
            fin = debut + 1
            for idx in range(debut + 1, limite):
                ligne = self.lignes[idx]
                if ligne.page != self.lignes[debut].page and idx > debut + 1 and not segments_libelles(ligne.toks):
                    break
                if any(x.cle in TERMINATEURS for x in self.hits_par_ligne.get(idx, [])) or \
                        re.match(r"(?i)\s*(?:total|totaux|summe|totale)\b", ligne.texte):
                    break
                if not segments_libelles(ligne.toks) and ligne_taxe_prose(ligne.toks) is None:
                    break
                fin = idx + 1
            if fin == debut + 1:
                continue  # ligne isolée : pas un article d'un récapitulatif (aucun détail ni taxe ne suit)
            out.append((debut, a, fin))
            self.lignes_blocs.update(range(debut, fin))
        return out

    def _article_liste(self, debut: int, ancre: tuple[int, int, int], fin: int) -> None:
        ligne = self.lignes[debut]
        toks = ligne.toks
        k = len(self.champs.articles)
        base = f"articles[{k}]"
        i_num, i_code, j_code = ancre
        num = self.v_petit_entier(_Span([toks[i_num]]))
        numero = self._vs(f"{base}.numero_article", num)
        self.champs.definir(f"{base}.numero_article", numero)
        if numero is not None:
            self.vs_articles[k] = numero
        art = self.champs.articles[k]
        art.code_marchandise = self._vs(f"{base}.code_marchandise", self.v_code_marchandise(_Span(toks[i_code:j_code])))
        des = self.v_texte(_Span(toks[j_code:]))
        art.description = self._vs(f"{base}.description", des, type_valeur=TypeValeur.texte)
        devise = self.champs.devise_facture.valeur if self.champs.devise_facture else None
        for idx in range(debut + 1, fin):
            lt = self.lignes[idx].toks
            plages = ligne_taxe_prose(lt)
            if plages is not None:
                self._taxe_prose(self.lignes[idx], plages, numero)
                continue
            for champ, a, b in segments_libelles(lt):
                sp = _Span(lt[a:b])
                if champ == "pays_origine" and art.pays_origine is None:
                    art.pays_origine = self._vs(f"{base}.pays_origine", self.v_pays(sp))
                elif champ == "montant_facture_article" and art.montant_facture_article is None:
                    mt = self.v_montant_devise(sp, devise)
                    art.montant_facture_article = self._vs(f"{base}.montant_facture_article", mt,
                                                           unite=(mt.extra.get("devise") if mt else None) or devise)
                elif champ == "valeur_statistique" and art.valeur_statistique is None:
                    art.valeur_statistique = self._vs(f"{base}.valeur_statistique", self.v_montant_devise(sp, "EUR"),
                                                      unite="EUR")
                elif champ in ("masse_nette", "masse_brute") and getattr(art, champ) is None:
                    setattr(art, champ, self._vs(f"{base}.{champ}", self.v_masse(sp), unite="KGM"))
                elif champ == "nombre_colis" and art.nombre_colis is None:
                    art.nombre_colis = self._vs(f"{base}.nombre_colis", self.v_entier(sp))
                elif champ == "quantite" and art.quantite_unite_supplementaire is None:
                    q = self.v_quantite(sp)
                    art.quantite_unite_supplementaire = self._vs(
                        f"{base}.quantite_unite_supplementaire", q, unite=q.extra.get("unite") if q else None,
                        unite_brute=q.extra.get("unite_brute") if q else None)
                elif champ == "code_preference" and art.code_preference is None:
                    art.code_preference = self._vs(f"{base}.code_preference", self._v_motif(sp, r"\d{3}"),
                                                   type_valeur=TypeValeur.texte)
                elif champ == "regime" and art.regime is None:
                    art.regime = self._vs(f"{base}.regime", self._v_motif(sp, r"\d{4}(?: \d{3})?"),
                                          type_valeur=TypeValeur.texte)

    def _taxes_prose_hors_articles(self) -> list[tuple[int, dict[str, tuple[int, int]]]]:
        """Taxations en prose hors des articles (« FPE Droit forfaitaire petits envois : 2 articles x 3,00 EUR =
        6,00 EUR ») : taxations de niveau déclaration (D-1803)."""
        out = []
        for ligne in self.lignes:
            if ligne.idx in self.lignes_blocs or ligne.idx in self.lignes_tableaux:
                continue
            plages = ligne_taxe_prose(ligne.toks)
            if plages is not None and _code_taxe(_Span(ligne.toks[:1]), ligne) is not None:
                out.append((ligne.idx, plages))
                self.lignes_tableaux.add(ligne.idx)
        return out

    def _taxe_prose(self, ligne: _Ligne, plages: dict[str, tuple[int, int]], article: ValeurSourcee | None) -> None:
        toks = ligne.toks

        def sp(nom: str) -> _Span | None:
            return _Span(toks[plages[nom][0]:plages[nom][1]]) if nom in plages else None

        code = _code_taxe(_Span(toks[:1]), ligne)
        lib = sp("libelle")
        self._taxation(article, code, lib.texte if lib else None, sp("base"), sp("taux"), sp("montant"), sp("mp"))

    def _taxes_niveau_declaration(self) -> None:
        for ligne in self.lignes:
            if ligne.idx in self.lignes_blocs or ligne.idx in self.lignes_tableaux:
                continue
            cols = self._entete_taxes(ligne)
            if cols:
                self.lignes_tableaux.add(ligne.idx)
                self._lignes_taxes(cols, ligne.idx, len(self.lignes), None)

    def _forfait_sans_entete(self) -> None:
        """Ligne de droit forfaitaire « petits envois » lue hors tableau (en-tête des colonnes illisible, OCR) :
        « <libellé> N article(s) T EUR/art. M [MP] » : présence, base et taux seulement (pas le montant). Seulement
        si aucune ligne de forfait n'a été lue (D-811)."""
        if any(t.categorie is CategorieTaxe.forfait_petits_envois for t in self.champs.taxations):
            return
        for ligne in self.lignes:
            toks = ligne.toks
            if not _FORFAIT_LIBELLE_RE.search(sans_accents(" ".join(t.t for t in toks)).lower()):
                continue
            i = next((k for k in range(1, len(toks) - 1) if re.fullmatch(r"\d{1,4}", toks[k].t)
                      and _ARTICLES_RE.match(toks[k + 1].t)), None)
            # taux : nombre décimal suivi de « EUR/art. » (obligatoire : c'est lui qui fait la ligne de forfait)
            j = next((k for k in range((i + 2) if i is not None else 1, len(toks) - 1)
                      if _DECIMAL_RE.fullmatch(toks[k].t) and re.match(r"[A-Z]{3}\s*/", toks[k + 1].t)), None)
            if j is None:
                continue
            fin_taux = min(j + (3 if toks[j + 1].t.endswith("/") else 2), len(toks))  # « EUR/ art. » coupé
            libelle = " ".join(t.t for t in toks[: i if i is not None else j])
            base = _Span(toks[i:i + 2]) if i is not None else None
            # Le montant n'est pas repris : le tableau des taxes n'a pas été lu (en-tête illisible), d'autres
            # lignes ont pu échapper à la lecture ; un montant isolé fausserait les sommes (B2) et les
            # comparaisons de débours (G4). La ligne sert à sa présence, sa base et son taux (G2, G3, G6).
            self._taxation(None, None, libelle, base, _Span(toks[j:fin_taux]), None, None,
                           categorie=CategorieTaxe.forfait_petits_envois, taux_nature=TauxNature.specifique)
            self.avertissements.append("forfait_lu_hors_tableau")
            return

    def _tableaux_articles(self, blocs: list) -> list[tuple[list[_Colonne], int, int]]:
        out = []
        for ligne in self.lignes:
            if ligne.idx in self.lignes_blocs:
                continue
            cols = self._colonnes(ligne)
            cles = {c.cle for c in cols}
            # « type » : colonnes de taxation sur la ligne de l'article (tableau mixte, sous-lignes de taxe sous la
            # ligne de l'article, D-2405) ; exige alors la colonne du montant de la taxe
            if "code" in cles and "origine" in cles and ({"montant_facture", "valeur", "base_droits"} & cles) \
                    and ("type" not in cles or {"montant", "base"} <= cles):
                fin = self._fin_tableau(ligne.idx, cols)
                out.append((cols, ligne.idx, fin))
                self.lignes_tableaux.update(range(ligne.idx, fin))
        return out

    def _fin_tableau(self, debut: int, cols: list[_Colonne]) -> int:
        types = _TYPES_ARTICLES
        manquees = 0
        derniere = debut + 1
        for idx in range(debut + 1, len(self.lignes)):
            ligne = self.lignes[idx]
            if ligne.page != self.lignes[debut].page:
                break
            if any(h.cle in TERMINATEURS for h in self.hits_par_ligne.get(idx, [])) or \
                    re.match(r"(?i)\s*total\b", ligne.texte):
                break
            cells = self._cellules(ligne, cols, types)
            if _ligne_article(cells) or (cells.get("code") and _code_taxe(cells["code"], ligne)) \
                    or (cells.get("type") and _code_taxe(cells["type"], ligne)) or _sous_ligne_taxe_sans_code(cells):
                manquees = 0
                derniere = idx + 1
                continue
            if _parasite(ligne):
                continue  # débris d'OCR (filets du tableau)
            if derniere == idx and _suite_designation(ligne, cols):
                derniere = idx + 1  # suite de la désignation de l'article (« IMG-KB102-M, IMG-KB102-XL, »)
                continue
            manquees += 1
            if manquees > 1:
                break
        return derniere

    def _article_tableau(self, cols: list[_Colonne], debut: int, fin: int) -> None:
        types = _TYPES_ARTICLES
        devise = self.champs.devise_facture.valeur if self.champs.devise_facture else None
        courant: ValeurSourcee | None = None
        for idx in range(debut + 1, fin):
            ligne = self.lignes[idx]
            cells = self._cellules(ligne, cols, types)
            if _ligne_article(cells):
                k = len(self.champs.articles)
                base = f"articles[{k}]"
                num = self.v_petit_entier(cells["numero"]) if "numero" in cells else None
                if num is None:
                    num = self._numero_un_ocr(ligne, cols)
                courant = self._vs(f"{base}.numero_article", num)
                if courant is not None:
                    self.champs.definir(f"{base}.numero_article", courant)
                    self.vs_articles[k] = courant
                else:
                    self.champs.definir(f"{base}.numero_article", None)
                art = self.champs.articles[k]
                art.code_marchandise = self._vs(f"{base}.code_marchandise", self.v_code_marchandise(cells["code"]))
                if "designation" in cells:
                    art.description = self._vs(f"{base}.description", self.v_texte(cells["designation"]),
                                               type_valeur=TypeValeur.texte)
                if "origine" in cells:
                    art.pays_origine = self._vs(f"{base}.pays_origine", self.v_pays(cells["origine"]))
                if "montant_facture" in cells:
                    mt = self.v_montant_devise(cells["montant_facture"], devise)
                    art.montant_facture_article = self._vs(f"{base}.montant_facture_article", mt, unite=devise)
                elif "valeur" in cells:
                    dev_col = _devise_colonne(ligne, cols, "valeur", self.lignes[debut]) or devise
                    mt = self.v_montant_devise(cells["valeur"], dev_col)
                    art.montant_facture_article = self._vs(f"{base}.montant_facture_article", mt, unite=dev_col)
                if "valeur_statistique" in cells:
                    art.valeur_statistique = self._vs(f"{base}.valeur_statistique",
                                                      self.v_montant_devise(cells["valeur_statistique"], "EUR"),
                                                      unite="EUR")
                if "colis" in cells:
                    art.nombre_colis = self._vs(f"{base}.nombre_colis", self.v_entier(cells["colis"]))
                if "preference" in cells:
                    art.code_preference = self._vs(f"{base}.code_preference",
                                                   self._v_motif(cells["preference"], r"\d{3}"),
                                                   type_valeur=TypeValeur.texte)
                if "regime" in cells:
                    art.regime = self._vs(f"{base}.regime", self._v_motif(cells["regime"], r"\d{4}(?: \d{3})?"),
                                          type_valeur=TypeValeur.texte)
                if "quantite" in cells:
                    q = self.v_quantite(cells["quantite"])
                    art.quantite_unite_supplementaire = self._vs(
                        f"{base}.quantite_unite_supplementaire", q, unite=q.extra.get("unite") if q else None,
                        unite_brute=q.extra.get("unite_brute") if q else None)
                if "masse_brute" in cells:
                    art.masse_brute = self._vs(f"{base}.masse_brute", self.v_masse(cells["masse_brute"]), unite="KGM")
                if "masse_nette" in cells:
                    art.masse_nette = self._vs(f"{base}.masse_nette", self.v_masse(cells["masse_nette"]), unite="KGM")
                self._taxes_condensees(courant, cells)
                if cells.get("type") and (code_lu := _code_taxe(cells["type"], ligne)) is not None:
                    self._taxe_mixte(courant, code_lu, cells)
            elif cells.get("type") and (code_lu := _code_taxe(cells["type"], ligne)) is not None:
                # tableau mixte : sous-ligne de taxe dans les colonnes de taxation (« B00 222,94 20,0 % 44,59 »)
                self._taxe_mixte(courant, code_lu, cells)
            elif cells.get("code") and _code_taxe(cells["code"], ligne) is not None:
                # sous-ligne de taxe (« A30 Droit antidumping … ») rattachée à l'article courant
                code_lu = _code_taxe(cells["code"], ligne)
                lib = cells.get("designation")
                self._taxation(courant, code_lu, lib.texte if lib else None, cells.get("base_droits"),
                               cells.get("taux_droits"), cells.get("droits"), cells.get("statut"))
            elif courant is not None and _sous_ligne_taxe_sans_code(cells):
                # Sous-ligne de taxe dont le code est illisible (« x1 Droit spécifique … 623 LTR 0,12 74,76 ») :
                # la ligne existe et son montant est imprimé ; l'ignorer rendrait la somme des lignes lues
                # incomplète sans le signaler. Catégorie d'après le libellé seulement (sinon ``inconnue``),
                # confiance plafonnée (jamais une valeur clé d'un écart certain).
                lib = cells.get("designation")
                self._taxation(courant, None, lib.texte if lib else None, cells.get("base_droits"),
                               cells.get("taux_droits"), cells.get("droits"), cells.get("statut"))
                self._codes_illisibles.append(self.champs.taxations[-1])
                self.avertissements.append("code_taxe_illisible")

    def _taxe_mixte(self, article: ValeurSourcee | None, code: _Lu, cells: dict[str, _Span]) -> None:
        """Taxation lue dans les colonnes de taxation d'un tableau mixte (type, base, taux, montant, à payer, MP)."""
        self.lignes_tableaux.add(code.span.toks[0].li)
        self._taxation(article, code, None, cells.get("base"), cells.get("taux"), cells.get("montant"),
                       cells.get("mp"), a_payer=cells.get("a_payer"))

    def _taxes_condensees(self, article: ValeurSourcee | None, cells: dict[str, _Span]) -> None:
        """Colonnes droits / TVA d'un tableau condensé : une taxation par groupe de colonnes imprimé."""
        if any(k in cells for k in ("base_droits", "droits")):
            code = self.codes_colonnes.get("droits")
            code_lu = _Lu(code[1], code[1].toks[0].t.strip("()"), code[0]) if code else None
            self._taxation(article, code_lu, None, cells.get("base_droits"), cells.get("taux_droits"),
                           cells.get("droits"), cells.get("statut"), categorie=CategorieTaxe.droit,
                           taux_nature=TauxNature.ad_valorem)
        if any(k in cells for k in ("base_tva", "tva")):
            code = self.codes_colonnes.get("tva")
            code_lu = _Lu(code[1], code[1].toks[0].t.strip("()"), code[0]) if code else None
            self._taxation(article, code_lu, None, cells.get("base_tva"), None, cells.get("tva"),
                           cells.get("statut"), categorie=CategorieTaxe.tva, taux_nature=TauxNature.ad_valorem)

    # --- totaux, indices ---------------------------------------------------------------------------------------------

    def _totaux(self) -> None:
        tout = {li.idx for li in self.lignes} - self.lignes_tableaux
        self.champs.total_droits_taxes = self._vs(
            "total_droits_taxes", self._lire(["total_droits_taxes"], self.v_montant, lignes=tout, dessous=False),
            unite="EUR")
        self.champs.total_a_payer = self._vs(
            "total_a_payer", self._lire(["total_a_payer"], self.v_montant, lignes=tout, dessous=False), unite="EUR")

    def _indices(self) -> None:
        c = self.champs
        for d in c.documents_references:
            if d.type_code is None or d.type_code.valeur not in ("1008", "FR7"):
                continue
            typ = TypeIndiceAutoliquidation.code_1008 if d.type_code.valeur == "1008" \
                else TypeIndiceAutoliquidation.reference_fr7
            k = len(c.indices_autoliquidation)
            ind = IndiceAutoliquidation(type=typ)
            c.indices_autoliquidation.append(ind)
            ind.valeur = self._copie(d.type_code, f"indices_autoliquidation[{k}].valeur")
            ind.tva = self._copie(d.reference, f"indices_autoliquidation[{k}].tva")
        for tx in c.taxations:
            if tx.categorie is CategorieTaxe.tva and tx.paiement_normalise is PaiementNormalise.autoliquide \
                    and tx.mode_paiement is not None:
                k = len(c.indices_autoliquidation)
                ind = IndiceAutoliquidation(type=TypeIndiceAutoliquidation.mode_paiement_tva)
                c.indices_autoliquidation.append(ind)
                ind.valeur = self._copie(tx.mode_paiement, f"indices_autoliquidation[{k}].valeur")

    def _sens_taux_derive(self) -> None:
        """§8.7 : taux imprimé sans libellé de sens -> sens déduit (méthode ``derive``, confiance 0,85).

        Référence : table BCE (``context.options['taux_reference']``) si fournie ; à défaut, rapport entre un
        montant facturé en devise et la valeur statistique en EUR d'un même article imprimés sur le document."""
        c = self.champs
        if c.taux_change is None or c.taux_change_sens is not None or not c.taux_change.est_lisible:
            return
        taux = c.taux_change.decimal()
        devise = (c.devise_facture.valeur if c.devise_facture else None) or c.taux_change.unite
        sources: list[ValeurSourcee] = [c.taux_change]
        reference: Decimal | None = None  # devise par EUR
        table = self.context.options.get("taux_reference")
        if table is not None and devise and devise != "EUR" and c.date_acceptation is not None:
            try:
                reference = table.devise_par_eur(devise, c.date_acceptation.date_iso())
            except Exception:
                reference = None
        if reference is None:
            for a in c.articles:
                mf = a.montant_facture_article
                bases = [a.valeur_statistique] + [
                    t.base_montant for t in c.taxations if t.categorie is CategorieTaxe.droit
                    and t.article is not None and a.numero_article is not None
                    and t.article.valeur == a.numero_article.valeur]
                eur = next((v for v in bases if v is not None and v.est_lisible and v.decimal() > 0), None)
                if mf and eur and mf.est_lisible and mf.unite and mf.unite != "EUR":
                    reference = mf.decimal() / eur.decimal()  # unités de devise pour 1 EUR
                    sources += [mf, eur]
                    break
        if reference is None or reference <= 0 or taux <= 0:
            return
        ecart_dpe = abs(taux - reference) / reference
        ecart_epd = abs(Decimal(1) / taux - reference) / reference
        if min(ecart_dpe, ecart_epd) > Decimal("0.25") or abs(ecart_dpe - ecart_epd) < Decimal("0.05"):
            return
        sens = TauxChangeSens.devise_par_eur if ecart_dpe < ecart_epd else TauxChangeSens.eur_par_devise
        c.taux_change_sens = ValeurSourcee(
            id=self.ids.nouveau(Prefixe.valeur), chemin="declaration.taux_change_sens", valeur=sens.value,
            type=TypeValeur.enumeration, document_id=self.document.id, page=c.taux_change.page,
            extracteur=INFO, methode=Methode.derive, confiance=min(CONF_SENS_DERIVE, c.taux_change.confiance),
            derivee_de=[s.id for s in sources], regle_derivation="sens_taux_plus_proche_reference",
        )

    # --- recoupements (lectures OCR) -----------------------------------------------------------------------------

    def _reparer_separateurs(self) -> None:
        """OCR : une virgule décimale perdue (« 45185 » pour « 451,85 », « 47% » pour « 4,7 % ») rend la ligne
        de taxe incohérente. Si une seule relecture (montant / 100, taux / 10 ou / 100) rétablit
        base × taux = montant, elle est retenue avec une confiance plafonnée (jamais certaine) ; la valeur
        brute reste celle lue."""
        demi = Decimal("0.0051")

        def variantes(vs: ValeurSourcee | None, diviseurs: tuple[int, ...]) -> list[tuple[Decimal, bool]]:
            if vs is None or not vs.est_lisible:
                return []
            d = vs.decimal()
            out = [(d, False)]
            brut = (vs.valeur_brute or "").replace("%", "").strip()
            if self._est_ocr(vs) and re.fullmatch(r"\d{2,}", brut):
                out += [(d / k, True) for k in diviseurs]
            return out

        for tx in self.champs.taxations:
            if tx.taux_nature is not TauxNature.ad_valorem or tx.base_montant is None or tx.taux is None \
                    or tx.montant is None:
                continue
            solutions = []
            for b, rb in variantes(tx.base_montant, (100,)):
                for t, rt in variantes(tx.taux, (10, 100)):
                    for m, rm in variantes(tx.montant, (100,)):
                        if (rb or rt or rm) and t != 0 and abs(b * t / 100 - m) <= demi:
                            solutions.append(((b, rb), (t, rt), (m, rm)))
            if len(solutions) != 1 or abs(tx.base_montant.decimal() * tx.taux.decimal() / 100
                                          - tx.montant.decimal()) <= demi:
                continue
            for vs, (val, repare) in zip((tx.base_montant, tx.taux, tx.montant), solutions[0], strict=True):
                if repare:
                    exp = 2 if vs is not tx.taux else max(1, -val.normalize().as_tuple().exponent)
                    nouvelle = val.quantize(Decimal(1).scaleb(-exp))
                    object.__setattr__(vs, "valeur", str(nouvelle))
                    self._remplacer(vs, min(vs.confiance, PLAFOND_REPARE))
                    self._reparees.add(vs.id)

    def _confirmer(self, *valeurs: ValeurSourcee | None) -> None:
        for vs in valeurs:
            if vs is not None and self._est_ocr(vs):
                self._confirmees.add(vs.id)

    def _infirmer(self, *valeurs: ValeurSourcee | None) -> None:
        for vs in valeurs:
            if vs is not None and self._est_ocr(vs):
                self._infirmees.add(vs.id)

    def _recouper_montant_generique(self) -> None:
        """Montant total lu sous un libellé générique (« Montant facturé ») : plafonné à
        ``PLAFOND_INCOHERENT`` si les montants facturés lus par article, tous lisibles, ne lui sont pas égaux
        en somme (D-950)."""
        mt = self.champs.montant_total_facture
        if not self._mt_generique or mt is None or not mt.est_lisible:
            return
        montants = [a.montant_facture_article for a in self.champs.articles]
        if not montants or any(v is None or not v.est_lisible for v in montants):
            return
        somme = sum((v.decimal() for v in montants if v is not None), Decimal(0))
        if abs(somme - mt.decimal()) > Decimal("0.011") and mt.confiance > PLAFOND_INCOHERENT:
            self._remplacer(mt, PLAFOND_INCOHERENT)

    def _remplacer(self, vs: ValeurSourcee, conf: float) -> None:
        object.__setattr__(vs, "confiance", round(conf, 4))

    def _coherence(self) -> None:
        """Recoupements des lectures OCR (§6.3, §8.5.4). Une lecture OCR isolée reste sous ``C_MIN_CERTAIN``
        (``PLAFOND_OCR_SEUL``) ; elle n'atteint ``CONF_CONFIRMEE`` que si une relation indépendante imprimée
        sur le document la confirme (base × taux = montant, sommes, clé de TVA, double lecture…). Une relation
        contredite plafonne les lectures concernées à ``PLAFOND_INCOHERENT``."""
        self._confirmees: set[str] = set()
        self._infirmees: set[str] = set()
        #: lectures contredites par une relation qui prime sur toute confirmation (montant / à payer)
        self._douteuses: set[str] = set()
        self._reparer_separateurs()
        c = self.champs
        cent = Decimal("0.011")  # tolérance d'incohérence (T_LIGNE, §8.3)
        demi = Decimal("0.0051")  # confirmation : égalité au demi-centime près (arrondi d'un seul calcul)

        def lisibles(*vs: ValeurSourcee | None) -> bool:
            return all(v is not None and v.est_lisible for v in vs)

        def b1(tx: TaxationDeclaration) -> bool | None:
            if tx.taux_nature is TauxNature.ad_valorem and lisibles(tx.base_montant, tx.taux, tx.montant):
                calc = tx.base_montant.decimal() * tx.taux.decimal() / 100  # type: ignore[union-attr]
                m = tx.montant.decimal()  # type: ignore[union-attr]
                if abs(calc - m) <= demi:
                    return True
                if m == m.to_integral_value() and any(abs(x - m) < cent for x in (
                        calc.quantize(Decimal(1), rounding="ROUND_HALF_UP"),
                        calc.quantize(Decimal(1), rounding="ROUND_FLOOR"),
                        calc.quantize(Decimal(1), rounding="ROUND_CEILING"))):
                    return True  # droits arrondis à l'euro
                return False if abs(calc - m) > cent else None
            if tx.base_quantite is not None and lisibles(tx.base_quantite, tx.taux, tx.montant):
                ecart = abs(tx.base_quantite.decimal() * tx.taux.decimal()  # type: ignore[union-attr]
                            - tx.montant.decimal())  # type: ignore[union-attr]
                return True if ecart <= demi else (False if ecart > cent else None)
            return None

        # B1 : confirme le taux et le montant ; pas les centimes de la base (une erreur de lecture sur les
        # centimes de la base ne change presque pas le produit)
        for tx in c.taxations:
            ok = b1(tx)
            if ok is None:
                continue
            nul = tx.taux is not None and tx.taux.decimal() == 0
            if ok:
                self._confirmer(tx.montant, *(() if nul else (tx.taux,)))
                if tx.base_quantite is not None and not nul:
                    self._confirmer(tx.base_quantite)
            else:
                self._infirmer(tx.base_montant, tx.base_quantite, tx.taux, tx.montant)
        # montant et « à payer » d'une même ligne : égaux sauf paiement autoliquidé (à payer 0) ; un désaccord
        # (décimales perdues par l'OCR : « 12 » / « 12,12 ») rend les deux lectures douteuses (D-1805)
        for tx in c.taxations:
            if lisibles(tx.montant, tx.montant_a_payer) and tx.montant_a_payer.decimal() != 0 \
                    and tx.montant_a_payer.decimal() != tx.montant.decimal():  # type: ignore[union-attr]
                self._infirmer(tx.montant, tx.montant_a_payer)
                self._douteuses.update(v.id for v in (tx.montant, tx.montant_a_payer) if v is not None)
        # base TVA = base des droits + droits et taxes de l'article
        par_article: dict[str, list[TaxationDeclaration]] = {}
        for tx in c.taxations:
            par_article.setdefault(tx.article.valeur if tx.article and tx.article.valeur else "-", []).append(tx)
        for groupe in par_article.values():
            tvas = [t for t in groupe if t.categorie is CategorieTaxe.tva]
            autres = [t for t in groupe if t.categorie is not CategorieTaxe.tva]
            droit = next((t for t in autres if t.base_montant is not None), None)
            if len(tvas) != 1 or droit is None or not lisibles(tvas[0].base_montant, droit.base_montant) \
                    or not all(lisibles(t.montant) for t in autres):
                continue
            ajouts = [t.montant.decimal() for t in autres]  # type: ignore[union-attr]
            attendu = droit.base_montant.decimal() + sum(ajouts)  # type: ignore[union-attr]
            # une égalité entre deux lectures du même nombre n'est pas un recoupement (erreurs corrélées)
            if any(ajouts) and abs(attendu - tvas[0].base_montant.decimal()) <= demi:  # type: ignore[union-attr]
                self._confirmer(tvas[0].base_montant, droit.base_montant, *(t.montant for t in autres))
        # totaux des taxes
        montants = [tx.montant for tx in c.taxations]
        if _plusieurs(montants) and lisibles(c.total_droits_taxes, *montants):
            ok = abs(sum(m.decimal() for m in montants) - c.total_droits_taxes.decimal()) <= demi  # type: ignore
            (self._confirmer if ok else self._infirmer)(c.total_droits_taxes, *montants)
        if _plusieurs(montants) and lisibles(c.total_a_payer, *montants) and all(
                tx.paiement_normalise is not PaiementNormalise.inconnu for tx in c.taxations
                if tx.categorie is CategorieTaxe.tva):
            dus = sum(tx.montant.decimal() for tx in c.taxations  # type: ignore[union-attr]
                      if tx.paiement_normalise is not PaiementNormalise.autoliquide)
            ok = abs(dus - c.total_a_payer.decimal()) <= demi  # type: ignore[union-attr]
            (self._confirmer if ok else self._infirmer)(c.total_a_payer)
        # montant total facturé = somme des articles (même devise)
        mts = [a.montant_facture_article for a in c.articles]
        if _plusieurs(mts) and lisibles(c.montant_total_facture, *mts) and all(
                m.unite == c.montant_total_facture.unite for m in mts):  # type: ignore[union-attr]
            ok = abs(sum(m.decimal() for m in mts) - c.montant_total_facture.decimal()) <= demi  # type: ignore
            (self._confirmer if ok else self._infirmer)(c.montant_total_facture, *mts)
        # taux de change : montant facturé converti = valeur statistique (ou base des droits) d'un article
        self._recouper_taux()
        # masses, colis, nombre d'articles
        mbs = [a.masse_brute for a in c.articles]
        if _plusieurs(mbs) and lisibles(c.masse_brute_totale, *mbs):
            ok = abs(sum(m.decimal() for m in mbs) - c.masse_brute_totale.decimal()) \
                <= Decimal("0.0005")  # type: ignore[union-attr]
            (self._confirmer if ok else self._infirmer)(c.masse_brute_totale, *mbs)
        cls = [a.nombre_colis for a in c.articles]
        if _plusieurs(cls) and lisibles(c.nombre_colis_total, *cls):
            ok = sum(x.entier() for x in cls) == c.nombre_colis_total.entier()  # type: ignore[union-attr]
            (self._confirmer if ok else self._infirmer)(c.nombre_colis_total, *cls)
        if lisibles(c.nombre_articles) and c.articles:
            ok = c.nombre_articles.entier() == len(c.articles)  # type: ignore[union-attr]
            (self._confirmer if ok else self._infirmer)(c.nombre_articles)
        # identifiants : clé de TVA, EORI = SIREN de la TVA, doubles lectures (MRN, devise, date)
        for partie in (c.importateur, c.declarant):
            if lisibles(partie.tva) and tva_fr_valide(partie.tva.valeur) is True:  # type: ignore[union-attr]
                self._confirmer(partie.tva)
                if lisibles(partie.eori) and partie.eori.valeur[2:11] == partie.tva.valeur[4:]:  # type: ignore
                    self._confirmer(partie.eori)
        # double lecture : seulement sans caractère d'une classe de confusion (O/0, I/1…), car deux lectures
        # du même glyphe dans la même police se trompent de la même façon
        for vs in (c.mrn, c.devise_facture):
            if lisibles(vs) and not re.search(r"[0O1IL5S8B2Z6G]", (vs.valeur or "")[4:] if vs is c.mrn
                                              else "") and self._lectures(vs) >= 2:  # type: ignore[arg-type]
                self._confirmer(vs)
        # application
        for vs in self.champs.iter_valeurs():
            if not self._est_ocr(vs):
                continue
            plafond_page = self.pages[vs.page].plafond if vs.page in self.pages else 0.5
            if vs.id in self._reparees:
                continue  # relecture : jamais au-dessus de PLAFOND_REPARE
            if vs.id in self._douteuses or (vs.type is TypeValeur.montant
                                              and _ZERO_TETE_RE.match((vs.valeur_brute or "").strip())):
                self._remplacer(vs, min(vs.confiance, PLAFOND_INCOHERENT))
            elif vs.id in self._confirmees and vs.confiance >= 0.5:
                cible = CONF_CONFIRMEE if plafond_page >= 0.75 else min(PLAFOND_OCR_SEUL, vs.confiance + 0.1)
                self._remplacer(vs, max(vs.confiance, cible))
            elif vs.id in self._infirmees:
                self._remplacer(vs, min(vs.confiance, PLAFOND_INCOHERENT))

    def _recouper_taux(self) -> None:
        c = self.champs
        tx, sens = c.taux_change, c.taux_change_sens
        if tx is None or not tx.est_lisible or sens is None or not sens.est_lisible or tx.decimal() == 0:
            return
        for a in c.articles:
            mf = a.montant_facture_article
            refs = [a.valeur_statistique] + [t.base_montant for t in c.taxations
                                             if t.categorie is CategorieTaxe.droit and t.article is not None
                                             and a.numero_article is not None
                                             and t.article.valeur == a.numero_article.valeur]
            if mf is None or not mf.est_lisible or mf.unite in (None, "EUR"):
                continue
            eur = mf.decimal() / tx.decimal() if sens.valeur == TauxChangeSens.devise_par_eur.value \
                else mf.decimal() * tx.decimal()
            for r in refs:
                if r is not None and r.est_lisible and abs(eur - r.decimal()) <= Decimal("0.0051"):
                    self._confirmer(tx, sens, mf, r)
                    return

    def _lectures(self, vs: ValeurSourcee) -> int:
        """Nombre de lectures concordantes de la valeur ailleurs dans le document (titre, signature…)."""
        cible = norm_alnum(vs.valeur)
        n = 0
        for ligne in self.lignes:
            sp = _Span(ligne.toks)
            if vs.chemin.endswith("date_acceptation"):
                for m in _DATE_RE.finditer(sp.texte):
                    lu = self.v_date(sp.sous(m.start(), m.end()))
                    if lu is not None and lu.valeur == vs.valeur:
                        n += 1
                continue
            for t in ligne.toks:
                if norm_alnum(t.t) == cible:
                    n += 1
        return n


# --- aides de module -----------------------------------------------------------------------------------------

_TYPES_ARTICLES = {"numero": "entier", "code": "code", "designation": "texte", "origine": "pays",
                   "preference": "texte", "regime": "texte", "valeur_statistique": "nombre", "colis": "entier",
                   "montant_facture": "nombre", "valeur": "nombre", "quantite": "nombre", "masse_brute": "nombre",
                   "masse_nette": "nombre", "base_droits": "nombre", "taux_droits": "nombre", "droits": "nombre",
                   "base_tva": "nombre", "tva": "nombre", "statut": "mp",
                   # colonnes de taxation d'un tableau mixte (D-2405)
                   "type": "code_taxe", "base": "nombre", "taux": "nombre", "montant": "nombre", "a_payer": "nombre",
                   "mp": "mp"}


_LIBELLE_TAXE_RE = re.compile(r"\b(droits?|tax\w*|dut(y|ies)|accises?|excise|dumping|specifique|specific)\b")


def _blocs_colonnes(cols: list[_Colonne]) -> list[tuple[list[_Colonne], float, float]]:
    """En-tête répété sur une même ligne (deux tableaux côte à côte) : groupes de colonnes qui commencent à chaque
    nouvelle occurrence de la première colonne, avec leur étendue horizontale. Un seul groupe sinon."""
    if not cols or sum(1 for c in cols if c.cle == cols[0].cle) < 2:
        return [(cols, -1.0, 2.0)]
    groupes: list[list[_Colonne]] = []
    for c in cols:
        if c.cle == cols[0].cle or not groupes:
            groupes.append([c])
        else:
            groupes[-1].append(c)
    if any(len({c.cle for c in g}) != len(g) for g in groupes):
        return [(cols, -1.0, 2.0)]  # clé répétée dans un même groupe : pas deux tableaux
    out = []
    for k, g in enumerate(groupes):
        x0 = -1.0 if k == 0 else (groupes[k - 1][-1].x1 + g[0].x0) / 2
        x1 = 2.0 if k + 1 == len(groupes) else (g[-1].x1 + groupes[k + 1][0].x0) / 2
        out.append((g, x0, x1))
    return out


def _suite_designation(ligne: _Ligne, cols: list[_Colonne]) -> bool:
    """Ligne qui prolonge la désignation de l'article précédent : mots tous dans la colonne de la désignation
    (jusqu'à la colonne suivante), aucun montant décimal."""
    des = next((c for c in cols if c.cle == "designation"), None)
    if des is None or _DECIMAL_RE.search(ligne.texte):
        return False
    droite = min((c.x0 for c in cols if c.x0 > des.x1), default=1.0)
    return all(t.x0 >= des.x0 - 0.01 and t.x1 <= droite + 0.02 for t in ligne.toks)


def _sous_ligne_taxe_sans_code(cells: dict[str, _Span]) -> bool:
    """Sous-ligne d'un tableau condensé sans code de taxe lisible mais qui est une ligne de taxe : montant
    décimal dans la colonne des droits, et libellé de taxe ou base en quantité (« 623 LTR »)."""
    if _ligne_article(cells):
        return False
    droits = cells.get("droits")
    if droits is None or droits.vide or not _DECIMAL_RE.search(droits.texte):
        return False
    lib = cells.get("designation")
    if lib is not None and _LIBELLE_TAXE_RE.search(sans_accents(lib.texte).lower()):
        return True
    base = cells.get("base_droits")
    return base is not None and re.search(r"\d\s?[A-Za-z]{2,4}\b", base.texte) is not None


def _reference_apres_nature(toks: Sequence[_Tok], j: int) -> list[_Tok]:
    """Mots de la référence d'un document produit à partir du mot ``j`` qui suit le code.

    Quand une colonne « nature » (libellé en lettres, sans chiffre : « Facture commerciale », « LTA »,
    « Autoliquidation TVA — n° TVA ») sépare le code de la référence, la référence est le premier mot suivant
    qui porte un chiffre, avant tout autre code de document. Un court préfixe en capitales collé au numéro
    (« FT 4800/2026 ») en fait partie. À défaut, le mot ``j`` seul (comportement d'origine)."""
    def avec_prefixe(k: int) -> list[_Tok]:
        if k > j and re.fullmatch(r"[A-Z]{1,4}", toks[k - 1].t) and \
                toks[k].x0 - toks[k - 1].x1 <= 1.5 * max(toks[k].hx, 1e-3):
            return [toks[k - 1], toks[k]]
        return [toks[k]]

    if re.search(r"\d", toks[j].t):
        return [toks[j]]
    for k in range(j + 1, min(len(toks), j + 9)):
        t = toks[k].t.strip(".,;")
        if _CODE_DOC_RE.match(t) or t in ("1008", "FR7"):
            break
        if re.search(r"\d", t):
            return avec_prefixe(k) if len(re.sub(r"[^A-Za-z0-9]", "", t)) >= 4 else [toks[j]]
    return [toks[j]]


def _ligne_taxe_chiffree(cells: dict[str, _Span]) -> bool:
    """Ligne d'un tableau de taxes sans code lisible mais chiffrée : montant décimal, taux (« % » ou décimal) et
    base imprimés dans leurs colonnes."""
    montant, taux, base = cells.get("montant"), cells.get("taux"), cells.get("base")
    if not (montant is not None and _DECIMAL_RE.search(montant.texte) and taux is not None and "%" in taux.texte
            and base is not None and re.search(r"\d", base.texte)):
        return False
    # cohérence imprimée exigée : base × taux = montant (au centime, ou droits arrondis à l'euro)
    lus = []
    for sp in (base, taux, montant):
        ms = _nombres(sp)
        d = _decimal(ms[0].group(0), ",")[0] if ms else None
        if d is None:
            d = _decimal(ms[0].group(0), ".")[0] if ms else None
        lus.append(d)
    b, t, m = lus
    if b is None or t is None or m is None or m == 0:
        return False
    calc = b * t / 100
    return abs(calc - m) <= Decimal("0.011") or abs(calc.quantize(Decimal(1), rounding=ROUND_HALF_UP) - m) < Decimal("0.011")


def _parasite(ligne: _Ligne) -> bool:
    """Ligne de débris d'OCR (filets, ponctuation) : aucun mot de trois caractères alphanumériques."""
    return not any(len(re.sub(r"[^A-Za-z0-9]", "", t.t)) >= 3 for t in ligne.toks)


def _plusieurs(valeurs: Sequence[ValeurSourcee | None]) -> bool:
    """Au moins deux termes non nuls : une somme d'un seul terme recopie le même nombre (pas un recoupement)."""
    n = 0
    for v in valeurs:
        try:
            if v is not None and v.est_lisible and v.decimal() != 0:
                n += 1
        except ValueError:
            continue
    return n >= 2


def _b(v: float) -> float:
    return min(1.0, max(0.0, round(float(v), 5)))


def _candidats(toks: Sequence[_Tok], index: dict[str, list[tuple[str, str]]], lmax: int
               ) -> list[tuple[float, float, str, int, int]]:
    cands = []
    for i, t in enumerate(toks):
        if not t.k:
            continue
        acc = ""
        for j in range(i, min(len(toks), i + 9)):
            if toks[j].k == "" and j > i:
                continue
            acc += toks[j].k
            if len(acc) > lmax + 3:
                break
            for cle, vk in index.get(acc[:2], ()):
                if acc == vk:
                    s = 1.0
                elif abs(len(vk) - len(acc)) > max(1, len(vk) // 5) or len(vk) <= 4:
                    continue
                else:
                    s = _ratio(vk, acc)
                if s == 1.0 or s >= _seuil(len(vk)):
                    cands.append((s ** 3 * len(vk), s, cle, i, j + 1))
    return cands


def _resoudre(cands: list[tuple[float, float, str, int, int]]) -> list[tuple[float, str, int, int]]:
    cands.sort(key=lambda c: (-c[0], -c[1], c[3]))
    pris: set[int] = set()
    out = []
    for _p, s, cle, i, j in cands:
        r = set(range(i, j))
        if r & pris:
            continue
        pris |= r
        out.append((s, cle, i, j))
    return out


def _credible(toks: Sequence[_Tok], i: int, j: int) -> bool:
    """Un libellé est en tête de ligne, de colonne ou de case, ou suivi de « : » ; un mot identique au milieu
    d'une phrase (« édition logiciel déclarant … ») n'en est pas un."""
    if i == 0:
        return True
    prev = toks[i - 1]
    if prev.t in _SEPARATEURS or prev.t.endswith((":", ";", "|")) or _BOITE_RE.match(prev.t):
        return True
    if toks[i].t.startswith("(") and len(toks[i].t) > 2:
        return True  # « LRN… (version 1) », « Nom SARL (TVA FR…) » : rubrique ouverte par une parenthèse
    if prev.t in ("—", "–", "·", "•") and i >= 2:  # « LRN … — version 1 » : tiret séparateur de rubriques
        return True
    if prev.t == "/" and i >= 2 and re.match(r"[^\W\d_]", toks[i - 2].t[-1:] or "0"):
        return True  # « Colis / articles », « LRN / rang » : seconde partie d'une rubrique composée (D-2402)
    if toks[i].x0 - prev.x1 > 0.8 * toks[i].hx:
        return True
    if toks[j - 1].t.endswith((":", "..", "…")):
        return True
    return j < len(toks) and toks[j].t in (":", ".:", "…:")


def _compatible(t: _Tok, genre: str) -> bool:
    s = t.t.strip(".,:;")
    if genre == "texte":
        return True
    if genre == "pays":
        return bool(re.fullmatch(r"[A-Z]{2}", s))
    if genre == "code":
        return bool(re.fullmatch(r"[0-9OIlSB .]{6,12}", s)) or bool(_CODE_TAXE_RE.match(s)) or _code_minuscule(s)
    if genre == "code_taxe":
        return bool(_CODE_TAXE_RE.match(s)) or _code_minuscule(s)
    if genre == "mp":
        if re.fullmatch(r"[^\W\d_]{4,}", s):  # mode imprimé en toutes lettres (D-950)
            cle_mot = sans_accents(s).lower()
            return any(motif.match(cle_mot) for motif, _pn in _SENS_PAIEMENT)
        return bool(re.fullmatch(r"[A-Z0-9©]", sans_accents(s)))
    if genre == "entier":
        return bool(re.fullmatch(r"\d{1,3}", s))
    # nombre : chiffres, unité (%, kg, EUR/xxx, LTR…), ellipse
    return bool(re.search(r"\d", s)) or s in ("%", "…") or bool(re.fullmatch(r"[A-Za-z/().]{1,12}", s))


def _code_minuscule(s: str) -> bool:
    """Code de taxe dont la lettre a été lue en minuscule par l'OCR (« x01 »)."""
    return bool(re.fullmatch(r"[a-z][0-9OoIlSZ]{2}", s)) and bool(re.search(r"\d", s))


def _code_taxe(span: _Span, ligne: _Ligne | None = None) -> _Lu | None:
    if span is None or span.vide:
        return None
    t = span.toks[0]
    s = t.t.strip(".,:;()_|—-~'‘’\"°*«»[]{}")
    if _code_minuscule(s) and ligne is not None and _DECIMAL_RE.search(ligne.texte):
        # OCR : lettre du code lue en minuscule (« x01 » pour X01, droit spécifique). Seulement sur une ligne
        # qui porte un montant décimal, et avec au moins un chiffre lu tel quel : un débris d'OCR (« s00 »
        # sans montant) n'ouvre pas une ligne de taxation.
        s_lu, s = s, s[0].upper() + s[1:]
    else:
        s_lu = s
    if not _CODE_TAXE_RE.match(s) or s in _MOTS_NON_TAXE:
        return None
    corr = s[0] + s[1:].upper().translate(_VERS_CHIFFRE) if re.fullmatch(r"[A-Z][0-9OoIlSZQ]{2}", s) else s
    if not re.fullmatch(r"[A-Z]\d{2}|[A-Z]{3}", corr):
        return None
    pen = 0.0 if corr == s_lu else 0.12
    return _Lu(span.depuis([t]), s_lu, corr, pen)


_GROUPE_CODE_RE = re.compile(r"\d{4}(?:[ .]\d{2}){2,3}")


def _code_groupes(toks: Sequence[_Tok]) -> tuple[int, int, str] | None:
    """Code marchandise imprimé par groupes séparés d'espaces (« 8207 70 37 00 », « 8481 80 85 ») : mots
    consécutifs ``i`` à ``j`` exclus, rapprochés (pas de grand blanc), formant 4 + 2 + 2 (+ 2) chiffres, et
    chiffres joints. Seuls des chiffres imprimés tels quels (aucune correction lettre/chiffre)."""
    for i, t in enumerate(toks):
        if not re.fullmatch(r"\d{4}", t.t.strip(".,:;")):
            continue
        for n in (4, 3):
            sel = toks[i:i + n]
            if len(sel) < n:
                continue
            if any(b.x0 - a.x1 > 1.2 * max(a.hx, 1e-3) for a, b in pairwise(sel)):
                continue
            txt = " ".join(x.t.strip(",:;") for x in sel)
            if not _GROUPE_CODE_RE.fullmatch(txt.rstrip(".")):
                continue
            suivant = toks[i + n] if i + n < len(toks) else None
            if suivant is not None and re.fullmatch(r"\d{1,2}", suivant.t) and suivant.x0 - sel[-1].x1 < sel[-1].hx:
                continue  # groupe de chiffres qui continue : pas un code
            return i, i + n, re.sub(r"\D", "", txt)
    return None


def _ligne_article(cells: dict[str, _Span]) -> bool:
    code = cells.get("code")
    if code is None or code.vide:
        return False
    cg = _code_groupes(code.toks[:4])
    if cg is not None and cg[0] == 0:
        return True
    s = re.sub(r"[ .]", "", code.toks[0].t.strip(",:;"))
    return len(s) in (8, 10) and sum(c.isdigit() for c in s) >= len(s) - 2


def _devise_colonne(ligne: _Ligne, cols: list[_Colonne], cle: str, entete: _Ligne) -> str | None:
    col = next((c for c in cols if c.cle == cle), None)
    if col is None:
        return None
    for t in entete.toks:
        if t.x0 >= col.x0 - 0.005 and t.x1 <= col.x1 + 0.005:
            m = re.search(r"\b([A-Z]{3})\b", t.t)
            if m and m.group(1) in ISO_4217:
                return m.group(1)
    return None


def _tva(t: _Tok) -> tuple[str, str, float] | None:
    """Numéro de TVA lu dans un mot : (brut, valeur, pénalité). Confusions corrigées sur les positions
    numériques d'une TVA française, la clé est vérifiée. Un libellé collé au numéro (« TVAFR15000100008 »)
    est retiré si le numéro qui reste a une forme (et une clé) valide (D-952)."""
    brut = t.t.strip(".,:;()")
    colle = separer_libelle_tva(brut)
    if colle is not None:
        brut = colle
    net = re.sub(r"[^A-Za-z0-9]", "", brut).upper()
    if net.startswith("FR") and len(net) == 13:
        corps = net[2:].translate(_VERS_CHIFFRE)
        if not corps.isdigit():
            return None
        val = "FR" + corps
        pen = 0.0 if corps == net[2:] else 0.06
        ok = tva_fr_valide(val)
        if ok is False:
            pen += 0.4
        return brut, val, pen
    if re.fullmatch(r"(?!FR)[A-Z]{2}[0-9A-Z]{8,12}", net) and sum(c.isdigit() for c in net) >= 7 \
            and net[:2] in ISO2:
        return brut, net, 0.05
    return None
