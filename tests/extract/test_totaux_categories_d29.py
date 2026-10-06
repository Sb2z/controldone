"""Totaux imprimés par code de taxe et recoupement des lectures OCR d'une déclaration (D-2903).

Documents **fictifs** propres à ces tests : une édition de déclaration en tableaux, rendue en PDF puis présentée
à l'extracteur comme une page lue par OCR (mêmes mots, confiance OCR par mot)."""

from __future__ import annotations

import io
from dataclasses import replace

from reportlab.lib.pagesizes import A4, landscape
from reportlab.pdfgen import canvas

from controldone.extract.base import ExtractionContext
from controldone.extract.deterministe.declaration import ExtracteurDeclaration
from controldone.ids import IdGenerator
from controldone.ingest import OptionsPages, extraire_pages
from controldone.ingest.texte import Ligne, PageText
from controldone.model import Document, Page, PageRef
from controldone.model.champs import ChampsDeclaration
from controldone.model.enums import QualiteTexte, TypeDocument
from controldone.normalize import tva_fr_depuis_siren

TVA_IMP = tva_fr_depuis_siren("000424242")
MRN = "26FRQ7ZK3M5T8W2N4B"


def _pdf(elements: list[tuple]) -> bytes:
    larg, haut = landscape(A4)
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=landscape(A4), invariant=1)
    for x, y, texte in elements:
        c.setFont("Helvetica", 8)
        c.drawString(x * larg, (1 - y) * haut, texte)
    c.showPage()
    c.save()
    return buf.getvalue()


def _page(taxes: list[tuple], totaux: str | None, total: str = "74,47") -> bytes:
    el = [(0.04, 0.05, "LOGICIEL FICTIF — EDITION DE LA DECLARATION ACCEPTEE"),
          (0.04, 0.08, f"MRN: {MRN}   LRN: LRN-TEST-0077   Version: 1   Date d'acceptation: 12/05/2026"),
          (0.04, 0.10, f"Importateur: Atelier Fictif SARL   TVA: {TVA_IMP}"),
          (0.04, 0.14, "Monnaie de facturation: EUR   Montant total facturé: 300,00"),
          (0.04, 0.16, "Masse brute totale: 30,000 kg   Colis: 4   Nombre d'articles: 2")]
    tcols = [(0.05, "Art"), (0.09, "Type"), (0.20, "Base"), (0.28, "Taux"), (0.36, "Montant"), (0.44, "A payer"),
             (0.50, "MP")]
    el += [(0.04, 0.31, "LIQUIDATION")] + [(x, 0.33, t) for x, t in tcols]
    for k, ligne in enumerate(taxes):
        el += [(x, 0.35 + 0.02 * k, t) for (x, _), t in zip(tcols, ligne, strict=True)]
    if totaux:
        el.append((0.04, 0.45, totaux))
    el.append((0.04, 0.47, f"TOTAL DROITS ET TAXES: {total} EUR   TOTAL A PAYER: {total} EUR"))
    return _pdf(el)


def _extraire_ocr(contenu: bytes, conf: float = 0.96) -> ChampsDeclaration:
    """Extraction sur le texte natif du PDF présenté comme une lecture OCR (confiance ``conf`` par mot)."""
    pe = extraire_pages(contenu, type_mime="application/pdf", options=OptionsPages(ocr=False, isoler=False))[0]
    lignes = [Ligne(texte=li.texte, mots=tuple(replace(m, confiance=conf) for m in li.mots)) for li in pe.texte.lignes]
    pt = PageText(numero=1, texte=pe.texte.texte, lignes=lignes, qualite=QualiteTexte.ocr, source="ocr",
                  score_ocr=0.93, largeur=842.0, hauteur=595.0)
    page = Page(fichier_id="fic_test", numero=1, qualite_texte=QualiteTexte.ocr, texte=pt.texte)
    doc = Document(type=TypeDocument.declaration,
                   pages=[PageRef(fichier_id="fic_test", numero=1, qualite_texte=QualiteTexte.ocr)])
    ctx = ExtractionContext(ids=IdGenerator.deterministe(5), options={"textes_pages": {1: pt}})
    res = ExtracteurDeclaration().extract(doc, [page], ctx)
    assert isinstance(res.champs, ChampsDeclaration)
    return res.champs


# montant de la ligne 1 / A00 imprimé faux (base × taux = 5,67) : la ligne est incohérente
TAXES = [("1", "A00", "210,00", "2,7 %", "8,67", "8,67", "E"), ("1", "B00", "215,67", "20,0 %", "43,13", "43,13", "E"),
         ("2", "A00", "105,00", "3,7 %", "3,89", "3,89", "E"), ("2", "B00", "108,89", "20,0 %", "21,78", "21,78", "E")]


def _taxe(c: ChampsDeclaration, article: str, code: str):
    return next(t for t in c.taxations if t.article.valeur == article and t.type_taxe.valeur == code)


def test_somme_des_lignes_d_un_code_egale_a_son_total_confirme_les_montants():
    c = _extraire_ocr(_page(TAXES, "Total A00: 12,56   Total B00: 64,91", total="77,47"))
    m = _taxe(c, "1", "A00").montant
    assert m.valeur == "8.67" and m.confiance >= 0.9  # Σ A00 = 12,56 imprimé : lecture confirmée
    assert _taxe(c, "1", "A00").taux.confiance < 0.9  # facteur du produit contredit : non confirmé
    assert c.total_droits_taxes.confiance >= 0.9


