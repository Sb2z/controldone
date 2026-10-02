"""Registre de recouvrement (SPEC §17) et dossier de réclamation rédigé pour le client (§17.3).

- ``registre`` : écarts à recouvrer du client (constats validés ``recouvrable``), âge depuis la réclamation,
  relances suggérées à 30, 60 et 90 jours, événements append-only ;
- ``declarer_envoi`` : le **client** déclare avoir envoyé lui-même sa réclamation (``ouvert`` -> ``reclame``) ;
- ``enregistrer_avoir`` : avoir reçu (montant, référence) -> ``partiellement_credite`` ou ``credite`` ;
- ``preparer_dossier`` (fondateur) : dossier de réclamation **au nom du client** (première personne, entité
  du client en expéditeur, aucune mention du prestataire, aucune signature autre que celle à compléter par le
  client), en texte et en PDF ; garde-fous §3.2 ; proposé dans la file des sorties (``reclamation_dossier``)
  pour validation par le fondateur avant mise à disposition. Le système n'envoie **jamais** rien au
  transitaire.
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from xml.sax.saxutils import escape

from controldone.auth.roles import Acteur, Action, Role
from controldone.formatage import format_montant
from controldone.guardrails import AVERTISSEMENT, check_text
from controldone.ids import Prefixe, nouvel_id
from controldone.model.dossier import Dossier as DossierModele
from controldone.model.enums import Composante, StatutEcart
from controldone.model.recouvrement import ErreurTransition, PieceRecouvrement, Reclamation
from controldone.outbox import FileSortante, TypeAction
from controldone.rapport.vue import LIBELLES_COMPOSANTE
from controldone.services.plateforme import Interdit, Plateforme, RequeteInvalide, exiger
from controldone.storage.erreurs import AccesRefuse
from controldone.storage.models import Constat, Dossier, Ecart, Entite, EvenementRecouvrement, Transitaire
from controldone.storage.scope import TenantScope

__all__ = ["LIBELLES_STATUT_ECART", "LigneRegistre", "declarer_envoi", "enregistrer_avoir", "preparer_dossier",
           "registre"]

LIBELLES_STATUT_ECART = {
    "ouvert": "Ouvert", "reclame": "Réclamé", "partiellement_credite": "Partiellement crédité",
    "credite": "Crédité", "conteste": "Contesté", "abandonne": "Abandonné",
}
RELANCES = (30, 60, 90)


@dataclass
class LigneRegistre:
    id: str
    constat_id: str
    dossier_id: str | None
    dossier_reference: str | None
    transitaire: str
    transitaire_id: str | None
    composante: str
    niveau: str | None
    mrn: str | None
    montant_initial: Decimal
    montant_credite: Decimal
    reste: Decimal
    statut: str
    statut_code: str
    age_jours: int | None
    relance: str | None
    evenements: list[dict[str, Any]]

    def en_dict(self) -> dict[str, Any]:
        return {"litige_id": self.id, "constat_id": self.constat_id, "dossier_id": self.dossier_id,
                "dossier_reference": self.dossier_reference, "transitaire": self.transitaire,
                "composante": self.composante, "niveau": self.niveau, "mrn": self.mrn,
                "montant_initial_eur": str(self.montant_initial), "montant_credite_eur": str(self.montant_credite),
                "reste_eur": str(self.reste), "statut": self.statut_code, "age_jours": self.age_jours,
                "relance_suggeree": self.relance, "evenements": self.evenements,
                "nature": "écart constaté entre documents ; ne préjuge pas des sommes légalement dues"}


def _relance(age: int | None, statut: str) -> str | None:
    if age is None or statut not in ("reclame", "partiellement_credite", "conteste"):
        return None
    passees = [j for j in RELANCES if age >= j]
    return f"relance suggérée ({passees[-1]} jours)" if passees else None


def registre(scope: TenantScope, *, ecart_id: str | None = None) -> list[LigneRegistre]:
    """Écarts du client dont le constat est visible par l'acteur (rôle client : constats publiés)."""
    visibles = {c.id: c for c in scope.lister(Constat)}
    transitaires = {t.id: t.nom for t in scope.lister(Transitaire)}
    references = {d.id: d.reference or d.id for d in scope.lister(Dossier)}
    lignes = [scope.obtenir(Ecart, ecart_id)] if ecart_id else scope.lister(Ecart, ordre=Ecart.modifie_le)
    maintenant = datetime.now(UTC)
    out = []
    for e in lignes:
        if e.constat_id not in visibles:
            if ecart_id:
                raise AccesRefuse("introuvable ou hors périmètre")
            continue
        j = e.contenu or {}
        reclame_le = j.get("reclame_le")
        age = None
        if reclame_le:
            try:
                age = (maintenant - datetime.fromisoformat(reclame_le.replace("Z", "+00:00"))).days
            except ValueError:
                age = None
        evts = [{"de": v.de, "vers": v.vers, "le": v.le.isoformat() if v.le else None,
                 "montant": str(v.montant) if v.montant is not None else None,
                 "commentaire": (v.contenu or {}).get("commentaire"),
                 "piece": ((v.contenu or {}).get("piece") or {}).get("autre")}
                for v in scope.lister(EvenementRecouvrement, ecart_id=e.id, ordre=EvenementRecouvrement.le)]
        try:
            comp = LIBELLES_COMPOSANTE.get(Composante(j.get("composante")), j.get("composante") or "—")
        except ValueError:
            comp = j.get("composante") or "—"
        out.append(LigneRegistre(
            id=e.id, constat_id=e.constat_id, dossier_id=j.get("dossier_id"),
            dossier_reference=references.get(j.get("dossier_id") or ""),
            transitaire=transitaires.get(e.transitaire_id or "", e.transitaire_id or "transitaire non identifié"),
            transitaire_id=e.transitaire_id, composante=comp, niveau=visibles[e.constat_id].niveau, mrn=j.get("mrn"),
            montant_initial=e.montant_initial, montant_credite=Decimal(str(j.get("montant_credite") or "0")),
            reste=e.reste, statut=LIBELLES_STATUT_ECART.get(e.statut, e.statut), statut_code=e.statut,
            age_jours=age, relance=_relance(age, e.statut), evenements=evts))
    return out


