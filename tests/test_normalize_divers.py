from datetime import date
from decimal import Decimal as D

import pytest

from controldone.normalize import (
    cle_tva_fr,
    code_marchandise,
    code_sh6,
    country_to_iso2,
    est_mrn,
    extraire_siren,
    mrn_egaux,
    mrn_prefixe,
    norm_ref,
    norm_ref_containment,
    norm_ref_transport,
    normalize_currency,
    normalize_eori,
    normalize_unit,
    normalize_vat,
    parse_date,
    parse_date_detail,
    parse_incoterm,
    parse_weight_kg,
    ref_compatibles,
    ref_egales,
    ref_transport_compatibles,
    ref_transport_egales,
    siren_depuis_siret,
    siren_depuis_tva,
    siren_luhn_valide,
    tva_fr_depuis_siren,
    tva_fr_valide,
)

# --- dates -------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "texte",
    [
        "2026-08-14",
        "14/08/2026",
        "14.08.2026",
        "14-08-2026",
        "14/08/26",
        "14 août 2026",
        "14 aout 2026",
        "14 Août 2026",
        "August 14, 2026",
        "Aug. 14, 2026",
        "14 Aug 2026",
        "14-Aug-26",
        "14th August 2026",
        "14 de agosto de 2026",
        "14 agosto 2026",
        "Date : 14/08/2026",
        "20260814",
        "2026/08/14",
    ],
)
def test_dates(texte):
    assert parse_date(texte) == date(2026, 8, 14)


def test_dates_mois_divers():
    assert parse_date("1er août 2026") == date(2026, 8, 1)
    assert parse_date("3 février 2026") == date(2026, 2, 3)
    assert parse_date("15 décembre 2025") == date(2025, 12, 15)
    assert parse_date("5 enero 2026") == date(2026, 1, 5)
    assert parse_date("September 30, 2026") == date(2026, 9, 30)


def test_dates_ambigues():
    d = parse_date_detail("03/04/2026")
    assert d.date == date(2026, 4, 3) and d.ambigu
    assert parse_date("03/04/2026", ordre="MDY") == date(2026, 3, 4)
    assert parse_date_detail("13/04/2026").ambigu is False
    assert parse_date("04/13/2026") == date(2026, 4, 13)


@pytest.mark.parametrize("texte", ["", None, "31/02/2026", "pas de date", "99/99/9999"])
def test_dates_invalides(texte):
    assert parse_date(texte) is None


# --- masses et unités -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("texte", "kg"),
    [
        ("1 234,5 kg", "1234.500"),
        ("12.5 KGS", "12.500"),
        ("500 g", "0.500"),
        ("2 t", "2000.000"),
        ("10 lbs", "4.536"),
        ("1234", "1234.000"),
        ("Gross weight: 1,250.75 kg", "1250.750"),
        ("0,3333 kg", "0.333"),
        ("12 kilos", "12.000"),
    ],
)
def test_masses(texte, kg):
    assert parse_weight_kg(texte) == D(kg)


def test_masse_illisible():
    assert parse_weight_kg("abc") is None
    assert parse_weight_kg("-5 kg") is None


@pytest.mark.parametrize(
    ("texte", "code"),
    [
        ("pcs", "C62"),
        ("PCE", "C62"),
        ("pièces", "C62"),
        ("units", "C62"),
        ("kg", "KGM"),
        ("litres", "LTR"),
        ("m2", "MTK"),
        ("m²", "MTK"),
        ("paires", "PR"),
        ("pairs", "PR"),
        ("m", "MTR"),
        ("sets", "SET"),
        ("zorglub", "inconnue"),
    ],
)
def test_unites(texte, code):
    assert normalize_unit(texte).code == code


def test_unite_brute_conservee():
    u = normalize_unit("zorglub")
    assert u.brut == "zorglub" and not u.connue
    assert normalize_unit("pcs").entiere and not normalize_unit("kg").entiere


# --- devises ---------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("texte", "attendu"),
    [
        ("USD", "USD"),
        ("eur", "EUR"),
        ("€", "EUR"),
        ("£", "GBP"),
        ("US$", "USD"),
        ("HK$", "HKD"),
        ("12 euros", "EUR"),
        ("RMB", "CNY"),
        ("₩", "KRW"),
        ("CHF", "CHF"),
        ("", None),
        ("12,00", None),
        ("XYZ", "inconnue"),
        ("USD / EUR", "inconnue"),
    ],
)
def test_devises(texte, attendu):
    assert normalize_currency(texte) == attendu


