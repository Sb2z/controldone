"""Auto-contrôles du corpus généré.

    python -m bench.generator.check --corpus bench/corpus --seed 20261002 --count 250 [--determinism]

1. arithmétique des valeurs NON injectées (lignes, sommes, base × taux, totaux) ;
2. validité des identifiants fictifs, présence du marqueur « DONNÉES FICTIVES » ;
3. composition (gabarits, mises en page, dégradations, scénarios) ;
4. couverture des contrôles A1–G6 : split dev mesuré sur les fichiers, split holdout calculé par
   simulation (aucun fichier holdout n'est écrit) ;
5. déterminisme : 3 dossiers générés deux fois dans des répertoires temporaires, empreintes comparées
   (et comparées au corpus existant s'il a été généré avec la même graine).
"""

from __future__ import annotations

import argparse
import glob
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from collections import Counter, defaultdict
from decimal import Decimal

from .common import luhn_ok
from .plan import CERTAIN_ELIGIBLE, CONTROLS

D = Decimal
MRN_RE = re.compile(r"^\d{2}FR[A-Z0-9]{14}$")
TOL = D("0.011")


class Report:
    def __init__(self):
        self.problems = []
        self.checked = Counter()

    def fail(self, did, msg):
        self.problems.append(f"{did}: {msg}")

    def ok(self, k, n=1):
        self.checked[k] += n


def _inj(t):
    """(doc, contrôle) des erreurs injectées : valeurs exclues des contrôles arithmétiques."""
    out = defaultdict(set)
    for e in t["injected_errors"]:
        for d in e["documents"]:
            out[d].add(e["control_id"])
    return out


def _d(x):
    return D(str(x)) if x is not None else None


