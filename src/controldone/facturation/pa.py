"""Connecteur vers la **plateforme agréée (PA) partenaire du fondateur**, pour ses propres factures.

**ControlDOne n'est pas une plateforme agréée et ne prétend pas l'être.** Il ne transmet aucune facture
ni aucune donnée à l'administration, ne fait pas d'e-reporting et ne gère pas l'annuaire. Pour ses propres
factures, le fondateur passe par une PA immatriculée qu'il choisit (liste de contrôle :
``docs/FACTURATION.md``) ; ce module n'est que le client de l'API de cette PA (dépôt d'une facture
Factur-X, lecture des statuts de cycle de vie). Tant qu'aucune PA n'est branchée, le bouchon
``PlateformeAgreeeBouchon`` écrit dans ``var/pa_bouchon/``.

Calendrier (``docs/recherche/einvoice.md``, sources impots.gouv.fr) : **réception** obligatoire pour
toutes les entreprises depuis le 1er septembre 2026 ; **émission** obligatoire depuis le 1er septembre
2026 pour les grandes entreprises et les ETI, au plus tard le 1er septembre 2027 pour les PME, TPE et
micro-entreprises (cas du fondateur).

Statuts de cycle de vie : seuls « Déposée » (200), « Refusée » (210), « Encaissée » (212) et « Rejetée »
(213) sont cités comme obligatoires par des sources secondaires ; la liste complète vient de sources non
officielles (hypothèse à confirmer sur XP Z12-012 avant tout branchement réel).
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol, runtime_checkable

__all__ = [
    "STATUTS_CYCLE_DE_VIE",
    "STATUTS_OBLIGATOIRES",
    "AccuseDepot",
    "FactureADeposer",
    "PlateformeAgreee",
    "PlateformeAgreeeBouchon",
    "StatutCycleVie",
]

#: Codes de statut (hypothèse : sources non officielles du brief ; à confirmer sur XP Z12-012).
STATUTS_CYCLE_DE_VIE: dict[str, str] = {
    "200": "Déposée",
    "201": "Émise par la plateforme",
    "202": "Reçue par la plateforme",
    "203": "Mise à disposition",
    "204": "Prise en charge",
    "205": "Approuvée",
    "206": "Approuvée partiellement",
    "207": "En litige",
    "208": "Suspendue",
    "209": "Complétée",
    "210": "Refusée",
    "211": "Paiement transmis",
    "212": "Encaissée",
    "213": "Rejetée",
}
STATUTS_OBLIGATOIRES = ("200", "210", "212", "213")

_NOM_RE = re.compile(r"[^A-Za-z0-9_.-]")


@dataclass(frozen=True)
class FactureADeposer:
    numero: str
    facture_id: str
    siren_acheteur: str
    contenu: bytes  # PDF Factur-X (XML CII embarqué)
    format: str = "factur-x"


@dataclass(frozen=True)
class AccuseDepot:
    identifiant_pa: str
    numero: str
    code: str
    horodatage: str


@dataclass(frozen=True)
class StatutCycleVie:
    identifiant_pa: str
    numero: str
    code: str
    libelle: str
    horodatage: str
    motif: str | None = None


@runtime_checkable
class PlateformeAgreee(Protocol):
    """API de la PA partenaire du fondateur (dépôt et statuts de SES factures)."""

    nom: str

    def deposer_facture(self, facture: FactureADeposer) -> AccuseDepot:
        """Dépose la facture (idempotent par numéro) ; renvoie l'accusé (statut 200 « Déposée »)."""
        ...

    def statut(self, identifiant_pa: str) -> StatutCycleVie | None:
        """Dernier statut connu de la facture."""
        ...

    def recevoir_statuts(self) -> list[StatutCycleVie]:
        """Statuts reçus depuis le dernier appel (chaque statut n'est rendu qu'une fois)."""
        ...


def _maintenant() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _ecrire(chemin: Path, contenu: bytes) -> None:
    chemin.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, tmp = tempfile.mkstemp(dir=chemin.parent, prefix=".tmp-")
    with os.fdopen(fd, "wb") as f:
        f.write(contenu)
    os.chmod(tmp, 0o600)
    os.replace(tmp, chemin)


