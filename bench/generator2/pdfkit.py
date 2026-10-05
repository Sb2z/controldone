"""Petite boîte à outils reportlab (déterministe : invariant=1, polices TTF embarquées)."""

from __future__ import annotations

import io
import math
import random

from reportlab.lib.colors import Color, HexColor, black, white
from reportlab.lib.pagesizes import A4, A5, landscape
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

from .util import FICTIF

_FONTS_OK = False
FONT_DIR = "/usr/share/fonts/truetype"


def register_fonts():
    global _FONTS_OK
    if _FONTS_OK:
        return
    spec = {
        "Sans": "liberation/LiberationSans-Regular.ttf", "Sans-B": "liberation/LiberationSans-Bold.ttf",
        "Sans-I": "liberation/LiberationSans-Italic.ttf",
        "Serif": "liberation/LiberationSerif-Regular.ttf", "Serif-B": "liberation/LiberationSerif-Bold.ttf",
        "Serif-I": "liberation/LiberationSerif-Italic.ttf",
        "Mono": "liberation/LiberationMono-Regular.ttf", "Mono-B": "liberation/LiberationMono-Bold.ttf",
        "DV": "dejavu/DejaVuSans.ttf", "DV-B": "dejavu/DejaVuSans-Bold.ttf",
        "DVM": "dejavu/DejaVuSansMono.ttf",
        "Free": "freefont/FreeSans.ttf", "Free-B": "freefont/FreeSansBold.ttf", "Free-I": "freefont/FreeSansOblique.ttf",
        "FSerif": "freefont/FreeSerif.ttf", "FSerif-B": "freefont/FreeSerifBold.ttf", "Hand": "freefont/FreeSerifItalic.ttf",
        "FMono": "freefont/FreeMono.ttf",
    }
    for name, rel in spec.items():
        pdfmetrics.registerFont(TTFont(name, f"{FONT_DIR}/{rel}"))
    pdfmetrics.registerFont(TTFont("CJK", f"{FONT_DIR}/wqy/wqy-zenhei.ttc", subfontIndex=0))
    _FONTS_OK = True


GREY = HexColor("#777777")
LIGHT = HexColor("#e8e8e8")


