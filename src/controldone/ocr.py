"""PDF text extraction with native-text priority and OCR fallback.

Works page-by-page so callers can use the same extractor for merged PDFs
(where different pages must be classified separately).

v3.1 improvements
-----------------
* Image preprocessing before Tesseract:
    - adaptive binarisation (cv2 or PIL fallback)
    - CLAHE contrast enhancement
    - deskew via HoughLines (cv2) or pytesseract OSD
    - upscaling when effective DPI < 150
* Optimised Tesseract config: --oem 3 --psm 6 for tables,
  --psm 4 for mixed pages, --psm 3 as last-resort fallback
* Disk cache (data/cache/<sha256>.txt): already-OCR'd pages are
  never re-processed
* Parallel page OCR via ThreadPoolExecutor (order preserved)
* Smarter native-text detection: force OCR when native text is
  very short (<80 chars) but the page is mostly image (>80 % of
  the page area is covered by image objects)
"""
from __future__ import annotations

import contextvars
import hashlib
import os
import re
import shutil
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Optional, Tuple

import fitz  # PyMuPDF

from controldone.profile import current_profile
from controldone.paths import data_dir

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

TESSERACT_EXE: Optional[str] = None

OCR_DPI = 300
OCR_LANG = "fra+eng"

# Default PSM modes tried in order: 6 (uniform block) → 4 (mixed page) → 3 (auto)
OCR_PSM_TABLE = 6       # suited for tabular layouts
OCR_PSM_MIXED = 4       # column or mixed layout
OCR_PSM_AUTO = 3        # fully automatic (slower)
OCR_PSM_SPARSE = 11     # sparse text, useful for low-quality scanned invoices
OCR_PSM_SPARSE_OSD = 12 # sparse text with orientation/script detection
OCR_MIN_CHARS_FALLBACK = 60   # if psm6 gives fewer chars, retry with psm4
# Bump whenever OCR quality changes so stale cached text is recomputed.
OCR_CACHE_VERSION = "v430"
OCR_TIMEOUT_SECONDS = int(os.environ.get("CONTROLDONE_OCR_TIMEOUT", "45"))

# Minimum text chars to consider a page "natively digital"
NATIVE_MIN_CHARS = 80
# If image area covers more than this fraction of the page → force OCR even if native text exists
IMAGE_AREA_RATIO_THRESHOLD = 0.80

CACHE_DIR = str(data_dir("cache"))

_TESS_CHECKED = False

# ---------------------------------------------------------------------------
# Optional imports (graceful degradation)
# ---------------------------------------------------------------------------

try:
    import cv2
    import numpy as np
    _CV2_AVAILABLE = True
except ImportError:
    _CV2_AVAILABLE = False

try:
    from PIL import Image, ImageEnhance, ImageFilter, ImageOps
    _PIL_AVAILABLE = True
except ImportError:
    _PIL_AVAILABLE = False

try:
    import pytesseract
    _TESS_AVAILABLE = True
except ImportError:
    _TESS_AVAILABLE = False


# ---------------------------------------------------------------------------
# Tesseract setup
# ---------------------------------------------------------------------------

def _ensure_tesseract() -> None:
    global _TESS_CHECKED
    if _TESS_CHECKED:
        return
    configure_tesseract()
    _TESS_CHECKED = True


def configure_tesseract() -> Optional[str]:
    """Configure pytesseract from PATH, env vars, or common Windows installs."""
    if not _TESS_AVAILABLE:
        return None
    exe = find_tesseract_executable()
    if exe:
        pytesseract.pytesseract.tesseract_cmd = exe
    return exe


def find_tesseract_executable() -> Optional[str]:
    """Return a usable Tesseract executable path if one can be found."""
    candidates = []
    for var in ("CONTROLDONE_TESSERACT_CMD", "TESSERACT_CMD", "TESSERACT_EXE"):
        val = os.environ.get(var)
        if val:
            candidates.append(val)
    if TESSERACT_EXE:
        candidates.append(TESSERACT_EXE)

    found = shutil.which("tesseract")
    if found:
        candidates.append(found)

    local_app_data = os.environ.get("LOCALAPPDATA")
    user_profile = os.environ.get("USERPROFILE")
    program_files = os.environ.get("ProgramFiles", r"C:\Program Files")
    program_files_x86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
    candidates.extend([
        os.path.join(program_files, "Tesseract-OCR", "tesseract.exe"),
        os.path.join(program_files_x86, "Tesseract-OCR", "tesseract.exe"),
    ])
    if local_app_data:
        candidates.append(os.path.join(local_app_data, "Programs", "Tesseract-OCR", "tesseract.exe"))
    if user_profile:
        candidates.append(os.path.join(user_profile, "AppData", "Local", "Programs", "Tesseract-OCR", "tesseract.exe"))

    seen = set()
    for candidate in candidates:
        if not candidate:
            continue
        path = os.path.expandvars(os.path.expanduser(str(candidate).strip('"')))
        if path in seen:
            continue
        seen.add(path)
        if os.path.exists(path):
            return path
    return None


