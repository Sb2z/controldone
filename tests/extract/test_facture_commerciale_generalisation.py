"""Généralisation de l'extracteur des factures commerciales, des listes de colisage et des avoirs fournisseurs
(D-2001 à D-2011).

Mises en page **propres à ces tests** (ni celles du banc, ni celles de la démonstration), rendues par reportlab :
factures allemande (francs suisses, « 1'234.50 »), italienne (titre à gauche, vendeur à droite, pro forma),
néerlandaise, indienne (groupement « 1,23,456.00 »), japonaise et coréenne (devises sans décimales, « ¥ » ambigu),
chinoise (origine déclarée pour toute la facture, en-têtes « (USD) » sous les colonnes), liste de colisage et avoir
allemand. Sociétés, numéros et adresses **fictifs**.
"""

from __future__ import annotations

from decimal import Decimal

import fixtures_fc as fx
import pytest

from controldone.extract.deterministe._fc_regles import (
    devise_symbole,
    nettoyer_colonnes,
    scinder_mots_colles,
)
from controldone.extract.deterministe._mise_en_page import Colonne, Segment, VueLigne
from controldone.extract.deterministe.avoir import ExtracteurAvoir
from controldone.ingest.texte import Ligne, Mot
from controldone.model.enums import TypeDocument
from controldone.normalize import normalize_unit, parse_amount, tva_fr_depuis_siren

TVA_CL = tva_fr_depuis_siren("000646464")


def _fc(contenu: bytes):
    r = fx.extraire(contenu, TypeDocument.facture_commerciale)
    assert r.champs is not None
    return r.champs


def _v(x):
    return None if x is None else x.valeur


def _c(x):
    return None if x is None else x.confiance


def _tableau(p: fx.PagePdf, y: float, entete: list[tuple[float, str, bool]], lignes: list[list[str]],
             xs: list[tuple[float, bool]], pas: float = 16) -> float:
    p.ligne(y, entete, taille=8)
    y += pas
    for ln in lignes:
        p.ligne(y, [(x, t, d) for (x, d), t in zip(xs, ln, strict=True)], taille=8)
        y += pas
    return y


# --- facture allemande : francs suisses, libellés de/ch, poids sur une même ligne ------------------------------


def pdf_de() -> bytes:
    p = fx.PagePdf()
    p.t(200, 40, "Alpenfiktiv Werkzeuge AG (FIKTIV)", taille=13, gras=True)
    p.t(200, 54, "Nirgendweg 3 · 9999 Fantasiedorf · Schweiz")
    p.t(42, 90, "HANDELSRECHNUNG", taille=13, gras=True)
    p.t(400, 90, "Rechnung Nr. AW-2026-0417", gras=True)
    p.t(400, 104, "Datum: 14.09.2026")
    p.t(42, 130, "Rechnungsempfänger", gras=True)
    p.t(300, 130, "Lieferadresse", gras=True)
    p.t(42, 142, "Outils Chimère SARL (FICTIF)")
    p.t(300, 142, "Entrepôt Chimère (FICTIF)")
    p.t(42, 154, "4 impasse du Songe, 31999 Nullepart")
    p.t(300, 154, "Zone fictive 2, 31999 Nullepart")
    p.t(42, 166, f"USt-IdNr.: {TVA_CL}")
    entete = [(42, "Pos", False), (66, "Art.-Nr.", False), (120, "Bezeichnung", False), (250, "Zolltarifnr.", False),
              (320, "Herkunft", False), (400, "Menge", True), (406, "Einh.", False), (490, "Einzelpreis CHF", True),
              (560, "Gesamtpreis CHF", True)]
    xs = [(42, False), (66, False), (120, False), (250, False), (320, False), (400, True), (406, False), (490, True),
          (560, True)]
    y = _tableau(p, 200, entete, [
        ["1", "AW-SCH12", "Schraubstock 125 mm", "8205 70", "CH", "40", "Stück", "86.50", "3'460.00"],
        ["2", "AW-ZNG8", "Zange 180 mm 18 V", "8203 20", "DE", "1'200", "Stk.", "4.15", "4'980.00"],
        ["3", "AW-DRT", "Stahldraht verzinkt", "7217 20", "CH", "750", "kg", "2.80", "2'100.00"],
    ], xs)
    p.t(420, y + 10, "Warenwert")
    p.t(560, y + 10, "10'540.00", droite=True)
    p.t(420, y + 24, "Fracht")
    p.t(560, y + 24, "312.40", droite=True)
    p.t(380, y + 40, "Rechnungsbetrag CHF", gras=True)
    p.t(560, y + 40, "10'852.40", droite=True, gras=True)
    p.t(42, y + 70, "Lieferbedingungen: DAP Basel (Incoterms® 2020)")
    p.t(42, y + 82, "CMR-Frachtbrief: CMR-ZZ-104455")
    p.t(42, y + 94, "Nettogewicht: 1'912.400 kg   Bruttogewicht: 2'046.750 kg")
    p.t(42, y + 106, "Packstücke: 14")
    return fx.pdf([p])


