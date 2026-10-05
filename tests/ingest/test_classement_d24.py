"""Classement, découpage et regroupement : nouvelles présentations (D-2406 à D-2409). Documents **fictifs** propres
à ces tests (aucun nom, numéro ou mise en page du banc)."""

from __future__ import annotations

import io

import fabriques as fab
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

from controldone.ids import IdGenerator
from controldone.ingest import OptionsPages, classer_page, decouper_fichier, extraire_pages, recevoir_octets
from controldone.model.enums import SousTypeSupport, TypeDocument

LOCAL = OptionsPages(isoler=False)
MRN = "26FR0000000000AAA1"


def _classer(lignes, titre=None, numero=1):
    p = extraire_pages(fab.pdf([lignes], titres=[titre]), type_mime="application/pdf", options=LOCAL)[0]
    return classer_page(p.texte, numero_dans_fichier=numero)


def _docs_pdf(contenu: bytes):
    rec = recevoir_octets([("lot.pdf", contenu)], ids=IdGenerator.deterministe(3))
    fr = rec.fichiers[0]
    return decouper_fichier(fr.fichier, fr.contenu, options=LOCAL, ids=IdGenerator.deterministe(4)).documents


# --- rubriques citées : pas des intitulés -----------------------------------------------------------------------


def test_annexe_de_declaration_montant_facture_n_est_pas_un_intitule():
    lignes = [f"ANNEXE 1 — MRN {MRN}   2/2",
              "Article 1 — 8471300000 — origine CN — préf. 100 — régime 4000/000",
              "Montant facturé 1 000,00 USD — valeur statistique 862,07 EUR",
              "Masse nette 9,000 kg — masse brute 10,000 kg — colis 2",
              "Droits et autres taxes   TVA à l'importation",
              "Taxe   Base   Taux   Montant   MP   Taxe   Base   Taux   Montant   MP",
              "A00   862,07   2,0%   17,24   A   B00   879,31   20,0%   175,86   A"]
    c = _classer(lignes, numero=2)
    assert c.type is TypeDocument.declaration, c.indices


def test_page_de_suite_d_un_etat_de_liquidation_n_est_pas_une_facture():
    lignes = ["Art.   Code NC   Or.   Désignation   Mt facturé   Net kg   Brut kg   Colis   Taxe   Base   Taux",
              "11   8471300000   CN   Article fictif   100,00   1,000   1,200   1   A00   100,00   2,0 %",
              "B00   102,00   20,0 %"]
    assert _classer(lignes, numero=2).type is not TypeDocument.facture_commerciale


# --- factures de transitaire et avoirs en polonais, portugais -------------------------------------------------

FT_PL = ["Spedycja Fikcja Sp. z o.o. (FICTIF)", "Data wystawienia: 01.02.2026 — str. 1", f"MRN: {MRN}",
         "Należności celne i podatkowe (refaktura, poza VAT)", "Lp. Nazwa   MRN   Ilość   Wartość netto",
         f"1   Cło   {MRN}   1 szt.   71,97", f"2   VAT z tytułu importu   {MRN}   1 szt.   403,39",
         "Usługi", "3   Odprawa celna   1 szt.   55,00", "4   Prowizja za kredytowanie   1 szt.   15,00"]


def test_facture_de_transitaire_polonaise():
    c = _classer(FT_PL, "FAKTURA VAT Nr FV/1/01/2026")
    assert c.type is TypeDocument.facture_transitaire, c.indices
    assert c.refs.numero_facture == "FV1012026"


def test_facture_corrective_polonaise_est_un_avoir():
    lignes = ["Spedycja Fikcja Sp. z o.o. (FICTIF)", "Faktura pierwotna: FV/1/01/2026", f"MRN: {MRN}",
              "Usługi", "1   Odprawa celna   1 szt.   10,00   -10,00"]
    assert _classer(lignes, "FAKTURA KORYGUJACA Nr FK/1/2026").type is TypeDocument.avoir
    recap = ["Spedycja Fikcja Sp. z o.o. (FICTIF)", "PODSUMOWANIE / RÉCAPITULATIF", "Razem netto   -10,00 EUR",
             "VAT 20 %   -2,00 EUR", "Razem brutto   -12,00 EUR"]
    assert _classer(recap, "FAKTURA Nr FK/1/2026", numero=2).type is TypeDocument.avoir