def check_arithmetic(t, rep):
    did = t["dossier_id"]
    inj = _inj(t)
    docs = {d["doc_id"]: d for d in t["documents"]}
    for doc_id, tv in t["truth_values"].items():
        typ = docs[doc_id]["type"]
        ctl = inj.get(doc_id, set())
        if typ == "facture_commerciale":
            s = sum((_d(l["montant_ligne"]) for l in tv["lignes"]), D(0))
            for l in tv["lignes"]:
                calc = _d(l["quantite"]) * _d(l["prix_unitaire"])
                if abs(calc - _d(l["montant_ligne"])) > D("0.51"):
                    rep.fail(did, f"{doc_id} ligne {l['numero_ligne']} qté × prix {calc} != {l['montant_ligne']}")
                rep.ok("fc.ligne")
            st = tv["sous_totaux"]
            tot = s + sum((_d(v) for k, v in st.items() if k != "remise"), D(0)) - _d(st.get("remise", "0"))
            if abs(tot - _d(tv["total_facture"])) > TOL:
                rep.fail(did, f"{doc_id} total {tv['total_facture']} != lignes + pied {tot}")
            rep.ok("fc.total")
        elif typ == "declaration":
            for i, x in enumerate(tv["taxations"]):
                if x["categorie"] == "forfait_petits_envois":
                    if "G1" in ctl:
                        continue
                    calc = _d(x["base_quantite"]) * _d(x["taux"])
                else:
                    if "B1" in ctl:
                        continue
                    if x["base_montant"] is not None:
                        calc = _d(x["base_montant"]) * _d(x["taux"]) / 100
                    else:
                        calc = _d(x["base_quantite"]) * _d(x["taux"])
                m = _d(x["montant"])
                if abs(m - calc) > TOL and m not in (calc.to_integral_value("ROUND_FLOOR"),
                                                     calc.to_integral_value("ROUND_CEILING"),
                                                     calc.quantize(D(1), "ROUND_HALF_UP")):
                    rep.fail(did, f"{doc_id} taxation {i} {x['type_taxe']} base×taux {calc} != {m}")
                rep.ok("dec.base_x_taux")
            if "B3" not in ctl and "F5" not in ctl:
                s = sum((_d(a["montant_facture_article"]) for a in tv["articles"]), D(0))
                if abs(s - _d(tv["montant_total_facture"])) > TOL:
                    rep.fail(did, f"{doc_id} Σ articles {s} != total {tv['montant_total_facture']}")
                rep.ok("dec.somme_articles")
            s = sum((_d(a["masse_brute"]) for a in tv["articles"]), D(0))
            if abs(s - _d(tv["masse_brute_totale"])) > D("0.002"):
                rep.fail(did, f"{doc_id} Σ masses brutes {s} != {tv['masse_brute_totale']}")
            rep.ok("dec.masses")
            if "B4" not in ctl:
                for a in tv["articles"]:
                    if _d(a["masse_nette"]) > _d(a["masse_brute"]):
                        rep.fail(did, f"{doc_id} article {a['numero_article']} nette > brute sans injection B4")
            if "B5" not in ctl:
                s = sum(a["nombre_colis"] for a in tv["articles"])
                if s != tv["nombre_colis_total"]:
                    rep.fail(did, f"{doc_id} Σ colis {s} != {tv['nombre_colis_total']}")
                rep.ok("dec.colis")
            if "B2" not in ctl:
                bytype = defaultdict(D)
                for x in tv["taxations"]:
                    bytype[x["type_taxe"]] += _d(x["montant"])
                for k, v in tv["totaux_par_type"].items():
                    if abs(bytype[k] - _d(v)) > TOL:
                        rep.fail(did, f"{doc_id} total {k} {v} != Σ {bytype[k]}")
                pay = sum((_d(x["montant"]) for x in tv["taxations"] if x["paiement_normalise"] != "autoliquide"), D(0))
                if abs(pay - _d(tv["total_a_payer"])) > TOL:
                    rep.fail(did, f"{doc_id} total à payer {tv['total_a_payer']} != {pay}")
                rep.ok("dec.totaux")
            if not MRN_RE.match(tv["mrn"]):
                rep.fail(did, f"{doc_id} MRN mal formé {tv['mrn']}")
        elif typ in ("facture_transitaire", "avoir"):
            for l in tv["lignes"]:
                if typ == "facture_transitaire":
                    calc = _d(l["quantite"]) * _d(l["prix_unitaire"])
                    if abs(calc - _d(l["montant_ht"])) > TOL:
                        rep.fail(did, f"{doc_id} ligne {l['libelle']} qté × PU {calc} != {l['montant_ht']}")
                calc = _d(l["montant_ht"]) * _d(l["taux_tva"]) / 100
                if abs(calc - _d(l["montant_tva"])) > TOL:
                    rep.fail(did, f"{doc_id} ligne {l['libelle']} TVA {calc} != {l['montant_tva']}")
                rep.ok("ft.ligne")
            ht = sum((_d(l["montant_ht"]) for l in tv["lignes"]), D(0))
            tva = sum((_d(l["montant_tva"]) for l in tv["lignes"]), D(0))
            if typ == "facture_transitaire":
                deb = sum((_d(l["montant_ht"]) for l in tv["lignes"] if l["nature"].startswith("debours")), D(0))
                if abs(deb - _d(tv["total_debours"])) > TOL:
                    rep.fail(did, f"{doc_id} total débours {tv['total_debours']} != {deb}")
                if "D1" not in ctl:
                    if abs(ht - _d(tv["total_ht"])) > TOL or abs(ht + tva - _d(tv["total_ttc"])) > TOL:
                        rep.fail(did, f"{doc_id} totaux HT/TTC incohérents sans injection D1")
                    if abs(_d(tv["total_ttc"]) - _d(tv["acompte"]) - _d(tv["net_a_payer"])) > TOL:
                        rep.fail(did, f"{doc_id} net à payer incohérent")
                rep.ok("ft.totaux")
            elif "E4" not in ctl:
                if abs(ht + tva - _d(tv["total_credite_ttc"])) > TOL:
                    rep.fail(did, f"{doc_id} total avoir incohérent sans injection E4")
                rep.ok("av.totaux")


