"""ResultatControle, Constat, Preuve, Execution, Correction (SPEC §6.2.9, §6.2.11, §6.2.12)."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import Field, model_validator

from controldone.ids import Prefixe, nouvel_id
from controldone.model.base import Enregistrement, Modele, horodatage
from controldone.model.enums import (
    Composante,
    NatureMontant,
    Niveau,
    Outcome,
    RaisonCode,
    RoleAuteur,
    RolePreuve,
    Sens,
    StatutValidation,
)

__all__ = ["RAISONS_INFORMATIVES", "Constat", "Correction", "Execution", "Preuve", "ResultatControle"]

#: Raisons qui n'expriment pas un doute et peuvent accompagner un ``ecart_certain`` (ex. C5 dont le
#: montant n'est pas additionné, §8.6).
RAISONS_INFORMATIVES: frozenset[RaisonCode] = frozenset(
    {RaisonCode.doublon_composantes, RaisonCode.montant_converti, RaisonCode.couvert_par_autre_controle}
)


class Preuve(Modele):
    """Preuve d'un constat (§6.2.9).

    ``document_id``, ``page`` et ``valeur_brute`` sont des copies dénormalisées de la valeur sourcée,
    pour que le constat se suffise à lui-même (sortie ``findings.json``, Annexe C). Une preuve de
    calcul (``role = operande`` sans valeur sourcée) porte ``calcul`` (texte du calcul affiché).
    """

    valeur_sourcee_id: str | None = None
    role: RolePreuve
    document_id: str | None = None
    page: int | None = None
    valeur_brute: str | None = None
    chemin: str | None = None
    calcul: str | None = None
    extrait_image: str | None = None


class Constat(Modele):
    """Constat (finding) : résultat ``ecart_certain`` ou ``a_verifier`` (§6.2.9)."""

    id: str = Field(default_factory=lambda: nouvel_id(Prefixe.constat))
    controle_id: str
    sous_controle: str | None = None
    niveau: Niveau
    raisons: list[RaisonCode] = Field(default_factory=list)
    libelle: str = ""
    #: Montant signé en EUR arrondi au centime (§8.6) ; ``None`` si renvoi, aucun, non calculable.
    montant_en_jeu: Decimal | None = None
    #: Montant avant déduction des avoirs imputés (§8.6, ``recouvrable``).
    montant_brut: Decimal | None = None
    #: D2 : TVA correspondant à la ligne hors grille (informatif).
    montant_tva_associee: Decimal | None = None
    nature_montant: NatureMontant
    composante: Composante | None = None
    sens: Sens | None = None
    documents_concernes: list[str] = Field(default_factory=list)
    #: Autres dossiers cités (famille F).
    autres_dossiers: list[str] = Field(default_factory=list)
    preuves: list[Preuve] = Field(default_factory=list)
    renvoi: bool = False
    statut_validation: StatutValidation = StatutValidation.propose
    valide_par: str | None = None
    valide_le: datetime | None = None
    commentaire_validation: str | None = None
    prochaine_action: str = ""
    #: Motif de blocage avant publication (ex. ``formulation_interdite``, §3.2).
    motif_blocage: str | None = None

    @model_validator(mode="after")
    def _invariants(self) -> Constat:
        # §3.3 / §3.5 : une note de renvoi est a_verifier et n'a jamais de montant.
        if self.nature_montant in (NatureMontant.renvoi, NatureMontant.aucun) and self.montant_en_jeu is not None:
            raise ValueError(f"{self.controle_id} : montant interdit pour la nature {self.nature_montant.value}")
        if self.renvoi and self.niveau is not Niveau.a_verifier:
            raise ValueError(f"{self.controle_id} : une note de renvoi est toujours a_verifier")
        if self.renvoi and self.montant_en_jeu is not None:
            raise ValueError(f"{self.controle_id} : une note de renvoi ne porte pas de montant")
        if self.niveau is Niveau.ecart_certain and not set(self.raisons) <= RAISONS_INFORMATIVES:
            raise ValueError(f"{self.controle_id} : un ecart_certain ne porte pas de raison de doute")
        if self.niveau is Niveau.a_verifier and not self.raisons:
            raise ValueError(f"{self.controle_id} : un a_verifier porte au moins une raison (§3.1 règle 4)")
        return self


class ResultatControle(Modele):
    """Résultat d'une exécution de contrôle sur une unité de comparaison (§6.2.9).

    ``unite`` est la clé stable de l'unité de comparaison (ex. ``dec:<doc_id>|tax:3``) : elle fonde
    l'identifiant stable du résultat et les règles de non-double-comptage (§8.6).
    ``constat`` est présent si et seulement si ``outcome`` est un constat.
    """

    id: str = Field(default_factory=lambda: nouvel_id(Prefixe.resultat))
    controle_id: str
    sous_controle: str | None = None
    unite: str = "dossier"
    dossier_id: str
    dossier_version: int
    execution_id: str | None = None
    outcome: Outcome
    raison_code: RaisonCode | None = None
    entrees: dict[str, str] = Field(default_factory=dict)
    attendu: str | None = None
    constate: str | None = None
    ecart: Decimal | None = None
    tolerance_appliquee: Decimal | None = None
    seuil_certitude_applique: Decimal | None = None
    empreinte_tolerances: str | None = None
    documents_concernes: list[str] = Field(default_factory=list)
    #: Informations complémentaires déterministes (clés triées à l'export), sans contenu de document.
    details: dict[str, Any] = Field(default_factory=dict)
    constat: Constat | None = None

    @model_validator(mode="after")
    def _coherence(self) -> ResultatControle:
        if self.outcome.est_constat:
            if self.constat is None:
                raise ValueError(f"{self.controle_id} : outcome {self.outcome.value} sans constat")
            if self.constat.niveau.value != self.outcome.value:
                raise ValueError(f"{self.controle_id} : niveau du constat différent de l'outcome")
        elif self.constat is not None:
            raise ValueError(f"{self.controle_id} : constat interdit pour l'outcome {self.outcome.value}")
        if self.outcome in (Outcome.non_verifiable, Outcome.non_applicable) and self.raison_code is None:
            raise ValueError(f"{self.controle_id} : {self.outcome.value} exige une raison_code")
        return self


class Execution(Modele):
    """Exécution (run) : versions et coûts (§6.2.12). Globale : pas de ``client_id`` obligatoire."""

    id: str = Field(default_factory=lambda: nouvel_id(Prefixe.execution))
    client_id: str | None = None
    demarre_le: datetime = Field(default_factory=horodatage)
    termine_le: datetime | None = None
    version_moteur: str
    version_schema: str
    version_regles: str
    empreinte_tolerances: str | None = None
    versions_extracteurs: dict[str, str] = Field(default_factory=dict)
    modele_llm: str | None = None
    cout_ia_eur: Decimal = Decimal("0")
    jetons_entree: int = 0
    jetons_sortie: int = 0
    duree_s: float | None = None

    @classmethod
    def nouvelle(cls, **kwargs: Any) -> Execution:
        """Exécution aux versions courantes du moteur."""
        from controldone import SCHEMA_VERSION, VERSION_MOTEUR, VERSION_REGLES

        kwargs.setdefault("version_moteur", VERSION_MOTEUR)
        kwargs.setdefault("version_schema", SCHEMA_VERSION)
        kwargs.setdefault("version_regles", VERSION_REGLES)
        return cls(**kwargs)


class Correction(Enregistrement):
    """Événement append-only (§6.2.11). ``cible`` : identifiant de valeur sourcée ou de lien."""

    id: str = Field(default_factory=lambda: nouvel_id(Prefixe.correction))
    dossier_id: str | None = None
    cible: str
    ancienne_valeur: str | None = None
    nouvelle_valeur: str | None = None
    #: Identifiant de la nouvelle ``ValeurSourcee`` (``saisie_humaine``) créée par la correction.
    nouvelle_valeur_sourcee_id: str | None = None
    auteur: str
    role_auteur: RoleAuteur
    motif: str
    le: datetime = Field(default_factory=horodatage)
