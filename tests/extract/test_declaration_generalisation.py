"""Déclarations imprimées sous des présentations **inconnues** (D-1801 à D-1806).

PDF rendus ici par reportlab (H1 sur deux pages avec page de suite, édition « paysage » en tableaux, certificat
anglais de commissionnaire en couples libellé / valeur) et courriel en texte seul. Données **fictives** ;
mises en page propres à ces tests (ni celles du banc ni celles de la démonstration).
"""

from __future__ import annotations

import io
from email.message import EmailMessage

from reportlab.lib.pagesizes import A4, landscape
from reportlab.pdfgen import canvas

from controldone.extract.base import ExtractionContext
from controldone.extract.deterministe._declaration_generique import (
    ancre_article,
    date_en_lettres,
    date_prose_acceptation,
    ligne_taxe_prose,
    segments_libelles,
)
from controldone.extract.deterministe.declaration import ExtracteurDeclaration
from controldone.ids import IdGenerator
from controldone.ingest.pages import OptionsPages, extraire_pages
from controldone.model import Document, PageRef
from controldone.model.champs import ChampsDeclaration
from controldone.model.enums import CategorieTaxe, PaiementNormalise, TauxChangeSens, TauxNature, TypeDocument
from controldone.normalize import tva_fr_depuis_siren

TVA_IMP = tva_fr_depuis_siren("000424242")
TVA_DEC = tva_fr_depuis_siren("000515151")
MRN = "26FRQ7ZK3M5T8W2N4B"


def _pdf(pages: list[list[tuple]], taille_page=A4) -> bytes:
    """Éléments ``(x, y, texte[, taille[, "d"]])`` en fractions de page (origine en haut à gauche)."""
    larg, haut = taille_page
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=taille_page, invariant=1)
    for elements in pages:
        c.setFont("Helvetica", 6)
        c.drawCentredString(0.5 * larg, 0.985 * haut, "DONNÉES FICTIVES — DOCUMENT DE TEST")
        for el in elements:
            x, y, texte = el[:3]
            c.setFont("Helvetica", el[3] if len(el) > 3 else 8)
            if len(el) > 4 and el[4] == "d":
                c.drawRightString(x * larg, (1 - y) * haut, texte)
            else:
                c.drawString(x * larg, (1 - y) * haut, texte)
        c.showPage()
    c.save()
    return buf.getvalue()


def _extraire(contenu: bytes, mime: str = "application/pdf") -> ChampsDeclaration:
    extraites = extraire_pages(contenu, type_mime=mime, options=OptionsPages(ocr=False, isoler=False))
    pages = [pe.page for pe in extraites]
    doc = Document(type=TypeDocument.declaration,
                   pages=[PageRef(fichier_id=p.fichier_id, numero=p.numero, qualite_texte=p.qualite_texte)
                          for p in pages])
    ctx = ExtractionContext(ids=IdGenerator.deterministe(5),
                            options={"textes_pages": {pe.page.numero: pe.texte for pe in extraites}})
    ex = ExtracteurDeclaration()
    assert ex.supports(doc, pages)
    res = ex.extract(doc, pages, ctx)
    assert isinstance(res.champs, ChampsDeclaration)
    return res.champs


def _refs(c: ChampsDeclaration) -> list[tuple[str, str]]:
    return sorted((d.type_code.valeur, d.reference.valeur) for d in c.documents_references)


def _taxes(c: ChampsDeclaration) -> list[tuple]:
    return [(t.article.valeur if t.article else None, t.type_taxe.valeur if t.type_taxe else None,
             t.montant.valeur if t.montant else None) for t in c.taxations]


# --- H1 sur deux pages : articles continués en page 2 ------------------------------------------------------


def _ligne_taxe(y: float, code: str, lib: str, base: str, taux: str, montant: str, a_payer: str, mp: str):
    return [(0.08, y, code), (0.15, y, lib), (0.58, y, base, 8, "d"), (0.68, y, taux, 8, "d"),
            (0.80, y, montant, 8, "d"), (0.90, y, a_payer, 8, "d"), (0.93, y, mp)]


