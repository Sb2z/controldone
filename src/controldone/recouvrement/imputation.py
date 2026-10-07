"""Imputation déterministe des avoirs sur les écarts à recouvrer (SPEC §17.2).

Fonction pure, sans état ni accès à une base : mêmes entrées -> même sortie, octet pour octet.

    from controldone.recouvrement.imputation import (
        EcartImputable, LigneCredit, imputer_avoirs, lignes_credit_depuis_avoir, cle_emetteur,
    )

    lignes = lignes_credit_depuis_avoir(doc_avoir, emetteur=cle_emetteur(doc_avoir.av.emetteur, transitaires))
    ecarts = [EcartImputable(id="x", emetteur="tra_…", composante=Composante.droit, reste=Decimal("40.00"),
                             facture_ref="FT-001", mrn="26FR…")]
    res = imputer_avoirs(lignes, ecarts, t_debours=Decimal("0.05"))
    res.credit_pour("x")        # montant imputé sur l'écart
    res.ecarts["x"].reste       # reste à recouvrer, res.ecarts["x"].statut
    res.reliquats               # reliquats d'avoir non imputés (E5)

Règles (§17.2) :

1. Écarts candidats d'une ligne d'avoir : même émetteur, même composante (``debours_droits`` -> ``droit``,
   ``debours_autres_taxes`` -> ``autre_taxe``, ``debours_tva`` -> ``tva``, ``debours_forfait_petits_envois``
   -> ``forfait_petits_envois``, toute prestation -> ``prestation``), statut ∈ {``reclame``,
   ``partiellement_credite``, ``conteste``, ``ouvert``}, reste > 0 ; puis rattachement par paliers : même
   facture d'origine (``ref_compatibles``) ; à défaut (aucun candidat à ce palier), même MRN (préfixe) ;
   à défaut, même référence de transport.
2. Ordre : à composante égale, écart de même nature de ligne que la ligne d'avoir d'abord (D-2208) ; puis
   écarts déjà réclamés (``reclame``, ``partiellement_credite``, ``conteste``) avant ``ouvert``, puis date de
   constat croissante (absente en dernier), puis ``constat_id``, puis ``id``.
3. ``impute = min(reste_avoir, reste_ecart)`` au centime ; statut ``credite`` si ``reste ≤ T_DEBOURS``,
   sinon ``partiellement_credite``.
4. Ligne combinée (``debours_combines``) : composantes ``droit``, ``autre_taxe``, ``tva``,
   ``forfait_petits_envois`` dans cet ordre.
5. Ce qui reste d'une ligne d'avoir est un reliquat (contrôle E5). Une ligne sans nature connue
   (avoir sans ventilation) n'est jamais imputée : tout son montant est un reliquat.

Ordre de traitement des lignes : avoirs par date croissante (absente en dernier), numéro normalisé, id ;
dans un avoir, lignes triées par nature (ordre de l'énumération ``NatureLigne``) puis par index.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
from types import MappingProxyType
from typing import Any, TypeVar

from controldone.model.champs import LigneFactureTransitaire, Partie
from controldone.model.documents import Document
from controldone.model.enums import Composante, Methode, NatureLigne, RaisonCode, StatutEcart
from controldone.model.recouvrement import EcartARecouvrer
from controldone.model.referentiel import Transitaire
from controldone.model.valeur import ValeurSourcee
from controldone.normalize.fiscal import normalize_vat
from controldone.normalize.parties import identifier_transitaire
from controldone.normalize.refs import mrn_prefixe, norm_ref, ref_compatibles, ref_transport_egales
from controldone.normalize.text import cle_texte

__all__ = [
    "ORDRE_COMBINE",
    "STATUTS_IMPUTABLES",
    "EcartImputable",
    "EtatEcart",
    "Imputation",
    "LigneCredit",
    "Reliquat",
    "ResultatImputation",
    "choisir_par_paliers",
    "cle_emetteur",
    "composantes_de_nature",
    "emetteurs_compatibles",
    "imputer_avoirs",
    "lignes_credit_depuis_avoir",
]

_CENTIME = Decimal("0.01")
_ZERO = Decimal("0.00")

#: Statuts d'écart pouvant recevoir une imputation (§17.2, étape 1).
STATUTS_IMPUTABLES: frozenset[StatutEcart] = frozenset(
    {StatutEcart.reclame, StatutEcart.partiellement_credite, StatutEcart.conteste, StatutEcart.ouvert}
)
#: Ordre d'imputation d'une ligne « droits et taxes » combinée (§17.2, étape 4).
ORDRE_COMBINE: tuple[Composante, ...] = (
    Composante.droit,
    Composante.autre_taxe,
    Composante.tva,
    Composante.forfait_petits_envois,
)
_ORDRE_NATURE = {n: i for i, n in enumerate(NatureLigne)}


def _c(x: Decimal) -> Decimal:
    return Decimal(x).quantize(_CENTIME, rounding=ROUND_HALF_UP)


def composantes_de_nature(nature: NatureLigne | None) -> tuple[Composante, ...]:
    """Composantes qu'une ligne d'avoir de cette nature peut créditer, dans l'ordre d'imputation."""
    if nature is None:
        return ()
    if nature is NatureLigne.debours_combines:
        return ORDRE_COMBINE
    c = nature.composante
    return (c,) if c is not None else ()


def cle_emetteur(partie: Partie | None, transitaires: Iterable[Transitaire] = ()) -> str | None:
    """Clé d'émetteur comparable entre avoirs et écarts.

    Identifiant du ``Transitaire`` reconnu (``identifier_transitaire``, règle unique D-1211) ; à défaut
    ``"tva:<TVA normalisée>"`` ou ``"nom:<nom normalisé>"`` ; ``None`` si le pavé est vide.
    """
    if partie is None:
        return None
    tva = normalize_vat(partie.tva.valeur) if partie.tva is not None and partie.tva.valeur else None
    nom = cle_texte(partie.nom.valeur) if partie.nom is not None and partie.nom.valeur else None
    tid = identifier_transitaire(tva, nom, transitaires)
    if tid is not None:
        return tid
    if tva:
        return f"tva:{tva}"
    if nom:
        return f"nom:{nom}"
    return None


@dataclass(frozen=True, slots=True)
class LigneCredit:
    """Ligne d'avoir à imputer. ``nature = None`` : avoir sans ventilation (jamais imputé)."""

    avoir_id: str
    ligne: int | None
    nature: NatureLigne | None
    montant: Decimal
    emetteur: str | None = None
    date_avoir: date | None = None
    numero_avoir: str | None = None
    factures_origine: tuple[str, ...] = ()
    mrns: tuple[str, ...] = ()
    refs_transport: tuple[str, ...] = ()
    #: Valeur sourcée du montant (preuve des constats C et D), hors comparaison.
    valeur: Any = field(default=None, compare=False)


