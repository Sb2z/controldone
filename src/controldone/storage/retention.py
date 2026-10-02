"""Conservation, effacement et restitution (SPEC §20.4).

- ``purger_expires(db, vault, now)`` : supprime fichiers bruts et textes de page ``retention_jours``
  après la clôture du dossier (un fichier commun à plusieurs dossiers attend l'expiration de tous ; un
  fichier rattaché à aucun dossier suit la clôture de son lot). Les métadonnées, constats, valeurs
  sourcées clés et le registre de recouvrement sont conservés.
- ``supprimer_client(db, vault, tenant_id, acteur, motif)`` : effacement complet d'un client (demande
  RGPD, fin de contrat) ; seul le journal d'audit (identifiants, sans contenu) est conservé, avec une
  entrée ``supprimer_client``.
- ``exporter_client(db, vault, tenant_id, acteur, destination)`` : archive ZIP (JSON + pièces d'origine,
  PDF compris) pour la restitution.
"""

from __future__ import annotations

import hashlib
import json
import re
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import delete, select

from controldone.auth.roles import Acteur, Action, Ressource, Role, peut
from controldone.storage.audit import journaliser
from controldone.storage.coltypes import maintenant
from controldone.storage.db import Database
from controldone.storage.erreurs import AccesRefuse
from controldone.storage.file_jobs import JobStore
from controldone.storage.models import (
    MODELES_CLIENT,
    AiUsage,
    Alerte,
    Base,
    Constat,
    Document,
    Dossier,
    DossierFichier,
    Ecart,
    Entite,
    EvenementRecouvrement,
    Fichier,
    Grille,
    Lot,
    Membership,
    Outbox,
    PageTexte,
    Reclamation,
    Resultat,
    Tenant,
    Transitaire,
    User,
)
from controldone.storage.vault import FileVault

__all__ = ["RapportPurge", "exporter_client", "purger_expires", "supprimer_client"]


@dataclass
class RapportPurge:
    fichiers: dict[str, int] = field(default_factory=dict)
    textes: dict[str, int] = field(default_factory=dict)

    @property
    def total(self) -> int:
        return sum(self.fichiers.values()) + sum(self.textes.values())


def purger_expires(db: Database, vault: FileVault, now: datetime | None = None) -> RapportPurge:
    now = now or maintenant()
    rapport = RapportPurge()
    with db.transaction_systeme() as s:
        a_effacer: list[tuple[str, str, str]] = []  # (tenant, sha, espace)
        for t in s.execute(select(Tenant)).scalars():
            limite = now - timedelta(days=t.retention_jours)
            dossiers = {d.id: d for d in s.execute(select(Dossier).where(Dossier.tenant_id == t.id)).scalars()}
            expires = {i for i, d in dossiers.items() if d.cloture_le is not None and d.cloture_le <= limite}
            liens: dict[str, set[str]] = {}
            for lien in s.execute(select(DossierFichier).where(DossierFichier.tenant_id == t.id)).scalars():
                liens.setdefault(lien.fichier_id, set()).add(lien.dossier_id)
            lots = {lot.id: lot for lot in s.execute(select(Lot).where(Lot.tenant_id == t.id)).scalars()}
            fichiers = list(s.execute(select(Fichier).where(Fichier.tenant_id == t.id)).scalars())
            n_fic = n_txt = 0
            for f in fichiers:
                if f.purge_le is not None:
                    continue
                if f.id in liens:
                    expire = liens[f.id] <= expires
                else:
                    lot = lots.get(f.lot_id or "")
                    expire = lot is not None and lot.cloture_le is not None and lot.cloture_le <= limite
                if not expire:
                    continue
                for p in s.execute(select(PageTexte).where(PageTexte.tenant_id == t.id,
                                                           PageTexte.fichier_id == f.id)).scalars():
                    if p.texte_ref:
                        a_effacer.append((t.id, p.texte_ref, "textes"))
                        n_txt += 1
                    p.texte_ref, p.purge_le = None, now
                if f.coffre_ref:
                    a_effacer.append((t.id, f.coffre_ref, "fichiers"))
                f.coffre_ref, f.purge_le = None, now
                n_fic += 1
            if n_fic or n_txt:
                rapport.fichiers[t.id], rapport.textes[t.id] = n_fic, n_txt
                journaliser(s, actor="systeme:retention", role="systeme", action="purge_retention",
                            tenant_id=t.id, details={"fichiers": n_fic, "textes": n_txt,
                                                     "retention_jours": t.retention_jours})
        s.flush()
        # Adressage par contenu : un contenu encore référencé par une ligne non purgée est conservé.
        encore = {(f.tenant_id, f.coffre_ref, "fichiers") for f in s.execute(
            select(Fichier).where(Fichier.coffre_ref.is_not(None))).scalars()}
        encore |= {(p.tenant_id, p.texte_ref, "textes") for p in s.execute(
            select(PageTexte).where(PageTexte.texte_ref.is_not(None))).scalars()}
    for tenant, sha, espace in set(a_effacer) - encore:
        vault.supprimer(tenant, sha, espace=espace)
    return rapport


