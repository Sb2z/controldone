"""Moteur d'exécution des contrôles (SPEC §7 étape 7, §8.6).

``run_controls(ctx)`` :

1. charge les modules ``famille_*`` et exécute les contrôles enregistrés dans l'ordre de l'Annexe A ;
2. isole chaque contrôle : une exception donne un résultat ``non_verifiable`` (raison ``erreur_interne``),
   journalisé **sans contenu de document** (§20.8), et n'interrompt pas les autres ;
3. applique les garde-fous à chaque résultat (``garde_fous_resultat``) : niveau ``a_verifier`` forcé pour
   un contrôle non éligible, note de renvoi sans montant et avec la phrase de renvoi, montant ``aucun``
   nul, écart en faveur du client jamais certain, texte filtré (§3.2) ;
4. s'arrête après P5 si le dossier est non concerné (§9) ;
5. applique les règles de non-double-comptage de §8.6 (``appliquer_regles_dedoublonnage``).
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from decimal import Decimal
from typing import Any

from controldone.controls.classify import trier_raisons
from controldone.controls.context import ControlContext
from controldone.controls.registry import charger_controles, controles_enregistres
from controldone.controls.specs import get_spec
from controldone.guardrails import MOTIF_FORMULATION_INTERDITE, PHRASE_RENVOI, check_text
from controldone.model.enums import NatureMontant, Niveau, Outcome, RaisonCode
from controldone.model.resultats import RAISONS_INFORMATIVES, Constat, ResultatControle

__all__ = [
    "EVALUABLES",
    "appliquer_regles_dedoublonnage",
    "garde_fous_resultat",
    "run_controls",
]

log = logging.getLogger("controldone.controls")

#: Outcomes d'un contrôle « évaluable » (§8.6 : C1, C2, C3/C4 tous évaluables).
EVALUABLES = frozenset({Outcome.conforme, Outcome.ecart_certain, Outcome.a_verifier})


def _reconstruire_constat(c: Constat, **maj: Any) -> Constat:
    d = c.model_dump()
    d.update(maj)
    return Constat.model_validate(d)


def _reconstruire_resultat(r: ResultatControle, **maj: Any) -> ResultatControle:
    d = r.model_dump()
    d.pop("constat", None)
    d.update(maj)
    constat = maj.get("constat", r.constat)
    d["constat"] = constat
    return ResultatControle.model_validate(d)


def _avec_raisons(c: Constat, *ajouts: RaisonCode) -> list[RaisonCode]:
    return list(trier_raisons([*c.raisons, *ajouts]))


def garde_fous_resultat(r: ResultatControle) -> ResultatControle:
    """Filet de sécurité appliqué à chaque résultat, quel que soit le contrôle qui l'a produit."""
    c = r.constat
    if c is None:
        return r
    spec = get_spec(r.controle_id)
    maj: dict[str, Any] = {}
    niveau = c.niveau
    raisons = list(c.raisons)
    # Contrôle non éligible à ecart_certain (Annexe A).
    if niveau is Niveau.ecart_certain and spec.eligible_certain is False:
        niveau = Niveau.a_verifier
        raisons.append(RaisonCode.controle_signal_seulement)
    # Écart en faveur du client : jamais certain (§8.6).
    if (
        niveau is Niveau.ecart_certain
        and c.nature_montant is NatureMontant.recouvrable
        and c.montant_en_jeu is not None
        and c.montant_en_jeu < 0
    ):
        niveau = Niveau.a_verifier
        raisons.append(RaisonCode.ecart_en_faveur_client)
    # Note de renvoi : a_verifier, sans montant, avec la phrase exacte (§3.3).
    renvoi = c.renvoi or spec.est_renvoi
    if renvoi:
        niveau = Niveau.a_verifier
        raisons.append(RaisonCode.renvoi_reglementaire)
        maj.update(renvoi=True, montant_en_jeu=None, montant_brut=None, sens=None)
        if PHRASE_RENVOI not in c.libelle and PHRASE_RENVOI not in c.prochaine_action:
            maj["prochaine_action"] = (c.prochaine_action + " " + PHRASE_RENVOI).strip()
    if c.nature_montant is NatureMontant.aucun and c.montant_en_jeu is not None:
        maj.update(montant_en_jeu=None, montant_brut=None, sens=None)
    if niveau is Niveau.a_verifier and not [x for x in raisons if x not in RAISONS_INFORMATIVES]:
        raisons.append(RaisonCode.controle_signal_seulement)
    # Formulations interdites (§3.2) : le constat est bloqué avant publication.
    texte = " ".join([c.libelle, maj.get("prochaine_action", c.prochaine_action)])
    if check_text(texte):
        maj["motif_blocage"] = MOTIF_FORMULATION_INTERDITE
    raisons_triees = list(trier_raisons(raisons))
    if niveau is c.niveau and raisons_triees == list(c.raisons) and not maj:
        return r
    nouveau = _reconstruire_constat(c, niveau=niveau, raisons=raisons_triees, **maj)
    return _reconstruire_resultat(r, outcome=niveau.outcome, constat=nouveau)


