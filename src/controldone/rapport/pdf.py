"""Rendu PDF du rapport (ReportLab) : même contenu que le HTML, pages numérotées et horodatées,
avertissement en pied de **chaque** page, bandeau « DONNÉES FICTIVES » pour une démonstration."""

from __future__ import annotations

import io
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas as rl_canvas
from reportlab.platypus import (
    BaseDocTemplate,
    CondPageBreak,
    Frame,
    Image,
    KeepTogether,
    NextPageTemplate,
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)

from controldone.formatage import format_montant
from controldone.rapport.vue import ConstatVue, DossierVue, RapportVue

__all__ = ["rendre_pdf"]

MARINE = colors.HexColor("#1d3557")
MARINE_2 = colors.HexColor("#2f4b73")
ENCRE = colors.HexColor("#1f2933")
ENCRE_2 = colors.HexColor("#52606d")
ENCRE_3 = colors.HexColor("#7b8794")
FILET = colors.HexColor("#d9dee5")
FOND_2 = colors.HexColor("#f5f7fa")
CERTAIN = colors.HexColor("#9b2226")
CERTAIN_FOND = colors.HexColor("#fbeaea")
VERIFIER = colors.HexColor("#9a5b00")
VERIFIER_FOND = colors.HexColor("#fff4e0")
RENVOI = colors.HexColor("#3d5a80")
RENVOI_FOND = colors.HexColor("#e8eef6")
CONFORME = colors.HexColor("#2d6a4f")
CONFORME_FOND = colors.HexColor("#e7f4ec")
DEMO = colors.HexColor("#b42318")

COULEURS_STATUT = {
    "ecart_certain": (CERTAIN, CERTAIN_FOND),
    "a_verifier": (VERIFIER, VERIFIER_FOND),
    "renvoi": (RENVOI, RENVOI_FOND),
    "conforme": (CONFORME, CONFORME_FOND),
}

MARGE_G, MARGE_D, MARGE_H, MARGE_B = 16 * mm, 16 * mm, 20 * mm, 27 * mm
LARGEUR = A4[0] - MARGE_G - MARGE_D

_POLICES: tuple[str, str, str, str] | None = None


def _polices() -> tuple[str, str, str, str]:
    """DejaVu Sans (couverture Unicode étendue) si présente, sinon Vera livrée avec ReportLab."""
    global _POLICES
    if _POLICES is not None:
        return _POLICES
    import reportlab

    candidats = [
        ("/usr/share/fonts/truetype/dejavu", "DejaVuSans.ttf", "DejaVuSans-Bold.ttf", "DejaVuSans-Oblique.ttf",
         "DejaVuSansMono.ttf"),
        (str(Path(reportlab.__file__).parent / "fonts"), "Vera.ttf", "VeraBd.ttf", "VeraIt.ttf", "Vera.ttf"),
    ]
    for dossier, n, b, i, m in candidats:
        chemins = [Path(dossier) / x for x in (n, b, i, m)]
        if all(p.exists() for p in chemins):
            noms = ("CD-Regular", "CD-Bold", "CD-Italic", "CD-Mono")
            for nom, p in zip(noms, chemins, strict=True):
                pdfmetrics.registerFont(TTFont(nom, str(p)))
            pdfmetrics.registerFontFamily("CD", normal="CD-Regular", bold="CD-Bold", italic="CD-Italic",
                                          boldItalic="CD-Bold")
            _POLICES = noms
            return noms
    _POLICES = ("Helvetica", "Helvetica-Bold", "Helvetica-Oblique", "Courier")
    return _POLICES


