"""Rédaction du dossier de demande d'avoir (SPEC §17.3) : texte modifiable et PDF.

Règles (§3, §17.3) :

- rédigé à la **première personne du client** (« Nous avons constaté… »), pour que le client l'envoie
  lui-même ; aucune mention du prestataire, aucune signature autre que celle à compléter par le client ;
- aucune qualification juridique, aucun délai légal, aucune menace : chaque montant est présenté comme un
  « écart constaté entre documents », avec les documents, pages et valeurs lues ;
- le texte passe ``guardrails.check_text`` (``FormulationInterdite`` sinon) ;
- l'avertissement général (§3.4) figure en fin de texte et au pied de chaque page du PDF.
"""

from __future__ import annotations

import io
import re
from decimal import Decimal
from xml.sax.saxutils import escape

from controldone.formatage import format_montant
from controldone.guardrails import AVERTISSEMENT, assert_clean
from controldone.model.enums import Composante

from .modele import DossierReclamation, LigneReclamation

__all__ = ["LIBELLES_COMPOSANTE", "nettoyer_libelle", "objet_reclamation", "rendre_pdf", "rendre_texte"]

LIBELLES_COMPOSANTE: dict[Composante, str] = {
    Composante.droit: "droits de douane",
    Composante.autre_taxe: "autres taxes",
    Composante.tva: "TVA à l'importation",
    Composante.forfait_petits_envois: "forfait petits envois",
    Composante.prestation: "prestations",
    Composante.valeur: "valeur",
}

_PHRASE_RE = re.compile(r"[^.!?]*[.!?]?")


def nettoyer_libelle(texte: str | None) -> str:
    """Retire d'un libellé de constat toute phrase qui cite le prestataire (le dossier est celui du client)."""
    if not texte:
        return ""
    phrases = [p.strip() for p in _PHRASE_RE.findall(texte) if p.strip()]
    return " ".join(p for p in phrases if "controldone" not in p.casefold())


def objet_reclamation(dossier: DossierReclamation) -> str:
    factures = ", ".join(dossier.factures) if dossier.factures else "(à compléter)"
    return f"Demande d'avoir — factures n° {factures}"


def _eur(x: Decimal) -> str:
    return format_montant(Decimal(x), "EUR")


def _texte_ligne(i: int, ligne: LigneReclamation) -> str:
    morceaux = [f"Facture n° {ligne.facture or '(non lue)'}"]
    if ligne.mrn:
        morceaux.append(f"MRN {ligne.mrn}")
    morceaux.append(LIBELLES_COMPOSANTE.get(ligne.composante, str(ligne.composante)))
    entete = " — ".join(morceaux)
    detail = []
    if ligne.montant_refacture:
        src = f" ({ligne.source_refacture})" if ligne.source_refacture else ""
        detail.append(f"montant refacturé {ligne.montant_refacture}{src}")
    if ligne.montant_reference:
        src = f" ({ligne.source_reference})" if ligne.source_reference else ""
        detail.append(f"montant de référence {ligne.montant_reference}{src}")
    detail.append(f"écart constaté entre documents : {_eur(ligne.ecart)}")
    texte = f"{i}. {entete} : " + " ; ".join(detail) + "."
    if ligne.a_confirmer:
        texte += " (à confirmer)"
    constat = nettoyer_libelle(ligne.constat)
    if constat:
        texte += f"\n   {constat}"
    return texte


def _bloc_partie(d: dict[str, str | None], defaut: str) -> list[str]:
    lignes = [d.get("raison_sociale") or d.get("nom") or defaut]
    for cle in ("adresse", "contact"):
        if d.get(cle):
            lignes.append(str(d[cle]))
    if d.get("tva"):
        lignes.append(f"TVA : {d['tva']}")
    return lignes


