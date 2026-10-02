#!/usr/bin/env python3
"""Squelette de fichier de prospection à partir de l'API officielle « Recherche d'entreprises ».

API : https://recherche-entreprises.api.gouv.fr (DINUM, données SIRENE / RNE, accès libre, sans clé).
Documentation : https://recherche-entreprises.api.gouv.fr/docs/

Ce que fait le script
---------------------
1. Interroge l'API avec des filtres : NAF (commerce de gros 46.xx par défaut), tranche d'effectif
   salarié (10 à 249 salariés), entreprises actives (`etat_administratif=A`), et un ou plusieurs
   mots-clés (`q`, cherché surtout dans la dénomination).
2. Écarte les sociétés dont la dénomination, l'enseigne ou un dirigeant personne morale correspond
   à la liste d'exclusion (groupes L'Occitane et CHANEL, voir `EXCLUSIONS`).
3. Écrit un CSV (UTF-8, séparateur `;`) au format de `commercial/prospects.csv`, avec les colonnes
   de qualification VIDES : preuve d'import, contact publié et source, raison du ciblage.
   Ces colonnes se remplissent À LA MAIN, après lecture du site de l'entreprise.

Ce que le script ne fait PAS
----------------------------
- Il ne lit aucun site d'entreprise, ne cherche aucune adresse e-mail, ne devine aucun contact.
- Il n'envoie rien. Il ne crée aucun compte.

Politesse
---------
L'API limite le débit (7 requêtes par seconde par IP selon sa documentation). Le script attend
`--pause` secondes entre deux appels (1,0 s par défaut), respecte l'en-tête `Retry-After` en cas de
réponse 429, et s'arrête après 5 refus consécutifs.

Exemples
--------
    python prospection_sirene.py --q import --q importateur --q asia --pages 4 \
        --sortie /tmp/squelette.csv
    python prospection_sirene.py --naf 46.49Z --naf 46.90Z --departement 69 --q import

Bibliothèque standard uniquement (urllib, csv, json).
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request

API = "https://recherche-entreprises.api.gouv.fr/search"
USER_AGENT = "ControlDOne-prospection/1.0 (usage ponctuel, faible volume)"

# Tranches INSEE : 11 = 10-19, 12 = 20-49, 21 = 50-99, 22 = 100-199, 31 = 200-249.
TRANCHES_PME = ["11", "12", "21", "22", "31"]
LIBELLE_TRANCHE = {
    "00": "0", "01": "1-2", "02": "3-5", "03": "6-9", "11": "10-19", "12": "20-49",
    "21": "50-99", "22": "100-199", "31": "200-249", "32": "250-499", "41": "500-999",
    "42": "1000-1999", "51": "2000-4999", "52": "5000-9999", "53": "10000+", "NN": "non renseigné",
}

# NAF par défaut : commerce de gros de biens souvent importés hors UE.
NAF_DEFAUT = [
    "46.15Z", "46.16Z", "46.18Z", "46.19B", "46.31Z", "46.37Z", "46.38B", "46.39B",
    "46.41Z", "46.42Z", "46.43Z", "46.44Z", "46.47Z", "46.48Z", "46.49Z", "46.51Z",
    "46.52Z", "46.65Z", "46.69B", "46.69C", "46.73B", "46.74A", "46.90Z",
]

# Groupes exclus (consigne du fondateur). Comparaison sans casse ni accents, sur la dénomination,
# les enseignes et les dirigeants personnes morales. Liste à compléter si un nouveau nom apparaît.
EXCLUSIONS = [
    # Groupe L'Occitane
    "occitane", "melvita", "erborian", "elemis", "sol de janeiro", "dr vranjes", "limelife",
    "grown alchemist", "l'occitane", "loccitane",
    # Groupe CHANEL
    "chanel", "paraffection", "eres", "lesage", "lemarie", "massaro", "goossens", "desrues",
    "maison michel", "causse", "montex", "barrie", "holland & holland", "lognon",
]

COLONNES = [
    "raison_sociale", "siren", "naf", "effectif_tranche", "ville", "site_web", "preuve_import",
    "contact_publie", "source_contact", "raison_ciblage", "canal", "exclusion_verifiee",
    "date_collecte",
]


def normaliser(texte: str) -> str:
    texte = unicodedata.normalize("NFKD", texte or "")
    return "".join(c for c in texte if not unicodedata.combining(c)).lower()


def est_exclu(resultat: dict) -> str | None:
    """Renvoie le motif d'exclusion, ou None."""
    noms = [resultat.get("nom_complet") or "", resultat.get("nom_raison_sociale") or ""]
    siege = resultat.get("siege") or {}
    noms += siege.get("liste_enseignes") or []
    for d in resultat.get("dirigeants") or []:
        if d.get("type_dirigeant") == "personne morale":
            noms.append(d.get("denomination") or "")
    for nom in noms:
        n = normaliser(nom)
        for motif in EXCLUSIONS:
            m = normaliser(motif)
            # mot entier pour les motifs courts (ex. « eres »)
            if (len(m) <= 5 and m in n.replace("-", " ").split()) or (len(m) > 5 and m in n):
                return f"correspond à « {motif} » ({nom})"
    return None