def _styles() -> dict[str, ParagraphStyle]:
    r, b, _i, m = _polices()
    base = ParagraphStyle("base", fontName=r, fontSize=8.8, leading=12, textColor=ENCRE)
    return {
        "base": base,
        "petit": ParagraphStyle("petit", parent=base, fontSize=7.6, leading=10, textColor=ENCRE_2),
        "mini": ParagraphStyle("mini", parent=base, fontSize=6.8, leading=8.6, textColor=ENCRE_3),
        "mono": ParagraphStyle("mono", parent=base, fontName=m, fontSize=7.6, leading=10),
        "gras": ParagraphStyle("gras", parent=base, fontName=b),
        "h1": ParagraphStyle("h1", parent=base, fontName=b, fontSize=28, leading=33, textColor=MARINE),
        "h2": ParagraphStyle("h2", parent=base, fontName=b, fontSize=15, leading=19, textColor=MARINE,
                             spaceBefore=6, spaceAfter=7),
        "h3": ParagraphStyle("h3", parent=base, fontName=b, fontSize=12, leading=15, textColor=MARINE,
                             spaceBefore=4, spaceAfter=4),
        "h4": ParagraphStyle("h4", parent=base, fontName=b, fontSize=9.6, leading=12.5, textColor=MARINE_2,
                             spaceBefore=8, spaceAfter=3),
        "marque": ParagraphStyle("marque", parent=base, fontName=b, fontSize=10, textColor=MARINE_2),
        "sous": ParagraphStyle("sous", parent=base, fontSize=13, leading=17, textColor=ENCRE_2),
        "carte_et": ParagraphStyle("carte_et", parent=base, fontSize=6.8, leading=8.5, textColor=ENCRE_2),
        "carte_val": ParagraphStyle("carte_val", parent=base, fontName=b, fontSize=14, leading=17),
        "droite": ParagraphStyle("droite", parent=base, alignment=TA_RIGHT),
        "droite_gras": ParagraphStyle("droite_gras", parent=base, fontName=b, fontSize=11, leading=14,
                                      alignment=TA_RIGHT),
        "avis": ParagraphStyle("avis", parent=base, fontSize=8.2, leading=11, textColor=ENCRE),
    }


def _p(texte: str | None, style: ParagraphStyle) -> Paragraph:
    return Paragraph(escape(texte or "").replace("\n", "<br/>"), style)


def _fm(x: Decimal | None) -> str:
    return "—" if x is None or x == 0 else format_montant(x, "EUR")


# --- gabarits de page -----------------------------------------------------------------------------------


class _Canevas(rl_canvas.Canvas):
    """Canevas qui connaît le nombre total de pages (« page n / N »)."""

    def __init__(self, *args, vue: RapportVue, horodatage: str, **kwargs):
        super().__init__(*args, **kwargs)
        self._pages: list[dict] = []
        self._vue = vue
        self._horo = horodatage

    def showPage(self):
        self._pages.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        total = len(self._pages)
        for etat in self._pages:
            self.__dict__.update(etat)
            self._decor(total)
            super().showPage()
        super().save()

    def _decor(self, total: int) -> None:
        r, b, _i, _m = _polices()
        v = self._vue
        largeur, hauteur = A4
        if v.demo:
            self.setFillColor(DEMO)
            self.rect(0, hauteur - 9 * mm, largeur, 9 * mm, stroke=0, fill=1)
            self.setFillColor(colors.white)
            self.setFont(b, 8.5)
            self.drawCentredString(largeur / 2, hauteur - 6 * mm, "DONNÉES FICTIVES — DÉMONSTRATION")
        if self._pageNumber > 1:
            self.setFillColor(ENCRE_3)
            self.setFont(r, 7)
            y = hauteur - (13 if v.demo else 10) * mm
            self.drawString(MARGE_G, y, f"ControlDOne · {v.titre} · {v.client}")
            self.drawRightString(largeur - MARGE_D, y, v.date)
            self.setStrokeColor(FILET)
            self.setLineWidth(0.5)
            self.line(MARGE_G, y - 2.2 * mm, largeur - MARGE_D, y - 2.2 * mm)
        # pied : avertissement obligatoire sur chaque page
        st = ParagraphStyle("pied", fontName=r, fontSize=6.3, leading=7.8, textColor=ENCRE_2)
        texte = escape(v.avertissement)
        if v.demo:
            texte = f'<font name="{b}" color="#b42318">DONNÉES FICTIVES.</font> ' + texte
        par = Paragraph(texte, st)
        _w, h = par.wrap(LARGEUR - 30 * mm, 30 * mm)
        self.setStrokeColor(FILET)
        self.line(MARGE_G, 8 * mm + h + 2.5 * mm, largeur - MARGE_D, 8 * mm + h + 2.5 * mm)
        par.drawOn(self, MARGE_G, 8 * mm)
        self.setFont(r, 7)
        self.setFillColor(ENCRE_2)
        self.drawRightString(largeur - MARGE_D, 8 * mm + h - 7, f"Page {self._pageNumber} / {total}")
        self.drawRightString(largeur - MARGE_D, 8 * mm, self._horo)