def check_cross(t, rep):
    """Cohérence entre documents quand aucune erreur ne porte sur la paire."""
    did = t["dossier_id"]
    ctls = {e["control_id"] for e in t["injected_errors"]}
    tv = t["truth_values"]
    docs = {d["doc_id"]: d for d in t["documents"]}
    decls = [k for k, d in docs.items() if d["type"] == "declaration" and not k.endswith("_copie")]
    fts = [k for k, d in docs.items() if d["type"] == "facture_transitaire" and not k.endswith("_copie")]
    # débours refacturés = montants liquidés (hors erreurs C/G4/G5/F et piège d'arrondi)
    if not (ctls & {"C1", "C2", "C3", "C4", "C5", "G4", "G5", "F3", "D8", "P1"}):
        for k in decls:
            d = tv[k]
            liq = sum((_d(x["montant"]) for x in d["taxations"] if x["paiement_normalise"] != "autoliquide"), D(0))
            ref = sum((_d(l["montant_ht"]) for f in fts for l in tv[f]["lignes"]
                       if l["nature"].startswith("debours") and l["mrn"] == d["mrn"]), D(0))
            if ref and abs(ref - liq) > D("0.05"):
                if any(x["mrn"][:15] == d["mrn"][:15] and x is not d for x in (tv[j] for j in decls)):
                    continue  # version rectifiée : seule la dernière est refacturée
                rep.fail(did, f"débours refacturés {ref} != liquidés {liq} pour {d['mrn']} sans injection C")
            rep.ok("cross.debours")
    # montant déclaré = total facture (même devise), hors erreurs de valeur et pièges
    traps = {x["control_id"] for x in t["traps"]}
    if not (ctls & {"A3", "A4", "A5", "A6", "A7", "F5", "P1"}) and "A4" not in {x["control_id"] for x in t["traps"]
                                                                              if x["max_level"] == "a_verifier"}:
        fcs = [k for k, d in docs.items() if d["type"] == "facture_commerciale" and not k.endswith("_copie")]
        if len(decls) == 1 and fcs:
            dd = tv[decls[0]]
            tot = sum((_d(tv[f]["total_facture"]) for f in fcs), D(0))
            cur = tv[fcs[0]]["devise"]
            if dd["devise_facture"] == cur and abs(_d(dd["montant_total_facture"]) - tot) > TOL:
                rep.fail(did, f"montant déclaré {dd['montant_total_facture']} != total facture {tot}")
            rep.ok("cross.valeur")
    _ = traps


def check_identifiers(corpus, rep):
    for p in sorted(glob.glob(os.path.join(corpus, "clients", "*", "profil.json"))):
        prof = json.load(open(p, encoding="utf-8"))
        for e in prof["entites"]:
            s = e["siren"]
            key = (12 + 3 * (int(s) % 97)) % 97
            if not (s.startswith("000") and luhn_ok(s) and e["tva"] == f"FR{key:02d}{s}"
                    and e["eori"] == f"FR{s}00000" and "FICTIF" in e["raison_sociale"]):
                rep.fail(prof["client_id"], f"identifiants fictifs invalides {e}")
            rep.ok("identifiants")
        for tr in prof["transitaires"]:
            s = tr["tva"][4:]
            if not (s.startswith("000") and luhn_ok(s) and "FICTIF" in tr["nom"]):
                rep.fail(prof["client_id"], f"transitaire non fictif {tr}")


