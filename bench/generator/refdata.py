"""Données de référence fictives : produits, vendeurs, devises, transitaires, clients.

Tous les noms de sociétés, adresses et numéros sont inventés. Les codes du système
harmonisé (6 premiers chiffres) sont des positions publiques choisies pour la vraisemblance ;
les compléments à 8/10 chiffres et les taux imprimés sont fictifs.
"""

from __future__ import annotations

from dataclasses import dataclass, field

FICTIF = "(FICTIF)"


@dataclass(frozen=True)
class Product:
    key: str
    en: str
    fr: str
    es: str
    hs10: str
    unit: str  # C62, PR, KGM, LTR, MTR
    price: tuple  # (min, max) par unité, en USD équivalent
    kg: float  # masse nette par unité
    duty: str  # taux droit A00 en %
    other: tuple | None = None  # (code, libelle, nature, taux, unite_base)


PRODUCTS = [
    Product("laptop", "Laptop computer 14in", "Ordinateur portable 14 pouces", "Ordenador portátil 14 pulgadas", "8471300000", "C62", (310, 820), 1.6, "0"),
    Product("monitor", "LCD monitor 27in", "Moniteur LCD 27 pouces", "Monitor LCD 27 pulgadas", "8528521000", "C62", (95, 260), 5.2, "0"),
    Product("router", "Network switch 24 ports", "Commutateur réseau 24 ports", "Conmutador de red 24 puertos", "8517620090", "C62", (60, 190), 2.1, "0"),
    Product("psu", "Switching power supply 65W", "Alimentation à découpage 65 W", "Fuente de alimentación 65 W", "8504408290", "C62", (4, 14), 0.25, "3.3"),
    Product("cable", "Insulated copper cable 3G1.5", "Câble cuivre isolé 3G1,5", "Cable de cobre aislado", "8544429000", "MTR", (0.4, 1.6), 0.12, "3.7"),
    Product("lamp", "LED desk lamp", "Lampe de bureau LED", "Lámpara de escritorio LED", "9405420090", "C62", (6, 22), 0.9, "4.7"),
    Product("fan", "Table fan 40cm", "Ventilateur de table 40 cm", "Ventilador de mesa 40 cm", "8414510000", "C62", (9, 28), 2.6, "3.2"),
    Product("drill", "Cordless drill 18V", "Perceuse sans fil 18 V", "Taladro inalámbrico 18 V", "8467210000", "C62", (18, 65), 1.7, "2.7"),
    Product("screws", "Steel hex screws M8", "Vis acier tête hexagonale M8", "Tornillos de acero M8", "7318159590", "KGM", (1.8, 3.9), 1.0, "3.7",
            ("A30", "Droit antidumping", "autre_taxe", "22.3", None)),
    Product("valve", "Brass ball valve DN25", "Vanne à boisseau laiton DN25", "Válvula de bola latón", "8481808590", "C62", (5, 19), 0.6, "2.2"),
    Product("pump", "Centrifugal pump 0.75kW", "Pompe centrifuge 0,75 kW", "Bomba centrífuga 0,75 kW", "8413702100", "C62", (70, 240), 11.5, "1.7"),
    Product("motor", "Electric motor 1.1kW", "Moteur électrique 1,1 kW", "Motor eléctrico 1,1 kW", "8501520090", "C62", (55, 160), 9.8, "2.7"),
    Product("switch", "Rotary switch 16A", "Commutateur rotatif 16 A", "Interruptor rotativo 16 A", "8536508090", "C62", (1.2, 6), 0.08, "2.3"),
    Product("tshirt", "Cotton T-shirt", "T-shirt coton", "Camiseta de algodón", "6109100010", "C62", (1.8, 6.5), 0.18, "12"),
    Product("trousers", "Women's trousers, synthetic", "Pantalon femme synthétique", "Pantalón de mujer sintético", "6204630000", "C62", (5, 18), 0.4, "12"),
    Product("shoes", "Leather shoes", "Chaussures cuir", "Zapatos de cuero", "6403999800", "PR", (12, 45), 0.9, "8"),
    Product("bag", "Handbag, textile outer", "Sac à main extérieur textile", "Bolso de mano textil", "4202929800", "C62", (6, 25), 0.5, "2.7"),
    Product("towel", "Terry towel 50x100", "Serviette éponge 50x100", "Toalla de rizo 50x100", "6302600000", "C62", (1.5, 4.5), 0.35, "12"),
    Product("fabric", "Woven cotton fabric 150cm", "Tissu coton tissé 150 cm", "Tejido de algodón 150 cm", "5208520000", "MTR", (1.1, 3.8), 0.16, "8"),
    Product("hat", "Knitted hat", "Bonnet tricoté", "Gorro de punto", "6505009000", "C62", (0.9, 3.5), 0.08, "2.7"),
    Product("cream", "Face cream 50ml", "Crème visage 50 ml", "Crema facial 50 ml", "3304990000", "C62", (1.2, 6.8), 0.07, "0"),
    Product("shampoo", "Shampoo 250ml", "Shampooing 250 ml", "Champú 250 ml", "3305100000", "C62", (0.8, 3.2), 0.28, "0"),
    Product("soap", "Toilet soap 100g", "Savon de toilette 100 g", "Jabón de tocador 100 g", "3401110000", "C62", (0.3, 1.2), 0.1, "0"),
    Product("perfume", "Eau de toilette 100ml", "Eau de toilette 100 ml", "Agua de colonia 100 ml", "3303009000", "C62", (4, 16), 0.32, "0"),
    Product("tableware", "Porcelain dinner plate", "Assiette en porcelaine", "Plato de porcelana", "6911100000", "C62", (0.9, 3.8), 0.55, "12",
            ("A30", "Droit antidumping", "autre_taxe", "17.9", None)),
    Product("glass", "Drinking glass 30cl", "Verre à boire 30 cl", "Vaso 30 cl", "7013499900", "C62", (0.4, 1.6), 0.25, "11"),
    Product("knife", "Kitchen knife stainless", "Couteau de cuisine inox", "Cuchillo de cocina inox", "8211910000", "C62", (1.5, 7), 0.15, "8.5"),
    Product("pan", "Stainless steel saucepan", "Casserole inox", "Cacerola de acero inoxidable", "7323930090", "C62", (4, 14), 1.1, "3.2"),
    Product("blender", "Kitchen blender 600W", "Blender de cuisine 600 W", "Licuadora 600 W", "8509400000", "C62", (12, 38), 2.4, "2.2"),
    Product("chair", "Office chair, metal frame", "Chaise de bureau structure métal", "Silla de oficina", "9401710000", "C62", (25, 90), 12.0, "0"),
    Product("shelf", "Wooden shelf unit", "Étagère en bois", "Estantería de madera", "9403609090", "C62", (18, 70), 14.0, "0"),
    Product("toy", "Plastic construction toy", "Jouet de construction plastique", "Juguete de construcción", "9503007000", "C62", (2, 11), 0.45, "4.7"),
    Product("watch", "Wrist watch, quartz", "Montre-bracelet à quartz", "Reloj de pulsera de cuarzo", "9102110000", "C62", (6, 40), 0.06, "4.5"),
    Product("jewel", "Imitation jewellery necklace", "Collier bijouterie fantaisie", "Collar de bisutería", "7117190000", "C62", (0.8, 5), 0.03, "4"),
    Product("box", "Plastic storage box", "Boîte de rangement plastique", "Caja de almacenamiento", "3923100090", "C62", (0.7, 3.4), 0.35, "6.5"),
    Product("carton", "Corrugated carton box", "Carton ondulé", "Caja de cartón ondulado", "4819100000", "C62", (0.2, 0.9), 0.3, "0"),
    Product("printer", "Laser printer A4", "Imprimante laser A4", "Impresora láser A4", "8443321000", "C62", (60, 180), 8.0, "0"),
    Product("autopart", "Brake disc 280mm", "Disque de frein 280 mm", "Disco de freno 280 mm", "8708309100", "C62", (9, 32), 4.6, "4.5"),
    Product("juice", "Fruit juice drink 1L", "Boisson au jus de fruits 1 L", "Bebida de zumo 1 L", "2202999900", "LTR", (0.5, 1.4), 1.05, "9.6",
            ("X01", "Droit spécifique boissons (fictif)", "autre_taxe", "0.35", "LTR")),
    Product("oliveoil", "Olive oil 1L bottle", "Huile d'olive 1 L", "Aceite de oliva 1 L", "1509200000", "LTR", (3.5, 7.5), 0.92, "0",
            ("X01", "Droit spécifique (fictif)", "autre_taxe", "0.12", "LTR")),
    Product("bike", "Bicycle frame, aluminium", "Cadre de vélo aluminium", "Cuadro de bicicleta", "8714911090", "C62", (22, 75), 2.1, "4.7",
            ("A35", "Droit antidumping provisoire", "autre_taxe", "48.5", None)),
]

