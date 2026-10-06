"""Test de confusion de lecture (SPEC §8.5.4).

Le test est **positif** si **une seule** des transformations suivantes, appliquée à la chaîne brute d'une
valeur lue par OCR ou par le modèle, ramène l'écart dans la tolérance :

- substitution d'un chiffre par un autre de la même classe : {0, 6, 8, 9}, {3, 5, 8}, {1, 4, 7} ;
- substitution lettre/chiffre : O↔0, D↔0, l/I↔1, S↔5, B↔8, Z↔2, G↔6 ;
- perte ou ajout d'un zéro final (valeurs sans partie décimale : codes, quantités) ;
- interprétation inverse du séparateur décimal (facteur 100 ou 1000).

Une permutation de deux chiffres adjacents n'est **pas** une confusion de lecture (erreur de saisie
typique, donc vrai écart) : si la valeur lue est une transposition adjacente de la valeur attendue, le
test est négatif même si une autre transformation coïnciderait.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterator
from decimal import Decimal

from controldone.model.enums import Methode, QualiteTexte
from controldone.model.valeur import ValeurSourcee
from controldone.normalize.amounts import parse_nombre

__all__ = [
    "CLASSES_CONFUSION",
    "LETTRES_CHIFFRES",
    "codes_confondables",
    "confusion_applicable",
    "confusion_test",
    "confusion_test_fn",
    "est_transposition_adjacente",
    "variantes_chaine",
    "variantes_numeriques",
]

CLASSES_CONFUSION: tuple[frozenset[str], ...] = (
    frozenset("0689"),
    frozenset("358"),
    frozenset("147"),
)
#: Lettre lue -> chiffre voulu (et réciproquement, §8.5.4).
LETTRES_CHIFFRES: dict[str, str] = {
    "O": "0",
    "D": "0",
    "l": "1",
    "I": "1",
    "S": "5",
    "B": "8",
    "Z": "2",
    "G": "6",
}
_SUBSTITUTIONS: dict[str, tuple[str, ...]] = {
    c: tuple(sorted({x for cl in CLASSES_CONFUSION if c in cl for x in cl} - {c})) for c in "0123456789"
}
_CONFONDABLES = "0-9" + "".join(LETTRES_CHIFFRES)
# Noyau numérique : chiffres et lettres confondables collés, séparateurs internes.
_NOYAU_RE = re.compile(rf"[{_CONFONDABLES}]*\d(?:[{_CONFONDABLES}]|[.,'’    ](?=[{_CONFONDABLES}]))*")
_METHODES_SUJETTES = (Methode.ocr, Methode.llm)
_QUALITES_SUJETTES = (QualiteTexte.ocr, QualiteTexte.natif_faible)


def confusion_applicable(valeur: ValeurSourcee, qualite_page: QualiteTexte | None) -> bool:
    """Le test s'applique à une valeur ``ocr``/``llm`` lue sur une page ``ocr``/``natif_faible``.

    Qualité de page inconnue : on suppose la page sujette (lecture prudente).
    """
    if valeur.methode not in _METHODES_SUJETTES:
        return False
    return qualite_page is None or qualite_page in _QUALITES_SUJETTES


def _noyau(brut: str) -> tuple[int, int] | None:
    candidats = list(_NOYAU_RE.finditer(brut))
    if not candidats:
        return None
    m = max(candidats, key=lambda x: (len(x.group(0)), x.start()))
    return m.start(), m.end()


def variantes_chaine(brut: str) -> Iterator[str]:
    """Chaînes obtenues par **une** substitution (classe de chiffres ou lettre/chiffre) dans le noyau."""
    pos = _noyau(brut)
    if pos is None:
        return
    debut, fin = pos
    vues: set[str] = set()
    for i in range(debut, fin):
        c = brut[i]
        remplacements: tuple[str, ...] = ()
        if c in _SUBSTITUTIONS:
            # Un chiffre remplacé par une lettre ne donne pas de nombre : seul le sens lettre -> chiffre
            # sert aux comparaisons numériques (O lu pour 0, S lu pour 5…).
            remplacements = _SUBSTITUTIONS[c]
        elif c in LETTRES_CHIFFRES:
            remplacements = (LETTRES_CHIFFRES[c],)
        for r in remplacements:
            v = brut[:i] + r + brut[i + 1 :]
            if v not in vues:
                vues.add(v)
                yield v


def _lire(brut: str, separateur_decimal: str | None) -> Decimal | None:
    pos = _noyau(brut)
    if pos is not None and any(c in LETTRES_CHIFFRES for c in brut[pos[0] : pos[1]]):
        return None  # lettre dans le nombre : lecture brute non numérique
    lu = parse_nombre(brut, separateur_decimal=separateur_decimal)
    return lu.valeur if lu is not None else None


def variantes_numeriques(brut: str, *, separateur_decimal: str | None = None) -> Iterator[Decimal]:
    """Valeurs numériques atteignables par une seule transformation de §8.5.4."""
    for v in variantes_chaine(brut):
        x = _lire(v, separateur_decimal)
        if x is not None:
            yield x
    base = _lire(brut, separateur_decimal)
    if base is None:
        return
    pos = _noyau(brut)
    noyau = brut[pos[0] : pos[1]] if pos else ""
    sans_decimales = not re.search(r"[.,]\d{1,2}$", noyau)
    if sans_decimales:
        # perte ou ajout d'un zéro final (codes, quantités entières)
        yield base * 10
        if base == base.to_integral_value() and int(base) % 10 == 0:
            yield base / 10
    # séparateur décimal interprété à l'envers
    for f in (Decimal(100), Decimal(1000)):
        yield base * f
        yield base / f


def _chiffres_alignes(a: Decimal, b: Decimal) -> tuple[str, str]:
    exp = min(a.as_tuple().exponent, b.as_tuple().exponent, 0)
    q = Decimal(1).scaleb(exp)
    sa = str(abs(a).quantize(q)).replace(".", "")
    sb = str(abs(b).quantize(q)).replace(".", "")
    return sa, sb


def est_transposition_adjacente(a: Decimal, b: Decimal) -> bool:
    """Vrai si les chiffres de ``a`` et ``b`` ne diffèrent que par l'échange de deux chiffres voisins."""
    sa, sb = _chiffres_alignes(a, b)
    if len(sa) != len(sb) or sa == sb:
        return False
    diff = [i for i in range(len(sa)) if sa[i] != sb[i]]
    return (
        len(diff) == 2
        and diff[1] == diff[0] + 1
        and sa[diff[0]] == sb[diff[1]]
        and sa[diff[1]] == sb[diff[0]]
    )


