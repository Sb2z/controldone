"""Dégradations d1–d3 (SPEC §19.6) : rendu des pages, inclinaison, bruit, rotation, binarisation,
puis PDF image seule (aucune couche texte). Déterministe pour une graine donnée."""

from __future__ import annotations

import io

import numpy as np
import pypdfium2 as pdfium
from PIL import Image, ImageFilter
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

DPI = {"d1": 300, "d2": 200, "d3": 150}


def degrade_pdf(pdf_bytes: bytes, level: str, seed: int) -> bytes:
    rng = np.random.default_rng(seed)
    pdf = pdfium.PdfDocument(pdf_bytes)
    n = len(pdf)
    rotate_page = int(rng.integers(0, n)) if level == "d2" else -1
    rot_angle = int(rng.choice([90, 180])) if level == "d2" else 0
    buf = io.BytesIO()
    c = canvas.Canvas(buf, invariant=1, pageCompression=1)
    c.setTitle("scan")
    c.setAuthor("Générateur de corpus (FICTIF)")
    c.setCreator("bench.generator scan simulé")
    for i in range(n):
        page = pdf[i]
        w_pt, h_pt = page.get_size()
        scale = DPI[level] / 72.0
        img = page.render(scale=scale, grayscale=True).to_pil().convert("L")
        page.close()
        img = _degrade_image(img, level, rng)
        if i == rotate_page:
            img = img.rotate(rot_angle, expand=True, fillcolor=255)
        pw, ph = (h_pt, w_pt) if (i == rotate_page and rot_angle == 90) else (w_pt, h_pt)
        c.setPageSize((pw, ph))
        data = io.BytesIO()
        if level == "d3":
            img.convert("1").convert("L").save(data, format="PNG", optimize=False, compress_level=6)
        else:
            img.save(data, format="JPEG", quality=65 if level == "d2" else 74, optimize=False, progressive=False)
        data.seek(0)
        c.drawImage(ImageReader(data), 0, 0, width=pw, height=ph)
        c.showPage()
    pdf.close()
    c.save()
    return buf.getvalue()


def _degrade_image(img: Image.Image, level: str, rng) -> Image.Image:
    if level == "d1":
        angle = float(rng.uniform(-0.6, 0.6))
        sigma = 2.8
    elif level == "d2":
        angle = float(rng.uniform(-3.0, 3.0))
        sigma = 6.5
    else:
        angle = float(rng.uniform(-1.5, 1.5))
        sigma = 14.0
    if level == "d3":
        # grille de tableau marquée : épaississement des traits avant binarisation
        img = Image.blend(img, img.filter(ImageFilter.MinFilter(3)), 0.55)
    img = img.rotate(angle, resample=Image.BICUBIC, expand=False, fillcolor=255)
    arr = np.asarray(img, dtype=np.float32)
    # léger voile et variation de luminosité
    arr = arr * float(rng.uniform(0.93, 1.0)) + float(rng.uniform(0, 10))
    arr = arr + rng.normal(0, sigma, size=arr.shape).astype(np.float32)
    if level == "d3":
        h, w = arr.shape
        # rayures horizontales type télécopie
        for _ in range(int(rng.integers(3, 8))):
            y = int(rng.integers(0, h - 2))
            arr[y:y + int(rng.integers(1, 3)), :] = float(rng.choice([0.0, 255.0]))
        # points parasites
        k = int(h * w * 0.0015)
        ys = rng.integers(0, h, size=k)
        xs = rng.integers(0, w, size=k)
        arr[ys, xs] = 0.0
        arr = np.where(arr < 150, 0, 255).astype(np.float32)
    arr = np.clip(arr, 0, 255).astype(np.uint8)
    out = Image.fromarray(arr, mode="L")
    if level in ("d1", "d2"):
        out = out.filter(ImageFilter.GaussianBlur(0.55 if level == "d1" else 0.65))
    return out