PRODUCTS_BY_KEY = {p.key: p for p in PRODUCTS}
SMALL_PARCEL_PRODUCTS = ["tshirt", "hat", "jewel", "watch", "cream", "perfume", "toy", "bag", "knife", "lamp", "psu", "shoes"]
OTHER_TAX_PRODUCTS = [p.key for p in PRODUCTS if p.other]
UNIT_LABELS = {
    "en": {"C62": "pcs", "PR": "pairs", "KGM": "kg", "LTR": "L", "MTR": "m"},
    "fr": {"C62": "pce", "PR": "paires", "KGM": "kg", "LTR": "l", "MTR": "m"},
    "es": {"C62": "uds", "PR": "pares", "KGM": "kg", "LTR": "l", "MTR": "m"},
}

# Taux de référence fictifs (unités de devise pour 1 EUR) — ordre de grandeur réaliste.
REF_RATES = {"USD": "1.1250", "CNY": "8.0600", "GBP": "0.8600", "JPY": "168.20", "KRW": "1545.0",
             "CHF": "0.9400", "INR": "96.300", "TRY": "44.100", "CAD": "1.5450"}
VOLATILE = {"TRY"}


@dataclass(frozen=True)
class Seller:
    key: str
    name: str
    addr: tuple
    country: str
    lang: str
    currencies: tuple
    numstyle: str
    vat: str | None = None


