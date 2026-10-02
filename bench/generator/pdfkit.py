"""Petite boîte à outils de mise en page ReportLab (coordonnées en mm depuis le haut)."""

from __future__ import annotations

import io

from reportlab.lib.colors import Color, black, white
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

MARKER = "DONNÉES FICTIVES — DOCUMENT DE TEST"
_FONTS_DONE = False

FONT_FILES = {
    "LSans": "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    "LSans-B": "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "LSerif": "/usr/share/fonts/truetype/liberation/LiberationSerif-Regular.ttf",
    "LSerif-B": "/usr/share/fonts/truetype/liberation/LiberationSerif-Bold.ttf",
    "DSans": "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "DSans-B": "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "DMono": "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
    "DMono-B": "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf",
    "LMono": "/usr/share/fonts/truetype/liberation/LiberationMono-Regular.ttf",
    "LMono-B": "/usr/share/fonts/truetype/liberation/LiberationMono-Bold.ttf",
}

THEMES = {
    "sans": ("LSans", "LSans-B"),
    "dejavu": ("DSans", "DSans-B"),
    "serif": ("LSerif", "LSerif-B"),
    "mono": ("DMono", "DMono-B"),
    "lmono": ("LMono", "LMono-B"),
}

GREY = Color(0.45, 0.45, 0.45)
LIGHT = Color(0.9, 0.9, 0.9)
LIGHT2 = Color(0.95, 0.95, 0.97)
BLUE = Color(0.12, 0.25, 0.5)
DARK = Color(0.2, 0.2, 0.2)


def register_fonts():
    global _FONTS_DONE
    if _FONTS_DONE:
        return
    for name, path in FONT_FILES.items():
        pdfmetrics.registerFont(TTFont(name, path))
    _FONTS_DONE = True


