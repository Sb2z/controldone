"""Lot, Fichier, Page, Document (SPEC §6.2.5, §6.2.6)."""

from __future__ import annotations

from datetime import datetime
from typing import TypeVar

from pydantic import Field

from controldone.ids import Prefixe, nouvel_id
from controldone.model.base import Enregistrement, Modele, horodatage
from controldone.model.champs import (
    Champs,
    ChampsAvoir,
    ChampsDeclaration,
    ChampsDocument,
    ChampsFactureCommerciale,
    ChampsFactureTransitaire,
    ChampsSupport,
)
from controldone.model.enums import (
    CanalLot,
    MotifNonExploitable,
    QualiteTexte,
    StatutFichier,
    StatutLot,
    TypeDocument,
)
from controldone.model.valeur import ValeurSourcee

__all__ = ["Document", "Fichier", "Lot", "Page", "PageRef"]

_C = TypeVar("_C", bound=Champs)


class Lot(Enregistrement):
    """Ensemble de fichiers déposés en une fois (§6.2.5)."""

    id: str = Field(default_factory=lambda: nouvel_id(Prefixe.lot))
    canal: CanalLot = CanalLot.depot
    recu_le: datetime = Field(default_factory=horodatage)
    expediteur: str | None = None
    statut: StatutLot = StatutLot.recu


class Fichier(Enregistrement):
    id: str = Field(default_factory=lambda: nouvel_id(Prefixe.fichier))
    lot_id: str | None = None
    nom_original: str
    #: Chemin relatif d'origine (arborescence de dépôt / ZIP conservée), séparateur « / ».
    chemin_relatif: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    taille: int = Field(ge=0)
    type_mime: str
    statut: StatutFichier = StatutFichier.ok
    motif_refus: str | None = None
    nombre_pages: int | None = None
    #: Fichier identique déjà reçu pour ce client (§7.1) : identifiant du premier.
    doublon_de: str | None = None


class Page(Enregistrement):
    id: str = Field(default_factory=lambda: nouvel_id(Prefixe.page))
    fichier_id: str
    numero: int = Field(ge=1)
    rotation_appliquee: int = 0
    qualite_texte: QualiteTexte = QualiteTexte.natif
    score_ocr: float | None = Field(default=None, ge=0, le=1)
    #: Texte de la page (chiffré au repos par la couche de stockage, §6.2.5).
    texte: str = ""
    sha256_texte: str | None = None
    #: Nom de feuille pour un tableur.
    feuille: str | None = None
    largeur: float | None = None
    hauteur: float | None = None


class PageRef(Modele):
    """Page d'un document logique : ``{fichier_id, numero}`` (§6.2.6).

    ``qualite_texte`` est une copie dénormalisée de ``Page.qualite_texte``, renseignée par l'ingestion,
    pour que les contrôles (fonctions pures) appliquent le test de confusion (§8.5.4) sans accès base.
    """

    fichier_id: str
    numero: int = Field(ge=1)
    qualite_texte: QualiteTexte | None = None


class Document(Enregistrement):
    """Document **logique** (§6.2.6). ``champs`` est typé selon ``type`` (discriminant ``type_document``)."""

    id: str = Field(default_factory=lambda: nouvel_id(Prefixe.document))
    type: TypeDocument
    sous_type: str | None = None
    pages: list[PageRef] = Field(default_factory=list)
    confiance_classement: float = Field(default=1.0, ge=0, le=1)
    motif_non_exploitable: MotifNonExploitable | None = None
    #: Clé de dédoublonnage (§6.2.6).
    identite: str | None = None
    champs: ChampsDocument | None = None
    doublon_de: str | None = None
    #: Langue détectée (fr, en, es, fr_en…), indice pour la normalisation.
    langue: str | None = None

    # --- accès typés ---

    def valeurs(self) -> list[ValeurSourcee]:
        return list(self.champs.iter_valeurs()) if self.champs is not None else []

    def page_ref(self, numero: int | None) -> PageRef | None:
        if numero is None:
            return None
        for p in self.pages:
            if p.numero == numero:
                return p
        return None

    def fichier_ids(self) -> list[str]:
        vus: list[str] = []
        for p in self.pages:
            if p.fichier_id not in vus:
                vus.append(p.fichier_id)
        return vus

    @property
    def fc(self) -> ChampsFactureCommerciale:
        return self._champs(ChampsFactureCommerciale)

    @property
    def dec(self) -> ChampsDeclaration:
        return self._champs(ChampsDeclaration)

    @property
    def ft(self) -> ChampsFactureTransitaire:
        return self._champs(ChampsFactureTransitaire)

    @property
    def av(self) -> ChampsAvoir:
        return self._champs(ChampsAvoir)

    @property
    def sup(self) -> ChampsSupport:
        return self._champs(ChampsSupport)

    def _champs(self, cls: type[_C]) -> _C:
        if not isinstance(self.champs, cls):
            raise TypeError(f"document {self.id} ({self.type}) : champs {cls.__name__} attendus")
        return self.champs
