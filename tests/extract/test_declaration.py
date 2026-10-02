"""Extracteur déterministe des déclarations imprimées (SPEC §5.3.2, §6.3, §8.7).

Les PDF sont rendus ici par reportlab (données **fictives**, mises en page volontairement différentes de
celles du banc) ; les lectures OCR sont simulées par des ``PageText`` construits à la main (mots, boîtes,
confiances), sans dépendre de Tesseract ni de ``bench/corpus``.
"""

from __future__ import annotations

import io
from decimal import Decimal

import pytest
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

from controldone.extract.base import Extracteur, ExtractionContext
from controldone.extract.deterministe import EXTRACTEURS_DETERMINISTES
from controldone.extract.deterministe.declaration import (
    CONF_CONFIRMEE,
    PLAFOND_OCR_SEUL,
    ExtracteurDeclaration,
)
from controldone.ids import IdGenerator
from controldone.ingest.pages import OptionsPages, extraire_pages
from controldone.ingest.texte import Mot, PageText, construire_lignes
from controldone.model.champs import ChampsDeclaration
from controldone.model.documents import Document, Page, PageRef
from controldone.model.enums import (
    CategorieTaxe,
    Methode,
    PaiementNormalise,
    QualiteTexte,
    SigneImprime,
    TauxNature,
    TypeDocument,
    TypeIndiceAutoliquidation,
)
from controldone.normalize.fiscal import tva_fr_depuis_siren
from controldone.taux_reference import TableTauxReference

TVA_IMP = tva_fr_depuis_siren("000714980")
TVA_DECL = tva_fr_depuis_siren("000616383")
MRN = "26FRK7G7KR9KVHGNG3"
L, H = A4


# --- fabriques -----------------------------------------------------------------------------------------------


def _pdf(pages: list[list[tuple]]) -> bytes:
    """Pages d'éléments ``(x, y, texte[, taille[, alignement]])`` en fractions de page (origine en haut à
    gauche) ; ``("rect", x0, y0, x1, y1)`` trace un cadre."""
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4, invariant=1)
    for elements in pages:
        for el in elements:
            if el[0] == "rect":
                _, x0, y0, x1, y1 = el
                c.rect(x0 * L, (1 - y1) * H, (x1 - x0) * L, (y1 - y0) * H)
                continue
            x, y, texte = el[:3]
            taille = el[3] if len(el) > 3 else 8
            c.setFont("Helvetica", taille)
            if len(el) > 4 and el[4] == "d":
                c.drawRightString(x * L, (1 - y) * H, texte)
            else:
                c.drawString(x * L, (1 - y) * H, texte)
        c.drawString(0.35 * L, 0.03 * H, "DONNÉES FICTIVES — DOCUMENT DE TEST")
        c.showPage()
    c.save()
    return buf.getvalue()


def _extraire_pdf(contenu: bytes, **options) -> ChampsDeclaration:
    extraites = extraire_pages(contenu, options=OptionsPages(ocr=False, isoler=False))
    return _extraire([pe.texte for pe in extraites], pages=[pe.page for pe in extraites], **options)


def _extraire(textes: list[PageText], pages: list[Page] | None = None, **options) -> ChampsDeclaration:
    if pages is None:
        pages = [Page(fichier_id="fic_test", numero=t.numero, qualite_texte=t.qualite, texte=t.texte)
                 for t in textes]
    doc = Document(type=TypeDocument.declaration,
                   pages=[PageRef(fichier_id=p.fichier_id, numero=p.numero, qualite_texte=p.qualite_texte)
                          for p in pages])
    ctx = ExtractionContext(ids=IdGenerator.deterministe(3),
                            options={"textes_pages": {t.numero: t for t in textes}, **options})
    ex = ExtracteurDeclaration()
    assert ex.supports(doc, pages)
    res = ex.extract(doc, pages, ctx)
    assert res.champs is not None
    assert isinstance(res.champs, ChampsDeclaration)
    return res.champs


def _page_ocr(lignes: list[list[tuple]], *, numero: int = 1, score: float = 0.93) -> PageText:
    """``PageText`` OCR simulé : lignes de mots ``(texte, x0, x1[, confiance])`` à hauteur régulière."""
    mots = []
    for k, ligne in enumerate(lignes):
        y0 = 0.05 + 0.02 * k
        for m in ligne:
            texte, x0, x1 = m[:3]
            conf = m[3] if len(m) > 3 else 0.96
            mots.append(Mot(texte, x0, y0, x1, y0 + 0.009, conf))
    lignes_txt = construire_lignes(mots)
    return PageText(numero=numero, texte="\n".join(li.texte for li in lignes_txt), lignes=lignes_txt,
                    qualite=QualiteTexte.ocr, source="ocr", score_ocr=score, largeur=595.0, hauteur=842.0)


def _mots(texte: str, x0: float, conf: float = 0.96, pas: float = 0.0105) -> list[tuple]:
    """Mots d'un texte posés à partir de ``x0`` (largeur proportionnelle au nombre de caractères)."""
    out, x = [], x0
    for m in texte.split():
        out.append((m, x, x + pas * len(m) * 0.6, conf))
        x += pas * (len(m) * 0.6 + 0.5)
    return out


# --- 1. impression par articles (fr) ------------------------------------------------------------------------


