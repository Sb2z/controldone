"""Plafonds de coût IA par client (SPEC §20.5), fondés sur le registre ``ai_usage``.

- ``cout_mensuel(tenant)`` : coût IA (EUR) du mois en cours (ou de ``mois``) ;
- plafond mensuel : ``reglages["plafond_cout_ia_mensuel_eur"]`` du client, sinon la colonne
  ``plafond_cout_ia_mensuel_eur`` (défaut 8 EUR) ;
- à 80 % : alerte au fondateur (une par client et par mois) ; à 100 % : alerte et arrêt des appels au modèle
  pour ce client (``llm_autorise = False``) jusqu'à décision du fondateur (relèvement du plafond).
- ``RegistreCoutsDB`` : implémentation en base du protocole ``extract.llm.RegistreCouts`` (pour
  ``CostGuard``).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

from controldone.auth.roles import Acteur
from controldone.storage.db import Database
from controldone.storage.scope import TenantScope

__all__ = [
    "SEUIL_ALERTE",
    "EtatPlafond",
    "RegistreCoutsDB",
    "cout_mensuel",
    "enregistrer_cout",
    "etat_plafond",
    "mois_courant",
]

SEUIL_ALERTE = Decimal("0.80")


def mois_courant(now: datetime | None = None) -> str:
    """Mois du plafond IA : frontière de mois d'Europe/Paris, comme la facturation (D-1308)."""
    from controldone.calendrier import mois_paris

    return mois_paris(now)


@dataclass(frozen=True)
class EtatPlafond:
    tenant_id: str
    mois: str
    cout: Decimal
    plafond: Decimal

    @property
    def ratio(self) -> Decimal:
        return self.cout / self.plafond if self.plafond > 0 else Decimal("Infinity")

    @property
    def alerte(self) -> bool:
        return self.ratio >= SEUIL_ALERTE

    @property
    def arret(self) -> bool:
        return self.ratio >= 1

    @property
    def llm_autorise(self) -> bool:
        return not self.arret


def _plafond(scope: TenantScope) -> Decimal:
    t = scope.client()
    brut = (t.reglages or {}).get("plafond_cout_ia_mensuel_eur")
    return Decimal(str(brut)) if brut is not None else Decimal(t.plafond_cout_ia_mensuel_eur)


def _etat(scope: TenantScope, mois: str) -> EtatPlafond:
    return EtatPlafond(scope.tenant_id, mois, scope.cout_ia(mois=mois), _plafond(scope))


def cout_mensuel(tenant: str | TenantScope, *, db: Database | None = None, mois: str | None = None) -> Decimal:
    """Coût IA du client pour le mois (défaut : mois courant)."""
    mois = mois or mois_courant()
    if isinstance(tenant, TenantScope):
        return tenant.cout_ia(mois=mois)
    db = db or Database()
    with db.tenant(tenant, Acteur.systeme("couts"), lecture=True) as scope:
        return scope.cout_ia(mois=mois)


def etat_plafond(tenant: str | TenantScope, *, db: Database | None = None, mois: str | None = None) -> EtatPlafond:
    mois = mois or mois_courant()
    if isinstance(tenant, TenantScope):
        return _etat(tenant, mois)
    db = db or Database()
    with db.tenant(tenant, Acteur.systeme("couts"), lecture=True) as scope:
        return _etat(scope, mois)


def enregistrer_cout(scope: TenantScope, *, cout_eur: Decimal, jetons_entree: int = 0, jetons_sortie: int = 0,
                     modele: str | None = None, dossier_id: str | None = None, lot_id: str | None = None,
                     execution_id: str | None = None, now: datetime | None = None) -> EtatPlafond:
    """Enregistre un coût puis émet les alertes de seuil (80 %, 100 %) une fois par mois."""
    mois = mois_courant(now)
    scope.enregistrer_usage_ia(cout_eur=Decimal(cout_eur), mois=mois, jetons_entree=jetons_entree,
                               jetons_sortie=jetons_sortie, modele=modele, dossier_id=dossier_id, lot_id=lot_id,
                               execution_id=execution_id)
    scope.flush()
    etat = _etat(scope, mois)
    details: dict[str, Any] = {"mois": mois, "cout_eur": str(etat.cout), "plafond_eur": str(etat.plafond)}
    if etat.arret:
        scope.signaler_alerte(cle=f"cout100:{mois}", kind="cout_ia_plafond",
                              message=f"Plafond IA mensuel atteint ({etat.cout} / {etat.plafond} EUR) : appels au "
                              "modèle arrêtés pour ce client jusqu'à décision du fondateur.", details=details)
    if etat.alerte:
        scope.signaler_alerte(cle=f"cout80:{mois}", kind="cout_ia_alerte",
                              message=f"80 % du plafond IA mensuel atteint ({etat.cout} / {etat.plafond} EUR).",
                              details=details)
    return etat


class RegistreCoutsDB:
    """Registre des coûts en base pour **un** client, conforme au protocole
    ``controldone.extract.llm.RegistreCouts`` (à passer à ``CostGuard``)."""

    def __init__(self, db: Database, client_id: str) -> None:
        self.db = db
        self.client_id = client_id

    def _verifier(self, client_id: str | None) -> None:
        if client_id != self.client_id:
            from controldone.storage.erreurs import AccesRefuse

            raise AccesRefuse("registre de coûts d'un autre client")

    def total_dossier(self, dossier_id: str) -> Decimal:
        with self.db.tenant(self.client_id, Acteur.systeme("couts"), lecture=True) as scope:
            return scope.cout_ia(dossier_id=dossier_id)

    def total_client_mois(self, client_id: str, mois: str) -> Decimal:
        self._verifier(client_id)
        with self.db.tenant(self.client_id, Acteur.systeme("couts"), lecture=True) as scope:
            return scope.cout_ia(mois=mois)

    def enregistrer(self, entree: Any) -> None:
        self._verifier(entree.client_id)
        with self.db.tenant(self.client_id, Acteur.systeme("couts")) as scope:
            enregistrer_cout(scope, cout_eur=entree.cout_eur, jetons_entree=entree.jetons_entree,
                             jetons_sortie=entree.jetons_sortie, modele=entree.modele,
                             dossier_id=entree.dossier_id, lot_id=entree.lot_id)
