"""Généralisation des extracteurs déterministes à des mises en page **inconnues** (D-950 à D-953).

Les PDF sont rendus ici par reportlab dans plusieurs variantes (en-tête à deux colonnes dont les lignes
s'intercalent, bandeaux et filigranes, codes marchandise imprimés par groupes, libellé de TVA collé au
numéro). Données **fictives** ; mises en page propres à ces tests (ni celles du banc, ni celles de la
démonstration).
"""

from __future__ import annotations

import io
from decimal import Decimal

import pytest
from fixtures_fc import extraire
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

from controldone.extract.deterministe._mise_en_page import (
    lignes_bandeau,
    lire_tva_mots,
    separer_libelle_tva,
    vue_document,
)
from controldone.ingest.texte import Mot, PageText, construire_lignes
from controldone.model.enums import PaiementNormalise
from controldone.normalize.fiscal import tva_fr_depuis_siren

L, H = A4
TVA_IMP = tva_fr_depuis_siren("000271828")
TVA_TR = tva_fr_depuis_siren("000314159")
#: même SIREN, clé fausse
TVA_FAUSSE = "FR" + ("00" if TVA_IMP[2:4] != "00" else "01") + TVA_IMP[4:]


def _pdf(pages: list[list[tuple]]) -> bytes:
    """Éléments ``(x, y, texte[, taille[, "d"|"g"|"c"[, gras]]])`` en fractions de page (origine en haut à
    gauche)."""
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4, invariant=1)
    for elements in pages:
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
        c.showPage()
    c.save()
    return buf.getvalue()


def _paires(x_lib: float, x_val: float, y0: float, pas: float, paires: list[tuple[str, str]]) -> list[tuple]:
    """Colonne « libellé … valeur » (valeur alignée à droite)."""
    out: list[tuple] = []
    for k, (lib, val) in enumerate(paires):
        y = y0 + k * pas
        out += [(x_lib, y, lib, 7.5), (x_val, y, val, 8.5, "d", True)]
    return out


# --- déclarations ----------------------------------------------------------------------------------------------


