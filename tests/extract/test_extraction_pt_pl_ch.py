"""Factures portugaises, polonaises, suisses ; montants TVA comprise ; reports de page (D-2501 à D-2510).

Mises en page **propres à ces tests** (ni celles du banc, ni celles de la démonstration), rendues par reportlab.
Sociétés, numéros, adresses et MRN **fictifs**.
"""

from __future__ import annotations

from decimal import Decimal

import fixtures_fc as fx
import pytest

from controldone.model.enums import Methode, NatureLigne, SigneImprime, TypeDocument
from controldone.normalize import normalize_unit, tva_fr_depuis_siren
from controldone.normalize.natures import nature_libelle
from controldone.normalize.text import cle_texte

TVA_EM = tva_fr_depuis_siren("000313131")
TVA_CL = tva_fr_depuis_siren("000424241")
TVA_REP = tva_fr_depuis_siren("000979797")
MRN_A = "26FRK3M5P7R9T1V3X5"
MRN_B = "26FRB2D4F6H8J0L2N4"


def _v(x):
    return None if x is None else x.valeur


def _ft(contenu: bytes, td: TypeDocument = TypeDocument.facture_transitaire):
    r = fx.extraire(contenu, td, extracteur=_ext_ft())
    assert r.champs is not None
    return r


def _ext_ft():
    from controldone.extract.deterministe.facture_transitaire import ExtracteurFactureTransitaire

    return ExtracteurFactureTransitaire()


def _fc(contenu: bytes):
    r = fx.extraire(contenu, TypeDocument.facture_commerciale)
    assert r.champs is not None
    return r.champs


# --- vocabulaire -------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(("libelle", "nature"), [
    ("Desalfandegamento", NatureLigne.frais_dedouanement),
    ("Direitos aduaneiros", NatureLigne.debours_droits),
    ("IVA na importação", NatureLigne.debours_tva),
    ("Comissão de adiantamento", NatureLigne.frais_avance_fonds),
    ("Armazenagem", NatureLigne.magasinage),
    ("Manuseamento", NatureLigne.manutention),
    ("Odprawa celna", NatureLigne.frais_dedouanement),
    ("Cło", NatureLigne.debours_droits),
    ("Cło antydumpingowe", NatureLigne.debours_autres_taxes),
    ("VAT z tytułu importu", NatureLigne.debours_tva),
    ("Prowizja za kredytowanie", NatureLigne.frais_avance_fonds),
    ("Obsługa ładunku", NatureLigne.manutention),
    ("Składowanie", NatureLigne.magasinage),
    ("Dostawa", NatureLigne.transport),
])
def test_natures_pt_pl(libelle, nature):
    assert nature_libelle(libelle) is nature


def test_cle_texte_lettres_barrees():
    assert cle_texte("Razem usługi") == "razem uslugi"
    assert cle_texte("Do zapłaty") == "do zaplaty"


@pytest.mark.parametrize(("brut", "code"), [("szt.", "C62"), ("sztuk", "C62"), ("par", "PR"), ("kpl", "SET"),
                                            ("unidades", "C62")])
def test_unites_pl_pt(brut, code):
    assert normalize_unit(brut).code == code


# --- facture portugaise TVA comprise (D-2502) -------------------------------------------------------------------