# ---------------------------------------------------------------------------
# Disk cache
# ---------------------------------------------------------------------------

def _cache_path(digest: str) -> str:
    return os.path.join(CACHE_DIR, f"{digest}.txt")


def _read_cache(digest: str) -> Optional[str]:
    p = _cache_path(digest)
    if os.path.exists(p):
        try:
            with open(p, encoding="utf-8") as f:
                return f.read()
        except Exception:
            return None
    return None


def _write_cache(digest: str, text: str) -> None:
    try:
        os.makedirs(CACHE_DIR, exist_ok=True)
        with open(_cache_path(digest), "w", encoding="utf-8") as f:
            f.write(text)
    except Exception:
        pass


def _page_digest(raw_bytes: bytes) -> str:
    if OCR_CACHE_VERSION:
        raw_bytes = OCR_CACHE_VERSION.encode("utf-8") + raw_bytes
    return hashlib.sha256(raw_bytes).hexdigest()


# ---------------------------------------------------------------------------
# Image preprocessing
# ---------------------------------------------------------------------------

def _preprocess_pil(img: "Image.Image") -> "Image.Image":
    """Apply contrast + binarisation using PIL only (no cv2)."""
    if img.mode != "L":
        img = img.convert("L")
    # Auto-contrast
    img = ImageOps.autocontrast(img, cutoff=1)
    # Mild sharpening
    img = img.filter(ImageFilter.SHARPEN)
    # Adaptive threshold: convert to binary using a local mean approach
    # PIL doesn't have adaptiveThreshold; use a simple global Otsu-like approach
    import statistics
    pixels = list(img.getdata())
    if pixels:
        median_val = statistics.median(pixels)
        threshold = int(median_val * 0.85)
        img = img.point(lambda p: 255 if p > threshold else 0)
    return img


def _deskew_pil(img: "Image.Image") -> "Image.Image":
    """Attempt deskew via pytesseract OSD (graceful fallback)."""
    if not _TESS_AVAILABLE:
        return img
    try:
        osd = pytesseract.image_to_osd(img, config="--psm 0")
        angle_m = re.search(r"Rotate:\s*(\d+)", osd)
        if angle_m:
            angle = int(angle_m.group(1))
            if angle not in (0, 360):
                img = img.rotate(angle, expand=True, fillcolor=255)
    except Exception:
        pass
    return img


def _preprocess_cv2(pix: "fitz.Pixmap") -> Optional["Image.Image"]:
    """Full preprocessing pipeline using cv2: deskew + CLAHE + adaptive threshold."""
    if not _CV2_AVAILABLE or not _PIL_AVAILABLE:
        return None
    try:
        # Convert pixmap → numpy BGR
        mode = pix.colorspace.name if pix.colorspace else "RGB"
        arr = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
        if pix.n == 4:
            arr = cv2.cvtColor(arr, cv2.COLOR_RGBA2BGR)
        elif pix.n == 1:
            arr = cv2.cvtColor(arr, cv2.COLOR_GRAY2BGR)

        gray = cv2.cvtColor(arr, cv2.COLOR_BGR2GRAY)

        # Deskew via Hough lines
        gray = _deskew_cv2(gray)

        # CLAHE contrast enhancement
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        gray = clahe.apply(gray)

        # Adaptive threshold (Gaussian)
        binary = cv2.adaptiveThreshold(
            gray, 255,
            cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY,
            blockSize=31, C=10,
        )

        img = Image.fromarray(binary)
        return img
    except Exception:
        return None


def _gray_from_pix(pix: "fitz.Pixmap") -> Optional["np.ndarray"]:
    """Pixmap → grayscale numpy array (None when cv2/numpy unavailable)."""
    if not _CV2_AVAILABLE:
        return None
    try:
        arr = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
        if pix.n == 4:
            return cv2.cvtColor(arr, cv2.COLOR_RGBA2GRAY)
        if pix.n == 1:
            return arr.reshape(pix.height, pix.width).copy()
        return cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY)
    except Exception:
        return None