def _declaration_deux_colonnes(
    *, langue: str = "fr", tva_collee: bool = False, x_droite: float = 0.56, total: bool = True
) -> bytes:
    """En-tête à deux colonnes : pavé de l'importateur à gauche (interligne 0,016), couples libellé/valeur à
    droite (interligne 0,019), décalés : leurs lignes s'intercalent. Bandeau en haut de page."""
    fr = langue == "fr"
    el: list[tuple] = [
        (0.5, 0.014, "SPECIMEN — DONNÉES FICTIVES" if fr else "SPECIMEN — FICTITIOUS DATA", 7, "c", True)
    ]
    el.append((0.07, 0.06, "DÉCLARATION D'IMPORTATION" if fr else "IMPORT DECLARATION", 14, "g", True))
    droite = [
        ("MRN", "26FRX9QW00012345R7"),
        ("Date d'acceptation" if fr else "Date of acceptance", "02/03/2026"),
        ("Devise de facturation" if fr else "Invoice currency", "EUR"),
    ]
    if total:
        droite.append(("Montant facturé" if fr else "Invoice amount", "18 730,50" if fr else "18,730.50"))
    droite += [
        ("Pays d'expédition" if fr else "Country of dispatch", "DE"),
        ("Nombre d'articles" if fr else "Number of items", "2"),
    ]
    el += _paires(x_droite, 0.93, 0.105, 0.019, droite)
    tva = f"N° TVA{TVA_IMP}" if tva_collee else f"N° TVA {TVA_IMP}"
    if not fr:
        tva = f"VAT{TVA_IMP}" if tva_collee else f"VAT {TVA_IMP}"
    gauche = [
        "IMPORTATEUR" if fr else "IMPORTER",
        "BOREAL OUTILLAGE FICTIF SAS",
        "7 allée Inventée (fictive)",
        "38000 GRENOBLE",
        tva,
    ]
    for k, txt in enumerate(gauche):
        el.append((0.07, 0.112 + k * 0.016, txt, 7.5 if k == 0 else 8.5, "g", k <= 1))
    # tableau des articles : codes imprimés par groupes de chiffres
    y = 0.26
    cols = [
        (0.07, "Art."),
        (0.12, "Code marchandise" if fr else "Commodity code"),
        (0.30, "Désignation" if fr else "Description"),
        (0.50, "Origine" if fr else "Origin"),
        (0.66, "Masse nette" if fr else "Net mass", "d"),
        (0.88, "Montant facturé" if fr else "Invoice amount", "d"),
    ]
    for c in cols:
        el.append((c[0], y, c[1], 7.5, c[2] if len(c) > 2 else "g", True))
    lignes = [
        (
            "1",
            "8481 80 85 00",
            "Robinets fictifs",
            "DE",
            "320,0 kg" if fr else "320.0 kg",
            "11 230,50" if fr else "11,230.50",
        ),
        (
            "2",
            "7318 15 88",
            "Vis fictives",
            "CN",
            "95,5 kg" if fr else "95.5 kg",
            "7 500,00" if fr else "7,500.00",
        ),
    ]
    for k, ln in enumerate(lignes):
        yy = y + 0.02 * (k + 1)
        el += [
            (0.07, yy, ln[0]),
            (0.12, yy, ln[1]),
            (0.30, yy, ln[2]),
            (0.50, yy, ln[3]),
            (0.66, yy, ln[4], 8, "d"),
            (0.88, yy, ln[5], 8, "d"),
        ]
    # impositions : mode de paiement en toutes lettres
    y = 0.36
    el.append((0.07, y - 0.02, "Calcul des impositions" if fr else "Calculation of taxes", 9, "g", True))
    for x, t, a in (
        (0.07, "Art.", "g"),
        (0.13, "Type", "g"),
        (0.36, "Base", "d"),
        (0.46, "Taux" if fr else "Rate", "d"),
        (0.60, "Montant" if fr else "Amount", "d"),
        (0.64, "Mode de paiement" if fr else "MOP", "g"),
    ):
        el.append((x, y, t, 7.5, a, True))
    taxes = (
        [
            ("1", "A00", "11 230,50", "2,2", "247,07", "Comptant"),
            ("1", "B00", "11 477,57", "20", "2 295,51", "Autoliquidation"),
        ]
        if fr
        else [
            ("1", "A00", "11,230.50", "2.2", "247.07", "Cash"),
            ("1", "B00", "11,477.57", "20", "2,295.51", "Postponed"),
        ]
    )
    for k, tx in enumerate(taxes):
        yy = y + 0.02 * (k + 1)
        el += [
            (0.07, yy, tx[0]),
            (0.13, yy, tx[1]),
            (0.36, yy, tx[2], 8, "d"),
            (0.46, yy, tx[3], 8, "d"),
            (0.60, yy, tx[4], 8, "d"),
            (0.64, yy, tx[5]),
        ]
    el.append((0.5, 0.985, "Document fictif — aucune valeur réelle", 6.5, "c"))
    return _pdf([el])


@pytest.mark.parametrize("langue,x_droite", [("fr", 0.56), ("fr", 0.48), ("en", 0.56)])
def test_declaration_en_tete_deux_colonnes(langue: str, x_droite: float) -> None:
    c = extraire(_declaration_deux_colonnes(langue=langue, x_droite=x_droite), "declaration").champs
    assert c.mrn is not None and c.mrn.valeur == "26FRX9QW00012345R7"
    assert c.montant_total_facture is not None and c.montant_total_facture.valeur == "18730.50"
    assert c.montant_total_facture.confiance >= 0.9  # égal à la somme des articles
    assert c.importateur.nom is not None and c.importateur.nom.valeur == "BOREAL OUTILLAGE FICTIF SAS"
    assert c.importateur.tva is not None and c.importateur.tva.valeur == TVA_IMP
    codes = [a.code_marchandise.valeur if a.code_marchandise else None for a in c.articles]
    assert codes == ["8481808500", "73181588"]
    assert [a.pays_origine.valeur for a in c.articles if a.pays_origine] == ["DE", "CN"]
    assert [a.montant_facture_article.valeur for a in c.articles if a.montant_facture_article] == [
        "11230.50",
        "7500.00",
    ]
    assert [a.masse_nette.valeur for a in c.articles if a.masse_nette] == ["320.000", "95.500"]
    assert [t.type_taxe.valeur for t in c.taxations if t.type_taxe] == ["A00", "B00"]
    assert [t.paiement_normalise for t in c.taxations] == [
        PaiementNormalise.comptant,
        PaiementNormalise.autoliquide,
    ]


