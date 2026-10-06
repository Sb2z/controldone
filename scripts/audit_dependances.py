"""Audit des dépendances : vulnérabilités connues, nomenclature logicielle (SBOM CycloneDX) et licences (D-3203).

    python scripts/audit_dependances.py [--lock requirements.lock] [--venv .venv] [--outils .venv-audit]
                                        [--out var/audit] [--hors-ligne] [--image controldone:2.0.0]

Les outils (``pip-audit``, ``cyclonedx-py``, ``pip-licenses``) vivent dans un environnement **séparé**
(``--outils``, créé par ``make audit``) : ils n'entrent ni dans l'image ni dans ``requirements.lock``.

1. **Vulnérabilités** : ``pip-audit`` sur les versions figées de ``requirements.lock`` (``--no-deps``, base PyPI,
   puis OSV si PyPI ne répond pas). Sans réseau : avec ``--hors-ligne``, l'étape est marquée « non vérifiée »
   (code de sortie 0 si le reste est propre) ; sans l'option, l'audit échoue (on ne conclut jamais « propre » sans
   avoir interrogé une base).
2. **SBOM** : ``cyclonedx-py requirements`` (CycloneDX JSON), complété par la licence de chaque paquet et par les
   composants servis par l'application (``static/vendor`` : Motion, polices Geist), avec leur empreinte SHA-256.
3. **Licences** : ``pip-licenses`` sur l'environnement d'exécution, limité aux paquets de ``requirements.lock``.
   Permissives acceptées (MIT, BSD, Apache, ISC, PSF, domaine public, OFL pour les polices) ; toute autre
   (GPL, LGPL, AGPL, MPL, inconnue) est **signalée** et fait échouer l'audit, sauf exception justifiée dans
   ``config/audit_dependances.json``.

4. **Image Docker** (``--image``, D-3609) : paquets du système de l'image construite (Debian de
   ``python:3.11-slim``, Tesseract, libxml2…) par Trivy — binaire ``trivy`` s'il est installé, sinon l'image
   officielle ``aquasec/trivy`` (version figée ``TRIVY_IMAGE``) lancée par Docker. Échoue sur une vulnérabilité
   **HIGH** ou **CRITICAL corrigeable** (une version corrigée existe : reconstruire l'image suffit) ; les non
   corrigées sont comptées et listées (``image-trivy.json``, ``image.md``), à suivre sans bloquer. Mandataire à
   autorité privée : ``AUDIT_CA_BUNDLE=<fichier PEM>`` (monté dans le conteneur de Trivy).

Sorties dans ``--out`` : ``pip-audit.json``, ``sbom.cdx.json``, ``licences.md``, ``resume.json`` (et
``image-trivy.json``, ``image.md`` avec ``--image``). Code de sortie : 0 propre, 1 constat (vulnérabilité ou
licence non permissive non acceptée), 2 erreur d'outillage.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]

PERMISSIVES = re.compile(
    r"\b(mit|mit-0|mit-cmu|bsd|0bsd|apache|isc|psf|python software foundation|zlib|unlicense|public domain|"
    r"cc0|ofl|hpnd|historical permission)\b",
    re.IGNORECASE,
)
COPYLEFT = re.compile(r"\b(a?gpl|lgpl|gnu|mpl|mozilla|eupl|cddl|epl|sspl|osl|cpal|copyleft)\b", re.IGNORECASE)


def normaliser_nom(nom: str) -> str:
    return re.sub(r"[-_.]+", "-", nom).lower()


def lire_lock(chemin: Path) -> dict[str, str]:
    paquets = {}
    for ligne in chemin.read_text(encoding="utf-8").splitlines():
        ligne = ligne.split("#", 1)[0].strip()
        m = re.match(r"^([A-Za-z0-9_.\-]+)(?:\[[^\]]*\])?==([^\s;]+)", ligne)
        if m:
            paquets[normaliser_nom(m.group(1))] = m.group(2)
    return paquets


def classer_licence(texte: str) -> str:
    """``permissive``, ``copyleft`` ou ``inconnue``. Une licence qui offre un choix (« Apache-2.0 OR BSD ») est
    permissive si l'une des options l'est ; un copyleft cité sans alternative l'emporte."""
    t = (texte or "").strip()
    if not t or t.upper() == "UNKNOWN":
        return "inconnue"
    options = re.split(r"\s+OR\s+|\s*;\s*", t)
    if any(PERMISSIVES.search(o) and not COPYLEFT.search(o) for o in options):
        return "permissive"
    if COPYLEFT.search(t):
        return "copyleft"
    return "inconnue"