def _supprimer_traces_envoi(dossier: Path, tenant_id: str) -> int:
    """Traces en clair de l'expéditeur fichier (``<dossier>/<kind>/<id>.json``, champ ``tenant_id``)."""
    n = 0
    if not dossier.is_dir():
        return 0
    for p in dossier.glob("*/*.json"):
        try:
            if json.loads(p.read_text(encoding="utf-8")).get("tenant_id") != tenant_id:
                continue
            p.unlink()
            n += 1
        except (OSError, ValueError, AttributeError):
            continue
    return n


def supprimer_client(db: Database, vault: FileVault, tenant_id: str, acteur: Acteur, motif: str, *,
                     dossier_sorties: Path | str | None = None) -> dict[str, int]:
    """Efface toutes les données d'un client (base + coffre + traces des envois mis à disposition, écrites en
    clair par l'expéditeur fichier dans ``dossier_sorties``, défaut ``<data_dir>/outbox_envoyee``). Réservé au
    fondateur ; motif obligatoire."""
    if not peut(acteur, Action.supprimer_client, Ressource("client", tenant_id)):
        raise AccesRefuse("effacement réservé au fondateur")
    if not (motif and motif.strip()):
        raise ValueError("motif obligatoire")
    comptes: dict[str, int] = {}
    with db.transaction_systeme(effacement=True) as s:
        if s.get(Tenant, tenant_id) is None:
            raise AccesRefuse("client introuvable")
        membres = [m.user_id for m in s.execute(select(Membership).where(Membership.tenant_id == tenant_id)).scalars()]
        for modele in MODELES_CLIENT:
            res = s.execute(delete(modele).where(modele.tenant_id == tenant_id)  # type: ignore[attr-defined]
                            .execution_options(synchronize_session=False))
            comptes[modele.__tablename__] = res.rowcount or 0  # type: ignore[attr-defined]
        utilisateurs = 0
        for uid in membres:
            reste = s.execute(select(Membership.id).where(Membership.user_id == uid).limit(1)).scalar()
            u = s.get(User, uid)
            if reste is None and u is not None and u.role != Role.fondateur.value:
                s.delete(u)
                utilisateurs += 1
        comptes["users"] = utilisateurs
        comptes["jobs"] = JobStore(db).supprimer_client(s, tenant_id)
        comptes["alertes"] = s.execute(delete(Alerte).where(Alerte.tenant_id == tenant_id)).rowcount or 0
        s.execute(delete(Tenant).where(Tenant.id == tenant_id))
        journaliser(s, actor=acteur.id, role=acteur.role.value, action="supprimer_client", tenant_id=tenant_id,
                    target=f"tenants:{tenant_id}", ip=acteur.ip,
                    details={"motif": motif[:200], "lignes": {k: v for k, v in comptes.items() if v}})
    vault.supprimer_client(tenant_id)
    if dossier_sorties is None:
        from controldone.config import get_settings

        dossier_sorties = Path(get_settings().data_dir) / "outbox_envoyee"
    comptes["traces_envoi"] = _supprimer_traces_envoi(Path(dossier_sorties), tenant_id)
    return comptes


# --- export -----------------------------------------------------------------------------------------

_NOM_RE = re.compile(r"[^A-Za-z0-9._-]+")


def _nom_sur(nom: str, defaut: str = "fichier") -> str:
    propre = _NOM_RE.sub("_", Path(nom.replace("\\", "/")).name).strip("._") or defaut
    return propre[:150]


