"""Assemblage d'un dossier : répartition des documents en fichiers, rendu, dégradation, truth.json."""

from __future__ import annotations

import os
import re

from . import GENERATOR_VERSION
from .build import build_core
from .common import dumps, rng_for, sha256_bytes, sub_seed
from .degrade import degrade_pdf
from .pdfkit import Pen
from .render_ci import render_ci
from .render_decl import render_declaration
from .render_ft import render_avoir, render_ft
from .render_misc import render_awb, render_cg, render_cover_letter, render_nx, render_packing
from .model import SupportDoc
from .structured import (check_cii, cii_commercial, cii_forwarder, eml_message, facturx_embed, ubl_commercial,
                         x1_declaration, x2_declaration, xlsx_commercial)
from .truth import (compute_consequences, compute_links, compute_traps, finalize_errors, totals_and_outcome, tv_av,
                    tv_ci, tv_decl, tv_ft, tv_support)

STRUCTURED_FORMATS = {"factur_x", "ubl", "cii", "xml_declaration", "csv_declaration", "xlsx"}


def _safe(s):
    return re.sub(r"[^A-Za-z0-9._-]+", "-", s).strip("-")


class FileSpec:
    def __init__(self, path, kind, parts, degrade=None, title=""):
        self.path = path
        self.kind = kind  # pdf | facturx | xml | csv | xlsx | eml
        self.parts = parts  # [(kind, obj)]
        self.degrade = degrade
        self.title = title
        self.data = None
        self.pages = 1
        self.doc_pages = {}