def _h1_par_articles() -> bytes:
    p1 = [
        (0.06, 0.05, "DÉCLARATION EN DOUANE - MISE EN LIBRE PRATIQUE", 11),
        (0.94, 0.05, f"MRN {MRN}", 9, "d"),
        (0.06, 0.09, "MRN"), (0.30, 0.09, MRN),
        (0.06, 0.105, "LRN (référence déclarant)"), (0.30, 0.105, "REF-LOC-77"),
        (0.06, 0.12, "Date d'acceptation"), (0.30, 0.12, "14/08/2026"),
        (0.06, 0.135, "Version"), (0.30, 0.135, "2"),
        (0.55, 0.09, "Importateur"),
        (0.55, 0.105, "Atelier Prisme SARL (FICTIF)"),
        (0.55, 0.12, f"N° TVA : {TVA_IMP}"),
        (0.55, 0.135, "EORI : FR00071498000000"),
        (0.55, 0.16, "Déclarant / représentant"),
        (0.55, 0.175, "Douane Démo Express (FICTIF)"),
        (0.55, 0.19, f"N° TVA : {TVA_DECL}"),
        (0.06, 0.22, "Pays d'expédition :"), (0.25, 0.22, "US"),
        (0.50, 0.22, "Conditions de livraison :"), (0.70, 0.22, "FCA Newark"),
        (0.06, 0.235, "Monnaie de facturation :"), (0.25, 0.235, "USD"),
        (0.50, 0.235, "Montant total facturé :"), (0.70, 0.235, "12 540,00 USD"),
        (0.06, 0.25, "Taux de change :"), (0.25, 0.25, "1 EUR = 1,12500 USD"),
        (0.50, 0.25, "Masse brute totale :"), (0.70, 0.25, "1 234,500 kg"),
        (0.06, 0.265, "Nombre total de colis :"), (0.25, 0.265, "12"),
        (0.50, 0.265, "Nombre d'articles :"), (0.70, 0.265, "2"),
        (0.06, 0.30, "Documents produits", 9),
        (0.06, 0.315, "N380"), (0.14, 0.315, "INV-2026-0042"), (0.40, 0.315, "Facture commerciale"),
        (0.06, 0.33, "N740"), (0.14, 0.33, "999-12345675"), (0.40, 0.33, "LTA"),
        (0.06, 0.345, "1008"), (0.14, 0.345, TVA_IMP), (0.40, 0.345, "Autoliquidation TVA"),
        # article 1
        (0.06, 0.39, "Article 1", 9), (0.20, 0.39, "Code marchandise"), (0.36, 0.39, "8471300000"),
        (0.52, 0.39, "Origine"), (0.60, 0.39, "CN"),
        (0.06, 0.405, "Désignation : ORDINATEUR PORTABLE"),
        (0.06, 0.42, "Montant facturé : 10 000,00 USD | Valeur statistique : 8 888,89 EUR | Masse nette : 900,000 kg"
         " | Masse brute : 1 000,500 kg"),
        (0.06, 0.435, "Unités supplémentaires : 40 p/st | Colis : 10"),
        (0.10, 0.455, "Type"), (0.18, 0.455, "Libellé"), (0.55, 0.455, "Base d'imposition", 8, "d"),
        (0.68, 0.455, "Quotité", 8, "d"), (0.82, 0.455, "Montant", 8, "d"), (0.87, 0.455, "MP"),
        (0.10, 0.47, "A00"), (0.18, 0.47, "Droits de douane"), (0.55, 0.47, "8 888,89", 8, "d"),
        (0.68, 0.47, "2,5 %", 8, "d"), (0.82, 0.47, "222,22", 8, "d"), (0.875, 0.47, "E"),
        (0.10, 0.485, "B00"), (0.18, 0.485, "TVA"), (0.55, 0.485, "9 111,11", 8, "d"),
        (0.68, 0.485, "20 %", 8, "d"), (0.82, 0.485, "1 822,22", 8, "d"), (0.875, 0.485, "G"),
        # article 2
        (0.06, 0.52, "Article 2", 9), (0.20, 0.52, "Code marchandise"), (0.36, 0.52, "2208401100"),
        (0.52, 0.52, "Origine"), (0.60, 0.52, "JM"),
        (0.06, 0.535, "Désignation : RHUM"),
        (0.06, 0.55, "Montant facturé : 2 540,00 USD | Valeur statistique : 2 257,78 EUR | Masse nette : 200,000 kg"
         " | Masse brute : 234,000 kg"),
        (0.06, 0.565, "Unités supplémentaires : 150 l | Colis : 2"),
        (0.10, 0.585, "Type"), (0.18, 0.585, "Libellé"), (0.55, 0.585, "Base d'imposition", 8, "d"),
        (0.68, 0.585, "Quotité", 8, "d"), (0.82, 0.585, "Montant", 8, "d"), (0.87, 0.585, "MP"),
        (0.10, 0.60, "A00"), (0.18, 0.60, "Droits de douane"), (0.55, 0.60, "2 257,78", 8, "d"),
        (0.68, 0.60, "0 %", 8, "d"), (0.82, 0.60, "0,00", 8, "d"), (0.875, 0.60, "E"),
        (0.10, 0.615, "X07"), (0.18, 0.615, "Droit spécifique alcool"), (0.55, 0.615, "150 LTR", 8, "d"),
        (0.68, 0.615, "0,40 EUR/LTR", 8, "d"), (0.82, 0.615, "60,00", 8, "d"), (0.875, 0.615, "E"),
        (0.10, 0.63, "B00"), (0.18, 0.63, "TVA"), (0.55, 0.63, "2 317,78", 8, "d"),
        (0.68, 0.63, "20 %", 8, "d"), (0.82, 0.63, "463,56", 8, "d"), (0.875, 0.63, "G"),
        (0.06, 0.67, "Total des droits et taxes"), (0.82, 0.67, "2 568,00", 8, "d"),
        (0.06, 0.685, "Total à payer ou à garantir"), (0.82, 0.685, "282,22", 8, "d"),
        (0.06, 0.72, "Modes de paiement : A = comptant ; E = paiement différé ; G = TVA autoliquidée", 7),
    ]
    return _pdf([p1])


@pytest.fixture(scope="module")
def h1() -> ChampsDeclaration:
    return _extraire_pdf(_h1_par_articles())


