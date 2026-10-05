"""Généralisation de l'extracteur des factures de transitaire (D-1901 à D-1906).

Mises en page **propres à ces tests** (ni celles du banc, ni celles de la démonstration), rendues par reportlab :
factures allemande, italienne, espagnole, néerlandaise et anglaise ; totaux en tête de page ; tableau sur deux
pages avec report ; annexe de débours ; deux tableaux côte à côte ; tampon et annotation manuscrite superposés.
Sociétés, numéros et adresses **fictifs**.
"""

from __future__ import annotations

import io
from decimal import Decimal

import pytest
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

from controldone.extract.base import ExtractionContext
from controldone.extract.deterministe import _ft_langues as langues
from controldone.extract.deterministe._ft_nettoyage import retirer_surimpressions
from controldone.extract.deterministe.avoir import ExtracteurAvoir
from controldone.extract.deterministe.facture_transitaire import ExtracteurFactureTransitaire
from controldone.ids import IdGenerator
from controldone.ingest.pages import OptionsPages, extraire_pages
from controldone.ingest.texte import Ligne, Mot, PageText
from controldone.model.documents import Document, PageRef
from controldone.model.enums import NatureLigne, SigneImprime, TypeDocument
from controldone.normalize import parse_date
from controldone.normalize.fiscal import tva_fr_depuis_siren
from controldone.normalize.natures import nature_libelle

L, H = A4
TVA_TR = tva_fr_depuis_siren("000424242")
TVA_CL = tva_fr_depuis_siren("000535353")
MRN_A = "26FRQ4W7E2R9T1Y3U5"
MRN_B = "26FRZ8X6C4V2B0N7M1"


def _pdf(pages: list[list[tuple]], dessins=None) -> bytes:
    """Éléments ``(x, y, texte[, taille[, "g"|"d"|"c"[, gras]]])`` en fractions de page (origine en haut à
    gauche) ; ``dessins[k](canvas)`` dessine en plus sur la page ``k`` (tampons, annotations)."""
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4, invariant=1)
    for k, elements in enumerate(pages):
        for el in elements:
            x, y, texte = el[:3]
            taille = el[3] if len(el) > 3 else 8
            align = el[4] if len(el) > 4 else "g"
            c.setFont("Helvetica-Bold" if len(el) > 5 and el[5] else "Helvetica", taille)
            if align == "d":
                c.drawRightString(x * L, (1 - y) * H, texte)
            elif align == "c":
                c.drawCentredString(x * L, (1 - y) * H, texte)
            else:
                c.drawString(x * L, (1 - y) * H, texte)
        if dessins and k in dessins:
            dessins[k](c)
        c.showPage()
    c.save()
    return buf.getvalue()


def _extraire(contenu: bytes, type_doc: TypeDocument = TypeDocument.facture_transitaire, *, avoir_moteur=False):
    extraites = extraire_pages(contenu, options=OptionsPages(ocr=False, isoler=False))
    pages = [pe.page for pe in extraites]
    doc = Document(type=type_doc, pages=[PageRef(fichier_id=p.fichier_id, numero=p.numero,
                                                  qualite_texte=p.qualite_texte) for p in pages])
    ctx = ExtractionContext(ids=IdGenerator.deterministe(11),
                            options={"textes_pages": {pe.page.numero: pe.texte for pe in extraites}})
    ex = ExtracteurAvoir() if avoir_moteur else ExtracteurFactureTransitaire()
    res = ex.extract(doc, pages, ctx)
    assert res.champs is not None
    return res.champs


def _v(x):
    return None if x is None else x.valeur


def _lignes(c) -> list[tuple]:
    return [(lg.nature, _v(lg.montant_ht)) for lg in c.lignes]


def _ligne_tableau(y: float, cellules: list[tuple[float, str, str]], taille: float = 8) -> list[tuple]:
    return [(x, y, t, taille, al) for x, t, al in cellules]