def plan_files(dm):
    p = dm.plan
    r = rng_for(dm.seed, "files", p["id"])
    tpl = p["template"]
    deg = p["degradation"]
    absent = dm.absent
    files = []
    used = set()

    def path(name):
        base = name
        k = 1
        while name in used:
            k += 1
            stem, ext = os.path.splitext(base)
            name = f"{stem}_{k}{ext}"
        used.add(name)
        return name

    def pdf_deg(kind):
        if deg == "d0":
            return None
        if kind in ("ft", "av") and r.random() < 0.5:
            return None
        return deg

    if tpl == "T6":
        sup_cover = SupportDoc(f"sup{len(dm.supports) + 1}", "lettre_accompagnement", "fr",
                               {"ft_numero": dm.fts[0].numero, "date": dm.fts[0].date})
        dm.supports.append(sup_cover)
        sup_cg = SupportDoc(f"sup{len(dm.supports) + 1}", "conditions_generales", "fr", {})
        dm.supports.append(sup_cg)

    ci_parts = [("ci", ci) for ci in dm.cis if ci.doc_id not in absent]
    dec_pdf = [d for d in dm.decls if d.doc_id not in absent and d.layout in ("L1", "L2", "L3", "L4")]
    dec_struct = [d for d in dm.decls if d.doc_id not in absent and d.layout in ("X1", "X2")]
    awbs = [s for s in dm.supports if s.sous_type == "titre_transport"]
    packs = [s for s in dm.supports if s.sous_type == "liste_colisage"]
    emls = [s for s in dm.supports if s.sous_type == "courriel"]
    taken = set()

    # T6 : lettre + facture + copie de déclaration + CG dans un même PDF
    if tpl == "T6":
        cover = next(s for s in dm.supports if s.sous_type == "lettre_accompagnement")
        cg = next(s for s in dm.supports if s.sous_type == "conditions_generales")
        parts = [("cover", cover), ("ft", dm.fts[0])] + [("decl", d) for d in dec_pdf] + [("cg", cg)]
        for d in dec_pdf:
            taken.add(d.doc_id)
        taken.add(dm.fts[0].doc_id)
        files.append(FileSpec(path(f"{_safe(dm.fts[0].numero)}_envoi_complet.pdf"), "pdf", parts, pdf_deg("ft")))
        for ft in dm.fts[1:]:
            pass

    # PDF fusionné « envoi » : factures + colisage + LTA (+ déclaration parfois)
    if p["merged"] and tpl != "T6":
        parts = [x for x in ci_parts if x[1].fmt == "pdf"] + [("sup", s) for s in packs] + [("sup", s) for s in awbs]
        if dec_pdf and (r.random() < 0.4 or len(parts) < 2):
            parts += [("decl", d) for d in dec_pdf]
        if len(parts) < 2 and dec_pdf:
            parts += [("decl", d) for d in dec_pdf if ("decl", d) not in parts]
        if len(parts) >= 2:
            for k, o in parts:
                taken.add(o.doc_id)
            name = r.choice(["envoi_complet.pdf", "documents_expedition.pdf", "dossier_import.pdf",
                             f"scan_{r.randint(1000, 9999)}.pdf"])
            files.append(FileSpec(path(name), "pdf", parts, deg if deg != "d0" else None))
            dm.tags.append("pdf_fusionne")
    # factures commerciales
    for k, ci in [x for x in ci_parts if x[1].doc_id not in taken]:
        nm = _safe(ci.numero)
        if ci.fmt == "ubl":
            files.append(FileSpec(path(f"{nm}_ubl.xml"), "xml", [("ci_ubl", ci)]))
        elif ci.fmt == "cii":
            files.append(FileSpec(path(f"{nm}_cii.xml"), "xml", [("ci_cii", ci)]))
        elif ci.fmt == "xlsx":
            files.append(FileSpec(path(f"{nm}.xlsx"), "xlsx", [("ci_xlsx", ci)]))
        else:
            name = r.choice([f"{nm}.pdf", f"facture_fournisseur_{nm}.pdf", f"INVOICE_{nm}.pdf"])
            files.append(FileSpec(path(name), "pdf", [("ci", ci)], pdf_deg("ci")))
    # déclarations
    for d in dec_pdf:
        if d.doc_id in taken:
            continue
        prefix = {"L1": "DAU", "L2": "preuve_dedouanement", "L3": "DAU", "L4": "H7"}[d.layout]
        files.append(FileSpec(path(f"{prefix}_{d.mrn}.pdf"), "pdf", [("decl", d)], pdf_deg("decl")))
    for d in dec_struct:
        if d.layout == "X1":
            files.append(FileSpec(path(f"export_declaration_{d.mrn}.xml"), "xml", [("decl_x1", d)]))
        else:
            files.append(FileSpec(path(f"export_declaration_{d.mrn}.csv"), "csv", [("decl_x2", d)]))
    # factures transitaire
    fts = [ft for ft in dm.fts if ft.doc_id not in taken]
    if tpl == "T5" and p["merged"] and len([f for f in fts if f.kind in ("debours", "prestations")]) == 2:
        pair = [f for f in fts if f.kind in ("debours", "prestations")]
        files.append(FileSpec(path("factures_transitaire.pdf"), "pdf", [("ft", f) for f in pair], pdf_deg("ft")))
        fts = [f for f in fts if f not in pair]
        dm.tags.append("pdf_fusionne")
    for ft in fts:
        if ft.template == "T7":
            files.append(FileSpec(path(f"{_safe(ft.numero)}_facturx.pdf"), "facturx", [("ft", ft)]))
        else:
            files.append(FileSpec(path(f"{_safe(ft.numero)}.pdf"), "pdf", [("ft", ft)], pdf_deg("ft")))
    for av in dm.avoirs:
        if av.template == "T7":
            files.append(FileSpec(path(f"avoir_{_safe(av.numero)}_facturx.pdf"), "facturx", [("av", av)]))
        else:
            files.append(FileSpec(path(f"avoir_{_safe(av.numero)}.pdf"), "pdf", [("av", av)], pdf_deg("av")))
    for s in awbs + packs:
        if s.doc_id in taken:
            continue
        nm = (f"LTA_{_safe(s.data['ref'])}.pdf" if s.data.get("kind") == "awb" else
              f"BL_{_safe(s.data['ref'])}.pdf") if s.sous_type == "titre_transport" else "packing_list.pdf"
        files.append(FileSpec(path(nm), "pdf", [("sup", s)], pdf_deg("sup")))
    for s in emls:
        files.append(FileSpec(path("courriel_fournisseur.eml"), "eml", [("eml", s)]))
    for s in dm.nx:
        files.append(FileSpec(path(r.choice(["invoice_preliminary.pdf", "facture_fournisseur_scan.pdf",
                                             "INVOICE.pdf"])), "pdf", [("nx", s)], pdf_deg("nx")))
    for f in files:
        if len(f.parts) >= 2 and "pdf_fusionne" not in dm.tags:
            dm.tags.append("pdf_fusionne")
    return files


RENDER = {"ci": render_ci, "decl": render_declaration, "ft": render_ft, "av": render_avoir, "nx": render_nx,
          "cover": render_cover_letter, "cg": render_cg}