def declarer_envoi(scope: TenantScope, ecart_id: str, commentaire: str | None = None) -> None:
    """Le client déclare avoir envoyé lui-même la réclamation (§17.1)."""
    exiger(scope.actor, Action.declarer_recouvrement, scope.tenant_id)
    registre(scope, ecart_id=ecart_id)  # visibilité du constat
    try:
        scope.transitionner_ecart(ecart_id, StatutEcart.reclame, commentaire=(commentaire or "").strip()[:500] or None)
    except ErreurTransition as exc:
        raise RequeteInvalide(str(exc)) from exc


def enregistrer_avoir(scope: TenantScope, ecart_id: str, montant: Decimal, reference: str | None = None,
                      commentaire: str | None = None) -> None:
    """Avoir reçu du transitaire : crédite l'écart (partiellement ou totalement)."""
    exiger(scope.actor, Action.declarer_recouvrement, scope.tenant_id)
    ligne = registre(scope, ecart_id=ecart_id)[0]
    if montant <= 0:
        raise RequeteInvalide("le montant de l'avoir doit être positif")
    vers = StatutEcart.credite if montant >= ligne.reste else StatutEcart.partiellement_credite
    piece = PieceRecouvrement(autre=(reference or "").strip()[:200] or None)
    try:
        scope.transitionner_ecart(ecart_id, vers, montant=montant.quantize(Decimal("0.01")), piece=piece,
                                  commentaire=(commentaire or "").strip()[:500] or None)
    except ErreurTransition as exc:
        raise RequeteInvalide(str(exc)) from exc


# --- dossier de réclamation (§17.3) ---------------------------------------------------------------------


def _texte(entite: Entite | None, transitaire: Transitaire, lignes: list[LigneRegistre], factures: list[str]) -> str:
    total = sum((x.reste for x in lignes), Decimal(0))
    exp = entite.raison_sociale if entite else "[raison sociale de votre société]"
    tva = f" — TVA {entite.tva}" if entite and entite.tva else ""
    objet = "Demande d'avoir — factures n° " + (", ".join(factures) or "[à compléter]")
    corps = [
        f"Expéditeur : {exp}{tva}",
        f"Destinataire : {transitaire.nom}",
        f"Objet : {objet}",
        "",
        "Madame, Monsieur,",
        "",
        "Nous avons rapproché vos factures des déclarations en douane correspondantes. Pour les lignes "
        "ci-dessous, le montant refacturé diffère du montant de référence indiqué sur les documents :",
        "",
    ]
    for x in lignes:
        corps.append(f"- Dossier {x.dossier_reference or x.dossier_id} — MRN {x.mrn or '—'} — {x.composante} : "
                     f"écart constaté {format_montant(x.reste, 'EUR')}")
    corps += [
        "",
        f"Total des écarts constatés : {format_montant(total, 'EUR')}.",
        "",
        "Nous vous remercions de bien vouloir vérifier ces éléments et, le cas échéant, émettre un avoir "
        "correspondant. Les pièces justificatives (extraits des documents) sont jointes.",
        "",
        "Nous restons à votre disposition pour tout échange.",
        "",
        "[Nom, fonction et signature]",
    ]
    return "\n".join(corps)