def pdf_pt_ttc() -> bytes:
    p = fx.PagePdf()
    p.t(40, 50, "Agência Quimérica de Despachos Lda", taille=12, gras=True)
    p.t(40, 64, f"Rua do Sonho 9 · 13000 Marseille · NIF {TVA_EM}")
    p.t(430, 50, "FATURA", taille=14, gras=True)
    p.t(430, 66, "N.º QD 2026/0451")
    p.t(430, 80, "Data: 14-05-2026")
    p.t(40, 110, "Cliente")
    p.t(40, 124, "Ateliers Chimériques SAS")
    p.t(40, 138, "4 place de l'Invention, 31000 Toulouse")
    p.t(40, 152, f"NIF/IVA: {TVA_CL}")
    p.t(330, 124, f"MRN: {MRN_A}")
    p.t(330, 138, "AWB / B/L / CMR: 999-31415926")
    y = 200
    p.ligne(y, [(40, "Descrição", False), (200, "MRN", False), (330, "Qtd", True), (400, "Preço unit. c/ IVA", True),
                (450, "Taxa", True), (540, "Total c/ IVA", True)], taille=8)
    linhas = [
        ("Direitos aduaneiros", MRN_A, "1", "80,25 €", "isento", "80,25 €"),
        ("Desalfandegamento", MRN_A, "1", "96,00 €", "20%", "96,00 €"),
        ("Armazenagem", MRN_A, "3", "21,60 €", "20%", "64,80 €"),
        ("Entrega", "", "1", "120,00 €", "20%", "120,00 €"),
    ]
    for k, (d, m, q, pu, tx, tt) in enumerate(linhas):
        p.ligne(y + 16 * (k + 1), [(40, d, False), (200, m, False), (330, q, True), (400, pu, True), (450, tx, True),
                                   (540, tt, True)], taille=8)
    y += 16 * 6
    p.t(40, y, "Quadro resumo do IVA")
    p.ligne(y + 14, [(40, "Taxa normal 20 % (FR)", False), (400, "234,00", True), (540, "46,80", True)])
    p.ligne(y + 40, [(330, "Total despesas (suplidos)", False), (540, "80,25 €", True)])
    p.ligne(y + 54, [(330, "Total sem IVA", False), (540, "314,25 €", True)])
    p.ligne(y + 68, [(330, "IVA", False), (540, "46,80 €", True)])
    p.ligne(y + 82, [(330, "Total com IVA", False), (540, "361,05 €", True)])
    p.ligne(y + 96, [(330, "Total a pagar", False), (540, "361,05 €", True)])
    return fx.pdf([p])


@pytest.fixture(scope="module")
def pt_ttc():
    return _ft(pdf_pt_ttc()).champs


def test_pt_entete_et_totaux(pt_ttc):
    c = pt_ttc
    assert _v(c.numero) == "QD 2026/0451"
    assert _v(c.date) == "2026-05-14"
    assert _v(c.client_facture.tva) == TVA_CL
    assert _v(c.total_debours) == "80.25"
    assert _v(c.total_ht) == "314.25"
    assert _v(c.total_tva) == "46.80"
    assert _v(c.total_ttc) == "361.05"


def test_pt_lignes_ttc_exposent_l_imprime(pt_ttc):
    lignes = list(pt_ttc.lignes)
    assert [lg.nature for lg in lignes] == [NatureLigne.debours_droits, NatureLigne.frais_dedouanement,
                                           NatureLigne.magasinage, NatureLigne.transport]
    assert [_v(lg.montant_ttc) for lg in lignes] == ["80.25", "96.00", "64.80", "120.00"]
    # ligne exonérée : HT = montant imprimé, taux 0
    droits = lignes[0]
    assert _v(droits.montant_ht) == "80.25" and _v(droits.taux_tva) == "0"
    assert _v(droits.prix_unitaire) == "80.25"
    # ligne taxée : HT non imprimé -> dérivé, marqué, plafonné ; ni prix unitaire HT ni TVA fabriqués
    dedouan = lignes[1]
    assert _v(dedouan.montant_ht) == "80.00"
    assert dedouan.montant_ht.methode is Methode.derive
    assert dedouan.montant_ht.confiance <= 0.6
    assert dedouan.montant_ht.regle_derivation == "montant_ttc / (1 + taux_tva)"
    assert dedouan.prix_unitaire is None and dedouan.montant_tva is None
    assert _v(dedouan.taux_tva) == "20" and dedouan.taux_tva.confiance >= 0.9
    assert _v(lignes[2].quantite) == "3"
    # aucune valeur dérivée n'atteint le seuil d'un écart certain
    assert all(lg.montant_ht.confiance < 0.9 for lg in lignes[1:])


# --- facture polonaise : récapitulatif sur une page séparée, prestation au kg (D-2501) ---------------------------