@dataclass(frozen=True, slots=True)
class EcartImputable:
    """Écart candidat (§17.1) vu par l'imputation. ``reste`` = montant encore à recouvrer avant imputation."""

    id: str
    composante: Composante
    reste: Decimal
    emetteur: str | None = None
    statut: StatutEcart = StatutEcart.ouvert
    date_constat: datetime | date | None = None
    constat_id: str = ""
    facture_ref: str | None = None
    mrn: str | None = None
    ref_transport: str | None = None
    montant_initial: Decimal | None = None
    #: Nature de la ligne facturée en écart (prestations) : à composante égale, une ligne d'avoir de même
    #: nature est imputée d'abord sur cet écart (même choix que la déduction ligne à ligne de D, D-2208).
    nature: NatureLigne | None = None

    @classmethod
    def depuis_ecart(
        cls,
        ecart: EcartARecouvrer,
        *,
        facture_ref: str | None = None,
        ref_transport: str | None = None,
        emetteur: str | None = None,
        reste: Decimal | None = None,
    ) -> EcartImputable:
        """Depuis un ``EcartARecouvrer`` du registre. ``emetteur`` par défaut : ``transitaire_id``.
        ``reste`` par défaut : le reste enregistré (passer ``montant_initial`` pour un recalcul complet)."""
        return cls(
            id=ecart.id,
            composante=ecart.composante,
            reste=ecart.reste if reste is None else reste,
            emetteur=emetteur if emetteur is not None else ecart.transitaire_id,
            statut=ecart.statut,
            date_constat=ecart.date_constat,
            constat_id=ecart.constat_id,
            facture_ref=facture_ref,
            mrn=ecart.mrn,
            ref_transport=ref_transport,
            montant_initial=ecart.montant_initial,
        )


@dataclass(frozen=True, slots=True)
class Imputation:
    avoir_id: str
    ligne: int | None
    ecart_id: str
    montant: Decimal
    #: Palier de rattachement retenu : ``facture``, ``mrn`` ou ``transport``.
    palier: str