# --- blocs ---------------------------------------------------------------------------------------------------


def _table(donnees, largeurs, *, entete=True, alignes_droite=(), style_extra=()):
    r, b, _i, _m = _polices()
    t = Table(donnees, colWidths=largeurs, repeatRows=1 if entete else 0)
    cmds = [
        ("FONT", (0, 0), (-1, -1), r, 8.2),
        ("TEXTCOLOR", (0, 0), (-1, -1), ENCRE),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LINEBELOW", (0, 0), (-1, -1), 0.4, FILET),
        ("TOPPADDING", (0, 0), (-1, -1), 3.2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3.2),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
    ]
    if entete:
        cmds += [("BACKGROUND", (0, 0), (-1, 0), FOND_2), ("FONT", (0, 0), (-1, 0), b, 7.6),
                 ("TEXTCOLOR", (0, 0), (-1, 0), ENCRE_2)]
    for c in alignes_droite:
        cmds.append(("ALIGN", (c, 0), (c, -1), "RIGHT"))
    t.setStyle(TableStyle(cmds + list(style_extra)))
    return t


def _badge(texte: str, code: str, s, h_align: str = "LEFT") -> Table:
    fg, bg = COULEURS_STATUT.get(code, (ENCRE_2, FOND_2))
    st = ParagraphStyle("badge", parent=s["gras"], fontSize=7.4, leading=9, textColor=fg)
    largeur = pdfmetrics.stringWidth(texte, st.fontName, st.fontSize) + 10
    t = Table([[Paragraph(escape(texte), st)]], colWidths=[largeur], hAlign=h_align)
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), bg), ("BOX", (0, 0), (-1, -1), 0.4, fg),
                           ("TOPPADDING", (0, 0), (-1, -1), 1.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
                           ("LEFTPADDING", (0, 0), (-1, -1), 5), ("RIGHTPADDING", (0, 0), (-1, -1), 5)]))
    return t


def _image(png: bytes, largeur_max: float, hauteur_max: float = 38 * mm) -> Image:
    from PIL import Image as PILImage

    with PILImage.open(io.BytesIO(png)) as im:
        w, h = im.size
    ratio = min(largeur_max / w, hauteur_max / h, 0.5)  # rendu à 144 dpi : 1 px = 0,5 pt
    return Image(io.BytesIO(png), width=w * ratio, height=h * ratio)