class Pen:
    def __init__(self, theme="sans", landscape_mode=False, title="Document", author="Générateur de corpus fictif"):
        register_fonts()
        self.buf = io.BytesIO()
        self.pagesize = landscape(A4) if landscape_mode else A4
        self.c = canvas.Canvas(self.buf, pagesize=self.pagesize, invariant=1, pageCompression=1)
        self.c.setTitle(title)
        self.c.setAuthor(author)
        self.c.setCreator("bench.generator (FICTIF)")
        self.c.setProducer("ReportLab")
        self.W = self.pagesize[0] / mm
        self.H = self.pagesize[1] / mm
        self.set_theme(theme)
        self.page = 1
        self.dirty = False

    def set_theme(self, theme):
        self.f, self.fb = THEMES[theme]

    # -- pages
    def new_page(self, landscape_mode=None):
        self.footer_marker()
        self.c.showPage()
        if landscape_mode is not None:
            self.pagesize = landscape(A4) if landscape_mode else A4
            self.c.setPageSize(self.pagesize)
            self.W = self.pagesize[0] / mm
            self.H = self.pagesize[1] / mm
        self.page += 1
        self.dirty = False

    def footer_marker(self):
        c = self.c
        c.setFillColor(GREY)
        c.setFont(self.f, 6.5)
        c.drawCentredString(self.W * mm / 2, 5 * mm, MARKER)
        c.setFillColor(black)

    def finish(self) -> bytes:
        self.footer_marker()
        self.c.showPage()
        self.c.save()
        return self.buf.getvalue()

    # -- primitives
    def _y(self, y):
        return (self.H - y) * mm

    def text(self, x, y, s, size=9, bold=False, align="left", color=None, font=None, maxw=None):
        self.dirty = True
        fn = font or (self.fb if bold else self.f)
        s = "" if s is None else str(s)
        if maxw is not None:
            s = fit(s, fn, size, maxw)
        c = self.c
        if color is not None:
            c.setFillColor(color)
        c.setFont(fn, size)
        if align == "right":
            c.drawRightString(x * mm, self._y(y), s)
        elif align == "center":
            c.drawCentredString(x * mm, self._y(y), s)
        else:
            c.drawString(x * mm, self._y(y), s)
        if color is not None:
            c.setFillColor(black)

    def lines(self, x, y, items, size=9, leading=None, bold_first=False, maxw=None, color=None):
        leading = leading or size * 0.45
        for i, s in enumerate(items):
            self.text(x, y + i * leading, s, size=size, bold=(bold_first and i == 0), maxw=maxw, color=color)
        return y + len(items) * leading

    def rect(self, x, y, w, h, fill=None, stroke=True, lw=0.5, stroke_color=None):
        c = self.c
        c.setLineWidth(lw)
        if stroke_color is not None:
            c.setStrokeColor(stroke_color)
        if fill is not None:
            c.setFillColor(fill)
        c.rect(x * mm, self._y(y + h), w * mm, h * mm, stroke=1 if stroke else 0, fill=1 if fill is not None else 0)
        c.setFillColor(black)
        c.setStrokeColor(black)

    def hline(self, x1, x2, y, lw=0.5, color=None):
        c = self.c
        c.setLineWidth(lw)
        if color is not None:
            c.setStrokeColor(color)
        c.line(x1 * mm, self._y(y), x2 * mm, self._y(y))
        c.setStrokeColor(black)

    def vline(self, x, y1, y2, lw=0.5):
        self.c.setLineWidth(lw)
        self.c.line(x * mm, self._y(y1), x * mm, self._y(y2))

    def logo(self, x, y, label, w=38, h=12, color=BLUE):
        self.rect(x, y, w, h, fill=color, stroke=False)
        self.text(x + w / 2, y + h / 2 + 1.5, label, size=9, bold=True, align="center", color=white,
                  maxw=w - 2)

    def table(self, x, y, cols, rows, size=8, row_h=None, header=True, header_fill=LIGHT, grid="full",
              bold_rows=(), pad=1.2, header_size=None, fill_rows=None):
        """cols : [(titre, largeur_mm, align)] ; rows : listes de chaînes. Retourne le y de fin."""
        row_h = row_h or size * 0.5 + 1.6
        total_w = sum(c[1] for c in cols)
        cy = y
        if header:
            hs = header_size or size
            self.rect(x, cy, total_w, row_h, fill=header_fill, stroke=(grid != "none"), lw=0.4)
            cx = x
            for (title, w, al) in cols:
                self._cell(cx, cy, w, row_h, title, hs, True, al, pad)
                cx += w
            cy += row_h
        for i, row in enumerate(rows):
            if fill_rows and i in fill_rows:
                self.rect(x, cy, total_w, row_h, fill=LIGHT2, stroke=False)
            cx = x
            for (title, w, al), val in zip(cols, row):
                self._cell(cx, cy, w, row_h, val, size, i in bold_rows, al, pad)
                cx += w
            if grid == "full":
                self.rect(x, cy, total_w, row_h, lw=0.3)
                cx = x
                for (_, w, _) in cols[:-1]:
                    cx += w
                    self.vline(cx, cy, cy + row_h, lw=0.3)
            elif grid == "h":
                self.hline(x, x + total_w, cy + row_h, lw=0.2, color=GREY)
            cy += row_h
        if grid == "full" and header:
            cx = x
            for (_, w, _) in cols[:-1]:
                cx += w
                self.vline(cx, y, y + row_h, lw=0.3)
        return cy

    def _cell(self, x, y, w, h, val, size, bold, align, pad):
        if val is None:
            return
        yy = y + h / 2 + size * 0.13
        if align == "right":
            self.text(x + w - pad, yy, val, size=size, bold=bold, align="right", maxw=w - 2 * pad)
        elif align == "center":
            self.text(x + w / 2, yy, val, size=size, bold=bold, align="center", maxw=w - 2 * pad)
        else:
            self.text(x + pad, yy, val, size=size, bold=bold, maxw=w - 2 * pad)

    def paragraph(self, x, y, text, width, size=8, leading=None, bold=False):
        leading = leading or size * 0.42
        fn = self.fb if bold else self.f
        words = text.split()
        line = ""
        out = []
        for w in words:
            t = (line + " " + w).strip()
            if pdfmetrics.stringWidth(t, fn, size) / mm > width:
                out.append(line)
                line = w
            else:
                line = t
        if line:
            out.append(line)
        for i, l in enumerate(out):
            self.text(x, y + i * leading, l, size=size, bold=bold)
        return y + len(out) * leading


def fit(s, font, size, maxw):
    if pdfmetrics.stringWidth(s, font, size) / mm <= maxw:
        return s
    while s and pdfmetrics.stringWidth(s + "…", font, size) / mm > maxw:
        s = s[:-1]
    return s + "…"