def render_file(dm, f: FileSpec):
    did = dm.plan["id"]
    if f.kind in ("pdf", "facturx"):
        pen = Pen(title=f.path.rsplit("/", 1)[-1].rsplit(".", 1)[0], author="Générateur de corpus (FICTIF)")
        for i, (k, o) in enumerate(f.parts):
            if i > 0:
                pen.new_page()
            start = pen.page
            variant = sub_seed(did, o.doc_id) % 97
            if k == "sup":
                (render_awb if o.sous_type == "titre_transport" else render_packing)(pen, o, dm, variant)
            elif k == "ci":
                render_ci(pen, o, dm, sub_seed(did, o.doc_id, o.seller_key) % 30)
            else:
                RENDER[k](pen, o, dm, variant)
            f.doc_pages[o.doc_id] = list(range(start, pen.page + 1))
        data = pen.finish()
        f.pages = pen.page
        if f.kind == "facturx":
            o = f.parts[0][1]
            if f.parts[0][0] == "ft":
                xml = cii_forwarder(o, "380", notes=[f"Dossier {o.dossier_ref}"] if o.dossier_ref else ())
            else:
                xml = cii_forwarder(_AvoirAdapter(o), "381", origin_ref=(o.refs_origin[0] if o.refs_origin else None),
                                    notes=[f"Motif : {o.motif}"])
            data = facturx_embed(data, xml, f.title or o.numero)
        elif f.degrade:
            data = degrade_pdf(data, f.degrade, sub_seed(dm.seed, did, f.path) % (2 ** 32))
        f.data = data
        return
    k, o = f.parts[0]
    f.doc_pages[o.doc_id] = [1]
    if k == "ci_ubl":
        f.data = ubl_commercial(o)
    elif k == "ci_cii":
        f.data = cii_commercial(o)
        check_cii(f.data, "extended")
    elif k == "ci_xlsx":
        f.data = xlsx_commercial(o)
        f.doc_pages[o.doc_id] = [1]
    elif k == "decl_x1":
        f.data = x1_declaration(o)
    elif k == "decl_x2":
        f.data = x2_declaration(o)
    elif k == "eml":
        f.data = eml_message(o, did, dm.cis[0] if dm.cis else None)
    f.pages = 2 if k == "ci_xlsx" else 1


class _AvoirAdapter:
    """Présente un avoir avec l'interface attendue par cii_forwarder."""

    def __init__(self, av):
        self.numero = av.numero
        self.date = av.date
        self.emetteur = av.emetteur
        self.client = av.client
        self.lines = av.lines
        self.refs_mrn = av.refs_mrn
        self.refs_transport = av.refs_transport
        self.total_ht = av.total_ht
        self.total_tva = av.total_tva
        self.total_ttc = av.printed("total_ttc")
        self.net_a_payer = self.total_ttc
        self.acompte = 0
        self.due_date = None


FORMAT_OF = {"pdf": "pdf_natif", "facturx": "factur_x", "xlsx": "xlsx", "eml": "eml"}


def _doc_entry(dm, o, kind, f):
    p = dm.plan
    fmt = FORMAT_OF.get(f.kind)
    if f.kind == "pdf" and f.degrade:
        fmt = "pdf_scan"
    if f.kind == "xml":
        fmt = {"ci_ubl": "ubl", "ci_cii": "cii", "decl_x1": "xml_declaration"}[kind]
    if f.kind == "csv":
        fmt = "csv_declaration"
    deg = f.degrade if (f.kind == "pdf" and f.degrade) else "d0"
    if kind.startswith("ci"):
        t, st, lang, tpl = "facture_commerciale", o.sous_type, o.language, None
    elif kind.startswith("decl"):
        t, st, lang, tpl = "declaration", o.sous_type, "fr", None
    elif kind == "ft":
        t, st, lang, tpl = "facture_transitaire", None, dm.fw.lang, o.template
    elif kind == "av":
        t, st, lang, tpl = "avoir", None, dm.fw.lang, o.template
    elif kind == "nx":
        t, st, lang, tpl = "document_non_exploitable", o.sous_type, o.language, None
    else:
        t, st, lang, tpl = "document_support", o.sous_type, o.language if o.language in ("fr", "en", "es") else "fr", None
    if lang not in ("fr", "en", "es", "fr_en"):
        lang = "en"
    return {"doc_id": o.doc_id, "type": t, "sous_type": st, "format": fmt, "degradation": deg, "file": "docs/" + f.path,
            "pages": f.doc_pages[o.doc_id], "transitaire_template": tpl, "language": lang}


def _truth_values(o, kind):
    if kind.startswith("ci"):
        return tv_ci(o)
    if kind.startswith("decl"):
        return tv_decl(o)
    if kind == "ft":
        return tv_ft(o)
    if kind == "av":
        return tv_av(o)
    if kind in ("sup", "nx", "eml", "cover", "cg"):
        return tv_support(o)
    return {}


