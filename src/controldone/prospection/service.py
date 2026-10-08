"""Service de prospection du fondateur (niveau plateforme, D-5001 à D-5012).

Règles tenues ici, quel que soit l'appelant (interface, ligne de commande, agent) :

- **Fondateur seulement** (l'agent ``prospection`` prépare les étapes suivantes en tant que système, sans rien
  approuver ni envoyer). Un rôle client reçoit ``AccesRefuse`` (404 dans l'interface).
- **Rien ne part sans validation** : chaque courriel est un brouillon ``email_prospection`` de la file de
  validation (``FileSortante``). L'envoi n'a lieu qu'après approbation, par un expéditeur configuré ; sinon
  l'action reste approuvée. Le fondateur peut **déclarer** un envoi fait depuis sa propre messagerie.
- **Rien d'inventé** : prospects avec source (URL) et date de collecte ; adresses publiées ou saisies avec leur
  page source ; variables des modèles tirées de faits enregistrés (un fait absent bloque la préparation).
- **Liste d'exclusion** à l'import, à la recherche, avant la mise en file et avant l'envoi.
- **Opposition** (désinscription, rebond, « ne plus contacter ») vérifiée avant la mise en file et avant l'envoi ;
  adresses nominatives des pays à consentement (CH, BE) bloquées sans base légale enregistrée ; pays bloqués.
- **Plafonds quotidiens** de préparations et d'envois ; **arrêt des séquences** sur réponse, opposition, rebond,
  changement de statut ou brouillon refusé.
- Journal d'audit pour l'import, les changements de statut, la mise en file, l'envoi, l'opposition et la purge
  (identifiants et compteurs seulement, jamais d'adresse en clair).
- Texte d'une réponse reçue : **donnée**, enregistrée telle quelle et affichée échappée, jamais interprétée.
"""

from __future__ import annotations

import contextlib
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from typing import Any

from controldone.auth.roles import Acteur, Role
from controldone.calendrier import PARIS, aujourdhui_paris
from controldone.ids import nouvel_id
from controldone.outbox import FileSortante, StatutAction, TypeAction
from controldone.outbox.modele import ActionSortante
from controldone.prospection import contacts as adr
from controldone.prospection import gabarits
from controldone.prospection.config import A_COMPLETER, ConfigProspection, charger_config
from controldone.prospection.exclusion import chercher_exclusion, normaliser_nom, textes_a_verifier
from controldone.prospection.import_csv import LigneImport, analyser_csv, siren_valide
from controldone.prospection.recherche import (
    API_RECHERCHE,
    CandidatEntreprise,
    CriteresRecherche,
    ResultatRecherche,
    SourceEntreprises,
    url_annuaire,
)
from controldone.prospection.scoring import FaitsScore, Score, calculer_score
from controldone.prospection.statuts import (
    ETAPES_PIPELINE,
    LIBELLES_TRANCHE,
    STATUTS,
    STATUTS_ACTIFS_SEQUENCE,
    rang_statut,
)
from controldone.services.plateforme import RequeteInvalide
from controldone.storage import prospection as stock
from controldone.storage.audit import journaliser
from controldone.storage.coltypes import maintenant
from controldone.storage.db import Database
from controldone.storage.erreurs import AccesRefuse

__all__ = ["BLOCAGES", "RefusProspection", "ServiceProspection", "identite_par_defaut"]

KIND = TypeAction.email_prospection.value

#: Motifs qui empêchent de préparer ou d'envoyer un courriel (code -> libellé, traduit à l'affichage).
BLOCAGES = {
    "exclusion": "Liste d'exclusion : aucun courriel possible.",
    "pays_bloque": "Pays sans prospection autorisée (avis d'un avocat local attendu).",
    "opposition": "Adresse dans la liste d'opposition.",
    "consentement": "Adresse nominative d'un pays à consentement : base légale à enregistrer.",
    "formulaire": "Contact par formulaire seulement : aucun courriel possible.",
    "statut": "Statut du prospect incompatible avec un envoi.",
    "faits_manquants": "Faits manquants : le texte contient « à compléter ».",
    "pied_absent": "Le pied obligatoire (identité, opposition « STOP ») a été retiré du texte.",
    "plafond": "Plafond quotidien atteint.",
    "contact_absent": "Contact introuvable.",
}


#: Fichier d'import refusé (code de ``analyser_csv``) -> message.
REFUS_CSV = {
    "encodage": "Fichier CSV refusé : encodage attendu UTF-8.",
    "illisible": "Fichier CSV refusé : fichier illisible.",
    "colonnes": "Fichier CSV refusé : colonne raison_sociale absente.",
    "lignes": "Fichier CSV refusé : 2000 lignes au plus.",
    "taille": "Fichier CSV refusé : 512 Ko au plus.",
}


class RefusProspection(RequeteInvalide):
    """Refus d'une action (message gabarit français + paramètres, traduits à l'affichage)."""

    def __init__(self, gabarit: str, **params: Any) -> None:
        self.gabarit = gabarit
        self.params = params
        super().__init__(gabarit.format(**params) if params else gabarit)


def _ok(v: str | None) -> str | None:
    v = (v or "").strip()
    return v if v and A_COMPLETER not in v.upper() else None


def identite_par_defaut(config: ConfigProspection) -> gabarits.IdentiteExpediteur:
    """Identité de l'expéditeur : nom (configuration de prospection) ; SIREN et adresse (identité du vendeur,
    ``config/offres.yaml`` ou ``CONTROLDONE_VENDEUR_*``). Un champ « À COMPLÉTER » est absent."""
    siren = adresse = entreprise = None
    with contextlib.suppress(Exception):
        from controldone.facturation.offres import charger_offres

        v = charger_offres().vendeur
        siren = _ok(v.siren)
        rue, cp, ville = _ok(v.adresse_ligne), _ok(v.code_postal), _ok(v.ville)
        adresse = f"{rue}, {cp} {ville}" if rue and cp and ville else None
        rs, forme = _ok(v.raison_sociale), _ok(v.forme_juridique)
        entreprise = f"{rs} ({forme})" if rs and forme else rs
    return gabarits.IdentiteExpediteur(
        nom=_ok(config.expediteur_nom),
        fonction=config.expediteur_fonction,
        entreprise=entreprise,
        siren=siren,
        adresse=adresse,
    )


def _jour(now: datetime) -> tuple[datetime, datetime]:
    """Début et fin (UTC) du jour civil de Paris qui contient ``now``."""
    j = aujourdhui_paris(now)
    debut = datetime.combine(j, time(0), tzinfo=PARIS).astimezone(UTC)
    fin = datetime.combine(j + timedelta(days=1), time(0), tzinfo=PARIS).astimezone(UTC)
    return debut, fin


def _source_lisible(url: str | None) -> str | None:
    """« la page exemple.fr/contact » : origine de l'adresse, sans schéma (art. 14 RGPD)."""
    if not adr.url_valide(url):
        return None
    sans = url.split("://", 1)[1].rstrip("/")  # type: ignore[union-attr]
    return f"la page {sans.removeprefix('www.')}"


@dataclass
class VueContact:
    id: str
    genre: str
    adresse: str | None
    nature: str
    url_formulaire: str | None
    source_url: str
    personne: str | None
    origine: str
    oppose: bool
    blocages: list[str] = field(default_factory=list)


@dataclass
class VueEtape:
    rang: int
    outbox_id: str
    prepare_le: str
    statut: str | None = None
    envoye_le: datetime | None = None
    reference: str | None = None


@dataclass
class VueInscription:
    id: str
    sequence_id: str
    sequence_nom: str
    contact_id: str
    statut: str
    motif_arret: str | None
    demarree_le: datetime
    etapes: list[VueEtape]
    total_etapes: int
    prochaine: dict[str, Any] | None = None


@dataclass
class RapportImport:
    crees: int = 0
    doublons: int = 0
    exclus: int = 0
    invalides: int = 0
    contacts: int = 0