def test_extracteur_publie_dans_le_registre():
    ex = EXTRACTEURS_DETERMINISTES["declaration"]
    assert isinstance(ex, Extracteur) and ex.type == "deterministe"
    doc = Document(type=TypeDocument.declaration, sous_type="export_xml")
    assert not ex.supports(doc, [Page(fichier_id="f", numero=1, texte="x")])


def test_h1_entete(h1: ChampsDeclaration):
    assert h1.mrn.valeur == MRN and h1.mrn_prefixe == MRN[:15]
    assert h1.lrn.valeur == "REF-LOC-77"  # gardé distinct du MRN
    assert h1.date_acceptation.valeur == "2026-08-14"
    assert h1.version.valeur == "2"
    assert h1.importateur.nom.valeur == "Atelier Prisme SARL (FICTIF)"
    assert h1.importateur.tva.valeur == TVA_IMP
    assert h1.importateur.eori.valeur == "FR00071498000000"
    assert h1.declarant.tva.valeur == TVA_DECL  # jamais pris pour celui de l'importateur
    assert h1.devise_facture.valeur == "USD"
    assert h1.montant_total_facture.valeur == "12540.00" and h1.montant_total_facture.unite == "USD"
    assert h1.taux_change.valeur == "1.12500"
    assert h1.taux_change_sens.valeur == "devise_par_eur" and h1.taux_change_sens.methode is Methode.texte_natif
    assert (h1.incoterm.valeur, h1.incoterm_lieu.valeur) == ("FCA", "Newark")
    assert h1.pays_expedition.valeur == "US"
    assert h1.masse_brute_totale.valeur == "1234.500"
    assert h1.nombre_colis_total.valeur == "12" and h1.nombre_articles.valeur == "2"
    assert h1.total_droits_taxes.valeur == "2568.00" and h1.total_a_payer.valeur == "282.22"


def test_h1_documents_et_autoliquidation(h1: ChampsDeclaration):
    refs = {(d.type_code.valeur, d.reference.valeur) for d in h1.documents_references}
    assert refs == {("N380", "INV-2026-0042"), ("N740", "999-12345675"), ("1008", TVA_IMP)}
    types = {i.type for i in h1.indices_autoliquidation}
    assert TypeIndiceAutoliquidation.code_1008 in types and TypeIndiceAutoliquidation.mode_paiement_tva in types
    code = next(i for i in h1.indices_autoliquidation if i.type is TypeIndiceAutoliquidation.code_1008)
    assert code.tva.valeur == TVA_IMP and code.valeur.chemin == "declaration.indices_autoliquidation[0].valeur"


def test_h1_articles(h1: ChampsDeclaration):
    a1, a2 = h1.articles
    assert (a1.numero_article.valeur, a1.code_marchandise.valeur, a1.code_sh6) == ("1", "8471300000", "847130")
    assert a1.pays_origine.valeur == "CN" and a2.pays_origine.valeur == "JM"
    assert a1.montant_facture_article.valeur == "10000.00" and a1.montant_facture_article.unite == "USD"
    assert a1.valeur_statistique.valeur == "8888.89"
    assert (a1.masse_nette.valeur, a1.masse_brute.valeur) == ("900.000", "1000.500")
    assert a1.quantite_unite_supplementaire.valeur == "40" and a1.quantite_unite_supplementaire.unite == "C62"
    assert a2.quantite_unite_supplementaire.unite == "LTR"
    assert (a1.nombre_colis.valeur, a2.nombre_colis.valeur) == ("10", "2")


def test_h1_taxations(h1: ChampsDeclaration):
    lignes = [(t.article.valeur, t.type_taxe.valeur, t.categorie) for t in h1.taxations]
    assert lignes == [("1", "A00", CategorieTaxe.droit), ("1", "B00", CategorieTaxe.tva),
                      ("2", "A00", CategorieTaxe.droit), ("2", "X07", CategorieTaxe.autre_taxe),
                      ("2", "B00", CategorieTaxe.tva)]
    a00 = h1.taxations[0]
    assert (a00.base_montant.valeur, a00.taux.valeur, a00.montant.valeur) == ("8888.89", "2.5", "222.22")
    assert a00.taux_nature is TauxNature.ad_valorem
    assert a00.mode_paiement.valeur == "E" and a00.paiement_normalise is PaiementNormalise.differe
    assert h1.taxations[1].paiement_normalise is PaiementNormalise.autoliquide
    x07 = h1.taxations[3]  # catégorie lue sur le libellé imprimé (code inconnu de la table)
    assert x07.base_quantite.valeur == "150" and x07.base_unite.valeur == "LTR"
    assert x07.taux.valeur == "0.40" and x07.taux_nature is TauxNature.specifique
    assert x07.montant.valeur == "60.00"
    # le code de mode de paiement n'est jamais lu comme un montant
    assert all(t.montant.valeur not in ("E", "G") for t in h1.taxations)


def test_h1_provenance(h1: ChampsDeclaration):
    for vs in h1.iter_valeurs():
        assert vs.page == 1
        assert vs.methode is Methode.texte_natif
        assert vs.confiance == pytest.approx(0.97)
        assert vs.ancree, vs.chemin
        assert vs.zone is not None and 0 <= vs.zone.x0 < vs.zone.x1 <= 1
        assert vs.extracteur.id == ExtracteurDeclaration.id
    assert h1.montant_total_facture.valeur_brute == "12 540,00"
    assert h1.taux_change_sens.valeur_brute == "1 EUR = 1,12500 USD"


# --- 2. formulaire à cases ------------------------------------------------------------------------------------