def executer(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


def audit_vulnerabilites(outils: Path, lock: Path, sortie: Path, ignorees: dict[str, str]) -> dict:
    erreurs = []
    for service in ("pypi", "osv"):
        sortie.unlink(missing_ok=True)
        cmd = [
            str(outils / "pip-audit"),
            "-r",
            str(lock),
            "--no-deps",
            "--disable-pip",
            "--progress-spinner",
            "off",
            "-s",
            service,
            "-f",
            "json",
            "-o",
            str(sortie),
        ]
        for vid in sorted(ignorees):
            cmd += ["--ignore-vuln", vid]
        r = executer(cmd)
        if sortie.exists() and r.returncode in (0, 1):
            donnees = json.loads(sortie.read_text(encoding="utf-8") or "{}")
            vulns = [
                {
                    "paquet": d["name"],
                    "version": d["version"],
                    "id": v["id"],
                    "corrige_en": v.get("fix_versions"),
                }
                for d in donnees.get("dependencies", [])
                for v in d.get("vulns", [])
            ]
            return {
                "verifie": True,
                "service": service,
                "vulnerabilites": vulns,
                "ignorees": sorted(ignorees),
            }
        erreurs.append(f"{service}: {(r.stderr or r.stdout).strip().splitlines()[-1:] or ['?']}")
    return {"verifie": False, "erreurs": erreurs, "vulnerabilites": []}


def licences(outils: Path, venv_python: Path, lock: dict[str, str], acceptees: dict[str, str]) -> dict:
    r = executer([str(outils / "pip-licenses"), "--python", str(venv_python), "--format=json", "--with-urls"])
    if r.returncode != 0:
        raise RuntimeError("pip-licenses : " + r.stderr.strip())
    installes = {normaliser_nom(x["Name"]): x for x in json.loads(r.stdout)}
    lignes, signales, ecarts = [], [], []
    for nom, version in sorted(lock.items()):
        x = installes.get(nom)
        licence = x["License"] if x else "UNKNOWN"
        if x is None:
            ecarts.append(f"{nom}=={version} : absent de l'environnement (licence non lue)")
        elif x["Version"] != version:
            ecarts.append(f"{nom} : figé {version}, installé {x['Version']}")
        classe = classer_licence(licence)
        statut = "ok" if classe == "permissive" else ("accepte" if nom in acceptees else "SIGNALE")
        if statut == "SIGNALE":
            signales.append(f"{nom} ({licence})")
        lignes.append(
            {
                "paquet": nom,
                "version": version,
                "licence": licence,
                "classe": classe,
                "statut": statut,
                "justification": acceptees.get(nom, ""),
                "url": (x or {}).get("URL", ""),
            }
        )
    hors_lock = sorted(n for n in installes if n not in lock and n != "controldone")
    return {"paquets": lignes, "signales": signales, "ecarts_lock": ecarts, "installes_hors_lock": hors_lock}


def sha256(chemin: Path) -> str:
    return hashlib.sha256(chemin.read_bytes()).hexdigest()


def sbom(outils: Path, lock: Path, sortie: Path, lic: dict, embarques: list[dict]) -> int:
    r = executer([str(outils / "cyclonedx-py"), "requirements", str(lock), "--of", "JSON", "-o", str(sortie)])
    if r.returncode != 0:
        raise RuntimeError("cyclonedx-py : " + (r.stderr or r.stdout).strip())
    doc = json.loads(sortie.read_text(encoding="utf-8"))
    par_nom = {p["paquet"]: p for p in lic["paquets"]}
    for c in doc.get("components", []):
        p = par_nom.get(normaliser_nom(c.get("name", "")))
        if p and not c.get("licenses"):
            c["licenses"] = [{"license": {"name": p["licence"]}}]
    for e in embarques:
        chemin = RACINE / e["chemin"]
        comp = {
            "type": "library" if chemin.suffix == ".js" else "file",
            "name": e["nom"],
            "version": e["version"],
            "bom-ref": f"embarque:{e['nom']}",
            "licenses": [{"license": {"id": e["licence"]}}],
            "description": f"servi par l'application : {e['chemin']}",
            "externalReferences": [{"type": "website", "url": e["source"]}],
        }
        if chemin.exists():
            comp["hashes"] = [{"alg": "SHA-256", "content": sha256(chemin)}]
        doc.setdefault("components", []).append(comp)
    doc.setdefault("metadata", {})["component"] = {
        "type": "application",
        "name": "controldone",
        "version": "2.0.0",
        "bom-ref": "controldone",
    }
    sortie.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return len(doc.get("components", []))


def verifier_embarques(embarques: list[dict]) -> list[str]:
    """Chaque fichier de ``static/vendor`` (hors licences) est déclaré, avec une licence permissive et son texte."""
    problemes = []
    declares = {e["chemin"] for e in embarques}
    vendor = RACINE / "src/controldone/web/static/vendor"
    for f in sorted(vendor.rglob("*")):
        rel = str(f.relative_to(RACINE))
        if f.is_file() and not f.name.upper().startswith("LICENSE") and rel not in declares:
            problemes.append(f"{rel} : composant embarqué non déclaré dans config/audit_dependances.json")
    for e in embarques:
        if classer_licence(e["licence"]) != "permissive":
            problemes.append(f"{e['nom']} : licence {e['licence']} non permissive")
        if not (RACINE / e["fichier_licence"]).exists():
            problemes.append(f"{e['nom']} : texte de licence absent ({e['fichier_licence']})")
    return problemes


def ecrire_licences_md(chemin: Path, lic: dict, embarques: list[dict], problemes: list[str]) -> None:
    lignes = [
        "# Licences des dépendances (généré par `make audit`)",
        "",
        "| Paquet | Version | Licence | Classe | Statut |",
        "|---|---|---|---|---|",
    ]
    lignes += [
        f"| {p['paquet']} | {p['version']} | {p['licence']} | {p['classe']} | {p['statut']} |"
        for p in lic["paquets"]
    ]
    lignes += [
        "",
        "## Composants servis par l'application (`static/vendor`)",
        "",
        "| Composant | Version | Licence | Fichier |",
        "|---|---|---|---|",
    ]
    lignes += [f"| {e['nom']} | {e['version']} | {e['licence']} | `{e['chemin']}` |" for e in embarques]
    acceptes = [p for p in lic["paquets"] if p["statut"] == "accepte"]
    if acceptes:
        lignes += ["", "## Exceptions acceptées", ""] + [
            f"- **{p['paquet']}** : {p['justification']}" for p in acceptes
        ]
    if lic["signales"] or problemes:
        lignes += ["", "## À traiter", ""] + [f"- {s}" for s in [*lic["signales"], *problemes]]
    if lic["ecarts_lock"] or lic["installes_hors_lock"]:
        lignes += ["", "## Écarts entre l'environnement et `requirements.lock` (information)", ""]
        lignes += [f"- {s}" for s in lic["ecarts_lock"]]
        if lic["installes_hors_lock"]:
            lignes.append(
                "- installés hors du fichier figé (outils de développement ou ajout non figé) : "
                + ", ".join(lic["installes_hors_lock"])
            )
    chemin.write_text("\n".join(lignes) + "\n", encoding="utf-8")


#: Image officielle de Trivy utilisée quand le binaire n'est pas installé (version figée : un scanner qui change
#: de lui-même rendrait l'audit non reproductible).
TRIVY_IMAGE = "aquasec/trivy:0.75.0"
GRAVES = ("CRITICAL", "HIGH")


def commande_trivy(image: str, sortie: Path) -> list[str]:
    """Commande Trivy : binaire local, sinon conteneur ``TRIVY_IMAGE`` (socket Docker, cache ``~/.cache/trivy``)."""
    options = ["image", "--scanners", "vuln", "--pkg-types", "os,library", "--format", "json", "--quiet"]
    if shutil.which("trivy"):
        return ["trivy", *options, "-o", str(sortie), image]
    cache = Path.home() / ".cache" / "trivy"
    cache.mkdir(parents=True, exist_ok=True)
    cmd = [
        "docker",
        "run",
        "--rm",
        "-v",
        "/var/run/docker.sock:/var/run/docker.sock",
        "-v",
        f"{cache}:/root/.cache/trivy",
        "-v",
        f"{sortie.parent.resolve()}:/sortie",
    ]
    mandataire = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
    if mandataire:
        cmd += ["--network", "host", "-e", f"HTTPS_PROXY={mandataire}"]
    ca = os.environ.get("AUDIT_CA_BUNDLE")
    if ca:
        cmd += [
            "-v",
            f"{Path(ca).resolve()}:/etc/ssl/certs/audit-ca.pem:ro",
            "-e",
            "SSL_CERT_FILE=/etc/ssl/certs/audit-ca.pem",
        ]
    return [*cmd, TRIVY_IMAGE, *options, "-o", f"/sortie/{sortie.name}", image]


def resumer_trivy(donnees: dict) -> dict:
    """Comptes par gravité ; vulnérabilités graves corrigeables (bloquantes) et non corrigées (suivies)."""
    par_gravite: dict[str, int] = {}
    corrigeables, non_corrigees = [], []
    for r in donnees.get("Results") or []:
        for v in r.get("Vulnerabilities") or []:
            g = v.get("Severity", "UNKNOWN")
            par_gravite[g] = par_gravite.get(g, 0) + 1
            if g in GRAVES:
                ligne = {
                    "paquet": v.get("PkgName"),
                    "version": v.get("InstalledVersion"),
                    "id": v.get("VulnerabilityID"),
                    "gravite": g,
                    "corrige_en": v.get("FixedVersion") or None,
                    "cible": r.get("Target"),
                }
                (corrigeables if ligne["corrige_en"] else non_corrigees).append(ligne)
    os_ = (donnees.get("Metadata") or {}).get("OS") or {}
    return {
        "verifie": True,
        "systeme": f"{os_.get('Family', '?')} {os_.get('Name', '')}".strip(),
        "par_gravite": par_gravite,
        "corrigeables": corrigeables,
        "non_corrigees": non_corrigees,
    }


def audit_image(image: str, out: Path) -> dict:
    sortie = out / "image-trivy.json"
    sortie.unlink(missing_ok=True)
    try:
        r = executer(commande_trivy(image, sortie))
    except OSError as exc:
        return {"verifie": False, "erreur": f"{type(exc).__name__} : ni trivy ni docker utilisables"}
    if r.returncode != 0 or not sortie.exists():
        return {"verifie": False, "erreur": ((r.stderr or r.stdout).strip().splitlines() or ["?"])[-1][:300]}
    res = resumer_trivy(json.loads(sortie.read_text(encoding="utf-8")))
    lignes = [
        f"# Audit de l'image `{image}` (Trivy, généré par `make audit-image`)",
        "",
        f"Système : {res['systeme']}. Par gravité : "
        + ", ".join(f"{k} {v}" for k, v in sorted(res["par_gravite"].items())),
        "",
    ]
    lignes += ["## Graves et corrigeables (bloquant : reconstruire l'image)", ""]
    lignes += [
        f"- {v['paquet']} {v['version']} : {v['id']} ({v['gravite']}), corrigé en {v['corrige_en']}"
        for v in res["corrigeables"]
    ] or ["- aucune"]
    lignes += ["", "## Graves sans correctif publié (suivi)", ""]
    lignes += [
        f"- {v['paquet']} {v['version']} : {v['id']} ({v['gravite']})" for v in res["non_corrigees"]
    ] or ["- aucune"]
    (out / "image.md").write_text("\n".join(lignes) + "\n", encoding="utf-8")
    return res


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--lock", default=str(RACINE / "requirements.lock"))
    ap.add_argument("--venv", default=str(RACINE / ".venv"), help="environnement d'exécution (licences)")
    ap.add_argument("--outils", default=str(RACINE / ".venv-audit"), help="environnement des outils d'audit")
    ap.add_argument("--config", default=str(RACINE / "config" / "audit_dependances.json"))
    ap.add_argument("--out", default=str(RACINE / "var" / "audit"))
    ap.add_argument(
        "--hors-ligne",
        dest="hors_ligne",
        action="store_true",
        help="accepter un audit de vulnérabilités impossible faute de réseau",
    )
    ap.add_argument(
        "--image", default=None, help="image Docker construite à auditer (paquets du système, Trivy)"
    )
    a = ap.parse_args(argv)
    outils = Path(a.outils) / "bin"
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    config = json.loads(Path(a.config).read_text(encoding="utf-8"))
    for section in ("vulnerabilites_ignorees", "licences_acceptees"):
        vides = [k for k, v in config.get(section, {}).items() if not str(v).strip()]
        if vides:
            print(f"Exception sans justification dans {section} : {', '.join(vides)}", file=sys.stderr)
            return 2
    lock = lire_lock(Path(a.lock))
    embarques = config.get("composants_embarques", [])
    try:
        vul = audit_vulnerabilites(
            outils, Path(a.lock), out / "pip-audit.json", config.get("vulnerabilites_ignorees", {})
        )
        lic = licences(outils, Path(a.venv) / "bin" / "python", lock, config.get("licences_acceptees", {}))
        n_comp = sbom(outils, Path(a.lock), out / "sbom.cdx.json", lic, embarques)
    except (OSError, RuntimeError, json.JSONDecodeError) as exc:
        print(f"Erreur d'outillage : {exc} (lancer « make audit », qui installe les outils)", file=sys.stderr)
        return 2
    problemes = verifier_embarques(embarques)
    img = audit_image(a.image, out) if a.image else None
    ecrire_licences_md(out / "licences.md", lic, embarques, problemes)
    resume = {
        "paquets": len(lock),
        "composants_sbom": n_comp,
        "vulnerabilites": vul,
        "licences_signalees": lic["signales"],
        "embarques": problemes,
        "ecarts_lock": lic["ecarts_lock"],
        "installes_hors_lock": lic["installes_hors_lock"],
        "image": img,
    }
    (out / "resume.json").write_text(
        json.dumps(resume, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    print(f"Paquets figés : {len(lock)} ; composants SBOM : {n_comp} (dont {len(embarques)} embarqués)")
    if vul["verifie"]:
        print(f"Vulnérabilités connues ({vul['service']}) : {len(vul['vulnerabilites'])}")
        for v in vul["vulnerabilites"]:
            print(
                f"  - {v['paquet']} {v['version']} : {v['id']} (corrigé en {', '.join(v['corrige_en'] or []) or '?'})"
            )
    else:
        print("Vulnérabilités : NON VÉRIFIÉES (aucune base joignable) : " + " | ".join(vul["erreurs"]))
    print(
        f"Licences non permissives non acceptées : {len(lic['signales'])}"
        + ("".join(f"\n  - {s}" for s in lic["signales"]))
    )
    for p in problemes:
        print(f"  - {p}")
    if img is not None:
        if img["verifie"]:
            print(
                f"Image {a.image} ({img['systeme']}) : "
                + ", ".join(f"{k} {v}" for k, v in sorted(img["par_gravite"].items()))
                + f" ; graves corrigeables : {len(img['corrigeables'])}, graves sans correctif : {len(img['non_corrigees'])}"
                + f" (détail : {out}/image.md)"
            )
            for v in img["corrigeables"]:
                print(
                    f"  - {v['paquet']} {v['version']} : {v['id']} ({v['gravite']}), corrigé en {v['corrige_en']}"
                )
        else:
            print(f"Image {a.image} : NON VÉRIFIÉE ({img['erreur']})")
    print(f"Sorties : {out}/sbom.cdx.json, licences.md, pip-audit.json, resume.json")
    if (
        vul["vulnerabilites"]
        or lic["signales"]
        or problemes
        or (img and img["verifie"] and img["corrigeables"])
    ):
        return 1
    if img is not None and not img["verifie"] and not a.hors_ligne:
        return 1
    if not vul["verifie"] and not a.hors_ligne:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