def pdf_pl() -> bytes:
    p1, p2 = fx.PagePdf(), fx.PagePdf()
    for p, n in ((p1, 1), (p2, 2)):
        p.t(40, 50, "Spedycja Urojona Sp. z o.o.", taille=12, gras=True)
        p.t(330, 50, "FAKTURA VAT Nr FU/00777/05/2026", gras=True)
        p.t(330, 64, f"Data wystawienia: 03.05.2026 — str. {n}")
    p1.t(40, 90, "Sprzedawca")
    p1.t(330, 90, "Nabywca")
    p1.t(40, 104, f"NIP/VAT: {TVA_EM}")
    p1.t(330, 104, "Ateliers Chimériques SAS")
    p1.t(330, 118, f"NIP/VAT: {TVA_CL}")
    p1.t(40, 140, f"MRN: {MRN_A}")
    p1.t(40, 154, "AWB / B/L / CMR: 999-27182818")
    p1.t(40, 180, "Naleznosci celne i podatkowe (refaktura, poza VAT)")
    cols = [(40, "Lp.", False), (60, "Nazwa", False), (200, "MRN", False), (360, "Ilosc J.m.", True), (450, "Cena jedn.", True),
            (540, "Wartosc netto", True)]
    p1.ligne(196, cols, taille=8)
    p1.ligne(212, [(40, "1", False), (60, "Clo", False), (200, MRN_A, False), (360, "1 szt.", True),
                   (450, "41,30", True), (540, "41,30", True)], taille=8)
    p1.t(40, 240, "Uslugi")
    p1.ligne(256, [c for c in cols if c[1] != "MRN"], taille=8)
    p1.ligne(272, [(40, "2", False), (60, "Odprawa celna", False), (360, "1 szt.", True), (450, "70,00", True),
                   (540, "70,00", True)], taille=8)
    p1.ligne(288, [(40, "3", False), (60, "Obsluga ladunku", False), (340, "2 450", True), (360, "kg", False),
                   (450, "0,12", True), (540, "294,00", True)], taille=8)
    p1.t(40, 320, "Kwoty w EUR. Podsumowanie na nastepnej stronie.")
    p2.t(200, 100, "PODSUMOWANIE / RÉCAPITULATIF", gras=True)
    for k, (lib, mt) in enumerate((("Razem naleznosci (refaktura)", "41,30 EUR"), ("Razem uslugi netto", "364,00 EUR"),
                                   ("Razem netto", "405,30 EUR"), ("VAT 20 % (Francja)", "72,80 EUR"),
                                   ("Razem brutto", "478,10 EUR"), ("Do zaplaty", "478,10 EUR"))):
        p2.ligne(140 + 18 * k, [(120, lib, False), (450, mt, True)])
    return fx.pdf([p1, p2])


@pytest.fixture(scope="module")
def pl():
    return _ft(pdf_pl()).champs


def test_pl_entete(pl):
    assert _v(pl.numero) == "FU/00777/05/2026"
    assert _v(pl.date) == "2026-05-03"
    assert _v(pl.client_facture.tva) == TVA_CL and pl.client_facture.tva.confiance >= 0.9
    assert _v(pl.emetteur.tva) == TVA_EM


def test_pl_totaux_page_recapitulative(pl):
    assert (_v(pl.total_debours), _v(pl.total_ht), _v(pl.total_tva), _v(pl.total_ttc), _v(pl.net_a_payer)) == (
        "41.30", "405.30", "72.80", "478.10", "478.10")


def test_pl_lignes_et_prestation_au_kg(pl):
    lignes = list(pl.lignes)
    assert [(lg.nature, _v(lg.montant_ht)) for lg in lignes] == [
        (NatureLigne.debours_droits, "41.30"), (NatureLigne.frais_dedouanement, "70.00"),
        (NatureLigne.manutention, "294.00")]
    kg = lignes[2]
    assert (_v(kg.quantite), _v(kg.prix_unitaire)) == ("2450", "0.12")
    assert kg.quantite.confiance >= 0.9


# --- relevé suisse : 1'234.50, avoir mêlé aux frais, MRN par ligne (D-2501, D-2505) -------------------------------