def _entete_taxes(y: float):
    return [(0.08, y, "Type"), (0.15, y, "Libellé"), (0.58, y, "Base (EUR)", 8, "d"), (0.68, y, "Taux", 8, "d"),
            (0.80, y, "Montant", 8, "d"), (0.90, y, "À payer", 8, "d"), (0.93, y, "MP")]


def _article_bloc(y: float, n: int, code: str, des: str, mt: str, taxes: list[tuple]) -> list[tuple]:
    el = [(0.08, y, f"Article {n}", 9), (0.22, y, f"Code marchandise {code}"), (0.70, y, "Origine CN  Préf. 100"),
          (0.08, y + 0.02, des),
          (0.08, y + 0.04, f"Montant facturé : {mt} EUR   Masse nette : 10,000 kg   Masse brute : 11,500 kg"),
          *_entete_taxes(y + 0.07)]
    for k, t in enumerate(taxes):
        el += _ligne_taxe(y + 0.09 + 0.018 * k, *t)
    return el


def _h1_deux_pages() -> bytes:
    p1 = [(0.06, 0.04, "DÉCLARATION EN DOUANE — IMPORTATION", 13), (0.95, 0.04, f"MRN {MRN}", 10, "d"),
          (0.95, 0.06, "LRN LRN-TEST-0042 — version 2", 8, "d"), (0.95, 0.075, "Acceptée le 03/03/2026", 8, "d"),
          (0.07, 0.11, "Importateur", 7), (0.07, 0.125, "Atelier Fictif SARL"), (0.07, 0.14, f"TVA {TVA_IMP}"),
          (0.52, 0.11, "Déclarant / représentant", 7), (0.52, 0.125, "Transit Imaginaire SAS"),
          (0.52, 0.14, f"TVA {TVA_DEC}"),
          (0.07, 0.17, "Conditions de livraison", 7), (0.07, 0.185, "FOB Ningbo"),
          (0.52, 0.17, "Montant total facturé", 7), (0.52, 0.185, "12 600,00 EUR"),
          (0.07, 0.21, "Masse brute totale / colis", 7), (0.07, 0.225, "23,000 kg"), (0.07, 0.24, "63 colis"),
          (0.52, 0.21, "Nombre d'articles", 7), (0.52, 0.225, "2"),
          *_article_bloc(0.29, 1, "8467210000", "Perceuse fictive",  "12 000,00",
                         [("A00", "Droits de douane", "12 000,00", "2,7 %", "324,00", "324,00", "E"),
                          ("B00", "TVA import", "12 324,00", "20,0 %", "2 464,80", "0,00", "G")])]
    p2 = [(0.06, 0.04, f"Suite — déclaration MRN {MRN}", 9), (0.95, 0.04, "page 2/2", 8, "d"),
          *_article_bloc(0.08, 2, "7318158290", "Boulons fictifs", "600,00",
                         [("A00", "Droits de douane", "600,00", "3,7 %", "22,20", "22,20", "E"),
                          ("B00", "TVA import", "622,20", "20,0 %", "124,44", "124,44", "E")]),
          (0.06, 0.26, "Impositions au niveau de la déclaration", 9), *_entete_taxes(0.28),
          *_ligne_taxe(0.30, "FPE", "Droit forfaitaire petits envois", "2 articles", "3,00 EUR/article", "6,00",
                       "6,00", "A"),
          (0.06, 0.34, "Documents produits / références", 9),
          (0.07, 0.36, "Code"), (0.15, 0.36, "Nature"), (0.45, 0.36, "Référence"),
          (0.07, 0.38, "N380"), (0.15, 0.38, "Facture commerciale"), (0.45, 0.38, "FT 4800/2026"),
          (0.07, 0.40, "N740"), (0.15, 0.40, "LTA"), (0.45, 0.40, "999-12345675"),
          (0.07, 0.42, "1008"), (0.15, 0.42, "Autoliquidation TVA — n° TVA"), (0.45, 0.42, TVA_IMP),
          (0.06, 0.46, "MP (mode de paiement) : A = comptant ; E = paiement différé ; G = TVA autoliquidée", 7)]
    return _pdf([p1, p2])


