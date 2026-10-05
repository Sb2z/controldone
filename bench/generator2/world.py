"""Monde fictif du générateur n° 2 : clients CL11–CL14, transitaires (familles G1–G12),
fournisseurs, catalogues de produits, grilles tarifaires.

Tous les noms sont inventés et volontairement fantaisistes (« Fictilog », « Demofret »,
« Simulacargo »…). Aucun nom de société, de transitaire ou de logiciel réel.
"""

from __future__ import annotations

from decimal import Decimal as D

from .util import eori_fr, rng_for, siren_fictif, tva_fr

# ---------------------------------------------------------------------------
# Clients
# ---------------------------------------------------------------------------

CLIENTS_DEF = [
    {"client_id": "CL11", "groupe": "Groupe Imaginor (FICTIF)", "secteur": "electro", "entites": [
        {"raison_sociale": "Imaginor Distribution SAS", "alias": ["Imaginor Distribution", "IMAG-DIST"],
         "adresse": ["14 allée des Chimères", "69007 Lyon", "France"]},
        {"raison_sociale": "Imaginor Industrie SARL", "alias": ["Imaginor Industrie", "IMAG-IND"],
         "adresse": ["ZI des Mirages, 3 rue du Songe", "38070 Saint-Quentin-Fallavier", "France"]},
        {"raison_sociale": "Imaginor Logistique SAS", "alias": ["Imaginor Logistique", "IMAG-LOG"],
         "adresse": ["Plateforme Utopie, bâtiment C", "01120 Montluel", "France"]},
    ]},
    {"client_id": "CL12", "groupe": None, "secteur": "brasserie", "entites": [
        {"raison_sociale": "Brasserie Chimérique SA", "alias": ["Brasserie Chimerique", "BRCHIM"],
         "adresse": ["7 quai de l'Illusion", "59000 Lille", "France"]},
    ]},
    {"client_id": "CL13", "groupe": None, "secteur": "optique", "entites": [
        {"raison_sociale": "Optique Fantasia SARL", "alias": ["Optique Fantasia", "OPTFAN"],
         "adresse": ["21 boulevard du Mirage", "33000 Bordeaux", "France"]},
    ]},
    {"client_id": "CL14", "groupe": "Utopia Holding (FICTIF)", "secteur": "quincaillerie", "entites": [
        {"raison_sociale": "Quincaillerie Utopia SAS", "alias": ["Quincaillerie Utopia", "QU-UTOPIA"],
         "adresse": ["5 rue de Nulle-Part", "44000 Nantes", "France"]},
        {"raison_sociale": "Utopia Outillage SARL", "alias": ["Utopia Outillage", "UTO-OUT"],
         "adresse": ["Parc d'activités Atlantide", "44470 Carquefou", "France"]},
    ]},
]

# Entités tierces (hors client), pour l'injection « entite_tierce » / « client_facture_different »
TIERS_DEF = [
    {"raison_sociale": "Société Nébuleuse d'Import SARL", "adresse": ["9 impasse Fantôme", "13002 Marseille", "France"]},
    {"raison_sociale": "Comptoir Hypothétique SAS", "adresse": ["2 place de l'Ailleurs", "67000 Strasbourg", "France"]},
    {"raison_sociale": "Négoce Apocryphe SA", "adresse": ["40 avenue Irréelle", "31000 Toulouse", "France"]},
]

# ---------------------------------------------------------------------------
# Transitaires : une famille de mise en page par transitaire
# ---------------------------------------------------------------------------

