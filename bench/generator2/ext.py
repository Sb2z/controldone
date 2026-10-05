"""Extension 2.1 du générateur n° 2 (option `--ext`) : nouveaux clients CL15–CL18, nouvelles familles de
transitaire G13–G16, nouveaux fournisseurs (Portugal, Pologne), nouvelles présentations de déclaration
M7–M9, nouvelles factures commerciales CP / CL / CM, nouvelles dégradations.

Tout ce module est inactif sans `--ext` : les sorties des graines existantes restent identiques à l'octet
(aucun tirage aléatoire supplémentaire dans les chemins historiques, dictionnaires historiques inchangés en
itération ; les ajouts aux dictionnaires de libellés ne servent qu'aux recherches par clé).
Tous les noms sont inventés et marqués FICTIF.
"""

from __future__ import annotations

from decimal import Decimal as D

from .util import eori_fr, rng_for, siren_fictif, tva_fr

EXT_FAMILIES = ["G13", "G14", "G15", "G16"]
EXT_LAYOUTS = ["M7", "M8", "M9"]
EXT_CI_LAYOUTS = ["CP", "CL", "CM"]
EXT_CLIENTS = ["CL15", "CL16", "CL17", "CL18"]
EXT_MODES = ["skewlow", "overlay", "twoup", "jpegheavy", "faxnoise"]
VAT_INCLUSIVE_FAMILIES = {"G13"}

FORWARDERS_EXT = {
    "G13": {"nom": "Trânsitos Imaginários Lda", "lang": "pt",
            "adresse": ["Delegação de Lyon", "22 rue de la Fable", "69003 Lyon, França"],
            "alias": ["Transitos Imaginarios", "TRANSIMAG"]},
    "G14": {"nom": "Spedycja Fikcyjna Sp. z o.o.", "lang": "pl",
            "adresse": ["Oddział we Francji", "5 allée du Conte", "67960 Entzheim, Francja"],
            "alias": ["Spedycja Fikcyjna", "SPEDFIK"]},
    "G15": {"nom": "Zollagentur Phantasie AG", "lang": "de",
            "adresse": ["Niederlassung Saint-Louis (F)", "3 rue du Leurre", "68300 Saint-Louis, Frankreich"],
            "alias": ["Zollagentur Phantasie", "ZA PHANTASIE"]},
    "G16": {"nom": "Hypothèse Transports & Douane SAS", "lang": "fr",
            "adresse": ["Parc logistique Conjecture", "60 rue de l'Hypothèse", "91320 Wissous", "France"],
            "alias": ["Hypothese Transports", "HYPOTHESE T&D"]},
}

CLIENTS_EXT = [
    {"client_id": "CL15", "groupe": None, "secteur": "optique", "entites": [
        {"raison_sociale": "Helvetia Fictiva AG", "alias": ["Helvetia Fictiva", "HELV-FICT"],
         "adresse": ["Phantasiestrasse 8", "4051 Basel", "Suisse"], "fiscal_rep": True}]},
    {"client_id": "CL16", "groupe": "Groupe Mirabilis (FICTIF)", "secteur": "electro", "entites": [
        {"raison_sociale": "Mirabilis Holding SA", "alias": ["Mirabilis Holding", "MIRA-HOLD"],
         "adresse": ["1 cours de la Merveille", "75008 Paris", "France"]},
        {"raison_sociale": "Mirabilis France Distribution SAS", "alias": ["Mirabilis Distribution", "MIRA-DIST"],
         "adresse": ["ZAC des Prodiges, lot 4", "77700 Serris", "France"], "ship_to_sister": True},
        {"raison_sociale": "Mirabilis Services Techniques SARL", "alias": ["Mirabilis Services", "MIRA-ST"],
         "adresse": ["8 rue de l'Énigme", "59650 Villeneuve-d'Ascq", "France"], "ship_to_sister": True},
    ]},
    {"client_id": "CL17", "groupe": None, "secteur": "brasserie", "entites": [
        {"raison_sociale": "Malterie du Songe SAS", "alias": ["Malterie du Songe", "MALT-SONGE"],
         "adresse": ["Chemin des Rêveries", "02000 Laon", "France"], "vat_spaced": True}]},
    {"client_id": "CL18", "groupe": "Atelier Hypothétique (FICTIF)", "secteur": "quincaillerie", "entites": [
        {"raison_sociale": "Atelier Hypothétique SARL", "alias": ["Atelier Hypothetique", "Brico-Chimère", "AT-HYPO"],
         "adresse": ["14 rue de la Conjecture", "35000 Rennes", "France"], "trade_name": "Brico-Chimère"},
        {"raison_sociale": "Hypothétique Distribution SAS", "alias": ["Hypothetique Distribution", "HYP-DIST"],
         "adresse": ["ZI du Mirage", "35135 Chantepie", "France"], "trade_name": "HYP-DIST Négoce"},
    ]},
]