# --- vocabulaire ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize(("libelle", "nature"), [
    ("Zollabgaben", NatureLigne.debours_droits),
    ("Einfuhrumsatzsteuer", NatureLigne.debours_tva),
    ("Verzollung", NatureLigne.frais_dedouanement),
    ("Vorlageprovision", NatureLigne.frais_avance_fonds),
    ("Lagergeld", NatureLigne.magasinage),
    ("Dazi doganali", NatureLigne.debours_droits),
    ("IVA all'importazione", NatureLigne.debours_tva),
    ("Spese di sdoganamento", NatureLigne.frais_dedouanement),
    ("Commissione anticipo diritti", NatureLigne.frais_avance_fonds),
    ("Aranceles", NatureLigne.debours_droits),
    ("Comisión por anticipo", NatureLigne.frais_avance_fonds),
    ("Partidas adicionales", NatureLigne.frais_ligne_supplementaire),
    ("Invoerrechten", NatureLigne.debours_droits),
    ("Btw bij invoer", NatureLigne.debours_tva),
    ("Inklaring", NatureLigne.frais_dedouanement),
    ("Voorschotprovisie", NatureLigne.frais_avance_fonds),
    ("Additional entry lines", NatureLigne.frais_ligne_supplementaire),
    ("Forfait dédouanement", NatureLigne.frais_dedouanement),
])
def test_natures_multilingues(libelle, nature):
    assert nature_libelle(libelle) is nature


@pytest.mark.parametrize(("texte", "iso"), [
    ("5. März 2026", "2026-03-05"), ("3 marzo 2026", "2026-03-03"), ("12 maart 2026", "2026-03-12"),
    ("1 dicembre 2026", "2026-12-01"), ("15 Oktober 2026", "2026-10-15"), ("26 de junio de 2026", "2026-06-26"),
])
def test_dates_multilingues(texte, iso):
    assert str(parse_date(texte)) == iso


def test_total_tva_import_n_est_pas_la_tva_de_la_facture():
    motif = dict(langues.TOTAUX)["total_tva"]
    assert motif.match("iva 20 %") and motif.match("mwst. 20 %") and motif.match("btw 20%")
    assert not motif.match("iva de importacion") and not motif.match("tva a l'importation")


# --- surimpressions --------------------------------------------------------------------------------------------


def _mot(t, x0, y0, x1, y1):
    return Mot(t, x0, y0, x1, y1, None, None)


def test_retirer_surimpressions_glyphes_et_manuscrit():
    lignes = [Ligne("Texte", (_mot("Texte", 0.1, 0.1 + i * 0.02, 0.2, 0.11 + i * 0.02),)) for i in range(25)]
    total = (_mot("Total", 0.6, 0.6, 0.65, 0.61), _mot("HT", 0.66, 0.6, 0.68, 0.61),
             _mot("É", 0.75, 0.57, 0.79, 0.63),  # glyphe de tampon (6 fois la hauteur du texte)
             _mot("1", 0.8, 0.6, 0.805, 0.61), _mot("637,25", 0.807, 0.6, 0.85, 0.61))
    manuscrit = tuple(_mot(ch, 0.3 + 0.01 * k, 0.7, 0.312 + 0.01 * k, 0.715) for k, ch in enumerate("Visa962"))
    legende = tuple(_mot(t, x, 0.8, x + 0.006, 0.81) for t, x in (("%", 0.1), (";", 0.11), ("E", 0.12), ("=", 0.13)))
    pt = PageText(numero=1, texte="", lignes=[*lignes, Ligne("", total), Ligne("", manuscrit), Ligne("", legende)],
                  source="natif")
    out = retirer_surimpressions(pt)
    textes = [" ".join(m.texte for m in li.mots) for li in out.lignes]
    assert "Total HT 1 637,25" in textes  # le glyphe est retiré, le « 1 » des milliers reste
    assert not any("V" in t and "962" in t.replace(" ", "") for t in textes)
    assert "% ; E =" in textes  # signes espacés d'une légende : gardés
    assert retirer_surimpressions(PageText(numero=1, texte="", lignes=lignes, source="ocr")).lignes == lignes


# --- factures multilingues --------------------------------------------------------------------------------------