@dataclass(slots=True)
class EtatEcart:
    ecart_id: str
    montant_initial: Decimal
    montant_credite: Decimal
    reste: Decimal
    statut: StatutEcart


@dataclass(frozen=True, slots=True)
class Reliquat:
    avoir_id: str
    ligne: int | None
    nature: NatureLigne | None
    montant: Decimal


@dataclass(frozen=True)
class ResultatImputation:
    imputations: tuple[Imputation, ...]
    ecarts: Mapping[str, EtatEcart]
    reliquats: tuple[Reliquat, ...]
    _credits: Mapping[str, Decimal] = field(default_factory=dict, repr=False)

    def credit_pour(self, ecart_id: str) -> Decimal:
        """Total imputé sur un écart (0,00 si aucun)."""
        return self._credits.get(ecart_id, _ZERO)

    def reliquat_avoir(self, avoir_id: str) -> Decimal:
        """Reliquat total d'un avoir (somme de ses lignes non imputées)."""
        return _c(sum((r.montant for r in self.reliquats if r.avoir_id == avoir_id), _ZERO))

    def imputations_avoir(self, avoir_id: str) -> tuple[Imputation, ...]:
        return tuple(i for i in self.imputations if i.avoir_id == avoir_id)


def _rang_statut(s: StatutEcart) -> int:
    return 1 if s is StatutEcart.ouvert else 0


def _cle_date(d: datetime | date | None) -> tuple[int, str]:
    if d is None:
        return (1, "")
    return (0, d.isoformat())


def _cle_ecart(e: EcartImputable) -> tuple:
    return (_rang_statut(e.statut), _cle_date(e.date_constat), e.constat_id, e.id)


def _cle_ligne(lc: LigneCredit) -> tuple:
    nat = _ORDRE_NATURE[lc.nature] if lc.nature is not None else len(_ORDRE_NATURE)
    return (
        _cle_date(lc.date_avoir),
        norm_ref(lc.numero_avoir),
        lc.avoir_id,
        nat,
        -1 if lc.ligne is None else lc.ligne,
    )


def emetteurs_compatibles(a: str | None, b: str | None) -> bool:
    """Même émetteur (§17.2, D-304) ; un émetteur illisible d'un côté n'empêche pas le rapprochement (D-305)."""
    return a is None or b is None or a == b


_T = TypeVar("_T")


def choisir_par_paliers(
    lc: LigneCredit,
    cibles: Sequence[_T],
    *,
    factures: Callable[[_T], Iterable[str | None]],
    mrns: Callable[[_T], Iterable[str | None]],
    transports: Callable[[_T], Iterable[str | None]] | None = None,
) -> tuple[str, list[_T]]:
    """Rattachement par paliers d'une ligne d'avoir (§17.2, étape 1), règle unique des familles C, D et E :
    cibles de même facture d'origine (``ref_compatibles``) ; à défaut (aucune cible à ce palier), de même MRN
    (préfixe) ; à défaut, de même référence de transport. Retourne (palier, cibles retenues)."""
    if lc.factures_origine:
        par_facture = [
            c
            for c in cibles
            if any(f and ref_compatibles(o, f) for f in factures(c) for o in lc.factures_origine)
        ]
        if par_facture:
            return "facture", par_facture
    prefixes = {mrn_prefixe(m) for m in lc.mrns if len(mrn_prefixe(m)) == 15}
    if prefixes:
        par_mrn = [c for c in cibles if any(m and mrn_prefixe(m) in prefixes for m in mrns(c))]
        if par_mrn:
            return "mrn", par_mrn
    if lc.refs_transport and transports is not None:
        par_transport = [
            c
            for c in cibles
            if any(t and ref_transport_egales(r, t) for t in transports(c) for r in lc.refs_transport)
        ]
        if par_transport:
            return "transport", par_transport
    return "", []


def _palier(lc: LigneCredit, candidats: Sequence[EcartImputable]) -> tuple[str, list[EcartImputable]]:
    return choisir_par_paliers(
        lc,
        candidats,
        factures=lambda e: (e.facture_ref,),
        mrns=lambda e: (e.mrn,),
        transports=lambda e: (e.ref_transport,),
    )