def pdf_ch() -> bytes:
    p = fx.PagePdf()
    p.t(40, 50, "Zollbüro Trugbild AG", taille=12, gras=True)
    p.t(40, 64, f"Filiale Mulhouse (F) | 1 rue du Rêve | 68100 Mulhouse | {TVA_EM}")
    p.t(330, 90, "KONTOAUSZUG / SAMMELRECHNUNG   Nr. ZT-26-000123", gras=True)
    p.t(330, 104, "Datum: 07.09.2026")
    p.t(40, 120, "Ateliers Chimériques SAS")
    p.t(40, 134, f"MWST-/USt-Nr.: {TVA_CL}")
    p.t(40, 156, f"MRN: {MRN_A}, {MRN_B}")
    y = 190
    p.ligne(y, [(40, "Sendung / MRN", False), (200, "Leistung", False), (430, "Menge", True),
                (540, "Soll / Haben", True)], taille=8)
    zeilen = [(MRN_A, "Verzollung", "75.00 EUR"), (MRN_A, "Zollabgaben", "1'234.50 EUR"),
              (MRN_B, "Verzollung", "75.00 EUR"), (MRN_B, "Einfuhrumsatzsteuer", "2'046.10 EUR"),
              ("—", "Gutschrift zu Rechnung ZT-26-000099", "-30.00 EUR")]
    for k, (m, lib, mt) in enumerate(zeilen):
        p.ligne(y + 16 * (k + 1), [(40, m, False), (200, lib, False), (430, "1", True), (540, mt, True)], taille=8)
    y += 16 * 7
    p.ligne(y, [(300, "Total Auslagen (Zoll/EUSt, MWST-frei)", False), (540, "3'280.60 EUR", True)])
    p.ligne(y + 14, [(300, "Total netto", False), (540, "3'400.60 EUR", True)])
    p.ligne(y + 28, [(300, "MWST Frankreich 20 %", False), (540, "24.00 EUR", True)])
    p.ligne(y + 42, [(300, "Total EUR", False), (540, "3'424.60 EUR", True)])
    return fx.pdf([p])


@pytest.fixture(scope="module")
def ch():
    return _ft(pdf_ch()).champs


def test_ch_releve_lignes_et_avoir(ch):
    assert ch.est_releve is True
    lignes = list(ch.lignes)
    assert [(_v(lg.mrn), lg.nature, _v(lg.montant_ht)) for lg in lignes] == [
        (MRN_A, NatureLigne.frais_dedouanement, "75.00"), (MRN_A, NatureLigne.debours_droits, "1234.50"),
        (MRN_B, NatureLigne.frais_dedouanement, "75.00"), (MRN_B, NatureLigne.debours_tva, "2046.10"),
        (None, NatureLigne.autre_prestation, "30.00")]
    assert lignes[-1].montant_ht.signe_imprime is SigneImprime.negatif


def test_ch_totaux_apostrophe(ch):
    assert (_v(ch.total_debours), _v(ch.total_ht), _v(ch.total_tva), _v(ch.total_ttc)) == (
        "3280.60", "3400.60", "24.00", "3424.60")
    # la somme signée des lignes recoupe le total HT imprimé
    somme = sum(lg.montant_ht.decimal_signe() for lg in ch.lignes)
    assert somme == Decimal("3400.60")


# --- facture française groupée par MRN, intertitres (D-2503) ; représentant fiscal (D-2504) -----------------------


