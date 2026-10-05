"""Dégradations d'images, déterministes (graine par document) : scan propre, scan incliné,
photo de téléphone (perspective, ombre, flou), faible contraste, artefacts JPEG, TIFF multipage,
télécopie (binarisée, stries, en-tête), pages tournées et orientation mixte."""

from __future__ import annotations

import io
import random

import pypdfium2 as pdfium
from PIL import Image, ImageChops, ImageDraw, ImageEnhance, ImageFilter, ImageFont
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

from .util import FICTIF

MONO_FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"

# mode -> (dpi, classe)
MODE_INFO = {
    "native": (None, "d0"), "scan300": (300, "d1"), "scan250j": (250, "d1"),
    "skew200": (200, "d2"), "photo": (200, "d2"), "lowcontrast": (200, "d2"), "jpeg150": (150, "d2"),
    "tiff200": (200, "d2"), "rotated": (200, "d2"), "fax": (200, "d3"), "faxtiff": (200, "d3"),
    # extension 2.1 (--ext)
    "skewlow": (200, "d2"), "overlay": (200, "d2"), "twoup": (200, "d2"), "jpegheavy": (150, "d2"), "faxnoise": (200, "d3"),
}
PDF_COMPAT = {"photo": "skew200", "tiff200": "lowcontrast", "faxtiff": "fax"}


def rasterize(pdf_bytes: bytes, dpi: int) -> list:
    doc = pdfium.PdfDocument(pdf_bytes)
    out = []
    for i in range(len(doc)):
        page = doc[i]
        img = page.render(scale=dpi / 72, grayscale=True).to_pil().convert("L")
        out.append(img)
        page.close()
    doc.close()
    return out