def imputer_avoirs(
    lignes: Iterable[LigneCredit],
    ecarts: Iterable[EcartImputable],
    *,
    t_debours: Decimal = Decimal("0.05"),
) -> ResultatImputation:
    """Impute les lignes d'avoir sur les écarts (§17.2). Pure et déterministe (ordre d'entrée indifférent).

    ``t_debours`` : seuil ``T_DEBOURS`` sous lequel un reste vaut « crédité ».
    Un même identifiant d'écart ne doit apparaître qu'une fois (``ValueError`` sinon).
    """
    liste_ecarts = sorted(ecarts, key=_cle_ecart)
    ids = [e.id for e in liste_ecarts]
    if len(ids) != len(set(ids)):
        raise ValueError("identifiant d'écart en double")
    etats: dict[str, EtatEcart] = {
        e.id: EtatEcart(
            ecart_id=e.id,
            montant_initial=_c(e.montant_initial if e.montant_initial is not None else e.reste),
            montant_credite=_ZERO,
            reste=_c(e.reste),
            statut=e.statut,
        )
        for e in liste_ecarts
    }
    imputations: list[Imputation] = []
    reliquats: list[Reliquat] = []
    credits: dict[str, Decimal] = {}

    for lc in sorted(lignes, key=_cle_ligne):
        reste_avoir = _c(lc.montant)
        if reste_avoir <= 0:
            continue
        comps = composantes_de_nature(lc.nature)
        if comps:
            candidats = [
                e
                for e in liste_ecarts
                if e.composante in comps
                and emetteurs_compatibles(e.emetteur, lc.emetteur)
                and etats[e.id].statut in STATUTS_IMPUTABLES
                and etats[e.id].reste > 0
            ]
            palier, retenus = _palier(lc, candidats)
            retenus.sort(
                key=lambda e: (
                    comps.index(e.composante),
                    e.nature is None or e.nature is not lc.nature,
                    *_cle_ecart(e),
                )
            )
            for e in retenus:
                if reste_avoir <= 0:
                    break
                etat = etats[e.id]
                impute = min(reste_avoir, etat.reste)
                if impute <= 0:
                    continue
                reste_avoir = _c(reste_avoir - impute)
                etat.reste = _c(etat.reste - impute)
                etat.montant_credite = _c(etat.montant_credite + impute)
                etat.statut = (
                    StatutEcart.credite if etat.reste <= t_debours else StatutEcart.partiellement_credite
                )
                credits[e.id] = _c(credits.get(e.id, _ZERO) + impute)
                imputations.append(Imputation(lc.avoir_id, lc.ligne, e.id, impute, palier))
        if reste_avoir > 0:
            reliquats.append(Reliquat(lc.avoir_id, lc.ligne, lc.nature, reste_avoir))

    return ResultatImputation(
        imputations=tuple(imputations),
        ecarts=MappingProxyType(etats),
        reliquats=tuple(reliquats),
        _credits=MappingProxyType(credits),
    )


#: Règle de dérivation du hors-taxe d'une ligne imprimée TVA comprise (extracteur, D-2502).
REGLE_HT_DEPUIS_TTC = "montant_ttc / (1 + taux_tva)"
#: Confiance plafond d'un montant de ligne TVA comprise utilisé comme montant hors TVA (D-2701).
C_TVA_COMPRISE = 0.60


def _marquer_tva_comprise(v: ValeurSourcee) -> ValeurSourcee:
    raisons = list(v.raisons)
    if RaisonCode.montant_tva_comprise not in raisons:
        raisons.append(RaisonCode.montant_tva_comprise)
    return v.model_copy(update={"confiance": min(v.confiance, C_TVA_COMPRISE), "raisons": raisons})


def ht_depuis_ttc(ligne: LigneFactureTransitaire) -> bool:
    """Le hors-taxe de la ligne est déduit de son montant TVA comprise (``montant_ttc / (1 + taux)``)."""
    ht, ttc = ligne.montant_ht, ligne.montant_ttc
    if ht is None or ht.methode is not Methode.derive:
        return False
    return ht.regle_derivation == REGLE_HT_DEPUIS_TTC or (ttc is not None and ttc.id in ht.derivee_de)


