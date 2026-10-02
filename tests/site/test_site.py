"""Site public statique (site/) : garde-fous juridiques, liens, bandeaux, pas de ressource externe."""

from __future__ import annotations

from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit

import pytest

from controldone.guardrails import PHRASE_RENVOI, check_text

SITE = Path(__file__).resolve().parents[2] / "site"
PAGES = sorted(SITE.glob("*.html"))
DEMO = SITE / "demo" / "report.html"
PAGES_JURIDIQUES = ["mentions-legales.html", "cgv.html", "confidentialite.html", "dpa.html"]
PAGES_ATTENDUES = [
    "index.html", "tarifs.html", "demonstration.html", "methode.html", "experts-comptables.html",
    "contact.html", *PAGES_JURIDIQUES,
]
BANDEAU_AVOCAT = "BROUILLON — À RELIRE PAR UN AVOCAT"

# Seules sources officielles (ou citées comme source d'un chiffre) autorisées en lien sortant.
DOMAINES_AUTORISES = {
    "taxation-customs.ec.europa.eu",
    "commission.europa.eu",
    "eur-lex.europa.eu",
    "www.impots.gouv.fr",
    "www.legifrance.gouv.fr",
    "www.cnil.fr",
    "www.douane.gouv.fr",
    "entreprendre.service-public.gouv.fr",
    "www.dehst.de",
    "kpmg.com",
}


class _Page(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.texte: list[str] = []
        self.attrs_visibles: list[str] = []
        self.liens: list[tuple[str, str, str]] = []  # (balise, attribut, valeur)
        self.ids: set[str] = set()
        self.balises: list[str] = []
        self._cache = 0

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        self.balises.append(tag)
        if tag in ("script", "style", "template"):
            self._cache += 1
        if "id" in a:
            self.ids.add(a["id"])
        for attr in ("href", "src", "action", "data", "poster", "srcset"):
            if a.get(attr):
                self.liens.append((tag, attr, a[attr]))
        for attr in ("alt", "title", "aria-label", "content"):
            if a.get(attr):
                self.attrs_visibles.append(a[attr])

    def handle_endtag(self, tag):
        if tag in ("script", "style", "template") and self._cache:
            self._cache -= 1

    def handle_data(self, data):
        if not self._cache:
            self.texte.append(data)

    @property
    def visible(self) -> str:
        return " ".join(" ".join(self.texte).split())


def _lire(p: Path) -> _Page:
    parser = _Page()
    parser.feed(p.read_text(encoding="utf-8"))
    return parser


def test_pages_attendues_presentes():
    noms = {p.name for p in PAGES}
    assert set(PAGES_ATTENDUES) <= noms
    assert (SITE / "assets" / "style.css").exists()
    assert (SITE / "README.md").exists()


@pytest.mark.parametrize("page", [*PAGES, DEMO], ids=lambda p: p.name)
def test_aucune_formulation_interdite(page):
    doc = _lire(page)
    for texte in (doc.visible, " | ".join(doc.attrs_visibles)):
        assert check_text(texte) == [], f"{page.name} : {check_text(texte)}"


@pytest.mark.parametrize("page", PAGES, ids=lambda p: p.name)
def test_pas_de_ressource_externe_ni_formulaire(page):
    doc = _lire(page)
    assert "form" not in doc.balises, "aucun formulaire : le contact passe par mailto"
    assert "script" not in doc.balises, "aucun script"
    for tag, attr, val in doc.liens:
        u = urlsplit(val)
        if u.scheme in ("", "mailto"):
            continue
        assert u.scheme == "https", f"{page.name} : {val}"
        assert attr == "href" and tag == "a", f"{page.name} : ressource externe chargée {tag}[{attr}]={val}"
        assert u.hostname in DOMAINES_AUTORISES, f"{page.name} : lien externe non autorisé {val}"
    feuilles = [v for t, a, v in doc.liens if t == "link" and a == "href" and v.endswith(".css")]
    assert feuilles == ["assets/style.css"], "une seule feuille de style partagée"


def test_rapport_demo_sans_ressource_externe():
    doc = _lire(DEMO)
    for _tag, attr, val in doc.liens:
        if attr == "src":
            assert val.startswith("data:"), val
        else:
            assert urlsplit(val).scheme in ("", "mailto", "data"), val


@pytest.mark.parametrize("page", [*PAGES, DEMO], ids=lambda p: p.name)
def test_liens_internes_resolus(page):
    doc = _lire(page)
    for _tag, _attr, val in doc.liens:
        u = urlsplit(val)
        if u.scheme or val.startswith("data:"):
            continue
        cible = (page.parent / unquote(u.path)).resolve() if u.path else page
        assert cible.exists(), f"{page.name} : lien cassé {val}"
        assert SITE.resolve() in cible.parents or cible == SITE.resolve(), f"{page.name} : sort du site {val}"
        if u.fragment and cible.suffix == ".html":
            assert u.fragment in _lire(cible).ids, f"{page.name} : ancre absente {val}"


@pytest.mark.parametrize("nom", PAGES_JURIDIQUES)
def test_pages_juridiques_brouillon_et_champs_a_completer(nom):
    doc = _lire(SITE / nom)
    assert BANDEAU_AVOCAT in doc.visible
    brut = (SITE / nom).read_text(encoding="utf-8")
    assert brut.index(BANDEAU_AVOCAT) < brut.index("<h1"), "le bandeau précède le titre"
    assert "[À COMPLÉTER" in doc.visible


def test_mentions_legales_sans_identite_inventee():
    texte = _lire(SITE / "mentions-legales.html").visible
    for champ in ("SIREN", "forme juridique", "adresse", "hébergeur", "directeur de la publication"):
        assert champ in texte, champ
    assert texte.count("[À COMPLÉTER") >= 8


def test_phrase_de_renvoi_exacte():
    for nom in ("index.html", "methode.html"):
        assert PHRASE_RENVOI in _lire(SITE / nom).visible, nom


def test_demonstration_marquee_fictive():
    assert "DONNÉES FICTIVES" in _lire(SITE / "demonstration.html").visible
    rapport = _lire(DEMO).visible
    assert "DONNÉES FICTIVES" in rapport
    for capture in ("rapport-synthese.png", "rapport-constat.png", "rapport-mobile.png"):
        assert (SITE / "demo" / "captures" / capture).exists()


def test_prix_annonces():
    tarifs = _lire(SITE / "tarifs.html").visible
    for attendu in ("390 EUR", "20 %", "99 EUR", "Trois diagnostics offerts"):
        assert attendu in tarifs.replace(" ", " ")


def test_cgv_clauses_essentielles():
    cgv = _lire(SITE / "cgv.html").visible.replace(" ", " ")
    for attendu in ("audit technique de cohérence", "40 EUR", "L441-10", "opposer", "envoie lui-même",
                    "droit français", "Confidentialité"):
        assert attendu in cgv, attendu


def test_dpa_sous_traitants():
    dpa = _lire(SITE / "dpa.html").visible
    for attendu in ("Union européenne", "modèle de langage", "Désactivable", "Stripe", "Mesures de sécurité",
                    "Sort des données", "audit"):
        assert attendu in dpa, attendu
