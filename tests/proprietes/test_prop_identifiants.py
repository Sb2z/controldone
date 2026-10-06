"""Propriétés des identifiants : TVA (clé FR, SIREN), MRN (préfixe stable, confusions OCR), références (D-3903)."""

from __future__ import annotations

import re

import pytest
from hypothesis import assume, given
from hypothesis import strategies as st

from controldone.normalize.fiscal import (
    cle_tva_fr,
    extraire_siren,
    normalize_vat,
    siren_depuis_tva,
    siren_luhn_valide,
    tva_fr_depuis_siren,
    tva_fr_valide,
)
from controldone.normalize.refs import (
    CONFUSION_OCR,
    cle_confusion_ocr,
    est_mrn,
    mrn_egaux,
    mrn_prefixe,
    norm_ref,
    ref_compatibles,
    ref_egales,
)

pytestmark = pytest.mark.proprietes

sirens = st.from_regex(r"\A[0-9]{9}\Z")
alnum = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
pays = st.sampled_from(["FR", "DE", "IT", "ES", "BE", "NL", "EL", "PL", "CN", "US"])


def bruiter(t: str, data) -> str:
    """Casse, espaces, points et tirets insérés au hasard (lecture OCR ou saisie humaine)."""
    sortie = []
    for c in t:
        sortie.append(c.lower() if data.draw(st.booleans()) else c)
        sortie.append(data.draw(st.sampled_from(["", "", "", " ", ".", "-", " "])))
    return "".join(sortie)


@given(siren=sirens, data=st.data())
def test_tva_fr_cle_valide_et_bruit(siren, data):
    tva = tva_fr_depuis_siren(siren)
    assert tva_fr_valide(tva) is True
    assert siren_depuis_tva(tva) == siren
    lue = bruiter(tva, data)
    assert normalize_vat(lue) == tva
    assert tva_fr_valide(lue) is True
    assert extraire_siren(lue) == siren


@given(siren=sirens, autre=st.integers(0, 99))
def test_tva_fr_mauvaise_cle(siren, autre):
    cle = f"{autre:02d}"
    assume(cle != cle_tva_fr(siren))
    assert tva_fr_valide(f"FR{cle}{siren}") is False
    assert siren_depuis_tva(f"FR{cle}{siren}") == siren  # clé abîmée : SIREN quand même lisible


@given(siren=sirens)
def test_cle_tva_formule(siren):
    assert cle_tva_fr(siren) == f"{(12 + 3 * (int(siren) % 97)) % 97:02d}"
    assert len(cle_tva_fr(siren)) == 2


@given(st.text(max_size=30))
def test_normalize_vat_idempotent(x):
    t = normalize_vat(x)
    if t is not None:
        assert re.fullmatch(r"[A-Z]{2}[A-Z0-9]{2,13}", t)
        assert normalize_vat(t) == t


@given(p=pays, corps=st.text(alphabet="0123456789", min_size=8, max_size=12), prefixe=st.sampled_from(["", "TVA ", "VAT: ", "USt-IdNr. "]))
def test_normalize_vat_prefixes(p, corps, prefixe):
    assert normalize_vat(f"{prefixe}{p} {corps}") == p + corps


@given(st.from_regex(r"\A[0-9]{8}\Z"))
def test_luhn_un_chiffre_de_controle_exactement(base):
    valides = [d for d in "0123456789" if siren_luhn_valide(base + d)]
    assert len(valides) == 1


# --- MRN -----------------------------------------------------------------------------------------------------

mrns = st.builds(lambda a, p, r: f"{a:02d}{p}{r}", st.integers(0, 99), pays,
                 st.text(alphabet=alnum, min_size=14, max_size=14))


@given(mrn=mrns, data=st.data())
def test_mrn_normalisation(mrn, data):
    assert est_mrn(mrn)
    lu = bruiter(mrn, data)
    assert est_mrn(lu)
    assert norm_ref(lu) == mrn
    assert mrn_egaux(lu, mrn) and mrn_egaux(mrn, lu)
    assert mrn_prefixe(lu) == mrn[:15]


@given(mrn=mrns, fin=st.text(alphabet=alnum, min_size=3, max_size=3))
def test_mrn_version_rectificative_meme_prefixe(mrn, fin):
    """Les 3 derniers caractères peuvent changer entre versions : même préfixe stable, MRN égaux."""
    assert mrn_egaux(mrn, mrn[:15] + fin)


@given(st.text(max_size=25), st.text(max_size=25))
def test_mrn_egaux_symetrique(x, y):
    assert mrn_egaux(x, y) == mrn_egaux(y, x)
    if mrn_egaux(x, y):
        assert len(mrn_prefixe(x)) == 15


_CLASSES = {}
for _k, _v in CONFUSION_OCR.items():
    _CLASSES.setdefault(chr(_v), {chr(_v)}).add(chr(_k))


@given(ref=st.text(alphabet=alnum, min_size=1, max_size=20), data=st.data())
def test_cle_confusion_ocr_invariante(ref, data):
    """Remplacer un caractère par un autre de sa classe de confusion (0/O/Q/D, 1/I/L…) ne change pas la clé."""
    lue = []
    for c in ref:
        rep = c.translate(CONFUSION_OCR)
        classe = sorted(_CLASSES.get(rep, {c}))
        lue.append(data.draw(st.sampled_from(classe)))
    assert cle_confusion_ocr("".join(lue)) == cle_confusion_ocr(ref)
    assert cle_confusion_ocr(cle_confusion_ocr(ref)) == cle_confusion_ocr(ref)


@given(st.text(max_size=30))
def test_norm_ref_idempotent(x):
    n = norm_ref(x)
    assert norm_ref(n) == n
    assert re.fullmatch(r"[A-Z0-9]*", n)


@given(st.text(max_size=20), st.text(max_size=20))
def test_comparaisons_de_references_symetriques(x, y):
    assert ref_egales(x, y) == ref_egales(y, x)
    assert ref_compatibles(x, y) == ref_compatibles(y, x)
    if ref_egales(x, y):
        assert ref_compatibles(x, y)