@pytest.fixture(scope="module")
def de():
    return _fc(pdf_de())


def test_de_entete_et_parties(de):
    assert _v(de.numero) == "AW-2026-0417"
    assert _v(de.date) == "2026-09-14"
    assert _v(de.acheteur.tva) == TVA_CL and _c(de.acheteur.tva) >= 0.9
    assert _v(de.acheteur.nom) == "Outils Chimère SARL (FICTIF)"
    assert _v(de.vendeur.nom) == "Alpenfiktiv Werkzeuge AG (FIKTIV)"
    assert _v(de.incoterm) == "DAP" and _v(de.incoterm_lieu) == "Basel"
    assert _v(de.ref_transport) == "CMR-ZZ-104455"


def test_de_devise_dans_les_en_tetes_et_total_suisse(de):
    assert _v(de.devise) == "CHF" and _c(de.devise) >= 0.9
    assert Decimal(_v(de.total_facture)) == Decimal("10852.40") and _c(de.total_facture) >= 0.95
    st = {s.type.value: Decimal(s.montant.valeur) for s in de.sous_totaux}
    assert st == {"marchandises": Decimal("10540.00"), "fret": Decimal("312.40")}


def test_de_masses_sur_une_ligne_et_colis(de):
    assert Decimal(_v(de.masse_nette_totale)) == Decimal("1912.400")
    assert Decimal(_v(de.masse_brute_totale)) == Decimal("2046.750")
    assert _v(de.nombre_colis) == "14"


def test_de_lignes(de):
    assert len(de.lignes) == 3
    l0, l1, l2 = de.lignes
    assert (_v(l0.reference_article), _v(l0.code_marchandise_imprime), _v(l0.pays_origine)) == ("AW-SCH12", "820570",
                                                                                                "CH")
    assert (_v(l0.quantite), l0.quantite.unite, _v(l0.prix_unitaire), _v(l0.montant_ligne)) == ("40", "C62", "86.50",
                                                                                              "3460.00")
    # « 18 V » de la désignation déborde dans la colonne du code : hors du code
    assert _v(l1.code_marchandise_imprime) == "820320"
    assert (_v(l1.quantite), l1.quantite.unite) == ("1200", "C62")
    assert (_v(l2.quantite), l2.quantite.unite, _v(l2.montant_ligne)) == ("750", "KGM", "2100.00")
    assert all(_c(x.montant_ligne) >= 0.95 for x in de.lignes)


# --- facture italienne : titre à gauche, vendeur à droite, pro forma, « n. » ------------------------------------