def montant_net_ligne(
    ligne: LigneFactureTransitaire, utilisable: Callable[[ValeurSourcee | None], bool] | None = None
) -> ValeurSourcee | None:
    """Montant hors TVA d'une ligne de facture du transitaire ou d'avoir, à comparer à un tarif ou à un montant
    liquidé (D-2701).

    - ``montant_ht`` lu : tel quel ; déduit du TTC (ligne « TVA comprise », D-2502) : marqué
      ``montant_tva_comprise`` (jamais la base d'un écart certain) ;
    - pas de hors-taxe (ou hors-taxe inutilisable) : le TTC n'est un montant net que si la ligne ne porte pas de
      TVA (taux lu nul, ou TVA de ligne lue nulle) ; sinon il est rendu marqué ``montant_tva_comprise`` et
      plafonné (un brut comparé à un tarif net ne prouve aucun écart).
    """
    ok = utilisable or (lambda v: v is not None and v.est_lisible)
    ht, ttc = ligne.montant_ht, ligne.montant_ttc
    sans_tva = any(
        v is not None and v.est_lisible and v.decimal_ou_none() == 0
        for v in (ligne.taux_tva, ligne.montant_tva)
    )
    if ht is not None and ht_depuis_ttc(ligne):
        return _marquer_tva_comprise(ht)
    if ligne.tva_comprise and not sans_tva:
        # D-4602 : ligne marquée dès l'extraction « TVA comprise seulement » : aucun montant de la ligne n'est un
        # hors-taxe imprimé, quelle que soit la colonne où il a été rangé.
        v = ht if ht is not None and (ok(ht) or ttc is None or not ok(ttc)) else ttc
        return _marquer_tva_comprise(v) if v is not None else None
    if ht is not None and (ok(ht) or ttc is None or not ok(ttc)):
        return ht
    if ttc is None:
        return ht
    return ttc if sans_tva else _marquer_tva_comprise(ttc)


def lignes_credit_depuis_avoir(
    doc: Document, *, emetteur: str | None = None, utilisable: Callable[[Any], bool] | None = None
) -> list[LigneCredit]:
    """Lignes d'imputation d'un document ``avoir`` (montants HT des lignes, positifs).

    MRN et référence de transport : ceux de la ligne, à défaut ceux de l'en-tête de l'avoir. Un avoir sans
    ligne lisible donne une seule ligne sans nature, de montant ``total_credite_ht`` (à défaut TTC) :
    elle n'est jamais imputée (reliquat entier, signalé par E5).

    ``utilisable`` (contrôles : ``ctx.utilisable``, seuil ``C_MIN_UTILE``) écarte les montants et références
    trop douteux pour être exploités (D-1210).
    """
    ok: Callable[[Any], bool] = utilisable if utilisable is not None else (lambda v: True)

    def _valeurs_texte(vals: Iterable) -> tuple[str, ...]:
        return tuple(v.valeur for v in vals if v is not None and v.valeur and ok(v))

    av = doc.av
    d_avoir = None
    if av.date is not None and av.date.valeur:
        try:
            d_avoir = av.date.date_iso()
        except ValueError:
            d_avoir = None
    numero = av.numero.valeur if av.numero is not None else None
    origine = _valeurs_texte(av.refs_facture_origine)
    mrn_tete = _valeurs_texte(av.refs_mrn)
    transport_tete = _valeurs_texte(av.refs_transport)
    out: list[LigneCredit] = []
    for i, ligne in enumerate(av.lignes):
        m = montant_net_ligne(ligne, ok)
        montant = m.decimal_ou_none() if m is not None and ok(m) else None
        if montant is None:
            continue
        mrn_ligne = _valeurs_texte([ligne.mrn])
        transport_ligne = _valeurs_texte([ligne.ref_transport])
        out.append(
            LigneCredit(
                avoir_id=doc.id,
                ligne=i,
                nature=ligne.nature,
                montant=abs(montant),
                emetteur=emetteur,
                date_avoir=d_avoir,
                numero_avoir=numero,
                factures_origine=origine,
                mrns=mrn_ligne or mrn_tete,
                refs_transport=transport_ligne or transport_tete,
                valeur=m,
            )
        )
    if not out:
        total = av.total_credite_ht if av.total_credite_ht is not None else av.total_credite_ttc
        montant = total.decimal_ou_none() if total is not None and ok(total) else None
        if montant is not None:
            out.append(
                LigneCredit(
                    avoir_id=doc.id,
                    ligne=None,
                    nature=None,
                    montant=abs(montant),
                    emetteur=emetteur,
                    date_avoir=d_avoir,
                    numero_avoir=numero,
                    factures_origine=origine,
                    mrns=mrn_tete,
                    refs_transport=transport_tete,
                    valeur=total,
                )
            )
    return out