def _preprocess_gridless(gray: "np.ndarray") -> Optional["Image.Image"]:
    """Erase table grid lines before OCR.

    Bordered customs forms (entity proformas, grid repair invoices) defeat
    Tesseract: cell borders are read as characters and whole table rows come
    out as garbage.  Removing long horizontal/vertical strokes first lets the
    cell contents (HS codes, amounts, references) come through.
    """
    if not _CV2_AVAILABLE or not _PIL_AVAILABLE:
        return None
    try:
        binv = cv2.adaptiveThreshold(
            gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY_INV, 31, 10,
        )
        h_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (40, 1))
        v_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (1, 40))
        mask = cv2.bitwise_or(
            cv2.morphologyEx(binv, cv2.MORPH_OPEN, h_kernel, iterations=2),
            cv2.morphologyEx(binv, cv2.MORPH_OPEN, v_kernel, iterations=2),
        )
        cleaned = cv2.bitwise_and(binv, cv2.bitwise_not(mask))
        return Image.fromarray(255 - cleaned)
    except Exception:
        return None


def _detect_rotation(img: "Image.Image") -> int:
    """Detect page rotation (0/90/180/270) via Tesseract OSD; 0 on failure."""
    if not _TESS_AVAILABLE:
        return 0
    try:
        osd = pytesseract.image_to_osd(img, config="--psm 0", timeout=OCR_TIMEOUT_SECONDS)
        m = re.search(r"Rotate:\s*(\d+)", osd)
        if m:
            return int(m.group(1)) % 360
    except Exception:
        pass
    return 0


def _rotate_pil(img: "Image.Image", angle: int) -> "Image.Image":
    """Rotate counter-clockwise by the angle Tesseract OSD asks for."""
    if angle % 360 == 0:
        return img
    return img.rotate(-angle, expand=True, fillcolor=255)