def check_marker(corpus, rep, limit=60):
    """Marqueur « DONNÉES FICTIVES » dans le texte des PDF natifs et dans les fichiers texte."""
    import pypdfium2 as pdfium
    n = 0
    for t in _truths(corpus):
        base = os.path.join(corpus, t["split"], t["dossier_id"])
        for d in t["documents"]:
            if n >= limit:
                return
            p = os.path.join(base, d["file"])
            if d["format"] in ("pdf_natif", "factur_x"):
                pdf = pdfium.PdfDocument(p)
                for i in d["pages"]:
                    txt = pdf[i - 1].get_textpage().get_text_range()
                    if "DONNÉES FICTIVES" not in txt:
                        rep.fail(t["dossier_id"], f"marqueur absent {d['file']} p{i}")
                pdf.close()
                n += 1
                rep.ok("marqueur.pdf")
            elif d["format"] in ("ubl", "cii", "xml_declaration", "csv_declaration", "eml"):
                if "DONNÉES FICTIVES".encode() not in open(p, "rb").read():
                    rep.fail(t["dossier_id"], f"marqueur absent {d['file']}")
                rep.ok("marqueur.texte")
            elif d["format"] == "pdf_scan":
                pdf = pdfium.PdfDocument(p)
                for i in d["pages"]:
                    if pdf[i - 1].get_textpage().get_text_range().strip():
                        rep.fail(t["dossier_id"], f"PDF scanné avec couche texte {d['file']} p{i}")
                pdf.close()
                rep.ok("scan.sans_texte")


def _truths(corpus, split=None):
    out = []
    for s in ("dev", "holdout"):
        if split and s != split:
            continue
        for p in sorted(glob.glob(os.path.join(corpus, s, "BX*", "truth.json"))):
            out.append(json.load(open(p, encoding="utf-8")))
    return out


def composition(truths):
    n = len(truths)
    c = {"n": n}
    c["template"] = Counter(t["transitaire_template"] for t in truths)
    c["layout"] = Counter(t["declaration_layout"] for t in truths)
    c["degradation"] = Counter(t["degradation"] for t in truths)
    tags = Counter(tag for t in truths for tag in t["scenario_tags"])
    c["tags"] = tags
    c["sans_erreur"] = sum(1 for t in truths if not t["injected_errors"])
    c["deux_erreurs_plus"] = sum(1 for t in truths if len(t["injected_errors"]) >= 2)
    c["formats"] = Counter(d["format"] for t in truths for d in t["documents"])
    return c


def coverage(entries_by_split):
    table = {}
    for ctl in CONTROLS + ["P1", "P2"]:
        row = {}
        for split, errs in entries_by_split.items():
            es = [e for e in errs if e["control_id"] == ctl]
            row[split] = len(es)
            row[split + "_certain"] = sum(1 for e in es if e["expected_level"] == "ecart_certain")
        table[ctl] = row
    return table


def simulate_holdout(seed, count):
    from .assemble import simulate_dossier
    from .clients import build_registry
    from .plan import build_plan
    plans = build_plan(seed, count)
    reg = build_registry(seed)
    byid = {p["id"]: p for p in plans}
    sims = [simulate_dossier(seed, p, reg, byid) for p in plans if p["split"] == "holdout"]
    return sims


