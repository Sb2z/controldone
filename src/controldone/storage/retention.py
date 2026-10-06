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

from sqlalchemy import delete, select, update

from controldone.auth.roles import Acteur, Action, Ressource, Role, peut
from controldone.storage import garde
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

__all__ = ["RapportPurge", "cloturer_inactifs", "exporter_client", "purger_expires", "supprimer_client"]


@dataclass
class RapportPurge:
    fichiers: dict[str, int] = field(default_factory=dict)
    textes: dict[str, int] = field(default_factory=dict)
    #: Contenus non référencés mais redéposés récemment (dépôt en cours) : gardés (D-1324).
    epargnes: int = 0

    @property
    def total(self) -> int:
        return sum(self.fichiers.values()) + sum(self.textes.values())


def cloturer_inactifs(db: Database, now: datetime | None = None, *, jours: int = 60) -> dict[str, int]:
    """Clôture automatique (point de départ de la conservation, SPEC §20.4 ; D-1301).

    - **Dossier** : non clos, sans activité (``modifie_le``) depuis ``jours`` jours, sans écart à recouvrer
      encore ouvert (statut autre que ``credite``/``abandonne``) et sans constat en attente de décision
      (``propose``) dans sa version courante.
    - **Lot** : ``en_erreur`` (aucun fichier exploitable) reçu depuis ``jours`` jours ; ou traité dont tous
      les dossiers sont clos (un lot traité sans dossier est clos à la même échéance).

    Une nouvelle activité sur un dossier clos (nouveau lot rattaché, recontrôle) le rouvre
    (``TenantScope.enregistrer_dossier``). Une transaction par client ; journalisé (``cloture_auto``)."""
    now = now or maintenant()
    limite = now - timedelta(days=jours)
    total = {"dossiers": 0, "lots": 0}
    with db.transaction_systeme() as s:
        tenants = [t for (t,) in s.execute(select(Tenant.id).order_by(Tenant.id))]
    for tid in tenants:
        with db.transaction_systeme() as s:
            ouverts_constats = set(
                s.execute(
                    select(Constat.dossier_id)
                    .join(Ecart, (Ecart.constat_id == Constat.id) & (Ecart.tenant_id == Constat.tenant_id))
                    .where(Constat.tenant_id == tid, Ecart.statut.not_in(("credite", "abandonne")))
                ).scalars()
            )
            en_attente = set(
                s.execute(
                    select(Constat.dossier_id)
                    .join(
                        Dossier,
                        (Dossier.id == Constat.dossier_id)
                        & (Dossier.tenant_id == Constat.tenant_id)
                        & (Dossier.version == Constat.dossier_version),
                    )
                    .where(Constat.tenant_id == tid, Constat.statut_validation == "propose")
                ).scalars()
            )
            n_dos = 0
            for d in s.execute(
                select(Dossier).where(
                    Dossier.tenant_id == tid, Dossier.cloture_le.is_(None), Dossier.modifie_le <= limite
                )
            ).scalars():
                if d.id in ouverts_constats or d.id in en_attente:
                    continue
                s.execute(
                    update(Dossier)
                    .where(Dossier.tenant_id == tid, Dossier.id == d.id)
                    .values(cloture_le=now, modifie_le=d.modifie_le)
                    .execution_options(synchronize_session=False)
                )
                n_dos += 1
            vivants = set(
                s.execute(
                    select(Dossier.lot_id).where(
                        Dossier.tenant_id == tid, Dossier.cloture_le.is_(None), Dossier.lot_id.is_not(None)
                    )
                ).scalars()
            )
            n_lot = 0
            for lot in s.execute(
                select(Lot).where(
                    Lot.tenant_id == tid,
                    Lot.cloture_le.is_(None),
                    Lot.recu_le <= limite,
                    Lot.statut.in_(("en_erreur", "traite")),
                )
            ).scalars():
                if lot.statut == "traite" and lot.id in vivants:
                    continue
                lot.cloture_le = now
                n_lot += 1
            if n_dos or n_lot:
                journaliser(
                    s,
                    actor="systeme:retention",
                    role="systeme",
                    action="cloture_auto",
                    tenant_id=tid,
                    details={"dossiers": n_dos, "lots": n_lot, "jours": jours},
                )
            total["dossiers"] += n_dos
            total["lots"] += n_lot
    return total


#: Fichiers traités par transaction de purge (le verrou d'écriture SQLite reste court, D-1309).
PURGE_PAR_TRANSACTION = 500
#: Un contenu redéposé à l'identique depuis moins de ce délai n'est pas retiré du coffre par la purge.
GARDE_REDEPOT_S = 3600


