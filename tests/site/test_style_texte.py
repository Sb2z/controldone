"""Style des textes du site public (docs/marketing/RECHERCHE.md §3.2, décision D-5105).

Ce test complète le filtre juridique (`controldone.guardrails.check_text`) : il refuse les tics d'écriture qui font
« texte de modèle » (vocabulaire promotionnel, formules creuses), le tiret cadratin en incise et les noms de marques
exclues. Il porte sur le texte visible et les attributs lus (alt, title, aria-label, content).

Périmètre :
- liste de mots et d'expressions : pages commerciales FR et EN (les pages juridiques gardent leur vocabulaire) ;
- tirets en incise : toutes les pages du site, juridiques comprises ;
- marques exclues : tous les fichiers texte de `site/`.
Le rapport de démonstration (`site/demo/report.html`) est produit par le moteur et n'est pas couvert ici.
"""

from __future__ import annotations

import base64
import re
from pathlib import Path

import pytest
from test_site import PAGES_JURIDIQUES, _lire

SITE = Path(__file__).resolve().parents[2] / "site"
PAGES_FR = sorted(SITE.glob("*.html"))
PAGES_EN = sorted((SITE / "en").glob("*.html"))
PAGES_COMMERCIALES_FR = [p for p in PAGES_FR if p.name not in PAGES_JURIDIQUES]

#: Expressions refusées (expressions régulières, insensibles à la casse). Source : RECHERCHE.md §3.2.
INTERDITS_FR = [
    r"d[ée]couvrez",
    r"plongez",
    r"explorez",
    r"lib[ée]rez",
    r"r[ée]volution\w*",
    r"r[ée]invent\w*",
    r"repens\w*",
    r"transform(?:er|ez|e|ons)",
    r"en toute s[ée]r[ée]nit[ée]",
    r"en toute simplicit[ée]",
    r"en un clic",
    r"sans effort",
    r"cl[ée] en main",
    r"tout-en-un",
    r"solutions? innovantes?",
    r"innovant\w*",
    r"de pointe",
    r"nouvelle g[ée]n[ée]ration",
    r"intelligente?s?",
    r"puissante?s?",
    r"crucia\w*",
    r"essentiel\w*",
    r"incontournables?",
    r"v[ée]ritables?",
    r"au c(?:œ|oe)ur de",
    r"au service de",
    r"il est important de noter",
    r"il convient de souligner",
    r"permet(?:tent)? de",
    r"permettre de",
    r"optimis\w*",
    r"boost\w*",
    r"maximis\w*",
    r"accompagn\w*",
    r"garanti(?:r|s|ssons|ssez|t|e)?",
    r"n'attendez plus",
    r"ne laissez plus",
    r"que vous soyez",
    r"dans un monde o[ùu]",
    r"[àa] l'heure o[ùu]",
    r"en somme",
    r"en d[ée]finitive",
]
INTERDITS_EN = [
    r"delve\w*",
    r"tapestry",
    r"testament",
    r"pivotal",
    r"crucial\w*",
    r"underscor\w*",
    r"seamless\w*",
    r"unlock\w*",
    r"empower\w*",
    r"elevat\w*",
    r"leverag\w*",
    r"harness\w*",
    r"streamlin\w*",
    r"supercharg\w*",
    r"robust\w*",
    r"cutting-edge",
    r"next-gen\w*",
    r"best-in-class",
    r"all-in-one",
    r"game-?changer\w*",
    r"revolution\w*",
    r"effortless\w*",
    r"peace of mind",
    r"navigat\w* the complexit\w*",
    r"it'?s important to note",
    r"serves as",
    r"whether you'?re",
    r"in today'?s",
    r"in summary",
]
#: Marques à ne jamais citer, encodées pour ne pas figurer en clair dans le dépôt.
MARQUES_EXCLUES = [
    base64.b64decode(m).decode("utf-8") for m in ("bCdvY2NpdGFuZQ==", "b2NjaXRhbmU=", "Y2hhbmVs")
]

#: Tiret cadratin (toujours refusé dans le texte) et demi-cadratin entouré d'espaces (incise).
TIRET_INCISE = re.compile(r"—|\s–\s")


def _motifs(liste: list[str]) -> list[tuple[str, re.Pattern[str]]]:
    return [(m, re.compile(r"(?<![\w-])" + m + r"(?![\w])", re.IGNORECASE)) for m in liste]


MOTIFS_FR = _motifs(INTERDITS_FR)
MOTIFS_EN = _motifs(INTERDITS_EN)


def formulations(texte: str, motifs: list[tuple[str, re.Pattern[str]]]) -> list[str]:
    texte = texte.replace("’", "'")
    return [m for m, rx in motifs if rx.search(texte)]


def _textes(page: Path) -> list[str]:
    doc = _lire(page)
    return [doc.visible, " | ".join(doc.attrs_visibles)]


def test_detection():
    assert formulations("Découvrez notre solution innovante, en toute sérénité.", MOTIFS_FR) == [
        r"d[ée]couvrez",
        r"en toute s[ée]r[ée]nit[ée]",
        r"solutions? innovantes?",
        r"innovant\w*",
    ]
    assert formulations("ControlDOne permet de gagner du temps.", MOTIFS_FR) == [r"permet(?:tent)? de"]
    assert formulations("Je compare la facture du transitaire à la déclaration.", MOTIFS_FR) == []
    assert formulations("garanties de transfert", MOTIFS_FR) == []
    assert formulations("Unlock seamless workflows that empower teams.", MOTIFS_EN) == [
        r"seamless\w*",
        r"unlock\w*",
        r"empower\w*",
    ]
    assert formulations("I compare each line of the invoice.", MOTIFS_EN) == []
    assert TIRET_INCISE.search("un écart — chiffré")
    assert TIRET_INCISE.search("un écart – chiffré")
    assert not TIRET_INCISE.search("2026–2027")


@pytest.mark.parametrize("page", PAGES_COMMERCIALES_FR, ids=lambda p: p.name)
def test_pas_de_formulation_de_style_fr(page):
    for texte in _textes(page):
        assert formulations(texte, MOTIFS_FR) == [], f"{page.name} : {formulations(texte, MOTIFS_FR)}"


@pytest.mark.parametrize("page", PAGES_EN, ids=lambda p: p.name)
def test_pas_de_formulation_de_style_en(page):
    for texte in _textes(page):
        assert formulations(texte, MOTIFS_EN) == [], f"{page.name} : {formulations(texte, MOTIFS_EN)}"


@pytest.mark.parametrize("page", [*PAGES_FR, *PAGES_EN], ids=lambda p: p.parent.name + "/" + p.name)
def test_pas_de_tiret_en_incise(page):
    for texte in _textes(page):
        m = TIRET_INCISE.search(texte)
        assert not m, f"{page.name} : tiret en incise : …{texte[max(0, m.start() - 60) : m.end() + 60]}…"


@pytest.mark.parametrize("page", [*PAGES_FR, *PAGES_EN], ids=lambda p: p.parent.name + "/" + p.name)
def test_un_seul_point_d_exclamation_au_plus(page):
    assert sum(t.count("!") for t in _textes(page)) <= 1, page.name


def test_aucune_marque_exclue_dans_le_site():
    fichiers = [
        p for p in SITE.rglob("*") if p.is_file() and p.suffix in {".html", ".css", ".js", ".md", ".txt"}
    ]
    assert fichiers
    for f in fichiers:
        texte = f.read_text(encoding="utf-8", errors="ignore").lower()
        for marque in MARQUES_EXCLUES:
            assert marque not in texte, f"{f.relative_to(SITE)} : marque exclue"
