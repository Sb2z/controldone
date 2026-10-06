"""Couche d'accès unique aux données client (SPEC §20.1, D-003).

- ``TenantScope(session, tenant_id, actor)`` : **toutes** les lectures et écritures de données client
  passent par lui. Chaque requête est filtrée par ``tenant_id`` (filtre explicite + critère automatique de
  ``storage.garde`` + contrôle au flush). Un identifiant d'un autre client donne ``AccesRefuse``, exactement
  comme un identifiant inexistant.
- ``OperatorScope(db, actor)`` : accès transversal du fondateur, chaque accès écrit une entrée d'audit
  (``acces_admin``) ; l'écriture dans un client passe par ``op.client(tenant_id, motif)`` qui renvoie un
  ``TenantScope`` dont chaque écriture est aussi journalisée.

Règles de rôle (``auth.roles.peut``) : un rôle client n'ouvre que le périmètre de son propre client (et
doit en être membre) ; ``client_lecteur`` ne peut rien écrire ; un rôle client ne voit que les constats
``valide`` (publication §4) et jamais les résultats bruts ; le fondateur n'ouvre un client que via
``OperatorScope``.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any, TypeVar

from sqlalchemy import Numeric, case, cast, false, func, select, true
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from controldone.auth.roles import ROLES_CLIENT, Acteur, Action, Ressource, Role, peut
from controldone.storage import garde
from controldone.storage.audit import journaliser
from controldone.storage.coltypes import maintenant
from controldone.storage.erreurs import AccesRefuse
from controldone.storage.models import (
    AiUsage,
    Alerte,
    AppendOnly,
    AuditLog,
    Base,
    CleApi,
    Constat,
    CorrectionValeur,
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
    TenantMixin,
    Transitaire,
)

if TYPE_CHECKING:
    from controldone.model.dossier import Dossier as DossierModele
    from controldone.model.recouvrement import EcartARecouvrer
    from controldone.model.referentiel import GrilleTarifaire
    from controldone.model.resultats import ResultatControle
    from controldone.storage.db import Database

__all__ = ["OperatorScope", "TenantScope"]

M = TypeVar("M", bound=Base)

_JETON_OPERATEUR = object()
#: Modèles qu'un rôle client ne lit jamais directement (résultats bruts non publiés, hachés des clés).
_LECTURE_CLIENT_INTERDITE: frozenset[type] = frozenset({Resultat})
_CHAMPS_PROTEGES = frozenset({"id", "tenant_id"})
#: Tables qu'un rôle client peut écrire par l'API générique (le reste passe par des méthodes dédiées
#: qui portent leur propre contrôle de droit, ou est réservé au moteur et au fondateur).
_ECRITURE_CLIENT: frozenset[type] = frozenset({Lot, Fichier, PageTexte, Entite, Transitaire, Grille, Reclamation})
#: Champs dont la modification exige une permission particulière.
_CHAMPS_SENSIBLES: dict[type, dict[str, Action]] = {
    Constat: {"statut_validation": Action.valider_constat, "valide_par": Action.valider_constat,
              "valide_le": Action.valider_constat},
    Grille: {"statut": Action.valider_grille, "valide_par": Action.valider_grille,
             "valide_le": Action.valider_grille},
}
#: Valeur « neutre » d'un champ sensible à la création (pas de permission exigée).
_VALEURS_NEUTRES: dict[str, set[Any]] = {"statut_validation": {"propose"}, "statut": {"brouillon"},
                                         "valide_par": {None}, "valide_le": {None}}


def _modele_client(modele: type) -> None:
    if not (isinstance(modele, type) and issubclass(modele, TenantMixin) and issubclass(modele, Base)):
        raise AccesRefuse(f"{getattr(modele, '__name__', modele)!s} n'est pas une table de données client")


class TenantScope:
    """Périmètre d'un client. Ne pas partager une session entre deux clients."""

    def __init__(self, session: Session, tenant_id: str, actor: Acteur, *, _jeton: object = None) -> None:
        if not isinstance(tenant_id, str) or not tenant_id:
            raise AccesRefuse("client invalide")
        if not isinstance(actor, Acteur):
            raise AccesRefuse("acteur invalide")
        if actor.role is Role.fondateur and _jeton is not _JETON_OPERATEUR:
            raise AccesRefuse("le fondateur accède à un client via OperatorScope (accès tracé)")
        if actor.role in ROLES_CLIENT and actor.tenant_id != tenant_id:
            raise AccesRefuse("accès à un autre client refusé")
        info = session.info
        if info.get(garde.CLE_SYSTEME) or info.get(garde.CLE_OPERATEUR):
            raise AccesRefuse("session non cloisonnée : ouvrir une session dédiée")
        lie = info.get(garde.CLE_TENANT)
        if lie is not None and lie != tenant_id:
            raise AccesRefuse("session déjà liée à un autre client")
        info[garde.CLE_TENANT] = tenant_id
        self.session = session
        self.tenant_id = tenant_id
        self.actor = actor
        self._via_operateur = _jeton is _JETON_OPERATEUR
        tenant = session.get(Tenant, tenant_id)
        if tenant is None or not tenant.actif:
            raise AccesRefuse("client introuvable ou hors périmètre")
        if actor.role in ROLES_CLIENT and actor.id.startswith("api:"):
            # acteur issu d'une clé d'API (``auth.cles_api``) : la clé doit être de ce client, active, même rôle
            cle = session.execute(
                select(CleApi).where(CleApi.tenant_id == tenant_id, CleApi.id == actor.id[4:])
            ).scalar_one_or_none()
            if cle is None or cle.revoquee_le is not None or cle.role != actor.role.value:
                raise AccesRefuse("clé d'API non valable pour ce client")
        elif actor.role in ROLES_CLIENT:
            membre = session.execute(
                select(Membership).where(
                    Membership.tenant_id == tenant_id, Membership.user_id == actor.id
                )
            ).scalar_one_or_none()
            if membre is None or membre.role != actor.role.value:
                raise AccesRefuse("utilisateur non membre de ce client")

    # --- outils internes ---------------------------------------------------------------------------
    def _ressource(self, type_: str = "donnees") -> Ressource:
        return Ressource(type_, self.tenant_id)

    def exiger(self, action: Action, type_: str = "donnees") -> None:
        if not peut(self.actor, action, self._ressource(type_)):
            raise AccesRefuse(f"action « {action.value} » refusée pour le rôle {self.actor.role.value}")

    def _auditer(self, action: str, cible: str | None = None, details: dict[str, Any] | None = None,
                 *, toujours: bool = False) -> None:
        """Journalise les écritures du fondateur (toujours) et les actions sensibles (``toujours``)."""
        if toujours or self.actor.role is Role.fondateur:
            journaliser(self.session, actor=self.actor.id, role=self.actor.role.value, action=action,
                        tenant_id=self.tenant_id, target=cible, ip=self.actor.ip, details=details)

    def _requete(self, modele: type[M]) -> Any:
        _modele_client(modele)
        if self.actor.role in ROLES_CLIENT and modele in _LECTURE_CLIENT_INTERDITE:
            raise AccesRefuse("lecture réservée au fondateur")
        q = select(modele).where(modele.tenant_id == self.tenant_id)  # type: ignore[attr-defined]
        if modele is Constat and not peut(self.actor, Action.lire_constats_proposes, self._ressource()):
            q = q.where(Constat.statut_validation == "valide")
        return q

    def requete(self, modele: type[M]) -> Any:
        """``SELECT`` cloisonné de ``modele`` (même périmètre que ``lister`` : ce client, constats publiés seuls
        pour un rôle client), à compléter par l'appelant (filtres en paramètres liés, colonnes, tri, limite) —
        listes filtrées en SQL de l'interface (D-3801)."""
        self.exiger(Action.lire)
        return self._requete(modele)

    def lister_parmi(self, modele: type[M], champ: str, valeurs: Iterable[Any], *, ordre: Any = None) -> list[M]:
        """Lignes de ``modele`` dont ``champ`` est dans ``valeurs`` (``IN`` en paramètres liés, par paquets de 500),
        même cloisonnement que ``lister`` : lecture d'une page de liste sans tout relire (D-3801)."""
        if champ == "tenant_id":
            raise AccesRefuse("filtre tenant_id interdit")
        valeurs = list(dict.fromkeys(v for v in valeurs if v is not None))
        out: list[M] = []
        for i in range(0, len(valeurs), 500):
            q = self.requete(modele).where(getattr(modele, champ).in_(valeurs[i:i + 500]))
            if ordre is not None:
                q = q.order_by(ordre)
            out.extend(self.session.execute(q).scalars())
        return out

    def executer_lecture(self, q: Any) -> list[Any]:
        """Exécute une lecture construite **dans ``controldone.storage``** à partir de ``requete`` (listes en SQL)."""
        return list(self.session.execute(q))

    # --- API générique -----------------------------------------------------------------------------
    def obtenir(self, modele: type[M], id: Any) -> M:
        self.exiger(Action.lire)
        obj = self.session.execute(self._requete(modele).where(modele.id == id)).scalar_one_or_none()  # type: ignore[attr-defined]
        if obj is None:
            raise AccesRefuse("introuvable ou hors périmètre")
        return obj

    def lister(self, modele: type[M], *, ordre: Any = None, limite: int | None = None, **egalites: Any) -> list[M]:
        self.exiger(Action.lire)
        q = self._requete(modele)
        for champ, valeur in egalites.items():
            if champ == "tenant_id":
                raise AccesRefuse("filtre tenant_id interdit")
            q = q.where(getattr(modele, champ) == valeur)
        if ordre is not None:
            q = q.order_by(ordre)
        if limite is not None:
            q = q.limit(limite)
        return list(self.session.execute(q).scalars())

    def compter(self, modele: type[M], **egalites: Any) -> int:
        """``COUNT(*)`` en SQL (mêmes filtres et même cloisonnement que ``lister``)."""
        self.exiger(Action.lire)
        q = self._requete(modele)
        for champ, valeur in egalites.items():
            if champ == "tenant_id":
                raise AccesRefuse("filtre tenant_id interdit")
            q = q.where(getattr(modele, champ) == valeur)
        return int(self.session.execute(select(func.count()).select_from(q.subquery())).scalar() or 0)

    def _politique_ecriture(self, modele: type, champs: dict[str, Any], *, creation: bool) -> None:
        if self.actor.role in ROLES_CLIENT and modele not in _ECRITURE_CLIENT:
            raise AccesRefuse(f"écriture de {modele.__name__} réservée au moteur et au fondateur")
        for champ, action in _CHAMPS_SENSIBLES.get(modele, {}).items():
            if champ not in champs:
                continue
            if creation and champs[champ] in _VALEURS_NEUTRES.get(champ, set()):
                continue
            self.exiger(action)

    def ajouter(self, obj: M) -> M:
        """Ajout générique (rôle client : tables autorisées seulement ; champs sensibles contrôlés)."""
        _modele_client(type(obj))
        self.exiger(Action.ecrire)
        colonnes = {c: getattr(obj, c) for c in type(obj).__table__.columns.keys()}  # type: ignore[attr-defined]  # noqa: SIM118
        self._politique_ecriture(type(obj), colonnes, creation=True)
        return self._ajouter_interne(obj)

    def _ajouter_interne(self, obj: M) -> M:
        _modele_client(type(obj))
        if obj.tenant_id is None:  # type: ignore[attr-defined]
            obj.tenant_id = self.tenant_id  # type: ignore[attr-defined]
        elif obj.tenant_id != self.tenant_id:  # type: ignore[attr-defined]
            raise AccesRefuse("écriture refusée : objet d'un autre client")
        try:
            with self.session.begin_nested():
                self.session.add(obj)
        except IntegrityError as exc:
            raise AccesRefuse("écriture refusée (conflit d'identifiant ou de contrainte)") from exc
        self._auditer("ajouter", f"{type(obj).__tablename__}:{getattr(obj, 'id', '')}")
        return obj

    def _exiger_moteur(self) -> None:
        """Écritures produites par le moteur (dossiers, résultats, coûts) : système ou fondateur."""
        if self.actor.role not in (Role.systeme, Role.fondateur):
            raise AccesRefuse("écriture réservée au moteur et au fondateur")

    def modifier(self, modele: type[M], id: Any, /, **champs: Any) -> M:
        self.exiger(Action.ecrire)
        if issubclass(modele, AppendOnly):
            raise AccesRefuse("table append-only")
        interdits = _CHAMPS_PROTEGES & champs.keys()
        if interdits:
            raise AccesRefuse(f"champ non modifiable : {sorted(interdits)}")
        self._politique_ecriture(modele, champs, creation=False)
        obj = self.obtenir(modele, id)
        colonnes = set(modele.__table__.columns.keys())  # type: ignore[attr-defined]
        for k, v in champs.items():
            if k not in colonnes:
                raise AttributeError(k)
            setattr(obj, k, v)
        self.session.flush()
        self._auditer("modifier", f"{modele.__tablename__}:{id}", {"champs": sorted(champs)})  # type: ignore[attr-defined]
        return obj

    def supprimer(self, modele: type[M], id: Any) -> None:
        self.exiger(Action.ecrire)
        if issubclass(modele, AppendOnly):
            raise AccesRefuse("table append-only")
        self._politique_ecriture(modele, {}, creation=False)
        obj = self.obtenir(modele, id)
        self.session.delete(obj)
        self.session.flush()
        self._auditer("supprimer", f"{modele.__tablename__}:{id}")  # type: ignore[attr-defined]

    def flush(self) -> None:
        self.session.flush()

    def commit(self) -> None:
        self.session.commit()

    def rollback(self) -> None:
        self.session.rollback()

    # --- client et référentiels ----------------------------------------------------------------------
    def client(self) -> Tenant:
        self.exiger(Action.lire)
        tenant = self.session.get(Tenant, self.tenant_id)
        assert tenant is not None
        return tenant

    def enregistrer_entite(self, entite: Any) -> Entite:
        """Crée ou met à jour une ``Entite`` (modèle pydantic)."""
        self.exiger(Action.ecrire)
        contenu = entite.model_dump(mode="json")
        contenu["client_id"] = self.tenant_id
        existant = self._trouver(Entite, entite.id)
        if existant is None:
            return self._ajouter_interne(Entite(id=entite.id, raison_sociale=entite.raison_sociale, tva=entite.tva,
                                       contenu=contenu))
        existant.raison_sociale, existant.tva, existant.contenu = entite.raison_sociale, entite.tva, contenu
        self._auditer("modifier", f"entites:{entite.id}")
        return existant

    def enregistrer_transitaire(self, transitaire: Any) -> Transitaire:
        self.exiger(Action.ecrire)
        contenu = transitaire.model_dump(mode="json")
        contenu["client_id"] = self.tenant_id
        existant = self._trouver(Transitaire, transitaire.id)
        if existant is None:
            return self._ajouter_interne(Transitaire(id=transitaire.id, nom=transitaire.nom, tva=transitaire.tva,
                                            contenu=contenu))
        existant.nom, existant.tva, existant.contenu = transitaire.nom, transitaire.tva, contenu
        self._auditer("modifier", f"transitaires:{transitaire.id}")
        return existant

    def _trouver(self, modele: type[M], id: Any) -> M | None:
        try:
            return self.obtenir(modele, id)
        except AccesRefuse:
            return None

    # --- grilles ---------------------------------------------------------------------------------------
    def enregistrer_grille(self, grille: GrilleTarifaire) -> Grille:
        """Nouvelle **version** (statut ``brouillon``) d'une grille ; les versions précédentes restent."""
        self.exiger(Action.ecrire)
        derniere = self.session.execute(
            select(func.max(Grille.version)).where(Grille.tenant_id == self.tenant_id,
                                                   Grille.grille_id == grille.id)
        ).scalar()
        version = (derniere or 0) + 1
        contenu = grille.model_dump(mode="json")
        contenu.update(client_id=self.tenant_id, statut="brouillon")
        return self._ajouter_interne(Grille(
            id=f"{grille.id}@v{version}", grille_id=grille.id, version=version,
            transitaire_id=grille.transitaire_id, reference=grille.reference, statut="brouillon",
            contenu=contenu, cree_par=self.actor.id,
        ))

    def valider_grille(self, grille_id: str, version: int) -> Grille:
        """Validation par le fondateur (seule une grille validée sert aux contrôles D)."""
        self.exiger(Action.valider_grille)
        lignes = self.lister(Grille, grille_id=grille_id, version=version)
        if not lignes:
            raise AccesRefuse("introuvable ou hors périmètre")
        g = lignes[0]
        g.statut, g.valide_par, g.valide_le = "validee", self.actor.id, maintenant()
        g.contenu = {**g.contenu, "statut": "validee"}
        self.session.flush()
        self._auditer("valider_grille", f"grilles:{g.id}", toujours=True)
        return g

    def grilles_validees(self) -> list[GrilleTarifaire]:
        """Dernière version validée de chaque grille, en modèles pydantic."""
        from controldone.model.referentiel import GrilleTarifaire

        par_grille: dict[str, Grille] = {}
        for g in self.lister(Grille, statut="validee", ordre=Grille.version):
            par_grille[g.grille_id] = g
        return [GrilleTarifaire.model_validate(g.contenu) for g in par_grille.values()]

    # --- lots, fichiers, pages ----------------------------------------------------------------------
    def creer_lot(self, lot_id: str, *, canal: str = "depot", expediteur: str | None = None) -> Lot:
        self.exiger(Action.deposer)
        return self._ajouter_interne(Lot(id=lot_id, canal=canal, expediteur=expediteur, statut="recu"))

    def enregistrer_fichier(self, fichier: Any, *, lot_id: str | None, coffre_ref: str | None) -> Fichier:
        """Métadonnées d'un ``Fichier`` pydantic (le contenu est déjà dans le coffre)."""
        self.exiger(Action.deposer)
        return self._ajouter_interne(Fichier(
            id=fichier.id, lot_id=lot_id, nom_original=fichier.nom_original,
            chemin_relatif=fichier.chemin_relatif, sha256=fichier.sha256, taille=fichier.taille,
            type_mime=fichier.type_mime, statut=str(fichier.statut), motif_refus=fichier.motif_refus,
            nombre_pages=fichier.nombre_pages, doublon_de=fichier.doublon_de, coffre_ref=coffre_ref,
        ))

    def empreintes_fichiers(self) -> dict[str, str]:
        """``{sha256: fichier_id}`` des fichiers reçus et conservés (deux colonnes, pas les lignes entières)."""
        self.exiger(Action.lire)
        q = (select(Fichier.sha256, Fichier.id)
             .where(Fichier.tenant_id == self.tenant_id, Fichier.statut == "ok", Fichier.coffre_ref.is_not(None))
             .order_by(Fichier.recu_le))
        return {sha: fid for sha, fid in self.session.execute(q)}

    def contenus_references(self, shas: Iterable[str]) -> set[str]:
        """Parmi ``shas``, ceux qu'une ligne ``Fichier`` de ce client référence encore (coffre)."""
        self.exiger(Action.lire)
        liste = sorted(set(shas))
        if not liste:
            return set()
        return set(self.session.execute(select(Fichier.coffre_ref).where(
            Fichier.tenant_id == self.tenant_id, Fichier.coffre_ref.in_(liste))).scalars())

    def fichier_par_sha(self, sha256: str) -> Fichier | None:
        lignes = self.lister(Fichier, sha256=sha256, ordre=Fichier.recu_le, limite=1)
        return lignes[0] if lignes else None

    def enregistrer_page(self, page_id: str, fichier_id: str, numero: int, *, qualite_texte: str,
                         sha256_texte: str | None, texte_ref: str | None, meta: dict | None = None) -> PageTexte:
        self.exiger(Action.deposer)
        self.obtenir(Fichier, fichier_id)  # le fichier doit appartenir au client
        return self._ajouter_interne(PageTexte(id=page_id, fichier_id=fichier_id, numero=numero,
                                      qualite_texte=qualite_texte, sha256_texte=sha256_texte,
                                      texte_ref=texte_ref, meta=meta or {}))

    # --- dossiers, documents, résultats -------------------------------------------------------------
    def enregistrer_dossier(self, dossier: DossierModele, *, lot_id: str | None = None,
                            documents: Iterable[Any] = (), fichier_ids: Iterable[str] = ()) -> Dossier:
        """Crée ou met à jour l'instantané d'un dossier (version comprise) et ses documents."""
        self.exiger(Action.ecrire)
        self._exiger_moteur()
        contenu = dossier.model_dump(mode="json")
        contenu["client_id"] = self.tenant_id
        ligne = self._trouver(Dossier, dossier.id)
        statut = dossier.statut_global.value if dossier.statut_global else None
        if ligne is None:
            ligne = self._ajouter_interne(Dossier(id=dossier.id, lot_id=lot_id, reference=dossier.reference,
                                         version=dossier.version, statut_global=statut, contenu=contenu))
        else:
            if dossier.version < ligne.version:
                raise ValueError("version de dossier antérieure à la version enregistrée")
            ligne.version, ligne.statut_global, ligne.contenu = dossier.version, statut, contenu
            ligne.reference = dossier.reference
            ligne.cloture_le = None  # nouvelle activité : le dossier est rouvert (conservation, D-1301)
        for doc in documents:
            self.enregistrer_document(doc, dossier_id=dossier.id, lot_id=lot_id)
        for fid in fichier_ids:
            self.obtenir(Fichier, fid)
            if not self.lister(DossierFichier, dossier_id=dossier.id, fichier_id=fid):
                self._ajouter_interne(DossierFichier(dossier_id=dossier.id, fichier_id=fid))
        self.session.flush()
        return ligne

    def enregistrer_document(self, doc: Any, *, dossier_id: str | None = None,
                             lot_id: str | None = None) -> Document:
        self.exiger(Action.ecrire)
        self._exiger_moteur()
        contenu = doc.model_dump(mode="json")
        contenu["client_id"] = self.tenant_id
        ligne = self._trouver(Document, doc.id)
        if ligne is None:
            return self._ajouter_interne(Document(id=doc.id, lot_id=lot_id, dossier_id=dossier_id,
                                         type=str(doc.type), contenu=contenu))
        ligne.contenu, ligne.dossier_id, ligne.type = contenu, dossier_id or ligne.dossier_id, str(doc.type)
        return ligne

    def lire_dossier(self, dossier_id: str) -> DossierModele:
        from controldone.model.dossier import Dossier as DossierModele

        return DossierModele.model_validate(self.obtenir(Dossier, dossier_id).contenu)

    def cloturer_dossier(self, dossier_id: str, le: datetime | None = None) -> Dossier:
        self.exiger(Action.ecrire)
        d = self.obtenir(Dossier, dossier_id)
        d.cloture_le = le or maintenant()
        self.session.flush()
        self._auditer("cloturer_dossier", f"dossiers:{dossier_id}", toujours=True)
        return d

    def enregistrer_resultats(self, resultats: Sequence[ResultatControle]) -> int:
        """Enregistre (idempotent, identifiants stables D-009) résultats et constats. La validation déjà
        donnée par le fondateur à un constat de même identifiant est conservée."""
        from controldone.findings_io import constats_hors_totaux

        self.exiger(Action.ecrire)
        self._exiger_moteur()
        # Règle unique des totaux (``findings_io.constats_hors_totaux``, D-1202) : appliquée par dossier et
        # inscrite dans chaque constat (``contenu.hors_totaux``) pour que tableau de bord, API et espace
        # client comptent exactement comme le rapport (D-1319).
        par_dossier: dict[str, list[ResultatControle]] = {}
        for r in resultats:
            par_dossier.setdefault(r.dossier_id, []).append(r)
        hors_totaux: dict[str, str] = {}
        for groupe in par_dossier.values():
            hors_totaux.update(constats_hors_totaux(groupe))
        n = 0
        for r in resultats:
            self.obtenir(Dossier, r.dossier_id)  # le dossier doit être de ce client
            contenu = r.model_dump(mode="json")
            ligne = self._trouver(Resultat, r.id) if self.actor.role not in ROLES_CLIENT else None
            if ligne is None:
                self._ajouter_interne(Resultat(id=r.id, dossier_id=r.dossier_id, dossier_version=r.dossier_version,
                                      execution_id=r.execution_id, controle_id=r.controle_id,
                                      outcome=str(r.outcome), contenu=contenu))
            else:
                ligne.contenu, ligne.outcome = contenu, str(r.outcome)
                ligne.dossier_version, ligne.execution_id = r.dossier_version, r.execution_id
            c = r.constat
            if c is not None:
                existant = self.session.execute(
                    select(Constat).where(Constat.tenant_id == self.tenant_id, Constat.id == c.id)
                ).scalar_one_or_none()
                cj = {**c.model_dump(mode="json"),
                      # affichage des tolérances à côté du constat (§3.1 règle 6) sans lire les résultats bruts
                      "tolerance_appliquee": contenu.get("tolerance_appliquee"),
                      "seuil_certitude_applique": contenu.get("seuil_certitude_applique"),
                      "attendu": contenu.get("attendu"), "constate": contenu.get("constate"),
                      "hors_totaux": hors_totaux.get(c.id)}
                if existant is None:
                    self._ajouter_interne(Constat(
                        id=c.id, resultat_id=r.id, dossier_id=r.dossier_id, dossier_version=r.dossier_version,
                        controle_id=c.controle_id, niveau=str(c.niveau), montant_en_jeu=c.montant_en_jeu,
                        nature_montant=str(c.nature_montant) if c.nature_montant else None,
                        statut_validation=str(c.statut_validation), contenu=cj,
                    ))
                else:
                    # Recontrôle (nouvelle version du dossier) : la validation déjà donnée est conservée si
                    # le niveau et le montant sont inchangés ; sinon le constat est de nouveau proposé.
                    change = (existant.niveau != str(c.niveau) or existant.montant_en_jeu != c.montant_en_jeu)
                    if change and existant.statut_validation != "propose":
                        existant.statut_validation, existant.valide_par, existant.valide_le = "propose", None, None
                        existant.commentaire_validation = None
                    else:
                        cj = {**cj, "statut_validation": existant.statut_validation,
                              "valide_par": existant.valide_par,
                              "commentaire_validation": existant.commentaire_validation}
                    existant.contenu, existant.niveau = cj, str(c.niveau)
                    existant.montant_en_jeu = c.montant_en_jeu
                    existant.dossier_version, existant.resultat_id = r.dossier_version, r.id
            n += 1
        self.session.flush()
        return n

    def constats(self, dossier_id: str | None = None) -> list[Constat]:
        """Constats visibles par l'acteur (rôle client : publiés ``valide`` seulement)."""
        filtres = {"dossier_id": dossier_id} if dossier_id else {}
        return self.lister(Constat, ordre=Constat.id, **filtres)

    def valider_constat(self, constat_id: str, statut: str, commentaire: str | None = None) -> Constat:
        """Décision du fondateur (§7.7) : ``valide`` | ``rejete`` (motif obligatoire) | ``modifie``."""
        self.exiger(Action.valider_constat)
        if statut not in ("valide", "rejete", "modifie", "propose"):
            raise ValueError("statut de validation inconnu")
        if statut == "rejete" and not (commentaire and commentaire.strip()):
            raise ValueError("le rejet exige un motif")
        c = self.obtenir(Constat, constat_id)
        de = c.statut_validation
        c.statut_validation, c.valide_par, c.valide_le = statut, self.actor.id, maintenant()
        c.commentaire_validation = commentaire
        c.contenu = {**c.contenu, "statut_validation": statut, "valide_par": self.actor.id,
                     "commentaire_validation": commentaire}
        self.session.flush()
        self._auditer("valider_constat", f"constats:{constat_id}", {"de": de, "vers": statut}, toujours=True)
        return c

    def retrograder_constat(self, constat_id: str, motif: str) -> Constat:
        """Le fondateur rétrograde un ``ecart_certain`` en ``a_verifier`` (§7.7) ; le constat reste proposé.
        (L'inverse est impossible ici : seul un recontrôle après correction peut produire un écart certain.)"""
        self.exiger(Action.valider_constat)
        if not (motif and motif.strip()):
            raise ValueError("la rétrogradation exige un motif")
        c = self.obtenir(Constat, constat_id)
        if c.niveau != "ecart_certain":
            raise ValueError("seul un écart certain peut être rétrogradé")
        raisons = list((c.contenu or {}).get("raisons") or [])
        if "retrograde_par_fondateur" not in raisons:
            raisons.append("retrograde_par_fondateur")
        c.niveau = "a_verifier"
        c.statut_validation, c.valide_par, c.valide_le = "propose", self.actor.id, maintenant()
        c.commentaire_validation = motif.strip()[:1000]
        c.contenu = {**c.contenu, "niveau": "a_verifier", "raisons": raisons, "statut_validation": "propose",
                     "commentaire_validation": c.commentaire_validation}
        self.session.flush()
        self._auditer("retrograder_constat", f"constats:{constat_id}", {"vers": "a_verifier"}, toujours=True)
        return c

    # --- corrections (§6.2.11) ----------------------------------------------------------------------
    def appliquer_correction(self, *, correction_id: str, dossier_id: str, document_id: str, cible: str,
                             chemin: str, ancienne: dict[str, Any] | None, nouvelle: dict[str, Any],
                             contenu_document: dict[str, Any], motif: str, role_auteur: str) -> Dossier:
        """Enregistre une correction (append-only), remplace la valeur dans le document et incrémente la
        version du dossier. Le recontrôle est mis en file par l'appelant. Fondateur ou ``client_admin``."""
        self.exiger(Action.corriger)
        if not (motif and motif.strip()):
            raise ValueError("la correction exige un motif")
        dossier = self.obtenir(Dossier, dossier_id)
        doc = self.obtenir(Document, document_id)
        if document_id not in {lien.get("document_id") for lien in (dossier.contenu or {}).get("liens", [])}:
            raise AccesRefuse("introuvable ou hors périmètre")
        self._ajouter_interne(CorrectionValeur(
            id=correction_id, dossier_id=dossier_id, document_id=document_id, cible=cible, chemin=chemin[:300],
            ancienne_valeur=(ancienne or {}).get("valeur"), nouvelle_valeur=nouvelle.get("valeur"),
            auteur=self.actor.id, role_auteur=role_auteur, motif=motif.strip()[:1000],
            contenu={"ancienne": ancienne, "nouvelle": nouvelle},
        ))
        contenu = dict(contenu_document)
        contenu["client_id"] = self.tenant_id
        doc.contenu = contenu
        dossier.version = dossier.version + 1
        dossier.contenu = {**dossier.contenu, "version": dossier.version}
        self.session.flush()
        self._auditer("corriger_valeur", f"documents:{document_id}",
                      {"correction": correction_id, "dossier": dossier_id, "version": dossier.version}, toujours=True)
        return dossier

    def corrections(self, dossier_id: str) -> list[CorrectionValeur]:
        return self.lister(CorrectionValeur, dossier_id=dossier_id, ordre=CorrectionValeur.le)

    # --- recouvrement (§17) -------------------------------------------------------------------------
    def enregistrer_ecart(self, ecart: EcartARecouvrer) -> Ecart:
        self.exiger(Action.ecrire)
        self._exiger_moteur()
        contenu = ecart.model_dump(mode="json")
        contenu["client_id"] = self.tenant_id
        return self._ajouter_interne(Ecart(id=ecart.id, constat_id=ecart.constat_id, transitaire_id=ecart.transitaire_id,
                                  statut=ecart.statut.value, montant_initial=ecart.montant_initial,
                                  reste=ecart.reste, contenu=contenu))

    def lire_ecart(self, ecart_id: str) -> EcartARecouvrer:
        from controldone.model.recouvrement import EcartARecouvrer

        return EcartARecouvrer.model_validate(self.obtenir(Ecart, ecart_id).contenu)

    def transitionner_ecart(self, ecart_id: str, vers: Any, *, montant: Decimal | None = None,
                            piece: Any = None, commentaire: str | None = None) -> EvenementRecouvrement:
        """Transition §17.1 (règles de ``model.recouvrement.transitionner``), événement append-only."""
        from controldone.model.enums import StatutEcart
        from controldone.model.recouvrement import transitionner

        self.exiger(Action.declarer_recouvrement)
        ligne = self.obtenir(Ecart, ecart_id)
        ecart = self.lire_ecart(ecart_id)
        evt = transitionner(ecart, StatutEcart(vers), auteur=self.actor.id, montant=montant, piece=piece,
                            commentaire=commentaire)
        if montant is not None and evt.vers in (StatutEcart.partiellement_credite, StatutEcart.credite):
            ecart.montant_credite += montant
            ecart.reste = max(Decimal("0.00"), ecart.reste - montant)
        contenu = ecart.model_dump(mode="json")
        contenu["client_id"] = self.tenant_id
        ligne.statut, ligne.reste, ligne.contenu = ecart.statut.value, ecart.reste, contenu
        ligne_evt = EvenementRecouvrement(
            id=evt.id, ecart_id=ecart_id, de=evt.de.value, vers=evt.vers.value, le=evt.le, auteur=evt.auteur,
            montant=evt.montant, contenu=evt.model_dump(mode="json"),
        )
        self._ajouter_interne(ligne_evt)
        self._auditer("transition_ecart", f"ecarts:{ecart_id}", {"de": evt.de.value, "vers": evt.vers.value},
                      toujours=True)
        return ligne_evt

    def enregistrer_reclamation(self, reclamation: Any) -> Reclamation:
        self.exiger(Action.ecrire)
        contenu = reclamation.model_dump(mode="json")
        contenu["client_id"] = self.tenant_id
        ligne = self._trouver(Reclamation, reclamation.id)
        if ligne is None:
            return self._ajouter_interne(Reclamation(id=reclamation.id, transitaire_id=reclamation.transitaire_id,
                                            contenu=contenu))
        ligne.contenu = contenu
        return ligne

    # --- coûts IA (§20.5) ------------------------------------------------------------------------------
    def enregistrer_usage_ia(self, *, cout_eur: Decimal, mois: str, jetons_entree: int = 0,
                             jetons_sortie: int = 0, modele: str | None = None, dossier_id: str | None = None,
                             lot_id: str | None = None, execution_id: str | None = None) -> AiUsage:
        self.exiger(Action.ecrire)
        self._exiger_moteur()
        return self._ajouter_interne(AiUsage(cout_eur=Decimal(cout_eur), mois=mois, jetons_entree=jetons_entree,
                                    jetons_sortie=jetons_sortie, modele=modele, dossier_id=dossier_id,
                                    lot_id=lot_id, execution_id=execution_id))

    def cout_ia(self, *, mois: str | None = None, dossier_id: str | None = None) -> Decimal:
        filtres: dict[str, Any] = {}
        if mois:
            filtres["mois"] = mois
        if dossier_id:
            filtres["dossier_id"] = dossier_id
        return sum((u.cout_eur for u in self.lister(AiUsage, **filtres)), Decimal("0"))

    # --- membres, clés d'API, journal -------------------------------------------------------------------
    def membres(self) -> list[Membership]:
        return self.lister(Membership)

    def ajouter_membre(self, user_id: str, role: Role) -> Membership:
        self.exiger(Action.gerer_utilisateurs)
        if Role(role) not in ROLES_CLIENT:
            raise AccesRefuse("rôle client attendu")
        m = self._ajouter_interne(Membership(user_id=user_id, role=Role(role).value))
        self._auditer("ajouter_membre", f"users:{user_id}", {"role": Role(role).value}, toujours=True)
        return m

    def creer_cle_api(self, cle_id: str, nom: str, prefixe: str, hash_: str, role: Role) -> CleApi:
        self.exiger(Action.gerer_cles_api)
        if Role(role) not in ROLES_CLIENT:
            raise AccesRefuse("rôle client attendu")
        c = self._ajouter_interne(CleApi(id=cle_id, nom=nom, prefixe=prefixe, hash=hash_, role=Role(role).value,
                                cree_par=self.actor.id))
        self._auditer("creer_cle_api", f"api_keys:{cle_id}", {"prefixe": prefixe}, toujours=True)
        return c

    def revoquer_cle_api(self, cle_id: str) -> None:
        self.exiger(Action.gerer_cles_api)
        c = self.obtenir(CleApi, cle_id)
        c.revoquee_le = maintenant()
        self.session.flush()
        self._auditer("revoquer_cle_api", f"api_keys:{cle_id}", toujours=True)

    def journal(self, limite: int = 200) -> list[AuditLog]:
        """Entrées d'audit concernant ce client (lecture seule)."""
        self.exiger(Action.lire)
        q = (select(AuditLog).where(AuditLog.tenant_id == self.tenant_id)
             .order_by(AuditLog.id.desc()).limit(limite))
        return list(self.session.execute(q).scalars())

    def signaler_alerte(self, *, cle: str, kind: str, message: str,
                        details: dict[str, Any] | None = None) -> bool:
        """Alerte au fondateur concernant ce client (dédoublonnée par ``cle``), sans contenu de document."""
        from controldone.storage.alertes import emettre_alerte

        return emettre_alerte(self.session, cle=f"{self.tenant_id}:{cle}", kind=kind, message=message,
                              tenant_id=self.tenant_id, details=details)

    def sorties(self) -> list[Outbox]:
        """Actions sortantes concernant ce client."""
        return self.lister(Outbox, ordre=Outbox.cree_le)

    # --- file de tâches (même transaction, D-1306) ----------------------------------------------------------
    def mettre_en_file(self, kind: str, payload: dict[str, Any], cle: str) -> str:
        """Met un job de ce client en file **dans la transaction du périmètre** : il est validé avec les
        écritures qui le motivent (dépôt, correction) ou annulé avec elles. Idempotent par ``cle``."""
        from controldone.storage.file_jobs import JobStore

        self.exiger(Action.lire)
        job, _cree = JobStore.enqueue_dans(self.session, kind, payload, cle, self.tenant_id)
        return job.id


