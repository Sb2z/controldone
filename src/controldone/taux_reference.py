"""Table locale datée des taux de référence BCE (``ref/taux_bce.csv``, SPEC §8.7).

Format CSV : ``date,devise,devise_par_eur`` (convention BCE : unités de devise pour 1 EUR).
Usage **limité** (§8.7) : déterminer le sens d'un taux imprimé sans libellé, et A7 (ordre de grandeur).
Jamais pour calculer un montant en jeu.

Le fichier est alimenté hors ligne par ``scripts/importer_taux_bce.py`` à partir du fichier historique publié
par la BCE (``eurofxref-hist.csv``, format large : une colonne par devise) ; voir D-806.
"""

from __future__ import annotations

import csv
import hashlib
import io
import zipfile
from bisect import bisect_right
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

__all__ = ["TableTauxReference", "convertir_historique_bce", "table_par_defaut"]


class TableTauxReference:
    """Accès en lecture aux taux de référence, par devise et par date."""

    #: Écart maximal entre la date demandée et la dernière publication (week-ends, jours fériés).
    ANCIENNETE_MAX = timedelta(days=7)

    def __init__(self, taux: dict[str, dict[date, Decimal]] | None = None) -> None:
        self._taux: dict[str, list[tuple[date, Decimal]]] = {
            dev.upper(): sorted(par_date.items()) for dev, par_date in (taux or {}).items()
        }
        self._empreinte: str | None = None

    def empreinte(self) -> str:
        """Empreinte du contenu de la table (clé d'idempotence de l'étape 7), calculée une fois."""
        if self._empreinte is None:
            h = hashlib.sha256()
            for dev in sorted(self._taux):
                for d, t in self._taux[dev]:
                    h.update(f"{dev}|{d.isoformat()}|{t}\n".encode())
            self._empreinte = h.hexdigest()
        return self._empreinte

    @classmethod
    def depuis_csv(cls, chemin: Path | str) -> TableTauxReference:
        donnees: dict[str, dict[date, Decimal]] = {}
        with open(chemin, encoding="utf-8", newline="") as f:
            for ligne in csv.DictReader(f):
                donnees.setdefault(ligne["devise"].upper(), {})[date.fromisoformat(ligne["date"])] = Decimal(
                    ligne["devise_par_eur"]
                )
        return cls(donnees)

    def devise_par_eur(self, devise: str, le: date) -> Decimal | None:
        """Taux publié le jour ``le`` ou au plus 7 jours avant ; ``None`` sinon. EUR -> 1."""
        devise = devise.upper()
        if devise == "EUR":
            return Decimal(1)
        serie = self._taux.get(devise)
        if not serie:
            return None
        i = bisect_right(serie, (le, Decimal("Infinity"))) - 1
        if i < 0:
            return None
        d, t = serie[i]
        return t if le - d <= self.ANCIENNETE_MAX else None

    def eur_par_devise(self, devise: str, le: date) -> Decimal | None:
        t = self.devise_par_eur(devise, le)
        return None if t is None or t == 0 else Decimal(1) / t


def convertir_historique_bce(contenu: bytes, *, depuis: date | None = None) -> str:
    """Convertit le fichier historique de la BCE (``eurofxref-hist.csv`` ou son archive ZIP : ``Date,USD,JPY,…``,
    valeurs « N/A » pour une devise non cotée) au format ``date,devise,devise_par_eur`` de ``ref/taux_bce.csv``.
    Lignes triées par date puis devise ; ``depuis`` limite la période conservée."""
    if contenu[:2] == b"PK":
        with zipfile.ZipFile(io.BytesIO(contenu)) as z:
            nom = next(n for n in z.namelist() if n.lower().endswith(".csv"))
            contenu = z.read(nom)
    lignes: list[tuple[str, str, str]] = []
    for ligne in csv.DictReader(io.StringIO(contenu.decode("utf-8-sig"))):
        jour = (ligne.get("Date") or "").strip()
        if not jour:
            continue
        d = date.fromisoformat(jour)
        if depuis is not None and d < depuis:
            continue
        for devise, valeur in ligne.items():
            if not devise or devise == "Date" or valeur is None:
                continue
            valeur = valeur.strip()
            if not valeur or valeur.upper() == "N/A":
                continue
            Decimal(valeur)  # refuse une valeur non numérique
            lignes.append((d.isoformat(), devise.strip().upper(), valeur))
    lignes.sort()
    sortie = io.StringIO()
    w = csv.writer(sortie, lineterminator="\n")
    w.writerow(["date", "devise", "devise_par_eur"])
    w.writerows(lignes)
    return sortie.getvalue()


_DEFAUT: dict[str, TableTauxReference | None] = {}


def table_par_defaut() -> TableTauxReference | None:
    """Table ``<ref_dir>/taux_bce.csv`` (réglage ``CONTROLDONE_REF_DIR``), chargée une fois ; ``None`` si le
    fichier est absent ou ne contient aucun taux."""
    import os

    from controldone.config import RACINE_DEPOT

    # lecture directe de l'environnement : ne pas figer le cache des réglages (``get_settings``) ici
    chemin = Path(os.environ.get("CONTROLDONE_REF_DIR") or RACINE_DEPOT / "ref") / "taux_bce.csv"
    cle = str(chemin)
    if cle not in _DEFAUT:
        table = None
        if chemin.is_file():
            t = TableTauxReference.depuis_csv(chemin)
            table = t if t._taux else None
        _DEFAUT[cle] = table
    return _DEFAUT[cle]
