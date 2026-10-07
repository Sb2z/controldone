"""Module « Marketing » du fondateur (``/admin/prospection``) : prospects, pipeline, import, recherche, séquences,
courriels, opposition, délivrabilité ; et la page publique de désinscription (``/desinscription/{jeton}``).

Niveau plateforme : fondateur seulement (second facteur exigé par la session), un rôle client reçoit 404 sur
chaque route. Toute route POST vérifie d'abord le jeton CSRF. Aucun envoi sans approbation dans la file de
validation (``/admin/validation``) ; aucun suivi d'ouverture ni de clic (D-5001 à D-5012)."""

from __future__ import annotations

import base64
import binascii
from datetime import date
from typing import Any

from fastapi import APIRouter
from starlette.datastructures import UploadFile
from starlette.requests import Request
from starlette.responses import Response

from controldone.auth.debit import LimiteurDebit
from controldone.auth.roles import Acteur, Role
from controldone.prospection.gabarits import VARIABLES
from controldone.prospection.recherche import (
    ClientRechercheEntreprises,
    CriteresRecherche,
    RechercheIndisponible,
    SourceEntreprises,
)
from controldone.prospection.scoring import LIBELLES_SCORE
from controldone.prospection.service import BLOCAGES, RefusProspection, ServiceProspection
from controldone.prospection.statuts import (
    LIBELLES_ARRET,
    LIBELLES_EVENEMENT,
    LIBELLES_MOTIF_SUPPRESSION,
    LIBELLES_SOURCE,
    LIBELLES_STATUT,
    LIBELLES_TRANCHE,
    STATUTS,
)
from controldone.storage.erreurs import AccesRefuse
from controldone.web.i18n import N_
from controldone.web.listes import Param, contient, lire_requete, paginer, trier
from controldone.web.rendu import page, redirection, retour_sur
from controldone.web.securite import acteur_de, depuis_boucle, formulaire_sync, url_publique

routeur = APIRouter(prefix="/admin/prospection")
routeur_public = APIRouter()

BASE = "/admin/prospection"
NAV = "prospection"

LIBELLES_IMPORT = {
    "nouveau": N_("À importer"),
    "doublon": N_("Doublon"),
    "exclu": N_("Exclu"),
    "invalide": N_("Invalide"),
}
MOTIFS_IMPORT = {
    "raison_sociale": N_("raison sociale absente"),
    "siren": N_("SIREN invalide"),
    "source": N_("aucune page source"),
    "liste_exclusion": N_("liste d'exclusion"),
    "verification_non": N_("exclusion déjà constatée dans le fichier"),
    "pays_bloque": N_("pays sans prospection autorisée"),
    "base": N_("déjà dans la base"),
    "fichier": N_("déjà plus haut dans le fichier"),
}
AVERTISSEMENTS_IMPORT = {
    "siren_a_verifier": N_("SIREN à vérifier"),
    "naf_illisible": N_("code NAF illisible"),
    "site_illisible": N_("site web illisible"),
    "adresse_sans_source": N_("adresse sans page source : ignorée"),
}
LIBELLES_NATURE = {
    "generique": N_("Générique"),
    "nominative": N_("Nominative"),
    "formulaire": N_("Formulaire"),
}
LIBELLES_DOUANE = {"oui": N_("Aucun apparent"), "non": N_("Service interne"), "inconnu": N_("Inconnu")}
LIBELLES_COURRIEL = {
    "brouillon": N_("À valider"),
    "approuve": N_("Approuvé"),
    "corrige": N_("Corrigé et approuvé"),
    "refuse": N_("Refusé"),
    "envoye": N_("Envoyé"),
}
LIBELLES_MANQUANTS = {
    "raison_sociale": N_("raison sociale"),
    "accroche": N_("citation du site (preuve d'import entre « » avec sa page source)"),
    "ville": N_("ville"),
    "expediteur": N_("nom de l'expéditeur"),
    "expediteur_nom": N_("nom de l'expéditeur"),
    "expediteur_siren": N_("SIREN de l'expéditeur"),
    "expediteur_adresse": N_("adresse postale de l'expéditeur"),
    "source_adresse": N_("page source de l'adresse"),
}
LIBELLES_VARIABLES = {
    "raison_sociale": N_("Raison sociale (source publique)"),
    "accroche": N_("Citation du site de l'entreprise (preuve d'import, page source enregistrée)"),
    "ville": N_("Ville"),
    "expediteur": N_("Nom de l'expéditeur (configuration)"),
}
#: Régions (codes INSEE) proposées à la recherche ; noms propres affichés en français (lang="fr").
REGIONS = (
    ("11", "Île-de-France"),
    ("24", "Centre-Val de Loire"),
    ("27", "Bourgogne-Franche-Comté"),
    ("28", "Normandie"),
    ("32", "Hauts-de-France"),
    ("44", "Grand Est"),
    ("52", "Pays de la Loire"),
    ("53", "Bretagne"),
    ("75", "Nouvelle-Aquitaine"),
    ("76", "Occitanie"),
    ("84", "Auvergne-Rhône-Alpes"),
    ("93", "Provence-Alpes-Côte d'Azur"),
)
TRANCHES_RECHERCHE = ("11", "12", "21", "22", "31")
CRENEAUX_SCORE = {"70": N_("70 et plus"), "40": N_("40 à 69"), "0": N_("moins de 40")}