def purger_expires(
    db: Database, vault: FileVault, now: datetime | None = None, *, attente_verrou_s: float = 0.0
) -> RapportPurge:
    """Purge des contenus expirés. Une transaction par client et par paquet de ``PURGE_PAR_TRANSACTION``
    fichiers ; textes de page chargés par paquet (pas une requête par fichier).

    Sous le verrou de maintenance (``storage.verrou``, D-3504), partagé avec la sauvegarde et la restauration :
    lève ``VerrouOccupe`` si l'une d'elles est en cours (le handler reporte alors le job)."""
    from controldone.storage.verrou import verrou_maintenance

    with verrou_maintenance(vault.racine.parent, "purge", attente_s=attente_verrou_s):
        return _purger_expires(db, vault, now)


def _purger_expires(db: Database, vault: FileVault, now: datetime | None) -> RapportPurge:
    now = now or maintenant()
    rapport = RapportPurge()
    with db.transaction_systeme() as s:
        tenants = [(t.id, t.retention_jours) for t in s.execute(select(Tenant).order_by(Tenant.id)).scalars()]
    a_effacer: list[tuple[str, str, str]] = []  # (tenant, sha, espace)
    for tid, retention in tenants:
        limite = now - timedelta(days=retention)
        with db.session(lecture=True) as s:
            s.info[garde.CLE_SYSTEME] = True
            expires = set(
                s.execute(
                    select(Dossier.id).where(
                        Dossier.tenant_id == tid,
                        Dossier.cloture_le.is_not(None),
                        Dossier.cloture_le <= limite,
                    )
                ).scalars()
            )
            liens: dict[str, set[str]] = {}
            for fid, did in s.execute(
                select(DossierFichier.fichier_id, DossierFichier.dossier_id).where(
                    DossierFichier.tenant_id == tid
                )
            ):
                liens.setdefault(fid, set()).add(did)
            lots_clos = set(
                s.execute(
                    select(Lot.id).where(
                        Lot.tenant_id == tid, Lot.cloture_le.is_not(None), Lot.cloture_le <= limite
                    )
                ).scalars()
            )
            candidats = [
                fid
                for fid, lot_id in s.execute(
                    select(Fichier.id, Fichier.lot_id)
                    .where(Fichier.tenant_id == tid, Fichier.purge_le.is_(None))
                    .order_by(Fichier.id)
                )
                if (liens[fid] <= expires if fid in liens else (lot_id or "") in lots_clos)
            ]
        n_fic = n_txt = 0
        for i in range(0, len(candidats), PURGE_PAR_TRANSACTION):
            paquet = candidats[i : i + PURGE_PAR_TRANSACTION]
            with db.transaction_systeme() as s:
                for p in s.execute(
                    select(PageTexte).where(PageTexte.tenant_id == tid, PageTexte.fichier_id.in_(paquet))
                ).scalars():
                    if p.texte_ref:
                        a_effacer.append((tid, p.texte_ref, "textes"))
                        n_txt += 1
                    p.texte_ref, p.purge_le = None, now
                for f in s.execute(
                    select(Fichier).where(
                        Fichier.tenant_id == tid, Fichier.id.in_(paquet), Fichier.purge_le.is_(None)
                    )
                ).scalars():
                    if f.coffre_ref:
                        a_effacer.append((tid, f.coffre_ref, "fichiers"))
                    f.coffre_ref, f.purge_le = None, now
                    n_fic += 1
        if n_fic or n_txt:
            rapport.fichiers[tid], rapport.textes[tid] = n_fic, n_txt
            with db.transaction_systeme() as s:
                journaliser(
                    s,
                    actor="systeme:retention",
                    role="systeme",
                    action="purge_retention",
                    tenant_id=tid,
                    details={"fichiers": n_fic, "textes": n_txt, "retention_jours": retention},
                )
    # Adressage par contenu : un contenu encore référencé par une ligne non purgée est conservé. Vérification
    # et suppression **sous le verrou d'écriture** (un dépôt enregistre ses fichiers dans une transaction
    # d'écriture : il voit la suppression, ou la purge voit sa ligne), et un contenu redéposé à l'identique
    # depuis moins de ``GARDE_REDEPOT_S`` (dépôt en cours, pas encore enregistré) est épargné (D-1324).
    seuil = (now - timedelta(seconds=GARDE_REDEPOT_S)).timestamp()
    tries = sorted(set(a_effacer))
    for i in range(0, len(tries), PURGE_PAR_TRANSACTION):
        with db.transaction_systeme() as s:
            for tenant, sha, espace in tries[i : i + PURGE_PAR_TRANSACTION]:
                if espace == "fichiers":
                    q = select(Fichier.id).where(Fichier.tenant_id == tenant, Fichier.coffre_ref == sha)
                else:
                    q = select(PageTexte.id).where(PageTexte.tenant_id == tenant, PageTexte.texte_ref == sha)
                if s.execute(q.limit(1)).first() is not None:
                    continue
                depuis = vault.depose_depuis(tenant, sha, espace=espace)
                if depuis is not None and depuis >= seuil:
                    rapport.epargnes += 1
                    continue
                vault.supprimer(tenant, sha, espace=espace)
    return rapport


