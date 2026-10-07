"""Administration par le fondateur : clients, comptes, entités, transitaires, grilles tarifaires, clés
d'API, plafond IA, tableau de bord. Chaque accès à un client passe par ``OperatorScope.client`` (journal
d'audit ``acces_admin`` avec motif).

Règle SQLite (un seul écrivain) : un périmètre ouvert par ``op.client`` tient le verrou d'écriture
jusqu'à sa validation ; les appels qui ouvrent leur propre transaction (comptes, file de tâches, file des
sorties) sont faits **après** la sortie du bloc ``with db.operateur(...)``.
"""

from __future__ import annotations

import csv
import io
import json
import re
import secrets
from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from controldone.auth.cles_api import CleApiCreee, creer_cle_api
from controldone.auth.motdepasse import hacher_mot_de_passe
from controldone.auth.roles import ROLES_CLIENT, Acteur, Role
from controldone.ids import Prefixe, id_stable, nouvel_id
from controldone.jobs.couts import etat_plafond, llm_desactive
from controldone.model.referentiel import Entite as EntiteModele
from controldone.model.referentiel import GrilleTarifaire
from controldone.model.referentiel import Transitaire as TransitaireModele
from controldone.normalize.fiscal import normalize_vat
from controldone.outbox import FileSortante
from controldone.services.lecture import client_info, lister_dossiers, lister_lots
from controldone.services.plateforme import Interdit, Plateforme, RequeteInvalide
from controldone.storage.comptes import creer_utilisateur, utilisateur, utilisateur_par_email
from controldone.storage.file_jobs import JobStore
from controldone.storage.models import CleApi, Entite, Grille, Transitaire
from controldone.storage.scope import TenantScope

__all__ = [
    "ajouter_entite",
    "ajouter_transitaire",
    "creer_cle",
    "creer_client",
    "creer_utilisateur_client",
    "fiche_client",
    "importer_grille",
    "mois_courant",
    "tableau_de_bord",
]

_ID_CLIENT_RE = re.compile(r"[^a-z0-9]+")


def mois_courant() -> str:
    from controldone.calendrier import mois_paris

    return mois_paris()


def _fondateur(acteur: Acteur) -> None:
    if acteur.role is not Role.fondateur:
        raise Interdit("réservé au fondateur")


def _dec(x: Any, nom: str) -> Decimal | None:
    if x is None or str(x).strip() == "":
        return None
    from controldone.services.saisie import montant_saisi

    # analyseur strict commun (D-1316) : ni NaN, ni Infinity, ni notation scientifique, ni valeur négative
    return montant_saisi(x, nom=nom, decimales=4, zero=True)


# --- clients et comptes ----------------------------------------------------------------------------------


def creer_client(
    plateforme: Plateforme,
    fondateur: Acteur,
    raison_sociale: str,
    *,
    offre: str = "diagnostic",
    plafond: str | None = None,
    demo: bool = False,
    tenant_id: str | None = None,
) -> str:
    _fondateur(fondateur)
    raison_sociale = (raison_sociale or "").strip()
    if not raison_sociale or len(raison_sociale) > 300:
        raise RequeteInvalide("raison sociale obligatoire (300 caractères au plus)")
    if offre not in ("diagnostic", "continu"):
        raise RequeteInvalide("offre inconnue")
    from controldone.config import get_settings
    from controldone.services.saisie import montant_saisi

    p = (
        montant_saisi(plafond, nom="plafond", maximum=Decimal("10000"), zero=True)
        if plafond is not None and str(plafond).strip()
        else get_settings().plafond_mensuel_defaut(offre)
    )
    tid = tenant_id or (
        "cli_"
        + (_ID_CLIENT_RE.sub("_", raison_sociale.lower()).strip("_")[:24] or "client")
        + "_"
        + secrets.token_hex(3)
    )
    with plateforme.db.operateur(fondateur) as op:
        op.creer_client(
            tid,
            raison_sociale,
            offre=offre,
            plafond_cout_ia_mensuel_eur=p,
            reglages={"demo": True} if demo else {},
        )
    return tid