def _commun() -> dict[str, Any]:
    return {
        "statuts": STATUTS,
        "libelles_statut": LIBELLES_STATUT,
        "libelles_source": LIBELLES_SOURCE,
        "libelles_tranche": LIBELLES_TRANCHE,
        "libelles_evenement": LIBELLES_EVENEMENT,
        "libelles_arret": LIBELLES_ARRET,
        "libelles_nature": LIBELLES_NATURE,
        "libelles_douane": LIBELLES_DOUANE,
        "libelles_courriel": LIBELLES_COURRIEL,
        "libelles_manquants": LIBELLES_MANQUANTS,
        "libelles_motif_suppression": LIBELLES_MOTIF_SUPPRESSION,
        "blocages_lib": BLOCAGES,
        "libelles_score": LIBELLES_SCORE,
        "base": BASE,
    }


def _fondateur(request: Request) -> Acteur:
    acteur = acteur_de(request)
    if acteur.role is not Role.fondateur:
        raise AccesRefuse("introuvable ou hors périmètre")
    return acteur


def _url_publique(request: Request | None) -> str | None:
    try:
        return url_publique(request)
    except ValueError:
        return None


def _svc(request: Request) -> ServiceProspection:
    return ServiceProspection(request.app.state.plateforme.db, url_publique=_url_publique(request))


def _source(request: Request) -> SourceEntreprises:
    """Source des candidats : un double peut être posé sur ``app.state.source_entreprises`` (tests, aucun réseau)."""
    source = getattr(request.app.state, "source_entreprises", None)
    return source if source is not None else ClientRechercheEntreprises()


def _s(form: Any, cle: str, n: int = 500) -> str:
    v = form.get(cle)
    return v.strip()[:n] if isinstance(v, str) else ""


def _refus(request: Request, url: str, exc: RefusProspection) -> Response:
    return redirection(request, url, erreur=exc.gabarit, **exc.params)


def _fiche(pid: str) -> str:
    return f"{BASE}/prospects/{pid}"


# --- tableau de bord ---------------------------------------------------------------------------------------------


@routeur.get("")
def tableau(request: Request) -> Response:
    f = _fondateur(request)
    svc = _svc(request)
    t = svc.tableau(f)
    from controldone.web.graphes import barres

    graphe = barres(
        "prosp-pipeline",
        N_("Prospects par statut"),
        [(_lib(LIBELLES_STATUT[st]), n) for st, n in t["par_statut"] if n],
        colonne_libelle=N_("Statut"),
        colonne_valeur=N_("Prospects"),
    )
    return page(
        request,
        "admin/prospection/tableau.html.j2",
        titre=N_("Marketing"),
        nav=NAV,
        sous_nav="tableau",
        t=t,
        graphe_pipeline=graphe,
        stats=svc.statistiques(f),
        **_commun(),
    )


