"""La valeur sourcée (SPEC §6.3) et les règles de confiance des valeurs dérivées (§8.5.2)."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from decimal import Decimal, InvalidOperation

from pydantic import Field, field_validator, model_validator

from controldone.ids import Prefixe, nouvel_id
from controldone.model.base import Modele
from controldone.model.enums import (
    Methode,
    RaisonCode,
    SigneImprime,
    TotalOrigine,
    TypeExtracteur,
    TypeValeur,
)

__all__ = [
    "FACTEUR_NOM_FICHIER",
    "FACTEUR_RECONSTRUIT_OCR",
    "FACTEUR_SOMME_ANCREE",
    "PLAFOND_CONFIANCE_DESACCORD",
    "PLAFOND_CONFIANCE_LLM_NON_ANCREE",
    "PLAFOND_CONFIANCE_TOTAL_RECONSTRUIT",
    "ExtracteurInfo",
    "ValeurSourcee",
    "Zone",
    "confiance_derivee",
    "deriver_somme",
    "facteur_derivation",
]

#: §8.5.2 : somme de valeurs toutes ancrées.
FACTEUR_SOMME_ANCREE = 1.0
#: §8.5.2 : total reconstruit depuis des lignes OCR (ou non ancrées).
FACTEUR_RECONSTRUIT_OCR = 0.6
#: §8.5.2 : valeur tirée d'un nom de fichier.
FACTEUR_NOM_FICHIER = 0.3
#: §6.3 : une valeur ``llm`` non ancrée a sa confiance plafonnée à 0,50.
PLAFOND_CONFIANCE_LLM_NON_ANCREE = 0.50
#: §5.3.1 : total facture reconstruit (absent du document) plafonné à 0,60.
PLAFOND_CONFIANCE_TOTAL_RECONSTRUIT = 0.60
#: §7.3 : désaccord entre extracteurs sur un champ clé : confiance plafonnée à 0,80.
PLAFOND_CONFIANCE_DESACCORD = 0.80


class Zone(Modele):
    """Coordonnées relatives à la page (0–1), origine en haut à gauche."""

    x0: float = Field(ge=0, le=1)
    y0: float = Field(ge=0, le=1)
    x1: float = Field(ge=0, le=1)
    y1: float = Field(ge=0, le=1)


class ExtracteurInfo(Modele):
    type: TypeExtracteur
    id: str
    version: str


class ValeurSourcee(Modele):
    """Valeur extraite avec sa provenance (§6.3).

    ``valeur`` est **toujours une chaîne** (ou ``None`` si illisible) : décimal en notation point sans
    séparateur de milliers (``"12540.00"``), date ISO, code ISO, texte… Utiliser ``decimal()``,
    ``entier()``, ``date_iso()`` pour la lire typée. Les montants sont en valeur absolue ; un signe
    imprimé négatif est porté par ``signe_imprime`` (§5.2).
    """

    id: str = Field(default_factory=lambda: nouvel_id(Prefixe.valeur))
    chemin: str
    valeur: str | None
    type: TypeValeur = TypeValeur.texte
    unite: str | None = None
    unite_brute: str | None = None
    valeur_brute: str | None = None
    document_id: str | None = None
    page: int | None = Field(default=None, ge=1)
    zone: Zone | None = None
    texte_contexte: str | None = None
    extracteur: ExtracteurInfo
    methode: Methode
    confiance: float = Field(ge=0.0, le=1.0)
    derivee_de: list[str] = Field(default_factory=list)
    regle_derivation: str | None = None
    ancree: bool = False
    signe_imprime: SigneImprime | None = None
    total_origine: TotalOrigine | None = None
    #: Raisons mémorisées à l'extraction (ex. ``extracteurs_en_desaccord``, §7.3).
    raisons: list[RaisonCode] = Field(default_factory=list)
    #: Si cette valeur est une correction (``saisie_humaine``) : identifiant de la valeur remplacée.
    remplace: str | None = None

    @field_validator("confiance")
    @classmethod
    def _arrondi_confiance(cls, v: float) -> float:
        return round(float(v), 4)

    @model_validator(mode="after")
    def _regles_provenance(self) -> ValeurSourcee:
        # §6.3 : une valeur llm non ancrée a sa confiance plafonnée à 0,50.
        if (
            self.methode is Methode.llm
            and not self.ancree
            and self.confiance > PLAFOND_CONFIANCE_LLM_NON_ANCREE
        ):
            object.__setattr__(self, "confiance", PLAFOND_CONFIANCE_LLM_NON_ANCREE)
        if self.methode is Methode.derive and not self.derivee_de and self.regle_derivation is None:
            raise ValueError("une valeur dérivée doit citer ses sources (derivee_de) ou sa règle")
        return self

    # --- lecture typée ---

    @property
    def est_lisible(self) -> bool:
        return self.valeur is not None and self.valeur != ""

    def decimal(self) -> Decimal:
        """Valeur en ``Decimal`` (lève ``ValueError`` si absente ou non numérique)."""
        if self.valeur is None:
            raise ValueError(f"valeur absente ({self.chemin})")
        try:
            return Decimal(self.valeur)
        except InvalidOperation as e:
            raise ValueError(f"valeur non numérique ({self.chemin}) : {self.valeur!r}") from e

    def decimal_ou_none(self) -> Decimal | None:
        try:
            return self.decimal()
        except ValueError:
            return None

    def decimal_signe(self) -> Decimal:
        """Valeur numérique avec le signe imprimé (négative si ``signe_imprime = negatif``)."""
        d = self.decimal()
        return -d if self.signe_imprime is SigneImprime.negatif else d

    def entier(self) -> int:
        d = self.decimal()
        if d != d.to_integral_value():
            raise ValueError(f"valeur non entière ({self.chemin}) : {self.valeur!r}")
        return int(d)

    def date_iso(self) -> date:
        if self.valeur is None:
            raise ValueError(f"date absente ({self.chemin})")
        return date.fromisoformat(self.valeur)

    @property
    def est_structuree(self) -> bool:
        return self.methode.est_structuree

    @property
    def est_reconstruite(self) -> bool:
        return self.total_origine is TotalOrigine.reconstruit

    def ancrage_suffisant(self) -> bool:
        """Condition d'ancrage de §8.5.1 (3) : ancrée, ou méthode structurée / saisie humaine."""
        return self.ancree or self.est_structuree

    def fiable_pour_certain(self, c_min_certain: float) -> bool:
        """§8.5.1 (3) : confiance ≥ ``C_MIN_CERTAIN`` et ancrage suffisant."""
        return self.confiance >= c_min_certain and self.ancrage_suffisant()