def _facture_allemande(*, stempel: bool = False) -> bytes:
    el = [
        (0.06, 0.04, "Fiktiv Spedition GmbH (FICTIF)", 14, "g", True),
        (0.06, 0.085, "Rechnungsempfänger:", 8), (0.52, 0.085, "RECHNUNG", 12, "g", True),
        (0.06, 0.102, "Phantom Import SAS (FICTIF)", 8), (0.52, 0.102, "Nr. FS 2026-7781", 9),
        (0.06, 0.117, "3 rue Imaginaire", 8), (0.52, 0.117, "Datum: 5. März 2026", 8),
        (0.06, 0.132, "75999 Paris", 8), (0.52, 0.132, "Absender: Fiktiv Spedition GmbH", 8),
        (0.06, 0.161, f"USt-IdNr. {TVA_CL}", 8), (0.52, 0.161, f"USt-IdNr. {TVA_TR}", 8),
        (0.06, 0.19, f"MRN: {MRN_A}", 8), (0.06, 0.204, "AWB / B/L: 999-12345675", 8),
        (0.07, 0.24, "Pos.", 8, "g", True), (0.12, 0.24, "Leistung", 8, "g", True),
        (0.62, 0.24, "Menge", 8, "g", True), (0.71, 0.24, "Einzelpreis", 8, "g", True),
        (0.93, 0.24, "Betrag", 8, "d", True),
    ]
    rangees = [("1", "Zollabgaben", "1", "312,40 EUR", "312,40 EUR"),
               ("2", "Einfuhrumsatzsteuer", "1", "1.204,10 EUR", "1.204,10 EUR"),
               ("3", "Verzollung", "1", "80,00 EUR", "80,00 EUR"),
               ("4", "Vorlageprovision", "1", "30,33 EUR", "30,33 EUR")]
    for k, (pos, lib, q, pu, mt) in enumerate(rangees):
        y = 0.258 + k * 0.017
        el += _ligne_tableau(y, [(0.08, pos, "g"), (0.12, lib, "g"), (0.66, q, "d"), (0.79, pu, "d"),
                                 (0.93, mt, "d")])
    el += [(0.75, 0.34, "Summe Auslagen", 8, "d"), (0.94, 0.34, "1.516,50 EUR", 8, "d"),
           (0.75, 0.356, "Nettobetrag gesamt", 8, "d"), (0.94, 0.356, "1.626,83 EUR", 8, "d"),
           (0.75, 0.372, "MwSt. 20 %", 8, "d"), (0.94, 0.372, "22,07 EUR", 8, "d"),
           (0.75, 0.388, "Rechnungsbetrag", 8, "d", True), (0.94, 0.388, "1.648,90 EUR", 8, "d", True)]

    def tampon(c):
        # tampon « BEZAHLT » en grandes lettres inclinées sur le bloc des totaux, une lettre par mot
        c.setFont("Helvetica-Bold", 26)
        for k, ch in enumerate("BEZAHLT"):
            c.saveState()
            c.translate((0.56 + 0.045 * k) * L, (1 - 0.40 + 0.012 * k) * H)
            c.rotate(18)
            c.drawString(0, 0, ch)
            c.restoreState()
        # annotation manuscrite : glyphes isolés qui se chevauchent
        c.setFont("Helvetica-Oblique", 13)
        for k, ch in enumerate("Visa 962"):
            if ch != " ":
                c.drawString((0.1 + 0.0145 * k) * L, (1 - 0.82 - 0.002 * (k % 2)) * H, ch)

    return _pdf([el], {0: tampon} if stempel else None)


@pytest.mark.parametrize("stempel", [False, True])
def test_facture_allemande(stempel):
    c = _extraire(_facture_allemande(stempel=stempel))
    assert _v(c.numero) == "FS 2026-7781" and _v(c.date) == "2026-03-05"
    assert _v(c.client_facture.tva) == TVA_CL and _v(c.emetteur.tva) == TVA_TR
    assert [_v(x) for x in c.refs_transport] == ["999-12345675"] and [_v(x) for x in c.refs_mrn] == [MRN_A]
    assert _lignes(c) == [(NatureLigne.debours_droits, "312.40"), (NatureLigne.debours_tva, "1204.10"),
                          (NatureLigne.frais_dedouanement, "80.00"), (NatureLigne.frais_avance_fonds, "30.33")]
    assert _v(c.lignes[0].libelle) == "Zollabgaben"  # le n° de position n'est pas le libellé
    assert (_v(c.total_debours), _v(c.total_ht), _v(c.total_tva), _v(c.total_ttc)) == \
        ("1516.50", "1626.83", "22.07", "1648.90")
    assert c.total_ttc.confiance >= 0.9