@pytest.mark.parametrize("langue", ["fr", "en"])
def test_declaration_tva_collee_au_libelle(langue: str) -> None:
    c = extraire(_declaration_deux_colonnes(langue=langue, tva_collee=True), "declaration").champs
    assert c.importateur.tva is not None and c.importateur.tva.valeur == TVA_IMP
    assert c.importateur.nom is not None and c.importateur.nom.valeur == "BOREAL OUTILLAGE FICTIF SAS"


def test_declaration_montant_facture_des_articles_jamais_pris_pour_le_total() -> None:
    """Sans montant total dans l'en-tête, la colonne « Montant facturé » du tableau des articles ne devient
    pas le montant total facturé."""
    c = extraire(_declaration_deux_colonnes(total=False), "declaration").champs
    assert c.montant_total_facture is None
    assert len(c.articles) == 2


def test_tva_collee_cle_fausse_rejetee() -> None:
    assert separer_libelle_tva(f"TVA{TVA_IMP}") == TVA_IMP
    assert separer_libelle_tva(f"N°TVA{TVA_IMP}") == TVA_IMP
    assert separer_libelle_tva("VATDE123456789") == "DE123456789"
    assert separer_libelle_tva(f"TVA{TVA_FAUSSE}") is None
    assert separer_libelle_tva("TVAFR1234") is None
    mots = [Mot("N°", 0.1, 0.1, 0.12, 0.11), Mot(f"TVA{TVA_IMP}", 0.13, 0.1, 0.3, 0.11)]
    r = lire_tva_mots(mots)
    assert r is not None and r[2] == TVA_IMP
    assert lire_tva_mots([Mot(f"TVA{TVA_FAUSSE}", 0.1, 0.1, 0.3, 0.11)]) is None


# --- factures commerciales ----------------------------------------------------------------------------------