def test_dollar_ambigu():
    assert normalize_currency("$") == "inconnue"
    assert normalize_currency("$", pays_vendeur="US") == "USD"
    assert normalize_currency("$", pays_vendeur="CA") == "CAD"
    assert normalize_currency("$", pays_vendeur="FR") == "inconnue"
    assert normalize_currency("$", codes_iso_page=["USD", "EUR"]) == "USD"
    assert normalize_currency("$", codes_iso_page=["USD", "CAD"]) == "inconnue"
    assert normalize_currency("¥") == "inconnue"
    assert normalize_currency("¥", pays_vendeur="JP") == "JPY"
    assert normalize_currency("¥", pays_vendeur="CN") == "CNY"


# --- pays ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("texte", "iso"),
    [
        ("Chine", "CN"),
        ("China", "CN"),
        ("CN", "CN"),
        ("cn", "CN"),
        ("Allemagne", "DE"),
        ("Germany", "DE"),
        ("Alemania", "DE"),
        ("États-Unis", "US"),
        ("United States of America", "US"),
        ("Estados Unidos", "US"),
        ("Viêt Nam", "VN"),
        ("the Netherlands", "NL"),
        ("Pays-Bas", "NL"),
        ("Made in China", "CN"),
        ("Royaume-Uni", "GB"),
        ("Corée du Sud", "KR"),
        ("Turquie", "TR"),
        ("FRA", "FR"),
        ("Atlantide", None),
        ("ZZ", None),
    ],
)
def test_pays(texte, iso):
    assert country_to_iso2(texte) == iso


# --- incoterms ------------------------------------------------------------------------------------------


def test_incoterms():
    assert parse_incoterm("FOB Shanghai").code == "FOB"
    assert parse_incoterm("FOB Shanghai").lieu == "Shanghai"
    i = parse_incoterm("Incoterms 2020: CIF Le Havre")
    assert (i.code, i.lieu) == ("CIF", "Le Havre")
    assert parse_incoterm("Ex Works Lyon").code == "EXW"
    assert parse_incoterm("Delivered Duty Paid").code == "DDP"
    assert parse_incoterm("DDU Paris").ancien is True
    assert parse_incoterm("fob").code == "FOB"
    assert parse_incoterm("Payment 30 days") is None


# --- références ------------------------------------------------------------------------------------------


def test_norm_ref():
    assert norm_ref("inv-2026/0815") == "INV20260815"
    assert norm_ref("Réf. é-12") == "REFE12"
    assert norm_ref_containment("INV-000123") == "INV123"
    assert norm_ref_containment("A00123") == "A00123"


def test_ref_egales_compatibles():
    assert ref_egales("INV 2026-0815", "inv20260815")
    assert not ref_egales("", "")
    assert ref_compatibles("INV-2026-0815", "2026-0815")  # inclusion, 8 caractères
    assert ref_compatibles("FAC-000815", "815-X") is False
    assert ref_compatibles("INV-0001234", "INV-1234")  # zéros de tête d'un segment numérique
    assert ref_compatibles("FAC/2026/0001-0", "0001-0")  # troncature, forme norm_ref de 5 caractères (D-805)
    assert ref_compatibles("EXP-26-00950", "6-00950")
    assert not ref_compatibles("FAC/2026/0001-0", "001-0")  # 4 caractères : trop court
    assert not ref_compatibles("INV-1234", "1234")  # la plus courte a moins de 5 caractères
    assert ref_compatibles("12345", "AB12345CD")


def test_mrn():
    mrn = "26FR0000000000001A"
    assert est_mrn(mrn)
    assert not est_mrn("26FR123")
    assert mrn_prefixe(mrn) == "26FR00000000000"
    assert mrn_egaux(mrn, "26FR0000000000001B")  # version rectificative : même préfixe
    assert not mrn_egaux(mrn, "26FR0000000000101A")


def test_ref_transport():
    assert ref_transport_egales("999-11112222", "99911112222")
    assert ref_transport_egales("999 1111 2222", "999-1111-2222")
    assert ref_transport_egales("LTA 999-11112222", "99911112222")
    assert ref_transport_egales("AWB: 999-11112222", "999/11112222")
    assert norm_ref_transport("B/L MSCU 1234567") == "MSCU1234567"
    assert ref_transport_compatibles("MSCU1234567", "1234567")
    assert not ref_transport_compatibles("MSCU1234567", "1234")


# --- identifiants fiscaux ----------------------------------------------------------------------------------


