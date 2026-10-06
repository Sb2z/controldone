"""Relevé d'écarts (SPEC §17.3, revu par le brief juridique §1.3 et §9) : texte et PDF.

Deux parties distinctes, produites à partir de **gabarits fixes** (jamais par le modèle de langage) :

1. **Relevé d'écarts entre documents** : document factuel — pour chaque écart, les documents et pages, les
   valeurs lues, la différence calculée et la tolérance appliquée. Aucune qualification juridique, aucune
   règle de droit, aucun avis sur des sommes dues : un « simple calcul de cohérence » (CA Paris, 9 avril
   2018, cité par le brief §1.2).
2. **« Modèle à adapter par le client »** : courrier court et neutre que le client complète, modifie, signe
   et envoie **lui-même** s'il le décide. Il expose les différences chiffrées et demande au transitaire de
   **vérifier** sa facture et d'**indiquer** s'il émettra un avoir. Il ne contient ni « nous réclamons », ni
   mise en demeure, ni délai, ni pénalité, ni citation de texte (``EXPRESSIONS_INTERDITES``, vérifié).

Aucune mention du prestataire ; le texte passe ``guardrails.check_text`` ; l'avertissement général (§3.4)
figure en fin de texte et au pied de chaque page du PDF.
"""

from __future__ import annotations

import io
import re
from decimal import Decimal
from xml.sax.saxutils import escape

from controldone.formatage import format_montant
from controldone.guardrails import AVERTISSEMENT, FormulationInterdite, Violation, assert_clean
from controldone.model.enums import Composante

from .modele import DossierReclamation, LigneReclamation

__all__ = [
    "EXPRESSIONS_INTERDITES",
    "LIBELLES_COMPOSANTE",
    "TITRE_MODELE",
    "TITRE_RELEVE",
    "nettoyer_libelle",
    "objet_reclamation",
    "rendre_modele",
    "rendre_pdf",
    "rendre_releve",
    "rendre_texte",
    "verifier_modele",
]

TITRE_RELEVE = "Relevé d'écarts entre documents"
TITRE_MODELE = "Modèle à adapter par le client"
NATURE_RELEVE = (
    "Ce relevé présente des valeurs lues dans les documents transmis et les différences calculées "
    "entre elles. Il ne qualifie pas juridiquement la situation et ne se prononce pas sur des sommes "
    "dues."
)
NOTE_MODELE = (
    "Modèle fourni à titre indicatif : vous le complétez, le modifiez et décidez seul de son envoi, "
    "sous votre nom. Il expose des différences chiffrées et ne contient aucun argument juridique."
)

#: Expressions qui feraient du modèle un acte juridique pour autrui (brief §9.8) : jamais dans le texte.
EXPRESSIONS_INTERDITES: tuple[str, ...] = (
    "nous réclamons",
    "réclamons",
    "mise en demeure",
    "mettons en demeure",
    "en application de l'article",
    "conformément aux dispositions",
    "conformément au contrat",
    "à défaut de régularisation",
    "action en justice",
    "nous nous réservons le droit",
    "vous êtes tenu",
    "sous huitaine",
    "sous quinzaine",
    "dans un délai",
    "pénalité",
    "intérêts de retard",
    "code des douanes",
    "code de commerce",
    "code civil",
    "suivi du recouvrement",
    "relance au transitaire",
)
#: Citations de textes (« article L. 221-3 », « art. 1231 du code… ») : jamais dans le relevé ni le modèle.
_CITATION = r"\bart(?:icle|\.)\s*[LRD]\.?\s?\d|\bloi n°"
_INTERDITES_RE = re.compile(
    "|".join([*(re.escape(x) for x in EXPRESSIONS_INTERDITES), _CITATION]), re.IGNORECASE
)

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
    """Retire d'un libellé de constat toute phrase qui cite le prestataire (le relevé est remis au client)."""
    if not texte:
        return ""
    phrases = [p.strip() for p in _PHRASE_RE.findall(texte) if p.strip()]
    return " ".join(p for p in phrases if "controldone" not in p.casefold())


def objet_reclamation(dossier: DossierReclamation) -> str:
    """Objet du relevé (nom conservé pour compatibilité)."""
    factures = ", ".join(dossier.factures) if dossier.factures else "(à compléter)"
    return f"{TITRE_RELEVE} — factures n° {factures}"


def _objet_modele(dossier: DossierReclamation) -> str:
    factures = ", ".join(dossier.factures) if dossier.factures else "[n° à compléter]"
    return f"Vérification des factures n° {factures}"


def _eur(x: Decimal) -> str:
    return format_montant(Decimal(x), "EUR")


