"""Corpus de banc : régénération par recette et contrôle d'empreinte (D-3904, D-4403).

Chaque corpus du banc a sa recette (générateur, graine, nombre, options) et ses empreintes dans
``bench/corpus_empreintes.json`` : ``make corpus-tous`` régénère ce qui manque, ``make corpus-verifier`` vérifie
tout. Les corpus n'ont donc pas besoin d'être versionnés.

Empreintes consignées (voir ``bench/README.md``) :

- ``sha256`` : SHA-256 de la liste « ``<sha256>  <chemin relatif>`` » des ``truth.json`` du corpus, triée par chemin
  (octets), soit, depuis la racine du corpus : ``find dev holdout -name truth.json | sort | xargs sha256sum |
  sha256sum`` (``dev`` et ``holdout`` si les deux existent). Valeur d'une régénération par le générateur actuel,
  dont les TIFF sont écrits de façon déterministe (D-4402) ;
- ``sha256_historique`` : même empreinte, pour la copie produite avant D-4402 (octets de remplissage TIFF
  aléatoires), quand elle diffère ;
- ``sha256_pixels`` : même calcul, l'empreinte de chaque TIFF cité étant remplacée par celle de ses pixels ;
- ``sha256_arbre`` / ``sha256_arbre_pixels`` : tous les fichiers du corpus (sauf ``stats_generation.json``, qui
  contient une durée), octets exacts / TIFF par leurs pixels ; ``sha256_arbre_historique`` : octets exacts de la
  copie antérieure à D-4402.

Commandes :

- ``empreinte DOSSIER [--pixels] [--arbre]`` : affiche une empreinte ;
- ``verifier DOSSIER --attendu SHA``, ``verifier NOM`` (recette connue) ou ``verifier --tous`` : 0 si conforme ;
- ``generer NOM [--force]`` ou ``generer --tous`` : régénère un corpus connu (sauté s'il est déjà conforme),
  puis vérifie ;
- ``generer --graine G --prefixe XX --sortie DOSSIER [--nombre N] [--par-controle K] …`` : corpus quelconque,
  empreintes affichées pour être consignées.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
RECETTES = RACINE / "bench" / "corpus_empreintes.json"
# Dépendances propres au banc (numpy pour le générateur 1), hors de l'environnement de l'application :
# `make corpus-deps` les installe ici (uv pip install --target).
DEPS_BANC = RACINE / "var" / "bench_deps"
TIFF = (".tif", ".tiff")
HORS_ARBRE = {"stats_generation.json"}  # contient la durée de génération


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _verites(dossier: Path) -> list[str]:
    return sorted((p.relative_to(dossier).as_posix() for split in ("dev", "holdout")
                   for p in (dossier / split).rglob("truth.json")), key=lambda s: s.encode())


def empreinte(dossier: Path) -> tuple[str, int]:
    """(empreinte, nombre de ``truth.json``)."""
    verites = _verites(dossier)
    lignes = "".join(f"{_sha((dossier / v).read_bytes())}  {v}\n" for v in verites)
    return _sha(lignes.encode()), len(verites)


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
    """Empreinte insensible aux octets de remplissage des TIFF (D-3904) : comme ``empreinte``, mais l'empreinte
    d'octets de chaque fichier TIFF cité par ``truth.json`` est remplacée par celle de ses pixels.

    Avant D-4402, Pillow (compression LZW ou G4 via libtiff) laissait un octet de remplissage non initialisé
    avant le répertoire TIFF : deux générations donnaient les mêmes pixels mais pas toujours les mêmes octets.
    Les corpus produits avant cette correction ne se comparent donc aux régénérations que par cette empreinte.
    """
    verites = _verites(dossier)
    lignes = []
    for v in verites:
        verite = json.loads((dossier / v).read_text(encoding="utf-8"))
        racine = (dossier / v).parent
        for f in verite.get("files", []):
            if str(f.get("path", "")).lower().endswith(TIFF):
                f["sha256"] = "pixels:" + _empreinte_pixels(racine / f["path"])
        canon = json.dumps(verite, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
        lignes.append(f"{_sha(canon)}  {v}\n")
    return _sha("".join(lignes).encode()), len(verites)


def _remplacer(obj, carte: dict[str, str]):
    if isinstance(obj, dict):
        return {k: _remplacer(v, carte) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_remplacer(v, carte) for v in obj]
    if isinstance(obj, str):
        return carte.get(obj, obj)
    return obj


def empreinte_arbre(dossier: Path, pixels: bool = False) -> tuple[str, int]:
    """(empreinte de tous les fichiers du corpus, nombre de fichiers), ``stats_generation.json`` exclu.

    ``pixels`` : chaque TIFF compte par ses pixels ; dans les JSON (``truth.json``, ``manifest.json``), toute
    empreinte d'un fichier ainsi remplacé (TIFF, puis ``truth.json`` qui le cite) l'est aussi, quelle que soit la
    clé qui la porte. Un corpus produit avant D-4402 et sa régénération ont ainsi la même empreinte « pixels ».
    """
    fichiers = sorted((p.relative_to(dossier).as_posix() for p in dossier.rglob("*")
                       if p.is_file() and p.name not in HORS_ARBRE), key=lambda s: s.encode())
    valeurs: dict[str, str] = {}
    carte: dict[str, str] = {}

    def par_octets(rel: str) -> str:
        return _sha((dossier / rel).read_bytes())

    if pixels:
        for rel in (r for r in fichiers if r.lower().endswith(TIFF)):
            valeurs[rel] = "pixels:" + _empreinte_pixels(dossier / rel)
            carte[par_octets(rel)] = valeurs[rel]
        # truth.json d'abord (cite les TIFF), puis les autres JSON (manifest.json cite les truth.json)
        for premier in (True, False):
            for rel in (r for r in fichiers if r.endswith(".json") and (Path(r).name == "truth.json") == premier):
                data = (dossier / rel).read_bytes()
                obj = json.loads(data)
                norm = _remplacer(obj, carte)
                if norm != obj:
                    valeurs[rel] = "json:" + _sha(json.dumps(norm, sort_keys=True, ensure_ascii=False,
                                                             separators=(",", ":")).encode())
                    carte[_sha(data)] = valeurs[rel]
    lignes = "".join(f"{valeurs.get(rel) or par_octets(rel)}  {rel}\n" for rel in fichiers)
    return _sha(lignes.encode()), len(fichiers)


def recettes() -> dict:
    return json.loads(RECETTES.read_text(encoding="utf-8"))["corpus"]


def commande(r: dict, sortie: Path, jobs: int) -> list[str]:
    gen = r.get("generateur", "bench.generator2")
    cmd = [sys.executable, "-m", gen, "--out", str(sortie)]
    if r.get("prefixe"):
        cmd += ["--prefix", r["prefixe"]]
    cmd += ["--count", str(r["nombre"]), "--seed", str(r["graine"]), "--split", r.get("split", "holdout"),
            "--jobs", str(jobs)]
    if r.get("par_controle") is not None:
        cmd += ["--per-control", str(r["par_controle"])]
    cmd += [f"--{o}" for o in r.get("options", [])]
    return cmd


def verifier(dossier: Path, attendu: str | list[str], nb_attendu: int | None = None,
             attendu_pixels: str | None = None, arbre: str | list[str] | None = None,
             arbre_pixels: str | None = None) -> bool:
    """Empreinte exacte (``attendu`` : une valeur ou plusieurs admises), ou à défaut empreinte des pixels
    (``attendu_pixels``) ; idem pour l'arbre complet si ``arbre`` / ``arbre_pixels`` sont donnés."""
    if not dossier.is_dir():
        print(f"{dossier} : absent")
        return False
    admis = [attendu] if isinstance(attendu, str) else [a for a in attendu if a]
    obtenu, n = empreinte(dossier)
    if nb_attendu is not None and n != nb_attendu:
        print(f"{dossier} : {n} dossier(s), {nb_attendu} attendus — NON CONFORME")
        return False
    if obtenu in admis:
        mode = "octets"
    elif attendu_pixels and empreinte_pixels(dossier)[0] == attendu_pixels:
        mode = "pixels"
    else:
        print(f"{dossier} : {n} dossier(s), empreinte {obtenu} — NON CONFORME, attendu {' ou '.join(admis)}")
        return False
    arbres = [a for a in ([arbre] if isinstance(arbre, str) else (arbre or [])) if a]
    if arbres or arbre_pixels:
        a_obtenu, nf = empreinte_arbre(dossier)
        if a_obtenu not in arbres:
            if arbre_pixels and empreinte_arbre(dossier, pixels=True)[0] == arbre_pixels:
                mode = "pixels"
            else:
                print(f"{dossier} : {nf} fichier(s), empreinte de l'arbre {a_obtenu} — NON CONFORME "
                      f"(truth.json conformes, autres fichiers différents)")
                return False
    if mode == "octets":
        histo = " (copie antérieure à D-4402)" if admis and obtenu != admis[0] else ""
        print(f"{dossier} : {n} dossier(s), empreinte {obtenu} — conforme{histo}")
    else:
        print(f"{dossier} : {n} dossier(s), empreinte {obtenu} différente, mais empreinte des pixels conforme "
              "(seuls des octets de remplissage TIFF diffèrent : écriture antérieure à D-4402)")
    return True