def test_sans_totaux_par_code_la_ligne_incoherente_reste_sous_le_seuil():
    taxes = [list(t) for t in TAXES]
    taxes[2][4] = taxes[2][5] = "3,8"  # une autre ligne mal lue : la somme générale ne tient plus
    c = _extraire_ocr(_page([tuple(t) for t in taxes], None, total="77,47"))
    assert _taxe(c, "1", "A00").montant.confiance < 0.9
    assert c.total_droits_taxes.confiance < 0.9


def test_total_general_confirme_par_les_totaux_par_code():
    # ligne 2 / A00 illisible : seule la somme des totaux par code confirme le total des droits et taxes
    taxes = [list(t) for t in TAXES]
    taxes[2][4] = taxes[2][5] = "3:8"
    c = _extraire_ocr(_page([tuple(t) for t in taxes], "Total A00: 12,56   Total B00: 64,91", total="77,47"))
    assert c.total_droits_taxes.valeur == "77.47" and c.total_droits_taxes.confiance >= 0.9
    assert c.total_a_payer.confiance >= 0.9


def test_total_de_code_faux_ne_confirme_ni_n_infirme():
    # total A00 imprimé faux (B2) et total général qui ne tient pas : aucune confirmation par le code A00
    c = _extraire_ocr(_page(TAXES, "Total A00: 99,99   Total B00: 64,91", total="74,47"))
    assert _taxe(c, "1", "A00").montant.confiance < 0.9
    assert _taxe(c, "2", "B00").montant.confiance >= 0.9  # Σ B00 = 64,91 imprimé
    # les totaux par code ne sont jamais des lignes de taxation (les contrôles additionnent les lignes)
    assert all(t.article is not None for t in c.taxations)


def test_montant_de_devise_n_est_pas_un_total_de_code():
    taxes = [list(t) for t in TAXES]
    taxes[2][4] = taxes[2][5] = "3:8"
    contenu = _page([tuple(t) for t in taxes], "Total TRY 1 616,35   Total A00: 12,56   Total B00: 64,91", total="77,47")
    c = _extraire_ocr(contenu)
    assert c.total_droits_taxes.confiance >= 0.9  # « TRY » n'est pas un code de taxe lu : Σ A00 + B00 = total


def test_separateur_decimal_lu_deux_points():
    taxes = [list(t) for t in TAXES]
    taxes[2][4] = "3:89:"
    c = _extraire_ocr(_page([tuple(t) for t in taxes], None, total="77,47"))
    m = _taxe(c, "2", "A00").montant
    assert m.valeur == "3.89" and m.confiance < 0.9  # relecture : jamais certaine seule


def test_ligne_de_taxe_manquante_aucun_total_confirme():
    # D-2906 : la ligne 2 / A00 n'est pas imprimée-lue : ni la somme des lignes ni celle des totaux par code ne
    # confirme le total (une ligne manque à la somme que font les contrôles)
    taxes = [t for t in TAXES if not (t[0] == "2" and t[1] == "A00")]
    c = _extraire_ocr(_page(taxes, "Total A00: 12,56   Total B00: 64,91", total="77,47"))
    assert c.total_droits_taxes.confiance < 0.9 and c.total_a_payer.confiance < 0.9


# --- D-3101 : totaux par code portés par le modèle ---------------------------------------------------------------


def _totaux(c: ChampsDeclaration) -> dict[str, tuple[str, float]]:
    return {t.type_taxe.valeur: (t.montant.valeur, t.montant.confiance) for t in c.totaux_par_code}


def test_totaux_par_code_portes_par_le_modele_jamais_des_lignes():
    c = _extraire_ocr(_page(TAXES, "Total A00: 12,56   Total B00: 64,91", total="77,47"))
    t = _totaux(c)
    assert {k: v for k, (v, _) in t.items()} == {"A00": "12.56", "B00": "64.91"}
    assert t["A00"][1] >= 0.9 and t["B00"][1] >= 0.9  # Σ des lignes du code = total imprimé du code
    assert len(c.taxations) == 4 and all(x.article is not None for x in c.taxations)
    assert c.totaux_par_code[0].montant.chemin == "declaration.totaux_par_code[0].montant"


def test_total_de_code_faux_porte_tel_quel_sans_confirmation():
    c = _extraire_ocr(_page(TAXES, "Total A00: 99,99   Total B00: 64,91", total="74,47"))
    t = _totaux(c)
    assert t["A00"][0] == "99.99" and t["A00"][1] < 0.9  # valeur mise en cause par B2 : jamais confirmée
    assert t["B00"][1] >= 0.9


def test_code_suivi_de_deux_points_dans_une_case_comptable():
    c = _extraire_ocr(_page(TAXES, "N380 0005-0   A00 : 12,56   B00 : 64,91", total="77,47"))
    assert {k: v for k, (v, _) in _totaux(c).items()} == {"A00": "12.56", "B00": "64.91"}


def test_code_entre_parentheses_apres_le_libelle():
    c = _extraire_ocr(_page(TAXES, "Total droits (A00)   12,56", total="77,47"))
    assert {k: v for k, (v, _) in _totaux(c).items()} == {"A00": "12.56"}


def test_code_deux_points_avec_plusieurs_nombres_ignore():
    c = _extraire_ocr(_page(TAXES, "A00 : 12,56 20,0 % 2,51", total="77,47"))
    assert _totaux(c) == {}
