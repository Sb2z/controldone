"""Propriétés de la lecture et du formatage des montants (normalize/amounts.py, formatage.py, services/saisie.py).

Un montant écrit selon les usages français, anglais, allemand, suisse ou indien, avec ou sans devise, signe moins
(avant, après, Unicode) ou parenthèses, est relu à l'identique en ``Decimal`` (D-3903).
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from hypothesis import assume, example, given
from hypothesis import strategies as st

from controldone.controls.tolerances import arrondi_devise
from controldone.formatage import format_montant, format_nombre
from controldone.normalize.amounts import parse_amount, parse_decimal, parse_int, parse_nombre
from controldone.services.plateforme import RequeteInvalide
from controldone.services.saisie import MONTANT_MAX, montant_saisi

pytestmark = pytest.mark.proprietes

# (séparateur de milliers, séparateur décimal)
STYLES = {
    "fr": (" ", ","),
    "fr_espace": (" ", ","),
    "fr_fine": (" ", ","),
    "en": (",", "."),
    "de": (".", ","),
    "ch": ("'", "."),
    "ch_typo": ("’", "."),
    "sans_groupe_point": ("", "."),
    "sans_groupe_virgule": ("", ","),
}


def grouper(entier: str, sep: str, indien: bool = False) -> str:
    if not sep or len(entier) <= 3:
        return entier
    tete, queue = entier[:-3], entier[-3:]
    groupes = [queue]
    pas = 2 if indien else 3
    while tete:
        groupes.insert(0, tete[-pas:])
        tete = tete[:-pas]
    return sep.join(groupes)


def ecrire(valeur: Decimal, decimales: int, style: str) -> str:
    """Écriture imprimée de ``|valeur|`` avec ``decimales`` chiffres après la virgule."""
    texte = format(abs(valeur).quantize(Decimal(1).scaleb(-decimales)), "f")
    entier, _, frac = texte.partition(".")
    if style == "in":
        corps = grouper(entier, ",", indien=True)
        dec = "."
    else:
        sep, dec = STYLES[style]
        corps = grouper(entier, sep)
    return corps + (dec + frac if frac else "")


montants = st.decimals(
    min_value=0, max_value=Decimal("999999999999"), places=2, allow_nan=False, allow_infinity=False
)
styles = st.sampled_from([*STYLES, "in"])


def _attendu(v: Decimal, decimales: int) -> Decimal:
    return abs(v).quantize(Decimal(1).scaleb(-decimales))


@given(v=montants, decimales=st.sampled_from([0, 1, 2]), style=styles)
@example(v=Decimal("1234567.89"), decimales=2, style="in")
@example(v=Decimal("1234.5"), decimales=2, style="ch")
@example(v=Decimal("0.05"), decimales=2, style="fr")
def test_ecriture_relue_a_l_identique(v, decimales, style):
    texte = ecrire(v, decimales, style)
    lu = parse_nombre(texte)
    assert lu is not None, texte
    assert lu.valeur == _attendu(v, decimales), texte
    assert not lu.negatif
    assert isinstance(lu.valeur, Decimal)


@given(
    v=montants,
    decimales=st.sampled_from([0, 2]),
    style=styles,
    devise=st.sampled_from(["EUR", "USD", "CHF", "GBP", "INR", "CNY"]),
    place=st.sampled_from(["avant", "apres", "sans"]),
    signe=st.sampled_from(["aucun", "moins", "moins_unicode", "moins_apres", "parentheses", "moins_devise"]),
)
def test_montant_avec_devise_et_signe(v, decimales, style, devise, place, signe):
    nombre = ecrire(v, decimales, style)
    if place == "avant":
        corps = f"{devise} {nombre}"
    elif place == "apres":
        corps = f"{nombre} {devise}"
    else:
        corps = nombre
    if signe == "moins":
        texte = f"-{nombre}" if place == "sans" else corps.replace(nombre, "-" + nombre)
    elif signe == "moins_unicode":
        texte = corps.replace(nombre, "−" + nombre)
    elif signe == "moins_apres":
        texte = corps + "-"
    elif signe == "parentheses":
        texte = f"({corps})"
    elif signe == "moins_devise":
        texte = f"-{devise} {nombre}" if place != "apres" else f"-{nombre} {devise}"
    else:
        texte = corps
    lu = parse_amount(texte, devise=None if place != "sans" else devise)
    assert lu is not None, texte
    assert lu.valeur == _attendu(v, decimales), texte
    assert lu.negatif is (signe != "aucun"), texte
    assert lu.devise == devise, texte
    assert lu.valeur_signee == (-lu.valeur if signe != "aucun" else lu.valeur)


@given(
    v=st.decimals(
        min_value=Decimal("-999999999"),
        max_value=Decimal("999999999"),
        places=2,
        allow_nan=False,
        allow_infinity=False,
    ),
    devise=st.sampled_from(["EUR", "USD", "CHF", "JPY", "KRW", "GBP"]),
)
def test_format_montant_puis_lecture(v, devise):
    """``format_montant`` (français, devise après) est relu à la valeur arrondie à l'unité de la devise."""
    texte = format_montant(v, devise)
    lu = parse_amount(texte)
    assert lu is not None, texte
    assert lu.devise == devise
    attendu = arrondi_devise(v, devise)
    assert lu.valeur_signee == attendu or (attendu == 0 and lu.valeur == 0), texte