def test_avoir_cite_dans_le_corps_d_une_facture_ne_l_emporte_pas():
    lignes = ["Zollagentur Fiktiv AG (FICTIF)", "Datum: 06.07.2026", f"MRN: {MRN}",
              "Leistung   Menge   Betrag", "Verzollung   1   59.00 EUR", "Zollabgaben   1   882.00 EUR",
              "Gutschrift zu Rechnung ZF-26-000001   -25.00 EUR", "Total EUR   916.00 EUR"]
    c = _classer(["RECHNUNG Nr. ZF-26-000002", *lignes])
    assert c.type is TypeDocument.facture_transitaire, c.indices


def test_lettre_d_accompagnement_portugaise():
    lignes = ["Trânsitos Fictícios Lda (FICTIF)", "Assunto: faturas da remessa FICU000000001", "Exmos. Senhores,",
              "Junto enviamos as nossas faturas relativas ao desalfandegamento da vossa remessa.",
              "Com os melhores cumprimentos,"]
    c = _classer(lignes)
    assert c.type is TypeDocument.document_support and c.sous_type == SousTypeSupport.lettre_accompagnement.value


# --- intitulé collé au nom de société (texte natif) ------------------------------------------------------------


def _pdf_entete(nom: str, titre: str, x_titre: float, corps: list[str]) -> bytes:
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4, invariant=1)
    c.setFont("Helvetica-Bold", 13)
    c.drawString(40, 800, nom)
    c.setFont("Helvetica-Bold", 11)
    c.drawString(x_titre, 800, titre)
    c.setFont("Helvetica", 9)
    y = 770
    for li in corps:
        c.drawString(40, y, li)
        y -= 14
    c.showPage()
    c.save()
    return buf.getvalue()


def test_intitule_colle_ou_entrelace_au_nom_de_societe():
    for x_titre in (160.0, 120.0):  # juste après le nom, puis par-dessus la fin du nom (mots entrelacés)
        contenu = _pdf_entete("Spedycja Fikcja Sp. z o.o.", "NOTA OBCIAZENIOWA Nr FV/7/09/2026", x_titre, FT_PL[1:])
        p = extraire_pages(contenu, type_mime="application/pdf", options=LOCAL)[0]
        c = classer_page(p.texte)
        assert c.type is TypeDocument.facture_transitaire, (x_titre, c.indices)
        assert c.refs.numero_facture == "FV7092026", x_titre


# --- découpage ---------------------------------------------------------------------------------------------------


def test_facture_polonaise_sur_deux_pages_meme_numero_est_un_document():
    recap = ["Spedycja Fikcja Sp. z o.o. (FICTIF)", "Data wystawienia: 01.02.2026 — str. 2",
             "PODSUMOWANIE / RÉCAPITULATIF", "Razem należności (refaktura)   475,36 EUR", "Razem brutto   545,36 EUR"]
    docs = _docs_pdf(fab.pdf([FT_PL, recap], titres=["FAKTURA VAT Nr FV/1/01/2026", "FAKTURA VAT Nr FV/1/01/2026"]))
    assert [(d.type, [p.numero for p in d.pages]) for d in docs] == [(TypeDocument.facture_transitaire, [1, 2])]


def test_versions_rectificatives_dans_un_meme_pdf_sont_deux_declarations():
    def decl(mrn):
        return [f"MRN {mrn}", "Code marchandise 8471300000   Régime 4000", "Liquidation", "Droits et taxes   50,00",
                "Mode de paiement A", "Déclarant: Transitaire Fictif SAS"]

    suite = ["Suite — déclaration   page 2/2", "Article 2   Code marchandise 8471300000", "Liquidation",
             "Droits et taxes   25,00", "Régime 4000"]
    v1, v2 = "26FRAB12CD34EF5XYZ", "26FRAB12CD34EF5KLM"  # même préfixe (15), versions différentes
    docs = _docs_pdf(fab.pdf([decl(v1), suite, decl(v2), suite],
                             titres=["DÉCLARATION EN DOUANE", None, "DÉCLARATION EN DOUANE", None]))
    assert [(d.type, [p.numero for p in d.pages]) for d in docs] == [
        (TypeDocument.declaration, [1, 2]), (TypeDocument.declaration, [3, 4])]