FORWARDERS_DEF = {
    "G1": {"nom": "Fictilog Transit SAS", "lang": "fr", "adresse": ["Terminal Chimère, quai 12", "76600 Le Havre", "France"],
           "alias": ["Fictilog", "FICTILOG TRANSIT"]},
    "G2": {"nom": "Placebo Freight Ltd", "lang": "en", "adresse": ["French branch - Cargo Zone 4", "95700 Roissy-en-France", "France"],
           "alias": ["Placebo Freight", "PLACEBO FRT"]},
    "G3": {"nom": "Simulacargo GmbH", "lang": "de", "adresse": ["Zweigniederlassung Strasbourg", "Port du Rhin, 8 rue Fictive", "67100 Strasbourg, Frankreich"],
           "alias": ["Simulacargo", "SIMULACARGO GMBH"]},
    "G4": {"nom": "Spedizioni Immaginarie Srl", "lang": "it", "adresse": ["Sede secondaria di Nizza", "15 avenue Inventée", "06300 Nice, Francia"],
           "alias": ["Spedizioni Immaginarie", "SPED. IMMAGINARIE"]},
    "G5": {"nom": "Tránsitos Ficticios SL", "lang": "es", "adresse": ["Sucursal de Perpiñán", "3 rue Imaginaire", "66000 Perpignan, Francia"],
           "alias": ["Transitos Ficticios", "TRANSFICT"]},
    "G6": {"nom": "Demofret SAS", "lang": "fr", "adresse": ["Zone portuaire Démo, hangar 3", "13002 Marseille", "France"],
           "alias": ["Demofret", "DEMOFRET SAS"]},
    "G7": {"nom": "Virtuafret SAS", "lang": "fr", "adresse": ["10 rue du Virtuel", "94150 Rungis", "France"],
           "alias": ["Virtuafret"]},
    "G8": {"nom": "Pseudotrans Douane SARL", "lang": "fr", "adresse": ["Aéroport Fictif, zone fret 2", "31700 Blagnac", "France"],
           "alias": ["Pseudotrans", "PSEUDOTRANS DOUANE"]},
    "G9": {"nom": "Mirage Douane & Fret", "lang": "fr", "adresse": ["45 chemin des Mirages", "69800 Saint-Priest", "France"],
           "alias": ["Mirage Douane", "MIRAGE D&F"]},
    "G10": {"nom": "Chimera Customs Brokers Ltd", "lang": "en", "adresse": ["(France branch) 2 rue Chimérique", "59810 Lesquin", "France"],
            "alias": ["Chimera Customs", "CHIMERA CB"]},
    "G11": {"nom": "Nebula Express Fictif", "lang": "fr_en", "adresse": ["Hub Nébuleuse, BP 77", "95700 Roissy-en-France", "France"],
            "alias": ["Nebula Express", "NEBULA EXP"]},
    "G12": {"nom": "Schaduw Expeditie B.V.", "lang": "nl", "adresse": ["Vestiging Rijsel / Lille", "12 rue de l'Ombre", "59000 Lille, Frankrijk"],
            "alias": ["Schaduw Expeditie", "SCHADUW EXP"]},
}

FAMILIES = list(FORWARDERS_DEF)

# Transitaires utilisés par chaque client (chacun a une grille validée)
CLIENT_FORWARDERS = {
    "CL11": ["G1", "G2", "G3", "G7", "G9", "G10", "G12", "G6"],
    "CL12": ["G1", "G4", "G5", "G6", "G8", "G12", "G2", "G3"],
    "CL13": ["G11", "G9", "G4", "G10", "G7", "G5", "G1"],
    "CL14": ["G3", "G5", "G6", "G8", "G2", "G10", "G11", "G4", "G12"],
}

# ---------------------------------------------------------------------------
# Fournisseurs étrangers
# ---------------------------------------------------------------------------

SUPPLIERS = [
    {"id": "S_CN1", "nom": "Shenzhen Fictive Trading Co., Ltd", "nom_local": "深圳虚构贸易有限公司", "pays": "CN",
     "adresse": ["Bldg 9, Imaginary Science Park", "Nanshan District, Shenzhen", "China"], "taxid": "USCC 91440300FICT0001X",
     "devises": ["USD", "CNY"], "layouts": ["CF", "CA", "CU"], "lang": "en", "port": "Shenzhen"},
    {"id": "S_CN2", "nom": "Ningbo Imaginary Hardware Co., Ltd", "nom_local": "宁波想象五金有限公司", "pays": "CN",
     "adresse": ["88 Phantom Road, Beilun", "Ningbo, Zhejiang", "China"], "taxid": "USCC 91330206FICT0002Y",
     "devises": ["CNY", "USD"], "layouts": ["CF", "CA", "CK"], "lang": "en", "port": "Ningbo"},
    {"id": "S_JP", "nom": "Osaka Phantom Optics K.K.", "pays": "JP",
     "adresse": ["3-7 Maboroshi-cho, Kita-ku", "Osaka 530-0000", "Japan"], "taxid": "T0000000000FX1",
     "devises": ["JPY"], "layouts": ["CA", "CG"], "lang": "en", "port": "Osaka"},
    {"id": "S_KR", "nom": "Busan Mirage Electronics Co.", "pays": "KR",
     "adresse": ["21 Sinkiru-ro, Haeundae-gu", "Busan 48000", "Korea"], "taxid": "BRN 000-00-00FX2",
     "devises": ["KRW"], "layouts": ["CA", "CK"], "lang": "en", "port": "Busan"},
    {"id": "S_IN", "nom": "Pune Notional Textiles Pvt Ltd", "pays": "IN",
     "adresse": ["Plot 404, Kalpana Industrial Estate", "Pune 411000", "India"], "taxid": "GSTIN 27FICT0000F1Z0",
     "devises": ["INR", "USD"], "layouts": ["CA", "CG"], "lang": "en", "port": "Nhava Sheva"},
    {"id": "S_TR", "nom": "Izmir Hayali Makine A.S.", "pays": "TR",
     "adresse": ["Hayal Sokak No. 5, Bornova", "35000 Izmir", "Turkey"], "taxid": "VKN 0000000FX3",
     "devises": ["TRY", "EUR"], "layouts": ["CA", "CE2"], "lang": "en", "port": "Izmir"},
    {"id": "S_GB", "nom": "Sheffield Pretend Tools Ltd", "pays": "GB",
     "adresse": ["Unit 7, Makebelieve Works", "Sheffield S1 0ZZ", "United Kingdom"], "taxid": "GB000 0000 00",
     "devises": ["GBP", "EUR"], "layouts": ["CA", "CU", "CK"], "lang": "en", "port": "Felixstowe"},
    {"id": "S_CH1", "nom": "Zürcher Scheinwerk AG", "pays": "CH",
     "adresse": ["Traumgasse 12", "8000 Zürich", "Schweiz"], "taxid": "CHE-000.000.001 MWST",
     "devises": ["CHF", "EUR"], "layouts": ["CB"], "lang": "de", "port": "Basel"},
    {"id": "S_CH2", "nom": "Lugano Finzione SA", "pays": "CH",
     "adresse": ["Via dei Sogni 4", "6900 Lugano", "Svizzera"], "taxid": "CHE-000.000.002 IVA",
     "devises": ["CHF", "EUR"], "layouts": ["CC"], "lang": "it", "port": "Chiasso"},
    {"id": "S_CH3", "nom": "Genève Illusoire Sàrl", "pays": "CH",
     "adresse": ["Rue de l'Utopie 30", "1201 Genève", "Suisse"], "taxid": "CHE-000.000.003 TVA",
     "devises": ["CHF", "EUR"], "layouts": ["CH"], "lang": "fr", "port": "Genève"},
    {"id": "S_AW", "nom": "Oranjestad Denkbeeld Handel N.V.", "pays": "AW",
     "adresse": ["Fantasiestraat 18", "Oranjestad", "Aruba"], "taxid": "PN 0000FX4",
     "devises": ["USD"], "layouts": ["CD"], "lang": "nl", "port": "Oranjestad"},
    {"id": "S_MX", "nom": "Monterrey Ficción Industrial SA de CV", "pays": "MX",
     "adresse": ["Av. Quimera 1200", "64000 Monterrey, N.L.", "México"], "taxid": "RFC FIC000000FX5",
     "devises": ["USD", "EUR"], "layouts": ["CE"], "lang": "es", "port": "Veracruz"},
    {"id": "S_US", "nom": "Ohio Makebelieve Supply Inc.", "pays": "US",
     "adresse": ["500 Nowhere Blvd", "Columbus, OH 43000", "USA"], "taxid": "EIN 00-000FX6",
     "devises": ["USD"], "layouts": ["CA", "CG", "CU"], "lang": "en", "port": "New York"},
]

