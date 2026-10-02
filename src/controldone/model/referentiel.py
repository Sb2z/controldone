"""Référentiels client : Client, Entite, Transitaire, GrilleTarifaire, ProfilTolerances (SPEC §6.2.1–6.2.4, §8.3)."""

from __future__ import annotations

import hashlib
from datetime import date
from decimal import Decimal
from typing import Any, ClassVar

from pydantic import Field, model_validator

from controldone.ids import Prefixe, nouvel_id
from controldone.model.base import Enregistrement, Modele, dump_canonique
from controldone.model.enums import (
    BasePourcentage,
    ModePoste,
    NatureLigne,
    Offre,
    PrestationsHorsGrille,
    StatutGrille,
)

__all__ = [
    "Client",
    "Entite",
    "ErreurTolerance",
    "GrilleTarifaire",
    "ParametresPetitsEnvois",
    "PosteGrille",
    "ProfilTolerances",
    "Transitaire",
]


class Client(Enregistrement):
    id: str = Field(default_factory=lambda: nouvel_id(Prefixe.client))
    raison_sociale: str
    offre: Offre = Offre.diagnostic
    plafond_cout_ia_mensuel_eur: Decimal = Decimal("8.00")
    retention_jours: int = 180
    boite_mail_dediee: str | None = None
    expediteurs_autorises: list[str] = Field(default_factory=list)


class Entite(Enregistrement):
    """Entité juridique contrôlée du client (§6.2.1). ``tva`` normalisée (majuscules, sans espace)."""

    id: str = Field(default_factory=lambda: nouvel_id(Prefixe.entite))
    raison_sociale: str
    tva: str | None = None
    siren: str | None = Field(default=None, pattern=r"^\d{9}$")
    eori: str | None = None
    alias: list[str] = Field(default_factory=list)
    adresses: list[str] = Field(default_factory=list)


class Transitaire(Enregistrement):
    id: str = Field(default_factory=lambda: nouvel_id(Prefixe.transitaire))
    nom: str
    tva: str | None = None
    alias: list[str] = Field(default_factory=list)
    adresse: str | None = None
    contact_reclamation: str | None = None


class PreuveGrille(Modele):
    document_id: str | None = None
    page: int | None = None
    description: str | None = None


class PosteGrille(Modele):
    """Poste d'une grille tarifaire (§6.2.4)."""

    code_poste: str
    nature: NatureLigne
    libelles_reconnus: list[str] = Field(default_factory=list)
    mode: ModePoste
    prix: Decimal | None = None
    #: Unité de base du prix unitaire (ex. ``article``, ``jour``, ``colis``, ``kg``).
    unite_base: str | None = None
    #: Pourcentage exprimé en pour cent (``2.5`` = 2,5 %).
    pourcentage: Decimal | None = None
    base_pourcentage: BasePourcentage | None = None
    minimum: Decimal | None = None
    maximum: Decimal | None = None
    franchise_jours: int | None = None
    #: Nombre d'unités comprises dans le forfait (ex. articles inclus, D9).
    inclus: int | None = None
    devise: str = "EUR"


class GrilleTarifaire(Enregistrement):
    id: str = Field(default_factory=lambda: nouvel_id(Prefixe.grille))
    transitaire_id: str
    reference: str
    valide_du: date | None = None
    valide_au: date | None = None
    statut: StatutGrille = StatutGrille.brouillon
    postes: list[PosteGrille] = Field(default_factory=list)
    prestations_hors_grille: PrestationsHorsGrille = PrestationsHorsGrille.tolerees
    preuve: PreuveGrille | None = None
    version: int = 1

    def applicable(self, transitaire_id: str, le: date | None) -> bool:
        """Seule une grille **validée**, du bon transitaire, valide à la date, sert aux contrôles D (§13)."""
        if self.statut is not StatutGrille.validee or self.transitaire_id != transitaire_id:
            return False
        if le is None:
            return self.valide_du is None and self.valide_au is None
        if self.valide_du is not None and le < self.valide_du:
            return False
        return not (self.valide_au is not None and le > self.valide_au)


