"""Détection des formulations interdites (§3.2).

La liste fait foi dans ``config/formulations_interdites.yaml`` (écrite par une autre équipe).
Si le fichier est absent ou ne contient aucune expression exploitable, on utilise la copie
intégrée du tableau de §3.2.

Recherche insensible à la casse et aux accents, tolérante au pluriel et au féminin
(suffixes ``e``, ``s``, ``es`` ; ``al/aux/ale(s)`` ; ``eux/euse(s)`` ; ``ier/ière(s)/iers`` ;
``if/ive(s)/ifs``), traits d'union équivalents à une espace ou à rien, bornes de mot.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

FORMULATIONS_INTEGREES: tuple[str, ...] = (
    # Classement tarifaire
    "le bon code", "le code correct", "mauvais classement", "erreur de classement",
    "devrait être classé",
    # Bien-fondé de l'imposition
    "droit dû", "droits dus", "taxe due", "montant dû à la douane", "trop payé en douane",
    "remboursement des droits",
    # Valeur en douane
    "valeur en douane incorrecte", "sous-évaluation", "sur-évaluation",
    # Origine / préférence
    "origine incorrecte", "origine fausse", "préférence injustifiée", "préférence applicable",
    "droit préférentiel",
    # Taux
    "taux erroné", "mauvais taux", "le taux applicable est",
    # Qualification juridique
    "non conforme à la réglementation", "illégal", "irrégulier", "en infraction", "fraude",
    "frauduleux",
    # Réclamation au nom du prestataire
    "nous réclamons", "ControlDOne réclame", "au nom de notre client", "mandaté par",
    # Démarche juridique
    "vous devez déposer une demande de remboursement", "déposez une réclamation en douane",
    "il faut rectifier la déclaration",
    # Engagement de résultat
    "nous garantissons", "certifié conforme",
)

_CLES_EXPRESSION = {"expression", "expressions", "texte", "formulation", "formulations",
                    "interdit", "interdits", "interdites", "phrase", "phrases", "liste"}
_CLES_REGEX = {"regex", "pattern", "motif_regex"}
_CLES_IGNOREES = {"pourquoi", "raison", "remplacer_par", "remplacement", "remplacer",
                  "motif", "description", "categorie", "catégorie", "version", "schema",
                  "commentaire", "note", "id", "exceptions", "autorise", "autorisees",
                  "exemples", "exemples_autorises"}


def normaliser_texte(texte: str) -> str:
    """Minuscules, sans accents, apostrophes et espaces unifiées."""
    t = unicodedata.normalize("NFKD", texte)
    t = "".join(c for c in t if not unicodedata.combining(c))
    t = t.lower()
    t = t.replace("’", "'").replace("‘", "'").replace("ʼ", "'")
    t = t.replace("‑", "-").replace("‐", "-").replace("–", "-")
    t = re.sub(r"[\s  ]+", " ", t)
    return t.strip()


def _motif_mot(mot: str) -> str:
    morceaux = [m for m in mot.split("-") if m]
    if not morceaux:
        return ""
    *debut, fin = morceaux
    if fin.endswith("al"):
        fin_re = re.escape(fin[:-2]) + r"(?:al|ale|ales|aux|als)"
    elif fin.endswith("eux"):
        fin_re = re.escape(fin[:-3]) + r"(?:eux|euse|euses)"
    elif fin.endswith("ier"):
        fin_re = re.escape(fin[:-3]) + r"(?:ier|iere|ieres|iers)"
    elif fin.endswith("if"):
        fin_re = re.escape(fin[:-2]) + r"(?:if|ive|ives|ifs)"
    else:
        fin_re = re.escape(fin) + r"(?:e|s|es)?"
    parties = [re.escape(m) for m in debut] + [fin_re]
    return r"[-\s]?".join(parties)


def compiler_expression(expression: str) -> re.Pattern[str]:
    norm = normaliser_texte(expression).strip(" «»\"'")
    mots = [m for m in norm.split(" ") if m]
    corps = r"\s+".join(_motif_mot(m) for m in mots)
    return re.compile(r"(?<![a-z0-9])" + corps + r"(?![a-z0-9])")


def _collecter(noeud, expressions: list[str], regexes: list[str], cle: str | None = None) -> None:
    if isinstance(noeud, dict):
        for k, v in noeud.items():
            kk = str(k).lower()
            if kk in _CLES_IGNOREES:
                continue
            if kk in _CLES_REGEX:
                if isinstance(v, str):
                    regexes.append(v)
                elif isinstance(v, list):
                    regexes.extend(x for x in v if isinstance(x, str))
                continue
            if isinstance(v, str):
                if kk in _CLES_EXPRESSION:
                    expressions.append(v)
                continue
            _collecter(v, expressions, regexes, kk)
    elif isinstance(noeud, list):
        for item in noeud:
            if isinstance(item, str):
                expressions.append(item)
            else:
                _collecter(item, expressions, regexes, cle)


@dataclass(frozen=True)
class Formulations:
    source: str
    expressions: tuple[tuple[str, re.Pattern[str]], ...]

    def chercher(self, texte: str | None) -> list[str]:
        """Expressions interdites trouvées dans ``texte`` (libellé de la liste)."""
        if not texte or not isinstance(texte, str):
            return []
        norm = normaliser_texte(texte)
        trouvees: list[str] = []
        zones: list[tuple[int, int]] = []
        for lib, motif in self.expressions:
            for m in motif.finditer(norm):
                # une même portion de texte n'est signalée qu'une fois (« droits dus » est
                # couvert à la fois par « droit dû » et « droits dus »)
                if any(m.start() < fin and debut < m.end() for debut, fin in zones):
                    continue
                zones.append(m.span())
                if lib not in trouvees:
                    trouvees.append(lib)
        return trouvees


def charger_formulations(chemin_config: Path | None = None) -> Formulations:
    if chemin_config is None:
        chemin_config = Path(__file__).resolve().parents[2] / "config" / "formulations_interdites.yaml"
    expressions: list[str] = []
    regexes: list[str] = []
    source = "integree_spec_3_2"
    if chemin_config.is_file():
        try:
            import yaml  # PyYAML (licence MIT)

            donnees = yaml.safe_load(chemin_config.read_text(encoding="utf-8"))
            _collecter(donnees, expressions, regexes)
            if expressions or regexes:
                source = str(chemin_config)
        except Exception:  # fichier illisible : on retombe sur la copie intégrée
            expressions, regexes = [], []
    if not expressions and not regexes:
        expressions = list(FORMULATIONS_INTEGREES)
    compilees: list[tuple[str, re.Pattern[str]]] = []
    vues: set[str] = set()
    for e in expressions:
        cle = normaliser_texte(e)
        if cle and cle not in vues:
            vues.add(cle)
            compilees.append((e, compiler_expression(e)))
    for r in regexes:
        try:
            compilees.append((r, re.compile(r)))
        except re.error:
            continue
    return Formulations(source=source, expressions=tuple(compilees))