def _cases() -> bytes:
    def case(x0, y0, x1, y1, libelle, valeur=None):
        out = [("rect", x0, y0, x1, y1), (x0 + 0.005, y0 + 0.012, libelle, 5)]
        if valeur is not None:
            out.append((x0 + 0.01, y0 + 0.032, valeur, 9))
        return out

    p1 = [(0.06, 0.04, "FORMULAIRE DÉCLARATION IMPORT (CASES)", 11)]
    p1 += case(0.05, 0.06, 0.50, 0.11, "2 Expéditeur / Exportateur", "Seller Demo Ltd (FICTITIOUS)")
    p1 += case(0.50, 0.06, 0.70, 0.11, "1 Déclaration", "IM A")
    p1 += case(0.70, 0.06, 0.95, 0.11, "5 Articles", "1")
    p1 += case(0.50, 0.11, 0.70, 0.16, "6 Total des colis", "3")
    p1 += case(0.70, 0.11, 0.95, 0.16, "7 Numéro de référence", "LRN-0000042")
    p1 += [("rect", 0.05, 0.16, 0.50, 0.24), (0.055, 0.172, "8 Destinataire / Importateur", 5),
           (0.06, 0.19, "Atelier Prisme SARL (FICTIF)", 9), (0.06, 0.205, f"TVA {TVA_IMP}", 9),
           (0.06, 0.22, "EORI FR00071498000000", 9),
           ("rect", 0.50, 0.16, 0.95, 0.24), (0.505, 0.172, "A Bureau de destination / MRN", 5),
           (0.51, 0.19, "FR000999 - bureau fictif", 9), (0.51, 0.205, f"MRN {MRN}", 9),
           (0.51, 0.22, "Acceptation : 02/09/2026", 9)]
    p1 += case(0.05, 0.24, 0.30, 0.29, "22 Monnaie et montant total facturé", "GBP 1 000,00")
    p1 += case(0.30, 0.24, 0.65, 0.29, "23 Taux de change", "1 GBP = 1,16981 EUR")
    p1 += case(0.65, 0.24, 0.95, 0.29, "35t Masse brute totale (kg)", "50,250")
    p1 += case(0.05, 0.29, 0.50, 0.34, "20 Conditions de livraison", "CIP Lyon")
    p1 += case(0.50, 0.29, 0.95, 0.34, "15 Pays d'expédition", "GB")
    p1 += [("rect", 0.05, 0.34, 0.60, 0.40), (0.055, 0.352, "31 Colis et désignation - article 1", 5),
           (0.06, 0.37, "THÉ NOIR EN VRAC", 9), (0.06, 0.385, "3 colis", 9)]
    p1 += case(0.60, 0.34, 0.75, 0.40, "32 Article n°", "1")
    p1 += case(0.75, 0.34, 0.95, 0.40, "33 Code des marchandises", "0902300000")
    p1 += case(0.05, 0.40, 0.35, 0.45, "34 Pays origine", "LK")
    p1 += case(0.35, 0.40, 0.65, 0.45, "35 Masse brute (kg)", "50,250")
    p1 += case(0.65, 0.40, 0.95, 0.45, "38 Masse nette (kg)", "45,000")
    p1 += case(0.05, 0.45, 0.50, 0.50, "42 Prix de l'article", "1 000,00")
    p1 += case(0.50, 0.45, 0.95, 0.50, "46 Valeur statistique", "1 169,81")
    p1 += [("rect", 0.05, 0.50, 0.95, 0.58), (0.055, 0.512, "47 Calcul des impositions", 5),
           (0.08, 0.53, "Type"), (0.40, 0.53, "Base d'imposition", 8, "d"), (0.55, 0.53, "Quotité", 8, "d"),
           (0.72, 0.53, "Montant", 8, "d"), (0.78, 0.53, "MP"),
           (0.08, 0.545, "A00"), (0.40, 0.545, "1 169,81", 8, "d"), (0.55, 0.545, "0 %", 8, "d"),
           (0.72, 0.545, "0,00", 8, "d"), (0.785, 0.545, "A"),
           (0.08, 0.56, "B00"), (0.40, 0.56, "1 169,81", 8, "d"), (0.55, 0.56, "5,5 %", 8, "d"),
           (0.72, 0.56, "64,34", 8, "d"), (0.785, 0.56, "A")]
    p1 += [("rect", 0.05, 0.58, 0.95, 0.66), (0.055, 0.592, "44 Mentions spéciales / Documents produits", 5),
           (0.06, 0.61, "N380 GB-INV-77", 9), (0.06, 0.625, "N705 DEMO000111222", 9),
           (0.55, 0.61, "Total droits et taxes : 64,34", 9), (0.55, 0.625, "Total à payer : 64,34", 9),
           (0.06, 0.68, "MP : A comptant / E différé / G autoliquidation TVA", 7)]
    return _pdf([p1])


def test_formulaire_a_cases():
    c = _extraire_pdf(_cases())
    assert c.mrn.valeur == MRN and c.lrn.valeur == "LRN-0000042"
    assert c.date_acceptation.valeur == "2026-09-02"
    assert c.importateur.nom.valeur == "Atelier Prisme SARL (FICTIF)" and c.importateur.tva.valeur == TVA_IMP
    assert (c.devise_facture.valeur, c.montant_total_facture.valeur) == ("GBP", "1000.00")
    assert (c.taux_change.valeur, c.taux_change_sens.valeur) == ("1.16981", "eur_par_devise")
    assert c.masse_brute_totale.valeur == "50.250" and c.nombre_colis_total.valeur == "3"
    assert c.nombre_articles.valeur == "1"
    assert (c.incoterm.valeur, c.incoterm_lieu.valeur, c.pays_expedition.valeur) == ("CIP", "Lyon", "GB")
    (a,) = c.articles
    assert (a.numero_article.valeur, a.code_marchandise.valeur, a.pays_origine.valeur) == ("1", "0902300000", "LK")
    assert (a.masse_brute.valeur, a.masse_nette.valeur) == ("50.250", "45.000")
    assert a.montant_facture_article.valeur == "1000.00" and a.valeur_statistique.valeur == "1169.81"
    assert a.nombre_colis.valeur == "3"
    assert [(t.type_taxe.valeur, t.taux.valeur, t.montant.valeur, t.paiement_normalise) for t in c.taxations] == [
        ("A00", "0", "0.00", PaiementNormalise.comptant), ("B00", "5.5", "64.34", PaiementNormalise.comptant)]
    assert {d.type_code.valeur for d in c.documents_references} == {"N380", "N705"}
    assert c.indices_autoliquidation == []
    assert (c.total_droits_taxes.valeur, c.total_a_payer.valeur) == ("64.34", "64.34")