def _lib(texte: str) -> str:
    from controldone.web.i18n import traduire

    return traduire(texte)


# --- prospects ---------------------------------------------------------------------------------------------------

_TRIS = ("-score", "score", "nom", "-nom", "-cree", "cree")


def _params_liste(lignes: list[dict[str, Any]]) -> dict[str, Param]:
    pays = tuple(sorted({x["p"].pays for x in lignes}))
    nafs = tuple(sorted({x["p"].naf for x in lignes if x["p"].naf}))
    return {
        "q": Param(N_("Recherche")),
        "statut": Param(N_("Statut"), "choix", STATUTS),
        "score": Param(N_("Score"), "choix", tuple(CRENEAUX_SCORE)),
        "pays": Param(N_("Pays"), "choix", pays),
        "naf": Param(N_("Secteur (NAF)"), "choix", nafs),
        "taille": Param(N_("Taille"), "choix", tuple(LIBELLES_TRANCHE)),
        "source": Param(N_("Source"), "choix", tuple(LIBELLES_SOURCE)),
    }


@routeur.get("/prospects")
def prospects(request: Request) -> Response:
    f = _fondateur(request)
    lignes = _svc(request).liste(f)
    params = _params_liste(lignes)
    req = lire_requete(request, params, _TRIS, "-score", ancre="#liste")
    fl = req.filtres

    def garde(x: dict[str, Any]) -> bool:
        p = x["p"]
        if fl.get("statut") and p.statut != fl["statut"]:
            return False
        if fl.get("score"):
            bas = int(fl["score"])
            haut = {"70": 101, "40": 70, "0": 40}[fl["score"]]
            if not bas <= p.score < haut:
                return False
        if fl.get("pays") and p.pays != fl["pays"]:
            return False
        if fl.get("naf") and p.naf != fl["naf"]:
            return False
        if fl.get("taille") and p.tranche_effectif != fl["taille"]:
            return False
        if fl.get("source") and p.source != fl["source"]:
            return False
        return contient(fl.get("q"), p.raison_sociale, p.ville, p.siren, p.naf)

    filtres = [x for x in lignes if garde(x)]
    tries = trier(
        filtres,
        req.tri,
        {
            "score": lambda x: x["p"].score,
            "nom": lambda x: x["p"].nom_normalise,
            "cree": lambda x: x["p"].cree_le,
        },
    )
    return page(
        request,
        "admin/prospection/prospects.html.j2",
        titre=N_("Prospects"),
        nav=NAV,
        sous_nav="prospects",
        p=paginer(tries, req),
        req=req,
        pays=params["pays"].choix,
        nafs=params["naf"].choix,
        creneaux=CRENEAUX_SCORE,
        **_commun(),
    )


@routeur.post("/prospects")
def creer(request: Request) -> Response:
    f = _fondateur(request)
    form = formulaire_sync(request)
    champs = {
        k: _s(form, k, 2000)
        for k in (
            "raison_sociale",
            "siren",
            "naf",
            "tranche_effectif",
            "pays",
            "departement",
            "ville",
            "site_web",
            "groupe",
            "preuve_import",
            "preuve_url",
            "sans_service_douane",
            "raison_ciblage",
            "source_url",
        )
    }
    contact = None
    if _s(form, "adresse", 320) or _s(form, "url_formulaire", 1000):
        contact = {
            "adresse": _s(form, "adresse", 320) or None,
            "url_formulaire": _s(form, "url_formulaire", 1000) or None,
            "source_url": _s(form, "source_contact", 1000),
            "personne": _s(form, "personne", 200) or None,
        }
    try:
        pid = _svc(request).creer(f, champs, contact)
    except RefusProspection as exc:
        return _refus(request, f"{BASE}/prospects#nouveau", exc)
    return redirection(request, _fiche(pid), message=N_("Prospect enregistré : à qualifier."))


