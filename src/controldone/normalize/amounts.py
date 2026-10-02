"""Lecture des nombres et montants imprimés (SPEC §5.2, §5.3.1 « Formats numériques »).

Formats reconnus : ``1.234,56`` ; ``1,234.56`` ; ``1 234,56`` (espace normale, insécable ou fine) ;
``1'234.56`` ; ``1,250,000`` (devise sans décimales) ; signe moins (avant ou après), parenthèses
(``(1 234,56)``) -> valeur absolue + ``negatif=True`` ; symbole ou code de devise avant ou après.

Ambiguïté : un seul séparateur suivi d'exactement 3 chiffres (``1,234`` / ``1.234``) est lu comme
séparateur de **milliers** sauf indication contraire (``separateur_decimal``) ; le résultat porte alors
``ambigu=True`` pour que l'extracteur baisse sa confiance.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from controldone.normalize.currency import DEVISE_INCONNUE, DEVISES_SANS_DECIMALES, normalize_currency

__all__ = ["MontantLu", "NombreLu", "parse_amount", "parse_decimal", "parse_int", "parse_nombre"]

_SEP_GROUPE = "       '’"
_NOMBRE_RE = re.compile(r"\d(?:[\d.,'’       ]*\d)?")
_MOINS = "-−–"


@dataclass(frozen=True, slots=True)
class NombreLu:
    valeur: Decimal  # valeur absolue
    negatif: bool
    ambigu: bool
    texte: str  # sous-chaîne numérique retenue


@dataclass(frozen=True, slots=True)
class MontantLu:
    """Montant lu : ``valeur`` toujours positive ou nulle ; ``negatif`` reflète le signe imprimé."""

    valeur: Decimal
    negatif: bool
    devise: str | None
    ambigu: bool
    brut: str

    @property
    def valeur_signee(self) -> Decimal:
        return -self.valeur if self.negatif else self.valeur


def _groupes_milliers_valides(partie_entiere: str, sep: str) -> bool:
    groupes = partie_entiere.split(sep)
    if not groupes[0] or len(groupes[0]) > 3:
        return False
    return all(len(g) == 3 and g.isdigit() for g in groupes[1:])


def _lire_noyau(noyau: str, separateur_decimal: str | None, sans_decimales: bool) -> tuple[Decimal, bool] | None:
    """Convertit une sous-chaîne « chiffres + séparateurs » en Decimal. ``None`` si incohérente."""
    ambigu = False
    groupe_espace = any(c in noyau for c in _SEP_GROUPE)
    if groupe_espace:
        # Les espaces/apostrophes sont des séparateurs de milliers : groupes de 3 obligatoires.
        morceaux = re.split(r"[       '’]", noyau)
        if any(m == "" for m in morceaux):
            return None
        premier, *suivants = morceaux
        if not re.fullmatch(r"\d{1,3}", premier):
            return None
        for i, m in enumerate(suivants):
            dernier = i == len(suivants) - 1
            if dernier:
                if not re.fullmatch(r"\d{3}(?:[.,]\d+)?", m):
                    return None
            elif not re.fullmatch(r"\d{3}", m):
                return None
        s = "".join(morceaux)
        # Un séparateur . ou , restant est forcément décimal.
        if s.count(".") + s.count(",") > 1:
            return None
        s = s.replace(",", ".")
    else:
        s = noyau
        pos_p, pos_v = s.rfind("."), s.rfind(",")
        if pos_p >= 0 and pos_v >= 0:
            dec = "." if pos_p > pos_v else ","
            mil = "," if dec == "." else "."
            if s.count(dec) != 1:
                return None
            entier, frac = s.split(dec)
            if not _groupes_milliers_valides(entier, mil):
                return None
            s = entier.replace(mil, "") + "." + frac
        elif pos_p >= 0 or pos_v >= 0:
            sep = "." if pos_p >= 0 else ","
            n = s.count(sep)
            if n > 1:
                if not _groupes_milliers_valides(s, sep):
                    return None
                s = s.replace(sep, "")
            else:
                entier, frac = s.split(sep)
                if len(frac) == 3 and 1 <= len(entier) <= 3 and entier.strip("0") != "":
                    if separateur_decimal == sep:
                        s = entier + "." + frac
                    elif separateur_decimal is not None or sans_decimales:
                        s = entier + frac
                    else:
                        s, ambigu = entier + frac, True
                else:
                    s = entier + "." + frac
    try:
        return Decimal(s), ambigu
    except InvalidOperation:
        return None


def _est_devise(mot: str) -> bool:
    """Code ISO 4217 en capitales (« EUR ») ou symbole monétaire seul."""
    return bool(re.fullmatch(r"[A-Z]{3}|[€$£¥₩]", mot))


def _signe_negatif(avant: str, apres: str) -> bool:
    """Signe imprimé : parenthèses englobantes, moins avant (éventuellement devant la devise) ou après."""
    a, p = avant.rstrip(), apres.lstrip()
    # Parenthèses englobant le nombre (et éventuellement la devise) : « (1 234,56) », « (EUR 12,00) ».
    if "(" in a and ")" in p:
        entre_avant = a[a.rfind("(") + 1:]
        entre_apres = p[: p.find(")")]
        if re.fullmatch(r"[A-Za-z€$£¥₩\s]{0,6}", entre_avant) and re.fullmatch(r"[A-Za-z€$£¥₩\s]{0,6}", entre_apres):
            return True
    # Moins avant : « -1 234 », « - 12 », « -€12 », « EUR -12 » ; pas « 10-20 » (plage).
    m = re.search(r"(^|[^\d])[-−–]\s*[A-Za-z€$£¥₩]{0,4}\s*$", a)
    if m:
        # Tiret isolé entre espaces après un mot ou un nombre : séparateur (« Frais de dossier - 45,00 »,
        # « Ligne 3 - 1 234,56 »), sauf si ce mot est une devise (« EUR - 12 », D-1209).
        sep = re.search(r"(\S+)\s+[-−–]\s+(?:[A-Za-z€$£¥₩]{1,4}\s*)?$", avant)
        return sep is None or not re.search(r"[0-9A-Za-zÀ-ÿ]$", sep.group(1)) or _est_devise(sep.group(1))
    # Moins après : « 1 234,56- », « 12,00 EUR- ».
    return bool(re.match(r"^[A-Za-z€$£¥₩\s]{0,5}[-−–](?!\s*\d)", p))


def parse_nombre(
    texte: str | None, *, separateur_decimal: str | None = None, sans_decimales: bool = False
) -> NombreLu | None:
    """Lit le **dernier** nombre exploitable d'un texte (le libellé précède la valeur)."""
    if not texte:
        return None
    candidats = list(_NOMBRE_RE.finditer(texte))
    for m in reversed(candidats):
        noyau = m.group(0)
        # Si les espaces ont soudé deux nombres (« 10 1 234,56 »), on retire les groupes de tête.
        essais = [noyau]
        morceaux = re.split(r"(?<=\d)[       ]+(?=\d)", noyau)
        for k in range(1, len(morceaux)):
            # le préfixe retiré doit lui-même être un nombre bien formé (ex. une quantité)
            if _lire_noyau(" ".join(morceaux[:k]), separateur_decimal, sans_decimales) is not None:
                essais.append(" ".join(morceaux[k:]))
        for essai in essais:
            lu = _lire_noyau(essai, separateur_decimal, sans_decimales)
            if lu is None:
                continue
            valeur, ambigu = lu
            debut = m.start() + (len(noyau) - len(essai))
            negatif = _signe_negatif(texte[:debut], texte[m.end():])
            return NombreLu(valeur=valeur, negatif=negatif, ambigu=ambigu, texte=essai)
    return None