# --- 3. preuve condensée (tableau, statut chiffré expliqué par la légende) -------------------------------------


def _preuve(sans_sens: bool = False) -> bytes:
    taux = "Taux......: 0,90000" if sans_sens else "Taux......: 1 USD = 0,90000 EUR"
    p1 = [
        (0.06, 0.05, "PREUVE DE DÉDOUANEMENT", 12),
        (0.06, 0.09, f"MRN.......: {MRN}"), (0.55, 0.09, "Incoterm..: DAP Lille"),
        (0.06, 0.105, "Réf. int..: LRN-123"), (0.55, 0.105, "Pays exp..: US"),
        (0.06, 0.12, "Accepté le: 01/09/2026"), (0.55, 0.12, "Valeur fac: 3000,00 USD"),
        (0.06, 0.135, "Importat..: Atelier Prisme SARL (FICTIF)"), (0.55, 0.135, taux),
        (0.06, 0.15, f"TVA imp...: {TVA_IMP}"), (0.55, 0.15, "Poids brut: 120,000 kg"),
        (0.55, 0.165, "Colis.....: 4"), (0.55, 0.18, "Nb articles: 2"),
        (0.06, 0.20, "Docs: N380:INV-9 N705:DEMO42"),
        (0.06, 0.23, "N"), (0.09, 0.23, "Code"), (0.20, 0.23, "Désignation"), (0.40, 0.23, "Or"),
        (0.52, 0.23, "Mt facturé", 8, "d"), (0.61, 0.23, "Base droits", 8, "d"), (0.66, 0.23, "Tx", 8, "d"),
        (0.73, 0.23, "Droits", 8, "d"), (0.82, 0.23, "Base TVA", 8, "d"), (0.89, 0.23, "TVA", 8, "d"),
        (0.92, 0.23, "St"),
        (0.06, 0.245, "1"), (0.09, 0.245, "6109100010"), (0.20, 0.245, "T-SHIRT COTON M"), (0.40, 0.245, "BD"),
        (0.52, 0.245, "1000,00", 8, "d"), (0.61, 0.245, "900,00", 8, "d"), (0.66, 0.245, "12", 8, "d"),
        (0.73, 0.245, "108,00", 8, "d"), (0.82, 0.245, "1008,00", 8, "d"), (0.89, 0.245, "201,60", 8, "d"),
        (0.925, 0.245, "7"),
        (0.09, 0.26, "A30"), (0.20, 0.26, "Droit antidumping"), (0.61, 0.26, "900,00", 8, "d"),
        (0.66, 0.26, "10", 8, "d"), (0.73, 0.26, "90,00", 8, "d"), (0.925, 0.26, "0"),
        (0.06, 0.275, "2"), (0.09, 0.275, "9503007000"), (0.20, 0.275, "JOUET 3 KG"), (0.40, 0.275, "CN"),
        (0.52, 0.275, "2000,00", 8, "d"), (0.61, 0.275, "1800,00", 8, "d"), (0.66, 0.275, "0", 8, "d"),
        (0.73, 0.275, "0,00", 8, "d"), (0.82, 0.275, "1800,00", 8, "d"), (0.89, 0.275, "360,00", 8, "d"),
        (0.925, 0.275, "1"),
        (0.55, 0.30, "Total droits (A00)"), (0.94, 0.30, "108,00", 8, "d"),
        (0.55, 0.315, "Total autres taxes"), (0.94, 0.315, "90,00", 8, "d"),
        (0.55, 0.33, "Total TVA (B00)"), (0.94, 0.33, "561,60", 8, "d"),
        (0.55, 0.345, "TOTAL DROITS ET TAXES"), (0.94, 0.345, "759,60", 8, "d"),
        (0.55, 0.36, "TOTAL A PAYER"), (0.94, 0.36, "558,00", 8, "d"),
        (0.06, 0.39, "St (statut paiement) : 0 = comptant ; 1 = différé ; 7 = TVA autoliquidée", 7),
    ]
    return _pdf([p1])


def test_preuve_condensee():
    c = _extraire_pdf(_preuve())
    assert c.mrn.valeur == MRN and c.lrn.valeur == "LRN-123"
    assert (c.devise_facture.valeur, c.montant_total_facture.valeur) == ("USD", "3000.00")
    assert c.importateur.tva.valeur == TVA_IMP
    assert [a.code_marchandise.valeur for a in c.articles] == ["6109100010", "9503007000"]
    assert [a.pays_origine.valeur for a in c.articles] == ["BD", "CN"]  # « M », « KG » restent des désignations
    assert c.articles[0].montant_facture_article.unite == "USD"
    resume = [(t.article.valeur, t.type_taxe.valeur if t.type_taxe else None, t.categorie, t.paiement_normalise)
              for t in c.taxations]
    assert resume == [
        ("1", "A00", CategorieTaxe.droit, PaiementNormalise.inconnu),  # « 7 » ne concerne que la TVA
        ("1", "B00", CategorieTaxe.tva, PaiementNormalise.autoliquide),
        ("1", "A30", CategorieTaxe.autre_taxe, PaiementNormalise.comptant),
        ("2", "A00", CategorieTaxe.droit, PaiementNormalise.differe),
        ("2", "B00", CategorieTaxe.tva, PaiementNormalise.differe),
    ]
    assert c.taxations[1].taux is None  # taux de TVA non imprimé : jamais inventé
    assert c.taxations[0].mode_paiement is None and c.taxations[1].mode_paiement.valeur == "7"
    assert (c.taxations[0].taux.valeur, c.taxations[0].montant.valeur) == ("12", "108.00")
    assert any(i.type is TypeIndiceAutoliquidation.mode_paiement_tva for i in c.indices_autoliquidation)