def _facture_deux_colonnes(*, pages: int = 1, bandeau_haut: bool = True, x_droite: float = 0.55) -> bytes:
    """Facture sans libellé « vendeur » : nom du fournisseur en tête ; pavé acheteur à gauche ; colonne de
    couples libellé/valeur à droite dont les lignes s'intercalent avec le pavé (le libellé « Place »
    tombe entre le titre du pavé et le nom de l'acheteur)."""
    out = []
    for n in range(1, pages + 1):
        el: list[tuple] = []
        if bandeau_haut:
            el.append((0.5, 0.012, "FICTITIOUS DATA — SAMPLE DOCUMENT", 7, "c", True))
        el += [
            (0.07, 0.05, "NORDLICHT MOCK TOOLS GMBH (FICTITIOUS)", 11, "g", True),
            (0.07, 0.066, "Musterweg 0, 00000 Beispielstadt"),
            (0.62, 0.05, "INVOICE", 15, "g", True),
        ]
        if n == 1:
            el += _paires(
                x_droite,
                0.93,
                0.10,
                0.019,
                [
                    ("Invoice No.", "NM-2026-0042"),
                    ("Date", "05/02/2026"),
                    ("Currency", "EUR"),
                    ("Incoterms", "DAP"),
                    ("Place", "Grenoble"),
                    ("Packages", "7"),
                    ("Gross weight", "212.0 kg"),
                    ("Net weight", "198.5 kg"),
                ],
            )
            for k, txt in enumerate(
                [
                    "SOLD TO",
                    "BOREAL OUTILLAGE FICTIF SAS",
                    "7 allée Inventée (fictive)",
                    "38000 GRENOBLE — FRANCE",
                    f"VAT No. {TVA_IMP}",
                ]
            ):
                el.append((0.07, 0.1475 + k * 0.016, txt, 7.5 if k == 0 else 8.5, "g", k <= 1))
            y = 0.30
            for x, t, a in (
                (0.07, "#", "g"),
                (0.11, "Description", "g"),
                (0.40, "HS code", "g"),
                (0.53, "Origin", "g"),
                (0.66, "Qty", "d"),
                (0.77, "Unit price", "d"),
                (0.92, "Amount", "d"),
            ):
                el.append((x, y, t, 7.5, a, True))
            for k, ln in enumerate(
                [
                    ("1", "Ball valve DN15 (fictitious)", "8481.80", "DE", "300", "20.50", "6,150.00"),
                    ("2", "Hex screw M6 (fictitious)", "7318.15", "CN", "1000", "1.25", "1,250.00"),
                ]
            ):
                yy = y + 0.02 * (k + 1)
                el += [
                    (0.07, yy, ln[0]),
                    (0.11, yy, ln[1]),
                    (0.40, yy, ln[2]),
                    (0.53, yy, ln[3]),
                    (0.66, yy, ln[4], 8, "d"),
                    (0.77, yy, ln[5], 8, "d"),
                    (0.92, yy, ln[6], 8, "d"),
                ]
            el += [(0.78, 0.40, "TOTAL EUR", 8.5, "d"), (0.92, 0.40, "7,400.00", 9.5, "d", True)]
        else:
            el.append((0.07, 0.12, "Terms and conditions (fictitious): payment within 30 days."))
        el.append(
            (0.07, 0.96, f"Nordlicht Mock Tools — registered office (fictitious) — page {n} / {pages}", 6.5)
        )
        out.append(el)
    return _pdf(out)


@pytest.mark.parametrize("x_droite", [0.55, 0.45])
def test_facture_commerciale_pave_intercale_et_bandeau(x_droite: float) -> None:
    c = extraire(_facture_deux_colonnes(x_droite=x_droite), "facture_commerciale").champs
    assert c.acheteur.nom is not None and c.acheteur.nom.valeur == "BOREAL OUTILLAGE FICTIF SAS"
    assert c.acheteur.nom.confiance <= 0.8  # structure ambiguë (colonnes intercalées)
    assert c.acheteur.tva is not None and c.acheteur.tva.valeur == TVA_IMP
    assert c.vendeur.nom is not None and c.vendeur.nom.valeur.startswith("NORDLICHT MOCK TOOLS")
    assert c.nombre_colis is not None and c.nombre_colis.valeur == "7"
    assert c.total_facture is not None and Decimal(c.total_facture.valeur) == Decimal("7400.00")
    assert [ln.code_marchandise_imprime.valeur for ln in c.lignes if ln.code_marchandise_imprime] == [
        "848180",
        "731815",
    ]


def test_facture_commerciale_plusieurs_pages_en_tete_repete() -> None:
    """L'en-tête du fournisseur répété sur chaque page reste lisible comme son nom ; le pied répété et le
    bandeau ne deviennent jamais un nom."""
    c = extraire(_facture_deux_colonnes(pages=2), "facture_commerciale").champs
    assert c.vendeur.nom is not None and c.vendeur.nom.valeur.startswith("NORDLICHT MOCK TOOLS")
    assert c.acheteur.nom is not None and c.acheteur.nom.valeur == "BOREAL OUTILLAGE FICTIF SAS"


def test_facture_commerciale_sans_nom_lisible_aucun_bandeau_retenu() -> None:
    """Seul texte au-dessus du pavé acheteur : un bandeau -> pas de nom de vendeur (plutôt qu'un faux)."""
    el = [
        (0.5, 0.012, "DONNÉES FICTIVES — DOCUMENT DE TEST", 7, "c", True),
        (0.07, 0.10, "Buyer:", 8, "g", True),
        (0.07, 0.116, "BOREAL OUTILLAGE FICTIF SAS"),
        (0.07, 0.132, f"VAT {TVA_IMP}"),
        (0.55, 0.10, "Invoice No.:"),
        (0.75, 0.10, "NM-77"),
        (0.75, 0.30, "TOTAL EUR 100.00"),
    ]
    c = extraire(_pdf([el]), "facture_commerciale").champs
    assert c.vendeur.nom is None
    assert c.acheteur.nom is not None and c.acheteur.nom.valeur == "BOREAL OUTILLAGE FICTIF SAS"


