"""Classement page par page (SPEC §5.3, §7.2, §9 P2) — déterministe, par mots-clés pondérés fr/en/es.

Chaque page reçoit un type parmi ceux de §6.2.6 ou ``continuation``, un sous-type, un motif P2 le cas
échéant et une confiance. Les règles de §5.3 sont appliquées explicitement :

- un document intitulé facture qui porte une référence de transport reste une facture (§5.3.5) ;
- un nom de transporteur ou d'intégrateur sur une facture commerciale n'en fait pas une facture de
  transitaire : seuls des libellés de débours et de prestations de dédouanement le font (§5.3.3) ;
- un avoir est reconnu par son intitulé ou par un total négatif (§5.3.1) ;
- conditions générales et lettres d'accompagnement sont des documents support (§7.2) ;
- un document intitulé facture mais qui est un devis, un bon de commande, une pré-alerte… est
  ``document_non_exploitable`` avec son motif (P2).

Le texte est une **donnée** (§20.2) : il n'est comparé qu'à des listes fermées de libellés. Le texte
invisible d'un PDF (retiré par ``pages``) n'est jamais lu ici ; le classement se fonde d'abord sur
l'en-tête visible de la page (titre en haut de page ou en grand corps), ce qui borne l'effet d'une
phrase glissée dans le corps.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field

from controldone.model.enums import (
    MotifNonExploitable,
    QualiteTexte,
    SousTypeDeclaration,
    SousTypeFactureCommerciale,
    SousTypeSupport,
    TypeDocument,
)
from controldone.normalize.refs import mrn_prefixe, norm_ref
from controldone.normalize.text import sans_accents

from .texte import Ligne, PageText

__all__ = [
    "CONTINUATION",
    "SEUIL_CONFIANCE",
    "VERSION_CLASSIFIEUR",
    "ClassementPage",
    "RefsPage",
    "classer_page",
    "detecter_langue",
    "extraire_refs",
]

VERSION_CLASSIFIEUR = "1.0.0"
#: §7.2 : confiance de classement < 0,70 -> ``inconnu``.
SEUIL_CONFIANCE = 0.70
CONTINUATION = "continuation"

_MRN_RE = re.compile(r"\b(\d{2}[A-Z]{2}[A-Z0-9]{14})\b")


def _norm(t: str) -> str:
    t = sans_accents(t).lower().replace("’", "'").replace("‘", "'")
    return re.sub(r"[ \t  ]+", " ", t)


def _rx(*motifs: str) -> re.Pattern[str]:
    return re.compile("|".join(f"(?:{m})" for m in motifs))


# --- libellés (texte normalisé : minuscules, sans accents) -----------------------------------------------

TITRE_FACTURE = _rx(
    r"\bcommercial invoice\b", r"\bfacture commerciale\b", r"\bfactura comercial\b", r"\btax invoice\b",
    r"\binvoice\b", r"\bfacture\b", r"\bfactura\b", r"\bpro ?-?forma\b", r"\brechnung\b",
    # de / it / nl / pt-tr-pl : « Handelsrechnung », « Fattura commerciale », « Handelsfactuur »,
    # « Voorschotfactuur », « Dienstenfactuur » (mots composés néerlandais et allemands)
    r"\b\w{0,16}rechnung\b", r"\bfattura\b",
    r"\b\w{0,16}factuur\b", r"\bfatura\b", r"\bfaktura\b",
)
TITRE_AVOIR = _rx(
    r"\bcredit note\b", r"\bcredit memo\b", r"\bfacture d'avoir\b", r"\bnote de credit\b",
    r"\bnota de credito\b", r"\bfactura rectificativa\b", r"\bavoir\b", r"\babono\b", r"\bcreditnote\b",
    r"\bgutschrift\b", r"\brechnungskorrektur\b", r"\bnota di credito\b", r"\bnota d'accredito\b",
    r"\bcreditnota\b", r"\bcreditfactuur\b", r"\bfactura de abono\b",
)
PRO_FORMA = _rx(r"\bpro ?-?forma\b")
VALEUR_DOUANE = _rx(r"for customs purposes? only", r"valeur (?:en douane|pour la douane) seulement",
                    r"customs value only", r"value for customs", r"solo (?:para|a efectos de) aduana",
                    r"\bcustoms invoice\b", r"facture (?:pour la )?douane")
SANS_VALEUR = _rx(r"no commercial value", r"sans valeur commerciale", r"\bncv\b", r"sin valor comercial",
                  r"free of charge", r"\bgratuit\b")

TITRE_DECLARATION = _rx(
    r"declaration (?:en )?douane", r"declaration d'importation", r"declaration (?:import|simplifiee)",
    r"customs declaration", r"import declaration", r"declaracion (?:de importacion|aduanera|en aduana)",
    r"document administratif unique", r"\bdau\b", r"\bh7\b", r"\bh1\b", r"avis de mainlevee",
    r"bon a enlever", r"preuve de ded\w*", r"proof of (?:customs )?clearance", r"dedouanement import",
    r"envoi de faible valeur",
    r"declaration de mise en libre pratique", r"liquidation des droits",
    # récapitulatifs et certificats de dédouanement, éditions de logiciel, autres langues
    r"(?:certificate|certificat|attestation) (?:of|de) (?:customs )?(?:clearance|dedouanement)",
    r"customs clearance (?:certificate|summary|confirmation)", r"clearance (?:certificate|summary)",
    r"customs release", r"\brelease note\b", r"declaration (?:acceptee|import(?:ation)? acceptee)",
    r"edition de la declaration", r"suite\W{0,4}(?:de la )?declaration", r"\bzollanmeldung\b", r"\beinfuhranmeldung\b",
    r"\bzollfreigabe\b", r"\bdichiarazione (?:doganale|di importazione)\b", r"\bbolletta doganale\b",
    r"\bdeclaracion (?:de importacion|aduanera|en aduana|sumaria)\b", r"\blevante aduanero\b",
    r"\bdouaneaangifte\b", r"\baangifte ten invoer\b", r"\binvoeraangifte\b",
)
CORPS_DECLARATION = _rx(
    r"\bmrn\b", r"\blrn\b", r"\bdeclarant\b", r"\bregime\b", r"\bprocedure\b", r"\bmainlevee\b",
    r"\bliquidation\b", r"\bbase d'imposition\b", r"\btype de taxe\b", r"\bmode de paiement\b",
    r"\b[ab]00\b", r"\bb00\b", r"\bcase \d+", r"\bde \d{2} \d{2}", r"\bunite supplementaire\b",
    r"\bvaleur statistique\b", r"\bdate d'acceptation\b", r"\bbureau de douane\b", r"\bcode marchandise\b",
    r"\bimportateur\b", r"\btaux de change\b", r"\bmontant total facture\b", r"\bpays d'origine\b",
    r"\bcustoms office\b", r"\bacceptance date\b", r"\bcommodity code\b", r"\bdeclarant\b",
    r"\bnombre d'articles\b", r"\bdroits et taxes\b", r"\baccepte le\b", r"\bref\. int", r"\bimportat\.",
    r"\bmise en libre pratique\b", r"\bcalcul des impositions\b", r"\bquotite\b",
    # en / de / it / es / nl
    r"\blocal reference\b", r"\bimporter\b", r"\bcountry of dispatch\b", r"\bnumber of items\b",
    r"\bstatistical value\b", r"\bsupporting documents\b", r"\bcustoms duty\b", r"\bimport vat\b",
    r"\btotal (?:duties and taxes|payable)\b", r"\bexchange rate\b", r"\bprocedure code\b",
    r"\bwarennummer\b", r"\bzollwert\b", r"\bannahmedatum\b", r"\banmelder\b", r"\beinfuhrer\b",
    r"\bversendungsland\b", r"\bzollstelle\b", r"\bcodice (?:merce|nc)\b", r"\bdata di accettazione\b",
    r"\bdichiarante\b", r"\bimportatore\b", r"\bufficio doganale\b", r"\bvalore statistico\b",
    r"\bfecha de admision\b", r"\bdeclarante\b", r"\bimportador\b", r"\baduana de\b",
    r"\bvalor estadistico\b", r"\baangever\b", r"\bgoederencode\b", r"\bdatum van aanvaarding\b",
    r"\bstatistische waarde\b", r"\bdouanekantoor\b",
)
TYPE_DAU = _rx(r"document administratif unique", r"\b(?:22 monnaie|33 code des marchandises|47 calcul|"
               r"8 destinataire|14 declarant|31 colis)")
CORPS_TRANSPORT = _rx(r"\bshipper\b", r"\bconsignee\b", r"\bnotify party\b", r"port of (?:loading|discharge)",
                      r"\bvessel\b", r"\bbill of lading\b", r"\bwaybill\b", r"airport of (?:departure|destination)",
                      r"\bchargeable weight\b", r"issuing carrier", r"\bfreight (?:prepaid|collect)\b",
                      r"\bplace of (?:receipt|delivery)\b", r"\bbill\b", r"\blading\b")
TYPE_H7 = _rx(r"\bh7\b", r"faible valeur", r"low value")
TYPE_PREUVE = _rx(r"preuve de ded\w*", r"dedouanement import", r"avis de mainlevee", r"bon a enlever",
                  r"proof of (?:customs )?clearance", r"release note",
                  r"(?:certificate|certificat|attestation) (?:of|de) (?:customs )?(?:clearance|dedouanement)",
                  r"customs clearance (?:certificate|summary|confirmation)", r"clearance (?:certificate|summary)",
                  r"customs release", r"\bzollfreigabe\b", r"\blevante aduanero\b")

# Facture de transitaire : libellés de débours et de prestations (jamais un nom de transporteur).
FORTS_TRANSITAIRE = _rx(
    r"\bdebours\b", r"\bdisbursements?\b", r"avance de fonds", r"frais d'avance", r"advance (?:fee|of funds)",
    r"\bfrais de dedouanement\b", r"\bcustoms clearance (?:fee|charges?)\b", r"\bclearance fee\b",
    r"\bhonoraires? de dedouanement\b", r"\bprestation de dedouanement\b", r"\bdroits de douane refactures\b",
    r"\btva (?:a l')?import(?:ation)? (?:refacturee|avancee|payee)\b", r"\bgastos suplidos\b", r"\bsuplidos\b",
    r"\bduties and taxes advanced\b", r"\brepresentation (?:en douane|fiscale)\b",
    # de / it / es / nl : débours, commission d'avance, prestation de dédouanement
    r"\bauslagen\b", r"\bvorlageprovision\b", r"\bverzollung\b", r"\bzollabfertigung\b",
    r"\banticipazion[ei]\b", r"\bcommissione (?:di )?anticip\w*", r"\bsdoganamento\b",
    r"\bcomision (?:por|de) anticipo\b", r"\bdespacho (?:de )?aduan\w*", r"\bhonorarios de despacho\b",
    r"\bvoorschot(?:ten|provisie|factuur)?\b", r"\binklaring\b", r"\bdouane-?afhandeling\b",
)
CORPS_TRANSITAIRE = _rx(
    r"\bdedouanement\b", r"\bcustoms clearance\b", r"\bdroits de douane\b", r"\bdroits et taxes\b",
    r"\bduties\b", r"\bimport vat\b", r"\btva import", r"\bmagasinage\b", r"\bstorage\b", r"\bmanutention\b",
    r"\bhandling\b", r"\bfrais de dossier\b", r"\bligne(?:s)? supplementaire", r"\badditional (?:line|item)s?\b",
    r"\btransitaire\b", r"\bfreight forwarder\b", r"\bcommissionnaire\b", r"\bsurcharge\b", r"\bmrn\b",
    r"\bprestations?\b", r"\bdossier\b", r"\bltas?\b", r"\bawb\b", r"\bdroit forfaitaire\b",
    r"\bzollabgaben\b", r"\beinfuhrumsatzsteuer\b", r"\blagergeld\b", r"\bumschlag\b", r"\bzustellung\b",
    r"\bleistungen\b", r"\bdazi[oe]?\b", r"\biva (?:all'|di )?importazione\b", r"\bmagazzinaggio\b",
    r"\bmovimentazione\b", r"\bspese di pratica\b", r"\baranceles?\b", r"\biva (?:de )?importacion\b",
    r"\balmacenaje\b", r"\bmanipulacion\b", r"\binvoerrechten\b", r"\bbtw bij invoer\b",
    r"\bopslag\b", r"\bbehandeling\b", r"\bbezorging\b",
)
CORPS_FACTURE_COMMERCIALE = _rx(
    r"\bhs ?code\b", r"\bcode (?:sh|nc|douanier)\b", r"\btariff code\b", r"\bcountry of origin\b",
    r"\bpays d'origine\b", r"\bpais de origen\b", r"\borigin\b", r"\bunit price\b", r"\bprix unitaire\b",
    r"\bprecio unitario\b", r"\bincoterms?\b", r"\b(?:fob|cif|exw|fca|cfr|cpt|cip|dap|ddp|dpu)\b",
    r"\bseller\b", r"\bexporter\b", r"\bvendeur\b", r"\bexportateur\b", r"\bnet weight\b", r"\bgross weight\b",
    r"\bpoids (?:net|brut)\b", r"\bsold to\b", r"\bbill to\b", r"\bship to\b", r"\bbuyer\b", r"\bacheteur\b",
    r"\bmade in\b", r"\bqty\b", r"\bquantite\b", r"\bcantidad\b", r"\bpart (?:no|number)\b",
    r"\breference article\b",
    # de / it / es / nl
    r"\b(?:waren|zoll)tarif(?:nummer)?\b", r"\bursprung(?:sland)?\b", r"\bherkunftsland\b",
    r"\blieferbedingungen\b", r"\bvoce doganale\b", r"\bpaese di origine\b", r"\borigine\b",
    r"\bprezzo unit\w*", r"\bpeso (?:netto|lordo|neto|bruto)\b", r"\bresa\b", r"\bpartida arancelaria\b",
    r"\bcondiciones de entrega\b", r"\bgn-?code\b", r"\boorsprong\b", r"\b(?:netto|bruto)gewicht\b",
    r"\bleveringsvoorwaarden\b", r"\bnettogewicht\b", r"\bbruttogewicht\b",
)

SUPPORT_TITRES: list[tuple[SousTypeSupport, re.Pattern[str]]] = [
    (SousTypeSupport.titre_transport, _rx(
        r"\bair ?way ?bill\b", r"\bairwaybill\b", r"lettre de transport aerien", r"\bbill of lading\b",
        r"\bconnaissement\b", r"\bcmr\b", r"lettre de voiture", r"\bsea waybill\b", r"\bwaybill\b",
        r"conocimiento de embarque", r"\bguia aerea\b", r"\bhawb\b", r"\bmawb\b", r"\blta\b(?! ?n)",
    )),
    (SousTypeSupport.liste_colisage, _rx(r"\bpacking list\b", r"\bliste de colisage\b", r"\blista de empaque\b",
                                         r"\bpacking slip\b", r"\bnote de colisage\b", r"\bcolisage\b",
                                         r"\bpackliste\b", r"\bpackzettel\b", r"\bpacking ?list\b",
                                         r"\b(?:lista|distinta) (?:di )?colli\b", r"\bdistint ?a di imball\w*", r"\bpaklijst\b",
                                         r"\blista de (?:empaque|embalaje|bultos)\b", r"\bpakbon\b")),
    (SousTypeSupport.conditions_generales, _rx(
        r"conditions generales", r"general (?:terms|conditions)", r"terms and conditions", r"conditions de vente",
        r"\bcgv\b", r"condiciones generales", r"terminos y condiciones", r"standard trading conditions",
        r"allgemeine (?:geschafts|liefer|verkaufs)\w*bedingungen", r"\bagb\b", r"\badsp\b",
        r"condizioni generali", r"algemene (?:leverings|verkoop)?voorwaarden",
    )),
    (SousTypeSupport.certificat, _rx(r"certificat d'origine", r"certificate of origin", r"\beur\.? ?1\b",
                                     r"\beur-med\b", r"certificado de origen", r"\bcertificat\b",
                                     r"\bcertificate\b", r"\bcertificado\b")),
    (SousTypeSupport.preuve_paiement, _rx(r"avis de (?:virement|paiement)", r"ordre de virement",
                                          r"payment (?:advice|confirmation)", r"remittance advice",
                                          r"proof of payment", r"preuve de paiement", r"\bmt ?103\b",
                                          r"justificante de pago", r"confirmation de (?:virement|paiement)")),
    (SousTypeSupport.pre_alerte, _rx(r"\bpre-? ?alert", r"\bprealerte\b", r"\bpre-alerte\b",
                                     r"shipment notification", r"avis d'expedition", r"advance shipping notice",
                                     r"arrival notice", r"avis d'arrivee", r"notification d'arrivee",
                                     r"aviso de llegada")),
]

LETTRE = _rx(
    r"madame,? monsieur", r"\bdear (?:sir|madam|sirs|customer|mr|ms)", r"veuillez trouver", r"please find (?:enclosed|attached)",
    r"\bci-?joint", r"\bcordialement\b", r"\bsincerely\b", r"kind regards", r"best regards",
    r"salutations distinguees", r"\batentamente\b", r"\bestimad[oa]s?\b", r"nous vous prions", r"\bobjet ?:",
    r"\bsubject ?:", r"\bre ?:",
    # de / it / es / nl
    r"sehr geehrte", r"mit freundlichen gru", r"\banbei\b", r"\bbetreff ?:", r"\bgentil[ei] (?:signor|client)",
    r"cordiali saluti", r"distinti saluti", r"\bin allegato\b", r"\boggetto ?:", r"\badjunt[oa]s?\b",
    r"\basunto ?:", r"\bun saludo\b", r"\bgeachte\b", r"met vriendelijke groet", r"\bbijgaand\b",
    r"\bin de bijlage\b", r"\bonderwerp ?:",
)
CG_CORPS = _rx(r"\barticle \d+", r"\bart\. \d+", r"\bclause \d+", r"\bresponsabilite\b", r"\bliability\b",
               r"\bjuridiction\b", r"\bjurisdiction\b", r"\btribunal\b", r"\bforce majeure\b")

NON_EXPLOITABLE: list[tuple[MotifNonExploitable, re.Pattern[str]]] = [
    (MotifNonExploitable.devis, _rx(r"\bdevis\b", r"\bquotation\b", r"\bquote\b", r"offre de prix",
                                    r"\bcotizacion\b", r"\bpresupuesto\b", r"proposition (?:commerciale|tarifaire)",
                                    r"price offer")),
    (MotifNonExploitable.bon_commande, _rx(r"bon de commande", r"purchase order", r"orden de compra",
                                           r"confirmation de commande", r"order confirmation", r"pedido de compra",
                                           r"\bp\.?o\.? (?:no|number|n)")),
    (MotifNonExploitable.pre_alerte, _rx(r"\bpre-? ?alert", r"\bprealerte\b", r"\bpre-alerte\b",
                                         r"shipment notification", r"advance shipping notice")),
    (MotifNonExploitable.liste_expedition, _rx(r"liste d'expedition", r"shipping list", r"liste de chargement",
                                               r"packing details", r"shipping details", r"details d'expedition",
                                               r"loading list", r"lista de envio", r"shipping manifest")),
    (MotifNonExploitable.bon_livraison_sans_valeur, _rx(r"bon de livraison", r"delivery note", r"\balbaran\b",
                                                        r"nota de entrega", r"delivery slip",
                                                        r"bordereau de livraison", r"delivery order")),
    (MotifNonExploitable.liste_reparation, _rx(r"liste de reparation", r"repair list", r"repair order",
                                               r"ordre de reparation", r"lista de reparacion",
                                               r"\breparations?\b", r"\brepairs?\b")),
    (MotifNonExploitable.document_export, _rx(r"declaration d'export", r"export declaration",
                                              r"document d'export", r"export accompanying document",
                                              r"declaracion de exportacion", r"\bex-?a\b", r"\bex ?1\b",
                                              r"facture d'export(?:ation)? (?:temporaire)?")),
    (MotifNonExploitable.perfectionnement_passif, _rx(r"perfectionnement passif", r"outward processing",
                                                      r"perfeccionamiento pasivo")),
    (MotifNonExploitable.recu, _rx(r"^\s*recu\b", r"\breceipt\b", r"\brecibo\b", r"\bquittance\b",
                                   r"recu de paiement")),
]

#: Mentions explicites « ce document n'est pas la facture » (P2), cherchées dans tout le texte.
P2_CORPS = _rx(r"commercial invoice (?:sent separately|to follow|will follow)", r"not a payable document",
               r"shipping details only", r"facture commerciale (?:suivra|envoyee separement)",
               r"document sans valeur commerciale", r"ceci n'est pas une facture", r"this is not an invoice")

#: Montant à payer imprimé positif (« Net à payer 1 173,99 € ») : un tiret isolé ailleurs (« Total débours   -
#: 975,38 € », OCR) ne fait pas un avoir.
_A_PAYER_POSITIF = re.compile(
    r"\b(?:net a payer|total ttc|amount due|balance due|grand total|total general|rechnungsbetrag|totale documento|"
    r"total factura|totaal incl\.? btw)\b[a-z :€$£.]{0,25}?(?<![\w.,/-])(?<!- )(?<!\()\d", re.MULTILINE)
_TOTAL_NEGATIF = re.compile(
    r"(?<!sous-)(?<!sous )(?<!sub-)(?<!sub )(?<!sub)\b(?:total|net a payer|amount due|montant (?:total|du)|"
    r"importe total|total general|grand total|balance due|a payer|to pay)\b[a-z :€$£.]{0,25}?"
    r"(?:(?<![\w.,/])-\s?\d|\(\s?\d[\d .,']*\)|\d[\d.,']*-[ \t]*$)",
    re.MULTILINE,
)

#: Après un libellé de titre : étiquette de champ (« Connaissement n° : X ») ou début de phrase (« Invoice. »).
#: « / » n'en fait une étiquette que s'il annonce un autre libellé court suivi de « : » (« AWB / B/L: ») ;
#: « PURCHASE ORDER / FACTURE » reste un intitulé (bon de commande, P2) — D-2114.
_SUITE_CHAMP = re.compile(r"\s*(?:n°|nº|no\b|nr\b|number|numero|#|:|ref|/(?=\s*[^\s:]{1,8}\s*:))")
_SUITE_PHRASE = re.compile(r"\.\s+\w")
#: « Invoice currency / total », « Facture : montant » : rubrique qui cite la facture (déclaration), pas un intitulé.
_SUITE_CITATION = re.compile(r"\.\s+\w|\s*(?:currency|value|amount|total)\b")
#: Un « mot » compte s'il porte une lettre ou un chiffre (« / », « — », « | » ne comptent pas).
_MOT = re.compile(r"[a-z0-9]")
#: Mot qui, juste avant un libellé de titre, en fait une référence citée (« Ref. invoice », « Réf. facture »).
_CITATION_AVANT = re.compile(r"(?:ref|refs|reference|your|votre|vtre|uw|ihre|vostra|su)[.:]?")

_PAGE_N = re.compile(r"\b(?:page|pag|pagina|seite|blatt|blad|p\.)\s*[:.]?\s*(\d{1,3})\s*(?:/|of|sur|de|von|di|van)\s*"
                     r"(\d{1,3})\b")
#: « Page 2 » seul sur sa ligne, sans total.
_PAGE_SEULE = re.compile(r"^[ \t]*(?:page|seite|pagina|pag\.?|blad|blatt)[ \t]*[:.]?[ \t]*(\d{1,3})[ \t]*$", re.MULTILINE)
_SUITE = re.compile(r"\b(?:suite|continued|continuation|a reporter|report|carried forward|(?:\(|-)\s?cont|"
                    r"fortsetzung|ubertrag|seguito|riporto|continuacion|suma y sigue|vervolg)\b")
_NUM_FACTURE = re.compile(
    r"(?:invoice|facture|factura|avoir|credit note|nota de credito|note de credit|inv)\.?[ \t]*"
    r"(?:(?:no|n\.?\s?°|n\.?\s?º|n o|nr|num(?:ero|ber)?|#|ref)\.?[ \t]*(?:de facture)?[ \t]*[:#]?|[:#])[ \t]*"
    r"([a-z0-9][a-z0-9\-/_.]{2,30})"
)
_NUM_FACTURE2 = re.compile(
    r"(?:n°|no\.?|numero|number|num\.?)[ \t]*(?:de |of )?(?:la )?(?:facture|invoice|factura|avoir|credit note)"
    r"[ \t]*[:#]?[ \t]*([a-z0-9][a-z0-9\-/_.]{2,30})"
)
_AVANT_NUM_EXCLU = re.compile(r"(?:montant|total|valeur|amount|value|date|importe|ref(?:erence)?s?)[^\n]{0,12}$")
_MOTS_LANGUE = {
    "fr": {"le", "la", "les", "des", "du", "et", "pour", "facture", "montant", "pays", "poids", "droits", "taxe",
           "date", "total", "avec", "sur", "par"},
    "en": {"the", "and", "of", "invoice", "amount", "total", "weight", "country", "to", "for", "with", "by", "due",
           "price", "description"},
    "es": {"el", "los", "las", "del", "y", "factura", "importe", "peso", "pais", "por", "con", "para", "precio",
           "cantidad"},
    "de": {"der", "die", "das", "und", "fur", "mit", "von", "rechnung", "betrag", "datum", "menge", "summe",
           "zoll", "gesamt"},
    "it": {"il", "di", "della", "delle", "fattura", "importo", "data", "totale", "per", "con", "prezzo",
           "cliente", "dazio"},
    "nl": {"het", "een", "en", "van", "factuur", "bedrag", "datum", "totaal", "voor", "met", "klant",
           "omschrijving", "btw"},
}
_ORDRE_LANGUES = ["fr", "en", "es", "de", "it", "nl"]


@dataclass(frozen=True)
class RefsPage:
    """Références clés lues sur une page (servent au découpage, §7.2)."""

    mrns: tuple[str, ...] = ()
    numero_facture: str | None = None
    page_n: int | None = None
    page_total: int | None = None

    @property
    def mrn_prefixes(self) -> tuple[str, ...]:
        vus: list[str] = []
        for m in self.mrns:
            p = mrn_prefixe(m)
            if p not in vus:
                vus.append(p)
        return tuple(vus)


@dataclass
class ClassementPage:
    numero: int
    type: TypeDocument | str
    sous_type: str | None = None
    confiance: float = 0.0
    motif_non_exploitable: MotifNonExploitable | None = None
    refs: RefsPage = field(default_factory=RefsPage)
    titre: str | None = None
    langue: str | None = None
    #: Indices retenus (identifiants de règles, sans texte du document).
    indices: list[str] = field(default_factory=list)
    #: La page porte un intitulé propre (et non des indices de corps seulement).
    intitulee: bool = False
    #: Le haut de page annonce une suite (« Suite », « page 2/2 », « Fortsetzung »…) : D-2113.
    suite: bool = False

    @property
    def est_continuation(self) -> bool:
        return self.type == CONTINUATION


def detecter_langue(texte: str) -> str | None:
    mots = re.findall(r"[a-z]+", _norm(texte))
    if not mots:
        return None
    comptes = {lg: sum(1 for m in mots if m in voc) for lg, voc in _MOTS_LANGUE.items()}
    tri = sorted(comptes.items(), key=lambda kv: (-kv[1], kv[0]))
    if tri[0][1] == 0:
        return None
    if tri[1][1] >= 0.6 * tri[0][1] and tri[1][1] >= 3:
        return "_".join(sorted([tri[0][0], tri[1][0]], key=_ORDRE_LANGUES.index))
    return tri[0][0]


def extraire_refs(texte: str) -> RefsPage:
    """MRN (18 caractères, année puis code pays), numéro de facture et « page n/m »."""
    haut = texte.upper()
    mrns: list[str] = []
    for m in _MRN_RE.finditer(haut):
        v = m.group(1)
        if v not in mrns:
            mrns.append(v)
    t = _norm(texte)
    num = None
    for rx in (_NUM_FACTURE2, _NUM_FACTURE):
        for m in rx.finditer(t):
            cand = m.group(1).strip("._-/")
            if _AVANT_NUM_EXCLU.search(t[max(0, m.start() - 30):m.start()]):
                continue  # « montant total facturé : 12 540,00 », « référence facture : … » (citation)
            if re.match(r"[.,]\d", t[m.end(1):m.end(1) + 2]):
                continue  # un montant, pas un numéro
            if any(c.isdigit() for c in cand) and not re.fullmatch(r"\d{1,2}[/.-]\d{1,2}[/.-]\d{2,4}", cand):
                num = norm_ref(cand)
                break
        if num:
            break
    pn = pt = None
    m = _PAGE_N.search(t)
    if m:
        pn, pt = int(m.group(1)), int(m.group(2))
        if pt == 0 or pn > pt:
            pn = pt = None
    else:
        m = _PAGE_SEULE.search(t)
        if m and int(m.group(1)) > 0:
            pn = int(m.group(1))  # « Page 2 » seul sur sa ligne (relevé sur plusieurs pages, D-2113)
    return RefsPage(mrns=tuple(mrns), numero_facture=num, page_n=pn, page_total=pt)


@dataclass
class _Titres:
    """Lignes d'en-tête normalisées : ``grandes`` (grand corps, moitié haute) et ``entete`` (haut de page)."""

    grandes: list[str]
    entete: list[str]
    #: Lignes entières du haut de page (un intitulé espacé, « Suite   déclaration », forme plusieurs segments).
    lignes: list[str] = field(default_factory=list)

    @property
    def texte_entete(self) -> str:
        return "\n".join(self.entete)

    @property
    def texte_lignes(self) -> str:
        return "\n".join(self.entete + self.lignes)

    def niveau(self, rx: re.Pattern[str], *, exclure_suite: re.Pattern[str] | None = None) -> int:
        return self.rang(rx, exclure_suite=exclure_suite)[0]

    def rang(self, rx: re.Pattern[str], *, exclure_suite: re.Pattern[str] | None = None) -> tuple[int, int]:
        """(niveau, position de la première ligne qui porte l'intitulé) ; niveau 2 : intitulé en grand corps ; 1 : en tête d'un segment court de l'en-tête ; 0 : absent.

        Le libellé doit ouvrir le segment (au plus un mot avant : « COMMERCIAL INVOICE », « Facture N° … »)
        ou le segment doit être très court (≤ 4 mots) ; segment de 10 mots au plus. Une phrase (« veuillez
        trouver ci-joint notre facture… ») ne compte pas. ``exclure_suite`` : texte qui, juste après le
        libellé, en fait une étiquette de champ (« Connaissement n° : … ») et non un intitulé.
        """
        def ok1(li: str) -> bool:
            mots = [w for w in li.split() if _MOT.search(w)]
            if len(mots) > 10:
                return False
            for m in rx.finditer(li):
                if exclure_suite is not None and exclure_suite.match(li, m.end()):
                    continue
                avant = [w for w in li[: m.start()].split() if _MOT.search(w)]
                if avant and (any(c.isdigit() for c in avant[-1]) or _CITATION_AVANT.fullmatch(avant[-1])):
                    # « N380 Facture commerciale … » (rangée d'un tableau de documents), « Ref. invoice : … »
                    # (référence citée) : pas un intitulé
                    continue
                if len(avant) <= 1 or len(mots) <= 4:
                    return True
            return False

        def ok(li: str) -> bool:
            if ok1(li):
                return True
            # intitulé espacé lettre à lettre par l'OCR (« HAN DE LS FACTU U R ») : relu sans les blancs
            mots = li.split()
            if 3 <= len(mots) <= 12 and sum(len(w) for w in mots) <= 3 * len(mots) and all(w.isalpha() for w in mots):
                return ok1("".join(mots))
            return False

        for i, li in enumerate(self.grandes):
            if ok(li):
                return 2, i
        for i, li in enumerate(self.entete):
            if ok(li):
                return 1, i
        return 0, 10**6

    def premiere(self) -> str | None:
        for li in self.grandes + self.entete:
            if li.strip():
                return li.strip()[:80]
        return None


