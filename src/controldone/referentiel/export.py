"""Export du référentiel anonymisé (CSV et JSON) et calcul complet (``recalculer``)."""

from __future__ import annotations

import csv
import hashlib
import hmac
import io
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from controldone.storage.db import Database

from .anonymisation import charger_alias_publics
from .calcul import ResultatReferentiel, Seuils, agreger
from .collecte import NATURES_PRIX, collecter

__all__ = ["SCHEMA_REFERENTIEL", "en_csv", "en_json", "recalculer", "sel_referentiel"]

SCHEMA_REFERENTIEL = "controldone.referentiel/1.0.0"


def sel_referentiel() -> bytes:
    """Sel secret du hachage des transitaires : ``CONTROLDONE_REFERENTIEL_SEL``, sinon dérivé de la clé
    maîtresse (HMAC, usage « referentiel »). Jamais exporté."""
    brut = os.environ.get("CONTROLDONE_REFERENTIEL_SEL")
    if brut:
        return brut.encode("utf-8")
    from controldone.storage.cles import charger_cles_maitresses

    return hmac.new(charger_cles_maitresses()[0], b"controldone-referentiel", hashlib.sha256).digest()


def en_json(res: ResultatReferentiel, *, genere_le: datetime | None = None) -> dict[str, Any]:
    return {
        "schema": SCHEMA_REFERENTIEL,
        "genere_le": (genere_le or datetime.now(UTC)).isoformat(),
        "seuils": {"clients_distincts_min": res.seuils.k_clients, "dossiers_min": res.seuils.k_dossiers},
        "arrondis": {"montants_eur": "5", "taux": "0.05", "effectifs": "tranches"},
        "agregats_publies": len(res.agregats),
        "agregats_supprimes": res.supprimes,
        "agregats": [
            {"transitaire": a.transitaire, "groupe_origine": a.groupe_origine, "regime": a.regime,
             "famille_incoterm": a.famille_incoterm, "mois": a.mois, "dossiers": a.dossiers,
             "taux_dossiers_avec_ecart": str(a.taux_dossiers_avec_ecart),
             "prix": {n: {k: str(v) for k, v in s.items()} for n, s in a.prix.items()}}
            for a in res.agregats
        ],
    }


def en_csv(res: ResultatReferentiel) -> str:
    entetes = ["transitaire", "groupe_origine", "regime", "famille_incoterm", "mois", "dossiers",
               "taux_dossiers_avec_ecart"]
    for n in NATURES_PRIX:
        entetes += [f"{n}_p25", f"{n}_mediane", f"{n}_p75"]
    tampon = io.StringIO()
    w = csv.writer(tampon, lineterminator="\n")
    w.writerow(entetes)
    for a in res.agregats:
        ligne = [a.transitaire, a.groupe_origine, a.regime, a.famille_incoterm, a.mois, a.dossiers,
                 str(a.taux_dossiers_avec_ecart)]
        for n in NATURES_PRIX:
            s = a.prix.get(n) or {}
            ligne += [str(s.get("p25", "")), str(s.get("mediane", "")), str(s.get("p75", ""))]
        w.writerow(ligne)
    return tampon.getvalue()


def recalculer(db: Database, *, dossier_sortie: Path | str | None = None, sel: bytes | None = None,
               alias_publics: dict | None = None, seuils: Seuils | None = None) -> dict[str, Any]:
    """Collecte, agrège, écrit ``referentiel.json`` et ``referentiel.csv`` ; renvoie un résumé."""
    if dossier_sortie is None:
        from controldone.config import get_settings

        dossier_sortie = Path(get_settings().data_dir) / "referentiel"
    sortie = Path(dossier_sortie)
    sortie.mkdir(parents=True, exist_ok=True)
    enregistrements, stats = collecter(db)
    res = agreger(enregistrements, sel=sel or sel_referentiel(),
                  alias_publics=charger_alias_publics() if alias_publics is None else alias_publics, seuils=seuils)
    (sortie / "referentiel.json").write_text(json.dumps(en_json(res), ensure_ascii=False, indent=2), encoding="utf-8")
    (sortie / "referentiel.csv").write_text(en_csv(res), encoding="utf-8")
    return {"publies": len(res.agregats), "supprimes": res.supprimes, **stats, "dossier": str(sortie)}
