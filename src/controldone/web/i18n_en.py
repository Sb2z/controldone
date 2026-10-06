"""Catalogue anglais de l'interface (D-3803) : texte français source -> traduction anglaise.

Clés : textes exacts marqués ``_()`` dans les gabarits et le code web (y compris les paramètres ``{n}``).
Ne contient **pas** les textes juridiques (``AVERTISSEMENT``, ``PHRASE_RENVOI``) ni les textes des constats,
rapports et relevés d'écarts, qui restent en français (``web/i18n.py``)."""

from __future__ import annotations

#: Textes du JavaScript (``static/app.js``), transmis à la page en JSON inerte.
TEXTES_JS: tuple[str, ...] = ()

CATALOGUE_EN: dict[str, str] = {}