def facteur_derivation(sources: Sequence[ValeurSourcee], *, depuis_nom_fichier: bool = False) -> float:
    """Facteur ``f`` de §8.5.2.

    - ``0,3`` pour une valeur tirée d'un nom de fichier ;
    - ``1,0`` si toutes les sources sont ancrées (ou structurées / saisies) et aucune n'est OCR ;
    - ``0,6`` sinon (reconstruction depuis des lignes OCR ou non ancrées : lecture prudente).
    """
    if depuis_nom_fichier:
        return FACTEUR_NOM_FICHIER
    if sources and all(s.ancrage_suffisant() and s.methode is not Methode.ocr for s in sources):
        return FACTEUR_SOMME_ANCREE
    return FACTEUR_RECONSTRUIT_OCR


def confiance_derivee(sources: Sequence[ValeurSourcee], facteur: float | None = None) -> float:
    """``confiance(dérivée) = min(confiances sources) × f`` (§8.5.2). 0 si aucune source."""
    if not sources:
        return 0.0
    f = facteur_derivation(sources) if facteur is None else facteur
    return round(min(s.confiance for s in sources) * f, 4)


def deriver_somme(
    chemin: str,
    sources: Sequence[ValeurSourcee],
    *,
    document_id: str | None,
    extracteur: ExtracteurInfo,
    type_valeur: TypeValeur = TypeValeur.montant,
    unite: str | None = None,
    regle: str = "somme",
    total_reconstruit: bool = False,
    id_valeur: str | None = None,
) -> ValeurSourcee:
    """Construit une valeur ``derive`` égale à la somme exacte des sources (sans arrondi intermédiaire).

    Avec ``total_reconstruit=True`` (total absent du document, §5.3.1) : ``total_origine = reconstruit``
    et confiance plafonnée à 0,60.
    """
    total = sum((s.decimal_signe() for s in sources), Decimal(0))
    conf = confiance_derivee(sources)
    if total_reconstruit:
        conf = min(conf, PLAFOND_CONFIANCE_TOTAL_RECONSTRUIT)
    signe = None
    if total < 0:
        signe, total = SigneImprime.negatif, -total
    kwargs = {"id": id_valeur} if id_valeur else {}
    return ValeurSourcee(
        **kwargs,
        chemin=chemin,
        valeur=str(total),
        type=type_valeur,
        unite=unite,
        document_id=document_id,
        extracteur=extracteur,
        methode=Methode.derive,
        confiance=conf,
        derivee_de=[s.id for s in sources],
        regle_derivation=regle,
        ancree=False,
        signe_imprime=signe,
        total_origine=TotalOrigine.reconstruit if total_reconstruit else None,
    )
