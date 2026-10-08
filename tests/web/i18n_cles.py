"""Extraction des textes marqués à traduire de l'interface (D-3803) : gabarits (``_("…")``, formes de
``pluriel("…", "…", n, aucun="…")``), code web (``_()``, ``traduire()``, ``N_()``, ``pluriel()``, ``accord()``,
``page(titre=…, message=…, erreur=…)``, ``redirection(message=…, erreur=…)``), JavaScript (``T("…")`` et les deux
formes de ``TP(n, "…", "…")``) et libellés fixes affichés par l'interface (statuts, niveaux, natures…)."""

from __future__ import annotations

import ast
import re
from pathlib import Path

import controldone.web as web

RACINE_WEB = Path(web.__file__).parent
GABARITS = RACINE_WEB / "templates"
_JINJA = re.compile(r"""\b_\(\s*"((?:[^"\\]|\\.)*)"|\b_\(\s*'((?:[^'\\]|\\.)*)'""")
_JS = re.compile(r"""\bT\(\s*"((?:[^"\\]|\\.)*)\"""")
#: Accord en nombre : ``pluriel("un", "plusieurs", n, aucun="zéro")`` (gabarits), ``TP(n, "un", "plusieurs")`` (JS).
_CHAINE = r'"((?:[^"\\]|\\.)*)"'
_PLURIEL = re.compile(r"\bpluriel\(\s*" + _CHAINE + r"\s*,\s*" + _CHAINE)
_AUCUN = re.compile(r"\baucun=" + _CHAINE)
_JS_TP = re.compile(r"\bTP\([^\"]*" + _CHAINE + r"\s*,\s*" + _CHAINE)
_KW = {"page": ("titre", "message", "erreur"), "redirection": ("message", "erreur")}


def cles_gabarits() -> dict[str, set[str]]:
    out: dict[str, set[str]] = {}
    for f in sorted(GABARITS.rglob("*.j2")):
        texte = f.read_text(encoding="utf-8")
        for m in _JINJA.finditer(texte):
            brut = m.group(1) if m.group(1) is not None else m.group(2)
            out.setdefault(brut.replace('\\"', '"').replace("\\'", "'"), set()).add(f.name)
        for m in (*_PLURIEL.finditer(texte), *_AUCUN.finditer(texte)):
            for brut in m.groups():
                out.setdefault(brut.replace('\\"', '"'), set()).add(f.name)
    return out


def _nom(f: ast.expr) -> str | None:
    if isinstance(f, ast.Name):
        return f.id
    if isinstance(f, ast.Attribute):
        return f.attr
    return None


def cles_python() -> dict[str, set[str]]:
    out: dict[str, set[str]] = {}
    for f in sorted(RACINE_WEB.glob("*.py")):
        if f.name in ("i18n_en.py",):
            continue
        arbre = ast.parse(f.read_text(encoding="utf-8"))
        for n in ast.walk(arbre):
            if not isinstance(n, ast.Call):
                continue
            nom = _nom(n.func)
            valeurs: list[ast.expr] = []
            if nom in ("_", "traduire", "N_") and n.args:
                valeurs.append(n.args[0])
            if nom in ("pluriel", "accord"):
                valeurs.extend(n.args[:2])
                valeurs.extend(kw.value for kw in n.keywords if kw.arg == "aucun")
            for kw in n.keywords:
                if kw.arg in _KW.get(nom or "", ()):
                    valeurs.append(kw.value)
            for v in valeurs:
                if isinstance(v, ast.Constant) and isinstance(v.value, str) and v.value.strip():
                    out.setdefault(v.value, set()).add(f.name)
    return out


def cles_js() -> set[str]:
    texte = (RACINE_WEB / "static" / "app.js").read_text(encoding="utf-8")
    return {m.group(1) for m in _JS.finditer(texte)} | {x for m in _JS_TP.finditer(texte) for x in m.groups()}


def libelles_fixes() -> set[str]:
    """Libellés fixes affichés par l'interface et traduits à l'affichage (``_(variable)``)."""
    from controldone.rapport.vue import (
        LIBELLES_COMPOSANTE,
        LIBELLES_FORCE,
        LIBELLES_NATURE,
        LIBELLES_OUTCOME,
        LIBELLES_STATUT,
        LIBELLES_TYPE,
    )
    from controldone.services.lecture import LIBELLES_LOT, LIBELLES_NIVEAU, LIBELLES_ROLE, LIBELLES_VALIDATION
    from controldone.services.reclamations import LIBELLES_STATUT_ECART
    from controldone.storage.securite import _NAVIGATEURS, _SYSTEMES

    out: set[str] = set()
    for d in (
        LIBELLES_COMPOSANTE,
        LIBELLES_FORCE,
        LIBELLES_NATURE,
        LIBELLES_OUTCOME,
        LIBELLES_STATUT,
        LIBELLES_TYPE,
        LIBELLES_LOT,
        LIBELLES_NIVEAU,
        LIBELLES_ROLE,
        LIBELLES_VALIDATION,
        LIBELLES_STATUT_ECART,
    ):
        out |= set(d.values())
    out |= {
        "Facture du transitaire",
        "Transport",
        "MRN",
        "Facture commerciale",
        "En cours",
        "En cours de validation",
        "transitaire non identifié",
        "Navigateur inconnu",
        "système inconnu",
    }
    out |= {nom for _m, nom in _NAVIGATEURS} | {nom for _m, nom in _SYSTEMES}
    return out


def toutes() -> set[str]:
    return set(cles_gabarits()) | set(cles_python()) | cles_js() | libelles_fixes()
