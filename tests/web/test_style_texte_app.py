"""Style des textes de l'interface (D-5204, RECHERCHE §3.2) : aucune formule promotionnelle ni tiret cadratin en
incise dans les catalogues français (clés) et anglais (traductions).

Liste séparée des formulations juridiques interdites (``config/formulations_interdites.yaml``, garde-fous), qui
restent vérifiées par leurs propres tests. Les textes juridiques exacts (avertissement, phrase de renvoi) ne sont
pas dans les catalogues et ne sont pas concernés."""

from __future__ import annotations

import re

from controldone.web.i18n import AVERTISSEMENT_EN, PHRASE_RENVOI_EN
from controldone.web.i18n_en import CATALOGUE_EN

#: Mots et tournures de la liste noire française (RECHERCHE §3.2).
STYLE_FR = re.compile(
    r"\b(découvrez|plongez|explorez|libérez|révolutionn\w*|réinvent\w*|en toute sérénité|en toute simplicité|"
    r"en un clic|sans effort|clé en main|tout-en-un|solution innovante|de pointe|nouvelle génération|"
    r"optimis\w*|boost\w*|maximis\w*|incontournable|crucial\w*|essentiel\w*|au cœur de|au service de|"
    r"il est important de noter|il convient de souligner|n'attendez plus|ne laissez plus|"
    r"nous vous accompagnons|garantiss\w*|dans un monde où|à l'heure où|en somme|en définitive)\b",
    re.IGNORECASE,
)
#: Équivalents anglais (RECHERCHE §3.2).
STYLE_EN = re.compile(
    r"\b(seamless\w*|unlock\w*|empower\w*|elevat\w*|leverag\w*|harness\w*|streamlin\w*|supercharg\w*|robust|"
    r"cutting-edge|next-gen|best-in-class|all-in-one|game-changer|revolutioni[sz]\w*|effortless\w*|"
    r"peace of mind|delve|tapestry|testament|pivotal|crucial|underscore\w*|it's important to note|"
    r"in today's fast-paced world|navigate the complexities)\b",
    re.IGNORECASE,
)
#: Tiret cadratin employé en incise (entouré d'espaces) ; un tiret seul pour une valeur absente (« — ») est admis.
INCISE = re.compile(r"\S\s+—\s+\S")

#: Exceptions motivées : terme technique « en un clic » (désinscription RFC 8058, module de prospection).
AUTORISES_FR = frozenset({"désinscription en un clic"})


def _hors_exceptions(texte: str, autorises: frozenset[str]) -> str:
    for a in autorises:
        texte = texte.replace(a, " ")
    return texte


def test_francais_sans_formule_promotionnelle_ni_incise() -> None:
    fautes = [
        fr for fr in CATALOGUE_EN if STYLE_FR.search(_hors_exceptions(fr, AUTORISES_FR)) or INCISE.search(fr)
    ]
    assert not fautes, f"textes à reformuler : {fautes}"


def test_anglais_sans_formule_promotionnelle_ni_incise() -> None:
    fautes = [en for en in CATALOGUE_EN.values() if STYLE_EN.search(en) or INCISE.search(en)]
    assert not fautes, f"wording to rewrite: {fautes}"


def test_textes_juridiques_hors_du_controle_de_style() -> None:
    # Les traductions de courtoisie du texte juridique restent telles quelles, hors catalogue.
    assert AVERTISSEMENT_EN not in CATALOGUE_EN.values()
    assert PHRASE_RENVOI_EN not in CATALOGUE_EN.values()


def test_le_controle_detecte_les_cas_connus() -> None:
    assert STYLE_FR.search("Découvrez une solution innovante")
    assert STYLE_FR.search("Optimisez vos coûts en toute sérénité")
    assert STYLE_EN.search("Unlock seamless savings")
    assert INCISE.search("ControlDOne — contrôle technique")
    assert not INCISE.search("—")
