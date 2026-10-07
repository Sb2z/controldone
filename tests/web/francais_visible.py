"""Repérage des mots français visibles dans une page de l'interface anglaise (bloc I4, D-4803).

Texte visible et attributs lus par l'utilisateur (``title``, ``aria-label``, ``placeholder``, ``alt``, valeur des
boutons) **hors** des régions ``lang="fr"`` (textes des constats, rapports, texte juridique exact : décision 7B,
SPEC §3), des scripts et des styles. Le contenu de ``<code>`` et ``<kbd>`` (identifiants techniques) et les jetons techniques (``_``, ``.``, ``/``,
chiffres) sont ignorés. Un mot est signalé s'il figure dans une liste de mots outils français sans
homographe anglais courant, ou s'il porte un accent propre au français. Les données (raisons sociales fictives,
références, noms de fichiers) sont écartées par une liste d'autorisations explicite côté test."""

from __future__ import annotations

import re
from html.parser import HTMLParser

__all__ = ["MOTS_FRANCAIS", "mots_francais", "segments_visibles"]

#: Mots outils et mots d'interface français sans homographe anglais courant.
MOTS_FRANCAIS = frozenset(
    """
    le la les des du une aux au est sont avec pour dans sur sous aucun aucune pas ce cet cette ces vos votre nos
    notre leur leurs qui que quoi où mais donc ni chez entre selon depuis puis encore déjà très
    tous toutes tout toute il elle ils elles nous vous je se sa ses mes mon ma
    être été avoir fait faire peut doit voir ajouter supprimer enregistrer valider rejeter fermer ouvrir
    afficher rechercher télécharger déposer envoyer modifier annuler retour suivant précédent
    dossier dossiers fichier fichiers facture factures avoirs écart écarts constat constats
    montant montants rapport rapports relevé relevés statut tâche tâches compte comptes erreur
    oui traitement connexion déconnexion utilisateur utilisateurs adresse
    transitaire transitaires douane douanes déclaration déclarations entité entités clé clés
    alerte alertes sauvegarde sauvegardes coût coûts plafond mois jour jours année semaine
    """.split()
)
_ACCENTS = re.compile(r"[éèêëàâçùûôîïœÉÈÊÀÂÇÙÛÔÎÏŒ]")
_JETON = re.compile(r"[^\s,;:()«»“”\"!?·—–…*`]+")
#: Jeton technique (identifiant, chemin, champ, nombre) : jamais signalé.
_TECHNIQUE = re.compile(r"[_./\[\]=@{}<>#0-9]")
_VIDES = frozenset(
    {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "wbr"}
)
_ATTRS = ("title", "aria-label", "placeholder", "alt")


class _Lecteur(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.pile: list[tuple[str, bool]] = []  # (balise, région exclue)
        self.segments: list[str] = []

    def _exclu(self) -> bool:
        return bool(self.pile) and self.pile[-1][1]

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = dict(attrs)
        exclu = (
            self._exclu() or a.get("lang") == "fr" or tag in ("script", "style", "template", "code", "kbd")
        )
        if tag == "html":
            exclu = False
        if not exclu:
            for nom in _ATTRS:
                if a.get(nom):
                    self.segments.append(str(a[nom]))
            if tag == "input" and a.get("type") in ("submit", "button") and a.get("value"):
                self.segments.append(str(a["value"]))
        if tag not in _VIDES:
            self.pile.append((tag, exclu))

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _VIDES:
            self.handle_starttag(tag, attrs)
        else:  # <x/> : ouvert puis fermé
            self.handle_starttag(tag, attrs)
            self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        for i in range(len(self.pile) - 1, -1, -1):
            if self.pile[i][0] == tag:
                del self.pile[i:]
                return

    def handle_data(self, data: str) -> None:
        if not self._exclu() and data.strip():
            self.segments.append(data)


def segments_visibles(html: str) -> list[str]:
    """Textes et attributs lus par l'utilisateur, hors régions ``lang="fr"``, scripts et styles."""
    lecteur = _Lecteur()
    lecteur.feed(html)
    lecteur.close()
    return [re.sub(r"\s+", " ", s).strip() for s in lecteur.segments if s.strip()]


def mots_francais(html: str, autorises: frozenset[str] | set[str] = frozenset()) -> list[tuple[str, str]]:
    """``(mot, segment)`` français visibles ; ``autorises`` : segments (données, noms propres) tolérés tels quels,
    comparés après suppression des espaces de bord."""
    out = []
    for seg in segments_visibles(html):
        if seg in autorises:
            continue
        seg = re.sub(r"`[^`]*`", " ", seg)  # `identifiant` d'un texte au format Markdown : technique
        for m in _JETON.finditer(seg):
            jeton = m.group(0)
            if _TECHNIQUE.search(jeton):
                continue
            for mot in re.split(r"['’-]", jeton):
                if mot.lower() in MOTS_FRANCAIS or _ACCENTS.search(mot):
                    out.append((mot, seg))
    return out
