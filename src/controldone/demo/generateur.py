"""Dessin des PDF de démonstration (ReportLab, mises en page génériques propres à ControlDOne).

Chaque document porte un bandeau « DONNÉES FICTIVES » et une mention de bas de page. PDF reproductibles
(``invariant=1`` : pas d'horodatage variable). Chaque valeur est écrite d'un seul tenant, pour que la
couche texte la restitue telle qu'imprimée.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas

from controldone.demo.donnees import MENTION, dossiers_demo, grille_demo, profil_demo
from controldone.demo.modele import DocDemo
from controldone.rapport.pdf import _polices

__all__ = ["dessiner_document", "generer_demo"]

ENCRE = colors.HexColor("#222831")
GRIS = colors.HexColor("#6b7280")
FILET = colors.HexColor("#cfd4da")
FOND = colors.HexColor("#f3f4f6")
ROUGE = colors.HexColor("#b42318")
ACCENTS = {
    "facture_commerciale": colors.HexColor("#0f4c5c"),
    "declaration": colors.HexColor("#3a3a6a"),
    "facture_transitaire": colors.HexColor("#5c3d0f"),
}


class _Releve:
    """Écrit les textes et relève la zone (relative, origine en haut à gauche) des valeurs du modèle."""

    def __init__(self, c: canvas.Canvas) -> None:
        self.c = c
        self.zones: dict[str, tuple[float, float, float, float]] = {}

    def ecrire(
        self,
        x: float,
        y: float,
        texte: str,
        police: str,
        taille: float,
        *,
        droite: bool = False,
        centre: bool = False,
        chemin: str | None = None,
    ) -> None:
        from reportlab.pdfbase.pdfmetrics import stringWidth

        c = self.c
        c.setFont(police, taille)
        w = stringWidth(texte, police, taille)
        if droite:
            c.drawRightString(x, y, texte)
            x0 = x - w
        elif centre:
            c.drawCentredString(x, y, texte)
            x0 = x - w / 2
        else:
            c.drawString(x, y, texte)
            x0 = x
        if chemin:
            largeur, hauteur = A4
            self.zones[chemin] = (
                max(0.0, x0 / largeur),
                max(0.0, 1 - (y + 0.85 * taille) / hauteur),
                min(1.0, (x0 + w) / largeur),
                min(1.0, 1 - (y - 0.25 * taille) / hauteur),
            )


def dessiner_document(
    doc: DocDemo, chemin: Path | None = None
) -> dict[str, tuple[float, float, float, float]]:
    """Dessine le document (dans ``chemin``, ou en mémoire) ; retourne la zone de chaque valeur du modèle
    (chemin relatif -> ``(x0, y0, x1, y1)``)."""
    import io

    r, b, _i, _m = _polices()
    cible: Any = io.BytesIO()
    if chemin is not None:
        chemin.parent.mkdir(parents=True, exist_ok=True)
        cible = str(chemin)
    c = canvas.Canvas(cible, pagesize=A4, invariant=1)
    rel = _Releve(c)
    c.setTitle(f"{doc.titre} {doc.cle} — DONNÉES FICTIVES")
    c.setAuthor("ControlDOne — démonstration")
    largeur, hauteur = A4
    g, d = 16 * mm, largeur - 16 * mm
    accent = ACCENTS.get(doc.type.value, ENCRE)

    # bandeau
    c.setFillColor(ROUGE)
    c.rect(0, hauteur - 8 * mm, largeur, 8 * mm, stroke=0, fill=1)
    c.setFillColor(colors.white)
    rel.ecrire(
        largeur / 2, hauteur - 5.3 * mm, "DONNÉES FICTIVES — DOCUMENT DE DÉMONSTRATION", b, 8, centre=True
    )
    # titre (ligne propre), puis émetteur à gauche et en-tête à droite
    c.setFillColor(accent)
    rel.ecrire(g, hauteur - 20 * mm, doc.titre, b, 16)
    c.setStrokeColor(accent)
    c.setLineWidth(1.4)
    c.line(g, hauteur - 23 * mm, d, hauteur - 23 * mm)
    y = hauteur - 30 * mm
    c.setFillColor(ENCRE)
    for k, ligne in enumerate(doc.emetteur):
        rel.ecrire(g, y, ligne, b if k == 0 else r, 10 if k == 0 else 8)
        y -= 5 * mm if k == 0 else 4 * mm
    y_ent = hauteur - 27 * mm
    largeur_bloc = 84 * mm
    x0 = d - largeur_bloc
    n = len(doc.entete)
    c.setFillColor(FOND)
    c.setStrokeColor(FILET)
    c.setLineWidth(0.5)
    c.rect(x0, y_ent - n * 5 * mm - 2 * mm, largeur_bloc, n * 5 * mm + 2 * mm, stroke=1, fill=1)
    yy = y_ent - 2 * mm
    for ch in doc.entete:
        c.setFillColor(GRIS)
        rel.ecrire(x0 + 3 * mm, yy - 1.5 * mm, ch.libelle, r, 7.5)
        c.setFillColor(ENCRE)
        rel.ecrire(d - 3 * mm, yy - 1.5 * mm, ch.brut, b, 8.5, droite=True, chemin=ch.chemin)
        yy -= 5 * mm
    # destinataire
    yd = y - 5 * mm
    c.setFillColor(GRIS)
    rel.ecrire(g, yd, doc.destinataire_titre.upper(), b, 7.5)
    yd -= 4.5 * mm
    for k, ch in enumerate(doc.destinataire):
        c.setFillColor(ENCRE)
        police, taille = (b, 9) if k == 0 else (r, 8)
        if ch.libelle:
            from reportlab.pdfbase.pdfmetrics import stringWidth

            rel.ecrire(g, yd, ch.libelle, police, taille)
            rel.ecrire(
                g + stringWidth(ch.libelle + " ", police, taille),
                yd,
                ch.brut,
                police,
                taille,
                chemin=ch.chemin,
            )
        else:
            rel.ecrire(g, yd, ch.brut, police, taille, chemin=ch.chemin)
        yd -= 4.3 * mm
    y = min(yd, yy) - 8 * mm

    # tableaux
    for t in doc.tableaux:
        c.setFillColor(accent)
        rel.ecrire(g, y, t.titre, b, 9.5)
        y -= 3 * mm
        total = sum(col[2] for col in t.colonnes) * mm
        echelle = min(1.0, (d - g) / total)
        xs = [g]
        for col in t.colonnes:
            xs.append(xs[-1] + col[2] * mm * echelle)
        c.setFillColor(accent)
        c.rect(g, y - 5.5 * mm, xs[-1] - g, 5.5 * mm, stroke=0, fill=1)
        c.setFillColor(colors.white)
        for k, col in enumerate(t.colonnes):
            if col[3]:
                rel.ecrire(xs[k + 1] - 1.5 * mm, y - 3.8 * mm, col[1], b, 7.3, droite=True)
            else:
                rel.ecrire(xs[k] + 1.5 * mm, y - 3.8 * mm, col[1], b, 7.3)
        y -= 5.5 * mm
        for i, ligne in enumerate(t.lignes):
            if i % 2 == 1:
                c.setFillColor(FOND)
                c.rect(g, y - 5.5 * mm, xs[-1] - g, 5.5 * mm, stroke=0, fill=1)
            c.setFillColor(ENCRE)
            for k, col in enumerate(t.colonnes):
                v = ligne.get(col[0] or "", "")
                ch = f"{t.liste}[{i}].{col[0]}" if col[0] else None
                if col[3]:
                    rel.ecrire(xs[k + 1] - 1.5 * mm, y - 3.9 * mm, v, r, 8, droite=True, chemin=ch)
                else:
                    rel.ecrire(xs[k] + 1.5 * mm, y - 3.9 * mm, v, r, 8, chemin=ch)
            y -= 5.5 * mm
        c.setStrokeColor(FILET)
        c.line(g, y, xs[-1], y)
        y -= 8 * mm

    # totaux
    for ch in doc.totaux:
        c.setFillColor(GRIS)
        rel.ecrire(d - 34 * mm, y, ch.libelle, r, 8.5, droite=True)
        c.setFillColor(ENCRE)
        rel.ecrire(d, y, ch.brut, b, 9.5, droite=True, chemin=ch.chemin)
        y -= 5.5 * mm
    c.setStrokeColor(accent)
    c.setLineWidth(1.2)
    c.line(d - 80 * mm, y + 3.5 * mm, d, y + 3.5 * mm)

    # mentions, pied
    y -= 6 * mm
    c.setFillColor(GRIS)
    for m in doc.mentions:
        rel.ecrire(g, y, m, r, 7.5)
        y -= 4 * mm
    c.setStrokeColor(FILET)
    c.setLineWidth(0.5)
    c.line(g, 14 * mm, d, 14 * mm)
    rel.ecrire(g, 10 * mm, MENTION, r, 7)
    rel.ecrire(d, 10 * mm, "Page 1 / 1", r, 7, droite=True)
    c.showPage()
    c.save()
    return rel.zones


def generer_demo(racine: Path | str) -> Path:
    """Écrit le jeu de démonstration sous ``racine`` :

    - ``clients/DEMO/profil.json`` et ``clients/DEMO/grilles/grille.json`` ;
    - ``dossiers/<DEMO-n>/docs/*.pdf`` (un sous-dossier par dossier : frontière de regroupement).
    """
    racine = Path(racine)
    client = racine / "clients" / "DEMO"
    (client / "grilles").mkdir(parents=True, exist_ok=True)
    (client / "profil.json").write_text(
        json.dumps(profil_demo(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (client / "grilles" / "grille.json").write_text(
        json.dumps(grille_demo(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    for dossier in dossiers_demo():
        for doc in dossier.documents:
            dessiner_document(doc, racine / "dossiers" / dossier.nom / "docs" / doc.fichier)
    (racine / "LISEZMOI.txt").write_text(
        "Jeu de démonstration ControlDOne — DONNÉES FICTIVES.\n"
        "Sociétés, adresses, numéros et montants inventés. Régénérer : controldone demo.\n",
        encoding="utf-8",
    )
    return racine
