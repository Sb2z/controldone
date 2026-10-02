"""Rendu HTML du rapport (Jinja2, CSS intégrée, aucune ressource externe, lisible sans JavaScript)."""

from __future__ import annotations

import base64
from decimal import Decimal
from functools import lru_cache

from jinja2 import Environment, PackageLoader, select_autoescape

from controldone.formatage import format_montant
from controldone.rapport.vue import RapportVue

__all__ = ["rendre_html", "texte_visible"]


@lru_cache(maxsize=1)
def _env() -> Environment:
    env = Environment(
        loader=PackageLoader("controldone.rapport", "templates"),
        autoescape=select_autoescape(["html", "j2"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    env.globals["b64"] = lambda b: base64.b64encode(b).decode("ascii")
    env.globals["fm"] = lambda x: "—" if x is None or x == Decimal(0) else format_montant(x, "EUR")
    return env


def rendre_html(vue: RapportVue) -> str:
    return _env().get_template("rapport.html.j2").render(r=vue)


def texte_visible(html: str) -> str:
    """Texte affiché d'une page HTML (balises, styles et images retirés) : contrôle des garde-fous."""
    import re
    from html import unescape

    t = re.sub(r"<style.*?</style>", " ", html, flags=re.S)
    t = re.sub(r"<img[^>]*>", " ", t)
    t = re.sub(r"<[^>]+>", " ", t)
    return re.sub(r"\s+", " ", unescape(t)).strip()