def test_h1_deux_pages_colonne_a_payer_et_page_de_suite():
    c = _extraire(_h1_deux_pages())
    assert c.mrn.valeur == MRN and c.version.valeur == "2"
    assert c.importateur.tva.valeur == TVA_IMP and c.montant_total_facture.valeur == "12600.00"
    assert c.nombre_colis_total.valeur == "63" and c.masse_brute_totale.valeur == "23.000"
    assert [a.numero_article.valeur for a in c.articles] == ["1", "2"]
    # « À payer » est une colonne à part : le montant de la TVA autoliquidée n'est pas son « 0,00 », et un
    # montant à milliers « 2 464,80 » n'est pas coupé par le montant à payer voisin
    tva1 = next(t for t in c.taxations if t.article and t.article.valeur == "1" and t.type_taxe.valeur == "B00")
    assert tva1.montant.valeur == "2464.80" and tva1.montant_a_payer.valeur == "0.00"
    assert tva1.paiement_normalise is PaiementNormalise.autoliquide
    # taxation de niveau déclaration après le dernier article : pas rattachée à l'article 2
    fpe = next(t for t in c.taxations if t.type_taxe.valeur == "FPE")
    assert fpe.article is None and fpe.categorie is CategorieTaxe.forfait_petits_envois
    assert len(c.taxations) == 5
    # colonne « nature » entre le code et la référence ; préfixe « FT » de la référence ; code 1008
    assert _refs(c) == [("1008", TVA_IMP), ("N380", "FT 4800/2026"), ("N740", "999-12345675")]
    assert c.indices_autoliquidation


# --- édition « paysage » en tableaux --------------------------------------------------------------------------


def _paysage() -> bytes:
    el = [(0.04, 0.05, "LOGICIEL FICTIF — EDITION DE LA DECLARATION ACCEPTEE", 10),
          (0.04, 0.08, f"MRN: {MRN}   LRN: LRN-TEST-0077   Version: 1   Date d'acceptation: 12/05/2026"),
          (0.04, 0.10, f"Importateur: Atelier Fictif SARL   TVA: {TVA_IMP}   EORI: FR00042424200000"),
          (0.04, 0.12, f"Déclarant: Transit Imaginaire SAS   TVA: {TVA_DEC}"),
          (0.04, 0.14, "Incoterm: EXW Felixstowe   Monnaie de facturation: EUR   Montant total facturé: 300,00   "
                       "Taux: 1 EUR = 0,85000 GBP"),
          (0.04, 0.16, "Masse brute totale: 30,000 kg   Colis: 4   Nombre d'articles: 2"),
          (0.04, 0.18, f"Documents: N380 INV-77 | N705 BL-778899 | 1008 {TVA_IMP}")]
    cols = [(0.05, "Art"), (0.08, "Code NC"), (0.20, "Désignation"), (0.42, "Or."), (0.46, "Pf"),
            (0.50, "Rég."), (0.60, "Mt facturé"), (0.68, "Val. stat."), (0.76, "Net kg"), (0.83, "Brut kg"),
            (0.90, "Qté sup."), (0.95, "Colis")]
    el += [(x, 0.23, t) for x, t in cols]
    lignes = [("1", "8467210000", "Perceuse fictive", "GB", "100", "4000", "200,00", "210,00", "18,000", "20,000",
               "4 p/st", "3"),
              ("2", "8203200000", "Pince fictive", "GB", "100", "4000", "100,00", "105,00", "9,000", "10,000",
               "10 p/st", "1")]
    for k, ligne in enumerate(lignes):
        y = 0.25 + 0.02 * k
        el += [(x, y, t) for (x, _), t in zip(cols, ligne, strict=True)]
    tcols = [(0.05, "Art"), (0.09, "Type"), (0.20, "Base"), (0.28, "Taux"), (0.36, "Montant"), (0.44, "A payer"),
             (0.50, "MP")]
    el += [(0.04, 0.31, "LIQUIDATION")] + [(x, 0.33, t) for x, t in tcols]
    taxes = [("1", "A00", "210,00", "2,7 %", "5,67", "5,67", "E"), ("1", "B00", "215,67", "20,0 %", "43,13", "0,00", "G"),
             ("2", "A00", "105,00", "3,7 %", "3,89", "3,89", "E"), ("2", "B00", "108,89", "20,0 %", "21,78", "0,00", "G")]
    for k, ligne in enumerate(taxes):
        y = 0.35 + 0.02 * k
        el += [(x, y, t) for (x, _), t in zip(tcols, ligne, strict=True)]
    el += [(0.04, 0.45, "Total A00: 9,56   Total B00: 64,91"),
           (0.04, 0.47, "TOTAL DROITS ET TAXES: 74,47 EUR   TOTAL A PAYER: 9,56 EUR"),
           (0.04, 0.49, "MP: A=comptant E=différé G=autoliquidation")]
    return _pdf([el], landscape(A4))