def pdf_it() -> bytes:
    p = fx.PagePdf()
    p.t(42, 40, "FATTURA PROFORMA", taille=13, gras=True)
    p.t(360, 40, "Officine Immaginarie S.r.l. (FITTIZIA)", gras=True)
    p.t(360, 52, "Via Inesistente 9")
    p.t(360, 64, "20999 Milano Finta")
    p.t(42, 64, "Fattura n. OI 0331/2026")
    p.t(42, 76, "Data: 3 marzo 2026")
    p.t(42, 110, "Intestatario", gras=True)
    p.t(300, 110, "Destinatario merce", gras=True)
    p.t(42, 122, "Outils Chimère SARL (FICTIF)")
    p.t(300, 122, "Outils Chimère SARL (FICTIF)")
    p.t(42, 134, f"Partita IVA: {TVA_CL}")
    entete = [(42, "#", False), (60, "Codice", False), (120, "Descrizione", False), (260, "Voce doganale", False),
              (340, "Origine", False), (400, "Q.tà", True), (406, "U.M.", False), (510, "Prezzo unit. EUR", True),
              (565, "Importo EUR", True)]
    xs = [(42, False), (60, False), (120, False), (260, False), (340, False), (400, True), (406, False), (510, True),
          (565, True)]
    y = _tableau(p, 170, entete, [
        ["1", "OI-VLV", "Valvola in ottone", "8481 80 85", "IT", "200", "pezzi", "12,40", "2.480,00"],
        ["2", "OI-GRN", "Guarnizioni assortite", "4016 93 00", "IT", "50", "paia", "3,10", "155,00"],
    ], xs)
    p.t(300, y + 10, "Totale merce")
    p.t(560, y + 10, "2.635,00", droite=True)
    p.t(300, y + 24, "Imballo")
    p.t(560, y + 24, "40,00", droite=True)
    p.t(300, y + 40, "TOTALE FATTURA EUR", gras=True)
    p.t(560, y + 40, "2.675,00", droite=True, gras=True)
    p.t(42, y + 70, "Resa: FCA Como (Incoterms® 2020)")
    p.t(42, y + 82, "Peso netto: 310,500 kg   Peso lordo: 342,250 kg")
    p.t(42, y + 94, "Colli: 6")
    return fx.pdf([p])


@pytest.fixture(scope="module")
def it():
    return _fc(pdf_it())


def test_it_entete(it):
    assert _v(it.numero).replace(" ", "") == "OI0331/2026"
    assert _v(it.date) == "2026-03-03"
    assert _v(it.vendeur.nom) == "Officine Immaginarie S.r.l. (FITTIZIA)"
    assert _v(it.acheteur.tva) == TVA_CL
    assert _v(it.devise) == "EUR" and _c(it.devise) >= 0.9
    assert Decimal(_v(it.total_facture)) == Decimal("2675.00") and _c(it.total_facture) >= 0.95
    assert {s.type.value for s in it.sous_totaux} == {"marchandises", "emballage"}
    assert Decimal(_v(it.masse_brute_totale)) == Decimal("342.250")
    assert _v(it.nombre_colis) == "6"
    assert (_v(it.incoterm), _v(it.incoterm_lieu)) == ("FCA", "Como")


def test_it_lignes(it):
    l0, l1 = it.lignes
    assert (_v(l0.quantite), l0.quantite.unite, _v(l0.montant_ligne)) == ("200", "C62", "2480.00")
    assert (_v(l1.quantite), l1.quantite.unite, _v(l1.pays_origine)) == ("50", "PR", "IT")
    assert _v(l0.code_marchandise_imprime) == "84818085"


# --- facture néerlandaise --------------------------------------------------------------------------------------