def confusion_test_fn(
    brut: str | None,
    accepte: Callable[[Decimal], bool],
    *,
    separateur_decimal: str | None = None,
) -> bool:
    """Forme générale : vrai si une variante de lecture de ``brut`` satisfait ``accepte``.

    Utile quand la valeur est un opérande (base ou taux d'un produit, ligne d'une somme) : ``accepte``
    recalcule l'écart avec la variante.
    """
    if not brut:
        return False
    base = _lire(brut, separateur_decimal)
    if base is not None and accepte(base):
        return False  # aucune erreur de lecture à expliquer
    return any(accepte(v) for v in variantes_numeriques(brut, separateur_decimal=separateur_decimal))


def confusion_test(
    brut: str | None,
    autre: Decimal,
    tolerance: Decimal,
    *,
    separateur_decimal: str | None = None,
) -> bool:
    """§8.5.4 : vrai si une seule transformation de ``brut`` ramène ``|valeur − autre|`` dans ``tolerance``.

    ``autre`` est la valeur que ``brut`` devrait porter pour que l'écart disparaisse (valeur de l'autre
    document, ou valeur implicite d'un opérande). Les valeurs lues sont comparées en valeur absolue.
    """
    if not brut:
        return False
    base = _lire(brut, separateur_decimal)
    if base is not None and est_transposition_adjacente(base, autre):
        return False
    return confusion_test_fn(
        brut, lambda v: abs(v - autre) <= tolerance, separateur_decimal=separateur_decimal
    )


def codes_confondables(a: str, b: str, *, max_differences: int = 2) -> bool:
    """Codes (chiffres) de même longueur différant de 1 à ``max_differences`` chiffres, chacun d'une même
    classe de confusion (A13 : raison ``lecture_douteuse``). Une transposition adjacente n'en est pas une."""
    ca, cb = re.sub(r"\D", "", a or ""), re.sub(r"\D", "", b or "")
    if len(ca) != len(cb) or ca == cb:
        return False
    diff = [i for i in range(len(ca)) if ca[i] != cb[i]]
    if len(diff) > max_differences:
        return False
    if (
        len(diff) == 2
        and diff[1] == diff[0] + 1
        and ca[diff[0]] == cb[diff[1]]
        and ca[diff[1]] == cb[diff[0]]
    ):
        return False
    return all(cb[i] in _SUBSTITUTIONS[ca[i]] for i in diff)