def test_edition_paysage_en_tableaux():
    c = _extraire(_paysage())
    assert c.importateur.tva.valeur == TVA_IMP and c.declarant.tva.valeur == TVA_DEC  # sur la ligne du libellé
    assert c.taux_change.valeur == "0.85000" and c.taux_change_sens.valeur == TauxChangeSens.devise_par_eur.value
    a1, a2 = c.articles
    assert (a1.masse_nette.valeur, a1.masse_brute.valeur, a1.valeur_statistique.valeur) == ("18.000", "20.000",
                                                                                           "210.00")
    assert a1.nombre_colis.valeur == "3" and a1.quantite_unite_supplementaire.valeur == "4"
    assert a1.montant_facture_article.valeur == "200.00"  # pas la préférence « 100 »
    assert a2.code_preference.valeur == "100" and a2.regime.valeur == "4000"
    # colonne « Art » du tableau de liquidation : rattachement ; « Total A00: … » n'est pas une taxation
    assert _taxes(c) == [("1", "A00", "5.67"), ("1", "B00", "43.13"), ("2", "A00", "3.89"), ("2", "B00", "21.78")]
    assert c.total_a_payer.valeur == "9.56"


# --- certificat anglais d'un commissionnaire : couples libellé / valeur ------------------------------------


def _certificat() -> bytes:
    paires = [("MRN", MRN), ("Local reference", "LRN-TEST-0099"), ("Acceptance date", "2026-03-11"),
              ("Importer", f"Atelier Fictif SARL — VAT {TVA_IMP} — EORI FR00042424200000"),
              ("Delivery terms", "CFR Le Havre"), ("Country of dispatch", "CH"),
              ("Invoice currency / total", "CHF 5,154.72"), ("Exchange rate applied", "EUR 1 = CHF 0.91106"),
              ("Gross mass / packages", "3,037.727 kg / 60 packages"), ("Number of items", "2"),
              ("Supporting documents", "N380 RE-2026-0001; N730 CMR-FX-554972")]
    el = [(0.30, 0.06, "CERTIFICATE OF CUSTOMS CLEARANCE", 14),
          (0.07, 0.10, "We hereby certify that the goods described below were released on 11 Mar 2026.")]
    for k, (lib, val) in enumerate(paires):
        el += [(0.07, 0.14 + 0.018 * k, lib), (0.30, 0.14 + 0.018 * k, val)]
    cols = [(0.08, "Item"), (0.13, "Commodity code"), (0.30, "Description"), (0.60, "Origin"),
            (0.75, "Net kg", 8, "d"), (0.85, "Gross kg", 8, "d"), (0.95, "Value CHF", 8, "d")]
    el += [(x, 0.37, t, *r) for x, t, *r in cols]
    for k, (n, code, des, o, net, brut, val) in enumerate([
            ("1", "7318158290", "Boulons fictifs", "CH", "2,500.000", "2,895.000", "4,861.00"),
            ("2", "8203200000", "Pince fictive", "CH", "70.000", "142.727", "293.72")]):
        y = 0.39 + 0.018 * k
        el += [(0.08, y, n), (0.13, y, code), (0.30, y, des), (0.60, y, o), (0.75, y, net, 8, "d"),
               (0.85, y, brut, 8, "d"), (0.95, y, val, 8, "d")]
    el += [(0.07, 0.45, "Duties and taxes", 10), (0.08, 0.47, "Item"), (0.13, 0.47, "Tax"),
           (0.55, 0.47, "Basis", 8, "d"), (0.68, 0.47, "Rate", 8, "d"), (0.80, 0.47, "Amount EUR", 8, "d"),
           (0.82, 0.47, "Payment")]
    for k, (n, code, lib, base, taux, mt) in enumerate([
            ("1", "A00", "Customs duty", "EUR 5,335.62", "3.7%", "197.42"),
            ("1", "B00", "Import VAT", "EUR 5,533.04", "20.0%", "1,106.61")]):
        y = 0.49 + 0.018 * k
        el += [(0.08, y, n), (0.13, y, f"{code} {lib}"), (0.55, y, base, 8, "d"), (0.68, y, taux, 8, "d"),
               (0.80, y, mt, 8, "d"), (0.82, y, "cash")]
    el += [(0.62, 0.54, "Total duties and taxes"), (0.95, 0.54, "EUR 1,304.03", 8, "d")]
    return _pdf([el])