def test_tva():
    assert normalize_vat("fr 32 000 123 459") == "FR32000123459"
    assert normalize_vat("TVA : FR32000123459") == "FR32000123459"
    assert normalize_vat("pas une tva") is None
    siren = "000123459"
    tva = tva_fr_depuis_siren(siren)
    assert tva == f"FR{cle_tva_fr(siren)}{siren}"
    assert tva_fr_valide(tva) is True
    assert tva_fr_valide("FR00" + siren) is False
    assert tva_fr_valide("FRA1" + siren) is None  # clé alphabétique : non vérifiable
    assert tva_fr_valide("DE123456789") is None


def test_siren():
    assert siren_depuis_tva("FR99000123459") == "000123459"  # même si la clé est abîmée
    assert siren_depuis_tva("DE123456789") is None
    assert siren_depuis_siret("000 123 459 00017") == "000123459"
    assert extraire_siren("SIRET : 000 123 459 00017") == "000123459"
    assert extraire_siren("SIREN 000123459") == "000123459"
    assert extraire_siren("FR12000123459") == "000123459"
    assert siren_luhn_valide("732829320")
    assert not siren_luhn_valide("732829321")
    assert normalize_eori("fr 000123459 00000") == "FR00012345900000"


def test_codes_marchandise():
    assert code_marchandise("8471.30.00") == "84713000"
    assert code_marchandise("847130") == "847130"
    assert code_marchandise("8471300000") == "8471300000"
    assert code_marchandise("847130000") is None  # 9 chiffres : jamais complété ici
    assert code_marchandise("84 71 30") == "847130"
    assert code_sh6("8471.30.00") == "847130"


def test_identifier_transitaire_regle_unique():
    # D-1211 : une seule règle pour le regroupement, l'imputation des avoirs et le choix de la grille.
    from controldone.model.referentiel import Transitaire
    from controldone.normalize.parties import identifier_transitaire

    ts = [
        Transitaire(id="tra_1", nom="Transit FICTIF", tva="FR11000555550", alias=["TF Logistique"]),
        Transitaire(id="tra_2", nom="Douane Express FICTIF", tva=None),
    ]
    assert identifier_transitaire("FR 11 000555550", None, ts) == "tra_1"
    assert identifier_transitaire(None, "transit fictif", ts) == "tra_1"
    assert identifier_transitaire(None, "TF LOGISTIQUE", ts) == "tra_1"
    assert identifier_transitaire(None, "TRANSIT FICTIF SAS", ts) == "tra_1"  # mots entiers
    assert identifier_transitaire(None, "TRANSIT FICTIFS SAS", ts) is None  # pas une sous-chaîne
    assert identifier_transitaire(None, "TRANSIT FICTIF / DOUANE EXPRESS FICTIF", ts) is None  # ambigu
    assert identifier_transitaire(None, None, ts) is None


def test_cle_emetteur_reconnait_le_nom_complet():
    from controldone.model.champs import Partie
    from controldone.model.referentiel import Transitaire
    from controldone.recouvrement.imputation import cle_emetteur
    from controldone.testing import vs

    ts = [Transitaire(id="tra_1", nom="Transit FICTIF", tva="FR11000555550")]
    p = Partie(nom=vs("avoir.emetteur.nom", "TRANSIT FICTIF SAS", document_id="d"))
    assert cle_emetteur(p, ts) == "tra_1"


def test_references_proches_d3702():
    from controldone.normalize.refs import distance_bornee, mrn_proches, ref_transport_proches

    assert distance_bornee("ABCD", "ABXD", 2) == 1 and distance_bornee("AAAA", "BBBB", 2) == 3
    # MRN fictifs : une lecture OCR (pays, 5/S) reste proche ; un autre envoi ne l'est pas
    assert mrn_proches("26FA32BIVU7IEWGFWW", "26FR32BIVU7IEWGFWW")
    assert mrn_proches("26FRGKICHEPGSTEFAS", "26FRGK3CHEPG9T5FA4")
    assert not mrn_proches("26FRNQAXEOLD2XTWZ0", "26FRG9YL3TE5MNH5W6")
    assert not mrn_proches("26FR32BIVU7", "26FR32BIVU7")  # trop court
    assert ref_transport_proches("DEM0828978588", "DEMO028970508")
    assert ref_transport_proches("DEMO 6091 / 37653", "DEMO609137653")
    assert not ref_transport_proches("DEMO087829269", "DEMO609137653")
    assert not ref_transport_proches("FICU126999737", "FICU705793239")
    assert not ref_transport_proches("ABC123", "ABC124")  # trop court pour une lecture approchée