def pdf_fr_sections() -> bytes:
    p = fx.PagePdf()
    p.t(40, 50, "Chimère Transit SAS", taille=12, gras=True)
    p.t(40, 64, f"12 quai du Songe, 76600 Le Havre — TVA {TVA_EM}")
    p.t(400, 50, "FACTURE CT-2026-0912", gras=True)
    p.t(400, 64, "Émise le 9 septembre 2026")
    p.t(330, 90, "Helvetia Onirica AG")
    p.t(330, 104, "Traumgasse 3, 8000 Zürich")
    p.t(330, 118, "Rep. fiscal : Mandataire Imaginaire SARL")
    p.t(330, 132, f"TVA rep. fiscal : {TVA_REP}")
    p.t(330, 146, f"N° TVA : {TVA_CL}")
    p.t(40, 118, f"MRN: {MRN_A}, {MRN_B}")
    cols = [(40, "Désignation", False), (300, "Qté", True), (380, "P.U. HT", True), (460, "Montant HT", True),
            (500, "TVA %", True), (560, "TTC", True)]
    y = 180
    for mrn, lignes in ((MRN_A, [("Frais de dédouanement", "60,00", "20,00", "72,00"),
                                 ("Droits de douane", "112,40", "0,00", "112,40")]),
                        (MRN_B, [("Frais de dédouanement", "60,00", "20,00", "72,00")])):
        p.t(40, y, f"Envoi — MRN {mrn}")
        p.ligne(y + 16, cols, taille=8)
        for k, (lib, ht, tx, ttc) in enumerate(lignes):
            p.ligne(y + 32 + 16 * k, [(40, lib, False), (300, "1", True), (380, ht, True), (460, ht, True),
                                      (500, tx, True), (560, ttc, True)], taille=8)
        y += 32 + 16 * len(lignes) + 30
    p.t(40, y, "Prestations communes au dossier")
    p.ligne(y + 16, cols, taille=8)
    p.ligne(y + 32, [(40, "Frais de dossier", False), (300, "1", True), (380, "20,00", True), (460, "20,00", True),
                     (500, "20,00", True), (560, "24,00", True)], taille=8)
    p.ligne(y + 70, [(380, "Total HT", False), (560, "252,40 €", True)])
    p.ligne(y + 84, [(380, "TVA 20 %", False), (560, "28,00 €", True)])
    p.ligne(y + 98, [(380, "Total TTC", False), (560, "280,40 €", True)])
    return fx.pdf([p])


@pytest.fixture(scope="module")
def fr_sections():
    return _ft(pdf_fr_sections()).champs


def test_fr_mrn_par_intertitre(fr_sections):
    lignes = list(fr_sections.lignes)
    assert [_v(lg.mrn) for lg in lignes] == [MRN_A, MRN_A, MRN_B, None]
    assert [_v(lg.montant_ttc) for lg in lignes] == ["72.00", "112.40", "72.00", "24.00"]
    assert _v(fr_sections.date) == "2026-09-09"


def test_fr_tva_du_client_et_non_du_representant_fiscal(fr_sections):
    assert _v(fr_sections.client_facture.tva) == TVA_CL


# --- date sans libellé à côté du numéro (D-2506) ------------------------------------------------------------------


def test_date_dans_le_segment_voisin_du_numero():
    p = fx.PagePdf()
    p.t(40, 50, "Mirage Freight Ltd", taille=12, gras=True)
    p.t(470, 50, "INVOICE", gras=True)
    p.t(380, 66, "No. MFL/26/0042")
    p.t(480, 66, "12 Jul 2026")
    p.t(330, 100, "Account")
    p.t(330, 114, "Ateliers Chimériques SAS")
    p.t(330, 128, f"VAT {TVA_CL}")
    p.ligne(170, [(40, "Description", False), (300, "Qty", True), (450, "Amount", True)], taille=8)
    p.ligne(186, [(40, "Customs clearance", False), (300, "1", True), (450, "85.00", True)], taille=8)
    p.ligne(220, [(300, "Total", False), (450, "85.00", True)])
    c = _ft(fx.pdf([p])).champs
    assert _v(c.date) == "2026-07-12"


# --- avoir portugais : facture d'origine citée (D-2501) --------------------------------------------------------------


def test_avoir_pt_facture_origine():
    p = fx.PagePdf()
    p.t(40, 50, "Agência Quimérica de Despachos Lda", taille=12, gras=True)
    p.t(430, 50, "NOTA DE CRÉDITO", gras=True)
    p.t(430, 66, "N.º NC 2026/0012")
    p.t(430, 80, "Data: 20-05-2026")
    p.t(40, 110, "Cliente")
    p.t(40, 124, "Ateliers Chimériques SAS")
    p.t(330, 124, "Fatura de origem: QD 2026/0451")
    p.ligne(170, [(40, "Descrição", False), (330, "Qtd", True), (450, "Taxa", True), (540, "Total c/ IVA", True)],
            taille=8)
    p.ligne(186, [(40, "Desalfandegamento", False), (330, "1", True), (450, "20%", True), (540, "-96,00 €", True)],
            taille=8)
    p.ligne(220, [(330, "Total com IVA", False), (540, "-96,00 €", True)])
    c = _ft(fx.pdf([p]), TypeDocument.avoir).champs
    assert [_v(r) for r in c.refs_facture_origine] == ["QD 2026/0451"]


