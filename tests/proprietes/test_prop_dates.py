"""Propriétés de la lecture des dates (normalize/dates.py) : toute date écrite dans un format reconnu est relue
à l'identique ; l'ambiguïté jour/mois est signalée et tranchée par l'ordre demandé (D-3903)."""

from __future__ import annotations

from datetime import date

import pytest
from hypothesis import given
from hypothesis import strategies as st

from controldone.normalize.dates import parse_date, parse_date_detail

pytestmark = pytest.mark.proprietes

dates = st.dates(min_value=date(1970, 1, 1), max_value=date(2069, 12, 31))
MOIS_FR = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre",
           "novembre", "décembre"]
MOIS_EN = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
           "November", "December"]
MOIS_DE = ["Januar", "Februar", "März", "April", "Mai", "Juni", "Juli", "August", "September", "Oktober",
           "November", "Dezember"]


@given(d=dates, fmt=st.sampled_from(["iso", "iso_slash", "dmy_slash", "dmy_point", "dmy_tiret", "dmy_court",
                                     "compact", "fr", "fr_maj", "en_us", "en_uk", "de", "es"]),
       prefixe=st.sampled_from(["", "Date : ", "Invoice date ", "Le "]))
def test_date_ecrite_relue(d, fmt, prefixe):
    j, m, a = d.day, d.month, d.year
    texte = {
        "iso": d.isoformat(),
        "iso_slash": f"{a}/{m:02d}/{j:02d}",
        "dmy_slash": f"{j:02d}/{m:02d}/{a}",
        "dmy_point": f"{j}.{m}.{a}",
        "dmy_tiret": f"{j:02d}-{m:02d}-{a}",
        "dmy_court": f"{j:02d}/{m:02d}/{a % 100:02d}",
        "compact": f"{a}{m:02d}{j:02d}",
        "fr": f"{'1er' if j == 1 else j} {MOIS_FR[m - 1]} {a}",
        "fr_maj": f"{j} {MOIS_FR[m - 1].upper()} {a}",
        "en_us": f"{MOIS_EN[m - 1]} {j}, {a}",
        "en_uk": f"{j} {MOIS_EN[m - 1][:3]} {a}",
        "de": f"{j}. {MOIS_DE[m - 1]} {a}",
        "es": f"{j} de {['enero', 'febrero', 'marzo', 'abril', 'mayo', 'junio', 'julio', 'agosto', 'septiembre', 'octubre', 'noviembre', 'diciembre'][m - 1]} de {a}",
    }[fmt]
    if fmt == "compact" and a < 1990:
        return  # format compact reconnu pour 19xx/20xx seulement : couvert par 1990+
    assert parse_date(prefixe + texte) == d, texte


@given(d=dates)
def test_ambiguite_jour_mois(d):
    texte = f"{d.month:02d}/{d.day:02d}/{d.year}"
    us = parse_date_detail(texte, ordre="MDY")
    assert us is not None and us.date == d
    lu = parse_date_detail(texte, ordre="DMY")
    if d.day > 12 or d.day == d.month:
        assert lu is not None and lu.date == d and not lu.ambigu
    else:
        assert us.ambigu
        assert lu is None or lu.ambigu


@given(st.text(max_size=40), st.sampled_from(["DMY", "MDY"]))
def test_lecture_robuste(texte, ordre):
    d = parse_date(texte, ordre=ordre)
    assert d is None or isinstance(d, date)