def test_facture_italienne_totaux_en_tete_et_colonne_mrn():
    el = [
        (0.06, 0.04, "Spedizioni Fittizie Srl (FICTIF)", 14, "g", True), (0.94, 0.04, "FATTURA", 12, "d", True),
        (0.94, 0.062, "N. 812/2026/FI del 3 marzo 2026", 8, "d"),
        (0.06, 0.099, f"Partita IVA {TVA_TR}", 8),
        (0.06, 0.13, "Cliente", 8, "g", True),
        (0.06, 0.143, "Ottica Immaginaria SARL", 8), (0.58, 0.143, "Totale documento", 8), (0.93, 0.143, "€ 205,40", 8, "d"),
        (0.06, 0.157, "1 via Inventata", 8),
        (0.58, 0.163, "di cui anticipazioni", 8), (0.93, 0.163, "€ 100,00", 8, "d"),
        (0.06, 0.169, "69999 Lione", 8),
        (0.58, 0.179, "Totale imponibile + anticipazioni", 8), (0.93, 0.179, "€ 189,00", 8, "d"),
        (0.06, 0.194, f"Partita IVA {TVA_CL}", 8), (0.58, 0.194, "IVA 20%", 8), (0.93, 0.194, "€ 16,40", 8, "d"),
        (0.06, 0.24, f"MRN: {MRN_A}", 8),
        (0.07, 0.28, "Descrizione", 8, "g", True), (0.32, 0.28, "MRN", 8, "g", True),
        (0.52, 0.28, "Q.tà", 8, "g", True), (0.61, 0.28, "Prezzo", 8, "g", True),
        (0.72, 0.28, "Importo", 8, "g", True), (0.79, 0.28, "Cod. IVA", 8, "g", True),
        (0.93, 0.28, "IVA", 8, "d", True),
    ]
    rangees = [("Dazi doganali", MRN_A, "100,00", "E15", "€ 0,00"),
               ("Spese di sdoganamento", MRN_A, "65,00", "20%", "€ 13,00"),
               ("Spese di pratica", "", "17,00", "20%", "€ 3,40")]
    for k, (lib, mrn, mt, code, tva) in enumerate(rangees):
        y = 0.298 + k * 0.017
        el += _ligne_tableau(y, [(0.07, lib, "g"), (0.32, mrn, "g"), (0.55, "1", "d"), (0.65, f"€ {mt}", "d"),
                                 (0.76, f"€ {mt}", "d"), (0.82, code, "d"), (0.93, tva, "d")])
    c = _extraire(_pdf([el]))
    assert _v(c.numero) == "812/2026/FI" and _v(c.date) == "2026-03-03"
    assert (_v(c.total_debours), _v(c.total_ht), _v(c.total_tva), _v(c.total_ttc)) == \
        ("100.00", "189.00", "16.40", "205.40")
    assert _lignes(c) == [(NatureLigne.debours_droits, "100.00"), (NatureLigne.frais_dedouanement, "65.00"),
                          (NatureLigne.autre_prestation, "17.00")]
    # colonne réservée au MRN : la ligne sans MRN imprimé n'en reçoit pas
    assert [_v(lg.mrn) for lg in c.lignes] == [MRN_A, MRN_A, None]


def test_facture_espagnole_annexe_de_suplidos():
    p1 = [
        (0.08, 0.05, "Tránsitos Inventados SL (FICTIF)", 14, "g", True),
        (0.08, 0.07, f"NIF-IVA {TVA_TR}", 8),
        (0.07, 0.115, "FACTURA", 12, "g", True), (0.5, 0.115, "Cervecería Quimera SA", 8),
        (0.07, 0.131, "N.º FI26-0042", 8), (0.5, 0.131, f"NIF-IVA: {TVA_CL}", 8),
        (0.07, 0.148, "Fecha: 26 de junio de 2026", 8),
        (0.06, 0.196, f"MRN / DUA: {MRN_A}", 8),
        (0.07, 0.24, "Concepto", 8, "g", True), (0.48, 0.24, "Cant.", 8, "g", True),
        (0.59, 0.24, "Precio", 8, "g", True), (0.70, 0.24, "Importe", 8, "g", True),
        (0.78, 0.24, "IVA %", 8, "g", True), (0.87, 0.24, "Cuota IVA", 8, "g", True),
    ]
    p1 += _ligne_tableau(0.258, [(0.07, "Despacho de aduanas", "g"), (0.51, "1", "d"), (0.63, "90,00 €", "d"),
                                 (0.75, "90,00 €", "d"), (0.82, "20,00", "d"), (0.93, "18,00 €", "d")])
    p1 += _ligne_tableau(0.275, [(0.07, "Suplidos según anexo (página 2)", "g"), (0.75, "1.500,00 €", "d")])
    p1 += [(0.75, 0.30, "Base imponible", 8, "d"), (0.94, 0.30, "90,00 €", 8, "d"),
           (0.75, 0.316, "IVA 20 %", 8, "d"), (0.94, 0.316, "18,00 €", 8, "d"),
           (0.75, 0.332, "Total suplidos", 8, "d"), (0.94, 0.332, "1.500,00 €", 8, "d"),
           (0.75, 0.348, "Total sin IVA (servicios + suplidos)", 8, "d"), (0.94, 0.348, "1.590,00 €", 8, "d"),
           (0.75, 0.364, "TOTAL FACTURA", 8, "d", True), (0.94, 0.364, "1.608,00 €", 8, "d", True)]
    p2 = [(0.06, 0.05, "ANEXO — Relación de suplidos · FACTURA FI26-0042", 11, "g", True),
          (0.07, 0.09, "Concepto", 8, "g", True), (0.47, 0.09, "DUA / MRN", 8, "g", True),
          (0.86, 0.09, "Importe", 8, "d", True)]
    p2 += _ligne_tableau(0.108, [(0.07, "Aranceles", "g"), (0.47, MRN_A, "g"), (0.86, "250,00 €", "d")])
    p2 += _ligne_tableau(0.125, [(0.07, "IVA de importación", "g"), (0.47, MRN_A, "g"), (0.86, "1.250,00 €", "d")])
    p2 += [(0.86, 0.147, "Total suplidos: 1.500,00 €", 8, "d")]
    c = _extraire(_pdf([p1, p2]))
    assert _v(c.numero) == "FI26-0042" and _v(c.date) == "2026-06-26"
    # la ligne de renvoi à l'annexe n'est pas une ligne de plus : le détail de l'annexe la remplace
    assert _lignes(c) == [(NatureLigne.frais_dedouanement, "90.00"), (NatureLigne.debours_droits, "250.00"),
                          (NatureLigne.debours_tva, "1250.00")]
    assert (_v(c.total_debours), _v(c.total_ht), _v(c.total_tva), _v(c.total_ttc)) == \
        ("1500.00", "1590.00", "18.00", "1608.00")