def determinism(seed, count, corpus, ids=("BX0002", "BX0011", "BX0024")):
    res = {}
    hashes = []
    for k in range(2):
        d = tempfile.mkdtemp(prefix=f"det{k}_")
        subprocess.run([sys.executable, "-m", "bench.generator", "--out", d, "--split", "all", "--count", str(count),
                        "--seed", str(seed), "--only", ",".join(ids), "--jobs", "1"], check=True,
                       capture_output=True, cwd=os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
        h = {}
        for p in sorted(glob.glob(os.path.join(d, "*", "BX*", "**", "*"), recursive=True)):
            if os.path.isfile(p):
                h[os.path.relpath(p, d)] = hashlib.sha256(open(p, "rb").read()).hexdigest()
        hashes.append(h)
    res["fichiers"] = len(hashes[0])
    res["identiques_entre_deux_executions"] = hashes[0] == hashes[1]
    same_corpus = None
    if corpus and os.path.isdir(corpus):
        cmp = 0
        diff = 0
        for rel, hv in hashes[0].items():
            p = os.path.join(corpus, rel)
            if os.path.exists(p):
                cmp += 1
                if hashlib.sha256(open(p, "rb").read()).hexdigest() != hv:
                    diff += 1
        same_corpus = (cmp, diff)
    res["comparaison_corpus (comparés, différents)"] = same_corpus
    return res


def fmt_table(table, splits):
    head = "| Contrôle | " + " | ".join(f"{s} (dont certain)" for s in splits) + " | total |"
    sep = "|---" * (len(splits) + 2) + "|"
    lines = [head, sep]
    for ctl, row in table.items():
        tot = sum(row[s] for s in splits)
        flag = ""
        if ctl not in ("P1", "P2"):
            if tot < 6 or row.get("holdout", 99) < 2:
                flag = " ⚠"
            if ctl in CERTAIN_ELIGIBLE and sum(row[s + "_certain"] for s in splits) < 3:
                flag += " ⚠certain<3"
        lines.append(f"| {ctl} | " + " | ".join(f"{row[s]} ({row[s + '_certain']})" for s in splits)
                     + f" | {tot}{flag} |")
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", default="bench/corpus")
    ap.add_argument("--seed", type=int, default=20261002)
    ap.add_argument("--count", type=int, default=250)
    ap.add_argument("--determinism", action="store_true")
    ap.add_argument("--json", default="")
    args = ap.parse_args(argv)
    rep = Report()
    truths = _truths(args.corpus)
    for t in truths:
        check_arithmetic(t, rep)
        check_cross(t, rep)
    check_identifiers(args.corpus, rep)
    check_marker(args.corpus, rep)
    entries = {"dev": [e for t in truths if t["split"] == "dev" for e in t["injected_errors"]]}
    holdout_files = [t for t in truths if t["split"] == "holdout"]
    if holdout_files:
        entries["holdout"] = [e for t in holdout_files for e in t["injected_errors"]]
        sims = None
    else:
        sims = simulate_holdout(args.seed, args.count)
        entries["holdout"] = [e for s in sims for e in s["injected_errors"]]
    table = coverage(entries)
    comp = composition(truths)
    print("== Auto-contrôles ==")
    print("vérifications :", dict(rep.checked))
    print("problèmes :", len(rep.problems))
    for p in rep.problems[:40]:
        print("  -", p)
    print("\n== Composition (fichiers écrits) ==")
    n = comp["n"]
    print(f"dossiers : {n} ; sans erreur : {comp['sans_erreur']} ({100 * comp['sans_erreur'] / max(1, n):.0f} %) ; "
          f"2 erreurs ou plus : {comp['deux_erreurs_plus']} ({100 * comp['deux_erreurs_plus'] / max(1, n):.0f} %)")
    for k in ("template", "layout", "degradation"):
        print(f"{k} :", dict(sorted(comp[k].items(), key=lambda kv: str(kv[0]))))
    print("scénarios :", {k: f"{v} ({100 * v / max(1, n):.0f} %)" for k, v in sorted(comp["tags"].items())})
    print("formats de documents :", dict(sorted(comp["formats"].items())))
    if sims is not None:
        sn = len(sims)
        print(f"\n== Holdout planifié (simulation, aucun fichier écrit) : {sn} dossiers ; sans erreur "
              f"{sum(1 for s in sims if not s['injected_errors'])} ; 2+ erreurs "
              f"{sum(1 for s in sims if len(s['injected_errors']) >= 2)}")
        print("gabarits :", dict(sorted(Counter(s["template"] for s in sims).items())),
              "mises en page :", dict(sorted(Counter(s["layout"] for s in sims).items())))
        w = [w for s in sims for w in s["warnings"]]
        if w:
            print("avertissements de simulation :", w[:5])
    print("\n== Couverture par contrôle (erreurs injectées, dont attendues ecart_certain) ==")
    print(fmt_table(table, list(entries)))
    traps = Counter((x["control_id"], x["max_level"]) for t in truths for x in t["traps"])
    print("\n== Pièges (fichiers écrits) ==")
    print(dict(sorted((f"{a}:{b}", v) for (a, b), v in traps.items())))
    if args.determinism:
        print("\n== Déterminisme ==")
        print(determinism(args.seed, args.count, args.corpus))
    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump({"coverage": table, "problems": rep.problems}, fh, ensure_ascii=False, indent=1,
                      sort_keys=True)
    return 1 if rep.problems else 0


if __name__ == "__main__":
    sys.exit(main())