@routeur.get("/pipeline")
def pipeline(request: Request) -> Response:
    f = _fondateur(request)
    lignes = _svc(request).liste(f)
    colonnes: dict[str, list[dict[str, Any]]] = {st: [] for st in STATUTS}
    for x in sorted(lignes, key=lambda x: (-x["p"].score, x["p"].nom_normalise)):
        colonnes[x["p"].statut].append(x)
    return page(
        request,
        "admin/prospection/pipeline.html.j2",
        titre=N_("Pipeline"),
        nav=NAV,
        sous_nav="pipeline",
        colonnes=colonnes,
        limite=40,
        **_commun(),
    )


@routeur.get("/prospects/{pid}")
def fiche(request: Request, pid: str) -> Response:
    f = _fondateur(request)
    svc = _svc(request)
    d = svc.fiche(f, pid)
    return page(
        request,
        "admin/prospection/prospect.html.j2",
        titre=d["p"].raison_sociale,
        nav=NAV,
        sous_nav="prospects",
        d=d,
        variables=LIBELLES_VARIABLES,
        lien_public=svc.url_publique is not None,
        demo=bool(d["p"].demo),
        **_commun(),
    )


def _action_prospect(request: Request, pid: str, faire: Any, message: str) -> Response:
    f = _fondateur(request)
    form = formulaire_sync(request)
    retour = retour_sur(form.get("retour"), _fiche(pid))
    try:
        faire(_svc(request), f, form)
    except RefusProspection as exc:
        return _refus(request, retour, exc)
    return redirection(request, retour, message=message)


@routeur.post("/prospects/{pid}/statut")
def statut(request: Request, pid: str) -> Response:
    return _action_prospect(
        request,
        pid,
        lambda svc, f, form: svc.changer_statut(f, pid, _s(form, "statut", 32)),
        N_("Statut enregistré."),
    )


@routeur.post("/prospects/{pid}/modifier")
def modifier(request: Request, pid: str) -> Response:
    cles = (
        "preuve_import",
        "preuve_url",
        "site_web",
        "groupe",
        "raison_ciblage",
        "base_legale",
        "sans_service_douane",
        "naf",
        "tranche_effectif",
        "departement",
        "ville",
        "pays",
    )
    return _action_prospect(
        request,
        pid,
        lambda svc, f, form: svc.modifier(f, pid, {k: _s(form, k, 2000) for k in cles if k in form}),
        N_("Fiche enregistrée ; score recalculé."),
    )


@routeur.post("/prospects/{pid}/note")
def note(request: Request, pid: str) -> Response:
    return _action_prospect(
        request,
        pid,
        lambda svc, f, form: svc.ajouter_note(f, pid, _s(form, "texte", 5000)),
        N_("Note ajoutée."),
    )


@routeur.post("/prospects/{pid}/contacts")
def contact(request: Request, pid: str) -> Response:
    return _action_prospect(
        request,
        pid,
        lambda svc, f, form: svc.ajouter_contact(
            f,
            pid,
            adresse=_s(form, "adresse", 320) or None,
            url_formulaire=_s(form, "url_formulaire", 1000) or None,
            source_url=_s(form, "source_url", 1000),
            personne=_s(form, "personne", 200) or None,
        ),
        N_("Contact enregistré."),
    )


@routeur.post("/prospects/{pid}/reponse")
def reponse(request: Request, pid: str) -> Response:
    return _action_prospect(
        request,
        pid,
        lambda svc, f, form: svc.enregistrer_reponse(f, pid, _s(form, "texte", 10000)),
        N_("Réponse enregistrée : séquence arrêtée."),
    )


def _date_saisie(v: str) -> date | None:
    try:
        return date.fromisoformat(v) if v else None
    except ValueError:
        raise RefusProspection("Date attendue (AAAA-MM-JJ).") from None


@routeur.post("/prospects/{pid}/rendez-vous")
def rendez_vous(request: Request, pid: str) -> Response:
    return _action_prospect(
        request,
        pid,
        lambda svc, f, form: svc.enregistrer_rendez_vous(
            f, pid, _date_saisie(_s(form, "date", 10)), _s(form, "texte", 2000)
        ),
        N_("Rendez-vous enregistré."),
    )