class Pdf:
    def __init__(self, *, land=False, size=A4, title="Document", family="Sans", mark=FICTIF, mark_pos="bottom",
                 lang_mark="fr"):
        register_fonts()
        self.buf = io.BytesIO()
        ps = landscape(size) if land else size
        self.W, self.H = ps
        self.c = canvas.Canvas(self.buf, pagesize=ps, invariant=1, pageCompression=1)
        self.c.setTitle(title)
        self.c.setAuthor(f"{FICTIF} - bench.generator2")
        self.c.setCreator("bench.generator2 (ControlDOne, données fictives)")
        self.c.setSubject(FICTIF)
        self.fam = family
        self.mark = mark
        self.mark_pos = mark_pos
        self.page_no = 1
        self.lang_mark = lang_mark
        self._mark()

    # -- marquage fictif sur chaque page
    def _mark(self):
        c = self.c
        c.saveState()
        c.setFillColor(GREY)
        c.setFont("DV", 6.5)
        txt = {"fr": "DONNÉES FICTIVES — document de test généré, sans valeur juridique ni commerciale",
               "en": "DONNÉES FICTIVES — fictitious test document, no legal or commercial value",
               "de": "DONNÉES FICTIVES — fiktives Testdokument, ohne rechtliche oder kommerzielle Bedeutung",
               "it": "DONNÉES FICTIVES — documento di prova fittizio, senza valore",
               "es": "DONNÉES FICTIVES — documento de prueba ficticio, sin valor",
               "nl": "DONNÉES FICTIVES — fictief testdocument, zonder waarde"}.get(self.lang_mark, FICTIF)
        if self.mark_pos == "bottom":
            c.drawCentredString(self.W / 2, 14, txt)
        else:
            c.drawCentredString(self.W / 2, self.H - 12, txt)
        c.restoreState()

    def new_page(self):
        self.c.showPage()
        self.page_no += 1
        self._mark()

    def f(self, style="", size=9):
        name = self.fam + ("-" + style if style else "")
        try:
            pdfmetrics.getFont(name)
        except KeyError:
            name = self.fam
        self.c.setFont(name, size)
        return name

    def text(self, x, y, s, size=9, style="", align="l", color=black, font=None):
        c = self.c
        if font:
            c.setFont(font, size)
        else:
            self.f(style, size)
        c.setFillColor(color)
        s = str(s)
        if align == "r":
            c.drawRightString(x, y, s)
        elif align == "c":
            c.drawCentredString(x, y, s)
        else:
            c.drawString(x, y, s)
        c.setFillColor(black)

    def width(self, s, size=9, style="", font=None):
        name = font or (self.fam + ("-" + style if style else ""))
        try:
            return pdfmetrics.stringWidth(str(s), name, size)
        except KeyError:
            return pdfmetrics.stringWidth(str(s), self.fam, size)

    def lines(self, x, y, items, size=9, style="", leading=None, align="l", color=black, font=None):
        leading = leading or size * 1.25
        for it in items:
            if it is None:
                continue
            self.text(x, y, it, size=size, style=style, align=align, color=color, font=font)
            y -= leading
        return y

    def wrap(self, s, w, size=9, style="", font=None):
        words = str(s).split()
        out, cur = [], ""
        for wd in words:
            t = (cur + " " + wd).strip()
            if self.width(t, size, style, font) <= w or not cur:
                cur = t
            else:
                out.append(cur)
                cur = wd
        if cur:
            out.append(cur)
        return out

    def para(self, x, y, w, s, size=9, style="", leading=None, color=black, font=None):
        leading = leading or size * 1.3
        for ln in self.wrap(s, w, size, style, font):
            self.text(x, y, ln, size=size, style=style, color=color, font=font)
            y -= leading
        return y

    def hline(self, x1, x2, y, lw=0.5, color=black):
        c = self.c
        c.setStrokeColor(color)
        c.setLineWidth(lw)
        c.line(x1, y, x2, y)
        c.setStrokeColor(black)

    def vline(self, x, y1, y2, lw=0.5, color=black):
        c = self.c
        c.setStrokeColor(color)
        c.setLineWidth(lw)
        c.line(x, y1, x, y2)
        c.setStrokeColor(black)

    def rect(self, x, y, w, h, lw=0.6, fill=None, stroke=True, color=black):
        c = self.c
        c.setLineWidth(lw)
        c.setStrokeColor(color)
        if fill is not None:
            c.setFillColor(fill)
        c.rect(x, y, w, h, stroke=1 if stroke else 0, fill=1 if fill is not None else 0)
        c.setFillColor(black)
        c.setStrokeColor(black)

    def table(self, x, y, cols, rows, *, size=8, head_size=None, row_h=None, head_fill=LIGHT, grid="h",
              head_style="B", zebra=None, bottom=60, on_break=None, head_color=black, wrap_col=None,
              repeat_head=True, cell_font=None):
        """cols : [(titre, largeur, alignement)] ; rows : listes de chaînes (None = cellule vide).
        Retourne y sous le tableau. Saut de page avec on_break(pdf) -> nouveau y."""
        head_size = head_size or size
        row_h = row_h or size * 1.75
        tw = sum(c[1] for c in cols)

        def head(yh):
            hh = row_h * (1 + max(str(c[0]).count("\n") for c in cols))
            if head_fill is not None:
                self.rect(x, yh - hh, tw, hh, lw=0.4, fill=head_fill, stroke=grid != "none")
            cx = x
            for title, w, al in cols:
                parts = str(title).split("\n")
                ty = yh - row_h * 0.68
                for p in parts:
                    if al == "r":
                        self.text(cx + w - 3, ty, p, size=head_size, style=head_style, align="r", color=head_color)
                    elif al == "c":
                        self.text(cx + w / 2, ty, p, size=head_size, style=head_style, align="c", color=head_color)
                    else:
                        self.text(cx + 3, ty, p, size=head_size, style=head_style, color=head_color)
                    ty -= row_h * 0.8
                cx += w
            return yh - hh

        y = head(y)
        top = y
        for i, row in enumerate(rows):
            # hauteur de la ligne (colonne à retour à la ligne)
            wrapped = {}
            nl = 1
            for j, (title, w, al) in enumerate(cols):
                cell = row[j] if j < len(row) else None
                if cell is None:
                    continue
                if wrap_col is not None and j == wrap_col:
                    wrapped[j] = self.wrap(cell, w - 6, size, font=cell_font)
                    nl = max(nl, len(wrapped[j]))
            h = row_h + (nl - 1) * size * 1.15
            if y - h < bottom:
                if grid == "full":
                    self._vgrid(x, cols, top, y)
                if on_break:
                    y = on_break(self)
                else:
                    self.new_page()
                    y = self.H - 60
                if repeat_head:
                    y = head(y)
                top = y
            if zebra is not None and i % 2 == 1:
                self.rect(x, y - h, tw, h, lw=0, fill=zebra, stroke=False)
            cx = x
            for j, (title, w, al) in enumerate(cols):
                cell = row[j] if j < len(row) else None
                if cell is not None:
                    if j in wrapped:
                        yy = y - row_h * 0.68
                        for ln in wrapped[j]:
                            self.text(cx + 3, yy, ln, size=size, font=cell_font)
                            yy -= size * 1.15
                    elif al == "r":
                        self.text(cx + w - 3, y - row_h * 0.68, cell, size=size, align="r", font=cell_font)
                    elif al == "c":
                        self.text(cx + w / 2, y - row_h * 0.68, cell, size=size, align="c", font=cell_font)
                    else:
                        self.text(cx + 3, y - row_h * 0.68, cell, size=size, font=cell_font)
                cx += w
            y -= h
            if grid in ("h", "full"):
                self.hline(x, x + tw, y, lw=0.25, color=GREY)
        if grid == "full":
            self._vgrid(x, cols, top, y)
            self.rect(x, y, tw, top - y, lw=0.5)
        return y

    def _vgrid(self, x, cols, top, bottom):
        cx = x
        for _, w, _ in cols[:-1]:
            cx += w
            self.vline(cx, bottom, top, lw=0.3, color=GREY)

    # -- effets
    def stamp(self, x, y, s, size=26, angle=18, color=HexColor("#c0392b"), alpha=0.55, box=True):
        c = self.c
        c.saveState()
        c.translate(x, y)
        c.rotate(angle)
        col = Color(color.red, color.green, color.blue, alpha=alpha)
        c.setFillColor(col)
        c.setStrokeColor(col)
        c.setFont("DV-B", size)
        w = pdfmetrics.stringWidth(s, "DV-B", size)
        c.drawCentredString(0, 0, s)
        if box:
            c.setLineWidth(2.2)
            c.roundRect(-w / 2 - 8, -size * 0.35, w + 16, size * 1.25, 6, stroke=1, fill=0)
        c.restoreState()

    def watermark(self, s, size=70, angle=35, alpha=0.12):
        c = self.c
        c.saveState()
        c.translate(self.W / 2, self.H / 2)
        c.rotate(angle)
        c.setFillColor(Color(0.3, 0.3, 0.3, alpha=alpha))
        c.setFont("DV-B", size)
        c.drawCentredString(0, 0, s)
        c.restoreState()

    def handwriting(self, x, y, s, rng: random.Random, size=13, angle=-4, color=HexColor("#1f3a93")):
        """Annotation manuscrite simulée (caractères irréguliers, ligne de base ondulée)."""
        c = self.c
        c.saveState()
        c.translate(x, y)
        c.rotate(angle)
        c.setFillColor(color)
        cx = 0.0
        for i, ch in enumerate(s):
            sz = size * (1 + rng.uniform(-0.08, 0.1))
            c.setFont("Hand", sz)
            dy = math.sin(i * 0.7) * 1.2 + rng.uniform(-0.6, 0.6)
            c.saveState()
            c.translate(cx, dy)
            c.rotate(rng.uniform(-6, 6))
            c.drawString(0, 0, ch)
            c.restoreState()
            cx += pdfmetrics.stringWidth(ch, "Hand", sz) * rng.uniform(0.92, 1.05)
        # trait de soulignement irrégulier
        c.setStrokeColor(color)
        c.setLineWidth(0.8)
        p = c.beginPath()
        p.moveTo(-2, -4)
        for k in range(1, 9):
            p.lineTo(cx * k / 8, -4 + rng.uniform(-1.4, 1.4))
        c.drawPath(p, stroke=1, fill=0)
        c.restoreState()

    def hidden_text(self, x, y, s):
        """Texte blanc (consigne cachée, §20.2) : doit rester sans effet."""
        c = self.c
        c.saveState()
        c.setFillColor(white)
        c.setFont("DV", 4)
        c.drawString(x, y, s)
        c.restoreState()

    def logo(self, x, y, label, rng: random.Random, color=None, size=30):
        c = self.c
        color = color or HexColor(rng.choice(["#1a5276", "#7d3c98", "#117864", "#b9770e", "#922b21", "#2e4053"]))
        c.saveState()
        c.setFillColor(color)
        shape = rng.choice(["circle", "square", "tri"])
        if shape == "circle":
            c.circle(x + size / 2, y + size / 2, size / 2, stroke=0, fill=1)
        elif shape == "square":
            c.roundRect(x, y, size, size, 5, stroke=0, fill=1)
        else:
            p = c.beginPath()
            p.moveTo(x, y)
            p.lineTo(x + size, y)
            p.lineTo(x + size / 2, y + size)
            p.close()
            c.drawPath(p, stroke=0, fill=1)
        c.setFillColor(white)
        c.setFont("DV-B", size * 0.42)
        c.drawCentredString(x + size / 2, y + size * 0.3, label[:2].upper())
        c.restoreState()
        return color

    def save(self) -> bytes:
        self.c.showPage()
        self.c.save()
        return self.buf.getvalue()
