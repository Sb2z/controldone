"""Suivi du recouvrement : écarts à recouvrer, réclamations, événements (SPEC §17)."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import Field

from controldone.ids import Prefixe, nouvel_id
from controldone.model.base import Enregistrement, Modele, horodatage
from controldone.model.enums import Composante, StatutEcart

__all__ = [
    "TRANSITIONS_AUTORISEES",
    "EcartARecouvrer",
    "ErreurTransition",
    "EvenementRecouvrement",
    "PieceRecouvrement",
    "Reclamation",
    "transitionner",
]

#: Transitions autorisées (§17.1). ``credite`` et ``abandonne`` sont terminaux. ``conteste`` reste
#: ouvert à la relance (retour à ``reclame``). L'imputation d'un avoir (§17.2) peut créditer un écart
#: ``ouvert`` ou ``conteste`` directement.
TRANSITIONS_AUTORISEES: dict[StatutEcart, frozenset[StatutEcart]] = {
    StatutEcart.ouvert: frozenset(
        {StatutEcart.reclame, StatutEcart.partiellement_credite, StatutEcart.credite, StatutEcart.abandonne}
    ),
    StatutEcart.reclame: frozenset(
        {StatutEcart.partiellement_credite, StatutEcart.credite, StatutEcart.conteste, StatutEcart.abandonne}
    ),
    StatutEcart.partiellement_credite: frozenset(
        {StatutEcart.partiellement_credite, StatutEcart.credite, StatutEcart.conteste, StatutEcart.abandonne}
    ),
    StatutEcart.conteste: frozenset(
        {StatutEcart.reclame, StatutEcart.partiellement_credite, StatutEcart.credite, StatutEcart.abandonne}
    ),
    StatutEcart.credite: frozenset(),
    StatutEcart.abandonne: frozenset(),
}


class ErreurTransition(ValueError):
    pass


class EcartARecouvrer(Enregistrement):
    """Écart né d'un constat validé ``recouvrable`` de montant positif (§17.1)."""

    id: str = Field(default_factory=lambda: nouvel_id(Prefixe.ecart))
    constat_id: str
    dossier_id: str | None = None
    transitaire_id: str | None = None
    facture_transitaire_id: str | None = None
    mrn: str | None = None
    composante: Composante
    montant_initial: Decimal
    montant_credite: Decimal = Decimal("0.00")
    reste: Decimal
    statut: StatutEcart = StatutEcart.ouvert
    date_constat: datetime = Field(default_factory=horodatage)
    reclame_le: datetime | None = None
    reclamation_id: str | None = None

    def age_jours(self, maintenant: datetime) -> int | None:
        """Jours depuis ``reclame`` (§17.1) ; relances suggérées à 30, 60, 90 jours."""
        if self.reclame_le is None:
            return None
        return (maintenant - self.reclame_le).days


class Reclamation(Enregistrement):
    """Regroupe des écarts d'un même transitaire (§17.1, §17.3)."""

    id: str = Field(default_factory=lambda: nouvel_id(Prefixe.reclamation))
    transitaire_id: str
    entite_id: str | None = None
    dossier_ids: list[str] = Field(default_factory=list)
    ecart_ids: list[str] = Field(default_factory=list)
    #: Écarts ``a_verifier`` cochés explicitement par le client (mention « à confirmer »).
    ecarts_a_confirmer: list[str] = Field(default_factory=list)
    objet: str | None = None
    total_demande: Decimal = Decimal("0.00")
    valide_par_fondateur: bool = False
    valide_le: datetime | None = None
    envoyee_le: datetime | None = None


class PieceRecouvrement(Modele):
    avoir_id: str | None = None
    courriel: str | None = None
    autre: str | None = None


class EvenementRecouvrement(Modele):
    """Transition append-only d'un écart (§17.1)."""

    id: str = Field(default_factory=lambda: nouvel_id(Prefixe.evenement))
    client_id: str | None = None
    ecart_id: str
    de: StatutEcart
    vers: StatutEcart
    le: datetime = Field(default_factory=horodatage)
    auteur: str
    piece: PieceRecouvrement | None = None
    montant: Decimal | None = None
    commentaire: str | None = None


def transitionner(
    ecart: EcartARecouvrer,
    vers: StatutEcart,
    *,
    auteur: str,
    le: datetime | None = None,
    montant: Decimal | None = None,
    piece: PieceRecouvrement | None = None,
    commentaire: str | None = None,
) -> EvenementRecouvrement:
    """Applique une transition à ``ecart`` (mutation) et retourne l'événement à journaliser.

    Lève ``ErreurTransition`` si la transition n'est pas autorisée ou si ``abandonne`` n'a pas de motif.
    """
    if vers not in TRANSITIONS_AUTORISEES[ecart.statut]:
        raise ErreurTransition(f"transition interdite : {ecart.statut.value} -> {vers.value}")
    if vers is StatutEcart.abandonne and not (commentaire and commentaire.strip()):
        raise ErreurTransition("l'abandon exige un motif")
    moment = le or horodatage()
    evt = EvenementRecouvrement(
        client_id=ecart.client_id,
        ecart_id=ecart.id,
        de=ecart.statut,
        vers=vers,
        le=moment,
        auteur=auteur,
        piece=piece,
        montant=montant,
        commentaire=commentaire,
    )
    if vers is StatutEcart.reclame and ecart.reclame_le is None:
        ecart.reclame_le = moment
    ecart.statut = vers
    return evt
