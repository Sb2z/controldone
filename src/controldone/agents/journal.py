"""Journal des agents : un fichier JSONL par jour sous ``<data_dir>/journal_agents/`` (D-603).

Une ligne par événement (``debut``, ``outil``, ``refus_outil``, ``llm``, ``fin``, ``erreur``) :
identifiants, noms d'outils, compteurs, empreintes. **Jamais de contenu de document ni de texte de
client** : une chaîne longue ou libre est remplacée par sa longueur et son empreinte SHA-256 tronquée.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

__all__ = ["JournalAgents", "resumer"]

_ID_RE = re.compile(r"^[A-Za-z0-9_:\-.@/+]{1,96}$")
_VERROU = threading.Lock()


def _empreinte(texte: str) -> str:
    return f"<texte {len(texte)} car. sha256:{hashlib.sha256(texte.encode('utf-8')).hexdigest()[:12]}>"


def resumer(valeur: Any, profondeur: int = 0) -> Any:
    """Résumé journalisable d'une valeur : identifiants courts gardés, textes libres remplacés."""
    if valeur is None or isinstance(valeur, bool | int | float):
        return valeur
    if isinstance(valeur, str):
        return valeur if _ID_RE.match(valeur) else _empreinte(valeur)
    if isinstance(valeur, dict):
        if profondeur >= 1:
            return {"cles": sorted(str(k) for k in valeur)[:20]}
        return {str(k): resumer(v, profondeur + 1) for k, v in list(valeur.items())[:20]}
    if isinstance(valeur, list | tuple | set):
        return {"elements": len(valeur)}
    return type(valeur).__name__


class JournalAgents:
    def __init__(self, racine: Path | str | None = None) -> None:
        if racine is None:
            from controldone.config import get_settings

            racine = Path(get_settings().data_dir) / "journal_agents"
        self.racine = Path(racine)

    def chemin(self, quand: datetime) -> Path:
        return self.racine / f"{quand.astimezone(UTC).strftime('%Y-%m-%d')}.jsonl"

    def ecrire(self, *, agent: str, execution_id: str, tenant_id: str | None, evenement: str,
               quand: datetime | None = None, **champs: Any) -> None:
        quand = quand or datetime.now(UTC)
        entree = {"ts": quand.astimezone(UTC).isoformat(), "execution_id": execution_id, "agent": agent,
                  "tenant_id": tenant_id, "evenement": evenement, **champs}
        ligne = json.dumps(entree, ensure_ascii=False, sort_keys=True, default=str)
        chemin = self.chemin(quand)
        with _VERROU:
            chemin.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            fd = os.open(chemin, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
            with os.fdopen(fd, "a", encoding="utf-8") as f:
                f.write(ligne + "\n")

    def lire(self, quand: datetime | None = None) -> list[dict[str, Any]]:
        chemin = self.chemin(quand or datetime.now(UTC))
        if not chemin.exists():
            return []
        return [json.loads(x) for x in chemin.read_text(encoding="utf-8").splitlines() if x.strip()]
