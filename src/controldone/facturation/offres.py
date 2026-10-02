"""Offres, paliers, coupons, TVA et identité du vendeur : lecture de ``config/offres.yaml`` (fonctions
pures, ``Decimal`` exact).

- Diagnostic : forfait (390 EUR HT par défaut) ;
- Commission : taux × base §17.4 (crédits imputés sur des écarts issus de constats validés) ;
- Contrôle continu : abonnement mensuel par paliers de dossiers (99 / 199 / 349 EUR HT : valeurs de départ) ;
- Coupon de lancement : remise de 100 % sur un diagnostic, réservée aux clients qui ont **signé** l'accord
  de publication des résultats anonymisés.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Any

import yaml

__all__ = [
    "A_COMPLETER",
    "CatalogueOffres",
    "Consentement",
    "Coupon",
    "CouponRefuse",
    "Palier",
    "ParametresPaiement",
    "ParametresTVA",
    "Vendeur",
    "arrondi",
    "charger_offres",
]

A_COMPLETER = "À COMPLÉTER"
_CENTIME = Decimal("0.01")


def arrondi(x: Decimal) -> Decimal:
    """Arrondi au centime, demi supérieur (convention commerciale)."""
    return Decimal(x).quantize(_CENTIME, rounding=ROUND_HALF_UP)


class CouponRefuse(ValueError):
    """Coupon inconnu, épuisé, déjà utilisé par ce client, ou consentement absent."""


@dataclass(frozen=True)
class Palier:
    code: str
    libelle: str
    prix_mensuel_ht: Decimal
    dossiers_par_mois: int


@dataclass(frozen=True)
class Coupon:
    code: str
    libelle: str
    offre: str
    remise_pourcentage: Decimal
    utilisations_max: int
    une_fois_par_client: bool = True
    consentement_requis: bool = True

    def remise(self, montant_ht: Decimal) -> Decimal:
        return arrondi(Decimal(montant_ht) * self.remise_pourcentage / Decimal(100))


@dataclass(frozen=True)
class Consentement:
    """Accord du client pour la publication de ses résultats anonymisés (contrepartie du coupon)."""

    signe: bool
    signe_par: str = ""
    signe_le: str = ""  # date ISO
    reference_document: str = ""  # ex. « accord-publication-2026-10-02.pdf » (pièce conservée hors ligne)


@dataclass(frozen=True)
class ParametresTVA:
    tva_applicable: bool = True
    taux: Decimal = Decimal("20.00")
    mention_franchise: str = "TVA non applicable, art. 293 B du CGI"
    option_debits: bool = False

    @property
    def taux_effectif(self) -> Decimal:
        return self.taux if self.tva_applicable else Decimal("0.00")

    @property
    def categorie(self) -> str:
        """Catégorie de TVA EN 16931 (UNTDID 5305) : S (taux normal) ou E (exonéré : franchise en base)."""
        return "S" if self.tva_applicable else "E"


@dataclass(frozen=True)
class ParametresPaiement:
    delai_jours: int = 30
    moyen: str = ""
    penalites: str = ""
    indemnite: str = ""
    escompte: str = ""


@dataclass(frozen=True)
class Vendeur:
    identifiant: str = "fondateur"
    raison_sociale: str = A_COMPLETER
    forme_juridique: str = A_COMPLETER
    siren: str = A_COMPLETER
    rcs: str = A_COMPLETER
    tva_intracom: str = A_COMPLETER
    adresse_ligne: str = A_COMPLETER
    code_postal: str = A_COMPLETER
    ville: str = A_COMPLETER
    pays: str = "FR"
    email: str = A_COMPLETER
    iban: str = A_COMPLETER
    bic: str = A_COMPLETER
    adresse_electronique: str = ""

    def champs_a_completer(self) -> list[str]:
        return [k for k, v in self.__dict__.items() if isinstance(v, str) and A_COMPLETER in v]

    @property
    def complet(self) -> bool:
        return not self.champs_a_completer()

    @property
    def adresse_electronique_effective(self) -> str:
        """Adresse de facturation électronique (annuaire, schéma 0225) : celle configurée, sinon le SIREN."""
        return self.adresse_electronique or self.siren


@dataclass(frozen=True)
class CatalogueOffres:
    prix_diagnostic_ht: Decimal
    libelle_diagnostic: str
    taux_commission: Decimal
    libelle_commission: str
    libelle_continu: str
    paliers: tuple[Palier, ...]
    coupons: dict[str, Coupon]
    tva: ParametresTVA
    paiement: ParametresPaiement
    vendeur: Vendeur
    prefixe_facture: str = "F"
    prefixe_avoir: str = "AV"
    chiffres: int = 4
    brut: dict[str, Any] = field(default_factory=dict, compare=False, repr=False)

    # --- calculs purs ---------------------------------------------------------------------------------
    def palier(self, code: str) -> Palier:
        for p in self.paliers:
            if p.code == code:
                return p
        raise KeyError(f"palier inconnu : {code}")

    def palier_pour(self, dossiers_par_mois: int) -> Palier:
        """Plus petit palier dont le quota couvre le volume ; au-delà du dernier, le dernier palier."""
        if dossiers_par_mois < 0:
            raise ValueError("volume négatif")
        for p in sorted(self.paliers, key=lambda x: x.dossiers_par_mois):
            if dossiers_par_mois <= p.dossiers_par_mois:
                return p
        return max(self.paliers, key=lambda x: x.dossiers_par_mois)

    def commission(self, base: Decimal) -> Decimal:
        """Commission = base §17.4 × taux, au centime (demi supérieur), comme ``litiges.commission``."""
        if Decimal(base) < 0:
            raise ValueError("base de commission négative")
        return arrondi(Decimal(base) * self.taux_commission)

    def coupon(self, code: str) -> Coupon:
        c = self.coupons.get((code or "").strip().upper())
        if c is None:
            raise CouponRefuse("coupon inconnu")
        return c

    def verifier_coupon(self, code: str, *, offre: str, consentement: Consentement | None,
                        utilisations: int, deja_utilise_par_client: bool) -> Coupon:
        """Règles du coupon (pures) : offre visée, quota global, une fois par client, consentement signé."""
        c = self.coupon(code)
        if c.offre != offre:
            raise CouponRefuse(f"coupon réservé à l'offre « {c.offre} »")
        if c.consentement_requis and not (consentement and consentement.signe and consentement.signe_par.strip()
                                          and consentement.signe_le.strip()):
            raise CouponRefuse("accord de publication des résultats anonymisés non signé")
        if utilisations >= c.utilisations_max:
            raise CouponRefuse("coupon épuisé")
        if c.une_fois_par_client and deja_utilise_par_client:
            raise CouponRefuse("coupon déjà utilisé par ce client")
        return c


def _dec(v: Any, defaut: str) -> Decimal:
    return Decimal(str(v if v is not None else defaut))


def _vendeur(brut: dict[str, Any], env: dict[str, str]) -> Vendeur:
    valeurs: dict[str, str] = {}
    for nom in Vendeur.__dataclass_fields__:
        v = env.get(f"CONTROLDONE_VENDEUR_{nom.upper()}")
        if v is None:
            v = brut.get(nom)
        if v is not None:
            valeurs[nom] = str(v).strip()
    return Vendeur(**valeurs)


def charger_offres(chemin: Path | str | None = None, *, env: dict[str, str] | None = None) -> CatalogueOffres:
    """Lit ``config/offres.yaml`` (ou ``chemin``) ; l'identité du vendeur peut venir de l'environnement."""
    if chemin is None:
        from controldone.config import get_settings

        chemin = Path(get_settings().config_dir) / "offres.yaml"
    brut = yaml.safe_load(Path(chemin).read_text(encoding="utf-8")) or {}
    env = dict(os.environ) if env is None else env
    o = brut.get("offres", {})
    diag, com, cont = o.get("diagnostic", {}), o.get("commission", {}), o.get("continu", {})
    paliers = tuple(Palier(code=str(p["code"]), libelle=str(p.get("libelle", p["code"])),
                           prix_mensuel_ht=_dec(p["prix_mensuel_ht"], "0"), dossiers_par_mois=int(p["dossiers_par_mois"]))
                    for p in cont.get("paliers", []))
    if not paliers:
        raise ValueError("offre « continu » : au moins un palier attendu")
    coupons = {}
    for code, c in (brut.get("coupons") or {}).items():
        coupons[str(code).upper()] = Coupon(
            code=str(code).upper(), libelle=str(c.get("libelle", code)), offre=str(c.get("offre", "diagnostic")),
            remise_pourcentage=_dec(c.get("remise_pourcentage"), "0"),
            utilisations_max=int(c.get("utilisations_max", 0)),
            une_fois_par_client=bool(c.get("une_fois_par_client", True)),
            consentement_requis=bool(c.get("consentement_requis", True)))
    t = brut.get("tva", {})
    tva_env = env.get("CONTROLDONE_TVA_APPLICABLE")
    tva = ParametresTVA(
        tva_applicable=(tva_env.strip().lower() in ("1", "true", "oui")) if tva_env else bool(t.get("tva_applicable", True)),
        taux=_dec(t.get("taux"), "20.00"),
        mention_franchise=str(t.get("mention_franchise", "TVA non applicable, art. 293 B du CGI")),
        option_debits=bool(t.get("option_debits", False)))
    p = brut.get("paiement", {})
    paiement = ParametresPaiement(delai_jours=int(p.get("delai_jours", 30)), moyen=str(p.get("moyen", "")),
                                  penalites=str(p.get("penalites", "")), indemnite=str(p.get("indemnite", "")),
                                  escompte=str(p.get("escompte", "")))
    taux = _dec(com.get("taux"), "0.20")
    if not Decimal(0) <= taux <= Decimal(1):
        raise ValueError("taux de commission hors de [0, 1]")
    n = brut.get("numerotation", {})
    return CatalogueOffres(
        prix_diagnostic_ht=_dec(diag.get("prix_ht"), "390.00"), libelle_diagnostic=str(diag.get("libelle", "Diagnostic")),
        taux_commission=taux, libelle_commission=str(com.get("libelle", "Commission")),
        libelle_continu=str(cont.get("libelle", "Contrôle continu")), paliers=paliers, coupons=coupons, tva=tva,
        paiement=paiement, vendeur=_vendeur(brut.get("vendeur", {}), env),
        prefixe_facture=str(n.get("facture", "F")), prefixe_avoir=str(n.get("avoir", "AV")),
        chiffres=int(n.get("chiffres", 4)), brut=brut)
