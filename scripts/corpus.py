"""Corpus de banc non versionnés : régénération par graine et contrôle d'empreinte (D-3904).

Les corpus sont reproductibles à l'octet près par leur recette (générateur, graine, options). À partir de
``corpus_g6``, ils ne sont plus versionnés : la recette et l'empreinte attendue sont dans
``bench/corpus_empreintes.json`` ; ``make corpus-g6`` régénère et vérifie.

Empreinte : SHA-256 de la liste « ``<sha256>  <chemin relatif>`` » des ``truth.json`` du corpus, triée par chemin
(octets), soit, depuis la racine du corpus : ``find holdout -name truth.json | sort | xargs sha256sum | sha256sum``
(``dev`` et ``holdout`` si les deux existent).

Commandes :

- ``empreinte DOSSIER`` : affiche l'empreinte ;
- ``verifier DOSSIER --attendu SHA`` ou ``verifier NOM`` (recette connue) : 0 si conforme, 1 sinon ;
- ``generer NOM [--force]`` : régénère un corpus connu (sauté s'il est déjà conforme), puis vérifie ;
- ``generer --graine G --prefixe XX --sortie DOSSIER [--nombre N] [--par-controle K] …`` : corpus quelconque,
  empreinte affichée pour être consignée.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
RECETTES = RACINE / "bench" / "corpus_empreintes.json"


def empreinte(dossier: Path) -> tuple[str, int]:
    """(empreinte, nombre de ``truth.json``)."""
    verites = sorted((p.relative_to(dossier).as_posix() for split in ("dev", "holdout")
                      for p in (dossier / split).rglob("truth.json")), key=lambda s: s.encode())
    lignes = "".join(f"{hashlib.sha256((dossier / v).read_bytes()).hexdigest()}  {v}\n" for v in verites)
    return hashlib.sha256(lignes.encode()).hexdigest(), len(verites)


def _empreinte_pixels(chemin: Path) -> str:
    """SHA-256 des pixels décodés d'une image TIFF (mode, taille et octets de chaque page)."""
    from PIL import Image, ImageSequence

    h = hashlib.sha256()
    with Image.open(chemin) as im:
        for page in ImageSequence.Iterator(im):
            h.update(f"{page.mode}|{page.size}|".encode())
            h.update(page.tobytes())
    return h.hexdigest()


