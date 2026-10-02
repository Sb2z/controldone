"""Service de facturation du fondateur : brouillons, émission numérotée, Factur-X, dépôt sur la plateforme
agréée partenaire, liens de paiement et webhooks.

Cycle d'une facture (aucun envoi automatique) :

1. **Brouillon** ``facture_emise`` dans la file de validation (``proposer_*`` ; l'agent ``facturation`` et
   le service des litiges en créent aussi) : lignes HT, remise éventuelle, références ;
2. **Approbation** par le fondateur (``FileSortante.approuver`` ou ``corriger``) ;
3. **Émission** (``emettre``) : numéro suivant de la série (continu, chronologique), TVA, mentions
   obligatoires, XML CII EN 16931 validé par le XSD, PDF/A-3 Factur-X ; la facture est **immuable** ;
4. **Dépôt** (``deposer``) : envoi de l'action par ``ExpediteurFacture`` = dépôt sur la PA partenaire
   (bouchon par défaut) et copie dans ``<data_dir>/outbox_envoyee/facture_emise/``.

Une correction passe par un **avoir** (``proposer_avoir`` -> même cycle, série ``AV``).
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from controldone.auth.roles import Acteur, Role
from controldone.facturation.facturx_cii import controles_reforme, generer_xml, valider_xsd
from controldone.facturation.modele import (
    TYPE_AVOIR,
    TYPE_FACTURE,
    Acheteur,
    Facture,
    Ligne,
    Remise,
    mentions_obligatoires,
)
from controldone.facturation.offres import CatalogueOffres, Consentement, CouponRefuse, arrondi, charger_offres
from controldone.facturation.pa import FactureADeposer, PlateformeAgreee, PlateformeAgreeeBouchon
from controldone.facturation.paiements import FournisseurPaiement, SessionPaiement, fournisseur_depuis_env
from controldone.facturation.pdf import assembler_facturx, rendre_pdf
from controldone.formatage import format_montant
from controldone.guardrails import AVERTISSEMENT
from controldone.ids import nouvel_id
from controldone.litiges import commission_cle, destinataires_client
from controldone.outbox import ActionSortante, FileSortante, StatutAction, TypeAction
from controldone.storage import facturation as stock
from controldone.storage.db import Database
from controldone.storage.erreurs import AccesRefuse
from controldone.storage.models_facturation import FactureEmise

__all__ = ["EmissionRefusee", "ExpediteurFacture", "ServiceFacturation", "aujourdhui_paris"]

_PARIS = ZoneInfo("Europe/Paris")
_NOM_RE = re.compile(r"[^A-Za-z0-9_.-]")


class EmissionRefusee(ValueError):
    """Émission impossible (brouillon non approuvé, vendeur incomplet en production, avoir excessif…)."""


def aujourdhui_paris() -> date:
    return datetime.now(UTC).astimezone(_PARIS).date()


def _exiger_fondateur(acteur: Acteur) -> None:
    if acteur.role is not Role.fondateur:
        raise AccesRefuse("réservé au fondateur")


def _d(x: Any, defaut: str = "0") -> Decimal:
    return Decimal(str(x if x not in (None, "") else defaut))


@dataclass
class ExpediteurFacture:
    """Expéditeur de la file sortante pour ``facture_emise`` : dépôt de la facture **émise** sur la PA
    partenaire du fondateur (idempotent par numéro) et copie locale du PDF Factur-X."""

    service: ServiceFacturation
    nom: str = "plateforme_agreee"

    def envoyer(self, action: ActionSortante) -> str:
        f = stock.facture_par_outbox(self.service.db, action.id)
        if f is None:
            raise EmissionRefusee("facture non émise : émettre avant de déposer")
        accuse = self.service.pa.deposer_facture(FactureADeposer(
            numero=f.numero, facture_id=f.id, siren_acheteur=str((f.contenu.get("acheteur") or {}).get("siren", "")),
            contenu=f.pdf))
        stock.enregistrer_statut_pa(self.service.db, facture_id=f.id, numero=f.numero,
                                    identifiant_pa=accuse.identifiant_pa, code=accuse.code, libelle="Déposée",
                                    horodatage=accuse.horodatage)
        if self.service.dossier_sorties is not None:
            d = Path(self.service.dossier_sorties) / "facture_emise"
            d.mkdir(parents=True, exist_ok=True, mode=0o700)
            (d / f"{_NOM_RE.sub('_', f.numero)}.pdf").write_bytes(f.pdf)
        return f"pa:{self.service.pa.nom}:{accuse.identifiant_pa}"


class ServiceFacturation:
    def __init__(self, db: Database, *, catalogue: CatalogueOffres | None = None, pa: PlateformeAgreee | None = None,
                 paiement: FournisseurPaiement | None = None, dossier_sorties: Path | str | None = None,
                 prod: bool | None = None) -> None:
        self.db = db
        self.catalogue = catalogue or charger_offres()
        self.pa = pa or PlateformeAgreeeBouchon()
        self._paiement = paiement
        self.dossier_sorties = Path(dossier_sorties) if dossier_sorties else None
        if prod is None:
            from controldone.storage.cles import mode_execution

            prod = mode_execution() == "prod"
        self.prod = prod

    @property
    def paiement(self) -> FournisseurPaiement:
        if self._paiement is None:
            self._paiement = fournisseur_depuis_env()
        return self._paiement

    # --- acheteur --------------------------------------------------------------------------------------
    def acheteur(self, client_id: str) -> tuple[Acheteur, dict[str, Any]]:
        lu = stock.lire_client_facturation(self.db, client_id)
        if lu is None:
            raise AccesRefuse("client introuvable")
        raison, _offre, reglages = lu
        fx = dict(reglages.get("facturation") or {})
        contacts = destinataires_client(reglages, client_id)
        email = str(fx.get("email") or (contacts[0] if contacts and "@" in contacts[0] else ""))
        champs = {k: str(fx.get(k) or "") for k in ("siren", "tva_intracom", "adresse_ligne", "code_postal", "ville",
                                                     "adresse_electronique", "livraison_ligne", "livraison_code_postal",
                                                     "livraison_ville", "livraison_pays")}
        return Acheteur(client_id=client_id, raison_sociale=str(fx.get("raison_sociale") or raison),
                        pays=str(fx.get("pays") or "FR"), email=email, **champs), reglages

    # --- brouillons --------------------------------------------------------------------------------------
    def _payload(self, client_id: str, type_facture: str, lignes: list[Ligne], *, remises: list[Remise] | None = None,
                 references: dict[str, Any] | None = None, facturation: dict[str, Any] | None = None,
                 objet: str | None = None) -> dict[str, Any]:
        acheteur, reglages = self.acheteur(client_id)
        remises = remises or []
        total_ht = sum((x.montant_ht for x in lignes), Decimal("0.00")) - sum((arrondi(r.montant) for r in remises),
                                                                            Decimal("0.00"))
        tva = self.catalogue.tva
        montant_tva = arrondi(total_ht * tva.taux_effectif / Decimal(100))
        detail = "\n".join(f"- {x.libelle} : {format_montant(x.montant_ht, 'EUR')} HT" for x in lignes)
        detail += "".join(f"\n- Remise ({r.libelle}) : − {format_montant(r.montant, 'EUR')}" for r in remises)
        lib_tva = (f"TVA {tva.taux_effectif.normalize():f} %" if tva.tva_applicable else tva.mention_franchise)
        corps = (f"Brouillon de facture pour {acheteur.raison_sociale} ({type_facture}).\n\n{detail}\n\n"
                 f"Total HT : {format_montant(total_ht, 'EUR')} ; {lib_tva} : {format_montant(montant_tva, 'EUR')} ; "
                 f"total TTC : {format_montant(total_ht + montant_tva, 'EUR')}. Numéro attribué à l'émission, "
                 f"après votre approbation.\n\n{AVERTISSEMENT}")
        return {
            "objet": objet or f"Brouillon de facture — {type_facture}", "corps": corps,
            "destinataires": destinataires_client(reglages, client_id), "type_facture": type_facture,
            "lignes": [{"libelle": x.libelle, "quantite": str(x.quantite),
                        "prix_unitaire_ht": str(arrondi(x.prix_unitaire_ht)), "montant_ht": str(x.montant_ht)}
                       for x in lignes],
            "remises": [{"libelle": r.libelle, "montant": str(arrondi(r.montant))} for r in remises],
            "total_ht": str(total_ht), "total_tva": str(montant_tva), "total_ttc": str(total_ht + montant_tva),
            "devise": "EUR", "references": references or {}, "facturation": facturation or {},
        }

    def _proposer(self, client_id: str, payload: dict[str, Any], acteur: Acteur, cle: str) -> ActionSortante:
        return FileSortante(self.db).proposer(TypeAction.facture_emise, payload, acteur, tenant_id=client_id,
                                              idempotency_key=cle)

    def proposer_diagnostic(self, client_id: str, acteur: Acteur, *, coupon: str | None = None,
                            consentement: Consentement | None = None, references: dict[str, Any] | None = None,
                            prix_ht: Decimal | None = None) -> ActionSortante:
        c = self.catalogue
        ligne = Ligne(c.libelle_diagnostic, Decimal(prix_ht if prix_ht is not None else c.prix_diagnostic_ht))
        remises: list[Remise] = []
        fx: dict[str, Any] = {"offre": "diagnostic"}
        cle = f"facture:diagnostic:{client_id}"
        if coupon:
            utilisations = stock.coupon_utilisations(self.db, c.coupon(coupon).code)
            cp = c.verifier_coupon(coupon, offre="diagnostic", consentement=consentement,
                                   utilisations=len(utilisations),
                                   deja_utilise_par_client=any(u.client_id == client_id for u in utilisations))
            remises.append(Remise(f"{cp.libelle} (coupon {cp.code}, remise {cp.remise_pourcentage.normalize():f} %)",
                                  cp.remise(ligne.montant_ht)))
            fx["coupon"] = {"code": cp.code, "consentement": {
                "signe": True, "signe_par": consentement.signe_par, "signe_le": consentement.signe_le,  # type: ignore[union-attr]
                "reference_document": consentement.reference_document}}  # type: ignore[union-attr]
            cle += ":coupon"
        payload = self._payload(client_id, "diagnostic", [ligne], remises=remises, references=references, facturation=fx)
        return self._proposer(client_id, payload, acteur, cle)

    def proposer_abonnement(self, client_id: str, acteur: Acteur, *, palier: str, mois: str,
                            deja_paye: Decimal | None = None, reference_paiement: str = "") -> ActionSortante:
        if not re.fullmatch(r"\d{4}-\d{2}", mois):
            raise ValueError("mois au format AAAA-MM attendu")
        p = self.catalogue.palier(palier)
        ligne = Ligne(f"{p.libelle} — {mois} (jusqu'à {p.dossiers_par_mois} dossiers)", p.prix_mensuel_ht)
        fx: dict[str, Any] = {"offre": "continu", "palier": p.code, "mois": mois}
        if deja_paye is not None:
            fx["deja_paye"] = str(deja_paye)
            fx["reference_paiement"] = reference_paiement
        payload = self._payload(client_id, "abonnement", [ligne], references={"mois": mois}, facturation=fx)
        return self._proposer(client_id, payload, acteur, f"facture:abonnement:{client_id}:{mois}")

    def proposer_commission(self, client_id: str, acteur: Acteur, *, base: Decimal, avoir_id: str,
                            reclamation_id: str = "") -> ActionSortante:
        montant = self.catalogue.commission(base)
        pct = f"{(self.catalogue.taux_commission * 100).normalize():f}"
        ligne = Ligne(f"Commission de {pct} % sur avoir obtenu ({avoir_id}, base {format_montant(base, 'EUR')})", montant)
        payload = self._payload(client_id, "commission", [ligne],
                                references={"avoir_id": avoir_id, "reclamation_id": reclamation_id, "base": str(base)},
                                facturation={"offre": "commission"})
        return self._proposer(client_id, payload, acteur, commission_cle(client_id, avoir_id))

    def proposer_avoir(self, facture_id: str, acteur: Acteur, *, motif: str,
                       montant_ht: Decimal | None = None) -> ActionSortante:
        """Avoir total (ou partiel : ``montant_ht``) d'une facture émise. Le cumul des avoirs ne peut pas
        dépasser la base HT de la facture."""
        _exiger_fondateur(acteur)
        if not (motif and motif.strip()):
            raise ValueError("un avoir exige un motif")
        f = stock.facture(self.db, facture_id)
        if f is None or f.type_code != TYPE_FACTURE:
            raise AccesRefuse("facture introuvable")
        deja = sum((a.total_ht for a in stock.factures(self.db, client_id=f.client_id)
                    if a.facture_origine_id == f.id), Decimal("0.00"))
        montant = arrondi(montant_ht) if montant_ht is not None else f.total_ht - deja
        if montant <= 0 or deja + montant > f.total_ht:
            raise EmissionRefusee("montant de l'avoir supérieur au reste de la facture")
        ligne = Ligne(f"Avoir sur la facture n° {f.numero} — {motif.strip()[:200]}", montant)
        payload = self._payload(f.client_id, "avoir", [ligne], references={"facture_origine_id": f.id,
                                                                            "facture_origine": f.numero},
                                facturation={"facture_origine_id": f.id, "motif": motif.strip()[:500]},
                                objet=f"Brouillon d'avoir — facture n° {f.numero}")
        n = len([a for a in stock.factures(self.db, client_id=f.client_id) if a.facture_origine_id == f.id])
        return self._proposer(f.client_id, payload, acteur, f"avoir:{f.id}:{n + 1}")

    # --- émission ------------------------------------------------------------------------------------------
    def _facture(self, numero: str, a: ActionSortante, d: date) -> tuple[Facture, dict[str, Any]]:
        p = a.payload_effectif
        fx = dict(p.get("facturation") or {})
        lignes = tuple(Ligne(str(x["libelle"]), _d(x.get("prix_unitaire_ht")), _d(x.get("quantite"), "1"))
                       for x in p.get("lignes") or [])
        remises = tuple(Remise(str(r["libelle"]), _d(r.get("montant"))) for r in p.get("remises") or [])
        acheteur, _ = self.acheteur(a.tenant_id or "")
        c = self.catalogue
        origine = None
        type_code = TYPE_FACTURE
        if p.get("type_facture") == "avoir":
            origine = stock.facture(self.db, str(fx.get("facture_origine_id") or ""))
            if origine is None:
                raise EmissionRefusee("facture d'origine introuvable")
            type_code = TYPE_AVOIR
        echeance = d + timedelta(days=c.paiement.delai_jours)
        deja_paye = _d(fx.get("deja_paye"))
        if deja_paye:
            echeance = d
        f = Facture(numero=numero, type_code=type_code, date_emission=d, date_echeance=echeance if not origine else d,
                    vendeur=c.vendeur, acheteur=acheteur, lignes=lignes, tva=c.tva, paiement=c.paiement, remises=remises,
                    facture_origine=origine.numero if origine else None,
                    date_facture_origine=origine.date_emission if origine else None,
                    date_prestation=date.fromisoformat(fx["date_prestation"]) if fx.get("date_prestation") else None,
                    reference_paiement=str(fx.get("reference_paiement") or numero), objet=str(p.get("type_facture", "")))
        if deja_paye:
            from dataclasses import replace

            f = replace(f, deja_paye=min(deja_paye, f.total_ttc))
        return f, fx

    def emettre(self, action_id: str, acteur: Acteur, *, le: date | None = None) -> FactureEmise:
        """Émet la facture d'un brouillon **approuvé** (idempotent : renvoie la facture déjà émise)."""
        _exiger_fondateur(acteur)
        a = FileSortante(self.db).obtenir(action_id, acteur)
        if a.kind is not TypeAction.facture_emise or a.tenant_id is None:
            raise EmissionRefusee("action sans facture")
        deja = stock.facture_par_outbox(self.db, a.id)
        if deja is not None:
            return deja
        if a.statut not in (StatutAction.approuve, StatutAction.corrige):
            raise EmissionRefusee("le brouillon doit être approuvé par le fondateur avant l'émission")
        vendeur = self.catalogue.vendeur
        if self.prod and not vendeur.complet:
            raise EmissionRefusee("identité du vendeur incomplète (" + ", ".join(vendeur.champs_a_completer()) + ")")
        d = le or aujourdhui_paris()
        serie = self.catalogue.prefixe_avoir if a.payload_effectif.get("type_facture") == "avoir" else \
            self.catalogue.prefixe_facture
        fx_payload = dict(a.payload_effectif.get("facturation") or {})
        facture_id = nouvel_id("fac")

        def construire(numero: str) -> dict[str, Any]:
            f, fx = self._facture(numero, a, d)
            xml = generer_xml(f)
            valider_xsd(xml)
            pdf = assembler_facturx(rendre_pdf(f, non_valable=not vendeur.complet), xml, numero=numero,
                                    vendeur=vendeur.raison_sociale, titre="Avoir" if f.est_avoir else "Facture")
            origine_id = fx.get("facture_origine_id") if f.est_avoir else None
            contenu = {
                "type_facture": a.payload_effectif.get("type_facture"), "acheteur": f.acheteur.__dict__,
                "vendeur": {k: v for k, v in vendeur.__dict__.items() if k != "iban"},
                "lignes": [{"libelle": x.libelle, "quantite": str(x.quantite), "prix_unitaire_ht": str(x.prix_unitaire_ht),
                            "montant_ht": str(x.montant_ht)} for x in f.lignes],
                "remises": [{"libelle": r.libelle, "montant": str(r.montant)} for r in f.remises],
                "taux_tva": str(f.taux_tva), "categorie_tva": f.tva.categorie, "deja_paye": str(f.deja_paye),
                "net_a_payer": str(f.net_a_payer), "mentions": mentions_obligatoires(f),
                "references": a.payload_effectif.get("references") or {}, "facturation": fx,
                "controles_reforme": controles_reforme(f), "vendeur_complet": vendeur.complet,
                "facture_origine": f.facture_origine,
            }
            signe = -1 if f.est_avoir else 1
            return {"id": facture_id, "type_code": f.type_code, "type_facture": str(contenu["type_facture"] or "")[:32],
                    "client_id": a.tenant_id, "facture_origine_id": origine_id, "date_echeance": f.date_echeance,
                    "devise": f.devise, "total_ht": signe * f.base_ht, "total_tva": signe * f.montant_tva,
                    "total_ttc": signe * f.total_ttc, "contenu": contenu, "xml": xml.decode("utf-8"), "pdf": pdf,
                    "pdf_sha256": hashlib.sha256(pdf).hexdigest()}

        coupon = None
        if fx_payload.get("coupon"):
            cp = self.catalogue.coupon(fx_payload["coupon"]["code"])
            consent = fx_payload["coupon"].get("consentement") or {}
            if cp.consentement_requis and not consent.get("signe"):
                raise CouponRefuse("accord de publication non signé")
            coupon = {"code": cp.code, "client_id": a.tenant_id, "utilisations_max": cp.utilisations_max,
                      "une_fois_par_client": cp.une_fois_par_client, "consentement": consent}
        try:
            return stock.emettre_numerotee(self.db, emetteur=vendeur.identifiant, serie=serie, date_emission=d,
                                           chiffres=self.catalogue.chiffres, construire=construire,
                                           acteur_id=acteur.id, acteur_role=acteur.role.value, outbox_id=a.id,
                                           coupon=coupon)
        except stock.CouponIndisponible as exc:
            raise CouponRefuse(str(exc)) from exc

    def deposer(self, action_id: str, acteur: Acteur) -> ActionSortante:
        """Envoi de l'action (facture déjà émise) : dépôt sur la PA partenaire, copie locale."""
        _exiger_fondateur(acteur)
        return FileSortante(self.db).envoyer(action_id, ExpediteurFacture(self), acteur)

    def emettre_et_deposer(self, action_id: str, acteur: Acteur, *, le: date | None = None) -> FactureEmise:
        f = self.emettre(action_id, acteur, le=le)
        a = FileSortante(self.db).obtenir(action_id, acteur)
        if a.statut is not StatutAction.envoye:
            self.deposer(action_id, acteur)
        return f

    def synchroniser_statuts_pa(self) -> int:
        """Enregistre les statuts de cycle de vie reçus de la PA (append-only) ; renvoie le nombre de nouveaux."""
        n = 0
        for st in self.pa.recevoir_statuts():
            f = stock.facture_par_numero(self.db, st.numero, self.catalogue.vendeur.identifiant)
            if stock.enregistrer_statut_pa(self.db, facture_id=f.id if f else None, numero=st.numero,
                                           identifiant_pa=st.identifiant_pa, code=st.code, libelle=st.libelle,
                                           horodatage=st.horodatage, motif=st.motif):
                n += 1
        return n

    # --- paiement ------------------------------------------------------------------------------------------
    def _customer(self, client_id: str) -> str:
        compte = stock.compte_paiement(self.db, client_id)
        if compte and compte.customer_id and compte.fournisseur == self.paiement.nom:
            return compte.customer_id
        acheteur, _ = self.acheteur(client_id)
        cid = self.paiement.creer_client(client_id=client_id, raison_sociale=acheteur.raison_sociale,
                                         email=acheteur.email or None)
        stock.enregistrer_compte_paiement(self.db, client_id, fournisseur=self.paiement.nom, customer_id=cid)
        return cid

    def lien_paiement(self, facture_id: str, acteur: Acteur, *, url_base: str) -> SessionPaiement:
        """Session de paiement (Checkout) du net à payer d'une facture émise (diagnostic, commission)."""
        _exiger_fondateur(acteur)
        f = stock.facture(self.db, facture_id)
        if f is None or f.type_code != TYPE_FACTURE:
            raise AccesRefuse("facture introuvable")
        net = _d((f.contenu or {}).get("net_a_payer"), str(f.total_ttc))
        if net <= 0:
            raise EmissionRefusee("rien à payer sur cette facture")
        return self.paiement.session_paiement(
            client_id=f.client_id, customer_id=self._customer(f.client_id), facture_id=f.id, numero=f.numero,
            montant_ttc=net, libelle="ControlDOne", url_succes=f"{url_base}/admin/finances?paiement=ok",
            url_annulation=f"{url_base}/admin/finances?paiement=annule")

    def lien_abonnement(self, client_id: str, palier: str, acteur: Acteur, *, url_base: str) -> SessionPaiement:
        _exiger_fondateur(acteur)
        p = self.catalogue.palier(palier)
        ttc = p.prix_mensuel_ht + arrondi(p.prix_mensuel_ht * self.catalogue.tva.taux_effectif / Decimal(100))
        return self.paiement.session_abonnement(
            client_id=client_id, customer_id=self._customer(client_id), palier=p.code, libelle=p.libelle,
            montant_ttc_mensuel=ttc, url_succes=f"{url_base}/admin/finances?abonnement=ok",
            url_annulation=f"{url_base}/admin/finances?abonnement=annule")

    def traiter_webhook(self, charge: bytes, signature: str | None) -> dict[str, Any]:
        """Vérifie la signature (``SignatureInvalide`` sinon) puis traite l'événement (idempotent)."""
        return self.traiter_evenement(self.paiement.verifier_webhook(charge, signature))

    def traiter_evenement(self, evt: dict[str, Any]) -> dict[str, Any]:
        evt_id, typ = str(evt["id"])[:255], str(evt["type"])
        if any(e.id == evt_id for e in stock.evenements_paiement(self.db)):
            return {"statut": "deja_traite", "type": typ}
        obj = (evt.get("data") or {}).get("object") or {}
        meta = dict(obj.get("metadata") or {})
        meta_sub = dict(((obj.get("subscription_details") or {}).get("metadata")) or {})
        customer = obj.get("customer") if isinstance(obj.get("customer"), str) else None
        client = (meta.get("client_id") or meta_sub.get("client_id") or obj.get("client_reference_id")
                  or (stock.client_par_customer(self.db, customer) if customer else None))
        if client and stock.lire_client_facturation(self.db, str(client)) is None:
            client = None  # métadonnée inconnue : aucun effet sur un client
        montant: Decimal | None = None
        facture_id = None
        effets: list[str] = []
        systeme = Acteur.systeme("paiement")
        if typ == "checkout.session.completed":
            if client and customer:
                stock.enregistrer_compte_paiement(self.db, client, fournisseur=self.paiement.nom, customer_id=customer)
            if obj.get("mode") == "payment" and obj.get("payment_status") == "paid":
                montant = Decimal(int(obj.get("amount_total") or 0)) / 100
                f = stock.facture(self.db, str(meta.get("facture_id") or ""))
                facture_id = f.id if f and f.client_id == client else None
                effets.append("encaissement")
            elif obj.get("mode") == "subscription" and client:
                stock.enregistrer_compte_paiement(self.db, client, fournisseur=self.paiement.nom,
                                                  abonnement_id=obj.get("subscription"), palier=meta.get("palier"),
                                                  statut_abonnement="active")
                effets.append("abonnement_actif")
        elif typ == "invoice.paid":
            montant = Decimal(int(obj.get("amount_paid") or 0)) / 100
            if client:
                compte = stock.compte_paiement(self.db, client)
                palier = meta_sub.get("palier") or (compte.palier if compte else None)
                mois = str(meta.get("mois") or datetime.fromtimestamp(int(evt.get("created") or 0), UTC)
                           .astimezone(_PARIS).strftime("%Y-%m"))
                if palier:
                    a = self.proposer_abonnement(client, systeme, palier=palier, mois=mois, deja_paye=montant,
                                                 reference_paiement=str(obj.get("id", ""))[:140])
                    effets.append(f"brouillon_facture:{a.id}")
        elif typ == "invoice.payment_failed":
            stock.alerte_fondateur(self.db, cle=f"paiement_echoue:{obj.get('id')}", kind="paiement_echoue",
                                   tenant_id=client, message="Échec d'un prélèvement d'abonnement (Stripe) : relancer "
                                                             "le client ou vérifier son moyen de paiement.")
            effets.append("alerte")
        elif typ in ("customer.subscription.updated", "customer.subscription.deleted") and client:
            stock.enregistrer_compte_paiement(self.db, client, fournisseur=self.paiement.nom, abonnement_id=obj.get("id"),
                                              statut_abonnement="canceled" if typ.endswith("deleted") else obj.get("status"))
            effets.append("statut_abonnement")
        resume = {"objet": str(obj.get("id", ""))[:255], "mode": obj.get("mode"), "effets": effets,
                  "livemode": bool(evt.get("livemode"))}
        nouveau = stock.enregistrer_evenement(self.db, id=evt_id, fournisseur=self.paiement.nom, type=typ[:100],
                                              client_id=client, facture_id=facture_id, montant=montant,
                                              devise=str(obj.get("currency") or "eur").upper()[:3], contenu=resume)
        return {"statut": "traite" if nouveau else "deja_traite", "type": typ, "effets": effets}