def test_facture_neerlandaise_entete_en_colonnes_et_remise():
    el = [
        (0.12, 0.05, "Spook Expeditie B.V. (FICTIF)", 14, "g", True),
        (0.06, 0.095, "FACTUUR", 13, "g", True),
        (0.06, 0.131, "Nr.", 8, "g", True), (0.35, 0.131, "Datum", 8, "g", True), (0.63, 0.131, "Btw-nr.", 8, "g", True),
        (0.06, 0.145, "SP-2026-5521", 8), (0.35, 0.145, "12 maart 2026", 8), (0.63, 0.145, TVA_TR, 8),
        (0.06, 0.175, "Klant", 8, "g", True), (0.06, 0.188, "Utopia Gereedschap SARL", 8),
        (0.50, 0.188, f"MRN: {MRN_B}", 8), (0.50, 0.2, "AWB / B/L: CMR-FX-778899", 8),
        (0.06, 0.238, f"Btw-nr. {TVA_CL}", 8),
        (0.07, 0.28, "Omschrijving", 8, "g", True), (0.62, 0.28, "Aantal", 8, "g", True),
        (0.93, 0.28, "Bedrag", 8, "d", True),
    ]
    rangees = [("Invoerrechten", "1", "€ 210,00"), ("Inklaring", "1", "€ 75,00"), ("Korting", "1", "€ -10,00")]
    for k, (lib, q, mt) in enumerate(rangees):
        el += _ligne_tableau(0.298 + k * 0.017, [(0.07, lib, "g"), (0.66, q, "d"), (0.93, mt, "d")])
    el += [(0.75, 0.36, "Totaal voorschotten", 8, "d"), (0.94, 0.36, "€ 210,00", 8, "d"),
           (0.75, 0.376, "Totaal excl. btw", 8, "d"), (0.94, 0.376, "€ 275,00", 8, "d"),
           (0.75, 0.392, "Btw 20%", 8, "d"), (0.94, 0.392, "€ 13,00", 8, "d"),
           (0.75, 0.408, "Totaal incl. btw", 8, "d"), (0.94, 0.408, "€ 288,00", 8, "d")]
    c = _extraire(_pdf([el]))
    assert _v(c.numero) == "SP-2026-5521" and _v(c.date) == "2026-03-12"
    assert [_v(x) for x in c.refs_transport] == ["CMR-FX-778899"]
    assert _lignes(c) == [(NatureLigne.debours_droits, "210.00"), (NatureLigne.frais_dedouanement, "75.00"),
                          (NatureLigne.autre_prestation, "10.00")]
    assert c.lignes[2].montant_ht.signe_imprime is SigneImprime.negatif  # remise : montant négatif imprimé
    assert (_v(c.total_debours), _v(c.total_ht), _v(c.total_tva), _v(c.total_ttc)) == \
        ("210.00", "275.00", "13.00", "288.00")