def _annexe(dossier: DossierReclamation) -> list[str]:
    sortie = ["Annexe — pièces et calculs"]
    for i, ligne in enumerate(dossier.lignes, 1):
        sortie.append(f"{i}. Dossier {ligne.dossier_reference or ligne.dossier_id} — facture n° {ligne.facture or '(non lue)'}")
        for p in ligne.pieces:
            page = f", page {p.page}" if p.page else ""
            lu = f" : « {p.valeur_lue} »" if p.valeur_lue else ""
            calcul = f" — calcul : {p.calcul}" if p.calcul else ""
            sortie.append(f"   - {p.document}{page}{lu}{calcul}")
    return sortie


def rendre_texte(dossier: DossierReclamation) -> str:
    """Texte prêt à coller dans un courriel, modifiable par le client avant envoi."""
    certains = [ligne for ligne in dossier.lignes if not ligne.a_confirmer]
    a_confirmer = [ligne for ligne in dossier.lignes if ligne.a_confirmer]
    parties: list[str] = []
    parties += _bloc_partie(dossier.entite, "[Votre société — à compléter]")
    parties.append("")
    parties.append("À l'attention de :")
    parties += _bloc_partie(dossier.transitaire, "[Transitaire — à compléter]")
    parties.append("")
    parties.append(f"Objet : {objet_reclamation(dossier)}")
    parties.append("")
    parties.append("Madame, Monsieur,")
    parties.append("")
    parties.append(
        "En rapprochant vos factures des déclarations en douane et des autres documents de nos dossiers "
        "d'import, nous avons constaté les écarts suivants entre documents :"
    )
    parties.append("")
    n = 0
    for ligne in certains:
        n += 1
        parties.append(_texte_ligne(n, ligne))
    parties.append("")
    parties.append(f"Total des écarts constatés entre documents : {_eur(dossier.total_demande)}.")
    if a_confirmer:
        parties.append("")
        parties.append("Nous vous soumettons également les écarts suivants, à confirmer :")
        for ligne in a_confirmer:
            n += 1
            parties.append(_texte_ligne(n, ligne))
        parties.append(f"Total des écarts à confirmer : {_eur(dossier.total_a_confirmer)}.")
    parties.append("")
    parties.append(
        "Nous vous remercions de bien vouloir examiner ces écarts et, s'ils se confirment, émettre un avoir "
        "correspondant, ou nous indiquer les éléments qui les expliquent. Les pièces (extraits des documents "
        "et calculs) figurent en annexe."
    )
    parties.append("")
    parties.append("Cordialement,")
    parties.append("")
    parties.append("[Nom, fonction — à compléter]")
    parties.append("[Date — à compléter]")
    parties.append("")
    parties += _annexe(dossier)
    parties.append("")
    parties.append(AVERTISSEMENT)
    texte = "\n".join(parties)
    assert_clean(texte)
    return texte


# --- PDF ----------------------------------------------------------------------------------------------