SELLERS = [
    Seller("szde", "Shenzhen Demo Electronics Co., Ltd. (FICTITIOUS)", ("No. 0 Example Road, Demo Industrial Park", "Fictional District, Shenzhen 518000"), "CN", "en", ("USD", "CNY", "USD"), "en"),
    Seller("ningbo", "Ningbo Sample Hardware Manufacturing Co. (FICTITIOUS)", ("Unit 9, Imaginary Tech Zone", "Ningbo 315000"), "CN", "en", ("USD", "EUR", "CNY"), "en"),
    Seller("yiwu", "Yiwu Mock Trading Co., Ltd. (FICTITIOUS)", ("Block Z, Placeholder Market Street", "Yiwu 322000"), "CN", "en", ("USD", "EUR"), "en"),
    Seller("guangzhou", "Guangzhou Test Textiles Co. (FICTITIOUS)", ("88 Nowhere Avenue", "Guangzhou 510000"), "CN", "en", ("USD", "CNY"), "en"),
    Seller("pacific", "Pacific Sample Trading Inc. (FICTITIOUS)", ("1200 Imaginary Blvd, Suite 0", "Testville, CA 90000"), "US", "en", ("USD",), "en", "US-EIN 00-0000000"),
    Seller("lakes", "Great Lakes Demo Tools LLC (FICTITIOUS)", ("45 Placeholder Street", "Demotown, OH 43000"), "US", "en", ("USD",), "en"),
    Seller("thames", "Thames Mock Supplies Ltd (FICTITIOUS)", ("Unit 0, Fictional Business Park", "Sampleford, AB1 2CD"), "GB", "en", ("GBP", "EUR"), "en", "GB000000000"),
    Seller("osaka", "Osaka Dummy Precision K.K. (FICTITIOUS)", ("0-0-0 Kasou-cho", "Demo-ku, Osaka 530-0000"), "JP", "en", ("JPY",), "en"),
    Seller("busan", "Busan Example Industries Co. (FICTITIOUS)", ("00 Gasang-ro", "Haeundae-gu, Busan 48000"), "KR", "en", ("KRW",), "en"),
    Seller("mumbai", "Mumbai Placeholder Exports Pvt Ltd (FICTITIOUS)", ("Plot 0, Imaginary MIDC", "Mumbai 400000"), "IN", "en", ("USD", "INR"), "en"),
    Seller("izmir", "Izmir Ornek Tekstil A.S. (FICTITIOUS)", ("Hayali Cad. No:0", "Izmir 35000"), "TR", "en", ("EUR", "USD", "TRY"), "en"),
    Seller("hanoi", "Hanoi Sample Garment JSC (FICTITIOUS)", ("Lot 0, Demo Industrial Zone", "Hanoi 100000"), "VN", "en", ("USD",), "en"),
    Seller("geneve", "Atelier Démo Léman SA (FICTIF)", ("Chemin Imaginaire 0", "1200 Genève-Fictif"), "CH", "fr", ("CHF", "EUR"), "ch", "CHE-000.000.000 TVA"),
    Seller("casa", "Société Exemple Atlas SARL (FICTIF)", ("Zone industrielle Fictive, lot 0", "Casablanca-Démo 20000"), "MA", "fr", ("EUR",), "frs"),
    Seller("tunis", "Méditerranée Test Confection (FICTIF)", ("Rue de l'Exemple 0", "Tunis-Démo 1000"), "TN", "fr", ("EUR",), "fr"),
    Seller("montreal", "Fournitures Démo Saint-Laurent inc. (FICTIF)", ("0, boulevard Imaginaire", "Montréal-Fictif QC H0H 0H0"), "CA", "fr", ("CAD", "USD"), "frs"),
    Seller("mexico", "Distribuidora Ficticia del Norte S.A. de C.V. (FICTICIO)", ("Calle Imaginaria 0", "Monterrey-Demo, N.L. 64000"), "MX", "es", ("USD",), "en"),
    Seller("santiago", "Exportadora Ejemplo Andina SpA (FICTICIO)", ("Avenida Ficticia 0", "Santiago-Demo 8320000"), "CL", "es", ("USD",), "de"),
    Seller("bogota", "Comercializadora Muestra Ltda. (FICTICIO)", ("Carrera 0 # 00-00", "Bogotá-Demo 110111"), "CO", "es", ("USD", "EUR"), "de"),
]
SELLERS_BY_KEY = {s.key: s for s in SELLERS}

