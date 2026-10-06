"""Cycle de vie des litiges (SPEC §17) : du constat validé à la commission.

1. ``preparer`` (système ou fondateur) : à partir des constats **validés** ``recouvrable`` de montant
   positif d'un transitaire, crée les écarts à recouvrer (§17.1, identifiant stable par constat) et le
   dossier de demande d'avoir (§17.3) : texte modifiable + PDF, rédigés pour le client.
2. ``valider`` (fondateur) : mise à disposition du client = brouillon sortant ``reclamation_dossier``.
3. ``declarer_envoi`` (client ou fondateur) : c'est le client qui envoie ; les écarts passent
   ``reclame`` ; les relances au client sont planifiées (J+15, J+30, J+45 par défaut, réglables par
   ``reglages["relances_jours"]``).
4. ``creer_relances_dues`` (agent ``litiges``) : brouillons ``relance`` **adressés au client** (le
   produit n'écrit jamais au transitaire).
5. ``enregistrer_avoir`` (client ou fondateur) : imputation déterministe (§17.2), transitions des
   écarts (événements append-only), statut du dossier, commission (§17.4, ``Decimal`` exact) et brouillon
   ``facture_emise`` ; un reliquat d'avoir (E5) donne une alerte au fondateur.
6. ``contester`` / ``reprendre`` / ``cloturer`` / ``abandonner``.

Verrous SQLite : les propositions sortantes (``FileSortante``) ouvrent leur propre transaction ; elles
sont donc toujours faites **hors** d'un périmètre en écriture.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

from controldone.auth.roles import Acteur, Action, Role
from controldone.controls.tolerances import Tolerances
from controldone.formatage import format_montant
from controldone.guardrails import AVERTISSEMENT
from controldone.model.enums import Composante, NatureLigne, Niveau, StatutEcart
from controldone.model.recouvrement import EcartARecouvrer, PieceRecouvrement
from controldone.model.referentiel import ProfilTolerances
from controldone.outbox import FileSortante
from controldone.perimetre import perimetre
from controldone.recouvrement import EcartImputable, LigneCredit, imputer_avoirs
from controldone.storage.coltypes import maintenant
from controldone.storage.db import Database
from controldone.storage.erreurs import AccesRefuse
from controldone.storage.models import (
    Constat,
    Document,
    Ecart,
    Entite,
    EvenementRecouvrement,
    Reclamation,
    Resultat,
)
from controldone.storage.models import Transitaire as TransitaireRow
from controldone.storage.scope import TenantScope

from .commission import (
    ORIGINES_COMMISSIONNABLES,
    ORIGINES_CREDIT,
    base_commission,
    montant_commission,
    taux_commission,
)
from .etats import (
    STATUTS_ACTIFS,
    STATUTS_TERMINAUX,
    StatutReclamation,
    statut_depuis_ecarts,
    verifier_transition,
)
from .facture import LigneFacture, payload_facture
from .modele import AvoirImpute, Commission, DossierReclamation, LigneReclamation, PieceLigne, Relance
from .redaction import objet_reclamation, rendre_pdf, rendre_texte

__all__ = [
    "RELANCES_DEFAUT",
    "AvoirRecu",
    "ResultatAvoir",
    "ServiceLitiges",
    "commission_cle",
    "destinataires_client",
    "id_ecart",
]

RELANCES_DEFAUT: tuple[int, ...] = (15, 30, 45)
_VALIDES = ("valide", "modifie")
_ZERO = Decimal("0.00")
ACTEUR_SORTIES = Acteur.systeme("litiges")


def id_ecart(tenant_id: str, constat_id: str) -> str:
    """Identifiant stable de l'écart né d'un constat (rejouer ``preparer`` ne crée aucun doublon)."""
    return "eca_" + hashlib.sha256(f"{tenant_id}\x1f{constat_id}".encode()).hexdigest()[:32]


def destinataires_client(reglages: dict[str, Any] | None, tenant_id: str) -> list[str]:
    """Contacts du client (``reglages["contacts"]``) ; à défaut une référence symbolique que le fondateur
    résout. Jamais un contact de transitaire."""
    contacts = [str(c) for c in (reglages or {}).get("contacts", []) if c]
    return contacts or [f"client:{tenant_id}"]


@dataclass(frozen=True)
class AvoirRecu:
    """Avoir déclaré reçu (par le client ou le fondateur), prêt à imputer (§17.2)."""

    avoir_id: str
    transitaire_id: str
    lignes: tuple[LigneCredit, ...]
    numero: str | None = None
    date_avoir: date | None = None
    #: ``transitaire`` | ``administration`` (remboursement de la douane ou d'une autorité : pas de commission).
    origine: str = "transitaire"
    #: TVA portée par l'avoir (information) : les montants des lignes sont **hors taxes**, seule base.
    montant_tva: Decimal | None = None

    @classmethod
    def declare(
        cls,
        avoir_id: str,
        transitaire_id: str,
        montants: dict[NatureLigne, Decimal],
        *,
        numero: str | None = None,
        date_avoir: date | None = None,
        factures_origine: Sequence[str] = (),
        mrns: Sequence[str] = (),
        refs_transport: Sequence[str] = (),
        origine: str = "transitaire",
        montant_tva: Decimal | None = None,
    ) -> AvoirRecu:
        """Avoir saisi : une ligne par nature (ex. ``{NatureLigne.debours_droits: Decimal("240.00")}``)."""
        lignes = tuple(
            LigneCredit(
                avoir_id=avoir_id,
                ligne=i,
                nature=nature,
                montant=Decimal(m),
                emetteur=transitaire_id,
                date_avoir=date_avoir,
                numero_avoir=numero,
                factures_origine=tuple(factures_origine),
                mrns=tuple(mrns),
                refs_transport=tuple(refs_transport),
            )
            for i, (nature, m) in enumerate(sorted(montants.items()))
        )
        if origine not in ORIGINES_CREDIT:
            raise ValueError("origine d'avoir inconnue")
        return cls(
            avoir_id,
            transitaire_id,
            lignes,
            numero,
            date_avoir,
            origine,
            Decimal(montant_tva) if montant_tva is not None else None,
        )

    @property
    def montant_total(self) -> Decimal:
        return sum((ligne.montant for ligne in self.lignes), _ZERO)


@dataclass
class ResultatAvoir:
    avoir_id: str
    deja_traite: bool = False
    imputations: dict[str, Decimal] = field(default_factory=dict)
    reliquat: Decimal = _ZERO
    base_commission: Decimal = _ZERO
    taux: Decimal = _ZERO
    commission: Decimal = _ZERO
    outbox_facture: str | None = None
    statuts: dict[str, str] = field(default_factory=dict)  # reclamation_id -> statut


def _dec(x: Any) -> Decimal | None:
    if x is None or x == "":
        return None
    try:
        return Decimal(str(x))
    except InvalidOperation:
        return None


def _valeur(champ: Any) -> str | None:
    return champ.get("valeur") if isinstance(champ, dict) else None


_LIBELLE_TYPE = {
    "facture_transitaire": "facture du transitaire",
    "facture_commerciale": "facture commerciale",
    "declaration": "déclaration en douane",
    "avoir": "avoir",
}


def _libelle_document(row: Document | None) -> str:
    if row is None:
        return "document"
    champs = (row.contenu or {}).get("champs") or {}
    base = _LIBELLE_TYPE.get(row.type, "document")
    if row.type == "declaration":
        mrn = _valeur(champs.get("mrn"))
        return f"{base} MRN {mrn}" if mrn else base
    numero = _valeur(champs.get("numero"))
    return f"{base} n° {numero}" if numero else base


def _numero(row: Document | None, cle: str) -> str | None:
    if row is None:
        return None
    return _valeur(((row.contenu or {}).get("champs") or {}).get(cle))


class ServiceLitiges:
    def __init__(
        self,
        db: Database,
        *,
        vault: Any = None,
        sorties: FileSortante | None = None,
        horloge: Callable[[], datetime] = maintenant,
    ) -> None:
        self.db = db
        self.vault = vault
        self.sorties = sorties or FileSortante(db)
        self.horloge = horloge

    # --- outils internes --------------------------------------------------------------------------------
    @staticmethod
    def _exiger_moteur(acteur: Acteur) -> None:
        if acteur.role not in (Role.systeme, Role.fondateur):
            raise AccesRefuse("préparation réservée au système et au fondateur")

    @staticmethod
    def _lire(scope: TenantScope, reclamation_id: str) -> DossierReclamation:
        return DossierReclamation.model_validate(scope.obtenir(Reclamation, reclamation_id).contenu)

    def _historiser(
        self, d: DossierReclamation, acteur: Acteur, evenement: str, commentaire: str | None = None
    ) -> None:
        d.historique = [
            *d.historique,
            {
                "le": self.horloge().isoformat(),
                "par": acteur.id,
                "evenement": evenement,
                "commentaire": (commentaire or None) and commentaire[:500],
            },
        ]
        d.derniere_activite = self.horloge()
        d.modifie_le = self.horloge()

    def _changer_statut(
        self, d: DossierReclamation, vers: StatutReclamation, acteur: Acteur, motif: str | None = None
    ) -> None:
        verifier_transition(d.statut, vers, motif)
        de = d.statut
        d.statut = vers
        self._historiser(d, acteur, f"{de.value}->{vers.value}", motif)

    @staticmethod
    def _documents(scope: TenantScope, ids: Iterable[str]) -> dict[str, Document]:
        out: dict[str, Document] = {}
        for i in ids:
            try:
                out[i] = scope.obtenir(Document, i)
            except AccesRefuse:
                continue
        return out

    # --- 1. préparation -----------------------------------------------------------------------------------
    def constats_eligibles(
        self, scope: TenantScope, transitaire_id: str | None = None, dossier_ids: Iterable[str] | None = None
    ) -> list[Constat]:
        """Constats validés ``recouvrable`` de montant positif (§17.1), triés par identifiant."""
        filtre = set(dossier_ids) if dossier_ids is not None else None
        dossiers: dict[str, Any] = {}
        out = []
        for c in scope.lister(Constat, ordre=Constat.id):
            if c.statut_validation not in _VALIDES or c.nature_montant != "recouvrable":
                continue
            if c.montant_en_jeu is None or c.montant_en_jeu <= 0 or (c.contenu or {}).get("renvoi"):
                continue
            if filtre is not None and c.dossier_id not in filtre:
                continue
            if transitaire_id is not None:
                if c.dossier_id not in dossiers:
                    dossiers[c.dossier_id] = scope.lire_dossier(c.dossier_id)
                if dossiers[c.dossier_id].transitaire_id != transitaire_id:
                    continue
            out.append(c)
        return out

    def preparer(
        self,
        acteur: Acteur,
        tenant_id: str,
        transitaire_id: str,
        *,
        dossier_ids: Iterable[str] | None = None,
        a_confirmer: Iterable[str] = (),
        entite_id: str | None = None,
        motif: str = "préparation d'un dossier de demande d'avoir",
    ) -> DossierReclamation:
        """Prépare le dossier de demande d'avoir d'un transitaire (statut ``brouillon``).

        ``a_confirmer`` : constats ``a_verifier`` cochés explicitement par le client (§17.3 point 5).
        Les écarts déjà rattachés à un dossier non abandonné sont exclus (pas de double demande).
        """
        self._exiger_moteur(acteur)
        coches = set(a_confirmer)
        with perimetre(self.db, tenant_id, acteur, motif=motif) as sc:
            tra = sc.obtenir(TransitaireRow, transitaire_id)
            actives = {
                r.id
                for r in sc.lister(Reclamation)
                if (r.contenu or {}).get("statut") != StatutReclamation.abandonnee.value
            }
            lignes: list[LigneReclamation] = []
            ecarts_ids: list[str] = []
            dossiers: dict[str, Any] = {}
            for c in self.constats_eligibles(sc, transitaire_id, dossier_ids):
                niveau = Niveau(c.niveau)
                if niveau is Niveau.a_verifier and c.id not in coches:
                    continue
                cj = c.contenu or {}
                if not cj.get("composante"):
                    continue
                composante = Composante(cj["composante"])
                eid = id_ecart(tenant_id, c.id)
                try:
                    ecart = sc.lire_ecart(eid)
                except AccesRefuse:
                    ecart = None
                if ecart is not None and (
                    ecart.statut in (StatutEcart.credite, StatutEcart.abandonne)
                    or (ecart.reclamation_id and ecart.reclamation_id in actives)
                ):
                    continue
                if c.dossier_id not in dossiers:
                    dossiers[c.dossier_id] = sc.lire_dossier(c.dossier_id)
                dossier = dossiers[c.dossier_id]
                docs = self._documents(sc, cj.get("documents_concernes") or [])
                ft = next((d for d in docs.values() if d.type == "facture_transitaire"), None)
                dec = next((d for d in docs.values() if d.type == "declaration"), None)
                facture = _numero(ft, "numero") or next(iter(dossier.cles.num_facture_transitaire), None)
                mrn = _numero(dec, "mrn") or next(iter(dossier.cles.mrn), None)
                ligne = self._ligne(sc, c, eid, dossier, docs, composante, niveau, facture, mrn)
                if ecart is None:
                    ecart = EcartARecouvrer(
                        id=eid,
                        client_id=tenant_id,
                        constat_id=c.id,
                        dossier_id=c.dossier_id,
                        transitaire_id=transitaire_id,
                        facture_transitaire_id=ft.id if ft else None,
                        mrn=mrn,
                        composante=composante,
                        montant_initial=c.montant_en_jeu,
                        reste=c.montant_en_jeu,
                        date_constat=c.valide_le or self.horloge(),
                    )
                    sc.enregistrer_ecart(ecart)
                lignes.append(ligne)
                ecarts_ids.append(eid)
            if not lignes:
                raise ValueError("aucun écart validé à demander pour ce transitaire")
            entite = self._entite(sc, entite_id)
            tc = tra.contenu or {}
            d = DossierReclamation(
                client_id=tenant_id,
                transitaire_id=transitaire_id,
                entite_id=entite.get("id"),
                dossier_ids=sorted({x.dossier_id for x in lignes}),
                ecart_ids=ecarts_ids,
                ecarts_a_confirmer=[x.ecart_id for x in lignes if x.a_confirmer],
                entite={k: v for k, v in entite.items() if k != "id"},
                transitaire={
                    "nom": tra.nom,
                    "adresse": tc.get("adresse"),
                    "contact": tc.get("contact_reclamation"),
                },
                factures=sorted({x.facture for x in lignes if x.facture}),
                lignes=lignes,
                total_demande=sum((x.ecart for x in lignes if not x.a_confirmer), _ZERO),
                total_a_confirmer=sum((x.ecart for x in lignes if x.a_confirmer), _ZERO),
            )
            d.objet = objet_reclamation(d)
            d.texte = rendre_texte(d)
            if self.vault is not None:
                d.pdf_sha256 = self.vault.deposer(tenant_id, rendre_pdf(d))
            self._historiser(d, acteur, "preparation")
            sc.enregistrer_reclamation(d)
            for eid in ecarts_ids:
                e = sc.lire_ecart(eid)
                e.reclamation_id = d.id
                contenu = e.model_dump(mode="json")
                contenu["client_id"] = tenant_id
                sc.modifier(Ecart, eid, contenu=contenu)
            sc.flush()
            return d

    def _ligne(
        self,
        sc: TenantScope,
        c: Constat,
        eid: str,
        dossier: Any,
        docs: dict[str, Document],
        composante: Composante,
        niveau: Niveau,
        facture: str | None,
        mrn: str | None,
    ) -> LigneReclamation:
        cj = c.contenu or {}
        preuves = cj.get("preuves") or []
        pieces: list[PieceLigne] = []
        sources: dict[str, tuple[str | None, str | None]] = {}
        for p in preuves:
            doc_id = p.get("document_id")
            if doc_id and doc_id not in docs:
                docs.update(self._documents(sc, [doc_id]))
            libelle = _libelle_document(docs.get(doc_id)) if doc_id else "calcul"
            piece = PieceLigne(
                document=libelle,
                document_id=doc_id,
                page=p.get("page"),
                valeur_lue=p.get("valeur_brute"),
                role=p.get("role"),
                calcul=p.get("calcul"),
            )
            pieces.append(piece)
            src = f"{libelle}, page {piece.page}" if piece.page else libelle
            sources.setdefault(p.get("role") or "", (piece.valeur_lue, src))
        attendu = constate = None
        if c.resultat_id:
            try:
                rc = sc.obtenir(Resultat, c.resultat_id).contenu or {}
                attendu, constate = _dec(rc.get("attendu")), _dec(rc.get("constate"))
            except AccesRefuse:
                pass
        refac_lu, refac_src = sources.get("valeur_b", (None, None))
        ref_lu, ref_src = sources.get("valeur_a", (None, None))
        return LigneReclamation(
            ecart_id=eid,
            constat_id=c.id,
            dossier_id=c.dossier_id,
            dossier_reference=dossier.reference,
            controle_id=c.controle_id,
            niveau=niveau,
            a_confirmer=niveau is Niveau.a_verifier,
            facture=facture,
            mrn=mrn,
            ref_transport=next(iter(dossier.cles.ref_transport), None),
            composante=composante,
            montant_refacture=format_montant(constate, "EUR") if constate is not None else refac_lu,
            source_refacture=refac_src,
            montant_reference=format_montant(attendu, "EUR") if attendu is not None else ref_lu,
            source_reference=ref_src,
            ecart=Decimal(c.montant_en_jeu),
            constat=cj.get("libelle") or "",
            pieces=pieces,
            tolerance=str(cj["tolerance_appliquee"])
            if cj.get("tolerance_appliquee") not in (None, "")
            else None,
        )

    @staticmethod
    def _entite(sc: TenantScope, entite_id: str | None) -> dict[str, str | None]:
        lignes = sc.lister(Entite, ordre=Entite.id)
        e = (
            next((x for x in lignes if x.id == entite_id), None)
            if entite_id
            else (lignes[0] if lignes else None)
        )
        if e is None:
            return {"raison_sociale": sc.client().raison_sociale}
        adresses = (e.contenu or {}).get("adresses") or []
        return {
            "id": e.id,
            "raison_sociale": e.raison_sociale,
            "adresse": adresses[0] if adresses else None,
            "tva": e.tva,
        }

    # --- 2. validation et mise à disposition ----------------------------------------------------------------
    def valider(self, fondateur: Acteur, tenant_id: str, reclamation_id: str) -> DossierReclamation:
        if fondateur.role is not Role.fondateur:
            raise AccesRefuse("validation d'un dossier de demande d'avoir réservée au fondateur")
        motif = "validation d'un dossier de demande d'avoir"
        with perimetre(self.db, tenant_id, fondateur, motif=motif) as sc:
            d = self._lire(sc, reclamation_id)
            reglages = sc.client().reglages or {}
            self._changer_statut(d, StatutReclamation.valide, fondateur)
            d.valide_par_fondateur, d.valide_le = True, self.horloge()
            sc.enregistrer_reclamation(d)
        action = self.sorties.proposer(
            "reclamation_dossier",
            {
                "objet": f"Votre relevé d'écarts est prêt — {d.objet}",
                "corps": (
                    "Bonjour,\n\nLe relevé d'écarts ci-dessous présente les différences chiffrées entre vos documents. "
                    "Il est suivi d'un modèle de courrier neutre que vous pouvez adapter et utiliser vous-même si vous "
                    "le décidez. Si vous recevez un avoir, vous pouvez le déposer pour qu'il soit rapproché des "
                    "écarts.\n\n" + d.texte
                ),
                "destinataires": destinataires_client(reglages, tenant_id),
                "destinataire_role": "client",
                "pieces": [f"coffre:{d.pdf_sha256}"] if d.pdf_sha256 else [],
                "reclamation_id": d.id,
            },
            ACTEUR_SORTIES,
            tenant_id=tenant_id,
            idempotency_key=f"reclamation:{tenant_id}:{d.id}",
        )
        with perimetre(self.db, tenant_id, fondateur, motif=motif) as sc:
            d = self._lire(sc, reclamation_id)
            d.outbox_mise_a_disposition = action.id
            sc.enregistrer_reclamation(d)
        return d

    # --- 3. envoi déclaré par le client ---------------------------------------------------------------------
    def declarer_envoi(
        self, acteur: Acteur, tenant_id: str, reclamation_id: str, *, le: datetime | None = None
    ) -> DossierReclamation:
        moment = le or self.horloge()
        with perimetre(self.db, tenant_id, acteur, motif="déclaration d'envoi d'une demande d'avoir") as sc:
            sc.exiger(Action.declarer_recouvrement)
            d = self._lire(sc, reclamation_id)
            self._changer_statut(d, StatutReclamation.envoyee, acteur)
            for eid in d.ecart_ids:
                e = sc.lire_ecart(eid)
                if e.statut in (StatutEcart.ouvert, StatutEcart.conteste):
                    sc.transitionner_ecart(
                        eid, StatutEcart.reclame, commentaire="envoi déclaré par le client"
                    )
            d.envoyee_le = moment
            jours = (sc.client().reglages or {}).get("relances_jours") or list(RELANCES_DEFAUT)
            d.relances = [
                Relance(jours=int(j), due_le=(moment + timedelta(days=int(j))).date())
                for j in sorted({int(x) for x in jours if int(x) > 0})
            ]
            sc.enregistrer_reclamation(d)
            return d

    # --- 4. relances au client ------------------------------------------------------------------------------
    def creer_relances_dues(
        self, tenant_id: str, *, maintenant_: datetime | None = None, acteur: Acteur = ACTEUR_SORTIES
    ) -> list[str]:
        """Crée les brouillons ``relance`` échus (destinataire : le client). Renvoie les identifiants."""
        now = maintenant_ or self.horloge()
        a_creer: list[tuple[str, int, dict[str, Any]]] = []
        with perimetre(self.db, tenant_id, acteur, lecture=True) as sc:
            reglages = sc.client().reglages or {}
            for r in sc.lister(Reclamation, ordre=Reclamation.id):
                d = DossierReclamation.model_validate(r.contenu)
                if d.statut not in STATUTS_ACTIFS:
                    continue
                restes = [sc.lire_ecart(e).reste for e in d.ecart_ids]
                reste = sum(restes, _ZERO)
                for rel in d.relances:
                    if rel.statut == "planifiee" and rel.due_le <= now.date():
                        a_creer.append(
                            (d.id, rel.jours, self._payload_relance(d, rel, reste, reglages, tenant_id))
                        )
        crees: dict[tuple[str, int], str] = {}
        for rec_id, jours, payload in a_creer:
            action = self.sorties.proposer(
                "relance",
                payload,
                acteur,
                tenant_id=tenant_id,
                idempotency_key=f"relance:{tenant_id}:{rec_id}:{jours}",
            )
            crees[(rec_id, jours)] = action.id
        if crees:
            with perimetre(self.db, tenant_id, acteur) as sc:
                for rec_id in sorted({k[0] for k in crees}):
                    d = self._lire(sc, rec_id)
                    d.relances = [
                        rel.model_copy(
                            update={"statut": "brouillon_cree", "outbox_id": crees[(rec_id, rel.jours)]}
                        )
                        if (rec_id, rel.jours) in crees
                        else rel
                        for rel in d.relances
                    ]
                    sc.enregistrer_reclamation(d)
        return list(crees.values())

    @staticmethod
    def _payload_relance(
        d: DossierReclamation, rel: Relance, reste: Decimal, reglages: dict[str, Any], tenant_id: str
    ) -> dict[str, Any]:
        envoi = d.envoyee_le.date().strftime("%d/%m/%Y") if d.envoyee_le else "(date non déclarée)"
        nom = d.transitaire.get("nom") or "votre transitaire"
        factures = ", ".join(d.factures) or "(non lues)"
        corps = (
            f"Bonjour,\n\nRappel de votre échéance interne (J+{rel.jours}) : depuis l'envoi déclaré le {envoi} "
            f"de votre courrier à {nom} (factures n° {factures}), aucun avoir n'a été enregistré pour "
            f"{format_montant(reste, 'EUR')} sur {format_montant(d.total_demande + d.total_a_confirmer, 'EUR')} "
            "de différences constatées entre documents.\n\nSi vous avez reçu un avoir, vous pouvez le déposer "
            "pour qu'il soit rapproché des écarts. La suite à donner vous appartient.\n\nCe message vous est "
            f"adressé à vous seulement : nous n'écrivons jamais à votre transitaire.\n\n{AVERTISSEMENT}"
        )
        return {
            "objet": f"Suivi des avoirs reçus — factures n° {factures} (J+{rel.jours})",
            "corps": corps,
            "destinataires": destinataires_client(reglages, tenant_id),
            "destinataire_role": "client",
            "reclamation_id": d.id,
            "jours": rel.jours,
        }

    # --- 5. avoir reçu ----------------------------------------------------------------------------------------
    def enregistrer_avoir(self, acteur: Acteur, tenant_id: str, avoir: AvoirRecu) -> ResultatAvoir:
        res = ResultatAvoir(avoir_id=avoir.avoir_id)
        with perimetre(self.db, tenant_id, acteur, motif="enregistrement d'un avoir reçu") as sc:
            sc.exiger(Action.declarer_recouvrement)
            for evt in sc.lister(EvenementRecouvrement):
                if ((evt.contenu or {}).get("piece") or {}).get("avoir_id") == avoir.avoir_id:
                    res.deja_traite = True
                    return res
            reglages = sc.client().reglages or {}
            reclamations = {
                r.id: DossierReclamation.model_validate(r.contenu) for r in sc.lister(Reclamation)
            }
            facture_de: dict[str, tuple[str | None, str | None]] = {}
            for d in reclamations.values():
                for ligne in d.lignes:
                    facture_de[ligne.ecart_id] = (ligne.facture, ligne.ref_transport)
            ecarts = {
                e.id: sc.lire_ecart(e.id) for e in sc.lister(Ecart, transitaire_id=avoir.transitaire_id)
            }
            imputables = [
                EcartImputable.depuis_ecart(
                    e,
                    facture_ref=facture_de.get(e.id, (None, None))[0],
                    ref_transport=facture_de.get(e.id, (None, None))[1],
                    emetteur=avoir.transitaire_id,
                )
                for e in ecarts.values()
            ]
            t_debours = Tolerances(ProfilTolerances()).t_debours(0)
            imp = imputer_avoirs(avoir.lignes, imputables, t_debours=t_debours)
            for eid in sorted(imp.ecarts):
                credit = imp.credit_pour(eid)
                if credit <= 0:
                    continue
                res.imputations[eid] = credit
                origine = "" if avoir.origine == "transitaire" else " (remboursement d'une administration)"
                sc.transitionner_ecart(
                    eid,
                    imp.ecarts[eid].statut,
                    montant=credit,
                    piece=PieceRecouvrement(avoir_id=avoir.avoir_id, autre=f"origine:{avoir.origine}"),
                    commentaire=f"avoir {avoir.numero or avoir.avoir_id}{origine}",
                )
            res.reliquat = imp.reliquat_avoir(avoir.avoir_id)
            # Base de commission (§17.4) : crédits imputés sur des écarts dont le constat est validé.
            eligibles = set()
            for eid in res.imputations:
                try:
                    if sc.obtenir(Constat, ecarts[eid].constat_id).statut_validation in _VALIDES:
                        eligibles.add(eid)
                except AccesRefuse:
                    continue
            res.taux = taux_commission(reglages)
            # Assiette (CGV art. 5, D-1314) : montants HT des avoirs émis par un transitaire ; un remboursement
            # accordé par une administration n'entre jamais dans l'assiette.
            hors_assiette = avoir.origine not in ORIGINES_COMMISSIONNABLES
            if hors_assiette:
                eligibles = set()
            res.base_commission = base_commission(res.imputations, eligibles)
            res.commission = montant_commission(res.base_commission, res.taux)
            now = self.horloge()
            for d in reclamations.values():
                part = {e: m for e, m in res.imputations.items() if e in d.ecart_ids}
                if not part:
                    continue
                d.avoirs = [
                    *d.avoirs,
                    AvoirImpute(
                        avoir_id=avoir.avoir_id,
                        numero=avoir.numero,
                        date_avoir=avoir.date_avoir,
                        montant_total=avoir.montant_total,
                        impute=sum(part.values(), _ZERO),
                        reliquat=res.reliquat,
                        imputations=part,
                        le=now,
                        origine=avoir.origine,
                        hors_assiette=hors_assiette,
                        montant_tva=avoir.montant_tva,
                    ),
                ]
                base_rec = base_commission(part, eligibles)
                if base_rec > 0:
                    d.commissions = [
                        *d.commissions,
                        Commission(
                            avoir_id=avoir.avoir_id,
                            base=base_rec,
                            taux=res.taux,
                            montant=montant_commission(base_rec, res.taux),
                            le=now,
                        ),
                    ]
                vers = statut_depuis_ecarts(d.statut, [sc.lire_ecart(e).statut for e in d.ecart_ids])
                if vers is not d.statut and d.statut not in STATUTS_TERMINAUX:
                    try:
                        self._changer_statut(d, vers, acteur)
                    except ValueError:
                        self._historiser(d, acteur, f"avoir:{avoir.avoir_id}")
                else:
                    self._historiser(d, acteur, f"avoir:{avoir.avoir_id}")
                if d.statut is StatutReclamation.credite:
                    d.relances = [
                        r.model_copy(update={"statut": "annulee"}) if r.statut == "planifiee" else r
                        for r in d.relances
                    ]
                sc.enregistrer_reclamation(d)
                res.statuts[d.id] = d.statut.value
            if res.reliquat > 0:
                sc.signaler_alerte(
                    cle=f"avoir_reliquat:{avoir.avoir_id}",
                    kind="avoir_reliquat",
                    message=f"Avoir {avoir.numero or avoir.avoir_id} : reliquat non imputé de "
                    f"{res.reliquat} EUR (contrôle E5).",
                    details={"avoir_id": avoir.avoir_id, "reliquat": str(res.reliquat)},
                )
            raison_sociale = sc.client().raison_sociale
        if res.commission > 0:
            res.outbox_facture = self._proposer_commission(tenant_id, avoir, res, reglages, raison_sociale)
            with perimetre(self.db, tenant_id, acteur, motif="enregistrement d'un avoir reçu") as sc:
                for rec_id in res.statuts:
                    d = self._lire(sc, rec_id)
                    d.commissions = [
                        c.model_copy(update={"outbox_id": res.outbox_facture})
                        if c.avoir_id == avoir.avoir_id
                        else c
                        for c in d.commissions
                    ]
                    sc.enregistrer_reclamation(d)
        return res

    def _proposer_commission(
        self,
        tenant_id: str,
        avoir: AvoirRecu,
        res: ResultatAvoir,
        reglages: dict[str, Any],
        raison_sociale: str,
    ) -> str:
        quand = f" du {avoir.date_avoir.strftime('%d/%m/%Y')}" if avoir.date_avoir else ""
        pct = (res.taux * 100).normalize()
        ligne = LigneFacture(
            libelle=(
                f"Commission de {pct:f} % sur avoir obtenu (avoir n° {avoir.numero or avoir.avoir_id}{quand}, "
                f"base {format_montant(res.base_commission, 'EUR')})"
            ),
            prix_unitaire_ht=res.commission,
        )
        payload = payload_facture(
            "commission",
            [ligne],
            destinataires=destinataires_client(reglages, tenant_id),
            raison_sociale=raison_sociale,
            references={
                "avoir_id": avoir.avoir_id,
                "base_commission": str(res.base_commission),
                "taux": str(res.taux),
                "reclamation_ids": sorted(res.statuts),
            },
        )
        return self.sorties.proposer(
            "facture_emise",
            payload,
            ACTEUR_SORTIES,
            tenant_id=tenant_id,
            idempotency_key=commission_cle(tenant_id, avoir.avoir_id),
        ).id

    # --- 6. contestation, reprise, clôture, abandon -------------------------------------------------------------
    def _transition_ecarts(
        self,
        sc: TenantScope,
        d: DossierReclamation,
        depuis: set[StatutEcart],
        vers: StatutEcart,
        commentaire: str | None,
    ) -> None:
        for eid in d.ecart_ids:
            e = sc.lire_ecart(eid)
            if e.statut in depuis:
                sc.transitionner_ecart(eid, vers, commentaire=commentaire)

    def contester(
        self, acteur: Acteur, tenant_id: str, reclamation_id: str, commentaire: str
    ) -> DossierReclamation:
        with perimetre(self.db, tenant_id, acteur, motif="contestation déclarée") as sc:
            sc.exiger(Action.declarer_recouvrement)
            d = self._lire(sc, reclamation_id)
            self._changer_statut(d, StatutReclamation.conteste, acteur, commentaire)
            self._transition_ecarts(
                sc,
                d,
                {StatutEcart.reclame, StatutEcart.partiellement_credite},
                StatutEcart.conteste,
                commentaire,
            )
            sc.enregistrer_reclamation(d)
            return d

    def reprendre(self, acteur: Acteur, tenant_id: str, reclamation_id: str) -> DossierReclamation:
        """Après une contestation, le client relance son transitaire : retour à ``envoyee``."""
        with perimetre(self.db, tenant_id, acteur, motif="reprise d'un litige") as sc:
            sc.exiger(Action.declarer_recouvrement)
            d = self._lire(sc, reclamation_id)
            self._changer_statut(d, StatutReclamation.envoyee, acteur)
            self._transition_ecarts(sc, d, {StatutEcart.conteste}, StatutEcart.reclame, "relance du client")
            sc.enregistrer_reclamation(d)
            return d

    def _terminer(
        self, acteur: Acteur, tenant_id: str, reclamation_id: str, vers: StatutReclamation, motif: str | None
    ) -> DossierReclamation:
        with perimetre(self.db, tenant_id, acteur, motif=f"{vers.value} d'un litige") as sc:
            sc.exiger(Action.declarer_recouvrement)
            d = self._lire(sc, reclamation_id)
            self._changer_statut(d, vers, acteur, motif)
            vivants = {
                StatutEcart.ouvert,
                StatutEcart.reclame,
                StatutEcart.partiellement_credite,
                StatutEcart.conteste,
            }
            self._transition_ecarts(sc, d, vivants, StatutEcart.abandonne, motif or vers.value)
            d.relances = [
                r.model_copy(update={"statut": "annulee"}) if r.statut == "planifiee" else r
                for r in d.relances
            ]
            sc.enregistrer_reclamation(d)
            return d

    def cloturer(
        self, acteur: Acteur, tenant_id: str, reclamation_id: str, motif: str | None = None
    ) -> DossierReclamation:
        """Clôture : libre après ``credite`` ; sinon motif obligatoire et le reste est abandonné."""
        return self._terminer(acteur, tenant_id, reclamation_id, StatutReclamation.clos, motif)

    def abandonner(
        self, acteur: Acteur, tenant_id: str, reclamation_id: str, motif: str
    ) -> DossierReclamation:
        return self._terminer(acteur, tenant_id, reclamation_id, StatutReclamation.abandonnee, motif)

    # --- lecture --------------------------------------------------------------------------------------------
    def lister(self, acteur: Acteur, tenant_id: str) -> list[DossierReclamation]:
        with perimetre(self.db, tenant_id, acteur, motif="lecture des litiges", lecture=True) as sc:
            return [
                DossierReclamation.model_validate(r.contenu)
                for r in sc.lister(Reclamation, ordre=Reclamation.id)
            ]

    def lire(self, acteur: Acteur, tenant_id: str, reclamation_id: str) -> DossierReclamation:
        with perimetre(self.db, tenant_id, acteur, motif="lecture d'un litige", lecture=True) as sc:
            return self._lire(sc, reclamation_id)

    def pdf(self, acteur: Acteur, tenant_id: str, reclamation_id: str) -> bytes:
        return rendre_pdf(self.lire(acteur, tenant_id, reclamation_id))

    def inactifs(
        self, acteur: Acteur, tenant_id: str, *, jours: int = 60, maintenant_: datetime | None = None
    ) -> list[DossierReclamation]:
        """Litiges en cours sans activité depuis ``jours`` (agent ``litiges``)."""
        now = maintenant_ or self.horloge()
        limite = now - timedelta(days=jours)
        out = []
        for d in self.lister(acteur, tenant_id):
            if d.statut not in STATUTS_ACTIFS:
                continue
            derniere = d.derniere_activite or d.envoyee_le or d.cree_le
            if derniere.tzinfo is None:
                derniere = derniere.replace(tzinfo=UTC)
            if derniere < limite:
                out.append(d)
        return out


def commission_cle(tenant_id: str, avoir_id: str) -> str:
    """Clé d'idempotence du brouillon de facture de commission d'un avoir."""
    return f"commission:{tenant_id}:{avoir_id}"