def _noise(img, rng: random.Random, amount=0.06, scale=2):
    w, h = img.size
    sw, sh = max(1, w // scale), max(1, h // scale)
    n = Image.frombytes("L", (sw, sh), rng.randbytes(sw * sh)).resize((w, h), Image.NEAREST)
    return Image.blend(img, n, amount)


def _specks(img, rng: random.Random, n=120):
    d = ImageDraw.Draw(img)
    w, h = img.size
    for _ in range(n):
        x, y = rng.randrange(w), rng.randrange(h)
        r = rng.choice([1, 1, 1, 2])
        d.ellipse((x, y, x + r, y + r), fill=rng.choice([0, 40, 90]))
    return img


def _skew(img, angle):
    return img.rotate(angle, resample=Image.BICUBIC, expand=False, fillcolor=255)


def _solve(a, b):
    n = len(b)
    m = [row[:] + [b[i]] for i, row in enumerate(a)]
    for c in range(n):
        piv = max(range(c, n), key=lambda r: abs(m[r][c]))
        m[c], m[piv] = m[piv], m[c]
        pv = m[c][c]
        for k in range(c, n + 1):
            m[c][k] /= pv
        for r in range(n):
            if r != c and m[r][c] != 0:
                f = m[r][c]
                for k in range(c, n + 1):
                    m[r][k] -= f * m[c][k]
    return [m[i][n] for i in range(n)]


def _persp_coeffs(src, dst):
    """Coefficients PIL (sortie -> entrée) : dst = coins dans l'image de sortie, src = coins de l'entrée."""
    a, b = [], []
    for (x, y), (u, v) in zip(dst, src):
        a.append([x, y, 1, 0, 0, 0, -u * x, -u * y])
        b.append(u)
        a.append([0, 0, 0, x, y, 1, -v * x, -v * y])
        b.append(v)
    return _solve(a, b)


def photo(img, rng: random.Random):
    w, h = img.size
    W, H = int(w * 1.16), int(h * 1.12)
    base = rng.choice([(122, 98, 74), (92, 92, 96), (150, 132, 108), (60, 66, 72)])
    bg = Image.new("RGB", (W, H), base)
    grad = Image.linear_gradient("L").resize((W, H)).rotate(rng.choice([0, 90, 180, 270]))
    bg = Image.composite(bg, Image.new("RGB", (W, H), tuple(max(0, c - 40) for c in base)), grad)
    j = lambda m: rng.uniform(-m, m)  # noqa: E731
    ox, oy = (W - w) / 2, (H - h) / 2
    dst = [(ox + j(w * 0.05), oy + j(h * 0.03)), (ox + w + j(w * 0.05), oy + j(h * 0.03)),
           (ox + w + j(w * 0.05), oy + h + j(h * 0.03)), (ox + j(w * 0.05), oy + h + j(h * 0.03))]
    src = [(0, 0), (w, 0), (w, h), (0, h)]
    co = _persp_coeffs(src, dst)
    page = img.convert("RGB").transform((W, H), Image.PERSPECTIVE, co, resample=Image.BICUBIC)
    mask = Image.new("L", (w, h), 255).transform((W, H), Image.PERSPECTIVE, co, resample=Image.BILINEAR)
    tint = Image.new("RGB", (W, H), (255, 247, 232))
    page = ImageChops.multiply(page, tint)
    bg.paste(page, (0, 0), mask)
    # ombre (dégradé) et flou de bougé léger
    sh = Image.linear_gradient("L").resize((W, H)).rotate(rng.choice([0, 45, 90, 135, 180]), fillcolor=255)
    sh = sh.point(lambda v: int(150 + v * 105 / 255))
    bg = ImageChops.multiply(bg, Image.merge("RGB", (sh, sh, sh)))
    bg = bg.filter(ImageFilter.GaussianBlur(rng.uniform(0.7, 1.3)))
    return bg


def fax(img, rng: random.Random, header=""):
    w, h = img.size
    img = img.resize((w, h // 2), Image.BILINEAR).resize((w, h), Image.NEAREST)
    img = _skew(img, rng.uniform(-0.8, 0.8))
    img = _noise(img, rng, 0.04, 3)
    thr = rng.choice([150, 165, 175])
    bw = img.point(lambda v: 255 if v > thr else 0, mode="1").convert("L")
    d = ImageDraw.Draw(bw)
    for _ in range(rng.randint(3, 9)):
        y = rng.randrange(h)
        d.line((0, y, w, y), fill=rng.choice([0, 255]), width=rng.choice([1, 2, 3]))
    _specks(bw, rng, 300)
    if header:
        f = ImageFont.truetype(MONO_FONT, max(14, w // 70))
        d.text((20, 8), header, fill=0, font=f)
    return bw.convert("1")


def degrade_page(img, mode: str, rng: random.Random, page_idx: int, n_pages: int, fax_header=""):
    """Retourne (image, encodage) ; encodage ∈ {'jpeg:q', 'png'}."""
    if mode == "scan300":
        img = _skew(img, rng.uniform(-0.35, 0.35))
        img = _noise(img, rng, 0.03)
        return img.filter(ImageFilter.GaussianBlur(0.35)), "jpeg:85"
    if mode == "scan250j":
        img = _skew(img, rng.uniform(-0.5, 0.5))
        img = ImageEnhance.Brightness(_noise(img, rng, 0.04)).enhance(1.03)
        return img, "jpeg:78"
    if mode == "skew200":
        img = _skew(img, rng.choice([-1, 1]) * rng.uniform(1.0, 3.0))
        img = _specks(_noise(img, rng, 0.06), rng, 150)
        if page_idx == (n_pages - 1 if n_pages > 1 else 0) and (n_pages > 1 or rng.random() < 0.4):
            img = img.rotate(rng.choice([90, 180, 270]), expand=True)
        return img, "jpeg:75"
    if mode == "lowcontrast":
        img = ImageEnhance.Contrast(img).enhance(rng.uniform(0.32, 0.45))
        img = ImageEnhance.Brightness(img).enhance(rng.uniform(1.12, 1.25))
        img = _noise(img, rng, 0.05)
        return img.filter(ImageFilter.GaussianBlur(0.5)), "jpeg:80"
    if mode == "jpeg150":
        img = _skew(img, rng.uniform(-1, 1))
        return img, "jpeg:22"
    if mode == "tiff200":
        img = _skew(img, rng.uniform(-1.5, 1.5))
        return _noise(img, rng, 0.05), "tiff"
    if mode == "rotated":
        img = _noise(img, rng, 0.04)
        if n_pages == 1 or page_idx % 2 == 1:
            img = img.rotate(rng.choice([90, 270]), expand=True)
        return img, "jpeg:80"
    if mode in ("fax", "faxtiff"):
        return fax(img, rng, fax_header + f"  P.{page_idx + 1:02d}/{n_pages:02d}"), "png1"
    if mode == "photo":
        return photo(img, rng), "jpeg:70"
    # --- extension 2.1 ---
    if mode == "skewlow":
        img = _skew(img, rng.choice([-1, 1]) * rng.uniform(1.2, 2.8))
        img = ImageEnhance.Contrast(img).enhance(rng.uniform(0.35, 0.5))
        img = ImageEnhance.Brightness(img).enhance(rng.uniform(1.08, 1.2))
        return _noise(img, rng, 0.05), "jpeg:72"
    if mode == "overlay":
        img = _skew(img, rng.uniform(-0.6, 0.6))
        return overlay(img.convert("RGB"), rng), "jpeg:78"
    if mode == "twoup":
        img = _skew(img, rng.uniform(-0.8, 0.8))
        return _noise(img, rng, 0.04), "jpeg:75"
    if mode == "jpegheavy":
        w, h = img.size
        small = img.resize((int(w * 0.75), int(h * 0.75)), Image.BILINEAR)
        for q in (18, 12):
            buf = io.BytesIO()
            small.save(buf, format="JPEG", quality=q)
            small = Image.open(io.BytesIO(buf.getvalue())).convert("L")
        return small.resize((w, h), Image.BILINEAR), "jpeg:20"
    if mode == "faxnoise":
        bw = fax(img, rng, fax_header + f"  P.{page_idx + 1:02d}/{n_pages:02d}").convert("L")
        d = ImageDraw.Draw(bw)
        w, h = bw.size
        for _ in range(rng.randint(2, 5)):          # bandes verticales et rafales de bruit
            x = rng.randrange(w)
            d.rectangle((x, 0, x + rng.choice([1, 2]), h), fill=rng.choice([0, 255]))
        _specks(bw, rng, 900)
        return bw.convert("1"), "png1"
    raise ValueError(mode)


STAMPS = ["REÇU LE", "PAYÉ", "BON À PAYER", "COMPTABILISÉ", "VU", "RECEIVED", "CONTRÔLÉ"]


def overlay(img, rng: random.Random):
    """Tampons encrés et annotations manuscrites posés sur le texte (souvent sur la zone des montants)."""
    w, h = img.size
    layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    fs = max(28, w // 22)
    font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", fs)
    hand = ImageFont.truetype("/usr/share/fonts/truetype/freefont/FreeSerifItalic.ttf", max(26, w // 26))
    for _ in range(rng.randint(1, 2)):
        txt = rng.choice(STAMPS) + (f" {rng.randint(1, 28):02d}/{rng.randint(1, 12):02d}" if rng.random() < 0.5 else "")
        col = rng.choice([(192, 57, 43), (31, 58, 147), (30, 132, 73)])
        tw = d.textlength(txt, font=font)
        x = rng.randint(int(w * 0.35), max(int(w * 0.36), int(w - tw - 40)))
        y = rng.randint(int(h * 0.30), int(h * 0.75))
        st = Image.new("RGBA", (int(tw) + 40, fs + 40), (0, 0, 0, 0))
        sd = ImageDraw.Draw(st)
        sd.rectangle((4, 4, tw + 34, fs + 34), outline=col + (150,), width=5)
        sd.text((20, 14), txt, font=font, fill=col + (150,))
        st = st.rotate(rng.uniform(-18, 18), expand=True, resample=Image.BICUBIC)
        layer.alpha_composite(st, (min(x, w - st.size[0] - 1), min(y, h - st.size[1] - 1)))
    for _ in range(rng.randint(1, 3)):
        txt = rng.choice(["ok", "vu", "à vérifier ?", "payé", "réf. ok", "✓", "→ compta"])
        x, y = rng.randint(int(w * 0.1), int(w * 0.8)), rng.randint(int(h * 0.15), int(h * 0.9))
        d.text((x, y), txt, font=hand, fill=(20, 40, 120, 210))
        pts = [(x + i * 12, y + hand.size + 6 + rng.randint(-4, 4)) for i in range(rng.randint(5, 12))]
        d.line(pts, fill=(20, 40, 120, 200), width=3)
    out = img.convert("RGBA")
    out.alpha_composite(layer)
    return out.convert("RGB")


def two_up(pages: list, rng: random.Random):
    """Deux pages A4 côte à côte sur une feuille A4 paysage (même résolution)."""
    out = []
    for i in range(0, len(pages), 2):
        pair = [im.convert("L") for im, _ in pages[i:i + 2]]
        land = pair[0].size[0] > pair[0].size[1]
        if not land:        # pages portrait côte à côte sur une feuille paysage
            sh = max(im.size[1] for im in pair)
            sw = int(sh * 2339 / 1654)
        else:               # pages paysage l'une sous l'autre sur une feuille portrait
            sw = max(im.size[0] for im in pair)
            sh = int(sw * 2339 / 1654)
        sheet = Image.new("L", (sw, sh), 255)
        for j, im in enumerate(pair):
            cw, ch = (sw / 2, sh) if not land else (sw, sh / 2)
            scale = min((cw - 20) / im.size[0], (ch - 20) / im.size[1])
            im2 = im.resize((int(im.size[0] * scale), int(im.size[1] * scale)), Image.BILINEAR)
            ox, oy = (j * cw, 0) if not land else (0, j * ch)
            sheet.paste(im2, (int(ox + (cw - im2.size[0]) / 2), int(oy + (ch - im2.size[1]) / 2)))
        d = ImageDraw.Draw(sheet)
        if not land:
            d.line((sw // 2, 0, sw // 2, sh), fill=170, width=2)
        else:
            d.line((0, sh // 2, sw, sh // 2), fill=170, width=2)
        out.append((_noise(sheet, rng, 0.03), "jpeg:75"))
    return out


def encode(img, enc: str) -> bytes:
    buf = io.BytesIO()
    if enc.startswith("jpeg"):
        q = int(enc.split(":")[1])
        img.save(buf, format="JPEG", quality=q, optimize=False, progressive=False, subsampling=2 if img.mode == "RGB" else 0)
    elif enc == "png1":
        img.convert("1").save(buf, format="PNG", optimize=False)
    else:
        img.save(buf, format="PNG", optimize=False)
    return buf.getvalue()


def images_to_pdf(pages: list, dpi_list: list, title="Scan") -> bytes:
    """pages : [(image, encodage)] -> PDF image (reportlab invariant)."""
    buf = io.BytesIO()
    c = canvas.Canvas(buf, invariant=1, pageCompression=1)
    c.setTitle(title)
    c.setAuthor(FICTIF)
    c.setCreator("bench.generator2 scan (FICTIF)")
    for (img, enc), dpi in zip(pages, dpi_list):
        w, h = img.size
        pw, ph = w * 72 / dpi, h * 72 / dpi
        c.setPageSize((pw, ph))
        data = encode(img, enc if enc != "tiff" else "jpeg:80")
        c.drawImage(ImageReader(io.BytesIO(data)), 0, 0, width=pw, height=ph)
        c.showPage()
    c.save()
    return buf.getvalue()


def images_to_tiff(pages: list, dpi: int) -> bytes:
    buf = io.BytesIO()
    imgs = [img for img, _ in pages]
    one_bit = all(enc == "png1" for _, enc in pages)
    if one_bit:
        imgs = [im.convert("1") for im in imgs]
        imgs[0].save(buf, format="TIFF", save_all=True, append_images=imgs[1:], compression="group4", dpi=(dpi, dpi))
    else:
        imgs = [im.convert("L") for im in imgs]
        imgs[0].save(buf, format="TIFF", save_all=True, append_images=imgs[1:], compression="tiff_lzw", dpi=(dpi, dpi))
    return buf.getvalue()


def degrade_doc(pdf_bytes: bytes, mode: str, rng: random.Random, fax_header=""):
    dpi = MODE_INFO[mode][0]
    imgs = rasterize(pdf_bytes, dpi)
    out = [degrade_page(im, mode, rng, i, len(imgs), fax_header) for i, im in enumerate(imgs)]
    if mode == "twoup":
        out = two_up(out, rng)
    return out, dpi