CARRIERS = [
    "Express Démo Kilo (FICTIF)",
    "Fret Aérien Démo Lima (FICTIF)",
    "Navale Démo Mike Lines (FICTIF)",
    "Messagerie Démo November (FICTIF)",
]

# Huit transitaires fictifs, un par gabarit T1–T8 (SPEC §19.6).
FORWARDERS = [
    # (transitaire_id, template, nom, ville, préfixe facture, langue)
    ("TR01", "T1", "Transitaire Démo Alpha SAS (FICTIF)", "Villefictive-Port", "FA", "fr"),
    ("TR02", "T2", "Transitaire Démo Bravo Logistics (FICTIF)", "Roissy-Démo", "INV", "en"),
    ("TR03", "T3", "Transitaire Démo Charlie Douane (FICTIF)", "Le Havre-Fictif", "F", "fr"),
    ("TR04", "T4", "Transitaire Démo Delta Fret (FICTIF)", "Lyon-Exemple", "REL", "fr"),
    ("TR05", "T5", "Transitaire Démo Echo Transit (FICTIF)", "Marseille-Démo", "FD", "fr"),
    ("TR06", "T6", "Transitaire Démo Foxtrot Services (FICTIF)", "Lille-Fictif", "FAC", "fr"),
    ("TR07", "T7", "Transitaire Démo Golf Numérique (FICTIF)", "Nantes-Exemple", "FX", "fr"),
    ("TR08", "T8", "Transitaire Démo Hotel International (FICTIF)", "Strasbourg-Démo", "FB", "fr_en"),
]
TEMPLATE_TO_FORWARDER = {f[1]: f[0] for f in FORWARDERS}

# Clients fictifs. CL01 est un groupe à trois entités.
CLIENTS = [
    {
        "client_id": "CL01",
        "groupe": "Groupe Démo Lumen (FICTIF)",
        "entites": [
            ("Lumen Industrie SAS (FICTIF)", ["LUMEN INDUSTRIE", "LUMEN IND"], ("18 rue Imaginaire", "69999 Villefictive")),
            ("Lumen Distribution SARL (FICTIF)", ["LUMEN DISTRIBUTION", "LUMEN DISTRI"], ("ZA du Banc d'Essai, 4 allée du Test", "69998 Villefictive-Est")),
            ("Lumen Atelier SAS (FICTIF)", ["LUMEN ATELIER"], ("2 impasse de l'Exemple", "38999 Saint-Démo-sur-Test")),
        ],
        "templates": ["T1", "T2", "T4", "T6", "T7"],
    },
    {
        "client_id": "CL02",
        "groupe": None,
        "entites": [("Brindille Cosmétiques SAS (FICTIF)", ["BRINDILLE", "BRINDILLE COSMETIQUES"], ("7 chemin des Échantillons", "13999 Aix-Fictive"))],
        "templates": ["T2", "T3", "T5", "T8"],
    },
    {
        "client_id": "CL03",
        "groupe": None,
        "entites": [("Cap Horizon Outillage SARL (FICTIF)", ["CAP HORIZON", "CAP HORIZON OUTILLAGE"], ("33 route du Prototype", "44999 Nantes-Démo"))],
        "templates": ["T1", "T3", "T6", "T7"],
    },
    {
        "client_id": "CL04",
        "groupe": None,
        "entites": [("Maison Vellum Textile SAS (FICTIF)", ["VELLUM", "MAISON VELLUM"], ("5 quai de la Maquette", "59999 Roubaix-Fictif"))],
        "templates": ["T2", "T4", "T5", "T6", "T8"],
    },
]

THIRD_PARTY = ("Société Tierce Démo Omega SA (FICTIF)", ("1 place du Hors-Champ", "75999 Paris-Fictif"))