def _neutraliser(r: ResultatControle, raison: RaisonCode, couvert_par: str) -> ResultatControle:
    details = dict(r.details)
    details["couvert_par"] = couvert_par
    return _reconstruire_resultat(
        r, outcome=Outcome.non_applicable, raison_code=raison, constat=None, details=details
    )


def appliquer_regles_dedoublonnage(
    resultats: list[ResultatControle], ctx: ControlContext | None = None
) -> list[ResultatControle]:
    """Règles « pas de double comptage » de §8.6 et §10 (notes A5/A6), sur des unités identiques.

    - R1 : C3 constate pour une unité (facture transitaire × déclaration) -> C4 de la même unité
      ``non_applicable`` (raison ``couvert_par_autre_controle``) ;
    - R2 : C1, C2 et C3 ou C4 tous évaluables pour l'unité -> le constat C5 de l'unité garde son niveau
      mais ``montant_en_jeu = None`` et raison ``doublon_composantes`` (``montant_brut`` conservé) ; sinon
      C5 ne porte que le **résidu** non porté par les constats C1–C4 de l'unité (``None`` si le résidu est
      dans ``T_DEBOURS`` ou change de signe), D-1206 ;
    - R3 : A6 constate pour une unité -> A5 de la même unité ``non_applicable`` ;
    - R4 : G4 constate un excédent sur une facture transitaire et G5 constate le même excédent
      (à ``S_DEBOURS`` près) sur la même facture -> G5 ``montant_en_jeu = None``, ``doublon_composantes``.

    Les règles C6/D4 (assiette corrigée) et F3/C5 (même dossier) relèvent des contrôles eux-mêmes.
    """
    par_unite: dict[tuple[str, str], list[ResultatControle]] = {}
    for r in resultats:
        par_unite.setdefault((r.controle_id, r.unite), []).append(r)

    def constate(cid: str, unite: str) -> bool:
        return any(x.outcome.est_constat for x in par_unite.get((cid, unite), []))

    def evaluable(cid: str, unite: str) -> bool:
        rs = par_unite.get((cid, unite), [])
        return bool(rs) and all(x.outcome in EVALUABLES for x in rs)

    sortie: list[ResultatControle] = []
    for r in resultats:
        if r.controle_id == "C4" and constate("C3", r.unite):
            r = _neutraliser(r, RaisonCode.couvert_par_autre_controle, "C3")
        elif r.controle_id == "A5" and constate("A6", r.unite):
            r = _neutraliser(r, RaisonCode.couvert_par_autre_controle, "A6")
        elif r.controle_id == "C5" and r.constat is not None and r.constat.montant_en_jeu is not None:
            tva_ok = evaluable("C3", r.unite) or evaluable("C4", r.unite)
            c = r.constat
            assert c.montant_en_jeu is not None
            if evaluable("C1", r.unite) and evaluable("C2", r.unite) and tva_ok:
                residu: Decimal | None = None
            else:
                # Une composante n'est pas évaluable : C5 est le seul porteur du montant **non porté** par
                # les composantes constatées (§12 C5, §8.6 « pas de double comptage », D-1206).
                portes = [
                    x.constat.montant_en_jeu
                    for cid in ("C1", "C2", "C3", "C4")
                    for x in par_unite.get((cid, r.unite), [])
                    if x.constat is not None and x.constat.montant_en_jeu is not None
                ]
                residu = c.montant_en_jeu - sum(portes, Decimal(0)) if portes else c.montant_en_jeu
                tol = r.tolerance_appliquee if r.tolerance_appliquee is not None else Decimal("0.05")
                if (residu > 0) != (c.montant_en_jeu > 0) or abs(residu) <= tol:
                    residu = None
            if residu != c.montant_en_jeu:
                nouveau = _reconstruire_constat(
                    c,
                    montant_en_jeu=residu,
                    montant_brut=c.montant_brut if c.montant_brut is not None else c.montant_en_jeu,
                    sens=c.sens if residu is not None else None,
                    raisons=_avec_raisons(c, RaisonCode.doublon_composantes),
                )
                r = _reconstruire_resultat(r, constat=nouveau)
        sortie.append(r)

    # R4 : G5 face à G4 (unités différentes : ligne contre facture × déclaration).
    seuil = ctx.tol.s_debours() if ctx is not None else Decimal("1.00")
    g4 = [x for x in sortie if x.controle_id == "G4" and x.constat and (x.constat.montant_en_jeu or 0) > 0]
    resultat_final = []
    for r in sortie:
        c = r.constat
        if r.controle_id == "G5" and c is not None and c.montant_en_jeu is not None and c.montant_en_jeu > 0:
            for x in g4:
                assert x.constat is not None and x.constat.montant_en_jeu is not None
                memes_docs = set(x.documents_concernes) & set(r.documents_concernes)
                if memes_docs and abs(x.constat.montant_en_jeu - c.montant_en_jeu) <= seuil:
                    nouveau = _reconstruire_constat(
                        c,
                        montant_en_jeu=None,
                        montant_brut=c.montant_brut if c.montant_brut is not None else c.montant_en_jeu,
                        sens=None,
                        raisons=_avec_raisons(c, RaisonCode.doublon_composantes),
                    )
                    r = _reconstruire_resultat(r, constat=nouveau)
                    break
        resultat_final.append(r)
    return resultat_final


