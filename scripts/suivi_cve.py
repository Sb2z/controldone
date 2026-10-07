"""Suivi mensuel des vulnérabilités de l'image (D-4704) : compare le dernier audit Trivy au précédent.

    python scripts/suivi_cve.py [--courant var/audit/image-trivy.json] [--precedent fichier]
                                [--historique var/audit/historique] [--sortie var/audit/suivi-cve.md]
                                [--sans-archiver]

``make audit-image`` (D-3609) bloque sur une vulnérabilité HIGH/CRITICAL **corrigeable** et liste les autres ; il
ne dit pas ce qui a changé depuis le mois dernier. Ce script, **sans réseau** (il ne lit que des fichiers) :

1. lit l'audit courant : JSON de Trivy (``image-trivy.json``) ou, à défaut, ``image.md`` ;
2. le compare au précédent : ``--precedent``, sinon le plus récent de ``--historique`` dont le contenu diffère ;
3. liste, pour HIGH et CRITICAL seulement (clé : paquet + identifiant) : **nouvelles**, **disparues** (corrigées
   par une reconstruction ou retirées de l'image), **devenues corrigeables** (un correctif Debian est paru :
   reconstruire l'image), et le nombre d'inchangées ;
4. écrit le compte rendu (``--sortie``, Markdown) et l'affiche ;
5. archive l'audit courant dans ``--historique`` (``image-trivy-AAAAMMJJ-<empreinte>.json``) pour le mois suivant
   (rien si un fichier identique y est déjà).

Codes de sortie : 0 rien de neuf à traiter (ou première exécution : référence établie) ; 1 nouvelles vulnérabilités graves ou devenues corrigeables (à lire,
éventuellement reconstruire) ; 2 audit courant illisible ou absent. Routine : ``docs/EXPLOITATION.md`` (« Suivi mensuel des vulnérabilités de l'image »).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
GRAVES = ("CRITICAL", "HIGH")
_LIGNE_MD = re.compile(
    r"^- (?P<paquet>\S+) (?P<version>\S+) : (?P<id>\S+) \((?P<gravite>[A-Z]+)\)(?:, corrigé en (?P<corrige>\S+))?"
)


@dataclass(frozen=True)
class Vuln:
    paquet: str
    id: str
    gravite: str
    version: str
    corrige_en: str | None

    @property
    def cle(self) -> tuple[str, str]:
        return (self.paquet, self.id)

    def ligne(self) -> str:
        suite = f", corrigée en {self.corrige_en}" if self.corrige_en else ", sans correctif publié"
        return f"- {self.paquet} {self.version} : {self.id} ({self.gravite}){suite}"


def lire_audit(chemin: Path) -> dict[tuple[str, str], Vuln]:
    """Vulnérabilités HIGH/CRITICAL d'un audit (JSON Trivy ou ``image.md``), par (paquet, identifiant)."""
    texte = chemin.read_text(encoding="utf-8")
    vulns: dict[tuple[str, str], Vuln] = {}
    if chemin.suffix == ".json" or texte.lstrip().startswith("{"):
        donnees = json.loads(texte)
        for r in donnees.get("Results") or []:
            for v in r.get("Vulnerabilities") or []:
                if v.get("Severity") not in GRAVES:
                    continue
                x = Vuln(
                    str(v.get("PkgName")),
                    str(v.get("VulnerabilityID")),
                    str(v.get("Severity")),
                    str(v.get("InstalledVersion")),
                    v.get("FixedVersion") or None,
                )
                vulns.setdefault(x.cle, x)
        return vulns
    for ligne in texte.splitlines():
        m = _LIGNE_MD.match(ligne.strip())
        if m and m["gravite"] in GRAVES:
            x = Vuln(m["paquet"], m["id"], m["gravite"], m["version"], m["corrige"])
            vulns.setdefault(x.cle, x)
    return vulns


def _empreinte(chemin: Path) -> str:
    return hashlib.sha256(chemin.read_bytes()).hexdigest()


def precedent_dans(historique: Path, courant: Path) -> Path | None:
    """Le plus récent audit archivé dont le contenu diffère du courant."""
    if not historique.is_dir():
        return None
    e = _empreinte(courant)
    candidats = sorted(
        p for p in historique.glob("image-trivy-*") if p.is_file() and p.suffix in (".json", ".md")
    )
    for p in reversed(candidats):
        if _empreinte(p) != e:
            return p
    return None