def verifier_modele(texte: str) -> None:
    """Lève ``FormulationInterdite`` si le texte contient une expression d'acte juridique (brief §9.8)."""
    m = _INTERDITES_RE.search(texte)
    if m:
        raise FormulationInterdite(
            [
                Violation(
                    expression=m.group(0),
                    categorie="acte_juridique_pour_autrui",
                    extrait=texte[max(0, m.start() - 30) : m.end() + 30],
                    debut=m.start(),
                    fin=m.end(),
                )
            ]
        )


def _texte_ligne(i: int, ligne: LigneReclamation) -> str:
    morceaux = [
        f"Dossier {ligne.dossier_reference or ligne.dossier_id}",
        f"facture n° {ligne.facture or '(non lue)'}",
    ]
    if ligne.mrn:
        morceaux.append(f"MRN {ligne.mrn}")
    morceaux.append(LIBELLES_COMPOSANTE.get(ligne.composante, str(ligne.composante)))
    sortie = [f"{i}. " + " — ".join(morceaux) + (" (à confirmer)" if ligne.a_confirmer else "")]
    if ligne.montant_refacture:
        src = f" ({ligne.source_refacture})" if ligne.source_refacture else ""
        sortie.append(f"   Valeur facturée{src} : {ligne.montant_refacture}")
    if ligne.montant_reference:
        src = f" ({ligne.source_reference})" if ligne.source_reference else ""
        sortie.append(f"   Valeur de comparaison{src} : {ligne.montant_reference}")
    sortie.append(f"   Différence calculée : {_eur(ligne.ecart)}")
    if ligne.tolerance:
        sortie.append(f"   Tolérance appliquée : {ligne.tolerance}")
    constat = nettoyer_libelle(ligne.constat)
    if constat:
        sortie.append(f"   Constat ({ligne.controle_id}) : {constat}")
    return "\n".join(sortie)


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
        sortie.append(
            f"{i}. Dossier {ligne.dossier_reference or ligne.dossier_id} — facture n° {ligne.facture or '(non lue)'}"
        )
        for p in ligne.pieces:
            page = f", page {p.page}" if p.page else ""
            lu = f" : « {p.valeur_lue} »" if p.valeur_lue else ""
            calcul = f" — calcul : {p.calcul}" if p.calcul else ""
            sortie.append(f"   - {p.document}{page}{lu}{calcul}")
    return sortie


def rendre_releve(dossier: DossierReclamation) -> list[str]:
    """Partie 1 : relevé factuel (lignes de texte)."""
    certains = [ligne for ligne in dossier.lignes if not ligne.a_confirmer]
    a_confirmer = [ligne for ligne in dossier.lignes if ligne.a_confirmer]
    p: list[str] = [TITRE_RELEVE.upper(), ""]
    p.append("Client : " + " — ".join(_bloc_partie(dossier.entite, "[Votre société]")))
    p.append("Transitaire : " + (dossier.transitaire.get("nom") or "[Transitaire]"))
    p.append("Factures examinées : " + (", ".join(dossier.factures) or "(non lues)"))
    p += ["", NATURE_RELEVE, ""]
    n = 0
    for ligne in certains:
        n += 1
        p.append(_texte_ligne(n, ligne))
    p.append("")
    p.append(f"Total des différences constatées entre documents : {_eur(dossier.total_demande)}.")
    if a_confirmer:
        p += ["", "Différences à confirmer (lecture ou rapprochement incertain) :"]
        for ligne in a_confirmer:
            n += 1
            p.append(_texte_ligne(n, ligne))
        p.append(f"Total des différences à confirmer : {_eur(dossier.total_a_confirmer)}.")
    p.append("")
    p += _annexe(dossier)
    return p


def rendre_modele(dossier: DossierReclamation) -> list[str]:
    """Partie 2 : modèle de courrier neutre, à adapter par le client."""
    total = dossier.total_demande + dossier.total_a_confirmer
    p: list[str] = [TITRE_MODELE.upper(), NOTE_MODELE, ""]
    p += _bloc_partie(dossier.entite, "[Votre société — à compléter]")
    p += ["", "À l'attention de :"]
    p += _bloc_partie(dossier.transitaire, "[Transitaire — à compléter]")
    p += ["", f"Objet : {_objet_modele(dossier)}", "", "Madame, Monsieur,", ""]
    p.append(
        f"En rapprochant vos factures des autres documents de nos dossiers d'import, nous relevons des "
        f"différences chiffrées, présentées dans le relevé joint ({_eur(total)} au total)."
    )
    p.append("")
    p.append(
        "Pourriez-vous vérifier ces montants et nous indiquer si vous émettrez un avoir, ou nous "
        "transmettre les éléments qui expliquent ces différences ?"
    )
    p += [
        "",
        "[Formule de politesse — à compléter]",
        "",
        "[Nom, fonction — à compléter]",
        "[Date — à compléter]",
    ]
    return p