@routeur.post("/prospects/{pid}/sequence")
def preparer(request: Request, pid: str) -> Response:
    return _action_prospect(
        request,
        pid,
        lambda svc, f, form: svc.preparer_sequence(
            f, pid, _s(form, "contact_id", 64), _s(form, "sequence_id", 64)
        ),
        N_("Premier courriel préparé : à approuver dans la file de validation."),
    )


@routeur.post("/inscriptions/{iid}/arreter")
def arreter(request: Request, iid: str) -> Response:
    f = _fondateur(request)
    form = formulaire_sync(request)
    retour = retour_sur(form.get("retour"), f"{BASE}/prospects")
    _svc(request).arreter_sequence(f, iid)
    return redirection(request, retour, message=N_("Séquence arrêtée."))


@routeur.post("/contacts/{cid}/rebond")
def rebond(request: Request, cid: str) -> Response:
    f = _fondateur(request)
    form = formulaire_sync(request)
    retour = retour_sur(form.get("retour"), f"{BASE}/prospects")
    _svc(request).enregistrer_rebond(f, cid)
    return redirection(
        request, retour, message=N_("Rebond enregistré : adresse ajoutée à la liste d'opposition.")
    )


@routeur.post("/contacts/{cid}/opposition")
def opposition_contact(request: Request, cid: str) -> Response:
    f = _fondateur(request)
    form = formulaire_sync(request)
    retour = retour_sur(form.get("retour"), f"{BASE}/prospects")
    try:
        _svc(request).opposer_contact(f, cid, _s(form, "motif", 32) or "desinscription")
    except RefusProspection as exc:
        return _refus(request, retour, exc)
    return redirection(
        request, retour, message=N_("Opposition enregistrée : plus aucun courriel à ce prospect.")
    )


# --- import ------------------------------------------------------------------------------------------------------


def _form_import(request: Request) -> Any:
    form = depuis_boucle(request.form, max_files=1, max_fields=20, max_part_size=1024 * 1024)
    request.app.state.securite.verifier(
        request, form.get("csrf") if isinstance(form.get("csrf"), str) else None
    )
    return form


@routeur.get("/importer")
def importer_page(request: Request) -> Response:
    _fondateur(request)
    return page(
        request,
        "admin/prospection/import.html.j2",
        titre=N_("Importer des prospects"),
        nav=NAV,
        sous_nav="importer",
        lignes=None,
        **_commun(),
    )


@routeur.post("/importer")
def importer(request: Request) -> Response:
    f = _fondateur(request)
    form = _form_import(request)
    svc = _svc(request)
    fichier = form.get("fichier")
    if isinstance(fichier, UploadFile):  # étape 1 : aperçu
        contenu = fichier.file.read(600 * 1024)
        nom = (fichier.filename or "import.csv")[:200]
        try:
            lignes = svc.analyser_import(f, contenu)
        except RefusProspection as exc:
            return _refus(request, f"{BASE}/importer", exc)
        return page(
            request,
            "admin/prospection/import.html.j2",
            titre=N_("Importer des prospects"),
            nav=NAV,
            sous_nav="importer",
            lignes=lignes,
            nom_fichier=nom,
            contenu_b64=base64.b64encode(contenu).decode("ascii"),
            libelles_import=LIBELLES_IMPORT,
            motifs_import=MOTIFS_IMPORT,
            avertissements_import=AVERTISSEMENTS_IMPORT,
            **_commun(),
        )
    try:  # étape 2 : import confirmé (analyse refaite)
        contenu = base64.b64decode(_s(form, "contenu", 900 * 1024), validate=True)
    except (binascii.Error, ValueError):
        return redirection(
            request, f"{BASE}/importer", erreur=N_("Fichier manquant : choisissez un fichier CSV.")
        )
    if not contenu:
        return redirection(
            request, f"{BASE}/importer", erreur=N_("Fichier manquant : choisissez un fichier CSV.")
        )
    try:
        r = svc.importer(f, contenu, _s(form, "nom_fichier", 200) or "import.csv")
    except RefusProspection as exc:
        return _refus(request, f"{BASE}/importer", exc)
    return redirection(
        request,
        f"{BASE}/prospects",
        message=N_("{n} prospect(s) importé(s) ; doublons {d}, exclus {e}, invalides {i}."),
        n=r.crees,
        d=r.doublons,
        e=r.exclus,
        i=r.invalides,
    )