SUPPLIERS_BY_ID = {s["id"]: s for s in SUPPLIERS}

CLIENT_SUPPLIERS = {
    "CL11": ["S_CN1", "S_KR", "S_JP", "S_US", "S_GB", "S_CH1", "S_AW", "S_TR"],
    "CL12": ["S_CH1", "S_CH2", "S_GB", "S_MX", "S_TR", "S_US", "S_CN2", "S_IN"],
    "CL13": ["S_CN1", "S_JP", "S_KR", "S_CH2", "S_CH3", "S_US", "S_IN"],
    "CL14": ["S_CN2", "S_GB", "S_TR", "S_IN", "S_CH3", "S_MX", "S_AW", "S_CH1"],
}

# ---------------------------------------------------------------------------
# Catalogues (codes à 10 chiffres ; taux de droits fictifs, la famille B ne juge jamais un taux)
# desc : en, fr, de, it, nl, es
# ---------------------------------------------------------------------------

def _p(ref, hs, en, fr, de, it, nl, es, unit, price, kg, duty, ad=None):
    return {"ref": ref, "hs": hs, "desc": {"en": en, "fr": fr, "de": de, "it": it, "nl": nl, "es": es},
            "unit": unit, "price": D(price), "kg": D(kg), "duty": D(duty), "ad": D(ad) if ad else None}