def creer_utilisateur_client(
    plateforme: Plateforme,
    fondateur: Acteur,
    tenant_id: str,
    email: str,
    role: str,
    *,
    nom: str | None = None,
    mot_de_passe: str | None = None,
) -> str:
    """Crée le compte (ou rattache un compte client existant) ; renvoie le mot de passe provisoire (à
    transmettre hors ligne, affiché une seule fois) ou ``""`` si le compte existait."""
    _fondateur(fondateur)
    email = (email or "").strip().lower()
    if not re.fullmatch(r"[^@\s]{1,64}@[^@\s]{1,250}", email):
        raise RequeteInvalide("adresse électronique invalide")
    try:
        r = Role(role)
    except ValueError as exc:
        raise RequeteInvalide("rôle inconnu") from exc
    if r not in ROLES_CLIENT:
        raise RequeteInvalide("rôle client attendu")
    existant = utilisateur_par_email(plateforme.db, email)
    mdp = ""
    if existant is None:
        mdp = mot_de_passe or secrets.token_urlsafe(12)
        uid = nouvel_id("usr")
        creer_utilisateur(
            plateforme.db,
            user_id=uid,
            email=email,
            mot_de_passe_hash=hacher_mot_de_passe(mdp),
            role=r,
            acteur=fondateur,
            nom=(nom or "").strip()[:200] or None,
        )
    else:
        if existant.role == Role.fondateur.value:
            raise RequeteInvalide("ce compte ne peut pas être rattaché à un client")
        uid = existant.id
    with plateforme.db.operateur(fondateur) as op:
        op.client(tenant_id, "création d'un compte utilisateur").ajouter_membre(uid, r)
    return mdp


def ajouter_entite(
    scope: TenantScope,
    raison_sociale: str,
    *,
    tva: str | None = None,
    siren: str | None = None,
    eori: str | None = None,
    alias: str | None = None,
) -> Entite:
    raison_sociale = (raison_sociale or "").strip()
    if not raison_sociale:
        raise RequeteInvalide("raison sociale obligatoire")
    siren = (siren or "").strip() or None
    if siren and not re.fullmatch(r"\d{9}", siren):
        raise RequeteInvalide("SIREN : 9 chiffres")
    # identifiant dérivé de la TVA **normalisée** : « fr 40 303… » et « FR40303… » désignent la même entité (D-4902)
    tva_n = normalize_vat(tva) if tva else None
    e = EntiteModele(
        id=id_stable(Prefixe.entite, scope.tenant_id, raison_sociale, tva_n),
        client_id=scope.tenant_id,
        raison_sociale=raison_sociale[:300],
        tva=tva_n,
        siren=siren,
        eori=(eori or "").strip().upper() or None,
        alias=[a.strip() for a in (alias or "").split(";") if a.strip()][:20],
    )
    return scope.enregistrer_entite(e)


def ajouter_transitaire(
    scope: TenantScope,
    nom: str,
    *,
    tva: str | None = None,
    alias: str | None = None,
    adresse: str | None = None,
    contact: str | None = None,
    transitaire_id: str | None = None,
) -> Transitaire:
    nom = (nom or "").strip()
    if not nom:
        raise RequeteInvalide("nom obligatoire")
    t = TransitaireModele(
        id=transitaire_id or id_stable(Prefixe.transitaire, scope.tenant_id, nom),
        client_id=scope.tenant_id,
        nom=nom[:300],
        tva=normalize_vat(tva) if tva else None,
        alias=[a.strip() for a in (alias or "").split(";") if a.strip()][:20],
        adresse=(adresse or "").strip()[:500] or None,
        contact_reclamation=(contact or "").strip()[:500] or None,
    )
    return scope.enregistrer_transitaire(t)