# --- recherche d'entreprises --------------------------------------------------------------------------------------


def _criteres(form: Any) -> CriteresRecherche:
    nafs = [x.strip().upper() for x in _s(form, "naf", 400).replace(";", ",").split(",") if x.strip()]
    if form.get("naf_defaut") == "1":
        from controldone.prospection.config import charger_config

        nafs = sorted(set(nafs) | set(charger_config().naf_importateurs))
    import re

    nafs = [x for x in nafs if re.fullmatch(r"\d{2}\.\d{2}[A-Z]", x)][:30]
    tranches = [t for t in form.getlist("tranche") if t in TRANCHES_RECHERCHE]
    dep = _s(form, "departement", 3)
    region = _s(form, "region", 2)
    try:
        page_ = max(1, min(int(_s(form, "page", 3) or "1"), 20))
    except ValueError:
        page_ = 1
    return CriteresRecherche(
        mots=_s(form, "mots", 80),
        naf=tuple(nafs),
        tranches=tuple(tranches),
        departement=dep if re.fullmatch(r"\d{2,3}|2[AB]", dep) else "",
        region=region if region in dict(REGIONS) else "",
        page=page_,
    )


def _page_recherche(request: Request, **contexte: Any) -> Response:
    return page(
        request,
        "admin/prospection/recherche.html.j2",
        titre=N_("Rechercher des entreprises"),
        nav=NAV,
        sous_nav="rechercher",
        regions=REGIONS,
        tranches=TRANCHES_RECHERCHE,
        **{"resultats": None, "criteres": None, "erreur_api": False, **contexte},
        **_commun(),
    )


@routeur.get("/rechercher")
def rechercher_page(request: Request) -> Response:
    _fondateur(request)
    return _page_recherche(request)


@routeur.post("/rechercher")
def rechercher(request: Request) -> Response:
    """Recherche lancée par le fondateur (POST : jamais relancée par un simple rechargement)."""
    f = _fondateur(request)
    form = formulaire_sync(request)
    criteres = _criteres(form)
    if not (criteres.mots or criteres.naf or criteres.departement or criteres.region):
        return redirection(
            request,
            f"{BASE}/rechercher",
            erreur=N_("Indiquez au moins un critère (mots, NAF, département ou région)."),
        )
    try:
        candidats, exclus, res = _svc(request).rechercher(f, _source(request), criteres)
    except RechercheIndisponible:
        return _page_recherche(request, criteres=criteres, erreur_api=True)
    return _page_recherche(request, criteres=criteres, resultats=candidats, exclus=exclus, res=res)


@routeur.post("/rechercher/ajouter")
def ajouter_candidat(request: Request) -> Response:
    f = _fondateur(request)
    form = formulaire_sync(request)
    try:
        pid = _svc(request).ajouter_candidat(f, _source(request), _s(form, "siren", 9))
    except RefusProspection as exc:
        return _refus(request, f"{BASE}/rechercher", exc)
    except RechercheIndisponible:
        return redirection(
            request, f"{BASE}/rechercher", erreur=N_("Source publique injoignable : réessayez plus tard.")
        )
    return redirection(
        request,
        _fiche(pid),
        message=N_(
            "Candidat ajouté : à qualifier (preuve d'import et contact publié à relever sur son site)."
        ),
    )


# --- séquences ---------------------------------------------------------------------------------------------------