def test_sens_du_taux_deduit_methode_derive():
    c = _extraire_pdf(_preuve(sans_sens=True))
    assert c.taux_change.valeur == "0.90000"
    sens = c.taux_change_sens
    assert sens.valeur == "eur_par_devise" and sens.methode is Methode.derive
    assert sens.confiance == pytest.approx(0.85) and sens.derivee_de


def test_sens_du_taux_par_table_de_reference():
    from datetime import date

    table = TableTauxReference({"USD": {date(2026, 9, 1): Decimal("1.11")}})
    c = _extraire_pdf(_preuve(sans_sens=True), taux_reference=table)
    assert c.taux_change_sens.valeur == "eur_par_devise" and c.taux_change_sens.methode is Methode.derive


# --- 4. H7 (petits envois) -------------------------------------------------------------------------------------


def test_h7_droit_forfaitaire_et_fr7():
    p1 = [
        (0.06, 0.05, "DÉCLARATION - ENVOI DE FAIBLE VALEUR (H7)", 11),
        (0.06, 0.09, "MRN :"), (0.40, 0.09, MRN),
        (0.06, 0.105, "Date d'acceptation :"), (0.40, 0.105, "07/08/2026"),
        (0.06, 0.12, "Destinataire / importateur :"), (0.40, 0.12, "Atelier Prisme SARL (FICTIF)"),
        (0.06, 0.135, "N° TVA :"), (0.40, 0.135, TVA_IMP),
        (0.06, 0.15, "Référence fiscale complémentaire (DE 13 16) :"), (0.40, 0.15, f"FR7 {TVA_IMP}"),
        (0.06, 0.165, "Documents : N380 EXP-1 ; N740 999-00000001"),
        (0.06, 0.20, "Pos."), (0.12, 0.20, "Code marchandise"), (0.30, 0.20, "Description"),
        (0.62, 0.20, "Qté", 8, "d"), (0.65, 0.20, "Origine"), (0.82, 0.20, "Valeur (EUR)", 8, "d"),
        (0.94, 0.20, "Masse brute kg", 8, "d"),
        (0.07, 0.215, "1"), (0.12, 0.215, "8211910000"), (0.30, 0.215, "COUTEAU INOX"), (0.62, 0.215, "1", 8, "d"),
        (0.66, 0.215, "IN"), (0.82, 0.215, "3,00", 8, "d"), (0.94, 0.215, "0,211", 8, "d"),
        (0.06, 0.25, "Nombre d'articles (positions) : 1"),
        (0.06, 0.265, "Valeur intrinsèque totale : 3,00 EUR"),
        (0.06, 0.28, "Masse brute totale : 0,211 kg     Colis : 1"),
        (0.06, 0.31, "Type"), (0.14, 0.31, "Libellé"), (0.55, 0.31, "Base", 8, "d"), (0.70, 0.31, "Taux", 8, "d"),
        (0.85, 0.31, "Montant EUR", 8, "d"), (0.90, 0.31, "MP"),
        (0.06, 0.325, "FPE"), (0.14, 0.325, "Droit forfaitaire petits envois"), (0.55, 0.325, "1 article(s)", 8, "d"),
        (0.70, 0.325, "3,00 EUR/art.", 8, "d"), (0.85, 0.325, "3,00", 8, "d"), (0.905, 0.325, "A"),
        (0.06, 0.34, "B00"), (0.14, 0.34, "TVA"), (0.55, 0.34, "6,00", 8, "d"), (0.70, 0.34, "20 %", 8, "d"),
        (0.85, 0.34, "1,20", 8, "d"), (0.905, 0.34, "G"),
        (0.55, 0.37, "Total droits et taxes : -4,20"), (0.55, 0.385, "Total à payer : 3,00"),
        (0.06, 0.41, "Modes de paiement : A = comptant ; E = paiement différé ; G = TVA autoliquidée", 7),
    ]
    c = _extraire_pdf(_pdf([p1]))
    assert c.taux_change is None and c.taux_change_sens is None  # absent -> None
    assert (c.devise_facture.valeur, c.montant_total_facture.valeur) == ("EUR", "3.00")
    assert c.masse_brute_totale.valeur == "0.211" and c.nombre_colis_total.valeur == "1"
    refs = {(d.type_code.valeur, d.reference.valeur) for d in c.documents_references}
    assert ("FR7", TVA_IMP) in refs and ("N740", "999-00000001") in refs
    assert any(i.type is TypeIndiceAutoliquidation.reference_fr7 for i in c.indices_autoliquidation)
    (a,) = c.articles
    assert (a.code_marchandise.valeur, a.pays_origine.valeur, a.montant_facture_article.valeur) == (
        "8211910000", "IN", "3.00")
    assert a.masse_brute.valeur == "0.211" and a.quantite_unite_supplementaire.valeur == "1"
    fpe, tva = c.taxations
    assert fpe.article is None and fpe.categorie is CategorieTaxe.forfait_petits_envois
    assert (fpe.base_quantite.valeur, fpe.taux.valeur, fpe.taux_nature) == ("1", "3.00", TauxNature.specifique)
    assert tva.categorie is CategorieTaxe.tva and tva.paiement_normalise is PaiementNormalise.autoliquide
    # signe imprimé : valeur absolue + signe_imprime (§5.2)
    assert c.total_droits_taxes.valeur == "4.20" and c.total_droits_taxes.signe_imprime is SigneImprime.negatif


# --- 5. libellés anglais ------------------------------------------------------------------------------------------