def _deskew_cv2(gray: "np.ndarray") -> "np.ndarray":
    """Detect and correct skew angle using Hough transform."""
    try:
        edges = cv2.Canny(gray, 50, 150, apertureSize=3)
        lines = cv2.HoughLines(edges, 1, np.pi / 180, threshold=200)
        if lines is None:
            return gray
        angles = []
        for line in lines[:30]:
            rho, theta = line[0]
            angle_deg = np.degrees(theta) - 90
            if abs(angle_deg) < 20:  # only small skews
                angles.append(angle_deg)
        if not angles:
            return gray
        median_angle = float(np.median(angles))
        if abs(median_angle) < 0.5:
            return gray
        (h, w) = gray.shape
        center = (w // 2, h // 2)
        M = cv2.getRotationMatrix2D(center, median_angle, 1.0)
        rotated = cv2.warpAffine(
            gray, M, (w, h),
            flags=cv2.INTER_CUBIC,
            borderMode=cv2.BORDER_REPLICATE,
        )
        return rotated
    except Exception:
        return gray


# ---------------------------------------------------------------------------
# Page image extraction helpers
# ---------------------------------------------------------------------------

def _get_pix(page: "fitz.Page", dpi: int = OCR_DPI) -> "fitz.Pixmap":
    return page.get_pixmap(dpi=dpi)


def _pix_to_pil(pix: "fitz.Pixmap") -> Optional["Image.Image"]:
    if not _PIL_AVAILABLE:
        return None
    return Image.frombytes("RGB", [pix.width, pix.height], pix.samples)


def _image_area_ratio(page: "fitz.Page") -> float:
    """Fraction of page area covered by image objects."""
    try:
        page_area = page.rect.width * page.rect.height
        if page_area <= 0:
            return 0.0
        img_area = 0.0
        for img_info in page.get_image_info():
            r = fitz.Rect(img_info.get("bbox", (0, 0, 0, 0)))
            img_area += r.width * r.height
        return min(img_area / page_area, 1.0)
    except Exception:
        return 0.0


# ---------------------------------------------------------------------------
# Core OCR function
# ---------------------------------------------------------------------------

def _ocr_page_with_config(img: "Image.Image", lang: str, psm: int) -> str:
    """Run tesseract with given PSM. Return empty string on failure."""
    config = f"--oem 3 --psm {psm}"
    try:
        return pytesseract.image_to_string(
            img,
            lang=lang,
            config=config,
            timeout=OCR_TIMEOUT_SECONDS,
        )
    except Exception:
        return ""


def _ocr_pil_image(img: "Image.Image", collector: Optional[List[str]] = None) -> str:
    """Try OCR with multiple PSM configs and return the best business text.

    When ``collector`` is given, every non-empty pass output is appended to it
    so the caller can later merge business lines found by non-winning passes.
    """
    _ensure_tesseract()
    best = ""
    best_score = -1
    for psm in (OCR_PSM_TABLE, OCR_PSM_MIXED, OCR_PSM_AUTO):
        text = _ocr_page_with_config(img, OCR_LANG, psm)
        if collector is not None and text.strip():
            collector.append(text)
        score = _ocr_quality_score(text)
        if score > best_score:
            best = text
            best_score = score
    if _needs_sparse_retry(best):
        for psm in (OCR_PSM_SPARSE, OCR_PSM_SPARSE_OSD):
            text = _ocr_page_with_config(img, OCR_LANG, psm)
            if collector is not None and text.strip():
                collector.append(text)
            score = _ocr_quality_score(text)
            if score > best_score:
                best = text
                best_score = score
    if not best.strip() and OCR_LANG != "eng":
        # A Tesseract install without the French pack makes every fra+eng
        # pass fail silently; retry English-only rather than returning blank.
        for psm in (OCR_PSM_TABLE, OCR_PSM_AUTO):
            text = _ocr_page_with_config(img, "eng", psm)
            if collector is not None and text.strip():
                collector.append(text)
            score = _ocr_quality_score(text)
            if score > best_score:
                best = text
                best_score = score
    return best


def _ocr_quality_score(text: str) -> int:
    """Score OCR output for customs/invoice usefulness, not just raw length."""
    if not text:
        return 0
    up = text.upper()
    score = min(len(text), 4000)
    for token in (
        "INVOICE", "PROFORMA", "CUSTOMS", "CUSTOM", "VALUE", "TOTAL",
        "VAT", "TVA", "EORI", "SHIP TO", "BILL TO", "AWB", "TRACKING",
        "HS", "TARIFF", "COMMODITY", "MATRICULE", "DHL",
    ):
        score += 250 * up.count(token)
    score += 500 * len(re.findall(r"\b(?:EUR|USD|GBP|CHF|CAD|JPY|HKD|NOK|TWD|THB|AUD)\b", up))
    score += 250 * len(re.findall(r"\b[0-9]{4}[ .]?[0-9]{2}[ .]?[0-9]{2,4}\b", up))
    score += 250 * len(re.findall(r"\bFR\s*[0-9][0-9\s]{9,16}\b", up))
    return score


def _needs_sparse_retry(text: str) -> bool:
    up = (text or "").upper()
    keywords = ("INVOICE", "PROFORMA", "CUSTOMS", *current_profile().invoice_keywords)
    if not re.search(r"\b(?:" + "|".join(re.escape(k) for k in keywords) + r")\b", up):
        return False
    has_money = bool(re.search(r"\b[0-9][0-9 .,]*[,.][0-9]{2}\s*(?:EUR|USD|GBP|CHF|CAD|JPY|HKD|NOK|TWD|THB|AUD|€|£|¥)\b", up))
    has_hs = bool(re.search(r"\b(?:HS|TARIFF|CUSTOMS?\s+CODE|COMMODITY|MATRICULE|IB:|NO)\b[\s\S]{0,80}\b[0-9]{6,10}\b", up))
    # Sparse PSM is expensive, so reserve it for invoice-like pages where the
    # first OCR pass found the header but not the business fields.
    return not (has_money and has_hs)


# Business signals used both to decide extra OCR effort and to merge passes.
_SIG_HS = re.compile(r"\b\d{4}[ .]?\d{2}[ .]?\d{2,4}\b")
def _sig_vat() -> "re.Pattern":
    """VAT/identity signal for the active profile: a French VAT, or one of the
    controlled entities' bare SIRENs.  OCR mangles the FR key but rarely the
    9-digit SIREN, so SIREN-only lines from losing OCR passes stay recoverable.
    """
    sirens = [re.escape(s) for _, s in current_profile().siren_by_vat if s]
    pattern = r"\bFR\s?[0-9A-Z]{2}\s?\d{9}\b"
    if sirens:
        pattern += "|" + "|".join(sirens)
    return re.compile(pattern)
_SIG_MONEY = re.compile(
    r"\b\d[\d., ]*[.,]\d{2}\s*(?:EUR|USD|GBP|CHF|CAD|JPY|KRW|HKD|NOK|TWD|THB|AUD|AED|SGD|€|£|\$)"
    r"|\b(?:EUR|USD|GBP|CHF|CAD|JPY|KRW|HKD|NOK|TWD|THB|AUD|AED|SGD|€|£|\$)\s*\d[\d., ]*"
    r"|TOTAL[^\n]{0,50}\d", re.I)


# Stricter money signal for merging: a decimal amount or an ISO currency code.
# A bare "$" next to digits is too often fax noise ("199$ 10019").
_SIG_MONEY_STRICT = re.compile(
    r"\b\d[\d., ]*[.,]\d{2}\b"
    r"|\b(?:EUR|USD|GBP|CHF|CAD|JPY|KRW|HKD|NOK|TWD|THB|AUD|AED|SGD)\b", re.I)


def _missing_business_signals(text: str) -> bool:
    """True when OCR output lacks the fields the customs checks need."""
    up = (text or "").upper()
    return not (_SIG_HS.search(up) and _SIG_MONEY.search(up))


def _merge_business_lines(best: str, candidates: List[str]) -> str:
    """Append business lines other passes found but the winning pass missed.

    Merging is category-gated: lines from losing passes are only appended for
    signal categories (HS / VAT / amounts) entirely absent from the winner, so
    a noisy pass can never override a value the winner already read.
    """
    if not candidates:
        return best
    sig_vat = _sig_vat()
    gate_map = (
        (_SIG_HS, _SIG_HS),
        (sig_vat, sig_vat),
        (_SIG_MONEY, _SIG_MONEY_STRICT),
    )
    gates = [merge_re for present_re, merge_re in gate_map
             if not present_re.search(best.upper())]
    if not gates:
        return best
    seen = {re.sub(r"[^A-Z0-9]", "", ln.upper()) for ln in best.splitlines()}
    extra: List[str] = []
    for cand in candidates:
        if cand is best:
            continue
        for line in cand.splitlines():
            up = line.upper()
            if not any(g.search(up) for g in gates):
                continue
            key = re.sub(r"[^A-Z0-9]", "", up)
            if len(key) < 6 or key in seen:
                continue
            seen.add(key)
            extra.append(line.strip())
    if not extra:
        return best
    return best + "\n[COMPLEMENT OCR]\n" + "\n".join(extra)


def _ocr_page(page: "fitz.Page") -> str:
    """Full OCR pipeline for one page including preprocessing.

    Strategy: detect orientation, OCR several preprocessed variants of the
    upright page (adaptive threshold, raw, grid-line removal), and if the
    business fields are still missing, sweep the remaining rotations.  The
    final text is the best-scoring pass plus business lines recovered from
    the other passes.
    """
    if not _TESS_AVAILABLE or not _PIL_AVAILABLE:
        return ""

    pix = _get_pix(page, dpi=OCR_DPI)
    raw_img = _pix_to_pil(pix)
    if raw_img is None:
        return ""

    rotation = _detect_rotation(raw_img)
    upright = _rotate_pil(raw_img, rotation)

    all_passes: List[str] = []
    candidates: List[str] = []

    gray = _gray_from_pix(pix)
    if gray is not None and rotation:
        gray = np.rot90(gray, k=(360 - rotation) // 90).copy()

    if _CV2_AVAILABLE and gray is not None:
        # Adaptive threshold (CLAHE + deskew), best on faint or skewed scans.
        pre = _preprocess_cv2(pix) if not rotation else None
        if pre is None:
            try:
                clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
                binary = cv2.adaptiveThreshold(
                    clahe.apply(_deskew_cv2(gray)), 255,
                    cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY,
                    blockSize=31, C=10,
                )
                pre = Image.fromarray(binary)
            except Exception:
                pre = None
        if pre is not None:
            candidates.append(_ocr_pil_image(pre, collector=all_passes))
        # Grid-line removal at higher DPI, recovers bordered table rows with
        # tiny print (HS codes, totals), validated on bordered proforma scans.
        gray_hi = _gray_from_pix(_get_pix(page, dpi=400))
        if gray_hi is not None and rotation:
            gray_hi = np.rot90(gray_hi, k=(360 - rotation) // 90).copy()
        gridless = _preprocess_gridless(gray_hi if gray_hi is not None else gray)
        if gridless is not None:
            candidates.append(_ocr_pil_image(gridless, collector=all_passes))

    # Raw image sometimes beats binarisation on clean digital-looking scans.
    candidates.append(_ocr_pil_image(upright, collector=all_passes))
    if not _CV2_AVAILABLE:
        candidates.append(_ocr_pil_image(_preprocess_pil(upright), collector=all_passes))

    best = max(candidates, key=_ocr_quality_score) if candidates else ""

    # OSD misreads some fax scans: when key fields are still missing, sweep
    # the other rotations with the gridless variant (cheap, table-oriented).
    if _missing_business_signals(best) and _CV2_AVAILABLE and gray is not None:
        for extra_rot in (90, 180, 270):
            rotated = np.rot90(gray, k=(360 - extra_rot) // 90).copy()
            img = _preprocess_gridless(rotated)
            if img is None:
                continue
            for psm in (OCR_PSM_SPARSE, OCR_PSM_TABLE):
                text = _ocr_page_with_config(img, OCR_LANG, psm)
                if text.strip():
                    all_passes.append(text)
                    if _ocr_quality_score(text) > _ocr_quality_score(best):
                        best = text

    return _merge_business_lines(best, all_passes)


# ---------------------------------------------------------------------------
# Smart native-text detection
# ---------------------------------------------------------------------------

def _should_force_ocr(page: "fitz.Page", native_text: str) -> bool:
    """Return True if OCR should be used despite native text being present."""
    stripped = native_text.strip()
    if len(stripped) < NATIVE_MIN_CHARS:
        return True
    # Has native text but page is mostly image → still force OCR
    if len(stripped) < 300 and _image_area_ratio(page) > IMAGE_AREA_RATIO_THRESHOLD:
        return True
    return False


# ---------------------------------------------------------------------------
# Per-page worker (used both serially and in thread pool)
# ---------------------------------------------------------------------------

def _process_page(
    page_idx: int,
    pdf_path: str,
    force_ocr: bool,
) -> Tuple[int, str]:
    """
    Open the PDF, seek to page_idx, extract text (native or OCR).
    Returns (page_idx, text).
    Thread-safe because each call opens its own fitz.Document instance.
    """
    with fitz.open(pdf_path) as doc:
        page = doc[page_idx]

        # Compute page content hash for cache lookup
        try:
            raw = page.get_pixmap(dpi=72).tobytes()  # low-res for hashing speed
            digest = _page_digest(raw)
            cached = _read_cache(digest)
            if cached is not None:
                return page_idx, _clean(cached)
        except Exception:
            digest = None

        native = page.get_text() or ""

        if force_ocr or _should_force_ocr(page, native):
            text = _ocr_page(page)
            if not text and native.strip():
                text = native  # ultimate fallback
        else:
            text = native

        cleaned = _clean(text)
        if digest:
            _write_cache(digest, cleaned)
        return page_idx, cleaned


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def _clean(text: str) -> str:
    """Strip embedded HTML-like tags and null bytes."""
    text = re.sub(r"<[^>]{1,10}>", " ", text)
    text = text.replace("\x00", "")
    return text


def extract_text_per_page(pdf_path: str, force_ocr: bool = False,
                           max_workers: int = 4) -> List[str]:
    """Return one string per page.

    Uses native text when available; falls back to OCR otherwise.
    Pages are processed in parallel (ThreadPoolExecutor) and reassembled
    in original order.
    """
    with fitz.open(pdf_path) as doc:
        n_pages = len(doc)

    if n_pages == 0:
        return []

    results: List[Tuple[int, str]] = []

    # Single-page or very small PDFs: no thread overhead needed
    if n_pages <= 2 or max_workers <= 1:
        for i in range(n_pages):
            results.append(_process_page(i, pdf_path, force_ocr))
    else:
        with ThreadPoolExecutor(max_workers=min(max_workers, n_pages)) as pool:
            # contextvars do NOT propagate into ThreadPoolExecutor workers, so
            # the injected client profile would be invisible there.  Run each
            # page inside a copy of the current context to carry it across.
            futures = {
                pool.submit(contextvars.copy_context().run, _process_page, i, pdf_path, force_ocr): i
                for i in range(n_pages)
            }
            for fut in as_completed(futures):
                try:
                    results.append(fut.result())
                except Exception:
                    idx = futures[fut]
                    results.append((idx, ""))

    # Reassemble in page order
    results.sort(key=lambda t: t[0])
    return [text for _, text in results]


def extract_text(pdf_path: str, force_ocr: bool = False) -> str:
    """Whole-document text (pages joined with double newline)."""
    return "\n\n".join(extract_text_per_page(pdf_path, force_ocr=force_ocr))