@routeur.get("/sequences")
def sequences(request: Request) -> Response:
    f = _fondateur(request)
    svc = _svc(request)
    return page(
        request,
        "admin/prospection/sequences.html.j2",
        titre=N_("Séquences"),
        nav=NAV,
        sous_nav="sequences",
        sequences=svc.sequences(f),
        stats=svc.statistiques(f),
        variables=LIBELLES_VARIABLES,
        noms_variables=sorted(VARIABLES),
        **_commun(),
    )


@routeur.post("/sequences/{sid}")
def modifier_sequence(request: Request, sid: str) -> Response:
    f = _fondateur(request)
    form = formulaire_sync(request)
    etapes = []
    for rang in range(1, 7):
        objet, corps = _s(form, f"objet_{rang}", 200), _s(form, f"corps_{rang}", 6000)
        if not objet and not corps:
            continue
        try:
            delai: Any = int(_s(form, f"delai_{rang}", 4))
        except ValueError:
            delai = None
        etapes.append(
            {
                "rang": len(etapes) + 1,
                "delai_jours": delai,
                "objet": objet,
                "corps": corps.replace("\r\n", "\n"),
            }
        )
    try:
        _svc(request).modifier_sequence(f, sid, _s(form, "nom", 200), etapes)
    except RefusProspection as exc:
        return _refus(request, f"{BASE}/sequences#seq-{sid}", exc)
    return redirection(request, f"{BASE}/sequences#seq-{sid}", message=N_("Séquence enregistrée."))


# --- courriels ---------------------------------------------------------------------------------------------------


@routeur.get("/courriels")
def courriels(request: Request) -> Response:
    f = _fondateur(request)
    svc = _svc(request)
    from controldone.prospection.envoi import expediteur_configure

    return page(
        request,
        "admin/prospection/courriels.html.j2",
        titre=N_("Courriels de prospection"),
        nav=NAV,
        sous_nav="courriels",
        liste=svc.courriels(f),
        envoi_configure=expediteur_configure() is not None,
        compteurs=svc.compteurs_du_jour(),
        **_commun(),
    )


@routeur.post("/courriels/etapes")
def etapes_dues(request: Request) -> Response:
    f = _fondateur(request)
    formulaire_sync(request)
    ids = _svc(request).preparer_etapes_dues(f)
    return redirection(
        request,
        f"{BASE}/courriels",
        message=N_("{n} étape(s) préparée(s) : à approuver dans la file de validation."),
        n=len(ids),
    )


def _envoi(request: Request, aid: str, declaration: bool) -> Response:
    f = _fondateur(request)
    formulaire_sync(request)
    from controldone.prospection.envoi import ExpediteurDeclaration, expediteur_configure

    exp = ExpediteurDeclaration(f.id) if declaration else expediteur_configure()
    if exp is None:
        return redirection(
            request,
            f"{BASE}/courriels",
            erreur=N_("Approuvé, envoi non configuré : aucune messagerie de prospection n'est configurée."),
        )
    try:
        _svc(request).envoyer(f, aid, exp, declaration=declaration)
    except RefusProspection as exc:
        return _refus(request, f"{BASE}/courriels", exc)
    except Exception as exc:  # erreur de la messagerie : rien n'est marqué envoyé (réservation levée)
        from controldone.outbox import ActionBloquee, TransitionInterdite

        if isinstance(exc, ActionBloquee):
            return redirection(request, f"{BASE}/courriels", erreur=N_("Bloqué par les garde-fous."))
        if isinstance(exc, TransitionInterdite):
            return redirection(request, f"{BASE}/courriels", erreur=N_("Ce courriel a déjà été envoyé."))
        return redirection(
            request, f"{BASE}/courriels", erreur=N_("Échec de l'envoi : rien n'a été marqué envoyé.")
        )
    return redirection(
        request,
        f"{BASE}/courriels",
        message=N_("Envoi déclaré : enregistré comme envoyé depuis votre messagerie.")
        if declaration
        else N_("Courriel envoyé."),
    )


@routeur.post("/courriels/{aid}/envoyer")
def envoyer(request: Request, aid: str) -> Response:
    return _envoi(request, aid, False)