class PlateformeAgreeeBouchon:
    """Bouchon local : ``<racine>/deposees/<numero>.pdf`` + ``.json`` ; statuts simulés dans
    ``<racine>/statuts/`` (``simuler_statut``), rendus une fois par ``recevoir_statuts``."""

    nom = "pa_bouchon"

    def __init__(self, racine: Path | str | None = None) -> None:
        if racine is None:
            from controldone.config import get_settings

            racine = Path(get_settings().data_dir) / "pa_bouchon"
        self.racine = Path(racine)

    def _id(self, numero: str) -> str:
        return "PA-BOUCHON-" + _NOM_RE.sub("_", numero)

    def deposer_facture(self, facture: FactureADeposer) -> AccuseDepot:
        if facture.contenu[:5] != b"%PDF-":
            raise ValueError("dépôt refusé : PDF Factur-X attendu")
        ident = self._id(facture.numero)
        meta = self.racine / "deposees" / f"{ident}.json"
        if meta.exists():  # idempotent
            m = json.loads(meta.read_text(encoding="utf-8"))
            return AccuseDepot(ident, facture.numero, "200", m["horodatage"])
        h = _maintenant()
        _ecrire(self.racine / "deposees" / f"{ident}.pdf", facture.contenu)
        _ecrire(
            meta,
            json.dumps(
                {
                    "identifiant_pa": ident,
                    "numero": facture.numero,
                    "facture_id": facture.facture_id,
                    "siren_acheteur": facture.siren_acheteur,
                    "format": facture.format,
                    "horodatage": h,
                },
                ensure_ascii=False,
            ).encode(),
        )
        self.simuler_statut(ident, "200", horodatage=h)
        return AccuseDepot(ident, facture.numero, "200", h)

    def simuler_statut(
        self, identifiant_pa: str, code: str, *, motif: str | None = None, horodatage: str | None = None
    ) -> StatutCycleVie:
        if code not in STATUTS_CYCLE_DE_VIE:
            raise ValueError(f"code de statut inconnu : {code}")
        meta = self.racine / "deposees" / f"{_NOM_RE.sub('_', identifiant_pa)}.json"
        if not meta.exists():
            raise KeyError("facture inconnue de la plateforme")
        numero = json.loads(meta.read_text(encoding="utf-8"))["numero"]
        s = StatutCycleVie(
            identifiant_pa, numero, code, STATUTS_CYCLE_DE_VIE[code], horodatage or _maintenant(), motif
        )
        n = len(list((self.racine / "statuts").glob("*.json"))) + len(
            list((self.racine / "statuts" / "lus").glob("*.json"))
        )
        _ecrire(
            self.racine / "statuts" / f"{n:06d}-{_NOM_RE.sub('_', identifiant_pa)}-{code}.json",
            json.dumps(asdict(s), ensure_ascii=False).encode(),
        )
        return s

    def _tous(self) -> list[tuple[Path, StatutCycleVie]]:
        out = []
        fichiers = list((self.racine / "statuts").glob("*.json")) + list(
            (self.racine / "statuts" / "lus").glob("*.json")
        )
        for p in sorted(fichiers, key=lambda x: x.name):
            out.append((p, StatutCycleVie(**json.loads(p.read_text(encoding="utf-8")))))
        return out

    def statut(self, identifiant_pa: str) -> StatutCycleVie | None:
        derniers = [s for _p, s in self._tous() if s.identifiant_pa == identifiant_pa]
        return derniers[-1] if derniers else None

    def recevoir_statuts(self) -> list[StatutCycleVie]:
        sortie = []
        lus = self.racine / "statuts" / "lus"
        lus.mkdir(parents=True, exist_ok=True, mode=0o700)
        for p in sorted((self.racine / "statuts").glob("*.json")):
            sortie.append(StatutCycleVie(**json.loads(p.read_text(encoding="utf-8"))))
            os.replace(p, lus / p.name)
        return sortie
