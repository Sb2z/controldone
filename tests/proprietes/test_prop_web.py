"""Propriétés de sécurité de l'interface : redirection interne seulement (web/rendu.py ``retour_sur``) et
validation stricte des paramètres de liste (web/listes.py) — toute entrée donne une valeur sûre ou
``RequeteInvalide`` (page 400), jamais une erreur 500 (D-3903)."""

from __future__ import annotations

from urllib.parse import urlencode, urlsplit

import pytest
from hypothesis import given
from hypothesis import strategies as st
from starlette.requests import Request

from controldone.services.plateforme import RequeteInvalide
from controldone.web.listes import (
    PAGE_MAX,
    TAILLES,
    TEXTE_MAX,
    Param,
    Requete,
    _numeros,
    decalage,
    lire_requete,
    paginer,
)
from controldone.web.rendu import retour_sur

pytestmark = pytest.mark.proprietes

DEFAUT = "/espace"

# --- redirection ------------------------------------------------------------------------------------------------

hostiles = st.sampled_from([
    "//evil.example", "/\\evil.example", "https://evil.example", "javascript:alert(1)", "/%2F%2Fevil.example",
    "\\\\evil.example", "/\t/evil.example", " /espace", "/espace\r\nLocation: //evil", "///evil.example",
    "http:/evil", "/espace@evil.example", "data:text/html,x",
])


@given(st.one_of(st.text(max_size=60), hostiles, st.from_regex(r"\A/[ -~]{0,40}\Z"), st.none(), st.integers()))
def test_retour_toujours_interne(valeur):
    r = retour_sur(valeur, DEFAUT)
    assert r in (DEFAUT, valeur)
    morceaux = urlsplit(r)
    assert morceaux.scheme == "" and morceaux.netloc == ""
    assert r.startswith("/") and not r.startswith("//")
    assert "\\" not in r and ":" not in r and "@" not in r
    assert all(0x21 <= ord(c) < 0x7F for c in r)


@given(st.from_regex(r"\A/[A-Za-z0-9_\-]{1,20}(?:/[A-Za-z0-9_\-]{1,20}){0,3}(?:\?[a-z]{1,5}=[A-Za-z0-9]{0,8})?\Z"))
def test_retour_chemin_interne_conserve(chemin):
    assert retour_sur(chemin, DEFAUT) == chemin


# --- paramètres de liste --------------------------------------------------------------------------------------

PARAMS = {
    "q": Param("Recherche"),
    "statut": Param("Statut", "choix", ("ouvert", "clos")),
    "min": Param("Montant minimal", "montant"),
    "du": Param("Du", "date"),
}
TRIS = ("date", "-date", "montant", "-montant")


def requete(paires: list[tuple[str, str]]) -> Request:
    return Request({"type": "http", "method": "GET", "path": "/liste", "headers": [],
                    "query_string": urlencode(paires).encode()})


noms = st.sampled_from(["q", "statut", "min", "du", "tri", "page", "taille", "inconnu"])
valeurs = st.one_of(st.text(max_size=100), st.sampled_from(["ouvert", "clos", "1 234,56", "2026-10-06", "1999-01-01",
                                                            "date", "-montant", "²", "0", "10001", "25", "50", "100",
                                                            "-1", "1e3", "NaN", "\x00", "a\x1fb"]))


@given(st.lists(st.tuples(noms, valeurs), max_size=8))
def test_lire_requete_valeur_sure_ou_400(paires):
    try:
        req = lire_requete(requete(paires), PARAMS, TRIS, "-date")
    except RequeteInvalide:
        return
    assert 1 <= req.page <= PAGE_MAX
    assert req.taille in TAILLES
    assert req.tri in TRIS
    assert set(req.filtres) <= set(PARAMS) and set(req.brut) == set(req.filtres)
    for v in req.brut.values():
        assert len(v) <= TEXTE_MAX and not any(ord(c) < 0x20 or ord(c) == 0x7F for c in v)
    if "statut" in req.filtres:
        assert req.filtres["statut"] in ("ouvert", "clos")
    # les liens réémis ne portent que des paramètres connus, et se relisent à l'identique
    relue = lire_requete(requete(list(_qs(req.url()))), PARAMS, TRIS, "-date")
    assert relue.brut == req.brut and relue.tri == req.tri and relue.taille == req.taille
    assert relue.page == req.page


def _qs(url: str):
    from urllib.parse import parse_qsl

    return parse_qsl(urlsplit(url).query, keep_blank_values=True)


@given(page=st.integers(1, PAGE_MAX), taille=st.sampled_from(TAILLES), n=st.integers(0, 1000))
def test_pagination_couvre_tout_sans_doublon(page, taille, n):
    elements = list(range(n))
    req = Requete(filtres={}, brut={}, tri="-date", tri_defaut="-date", page=page, taille=taille)
    p = paginer(elements, req)
    assert 1 <= p.page <= p.pages
    assert p.elements == elements[(p.page - 1) * taille: p.page * taille]
    assert p.total == n
    if n:
        assert p.debut == (p.page - 1) * taille + 1 and p.fin == p.debut + len(p.elements) - 1
    req2 = Requete(filtres={}, brut={}, tri="-date", tri_defaut="-date", page=page, taille=taille)
    assert decalage(req2, n) == (p.page - 1) * taille


@given(pages=st.integers(1, PAGE_MAX), data=st.data())
def test_numeros_de_page(pages, data):
    page = data.draw(st.integers(1, pages))
    nums = _numeros(page, pages)
    vus = [x for x in nums if x is not None]
    assert vus == sorted(set(vus))
    assert {1, pages, page} <= set(vus)
    assert all(nums[i] is not None or nums[i + 1] is not None for i in range(len(nums) - 1))
    assert len(nums) <= 9