CATALOG = {
    "electro": [
        _p("IMG-PS240", "8504403090", "Switching power supply 240W", "Alimentation à découpage 240 W", "Schaltnetzteil 240 W", "Alimentatore switching 240 W", "Schakelende voeding 240 W", "Fuente conmutada 240 W", "C62", "18.40", "0.62", "0.0"),
        _p("IMG-LED60", "9405110090", "LED ceiling panel 60x60", "Panneau LED plafond 60x60", "LED-Deckenpanel 60x60", "Pannello LED soffitto 60x60", "LED-plafondpaneel 60x60", "Panel LED de techo 60x60", "C62", "22.10", "2.35", "4.7"),
        _p("IMG-CBL5", "8544429090", "Data cable 5 m shielded", "Câble de données blindé 5 m", "Datenkabel geschirmt 5 m", "Cavo dati schermato 5 m", "Datakabel afgeschermd 5 m", "Cable de datos apantallado 5 m", "C62", "3.85", "0.21", "3.7"),
        _p("IMG-KB102", "8471607000", "USB keyboard AZERTY", "Clavier USB AZERTY", "USB-Tastatur AZERTY", "Tastiera USB AZERTY", "USB-toetsenbord AZERTY", "Teclado USB AZERTY", "C62", "9.70", "0.55", "0.0"),
        _p("IMG-MTR7", "8501109990", "Micro motor 12V", "Micromoteur 12 V", "Mikromotor 12 V", "Micromotore 12 V", "Micromotor 12 V", "Micromotor 12 V", "C62", "4.15", "0.09", "2.7"),
        _p("IMG-SNS3", "9026208000", "Pressure sensor module", "Module capteur de pression", "Drucksensormodul", "Modulo sensore di pressione", "Druksensormodule", "Módulo sensor de presión", "C62", "31.50", "0.12", "0.0"),
        _p("IMG-FAN12", "8414598090", "Cooling fan 120 mm", "Ventilateur 120 mm", "Lüfter 120 mm", "Ventola 120 mm", "Ventilator 120 mm", "Ventilador 120 mm", "C62", "2.95", "0.15", "2.3"),
        _p("IMG-BAT18", "8507600090", "Li-ion battery pack 18V", "Batterie Li-ion 18 V", "Li-Ion-Akku 18 V", "Batteria agli ioni di litio 18 V", "Li-ionaccu 18 V", "Batería de iones de litio 18 V", "C62", "27.80", "0.48", "2.7", "12.5"),
    ],
    "brasserie": [
        _p("BRC-MALT", "1107100099", "Pale malt, unroasted (25 kg bags)", "Malt pâle non torréfié (sacs 25 kg)", "Helles Malz, ungeröstet (25-kg-Säcke)", "Malto chiaro non torrefatto (sacchi 25 kg)", "Licht mout, ongebrand (zakken 25 kg)", "Malta pálida sin tostar (sacos 25 kg)", "KGM", "0.92", "1.0", "6.1"),
        _p("BRC-HOP", "1210200000", "Hop pellets T90", "Houblon en granulés T90", "Hopfenpellets T90", "Luppolo in pellet T90", "Hopkorrels T90", "Lúpulo en pellets T90", "KGM", "14.60", "1.0", "5.8"),
        _p("BRC-BOT33", "7010904100", "Amber glass bottle 33 cl", "Bouteille verre ambré 33 cl", "Braunglasflasche 33 cl", "Bottiglia vetro ambrato 33 cl", "Bruine glazen fles 33 cl", "Botella vidrio ámbar 33 cl", "C62", "0.11", "0.19", "5.0", "9.6"),
        _p("BRC-CAP26", "8309100000", "Crown caps 26 mm", "Capsules couronne 26 mm", "Kronkorken 26 mm", "Tappi a corona 26 mm", "Kroonkurken 26 mm", "Chapas corona 26 mm", "C62", "0.012", "0.002", "2.7"),
        _p("BRC-KEG30", "7310100000", "Stainless keg 30 L", "Fût inox 30 L", "Edelstahlfass 30 L", "Fusto inox 30 L", "RVS-vat 30 L", "Barril inox 30 L", "C62", "48.00", "9.8", "2.7"),
        _p("BRC-YST", "2102109000", "Dried brewing yeast", "Levure de brasserie sèche", "Getrocknete Brauhefe", "Lievito di birra secco", "Gedroogde brouwgist", "Levadura cervecera seca", "KGM", "38.00", "1.0", "10.9"),
        _p("BRC-LBL", "4821101000", "Printed paper labels", "Étiquettes papier imprimées", "Bedruckte Papieretiketten", "Etichette in carta stampate", "Bedrukte papieren etiketten", "Etiquetas de papel impresas", "C62", "0.018", "0.001", "0.0"),
        _p("BRC-PMP", "8413702100", "Centrifugal wort pump", "Pompe centrifuge à moût", "Kreiselpumpe für Würze", "Pompa centrifuga per mosto", "Centrifugaalpomp voor wort", "Bomba centrífuga de mosto", "C62", "410.00", "18.5", "1.7"),
    ],
    "optique": [
        _p("OPF-FR01", "9003110000", "Plastic spectacle frames", "Montures de lunettes en plastique", "Brillenfassungen aus Kunststoff", "Montature in plastica", "Kunststof brilmonturen", "Monturas de plástico", "C62", "6.20", "0.025", "2.2"),
        _p("OPF-FR02", "9003191000", "Titanium spectacle frames", "Montures titane", "Titan-Brillenfassungen", "Montature in titanio", "Titanium brilmonturen", "Monturas de titanio", "C62", "14.90", "0.018", "2.2"),
        _p("OPF-SUN", "9004109100", "Sunglasses polarised", "Lunettes de soleil polarisées", "Polarisierte Sonnenbrillen", "Occhiali da sole polarizzati", "Gepolariseerde zonnebrillen", "Gafas de sol polarizadas", "C62", "4.75", "0.03", "2.9", "7.4"),
        _p("OPF-LNS", "9001500000", "Ophthalmic lenses, organic", "Verres ophtalmiques organiques", "Brillengläser organisch", "Lenti oftalmiche organiche", "Brillenglazen organisch", "Lentes oftálmicas orgánicas", "PR", "3.10", "0.012", "2.9"),
        _p("OPF-CASE", "4202329000", "Hard spectacle case", "Étui à lunettes rigide", "Brillenetui hart", "Astuccio rigido per occhiali", "Hard brillenkoker", "Estuche rígido para gafas", "C62", "0.85", "0.06", "3.7"),
        _p("OPF-CLTH", "6307109000", "Microfibre cleaning cloth", "Chiffonnette microfibre", "Mikrofaser-Putztuch", "Panno in microfibra", "Microvezel poetsdoek", "Gamuza de microfibra", "C62", "0.14", "0.004", "4.5"),
        _p("OPF-CHN", "7117190000", "Spectacle chain, base metal", "Chaînette à lunettes métal commun", "Brillenkette unedel", "Catenella per occhiali", "Brillenkoord metaal", "Cadena para gafas", "C62", "0.95", "0.008", "4.0"),
        _p("OPF-TOOL", "8205598099", "Optician screwdriver set", "Jeu de tournevis d'opticien", "Optiker-Schraubendrehersatz", "Set cacciaviti per ottico", "Opticien schroevendraaierset", "Juego de destornilladores de óptico", "C62", "5.40", "0.11", "2.7"),
    ],
    "quincaillerie": [
        _p("QU-HAM5", "8205200000", "Claw hammer 500 g", "Marteau arrache-clou 500 g", "Klauenhammer 500 g", "Martello da carpentiere 500 g", "Klauwhamer 500 g", "Martillo de carpintero 500 g", "C62", "3.40", "0.62", "3.7"),
        _p("QU-PLR", "8203200000", "Combination pliers 180 mm", "Pince universelle 180 mm", "Kombizange 180 mm", "Pinza universale 180 mm", "Combinatietang 180 mm", "Alicate universal 180 mm", "C62", "2.15", "0.28", "3.7"),
        _p("QU-SCR4", "7318159590", "Steel wood screws 4x40", "Vis à bois acier 4x40", "Holzschrauben Stahl 4x40", "Viti per legno acciaio 4x40", "Houtschroeven staal 4x40", "Tornillos para madera 4x40", "KGM", "2.60", "1.0", "3.7", "22.1"),
        _p("QU-HNG", "8302410000", "Door hinges, steel", "Charnières de porte acier", "Türscharniere Stahl", "Cerniere per porte in acciaio", "Deurscharnieren staal", "Bisagras de puerta acero", "PR", "0.78", "0.14", "2.7"),
        _p("QU-DRL", "8467210000", "Cordless drill 18V", "Perceuse sans fil 18 V", "Akku-Bohrmaschine 18 V", "Trapano a batteria 18 V", "Accuboormachine 18 V", "Taladro inalámbrico 18 V", "C62", "24.50", "1.45", "2.7"),
        _p("QU-TAPE", "9017800000", "Measuring tape 5 m", "Mètre ruban 5 m", "Bandmaß 5 m", "Metro a nastro 5 m", "Rolmaat 5 m", "Cinta métrica 5 m", "C62", "1.05", "0.19", "2.7"),
        _p("QU-BOLT", "7318158290", "Hex bolts M10, steel", "Boulons hexagonaux M10 acier", "Sechskantschrauben M10 Stahl", "Bulloni esagonali M10 acciaio", "Zeskantbouten M10 staal", "Pernos hexagonales M10 acero", "KGM", "1.95", "1.0", "3.7", "22.1"),
        _p("QU-LADR", "7616991000", "Aluminium step ladder", "Escabeau aluminium", "Aluminium-Stehleiter", "Scala in alluminio", "Aluminium trapladder", "Escalera de aluminio", "C62", "19.80", "4.2", "6.0"),
    ],
}