# --- facture commerciale multipage : report de page jamais compté deux fois (D-2508, D-2509) ----------------------


def pdf_fc_multipage() -> bytes:
    cols = [(40, "#", False), (60, "Item code", False), (150, "Description", False), (300, "HS code", False),
            (360, "Origin", False), (420, "Qty", True), (430, "Unit", False), (500, "Unit price", True),
            (560, "Amount", True)]
    pages = []
    lignes = [(k, f"CH-{k:03d}", f"Dream widget {k}", "847130", "GB", "10", "pcs", "2.50", "25.00")
              for k in range(1, 25)]
    for n, bloc in enumerate((lignes[:12], lignes[12:]), start=1):
        p = fx.PagePdf()
        p.t(40, 40, "Phantom Gadgets Ltd", taille=12, gras=True)
        p.t(330, 40, "COMMERCIAL INVOICE" + (" (continued)" if n > 1 else ""), gras=True)
        p.t(330, 54, f"Invoice No. PGL-INV-31337 — 4 Jun 2026 — Page {n}/2")
        y = 90
        if n == 1:
            p.t(40, 80, "Bill to / Buyer")
            p.t(40, 94, "Ateliers Chimériques SAS")
            p.t(40, 108, f"VAT No.: {TVA_CL}")
            y = 140
        p.ligne(y, cols, taille=8)
        y += 16
        if n > 1:
            p.ligne(y, [(60, "Brought forward", False), (560, "300.00", True)], taille=8)
            y += 16
        for ln in bloc:
            p.ligne(y, [(x, str(t), d) for (x, _h, d), t in zip(cols, ln, strict=True)], taille=8)
            y += 16
        if n == 1:
            p.t(60, y + 10, "Page total 300.00 EUR — carried forward 300.00 EUR")
        else:
            p.ligne(y + 10, [(330, "INVOICE TOTAL EUR", False), (560, "600.00", True)])
            p.t(60, y + 30, "Delivery terms: FCA Dover (Incoterms® 2020)")
            p.t(60, y + 44, "Net weight: 48.000 kg Gross weight: 52.500 kg Packages: 6")
        pages.append(p)
    return fx.pdf(pages)


def test_fc_multipage_report_non_double_compte():
    c = _fc(pdf_fc_multipage())
    assert len(c.lignes) == 24
    assert sum(ln.montant_ligne.decimal() for ln in c.lignes) == Decimal("600.00")
    assert _v(c.total_facture) == "600.00"
    assert _v(c.date) == "2026-06-04"
    assert _v(c.nombre_colis) == "6"


# --- facture commerciale polonaise : contre-valeur indicative, représentant fiscal (D-2507, D-2504) -------------


def pdf_fc_pl() -> bytes:
    p = fx.PagePdf()
    p.t(40, 40, "FAKTURA EKSPORTOWA Faktura nr FE/0099/2026", taille=11, gras=True)
    p.t(40, 56, "Data wystawienia: 11.06.2026")
    p.t(40, 76, "Sprzedawca / Eksporter")
    p.t(40, 90, "Wyobraznia Handel Sp. z o.o.")
    p.t(40, 120, "Nabywca")
    p.t(40, 134, "Helvetia Onirica AG")
    p.t(40, 148, f"TVA rep. fiscal : {TVA_REP}")
    p.t(40, 162, f"NIP / VAT: {TVA_CL}")
    cols = [(40, "#", False), (55, "Indeks", False), (130, "Nazwa towaru", False), (300, "Kod CN", False),
            (350, "Pochodzenie", False), (420, "Ilosc", True), (428, "J.m.", False), (520, "Cena jedn. PLN", True),
            (585, "Wartosc PLN", True)]
    p.ligne(200, cols, taille=8)
    p.ligne(216, [(40, "1", False), (55, "WH-01", False), (130, "Dream lamp", False), (300, "94051100", False),
                  (350, "PL", False), (420, "20", True), (428, "szt.", False), (520, "12,50", True),
                  (585, "250,00", True)], taille=8)
    p.ligne(240, [(300, "Wartosc towarow", False), (570, "250,00 PLN", True)])
    p.ligne(254, [(300, "Fracht", False), (570, "30,00 PLN", True)])
    p.ligne(268, [(300, "RAZEM DO ZAPLATY", False), (570, "280,00 PLN", True)])
    p.t(40, 300, "Warunki dostawy: CPT Lyon (Incoterms® 2020)")
    p.t(40, 314, "Masa netto: 8,000 kg Masa brutto: 9,250 kg Liczba opakowan: 2")
    p.t(40, 328, "Rownowartosc informacyjna: 65,80 EUR (1 EUR = 4,2553 PLN), wylacznie informacyjnie")
    return fx.pdf([p])