def test_nl_libelles_et_colonnes():
    p = fx.PagePdf()
    p.t(42, 40, "HANDELSFACTUUR", taille=13, gras=True)
    p.t(360, 40, "Fictieve Handel B.V. (FICTIEF)", gras=True)
    p.t(42, 64, "Factuurnummer: FH 2026.0099")
    p.t(42, 76, "Factuurdatum: 12 maart 2026")
    p.t(42, 110, "Factuuradres", gras=True)
    p.t(300, 110, "Afleveradres", gras=True)
    p.t(42, 122, "Outils Chimère SARL (FICTIF)")
    p.t(300, 122, "Outils Chimère SARL (FICTIF)")
    p.t(42, 134, f"Btw-nummer: {TVA_CL}")
    entete = [(42, "#", False), (60, "Artikelnr.", False), (130, "Omschrijving", False), (260, "GN-code", False),
              (340, "Oorsprong", False), (420, "Aantal", True), (426, "Eenh.", False), (500, "Prijs USD", True),
              (560, "Bedrag USD", True)]
    xs = [(42, False), (60, False), (130, False), (260, False), (340, False), (420, True), (426, False), (500, True),
          (560, True)]
    y = _tableau(p, 170, entete, [["1", "FH-LMP", "Tafellamp", "9405.21", "NL", "30", "st.", "18,20", "546,00"]], xs)
    p.t(380, y + 10, "Subtotaal")
    p.t(560, y + 10, "546,00", droite=True)
    p.t(380, y + 24, "Vracht")
    p.t(560, y + 24, "24,00", droite=True)
    p.t(380, y + 40, "TOTAAL USD", gras=True)
    p.t(560, y + 40, "570,00", droite=True)
    p.t(42, y + 70, "Leveringsvoorwaarden: FOB Rotterdam (Incoterms® 2020)")
    p.t(42, y + 82, "Nettogewicht: 45,000 kg   Brutogewicht: 51,300 kg")
    c = _fc(fx.pdf([p]))
    assert _v(c.numero).replace(" ", "") == "FH2026.0099"
    assert _v(c.date) == "2026-03-12"
    assert _v(c.devise) == "USD"
    assert Decimal(_v(c.total_facture)) == Decimal("570.00")
    assert _v(c.acheteur.tva) == TVA_CL
    assert _v(c.vendeur.nom) == "Fictieve Handel B.V. (FICTIEF)"
    assert Decimal(_v(c.masse_brute_totale)) == Decimal("51.300")
    (ln,) = c.lignes
    assert (_v(ln.code_marchandise_imprime), _v(ln.pays_origine), _v(ln.montant_ligne)) == ("940521", "NL", "546.00")


# --- devises : roupie (groupement indien), yen ambigu, won sans décimales ---------------------------------------


def _facture_simple(*, colonnes_montant: tuple[str, str], lignes: list[list[str]], total: tuple[str, str],
                    origine_doc: str | None = None) -> bytes:
    p = fx.PagePdf()
    p.t(42, 40, "Notional Exports Pvt Ltd (FICTITIOUS)", taille=12, gras=True)
    p.t(400, 40, "INVOICE", taille=14, gras=True)
    p.t(42, 70, "Invoice number")
    p.t(42, 82, "NE/EXP/0042/26-27")
    p.t(200, 70, "Issue date")
    p.t(200, 82, "May 6, 2026")
    p.t(42, 110, "Customer", gras=True)
    p.t(42, 122, "Outils Chimère SARL (FICTIF)")
    p.t(42, 134, f"VAT {TVA_CL}")
    entete = [(42, "SKU", False), (110, "Item", False), (260, "Tariff no.", False), (420, "Qty", True),
              (426, "UoM", False), (500, colonnes_montant[0], True), (560, colonnes_montant[1], True)]
    if origine_doc is None:
        entete.insert(3, (340, "COO", False))
    xs = [(42, False), (110, False), (260, False)] + ([] if origine_doc else [(340, False)]) + [
        (420, True), (426, False), (500, True), (560, True)]
    y = _tableau(p, 170, entete, lignes, xs)
    p.t(420, y + 14, total[0], gras=True)
    p.t(560, y + 14, total[1], droite=True, gras=True)
    if origine_doc:
        p.t(42, y + 40, f"Country of origin: {origine_doc}")
    return fx.pdf([p])


def test_roupie_groupement_indien_et_devise_du_libelle_de_total():
    c = _fc(_facture_simple(colonnes_montant=("Price", "Line total"), lignes=[
        ["NE-TX1", "Cotton shirts", "62052000", "IN", "1,500", "PCS", "82.30", "1,23,450.00"],
        ["NE-TX2", "Silk scarves", "62141000", "IN", "300", "PCS", "410.00", "1,23,000.00"],
    ], total=("Total INR", "2,46,450.00")))
    assert _v(c.devise) == "INR" and _c(c.devise) >= 0.9
    assert Decimal(_v(c.total_facture)) == Decimal("246450.00") and _c(c.total_facture) >= 0.95
    assert [_v(x.montant_ligne) for x in c.lignes] == ["123450.00", "123000.00"]
    assert _v(c.date) == "2026-05-06"
    assert _v(c.numero) == "NE/EXP/0042/26-27"