def _constat(c: ConstatVue, s) -> KeepTogether:
    code = "renvoi" if c.renvoi else c.niveau_code
    fg, _bg = COULEURS_STATUT.get(code, (VERIFIER, VERIFIER_FOND))
    inner = LARGEUR - 6 * mm
    tete = Table(
        [[_badge("Renvoi" if c.renvoi else c.niveau, code, s),
          Paragraph(f"<b>{escape(c.controle_id)} — {escape(c.controle_libelle)}</b>"
                    + (f"<br/><font size='7' color='#52606d'>Dossier {escape(c.dossier_reference)}</font>"
                       if c.renvoi else ""), ParagraphStyle("t", parent=s["base"], textColor=MARINE)),
          _p(c.montant, s["droite_gras"])]],
        colWidths=[27 * mm, inner - 27 * mm - 36 * mm, 36 * mm],
    )
    tete.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0),
                              ("RIGHTPADDING", (0, 0), (-1, -1), 0)]))
    blocs = [tete, Spacer(1, 3), _p(c.libelle, s["base"])]
    if c.raisons:
        blocs.append(_p(" ; ".join(c.raisons), ParagraphStyle("r", parent=s["petit"], textColor=VERIFIER)))
    meta = [c.nature] + ([c.composante] if c.composante else []) + \
        ([f"Tolérance : {c.tolerance}"] if c.tolerance else []) + \
        ([f"Seuil de certitude : {c.seuil}"] if c.seuil else [])
    blocs.append(_p("   ·   ".join(meta), s["petit"]))
    if c.preuves:
        cellules = []
        col = (inner - 4 * mm) / 2
        for p in c.preuves:
            morceaux = [_p(p.role.upper(), s["mini"]), _p(p.document, s["gras"])]
            if p.fichier:
                morceaux.append(_p(f"{p.fichier}" + (f", page {p.page}" if p.page else ""), s["mono"]))
            if p.valeur_lue:
                morceaux.append(Paragraph(f"Valeur lue : <b>{escape(p.valeur_lue)}</b>", s["base"]))
            if p.calcul:
                morceaux.append(_p(f"Calcul : {p.calcul}", s["base"]))
            if p.image:
                morceaux.append(Spacer(1, 2))
                morceaux.append(_image(p.image, col - 8))
            cellules.append(morceaux)
        lignes = [cellules[k:k + 2] + ([[]] if len(cellules[k:k + 2]) == 1 else []) for k in range(0, len(cellules), 2)]
        tp = Table(lignes, colWidths=[col, col], hAlign="LEFT")
        cmds = [("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4), ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4)]
        for ri, ligne in enumerate(lignes):
            for ci, cell in enumerate(ligne):
                if cell:
                    cmds.append(("BOX", (ci, ri), (ci, ri), 0.4, FILET))
        tp.setStyle(TableStyle(cmds))
        blocs += [Spacer(1, 4), tp]
    if c.prochaine_action:
        act = Table([[Paragraph(f"<b>Prochaine action :</b> {escape(c.prochaine_action)}", s["petit"])]],
                    colWidths=[inner])
        act.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), FOND_2), ("LEFTPADDING", (0, 0), (-1, -1), 5),
                                 ("RIGHTPADDING", (0, 0), (-1, -1), 5)]))
        blocs += [Spacer(1, 4), act]
    cadre = Table([[blocs]], colWidths=[LARGEUR])
    cadre.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.5, FILET), ("LINEBEFORE", (0, 0), (0, -1), 3.2, fg),
        ("LEFTPADDING", (0, 0), (-1, -1), 3 * mm), ("RIGHTPADDING", (0, 0), (-1, -1), 2.5 * mm),
        ("TOPPADDING", (0, 0), (-1, -1), 2.5 * mm), ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5 * mm),
    ]))
    return KeepTogether([cadre, Spacer(1, 5)])