# --- grilles tarifaires ---------------------------------------------------------------------------------

COLONNES_CSV = [
    "code_poste",
    "nature",
    "mode",
    "prix",
    "unite_base",
    "pourcentage",
    "base_pourcentage",
    "minimum",
    "maximum",
    "franchise_jours",
    "inclus",
    "devise",
    "libelles_reconnus",
]


class _ExcelPointVirgule(csv.excel):
    delimiter = ";"


def _postes_csv(texte: str) -> list[dict[str, Any]]:
    try:
        dialecte: Any = csv.Sniffer().sniff(texte[:2048], delimiters=";,\t")
    except csv.Error:
        # Dialecte dérivé : modifier ``csv.excel`` lui-même changeait le séparateur de **tout** le processus
        # (exports CSV, lecture des taux BCE) après une grille mal formée (REV2-04).
        dialecte = _ExcelPointVirgule
    try:
        lignes = list(csv.DictReader(io.StringIO(texte), dialect=dialecte))
    except csv.Error as exc:  # champ démesuré, octet NUL… : refus lisible, jamais une erreur 500 (REV2-04)
        raise RequeteInvalide("fichier CSV illisible") from exc
    postes = []
    for n, ligne in enumerate(lignes, 2):
        if n > 500:
            raise RequeteInvalide("grille trop longue (500 postes au plus)")
        p = {k.strip(): (v or "").strip() for k, v in ligne.items() if k}
        if not p.get("code_poste"):
            continue
        poste: dict[str, Any] = {
            "code_poste": p["code_poste"],
            "nature": p.get("nature") or "autre_prestation",
            "mode": p.get("mode") or "forfait",
            "devise": p.get("devise") or "EUR",
            "libelles_reconnus": [
                x.strip() for x in (p.get("libelles_reconnus") or "").split("|") if x.strip()
            ],
        }
        for k in ("prix", "pourcentage", "minimum", "maximum"):
            d = _dec(p.get(k), f"ligne {n}, {k}")
            if d is not None:
                poste[k] = str(d)
        for k in ("franchise_jours", "inclus"):
            if p.get(k):
                try:
                    poste[k] = int(p[k])
                except ValueError as exc:
                    raise RequeteInvalide(f"ligne {n}, {k} : entier attendu") from exc
        for k in ("unite_base", "base_pourcentage"):
            if p.get(k):
                poste[k] = p[k]
        postes.append(poste)
    return postes


def importer_grille(
    scope: TenantScope,
    contenu: bytes,
    nom_fichier: str,
    *,
    transitaire_id: str,
    reference: str | None = None,
    valide_du: str | None = None,
    valide_au: str | None = None,
    hors_grille: str = "tolerees",
) -> Grille:
    """Grille en JSON (``GrilleTarifaire``) ou CSV (une ligne par poste, colonnes ``COLONNES_CSV``,
    libellés séparés par « | »). Enregistrée en **brouillon** : seule une grille validée par le fondateur
    sert aux contrôles D."""
    from controldone.referentiel_io import _grille_depuis_dict

    if len(contenu) > 2 * 1024 * 1024:
        raise RequeteInvalide("fichier de grille trop volumineux (2 Mo au plus)")
    scope.obtenir(Transitaire, transitaire_id)
    try:
        texte = contenu.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise RequeteInvalide("fichier texte UTF-8 attendu") from exc
    if nom_fichier.lower().endswith(".json") or texte.lstrip().startswith("{"):
        try:
            data = json.loads(texte)
        except json.JSONDecodeError as exc:
            raise RequeteInvalide("JSON illisible") from exc
        if not isinstance(data, dict):
            raise RequeteInvalide("objet JSON attendu")
    else:
        data = {"postes": _postes_csv(texte)}
    data = {k: v for k, v in data.items() if k not in ("statut", "client_id", "id")}
    data["transitaire_id"] = transitaire_id
    data["reference"] = (reference or data.get("reference") or data.get("grille_id") or "grille").strip()[
        :200
    ]
    if valide_du:
        data["valide_du"] = valide_du
    if valide_au:
        data["valide_au"] = valide_au
    if hors_grille in ("interdites", "tolerees"):
        data.setdefault("prestations_hors_grille", hors_grille)
    data["grille_id"] = data.get("grille_id") or id_stable(
        Prefixe.grille, scope.tenant_id, transitaire_id, data["reference"]
    )
    data["statut"] = "brouillon"
    try:
        g: GrilleTarifaire = _grille_depuis_dict(data, scope.tenant_id, False)
    except Exception as exc:
        raise RequeteInvalide("grille invalide : vérifier les colonnes et les valeurs") from exc
    if not g.postes:
        raise RequeteInvalide("aucun poste reconnu dans la grille")
    return scope.enregistrer_grille(g)


