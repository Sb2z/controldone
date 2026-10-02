"""Détection du type d'un fichier par ses octets (« magic bytes »), jamais par son extension.

L'extension ne sert qu'à départager deux formats texte indiscernables (CSV / texte brut).
"""

from __future__ import annotations

import csv
import io
import re
import zipfile

__all__ = [
    "MIMES_SUPPORTES",
    "MIME_CSV",
    "MIME_EML",
    "MIME_JPEG",
    "MIME_ODS",
    "MIME_PDF",
    "MIME_PNG",
    "MIME_TEXTE",
    "MIME_TIFF",
    "MIME_XLS",
    "MIME_XLSX",
    "MIME_XML",
    "MIME_ZIP",
    "decoder_texte",
    "detecter_type",
]

MIME_PDF = "application/pdf"
MIME_PNG = "image/png"
MIME_JPEG = "image/jpeg"
MIME_TIFF = "image/tiff"
MIME_ZIP = "application/zip"
MIME_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
MIME_ODS = "application/vnd.oasis.opendocument.spreadsheet"
MIME_XLS = "application/vnd.ms-excel"
MIME_XML = "application/xml"
MIME_CSV = "text/csv"
MIME_EML = "message/rfc822"
MIME_TEXTE = "text/plain"
MIME_DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
MIME_INCONNU = "application/octet-stream"

#: Types lus par l'ingestion (XLS : format binaire ancien, non lu par les bibliothèques retenues).
MIMES_SUPPORTES = frozenset(
    {MIME_PDF, MIME_PNG, MIME_JPEG, MIME_TIFF, MIME_ZIP, MIME_XLSX, MIME_ODS, MIME_XML, MIME_CSV, MIME_EML,
     MIME_TEXTE}
)

_ENTETES_EML = re.compile(
    rb"^(?:Return-Path|Received|From|To|Subject|Message-ID|MIME-Version|Date|Delivered-To|X-[A-Za-z-]+):",
    re.IGNORECASE | re.MULTILINE,
)


def decoder_texte(contenu: bytes) -> str | None:
    """Décode un fichier texte (UTF-8 avec ou sans BOM, UTF-16 avec BOM, sinon CP1252).

    ``None`` si le contenu ressemble à du binaire (octets nuls, caractères de contrôle nombreux).
    """
    if contenu.startswith((b"\xff\xfe", b"\xfe\xff")):
        try:
            return contenu.decode("utf-16")
        except UnicodeDecodeError:
            return None
    if b"\x00" in contenu[:4096]:
        return None
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            texte = contenu.decode(enc)
        except UnicodeDecodeError:
            continue
        echantillon = texte[:4096]
        controles = sum(1 for c in echantillon if ord(c) < 32 and c not in "\r\n\t\f")
        if echantillon and controles / len(echantillon) > 0.02:
            return None
        return texte
    return None


def _type_zip(contenu: bytes) -> str:
    try:
        with zipfile.ZipFile(io.BytesIO(contenu)) as z:
            noms = set(z.namelist())
            if "mimetype" in noms:
                try:
                    mt = z.read("mimetype")[:100].decode("ascii", "ignore").strip()
                except (RuntimeError, zipfile.BadZipFile, OSError):
                    mt = ""
                if mt == MIME_ODS:
                    return MIME_ODS
                if mt.startswith("application/vnd.oasis"):
                    return mt
            if "[Content_Types].xml" in noms:
                if any(n.startswith("xl/") for n in noms):
                    return MIME_XLSX
                if any(n.startswith("word/") for n in noms):
                    return MIME_DOCX
                return MIME_INCONNU
    except (zipfile.BadZipFile, OSError, ValueError):
        return MIME_ZIP  # archive illisible : la réception la refusera comme corrompue
    return MIME_ZIP


def _est_csv(texte: str) -> bool:
    """Texte tabulé : au moins 80 % des lignes non vides contiennent le même séparateur (``;``, tabulation,
    ``|`` ou ``,``) ; les largeurs peuvent varier (exports multi-enregistrements)."""
    lignes = [ligne for ligne in texte.splitlines()[:50] if ligne.strip()]
    if len(lignes) < 2:
        return False
    for sep in (";", "\t", "|"):
        if sum(1 for li in lignes if sep in li) >= 0.8 * len(lignes):
            return True
    try:
        dialecte = csv.Sniffer().sniff("\n".join(lignes[:20]), delimiters=",")
    except csv.Error:
        return False
    largeurs = [len(r) for r in csv.reader(lignes, dialecte)]
    return largeurs[0] >= 2 and sum(1 for n in largeurs if n == largeurs[0]) >= 0.8 * len(largeurs)


def detecter_type(contenu: bytes, nom: str = "") -> str:
    """Type MIME déduit des octets ; ``application/octet-stream`` si inconnu."""
    tete = contenu[:2048]
    if tete.startswith(b"\x89PNG\r\n\x1a\n"):
        return MIME_PNG
    if tete.startswith(b"\xff\xd8\xff"):
        return MIME_JPEG
    if tete.startswith((b"II*\x00", b"MM\x00*")):
        return MIME_TIFF
    if tete.startswith((b"PK\x03\x04", b"PK\x05\x06")):
        return _type_zip(contenu)
    if tete.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"):
        return MIME_XLS
    if tete.startswith((b"GIF87a", b"GIF89a", b"BM", b"7z\xbc\xaf", b"Rar!", b"\x1f\x8b")):
        return MIME_INCONNU
    if b"%PDF-" in tete[:1024]:  # des octets parasites peuvent précéder l'en-tête PDF
        return MIME_PDF
    texte = decoder_texte(contenu)
    if texte is None:
        return MIME_INCONNU
    debut = texte.lstrip("﻿ \t\r\n")
    if re.match(r"<!DOCTYPE\s+html|<html", debut, re.IGNORECASE):
        return "text/html"
    if debut.startswith("<?xml") or re.match(r"<[A-Za-z_][\w.:-]*[\s>/]", debut):
        return MIME_XML
    if len(_ENTETES_EML.findall(contenu[:8192])) >= 2 and re.search(rb"^From:", contenu[:8192], re.I | re.M):
        return MIME_EML
    if _est_csv(texte):
        return MIME_CSV
    return MIME_TEXTE