@dataclass
class Candidat:
    entreprise: CandidatEntreprise
    score: Score
    deja: str | None


class ServiceProspection:
    def __init__(
        self,
        db: Database,
        *,
        config: ConfigProspection | None = None,
        horloge: Callable[[], datetime] = maintenant,
        identite: gabarits.IdentiteExpediteur | None = None,
        secrets_jetons: list[bytes] | None = None,
        url_publique: str | None = None,
    ) -> None:
        self.db = db
        self._config = config
        self.horloge = horloge
        self._identite = identite
        self._secrets = secrets_jetons
        self.url_publique = url_publique.rstrip("/") if url_publique else None

    # --- dépendances ----------------------------------------------------------------------------------------
    @property
    def config(self) -> ConfigProspection:
        if self._config is None:
            self._config = charger_config()
        return self._config

    @property
    def identite(self) -> gabarits.IdentiteExpediteur:
        if self._identite is None:
            self._identite = identite_par_defaut(self.config)
        return self._identite

    def secrets_jetons(self) -> list[bytes]:
        if self._secrets is None:
            from controldone.prospection.jetons import secrets_depuis_env

            self._secrets = secrets_depuis_env()
        return self._secrets

    def lien_desinscription(self, adresse: str) -> str | None:
        if not self.url_publique:
            return None
        from controldone.prospection.jetons import emettre

        return f"{self.url_publique}/desinscription/{emettre(adr.empreinte(adresse), self.secrets_jetons())}"

    # --- droits et journal ------------------------------------------------------------------------------------
    @staticmethod
    def _fondateur(acteur: Acteur) -> None:
        if Role(acteur.role) is not Role.fondateur:
            raise AccesRefuse("introuvable ou hors périmètre")

    @staticmethod
    def _fondateur_ou_systeme(acteur: Acteur) -> None:
        if Role(acteur.role) not in (Role.fondateur, Role.systeme):
            raise AccesRefuse("introuvable ou hors périmètre")

    @staticmethod
    def _audit(s: Any, acteur: Acteur, action: str, cible: str | None, **details: Any) -> None:
        journaliser(
            s,
            actor=acteur.id,
            role=Role(acteur.role).value,
            action=f"prospection_{action}",
            target=cible,
            ip=acteur.ip,
            details=details,
        )

    def _evenement(self, s: Any, prospect_id: str, kind: str, auteur: str, **champs: Any) -> None:
        stock.ajouter_evenement(
            s, prospect_id=prospect_id, kind=kind, auteur=auteur, le=self.horloge(), **champs
        )

    @staticmethod
    def _lire(s: Any, prospect_id: str, *, verrou: bool = False) -> Any:
        p = stock.lire_prospect(s, prospect_id, verrou=verrou)
        if p is None:
            raise AccesRefuse("introuvable ou hors périmètre")
        return p

    # --- score et exclusion -----------------------------------------------------------------------------------
    def score(self, p: Any, natures: Iterable[str]) -> Score:
        return calculer_score(
            FaitsScore(
                naf=p.naf,
                tranche_effectif=p.tranche_effectif,
                preuve_import=p.preuve_import,
                preuve_url=p.preuve_url,
                sans_service_douane=p.sans_service_douane,
                natures_contacts=tuple(natures),
                departement=p.departement,
            ),
            self.config,
        )

    def _rescorer(self, s: Any, p: Any) -> None:
        sc = self.score(p, [c.nature for c in stock.contacts(s, p.id)])
        p.score, p.score_detail = sc.total, sc.detail()

    def _exclusion(self, p: Any, adresses: Iterable[str | None] = ()) -> Any:
        return chercher_exclusion(
            textes_a_verifier(
                raison_sociale=p.raison_sociale, groupe=p.groupe, site_web=p.site_web, adresses=adresses
            ),
            self.config,
        )

    # --- création ---------------------------------------------------------------------------------------------
    def _existant(self, s: Any) -> Callable[[str | None, str], str | None]:
        def f(siren: str | None, nom: str) -> str | None:
            if siren and (p := stock.prospect_par_siren(s, siren)) is not None:
                return p.id
            p = stock.prospect_par_nom(s, nom)
            return p.id if p is not None else None

        return f

    def _inserer(
        self,
        s: Any,
        acteur: Acteur,
        champs: dict[str, Any],
        contacts: list[dict[str, Any]],
        source: str,
        **ev: Any,
    ) -> Any:
        p = stock.inserer_prospect(
            s,
            id=nouvel_id("prs"),
            nom_normalise=normaliser_nom(champs["raison_sociale"]),
            source=source,
            statut="a_qualifier",
            **champs,
        )
        for c in contacts:
            self._contact(s, acteur, p, **c)
        self._rescorer(s, p)
        self._evenement(s, p.id, "creation", acteur.id, vers="a_qualifier", details={"source": source, **ev})
        return p

    def _contact(
        self,
        s: Any,
        acteur: Acteur,
        p: Any,
        *,
        source_url: str,
        adresse: str | None = None,
        url_formulaire: str | None = None,
        personne: str | None = None,
        origine: str = "fondateur",
    ) -> Any:
        if not adr.url_valide(source_url):
            raise RefusProspection("Page source du contact obligatoire (adresse https://…).")
        if adresse:
            if not adr.adresse_valide(adresse):
                raise RefusProspection("Adresse électronique invalide.")
            a = adr.normaliser_adresse(adresse)
            if any(c.adresse == a for c in stock.contacts(s, p.id)):
                raise RefusProspection("Cette adresse est déjà enregistrée pour ce prospect.")
            if self._exclusion(p, [a]) is not None:
                raise RefusProspection("Liste d'exclusion : ce contact ne peut pas être enregistré.")
            return stock.ajouter_contact(
                s,
                id=nouvel_id("pct"),
                prospect_id=p.id,
                genre="courriel",
                adresse=a,
                nature=adr.nature_adresse(a),
                empreinte=adr.empreinte(a),
                source_url=source_url,
                personne=(personne or "").strip()[:200] or None,
                origine=origine,
                cree_par=acteur.id,
                cree_le=self.horloge(),
            )
        if not adr.url_valide(url_formulaire):
            raise RefusProspection("Adresse électronique ou page de formulaire obligatoire.")
        return stock.ajouter_contact(
            s,
            id=nouvel_id("pct"),
            prospect_id=p.id,
            genre="formulaire",
            nature="formulaire",
            url_formulaire=url_formulaire,
            source_url=source_url,
            personne=(personne or "").strip()[:200] or None,
            origine=origine,
            cree_par=acteur.id,
            cree_le=self.horloge(),
        )

    def creer(self, acteur: Acteur, champs: dict[str, Any], contact: dict[str, Any] | None = None) -> str:
        """Saisie du fondateur : raison sociale et page source obligatoires ; exclusion et doublons refusés."""
        self._fondateur(acteur)
        rs = " ".join((champs.get("raison_sociale") or "").split())[:300]
        if not rs:
            raise RefusProspection("Raison sociale obligatoire.")
        siren = (champs.get("siren") or "").replace(" ", "") or None
        if siren and not siren_valide(siren):
            raise RefusProspection("SIREN invalide (9 chiffres, clé de contrôle).")
        source_url = (champs.get("source_url") or "").strip()
        if not adr.url_valide(source_url):
            raise RefusProspection("Page source obligatoire (adresse https://…).")
        pays = (champs.get("pays") or "FR").strip().upper()[:2] or "FR"
        if pays in self.config.pays_bloques:
            raise RefusProspection("Pays sans prospection autorisée (avis d'un avocat local attendu).")
        preuve_url = (champs.get("preuve_url") or "").strip() or None
        if preuve_url and not adr.url_valide(preuve_url):
            raise RefusProspection("Page de la preuve d'import invalide (adresse https://…).")
        site = (champs.get("site_web") or "").strip() or None
        if site and not adr.url_valide(site):
            raise RefusProspection("Site web invalide (adresse https://…).")
        donnees = {
            "raison_sociale": rs,
            "siren": siren,
            "naf": (champs.get("naf") or "").strip().upper()[:10] or None,
            "tranche_effectif": champs.get("tranche_effectif") or None,
            "effectif_libelle": LIBELLES_TRANCHE.get(champs.get("tranche_effectif") or ""),
            "pays": pays,
            "departement": (champs.get("departement") or "").strip()[:3] or None,
            "ville": (champs.get("ville") or "").strip()[:200] or None,
            "site_web": site,
            "groupe": (champs.get("groupe") or "").strip()[:300] or None,
            "preuve_import": (champs.get("preuve_import") or "").strip()[:2000] or None,
            "preuve_url": preuve_url,
            "sans_service_douane": champs.get("sans_service_douane") or "inconnu",
            "raison_ciblage": (champs.get("raison_ciblage") or "").strip()[:2000] or None,
            "source_url": source_url,
            "source_detail": (champs.get("source_detail") or "").strip()[:300] or None,
            "collecte_le": champs.get("collecte_le") or aujourdhui_paris(self.horloge()),
            "demo": bool(champs.get("demo")),
        }
        if donnees["sans_service_douane"] not in ("oui", "non", "inconnu"):
            donnees["sans_service_douane"] = "inconnu"
        if donnees["tranche_effectif"] not in LIBELLES_TRANCHE:
            donnees["tranche_effectif"] = None
        adresses = [contact.get("adresse")] if contact else []
        with self.db.transaction_systeme() as s:
            if self._exclusion(_Faits(**donnees), adresses) is not None:
                raise RefusProspection("Liste d'exclusion : ce prospect ne peut pas être enregistré.")
            deja = self._existant(s)(siren, normaliser_nom(rs))
            if deja:
                raise RefusProspection("Ce prospect existe déjà (même SIREN ou même nom).")
            source = champs.get("source") or "saisie"
            p = self._inserer(s, acteur, donnees, [contact] if contact else [], source)
            self._audit(s, acteur, "creer", f"prospect:{p.id}", source=source)
            return p.id

    # --- import CSV -------------------------------------------------------------------------------------------
    def analyser_import(self, acteur: Acteur, contenu: bytes) -> list[LigneImport]:
        self._fondateur(acteur)
        with self.db.transaction_systeme() as s:
            try:
                return analyser_csv(
                    contenu,
                    self.config,
                    existant=self._existant(s),
                    aujourdhui=aujourdhui_paris(self.horloge()),
                )
            except ValueError as exc:
                raise RefusProspection(REFUS_CSV.get(str(exc), REFUS_CSV["illisible"])) from None

    def importer(self, acteur: Acteur, contenu: bytes, nom_fichier: str) -> RapportImport:
        """Importe les lignes ``nouveau`` (analyse refaite au moment de l'import : doublons et exclusion revus)."""
        self._fondateur(acteur)
        r = RapportImport()
        nom = (nom_fichier or "import.csv")[:200]
        with self.db.transaction_systeme() as s:
            try:
                lignes = analyser_csv(
                    contenu,
                    self.config,
                    existant=self._existant(s),
                    aujourdhui=aujourdhui_paris(self.horloge()),
                )
            except ValueError as exc:
                raise RefusProspection(REFUS_CSV.get(str(exc), REFUS_CSV["illisible"])) from None
            for ligne in lignes:
                if ligne.statut == "doublon":
                    r.doublons += 1
                elif ligne.statut == "exclu":
                    r.exclus += 1
                elif ligne.statut != "nouveau":
                    r.invalides += 1
                if ligne.statut != "nouveau":
                    continue
                champs = dict(ligne.champs)
                champs["source_detail"] = f"{nom}, ligne {ligne.numero}"
                contacts = [
                    {
                        "source_url": c.source_url,
                        "adresse": c.adresse,
                        "url_formulaire": c.url_formulaire,
                        "origine": "import",
                    }
                    for c in ligne.contacts
                ]
                self._inserer(s, acteur, champs, contacts, "import_csv", fichier=nom, ligne=ligne.numero)
                r.crees += 1
                r.contacts += len(contacts)
            self._audit(
                s,
                acteur,
                "importer",
                "prospects",
                fichier=nom,
                crees=r.crees,
                doublons=r.doublons,
                exclus=r.exclus,
                invalides=r.invalides,
            )
        return r

    # --- recherche d'entreprises ---------------------------------------------------------------------------
    def rechercher(
        self, acteur: Acteur, source: SourceEntreprises, criteres: CriteresRecherche
    ) -> tuple[list[Candidat], int, ResultatRecherche]:
        """Candidats (exclus retirés, comptés à part), avec leur score indicatif et le prospect existant."""
        self._fondateur(acteur)
        res = source.rechercher(criteres)
        visibles: list[Candidat] = []
        exclus = 0
        with self.db.transaction_systeme() as s:
            existant = self._existant(s)
            for c in res.candidats:
                if self._exclusion_candidat(c) is not None:
                    exclus += 1
                    continue
                sc = calculer_score(
                    FaitsScore(naf=c.naf, tranche_effectif=c.tranche_effectif, departement=c.departement),
                    self.config,
                )
                visibles.append(Candidat(c, sc, existant(c.siren, normaliser_nom(c.raison_sociale))))
        visibles.sort(key=lambda x: (-x.score.total, x.entreprise.raison_sociale))
        return visibles, exclus, res

    def _exclusion_candidat(self, c: CandidatEntreprise) -> Any:
        return chercher_exclusion(
            textes_a_verifier(
                raison_sociale=c.raison_sociale,
                enseignes=c.enseignes,
                dirigeants=c.dirigeants_personnes_morales,
            ),
            self.config,
        )

    def ajouter_candidat(self, acteur: Acteur, source: SourceEntreprises, siren: str) -> str:
        """Ajoute un candidat choisi par le fondateur : relu dans l'API par son SIREN (les données viennent de la
        source, pas du formulaire), exclusion revérifiée, statut « à qualifier »."""
        self._fondateur(acteur)
        if not siren_valide(siren):
            raise RefusProspection("SIREN invalide (9 chiffres, clé de contrôle).")
        res = source.rechercher(CriteresRecherche(mots=siren))
        c = next((x for x in res.candidats if x.siren == siren), None)
        if c is None:
            raise RefusProspection("Entreprise introuvable dans la source publique.")
        if self._exclusion_candidat(c) is not None:
            raise RefusProspection("Liste d'exclusion : ce prospect ne peut pas être enregistré.")
        annee = f" ({c.annee_effectif})" if c.annee_effectif else ""
        return self.creer(
            acteur,
            {
                "raison_sociale": c.raison_sociale,
                "siren": c.siren,
                "naf": c.naf,
                "tranche_effectif": c.tranche_effectif,
                "departement": c.departement,
                "ville": c.ville,
                "source_url": url_annuaire(c.siren),
                "source_detail": f"{API_RECHERCHE}?q={c.siren}{annee}",
                "source": "recherche",
            },
        )

    # --- lecture ---------------------------------------------------------------------------------------------
    def liste(self, acteur: Acteur) -> list[dict[str, Any]]:
        self._fondateur(acteur)
        with self.db.transaction_systeme() as s:
            prospects = stock.lister_prospects(s)
            contacts: dict[str, list[Any]] = defaultdict(list)
            for c in stock.tous_contacts(s):
                contacts[c.prospect_id].append(c)
            actives = {i.prospect_id for i in stock.inscriptions(s, statut="active")}
        return [
            {
                "p": p,
                "contacts": len(contacts[p.id]),
                "courriels": sum(1 for c in contacts[p.id] if c.genre == "courriel"),
                "sequence": p.id in actives,
                "exclu": self._exclusion(p, [c.adresse for c in contacts[p.id]]) is not None,
            }
            for p in prospects
        ]

    def _blocages_contact(self, s: Any, p: Any, c: Any) -> list[str]:
        out = []
        if self._exclusion(p, [c.adresse]) is not None:
            out.append("exclusion")
        if p.pays in self.config.pays_bloques:
            out.append("pays_bloque")
        if c.genre != "courriel" or not c.adresse:
            out.append("formulaire")
            return out
        if stock.suppression(s, c.empreinte or adr.empreinte(c.adresse)) is not None:
            out.append("opposition")
        if (
            c.nature == "nominative"
            and p.pays in self.config.pays_consentement_nominatif
            and not (p.base_legale or "").strip()
        ):
            out.append("consentement")
        if p.statut not in STATUTS_ACTIFS_SEQUENCE:
            out.append("statut")
        return out

    def _faits(self, p: Any) -> dict[str, str | None]:
        return {
            "raison_sociale": p.raison_sociale,
            "accroche": gabarits.accroche_depuis_preuve(p.preuve_import, p.preuve_url),
            "ville": p.ville,
        }

    def rendu(self, p: Any, c: Any | None, etape: dict[str, Any]) -> gabarits.Rendu:
        return gabarits.rendre(
            etape,
            self._faits(p),
            self.identite,
            source_adresse=_source_lisible(c.source_url) if c is not None else None,
            lien_desinscription=self.lien_desinscription(c.adresse) if c is not None and c.adresse else None,
        )

    def fiche(self, acteur: Acteur, prospect_id: str) -> dict[str, Any]:
        self._fondateur(acteur)
        self.sequences(acteur)
        fs = FileSortante(self.db)
        with self.db.transaction_systeme() as s:
            p = self._lire(s, prospect_id)
            cs = stock.contacts(s, p.id)
            vues = [
                VueContact(
                    id=c.id,
                    genre=c.genre,
                    adresse=c.adresse,
                    nature=c.nature,
                    url_formulaire=c.url_formulaire,
                    source_url=c.source_url,
                    personne=c.personne,
                    origine=c.origine,
                    oppose=bool(c.empreinte and stock.suppression(s, c.empreinte) is not None),
                    blocages=self._blocages_contact(s, p, c),
                )
                for c in cs
            ]
            evts = stock.evenements(s, p.id)
            seqs = {q.id: q for q in stock.sequences(s)}
            inscr = stock.inscriptions(s, prospect_id=p.id)
        vues_inscr = [self._vue_inscription(i, seqs.get(i.sequence_id), fs, acteur) for i in inscr]
        seq_defaut = next(iter(seqs.values()), None)
        contact_courriel = next((c for c in cs if c.genre == "courriel"), None)
        apercu = (
            self.rendu(p, contact_courriel, seq_defaut.etapes[0])
            if seq_defaut is not None and seq_defaut.etapes
            else None
        )
        return {
            "p": p,
            "contacts": vues,
            "evenements": list(reversed(evts)),
            "inscriptions": list(reversed(vues_inscr)),
            "sequences": list(seqs.values()),
            "apercu": apercu,
            "exclu": self._exclusion(p, [c.adresse for c in cs]) is not None,
            "active": next((v for v in vues_inscr if v.statut == "active"), None),
        }

    def _vue_inscription(self, i: Any, seq: Any, fs: FileSortante, acteur: Acteur) -> VueInscription:
        etapes = []
        for e in i.etapes or []:
            v = VueEtape(rang=int(e["rang"]), outbox_id=e["outbox_id"], prepare_le=e.get("prepare_le", ""))
            try:
                a = fs.obtenir(e["outbox_id"], acteur)
                v.statut, v.envoye_le, v.reference = a.statut.value, a.envoye_le, a.reference_envoi
            except AccesRefuse:
                v.statut = None
            etapes.append(v)
        vue = VueInscription(
            id=i.id,
            sequence_id=i.sequence_id,
            sequence_nom=seq.nom if seq is not None else i.sequence_id,
            contact_id=i.contact_id,
            statut=i.statut,
            motif_arret=i.motif_arret,
            demarree_le=i.demarree_le,
            etapes=etapes,
            total_etapes=len(seq.etapes) if seq is not None else len(etapes),
        )
        if i.statut == "active" and seq is not None:
            vue.prochaine = self._prochaine(seq, etapes)
        return vue

    @staticmethod
    def _prochaine(seq: Any, etapes: list[VueEtape]) -> dict[str, Any] | None:
        """Prochaine étape et sa date : J+délai depuis l'envoi de l'étape 1, et au moins un jour après l'envoi de
        l'étape précédente. ``None`` : attente d'une décision (brouillon non envoyé) ou séquence finie."""
        if not etapes:
            return None
        derniere = etapes[-1]
        suivante = next((e for e in seq.etapes if int(e["rang"]) == derniere.rang + 1), None)
        if suivante is None:
            return {"fin": True}
        if derniere.statut != StatutAction.envoye.value or derniere.envoye_le is None:
            return {"attente": derniere.statut or "inconnu", "rang": derniere.rang + 1}
        premiere = etapes[0]
        if premiere.envoye_le is None:  # pragma: no cover - l'étape 1 est envoyée avant toute autre
            return None
        due = max(
            premiere.envoye_le + timedelta(days=int(suivante["delai_jours"])),
            derniere.envoye_le + timedelta(days=1),
        )
        return {"rang": derniere.rang + 1, "due": due, "etape": suivante}

    # --- modifications -----------------------------------------------------------------------------------------
    def modifier(self, acteur: Acteur, prospect_id: str, champs: dict[str, Any]) -> None:
        """Faits du prospect (preuve, signaux, base légale…) ; score recalculé ; un prospect devenu exclu passe en
        « ne plus contacter » et ses séquences s'arrêtent."""
        self._fondateur(acteur)
        with self.db.transaction_systeme() as s:
            p = self._lire(s, prospect_id, verrou=True)
            modifies = []
            for cle in ("preuve_import", "raison_ciblage", "base_legale", "groupe", "ville"):
                if cle in champs:
                    v = (champs[cle] or "").strip()[:2000] or None
                    if v != getattr(p, cle):
                        setattr(p, cle, v)
                        modifies.append(cle)
            for cle in ("preuve_url", "site_web"):
                if cle in champs:
                    v = (champs[cle] or "").strip() or None
                    if v and not adr.url_valide(v):
                        raise RefusProspection("Adresse de page invalide (https://…).")
                    if v != getattr(p, cle):
                        setattr(p, cle, v)
                        modifies.append(cle)
            douane = champs.get("sans_service_douane")
            if douane in ("oui", "non", "inconnu") and douane != p.sans_service_douane:
                p.sans_service_douane = douane
                modifies.append("sans_service_douane")
            if "naf" in champs:
                naf = (champs["naf"] or "").strip().upper()[:10] or None
                if naf != p.naf:
                    p.naf = naf
                    modifies.append("naf")
            if "tranche_effectif" in champs and (champs["tranche_effectif"] or None) != p.tranche_effectif:
                t = champs["tranche_effectif"] or None
                if t is not None and t not in LIBELLES_TRANCHE:
                    raise RefusProspection("Tranche d'effectif inconnue.")
                p.tranche_effectif, p.effectif_libelle = t, LIBELLES_TRANCHE.get(t or "")
                modifies.append("tranche_effectif")
            if "departement" in champs:
                d = (champs["departement"] or "").strip()[:3] or None
                if d != p.departement:
                    p.departement = d
                    modifies.append("departement")
            if "pays" in champs:
                pays = (champs["pays"] or "FR").strip().upper()[:2]
                if len(pays) != 2 or not pays.isalpha():
                    raise RefusProspection("Pays : code à deux lettres (FR, CH, BE…).")
                if pays != p.pays:
                    p.pays = pays
                    modifies.append("pays")
            if not modifies:
                return
            self._rescorer(s, p)
            self._evenement(s, p.id, "modification", acteur.id, details={"champs": modifies})
            self._audit(s, acteur, "modifier", f"prospect:{p.id}", champs=modifies)
            if self._exclusion(p, [c.adresse for c in stock.contacts(s, p.id)]) is not None:
                self._changer_statut(s, acteur, p, "ne_plus_contacter", motif_arret="exclusion")

    def _changer_statut(
        self,
        s: Any,
        acteur: Acteur,
        p: Any,
        vers: str,
        *,
        motif_arret: str = "statut",
        texte: str | None = None,
    ) -> bool:
        if vers not in STATUTS:
            raise RefusProspection("Statut inconnu.")
        de = p.statut
        if de == vers:
            return False
        p.statut = vers
        self._evenement(s, p.id, "statut", acteur.id, de=de, vers=vers, texte=texte)
        self._audit(s, acteur, "statut", f"prospect:{p.id}", de=de, vers=vers)
        if vers not in STATUTS_ACTIFS_SEQUENCE:
            self._arreter(s, acteur, p.id, motif_arret)
        if vers == "ne_plus_contacter":
            for c in stock.contacts(s, p.id):
                if c.empreinte:
                    self._opposer(s, acteur, c.empreinte, "ne_plus_contacter", "statut « ne plus contacter »")
        return True

    def _arreter(self, s: Any, acteur: Acteur, prospect_id: str, motif: str) -> int:
        n = 0
        for i in stock.inscriptions(s, prospect_id=prospect_id, statut="active"):
            i.statut, i.motif_arret, i.arretee_le = "arretee", motif, self.horloge()
            self._evenement(
                s, prospect_id, "sequence_arret", acteur.id, details={"inscription": i.id, "motif": motif}
            )
            n += 1
        return n

    def _opposer(self, s: Any, acteur: Acteur, empreinte: str, motif: str, source: str) -> bool:
        _ligne, cree = stock.ajouter_suppression(
            s,
            empreinte=empreinte,
            motif=motif,
            source=source[:200],
            cree_par=acteur.id,
            cree_le=self.horloge(),
        )
        if cree:
            self._audit(s, acteur, "opposition", "suppression", motif=motif)
        return cree

    def changer_statut(self, acteur: Acteur, prospect_id: str, vers: str) -> bool:
        self._fondateur(acteur)
        with self.db.transaction_systeme() as s:
            p = self._lire(s, prospect_id, verrou=True)
            if (
                vers in ("qualifie", "contacte")
                and self._exclusion(p, [c.adresse for c in stock.contacts(s, p.id)]) is not None
            ):
                raise RefusProspection("Liste d'exclusion : aucun courriel possible.")
            return self._changer_statut(s, acteur, p, vers)

    def ajouter_note(self, acteur: Acteur, prospect_id: str, texte: str) -> None:
        self._fondateur(acteur)
        texte = (texte or "").strip()[:5000]
        if not texte:
            raise RefusProspection("Note vide.")
        with self.db.transaction_systeme() as s:
            p = self._lire(s, prospect_id)
            self._evenement(s, p.id, "note", acteur.id, texte=texte)

    def ajouter_contact(self, acteur: Acteur, prospect_id: str, **champs: Any) -> str:
        self._fondateur(acteur)
        with self.db.transaction_systeme() as s:
            p = self._lire(s, prospect_id, verrou=True)
            c = self._contact(s, acteur, p, origine="fondateur", **champs)
            self._rescorer(s, p)
            self._evenement(s, p.id, "contact", acteur.id, details={"contact": c.id, "nature": c.nature})
            self._audit(s, acteur, "contact", f"prospect:{p.id}", nature=c.nature)
            return c.id

    def enregistrer_reponse(self, acteur: Acteur, prospect_id: str, texte: str | None) -> None:
        """Réponse reçue (saisie par le fondateur) : texte conservé tel quel comme **donnée** ; séquence arrêtée,
        statut « a répondu » (s'il est en amont), dernier contact émanant du prospect mis à jour."""
        self._fondateur(acteur)
        with self.db.transaction_systeme() as s:
            p = self._lire(s, prospect_id, verrou=True)
            self._evenement(s, p.id, "reponse", acteur.id, texte=(texte or "").strip()[:10000] or None)
            p.derniere_interaction_le = self.horloge()
            self._arreter(s, acteur, p.id, "reponse")
            if rang_statut(p.statut) < rang_statut("a_repondu"):
                self._changer_statut(s, acteur, p, "a_repondu", motif_arret="reponse")
            self._audit(s, acteur, "reponse", f"prospect:{p.id}")

    def enregistrer_rendez_vous(
        self, acteur: Acteur, prospect_id: str, quand: date | None, texte: str | None
    ) -> None:
        self._fondateur(acteur)
        with self.db.transaction_systeme() as s:
            p = self._lire(s, prospect_id, verrou=True)
            self._evenement(
                s,
                p.id,
                "rendez_vous",
                acteur.id,
                texte=(texte or "").strip()[:2000] or None,
                details={"date": quand.isoformat() if quand else None},
            )
            p.derniere_interaction_le = self.horloge()
            self._arreter(s, acteur, p.id, "reponse")
            if rang_statut(p.statut) < rang_statut("rendez_vous") or p.statut == "a_repondu":
                self._changer_statut(s, acteur, p, "rendez_vous", motif_arret="reponse")
            self._audit(s, acteur, "rendez_vous", f"prospect:{p.id}")

    def enregistrer_rebond(self, acteur: Acteur, contact_id: str) -> None:
        """Adresse en échec (rebond définitif) : liste d'opposition, séquences de ce contact arrêtées."""
        self._fondateur(acteur)
        with self.db.transaction_systeme() as s:
            c = stock.contact(s, contact_id)
            if c is None or not c.empreinte:
                raise AccesRefuse("introuvable ou hors périmètre")
            self._opposer(s, acteur, c.empreinte, "rebond", "rebond déclaré par le fondateur")
            for i in stock.inscriptions(s, prospect_id=c.prospect_id, statut="active"):
                if i.contact_id == c.id:
                    i.statut, i.motif_arret, i.arretee_le = "arretee", "rebond", self.horloge()
            self._evenement(s, c.prospect_id, "rebond", acteur.id, details={"contact": c.id})

    def opposer_contact(self, acteur: Acteur, contact_id: str, motif: str = "desinscription") -> None:
        """Opposition reçue (« STOP ») pour un contact : liste d'opposition, prospect « ne plus contacter »."""
        self._fondateur(acteur)
        if motif not in ("desinscription", "plainte", "ne_plus_contacter"):
            raise RefusProspection("Motif inconnu.")
        with self.db.transaction_systeme() as s:
            c = stock.contact(s, contact_id)
            if c is None or not c.empreinte:
                raise AccesRefuse("introuvable ou hors périmètre")
            p = self._lire(s, c.prospect_id, verrou=True)
            self._opposer(s, acteur, c.empreinte, motif, "opposition enregistrée par le fondateur")
            self._evenement(s, p.id, "desinscription", acteur.id, details={"contact": c.id, "motif": motif})
            self._changer_statut(s, acteur, p, "ne_plus_contacter", motif_arret="desinscription")
            self._arreter(s, acteur, p.id, "desinscription")

    def ajouter_opposition(self, acteur: Acteur, adresse: str, motif: str) -> bool:
        """Opposition saisie hors fiche (adresse reçue par un autre canal) : seule l'empreinte est conservée."""
        self._fondateur(acteur)
        if not adr.adresse_valide(adresse):
            raise RefusProspection("Adresse électronique invalide.")
        if motif not in ("desinscription", "rebond", "ne_plus_contacter", "plainte"):
            raise RefusProspection("Motif inconnu.")
        emp = adr.empreinte(adresse)
        with self.db.transaction_systeme() as s:
            cree = self._opposer(s, acteur, emp, motif, "saisie du fondateur")
            for c in stock.contacts_par_empreinte(s, emp):
                self._evenement(
                    s, c.prospect_id, "desinscription", acteur.id, details={"contact": c.id, "motif": motif}
                )
                for i in stock.inscriptions(s, prospect_id=c.prospect_id, statut="active"):
                    if i.contact_id == c.id:
                        i.statut, i.motif_arret, i.arretee_le = "arretee", "opposition", self.horloge()
            return cree

    def desinscrire_par_jeton(self, jeton: str) -> bool:
        """Lien de désinscription (public, sans compte) : ``JetonInvalide`` si la signature est fausse. Idempotent ;
        vrai si l'adresse vient d'entrer dans la liste d'opposition."""
        from controldone.prospection.jetons import verifier

        emp = verifier(jeton, self.secrets_jetons())
        systeme = Acteur.systeme("desinscription")
        with self.db.transaction_systeme() as s:
            cree = self._opposer(s, systeme, emp, "desinscription", "lien de désinscription")
            for c in stock.contacts_par_empreinte(s, emp):
                p = stock.lire_prospect(s, c.prospect_id, verrou=True)
                if p is None:  # pragma: no cover - contact sans prospect (clé étrangère)
                    continue
                if cree or p.statut != "ne_plus_contacter":
                    self._evenement(
                        s, p.id, "desinscription", systeme.id, details={"contact": c.id, "lien": True}
                    )
                    self._changer_statut(s, systeme, p, "ne_plus_contacter", motif_arret="desinscription")
                    self._arreter(s, systeme, p.id, "desinscription")
            return cree

    # --- séquences --------------------------------------------------------------------------------------------
    def sequences(self, acteur: Acteur) -> list[Any]:
        """Séquences ; la séquence par défaut est créée au premier accès (une seule fois)."""
        self._fondateur_ou_systeme(acteur)
        with self.db.transaction_systeme() as s:
            seqs = stock.sequences(s)
            if not seqs:
                d = gabarits.SEQUENCE_DEFAUT
                stock.inserer_sequence(
                    s,
                    id=d["id"],
                    nom=d["nom"],
                    actif=True,
                    etapes=[dict(e) for e in d["etapes"]],
                    modifie_par="systeme:prospection",
                    modifie_le=self.horloge(),
                )
                seqs = stock.sequences(s)
            return seqs

    def modifier_sequence(
        self, acteur: Acteur, sequence_id: str, nom: str, etapes: list[dict[str, Any]]
    ) -> None:
        self._fondateur(acteur)
        nom = " ".join((nom or "").split())[:200]
        if not nom:
            raise RefusProspection("Nom de la séquence obligatoire.")
        erreurs = gabarits.valider_etapes(etapes)
        if erreurs:
            raise RefusProspection(erreurs[0][0], **erreurs[0][1])
        with self.db.transaction_systeme() as s:
            q = stock.sequence(s, sequence_id, verrou=True)
            if q is None:
                raise AccesRefuse("introuvable ou hors périmètre")
            q.nom, q.etapes, q.modifie_par, q.modifie_le = nom, etapes, acteur.id, self.horloge()
            self._audit(s, acteur, "sequence", f"sequence:{q.id}", etapes=len(etapes))

    def _plafond(self, s: Any, kinds: tuple[str, ...], maximum: int) -> bool:
        debut, fin = _jour(self.horloge())
        return stock.compter_evenements(s, kinds, debut, fin) >= maximum

    def compteurs_du_jour(self) -> dict[str, int]:
        debut, fin = _jour(self.horloge())
        with self.db.transaction_systeme() as s:
            return {
                "preparations": stock.compter_evenements(s, ("preparation",), debut, fin),
                "envois": stock.compter_evenements(s, ("envoi", "declaration_envoi"), debut, fin),
                "plafond_preparations": self.config.preparations_par_jour,
                "plafond_envois": self.config.envois_par_jour,
            }

    def preparer_sequence(self, acteur: Acteur, prospect_id: str, contact_id: str, sequence_id: str) -> str:
        """« Préparer la séquence » : inscrit le prospect et met l'étape 1 en brouillon dans la file de validation.
        Refusé (``RefusProspection``) si un blocage existe, si un fait manque ou si le plafond est atteint."""
        self._fondateur(acteur)
        seqs = {q.id: q for q in self.sequences(acteur)}
        seq = seqs.get(sequence_id)
        if seq is None or not seq.etapes or not seq.actif:
            raise RefusProspection("Séquence introuvable ou inactive.")
        with self.db.transaction_systeme() as s:
            p = self._lire(s, prospect_id, verrou=True)
            c = stock.contact(s, contact_id)
            if c is None or c.prospect_id != p.id:
                raise RefusProspection(BLOCAGES["contact_absent"])
            if p.statut != "qualifie":
                raise RefusProspection("Qualifiez d'abord le prospect (statut « qualifié »).")
            blocages = self._blocages_contact(s, p, c)
            if blocages:
                raise RefusProspection(BLOCAGES[blocages[0]])
            if stock.inscriptions(s, prospect_id=p.id, statut="active"):
                raise RefusProspection("Une séquence est déjà en cours pour ce prospect.")
            rendu = self.rendu(p, c, seq.etapes[0])
            if rendu.manquants:
                raise RefusProspection("Faits manquants : {faits}.", faits=", ".join(rendu.manquants))
            if self._plafond(s, ("preparation",), self.config.preparations_par_jour):
                raise RefusProspection(BLOCAGES["plafond"])
            i = stock.inserer_inscription(
                s,
                id=nouvel_id("pin"),
                prospect_id=p.id,
                contact_id=c.id,
                sequence_id=seq.id,
                statut="active",
                etapes=[],
                demarree_le=self.horloge(),
            )
            inscription_id, adresse = i.id, c.adresse
            payload = self._payload(p, c, i.id, seq.id, 1, rendu)
        try:
            action = FileSortante(self.db).proposer(
                KIND, payload, acteur, idempotency_key=f"prospection:{inscription_id}:1"
            )
        except BaseException:
            with self.db.transaction_systeme() as s:
                i = stock.inscription(s, inscription_id, verrou=True)
                if i is not None and not i.etapes:
                    i.statut, i.motif_arret, i.arretee_le = "arretee", "fondateur", self.horloge()
            raise
        self._enregistrer_preparation(acteur, inscription_id, 1, action, adresse)
        return action.id

    def _payload(
        self, p: Any, c: Any, inscription_id: str, sequence_id: str, rang: int, r: gabarits.Rendu
    ) -> dict[str, Any]:
        return {
            "objet": r.objet,
            "corps": r.corps,
            "destinataires": [c.adresse],
            "prospect_id": p.id,
            "contact_id": c.id,
            "inscription_id": inscription_id,
            "sequence_id": sequence_id,
            "rang": rang,
            "lien_desinscription": self.lien_desinscription(c.adresse),
        }

    def _enregistrer_preparation(
        self, acteur: Acteur, inscription_id: str, rang: int, action: ActionSortante, _adresse: str | None
    ) -> None:
        with self.db.transaction_systeme() as s:
            i = stock.inscription(s, inscription_id, verrou=True)
            if i is None or any(int(e["rang"]) == rang for e in i.etapes or []):
                return
            i.etapes = [
                *(i.etapes or []),
                {"rang": rang, "outbox_id": action.id, "prepare_le": self.horloge().isoformat()},
            ]
            self._evenement(
                s,
                i.prospect_id,
                "preparation",
                acteur.id,
                details={"outbox": action.id, "rang": rang, "inscription": i.id},
            )
            self._audit(s, acteur, "preparer", f"outbox:{action.id}", prospect=i.prospect_id, rang=rang)

    def arreter_sequence(self, acteur: Acteur, inscription_id: str) -> None:
        self._fondateur(acteur)
        with self.db.transaction_systeme() as s:
            i = stock.inscription(s, inscription_id, verrou=True)
            if i is None:
                raise AccesRefuse("introuvable ou hors périmètre")
            if i.statut == "active":
                i.statut, i.motif_arret, i.arretee_le = "arretee", "fondateur", self.horloge()
                self._evenement(
                    s,
                    i.prospect_id,
                    "sequence_arret",
                    acteur.id,
                    details={"inscription": i.id, "motif": "fondateur"},
                )
                self._audit(s, acteur, "arreter", f"inscription:{i.id}")

    def preparer_etapes_dues(self, acteur: Acteur) -> list[str]:
        """Étapes suivantes échues (agent quotidien ou bouton du fondateur) : brouillons seulement, dans la file de
        validation ; arrêt des séquences dont un motif d'arrêt est apparu ; plafond quotidien respecté. Les
        lectures de la file et les écritures se font dans des transactions séparées (jamais imbriquées)."""
        self._fondateur_ou_systeme(acteur)
        seqs = {q.id: q for q in self.sequences(acteur)}
        fs = FileSortante(self.db)
        lecteur = acteur if Role(acteur.role) is Role.fondateur else Acteur.systeme("prospection")
        prepares: list[str] = []
        with self.db.transaction_systeme() as s:
            ids = [i.id for i in stock.inscriptions(s, statut="active")]
        for inscription_id in ids:
            # 1. lecture et motifs d'arrêt propres au prospect
            with self.db.transaction_systeme() as s:
                i = stock.inscription(s, inscription_id, verrou=True)
                if i is None or i.statut != "active":
                    continue
                p = stock.lire_prospect(s, i.prospect_id)
                c = stock.contact(s, i.contact_id)
                seq = seqs.get(i.sequence_id)
                if p is None or c is None or seq is None:
                    self._clore(s, acteur, i, "arretee", "fondateur")
                    continue
                blocages = self._blocages_contact(s, p, c)
                if blocages:
                    motif = {"opposition": "opposition", "exclusion": "exclusion", "statut": "statut"}.get(
                        blocages[0], "fondateur"
                    )
                    self._clore(s, acteur, i, "arretee", motif)
                    continue
            # 2. état des étapes dans la file de validation (hors transaction d'écriture)
            vue = self._vue_inscription(i, seq, fs, lecteur)
            prochaine = vue.prochaine or {}
            if any(e.statut == StatutAction.refuse.value for e in vue.etapes):
                decision: tuple[str, str | None] | None = ("arretee", "refus")
            elif prochaine.get("fin") and vue.etapes and vue.etapes[-1].statut == StatutAction.envoye.value:
                decision = ("terminee", None)
            else:
                decision = None
            if decision is not None:
                with self.db.transaction_systeme() as s:
                    i2 = stock.inscription(s, inscription_id, verrou=True)
                    if i2 is not None and i2.statut == "active":
                        self._clore(s, acteur, i2, *decision)
                continue
            if "due" not in prochaine or prochaine["due"] > self.horloge():
                continue
            rang = int(prochaine["rang"])
            rendu = self.rendu(p, c, prochaine["etape"])
            if rendu.manquants:
                continue
            # 3. plafond, puis brouillon (idempotent par inscription et rang) et enregistrement
            with self.db.transaction_systeme() as s:
                if self._plafond(s, ("preparation",), self.config.preparations_par_jour):
                    break
            payload = self._payload(p, c, inscription_id, seq.id, rang, rendu)
            action = fs.proposer(
                KIND, payload, acteur, idempotency_key=f"prospection:{inscription_id}:{rang}"
            )
            self._enregistrer_preparation(acteur, inscription_id, rang, action, c.adresse)
            prepares.append(action.id)
        return prepares

    def _clore(self, s: Any, acteur: Acteur, i: Any, statut: str, motif: str | None) -> None:
        i.statut, i.motif_arret, i.arretee_le = statut, motif, self.horloge()
        kind = "sequence_fin" if statut == "terminee" else "sequence_arret"
        self._evenement(s, i.prospect_id, kind, acteur.id, details={"inscription": i.id, "motif": motif})

    # --- envoi -----------------------------------------------------------------------------------------------
    def blocages_envoi(self, a: ActionSortante) -> list[str]:
        """Motifs qui empêchent l'envoi d'une action approuvée (revérifiés juste avant l'envoi)."""
        p_ = a.payload_effectif
        corps = str(p_.get("corps") or "") + str(p_.get("objet") or "")
        out = []
        with self.db.transaction_systeme() as s:
            p = stock.lire_prospect(s, str(a.payload.get("prospect_id") or ""))
            c = stock.contact(s, str(a.payload.get("contact_id") or ""))
            if p is None or c is None:
                return ["contact_absent"]
            dest = [adr.normaliser_adresse(x) for x in p_.get("destinataires") or []]
            if dest != [c.adresse]:
                out.append("contact_absent")
            out += [b for b in self._blocages_contact(s, p, c) if b != "statut"]
            if p.statut in ("perdu", "ne_plus_contacter", "client"):
                out.append("statut")
            if gabarits.MARQUE_MANQUANT in corps:
                out.append("faits_manquants")
            if "STOP" not in corps or (self.identite.siren and self.identite.siren not in corps):
                out.append("pied_absent")
            if self._plafond(s, ("envoi", "declaration_envoi"), self.config.envois_par_jour):
                out.append("plafond")
        return list(dict.fromkeys(out))

    def envoyer(
        self, acteur: Acteur, action_id: str, expediteur: Any, *, declaration: bool = False
    ) -> ActionSortante:
        """Envoie (expéditeur configuré) ou enregistre l'envoi déclaré par le fondateur, après revérification."""
        self._fondateur(acteur)
        fs = FileSortante(self.db)
        a = fs.obtenir(action_id, acteur)
        if a.kind is not TypeAction.email_prospection:
            raise AccesRefuse("introuvable ou hors périmètre")
        if a.statut not in (StatutAction.approuve, StatutAction.corrige):
            raise RefusProspection("Seul un courriel approuvé peut être envoyé.")
        blocages = self.blocages_envoi(a)
        if blocages:
            raise RefusProspection(BLOCAGES[blocages[0]])
        envoye = fs.envoyer(action_id, expediteur, acteur)
        with self.db.transaction_systeme() as s:
            pid = str(a.payload.get("prospect_id"))
            p = self._lire(s, pid, verrou=True)
            kind = "declaration_envoi" if declaration else "envoi"
            self._evenement(
                s, p.id, kind, acteur.id, details={"outbox": action_id, "rang": a.payload.get("rang")}
            )
            if rang_statut(p.statut) < rang_statut("contacte"):
                self._changer_statut(s, acteur, p, "contacte")
        return envoye

    def courriels(self, acteur: Acteur) -> list[dict[str, Any]]:
        """Courriels de prospection de la file (tous statuts), avec prospect et blocages d'envoi."""
        self._fondateur(acteur)
        actions = FileSortante(self.db).lister(acteur, kind=KIND)
        with self.db.transaction_systeme() as s:
            noms = {p.id: p.raison_sociale for p in stock.lister_prospects(s)}
        sortie = []
        for a in reversed(actions):
            blocages = (
                self.blocages_envoi(a) if a.statut in (StatutAction.approuve, StatutAction.corrige) else []
            )
            sortie.append(
                {
                    "a": a,
                    "prospect_id": a.payload.get("prospect_id"),
                    "prospect": noms.get(str(a.payload.get("prospect_id")), "—"),
                    "rang": a.payload.get("rang"),
                    "blocages": blocages,
                    "declare": (a.reference_envoi or "").startswith("declaration:"),
                }
            )
        return sortie

    # --- suivi et tableau de bord ------------------------------------------------------------------------------
    def statistiques(self, acteur: Acteur) -> dict[str, Any]:
        """Compteurs réels par séquence et par étape (préparés, approuvés, envoyés, réponses) et rendez-vous."""
        self._fondateur(acteur)
        seqs = self.sequences(acteur)
        actions = {a.id: a for a in FileSortante(self.db).lister(acteur, kind=KIND)}
        with self.db.transaction_systeme() as s:
            inscr = stock.inscriptions(s)
            reponses = stock.tous_evenements(s, ("reponse",))
            rdv = stock.tous_evenements(s, ("rendez_vous",))
        par_seq: dict[str, dict[str, Any]] = {
            q.id: {
                "sequence": q,
                "inscrits": 0,
                "rendez_vous": 0,
                "etapes": {
                    int(e["rang"]): Counter({"prepares": 0, "approuves": 0, "envoyes": 0, "reponses": 0})
                    for e in q.etapes
                },
            }
            for q in seqs
        }
        par_prospect: dict[str, list[Any]] = defaultdict(list)
        for i in inscr:
            par_prospect[i.prospect_id].append(i)
            d = par_seq.get(i.sequence_id)
            if d is None:
                continue
            d["inscrits"] += 1
            for e in i.etapes or []:
                cpt = d["etapes"].setdefault(int(e["rang"]), Counter())
                cpt["prepares"] += 1
                a = actions.get(e["outbox_id"])
                if a is not None and a.statut in (
                    StatutAction.approuve,
                    StatutAction.corrige,
                    StatutAction.envoye,
                ):
                    cpt["approuves"] += 1
                if a is not None and a.statut is StatutAction.envoye:
                    cpt["envoyes"] += 1
        for ev in reponses:
            i, rang = self._attribuer(par_prospect.get(ev.prospect_id, []), ev.le, actions)
            if i is not None and rang and i.sequence_id in par_seq:
                par_seq[i.sequence_id]["etapes"].setdefault(rang, Counter())["reponses"] += 1
        for ev in rdv:
            i, _r = self._attribuer(par_prospect.get(ev.prospect_id, []), ev.le, actions)
            if i is not None and i.sequence_id in par_seq:
                par_seq[i.sequence_id]["rendez_vous"] += 1
        return {"sequences": list(par_seq.values())}

    @staticmethod
    def _attribuer(inscr: list[Any], le: datetime, actions: dict[str, ActionSortante]) -> tuple[Any, int]:
        """Inscription et étape auxquelles revient un événement : dernière étape envoyée avant ``le``."""
        candidates = [i for i in inscr if i.demarree_le <= le]
        if not candidates:
            return None, 0
        i = candidates[-1]
        rang = 0
        for e in i.etapes or []:
            a = actions.get(e["outbox_id"])
            if a is not None and a.envoye_le is not None and a.envoye_le <= le:
                rang = max(rang, int(e["rang"]))
        return i, rang

    def tableau(self, acteur: Acteur) -> dict[str, Any]:
        self._fondateur(acteur)
        maintenant_ = self.horloge()
        actions = FileSortante(self.db).lister(acteur, kind=KIND)
        with self.db.transaction_systeme() as s:
            prospects = stock.lister_prospects(s)
            evts = stock.tous_evenements(s, ("statut", "reponse", "envoi", "declaration_envoi"))
        par_statut = Counter(p.statut for p in prospects)
        # étape la plus avancée atteinte par chaque prospect (historique des statuts et statut courant)
        atteint: dict[str, int] = {p.id: max(rang_statut(p.statut), 0) for p in prospects}
        for e in evts:
            if e.kind == "statut" and e.vers in ETAPES_PIPELINE and e.prospect_id in atteint:
                atteint[e.prospect_id] = max(atteint[e.prospect_id], rang_statut(e.vers))
        for p in prospects:
            if (
                p.statut not in ETAPES_PIPELINE
            ):  # perdu / ne plus contacter : rang tiré de l'historique seulement
                atteint[p.id] = max(
                    [0]
                    + [
                        rang_statut(e.vers)
                        for e in evts
                        if e.prospect_id == p.id and e.vers in ETAPES_PIPELINE
                    ]
                )
        # conversion d'une étape à la suivante : « atteint / precedent » et son pourcentage entier (le même nombre
        # sert au libellé et à la barre) ; sans prospect à l'étape précédente, pas de taux.
        conversion = []
        precedent = None
        for k, st in enumerate(ETAPES_PIPELINE):
            n = sum(1 for v in atteint.values() if v >= k)
            conversion.append(
                {
                    "statut": st,
                    "atteint": n,
                    "precedent": precedent,
                    "taux": (round(100 * n / precedent) if precedent else None),
                }
            )
            precedent = n
        contactes = {e.prospect_id for e in evts if e.kind in ("envoi", "declaration_envoi")}
        repondus = {e.prospect_id for e in evts if e.kind == "reponse"}
        segments: dict[tuple[str, str], list[int]] = defaultdict(lambda: [0, 0])
        for p in prospects:
            if p.id not in contactes:
                continue
            for cle in (("naf", p.naf or "?"), ("taille", p.tranche_effectif or "?")):
                segments[cle][0] += 1
                segments[cle][1] += p.id in repondus
        top = sorted(
            (
                {"genre": g, "valeur": v, "contactes": n, "reponses": r, "taux": round(100 * r / n)}
                for (g, v), (n, r) in segments.items()
            ),
            key=lambda x: (-x["taux"], -x["contactes"], x["valeur"]),
        )
        debut_semaine = datetime.combine(
            aujourdhui_paris(maintenant_) - timedelta(days=aujourdhui_paris(maintenant_).weekday()),
            time(0),
            tzinfo=PARIS,
        ).astimezone(UTC)
        brouillons = [a for a in actions if a.statut is StatutAction.brouillon]
        return {
            "total": len(prospects),
            "par_statut": [(st, par_statut.get(st, 0)) for st in STATUTS],
            "conversion": conversion,
            "a_valider": brouillons,
            "a_valider_semaine": sum(1 for a in brouillons if a.cree_le >= debut_semaine),
            "approuves": [a for a in actions if a.statut in (StatutAction.approuve, StatutAction.corrige)],
            "envoyes_semaine": sum(1 for a in actions if a.envoye_le and a.envoye_le >= debut_semaine),
            "reponses_a_traiter": sorted(
                (p for p in prospects if p.statut == "a_repondu"),
                key=lambda p: p.derniere_interaction_le or p.modifie_le,
                reverse=True,
            ),
            "segments": top[:8],
            "a_purger": len(self._a_purger(prospects)),
            "compteurs": self.compteurs_du_jour(),
        }

    # --- conservation ----------------------------------------------------------------------------------------
    def _a_purger(self, prospects: Iterable[Any]) -> list[Any]:
        limite = self.horloge() - timedelta(days=365 * self.config.conservation_annees)
        sortie = []
        for p in prospects:
            if p.statut == "client":
                continue
            ref = datetime.combine(p.collecte_le, time(0), tzinfo=UTC)
            if p.derniere_interaction_le is not None:
                ref = max(ref, p.derniere_interaction_le)
            if ref < limite:
                sortie.append(p)
        return sortie

    def a_purger(self, acteur: Acteur) -> list[Any]:
        self._fondateur(acteur)
        with self.db.transaction_systeme() as s:
            return self._a_purger(stock.lister_prospects(s))

    def purger(self, acteur: Acteur) -> int:
        """Supprime les prospects sans contact émanant d'eux depuis la durée de conservation (3 ans) ; la liste
        d'opposition est conservée. Journalisé (nombre seulement)."""
        self._fondateur(acteur)
        with self.db.transaction_systeme(effacement=True) as s:
            ids = [p.id for p in self._a_purger(stock.lister_prospects(s))]
            n = stock.supprimer_prospects(s, ids)
            self._audit(s, acteur, "purge", "prospects", nombre=n, annees=self.config.conservation_annees)
            return n

    def suppressions(self, acteur: Acteur) -> list[dict[str, Any]]:
        """Liste d'opposition ; l'adresse n'est montrée que si un contact enregistré a la même empreinte."""
        self._fondateur(acteur)
        with self.db.transaction_systeme() as s:
            connus: dict[str, Any] = {}
            for c in stock.tous_contacts(s):
                if c.empreinte:
                    connus.setdefault(c.empreinte, c)
            return [{"s": x, "contact": connus.get(x.empreinte)} for x in stock.suppressions(s)]


class _Faits:
    """Champs d'un prospect pas encore enregistré, pour la recherche d'exclusion."""

    def __init__(self, **champs: Any) -> None:
        self.raison_sociale: str = champs["raison_sociale"]
        self.groupe: str | None = champs.get("groupe")
        self.site_web: str | None = champs.get("site_web")
