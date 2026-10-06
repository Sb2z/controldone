"""Lecture des référentiels d'un client : ``profil.json`` et grilles tarifaires (SPEC §6.2.1–6.2.4, §19.2).

Format de ``profil.json`` (banc, §19.2) ::

    {"schema": "controldone.bench.profil/1.0.0", "client_id": "CL03",
     "entites": [{"raison_sociale", "tva", "siren", "eori", "alias": []}],
     "transitaires": [{"transitaire_id", "nom", "tva", "alias": []}],
     "tolerances": {}}

Champs facultatifs reconnus : ``raison_sociale`` (du client), ``offre`` (``diagnostic`` | ``continu``),
``demo`` (booléen : données fictives de démonstration), ``periode``.

Grilles : un fichier JSON par grille (``GrilleTarifaire`` ; ``transitaire_id`` = identifiant du
transitaire du profil). Lecture tolérante : champs inconnus ignorés, statut ``validee`` par défaut pour
les grilles du banc (« grilles tarifaires validées », §19.2), grille illisible écartée sans bloquer.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from controldone.ids import Prefixe, id_stable
from controldone.model.enums import Offre, StatutGrille
from controldone.model.referentiel import (
    Client,
    Entite,
    GrilleTarifaire,
    ParametresPetitsEnvois,
    ProfilTolerances,
    Transitaire,
)

__all__ = ["ProfilClient", "charger_grilles", "charger_profil_client", "profil_depuis_dict"]

log = logging.getLogger("controldone.referentiel")


@dataclass
class ProfilClient:
    """Référentiels d'un client nécessaires au pipeline."""

    client: Client
    entites: list[Entite] = field(default_factory=list)
    transitaires: list[Transitaire] = field(default_factory=list)
    tolerances: ProfilTolerances = field(default_factory=lambda: ProfilTolerances(id="tol_defaut"))
    parametres_petits_envois: ParametresPetitsEnvois = field(default_factory=ParametresPetitsEnvois)
    #: Données fictives de démonstration : bandeau « DONNÉES FICTIVES » sur le rapport.
    demo: bool = False
    periode: str | None = None

    @property
    def client_id(self) -> str:
        return self.client.id


def _siren(x: Any) -> str | None:
    s = str(x or "").strip()
    return s if len(s) == 9 and s.isdigit() else None


def profil_depuis_dict(data: Mapping[str, Any]) -> ProfilClient:
    client_id = str(data.get("client_id") or "client")
    client = Client(
        id=client_id,
        raison_sociale=str(
            data.get("raison_sociale") or (data.get("entites") or [{}])[0].get("raison_sociale") or client_id
        ),
        offre=Offre(data.get("offre", "diagnostic")),
    )
    entites = []
    for e in data.get("entites", []) or []:
        entites.append(
            Entite(
                id=e.get("id") or id_stable(Prefixe.entite, client_id, e.get("tva"), e.get("raison_sociale")),
                client_id=client_id,
                raison_sociale=e.get("raison_sociale") or "",
                tva=e.get("tva"),
                siren=_siren(e.get("siren")),
                eori=e.get("eori"),
                alias=list(e.get("alias") or []),
                adresses=list(e.get("adresses") or []),
            )
        )
    transitaires = []
    for t in data.get("transitaires", []) or []:
        tid = (
            t.get("transitaire_id") or t.get("id") or id_stable(Prefixe.transitaire, client_id, t.get("nom"))
        )
        transitaires.append(
            Transitaire(
                id=str(tid),
                client_id=client_id,
                nom=t.get("nom") or str(tid),
                tva=t.get("tva"),
                alias=list(t.get("alias") or []),
                adresse=t.get("adresse"),
                contact_reclamation=t.get("contact_reclamation"),
            )
        )
    tol = ProfilTolerances(id=id_stable(Prefixe.profil, client_id), client_id=client_id)
    surcharges = data.get("tolerances") or {}
    if surcharges:
        tol = tol.appliquer_surcharges(dict(surcharges))
    pe = data.get("parametres_petits_envois")
    return ProfilClient(
        client=client,
        entites=entites,
        transitaires=transitaires,
        tolerances=tol,
        parametres_petits_envois=ParametresPetitsEnvois.model_validate(pe)
        if pe
        else ParametresPetitsEnvois(),
        demo=bool(data.get("demo", False)),
        periode=data.get("periode"),
    )


def charger_profil_client(source: Path | str | Mapping[str, Any] | ProfilClient | None) -> ProfilClient:
    """Profil depuis un chemin, un dictionnaire ou un ``ProfilClient`` ; ``None`` -> profil anonyme."""
    if isinstance(source, ProfilClient):
        return source
    if source is None:
        return profil_depuis_dict({"client_id": "client", "raison_sociale": "Client"})
    if isinstance(source, Mapping):
        return profil_depuis_dict(source)
    return profil_depuis_dict(json.loads(Path(source).read_text(encoding="utf-8")))


def _grille_depuis_dict(
    data: Mapping[str, Any], client_id: str | None, defaut_validee: bool
) -> GrilleTarifaire:
    d = dict(data)
    d.setdefault("id", d.get("grille_id") or id_stable(Prefixe.grille, client_id, d.get("reference")))
    d.setdefault("reference", d.get("grille_id") or d["id"])
    if "statut" not in d and defaut_validee:
        d["statut"] = StatutGrille.validee.value
    d.setdefault("client_id", client_id)
    d["postes"] = [p for p in (_poste_tolerant(x) for x in d.get("postes") or []) if p is not None]
    return GrilleTarifaire.model_validate(d)


def _poste_tolerant(p: Mapping[str, Any]) -> dict[str, Any] | None:
    """Valeurs d'énumération inconnues : base de pourcentage -> ``autre`` ; nature -> ``autre_prestation`` ;
    mode inconnu : poste écarté (journal sans contenu)."""
    from controldone.model.enums import BasePourcentage, ModePoste, NatureLigne

    q = dict(p)
    if q.get("base_pourcentage") not in (None, *[x.value for x in BasePourcentage]):
        q["base_pourcentage"] = BasePourcentage.autre.value
    if q.get("nature") not in [x.value for x in NatureLigne]:
        q["nature"] = NatureLigne.autre_prestation.value
    if q.get("mode") not in [x.value for x in ModePoste]:
        log.warning("poste_de_grille_ecarte mode_inconnu")
        return None
    return q


def charger_grilles(
    source: Path | str | None, *, client_id: str | None = None, defaut_validee: bool = True
) -> list[GrilleTarifaire]:
    """Grilles d'un dossier (``*.json``, ordre trié) ou d'un fichier. Une grille illisible est écartée
    (journal sans contenu) ; seules les grilles validées serviront aux contrôles D."""
    if source is None:
        return []
    p = Path(source)
    fichiers = sorted(p.glob("*.json")) if p.is_dir() else ([p] if p.exists() else [])
    grilles = []
    for f in fichiers:
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            items = (
                data
                if isinstance(data, list)
                else data.get("grilles", [data])
                if isinstance(data, dict)
                else []
            )
            for item in items:
                grilles.append(_grille_depuis_dict(item, client_id, defaut_validee))
        except Exception as e:  # une grille illisible ne bloque pas le lot
            log.warning("grille_illisible fichier=%s exception=%s", f.name, type(e).__name__)
    return grilles
