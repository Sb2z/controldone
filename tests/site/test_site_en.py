"""English version of the public site (site/en/): links, language switcher, banned phrasings, sources."""

from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import unquote, urlsplit

import pytest
from test_site import DOMAINES_AUTORISES, PAGES, _lire, verifier_ressources

from controldone.guardrails import PHRASE_RENVOI, check_text

SITE = Path(__file__).resolve().parents[2] / "site"
EN = SITE / "en"
#: English page -> French counterpart.
CORRESPONDANCE = {
    "index.html": "index.html",
    "pricing.html": "tarifs.html",
    "demo.html": "demonstration.html",
    "method.html": "methode.html",
    "contact.html": "contact.html",
}
PAGES_EN = [EN / n for n in CORRESPONDANCE]
NOTE_JURIDIQUE = "French version prevails; draft to be reviewed by a lawyer"

#: English mirror of SPEC §3.2 (case-insensitive, simple plural forms).
FORMULATIONS_INTERDITES_EN = [
    "correct code",
    "right code",
    "wrong classification",
    "misclassified",
    "should be classified",
    "duty owed",
    "duties owed",
    "tax owed",
    "overpaid",
    "refund of duties",
    "duty refund",
    "incorrect customs value",
    "undervaluation",
    "overvaluation",
    "incorrect origin",
    "false origin",
    "preference applies",
    "applicable preference",
    "wrong rate",
    "incorrect rate",
    "the applicable rate is",
    "illegal",
    "unlawful",
    "non-compliant with the regulations",
    "irregular",
    "infringement",
    "fraud",
    "fraudulent",
    "we claim on behalf of",
    "we claim",
    "on behalf of our client",
    "mandated by",
    "you must file a refund request",
    "file a claim with customs",
    "the declaration must be amended",
    "we guarantee",
    "certified compliant",
]
_MOTIFS_EN = [
    (
        e,
        re.compile(
            r"(?<![a-z])" + r"\s+".join(re.escape(m) for m in e.split()) + r"(?:s|es|ly)?(?![a-z])",
            re.IGNORECASE,
        ),
    )
    for e in FORMULATIONS_INTERDITES_EN
]


def check_text_en(texte: str) -> list[str]:
    t = " ".join(texte.replace("-", " - ").split()).replace(" - ", "-")
    return [e for e, m in _MOTIFS_EN if m.search(t)]


def test_controle_anglais_detecte():
    assert check_text_en("We guarantee the correct code and the duty owed.") == [
        "correct code",
        "duty owed",
        "we guarantee",
    ]
    assert check_text_en("Fraudulent, ILLEGAL, overpaid amounts") == ["overpaid", "illegal", "fraudulent"]
    assert check_text_en("We claim on behalf of you") == ["we claim on behalf of", "we claim"]
    assert check_text_en("The difference found between the documents.") == []


def test_pages_anglaises_presentes():
    assert {p.name for p in EN.glob("*.html")} == set(CORRESPONDANCE)
    for nom in ("cgv.html", "mentions-legales.html", "confidentialite.html", "dpa.html"):
        assert not (EN / nom).exists(), "les pages juridiques restent en français seulement"


@pytest.mark.parametrize("page", PAGES_EN, ids=lambda p: p.name)
def test_aucune_formulation_interdite_en(page):
    doc = _lire(page)
    for texte in (doc.visible, " | ".join(doc.attrs_visibles)):
        assert check_text_en(texte) == [], f"{page.name} : {check_text_en(texte)}"
        assert check_text(texte) == [], f"{page.name} : {check_text(texte)}"  # citations françaises comprises


@pytest.mark.parametrize("page", PAGES, ids=lambda p: p.name)
def test_pages_francaises_propres_et_lien_anglais(page):
    doc = _lire(page)
    assert check_text(doc.visible) == [] and check_text(" | ".join(doc.attrs_visibles)) == []
    liens_en = [v for t, a, v in doc.liens if t == "a" and v.startswith("en/")]
    assert len(liens_en) == 2, f"{page.name} : sélecteur de langue (menu et menu mobile)"
    attendu = next((f"en/{en}" for en, fr in CORRESPONDANCE.items() if fr == page.name), "en/index.html")
    assert set(liens_en) == {attendu}
    assert (SITE / attendu).exists()