def test_yen_seul_devise_inconnue_mais_resolue_par_un_code_iso():
    lignes = [["NE-A", "Lens cloth", "63079098", "JP", "10", "PCS", "120", "1,200"]]
    seul = _fc(_facture_simple(colonnes_montant=("Price", "Line total"), lignes=lignes, total=("Total", "¥1,200")))
    assert _v(seul.devise) in (None, "inconnue") or _c(seul.devise) < 0.5
    jpy = _fc(_facture_simple(colonnes_montant=("Price JPY", "Amount JPY"), lignes=lignes, total=("Total", "¥1,200")))
    assert _v(jpy.devise) == "JPY" and _c(jpy.devise) >= 0.9
    assert Decimal(_v(jpy.total_facture)) == Decimal("1200")


def test_won_sans_decimales():
    c = _fc(_facture_simple(colonnes_montant=("Price KRW", "Amount KRW"), lignes=[
        ["NE-K", "Phone case", "42029291", "KR", "500", "PCS", "2,500", "1,250,000"],
    ], total=("TOTAL KRW", "1,250,000")))
    assert _v(c.devise) == "KRW"
    assert Decimal(_v(c.total_facture)) == Decimal("1250000")
    assert _v(c.lignes[0].prix_unitaire) == "2500"


def test_origine_declaree_pour_toute_la_facture():
    c = _fc(_facture_simple(colonnes_montant=("Price USD", "Amount USD"), lignes=[
        ["NE-A", "Cable 5 m", "85444290", "200", "PCS", "1.10", "220.00"],
        ["NE-B", "Plug", "85366990", "100", "PCS", "0.50", "50.00"],
    ], total=("TOTAL USD", "270.00"), origine_doc="China (CN)"))
    assert [_v(x.pays_origine) for x in c.lignes] == ["CN", "CN"]
    assert all(_c(x.pays_origine) <= 0.85 for x in c.lignes)


# --- liste de colisage -----------------------------------------------------------------------------------------


def test_liste_colisage_total_du_tableau_et_libelles_bilingues():
    p = fx.PagePdf()
    p.t(42, 40, "Alpenfiktiv Werkzeuge AG (FIKTIV)", gras=True)
    p.t(420, 40, "PACKLISTE", taille=13, gras=True)
    p.t(42, 64, "Ref. invoice / facture: AW-2026-0417 — 2026-09-14")
    p.t(42, 76, "Consignee: Outils Chimère SARL (FICTIF)")
    p.t(42, 88, "Transport: CMR-ZZ-104455")
    entete = [(42, "#", False), (60, "Artikel", False), (140, "Bezeichnung", False), (400, "Menge", True),
              (470, "Netto kg", True), (550, "Brutto kg", True)]
    xs = [(42, False), (60, False), (140, False), (400, True), (470, True), (550, True)]
    y = _tableau(p, 120, entete, [["1", "AW-SCH12", "Schraubstock", "40", "1'120,000", "1'190,500"],
                                  ["2", "AW-DRT", "Stahldraht", "750", "792,400", "856,250"]], xs)
    p.ligne(y, [(140, "Summe", False), (470, "1'912,400", True), (550, "2'046,750", True)])
    p.t(42, y + 24, "Packages / colis: 14")
    r = fx.extraire(fx.pdf([p]), TypeDocument.document_support, sous_type="liste_colisage")
    c = r.champs
    assert Decimal(_v(c.masse_brute)) == Decimal("2046.750") and _c(c.masse_brute) >= 0.9
    assert _v(c.nombre_colis) == "14"
    assert _v(c.ref_transport_maitre) == "CMR-ZZ-104455"
    assert [x.valeur_brute for x in c.refs_facture] == ["AW-2026-0417"]


# --- avoir fournisseur allemand --------------------------------------------------------------------------------