def rendre_texte(dossier: DossierReclamation) -> str:
    """Relevé d'écarts puis modèle à adapter (texte modifiable par le client), puis avertissement."""
    parties = [*rendre_releve(dossier), "", "-" * 60, "", *rendre_modele(dossier), "", AVERTISSEMENT]
    texte = "\n".join(parties)
    assert_clean(texte)
    verifier_modele(texte)
    return texte


# --- PDF ----------------------------------------------------------------------------------------------


def rendre_pdf(dossier: DossierReclamation) -> bytes:
    """PDF : relevé d'écarts (première partie) puis, sur une nouvelle page, le modèle à adapter par le client.
    Les textes sont vérifiés par ``rendre_texte``."""
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
    # --- partie 1 : relevé factuel ---
    flux.append(p(TITRE_RELEVE, titre))
    flux.append(Spacer(1, 2 * mm))
    flux.append(p("Client : " + " — ".join(_bloc_partie(dossier.entite, "[Votre société]"))))
    flux.append(p("Transitaire : " + (dossier.transitaire.get("nom") or "[Transitaire]")))
    flux.append(p("Factures examinées : " + (", ".join(dossier.factures) or "(non lues)")))
    flux.append(Spacer(1, 2 * mm))
    flux.append(p(NATURE_RELEVE, petit))
    flux.append(Spacer(1, 3 * mm))
    donnees = [
        [
            p(x, petit)
            for x in (
                "Dossier / facture",
                "Composante",
                "Valeur facturée (document, page)",
                "Valeur de comparaison (document, page)",
                "Différence calculée",
                "Tolérance",
            )
        ]
    ]
    for ligne in dossier.lignes:
        refac = (ligne.montant_refacture or "—") + (
            f"\n{ligne.source_refacture}" if ligne.source_refacture else ""
        )
        ref = (ligne.montant_reference or "—") + (
            f"\n{ligne.source_reference}" if ligne.source_reference else ""
        )
        ecart = _eur(ligne.ecart) + ("\n(à confirmer)" if ligne.a_confirmer else "")
        doss = f"{ligne.dossier_reference or ligne.dossier_id}\n{ligne.facture or '(non lue)'}" + (
            f"\nMRN {ligne.mrn}" if ligne.mrn else ""
        )
        donnees.append(
            [
                p(doss, petit),
                p(LIBELLES_COMPOSANTE.get(ligne.composante, str(ligne.composante)), petit),
                p(refac, petit),
                p(ref, petit),
                p(ecart, petit),
                p(ligne.tolerance or "—", petit),
            ]
        )
    tableau = Table(donnees, colWidths=[30 * mm, 22 * mm, 36 * mm, 36 * mm, 26 * mm, 30 * mm], repeatRows=1)
    tableau.setStyle(
        TableStyle(
            [
                ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#c0c6ce")),
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eef1f5")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ]
        )
    )
    flux += [tableau, Spacer(1, 3 * mm)]
    flux.append(
        p(f"Total des différences constatées entre documents : {_eur(dossier.total_demande)}.", titre)
    )
    if dossier.total_a_confirmer:
        flux.append(p(f"Total des différences à confirmer : {_eur(dossier.total_a_confirmer)}."))
    flux.append(Spacer(1, 3 * mm))
    for ligne in dossier.lignes:
        constat = nettoyer_libelle(ligne.constat)
        if constat:
            flux.append(p(f"• {ligne.facture or '(non lue)'} ({ligne.controle_id}) — {constat}", petit))
    flux.append(Spacer(1, 4 * mm))
    annexe = _annexe(dossier)
    flux.append(p(annexe[0], titre))
    for ligne_annexe in annexe[1:]:
        flux.append(p(ligne_annexe, petit))
    # --- partie 2 : modèle à adapter par le client ---
    flux.append(PageBreak())
    modele = rendre_modele(dossier)
    flux.append(p(TITRE_MODELE, titre))
    flux.append(p(NOTE_MODELE, petit))
    flux.append(Spacer(1, 6 * mm))
    for ligne_modele in modele[3:]:
        flux.append(p(ligne_modele) if ligne_modele else Spacer(1, 3 * mm))

    tampon = io.BytesIO()
    doc = SimpleDocTemplate(
        tampon,
        pagesize=A4,
        leftMargin=15 * mm,
        rightMargin=15 * mm,
        topMargin=16 * mm,
        bottomMargin=26 * mm,
        title=objet_reclamation(dossier),
    )
    # (titre du document PDF : « Relevé d'écarts entre documents — factures n° … »)
    doc.build(flux, onFirstPage=pied, onLaterPages=pied)
    return tampon.getvalue()