UNIT_LABELS = {
    "C62": {"en": ["pcs", "PCS", "units"], "fr": ["pièces", "pce", "u."], "de": ["Stk.", "Stück"], "it": ["pz", "pezzi"],
            "nl": ["st.", "stuks"], "es": ["uds", "unidades"]},
    "PR": {"en": ["pairs", "PRS"], "fr": ["paires", "pr"], "de": ["Paar", "Pr."], "it": ["paia"], "nl": ["paar"], "es": ["pares"]},
    "KGM": {"en": ["kg", "KGS"], "fr": ["kg"], "de": ["kg"], "it": ["kg"], "nl": ["kg"], "es": ["kg"]},
}

# Taux indicatifs (repli si la table BCE locale ne couvre pas la date)
FALLBACK_RATES = {"USD": "1.15", "CNY": "7.80", "JPY": "184", "GBP": "0.86", "CHF": "0.93",
                  "KRW": "1700", "INR": "110", "TRY": "54"}

INCOTERMS = ["EXW", "FCA", "FOB", "CFR", "CIF", "CPT", "CIP", "DAP", "DDP"]


# ---------------------------------------------------------------------------
# Construction déterministe du monde
# ---------------------------------------------------------------------------

def build_world(seed: int) -> dict:
    rng = rng_for(seed, "world")
    used: set = set()
    clients = {}
    for cdef in CLIENTS_DEF:
        ents = []
        for e in cdef["entites"]:
            siren = siren_fictif(rng, used)
            ents.append({**e, "siren": siren, "tva": tva_fr(siren), "eori": eori_fr(siren)})
        clients[cdef["client_id"]] = {**cdef, "entites": ents}
    tiers = []
    for t in TIERS_DEF:
        siren = siren_fictif(rng, used)
        tiers.append({**t, "siren": siren, "tva": tva_fr(siren), "eori": eori_fr(siren), "alias": []})
    forwarders = {}
    for fam, fdef in FORWARDERS_DEF.items():
        siren = siren_fictif(rng, used)
        forwarders[fam] = {**fdef, "family": fam, "transitaire_id": f"TR-{fam}", "siren": siren,
                           "tva": tva_fr(siren), "iban": f"FR76 0000 0000 0000 {rng.randint(1000, 9999)} FICT"}
    grids = {}
    for cid, fams in CLIENT_FORWARDERS.items():
        for fam in fams:
            grids[(cid, fam)] = make_grid(rng_for(seed, "grid", cid, fam), cid, fam, forwarders[fam])
    return {"clients": clients, "tiers": tiers, "forwarders": forwarders, "grids": grids}


