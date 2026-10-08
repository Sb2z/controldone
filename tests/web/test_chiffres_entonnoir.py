"""Typographie des chiffres et entonnoir du tableau Marketing (revue d'octobre 2026, données fictives).

1. Chiffres tabulaires seulement là où les nombres s'alignent ou défilent : dans Inter, « tnum » donne aussi au trait
   d'union la largeur d'un chiffre, si bien que « FT-FIC-0501 » ou « enregistrez-le » paraissaient espacés. Le texte
   courant garde des chiffres proportionnels ; colonnes numériques, indicateurs, montants mis en avant, compteurs
   animés et chasse fixe restent tabulaires. La flèche des petits liens garde son espace (« d'écarts → »).
2. « Conversion par étape » : la barre montre exactement le pourcentage écrit à côté d'elle (taux depuis l'étape
   précédente), avec l'effectif qui le fonde (« 2 / 2 » à côté de « 100 % »)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from aides_web import connecter_fondateur

from controldone.web.i18n import COOKIE_LANGUE

STATIQUE = Path(__file__).resolve().parents[2] / "src" / "controldone" / "web" / "static"
GABARITS = STATIQUE.parent / "templates"


def _regles(css: str) -> list[tuple[list[str], str]]:
    """``([sélecteurs], corps)`` de chaque règle (blocs @media compris, à plat, commentaires retirés)."""
    css = re.sub(r"/\*.*?\*/", " ", css, flags=re.S)
    return [
        ([s.strip() for s in m.group(1).split(",")], m.group(2))
        for m in re.finditer(r"([^{}@]+)\{([^{}]*)\}", css)
    ]


def _tabulaire(corps: str) -> bool:
    return bool(
        re.search(r"font-variant-numeric\s*:[^;]*tabular-nums|font-feature-settings\s*:[^;]*\"tnum\"", corps)
    )


# --- 1. chiffres tabulaires ciblés ---------------------------------------------------------------------------------


def test_texte_courant_sans_chiffres_tabulaires():
    """Aucune règle large (corps de page, paragraphes, cellules quelconques) n'active « tnum » : le trait d'union
    d'Inter garde sa largeur normale dans le texte."""
    larges = {"html", "body", ":root", "*", "p", "li", "td", "th", "a", "span", "div", "main", "label"}
    for feuille in ("app.css", "prospection.css"):
        for selecteurs, corps in _regles((STATIQUE / feuille).read_text(encoding="utf-8")):
            if _tabulaire(corps):
                assert not larges.intersection(selecteurs), (feuille, selecteurs, corps)
            # « tnum » passe par font-variant-numeric, jamais par font-feature-settings (qui écraserait « cv11 »)
            assert not re.search(r"font-feature-settings\s*:[^;]*\"tnum\"", corps), (feuille, selecteurs)
    corps_page = [c for s, c in _regles((STATIQUE / "app.css").read_text(encoding="utf-8")) if s == ["body"]]
    assert corps_page and all("tnum" not in c for c in corps_page)


def test_chiffres_tabulaires_la_ou_les_nombres_s_alignent():
    tabulaires = set()
    for feuille in ("app.css", "prospection.css"):
        for selecteurs, corps in _regles((STATIQUE / feuille).read_text(encoding="utf-8")):
            if _tabulaire(corps):
                tabulaires.update(selecteurs)
    # colonnes numériques et indicateurs (.num), montants mis en avant, compteurs animés, chasse fixe, scores
    attendus = {".num", "td.num", "[data-compteur]", ".bilan-chiffre", ".bilan-dossier dd", "code", "pre"}
    assert attendus <= tabulaires, attendus - tabulaires
    assert ".prosp-score" in tabulaires and ".prosp-points" in tabulaires
    # les valeurs des indicateurs (défilement animé par app.js) portent la classe .num
    macros = (GABARITS / "macros.html.j2").read_text(encoding="utf-8")
    assert '<div class="kpi-val num">' in macros