#: Attente du verrou de maintenance par l'effacement d'un client (une sauvegarde en cours dure quelques minutes :
#: l'effacement est alors refusé, à relancer ensuite).
ATTENTE_VERROU_EFFACEMENT_S = 10.0


def supprimer_client(
    db: Database,
    vault: FileVault,
    tenant_id: str,
    acteur: Acteur,
    motif: str,
    *,
    dossier_sorties: Path | str | None = None,
    attente_verrou_s: float = ATTENTE_VERROU_EFFACEMENT_S,
) -> dict[str, int]:
    """Efface toutes les données d'un client (base + coffre + traces des envois mis à disposition, chiffrées dans
    ``dossier_sorties``, défaut ``<data_dir>/outbox_envoyee``). Réservé au fondateur ; motif obligatoire.

    Sous le verrou de maintenance (D-3504, D-4103), partagé avec la sauvegarde, la purge et la restauration :
    attente courte (``attente_verrou_s``), puis ``VerrouOccupe`` (« sauvegarde en cours depuis … ») sans rien
    avoir effacé — une sauvegarde ne copie jamais un client à moitié effacé."""
    if not peut(acteur, Action.supprimer_client, Ressource("client", tenant_id)):
        raise AccesRefuse("effacement réservé au fondateur")
    if not (motif and motif.strip()):
        raise ValueError("motif obligatoire")
    from controldone.storage.verrou import verrou_maintenance

    with verrou_maintenance(vault.racine.parent, "effacement_client", attente_s=attente_verrou_s):
        return _supprimer_client(db, vault, tenant_id, acteur, motif, dossier_sorties)


def _supprimer_client(
    db: Database,
    vault: FileVault,
    tenant_id: str,
    acteur: Acteur,
    motif: str,
    dossier_sorties: Path | str | None,
) -> dict[str, int]:
    comptes: dict[str, int] = {}
    with db.transaction_systeme(effacement=True) as s:
        if s.get(Tenant, tenant_id) is None:
            raise AccesRefuse("client introuvable")
        membres = [
            m.user_id
            for m in s.execute(select(Membership).where(Membership.tenant_id == tenant_id)).scalars()
        ]
        for modele in MODELES_CLIENT:
            res = s.execute(
                delete(modele)
                .where(modele.tenant_id == tenant_id)  # type: ignore[attr-defined]
                .execution_options(synchronize_session=False)
            )
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
        journaliser(
            s,
            actor=acteur.id,
            role=acteur.role.value,
            action="supprimer_client",
            tenant_id=tenant_id,
            target=f"tenants:{tenant_id}",
            ip=acteur.ip,
            details={"motif": motif[:200], "lignes": {k: v for k, v in comptes.items() if v}},
        )
    vault.supprimer_client(tenant_id)
    if dossier_sorties is None:
        from controldone.config import get_settings

        dossier_sorties = Path(get_settings().data_dir) / "outbox_envoyee"
    from controldone.storage.traces_envoi import TracesEnvoi

    comptes["traces_envoi"] = TracesEnvoi(Path(dossier_sorties), vault.cles_maitresses).supprimer_client(
        tenant_id
    )
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


def exporter_client(
    db: Database, vault: FileVault, tenant_id: str, acteur: Acteur, destination: Path | str
) -> Path:
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
            for nom, modele in (
                ("entites", Entite),
                ("transitaires", Transitaire),
                ("grilles", Grille),
                ("lots", Lot),
                ("fichiers", Fichier),
                ("couts_ia", AiUsage),
            ):
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
                    if voit_resultats
                    else [],
                }
                ecrire(f"dossiers/{_nom_sur(d.id)}.json", _json(bloc))
            ecrire(
                "recouvrement.json",
                _json(
                    {
                        "ecarts": [_ligne(o) for o in scope.lister(Ecart)],
                        "evenements": [_ligne(o) for o in scope.lister(EvenementRecouvrement)],
                        "reclamations": [_ligne(o) for o in scope.lister(Reclamation)],
                    }
                ),
            )
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
            z.writestr(
                "manifest.json",
                _json(
                    {
                        "schema": "controldone.export/1.0.0",
                        "client": tenant_id,
                        "genere_le": maintenant().isoformat(),
                        "genere_par": acteur.id,
                        "contenu": manifeste,
                    }
                ),
            )
        scope._auditer("exporter_client", f"tenants:{tenant_id}", {"entrees": len(manifeste)}, toujours=True)
        scope.commit()
    finally:
        if op is not None:
            op.close()
        if session is not None:
            session.close()
    return destination