def test_certificat_anglais_libelle_valeur():
    c = _extraire(_certificat())
    assert c.lrn.valeur == "LRN-TEST-0099" and c.importateur.tva.valeur == TVA_IMP
    assert (c.devise_facture.valeur, c.montant_total_facture.valeur) == ("CHF", "5154.72")
    assert c.taux_change.valeur == "0.91106" and c.taux_change_sens.valeur == TauxChangeSens.devise_par_eur.value
    # masse et colis sous un même libellé ; le nombre d'une référence (« CMR-FX-554972 ») n'est pas un colis
    assert c.masse_brute_totale.valeur == "3037.727" and c.nombre_colis_total.valeur == "60"
    # en-tête « Item | Commodity code | … » : tableau, pas un bloc « Item 1 »
    assert [a.code_marchandise.valeur for a in c.articles] == ["7318158290", "8203200000"]
    assert c.articles[1].masse_brute.valeur == "142.727"
    assert _taxes(c) == [("1", "A00", "197.42"), ("1", "B00", "1106.61")]
    assert c.taxations[0].categorie is CategorieTaxe.droit and c.taxations[1].categorie is CategorieTaxe.tva
    assert c.taxations[0].paiement_normalise is PaiementNormalise.comptant


# --- courriel en texte seul ---------------------------------------------------------------------------------


def _courriel() -> bytes:
    corps = "\n".join([
        "Bonjour,", "",
        "Votre déclaration d'importation a été acceptée par la douane le 18 août 2026.", "",
        f"  MRN ..................... {MRN}",
        "  LRN ..................... LRN-TEST-0123 (version 1)",
        "  Importateur ............. Atelier Fictif SARL",
        f"  N° TVA importateur ...... {TVA_IMP}",
        f"  Déclarant ............... Transit Imaginaire SAS (TVA {TVA_DEC})",
        "  Incoterm ................ FCA Izmir",
        "  Montant facturé ......... 2 345,43 EUR",
        "  Taux de change .......... 1 USD = 0,85130 EUR",
        "  Masse brute totale ...... 40,600 kg",
        "  Nombre de colis ......... 2",
        "  Documents cités ......... N380 FAC-0001 ; N730 CMR-0002", "",
        "ARTICLES",
        "  [1] 8467210000 Perceuse fictive",
        "      origine TR | montant facturé 2 000,00 EUR | net 17,400 kg | brut 20,500 kg | colis 1",
        "      A00 Droits de douane : base 2 000,00 EUR x 2,7 % = 54,00 EUR (payé comptant)",
        "      B00 TVA import : base 2 054,00 EUR x 20,0 % = 410,80 EUR (autoliquidée)",
        "  [2] 8302410000 Charnières fictives",
        "      origine TR | montant facturé 345,43 EUR | net 18,000 kg | brut 20,100 kg | colis 1",
        "      A00 Droits de douane : base 345,43 EUR x 2,7 % = 9,33 EUR (paiement différé)", "",
        "IMPOSITIONS GLOBALES",
        "  FPE Droit forfaitaire petits envois : 2 articles x 3,00 EUR = 6,00 EUR (paiement différé)", "",
        "Total droits et taxes : 480,13 EUR",
        "Total à payer : 69,33 EUR", "",
        "Cordialement,", "-- ", "DONNÉES FICTIVES — message de test."])
    m = EmailMessage()
    m["From"] = "Service fictif <declarations@exemple-fictif.invalid>"
    m["To"] = "import@client-fictif.invalid"
    m["Subject"] = f"Bon à enlever - MRN {MRN}"
    m.set_content(corps, cte="8bit")
    return m.as_bytes()