# Libellés de prestations par langue ; le premier est le libellé imprimé par défaut
LABELS = {
    "fr": {
        "debours_droits": ["Droits de douane", "Droits de douane (A00)"],
        "debours_autres_taxes": ["Droits antidumping", "Autres taxes douanières"],
        "debours_tva": ["TVA à l'importation", "TVA import"],
        "debours_combines": ["Droits et taxes", "Droits & taxes acquittés"],
        "debours_forfait_petits_envois": ["Droit forfaitaire petits envois", "Forfait douane par article"],
        "frais_dedouanement": ["Frais de dédouanement", "Établissement déclaration import"],
        "frais_avance_fonds": ["Frais d'avance de fonds", "Commission d'avance de fonds"],
        "frais_ligne_supplementaire": ["Article supplémentaire", "Lignes supplémentaires"],
        "magasinage": ["Magasinage", "Frais de magasinage"],
        "transport": ["Livraison", "Transport aéroport - entrepôt"],
        "manutention": ["Manutention", "Frais de manutention"],
        "surcharge": ["Surcharge sûreté", "Surcharge carburant"],
        "autre_prestation": ["Frais de dossier", "Ouverture de dossier"],
    },
    "en": {
        "debours_droits": ["Customs duty", "Import duty"],
        "debours_autres_taxes": ["Anti-dumping duty", "Other customs taxes"],
        "debours_tva": ["Import VAT", "VAT on import"],
        "debours_combines": ["Duties and taxes", "Duty & tax paid"],
        "debours_forfait_petits_envois": ["Flat-rate duty per item", "Low value flat duty"],
        "frais_dedouanement": ["Customs clearance", "Import entry fee"],
        "frais_avance_fonds": ["Disbursement fee", "Duty advance fee"],
        "frais_ligne_supplementaire": ["Additional entry lines", "Extra tariff lines"],
        "magasinage": ["Storage", "Warehouse storage"],
        "transport": ["Delivery", "Collection & delivery"],
        "manutention": ["Handling", "Terminal handling"],
        "surcharge": ["Security surcharge", "Fuel surcharge"],
        "autre_prestation": ["File opening fee", "Documentation fee"],
    },
    "de": {
        "debours_droits": ["Zollabgaben", "Zoll (A00)"],
        "debours_autres_taxes": ["Antidumpingzoll", "Sonstige Abgaben"],
        "debours_tva": ["Einfuhrumsatzsteuer", "EUSt"],
        "debours_combines": ["Zölle und Steuern", "Abgaben gesamt"],
        "debours_forfait_petits_envois": ["Pauschalzoll Kleinsendungen", "Pauschalzoll je Artikel"],
        "frais_dedouanement": ["Verzollung", "Zollabfertigung Import"],
        "frais_avance_fonds": ["Vorlageprovision", "Auslagenprovision"],
        "frais_ligne_supplementaire": ["Zusätzliche Positionen", "Zusatzpositionen"],
        "magasinage": ["Lagergeld", "Lagerung"],
        "transport": ["Zustellung", "Transport Flughafen - Lager"],
        "manutention": ["Umschlag", "Handling"],
        "surcharge": ["Sicherheitszuschlag", "Treibstoffzuschlag"],
        "autre_prestation": ["Bearbeitungsgebühr", "Dossiergebühr"],
    },
    "it": {
        "debours_droits": ["Dazi doganali", "Dazio (A00)"],
        "debours_autres_taxes": ["Dazio antidumping", "Altri diritti"],
        "debours_tva": ["IVA all'importazione", "IVA import"],
        "debours_combines": ["Diritti e tasse", "Dazi e IVA"],
        "debours_forfait_petits_envois": ["Dazio forfettario piccole spedizioni", "Dazio forfettario per articolo"],
        "frais_dedouanement": ["Spese di sdoganamento", "Operazione doganale import"],
        "frais_avance_fonds": ["Commissione anticipo diritti", "Anticipo diritti"],
        "frais_ligne_supplementaire": ["Voci doganali aggiuntive", "Righe supplementari"],
        "magasinage": ["Magazzinaggio", "Sosta in magazzino"],
        "transport": ["Consegna", "Trasporto aeroporto - magazzino"],
        "manutention": ["Movimentazione", "Handling"],
        "surcharge": ["Supplemento sicurezza", "Supplemento carburante"],
        "autre_prestation": ["Spese di pratica", "Apertura pratica"],
    },
    "es": {
        "debours_droits": ["Aranceles", "Derechos de aduana"],
        "debours_autres_taxes": ["Derechos antidumping", "Otros tributos"],
        "debours_tva": ["IVA de importación", "IVA importación"],
        "debours_combines": ["Derechos e impuestos", "Tributos aduaneros"],
        "debours_forfait_petits_envois": ["Derecho fijo pequeños envíos", "Derecho fijo por artículo"],
        "frais_dedouanement": ["Despacho de aduanas", "Despacho de importación"],
        "frais_avance_fonds": ["Comisión por anticipo", "Anticipo de tributos"],
        "frais_ligne_supplementaire": ["Partidas adicionales", "Líneas adicionales"],
        "magasinage": ["Almacenaje", "Almacenaje en depósito"],
        "transport": ["Entrega", "Transporte aeropuerto - almacén"],
        "manutention": ["Manipulación", "Manipulación de carga"],
        "surcharge": ["Recargo de seguridad", "Recargo combustible"],
        "autre_prestation": ["Gastos de expediente", "Apertura de expediente"],
    },
    "nl": {
        "debours_droits": ["Invoerrechten", "Douanerechten"],
        "debours_autres_taxes": ["Antidumpingrechten", "Overige heffingen"],
        "debours_tva": ["Btw bij invoer", "Invoer-btw"],
        "debours_combines": ["Rechten en belastingen", "Heffingen totaal"],
        "debours_forfait_petits_envois": ["Forfaitair recht kleine zendingen", "Forfaitair recht per artikel"],
        "frais_dedouanement": ["Inklaring", "Invoeraangifte"],
        "frais_avance_fonds": ["Voorschotprovisie", "Provisie voorschot"],
        "frais_ligne_supplementaire": ["Extra aangifteregels", "Aanvullende regels"],
        "magasinage": ["Opslag", "Opslagkosten"],
        "transport": ["Bezorging", "Transport luchthaven - magazijn"],
        "manutention": ["Behandeling", "Handling"],
        "surcharge": ["Veiligheidstoeslag", "Brandstoftoeslag"],
        "autre_prestation": ["Dossierkosten", "Administratiekosten"],
    },
}

