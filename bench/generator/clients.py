"""Clients, entités, transitaires et grilles tarifaires fictifs (SPEC §6.2, §19.2)."""

from __future__ import annotations

from dataclasses import dataclass, field

from .common import D, make_siren, rng_for, vat_fr, eori_fr
from .model import FT_LABELS
from .refdata import CLIENTS, FORWARDERS, THIRD_PARTY


@dataclass
class Entity:
    name: str
    aliases: list
    addr: tuple
    siren: str
    vat: str
    eori: str
    client_id: str | None


@dataclass
class Forwarder:
    tid: str
    template: str
    name: str
    city: str
    prefix: str
    lang: str
    siren: str
    vat: str
    addr: tuple


@dataclass
class Registry:
    clients: dict = field(default_factory=dict)      # client_id -> {"entities": [...], "templates": [...]}
    forwarders: dict = field(default_factory=dict)   # tid -> Forwarder
    by_template: dict = field(default_factory=dict)  # template -> Forwarder
    grids: dict = field(default_factory=dict)        # (client_id, tid) -> grid dict
    third_party: Entity | None = None


_SYNONYMS = {
    "DEDOUANEMENT": ["Dédouanement import", "Customs clearance fee", "Honoraires de dédouanement"],
    "LIGNE_SUP": ["Ligne supplémentaire", "Article supplémentaire", "Additional item"],
    "AVANCE_FONDS": ["Avance de fonds", "Commission sur débours"],
    "MAGASINAGE": ["Frais de stockage"],
    "TRANSPORT": ["Transport", "Acheminement final"],
    "MANUTENTION": ["Frais de manutention"],
    "SURCHARGE_CARBURANT": [],
    "SURCHARGE_SURETE": [],
    "OUVERTURE_DOSSIER": [],
}


def _labels(code: str) -> list:
    out = []
    for v in FT_LABELS[code].values():
        if v not in out:
            out.append(v)
    return out + _SYNONYMS.get(code, [])


LABELS = {
    "frais_dedouanement": _labels("DEDOUANEMENT"),
    "frais_ligne_supplementaire": _labels("LIGNE_SUP"),
    "frais_avance_fonds": _labels("AVANCE_FONDS"),
    "magasinage": _labels("MAGASINAGE"),
    "transport": _labels("TRANSPORT"),
    "manutention": _labels("MANUTENTION"),
    "surcharge_carburant": _labels("SURCHARGE_CARBURANT"),
    "surcharge_surete": _labels("SURCHARGE_SURETE"),
    "ouverture_dossier": _labels("OUVERTURE_DOSSIER"),
}


def build_registry(seed: int) -> Registry:
    reg = Registry()
    r = rng_for(seed, "registry")
    used_sirens = set()

    def new_siren():
        while True:
            s = make_siren(r)
            if s not in used_sirens:
                used_sirens.add(s)
                return s

    for (tid, tpl, name, city, prefix, lang) in FORWARDERS:
        s = new_siren()
        num = r.randint(1, 98)
        fw = Forwarder(tid, tpl, name, city, prefix, lang, s, vat_fr(s),
                       (f"{num} avenue du Fret Imaginaire", f"{r.randint(10, 95)}999 {city}"))
        reg.forwarders[tid] = fw
        reg.by_template[tpl] = fw

    for c in CLIENTS:
        ents = []
        for (name, aliases, addr) in c["entites"]:
            s = new_siren()
            ents.append(Entity(name, list(aliases), addr, s, vat_fr(s), eori_fr(s), c["client_id"]))
        reg.clients[c["client_id"]] = {"entities": ents, "templates": list(c["templates"]),
                                       "groupe": c["groupe"]}

    s = new_siren()
    reg.third_party = Entity(THIRD_PARTY[0], [], THIRD_PARTY[1], s, vat_fr(s), eori_fr(s), None)

    for cid, c in sorted(reg.clients.items()):
        for tpl in c["templates"]:
            fw = reg.by_template[tpl]
            reg.grids[(cid, fw.tid)] = _make_grid(seed, cid, fw)
    return reg


def _poste(code, nature, mode, libelles, prix=None, unite_base=None, pourcentage=None, base_pourcentage=None,
           minimum=None, maximum=None, franchise_jours=None, inclus=None):
    return {
        "code_poste": code, "nature": nature, "libelles_reconnus": libelles, "mode": mode,
        "prix": None if prix is None else str(prix), "unite_base": unite_base,
        "pourcentage": None if pourcentage is None else str(pourcentage),
        "base_pourcentage": base_pourcentage,
        "minimum": None if minimum is None else str(minimum),
        "maximum": None if maximum is None else str(maximum),
        "franchise_jours": franchise_jours, "inclus": inclus, "devise": "EUR",
    }


