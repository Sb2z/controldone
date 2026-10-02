"""Description des documents de démonstration (données **fictives**) : une même description sert à
dessiner le PDF et, en l'absence d'extracteur déterministe publié, à l'extracteur de démonstration."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from controldone.model.enums import TypeDocument

__all__ = ["Champ", "DocDemo", "DossierDemo", "Tableau"]


@dataclass
class Champ:
    """Valeur imprimée. ``chemin`` relatif au modèle (``total_facture``, ``acheteur.tva``) ou ``None``
    pour un texte seulement affiché ; ``valeur`` force la valeur normalisée (énumérations)."""

    chemin: str | None
    libelle: str
    brut: str
    valeur: str | None = None


@dataclass
class Tableau:
    """Tableau de lignes : ``liste`` = ``lignes`` / ``articles`` / ``taxations`` / ``documents_references``.

    ``colonnes`` : ``(feuille, libellé, largeur en mm, aligné à droite)`` ; ``lignes`` : valeurs brutes par
    feuille ; ``enums`` : classifications déduites par ligne (``nature``, ``categorie``…)."""

    titre: str
    liste: str
    colonnes: list[tuple[str | None, str, float, bool]]
    lignes: list[dict[str, str]]
    enums: list[dict[str, Enum]] = field(default_factory=list)


@dataclass
class DocDemo:
    fichier: str
    type: TypeDocument
    titre: str
    cle: str  # texte unique du document (numéro), sert à le reconnaître
    sous_type: str | None = None
    langue: str = "fr"
    emetteur: list[str] = field(default_factory=list)
    emetteur_champs: list[Champ] = field(default_factory=list)
    destinataire_titre: str = "Destinataire"
    destinataire: list[Champ] = field(default_factory=list)
    entete: list[Champ] = field(default_factory=list)
    tableaux: list[Tableau] = field(default_factory=list)
    totaux: list[Champ] = field(default_factory=list)
    mentions: list[str] = field(default_factory=list)
    #: Objets construits directement (ex. ``indices_autoliquidation``) : ``{liste: [{feuille: brut, "type": enum}]}``.
    objets: dict[str, list[dict[str, Any]]] = field(default_factory=dict)


@dataclass
class DossierDemo:
    nom: str
    description: str
    documents: list[DocDemo]