# --- facture du transitaire ---------------------------------------------------------------------------------


@pytest.mark.parametrize("bandeau", ["DONNÉES FICTIVES — DOCUMENT DE DÉMONSTRATION", "SPECIMEN"])
def test_facture_transitaire_bandeau_jamais_emetteur(bandeau: str) -> None:
    el = [
        (0.5, 0.013, bandeau, 7, "c", True),
        (0.07, 0.05, "FACTURE", 15, "g", True),
        (0.07, 0.085, "TRANSIT IMAGINAIRE FICTIF SARL", 10, "g", True),
        (0.07, 0.10, "2 rue Inventée (fictive)"),
        (0.07, 0.114, f"N° TVA {TVA_TR}"),
        (0.55, 0.085, "Facture n°"),
        (0.93, 0.085, "TI-26-0007", 8.5, "d"),
        (0.55, 0.104, "Date"),
        (0.93, 0.104, "10/03/2026", 8.5, "d"),
        (0.07, 0.15, "CLIENT", 7.5, "g", True),
        (0.07, 0.166, "BOREAL OUTILLAGE FICTIF SAS"),
        (0.07, 0.182, f"N° TVA {TVA_IMP}"),
        (0.07, 0.25, "Désignation", 7.5, "g", True),
        (0.60, 0.25, "Montant HT", 7.5, "d", True),
        (0.07, 0.27, "Frais de dédouanement"),
        (0.60, 0.27, "70,00", 8, "d"),
        (0.50, 0.32, "Total HT"),
        (0.60, 0.32, "70,00", 8, "d"),
    ]
    c = extraire(_pdf([el]), "facture_transitaire").champs
    assert c.emetteur.nom is not None and c.emetteur.nom.valeur == "TRANSIT IMAGINAIRE FICTIF SARL"
    assert c.emetteur.tva is not None and c.emetteur.tva.valeur == TVA_TR


# --- bandeaux ---------------------------------------------------------------------------------------------------


def _page(numero: int, lignes: list[tuple[float, str]]) -> PageText:
    mots = []
    for y, texte in lignes:
        x = 0.1
        for m in texte.split():
            mots.append(Mot(m, x, y, x + 0.01 * len(m), y + 0.01))
            x += 0.01 * len(m) + 0.004
    lignes_pt = construire_lignes(mots)
    return PageText(numero=numero, texte="\n".join(li.texte for li in lignes_pt), lignes=lignes_pt)


def test_lignes_bandeau_regles() -> None:
    p1 = _page(
        1,
        [
            (0.008, "ACME"),
            (0.05, "ACME FICTIF SA"),
            (0.2, "Données fictives pour essai"),
            (0.5, "Contenu"),
            (0.93, "Pied commun page 1"),
        ],
    )
    p2 = _page(2, [(0.05, "ACME FICTIF SA"), (0.5, "Autre contenu"), (0.93, "Pied commun page 2")])
    vue = vue_document([p1, p2])
    textes = {(p.numero, li.rang): li.texte for p in vue.pages for li in p.lignes}
    tous = {textes[k] for k in lignes_bandeau(vue)}
    assert "ACME" in tous  # marge haute
    assert "Données fictives pour essai" in tous  # vocabulaire
    assert {"Pied commun page 1", "Pied commun page 2"} <= tous  # pied répété
    assert "ACME FICTIF SA" in tous  # en-tête répété
    assert "Contenu" not in tous
    sans_entetes = {textes[k] for k in lignes_bandeau(vue, entetes_repetes=False)}
    assert "ACME FICTIF SA" not in sans_entetes
    assert "Pied commun page 1" in sans_entetes
