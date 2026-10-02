"""Rendu lisible en français de ``metrics.json`` (``metrics.md``)."""

from __future__ import annotations

from typing import Any


def _pct(x: float | None) -> str:
    return "—" if x is None else f"{x * 100:.1f} %".replace(".", ",")


def _v(x: Any) -> str:
    return "—" if x is None else str(x).replace(".", ",")


def rendre_markdown(m: dict[str, Any]) -> str:
    g = m["global"]
    gate = m["gate"]
    lignes: list[str] = []
    a = lignes.append
    a(f"# Banc ControlDOne — exécution `{m['run_id']}` (split `{m['split']}`)")
    a("")
    a(f"**Seuil bloquant (§19.7) : {'PASSE' if gate['passe'] else 'ÉCHOUE'}**")
    a("")
    for motif in gate["motifs"]:
        a(f"- {motif}")
    if gate["motifs"]:
        a("")
    a("## Synthèse globale")
    a("")
    a("| Indicateur | Valeur |")
    a("|---|---|")
    rows = [
        ("Dossiers évalués", g["n_dossiers"]),
        ("Erreurs injectées (dont attendues certain)",
         f"{g['n_erreurs']} ({g['n_erreurs_certain']})"),
        ("Constats produits (certain / à vérifier)",
         f"{g['n_constats']} ({g['n_constats_certain']} / {g['n_constats_a_verifier']})"),
        ("VP certain / FP certain", f"{g['vp_certain']} / {g['fp_certain']}"),
        ("  dont FP non apparié / montant incorrect / piège",
         f"{g['fp_certain_non_apparie']} / {g['fp_certain_montant']} / {g['fp_certain_piege']}"),
        ("Précision certain", _pct(g["precision_certain"])),
        ("Borne basse de Wilson 95 %", _pct(g["precision_certain_wilson_bas"])),
        ("Rappel", _pct(g["rappel"])),
        ("Rappel certain", _pct(g["rappel_certain"])),
        ("Précision de détection", _pct(g["precision_detection"])),
        ("Exactitude des montants", _pct(g["exactitude_montant"])),
        ("Surclassements (taux)", f"{g['surclassement']} ({_pct(g['taux_surclassement'])})"),
        ("Sous-classements (taux)",
         f"{g['sous_classement']} ({_pct(g['taux_sous_classement'])})"),
        ("FN (erreurs manquées)", g["fn"]),
        ("FP à vérifier (bruit) / par dossier",
         f"{g['fp_a_verifier']} / {_v(g['bruit_a_verifier_par_dossier'])}"),
        ("Violations de pièges", g["violations_pieges"]),
        ("Constats neutres (miroir, doublon de composantes, piège toléré)", g["neutres"]),
    ]
    for k, v in rows:
        a(f"| {k} | {v} |")
    a("")
    d = m["dossiers"]
    if d["findings_absents"] or d["findings_illisibles"]:
        a("## Sorties manquantes")
        a("")
        if d["findings_absents"]:
            a(f"- `findings.json` absent (erreurs comptées FN) : {', '.join(d['findings_absents'])}")
        if d["findings_illisibles"]:
            a(f"- `findings.json` illisible (erreurs comptées FN) : "
              f"{', '.join(d['findings_illisibles'])}")
        a("")
    a("## Par contrôle")
    a("")
    a("Erreurs, VP certain, FN, rappel et exactitude des montants : sur le contrôle **principal** "
      "de l'erreur. Constats produits, FP et précision « constats » : sur le contrôle du constat.")
    a("")
    a("| Contrôle | Erreurs | dont certain | Constats certain produits | VP certain | FP certain "
      "| FN | Précision certain | Précision (constats) | Rappel | Exactitude montant |")
    a("|---|---|---|---|---|---|---|---|---|---|---|")
    for ctrl, c in m["par_controle"].items():
        a(f"| {ctrl} | {c['n_erreurs']} | {c['n_erreurs_certain']} | {c['n_constats_certain']} "
          f"| {c['vp_certain']} | {c['fp_certain']} | {c['fn']} | {_pct(c['precision_certain'])} "
          f"| {_pct(c['precision_certain_constats'])} | {_pct(c['rappel'])} "
          f"| {_pct(c['exactitude_montant'])} |")
    a("")
    ex = m["extraction_par_champ"]
    a("## Exactitude d'extraction par champ obligatoire")
    a("")
    if ex["n_dossiers_evalues"] == 0:
        a("Aucun `findings.json` ne contient `valeurs` : non mesurée.")
    else:
        a(f"{ex['n_dossiers_evalues']} dossier(s) ; global : {_pct(ex['global']['exactitude'])} "
          f"({ex['global']['corrects']}/{ex['global']['n']}).")
        a("")
        a("| Champ | n | Corrects | Exactitude |")
        a("|---|---|---|---|")
        for k, v in ex["champs"].items():
            a(f"| `{k}` | {v['n']} | {v['corrects']} | {_pct(v['exactitude'])} |")
    a("")
    r = m["regroupement"]
    a("## Regroupement (liens attendus)")
    a("")
    a(f"VP {r['vp']}, FP {r['fp']}, FN {r['fn']} — précision {_pct(r['precision'])}, "
      f"rappel {_pct(r['rappel'])}, F1 {_pct(r['f1'])} (modes : {r['modes']}).")
    a("")
    a("## Coût IA et durée par dossier")
    a("")
    c, du = m["cout"], m["duree"]
    a("| | n | Moyenne | Médiane | p95 | Maximum |")
    a("|---|---|---|---|---|---|")
    a(f"| Coût IA (EUR) | {c['n']} | {_v(c['moyenne_eur'])} | {_v(c['mediane_eur'])} "
      f"| {_v(c['p95_eur'])} | {_v(c['max_eur'])} |")
    a(f"| Durée (s) | {du['n']} | {_v(du['moyenne_s'])} | {_v(du['mediane_s'])} "
      f"| {_v(du['p95_s'])} | {_v(du['max_s'])} |")
    a("")
    if m["alertes"]:
        a("## Alertes (non bloquantes)")
        a("")
        for x in m["alertes"]:
            a(f"- {x}")
        a("")
    a(f"_Formulations interdites : source `{m['garde_fous']['source_formulations']}`._")
    a("")
    return "\n".join(lignes)