# Libellés de surcharge ABSENTS de toute grille (injection D7)
SURCHARGES_HORS_GRILLE = {
    "fr": "Surcharge haute saison", "en": "Peak season surcharge", "de": "Hochsaisonzuschlag",
    "it": "Supplemento alta stagione", "es": "Recargo temporada alta", "nl": "Piekseizoentoeslag",
}
# Prestations ABSENTES de toute grille (injection D2)
PRESTATIONS_HORS_GRILLE = {
    "fr": ["Frais de télétransmission", "Frais d'archivage", "Contrôle documentaire"],
    "en": ["Electronic transmission fee", "Archiving fee", "Document check fee"],
    "de": ["Übermittlungsgebühr", "Archivierungsgebühr", "Dokumentenprüfung"],
    "it": ["Spese di trasmissione", "Spese di archiviazione", "Verifica documentale"],
    "es": ["Gastos de transmisión", "Gastos de archivo", "Revisión documental"],
    "nl": ["Transmissiekosten", "Archiveringskosten", "Documentcontrole"],
}
# Remise (ligne négative, famille G6)
REMISE = {"fr": "Remise commerciale", "en": "Commercial discount", "de": "Rabatt", "it": "Sconto", "es": "Descuento", "nl": "Korting"}


def fam_lang(fam: str) -> str:
    lang = FORWARDERS_DEF[fam]["lang"]
    return "fr" if lang == "fr_en" else lang