def verifier_recette(r: dict, dossier: Path | None = None) -> bool:
    return verifier(dossier or RACINE / r["sortie"], [r["sha256"], r.get("sha256_historique", "")],
                    r.get("dossiers"), r.get("sha256_pixels"), [r.get("sha256_arbre", ""), r.get("sha256_arbre_historique", "")],
                    r.get("sha256_arbre_pixels"))


def generer(r: dict, sortie: Path, jobs: int, force: bool) -> int:
    if r.get("sha256") and not force and sortie.is_dir() and verifier_recette(r, sortie):
        print("Déjà à jour (FORCE=1 pour régénérer).")
        return 0
    if sortie.exists():
        if not force:
            print(f"{sortie} existe et n'est pas conforme : FORCE=1 pour l'effacer et régénérer.")
            return 1
        shutil.rmtree(sortie)
    env = dict(os.environ)
    if DEPS_BANC.is_dir():
        env["PYTHONPATH"] = os.pathsep.join(filter(None, [str(DEPS_BANC), env.get("PYTHONPATH")]))
    manquantes = [d for d in r.get("dependances", []) if not _importable(d.split("==")[0], env)]
    if manquantes:
        print(f"{sortie} : dépendance(s) du générateur absente(s) : {', '.join(manquantes)} — `make corpus-deps` "
              f"(installation dans {DEPS_BANC.relative_to(RACINE)}) ou `uv pip install {' '.join(manquantes)}`")
        return 2
    for split in r.get("splits") or [r.get("split", "holdout")]:
        cmd = commande({**r, "split": split}, sortie, jobs)
        print("$ " + " ".join(cmd[1:]), flush=True)
        rc = subprocess.run(cmd, cwd=RACINE, check=False, env=env).returncode
        if rc != 0:
            return rc
    if r.get("sha256"):
        return 0 if verifier_recette(r, sortie) else 1
    print(json.dumps(empreintes(sortie), indent=2) + "\n(à consigner dans bench/corpus_empreintes.json)")
    return 0