def _segments(ligne: Ligne, ecart: float = 0.02) -> list[tuple[str, float | None, float]]:
    """Segments d'une ligne séparés par un blanc de colonne : (texte, taille médiane des mots, y0).

    Un intitulé aligné à droite sur la ligne du nom de société (« SOCIÉTÉ X      PACKING LIST ») forme son
    propre segment."""
    sortie: list[tuple[str, float | None, float]] = []
    courant: list = []

    def fermer() -> None:
        if courant:
            tailles = sorted(m.taille for m in courant if m.taille)
            taille = tailles[len(tailles) // 2] if tailles else None
            sortie.append((" ".join(m.texte for m in courant), taille, min(m.y0 for m in courant)))

    prec = None
    for m in ligne.mots:
        if prec is not None and m.x0 - prec.x1 > ecart:
            fermer()
            courant = []
        courant.append(m)
        prec = m
    fermer()
    return sortie


def _titres(page: PageText) -> _Titres:
    lignes: Sequence[Ligne] = page.lignes
    if not lignes:
        brut = [_norm(li) for li in page.texte.splitlines() if li.strip()]
        return _Titres(grandes=[], entete=brut[:12])
    a_geometrie = page.source in ("natif", "ocr") and any(li.y1 > 0 for li in lignes)
    if not a_geometrie:
        segs = []
        for li in lignes[:12]:
            segs.extend(re.split(r"\s{3,}| \| ", li.texte))
        return _Titres(grandes=[], entete=[_norm(x) for x in segs if x.strip()])
    haut = [li for li in lignes if li.y0 <= 0.30]
    if len(haut) < 3:
        haut = list(lignes[:8])
    tailles = sorted(m.taille for li in lignes for m in li.mots if m.taille)
    mediane = tailles[len(tailles) // 2] if tailles else None
    entete: list[str] = []
    grandes: list[str] = []
    for li in haut:
        for texte, _taille, _y0 in _segments(li):
            entete.append(_norm(texte))
    lignes_haut = [_norm(li.texte) for li in haut]
    for li in lignes:
        if li.y0 > 0.5:
            continue
        for texte, taille, _y0 in _segments(li):
            if mediane and taille and taille >= 1.3 * mediane and len(texte.split()) <= 8:
                grandes.append(_norm(texte))
    return _Titres(grandes=grandes, entete=entete, lignes=lignes_haut)


def _compte(rx: re.Pattern[str], texte: str) -> int:
    """Nombre de motifs **distincts** trouvés."""
    return len({m.group(0).strip() for m in rx.finditer(texte)})


def _borne(x: float) -> float:
    return round(min(0.99, max(0.0, x)), 3)


def classer_page(
    page: PageText,
    *,
    numero_dans_fichier: int | None = None,
    corps_courriel: bool = False,
) -> ClassementPage:
    """Classe une page. ``numero_dans_fichier`` > 1 autorise le type ``continuation``."""
    numero = numero_dans_fichier or page.numero
    refs = extraire_refs(page.texte)
    langue = detecter_langue(page.texte)
    base = {"numero": numero, "refs": refs, "langue": langue}
    if corps_courriel:
        # Le corps d'un courriel est une donnée (§7.1) : il reste un courriel, sauf s'il **est** le récapitulatif
        # d'une déclaration acceptée (« bon à enlever », « clearance summary ») : MRN, intitulé ou vocabulaire de
        # déclaration et rubriques douanières. Rien de ce texte n'est exécuté : il est seulement classé (D-2101).
        c = classer_page(page, numero_dans_fichier=numero_dans_fichier)
        if (c.type is TypeDocument.declaration and refs.mrns and c.confiance >= 0.85
                and _compte(CORPS_DECLARATION, _norm(page.texte)) >= 4):
            c.sous_type = SousTypeDeclaration.preuve_dedouanement.value
            c.indices.append("courriel_recapitulatif_declaration")
            return c
        return ClassementPage(type=TypeDocument.document_support, sous_type=SousTypeSupport.courriel.value,
                              confiance=0.99, indices=["corps_courriel"], **base)
    texte = _norm(page.texte)
    nb_car = sum(1 for c in texte if not c.isspace())
    if page.qualite is QualiteTexte.illisible and nb_car < 40 and any(
            a.startswith(("ocr_indisponible", "ocr_desactive")) for a in page.avertissements):
        # §7.2 : image sans texte et OCR indisponible -> inconnu (indices du nom de fichier à l'extraction)
        return ClassementPage(type=TypeDocument.inconnu, confiance=0.3, indices=["ocr_indisponible"], **base)
    if page.qualite is QualiteTexte.illisible and nb_car < 40:
        return ClassementPage(type=TypeDocument.document_non_exploitable, confiance=0.75,
                              motif_non_exploitable=MotifNonExploitable.illisible, indices=["page_illisible"], **base)
    if nb_car < 15:
        if numero > 1:
            return ClassementPage(type=CONTINUATION, confiance=0.6, indices=["page_quasi_vide"], **base)
        return ClassementPage(type=TypeDocument.inconnu, confiance=0.2, indices=["page_quasi_vide"], **base)

    tt = _titres(page)
    entete = tt.texte_entete
    indices: list[str] = []

    n_facture, pos_facture = tt.rang(TITRE_FACTURE, exclure_suite=_SUITE_CITATION)
    n_avoir, pos_avoir = tt.rang(TITRE_AVOIR, exclure_suite=_SUITE_PHRASE)
    t_decl = _compte(TITRE_DECLARATION, tt.texte_lignes)
    c_decl = _compte(CORPS_DECLARATION, texte)
    n_mrn = len(refs.mrns)
    f_ft = _compte(FORTS_TRANSITAIRE, texte)
    c_ft = _compte(CORPS_TRANSITAIRE, texte)
    c_fc = _compte(CORPS_FACTURE_COMMERCIALE, texte)
    negatif = bool(_TOTAL_NEGATIF.search(texte)) and not _A_PAYER_POSITIF.search(texte)
    lettre = _compte(LETTRE, texte)
    cg = _compte(CG_CORPS, texte)

    support, n_support, pos_support = None, 0, 10**6
    for st, rx in SUPPORT_TITRES:
        n, pos = tt.rang(rx, exclure_suite=_SUITE_CHAMP)
        if n > n_support:
            support, n_support, pos_support = st, n, pos
    motif_p2, n_p2 = None, 0
    for motif, rx in NON_EXPLOITABLE:
        n = tt.niveau(rx, exclure_suite=_SUITE_CHAMP)
        if n > n_p2:
            motif_p2, n_p2 = motif, n
    if motif_p2 in (MotifNonExploitable.liste_reparation, MotifNonExploitable.recu) and n_p2 < 2 \
            and not (n_facture or n_avoir):
        motif_p2, n_p2 = None, 0  # « réparation », « reçu » dans une ligne ordinaire : pas un intitulé
    n_titre_facture = max(n_facture, n_avoir)
    pos_titre_facture = min(p for n, p in ((n_facture, pos_facture), (n_avoir, pos_avoir)) if n == n_titre_facture)

    def res(type_, sous_type=None, conf=0.0, motif=None) -> ClassementPage:
        return ClassementPage(type=type_, sous_type=sous_type, confiance=_borne(conf), motif_non_exploitable=motif,
                              titre=tt.premiere(), indices=indices,
                              intitulee=bool(n_titre_facture or n_support or n_p2 or t_decl),
                              suite=bool((refs.page_n and refs.page_n > 1) or _SUITE.search(tt.texte_lignes)), **base)

    # 1. Déclaration : MRN + vocabulaire douanier, sans intitulé de facture (une facture de transitaire
    #    cite des MRN mais porte un intitulé de facture et des débours).
    score_decl = (0.45 if t_decl else 0.0) + (0.2 if n_mrn else 0.0) + min(0.5, 0.06 * c_decl)
    facture_probable = n_titre_facture and (f_ft or c_fc >= 3 or n_avoir or n_titre_facture == 2)
    decl_forte = c_decl >= 8 and not f_ft and c_fc < 3 and not n_avoir and (n_mrn or numero > 1)
    if decl_forte:
        # MRN (ou page de suite) et rubriques de déclaration en nombre, aucun débours : « facture » n'est qu'une
        # rubrique citée (« Invoice currency / total », « N380 Facture commerciale » lu en grand corps par l'OCR)
        facture_probable = False
    if score_decl >= 0.55 and not (facture_probable and not t_decl):
        indices.append("declaration")
        if TYPE_PREUVE.search(tt.texte_lignes):
            st = SousTypeDeclaration.preuve_dedouanement
        elif TYPE_H7.search(entete):
            st = SousTypeDeclaration.h7
        elif TYPE_DAU.search(entete) or _compte(TYPE_DAU, texte) >= 3 or (
                re.search(r"\bcase \d+|\bbox \d+", texte) and c_decl >= 3):
            st = SousTypeDeclaration.dau_cases
        else:
            st = SousTypeDeclaration.h1
        if motif_p2 is MotifNonExploitable.document_export:
            indices.append("export")
            return res(TypeDocument.document_non_exploitable, None, 0.85, motif_p2)
        return res(TypeDocument.declaration, st.value, 0.5 + score_decl * 0.5)
    if decl_forte and numero > 1 and not t_decl:
        indices.append("continuation_declaration")  # page de suite d'une déclaration (MRN illisible)
        return res(CONTINUATION, None, 0.75)

    if n_titre_facture and n_p2 < n_titre_facture and P2_CORPS.search(texte):
        # Mention explicite « ce document n'est pas la facture » : elle l'emporte sur l'intitulé « facture »
        # (ex. « FACTURE - BON DE LIVRAISON » + « document sans valeur commerciale »), motif déjà lu conservé.
        if motif_p2 is None:
            motif_p2 = MotifNonExploitable.liste_expedition
            for motif, rx in NON_EXPLOITABLE:  # le motif nommé dans le texte l'emporte
                if rx.search(texte):
                    motif_p2 = motif
                    break
        n_p2 = n_titre_facture
    # 2. Non exploitables (P2) : intitulé de devis, bon de commande, pré-alerte… (l'emporte sur « facture »
    #    à niveau d'intitulé égal ou supérieur).
    if motif_p2 is not None and n_p2 >= n_titre_facture and n_p2 >= n_support:
        if motif_p2 is MotifNonExploitable.pre_alerte and not n_titre_facture:
            indices.append("pre_alerte_support")
            return res(TypeDocument.document_support, SousTypeSupport.pre_alerte.value, 0.85)
        indices.append(f"p2_{motif_p2.value}")
        return res(TypeDocument.document_non_exploitable, None, 0.88 if n_titre_facture else 0.82, motif_p2)

    # 3. Support titré en grand corps alors que « facture » n'apparaît que dans une ligne d'en-tête
    #    (ex. liste de colisage citant « Invoice ref ») : document support. À niveau égal, l'intitulé le plus haut
    #    sur la page l'emporte (« BILL OF LADING » en tête, « Invoice IHM… » cité plus bas).
    if support is not None and (n_support > n_titre_facture or (
            n_support == n_titre_facture and pos_support < pos_titre_facture and not f_ft)):
        indices.append(f"support_{support.value}")
        return res(TypeDocument.document_support, support.value, 0.86)

    # 4. Lettre d'accompagnement (formules de politesse) sans intitulé de facture en grand corps.
    if (lettre >= 2 and n_titre_facture < 2 and (n_titre_facture == 0 or lettre >= 3)) or (
            lettre >= 3 and not (n_titre_facture == 2 and c_fc >= 3)):
        indices.append("lettre_accompagnement")
        return res(TypeDocument.document_support, SousTypeSupport.lettre_accompagnement.value,
                   0.72 + 0.04 * min(5, lettre))

    # 5. Avoir : intitulé, ou intitulé de facture avec total négatif.
    if n_avoir or (n_facture and negatif):
        indices.append("avoir_intitule" if n_avoir else "avoir_total_negatif")
        return res(TypeDocument.avoir, None, 0.9 if n_avoir else 0.8)

    # 6. Factures : commerciale ou transitaire (un nom de transporteur ne compte pas, seuls les libellés
    #    de débours et de prestations de dédouanement font une facture de transitaire).
    if n_facture:
        st_fc = SousTypeFactureCommerciale.facture
        if PRO_FORMA.search(entete):
            st_fc = SousTypeFactureCommerciale.pro_forma
        elif VALEUR_DOUANE.search(texte):
            st_fc = SousTypeFactureCommerciale.valeur_douane_seulement
        elif SANS_VALEUR.search(texte):
            st_fc = SousTypeFactureCommerciale.sans_valeur_commerciale
        transitaire = (f_ft >= 1 and (f_ft * 2 + c_ft) >= c_fc * 0.5) or (c_ft >= 4 and c_ft > c_fc + 1)
        # Le sous-type « sans valeur / valeur douane » vient de mentions de corps (« free of charge ») : il ne
        # retient pas en facture commerciale une page de débours et de prestations (seul « pro forma » le fait).
        if transitaire and st_fc is not SousTypeFactureCommerciale.pro_forma:
            indices.append("facture_transitaire")
            conf = 0.82 + 0.03 * min(5, f_ft + c_ft // 2) - (0.1 if c_fc > c_ft + f_ft else 0)
            return res(TypeDocument.facture_transitaire, None, conf)
        indices.append("facture_commerciale")
        conf = (0.85 if n_facture == 2 else 0.78) + 0.025 * min(6, c_fc) - (0.1 if f_ft else 0.0)
        return res(TypeDocument.facture_commerciale, st_fc.value, conf)

    # 7. Documents support.
    if support is SousTypeSupport.conditions_generales or (cg >= 4 and lettre <= 2):
        indices.append("conditions_generales")
        return res(TypeDocument.document_support, SousTypeSupport.conditions_generales.value,
                   0.88 if support else 0.75)
    if support is not None:
        indices.append(f"support_{support.value}")
        return res(TypeDocument.document_support, support.value, 0.86 if n_support == 2 else 0.8)
    if lettre >= 2:
        indices.append("lettre_accompagnement")
        return res(TypeDocument.document_support, SousTypeSupport.lettre_accompagnement.value,
                   0.72 + 0.04 * min(5, lettre))

    if _compte(CORPS_TRANSPORT, texte) >= 4 and c_fc < 4:
        indices.append("support_titre_transport_corps")
        return res(TypeDocument.document_support, SousTypeSupport.titre_transport.value, 0.74)

    # 8. Sans intitulé : continuation (page > 1, ou « page n/m » avec n > 1, ou « suite »).
    if (refs.page_n and refs.page_n > 1) or (numero > 1 and (_SUITE.search(texte) or score_decl < 0.3
                                                              or not tt.grandes)):
        indices.append("continuation")
        conf = 0.85 if (refs.page_n and refs.page_n > 1) or _SUITE.search(texte) else 0.72
        return res(CONTINUATION, None, conf)

    # 9. Indices de corps seulement : faible confiance (-> inconnu si < 0,70).
    candidats = [
        (score_decl, TypeDocument.declaration, SousTypeDeclaration.h1.value),
        (0.12 * (f_ft * 2 + c_ft), TypeDocument.facture_transitaire, None),
        (0.08 * c_fc, TypeDocument.facture_commerciale, SousTypeFactureCommerciale.facture.value),
    ]
    candidats.sort(key=lambda c: -c[0])
    s, t, st = candidats[0]
    indices.append("indices_corps")
    return res(t if s > 0 else TypeDocument.inconnu, st if s > 0 else None, min(0.65, 0.3 + s * 0.5))