def _ligne(obj: Base) -> dict[str, Any]:
    sortie: dict[str, Any] = {}
    for col in obj.__table__.columns.keys():  # noqa: SIM118  # type: ignore[attr-defined]
        if col in ("hash", "mot_de_passe_hash", "totp_secret_chiffre"):
            continue
        v = getattr(obj, col)
        if isinstance(v, datetime):
            v = v.isoformat()
        elif isinstance(v, Decimal):
            v = str(v)
        sortie[col] = v
    return sortie


def _json(data: Any) -> bytes:
    return json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True, default=str).encode("utf-8")


def exporter_client(db: Database, vault: FileVault, tenant_id: str, acteur: Acteur,
                    destination: Path | str) -> Path:
    """Archive de restitution. Fondateur (export complet, accès tracé) ou ``client_admin`` du client
    (constats publiés seulement)."""
    if not peut(acteur, Action.exporter, Ressource("client", tenant_id)):
        raise AccesRefuse("export refusé")
    from controldone.storage.scope import OperatorScope, TenantScope

    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    op: OperatorScope | None = None
    session = None
    if acteur.role is Role.fondateur:
        op = OperatorScope(db, acteur)
        scope = op.client(tenant_id, "export de restitution (RGPD §20.4)")
    else:
        session = db.session(lecture=True)
        scope = TenantScope(session, tenant_id, acteur)
    manifeste: dict[str, str] = {}
    try:
        with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as z:
            def ecrire(nom: str, data: bytes) -> None:
                z.writestr(nom, data)
                manifeste[nom] = hashlib.sha256(data).hexdigest()

            ecrire("client.json", _json(_ligne(scope.client())))
            voit_resultats = acteur.role is Role.fondateur
            for nom, modele in (("entites", Entite), ("transitaires", Transitaire), ("grilles", Grille),
                                ("lots", Lot), ("fichiers", Fichier), ("couts_ia", AiUsage)):
                ecrire(f"{nom}.json", _json([_ligne(o) for o in scope.lister(modele)]))
            # Actions sortantes : un rôle client ne voit que celles mises à disposition (``envoye``), comme dans
            # son espace ; brouillons, refus et corrections internes restent au fondateur (revue RS-06).
            sorties_ = scope.lister(Outbox) if voit_resultats else scope.lister(Outbox, statut="envoye")
            ecrire("sorties.json", _json([_ligne(o) for o in sorties_]))
            for d in scope.lister(Dossier, ordre=Dossier.id):
                bloc = {
                    "dossier": _ligne(d),
                    "documents": [_ligne(o) for o in scope.lister(Document, dossier_id=d.id)],
                    "constats": [_ligne(o) for o in scope.constats(d.id)],
                    "resultats": [_ligne(o) for o in scope.lister(Resultat, dossier_id=d.id)]
                    if voit_resultats else [],
                }
                ecrire(f"dossiers/{_nom_sur(d.id)}.json", _json(bloc))
            ecrire("recouvrement.json", _json({
                "ecarts": [_ligne(o) for o in scope.lister(Ecart)],
                "evenements": [_ligne(o) for o in scope.lister(EvenementRecouvrement)],
                "reclamations": [_ligne(o) for o in scope.lister(Reclamation)],
            }))
            if voit_resultats:
                ecrire("constats_tous.json", _json([_ligne(o) for o in scope.lister(Constat)]))
            for f in scope.lister(Fichier, ordre=Fichier.id):
                if not f.coffre_ref:
                    continue
                try:
                    contenu = vault.lire(tenant_id, f.coffre_ref)
                except FileNotFoundError:
                    continue
                ecrire(f"pieces/{_nom_sur(f.id)}/{_nom_sur(f.nom_original)}", contenu)
            z.writestr("manifest.json", _json({
                "schema": "controldone.export/1.0.0", "client": tenant_id, "genere_le": maintenant().isoformat(),
                "genere_par": acteur.id, "contenu": manifeste,
            }))
        scope._auditer("exporter_client", f"tenants:{tenant_id}", {"entrees": len(manifeste)}, toujours=True)
        scope.commit()
    finally:
        if op is not None:
            op.close()
        if session is not None:
            session.close()
    return destination