def make_grid(rng, cid: str, fam: str, fwd: dict) -> dict:
    lang = fam_lang(fam)
    lab = LABELS[lang]
    labs_fr = LABELS["fr"]

    def labels(nature):
        out = list(lab[nature])
        if lang != "fr":
            out += [x for x in labs_fr[nature] if x not in out]
        if FORWARDERS_DEF[fam]["lang"] == "fr_en":
            out += [x for x in LABELS["en"][nature] if x not in out]
        return out

    pct = D(rng.choice(["1.5", "2", "2.5", "3"]))
    postes = [
        {"code_poste": "DEDOU", "nature": "frais_dedouanement", "libelles_reconnus": labels("frais_dedouanement"),
         "mode": "forfait", "prix": str(D(rng.choice([45, 55, 59, 65, 72, 85, 95])).quantize(D("0.01"))), "unite_base": "declaration",
         "pourcentage": None, "base_pourcentage": None, "minimum": None, "maximum": None,
         "franchise_jours": None, "inclus": None, "devise": "EUR"},
        {"code_poste": "LIGSUP", "nature": "frais_ligne_supplementaire", "libelles_reconnus": labels("frais_ligne_supplementaire"),
         "mode": "unitaire", "prix": str(D(rng.choice(["6", "7.5", "8", "9", "12"])).quantize(D("0.01"))), "unite_base": "article",
         "pourcentage": None, "base_pourcentage": None, "minimum": None, "maximum": None,
         "franchise_jours": None, "inclus": rng.choice([2, 3, 4, 5]), "devise": "EUR"},
        {"code_poste": "FAF", "nature": "frais_avance_fonds", "libelles_reconnus": labels("frais_avance_fonds"),
         "mode": "pourcentage", "prix": None, "unite_base": None, "pourcentage": str(pct),
         "base_pourcentage": rng.choice(["debours_total", "debours_total", "debours_hors_tva"]),
         "minimum": str(D(rng.choice([15, 18, 20, 25, 30])).quantize(D("0.01"))),
         "maximum": rng.choice([None, "250.00", "400.00"]), "franchise_jours": None, "inclus": None, "devise": "EUR"},
        {"code_poste": "MAG", "nature": "magasinage", "libelles_reconnus": labels("magasinage"),
         "mode": "par_jour", "prix": str(D(rng.choice(["8", "10", "12.5", "15", "18"])).quantize(D("0.01"))), "unite_base": "jour",
         "pourcentage": None, "base_pourcentage": None, "minimum": None, "maximum": None,
         "franchise_jours": rng.choice([2, 3, 4, 5]), "inclus": None, "devise": "EUR"},
        {"code_poste": "LIV", "nature": "transport", "libelles_reconnus": labels("transport"),
         "mode": "forfait", "prix": str(D(rng.choice([75, 90, 110, 135, 160])).quantize(D("0.01"))), "unite_base": "envoi",
         "pourcentage": None, "base_pourcentage": None, "minimum": None, "maximum": None,
         "franchise_jours": None, "inclus": None, "devise": "EUR"},
        {"code_poste": "DOSS", "nature": "autre_prestation", "libelles_reconnus": labels("autre_prestation"),
         "mode": "forfait", "prix": str(D(rng.choice([10, 12, 15, 20, 25])).quantize(D("0.01"))), "unite_base": "dossier",
         "pourcentage": None, "base_pourcentage": None, "minimum": None, "maximum": None,
         "franchise_jours": None, "inclus": None, "devise": "EUR"},
    ]
    if rng.random() < 0.7:
        postes.append({"code_poste": "MANUT", "nature": "manutention", "libelles_reconnus": labels("manutention"),
                       "mode": "forfait", "prix": str(D(rng.choice([18, 25, 32, 40])).quantize(D("0.01"))), "unite_base": "envoi",
                       "pourcentage": None, "base_pourcentage": None, "minimum": None, "maximum": None,
                       "franchise_jours": None, "inclus": None, "devise": "EUR"})
    if rng.random() < 0.6:
        postes.append({"code_poste": "SURSEC", "nature": "surcharge", "libelles_reconnus": [lab["surcharge"][0]] + ([labs_fr["surcharge"][0]] if lang != "fr" else []),
                       "mode": "forfait", "prix": str(D(rng.choice(["5", "7.5", "9", "12"])).quantize(D("0.01"))), "unite_base": "envoi",
                       "pourcentage": None, "base_pourcentage": None, "minimum": None, "maximum": None,
                       "franchise_jours": None, "inclus": None, "devise": "EUR"})
    return {
        "schema": "controldone.bench.grille/1.0.0",
        "grille_id": f"GR-{cid}-{fam}",
        "client_id": cid,
        "transitaire_id": fwd["transitaire_id"],
        "transitaire_nom": fwd["nom"],
        "reference": f"DEVIS-{fam}-{cid}-2026-{rng.randint(100, 999)}",
        "valide_du": "2026-01-01",
        "valide_au": "2026-12-31",
        "statut": "validee",
        "devise": "EUR",
        "prestations_hors_grille": rng.choice(["interdites", "interdites", "tolerees"]),
        "postes": postes,
        "preuve": {"document": f"devis_{fam}_{cid}.pdf (FICTIF)", "page": 1},
        "mention": "DONNÉES FICTIVES — grille tarifaire de test",
    }


def poste(grid: dict, nature: str) -> dict | None:
    for p in grid["postes"]:
        if p["nature"] == nature:
            return p
    return None