# --- clés d'API ------------------------------------------------------------------------------------------


def creer_cle(scope: TenantScope, nom: str, role: str = "client_admin") -> CleApiCreee:
    nom = (nom or "").strip()[:200] or "clé d'API"
    try:
        r = Role(role)
    except ValueError as exc:
        raise RequeteInvalide("rôle inconnu") from exc
    if r not in ROLES_CLIENT:
        raise RequeteInvalide("rôle client attendu")
    return creer_cle_api(scope, nom, role=r)


# --- lectures du fondateur -------------------------------------------------------------------------------


@dataclass
class LigneClient:
    id: str
    raison_sociale: str
    offre: str
    demo: bool
    actif: bool
    stats: dict[str, Any]
    cout_ia: Decimal
    plafond: Decimal
    llm_desactive: bool = False

    @property
    def ratio_ia(self) -> int:
        return int(self.cout_ia / self.plafond * 100) if self.plafond > 0 else 0


def tableau_de_bord(plateforme: Plateforme, fondateur: Acteur) -> dict[str, Any]:
    _fondateur(fondateur)
    mois = mois_courant()
    with plateforme.db.operateur(fondateur) as op:
        stats = op.statistiques()  # une seule entrée d'audit par affichage (« lire_tableau_de_bord »)
        clients = op.lister_clients(auditer=False)
        couts = op.couts_ia(mois, auditer=False)
        alertes = op.alertes(limite=200)
        nb_proposes = op.compter_proposes()
        lignes = []
        for t in clients:
            plafond = Decimal(
                str((t.reglages or {}).get("plafond_cout_ia_mensuel_eur") or t.plafond_cout_ia_mensuel_eur)
            )
            lignes.append(
                LigneClient(
                    id=t.id,
                    raison_sociale=t.raison_sociale,
                    offre=t.offre,
                    demo=bool((t.reglages or {}).get("demo")),
                    actif=t.actif,
                    stats=stats.get(t.id, {}),
                    cout_ia=couts.get(t.id, Decimal(0)),
                    plafond=plafond,
                    llm_desactive=llm_desactive(t.reglages),
                )
            )
        alertes_l = [
            {"id": a.id, "kind": a.kind, "tenant_id": a.tenant_id, "message": a.message, "cree_le": a.cree_le}
            for a in alertes
        ]
    store = JobStore(plateforme.db)
    jobs = store.compter_par_statut()
    n_echec = store.compter(statut="pending", avec_erreur=True)
    sorties = FileSortante(plateforme.db).lister(fondateur, statuts=["brouillon"])
    totaux = {
        "dossiers": sum(x.stats.get("nb_dossiers", 0) for x in lignes),
        "par_statut": {},
        "recouvrable_certain": sum(
            (x.stats.get("recouvrable_certain", Decimal(0)) for x in lignes), Decimal(0)
        ),
        "recouvrable_a_verifier": sum(
            (x.stats.get("recouvrable_a_verifier", Decimal(0)) for x in lignes), Decimal(0)
        ),
        "reste_a_recouvrer": sum((x.stats.get("reste_a_recouvrer", Decimal(0)) for x in lignes), Decimal(0)),
        "proposes": nb_proposes,
        "sorties": len(sorties),
        "jobs_echec": n_echec,
        "jobs_morts": jobs.get("dead", 0),
        "jobs": jobs,
    }
    for x in lignes:
        for st, n in (x.stats.get("dossiers") or {}).items():
            totaux["par_statut"][st] = totaux["par_statut"].get(st, 0) + n
    return {"mois": mois, "clients": lignes, "totaux": totaux, "alertes": alertes_l}