def test_libelles_anglais():
    p1 = [
        (0.06, 0.05, "CUSTOMS DECLARATION - IMPORT", 11),
        (0.06, 0.09, "MRN"), (0.30, 0.09, MRN),
        (0.06, 0.105, "Date of acceptance"), (0.30, 0.105, "2026-08-20"),
        (0.55, 0.09, "Importer"), (0.55, 0.105, "Prism Workshop Ltd (FICTITIOUS)"),
        (0.55, 0.12, f"VAT No : {TVA_IMP}"),
        (0.06, 0.15, "Invoice currency :"), (0.30, 0.15, "JPY"),
        (0.55, 0.15, "Total amount invoiced :"), (0.80, 0.15, "1,250,000 JPY"),
        (0.06, 0.165, "Exchange rate :"), (0.30, 0.165, "1 EUR = 169,19238 JPY"),
        (0.55, 0.165, "Delivery terms :"), (0.80, 0.165, "EXW Osaka"),
    ]
    c = _extraire_pdf(_pdf([p1]))
    assert c.mrn.valeur == MRN and c.date_acceptation.valeur == "2026-08-20"
    assert c.importateur.tva.valeur == TVA_IMP
    assert c.importateur.nom.valeur == "Prism Workshop Ltd (FICTITIOUS)"
    assert (c.devise_facture.valeur, c.montant_total_facture.valeur) == ("JPY", "1250000")
    assert (c.taux_change.valeur, c.taux_change_sens.valeur) == ("169.19238", "devise_par_eur")
    assert c.incoterm.valeur == "EXW"
    assert c.articles == [] and c.taxations == []


# --- 6. lectures OCR simulées -----------------------------------------------------------------------------------


def _ocr_h1(conf_base: float = 0.97, mrn_lu: str = MRN, montant_b00: str = "1 822,22",
            taux_a00: str = "2,5", conf_tva: float = 0.97) -> PageText:
    return _page_ocr([
        [*_mots("DÉCLARATION EN DOUANE", 0.06)],
        [("MRN", 0.06, 0.09), (mrn_lu, 0.30, 0.45, conf_base)],
        [*_mots("Date d'acceptation", 0.06), ("14/08/2026", 0.30, 0.37, conf_base)],
        [("Importateur", 0.55, 0.62)],
        [*_mots("Atelier Prisme SARL (FICTIF)", 0.55)],
        [*_mots("N° TVA :", 0.55), (TVA_IMP, 0.63, 0.73, conf_tva)],
        [*_mots("Monnaie de facturation :", 0.06), ("EUR", 0.30, 0.33, conf_base),
         *_mots("Montant total facturé :", 0.50), ("8", 0.75, 0.76, conf_base), ("888,89", 0.765, 0.81, conf_base),
         ("EUR", 0.82, 0.85, conf_base)],
        [("Article", 0.06, 0.11), ("1", 0.115, 0.12), *_mots("Code marchandise", 0.20),
         ("8471300000", 0.36, 0.44, conf_base), ("Origine", 0.52, 0.57), ("CN", 0.60, 0.62, conf_base)],
        [*_mots("Montant facturé :", 0.06), ("8", 0.20, 0.21, conf_base), ("888,89", 0.215, 0.26, conf_base),
         ("EUR", 0.27, 0.30, conf_base)],
        [("Type", 0.10, 0.13), ("Libellé", 0.18, 0.23), ("Base", 0.42, 0.45), ("d'imposition", 0.455, 0.55),
         ("Quotité", 0.62, 0.68), ("Montant", 0.76, 0.82), ("MP", 0.86, 0.88)],
        [("A00", 0.10, 0.13, conf_base), *_mots("Droits de douane", 0.18), ("8", 0.49, 0.50, conf_base),
         ("888,89", 0.505, 0.55, conf_base), (taux_a00, 0.64, 0.66, conf_base), ("%", 0.665, 0.68, conf_base),
         ("222,22", 0.775, 0.82, conf_base), ("E", 0.865, 0.875, conf_base)],
        [("B00", 0.10, 0.13, conf_base), ("TVA", 0.18, 0.21), ("9", 0.49, 0.50, conf_base),
         ("111,11", 0.505, 0.55, conf_base), ("20", 0.645, 0.66, conf_base), ("%", 0.665, 0.68, conf_base),
         *[(m, x0, x1, conf_base) for m, x0, x1 in zip(montant_b00.split(), (0.76, 0.775), (0.77, 0.82),
                                                       strict=False)],
         ("G", 0.865, 0.875, conf_base)],
        [*_mots("Total des droits et taxes", 0.06), ("2", 0.76, 0.77, conf_base), ("044,44", 0.775, 0.82, conf_base)],
        [*_mots("Modes de paiement : A = comptant ; E = paiement différé ; G = TVA autoliquidée", 0.06)],
    ])


def test_ocr_lecture_isolee_sous_le_seuil_de_certitude():
    c = _extraire([_ocr_h1()])
    assert c.mrn.methode is Methode.ocr
    # aucune lecture OCR isolée n'atteint C_MIN_CERTAIN ; les recoupements la confirment
    assert c.mrn.confiance <= PLAFOND_OCR_SEUL
    assert c.date_acceptation.confiance <= PLAFOND_OCR_SEUL
    assert c.importateur.tva.confiance == pytest.approx(CONF_CONFIRMEE)  # clé de TVA vérifiée
    a00, b00 = c.taxations
    assert a00.montant.confiance == pytest.approx(CONF_CONFIRMEE)  # base × taux = montant
    assert b00.base_montant.confiance == pytest.approx(CONF_CONFIRMEE)  # base TVA = base + droits
    assert c.total_droits_taxes.confiance == pytest.approx(CONF_CONFIRMEE)  # somme des taxes
    assert all(v.ancree for v in c.iter_valeurs() if v.methode is Methode.ocr)


