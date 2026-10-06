"""Aide commune aux extracteurs : de la valeur brute lue à la ``ValeurSourcee`` normalisée.

``normaliser_valeur(type, brut)`` applique la fonction de ``controldone.normalize`` adaptée au type de
champ (montant, date, masse, pays, devise, TVA…) ; ``valeur_sourcee(...)`` construit la valeur avec sa
provenance et son ancrage. Les extracteurs ``deterministe`` et ``llm`` l'utilisent de la même façon.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from controldone.model.champs import chemin_complet, type_valeur_pour
from controldone.model.enums import Methode, SigneImprime, TypeDocument, TypeValeur
from controldone.model.valeur import ExtracteurInfo, ValeurSourcee, Zone
from controldone.normalize import (
    DEVISE_INCONNUE,
    code_marchandise,
    country_to_iso2,
    norm_ref,
    normalize_currency,
    normalize_eori,
    normalize_unit,
    normalize_vat,
    parse_amount,
    parse_date,
    parse_decimal,
    parse_incoterm,
    parse_int,
    parse_weight_kg,
)
from controldone.normalize.amounts import parse_nombre
from controldone.normalize.fiscal import extraire_siren
from controldone.normalize.text import normaliser_espaces

__all__ = ["ValeurNormalisee", "normaliser_valeur", "valeur_sourcee"]


@dataclass(frozen=True, slots=True)
class ValeurNormalisee:
    valeur: str | None
    unite: str | None = None
    unite_brute: str | None = None
    signe: SigneImprime | None = None
    #: Lecture ambiguë (séparateur, ordre jour/mois…) : l'extracteur doit baisser sa confiance.
    ambigu: bool = False


def normaliser_valeur(
    type_valeur: TypeValeur,
    brut: str | None,
    *,
    separateur_decimal: str | None = None,
    devise: str | None = None,
    pays_vendeur: str | None = None,
    ordre_date: str = "DMY",
) -> ValeurNormalisee:
    """Normalise une valeur brute selon son type (SPEC §5.2). ``valeur=None`` si illisible."""
    if brut is None or not brut.strip():
        return ValeurNormalisee(None)
    b = brut.strip()
    t = type_valeur
    if t is TypeValeur.montant:
        m = parse_amount(b, devise=devise, separateur_decimal=separateur_decimal, pays_vendeur=pays_vendeur)
        if m is None:
            return ValeurNormalisee(None)
        unite = m.devise if m.devise and m.devise != DEVISE_INCONNUE else devise
        return ValeurNormalisee(
            str(m.valeur), unite=unite, signe=SigneImprime.negatif if m.negatif else None, ambigu=m.ambigu
        )
    if t in (TypeValeur.decimal, TypeValeur.taux):
        d = parse_decimal(b, separateur_decimal=separateur_decimal)
        return ValeurNormalisee(
            None if d is None else str(abs(d)),
            signe=SigneImprime.negatif if d is not None and d < 0 else None,
        )
    if t is TypeValeur.quantite:
        lu = parse_nombre(b, separateur_decimal=separateur_decimal)
        if lu is None:
            return ValeurNormalisee(None)
        reste = b[b.rfind(lu.texte) + len(lu.texte) :].strip() if lu.texte in b else ""
        u = normalize_unit(reste) if reste else None
        return ValeurNormalisee(
            str(lu.valeur), unite=u.code if u else None, unite_brute=u.brut if u else None, ambigu=lu.ambigu
        )
    if t is TypeValeur.entier:
        n = parse_int(b)
        return ValeurNormalisee(None if n is None else str(n))
    if t is TypeValeur.masse:
        kg = parse_weight_kg(b, separateur_decimal=separateur_decimal)
        return ValeurNormalisee(None if kg is None else str(kg), unite="KGM")
    if t is TypeValeur.date:
        d = parse_date(b, ordre=ordre_date)
        return ValeurNormalisee(None if d is None else d.isoformat())
    if t is TypeValeur.devise:
        return ValeurNormalisee(normalize_currency(b, pays_vendeur=pays_vendeur))
    if t is TypeValeur.pays:
        return ValeurNormalisee(country_to_iso2(b))
    if t is TypeValeur.tva:
        return ValeurNormalisee(normalize_vat(b))
    if t is TypeValeur.siren:
        return ValeurNormalisee(extraire_siren(b))
    if t is TypeValeur.eori:
        return ValeurNormalisee(normalize_eori(b))
    if t is TypeValeur.incoterm:
        inc = parse_incoterm(b)
        return ValeurNormalisee(inc.code if inc else None)
    if t is TypeValeur.unite:
        u = normalize_unit(b)
        return ValeurNormalisee(u.code, unite_brute=u.brut)
    if t is TypeValeur.code:
        cm = code_marchandise(b)
        return ValeurNormalisee(cm or normaliser_espaces(b))
    if t is TypeValeur.reference:
        return ValeurNormalisee(normaliser_espaces(b) if norm_ref(b) else None)
    return ValeurNormalisee(normaliser_espaces(b))


def valeur_sourcee(
    *,
    type_document: TypeDocument | str,
    chemin: str,
    brut: str | None,
    document_id: str,
    page: int | None,
    extracteur: ExtracteurInfo,
    methode: Methode,
    confiance: float,
    textes_pages: Mapping[int, str] | None = None,
    zone: Zone | None = None,
    texte_contexte: str | None = None,
    type_valeur: TypeValeur | None = None,
    separateur_decimal: str | None = None,
    devise: str | None = None,
    id_valeur: str | None = None,
    penalite_ambiguite: float = 0.15,
) -> ValeurSourcee:
    """Construit une ``ValeurSourcee`` : chemin complet, normalisation, ancrage et confiance.

    ``chemin`` est relatif (``total_facture``, ``lignes[2].montant_ht``). Une lecture ambiguë retire
    ``penalite_ambiguite`` à la confiance. Une valeur ``llm`` non ancrée est plafonnée à 0,50 par le modèle.
    """
    from controldone.extract.base import anchor

    tv = type_valeur or type_valeur_pour(chemin)
    n = normaliser_valeur(tv, brut, separateur_decimal=separateur_decimal, devise=devise)
    ancree = False
    if methode.est_structuree:
        ancree = True
    elif textes_pages is not None and page is not None:
        ancree = anchor(brut, textes_pages.get(page))
    conf = max(0.0, confiance - (penalite_ambiguite if n.ambigu else 0.0))
    if n.valeur is None:
        conf = min(conf, 0.0) if brut is None else min(conf, 0.3)
    kwargs = {"id": id_valeur} if id_valeur else {}
    return ValeurSourcee(
        **kwargs,
        chemin=chemin_complet(type_document, chemin),
        valeur=n.valeur,
        type=tv,
        unite=n.unite,
        unite_brute=n.unite_brute,
        valeur_brute=brut,
        document_id=document_id,
        page=page,
        zone=zone,
        texte_contexte=texte_contexte,
        extracteur=extracteur,
        methode=methode,
        confiance=conf,
        ancree=ancree,
        signe_imprime=n.signe,
    )