def _dup_target(dm, files):
    prefs = ["ft1", "fc1", "sup1", "sup2"]
    for pid in prefs:
        for f in files:
            if len(f.parts) == 1 and f.parts[0][1].doc_id == pid:
                return f
    for f in files:
        if len(f.parts) == 1 and f.kind in ("pdf", "facturx", "xml"):
            return f
    return None


def generate_dossier(seed, plan, reg, plans_by_id, out_root):
    dm = build_core(seed, plan, reg, plans_by_id)
    compute_consequences(dm)
    compute_traps(dm)
    files = plan_files(dm)
    for f in files:
        render_file(dm, f)
    # doublons (F1, E3) : copie octet pour octet dans docs/courriel/
    dup_files = []
    if getattr(dm, "f1_requested", False):
        tgt = _dup_target(dm, files)
        if tgt is not None:
            k, o = tgt.parts[0]
            nf = FileSpec("courriel/" + tgt.path.split("/")[-1], tgt.kind, tgt.parts, tgt.degrade)
            nf.data, nf.pages = tgt.data, tgt.pages
            nf.doc_pages = {o.doc_id + "_copie": tgt.doc_pages[o.doc_id], o.doc_id: tgt.doc_pages[o.doc_id]}
            nf.dup_of = (o.doc_id, o.doc_id + "_copie", k)
            dup_files.append(nf)
            dm.add_error("F1", "fichier_double", [o.doc_id, o.doc_id + "_copie"], eligible=False,
                         description=f"Le fichier {tgt.path} est présent deux fois dans le dossier.", key="F1")
        else:
            dm.warnings.append("F1 sans cible")
    for orig, dup in dm.duplicates:
        tgt = next(f for f in files if any(o.doc_id == orig for _, o in f.parts))
        nf = FileSpec("courriel/" + tgt.path.split("/")[-1], tgt.kind, tgt.parts, tgt.degrade)
        nf.data, nf.pages = tgt.data, tgt.pages
        nf.doc_pages = {dup: tgt.doc_pages[orig], orig: tgt.doc_pages[orig]}
        nf.dup_of = (orig, dup, tgt.parts[0][0])
        dup_files.append(nf)
    all_files = files + dup_files

    # documents, valeurs vraies
    documents = []
    truth_values = {}
    doc_meta = {}
    for f in all_files:
        if getattr(f, "dup_of", None):
            orig, dup, kind = f.dup_of
            o = next(o for _, o in f.parts if o.doc_id == orig)
            ent = _doc_entry(dm, o, kind, f)
            ent["doc_id"] = dup
            ent["pages"] = f.doc_pages[dup]
            documents.append(ent)
            truth_values[dup] = _truth_values(o, kind)
            doc_meta[dup] = {"degradation": ent["degradation"], "structured": ent["format"] in STRUCTURED_FORMATS}
            continue
        for kind, o in f.parts:
            ent = _doc_entry(dm, o, kind, f)
            documents.append(ent)
            truth_values[o.doc_id] = _truth_values(o, kind)
            doc_meta[o.doc_id] = {"degradation": ent["degradation"], "structured": ent["format"] in STRUCTURED_FORMATS}
    present = set(doc_meta)
    entries = finalize_errors(dm, doc_meta)
    expected_totals, outcome = totals_and_outcome(entries)
    links = compute_links(dm, present)
    did = plan["id"]
    traps = []
    for i, t in enumerate(dm.traps, 1):
        docs = [x for x in t["documents"] if x in present]
        if not docs:
            continue
        traps.append({"trap_id": f"{did}-T{i}", "control_id": t["control"], "max_level": t["max_level"],
                      "documents": docs, "description": t["description"]})
    tags = _scenario_tags(dm, all_files)
    split = plan["split"]
    base = os.path.join(out_root, split, did)
    file_entries = []
    for f in all_files:
        full = os.path.join(base, "docs", f.path)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "wb") as fh:
            fh.write(f.data)
        file_entries.append({"path": "docs/" + f.path, "sha256": sha256_bytes(f.data), "pages": f.pages})
    file_entries.sort(key=lambda x: x["path"])
    documents.sort(key=lambda x: (x["file"], x["pages"][0], x["doc_id"]))
    truth = {
        "schema": "controldone.bench.truth/1.0.0",
        "dossier_id": did,
        "split": split,
        "client_id": plan["client"],
        "generator_version": GENERATOR_VERSION,
        "seed": sub_seed(seed, did) % (2 ** 53),
        "transitaire_template": plan["template"] if dm.fts else None,
        "declaration_layout": plan["layout"],
        "degradation": plan["degradation"],
        "scenario_tags": tags,
        "files": file_entries,
        "documents": documents,
        "truth_values": truth_values,
        "expected_links": links,
        "injected_errors": [e for e, _ in entries],
        "traps": traps,
        "expected_outcome": outcome,
        "expected_totals": expected_totals,
    }
    data = dumps(truth).encode("utf-8")
    with open(os.path.join(base, "truth.json"), "wb") as fh:
        fh.write(data)
    return truth, sha256_bytes(data), dm.warnings