def _make_grid(seed: int, cid: str, fw: Forwarder) -> dict:
    r = rng_for(seed, "grid", cid, fw.tid)
    dedouan = D(r.choice(["55.00", "62.50", "65.00", "69.00", "72.00", "79.00", "85.00"]))
    ligne = D(r.choice(["6.00", "7.50", "8.00", "9.50", "10.00"]))
    inclus = r.choice([2, 3, 3, 5])
    faf_pct = D(r.choice(["2.0", "2.5", "2.5", "3.0"]))
    faf_base = r.choice(["debours_total", "debours_total", "debours_hors_tva"])
    if fw.template == "T3":
        faf_base = "debours_total"  # montant combiné : la base hors TVA n'est pas lisible
    faf_min = D(r.choice(["15.00", "18.00", "20.00", "25.00"]))
    faf_max = r.choice([None, None, D("350.00"), D("500.00")])
    mag = D(r.choice(["9.00", "11.50", "12.00", "15.00"]))
    franchise = r.choice([2, 3, 3, 5])
    transport = D(r.choice(["85.00", "95.00", "110.00", "125.00", "140.00"]))
    manut = D(r.choice(["22.00", "25.00", "28.00", "35.00"]))
    fuel = D(r.choice(["10.0", "12.0", "14.5"]))
    surete = D(r.choice(["5.00", "6.50", "8.00"]))
    hors = r.choice(["interdites", "interdites", "tolerees"])
    postes = [
        _poste("DEDOUANEMENT", "frais_dedouanement", "forfait", LABELS["frais_dedouanement"], prix=dedouan,
               unite_base="declaration"),
        _poste("LIGNE_SUP", "frais_ligne_supplementaire", "unitaire", LABELS["frais_ligne_supplementaire"], prix=ligne,
               unite_base="article", inclus=inclus),
        _poste("AVANCE_FONDS", "frais_avance_fonds", "pourcentage", LABELS["frais_avance_fonds"], pourcentage=faf_pct,
               base_pourcentage=faf_base, minimum=faf_min, maximum=faf_max),
        _poste("MAGASINAGE", "magasinage", "par_jour", LABELS["magasinage"], prix=mag, unite_base="jour",
               franchise_jours=franchise),
        _poste("TRANSPORT", "transport", "forfait", LABELS["transport"], prix=transport, unite_base="envoi"),
        _poste("MANUTENTION", "manutention", "forfait", LABELS["manutention"], prix=manut, unite_base="envoi"),
        _poste("SURCHARGE_CARBURANT", "surcharge", "pourcentage", LABELS["surcharge_carburant"], pourcentage=fuel,
               base_pourcentage="transport"),
        _poste("SURCHARGE_SURETE", "surcharge", "forfait", LABELS["surcharge_surete"], prix=surete, unite_base="envoi"),
    ]
    if r.random() < 0.5:
        postes.append(_poste("OUVERTURE_DOSSIER", "autre_prestation", "forfait", LABELS["ouverture_dossier"],
                             prix=D(r.choice(["12.00", "15.00", "18.00"])), unite_base="dossier"))
    return {
        "schema": "controldone.bench.grille/1.0.0",
        "grille_id": f"G-{cid}-{fw.tid}",
        "client_id": cid,
        "transitaire_id": fw.tid,
        "reference": f"DEVIS-{fw.tid}-{cid}-2026 (FICTIF)",
        "valide_du": "2026-01-01",
        "valide_au": "2026-12-31",
        "statut": "validee",
        "prestations_hors_grille": hors,
        "preuve": {"document": f"devis_{fw.tid}_{cid}_2026.pdf (non fourni, saisie validée)", "page": 1},
        "postes": postes,
    }


def grid_poste(grid: dict, code: str) -> dict | None:
    for p in grid["postes"]:
        if p["code_poste"] == code:
            return p
    return None


def profile_json(reg: Registry, cid: str) -> dict:
    c = reg.clients[cid]
    return {
        "schema": "controldone.bench.profil/1.0.0",
        "client_id": cid,
        "entites": [
            {"raison_sociale": e.name, "tva": e.vat, "siren": e.siren, "eori": e.eori, "alias": list(e.aliases),
             "adresses": [", ".join(e.addr)]}
            for e in c["entities"]
        ],
        "transitaires": [
            {"transitaire_id": reg.by_template[t].tid, "nom": reg.by_template[t].name, "tva": reg.by_template[t].vat,
             "alias": [reg.by_template[t].name.replace(" (FICTIF)", "").upper()]}
            for t in sorted(c["templates"], key=lambda t: reg.by_template[t].tid)
        ],
        "tolerances": {},
    }