# Transitaires par client en mode étendu (les anciens clients gagnent les nouvelles familles)
CLIENT_FORWARDERS_EXT = {
    "CL11": ["G1", "G2", "G3", "G7", "G9", "G10", "G12", "G6", "G13", "G16"],
    "CL12": ["G1", "G4", "G5", "G6", "G8", "G12", "G2", "G3", "G14", "G15"],
    "CL13": ["G11", "G9", "G4", "G10", "G7", "G5", "G1", "G13", "G15"],
    "CL14": ["G3", "G5", "G6", "G8", "G2", "G10", "G11", "G4", "G12", "G14", "G16"],
    "CL15": ["G15", "G13", "G3", "G11", "G14", "G16"],
    "CL16": ["G13", "G14", "G16", "G1", "G10", "G15"],
    "CL17": ["G14", "G15", "G16", "G5", "G12", "G13"],
    "CL18": ["G16", "G13", "G15", "G14", "G9", "G6"],
}

SUPPLIERS_EXT = [
    {"id": "S_PT", "nom": "Porto Imaginário Comércio Lda", "pays": "PT",
     "adresse": ["Rua da Fantasia 77", "4050-000 Porto", "Portugal"], "taxid": "NIF PT500000FX7",
     "devises": ["EUR", "USD"], "layouts": ["CP", "CM"], "lang": "pt", "port": "Leixões"},
    {"id": "S_PL", "nom": "Fikcja Handel Sp. z o.o.", "pays": "PL",
     "adresse": ["ul. Zmyślona 12", "80-000 Gdańsk", "Polska"], "taxid": "NIP PL0000000FX8",
     "devises": ["PLN", "EUR"], "layouts": ["CL", "CM"], "lang": "pl", "port": "Gdynia"},
]

CLIENT_SUPPLIERS_EXT = {
    "CL11": ["S_CN1", "S_KR", "S_JP", "S_US", "S_GB", "S_CH1", "S_AW", "S_TR", "S_PT", "S_PL"],
    "CL12": ["S_CH1", "S_CH2", "S_GB", "S_MX", "S_TR", "S_US", "S_CN2", "S_IN", "S_PL", "S_PT"],
    "CL13": ["S_CN1", "S_JP", "S_KR", "S_CH2", "S_CH3", "S_US", "S_IN", "S_PT"],
    "CL14": ["S_CN2", "S_GB", "S_TR", "S_IN", "S_CH3", "S_MX", "S_AW", "S_CH1", "S_PL"],
    "CL15": ["S_CN1", "S_JP", "S_PT", "S_PL", "S_CH3", "S_US"],
    "CL16": ["S_CN1", "S_KR", "S_PL", "S_PT", "S_GB", "S_US"],
    "CL17": ["S_PL", "S_PT", "S_CH1", "S_TR", "S_GB"],
    "CL18": ["S_PL", "S_PT", "S_CN2", "S_IN", "S_TR"],
}

LABELS_EXT = {
    "pt": {
        "debours_droits": ["Direitos aduaneiros", "Direitos de importação"],
        "debours_autres_taxes": ["Direitos anti-dumping", "Outras imposições"],
        "debours_tva": ["IVA na importação", "IVA importação"],
        "debours_combines": ["Direitos e impostos", "Imposições aduaneiras"],
        "debours_forfait_petits_envois": ["Direito fixo pequenas remessas", "Direito fixo por artigo"],
        "frais_dedouanement": ["Desalfandegamento", "Despacho aduaneiro"],
        "frais_avance_fonds": ["Comissão de adiantamento", "Adiantamento de direitos"],
        "frais_ligne_supplementaire": ["Adições suplementares", "Linhas suplementares"],
        "magasinage": ["Armazenagem", "Armazenagem em entreposto"],
        "transport": ["Entrega", "Transporte aeroporto - armazém"],
        "manutention": ["Manuseamento", "Movimentação de carga"],
        "surcharge": ["Sobretaxa de segurança", "Sobretaxa de combustível"],
        "autre_prestation": ["Abertura de processo", "Despesas de processo"],
    },
    "pl": {
        "debours_droits": ["Cło", "Należności celne"],
        "debours_autres_taxes": ["Cło antydumpingowe", "Inne należności"],
        "debours_tva": ["VAT z tytułu importu", "VAT importowy"],
        "debours_combines": ["Cło i podatki", "Należności celno-podatkowe"],
        "debours_forfait_petits_envois": ["Opłata ryczałtowa za artykuł", "Cło ryczałtowe przesyłki"],
        "frais_dedouanement": ["Odprawa celna", "Zgłoszenie importowe"],
        "frais_avance_fonds": ["Prowizja za kredytowanie", "Prowizja od należności"],
        "frais_ligne_supplementaire": ["Dodatkowe pozycje", "Pozycje dodatkowe zgłoszenia"],
        "magasinage": ["Składowanie", "Magazynowanie"],
        "transport": ["Dostawa", "Transport lotnisko - magazyn"],
        "manutention": ["Obsługa ładunku", "Przeładunek"],
        "surcharge": ["Dopłata bezpieczeństwa", "Dopłata paliwowa"],
        "autre_prestation": ["Otwarcie sprawy", "Opłata administracyjna"],
    },
}
SURCHARGES_HORS_GRILLE_EXT = {"pt": "Sobretaxa de época alta", "pl": "Dopłata sezonowa"}
PRESTATIONS_HORS_GRILLE_EXT = {
    "pt": ["Taxa de transmissão eletrónica", "Taxa de arquivo", "Verificação documental"],
    "pl": ["Opłata za transmisję", "Opłata archiwizacyjna", "Kontrola dokumentów"],
}
REMISE_EXT = {"pt": "Desconto comercial", "pl": "Rabat handlowy"}
GESTE_EXT = {"pt": "Crédito comercial", "pl": "Rabat posprzedażowy"}
UNIT_LABELS_EXT = {
    "C62": {"pt": ["un.", "unidades"], "pl": ["szt.", "sztuk"]},
    "PR": {"pt": ["pares"], "pl": ["par"]},
    "KGM": {"pt": ["kg"], "pl": ["kg"]},
}