def test_fc_pl():
    c = _fc(pdf_fc_pl())
    assert _v(c.numero) == "FE/0099/2026"
    assert _v(c.date) == "2026-06-11"
    assert _v(c.devise) == "PLN"
    assert _v(c.total_facture) == "280.00"
    assert _v(c.acheteur.tva) == TVA_CL
    assert (_v(c.masse_nette_totale), _v(c.masse_brute_totale), _v(c.nombre_colis)) == ("8.000", "9.250", "2")
    ln = c.lignes[0]
    assert (_v(ln.quantite), ln.quantite.unite, _v(ln.pays_origine), _v(ln.code_marchandise_imprime)) == (
        "20", "C62", "PL", "94051100")


# --- document support : numéro de facture à préfixe lettré (D-2510) ---------------------------------------------------


def test_support_ref_facture_prefixe_lettre():
    p = fx.PagePdf()
    p.t(40, 40, "Phantom Gadgets Ltd   PACKING LIST", gras=True)
    p.t(40, 56, "Ref. invoice / facture: FT PGL2026/0042 — 2026-06-04")
    p.t(40, 70, "Transport: 999-16180339")
    r = fx.extraire(fx.pdf([p]), TypeDocument.document_support, sous_type="liste_colisage")
    assert [_v(x) for x in r.champs.refs_facture] == ["FT PGL2026/0042"]


# --- numéro après un titre imprimé au milieu de l'en-tête (D-2511) ----------------------------------------------


def test_numero_apres_titre_dans_le_segment():
    p = fx.PagePdf()
    p.t(40, 40, "Spedycja Urojona Sp. z o.o. FAKTURA — USLUGI DODATKOWE Nr FU/00912/06/2026", gras=True)
    p.t(330, 60, "Data wystawienia: 21.06.2026")
    p.t(330, 90, "Nabywca")
    p.t(330, 104, "Ateliers Chimériques SAS")
    p.t(330, 118, f"NIP/VAT: {TVA_CL}")
    p.ligne(170, [(40, "Lp.", False), (60, "Nazwa", False), (360, "Ilosc", True), (450, "Cena jedn.", True),
                  (540, "Wartosc netto", True)], taille=8)
    p.ligne(186, [(40, "1", False), (60, "Odprawa celna", False), (360, "1", True), (450, "55,00", True),
                  (540, "55,00", True)], taille=8)
    p.ligne(220, [(300, "Razem netto", False), (540, "55,00 EUR", True)])
    c = _ft(fx.pdf([p])).champs
    assert _v(c.numero) == "FU/00912/06/2026"
    assert c.numero.confiance < 0.9  # valeur de position


# --- date de repli : seule date du haut de page, confiance plafonnée (D-2506) -------------------------------------


def test_date_de_repli_plafonnee():
    p = fx.PagePdf()
    p.t(40, 40, "Mirage Freight Ltd", taille=12, gras=True)
    p.t(400, 40, "INVOICE MFL-26-7781", gras=True)
    p.t(400, 70, "Lille, 30/06/2026")
    p.t(330, 100, "Bill to: Ateliers Chimériques SAS")
    p.ligne(170, [(40, "Description", False), (300, "Qty", True), (450, "Amount", True)], taille=8)
    p.ligne(186, [(40, "Customs clearance", False), (300, "1", True), (450, "85.00", True)], taille=8)
    p.ligne(220, [(300, "Total", False), (450, "85.00", True)])
    c = _ft(fx.pdf([p])).champs
    assert _v(c.date) == "2026-06-30"
    assert c.date.confiance < 0.9