def _cartes(v: RapportVue, s) -> Table:
    def carte(etiquette, valeur, note, couleur):
        return [_p(etiquette.upper(), s["carte_et"]), _p(valeur, s["carte_val"]), _p(note, s["mini"]), couleur]

    statuts = "<br/>".join(f"{escape(lib)} : <b>{n}</b>" for lib, _c, n in v.statuts)
    cartes = [
        carte("Montant recouvrable certain", v.recouvrable_certain, "écarts refacturés, preuve complète", CERTAIN),
        carte("Montant recouvrable à vérifier", v.recouvrable_a_verifier, "affiché à part, jamais additionné",
              VERIFIER),
        [_p("DOSSIERS PAR STATUT", s["carte_et"]), Paragraph(statuts, s["petit"]), _p("", s["mini"]), ENCRE_3],
        carte("Écarts de valeur entre documents", str(v.ecarts_documentaires_nb),
              f"montant absolu : {v.ecarts_documentaires}", MARINE_2),
        carte("Écarts de calcul sur la déclaration", str(v.ecarts_calcul_nb), f"montant absolu : {v.ecarts_calcul}",
              colors.HexColor("#6b7c93")),
        carte("Points à faire vérifier par un professionnel", str(v.nb_renvois), "sans montant", RENVOI),
    ]
    gout = 4 * mm
    larg = (LARGEUR - 2 * gout) / 3
    lignes, cmds = [], [("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0),
                        ("RIGHTPADDING", (0, 0), (-1, -1), 0)]
    for k in range(0, 6, 3):
        trio = [c[:3] for c in cartes[k:k + 3]]
        lignes.append([trio[0], "", trio[1], "", trio[2]])
        lignes.append(["", "", "", "", ""])
    for idx, c in enumerate(cartes):
        r_, c_ = divmod(idx, 3)
        r_, c_ = 2 * r_, 2 * c_
        cmds += [("BOX", (c_, r_), (c_, r_), 0.5, FILET), ("LINEABOVE", (c_, r_), (c_, r_), 3, c[3]),
                 ("TOPPADDING", (c_, r_), (c_, r_), 6), ("BOTTOMPADDING", (c_, r_), (c_, r_), 7),
                 ("LEFTPADDING", (c_, r_), (c_, r_), 7), ("RIGHTPADDING", (c_, r_), (c_, r_), 5)]
    t = Table(lignes, colWidths=[larg, gout, larg, gout, larg], rowHeights=[None, gout, None, 2],
              spaceBefore=2, spaceAfter=4)
    t.setStyle(TableStyle(cmds))
    return t


def _h2(num: int, titre: str, s) -> Paragraph:
    return Paragraph(f'<font color="#7b8794">{num}</font>  {escape(titre)}', s["h2"])


def _filet():
    t = Table([[""]], colWidths=[LARGEUR], rowHeights=[1.2])
    t.setStyle(TableStyle([("LINEABOVE", (0, 0), (-1, -1), 1.4, MARINE)]))
    return t


def _dossier(d: DossierVue, s) -> list:
    out: list = [PageBreak()]
    entete = Table([[Paragraph(f"Dossier {escape(d.reference)}", s["h3"]), _badge(d.statut, d.statut_code, s, "RIGHT")]],
                   colWidths=[LARGEUR - 40 * mm, 40 * mm])
    entete.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("ALIGN", (1, 0), (1, 0), "RIGHT"),
                                ("LINEBELOW", (0, 0), (-1, 0), 1.4, MARINE), ("LEFTPADDING", (0, 0), (-1, -1), 0)]))
    out.append(entete)
    out.append(Spacer(1, 4))
    cles = Table([[Paragraph(f'<font size="6.5" color="#7b8794">{escape(k.upper())}</font><br/>{escape(v)}',
                             s["petit"]) for k, v in d.cles]], colWidths=[LARGEUR / 4] * 4)
    cles.setStyle(TableStyle([("LEFTPADDING", (0, 0), (-1, -1), 0), ("VALIGN", (0, 0), (-1, -1), "TOP")]))
    out.append(cles)
    if d.transitaire:
        out.append(_p(f"Transitaire : {d.transitaire}", s["petit"]))
    if d.documents_manquants:
        out.append(_p(f"Documents manquants : {', '.join(d.documents_manquants)}.", s["gras"]))
    out.append(Paragraph("Documents et rattachements", s["h4"]))
    lignes = [["Type", "Fichier", "Pages", "Classement", "Rattachement"]]
    for doc in d.documents:
        lien = f'<font color="#9a5b00"><b>{escape(doc.lien)}</b></font>' if doc.faible else escape(doc.lien)
        lignes.append([_p(doc.type, s["base"]), _p(doc.fichier, s["mono"]), doc.pages, doc.confiance,
                       Paragraph(f"{lien}<br/><font size='7' color='#52606d'>{escape(doc.signaux)}</font>", s["base"])])
    out.append(_table(lignes, [34 * mm, 58 * mm, 14 * mm, 20 * mm, LARGEUR - 126 * mm], alignes_droite=(2, 3)))
    out.append(Paragraph("Constats", s["h4"]))
    if d.constats:
        out += [_constat(c, s) for c in d.constats]
    else:
        out.append(_p("Aucun constat sur ce dossier.", s["petit"]))
    if d.cote_a_cote:
        out.append(CondPageBreak(30 * mm))
        out.append(Paragraph("Lignes de facture et articles de déclaration (rapprochés par SH6)", s["h4"]))
        lignes = [["SH6", "Facture commerciale", "Déclaration"]]
        lignes += [[_p(x.sh6, s["mono"]), _p(x.facture, s["petit"]), _p(x.declaration, s["petit"])]
                   for x in d.cote_a_cote]
        out.append(_table(lignes, [16 * mm, (LARGEUR - 16 * mm) / 2, (LARGEUR - 16 * mm) / 2]))
    out.append(CondPageBreak(30 * mm))
    out.append(Paragraph(f"Contrôles exécutés ({len(d.resultats)})", s["h4"]))
    couleur = {"conforme": "#2d6a4f", "ecart_certain": "#9b2226", "a_verifier": "#9a5b00",
               "non_verifiable": "#52606d", "non_applicable": "#7b8794"}
    lignes = [["Contrôle", "Résultat", "Attendu", "Constaté", "Motif"]]  # en-tête
    for x in d.resultats:
        lignes.append([
            Paragraph(f"<b>{escape(x.controle_id)}</b> {escape(x.libelle)}", s["petit"]),
            Paragraph(f'<font color="{couleur.get(x.resultat_code, "#1f2933")}">{escape(x.resultat)}</font>',
                      s["petit"]),
            _p(x.attendu, s["mono"]), _p(x.constate, s["mono"]), _p(x.raison, s["mini"]),
        ])
    out.append(_table(lignes, [58 * mm, 24 * mm, 26 * mm, 26 * mm, LARGEUR - 134 * mm]))
    out.append(_p("État du recouvrement : aucune demande d'avoir enregistrée pour ce dossier.", s["petit"]))
    return out