def test_avoir_fournisseur_allemand():
    p = fx.PagePdf()
    p.t(42, 40, "Alpenfiktiv Werkzeuge AG (FIKTIV)", gras=True)
    p.t(42, 70, "GUTSCHRIFT", taille=13, gras=True)
    p.t(400, 70, "Gutschrift Nr. GS-2026-011")
    p.t(400, 82, "Datum: 02.10.2026")
    p.t(400, 94, "Ursprungsrechnung: AW-2026-0417")
    p.t(42, 110, "Rechnungsempfänger", gras=True)
    p.t(42, 122, "Outils Chimère SARL (FICTIF)")
    entete = [(42, "Pos", False), (66, "Art.-Nr.", False), (120, "Bezeichnung", False), (400, "Menge", True),
              (406, "Einh.", False), (490, "Einzelpreis CHF", True), (560, "Gesamtpreis CHF", True)]
    xs = [(42, False), (66, False), (120, False), (400, True), (406, False), (490, True), (560, True)]
    y = _tableau(p, 150, entete, [["1", "AW-SCH12", "Schraubstock 125 mm", "2", "Stück", "86.50", "173.00"]], xs)
    p.t(380, y + 14, "Gutschriftsbetrag CHF", gras=True)
    p.t(560, y + 14, "173.00", droite=True)
    p.t(42, y + 40, "Grund: Transportschaden")
    r = fx.extraire(fx.pdf([p]), TypeDocument.avoir, extracteur=ExtracteurAvoir())
    c = r.champs
    assert "avoir_fournisseur" in r.avertissements
    assert _v(c.numero) == "GS-2026-011"
    assert [x.valeur for x in c.refs_facture_origine] == ["AW-2026-0417"]
    assert _v(c.date) == "2026-10-02"
    assert _v(c.motif) == "Transportschaden"


# --- aides générales ---------------------------------------------------------------------------------------------


def _ligne(mots: list[tuple[str, float, float]]) -> VueLigne:
    ms = tuple(Mot(t, x0, 0.1, x1, 0.11) for t, x0, x1 in mots)
    return VueLigne(page=1, rang=0, segments=[Segment(ms, 1, 0, 0)], ligne=Ligne(texte="", mots=ms))


def test_scinder_mots_colles():
    li = _ligne([("Fracción", 0.30, 0.36), ("arancelariaOrigen", 0.37, 0.50)])
    out = [m.texte for m in scinder_mots_colles(li).mots]
    assert out == ["Fracción", "arancelaria", "Origen"]
    assert scinder_mots_colles(_ligne([("Amount", 0.1, 0.2)])) is not None


def test_nettoyer_colonnes_code_devise_et_doublons():
    cols = [Colonne("numero_ligne", 0.05, 0.07, "NO."), Colonne("numero_ligne", 0.10, 0.18, "ITEM NO."),
            Colonne("montant", 0.80, 0.86, "Amount"), Colonne("inconnue", 0.87, 0.90, "CNY")]
    out, codes = nettoyer_colonnes(cols)
    assert [c.type for c in out] == ["numero_ligne", "reference_article", "montant"]
    assert codes == ["CNY"] and out[-1].x1 == pytest.approx(0.90) and out[-1].droite == 1.0


def test_devise_symbole():
    assert devise_symbole("¥", []) is None
    assert devise_symbole("¥", ["JPY"]) == "JPY"
    assert devise_symbole("¥", ["JPY", "CNY"]) is None
    assert devise_symbole("₹", []) == "INR"
    assert devise_symbole("$", ["USD", "EUR"]) == "USD"


def test_normalisation_groupement_indien_et_unites():
    assert parse_amount("1,23,456.00").valeur == Decimal("123456.00")
    assert parse_amount("12,34,56,789").valeur == Decimal("123456789")
    assert parse_amount("1,23,4567") is None
    assert parse_amount("1,234,567.00").valeur == Decimal("1234567.00")
    assert {u: normalize_unit(u).code for u in ("Stück", "pezzi", "paia", "stuks", "Paar", "metre", "litri")} == {
        "Stück": "C62", "pezzi": "C62", "paia": "PR", "stuks": "C62", "Paar": "PR", "metre": "MTR", "litri": "LTR"}
    assert normalize_unit("m3").code == "MTQ" and normalize_unit("m2").code == "MTK"