def fiche_client(
    plateforme: Plateforme,
    fondateur: Acteur,
    tenant_id: str,
    *,
    lire_dossiers: Callable[[TenantScope], Any] | None = None,
) -> dict[str, Any]:
    """Fiche d'un client (une seule ouverture journalisée du périmètre). ``lire_dossiers`` : lecture des dossiers
    faite dans ce même périmètre (l'interface y passe sa page et ses indicateurs calculés en SQL, bloc I3) ;
    défaut : liste complète (``lister_dossiers``)."""
    _fondateur(fondateur)
    with plateforme.db.operateur(fondateur) as op:
        scope = op.client(tenant_id, "consultation de la fiche client", lecture=True)
        info = client_info(scope)
        membres = [(m.user_id, m.role) for m in scope.membres()]
        entites = scope.lister(Entite, ordre=Entite.raison_sociale)
        transitaires = scope.lister(Transitaire, ordre=Transitaire.nom)
        grilles = scope.lister(Grille, ordre=Grille.grille_id)
        cles = scope.lister(CleApi, ordre=CleApi.cree_le)
        dossiers = lire_dossiers(scope) if lire_dossiers is not None else lister_dossiers(scope)
        lots = lister_lots(scope, limite=20)
        cout = scope.cout_ia(mois=mois_courant())
        plafond = etat_plafond(scope).plafond
        donnees = {
            "info": info,
            "entites": [
                {
                    "id": e.id,
                    "raison_sociale": e.raison_sociale,
                    "tva": e.tva,
                    "siren": (e.contenu or {}).get("siren"),
                    "eori": (e.contenu or {}).get("eori"),
                    "alias": ", ".join((e.contenu or {}).get("alias") or []),
                }
                for e in entites
            ],
            "transitaires": [
                {
                    "id": t.id,
                    "nom": t.nom,
                    "tva": t.tva,
                    "contact": (t.contenu or {}).get("contact_reclamation"),
                }
                for t in transitaires
            ],
            "grilles": [
                {
                    "id": g.id,
                    "grille_id": g.grille_id,
                    "version": g.version,
                    "reference": g.reference,
                    "transitaire": next(
                        (t.nom for t in transitaires if t.id == g.transitaire_id), g.transitaire_id
                    ),
                    "statut": g.statut,
                    "postes": len((g.contenu or {}).get("postes") or []),
                    "valide_le": g.valide_le,
                    "contenu": g.contenu,
                }
                for g in grilles
            ],
            "cles": [
                {
                    "id": c.id,
                    "nom": c.nom,
                    "prefixe": c.prefixe,
                    "role": c.role,
                    "cree_le": c.cree_le,
                    "revoquee": c.revoquee_le is not None,
                    "dernier_usage": c.dernier_usage,
                }
                for c in cles
            ],
            "dossiers": dossiers,
            "lots": lots,
            "cout_ia": cout,
            "plafond": plafond,
        }
    donnees["membres"] = []
    for uid, role in membres:
        u = utilisateur(plateforme.db, uid)
        donnees["membres"].append(
            {"id": uid, "email": u.email if u else "?", "role": role, "actif": u.actif if u else False}
        )
    return donnees