def archiver(courant: Path, historique: Path) -> Path | None:
    """Copie l'audit courant dans l'historique (``image-trivy-AAAAMMJJ-<empreinte>``), sauf s'il y est déjà."""
    historique.mkdir(parents=True, exist_ok=True)
    e = _empreinte(courant)
    if any(_empreinte(p) == e for p in historique.glob("image-trivy-*") if p.is_file()):
        return None
    jour = datetime.now(UTC).strftime("%Y%m%d")
    if courant.suffix == ".json":
        try:
            cree = json.loads(courant.read_text(encoding="utf-8")).get("CreatedAt") or ""
            jour = cree[:10].replace("-", "") or jour
        except ValueError:
            pass
    cible = historique / f"image-trivy-{jour}-{e[:8]}{courant.suffix}"
    shutil.copyfile(courant, cible)
    return cible


@dataclass
class Comparaison:
    nouvelles: list[Vuln]
    disparues: list[Vuln]
    devenues_corrigeables: list[Vuln]
    inchangees: int
    total: int

    @property
    def a_traiter(self) -> bool:
        return bool(self.nouvelles or self.devenues_corrigeables)


def comparer(courant: dict[tuple[str, str], Vuln], precedent: dict[tuple[str, str], Vuln]) -> Comparaison:
    def tri(v: Vuln) -> tuple[int, str, str]:
        return (GRAVES.index(v.gravite), v.paquet, v.id)

    communes = set(courant) & set(precedent)
    return Comparaison(
        nouvelles=sorted((courant[k] for k in set(courant) - set(precedent)), key=tri),
        disparues=sorted((precedent[k] for k in set(precedent) - set(courant)), key=tri),
        devenues_corrigeables=sorted(
            (courant[k] for k in communes if courant[k].corrige_en and not precedent[k].corrige_en), key=tri
        ),
        inchangees=len(communes),
        total=len(courant),
    )


def compte_rendu(c: Comparaison, courant: Path, precedent: Path | None) -> str:
    def section(titre: str, vulns: list[Vuln]) -> list[str]:
        return ["", f"## {titre} ({len(vulns)})", "", *([v.ligne() for v in vulns] or ["- aucune"])]

    lignes = [
        f"# Suivi des vulnérabilités de l'image — {datetime.now(UTC):%Y-%m-%d}",
        "",
        f"Audit courant : `{courant.name}` ; précédent : "
        + (f"`{precedent.name}`" if precedent else "aucun (première exécution : référence établie)")
        + ".",
        f"HIGH/CRITICAL dans l'image : {c.total} ; inchangées depuis le précédent : {c.inchangees}.",
    ]
    lignes += section("Nouvelles", c.nouvelles)
    lignes += section(
        "Devenues corrigeables : reconstruire l'image (make audit-image)", c.devenues_corrigeables
    )
    lignes += section("Disparues (corrigées ou retirées)", c.disparues)
    lignes += [
        "",
        "À faire : "
        + ("lire les nouvelles, reconstruire si un correctif existe." if c.a_traiter else "rien."),
    ]
    return "\n".join(lignes) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Compare l'audit Trivy de l'image au précédent (sans réseau).")
    ap.add_argument(
        "--courant", default=None, help="défaut : var/audit/image-trivy.json, sinon var/audit/image.md"
    )
    ap.add_argument("--precedent", default=None, help="défaut : le plus récent de --historique qui diffère")
    ap.add_argument("--historique", default=str(RACINE / "var" / "audit" / "historique"))
    ap.add_argument("--sortie", default=str(RACINE / "var" / "audit" / "suivi-cve.md"))
    ap.add_argument("--sans-archiver", action="store_true", help="ne pas archiver l'audit courant")
    a = ap.parse_args(argv)

    if a.courant:
        courant = Path(a.courant)
    else:
        audit = RACINE / "var" / "audit"
        courant = audit / "image-trivy.json" if (audit / "image-trivy.json").is_file() else audit / "image.md"
    if not courant.is_file():
        print(f"audit courant introuvable : {courant} (lancer make audit-image)", file=sys.stderr)
        return 2
    historique = Path(a.historique)
    precedent = Path(a.precedent) if a.precedent else precedent_dans(historique, courant)
    try:
        vulns = lire_audit(courant)
        anciennes = lire_audit(precedent) if precedent else {}
    except (OSError, ValueError) as exc:
        print(f"audit illisible : {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    c = comparer(vulns, anciennes)
    texte = compte_rendu(c, courant, precedent)
    sortie = Path(a.sortie)
    sortie.parent.mkdir(parents=True, exist_ok=True)
    sortie.write_text(texte, encoding="utf-8")
    print(texte, end="")
    if not a.sans_archiver:
        archive = archiver(courant, historique)
        if archive:
            print(f"audit archivé : {archive}")
    return 1 if (precedent and c.a_traiter) else 0


if __name__ == "__main__":
    raise SystemExit(main())