def rendre_pdf(dossier: DossierReclamation) -> bytes:
    """PDF du dossier (même contenu que le texte). Les textes sont vérifiés par ``rendre_texte``."""
    rendre_texte(dossier)  # garde-fous (lève FormulationInterdite)
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.lib.utils import simpleSplit
    from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    from controldone.rapport.pdf import _polices

    regulier, gras, _italique, _mono = _polices()
    base = ParagraphStyle("base", fontName=regulier, fontSize=9.5, leading=13)
    petit = ParagraphStyle("petit", parent=base, fontSize=8, leading=10.5)
    titre = ParagraphStyle("titre", parent=base, fontName=gras, fontSize=11.5, leading=15)

    def p(texte: str, style: ParagraphStyle = base) -> Paragraph:
        return Paragraph(escape(texte).replace("\n", "<br/>"), style)

    def pied(canvas, doc) -> None:
        canvas.saveState()
        canvas.setFont(regulier, 6.8)
        largeur = A4[0] - 30 * mm
        y = 14 * mm
        for ligne in simpleSplit(AVERTISSEMENT, regulier, 6.8, largeur):
            canvas.drawString(15 * mm, y, ligne)
            y -= 8
        canvas.drawRightString(A4[0] - 15 * mm, A4[1] - 10 * mm, f"Page {doc.page}")
        canvas.restoreState()

    flux: list = []
    entete = Table(
        [[p("\n".join(_bloc_partie(dossier.entite, "[Votre société — à compléter]"))),
          p("À l'attention de :\n" + "\n".join(_bloc_partie(dossier.transitaire, "[Transitaire — à compléter]")))]],
        colWidths=[85 * mm, 85 * mm],
    )
    entete.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))
    flux += [entete, Spacer(1, 8 * mm), p(f"Objet : {objet_reclamation(dossier)}", titre), Spacer(1, 4 * mm)]
    flux.append(p("Madame, Monsieur,"))
    flux.append(Spacer(1, 2 * mm))
    flux.append(p("En rapprochant vos factures des déclarations en douane et des autres documents de nos dossiers "
                  "d'import, nous avons constaté les écarts suivants entre documents :"))
    flux.append(Spacer(1, 3 * mm))
    donnees = [[p(x, petit) for x in ("Facture", "MRN", "Composante", "Montant refacturé", "Montant de référence",
                                      "Écart constaté entre documents")]]
    for ligne in dossier.lignes:
        refac = (ligne.montant_refacture or "—") + (f"\n{ligne.source_refacture}" if ligne.source_refacture else "")
        ref = (ligne.montant_reference or "—") + (f"\n{ligne.source_reference}" if ligne.source_reference else "")
        ecart = _eur(ligne.ecart) + ("\n(à confirmer)" if ligne.a_confirmer else "")
        donnees.append([p(ligne.facture or "(non lue)", petit), p(ligne.mrn or "—", petit),
                        p(LIBELLES_COMPOSANTE.get(ligne.composante, str(ligne.composante)), petit),
                        p(refac, petit), p(ref, petit), p(ecart, petit)])
    tableau = Table(donnees, colWidths=[24 * mm, 34 * mm, 26 * mm, 30 * mm, 30 * mm, 30 * mm], repeatRows=1)
    tableau.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#c0c6ce")),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eef1f5")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    flux += [tableau, Spacer(1, 3 * mm)]
    flux.append(p(f"Total des écarts constatés entre documents : {_eur(dossier.total_demande)}.", titre))
    if dossier.total_a_confirmer:
        flux.append(p(f"Total des écarts à confirmer : {_eur(dossier.total_a_confirmer)}."))
    flux.append(Spacer(1, 4 * mm))
    for ligne in dossier.lignes:
        constat = nettoyer_libelle(ligne.constat)
        if constat:
            flux.append(p(f"• {ligne.facture or '(non lue)'} — {constat}", petit))
    flux.append(Spacer(1, 4 * mm))
    flux.append(p("Nous vous remercions de bien vouloir examiner ces écarts et, s'ils se confirment, émettre un "
                  "avoir correspondant, ou nous indiquer les éléments qui les expliquent. Les pièces (extraits des "
                  "documents et calculs) figurent en annexe."))
    flux += [Spacer(1, 6 * mm), p("Cordialement,"), Spacer(1, 10 * mm),
             p("[Nom, fonction — à compléter]\n[Date — à compléter]")]
    flux.append(PageBreak())
    annexe = _annexe(dossier)
    flux.append(p(annexe[0], titre))
    flux.append(Spacer(1, 3 * mm))
    for ligne_annexe in annexe[1:]:
        flux.append(p(ligne_annexe, petit))

    tampon = io.BytesIO()
    doc = SimpleDocTemplate(tampon, pagesize=A4, leftMargin=15 * mm, rightMargin=15 * mm, topMargin=16 * mm,
                            bottomMargin=26 * mm, title=objet_reclamation(dossier))
    doc.build(flux, onFirstPage=pied, onLaterPages=pied)
    return tampon.getvalue()