@pytest.mark.parametrize("page", PAGES_EN, ids=lambda p: p.name)
def test_structure_et_liens_en(page):
    brut = page.read_text(encoding="utf-8")
    assert '<html lang="en">' in brut
    doc = _lire(page)
    verifier_ressources(page, doc, "../")  # mêmes règles que le site français, chemins relatifs à en/
    for tag, attr, val in doc.liens:
        u = urlsplit(val)
        if u.scheme == "mailto":
            continue
        if u.scheme:
            assert u.scheme == "https" and tag == "a" and attr == "href", f"{page.name} : {val}"
            assert u.hostname in DOMAINES_AUTORISES, f"{page.name} : lien externe non autorisé {val}"
            continue
        cible = (page.parent / unquote(u.path)).resolve() if u.path else page
        assert cible.exists(), f"{page.name} : lien cassé {val}"
        assert SITE.resolve() in cible.parents, f"{page.name} : sort du site {val}"
        if u.fragment and cible.suffix == ".html":
            assert u.fragment in _lire(cible).ids, f"{page.name} : ancre absente {val}"
    # sélecteur de langue vers la page française correspondante
    fr = f"../{CORRESPONDANCE[page.name]}"
    assert [v for t, a, v in doc.liens if t == "a" and v == fr], f"{page.name} : lien vers {fr}"


@pytest.mark.parametrize("page", PAGES_EN, ids=lambda p: p.name)
def test_note_pages_juridiques(page):
    doc = _lire(page)
    assert NOTE_JURIDIQUE in doc.visible
    for nom in ("mentions-legales.html", "cgv.html", "confidentialite.html", "dpa.html"):
        assert any(v.startswith(f"../{nom}") for _t, _a, v in doc.liens), nom


@pytest.mark.parametrize(("en", "fr"), CORRESPONDANCE.items())
def test_memes_sources_que_la_version_francaise(en, fr):
    """Rien d'inventé : les liens sortants (sources citées) sont exactement ceux de la page française."""

    def externes(p: Path) -> set[str]:
        return {v for _t, _a, v in _lire(p).liens if urlsplit(v).scheme == "https"}

    assert externes(EN / en) == externes(SITE / fr)


def test_chiffres_identiques():
    tarifs = _lire(EN / "pricing.html").visible.replace("\u00a0", " ")
    for attendu in (
        "€390",
        "20%",
        "€99",
        "€199",
        "€349",
        "€487.50",
        "€1,485.00",
        "diagnostics are offered",
        "still due",
    ):
        assert attendu in tarifs, attendu
    accueil = _lire(EN / "index.html").visible.replace("\u00a0", " ")
    for attendu in (
        "€3 per item",
        "€150",
        "1 September 2026",
        "1 September 2027",
        "30 September 2027",
        "2026/382",
        "2025/2083",
        "2026/2108",
        "EUR 2,356.28",
        "160 fictitious files",
        "188",
    ):
        assert attendu in accueil, attendu


@pytest.mark.parametrize("page", PAGES_EN, ids=lambda p: p.name)
def test_offered_always_with_commission(page):
    texte = _lire(page).visible.replace("\u00a0", " ")
    for m in re.finditer(r"\boffered\b", texte):
        voisinage = texte[max(0, m.start() - 250) : m.end() + 250]
        assert "still due" in voisinage, f"{page.name} : …{voisinage}…"
    assert not re.search(r"\bfree\b", texte, re.IGNORECASE), f"{page.name} : « free »"


def test_demo_marquee_fictive():
    texte = _lire(EN / "demo.html").visible
    assert "FICTITIOUS DATA" in texte
    assert texte.count("FICTITIOUS DATA") >= 4
    assert "FICTITIOUS DATA" in _lire(EN / "index.html").visible


def test_phrase_de_renvoi_citee():
    for nom in ("index.html", "method.html"):
        assert PHRASE_RENVOI in _lire(EN / nom).visible, nom