def _importable(module: str, env: dict) -> bool:
    if importlib.util.find_spec(module) is not None:
        return True
    code = f"import importlib.util, sys; sys.exit(importlib.util.find_spec({module!r}) is None)"
    return subprocess.run([sys.executable, "-c", code], env=env, check=False).returncode == 0


def empreintes(dossier: Path) -> dict:
    """Toutes les empreintes d'un corpus, sous la forme de ``bench/corpus_empreintes.json``."""
    sha, n = empreinte(dossier)
    return {"dossiers": n, "sha256": sha, "sha256_pixels": empreinte_pixels(dossier)[0],
            "sha256_arbre": empreinte_arbre(dossier)[0], "sha256_arbre_pixels": empreinte_arbre(dossier, True)[0]}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("empreinte")
    e.add_argument("dossier", type=Path)
    e.add_argument("--pixels", action="store_true", help="TIFF comparés par leurs pixels (voir empreinte_pixels)")
    e.add_argument("--arbre", action="store_true", help="tous les fichiers, pas seulement les truth.json")
    e.add_argument("--toutes", action="store_true", help="toutes les empreintes, au format de la recette (JSON)")
    v = sub.add_parser("verifier")
    v.add_argument("cible", nargs="?", help="nom d'une recette (corpus_g6) ou dossier")
    v.add_argument("--attendu")
    v.add_argument("--tous", action="store_true", help="toutes les recettes")
    g = sub.add_parser("generer")
    g.add_argument("nom", nargs="?", help="recette connue (bench/corpus_empreintes.json)")
    g.add_argument("--tous", action="store_true", help="toutes les recettes (corpus présents et conformes sautés)")
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
        if a.toutes:
            print(json.dumps(empreintes(a.dossier), indent=2))
            return 0
        obtenu, n = (empreinte_arbre(a.dossier, a.pixels) if a.arbre
                     else (empreinte_pixels if a.pixels else empreinte)(a.dossier))
        print(f"{obtenu}  ({n} {'fichiers' if a.arbre else 'truth.json'})")
        return 0
    if a.cmd == "verifier":
        if a.tous:
            ko = [nom for nom, r in recettes().items() if not verifier_recette(r)]
            print(f"{len(recettes()) - len(ko)} corpus conformes sur {len(recettes())}"
                  + (f" ; non conformes ou absents : {', '.join(ko)}" if ko else ""))
            return 1 if ko else 0
        if not a.cible:
            ap.error("verifier : NOM, DOSSIER --attendu SHA, ou --tous")
        if a.attendu:
            return 0 if verifier(Path(a.cible), a.attendu) else 1
        return 0 if verifier_recette(recettes()[a.cible]) else 1
    if a.tous:
        codes = {nom: generer(r, RACINE / r["sortie"], a.jobs, a.force) for nom, r in recettes().items()}
        ko = [nom for nom, c in codes.items() if c]
        print(f"{len(codes) - len(ko)} corpus conformes sur {len(codes)}" + (f" ; échecs : {', '.join(ko)}" if ko else ""))
        return 1 if ko else 0
    if a.nom:
        r = recettes()[a.nom]
        return generer(r, a.sortie or RACINE / r["sortie"], a.jobs, a.force)
    if a.graine is None or not a.prefixe:
        ap.error("generer : NOM, --tous, ou --graine et --prefixe")
    options = [] if a.sans_ext else ["ext"]
    if not a.dev_et_holdout:
        options.append("all-holdout")
    r = {"prefixe": a.prefixe, "graine": a.graine, "nombre": a.nombre, "par_controle": a.par_controle,
         "split": a.split, "options": options}
    return generer(r, a.sortie or RACINE / "bench" / f"corpus_{a.prefixe.lower()}", a.jobs, a.force)


if __name__ == "__main__":
    sys.exit(main())