def test_courriel_recapitulatif_texte():
    c = _extraire(_courriel(), "message/rfc822")
    assert c.mrn.valeur == MRN and c.version.valeur == "1"
    assert c.date_acceptation.valeur == "2026-08-18"  # date dans la phrase d'acceptation
    assert c.date_acceptation.confiance < 0.97
    assert c.importateur.tva.valeur == TVA_IMP and c.declarant.tva.valeur == TVA_DEC
    assert c.declarant.nom.valeur == "Transit Imaginaire SAS"
    assert (c.montant_total_facture.valeur, c.devise_facture.valeur) == ("2345.43", "EUR")
    assert c.taux_change_sens.valeur == TauxChangeSens.eur_par_devise.value
    a1, a2 = c.articles
    assert (a1.numero_article.valeur, a1.code_marchandise.valeur, a1.pays_origine.valeur) == ("1", "8467210000", "TR")
    assert (a1.masse_nette.valeur, a1.masse_brute.valeur, a1.nombre_colis.valeur) == ("17.400", "20.500", "1")
    assert a2.montant_facture_article.valeur == "345.43"
    assert _taxes(c) == [("1", "A00", "54.00"), ("1", "B00", "410.80"), ("2", "A00", "9.33"), (None, "FPE", "6.00")]
    b00 = c.taxations[1]
    assert b00.base_montant.valeur == "2054.00" and b00.base_quantite is None  # « EUR » n'est pas une unité
    assert b00.paiement_normalise is PaiementNormalise.autoliquide and c.indices_autoliquidation
    assert c.taxations[0].paiement_normalise is PaiementNormalise.comptant
    fpe = c.taxations[3]
    assert fpe.base_quantite.valeur == "2" and fpe.taux.valeur == "3.00" and fpe.taux_nature is TauxNature.specifique
    assert c.total_a_payer.valeur == "69.33"


# --- aides génériques ---------------------------------------------------------------------------------------


class _T:
    def __init__(self, t: str):
        self.t = t


def _toks(s: str) -> list[_T]:
    return [_T(x) for x in s.split()]


def test_dates_en_lettres_multilingues():
    assert date_en_lettres("le 1er juillet 2026")[2] == "2026-07-01"
    assert date_en_lettres("on March 11, 2026")[2] == "2026-03-11"
    assert date_en_lettres("am 7. September 2026")[2] == "2026-09-07"
    assert date_en_lettres("el 3 de mayo de 2026")[2] == "2026-05-03"
    assert date_en_lettres("il 3 marzo 2026")[2] == "2026-03-03"
    assert date_en_lettres("le 31 février 2026") is None
    for phrase, attendu in [("Die Anmeldung wurde am 7. September 2026 angenommen.", "7. September 2026"),
                            ("Goods released by customs on 11 Mar 2026 under MRN", "11 Mar 2026"),
                            ("Dichiarazione accettata il 03/03/2026.", "03/03/2026")]:
        a, b = date_prose_acceptation(phrase)
        assert phrase[a:b] == attendu
    assert date_prose_acceptation("Edité le 26/07/2026") is None  # pas de mot d'acceptation


def test_ancres_segments_et_taxe_en_prose():
    assert ancre_article(_toks("[3] 8467 21 00 00 Perceuse")) == (0, 1, 5)
    assert ancre_article(_toks("Item 2 8203200000 Pliers")) == (1, 2, 3)
    assert ancre_article(_toks("(5 8471300000 Ordinateur")) is None  # parenthèse non refermée (débris d'OCR)
    assert ancre_article(_toks("12 8471300000")) is None  # numéro nu : pas une liste d'articles
    segs = segments_libelles(_toks("Ursprung CN | Rechnungsbetrag 12,00 EUR | Eigenmasse 1,5 kg | colli 2"))
    assert [s[0] for s in segs] == ["pays_origine", "montant_facture_article", "masse_nette", "nombre_colis"]
    p = ligne_taxe_prose(_toks("A00 Customs duty : basis 100.00 EUR x 2.7 % = 2.70 EUR (deferred)"))
    assert set(p) == {"code", "libelle", "base", "taux", "montant", "mp"}
    assert ligne_taxe_prose(_toks("A00 Droits de douane 1 079,49")) is None  # récapitulatif : pas de calcul