def _scenario_tags(dm, files):
    p = dm.plan
    tags = set(dm.tags)
    if any(len(f.parts) >= 2 for f in files):
        tags.add("pdf_fusionne")
    else:
        tags.discard("pdf_fusionne")
    if len(dm.final_decls) > 1:
        tags.add("multi_declarations")
    if p["n_ci"] > 1:
        tags.add("plusieurs_factures_une_declaration")
    if p["split_invoice"]:
        tags.add("facture_sur_plusieurs_declarations")
    if any(len(set(ft.refs_mrn) & {d.mrn for d in dm.final_decls}) > 1 for ft in dm.fts):
        tags.add("facture_transitaire_multi_mrn")
    if any(d.autoliq for d in dm.final_decls):
        tags.add("autoliquidation")
    if any(ci.currency != "EUR" for ci in dm.cis):
        tags.add("devise_etrangere")
    if any(ci.currency in ("JPY", "KRW") for ci in dm.cis):
        tags.add("devise_sans_decimales")
    if dm.avoirs:
        tags.add("avoirs")
    if p["layout"] == "L4":
        tags.add("petits_envois")
    if p["template"] == "T7" or any(f.kind == "xml" and f.parts[0][0] in ("ci_ubl", "ci_cii") for f in files):
        tags.add("facture_electronique")
    if any(f.kind == "xlsx" for f in files):
        tags.add("tableur")
    if any(ci.sous_type == "pro_forma" for ci in dm.cis):
        tags.add("pro_forma")
    if p.get("fpair"):
        tags.add("paire_inter_dossiers")
    if dm.absent:
        tags.add("document_manquant")
    if dm.nx:
        tags.add("document_non_exploitable")
    if any(getattr(f, "dup_of", None) for f in files):
        tags.add("fichier_double")
    return sorted(tags)


def simulate_dossier(seed, plan, reg, plans_by_id):
    """Calcule les erreurs attendues (niveaux, montants) SANS rendre ni écrire de fichier.

    Sert aux statistiques de couverture du split holdout avant sa génération effective."""
    dm = build_core(seed, plan, reg, plans_by_id)
    compute_consequences(dm)
    compute_traps(dm)
    files = plan_files(dm)
    doc_meta = {}
    for f in files:
        for kind, o in f.parts:
            fmt = FORMAT_OF.get(f.kind)
            if f.kind == "pdf" and f.degrade:
                fmt = "pdf_scan"
            if f.kind == "xml":
                fmt = {"ci_ubl": "ubl", "ci_cii": "cii", "decl_x1": "xml_declaration"}[kind]
            if f.kind == "csv":
                fmt = "csv_declaration"
            doc_meta[o.doc_id] = {"degradation": f.degrade if (f.kind == "pdf" and f.degrade) else "d0",
                                  "structured": fmt in STRUCTURED_FORMATS}
    if getattr(dm, "f1_requested", False):
        for f in files:
            f.doc_pages = {o.doc_id: [1] for _, o in f.parts}
        tgt = _dup_target(dm, files)
        if tgt is not None:
            o = tgt.parts[0][1]
            doc_meta[o.doc_id + "_copie"] = dict(doc_meta[o.doc_id])
            dm.add_error("F1", "fichier_double", [o.doc_id, o.doc_id + "_copie"], eligible=False,
                         description="simulation", key="F1")
    for orig, dup in dm.duplicates:
        doc_meta[dup] = dict(doc_meta.get(orig, {"degradation": "d0", "structured": False}))
    entries = finalize_errors(dm, doc_meta)
    totals, outcome = totals_and_outcome(entries)
    return {"dossier_id": plan["id"], "split": plan["split"], "injected_errors": [e for e, _ in entries],
            "traps": [{"control_id": t["control"], "max_level": t["max_level"], "description": t["description"]}
                      for t in dm.traps],
            "expected_outcome": outcome, "expected_totals": totals, "warnings": dm.warnings,
            "template": plan["template"], "layout": plan["layout"], "degradation": plan["degradation"],
            "tags": sorted(set(dm.tags))}