def test_releve_sur_deux_pages_avec_report():
    entete = [(0.07, 0.1, "MRN", 8, "g", True), (0.27, 0.1, "Description", 8, "g", True),
              (0.70, 0.1, "Qty", 8, "g", True), (0.93, 0.1, "Net amount", 8, "d", True)]
    p1 = [(0.06, 0.04, "PHANTOM FORWARDING LTD (FICTIF)", 13, "g", True), (0.94, 0.04, "INVOICE", 12, "d", True),
          (0.94, 0.06, "No. PH/26/0099 — 4 May 2026", 8, "d"), (0.06, 0.075, f"VAT {TVA_TR}", 8)]
    p1 += [(x, y + 0.2, t, s, a, g) for x, y, t, s, a, g in entete]
    lignes = [(MRN_A, "Customs duty", "100.00"), (MRN_A, "Import VAT", "400.00"), (MRN_A, "Customs clearance", "50.00"),
              (MRN_B, "Customs duty", "20.00"), (MRN_B, "Import VAT", "80.00"), (MRN_B, "Customs clearance", "50.00")]
    for k, (mrn, lib, mt) in enumerate(lignes[:4]):
        p1 += _ligne_tableau(0.32 + k * 0.025, [(0.07, mrn, "g"), (0.27, lib, "g"), (0.71, "1", "d"),
                                                (0.93, f"EUR {mt}", "d")])
    p1 += [(0.93, 0.45, "Carried forward EUR 570.00", 8, "d")]
    p2 = [(0.06, 0.04, "PHANTOM FORWARDING LTD (FICTIF)", 13, "g", True), (0.94, 0.04, "INVOICE", 12, "d", True),
          (0.94, 0.06, "No. PH/26/0099 — 4 May 2026", 8, "d"), *entete,
          (0.93, 0.125, "Brought forward EUR 570.00", 8, "d")]
    for k, (mrn, lib, mt) in enumerate(lignes[4:]):
        p2 += _ligne_tableau(0.15 + k * 0.025, [(0.07, mrn, "g"), (0.27, lib, "g"), (0.71, "1", "d"),
                                                (0.93, f"EUR {mt}", "d")])
    p2 += [(0.75, 0.22, "Total disbursements", 8, "d"), (0.94, 0.22, "EUR 600.00", 8, "d"),
           (0.75, 0.236, "Total net", 8, "d"), (0.94, 0.236, "EUR 700.00", 8, "d"),
           (0.75, 0.252, "VAT", 8, "d"), (0.94, 0.252, "EUR 20.00", 8, "d"),
           (0.75, 0.268, "Total incl. VAT", 8, "d"), (0.94, 0.268, "EUR 720.00", 8, "d")]
    c = _extraire(_pdf([p1, p2]))
    assert _v(c.numero) == "PH/26/0099" and _v(c.date) == "2026-05-04"
    assert [m for _, m in _lignes(c)] == ["100.00", "400.00", "50.00", "20.00", "80.00", "50.00"]
    assert [_v(lg.mrn) for lg in c.lignes] == [MRN_A] * 3 + [MRN_B] * 3
    assert (_v(c.total_debours), _v(c.total_ht), _v(c.total_ttc)) == ("600.00", "700.00", "720.00")