def parse_amount(
    texte: str | None,
    *,
    devise: str | None = None,
    separateur_decimal: str | None = None,
    pays_vendeur: str | None = None,
) -> MontantLu | None:
    """Lit un montant imprimé. ``devise`` : devise connue par ailleurs (sinon détectée dans le texte).

    >>> parse_amount("1.234,56 €").valeur
    Decimal('1234.56')
    >>> parse_amount("(1 234,56)").negatif
    True
    >>> parse_amount("1,250,000 KRW").valeur
    Decimal('1250000')
    """
    if texte is None:
        return None
    devise_lue = normalize_currency(texte, pays_vendeur=pays_vendeur)
    if devise_lue == DEVISE_INCONNUE and devise is not None:
        devise_lue = None
    devise_finale = devise or devise_lue
    sans_dec = devise_finale in DEVISES_SANS_DECIMALES
    lu = parse_nombre(texte, separateur_decimal=separateur_decimal, sans_decimales=sans_dec)
    if lu is None:
        return None
    return MontantLu(valeur=lu.valeur, negatif=lu.negatif, devise=devise_finale, ambigu=lu.ambigu, brut=texte)


def parse_decimal(texte: str | None, *, separateur_decimal: str | None = None) -> Decimal | None:
    """Nombre décimal signé (taux, quantités…). ``"2,5 %"`` -> ``Decimal('2.5')``."""
    lu = parse_nombre(texte, separateur_decimal=separateur_decimal)
    if lu is None:
        return None
    return -lu.valeur if lu.negatif else lu.valeur


def parse_int(texte: str | None) -> int | None:
    """Entier (séparateurs de milliers admis). ``None`` si la valeur a une partie décimale non nulle."""
    lu = parse_nombre(texte, sans_decimales=True)
    if lu is None:
        return None
    if lu.valeur != lu.valeur.to_integral_value():
        return None
    v = int(lu.valeur)
    return -v if lu.negatif else v