@given(
    v=st.decimals(
        min_value=Decimal("-1e12"), max_value=Decimal("1e12"), places=6, allow_nan=False, allow_infinity=False
    )
)
def test_format_nombre_aller_retour_avec_separateur_connu(v):
    """Avec le séparateur décimal connu (« , »), ``format_nombre`` est relu exactement, même avec 3 décimales."""
    texte = format_nombre(v)
    relu = parse_decimal(texte, separateur_decimal=",")
    assert relu == v or (v == 0 and relu == 0), texte


@given(
    n=st.integers(min_value=-(10**12), max_value=10**12),
    style=st.sampled_from(["fr", "fr_fine", "en", "de", "ch"]),
)
def test_entiers(n, style):
    texte = ("-" if n < 0 else "") + ecrire(Decimal(n), 0, style)
    assert parse_int(texte) == n


@given(st.text(max_size=60))
def test_lecture_robuste_sur_texte_quelconque(texte):
    """Jamais d'exception, valeur toujours positive ou nulle et finie, jamais de float."""
    lu = parse_nombre(texte)
    if lu is not None:
        assert isinstance(lu.valeur, Decimal)
        assert lu.valeur.is_finite() and lu.valeur >= 0
        assert lu.texte in texte
    m = parse_amount(texte)
    assert m is None or (isinstance(m.valeur, Decimal) and m.valeur >= 0)


@given(st.text(alphabet="0123456789 .,'’-€EURU  ", max_size=25))
def test_lecture_robuste_sur_chiffres_et_separateurs(texte):
    lu = parse_nombre(texte)
    assert lu is None or (lu.valeur.is_finite() and lu.valeur >= 0)


# --- saisie d'un montant dans l'interface (Decimal exact ou erreur lisible) ---------------------------------------


@given(
    v=st.decimals(
        min_value=Decimal("0.01"), max_value=MONTANT_MAX, places=2, allow_nan=False, allow_infinity=False
    ),
    style=st.sampled_from(
        ["fr", "fr_espace", "fr_fine", "en", "de", "ch", "sans_groupe_point", "sans_groupe_virgule"]
    ),
    euro=st.sampled_from(["", " €", " EUR", "€ "]),
)
def test_saisie_aller_retour(v, style, euro):
    nombre = ecrire(v, 2, style)
    texte = (euro + nombre) if euro.endswith(" ") else (nombre + euro)
    assert montant_saisi(texte) == v


@given(st.text(max_size=45))
def test_saisie_jamais_d_erreur_500(texte):
    try:
        v = montant_saisi(texte, negatif=True, zero=True)
    except RequeteInvalide:
        return
    assert isinstance(v, Decimal) and v.is_finite()
    assert abs(v) <= MONTANT_MAX
    assert v == v.quantize(Decimal("0.01"))


@given(st.text(alphabet="0123456789 .,'", min_size=1, max_size=20))
def test_saisie_separateurs_melanges(texte):
    """Une saisie acceptée ne perd jamais de chiffre : la valeur relue a les mêmes chiffres significatifs."""
    try:
        v = montant_saisi(texte, zero=True)
    except RequeteInvalide:
        return
    chiffres_saisis = "".join(c for c in texte if c.isdigit()).lstrip("0")
    chiffres_lus = format(v, "f").replace(".", "").lstrip("0").rstrip("0")
    assume(chiffres_lus)
    assert chiffres_saisis.rstrip("0") == chiffres_lus, (texte, v)