def test_deux_tableaux_cote_a_cote_et_mrn_en_ligne_de_suite():
    el = [(0.06, 0.04, "Chimera Brokers Ltd (FICTIF)", 14, "g", True), (0.94, 0.04, "INVOICE", 12, "d", True),
          (0.94, 0.084, "No. CB-INV-5512", 8, "d"), (0.94, 0.097, "Date 5 May 2026", 8, "d"),
          (0.06, 0.12, f"VAT {TVA_TR}", 8), (0.06, 0.145, "Invoice to", 8, "g", True),
          (0.06, 0.157, "Imaginor Distribution SAS", 8), (0.06, 0.208, f"VAT {TVA_CL}", 8),
          (0.06, 0.239, "Disbursements paid on your behalf", 8, "g", True),
          (0.51, 0.239, "Our charges (VAT 20%)", 8, "g", True),
          (0.07, 0.255, "Item", 8, "g", True), (0.35, 0.255, "Qty", 8, "d", True), (0.48, 0.255, "Amount", 8, "d", True),
          (0.52, 0.255, "Item", 8, "g", True), (0.80, 0.255, "Qty", 8, "d", True), (0.93, 0.255, "Amount", 8, "d", True)]
    el += _ligne_tableau(0.271, [(0.07, "Customs duty", "g"), (0.35, "1", "d"), (0.48, "300.00 EUR", "d"),
                                 (0.52, "Customs clearance", "g"), (0.80, "1", "d"), (0.93, "60.00 EUR", "d")])
    el += _ligne_tableau(0.282, [(0.07, f"[{MRN_A}]", "g"), (0.52, f"[{MRN_A}]", "g")], taille=7)
    el += _ligne_tableau(0.297, [(0.07, "Import VAT", "g"), (0.35, "1", "d"), (0.48, "1,200.00 EUR", "d"),
                                 (0.52, "Disbursement fee", "g"), (0.80, "1", "d"), (0.93, "40.00 EUR", "d")])
    el += _ligne_tableau(0.308, [(0.07, f"[{MRN_A}]", "g"), (0.52, f"[{MRN_A}]", "g")], taille=7)
    el += [(0.75, 0.34, "Total disbursements", 8, "d"), (0.94, 0.34, "1,500.00 EUR", 8, "d"),
           (0.75, 0.356, "Total charges (net)", 8, "d"), (0.94, 0.356, "100.00 EUR", 8, "d"),
           (0.75, 0.372, "Total net", 8, "d"), (0.94, 0.372, "1,600.00 EUR", 8, "d"),
           (0.75, 0.388, "VAT @ 20% on charges", 8, "d"), (0.94, 0.388, "20.00 EUR", 8, "d"),
           (0.75, 0.404, "Total incl. VAT", 8, "d"), (0.94, 0.404, "1,620.00 EUR", 8, "d")]
    c = _extraire(_pdf([el]))
    assert sorted(_lignes(c), key=lambda x: x[1]) == sorted(
        [(NatureLigne.debours_droits, "300.00"), (NatureLigne.debours_tva, "1200.00"),
         (NatureLigne.frais_dedouanement, "60.00"), (NatureLigne.frais_avance_fonds, "40.00")], key=lambda x: x[1])
    assert all(_v(lg.mrn) == MRN_A and lg.mrn.confiance >= 0.9 for lg in c.lignes)
    assert (_v(c.total_debours), _v(c.total_ht), _v(c.total_tva), _v(c.total_ttc)) == \
        ("1500.00", "1600.00", "20.00", "1620.00")
    assert _v(c.date) == "2026-05-05" and _v(c.numero) == "CB-INV-5512"


def test_paysage_intertitres_colonne_ttc_et_pu_ht():
    from reportlab.lib.pagesizes import landscape

    lw, lh = landscape(A4)
    buf = io.BytesIO()
    cv = canvas.Canvas(buf, pagesize=(lw, lh), invariant=1)

    def t(x, y, s, size=8, al="g"):
        cv.setFont("Helvetica", size)
        (cv.drawRightString if al == "d" else cv.drawString)(x * lw, (1 - y) * lh, s)

    t(0.10, 0.06, "Transit Imaginaire SAS (FICTIF)", 14)
    t(0.96, 0.06, "FACTURE N° TI-2026-0007", 12, "d")
    t(0.10, 0.09, f"Quai fictif — 76999 Le Havre — TVA {TVA_TR}")
    t(0.96, 0.09, "du 14/04/2026", 8, "d")
    t(0.04, 0.15, f"MRN: {MRN_A}")
    t(0.04, 0.165, "LTA / B/L / CMR: FICU1234567")
    t(0.65, 0.16, "Société Fictive SARL")
    t(0.65, 0.23, f"TVA intracom. : {TVA_CL}")
    for x, s, al in [(0.05, "Désignation", "g"), (0.34, "Réf. MRN", "g"), (0.56, "Qté", "d"), (0.64, "P.U. HT", "d"),
                     (0.74, "Montant HT", "d"), (0.79, "TVA %", "d"), (0.88, "Montant TVA", "d"),
                     (0.95, "Montant TTC", "d")]:
        t(x, 0.29, s, 8, al)
    t(0.05, 0.314, "DÉBOURS (HORS CHAMP DE TVA)")
    rows = [(0.338, "Droits de douane", MRN_A, "257,01 €", "0,00", "0,00 €", "257,01 €"),
            (0.385, "Frais de dédouanement", MRN_A, "95,00 €", "20,00", "19,00 €", "114,00 €"),
            (0.409, "Manutention", "", "40,00 €", "20,00", "8,00 €", "48,00 €")]
    t(0.05, 0.362, "PRESTATIONS")
    for y, lib, mrn, mt, tx, tva, ttc in rows:
        t(0.05, y, lib)
        t(0.34, y, mrn)
        t(0.56, y, "1", 8, "d")
        t(0.64, y, mt, 8, "d")
        t(0.74, y, mt, 8, "d")
        t(0.79, y, tx, 8, "d")
        t(0.88, y, tva, 8, "d")
        t(0.95, y, ttc, 8, "d")
    for k, (lib, mt) in enumerate([("Total débours", "257,01 €"), ("Total HT", "392,01 €"), ("TVA 20 %", "27,00 €"),
                                   ("Total TTC", "419,01 €")]):
        t(0.81, 0.44 + 0.022 * k, lib, 8, "d")
        t(0.95, 0.44 + 0.022 * k, mt, 8, "d")
    cv.showPage()
    cv.save()
    c = _extraire(buf.getvalue())
    assert _lignes(c) == [(NatureLigne.debours_droits, "257.01"), (NatureLigne.frais_dedouanement, "95.00"),
                          (NatureLigne.manutention, "40.00")]
    assert [_v(lg.prix_unitaire) for lg in c.lignes] == ["257.01", "95.00", "40.00"]
    assert [_v(lg.montant_tva) for lg in c.lignes] == ["0.00", "19.00", "8.00"]
    assert [_v(x) for x in c.refs_transport] == ["FICU1234567"]
    assert _v(c.date) == "2026-04-14" and _v(c.total_ht) == "392.01"