def appeler(params: dict, pause: float) -> dict:
    url = API + "?" + urllib.parse.urlencode(params, doseq=False)
    refus = 0
    while True:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=30) as rep:
                donnees = json.load(rep)
            time.sleep(pause)
            return donnees
        except urllib.error.HTTPError as exc:
            if exc.code in (429, 503) and refus < 5:
                refus += 1
                attente = float(exc.headers.get("Retry-After") or 5) + pause
                print(f"  {exc.code}, nouvel essai dans {attente:.0f} s", file=sys.stderr)
                time.sleep(attente)
                continue
            raise


def chercher(mots: list[str], naf: list[str], tranches: list[str], departement: str | None,
             pages: int, pause: float) -> list[dict]:
    vus: dict[str, dict] = {}
    for mot in mots:
        for page in range(1, pages + 1):
            params = {
                "q": mot,
                "activite_principale": ",".join(naf),
                "tranche_effectif_salarie": ",".join(tranches),
                "etat_administratif": "A",
                "per_page": 25,
                "page": page,
            }
            if departement:
                params["departement"] = departement
            print(f"q={mot!r} page {page}", file=sys.stderr)
            donnees = appeler(params, pause)
            for r in donnees.get("results", []):
                vus.setdefault(r["siren"], r)
            if page >= int(donnees.get("total_pages") or 0):
                break
    return list(vus.values())


def ligne_squelette(r: dict, date: str) -> dict:
    siege = r.get("siege") or {}
    motif = est_exclu(r)
    return {
        "raison_sociale": r.get("nom_complet", ""),
        "siren": r.get("siren", ""),
        "naf": r.get("activite_principale", ""),
        "effectif_tranche": LIBELLE_TRANCHE.get(r.get("tranche_effectif_salarie") or "NN", "?")
        + (f" ({r.get('annee_tranche_effectif_salarie')})" if r.get("annee_tranche_effectif_salarie") else ""),
        "ville": siege.get("libelle_commune", ""),
        "site_web": "",          # à remplir à la main
        "preuve_import": "",     # à remplir : citation courte + URL du site de l'entreprise
        "contact_publie": "",    # à remplir : adresse générique ou page Contact publiée par l'entreprise
        "source_contact": "",    # à remplir : URL où le contact est publié
        "raison_ciblage": "",    # à remplir
        "canal": "PME",
        "exclusion_verifiee": ("NON — " + motif) if motif else
        "à confirmer (aucune correspondance automatique avec la liste L'Occitane / CHANEL)",
        "date_collecte": date,
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--q", action="append", help="mot-clé (répétable). Défaut : import, importateur, impex, trading")
    p.add_argument("--naf", action="append", help="code NAF (répétable). Défaut : liste commerce de gros")
    p.add_argument("--tranche", action="append", help="tranche d'effectif INSEE (répétable). Défaut : 11 à 31")
    p.add_argument("--departement", help="filtre département (ex. 69)")
    p.add_argument("--pages", type=int, default=2, help="pages de 25 résultats par mot-clé (défaut 2)")
    p.add_argument("--pause", type=float, default=1.0, help="secondes entre deux appels (défaut 1,0)")
    p.add_argument("--sortie", default="prospects_squelette.csv", help="fichier CSV produit")
    a = p.parse_args(argv)

    mots = a.q or ["import", "importateur", "impex", "trading"]
    try:
        resultats = chercher(mots, a.naf or NAF_DEFAUT, a.tranche or TRANCHES_PME, a.departement, a.pages, a.pause)
    except (urllib.error.URLError, TimeoutError) as exc:
        print(f"API injoignable depuis cette machine ({exc}). Aucun fichier écrit ; relancer depuis un "
              "poste qui a accès à recherche-entreprises.api.gouv.fr.", file=sys.stderr)
        return 2
    date = dt.date.today().isoformat()
    lignes = [ligne_squelette(r, date) for r in resultats]
    exclues = [l for l in lignes if l["exclusion_verifiee"].startswith("NON")]
    lignes = [l for l in lignes if not l["exclusion_verifiee"].startswith("NON")]
    with open(a.sortie, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLONNES, delimiter=";")
        w.writeheader()
        w.writerows(lignes)
    print(f"{len(lignes)} lignes écrites dans {a.sortie} ; {len(exclues)} écartées (groupes exclus).", file=sys.stderr)
    print("Étape suivante : qualifier chaque ligne à la main (site, preuve d'import, contact publié).", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