def _verifier_sortie(cid: str, sortie: Iterable[Any]) -> list[ResultatControle]:
    liste = list(sortie or [])
    for r in liste:
        if not isinstance(r, ResultatControle):
            raise TypeError(f"le contrôle {cid} doit retourner des ResultatControle, pas {type(r).__name__}")
        if r.controle_id != cid:
            raise ValueError(f"le contrôle {cid} a produit un résultat {r.controle_id}")
    ids = [r.id for r in liste]
    if len(ids) != len(set(ids)):
        raise ValueError(f"le contrôle {cid} a produit deux résultats de même unité (identifiants égaux)")
    return liste


def run_controls(ctx: ControlContext, *, controles: Iterable[str] | None = None) -> list[ResultatControle]:
    """Exécute les contrôles enregistrés (ordre de l'Annexe A) et retourne tous les résultats."""
    charger_controles()
    filtre = set(controles) if controles is not None else None
    ctx._journal.clear()
    for cid, fn in controles_enregistres().items():
        if filtre is not None and cid not in filtre:
            continue
        try:
            produits = _verifier_sortie(cid, fn(ctx))
        except Exception as e:  # un contrôle en erreur n'arrête jamais les autres (§20.6)
            log.error(
                "controle_en_erreur controle=%s dossier=%s version=%s exception=%s",
                cid,
                ctx.dossier.id,
                ctx.dossier.version,
                type(e).__name__,
            )
            produits = [
                ctx.non_verifiable(
                    cid, RaisonCode.erreur_interne, unite="erreur", details={"exception": type(e).__name__}
                )
            ]
        produits = [garde_fous_resultat(r) for r in produits]
        ctx._journal.extend(produits)
        if cid == "P5" and any(r.details.get("non_concerne") for r in produits):
            log.info("dossier_non_concerne dossier=%s", ctx.dossier.id)
            break
    return appliquer_regles_dedoublonnage(list(ctx._journal), ctx)