class OperatorScope:
    """Accès transversal du fondateur. Chaque accès est journalisé (``acces_admin`` …)."""

    def __init__(self, db: Database, actor: Acteur, *, ip: str | None = None) -> None:
        if not isinstance(actor, Acteur) or actor.role is not Role.fondateur:
            raise AccesRefuse("OperatorScope réservé au fondateur")
        self.db = db
        self.actor = actor if ip is None else Acteur(actor.id, actor.role, actor.tenant_id, ip)
        # Session propre en lecture (transaction différée : ne prend pas le verrou d'écriture SQLite).
        self.session = db.session(lecture=True)
        self.session.info[garde.CLE_OPERATEUR] = True
        self._enfants: list[Session] = []

    def _audit_immediat(self, action: str, tenant_id: str | None, cible: str | None,
                        details: dict[str, Any] | None = None) -> None:
        """Entrée d'audit validée tout de suite (trace de l'accès même si l'opération échoue ensuite).

        Les périmètres client déjà ouverts sont validés d'abord : avec SQLite (un seul écrivain), une
        transaction d'écriture en cours bloquerait l'écriture de l'audit. Chaque nouvel accès tracé
        valide donc les écritures précédentes de l'opérateur."""
        for enfant in self._enfants:
            enfant.commit()
        self.session.rollback()  # libère l'instantané de lecture
        with self.db.transaction_systeme() as s:
            journaliser(s, actor=self.actor.id, role=self.actor.role.value, action=action,
                        tenant_id=tenant_id, target=cible, ip=self.actor.ip, details=details)

    def client(self, tenant_id: str, motif: str, *, lecture: bool = False) -> TenantScope:
        """Ouvre le périmètre d'un client (session dédiée, validée par ``commit``).

        ``lecture=True`` (consultation, vignettes, rapport) : transaction **différée**, sans le verrou
        d'écriture SQLite (``BEGIN IMMEDIATE``) — une lecture du fondateur ne bloque plus le worker ni les
        dépôts (F-06, D-1304). L'accès reste journalisé (``acces_admin``)."""
        if not (motif and motif.strip()):
            raise AccesRefuse("motif d'accès obligatoire")
        self._audit_immediat("acces_admin", tenant_id, f"tenants:{tenant_id}", {"motif": motif[:200]})
        s = self.db.session(lecture=lecture)
        self._enfants.append(s)
        return TenantScope(s, tenant_id, self.actor, _jeton=_JETON_OPERATEUR)

    def creer_client(self, tenant_id: str, raison_sociale: str, *, offre: str = "diagnostic",
                     plafond_cout_ia_mensuel_eur: Decimal | None = None, retention_jours: int = 180,
                     reglages: dict[str, Any] | None = None) -> Tenant:
        if plafond_cout_ia_mensuel_eur is None:  # défaut unique : ``Settings`` (CONTROLDONE_LLM_PLAFOND_*)
            from controldone.config import get_settings

            plafond_cout_ia_mensuel_eur = get_settings().llm_plafond_client_mensuel_eur
        with self.db.transaction_systeme() as s:
            t = Tenant(id=tenant_id, raison_sociale=raison_sociale, offre=offre,
                       plafond_cout_ia_mensuel_eur=Decimal(plafond_cout_ia_mensuel_eur),
                       retention_jours=retention_jours, reglages=reglages or {})
            s.add(t)
            s.flush()
            journaliser(s, actor=self.actor.id, role=self.actor.role.value, action="creer_client",
                        tenant_id=tenant_id, target=f"tenants:{tenant_id}", ip=self.actor.ip)
        return t

    def modifier_client(self, tenant_id: str, **champs: Any) -> None:
        autorises = {"raison_sociale", "offre", "plafond_cout_ia_mensuel_eur", "retention_jours", "reglages",
                     "actif"}
        if not champs.keys() <= autorises:
            raise AccesRefuse(f"champs non modifiables : {sorted(champs.keys() - autorises)}")
        with self.db.transaction_systeme() as s:
            t = s.get(Tenant, tenant_id)
            if t is None:
                raise AccesRefuse("introuvable")
            for k, v in champs.items():
                setattr(t, k, v)
            journaliser(s, actor=self.actor.id, role=self.actor.role.value, action="modifier_client",
                        tenant_id=tenant_id, target=f"tenants:{tenant_id}", ip=self.actor.ip,
                        details={"champs": sorted(champs)})

    def lister_clients(self, *, auditer: bool = True) -> list[Tenant]:
        if auditer:
            self._audit_immediat("lister_clients", None, "tenants")
        return list(self.session.execute(select(Tenant).order_by(Tenant.id)).scalars())

    def _proposes_courants(self) -> Any:
        """Constats ``propose`` de la **version courante** de leur dossier (jointure SQL)."""
        return (select(Constat).join(Dossier, (Dossier.id == Constat.dossier_id)
                                     & (Dossier.tenant_id == Constat.tenant_id)
                                     & (Dossier.version == Constat.dossier_version))
                .where(Constat.statut_validation == "propose"))

    def file_validation(self, limite: int = 500, *, auditer: bool = True) -> list[Constat]:
        """Constats ``propose`` de tous les clients (§7.7), lecture transversale journalisée. Le tri par
        priorité (écart certain d'abord, puis montant décroissant) est fait **en SQL avant la limite** : au-delà
        de ``limite`` constats, ce sont les moins prioritaires qui manquent (F-15, D-1309)."""
        if auditer:
            self._audit_immediat("lire_file_validation", None, "constats")
        rang = case((Constat.niveau == "ecart_certain", 0), else_=1)
        montant = cast(func.coalesce(Constat.montant_en_jeu, "0"), Numeric)
        q = self._proposes_courants().order_by(rang, montant.desc(), Constat.id).limit(limite)
        constats = list(self.session.execute(q).scalars())

        def priorite(c: Constat) -> tuple[int, Decimal]:
            return (0 if c.niveau == "ecart_certain" else 1, -(c.montant_en_jeu or Decimal(0)))

        return sorted(constats, key=priorite)  # tri exact en Decimal (stable)

    def rechercher_file_validation(self, *, clients: Sequence[str], client: str | None = None,
                                   controle: str | None = None, niveau: str | None = None,
                                   mini: Decimal | None = None, maxi: Decimal | None = None, tri: str = "priorite",
                                   decalage: int = 0, limite: int = 25,
                                   auditer: bool = True) -> tuple[list[Constat], int, int]:
        """Page filtrée de la file de validation (D-3801) : ``(constats, total filtré, total de la file)``.

        Filtres et tri **en SQL** (paramètres liés), sur les constats ``propose`` de la version courante des
        clients ``clients`` (actifs). ``niveau`` : ``ecart_certain`` / ``a_verifier`` (hors renvois) ou
        ``renvoi``. ``mini`` / ``maxi`` : montant en jeu chiffré (nature autre que ``renvoi`` / ``aucun``).
        Tri ``priorite`` (§7.7 : renvois en dernier, écarts certains, à vérifier, montant décroissant,
        contrôle), ``montant`` / ``-montant`` (sans montant en dernier) ou ``client`` (raison sociale, dossier).
        Les montants, stockés en texte exact, sont comparés et triés par ``CAST … AS NUMERIC`` ; les bornes sont
        passées en texte et converties par la base (aucun flottant côté Python)."""
        if auditer:
            self._audit_immediat("lire_file_validation", None, "constats")
        renvoi = func.coalesce(Constat.contenu["renvoi"].as_boolean(), False)
        nature = func.coalesce(func.nullif(Constat.contenu["nature_montant"].as_string(), ""),
                               func.nullif(Constat.nature_montant, ""), "aucun")
        chiffre = Constat.montant_en_jeu.is_not(None) & nature.not_in(("renvoi", "aucun"))
        montant = cast(Constat.montant_en_jeu, Numeric)
        valeur = case((chiffre, montant), else_=None)
        base = self._proposes_courants().where(Constat.tenant_id.in_(list(clients)))
        total_file = int(self.session.execute(
            base.with_only_columns(func.count()).order_by(None)).scalar() or 0)
        q = base
        if client:
            q = q.where(Constat.tenant_id == client)
        if controle:
            q = q.where(Constat.controle_id == controle)
        if niveau == "renvoi":
            q = q.where(renvoi == true())
        elif niveau:
            q = q.where((Constat.niveau == niveau) & (renvoi == false()))
        if mini is not None:
            q = q.where(chiffre & (montant >= cast(str(mini), Numeric)))
        if maxi is not None:
            q = q.where(chiffre & (montant <= cast(str(maxi), Numeric)))
        total = int(self.session.execute(
            select(func.count()).select_from(q.order_by(None).subquery())).scalar() or 0)
        rang = case((Constat.niveau == "ecart_certain", 0), (Constat.niveau == "a_verifier", 1), else_=2)
        # même ordre que ``services.lecture.trier_constats`` appliqué à ``file_validation`` (ordre stable)
        priorite = [renvoi, rang, func.coalesce(valeur, 0).desc(), Constat.controle_id,
                    func.coalesce(montant, 0).desc(), Constat.id]
        if tri in ("montant", "-montant"):
            ordre = [valeur.is_(None), valeur.desc() if tri == "-montant" else valeur.asc(), *priorite]
        elif tri == "client":
            q = q.join(Tenant, Tenant.id == Constat.tenant_id)
            ordre = [func.lower(Tenant.raison_sociale), func.coalesce(Dossier.reference, Dossier.id), *priorite]
        else:
            ordre = priorite
        constats = list(self.session.execute(q.order_by(*ordre).offset(decalage).limit(limite)).scalars())
        return constats, total, total_file

    def points_attention(self, clients: Sequence[str], *, limite: int = 200,
                         auditer: bool = True) -> tuple[list[dict[str, Any]], int]:
        """Points d'attention de la file de validation (D-3801) : documents non reconnus rattachés à un dossier
        et rattachements faibles, pour les clients ``clients``. Lecture **en colonnes** (référence, liste
        ``liens`` extraite du JSON en SQL), sans valider chaque dossier ; au plus ``limite`` lignes, plus le
        total. ``detail`` : identifiant du document (libellé calculé par l'appelant)."""
        if auditer:
            self._audit_immediat("lire_points_attention", None, "dossiers")
        ids = list(clients)
        sortie: list[dict[str, Any]] = []
        total = 0
        q = (select(Dossier.tenant_id, Dossier.id, Dossier.reference, Dossier.contenu["liens"])
             .where(Dossier.tenant_id.in_(ids)).order_by(Dossier.tenant_id, Dossier.reference, Dossier.id))
        for tenant_id, dossier_id, reference, liens in self.session.execute(q):
            for lien in liens or []:
                if isinstance(lien, dict) and lien.get("force") == "faible":
                    total += 1
                    if len(sortie) < limite:
                        sortie.append({"type": "faible", "tenant_id": tenant_id, "dossier_id": dossier_id,
                                       "dossier": reference or dossier_id,
                                       "document_id": str(lien.get("document_id") or "")})
        d = (select(Document.tenant_id, Document.dossier_id, Document.id, Dossier.reference)
             .join(Dossier, (Dossier.id == Document.dossier_id) & (Dossier.tenant_id == Document.tenant_id),
                   isouter=True)
             .where(Document.tenant_id.in_(ids), Document.type == "inconnu", Document.dossier_id.is_not(None))
             .order_by(Document.tenant_id, Document.id))
        for tenant_id, dossier_id, document_id, reference in self.session.execute(d):
            total += 1
            if len(sortie) < limite:
                sortie.append({"type": "inconnu", "tenant_id": tenant_id, "dossier_id": dossier_id,
                               "dossier": reference or dossier_id, "document_id": document_id})
        return sortie, total

    def compter_proposes(self) -> int:
        q = self._proposes_courants().with_only_columns(func.count()).order_by(None)
        return int(self.session.execute(q).scalar() or 0)

    def couts_ia(self, mois: str, *, auditer: bool = True) -> dict[str, Decimal]:
        if auditer:
            self._audit_immediat("lire_couts_ia", None, "ai_usage", {"mois": mois})
        totaux: dict[str, Decimal] = {}
        for u in self.session.execute(select(AiUsage).where(AiUsage.mois == mois)).scalars():
            totaux[u.tenant_id] = totaux.get(u.tenant_id, Decimal(0)) + u.cout_eur
        return totaux

    def statistiques(self, *, auditer: bool = True) -> dict[str, dict[str, Any]]:
        """Indicateurs agrégés par client pour le tableau de bord (lecture transversale journalisée) :
        dossiers par statut, constats proposés, montants recouvrables (validés certains / à vérifier),
        écarts ouverts. Identifiants et compteurs seulement. Constats lus **colonne par colonne** (jamais le
        JSON ``contenu``), filtrés en SQL sur la version courante (F-15)."""
        if auditer:
            self._audit_immediat("lire_tableau_de_bord", None, "tenants")
        stats: dict[str, dict[str, Any]] = {}

        def bloc(t: str) -> dict[str, Any]:
            return stats.setdefault(t, {"dossiers": {}, "nb_dossiers": 0, "proposes": 0,
                                        "recouvrable_certain": Decimal(0), "recouvrable_a_verifier": Decimal(0),
                                        "ecarts_ouverts": 0, "reste_a_recouvrer": Decimal(0)})

        for t, st, n in self.session.execute(
                select(Dossier.tenant_id, Dossier.statut_global, func.count()).group_by(Dossier.tenant_id,
                                                                                         Dossier.statut_global)):
            b = bloc(t)
            b["dossiers"][st or "inconnu"] = n
            b["nb_dossiers"] += n
        courants = (select(Constat.tenant_id, Constat.statut_validation, Constat.niveau, Constat.nature_montant,
                           Constat.montant_en_jeu, Constat.contenu["hors_totaux"].as_string(), Constat.controle_id,
                           Dossier.cree_le)
                    .join(Dossier, (Dossier.id == Constat.dossier_id) & (Dossier.tenant_id == Constat.tenant_id)
                          & (Dossier.version == Constat.dossier_version))
                    .where(Constat.statut_validation != "rejete"))
        from controldone.calendrier import mois_paris

        for tenant, statut, niveau, nature, montant, exclu, controle, cree_le in self.session.execute(courants):
            b = bloc(tenant)
            # séries des graphiques du tableau de bord (D-3403) : constats par famille, montant certain par mois
            fam = (controle or "?")[:1]
            cle_fam = "familles_proposes" if statut == "propose" else "familles_valides"
            if statut in ("propose", "valide"):
                b.setdefault(cle_fam, {})[fam] = b.setdefault(cle_fam, {}).get(fam, 0) + 1
            if statut == "propose":
                b["proposes"] += 1
            if exclu:  # hors totaux (E6 remplaçant, doublon F5) : compté une seule fois, comme le rapport
                continue
            if nature == "recouvrable" and montant and montant > 0:
                if niveau == "ecart_certain" and statut == "valide":
                    b["recouvrable_certain"] += montant
                    if cree_le is not None:
                        par_mois = b.setdefault("certain_par_mois", {})
                        m = mois_paris(cree_le)
                        par_mois[m] = par_mois.get(m, Decimal(0)) + montant
                elif niveau == "a_verifier" and statut != "rejete":
                    b["recouvrable_a_verifier"] += montant
        for tenant, reste in self.session.execute(
                select(Ecart.tenant_id, Ecart.reste).where(Ecart.statut.not_in(("credite", "abandonne")))):
            b = bloc(tenant)
            b["ecarts_ouverts"] += 1
            b["reste_a_recouvrer"] += reste
        return stats

    def marquer_alerte_lue(self, alerte_id: int) -> None:
        from controldone.storage.alertes import marquer_lue

        with self.db.transaction_systeme() as s:
            marquer_lue(s, alerte_id)
            journaliser(s, actor=self.actor.id, role=self.actor.role.value, action="alerte_lue",
                        target=f"alertes:{alerte_id}", ip=self.actor.ip)

    def alertes(self, *, non_lues: bool = True, limite: int = 500) -> list[Alerte]:
        """Les ``limite`` alertes les plus récentes, en ordre chronologique."""
        q = select(Alerte).order_by(Alerte.id.desc()).limit(limite)
        if non_lues:
            q = q.where(Alerte.lue_le.is_(None))
        return list(reversed(list(self.session.execute(q).scalars())))

    def journal(self, limite: int = 500) -> list[AuditLog]:
        return list(self.session.execute(select(AuditLog).order_by(AuditLog.id.desc()).limit(limite)).scalars())

    def rechercher_journal(self, *, acteur: str | None = None, action: str | None = None,
                           tenant_id: str | None = None, du: datetime | None = None, au: datetime | None = None,
                           croissant: bool = False, decalage: int = 0, limite: int = 50) -> tuple[list[AuditLog], int]:
        """Page du journal filtrée (D-3401) : ``(entrées, total)``. Filtres passés à l'ORM comme paramètres liés
        (``acteur`` : sous-chaîne, ``%`` et ``_`` échappés) ; ``du`` inclus, ``au`` exclu."""
        conds = []
        if acteur:
            conds.append(AuditLog.actor.contains(acteur, autoescape=True))
        if action:
            conds.append(AuditLog.action == action)
        if tenant_id:
            conds.append(AuditLog.tenant_id == tenant_id)
        if du is not None:
            conds.append(AuditLog.ts >= du)
        if au is not None:
            conds.append(AuditLog.ts < au)
        total = int(self.session.execute(select(func.count()).select_from(AuditLog).where(*conds)).scalar() or 0)
        ordre = AuditLog.id.asc() if croissant else AuditLog.id.desc()
        q = select(AuditLog).where(*conds).order_by(ordre).offset(max(0, decalage)).limit(max(1, min(limite, 500)))
        return list(self.session.execute(q).scalars()), total

    def valeurs_journal(self) -> tuple[list[str], list[str]]:
        """Actions et clients présents dans le journal (listes fermées des filtres)."""
        actions = [a for (a,) in self.session.execute(select(AuditLog.action).distinct().order_by(AuditLog.action))]
        clients = [t for (t,) in self.session.execute(
            select(AuditLog.tenant_id).where(AuditLog.tenant_id.is_not(None)).distinct().order_by(AuditLog.tenant_id))]
        return actions, clients

    def verifier_journal(self) -> list[Any]:
        from controldone.storage.audit import verifier_chaine

        return verifier_chaine(self.session)

    def commit(self) -> None:
        for s in self._enfants:
            s.commit()
        self.session.commit()

    def rollback(self) -> None:
        for s in self._enfants:
            s.rollback()
        self.session.rollback()

    def close(self) -> None:
        for s in self._enfants:
            s.close()
        self.session.close()