# --- scans : pavé acheteur, natures courtes, variantes de MRN (D-2513 à D-2516) ----------------------------------


def _vue_ocr(lignes_txt: list[tuple[float, list[tuple[float, str]]]]):
    """Page OCR synthétique : (y, [(x0, mot)]) ; chaque mot fait 0,012 de large par caractère."""
    from controldone.extract.deterministe._mise_en_page import vue_document
    from controldone.ingest.texte import Ligne, Mot, PageText

    lignes = []
    for y, mots in lignes_txt:
        ms = tuple(Mot(t, x, y, x + 0.012 * len(t), y + 0.01, 0.95, None) for x, t in mots)
        lignes.append(Ligne(" ".join(m.texte for m in ms), ms))
    texte = "\n".join(li.texte for li in lignes)
    return vue_document([PageText(numero=1, texte=texte, lignes=lignes, source="ocr")])


def test_pave_ocr_ligne_decoupee_et_bruit():
    from controldone.extract.deterministe import facture_commerciale as fc
    from controldone.extract.deterministe._mise_en_page import chercher, pave

    vue = _vue_ocr([
        (0.150, [(0.06, "Nabywca"), (0.63, "7")]),
        (0.170, [(0.19, "SARL"), (0.62, "SARL")]),
        (0.171, [(0.06, "Onirique"), (0.52, "Onirique")]),
        (0.185, [(0.30, ":")]),
        (0.195, [(0.06, "12"), (0.10, "rue"), (0.14, "du"), (0.17, "Songe"), (0.52, "12 rue du Songe")]),
    ])
    t = chercher(vue, fc.LIB_ACHETEUR)[0]
    lignes = [" ".join(m.texte for m in ms) for _li, ms in pave(t, fin=fc.LIB_FIN_PAVE)]
    assert lignes == ["Onirique SARL", "12 rue du Songe"]


def test_libelle_acheteur_deforme_par_l_ocr():
    from controldone.extract.deterministe import facture_commerciale as fc

    vue = _vue_ocr([(0.05, [(0.06, "FACTURE")]), (0.15, [(0.06, "Facuré"), (0.14, "à"), (0.52, "Livré à")]),
                    (0.17, [(0.06, "Ateliers"), (0.17, "Chimériques")])])
    trouves = fc._libelles_acheteur_flous(vue)
    assert [t.segment.texte for t in trouves] == ["Facuré à"]  # ni le titre « FACTURE », ni « Livré à »
    assert fc._reste_de_libelle([type("M", (), {"texte": "] Buyer"})()])
    assert not fc._nom_plausible([type("M", (), {"texte": t})() for t in ("21", "boulevard", "du", "Rêve")])
    assert fc._nom_plausible([type("M", (), {"texte": t})() for t in ("3M", "Chimères", "SAS")])


def test_nature_mot_court_lu_par_l_ocr():
    assert nature_libelle("Cto", tolerant=True) is NatureLigne.debours_droits  # « Cło » : ł lu « t »
    assert nature_libelle("Cto") is None  # texte natif : aucune correction
    assert nature_libelle("Cte", tolerant=True) is None  # deux glyphes différents : non


def test_variantes_ocr_d_un_mrn_reunies():
    from controldone.extract.deterministe.facture_transitaire import _fusionner_variantes_ocr

    a, b, c = "26FRMOK30718F2R08K", "26FRMOK3OZ18F2RO8K", "26FRB2D4F6H8J0L2N4"
    groupes = {"26FRMOK3O7I8FZRO8K": [a], "26FRMOK3OZI8FZRO8K": [b], c: [c]}
    out = _fusionner_variantes_ocr(groupes, {a, b})
    assert sorted(sorted(v) for v in out.values()) == sorted([sorted([a, b]), [c]])
    # lecture native de part et d'autre : deux MRN distincts restent distincts
    assert len(_fusionner_variantes_ocr(groupes, set())) == 3