def install_dicts(world_mod):
    """Ajoute les clés pt / pl et les nouveaux fournisseurs aux dictionnaires de recherche (sans effet sur
    les chemins historiques : aucune itération sur ces dictionnaires)."""
    for k, v in LABELS_EXT.items():
        world_mod.LABELS.setdefault(k, v)
    for k, v in SURCHARGES_HORS_GRILLE_EXT.items():
        world_mod.SURCHARGES_HORS_GRILLE.setdefault(k, v)
    for k, v in PRESTATIONS_HORS_GRILLE_EXT.items():
        world_mod.PRESTATIONS_HORS_GRILLE.setdefault(k, v)
    for k, v in REMISE_EXT.items():
        world_mod.REMISE.setdefault(k, v)
    for u, m in UNIT_LABELS_EXT.items():
        for k, v in m.items():
            world_mod.UNIT_LABELS[u].setdefault(k, v)
    for s in SUPPLIERS_EXT:
        world_mod.SUPPLIERS_BY_ID.setdefault(s["id"], s)


def extend_world(world: dict, seed: int, make_grid) -> dict:
    """Complète un monde construit par build_world (tirages séparés : graine « world_ext »)."""
    rng = rng_for(seed, "world_ext")
    used = {e["siren"] for c in world["clients"].values() for e in c["entites"]}
    used |= {t["siren"] for t in world["tiers"]} | {f["siren"] for f in world["forwarders"].values()}
    # représentant fiscal (CL15)
    rep_siren = siren_fictif(rng, used)
    rep = {"nom": "Repfisc Imaginaire SAS (représentant fiscal)", "tva": tva_fr(rep_siren), "siren": rep_siren}
    world["fiscal_rep"] = rep
    for cdef in CLIENTS_EXT:
        ents = []
        for e in cdef["entites"]:
            siren = siren_fictif(rng, used)
            ent = {**e, "siren": siren, "tva": tva_fr(siren), "eori": eori_fr(siren)}
            if e.get("fiscal_rep"):
                ent["adresse"] = list(e["adresse"]) + ["Rep. fiscal : " + rep["nom"].split(" (")[0], f"TVA rep. fiscal : {rep['tva']}"]
                ent["fiscal_rep"] = rep
            ents.append(ent)
        world["clients"][cdef["client_id"]] = {**cdef, "entites": ents}
    for fam, fdef in FORWARDERS_EXT.items():
        siren = siren_fictif(rng, used)
        world["forwarders"][fam] = {**fdef, "family": fam, "transitaire_id": f"TR-{fam}", "siren": siren,
                                    "tva": tva_fr(siren), "iban": f"FR76 0000 0000 0000 {rng.randint(1000, 9999)} FICT"}
    for cid, fams in CLIENT_FORWARDERS_EXT.items():
        for fam in fams:
            if (cid, fam) in world["grids"]:
                continue
            g = make_grid(rng_for(seed, "grid", cid, fam), cid, fam, world["forwarders"][fam])
            world["grids"][(cid, fam)] = adapt_grid(g, fam, rng_for(seed, "grid_ext", cid, fam))
    world["ext"] = True
    return world


def adapt_grid(g: dict, fam: str, rng) -> dict:
    """Pratiques tarifaires propres aux nouvelles familles : manutention au kg (G14), livraison au kg (G16)."""
    if fam == "G14":
        for p in g["postes"]:
            if p["nature"] == "manutention":
                break
        else:
            p = {"code_poste": "MANUT", "nature": "manutention", "libelles_reconnus": [], "mode": "forfait", "prix": "0",
                 "unite_base": "envoi", "pourcentage": None, "base_pourcentage": None, "minimum": None, "maximum": None,
                 "franchise_jours": None, "inclus": None, "devise": "EUR"}
            g["postes"].append(p)
            from .world import LABELS
            p["libelles_reconnus"] = list(LABELS["pl"]["manutention"]) + list(LABELS["fr"]["manutention"])
        p.update({"mode": "unitaire", "unite_base": "kg", "prix": str(D(rng.choice(["0.08", "0.10", "0.12", "0.15"])))})
    if fam == "G16":
        for p in g["postes"]:
            if p["nature"] == "transport":
                p.update({"mode": "unitaire", "unite_base": "kg", "prix": str(D(rng.choice(["0.18", "0.22", "0.25", "0.30"])))})
    return g