@routeur.post("/courriels/{aid}/declarer")
def declarer(request: Request, aid: str) -> Response:
    return _envoi(request, aid, True)


# --- liste d'opposition, conservation, délivrabilité ---------------------------------------------------------------


@routeur.get("/opposition")
def opposition(request: Request) -> Response:
    f = _fondateur(request)
    svc = _svc(request)
    return page(
        request,
        "admin/prospection/opposition.html.j2",
        titre=N_("Liste d'opposition"),
        nav=NAV,
        sous_nav="opposition",
        liste=svc.suppressions(f),
        a_purger=svc.a_purger(f),
        **_commun(),
    )


@routeur.post("/opposition")
def ajouter_opposition(request: Request) -> Response:
    f = _fondateur(request)
    form = formulaire_sync(request)
    try:
        _svc(request).ajouter_opposition(f, _s(form, "adresse", 320), _s(form, "motif", 32))
    except RefusProspection as exc:
        return _refus(request, f"{BASE}/opposition", exc)
    return redirection(request, f"{BASE}/opposition", message=N_("Adresse ajoutée à la liste d'opposition."))


@routeur.post("/purger")
def purger(request: Request) -> Response:
    f = _fondateur(request)
    formulaire_sync(request)
    n = _svc(request).purger(f)
    return redirection(request, f"{BASE}/opposition", message=N_("{n} prospect(s) purgé(s)."), n=n)


@routeur.get("/delivrabilite")
def delivrabilite(request: Request) -> Response:
    _fondateur(request)
    from controldone.prospection.config import charger_config

    return page(
        request,
        "admin/prospection/delivrabilite.html.j2",
        titre=N_("Délivrabilité"),
        nav=NAV,
        sous_nav="delivrabilite",
        config=charger_config(),
        **_commun(),
    )


# --- désinscription (publique) ---------------------------------------------------------------------------------------


def _limiteur(request: Request) -> LimiteurDebit:
    lim = getattr(request.app.state, "limiteur_desinscription", None)
    if lim is None:
        lim = LimiteurDebit(20, 20 / 60)  # 20 d'avance, puis une toutes les 3 secondes, par adresse IP
        request.app.state.limiteur_desinscription = lim
    return lim


def _desinscription(request: Request, jeton: str, confirmer: bool) -> Response:
    from controldone.prospection.jetons import JetonInvalide, verifier

    ip = request.client.host if request.client else "?"
    if not _limiteur(request).autoriser(f"desinscription:{ip}"):
        return page(
            request,
            "admin/prospection/desinscription.html.j2",
            titre=N_("Désinscription"),
            statut=429,
            etat="trop",
        )
    svc = _svc(request)
    try:
        if confirmer:
            svc.desinscrire_par_jeton(jeton)
        else:
            verifier(jeton, svc.secrets_jetons())
    except JetonInvalide:
        return page(
            request,
            "admin/prospection/desinscription.html.j2",
            titre=N_("Désinscription"),
            statut=403 if confirmer else 404,
            etat="invalide",
        )
    return page(
        request,
        "admin/prospection/desinscription.html.j2",
        titre=N_("Désinscription"),
        etat="faite" if confirmer else "confirmer",
        jeton=jeton,
    )


@routeur_public.get("/desinscription/{jeton}")
def desinscription_page(request: Request, jeton: str) -> Response:
    """Lien du pied des courriels : page de confirmation (un clic). Pas d'opposition sur un simple GET : les
    passerelles de sécurité des messageries ouvrent les liens à l'avance (D-5007)."""
    return _desinscription(request, jeton, False)


@routeur_public.post("/desinscription/{jeton}")
def desinscription(request: Request, jeton: str) -> Response:
    """Opposition : bouton de la page, ou désinscription en un clic depuis la messagerie (RFC 8058,
    ``List-Unsubscribe-Post``). Le jeton signé tient lieu d'autorisation (pas de jeton CSRF : la messagerie n'en a
    pas) ; un jeton invalide reçoit 403."""
    return _desinscription(request, jeton, True)
