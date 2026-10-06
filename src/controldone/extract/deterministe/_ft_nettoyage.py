"""Nettoyage des surimpressions d'une page avant lecture (factures de transitaire et avoirs).

Tampons (« PAYÉ », « ACQUITTÉ », « COPIE »), filigranes en diagonale et annotations manuscrites sont
superposés au texte de la facture. Dans le texte natif, leurs glyphes deviennent des « mots » qui se glissent
dans les lignes voisines (« Total HT  I T T É  1 637,25 € », « I Total TTC ») et déplacent la ligne, ou
forment des lignes parasites. Règles générales, sur la seule géométrie (aucun texte de tampon attendu) :

- **glyphe surdimensionné** : un mot court (une ou deux lettres, sans chiffre) dont la hauteur atteint
  2 fois la hauteur médiane des mots de la page, ou tout mot de hauteur ≥ 4 fois la médiane (filigrane en
  grands caractères) — un titre de facture fait au plus 2 à 2,5 fois le corps du texte et compte plusieurs
  lettres ;
- **écriture manuscrite** : une suite d'au moins 4 « mots » d'un seul caractère (dont 3 lettres ou chiffres)
  rapprochés, dont au moins la moitié des boîtes voisines se chevauchent : une police ordinaire ne découpe
  jamais un mot en glyphes isolés qui se recouvrent ; les signes séparés par une espace (« A = TVA 20 % ;
  E = … », « 3 × 3 ») ne sont pas concernés.

Seul le texte natif est traité (les boîtes OCR d'un trait ou d'une tache ne sont pas fiables).
Les mots retirés n'existent plus pour l'extraction ; le texte de la page (ancrage) n'est pas modifié.
Les lignes sont ensuite reclassées de haut en bas (une ligne qui commençait par un glyphe de tampon placé
plus haut reprend sa place).
"""

from __future__ import annotations

import re
from itertools import pairwise
from statistics import median

from controldone.ingest.texte import Ligne, Mot, PageText

__all__ = ["retirer_surimpressions"]

#: Hauteur relative (à la médiane de la page) d'un glyphe de tampon court.
RATIO_GLYPHE = 2.0
#: Hauteur relative de tout mot de filigrane.
RATIO_FILIGRANE = 4.0
#: Longueur minimale d'une suite de glyphes isolés jointifs (écriture manuscrite).
SUITE_MANUSCRITE = 4
#: Écart maximal (relatif à la largeur de page) entre deux glyphes d'une même suite.
ECART_JOINTIF = 0.005


def _hauteur(m: Mot) -> float:
    return max(0.0, m.y1 - m.y0)


def _glyphe_court(t: str) -> bool:
    t = t.strip()
    return 0 < len(t) <= 2 and not re.search(r"\d", t)


def _suites_manuscrites(mots: tuple[Mot, ...]) -> set[int]:
    """Indices des mots appartenant à une suite de glyphes isolés jointifs (mots triés par x)."""
    retirer: set[int] = set()
    ordre = sorted(range(len(mots)), key=lambda k: mots[k].x0)
    suite: list[int] = []

    def clore() -> None:
        if len(suite) < SUITE_MANUSCRITE:
            return
        chevauchements = sum(1 for a, b in pairwise(suite) if mots[b].x0 < mots[a].x1)
        alnum = sum(1 for k in suite if mots[k].texte.strip().isalnum())
        if chevauchements >= max(2, (len(suite) - 1) / 2) and alnum >= 3:
            retirer.update(suite)

    for k in ordre:
        m = mots[k]
        if len(m.texte.strip()) == 1:
            if suite and m.x0 - mots[suite[-1]].x1 > ECART_JOINTIF:
                clore()
                suite = []
            suite.append(k)
        else:
            clore()
            suite = []
    clore()
    return retirer


def retirer_surimpressions(pt: PageText) -> PageText:
    """Page sans les glyphes de tampon, de filigrane et d'annotation manuscrite (voir le module)."""
    if pt.source != "natif" or not pt.lignes:
        return pt
    hauteurs = [_hauteur(m) for li in pt.lignes for m in li.mots if _hauteur(m) > 0]
    if len(hauteurs) < 20:
        return pt
    h_med = median(hauteurs)
    if h_med <= 0:
        return pt
    modifie = False
    lignes: list[Ligne] = []
    for li in pt.lignes:
        # 1) glyphes de tampon ou de filigrane, 2) parmi les mots restants, écriture manuscrite
        restants = tuple(
            m
            for m in li.mots
            if not (
                _hauteur(m) >= RATIO_FILIGRANE * h_med
                or (_hauteur(m) >= RATIO_GLYPHE * h_med and _glyphe_court(m.texte))
            )
        )
        manuscrits = _suites_manuscrites(restants)
        gardes = [m for k, m in enumerate(restants) if k not in manuscrits]
        if len(gardes) != len(li.mots):
            modifie = True
            if gardes:
                lignes.append(Ligne(texte=" ".join(m.texte for m in gardes), mots=tuple(gardes)))
        else:
            lignes.append(li)
    if not modifie:
        return pt
    lignes.sort(key=lambda li: (li.y0 + li.y1) / 2)
    return PageText(
        numero=pt.numero,
        texte=pt.texte,
        lignes=lignes,
        qualite=pt.qualite,
        source=pt.source,
        score_natif=pt.score_natif,
        score_ocr=pt.score_ocr,
        rotation=pt.rotation,
        desinclinaison=pt.desinclinaison,
        largeur=pt.largeur,
        hauteur=pt.hauteur,
        feuille=pt.feuille,
        texte_masque=pt.texte_masque,
        avertissements=list(pt.avertissements),
    )
