"""Pays : noms courants (fr, en, es) et codes -> ISO 3166-1 alpha-2 (SPEC §5.2)."""

from __future__ import annotations

import re

from controldone.normalize.text import cle_texte

__all__ = ["ISO2", "country_to_iso2"]

ISO2: frozenset[str] = frozenset(
    """
    AD AE AF AG AI AL AM AO AQ AR AS AT AU AW AX AZ BA BB BD BE BF BG BH BI BJ BL BM BN BO BQ BR BS BT BV
    BW BY BZ CA CC CD CF CG CH CI CK CL CM CN CO CR CU CV CW CX CY CZ DE DJ DK DM DO DZ EC EE EG EH ER ES
    ET FI FJ FK FM FO FR GA GB GD GE GF GG GH GI GL GM GN GP GQ GR GS GT GU GW GY HK HM HN HR HT HU ID IE
    IL IM IN IO IQ IR IS IT JE JM JO JP KE KG KH KI KM KN KP KR KW KY KZ LA LB LC LI LK LR LS LT LU LV LY
    MA MC MD ME MF MG MH MK ML MM MN MO MP MQ MR MS MT MU MV MW MX MY MZ NA NC NE NF NG NI NL NO NP NR NU
    NZ OM PA PE PF PG PH PK PL PM PN PR PS PT PW PY QA RE RO RS RU RW SA SB SC SD SE SG SH SI SJ SK SL SM
    SN SO SR SS ST SV SX SY SZ TC TD TF TG TH TJ TK TL TM TN TO TR TT TV TW TZ UA UG UM US UY UZ VA VC VE
    VG VI VN VU WF WS XK YE YT ZA ZM ZW
    """.split()
)

# CODE: noms fr ; en ; es (et variantes), séparés par « | »
_NOMS = """
AE: emirats arabes unis | united arab emirates | uae | emiratos arabes unidos
AR: argentine | argentina
AT: autriche | austria
AU: australie | australia
BD: bangladesh
BE: belgique | belgium | belgica
BG: bulgarie | bulgaria
BR: bresil | brazil | brasil
CA: canada | canada
CH: suisse | switzerland | suiza
CL: chili | chile
CN: chine | china | people's republic of china | prc | republique populaire de chine
CO: colombie | colombia
CY: chypre | cyprus | chipre
CZ: republique tcheque | tchequie | czech republic | czechia | republica checa
DE: allemagne | germany | alemania
DK: danemark | denmark | dinamarca
DZ: algerie | algeria | argelia
EE: estonie | estonia
EG: egypte | egypt | egipto
ES: espagne | spain | espana
FI: finlande | finland | finlandia
FR: france | francia
GB: royaume-uni | royaume uni | united kingdom | uk | great britain | grande-bretagne | england | angleterre | reino unido
GR: grece | greece | grecia
HK: hong kong | hong-kong | hongkong
HR: croatie | croatia | croacia
HU: hongrie | hungary | hungria
ID: indonesie | indonesia
IE: irlande | ireland | irlanda
IL: israel
IN: inde | india
IR: iran
IS: islande | iceland | islandia
IT: italie | italy | italia
JP: japon | japan
KH: cambodge | cambodia | camboya
KR: coree du sud | republique de coree | south korea | korea | republic of korea | corea del sur
LK: sri lanka
LT: lituanie | lithuania | lituania
LU: luxembourg | luxemburgo
LV: lettonie | latvia | letonia
MA: maroc | morocco | marruecos
MT: malte | malta
MX: mexique | mexico
MY: malaisie | malaysia | malasia
NL: pays-bas | pays bas | hollande | netherlands | the netherlands | holland | paises bajos | holanda
NO: norvege | norway | noruega
NZ: nouvelle-zelande | nouvelle zelande | new zealand | nueva zelanda
PE: perou | peru
PH: philippines | filipinas
PK: pakistan | pakistan
PL: pologne | poland | polonia
PT: portugal
RO: roumanie | romania | rumania
RS: serbie | serbia
RU: russie | russia | russian federation | federation de russie | rusia
SA: arabie saoudite | saudi arabia | arabia saudita
SE: suede | sweden | suecia
SG: singapour | singapore | singapur
SI: slovenie | slovenia | eslovenia
SK: slovaquie | slovakia | eslovaquia
TH: thailande | thailand | tailandia
TN: tunisie | tunisia | tunez
TR: turquie | turkey | turkiye | turquia
TW: taiwan | taiwan, province of china | chinese taipei
UA: ukraine | ucrania
US: etats-unis | etats unis | etats-unis d'amerique | usa | u.s.a. | united states | united states of america | us | estados unidos | eeuu | ee.uu.
VN: vietnam | viet nam
ZA: afrique du sud | south africa | sudafrica
"""

_INDEX: dict[str, str] = {}
for _ligne in _NOMS.strip().splitlines():
    _code, _, _noms = _ligne.partition(":")
    for _n in _noms.split("|"):
        _INDEX[cle_texte(_n)] = _code.strip()

_ISO3: dict[str, str] = {
    "FRA": "FR", "DEU": "DE", "ESP": "ES", "ITA": "IT", "GBR": "GB", "USA": "US", "CHN": "CN", "JPN": "JP",
    "KOR": "KR", "IND": "IN", "VNM": "VN", "TWN": "TW", "HKG": "HK", "THA": "TH", "TUR": "TR", "BEL": "BE",
    "NLD": "NL", "CHE": "CH", "PRT": "PT", "POL": "PL", "MAR": "MA", "TUN": "TN", "BRA": "BR", "MEX": "MX",
    "CAN": "CA", "AUS": "AU", "BGD": "BD", "PAK": "PK", "IDN": "ID", "MYS": "MY", "SGP": "SG", "LKA": "LK",
}


def country_to_iso2(texte: str | None) -> str | None:
    """Code ISO 3166-1 alpha-2 d'un nom de pays (fr/en/es), d'un code ISO2 ou ISO3. ``None`` sinon.

    >>> country_to_iso2("Chine")
    'CN'
    >>> country_to_iso2("Estados Unidos")
    'US'
    """
    if not texte:
        return None
    brut = texte.strip()
    if re.fullmatch(r"[A-Za-z]{2}", brut) and brut.upper() in ISO2:
        return brut.upper()
    if re.fullmatch(r"[A-Z]{3}", brut) and brut in _ISO3:
        return _ISO3[brut]
    cle = cle_texte(brut).strip(" .,;:()")
    cle = re.sub(r"^(?:made in|origin|origine|pays d'origine|country of origin|pais de origen)\s*:?\s*", "", cle)
    if cle in _INDEX:
        return _INDEX[cle]
    sans_article = re.sub(r"^(?:the|la|le|les|l'|el|los|las)\s+", "", cle)
    return _INDEX.get(sans_article)
