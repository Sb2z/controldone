"""Relevé de tous les connecteurs configurés : ``python -m controldone.connecteurs.releve`` (cron).

Configuration par client, dans ``reglages["connecteurs"]`` (aucun secret en base) :

    {"dossier_surveille": {"chemin": "/srv/depots/cli_x", "stabilite_s": 10},
     "imap": {"hote": "imap.exemple.fr", "utilisateur": "depot-cli-x", "secret_env": "CONTROLDONE_IMAP_CLI_X"},
     "plateforme_agreee": {"fournisseur": "fictif", "dossier": "/srv/pa/cli_x"}}

Liste blanche des expéditeurs de la boîte dédiée : ``reglages["expediteurs_autorises"]``.
Une erreur d'un connecteur n'arrête jamais les autres (journalisée par nom de classe seulement).
"""

from __future__ import annotations

import argparse
import json
import logging
from collections.abc import Callable, Sequence
from typing import Any

from controldone.auth.roles import Acteur
from controldone.storage.clients import clients_actifs
from controldone.storage.db import Database

from .base import ConnecteurEntrant
from .depot import integrer_depot
from .dossier_surveille import DossierSurveille
from .imap import BoiteImap, ConfigImap
from .plateforme_agreee import ClientPAFictif, PlateformeAgreeeEntrante

__all__ = ["FABRIQUES_PA", "connecteurs_configures", "main", "relever_tout"]

log = logging.getLogger("controldone.connecteurs")

#: Fournisseurs de PA branchés (aucun partenaire réel livré : bouchon « fictif » seulement).
FABRIQUES_PA: dict[str, Callable[[dict[str, Any]], Any]] = {
    "fictif": lambda conf: ClientPAFictif.depuis_dossier(conf["dossier"]),
}


def connecteurs_configures(db: Database) -> list[ConnecteurEntrant]:
    sortie: list[ConnecteurEntrant] = []
    for tenant in clients_actifs(db):
        with db.tenant(tenant, Acteur.systeme("connecteurs"), lecture=True) as sc:
            conf = dict((sc.client().reglages or {}).get("connecteurs") or {})
        if conf.get("dossier_surveille", {}).get("chemin"):
            d = conf["dossier_surveille"]
            sortie.append(DossierSurveille(tenant, d["chemin"], stabilite_s=float(d.get("stabilite_s", 10))))
        if conf.get("imap"):
            try:
                sortie.append(BoiteImap(tenant, ConfigImap.depuis_reglages(conf["imap"])))
            except (
                KeyError,
                TypeError,
                ValueError,
            ) as exc:  # configuration refusée : les autres clients continuent
                log.warning(
                    "connecteur_imap_config_refusee tenant=%s exception=%s", tenant, type(exc).__name__
                )
        pa = conf.get("plateforme_agreee") or {}
        if pa.get("fournisseur") in FABRIQUES_PA:
            sortie.append(PlateformeAgreeeEntrante(tenant, FABRIQUES_PA[pa["fournisseur"]](pa)))
    return sortie


def relever_tout(
    db: Database, vault: Any, connecteurs: Sequence[ConnecteurEntrant] | None = None
) -> list[dict[str, Any]]:
    """Relève chaque connecteur une fois, intègre ses dépôts et les acquitte ; renvoie un résumé."""
    resume = []
    for c in connecteurs if connecteurs is not None else connecteurs_configures(db):
        entree: dict[str, Any] = {"connecteur": c.nom, "tenant_id": c.tenant_id, "depots": []}
        try:
            for depot in c.relever():
                res = integrer_depot(db, vault, depot)
                acquitter = getattr(c, "acquitter", None)
                if acquitter is not None:
                    acquitter(depot, res)
                entree["depots"].append(res.en_dict())
        except Exception as exc:
            log.warning(
                "connecteur_erreur connecteur=%s tenant=%s exception=%s",
                c.nom,
                c.tenant_id,
                type(exc).__name__,
            )
            entree["erreur"] = type(exc).__name__
        resume.append(entree)
    return resume


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m controldone.connecteurs.releve")
    parser.add_argument("--init-schema", action="store_true")
    args = parser.parse_args(argv)
    from controldone.storage.vault import FileVault

    db = Database()
    if args.init_schema:
        db.creer_schema()
    try:
        print(json.dumps(relever_tout(db, FileVault.depuis_env()), ensure_ascii=False))
    finally:
        db.fermer()
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