def test_fleche_des_petits_liens_detachee_du_texte():
    """Un espace en tête du contenu d'un pseudo-élément inline-block est supprimé au rendu (« d'écarts→ ») : l'écart
    passe par une marge."""
    for feuille in ("app.css", "prospection.css"):
        for selecteurs, corps in _regles((STATIQUE / feuille).read_text(encoding="utf-8")):
            if re.search(r"display\s*:\s*inline-block", corps):
                assert not re.search(r"content\s*:\s*\"\s", corps), (feuille, selecteurs)
    regle = [
        c
        for s, c in _regles((STATIQUE / "app.css").read_text(encoding="utf-8"))
        if s == [".petit-lien::after"]
    ]
    assert regle and 'content: "→"' in regle[0] and "margin-left" in regle[0]


def test_largeurs_au_pour_cent_pres():
    """Classes w-0 à w-100 : une barre peut prendre exactement le pourcentage affiché (aucun style en ligne, CSP)."""
    largeurs: dict[str, str] = {}
    for selecteurs, corps in _regles((STATIQUE / "app.css").read_text(encoding="utf-8")):
        for s in selecteurs:
            if re.fullmatch(r"\.w-\d+", s):
                largeurs[s] = re.search(r"width\s*:\s*([^;]+)", corps).group(1).strip()
    for n in range(101):
        assert largeurs.get(f".w-{n}") == ("0" if n == 0 else f"{n}%"), n


# --- 2. entonnoir : la barre dit la même chose que le nombre ---------------------------------------------------------


def _lignes_entonnoir(html: str) -> list[dict]:
    table = re.search(r'<table class="donnees compacte prosp-entonnoir">(.*?)</table>', html, re.S)
    assert table, "tableau de conversion absent"
    corps = re.search(r"<tbody>(.*?)</tbody>", table.group(1), re.S).group(1)
    lignes = []
    for tr in re.findall(r"<tr>(.*?)</tr>", corps, re.S):
        cellules = re.findall(r'<td(?: class="([^"]*)")?>(.*?)</td>', tr, re.S)
        par_classe = {classe: contenu.strip() for classe, contenu in cellules}
        barre = re.search(
            r'<span class="barre"[^>]*><span class="w-(\d+)"></span></span>', par_classe["barre-col"]
        )
        lignes.append(
            {
                "atteint": int(cellules[1][1]),
                "sur": par_classe["num prosp-sur"],
                "taux": par_classe["num prosp-taux"],
                "barre": int(barre.group(1)) if barre else None,
            }
        )
    return lignes


@pytest.mark.parametrize("langue", ["fr", "en"])
def test_entonnoir_barre_egale_au_pourcentage_affiche(monde, langue):
    c = monde.client()
    c.cookies.set(COOKIE_LANGUE, langue)
    connecter_fondateur(c, monde)
    lignes = _lignes_entonnoir(c.get("/admin/prospection").text)
    assert len(lignes) == 7  # à qualifier -> client
    total = lignes[0]["atteint"]
    # première étape : pas d'étape précédente, donc ni taux ni barre
    assert total > 0 and lignes[0]["taux"] == "—" and lignes[0]["barre"] is None
    precedent = total
    ecart_avec_la_part_du_total = False
    for ligne in lignes[1:]:
        if precedent == 0:  # personne à l'étape précédente : ni taux ni barre
            assert ligne["taux"] == "—" and ligne["barre"] is None and ligne["sur"] == ""
        else:
            pct = int(re.fullmatch(r"(\d+) %", ligne["taux"]).group(1))
            assert ligne["barre"] == pct  # la barre montre le pourcentage écrit juste avant elle
            # l'effectif qui fonde le taux : « atteint / étape précédente »
            assert ligne["sur"] == f"{ligne['atteint']} / {precedent}"
            assert pct == round(100 * ligne["atteint"] / precedent)
            ecart_avec_la_part_du_total |= pct != round(100 * ligne["atteint"] / total)
        precedent = ligne["atteint"]
    # les données de démonstration contiennent le cas signalé (« 100 % » quand peu de prospects atteignent l'étape) :
    # l'ancienne barre (part du total) aurait été plus courte que le nombre affiché
    assert ecart_avec_la_part_du_total