def _histoire(v: RapportVue, s) -> list:
    r_, _b, _i, _m = _polices()
    h: list = []
    # couverture
    h.append(Spacer(1, 6 * mm))
    h.append(Paragraph('CONTROLDONE <font color="#7b8794" size="8.5">contrôle technique de cohérence des documents '
                       "d'import</font>", s["marque"]))
    h.append(Spacer(1, 42 * mm))
    h.append(_p(v.titre, s["h1"]))
    h.append(Spacer(1, 3 * mm))
    h.append(_p(v.client, s["sous"]))
    h.append(Spacer(1, 12 * mm))
    fiche = [["Client", Paragraph(f"<b>{escape(v.client)}</b>", s["base"])], ["Période couverte", v.periode],
             ["Offre", v.offre], ["Dossiers analysés", str(v.nb_dossiers)], ["Date du rapport", v.date],
             ["Versions", _p(" · ".join(f"{k} {x}" for k, x in v.versions.items()), s["petit"])],
             ["Exécution", _p(", ".join(v.execution_ids), s["mono"])]]
    t = Table(fiche, colWidths=[52 * mm, LARGEUR - 52 * mm])
    t.setStyle(TableStyle([("FONT", (0, 0), (-1, -1), r_, 10), ("TEXTCOLOR", (0, 0), (0, -1), ENCRE_2),
                           ("LINEABOVE", (0, 0), (-1, 0), 2.2, MARINE), ("LINEBELOW", (0, 0), (-1, -1), 0.4, FILET),
                           ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                           ("LEFTPADDING", (0, 0), (-1, -1), 1), ("VALIGN", (0, 0), (-1, -1), "TOP")]))
    h.append(t)
    h.append(Spacer(1, 26 * mm))
    avis = []
    if v.demo:
        avis.append(Paragraph('<font color="#b42318"><b>Données fictives.</b></font> Toutes les sociétés, adresses, '
                              "numéros et montants de ce rapport sont inventés pour la démonstration.", s["avis"]))
    if v.mention_validation:
        avis.append(_p(v.mention_validation, s["avis"]))
    avis.append(Paragraph(f"<b>Avertissement.</b> {escape(v.avertissement)}", s["avis"]))
    for a in avis:
        bloc = Table([[a]], colWidths=[LARGEUR])
        bloc.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), FOND_2),
                                  ("LINEBEFORE", (0, 0), (0, -1), 3, DEMO if "fictives" in a.text else MARINE),
                                  ("LEFTPADDING", (0, 0), (-1, -1), 7), ("TOPPADDING", (0, 0), (-1, -1), 5),
                                  ("BOTTOMPADDING", (0, 0), (-1, -1), 6)]))
        h += [bloc, Spacer(1, 4)]
    h.append(NextPageTemplate("normal"))
    h.append(PageBreak())

    # 1. synthèse
    h.append(_h2(1, "Synthèse", s))
    h.append(_cartes(v, s))
    h.append(_p("Les montants de natures différentes ne sont jamais additionnés entre eux. Les écarts de valeur entre "
                "documents et les écarts de calcul ne sont pas des montants de droits.", s["petit"]))
    for titre, lignes in (("Écarts refacturés par composante", v.par_composante), ("Par transitaire", v.par_transitaire),
                          ("Par mois de facture", v.par_mois)):
        if lignes:
            h.append(Paragraph(titre, s["h4"]))
            h.append(_table([["", "Certain", "À vérifier"], *[[_p(k, s["base"]), c, a] for k, c, a in lignes]],
                            [LARGEUR - 70 * mm, 35 * mm, 35 * mm], alignes_droite=(1, 2)))
    # 2. actions
    h.append(_h2(2, "Prochaines actions", s))
    if v.actions:
        for a in v.actions:
            corps = [Paragraph(f"<b>{escape(a.titre)}</b>", s["base"])]
            corps += [Paragraph(f"• {escape(x)}", s["petit"]) for x in a.details]
            t = Table([[Paragraph(f'<font color="white"><b>{a.priorite}</b></font>', s["base"]), corps]],
                      colWidths=[11 * mm, LARGEUR - 11 * mm])
            t.setStyle(TableStyle([("BACKGROUND", (0, 0), (0, 0), MARINE), ("VALIGN", (0, 0), (-1, -1), "TOP"),
                                   ("BOX", (0, 0), (-1, -1), 0.5, FILET), ("ALIGN", (0, 0), (0, 0), "CENTER"),
                                   ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 5)]))
            h += [KeepTogether(t), Spacer(1, 4)]
    else:
        h.append(_p("Aucune action à mener.", s["petit"]))
    # 3. nature
    h.append(_h2(3, "Constats par nature", s))
    h.append(_table([["Nature", "Constats", "Montant", "Précision"],
                     *[[_p(x.libelle, s["base"]), str(x.nombre), x.montant, _p(x.note, s["petit"])]
                       for x in v.table_nature]],
                    [62 * mm, 18 * mm, 30 * mm, LARGEUR - 110 * mm], alignes_droite=(1, 2)))
    # 4. tableau des dossiers
    h.append(CondPageBreak(40 * mm))
    h.append(_h2(4, "Tableau des dossiers", s))
    lignes = [[Paragraph(f"<b>{x}</b>", s["mini"]) for x in
               ("Dossier", "Clés (facture transitaire · transport · MRN · facture)", "TVA acheteur / importateur",
                "Facturé / déclaré", "Statut", "Recouvrable")]]
    for d in v.dossiers:
        cles = " · ".join(x for _k, x in d.cles)
        rec = escape(_fm(d.recouvrable_certain)) + (f"<br/><font size='7' color='#52606d'>à vérifier : "
                                            f"{_fm(d.recouvrable_a_verifier)}</font>" if d.recouvrable_a_verifier else "")
        lignes.append([
            _p(d.reference, ParagraphStyle("ref", parent=s["mono"], fontSize=6.9)),
            Paragraph(escape(cles) + (f"<br/><font size='6.8' color='#7b8794'>{escape(d.raisons)}</font>"
                                      if d.raisons != "—" else ""), s["petit"]),
            _p(f"{d.tva_acheteur}\n{d.tva_importateur}", s["mono"]),
            Paragraph(f"{escape(d.montant_facture)}<br/>{escape(d.montant_declare)}", s["droite"]),
            _badge(d.statut, d.statut_code, s), Paragraph(rec, s["droite"]),
        ])
    h.append(_table(lignes, [25 * mm, 44 * mm, 28 * mm, 27 * mm, 26 * mm, LARGEUR - 150 * mm]))
    # 5. fiches
    h.append(PageBreak())
    h.append(_h2(5, "Fiches dossiers", s))
    for k, d in enumerate(v.dossiers):
        bloc = _dossier(d, s)
        h += bloc[1:] if k == 0 else bloc
    # 6. renvois
    h.append(PageBreak())
    h.append(_h2(6, "Points à faire vérifier par un professionnel", s))
    renv = Table([[_p(v.phrase_renvoi, s["avis"])]], colWidths=[LARGEUR])
    renv.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), RENVOI_FOND), ("LINEBEFORE", (0, 0), (0, -1), 3, RENVOI),
                              ("LEFTPADDING", (0, 0), (-1, -1), 7), ("TOPPADDING", (0, 0), (-1, -1), 5),
                              ("BOTTOMPADDING", (0, 0), (-1, -1), 6)]))
    h += [renv, Spacer(1, 6)]
    h += [_constat(c, s) for c in v.renvois] or [_p("Aucun point réglementaire relevé.", s["petit"])]
    # 7. non lus
    h.append(CondPageBreak(40 * mm))
    h.append(_h2(7, "Documents non lus ou non reconnus", s))
    if v.non_lus:
        h.append(_table([["Fichier", "Motif", "Pages"], *[[_p(f, s["mono"]), _p(m, s["base"]), p] for f, m, p in v.non_lus]],
                        [80 * mm, LARGEUR - 100 * mm, 20 * mm], alignes_droite=(2,)))
    else:
        h.append(_p("Tous les fichiers reçus ont été lus et reconnus.", s["petit"]))
    # 8. méthode
    h.append(CondPageBreak(60 * mm))
    h.append(_h2(8, "Méthode et tolérances", s))
    for x in v.limites:
        h.append(Paragraph(f"• {escape(x)}", s["base"]))
    h.append(Paragraph("Tolérances appliquées", s["h4"]))
    h.append(_table([["Tolérance", "Valeur"], *[[_p(k, s["base"]), x] for k, x in v.tolerances]],
                    [LARGEUR - 40 * mm, 40 * mm], alignes_droite=(1,)))
    h.append(_p(f"Empreinte du profil de tolérances : {v.empreinte}", s["mono"]))
    h.append(Paragraph("Versions", s["h4"]))
    vers = [[k, x] for k, x in v.versions.items()] + [[f"extracteur {k}", x] for k, x in v.extracteurs]
    vers.append(["modèle de langage", v.modele_llm])
    h.append(_table([["Composant", "Version"], *[[_p(a, s["base"]), _p(b, s["mono"])] for a, b in vers]],
                    [60 * mm, LARGEUR - 60 * mm]))
    # 9. avertissement
    h.append(CondPageBreak(30 * mm))
    h.append(_h2(9, "Avertissement", s))
    h.append(_p(v.avertissement, s["base"]))
    return h


def rendre_pdf(vue: RapportVue, *, horodatage: datetime | None = None) -> bytes:
    s = _styles()
    tampon = io.BytesIO()
    doc = BaseDocTemplate(
        tampon, pagesize=A4, leftMargin=MARGE_G, rightMargin=MARGE_D, topMargin=MARGE_H, bottomMargin=MARGE_B,
        title=f"{vue.titre} — {vue.client}", author="ControlDOne", subject=vue.titre, creator="ControlDOne",
    )
    cadre = Frame(MARGE_G, MARGE_B, LARGEUR, A4[1] - MARGE_H - MARGE_B, id="corps", leftPadding=0, rightPadding=0,
                  topPadding=0, bottomPadding=0)
    doc.addPageTemplates([PageTemplate(id="couverture", frames=[cadre]), PageTemplate(id="normal", frames=[cadre])])
    horo = (horodatage or datetime.now()).strftime("édité le %d/%m/%Y à %H:%M")
    doc.build(_histoire(vue, s), canvasmaker=lambda *a, **k: _Canevas(*a, vue=vue, horodatage=horo, **k))
    return tampon.getvalue()
