"""Connecteur ``DossierSurveille`` : dossier de dépôt surveillé par client (relevé par interrogation).

- Un fichier n'est pris que s'il est **stable** : même taille et même date de modification qu'au relevé
  précédent, ou non modifié depuis ``stabilite_s`` secondes (fichier en cours de copie : attendu).
- Fichiers ignorés : cachés (``.``), temporaires (``~$``, ``.part``, ``.tmp``, ``.crdownload``), liens
  symboliques, et tout ce qui est sous le sous-dossier d'archive.
- Un relevé = un dépôt (arborescence relative conservée, utile au regroupement §7.5).
- ``acquitter`` déplace les fichiers relevés vers ``<racine>/_archive/<AAAAMMJJ>/…`` (sans écraser) ;
  l'idempotence repose aussi sur le sha256 (un fichier redéposé n'est pas retraité, §7.1).
"""

from __future__ import annotations

import json
import os
import shutil
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from .base import Depot, ResultatDepot

__all__ = ["DossierSurveille"]

_SUFFIXES_TEMP = (".part", ".tmp", ".crdownload", ".partial")


class DossierSurveille:
    nom = "dossier_surveille"

    def __init__(self, tenant_id: str, racine: Path | str, *, stabilite_s: float = 10.0,
                 archive: str = "_archive", horloge: Callable[[], float] = time.time,
                 max_fichiers: int = 2000) -> None:
        self.tenant_id = tenant_id
        self.racine = Path(racine)
        self.stabilite_s = stabilite_s
        self.archive = archive
        self.horloge = horloge
        self.max_fichiers = max_fichiers
        self._etat_chemin = self.racine / ".etat_surveillance.json"

    # --- état des tailles observées -------------------------------------------------------------------
    def _lire_etat(self) -> dict[str, list[int]]:
        try:
            return json.loads(self._etat_chemin.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def _ecrire_etat(self, etat: dict[str, list[int]]) -> None:
        tmp = self._etat_chemin.with_suffix(".tmp")
        tmp.write_text(json.dumps(etat, sort_keys=True), encoding="utf-8")
        os.replace(tmp, self._etat_chemin)

    def _candidats(self) -> list[Path]:
        if not self.racine.is_dir():
            return []
        sortie = []
        for p in sorted(self.racine.rglob("*")):
            rel = p.relative_to(self.racine)
            if rel.parts[0] == self.archive or any(x.startswith((".", "~$")) for x in rel.parts):
                continue
            if p.is_symlink() or not p.is_file() or p.name.lower().endswith(_SUFFIXES_TEMP):
                continue
            sortie.append(p)
        return sortie[: self.max_fichiers]

    def relever(self) -> list[Depot]:
        maintenant = self.horloge()
        precedent = self._lire_etat()
        etat: dict[str, list[int]] = {}
        prets: list[tuple[str, bytes]] = []
        for p in self._candidats():
            rel = p.relative_to(self.racine).as_posix()
            st = p.stat()
            signature = [st.st_size, st.st_mtime_ns]
            stable = precedent.get(rel) == signature or (maintenant - st.st_mtime) >= self.stabilite_s
            if not stable:
                etat[rel] = signature
                continue
            contenu = p.read_bytes()
            if len(contenu) != st.st_size:  # modifié pendant la lecture : au prochain relevé
                etat[rel] = [len(contenu), st.st_mtime_ns]
                continue
            prets.append((rel, contenu))
        self._ecrire_etat(etat)
        if not prets:
            return []
        return [Depot(tenant_id=self.tenant_id, canal="depot", source=self.nom, elements=prets,
                      meta={"chemins": [r for r, _ in prets]})]

    def acquitter(self, depot: Depot, resultat: ResultatDepot) -> None:
        """Archive les fichiers intégrés (lot créé, déjà reçus ou vides) ; rien en cas d'erreur."""
        if resultat.statut not in ("lot_cree", "deja_recu", "vide"):
            return
        jour = datetime.fromtimestamp(self.horloge(), UTC).strftime("%Y%m%d")
        base = self.racine / self.archive / jour
        for rel in depot.meta.get("chemins", []):
            source = self.racine / rel
            if not source.exists():
                continue
            cible = base / rel
            cible.parent.mkdir(parents=True, exist_ok=True)
            n = 1
            while cible.exists():
                cible = (base / rel).with_name(f"{Path(rel).stem}-{n}{Path(rel).suffix}")
                n += 1
            shutil.move(str(source), str(cible))
        # répertoires de dépôt vidés : supprimés (hors racine et archive)
        for d in sorted((x for x in self.racine.rglob("*") if x.is_dir()), key=lambda x: len(x.parts), reverse=True):
            rel = d.relative_to(self.racine)
            if rel.parts[0] != self.archive and not any(d.iterdir()):
                d.rmdir()