def _pdf(texte: str, lignes: list[LigneRegistre]) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    from controldone.rapport.pdf import _polices

    r, b, _i, _m = _polices()
    base = ParagraphStyle("b", fontName=r, fontSize=9.5, leading=13)
    petit = ParagraphStyle("p", parent=base, fontSize=7.5, leading=10, textColor=colors.HexColor("#555555"))
    tampon = io.BytesIO()
    doc = SimpleDocTemplate(tampon, pagesize=A4, leftMargin=20 * mm, rightMargin=20 * mm, topMargin=20 * mm,
                            bottomMargin=20 * mm, title="Demande d'avoir", author="", creator="")
    story: list[Any] = []
    for ligne in texte.split("\n"):
        if ligne.startswith("- "):
            continue
        story.append(Paragraph(escape(ligne) or "&nbsp;", base))
    donnees = [["Dossier", "MRN", "Composante", "Montant initial", "Déjà crédité", "Écart demandé"]]
    for x in lignes:
        donnees.append([x.dossier_reference or "—", x.mrn or "—", x.composante, format_montant(x.montant_initial, "EUR"),
                        format_montant(x.montant_credite, "EUR"), format_montant(x.reste, "EUR")])
    t = Table(donnees, repeatRows=1, colWidths=[28 * mm, 40 * mm, 34 * mm, 22 * mm, 22 * mm, 24 * mm])
    t.setStyle(TableStyle([("FONT", (0, 0), (-1, -1), r, 7.5), ("FONT", (0, 0), (-1, 0), b, 7.5),
                           ("LINEBELOW", (0, 0), (-1, 0), 0.6, colors.black),
                           ("ALIGN", (3, 0), (-1, -1), "RIGHT"), ("VALIGN", (0, 0), (-1, -1), "TOP")]))
    story += [Spacer(1, 6 * mm), t, Spacer(1, 8 * mm), Paragraph(escape(AVERTISSEMENT), petit)]
    doc.build(story)
    return tampon.getvalue()


def preparer_dossier(plateforme: Plateforme, fondateur: Acteur, tenant_id: str, transitaire_id: str) -> str:
    """Prépare le dossier de réclamation d'un transitaire (écarts certains validés, ouverts) et le propose
    dans la file des sorties ; renvoie l'identifiant de l'action."""
    if fondateur.role is not Role.fondateur:
        raise Interdit("préparation réservée au fondateur")
    with plateforme.db.operateur(fondateur) as op:
        scope = op.client(tenant_id, "préparation d'un dossier de réclamation")
        transitaire = scope.obtenir(Transitaire, transitaire_id)
        entites = scope.lister(Entite, ordre=Entite.raison_sociale)
        entite = entites[0] if entites else None
        lignes = [x for x in registre(scope) if x.transitaire_id == transitaire_id and x.statut_code == "ouvert"
                  and x.niveau == "ecart_certain"]
        if not lignes:
            raise RequeteInvalide("aucun écart certain validé et ouvert pour ce transitaire")
        factures = sorted({ref for x in lignes for ref in _factures_ft(scope, x)})
        texte = _texte(entite, transitaire, lignes, factures)
        if check_text(texte):
            raise RequeteInvalide("le texte du dossier contient une formulation interdite")
        pdf = _pdf(texte, lignes)
        ref_pdf = plateforme.vault.deposer(tenant_id, pdf)
        ref_txt = plateforme.vault.deposer(tenant_id, (texte + "\n\n" + AVERTISSEMENT + "\n").encode("utf-8"))
        total = sum((x.reste for x in lignes), Decimal(0))
        rec = Reclamation(id=nouvel_id(Prefixe.reclamation), client_id=tenant_id, transitaire_id=transitaire_id,
                          entite_id=entite.id if entite else None,
                          dossier_ids=sorted({x.dossier_id for x in lignes if x.dossier_id}),
                          ecart_ids=[x.id for x in lignes], objet=texte.split("\n")[2][len("Objet : "):],
                          total_demande=total)
        scope.enregistrer_reclamation(rec)
        nom = transitaire.nom
    payload = {
        "objet": f"Dossier de réclamation prêt — {nom}",
        "corps": texte,
        "destinataires": [],
        "pieces": [{"format": "pdf", "ref": ref_pdf, "nom": "demande_avoir.pdf"},
                   {"format": "txt", "ref": ref_txt, "nom": "demande_avoir.txt"}],
        "reclamation_id": rec.id,
        "total_eur": str(total),
    }
    action = FileSortante(plateforme.db).proposer(TypeAction.reclamation_dossier, payload, fondateur,
                                                  tenant_id=tenant_id, idempotency_key=f"reclamation:{rec.id}")
    return action.id


def _factures_ft(scope: TenantScope, ligne: LigneRegistre) -> list[str]:
    if not ligne.dossier_id:
        return []
    try:
        d = DossierModele.model_validate(scope.obtenir(Dossier, ligne.dossier_id).contenu)
    except AccesRefuse:
        return []
    return list(d.cles.num_facture_transitaire)