# --- avoirs ------------------------------------------------------------------------------------------------------


def test_gutschrift_allemande_et_routage_avoir_transitaire():
    el = [
        (0.06, 0.04, "Fiktiv Spedition GmbH (FICTIF)", 14, "g", True),
        (0.52, 0.085, "GUTSCHRIFT", 12, "g", True), (0.52, 0.102, "Nr. GS 2026-0311", 9),
        (0.52, 0.117, "Datum: 26.09.2026", 8), (0.06, 0.161, f"USt-IdNr. {TVA_CL}", 8),
        (0.52, 0.161, f"USt-IdNr. {TVA_TR}", 8), (0.06, 0.19, f"MRN: {MRN_B}", 8),
        (0.06, 0.204, "Ursprungsrechnung: FS 2026-7781", 8), (0.06, 0.218, "Grund: Tarifkorrektur", 8),
        (0.07, 0.26, "Bezeichnung", 8, "g", True), (0.62, 0.26, "Menge", 8, "g", True),
        (0.71, 0.26, "Einzelpreis", 8, "g", True), (0.93, 0.26, "Betrag", 8, "d", True),
    ]
    el += _ligne_tableau(0.278, [(0.07, "Verzollung", "g"), (0.66, "1", "d"), (0.79, "15,00 EUR", "d"),
                                 (0.93, "-15,00 EUR", "d")])
    el += [(0.75, 0.30, "Nettobetrag gesamt", 8, "d"), (0.94, 0.30, "-15,00 EUR", 8, "d"),
           (0.75, 0.316, "MwSt. 20 %", 8, "d"), (0.94, 0.316, "-3,00 EUR", 8, "d"),
           (0.75, 0.332, "Gutschriftsbetrag", 8, "d"), (0.94, 0.332, "-18,00 EUR", 8, "d")]
    c = _extraire(_pdf([el]), TypeDocument.avoir, avoir_moteur=True)
    assert _v(c.numero) == "GS 2026-0311" and _v(c.date) == "2026-09-26"
    assert [_v(x) for x in c.refs_facture_origine] == ["FS 2026-7781"]
    assert _v(c.motif) == "Tarifkorrektur"
    assert _lignes(c) == [(NatureLigne.frais_dedouanement, "15.00")]
    assert (_v(c.total_credite_ht), _v(c.total_credite_ttc)) == ("15.00", "18.00")


def test_cii_titre_de_transport_en_note_d_en_tete():
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ingest"))
    import fabriques as fab

    from controldone.ingest import ExtracteurFactureXML, OptionsPages, decouper_fichier, recevoir_octets

    xml = fab.cii(numero="FT-2026-0911", devise="EUR", incoterm=None, note="Titre de transport: FICU7654321",
                  lignes=[("Droits de douane", "1", "120.00", "120.00", None, None, "0"),
                          ("Frais de dédouanement", "1", "65.00", "65.00", None, None, "20")],
                  vendeur="FICTIF TRANSIT SARL", tva_vendeur=TVA_TR)
    rec = recevoir_octets([("ft.xml", xml)])
    fr = rec.fichiers[0]
    r = decouper_fichier(fr.fichier, fr.contenu, options=OptionsPages(isoler=False))
    doc = r.documents[0]
    assert doc.type is TypeDocument.facture_transitaire
    ctx = ExtractionContext(contenu_fichier=fr.contenu, type_mime=fr.fichier.type_mime, ids=IdGenerator.deterministe(3))
    c = ExtracteurFactureXML().extract(doc, r.pages, ctx).champs
    assert [_v(x) for x in c.refs_transport] == ["FICU7654321"]
    assert Decimal(_v(c.total_ht)) == Decimal("185.00")