def test_ocr_confiance_suit_la_confiance_des_mots():
    haute = _extraire([_ocr_h1(conf_base=0.97)])
    basse = _extraire([_ocr_h1(conf_base=0.55)])
    assert basse.date_acceptation.confiance < haute.date_acceptation.confiance < 0.9


def test_ocr_confusion_lettre_chiffre_baisse_la_confiance():
    # « O » lu à la place de « 0 » dans l'année : corrigé par la forme du MRN, avec une confiance réduite
    lu = "26FRK7G7KR9KVHGNG3".replace("26", "2G", 1)
    c = _extraire([_ocr_h1(mrn_lu=lu)])
    assert c.mrn.valeur == MRN and c.mrn.valeur_brute == lu
    assert c.mrn.confiance < 0.8
    tva_mal_lue = TVA_IMP.replace("0", "O", 1)
    pt = _ocr_h1()
    pt2 = PageText(numero=1, texte=pt.texte.replace(TVA_IMP, tva_mal_lue),
                   lignes=[type(li)(li.texte.replace(TVA_IMP, tva_mal_lue),
                                    tuple(Mot(tva_mal_lue if m.texte == TVA_IMP else m.texte, m.x0, m.y0, m.x1,
                                              m.y1, m.confiance) for m in li.mots)) for li in pt.lignes],
                   qualite=QualiteTexte.ocr, source="ocr", score_ocr=0.93, largeur=595.0, hauteur=842.0)
    c2 = _extraire([pt2])
    assert c2.importateur.tva.valeur == TVA_IMP and c2.importateur.tva.valeur_brute == tva_mal_lue


def test_ocr_separateur_decimal_perdu_releve_jamais_certain():
    c = _extraire([_ocr_h1(montant_b00="182222")])
    b00 = c.taxations[1]
    assert b00.montant.valeur == "1822.22" and b00.montant.valeur_brute == "182222"
    assert b00.montant.confiance <= 0.80


def test_ocr_incoherence_plafonne():
    c = _extraire([_ocr_h1(taux_a00="3,5")])  # 8 888,89 × 3,5 % ≠ 222,22
    a00 = c.taxations[0]
    assert a00.taux.valeur == "3.5" and a00.taux.confiance <= 0.80
    # le montant reste confirmé par la somme des taxes : c'est le taux qui est douteux
    assert a00.montant.confiance == pytest.approx(CONF_CONFIRMEE)


def test_page_illisible_ne_produit_rien():
    pt = PageText(numero=1, texte="", qualite=QualiteTexte.illisible, source="aucune")
    page = Page(fichier_id="f", numero=1, qualite_texte=QualiteTexte.illisible, texte="")
    doc = Document(type=TypeDocument.declaration, pages=[PageRef(fichier_id="f", numero=1)])
    ex = ExtracteurDeclaration()
    assert not ex.supports(doc, [page])
    res = ex.extract(doc, [page], ExtractionContext(options={"textes_pages": {1: pt}}))
    assert res.champs is not None and res.champs.mrn is None and res.partielle


# --- Mise au point du rappel (D-804, D-811) -----------------------------------------------------------------


def _entete_ocr() -> list[list[tuple]]:
    return [
        _mots("DÉCLARATION EN DOUANE - IMPORTATION (H1)", 0.06),
        [*_mots("MRN", 0.06), *_mots(MRN, 0.30)],
        [*_mots("Date d'acceptation", 0.06), *_mots("14/08/2026", 0.30)],
    ]


def test_documents_produits_sans_colonne_de_codes():
    """OCR : colonne des codes perdue (« référence + libellé ») et séparateur « | » entre code et référence."""
    lignes = [
        *_entete_ocr(),
        _mots("Documents produits / références (DG 12 03)", 0.06),
        [*_mots("FAC/2026/0042-0", 0.06), *_mots("Facture commerciale", 0.40)],
        [*_mots("N705 |", 0.06), *_mots("DEMO000111222", 0.14), *_mots("Connaissement", 0.40)],
        [*_mots("1008 |", 0.06), *_mots(TVA_IMP, 0.14), *_mots("Autoliquidation TVA", 0.40)],
        [*_mots("Article 1", 0.06), *_mots("Code marchandise 8471300000", 0.20)],
        [*_mots("Désignation : FACTURE COMMERCIALE EN PAPIER 4711", 0.06)],
    ]
    c = _extraire([_page_ocr(lignes)])
    refs = {(d.type_code.valeur, d.reference.valeur) for d in c.documents_references}
    assert refs == {("N380", "FAC/2026/0042-0"), ("N705", "DEMO000111222"), ("1008", TVA_IMP)}
    n380 = next(d for d in c.documents_references if d.type_code.valeur == "N380")
    assert n380.type_code.valeur_brute == "Facture commerciale" and n380.type_code.ancree


def test_forfait_petits_envois_hors_tableau():
    """OCR : en-tête du tableau des taxes illisible ; la ligne de forfait est lue (présence, base, taux),
    sans son montant (le reste du tableau a pu échapper à la lecture)."""
    lignes = [
        _mots("DÉCLARATION - ENVOI DE FAIBLE VALEUR (H7)", 0.06),
        [*_mots("MRN :", 0.06), *_mots(MRN, 0.40)],
        _mots("Nombre d'articles (positions) : 4", 0.06),
        _mots("Droits et taxes", 0.06),
        _mots("type | bone ER AR ES NE ame Tate) Montant EUR | We", 0.06),
        [*_mots("Droit forfaitaire petits envois", 0.06), *_mots("4 article(s)", 0.45), *_mots("3,00 EUR/art.", 0.62),
         *_mots("12,00 | E.", 0.80)],
    ]
    c = _extraire([_page_ocr(lignes)])
    (fpe,) = [t for t in c.taxations if t.categorie is CategorieTaxe.forfait_petits_envois]
    assert (fpe.base_quantite.valeur, fpe.taux.valeur, fpe.taux_nature) == ("4", "3.00", TauxNature.specifique)
    assert fpe.montant is None