class ErreurTolerance(ValueError):
    """Surcharge de tolérance refusée (seuil de certitude réduit, valeur négative…)."""


D = Decimal


class ProfilTolerances(Enregistrement):
    """Profil de tolérances (§8.3), versionné, avec empreinte SHA-256 du contenu canonique (§6.2.3).

    Les valeurs sont les **défauts** de la spécification. Règle de configuration : un client ne peut
    qu'**élargir** les seuils de certitude (``s_*``, ``c_min_certain``) — jamais les réduire — pour
    préserver la prudence. ``appliquer_surcharges`` l'impose. Les pourcentages sont des fractions
    (``0.001`` = 0,1 %).
    """

    id: str = Field(default_factory=lambda: nouvel_id(Prefixe.profil))
    version: int = 1

    # T_LIGNE
    t_ligne: Decimal = D("0.01")
    # T_SOMME = min(0,01 × n ; 0,50), au moins 0,01
    t_somme_par_ligne: Decimal = D("0.01")
    t_somme_plafond: Decimal = D("0.50")
    t_somme_minimum: Decimal = D("0.01")
    # T_TAXE_LIGNE (B1) : 0,01 EUR ou arrondi à l'euro du calcul
    t_taxe_ligne: Decimal = D("0.01")
    # T_VALEUR = max(1 unité ; 0,1 %) ; S_VALEUR = max(5 unités ; 0,5 %)
    t_valeur_unites: Decimal = D("1")
    t_valeur_fraction: Decimal = D("0.001")
    s_valeur_unites: Decimal = D("5")
    s_valeur_fraction: Decimal = D("0.005")
    # T_CONVERSION = max(1,00 EUR ; 0,1 %) ; S_CONVERSION = max(5,00 EUR ; 0,5 %)
    t_conversion_eur: Decimal = D("1.00")
    t_conversion_fraction: Decimal = D("0.001")
    s_conversion_eur: Decimal = D("5.00")
    s_conversion_fraction: Decimal = D("0.005")
    # BANDE_INDICATIVE : ± 25 % ; ± 40 % pour devises_volatiles
    bande_indicative: Decimal = D("0.25")
    bande_indicative_volatile: Decimal = D("0.40")
    devises_volatiles: list[str] = Field(
        default_factory=lambda: ["ARS", "EGP", "GHS", "LBP", "NGN", "PKR", "TRY", "VES", "ZWL"]
    )
    # T_DEBOURS = max(0,05 ; min(0,01 × nb_articles ; 0,50)) ; S_DEBOURS = 1,00
    t_debours_minimum: Decimal = D("0.05")
    t_debours_par_article: Decimal = D("0.01")
    t_debours_plafond: Decimal = D("0.50")
    s_debours: Decimal = D("1.00")
    # T_TARIF / S_TARIF / S_ARITH
    t_tarif: Decimal = D("0.01")
    s_tarif: Decimal = D("0.10")
    s_arith: Decimal = D("1.00")
    # Seuil de certitude des écarts de calcul sur la déclaration (B1, B2, B3, G1 : « > 1,00 EUR »).
    s_calcul_declaration: Decimal = D("1.00")
    # T_MASSE = max(0,5 kg ; 0,5 %)
    t_masse_kg: Decimal = D("0.5")
    t_masse_fraction: Decimal = D("0.005")
    # T_QUANTITE : 0 pour unités entières, 0,5 % sinon
    t_quantite_fraction: Decimal = D("0.005")
    # T_COLIS
    t_colis: Decimal = D("0")
    # Confiances
    c_min_certain: float = 0.90
    c_min_utile: float = 0.50
    # A6 (§10) : seuils de détection d'un montant repris sans conversion
    a6_ecart_taux_min: Decimal = D("0.02")
    a6_ecart_reference_min: Decimal = D("0.10")
    a6_confiance_devise_min: float = 0.95
    # Famille F : fenêtre de recherche en mois
    fenetre_doublons_mois: int = 24

    #: Champs dont la valeur ne peut qu'augmenter par rapport au défaut (seuils de certitude).
    SEUILS_NON_REDUCTIBLES: ClassVar[frozenset[str]] = frozenset(
        {
            "s_valeur_unites",
            "s_valeur_fraction",
            "s_conversion_eur",
            "s_conversion_fraction",
            "s_debours",
            "s_tarif",
            "s_arith",
            "s_calcul_declaration",
            "c_min_certain",
            "a6_confiance_devise_min",
        }
    )
    _CHAMPS_HORS_CONTENU: ClassVar[frozenset[str]] = frozenset(
        {"id", "client_id", "cree_le", "modifie_le", "version"}
    )

    @model_validator(mode="after")
    def _bornes(self) -> ProfilTolerances:
        for nom in type(self).model_fields:
            v = getattr(self, nom)
            if isinstance(v, Decimal | float | int) and not isinstance(v, bool) and v < 0:
                raise ErreurTolerance(f"tolérance négative : {nom}")
        if not 0 <= self.c_min_utile <= self.c_min_certain <= 1:
            raise ErreurTolerance("il faut 0 ≤ c_min_utile ≤ c_min_certain ≤ 1")
        return self

    def contenu(self) -> dict[str, Any]:
        """Contenu canonique (sans identifiant, horodatages ni version) : base de l'empreinte."""
        d = self.model_dump(mode="json", exclude=set(self._CHAMPS_HORS_CONTENU))
        d["devises_volatiles"] = sorted(d["devises_volatiles"])
        return d

    def empreinte(self) -> str:
        """SHA-256 hexadécimal du JSON canonique du contenu (§6.2.3)."""
        return hashlib.sha256(dump_canonique(self.contenu()).encode("utf-8")).hexdigest()

    @classmethod
    def defauts(cls, **kwargs: Any) -> ProfilTolerances:
        return cls(**kwargs)

    def appliquer_surcharges(self, surcharges: dict[str, Any]) -> ProfilTolerances:
        """Nouveau profil (version + 1) avec les surcharges du client.

        Lève ``ErreurTolerance`` si une surcharge réduit un seuil de certitude sous le **défaut** de la
        spécification (§8.3) ou nomme un champ inconnu.
        """
        defaut = type(self)()
        for nom, valeur in surcharges.items():
            if nom not in type(self).model_fields or nom in self._CHAMPS_HORS_CONTENU:
                raise ErreurTolerance(f"tolérance inconnue : {nom!r}")
            if nom in self.SEUILS_NON_REDUCTIBLES:
                attendu = type(getattr(defaut, nom))
                if attendu(str(valeur)) < getattr(defaut, nom):
                    raise ErreurTolerance(
                        f"{nom} : un seuil de certitude ne peut qu'être élargi (défaut {getattr(defaut, nom)})"
                    )
        donnees = self.model_dump(exclude={"id", "cree_le", "modifie_le"})
        donnees.update(surcharges)
        donnees["version"] = self.version + 1
        return type(self)(**donnees)


class ParametresPetitsEnvois(Modele):
    """Paramètres datés de la famille G (§16). Configurables, sans valeur réglementaire jugée.

    ``codes_forfait_petits_envois`` est vide par défaut : la reconnaissance se fait alors par libellé
    (``libelles_forfait_petits_envois``) ou par taux imprimé égal à ``forfait_unitaire`` (§16).
    """

    codes_forfait_petits_envois: list[str] = Field(default_factory=list)
    libelles_forfait_petits_envois: list[str] = Field(
        default_factory=lambda: [
            "droit forfaitaire",
            "forfait petits envois",
            "droit de douane forfaitaire",
            "flat rate duty",
            "flat-rate duty",
            "low value consignment duty",
        ]
    )
    forfait_unitaire_eur: Decimal = D("3.00")
    date_debut: date = date(2026, 7, 1)
    date_fin: date = date(2028, 7, 1)
    seuil_valeur_eur: Decimal = D("150")
