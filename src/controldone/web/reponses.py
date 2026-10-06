"""Réponses binaires : images PNG produites par le serveur, fichiers en pièce jointe.

Un fichier déposé n'est **jamais** rendu comme une page : téléchargement en pièce jointe, type
``application/octet-stream`` (sauf PDF, affiché par le lecteur du navigateur), ``nosniff``, CSP fermée.
Le rapport HTML (gabarit maison, sans script) peut être affiché, sous une CSP qui interdit tout script."""

from __future__ import annotations

import re
from urllib.parse import quote

from starlette.responses import Response

from controldone.web.securite import CSP_RAPPORT

__all__ = ["fichier_attache", "png"]


def png(contenu: bytes) -> Response:
    return Response(contenu, media_type="image/png", headers={"Cache-Control": "private, max-age=300"})


def _nom_ascii(nom: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", nom)[:120] or "fichier"


def fichier_attache(contenu: bytes, nom: str, mime: str | None = None, *, en_ligne: bool = False) -> Response:
    if mime is None:
        mime = (
            "application/pdf"
            if nom.lower().endswith(".pdf") and contenu[:5] == b"%PDF-"
            else "application/octet-stream"
        )
    if not en_ligne:
        mime = (
            mime
            if mime in ("application/pdf", "application/json", "text/plain; charset=utf-8")
            else "application/octet-stream"
        )
    dispo = "inline" if en_ligne else "attachment"
    entetes = {
        "Content-Disposition": f"{dispo}; filename=\"{_nom_ascii(nom)}\"; filename*=UTF-8''{quote(nom)}",
        "X-Content-Type-Options": "nosniff",
    }
    if mime.startswith("text/html"):
        entetes["Content-Security-Policy"] = CSP_RAPPORT
    elif mime != "application/pdf":
        entetes["Content-Security-Policy"] = "default-src 'none'; frame-ancestors 'none'"
    return Response(contenu, media_type=mime, headers=entetes)