def empreinte_pixels(dossier: Path) -> tuple[str, int]:
    """Empreinte de secours, insensible aux octets de remplissage des TIFF (D-3904) : comme ``empreinte``, mais
    l'empreinte d'octets de chaque fichier TIFF cité par ``truth.json`` est remplacée par celle de ses pixels.

    Pillow (compression LZW via libtiff) laisse un octet de remplissage non initialisé avant le répertoire TIFF :
    deux régénérations donnent les mêmes pixels mais pas toujours les mêmes octets (constaté sur corpus_g6 :
    6 fichiers TIFF sur 160 dossiers, un octet chacun).
    """
    verites = sorted((p.relative_to(dossier).as_posix() for split in ("dev", "holdout")
                      for p in (dossier / split).rglob("truth.json")), key=lambda s: s.encode())
    lignes = []
    for v in verites:
        verite = json.loads((dossier / v).read_text(encoding="utf-8"))
        racine = (dossier / v).parent
        for f in verite.get("files", []):
            if str(f.get("path", "")).lower().endswith((".tif", ".tiff")):
                f["sha256"] = "pixels:" + _empreinte_pixels(racine / f["path"])
        canon = json.dumps(verite, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
        lignes.append(f"{hashlib.sha256(canon).hexdigest()}  {v}\n")
    return hashlib.sha256("".join(lignes).encode()).hexdigest(), len(verites)


def recettes() -> dict:
    return json.loads(RECETTES.read_text(encoding="utf-8"))["corpus"]


def commande(r: dict, sortie: Path, jobs: int) -> list[str]:
    cmd = [sys.executable, "-m", r.get("generateur", "bench.generator2"), "--out", str(sortie),
           "--prefix", r["prefixe"], "--count", str(r["nombre"]), "--seed", str(r["graine"]),
           "--split", r.get("split", "holdout"), "--jobs", str(jobs)]
    if r.get("par_controle") is not None:
        cmd += ["--per-control", str(r["par_controle"])]
    cmd += [f"--{o}" for o in r.get("options", [])]
    return cmd


def verifier(dossier: Path, attendu: str, nb_attendu: int | None = None, attendu_pixels: str | None = None) -> bool:
    """Empreinte exacte, ou à défaut empreinte des pixels (``attendu_pixels``) : voir ``empreinte_pixels``."""
    if not dossier.is_dir():
        print(f"{dossier} : absent")
        return False
    obtenu, n = empreinte(dossier)
    if nb_attendu is not None and n != nb_attendu:
        print(f"{dossier} : {n} dossier(s), {nb_attendu} attendus — NON CONFORME")
        return False
    if obtenu == attendu:
        print(f"{dossier} : {n} dossier(s), empreinte {obtenu} — conforme")
        return True
    if attendu_pixels:
        pixels, _ = empreinte_pixels(dossier)
        if pixels == attendu_pixels:
            print(f"{dossier} : {n} dossier(s), empreinte {obtenu} différente de {attendu}, mais empreinte des "
                  f"pixels {pixels} — conforme (seuls des octets de remplissage TIFF diffèrent)")
            return True
    print(f"{dossier} : {n} dossier(s), empreinte {obtenu} — NON CONFORME, attendu {attendu}")
    return False


def generer(r: dict, sortie: Path, jobs: int, force: bool) -> int:
    if r.get("sha256") and not force and sortie.is_dir() and verifier(sortie, r["sha256"], r.get("dossiers"), r.get("sha256_pixels")):
        print("Déjà à jour (FORCE=1 pour régénérer).")
        return 0
    if sortie.exists():
        if not force:
            print(f"{sortie} existe et n'est pas conforme : FORCE=1 pour l'effacer et régénérer.")
            return 1
        shutil.rmtree(sortie)
    cmd = commande(r, sortie, jobs)
    print("$ " + " ".join(cmd[1:]), flush=True)
    rc = subprocess.run(cmd, cwd=RACINE, check=False).returncode
    if rc != 0:
        return rc
    if r.get("sha256"):
        return 0 if verifier(sortie, r["sha256"], r.get("dossiers"), r.get("sha256_pixels")) else 1
    obtenu, n = empreinte(sortie)
    pixels, _ = empreinte_pixels(sortie)
    print(f"{sortie} : {n} dossier(s), sha256 {obtenu}, sha256_pixels {pixels} "
          "(à consigner dans bench/corpus_empreintes.json)")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("empreinte")
    e.add_argument("dossier", type=Path)
    e.add_argument("--pixels", action="store_true", help="empreinte des pixels des TIFF (voir empreinte_pixels)")
    v = sub.add_parser("verifier")
    v.add_argument("cible", help="nom d'une recette (corpus_g6) ou dossier")
    v.add_argument("--attendu")
    g = sub.add_parser("generer")
    g.add_argument("nom", nargs="?", help="recette connue (bench/corpus_empreintes.json)")
    g.add_argument("--graine", type=int)
    g.add_argument("--prefixe")
    g.add_argument("--sortie", type=Path)
    g.add_argument("--nombre", type=int, default=160)
    g.add_argument("--par-controle", type=int, default=3)
    g.add_argument("--split", default="holdout", choices=["dev", "holdout", "all"])
    g.add_argument("--sans-ext", action="store_true", help="sorties 2.0.1 (sans l'extension 2.1)")
    g.add_argument("--dev-et-holdout", action="store_true", help="split par empreinte au lieu de tout en holdout")
    g.add_argument("--jobs", type=int, default=2)
    g.add_argument("--force", action="store_true")
    a = ap.parse_args(argv)

    if a.cmd == "empreinte":
        obtenu, n = (empreinte_pixels if a.pixels else empreinte)(a.dossier)
        print(f"{obtenu}  ({n} truth.json)")
        return 0
    if a.cmd == "verifier":
        if a.attendu:
            return 0 if verifier(Path(a.cible), a.attendu) else 1
        r = recettes()[a.cible]
        return 0 if verifier(RACINE / r["sortie"], r["sha256"], r.get("dossiers"), r.get("sha256_pixels")) else 1
    if a.nom:
        r = recettes()[a.nom]
        return generer(r, a.sortie or RACINE / r["sortie"], a.jobs, a.force)
    if a.graine is None or not a.prefixe:
        ap.error("generer : NOM, ou --graine et --prefixe")
    options = [] if a.sans_ext else ["ext"]
    if not a.dev_et_holdout:
        options.append("all-holdout")
    r = {"prefixe": a.prefixe, "graine": a.graine, "nombre": a.nombre, "par_controle": a.par_controle,
         "split": a.split, "options": options}
    return generer(r, a.sortie or RACINE / "bench" / f"corpus_{a.prefixe.lower()}", a.jobs, a.force)


if __name__ == "__main__":
    sys.exit(main())
