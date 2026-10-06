"""Vérifications avant enregistrement (D-3901), sans réseau ni dépendance hors bibliothèque standard (+ PyYAML).

Appelé par ``.pre-commit-config.yaml`` (via ``lancer.sh``) avec la liste des fichiers à vérifier :

- ``espaces``  : espaces en fin de ligne (fichiers texte) ;
- ``lourds``   : fichiers de plus de 2 Mo (``--max-ko``) ; les corpus de banc sont exclus par la configuration ;
- ``secrets``  : clés privées et jetons d'API reconnaissables (Anthropic, Stripe réel, AWS, GitHub, Slack) ;
  une ligne marquée ``pragma: allowlist secret`` est ignorée (valeur fictive assumée) ;
- ``syntaxe``  : JSON et YAML lisibles ;
- ``print``    : pas de ``print(`` dans les paquets cœur (contrôles, normalisation, web, extraction…), dont les
  sorties passent par les journaux ou les rapports ; les commandes (cli, sauvegarde…) gardent leurs ``print``.

Sortie : 0 si tout va bien, 1 sinon (une ligne par constat, ``chemin:ligne: message``).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Iterator
from pathlib import Path

MOTIFS_SECRETS = [
    ("clé privée", re.compile(r"-----BEGIN (?:[A-Z]+ )*PRIVATE KEY(?: BLOCK)?-----")),
    ("clé Anthropic", re.compile(r"sk-ant-(?:api|admin)\d{2}-[A-Za-z0-9_-]{20,}")),
    ("clé Stripe réelle", re.compile(r"\b(?:sk|rk)_live_[A-Za-z0-9]{16,}")),
    ("secret de webhook Stripe", re.compile(r"\bwhsec_[A-Za-z0-9]{24,}")),
    ("clé AWS", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    (
        "jeton GitHub",
        re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{36}\b|\bgithub_pat_[A-Za-z0-9_]{60,}"),
    ),
    ("jeton Slack", re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{20,}")),
]
PRAGMA = "pragma: allowlist secret"
PRINT_RE = re.compile(r"^\s*print\(")


def _texte(chemin: Path) -> str | None:
    """Contenu d'un fichier texte (UTF-8) ; ``None`` pour un binaire."""
    try:
        brut = chemin.read_bytes()
    except OSError:
        return None
    if b"\0" in brut[:8192]:
        return None
    try:
        return brut.decode("utf-8")
    except UnicodeDecodeError:
        return None


def _lignes(chemin: Path) -> Iterator[tuple[int, str]]:
    texte = _texte(chemin)
    if texte is None:
        return
    yield from enumerate(texte.splitlines(), start=1)


def _espace_final(ligne: str, markdown: bool) -> bool:
    if ligne == ligne.rstrip(" \t"):
        return False
    # Markdown : deux espaces après du texte = retour à la ligne forcé, admis.
    return not (
        markdown and ligne.endswith("  ") and ligne[:-2].strip() and ligne[:-2] == ligne[:-2].rstrip()
    )


def espaces(fichiers: list[Path]) -> list[str]:
    return [
        f"{p}:{n}: espace en fin de ligne"
        for p in fichiers
        for n, ligne in _lignes(p)
        if _espace_final(ligne, p.suffix == ".md")
    ]


def lourds(fichiers: list[Path], max_ko: int) -> list[str]:
    return [
        f"{p}: {p.stat().st_size // 1024} Ko > {max_ko} Ko (corpus : ne pas versionner, voir bench/README.md)"
        for p in fichiers
        if p.is_file() and p.stat().st_size > max_ko * 1024
    ]


def secrets(fichiers: list[Path]) -> list[str]:
    sortie = []
    for p in fichiers:
        for n, ligne in _lignes(p):
            if PRAGMA in ligne:
                continue
            sortie += [f"{p}:{n}: {nom} probable" for nom, motif in MOTIFS_SECRETS if motif.search(ligne)]
    return sortie


def syntaxe(fichiers: list[Path]) -> list[str]:
    import yaml

    sortie = []
    for p in fichiers:
        try:
            texte = p.read_text(encoding="utf-8")
            if p.suffix == ".json":
                json.loads(texte)
            elif p.suffix in {".yml", ".yaml"}:
                list(yaml.safe_load_all(texte))
        except (OSError, UnicodeDecodeError, ValueError, yaml.YAMLError) as exc:
            premiere = str(exc).splitlines()[0] if str(exc) else type(exc).__name__
            sortie.append(f"{p}: illisible ({premiere})")
    return sortie


def sans_print(fichiers: list[Path]) -> list[str]:
    return [
        f"{p}:{n}: print() dans un paquet cœur (utiliser logging)"
        for p in fichiers
        for n, ligne in _lignes(p)
        if PRINT_RE.match(ligne)
    ]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("verif", choices=["espaces", "lourds", "secrets", "syntaxe", "print"])
    ap.add_argument("fichiers", nargs="*", type=Path)
    ap.add_argument("--max-ko", type=int, default=2048)
    a = ap.parse_intermixed_args(argv)
    fichiers = [p for p in a.fichiers if p.is_file()]
    constats = {
        "espaces": lambda: espaces(fichiers),
        "lourds": lambda: lourds(fichiers, a.max_ko),
        "secrets": lambda: secrets(fichiers),
        "syntaxe": lambda: syntaxe(fichiers),
        "print": lambda: sans_print(fichiers),
    }[a.verif]()
    for c in constats:
        print(c)
    return 1 if constats else 0


if __name__ == "__main__":
    sys.exit(main())
