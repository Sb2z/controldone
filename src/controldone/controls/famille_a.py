"""Famille A — Facture commerciale contre déclaration (SPEC §10).

Unité par défaut : le **couple** (ensemble des factures commerciales allouées, déclaration(s)), clé
``cle_unite(fc=[...], dec=[...])`` (convention partagée A3–A7, règle A6 -> A5 du moteur). Les couples sont
formés à partir des allocations facture -> déclaration du dossier (composantes connexes) ; sans allocation,
toutes les factures exploitables et toutes les dernières versions de déclaration forment un seul couple.
Quand plusieurs factures sont allouées à une déclaration, leurs totaux sont additionnés (devise identique
exigée, sinon A3) ; quand une facture est répartie sur plusieurs déclarations, la somme des montants déclarés
est comparée au total facture (et chaque allocation explicite chiffrée est comparée en plus, A4).

Prudence (§8.5.1, P-7, P-8) : toute donnée absente ou de confiance < ``C_MIN_UTILE`` donne
``non_verifiable`` ; tout constat passe par ``ctx.classify`` (8 conditions) ; A2, A7–A15 sont des
contrôles de signal (``a_verifier`` seulement) ; A12 et A13 sont des notes de renvoi (``PHRASE_RENVOI``,
montant ``null``). Aucun jugement sur la valeur en douane, l'origine, le classement ou un taux.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from itertools import combinations

from controldone.controls.famille_p import entites_client_declaration, identifier_facture
from controldone.controls.framework import (
    Confusion,
    ControlContext,
    arrondi_centime,
    cle_unite,
    codes_confondables,
    control,
    eur_par_devise,
    montant_ecart_documentaire,
    preuve,
)
from controldone.formatage import format_montant, format_nombre, format_pourcentage
from controldone.guardrails import PHRASE_RENVOI
from controldone.model import (
    Allocation,
    ChampsSupport,
    Composante,
    Document,
    RaisonCode,
    ResultatControle,
    RolePreuve,
    SousTypeFactureCommerciale,
    SousTypeSupport,
    TauxChangeSens,
    TypeDocument,
    TypeSousTotal,
    ValeurSourcee,
)
from controldone.normalize.countries import country_to_iso2
from controldone.normalize.incoterms import parse_incoterm
from controldone.normalize.refs import norm_ref, ref_compatibles
from controldone.normalize.units import UNITE_INCONNUE, normalize_unit

__all__ = [
    "ACTION_A1",
    "ACTION_A2",
    "ACTION_A3",
    "ACTION_A4",
    "ACTION_A4_PIED",
    "ACTION_A5",
    "ACTION_A6",
    "ACTION_A7",
    "ACTION_A8",
    "ACTION_A9",
    "ACTION_A10",
    "ACTION_A11",
    "ACTION_A14",
    "ACTION_A15",
    "ACTION_RENVOI",
    "Couple",
    "a1_entite_importatrice",
    "a2_reference_facture",
    "a3_devise",
    "a4_valeur_facturee",
    "a5_montant_converti",
    "a6_montant_sans_conversion",
    "a7_ordre_de_grandeur",
    "a8_incoterm",
    "a9_quantites",
    "a10_masses",
    "a11_colis",
    "a12_pays_origine",
    "a13_codes_marchandise",
    "a14_chronologie",
    "a15_references_produit",
    "couples",
]

# --- Gabarits de « prochaine action » (testés contre les formulations interdites) ---------------------

ACTION_A1 = "Vérifier quelle entité du groupe est l'acheteur et l'importateur de cet envoi, et le faire confirmer."
ACTION_A2 = "Vérifier que la déclaration se rapporte bien à cette facture commerciale (référence citée)."
ACTION_A3 = "Vérifier auprès du déclarant la devise de facturation reprise sur la déclaration."
ACTION_A4 = "Demander au déclarant l'explication de l'écart entre le montant facturé déclaré et la facture commerciale."
ACTION_A4_PIED = (
    "Vérifier avec le déclarant le traitement de cette ligne de pied (fret, assurance, emballage, remise) dans "
    "le montant déclaré. " + PHRASE_RENVOI
)
ACTION_A5 = "Demander au déclarant l'explication de l'écart entre le montant déclaré en euros et la conversion au taux imprimé."
ACTION_A6 = "Demander au déclarant de vérifier la conversion en euros du montant facturé repris sur la déclaration."
ACTION_A7 = "Vérifier la conversion en euros du montant facturé : l'ordre de grandeur ne correspond pas."
ACTION_A8 = "Signaler cette différence d'Incoterm au déclarant. " + PHRASE_RENVOI
ACTION_A9 = "Vérifier les quantités reprises sur la déclaration avec la facture commerciale."
ACTION_A10 = "Vérifier les masses reprises sur la déclaration avec la facture ou la liste de colisage."
ACTION_A11 = "Vérifier le nombre de colis repris sur la déclaration avec la facture ou le titre de transport."
ACTION_A14 = "Vérifier la date de la facture commerciale et celle de la déclaration."
ACTION_A15 = "Vérifier que les articles déclarés correspondent aux références de la facture commerciale."
#: A12, A13 : la phrase de renvoi figure dans le libellé ; l'action oriente vers un professionnel.
ACTION_RENVOI = "Transmettre ce point, avec les deux documents, à un représentant en douane enregistré ou à un avocat."

_DEUX_PIEDS = (TypeSousTotal.fret, TypeSousTotal.assurance, TypeSousTotal.emballage, TypeSousTotal.remise)
_MAX_LIGNES_PIED = 12
_CODES_FACTURE = ("380", "325", "935")
_UNITES_LIB = {
    "C62": "pièces", "PR": "paires", "SET": "jeux", "DZN": "douzaines", "KGM": "kg", "GRM": "g", "TNE": "t",
    "LTR": "l", "MLT": "ml", "MTR": "m", "MTK": "m²", "MTQ": "m³", "CMT": "cm", "CT": "cartons", "BX": "boîtes",
    "PK": "paquets", "RO": "rouleaux", "KWH": "kWh",
}
_RE_ISO = re.compile(r"^[A-Z]{3}$")


# =====================================================================================================
# Couples (unité de comparaison)
# =====================================================================================================


@dataclass(frozen=True)
class Couple:
    """Ensemble de factures commerciales allouées et de déclarations (dernières versions)."""

    fcs: tuple[Document, ...]
    decs: tuple[Document, ...]
    allocations: tuple[Allocation, ...] = field(default=())

    @property
    def unite(self) -> str:
        return cle_unite(fc=[d.id for d in self.fcs], dec=[d.id for d in self.decs])

    @property
    def doc_ids(self) -> list[str]:
        return [d.id for d in self.fcs] + [d.id for d in self.decs]


def couples(ctx: ControlContext) -> list[Couple]:
    """Couples (factures allouées, déclarations) du dossier.

    - Sans allocation facture -> déclaration : un seul couple (toutes les factures, toutes les déclarations).
    - Sinon : composantes connexes du graphe des allocations (une allocation vers une version antérieure
      est reportée sur la dernière version du même préfixe MRN). Les documents sans allocation forment un
      couple résiduel ; s'il ne reste qu'un côté et une seule composante, ils la rejoignent, sinon le couple
      incomplet est rendu tel quel (les contrôles le déclarent ``non_verifiable``).
    """
    fcs, decs = ctx.factures_commerciales(), ctx.declarations()
    ids_fc = {d.id for d in fcs}
    derniere: dict[str, str] = {d.id: d.id for d in decs}
    for d in ctx.declarations(dernieres_versions=False):
        if d.id not in derniere:
            retenue = ctx.mrn_prefixes().get(d.dec.mrn_prefixe)
            if retenue is not None:
                derniere[d.id] = retenue.id
    aretes: list[tuple[str, str, Allocation]] = []
    for a in ctx.dossier.allocations:
        cible = derniere.get(a.cible_document_id or "")
        if a.source_document_id in ids_fc and cible is not None:
            aretes.append((a.source_document_id, cible, a))
    if not aretes:
        return [Couple(tuple(fcs), tuple(decs))] if fcs or decs else []

    parent: dict[str, str] = {}

    def racine(x: str) -> str:
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for f, d, _ in aretes:
        parent[racine(f)] = racine(d)
    groupes: dict[str, tuple[list[Document], list[Document], list[Allocation]]] = {}
    for doc in [*fcs, *decs]:
        if doc.id in parent:
            groupes.setdefault(racine(doc.id), ([], [], []))[0 if doc.id in ids_fc else 1].append(doc)
    for f, _d, a in aretes:
        groupes[racine(f)][2].append(a)
    resultat = [Couple(tuple(g[0]), tuple(g[1]), tuple(g[2])) for g in groupes.values()]
    reste_fc = tuple(d for d in fcs if d.id not in parent)
    reste_dec = tuple(d for d in decs if d.id not in parent)
    if reste_fc and reste_dec:
        resultat.append(Couple(reste_fc, reste_dec))
    elif (reste_fc or reste_dec) and len(resultat) == 1:
        c = resultat[0]
        resultat = [Couple(c.fcs + reste_fc, c.decs + reste_dec, c.allocations)]
    elif reste_fc or reste_dec:
        resultat.append(Couple(reste_fc, reste_dec))
    return resultat


def _par_couple(
    ctx: ControlContext, cid: str, fn: Callable[[ControlContext, Couple], list[ResultatControle]]
) -> list[ResultatControle]:
    if not ctx.factures_commerciales() or not ctx.declarations():
        return [ctx.non_verifiable(cid, RaisonCode.document_manquant)]
    out: list[ResultatControle] = []
    for c in couples(ctx):
        if not c.fcs or not c.decs:
            out.append(ctx.non_verifiable(cid, RaisonCode.document_manquant, unite=c.unite, documents=c.doc_ids))
            continue
        out.extend(fn(ctx, c))
    return out


# =====================================================================================================
# Textes
# =====================================================================================================


def _maj(s: str) -> str:
    return s[:1].upper() + s[1:]


def _num_fc(fc: Document) -> str | None:
    v = fc.fc.numero
    return v.valeur if v is not None and v.valeur else None


def _mrn(dec: Document) -> str | None:
    v = dec.dec.mrn
    return v.valeur if v is not None and v.valeur else None


def _ref_fc(fc: Document, v: ValeurSourcee | None = None) -> str:
    s = "la facture commerciale"
    if num := _num_fc(fc):
        s += f" n° {num}"
    if v is not None and v.page:
        s += f" (page {v.page})"
    return s


def _ref_dec(dec: Document, v: ValeurSourcee | None = None) -> str:
    morceaux = [x for x in (f"MRN {_mrn(dec)}" if _mrn(dec) else None,
                            f"page {v.page}" if v is not None and v.page else None) if x]
    return "la déclaration" + (f" ({', '.join(morceaux)})" if morceaux else "")


def _vals_par_document(docs: Sequence[Document], vals: Sequence[ValeurSourcee | None]) -> list[ValeurSourcee | None]:
    """Une valeur (ou ``None``) par document, pour citer sa page.

    Les valeurs peuvent être une par document (totaux) ou plusieurs par document (valeurs par article, quand
    le total n'est pas lu) : on rattache alors à chaque document sa première valeur (A10, A11)."""
    vals = list(vals)
    if len(vals) == len(docs) and all(v is None or v.document_id in (None, d.id) for d, v in zip(docs, vals, strict=True)):
        return vals
    if len(vals) <= len(docs) and all(v is None or v.document_id is None for v in vals):
        return vals + [None] * (len(docs) - len(vals))
    return [next((v for v in vals if v is not None and v.document_id == d.id), None) for d in docs]


def _refs_fc(fcs: Sequence[Document], vals: Sequence[ValeurSourcee | None] = ()) -> str:
    vals = _vals_par_document(fcs, vals)
    if len(fcs) == 1:
        return _ref_fc(fcs[0], vals[0])
    items = []
    for fc, v in zip(fcs, vals, strict=True):
        s = f"n° {_num_fc(fc) or '?'}"
        if v is not None and v.page:
            s += f" (page {v.page})"
        items.append(s)
    return "les factures commerciales " + ", ".join(items)


def _refs_dec(decs: Sequence[Document], vals: Sequence[ValeurSourcee | None] = ()) -> str:
    vals = _vals_par_document(decs, vals)
    if len(decs) == 1:
        return _ref_dec(decs[0], vals[0])
    items = []
    for dec, v in zip(decs, vals, strict=True):
        s = f"MRN {_mrn(dec) or '?'}"
        if v is not None and v.page:
            s += f", page {v.page}"
        items.append(s)
    return "les déclarations (" + " ; ".join(items) + ")"


def _date_fr(d: date) -> str:
    return d.strftime("%d/%m/%Y")


def _unite_lib(code: str | None) -> str:
    return _UNITES_LIB.get(code or "", code or "")


# =====================================================================================================
# Lectures
# =====================================================================================================


def _decimal(v: ValeurSourcee) -> Decimal | None:
    try:
        return v.decimal_signe()
    except ValueError:
        return None


def _lire_somme(
    ctx: ControlContext, valeurs: Sequence[ValeurSourcee | None]
) -> tuple[list[ValeurSourcee], Decimal] | RaisonCode:
    """Somme exacte de valeurs toutes utilisables ; sinon la raison du ``non_verifiable`` (P3)."""
    if not valeurs:
        return RaisonCode.valeur_absente
    lues: list[ValeurSourcee] = []
    total = Decimal(0)
    for v in valeurs:
        if not ctx.utilisable(v):
            return ctx.raison_inutilisable(v)
        assert v is not None
        d = _decimal(v)
        if d is None:
            return RaisonCode.valeur_absente
        lues.append(v)
        total += d
    return lues, total


def _confusions_somme(valeurs: Sequence[ValeurSourcee], accepte_total: Callable[[Decimal], bool]) -> list[Confusion]:
    """Test de confusion (§8.5.4) sur chaque terme d'une somme : la variante lue remplace le terme."""
    total = sum((v.decimal_signe() for v in valeurs), Decimal(0))
    out = []
    for v in valeurs:
        terme = v.decimal_signe()
        signe = -1 if terme < 0 else 1

        def accepte(x: Decimal, terme: Decimal = terme, signe: int = signe) -> bool:
            return accepte_total(total - terme + signe * x)

        out.append(Confusion(v, accepte=accepte))
    return out


def _date(ctx: ControlContext, v: ValeurSourcee | None) -> date | None:
    if not ctx.utilisable(v):
        return None
    assert v is not None
    try:
        return v.date_iso()
    except ValueError:
        return None


def _date_acceptation(ctx: ControlContext, c: Couple) -> date | None:
    dates = [d for d in (_date(ctx, dec.dec.date_acceptation) for dec in c.decs) if d is not None]
    return min(dates) if dates else None


# --- Devises ----------------------------------------------------------------------------------------------


def _code_devise(ctx: ControlContext, v: ValeurSourcee | None) -> str | None:
    if not ctx.utilisable(v):
        return None
    assert v is not None
    code = (v.valeur or "").strip().upper()
    return code if _RE_ISO.match(code) else None


def _iso_lu(v: ValeurSourcee) -> bool:
    """Code ISO 4217 lu tel quel (pas un symbole ambigu comme « $ ») ou valeur structurée/saisie."""
    if v.est_structuree:
        return True
    code = (v.valeur or "").upper()
    return bool(re.search(rf"(?<![A-Z]){re.escape(code)}(?![A-Z])", (v.valeur_brute or "").upper()))


@dataclass(frozen=True)
class Devises:
    """Situation des devises d'un couple.

    ``situation`` : ``meme`` (A4), ``converti`` (facture en D ≠ EUR, déclaration en EUR : A5/A6/A7),
    ``differente`` (autres devises différentes : A3), ``incertaine`` (une devise illisible : A3
    ``non_verifiable``, A4 au mieux ``a_verifier``), ``multiples`` (factures ou déclarations du couple en
    devises différentes entre elles).
    """

    fc: str | None
    dec: str | None
    fc_vals: tuple[ValeurSourcee, ...]
    dec_vals: tuple[ValeurSourcee, ...]
    situation: str
    illisible: ValeurSourcee | None = None
    raison_illisible: RaisonCode | None = None

    @property
    def valeurs(self) -> list[ValeurSourcee]:
        return [*self.fc_vals, *self.dec_vals]

    @property
    def iso_lus(self) -> bool:
        return all(_iso_lu(v) for v in self.valeurs)


def _devises(ctx: ControlContext, c: Couple) -> Devises:
    def cote(vals: list[ValeurSourcee | None]) -> tuple[str | None, bool, ValeurSourcee | None, list[ValeurSourcee]]:
        codes, lisibles, illisible = set(), [], None
        for v in vals:
            code = _code_devise(ctx, v)
            if code is None:
                illisible = illisible or v
                continue
            assert v is not None
            codes.add(code)
            lisibles.append(v)
        if len(codes) > 1:
            return None, True, illisible, lisibles
        if illisible is not None or not codes:
            return None, False, illisible, lisibles
        return codes.pop(), False, None, lisibles

    fv: list[ValeurSourcee | None] = [fc.fc.devise for fc in c.fcs]
    dv: list[ValeurSourcee | None] = [dec.dec.devise_facture for dec in c.decs]
    f_code, f_multi, f_ill, f_vals = cote(fv)
    d_code, d_multi, d_ill, d_vals = cote(dv)
    illisible = f_ill or d_ill
    raison = None
    if f_code is None or d_code is None:
        if f_ill is not None or d_ill is not None:
            raison = ctx.raison_inutilisable(f_ill if f_ill is not None else d_ill)
        elif not f_multi and not d_multi:
            raison = RaisonCode.valeur_absente
    if f_multi or d_multi:
        situation = "multiples"
    elif f_code is None or d_code is None:
        situation = "incertaine"
        if raison is None:
            raison = RaisonCode.valeur_absente
    elif f_code == d_code:
        situation = "meme"
    elif d_code == "EUR":
        situation = "converti"
    else:
        situation = "differente"
    return Devises(f_code, d_code, tuple(f_vals), tuple(d_vals), situation, illisible, raison)


# --- Taux de change (§8.7) ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Taux:
    """Taux imprimé d'un couple. ``motif`` : ``absent``, ``illisible``, ``incoherent`` (taux différents
    entre les déclarations du couple) ou ``None`` (taux exploitable)."""

    valeurs: tuple[ValeurSourcee, ...] = ()
    taux: Decimal | None = None
    sens: TauxChangeSens | None = None
    sens_lu: bool = False
    motif: str | None = None
    raison: RaisonCode | None = None

    @property
    def exploitable(self) -> bool:
        return self.motif is None and self.taux is not None

    def eur_par(self, sens: TauxChangeSens | None = None) -> Decimal | None:
        s = sens or self.sens
        if not self.exploitable or s is None:
            return None
        assert self.taux is not None
        return eur_par_devise(self.taux, s)

    def texte(self, devise: str | None) -> str:
        if self.taux is None:
            return ""
        t = format_nombre(self.taux)
        if self.sens is TauxChangeSens.eur_par_devise:
            return f"1 {devise} = {t} EUR"
        if self.sens is TauxChangeSens.devise_par_eur:
            return f"1 EUR = {t} {devise}"
        return f"{t} (sens non imprimé)"


def _taux(ctx: ControlContext, c: Couple, devise: str | None) -> Taux:
    vals = [dec.dec.taux_change for dec in c.decs]
    if all(v is None or not v.est_lisible for v in vals):
        return Taux(motif="absent", raison=RaisonCode.valeur_absente)
    lus: list[ValeurSourcee] = []
    for v in vals:
        if not ctx.utilisable(v):
            return Taux(motif="illisible", raison=ctx.raison_inutilisable(v))
        assert v is not None
        lus.append(v)
    nombres = {_decimal(v) for v in lus}
    if None in nombres or Decimal(0) in nombres:
        return Taux(tuple(lus), motif="illisible", raison=RaisonCode.valeur_absente)
    if len(nombres) > 1:
        return Taux(tuple(lus), motif="incoherent", raison=RaisonCode.valeur_absente)
    t = nombres.pop()
    assert t is not None
    # Sens : imprimé (non dérivé) si possible, sinon valeur dérivée, sinon taux de référence (§8.7).
    sens_vals = [dec.dec.taux_change_sens for dec in c.decs]
    sens_set = set()
    lu = True
    for sv in sens_vals:
        if not ctx.utilisable(sv):
            sens_set = set()
            break
        assert sv is not None
        try:
            sens_set.add(TauxChangeSens(sv.valeur))
        except ValueError:
            sens_set = set()
            break
        lu = lu and sv.methode.value != "derive"
    if len(sens_set) == 1:
        return Taux(tuple(lus), t, sens_set.pop(), lu)
    d = _date_acceptation(ctx, c)
    ref = ctx.taux_bce(devise, d) if devise and d else None
    if ref:
        ecart_dpe = abs(t - ref) / ref
        ecart_epd = abs(Decimal(1) / t - ref) / ref
        sens = TauxChangeSens.devise_par_eur if ecart_dpe <= ecart_epd else TauxChangeSens.eur_par_devise
        return Taux(tuple(lus), t, sens, False)
    return Taux(tuple(lus), t, None, False)


# --- Explications (condition 7 de §8.5.1) ---------------------------------------------------------------


def _explication_version(ctx: ControlContext, c: Couple, accepte: Callable[[Decimal], bool]) -> RaisonCode | None:
    """Une autre version (rectificative ou initiale) du même MRN dont le montant concorde : ``a_verifier``."""
    if len(c.decs) != 1:
        return None
    for autre in ctx.versions_anterieures(c.decs[0]):
        v = autre.dec.montant_total_facture
        if ctx.utilisable(v):
            assert v is not None
            d = _decimal(v)
            if d is not None and accepte(d):
                return RaisonCode.version_rectificative
    return None


def _lignes_pied(ctx: ControlContext, c: Couple) -> list[ValeurSourcee]:
    out = []
    for fc in c.fcs:
        for st in fc.fc.sous_totaux:
            if st.type in _DEUX_PIEDS and ctx.utilisable(st.montant):
                assert st.montant is not None
                out.append(st.montant)
    return out[:_MAX_LIGNES_PIED]


def _explique_par_pied(
    pieds: Sequence[ValeurSourcee], ecart: Decimal, tolerance: Decimal, facteur: Decimal = Decimal(1)
) -> list[ValeurSourcee]:
    """Lignes de pied dont la somme (en valeur absolue) égale ``|écart|`` dans la tolérance (A4 ; A5 avec
    ``facteur`` = EUR par unité de devise de la facture, la somme convertie arrondie au centime, D-2202)."""
    montants = [(v, abs(v.decimal_signe())) for v in pieds if _decimal(v) is not None]
    for n in range(1, len(montants) + 1):
        for combi in combinations(montants, n):
            somme = sum((m for _, m in combi), Decimal(0))
            if facteur != 1:
                somme = arrondi_centime(somme * facteur)
            if abs(abs(ecart) - somme) <= tolerance:
                return [v for v, _ in combi]
    return []


# =====================================================================================================
# A1 — Entité importatrice
# =====================================================================================================


def _tva_txt(v: ValeurSourcee | None) -> str:
    return f" (TVA {v.valeur})" if v is not None and v.valeur else ""


def _a1(ctx: ControlContext, c: Couple) -> list[ResultatControle]:
    cid, unite = "A1", c.unite
    commun = dict(unite=unite, documents=c.doc_ids)
    if not ctx.entites:
        return [ctx.non_verifiable(cid, RaisonCode.valeur_absente, details={"motif": "aucune_entite_client"}, **commun)]
    imports = [dec.dec.importateur.tva for dec in c.decs]
    for v in imports:
        if not ctx.utilisable(v):
            return [ctx.non_verifiable(cid, ctx.raison_inutilisable(v), **commun)]
    tva_imp = [v for v in imports if v is not None]
    e_d_set = {e.id: e for e in (ctx.entite_par_tva(v.valeur) for v in tva_imp) if e is not None}
    clients_dec: dict = {}
    for dec in c.decs:
        clients_dec.update(entites_client_declaration(ctx, dec))
    idents = [identifier_facture(ctx, fc) for fc in c.fcs]
    e_f_set = {i.entite.id: i.entite for i in idents if i.entite is not None}
    v_fc = [i.valeur or i.tva_hors_client for i in idents]
    valeurs_cles = [v for v in v_fc if v is not None] + tva_imp
    preuves = [preuve(v, RolePreuve.valeur_a) for v in v_fc if v is not None]
    preuves += [preuve(v, RolePreuve.valeur_b) for v in tva_imp]
    ref_f, ref_d = _refs_fc(c.fcs, [i.valeur or i.tva_hors_client for i in idents]), _refs_dec(c.decs, tva_imp)
    details = {
        "entite_facture": sorted(e_f_set), "entite_declaration": sorted(e_d_set),
        "methode_facture": [i.methode for i in idents],
    }

    def constat(libelle: str, raisons: Iterable[RaisonCode] = ()) -> list[ResultatControle]:
        cl = ctx.classify(cid, ecart=None, tolerance=None, seuil_certitude=None, valeurs_cles=valeurs_cles,
                          documents=c.doc_ids, raisons_supplementaires=list(raisons))
        return [ctx.constat(cid, cl, libelle=libelle, prochaine_action=ACTION_A1, preuves=preuves,
                            entrees={f"tva_importateur_{i}": v for i, v in enumerate(tva_imp)},
                            attendu=",".join(sorted(e_f_set)) or None, constate=",".join(sorted(e_d_set)) or None,
                            details=details, **commun)]

    # Plusieurs TVA du client sur la déclaration, ou plusieurs entités entre factures / déclarations.
    if len(clients_dec) > 1 or len(e_d_set) > 1 or len(e_f_set) > 1:
        noms = sorted({e.raison_sociale for e, _ in clients_dec.values()} | {e.raison_sociale for e in e_d_set.values()}
                      | {e.raison_sociale for e in e_f_set.values()})
        return constat(
            f"Plusieurs entités du client figurent sur les documents de ce dossier ({', '.join(noms)}) : "
            f"{ref_f} et {ref_d} ne permettent pas de désigner une seule entité.",
            [RaisonCode.plusieurs_entites],
        )
    e_f = next(iter(e_f_set.values()), None)
    e_d = next(iter(e_d_set.values()), None)
    imp_txt = ", ".join(v.valeur or "" for v in tva_imp)
    if e_f is not None and e_d is not None:
        if e_f.id == e_d.id:
            return [ctx.conforme(cid, details=details, **commun)]
        raisons = [] if all(i.par_tva for i in idents) else [RaisonCode.confiance_insuffisante]
        return constat(
            f"{_maj(ref_f)} est adressée à {e_f.raison_sociale}{_tva_txt(idents[0].valeur if idents[0].par_tva else None)} ; "
            f"{ref_d} indique comme importateur {e_d.raison_sociale} (TVA {imp_txt}).",
            raisons,
        )
    if e_f is not None and e_d is None:
        raisons = [] if all(i.par_tva for i in idents) else [RaisonCode.confiance_insuffisante]
        return constat(
            f"{_maj(ref_f)} est adressée à {e_f.raison_sociale} ; {ref_d} indique comme importateur le numéro "
            f"de TVA {imp_txt}, qui n'est celui d'aucune entité du client.",
            raisons,
        )
    if e_d is not None:  # E_f non identifiée
        hors = next((i.tva_hors_client for i in idents if i.tva_hors_client is not None), None)
        if hors is not None:
            libelle = (
                f"Le numéro de TVA lu dans le pavé acheteur de {ref_f} ({hors.valeur}) n'est celui d'aucune "
                f"entité du client (il peut s'agir de celui d'un tiers) ; {ref_d} indique comme importateur "
                f"{e_d.raison_sociale} (TVA {imp_txt})."
            )
            return constat(libelle, [RaisonCode.controle_signal_seulement])
        return constat(
            f"Le pavé acheteur de {ref_f} ne permet pas d'identifier une entité du client ; {ref_d} indique "
            f"comme importateur {e_d.raison_sociale} (TVA {imp_txt}).",
            [RaisonCode.confiance_insuffisante],
        )
    return constat(
        f"Ni {ref_f} ni {ref_d} (TVA importateur {imp_txt}) n'identifient une entité du client.",
        [RaisonCode.confiance_insuffisante],
    )


@control("A1")
def a1_entite_importatrice(ctx: ControlContext) -> list[ResultatControle]:
    """A1 — entité de la facture (TVA, SIREN, alias ; destinataire à défaut) contre importateur déclaré."""
    return _par_couple(ctx, "A1", _a1)


# =====================================================================================================
# A2 — Référence de la facture citée sur la déclaration
# =====================================================================================================


def _est_ref_facture(type_code: ValeurSourcee | None) -> bool:
    if type_code is None or not type_code.valeur:
        return True
    code = norm_ref(type_code.valeur)
    return any(x in code for x in _CODES_FACTURE)


def _a2(ctx: ControlContext, c: Couple) -> list[ResultatControle]:
    cid, unite = "A2", c.unite
    commun = dict(unite=unite, documents=c.doc_ids)
    numeros = [fc.fc.numero for fc in c.fcs]
    for v in numeros:
        if not ctx.utilisable(v):
            return [ctx.non_verifiable(cid, ctx.raison_inutilisable(v), **commun)]
    refs: list[ValeurSourcee] = []
    for dec in c.decs:
        for r in dec.dec.documents_references:
            if _est_ref_facture(r.type_code) and ctx.utilisable(r.reference):
                assert r.reference is not None
                refs.append(r.reference)
        for art in dec.dec.articles:
            refs.extend(v for v in art.references_facture if ctx.utilisable(v))
    entrees = {f"numero_{i}": v for i, v in enumerate(numeros) if v is not None}
    if not refs:
        # Aucune référence de facture citée (§10 A2 : « sinon constat »). On ne conclut que si la liste des
        # documents produits a bien été lue : export structuré, ou au moins une autre référence lue (titre de
        # transport, autoliquidation…). Sinon la section a pu échapper à la lecture : non vérifiable (D-803).
        autres = [r for dec in c.decs for r in dec.dec.documents_references if ctx.utilisable(r.reference)]
        structuree = any(dec.dec.mrn is not None and dec.dec.mrn.est_structuree for dec in c.decs)
        lus = [v for v in numeros if v is not None]
        if not (autres or structuree) or not lus:
            return [ctx.non_verifiable(cid, RaisonCode.valeur_absente,
                                       details={"motif": "aucune_reference_facture"}, **commun)]
        cl = ctx.classify(cid, ecart=None, tolerance=None, seuil_certitude=None, valeurs_cles=lus,
                          documents=c.doc_ids)
        nums = ", ".join(f"{v.valeur} (page {v.page})" if v.page else str(v.valeur) for v in lus)
        cites = ", ".join(dict.fromkeys(
            " ".join(x for x in ((r.type_code.valeur if r.type_code else None), r.reference.valeur) if x)
            for r in autres if r.reference is not None))
        libelle = (
            f"Le numéro de facture commerciale {nums} n'est pas cité sur {_refs_dec(c.decs)} : aucune référence "
            f"de facture ne figure parmi les documents produits"
            + (f" (documents cités : {cites})." if cites else ".")
        )
        return [ctx.constat(
            cid, cl, libelle=libelle, prochaine_action=ACTION_A2,
            preuves=[preuve(v, RolePreuve.valeur_a) for v in lus]
            + [preuve(r.reference, RolePreuve.valeur_b) for r in autres if r.reference is not None],
            entrees=entrees, attendu=",".join(v.valeur or "" for v in lus), constate=cites or "aucune",
            details={"motif": "aucune_reference_facture"}, **commun,
        )]
    absents = [(fc, v) for fc, v in zip(c.fcs, numeros, strict=True)
               if v is not None and not any(ref_compatibles(v.valeur, r.valeur) for r in refs)]
    if not absents:
        return [ctx.conforme(cid, entrees=entrees, **commun)]
    cl = ctx.classify(cid, ecart=None, tolerance=None, seuil_certitude=None,
                      valeurs_cles=[v for _, v in absents], documents=c.doc_ids)
    cites = ", ".join(dict.fromkeys(r.valeur or "" for r in refs))
    nums = ", ".join(f"{v.valeur} (page {v.page})" if v.page else str(v.valeur) for _, v in absents)
    libelle = (
        f"Le numéro de facture commerciale {nums} ne figure pas parmi les références de facture citées sur "
        f"{_refs_dec(c.decs, [refs[0]])} : {cites}."
    )
    return [ctx.constat(
        cid, cl, libelle=libelle, prochaine_action=ACTION_A2,
        preuves=[preuve(v, RolePreuve.valeur_a) for _, v in absents] + [preuve(r, RolePreuve.valeur_b) for r in refs],
        entrees=entrees, attendu=",".join(v.valeur or "" for _, v in absents), constate=cites, **commun,
    )]


@control("A2")
def a2_reference_facture(ctx: ControlContext) -> list[ResultatControle]:
    """A2 — le numéro de facture est-il cité (``ref_compatibles``) sur la déclaration ? Signal seulement."""
    return _par_couple(ctx, "A2", _a2)


# =====================================================================================================
# Valeurs (A3–A7)
# =====================================================================================================


@dataclass(frozen=True)
class Montants:
    fc_vals: list[ValeurSourcee]
    total: Decimal
    dec_vals: list[ValeurSourcee]
    declare: Decimal


def _montants(ctx: ControlContext, c: Couple) -> Montants | RaisonCode:
    f = _lire_somme(ctx, [fc.fc.total_facture for fc in c.fcs])
    if isinstance(f, RaisonCode):
        return f
    d = _lire_somme(ctx, [dec.dec.montant_total_facture for dec in c.decs])
    if isinstance(d, RaisonCode):
        return d
    return Montants(f[0], f[1], d[0], d[1])


def _a6_declenche(ctx: ControlContext, c: Couple, dv: Devises, m: Montants, t: Taux) -> bool | None:
    """A6 : déclaration en EUR, même nombre que le total facture (dans ``T_VALEUR``) alors que le taux imprimé
    s'écarte de 1 de plus de 2 % ou que le taux de référence de la devise s'écarte de 1 de plus de 10 %.
    ``None`` si l'on ne peut pas trancher (même nombre, ni taux imprimé ni taux de référence)."""
    if dv.situation != "converti":
        return False
    tol = ctx.tol.t_valeur(m.total, m.declare)
    if abs(m.declare - m.total) > tol:
        return False

    def discriminant(eur_par_unite: Decimal) -> bool:
        # « Même nombre » n'a de sens que si la conversion aurait déplacé le montant au-delà de T_VALEUR
        # (petits montants : 2,28 USD convertis restent à moins d'une unité de 2,28) — D-807.
        return abs(m.total * eur_par_unite - m.total) > tol

    p = ctx.profil
    if t.exploitable:
        assert t.taux is not None
        if abs(t.taux - 1) > p.a6_ecart_taux_min:
            return all(discriminant(eur) for s in TauxChangeSens if (eur := t.eur_par(s)) is not None)
    d = _date_acceptation(ctx, c)
    ref = ctx.taux_bce(dv.fc, d) if dv.fc and d else None
    if ref:
        return abs(ref - 1) > p.a6_ecart_reference_min and discriminant(Decimal(1) / ref)
    return None if not t.exploitable else False


def _evaluer_a5(ctx: ControlContext, c: Couple, dv: Devises, m: Montants, t: Taux) -> dict:
    """Calcul A5 partagé avec A3 : écart selon le sens retenu, écart dans l'autre sens, conformité."""
    tol = ctx.tol
    ecarts = {}
    for s in TauxChangeSens:
        eur = t.eur_par(s)
        assert eur is not None
        attendu = arrondi_centime(m.total * eur)
        ecarts[s] = (attendu, m.declare - attendu)
    # Sens inconnu : on retient le sens qui donne le plus petit écart (lecture prudente).
    sens = t.sens if t.sens is not None else min(TauxChangeSens, key=lambda s: abs(ecarts[s][1]))
    autre = next(s for s in TauxChangeSens if s is not sens)
    attendu, ecart = ecarts[sens]
    t_conv = tol.t_conversion(m.declare, attendu)
    conforme = abs(ecart) <= t_conv
    autre_conforme = False
    if not conforme and not t.sens_lu:
        a_att, a_ecart = ecarts[autre]
        if abs(a_ecart) <= tol.t_conversion(m.declare, a_att):
            autre_conforme = True
    return dict(sens=sens, autre=autre, attendu=attendu, ecart=ecart, t=t_conv,
                s=tol.s_conversion(m.declare, attendu), conforme=conforme or autre_conforme,
                sens_conforme=autre if autre_conforme else sens, ecarts=ecarts)


def _a3(ctx: ControlContext, c: Couple) -> list[ResultatControle]:
    cid = "A3"
    dv = _devises(ctx, c)
    commun = dict(unite=c.unite, documents=c.doc_ids,
                  entrees={f"devise_{i}": v for i, v in enumerate(dv.valeurs)},
                  attendu=dv.fc, constate=dv.dec)
    if dv.situation == "incertaine":
        return [ctx.non_verifiable(cid, dv.raison_illisible or RaisonCode.valeur_absente, **commun)]
    if dv.situation == "meme":
        return [ctx.conforme(cid, **commun)]
    if dv.situation == "converti":
        m = _montants(ctx, c)
        t = _taux(ctx, c, dv.fc)
        if not isinstance(m, RaisonCode) and t.exploitable and not _a6_declenche(ctx, c, dv, m, t) \
                and _evaluer_a5(ctx, c, dv, m, t)["conforme"]:
            return [ctx.conforme(cid, raison_code=RaisonCode.montant_converti, **commun)]
        return [ctx.non_applicable(cid, RaisonCode.montant_converti, details={"couvert_par": "A5, A6, A7"}, **commun)]
    # multiples ou differente : constat
    raisons = [] if dv.iso_lus else [RaisonCode.devise_incertaine]
    if dv.situation == "multiples":
        raisons = [RaisonCode.devise_incertaine]
        codes_f = sorted({(v.valeur or "").upper() for v in dv.fc_vals})
        codes_d = sorted({(v.valeur or "").upper() for v in dv.dec_vals})
        libelle = (
            f"Les documents rapprochés ne sont pas libellés dans une seule devise : {_refs_fc(c.fcs, dv.fc_vals)} "
            f"indique {', '.join(codes_f)} ; {_refs_dec(c.decs, dv.dec_vals)} indique {', '.join(codes_d)}."
        )
    else:
        libelle = (
            f"{_maj(_refs_fc(c.fcs, dv.fc_vals))} est libellée en {dv.fc} ; {_refs_dec(c.decs, dv.dec_vals)} "
            f"indique comme devise de facturation {dv.dec}."
        )
    cl = ctx.classify(cid, ecart=None, tolerance=None, seuil_certitude=None, valeurs_cles=dv.valeurs,
                      documents=c.doc_ids, raisons_supplementaires=raisons)
    preuves = [preuve(v, RolePreuve.valeur_a) for v in dv.fc_vals] + [preuve(v, RolePreuve.valeur_b) for v in dv.dec_vals]
    return [ctx.constat(cid, cl, libelle=libelle, prochaine_action=ACTION_A3, preuves=preuves, **commun)]


@control("A3")
def a3_devise(ctx: ControlContext) -> list[ResultatControle]:
    """A3 — devise de la facture contre monnaie de facturation déclarée (délégué à A5 si déclaration en EUR)."""
    return _par_couple(ctx, "A3", _a3)


def _a4_allocations(ctx: ControlContext, c: Couple, dv: Devises) -> list[ResultatControle]:
    """A4, sous-contrôle ``allocation`` : montant déclaré d'une déclaration contre le montant explicitement
    alloué de la facture (facture répartie sur plusieurs déclarations, même devise)."""
    if len(c.decs) < 2:
        return []
    out = []
    tol = ctx.tol
    for a in c.allocations:
        dec = next((d for d in c.decs if d.id == a.cible_document_id), None)
        fc = next((f for f in c.fcs if f.id == a.source_document_id), None)
        if dec is None or fc is None or a.montant_alloue is None:
            continue
        unite = cle_unite(fc=[fc.id], dec=[dec.id])
        v = dec.dec.montant_total_facture
        commun = dict(unite=unite, sous_controle="allocation", documents=[fc.id, dec.id])
        if not ctx.utilisable(v):
            out.append(ctx.non_verifiable("A4", ctx.raison_inutilisable(v), **commun))
            continue
        assert v is not None
        declare = v.decimal_signe()
        ecart = declare - a.montant_alloue
        t, s = tol.t_valeur(a.montant_alloue, declare), tol.s_valeur(a.montant_alloue, declare)
        commun.update(attendu=a.montant_alloue, constate=declare, ecart=ecart, tolerance=t, seuil_certitude=s,
                      entrees={"montant_declare": v})
        if abs(ecart) <= t:
            out.append(ctx.conforme("A4", **commun))
            continue
        cl = ctx.classify("A4", ecart=ecart, tolerance=t, seuil_certitude=s, valeurs_cles=[v],
                          documents=[fc.id, dec.id], allocations=[a],
                          confusion=[Confusion(v, autre=a.montant_alloue, tolerance=t)])
        taux = _taux(ctx, Couple((fc,), (dec,)), dv.fc)
        montant = montant_ecart_documentaire(declare, a.montant_alloue, devise=dv.fc, taux_eur_par_devise=taux.eur_par())
        libelle = (
            f"{_maj(_ref_dec(dec, v))} indique un montant total facturé de {format_montant(declare, dv.fc)} ; "
            f"le montant de {_ref_fc(fc)} alloué à cette déclaration est de {format_montant(a.montant_alloue, dv.fc)}, "
            f"soit un écart de {format_montant(ecart, dv.fc)}."
        )
        out.append(ctx.constat(
            "A4", cl, libelle=libelle, prochaine_action=ACTION_A4, montant=montant, composante=Composante.valeur,
            preuves=[preuve(v, RolePreuve.valeur_b),
                     preuve(None, RolePreuve.valeur_a, calcul=f"montant alloué : {format_montant(a.montant_alloue, dv.fc)}")],
            **commun,
        ))
    return out


def _a4(ctx: ControlContext, c: Couple) -> list[ResultatControle]:
    cid = "A4"
    dv = _devises(ctx, c)
    commun: dict = dict(unite=c.unite, documents=c.doc_ids)
    if dv.situation == "converti":
        return [ctx.non_applicable(cid, RaisonCode.montant_converti, details={"couvert_par": "A5"}, **commun)]
    if dv.situation == "differente":
        return [ctx.non_applicable(cid, RaisonCode.couvert_par_autre_controle, details={"couvert_par": "A3"}, **commun)]
    if dv.situation == "multiples":
        return [ctx.non_verifiable(cid, RaisonCode.devise_incertaine, **commun)]
    m = _montants(ctx, c)
    if isinstance(m, RaisonCode):
        return [ctx.non_verifiable(cid, m, **commun)]
    tol = ctx.tol
    devise = dv.fc or dv.dec
    ecart = m.declare - m.total
    t, s = tol.t_valeur(m.total, m.declare), tol.s_valeur(m.total, m.declare)
    entrees = {f"total_facture_{i}": v for i, v in enumerate(m.fc_vals)}
    entrees.update({f"montant_declare_{i}": v for i, v in enumerate(m.dec_vals)})
    commun.update(entrees=entrees, attendu=m.total, constate=m.declare, ecart=ecart, tolerance=t, seuil_certitude=s)
    raisons: list[RaisonCode] = []
    details: dict = {}
    taux = _taux(ctx, c, dv.fc)
    if dv.situation == "incertaine":
        # Devise illisible d'un côté : au mieux « à vérifier » (A3). Deux lectures possibles : même devise,
        # ou montant converti au taux imprimé.
        details["devise_incertaine"] = True
        if abs(ecart) <= t:
            return [ctx.conforme(cid, details={**details, "hypothese": "meme_devise"}, **commun)]
        if dv.fc not in (None, "EUR") and taux.exploitable:
            for sens in ([taux.sens] if taux.sens else list(TauxChangeSens)):
                eur = taux.eur_par(sens)
                assert eur is not None
                att = arrondi_centime(m.total * eur)
                if abs(m.declare - att) <= tol.t_conversion(m.declare, att):
                    return [ctx.conforme(cid, details={**details, "hypothese": "conversion"}, **commun)]
        raisons.append(RaisonCode.devise_incertaine)
    elif abs(ecart) <= t:
        return [ctx.conforme(cid, **commun), *_a4_allocations(ctx, c, dv)]

    pieds = _lignes_pied(ctx, c)
    expliquent = _explique_par_pied(pieds, ecart, t)
    explication = None
    if expliquent:
        explication = RaisonCode.ecart_explique_par_ligne_de_pied
        details["lignes_de_pied"] = [v.id for v in expliquent]
    else:
        explication = _explication_version(ctx, c, lambda d: abs(d - m.total) <= t)
    confusion = _confusions_somme(m.dec_vals, lambda x: abs(x - m.total) <= t)
    confusion += _confusions_somme(m.fc_vals, lambda x: abs(m.declare - x) <= t)
    cl = ctx.classify(cid, ecart=ecart, tolerance=t, seuil_certitude=s,
                      valeurs_cles=[*m.fc_vals, *m.dec_vals, *dv.valeurs], confusion=confusion,
                      documents=c.doc_ids, explication=explication, raisons_supplementaires=raisons)
    montant = None
    if dv.situation == "meme":
        montant = montant_ecart_documentaire(m.declare, m.total, devise=devise, taux_eur_par_devise=taux.eur_par())
    libelle = (
        f"{_maj(_refs_dec(c.decs, m.dec_vals))} indique un montant total facturé de "
        f"{format_montant(m.declare, dv.dec)} ; {_refs_fc(c.fcs, m.fc_vals)} indique un total de "
        f"{format_montant(m.total, dv.fc)}, soit un écart de {format_montant(ecart, devise)}."
    )
    if expliquent:
        libelle += (
            " Cet écart correspond à la ou les lignes de pied de la facture : "
            + ", ".join(f"{format_montant(abs(v.decimal_signe()), dv.fc)} (page {v.page})" for v in expliquent) + "."
        )
    preuves = [preuve(v, RolePreuve.valeur_a) for v in m.fc_vals] + [preuve(v, RolePreuve.valeur_b) for v in m.dec_vals]
    preuves += [preuve(v, RolePreuve.contexte) for v in expliquent]
    resultat = ctx.constat(
        cid, cl, libelle=libelle, prochaine_action=ACTION_A4_PIED if expliquent else ACTION_A4, montant=montant,
        composante=Composante.valeur, preuves=preuves, details=details, **commun,
    )
    return [resultat, *_a4_allocations(ctx, c, dv)]


@control("A4")
def a4_valeur_facturee(ctx: ControlContext) -> list[ResultatControle]:
    """A4 — total facture contre montant total facturé déclaré, même devise (``T_VALEUR`` / ``S_VALEUR``)."""
    return _par_couple(ctx, "A4", _a4)


def _a5(ctx: ControlContext, c: Couple) -> list[ResultatControle]:
    cid = "A5"
    dv = _devises(ctx, c)
    commun: dict = dict(unite=c.unite, documents=c.doc_ids)
    if dv.situation == "multiples":
        return [ctx.non_verifiable(cid, RaisonCode.devise_incertaine, **commun)]
    if dv.situation != "converti":
        couvert = "A3" if dv.situation == "differente" else "A4"
        return [ctx.non_applicable(cid, RaisonCode.couvert_par_autre_controle, details={"couvert_par": couvert},
                                   **commun)]
    m = _montants(ctx, c)
    if isinstance(m, RaisonCode):
        return [ctx.non_verifiable(cid, m, **commun)]
    t = _taux(ctx, c, dv.fc)
    if t.motif == "absent":
        return [ctx.non_applicable(cid, RaisonCode.couvert_par_autre_controle,
                                   details={"couvert_par": "A7", "motif": "taux_absent"}, **commun)]
    if not t.exploitable:
        return [ctx.non_verifiable(cid, t.raison or RaisonCode.valeur_absente, details={"motif": t.motif}, **commun)]
    if _a6_declenche(ctx, c, dv, m, t):
        return [ctx.non_applicable(cid, RaisonCode.couvert_par_autre_controle, details={"couvert_par": "A6"},
                                   **commun)]
    ev = _evaluer_a5(ctx, c, dv, m, t)
    entrees = {f"total_facture_{i}": v for i, v in enumerate(m.fc_vals)}
    entrees.update({f"montant_declare_{i}": v for i, v in enumerate(m.dec_vals)})
    entrees.update({f"taux_{i}": v for i, v in enumerate(t.valeurs)})
    details = {"sens": ev["sens_conforme"].value if ev["conforme"] else ev["sens"].value, "sens_lu": t.sens_lu}
    commun.update(entrees=entrees, attendu=ev["attendu"], constate=m.declare, ecart=arrondi_centime(ev["ecart"]),
                  tolerance=ev["t"], seuil_certitude=ev["s"], details=details)
    if ev["conforme"]:
        return [ctx.conforme(cid, **commun)]
    sens: TauxChangeSens = ev["sens"]
    eur = t.eur_par(sens)
    assert eur is not None and t.taux is not None
    t_conv = ev["t"]
    attendu = ev["attendu"]
    raisons = []
    if not t.sens_lu:
        # §10 A5 : sens dérivé -> certain seulement si l'écart dépasse le seuil dans les deux sens.
        _, ecart_autre = ev["ecarts"][ev["autre"]]
        if abs(ecart_autre) <= ev["s"]:
            raisons.append(RaisonCode.sens_taux_derive)
    taux_v = t.taux
    confusion = _confusions_somme(m.dec_vals, lambda x: abs(x - attendu) <= t_conv)
    confusion += _confusions_somme(
        m.fc_vals, lambda x: abs(m.declare - arrondi_centime(x * eur)) <= t_conv)
    confusion += [
        Confusion(v, accepte=lambda x: x != 0 and abs(m.declare - arrondi_centime(m.total * eur_par_devise(x, sens)))
                  <= t_conv)
        for v in t.valeurs
    ]
    # §8.5.1 condition 7 : une ligne de pied (fret, assurance, emballage, remise ; imprimée ou structurée,
    # p. ex. ``AllowanceCharge`` UBL) convertie au même taux explique l'écart -> à vérifier (D-2202).
    expliquent = _explique_par_pied(_lignes_pied(ctx, c), ev["ecart"], t_conv, facteur=eur)
    if expliquent:
        explication = RaisonCode.ecart_explique_par_ligne_de_pied
        details["lignes_de_pied"] = [v.id for v in expliquent]
    else:
        explication = _explication_version(ctx, c, lambda d: abs(d - attendu) <= t_conv)
    cl = ctx.classify(cid, ecart=ev["ecart"], tolerance=t_conv, seuil_certitude=ev["s"],
                      valeurs_cles=[*m.fc_vals, *m.dec_vals, *t.valeurs, *dv.valeurs], confusion=confusion,
                      documents=c.doc_ids, explication=explication, raisons_supplementaires=raisons)
    affichage = Taux(t.valeurs, taux_v, sens, t.sens_lu)
    calcul = f"{format_montant(m.total, dv.fc)} × {affichage.texte(dv.fc)} = {format_montant(attendu, 'EUR')}"
    libelle = (
        f"{_maj(_refs_dec(c.decs, m.dec_vals))} indique un montant facturé de {format_montant(m.declare, 'EUR')} ; "
        f"le total de {_refs_fc(c.fcs, m.fc_vals)}, {format_montant(m.total, dv.fc)}, converti au taux imprimé sur "
        f"la déclaration ({affichage.texte(dv.fc)}{'' if t.sens_lu else ', sens déduit'}), donne "
        f"{format_montant(attendu, 'EUR')}, soit un écart de {format_montant(ev['ecart'], 'EUR')}."
    )
    if expliquent:
        libelle += (
            " Cet écart correspond, au même taux, à la ou les lignes de pied de la facture : "
            + ", ".join(f"{format_montant(abs(v.decimal_signe()), dv.fc)} (page {v.page})" for v in expliquent) + "."
        )
    preuves = [preuve(v, RolePreuve.valeur_a) for v in m.fc_vals] + [preuve(v, RolePreuve.valeur_b) for v in m.dec_vals]
    preuves += [preuve(v, RolePreuve.operande) for v in t.valeurs]
    preuves.append(preuve(None, RolePreuve.operande, calcul=calcul))
    preuves += [preuve(v, RolePreuve.contexte) for v in expliquent]
    return [ctx.constat(cid, cl, libelle=libelle, prochaine_action=ACTION_A4_PIED if expliquent else ACTION_A5,
                        montant=ev["ecart"],
                        composante=Composante.valeur, preuves=preuves, **commun)]


@control("A5")
def a5_montant_converti(ctx: ControlContext) -> list[ResultatControle]:
    """A5 — montant déclaré en EUR contre total facture (D ≠ EUR) × taux imprimé (sens §8.7)."""
    return _par_couple(ctx, "A5", _a5)


def _a6(ctx: ControlContext, c: Couple) -> list[ResultatControle]:
    cid = "A6"
    dv = _devises(ctx, c)
    commun: dict = dict(unite=c.unite, documents=c.doc_ids)
    if dv.situation == "multiples":
        return [ctx.non_verifiable(cid, RaisonCode.devise_incertaine, **commun)]
    if dv.situation != "converti":
        return [ctx.non_applicable(cid, RaisonCode.couvert_par_autre_controle,
                                   details={"couvert_par": "A3" if dv.situation == "differente" else "A4"}, **commun)]
    m = _montants(ctx, c)
    if isinstance(m, RaisonCode):
        return [ctx.non_verifiable(cid, m, **commun)]
    t = _taux(ctx, c, dv.fc)
    declenche = _a6_declenche(ctx, c, dv, m, t)
    entrees = {f"total_facture_{i}": v for i, v in enumerate(m.fc_vals)}
    entrees.update({f"montant_declare_{i}": v for i, v in enumerate(m.dec_vals)})
    commun.update(entrees=entrees, attendu=m.total, constate=m.declare, tolerance=ctx.tol.t_valeur(m.total, m.declare))
    if declenche is None:
        return [ctx.non_verifiable(cid, RaisonCode.valeur_absente, details={"motif": "taux_inconnu"}, **commun)]
    if not declenche:
        return [ctx.conforme(cid, **commun)]
    p = ctx.profil
    devise_sure = all((v.est_structuree or v.confiance >= p.a6_confiance_devise_min) and _iso_lu(v) for v in dv.fc_vals)
    raisons = [] if devise_sure and t.exploitable else [RaisonCode.devise_incertaine]
    valeurs = [*m.fc_vals, *m.dec_vals, *dv.valeurs, *t.valeurs]
    cl = ctx.classify(cid, ecart=None, tolerance=None, seuil_certitude=None, valeurs_cles=valeurs,
                      documents=c.doc_ids, raisons_supplementaires=raisons)
    eur = t.eur_par()
    montant = arrondi_centime(m.declare - m.total * eur) if eur is not None else None
    if t.exploitable:
        motif = f"alors que la déclaration imprime un taux de change de {t.texte(dv.fc)}"
    else:
        motif = f"alors que le taux de référence indicatif de la devise {dv.fc} s'écarte de 1 de plus de 10 %"
    libelle = (
        f"{_maj(_refs_dec(c.decs, m.dec_vals))} indique un montant facturé de {format_montant(m.declare, 'EUR')} ; "
        f"{_refs_fc(c.fcs, m.fc_vals)} indique {format_montant(m.total, dv.fc)} : le même nombre figure dans deux "
        f"devises différentes, {motif}."
    )
    preuves = [preuve(v, RolePreuve.valeur_a) for v in [*m.fc_vals, *dv.fc_vals]]
    preuves += [preuve(v, RolePreuve.valeur_b) for v in [*m.dec_vals, *dv.dec_vals]]
    preuves += [preuve(v, RolePreuve.operande) for v in t.valeurs]
    return [ctx.constat(cid, cl, libelle=libelle, prochaine_action=ACTION_A6, montant=montant,
                        composante=Composante.valeur, preuves=preuves,
                        ecart=montant, details={"taux_imprime": t.exploitable}, **commun)]


@control("A6")
def a6_montant_sans_conversion(ctx: ControlContext) -> list[ResultatControle]:
    """A6 — montant repris sans conversion : même nombre, devise EUR déclarée, devise de facture ≠ EUR."""
    return _par_couple(ctx, "A6", _a6)


def _a7(ctx: ControlContext, c: Couple) -> list[ResultatControle]:
    cid = "A7"
    dv = _devises(ctx, c)
    commun: dict = dict(unite=c.unite, documents=c.doc_ids)
    if dv.situation == "multiples":
        return [ctx.non_verifiable(cid, RaisonCode.devise_incertaine, **commun)]
    if dv.situation != "converti":
        return [ctx.non_applicable(cid, RaisonCode.couvert_par_autre_controle,
                                   details={"couvert_par": "A3" if dv.situation == "differente" else "A4"}, **commun)]
    m = _montants(ctx, c)
    if isinstance(m, RaisonCode):
        return [ctx.non_verifiable(cid, m, **commun)]
    t = _taux(ctx, c, dv.fc)
    if t.exploitable:
        return [ctx.non_applicable(cid, RaisonCode.couvert_par_autre_controle, details={"couvert_par": "A5"}, **commun)]
    if _a6_declenche(ctx, c, dv, m, t):
        return [ctx.non_applicable(cid, RaisonCode.couvert_par_autre_controle, details={"couvert_par": "A6"}, **commun)]
    d = _date_acceptation(ctx, c)
    ref = ctx.taux_bce(dv.fc, d) if dv.fc and d else None  # devise par EUR
    if not ref or m.total == 0:
        return [ctx.non_verifiable(cid, RaisonCode.valeur_absente, details={"motif": "taux_reference_absent"},
                                   **commun)]
    assert d is not None
    ratio = m.declare * ref / m.total
    bande = ctx.tol.bande_indicative(dv.fc)
    entrees = {f"total_facture_{i}": v for i, v in enumerate(m.fc_vals)}
    entrees.update({f"montant_declare_{i}": v for i, v in enumerate(m.dec_vals)})
    commun.update(entrees=entrees, constate=ratio.quantize(Decimal("0.0001")), attendu=Decimal(1),
                  ecart=(ratio - 1).quantize(Decimal("0.0001")), tolerance=bande,
                  details={"taux_reference": str(ref), "date_reference": d.isoformat()})
    cl = ctx.classify(cid, ecart=ratio - 1, tolerance=bande, seuil_certitude=None,
                      valeurs_cles=[*m.fc_vals, *m.dec_vals], documents=c.doc_ids)
    if cl.niveau is None:
        return [ctx.conforme(cid, **commun)]
    pct = format_pourcentage((ratio * 100).quantize(Decimal(1)))
    libelle = (
        f"{_maj(_refs_dec(c.decs, m.dec_vals))} indique un montant facturé de {format_montant(m.declare, 'EUR')} "
        f"sans taux de change imprimé ; {_refs_fc(c.fcs, m.fc_vals)} indique {format_montant(m.total, dv.fc)}. "
        f"Au taux de référence indicatif du {_date_fr(d)} (1 EUR = {format_nombre(ref)} {dv.fc}), le montant "
        f"déclaré représente {pct} de la contre-valeur du total facture, hors de la fourchette de "
        f"± {format_pourcentage((bande * 100).normalize())}. Aucun montant n'est calculé au taux indicatif."
    )
    preuves = [preuve(v, RolePreuve.valeur_a) for v in m.fc_vals] + [preuve(v, RolePreuve.valeur_b) for v in m.dec_vals]
    return [ctx.constat(cid, cl, libelle=libelle, prochaine_action=ACTION_A7, preuves=preuves, **commun)]


@control("A7")
def a7_ordre_de_grandeur(ctx: ControlContext) -> list[ResultatControle]:
    """A7 — sans taux imprimé : ratio déclaré / (total × taux de référence) hors de ``1 ± BANDE_INDICATIVE``.
    Signal seulement, jamais de montant."""
    return _par_couple(ctx, "A7", _a7)


# =====================================================================================================
# A8 — Incoterm
# =====================================================================================================


def _incoterm(ctx: ControlContext, v: ValeurSourcee | None) -> str | None:
    if not ctx.utilisable(v):
        return None
    assert v is not None
    lu = parse_incoterm(v.valeur)
    return lu.code if lu else None


def _a8(ctx: ControlContext, c: Couple) -> list[ResultatControle]:
    cid = "A8"
    commun: dict = dict(unite=c.unite, documents=c.doc_ids)
    fv = [fc.fc.incoterm for fc in c.fcs]
    dv = [dec.dec.incoterm for dec in c.decs]
    for v in [*fv, *dv]:
        if _incoterm(ctx, v) is None:
            raison = ctx.raison_inutilisable(v) if not ctx.utilisable(v) else RaisonCode.valeur_absente
            return [ctx.non_verifiable(cid, raison, **commun)]
    fvals = [v for v in fv if v is not None]
    dvals = [v for v in dv if v is not None]
    codes_f = sorted({_incoterm(ctx, v) or "" for v in fvals})
    codes_d = sorted({_incoterm(ctx, v) or "" for v in dvals})
    commun.update(attendu=",".join(codes_f), constate=",".join(codes_d),
                  entrees={**{f"incoterm_facture_{i}": v for i, v in enumerate(fvals)},
                           **{f"incoterm_declaration_{i}": v for i, v in enumerate(dvals)}})
    if codes_f == codes_d and len(codes_f) == 1:
        return [ctx.conforme(cid, **commun)]
    cl = ctx.classify(cid, ecart=None, tolerance=None, seuil_certitude=None, valeurs_cles=[*fvals, *dvals],
                      documents=c.doc_ids)
    libelle = (
        f"{_maj(_refs_fc(c.fcs, fvals))} indique l'Incoterm {', '.join(codes_f)} ; {_refs_dec(c.decs, dvals)} "
        f"indique {', '.join(codes_d)}."
    )
    preuves = [preuve(v, RolePreuve.valeur_a) for v in fvals] + [preuve(v, RolePreuve.valeur_b) for v in dvals]
    return [ctx.constat(cid, cl, libelle=libelle, prochaine_action=ACTION_A8, preuves=preuves, **commun)]


@control("A8")
def a8_incoterm(ctx: ControlContext) -> list[ResultatControle]:
    """A8 — codes Incoterm à 3 lettres (lieu non comparé). Signal seulement, avec la phrase de renvoi."""
    return _par_couple(ctx, "A8", _a8)


# =====================================================================================================
# Rapprochement par SH6 (A9, A12)
# =====================================================================================================


def _sh6(ctx: ControlContext, v: ValeurSourcee | None) -> str | None:
    if not ctx.utilisable(v):
        return None
    assert v is not None
    chiffres = re.sub(r"\D", "", v.valeur or "")
    return chiffres[:6] if len(chiffres) >= 6 else None


def _lignes_par_sh6(ctx: ControlContext, c: Couple) -> dict[str, list[tuple[Document, int]]]:
    out: dict[str, list[tuple[Document, int]]] = {}
    for fc in c.fcs:
        for i, ligne in enumerate(fc.fc.lignes):
            code = _sh6(ctx, ligne.code_marchandise_imprime)
            if code:
                out.setdefault(code, []).append((fc, i))
    return out


def _articles_par_sh6(ctx: ControlContext, c: Couple) -> dict[str, list[tuple[Document, int]]]:
    out: dict[str, list[tuple[Document, int]]] = {}
    for dec in c.decs:
        for i, art in enumerate(dec.dec.articles):
            code = _sh6(ctx, art.code_marchandise)
            if code:
                out.setdefault(code, []).append((dec, i))
    return out


def _article_txt(dec: Document, i: int) -> str:
    art = dec.dec.articles[i]
    num = art.numero_article.valeur if art.numero_article is not None and art.numero_article.valeur else str(i + 1)
    return f"article {num}"


# =====================================================================================================
# A9 — Quantités
# =====================================================================================================


def _code_unite(v: ValeurSourcee) -> str | None:
    if not v.unite:
        return None
    code = normalize_unit(v.unite).code
    return None if code == UNITE_INCONNUE else code


def _comparer_quantites(
    ctx: ControlContext, c: Couple, unite: str, sous: str, fvals: list[ValeurSourcee | None],
    dvals: list[ValeurSourcee | None], intro: str,
) -> ResultatControle:
    cid = "A9"
    commun: dict = dict(unite=unite, sous_controle=sous, documents=c.doc_ids)
    f = _lire_somme(ctx, fvals)
    if isinstance(f, RaisonCode):
        return ctx.non_verifiable(cid, f, **commun)
    d = _lire_somme(ctx, dvals)
    if isinstance(d, RaisonCode):
        return ctx.non_verifiable(cid, d, **commun)
    (fl, ft), (dl, dt) = f, d
    unites = {_code_unite(v) for v in [*fl, *dl]}
    if len(unites) != 1 or None in unites:
        return ctx.non_verifiable(cid, RaisonCode.unites_differentes, details={"unites": sorted(u or "?" for u in unites)},
                                  **commun)
    code = unites.pop()
    t = ctx.tol.t_quantite(code, ft, dt)
    ecart = dt - ft
    commun.update(attendu=ft, constate=dt, ecart=ecart, tolerance=t,
                  entrees={**{f"quantite_facture_{i}": v for i, v in enumerate(fl)},
                           **{f"quantite_declaration_{i}": v for i, v in enumerate(dl)}},
                  details={"unite_quantite": code})
    if abs(ecart) <= t:
        return ctx.conforme(cid, **commun)
    confusion = _confusions_somme(dl, lambda x: abs(x - ft) <= t) + _confusions_somme(fl, lambda x: abs(dt - x) <= t)
    cl = ctx.classify(cid, ecart=ecart, tolerance=t, seuil_certitude=None, valeurs_cles=[*fl, *dl],
                      confusion=confusion, documents=c.doc_ids)
    lib_u = _unite_lib(code)
    libelle = (
        f"{intro}{_refs_fc(c.fcs, fl)} indique une quantité de {format_nombre(ft)} {lib_u} ; "
        f"{_refs_dec(c.decs, dl)} indique {format_nombre(dt)} {lib_u}."
    )
    preuves = [preuve(v, RolePreuve.valeur_a) for v in fl] + [preuve(v, RolePreuve.valeur_b) for v in dl]
    return ctx.constat(cid, cl, libelle=libelle, prochaine_action=ACTION_A9, preuves=preuves, **commun)


def _a9(ctx: ControlContext, c: Couple) -> list[ResultatControle]:
    lignes, articles = _lignes_par_sh6(ctx, c), _articles_par_sh6(ctx, c)
    communs = sorted(set(lignes) & set(articles))
    if communs:
        out = []
        for code in communs:
            fvals: list[ValeurSourcee | None] = [fc.fc.lignes[i].quantite for fc, i in lignes[code]]
            dvals: list[ValeurSourcee | None] = [dec.dec.articles[i].quantite_unite_supplementaire
                                                 for dec, i in articles[code]]
            arts = ", ".join(_article_txt(dec, i) for dec, i in articles[code])
            out.append(_comparer_quantites(
                ctx, c, cle_unite(fc=[d.id for d in c.fcs], dec=[d.id for d in c.decs], sh6=code), "sh6",
                fvals, dvals, f"Pour le code SH6 {code} ({arts}), ",
            ))
        return out
    fvals = [fc.fc.quantite_totale for fc in c.fcs]
    if not all(ctx.utilisable(v) for v in fvals):
        fvals = [ligne.quantite for fc in c.fcs for ligne in fc.fc.lignes]
    dvals = [art.quantite_unite_supplementaire for dec in c.decs for art in dec.dec.articles]
    return [_comparer_quantites(ctx, c, c.unite, "total", fvals, dvals, "Au total, ")]


@control("A9")
def a9_quantites(ctx: ControlContext) -> list[ResultatControle]:
    """A9 — quantités par code SH6 commun (sinon au total), unités normalisées identiques exigées."""
    return _par_couple(ctx, "A9", _a9)


# =====================================================================================================
# A10, A11 — Masses, colis
# =====================================================================================================


def _supports_ordonnes(ctx: ControlContext) -> list[Document]:
    ordre = {SousTypeSupport.liste_colisage.value: 0, SousTypeSupport.titre_transport.value: 1}
    sup = [d for d in ctx.supports() if d.type is TypeDocument.document_support and isinstance(d.champs, ChampsSupport)]
    return sorted(sup, key=lambda d: ordre.get(d.sous_type or "", 2))


def _valeurs_reference(ctx: ControlContext, c: Couple, champ_fc: str, champ_sup: str) -> list[ValeurSourcee] | None:
    """Valeurs de la facture (toutes les factures du couple), à défaut d'un document support (§10 A10, A11)."""
    vals = [getattr(fc.fc, champ_fc) for fc in c.fcs]
    if all(ctx.utilisable(v) for v in vals):
        return [v for v in vals if v is not None]
    for sup in _supports_ordonnes(ctx):
        v = getattr(sup.sup, champ_sup)
        if ctx.utilisable(v):
            return [v]
    return None


def _valeurs_declaration(
    ctx: ControlContext, c: Couple, champ_total: str | None, champ_article: str
) -> list[ValeurSourcee] | RaisonCode:
    out: list[ValeurSourcee] = []
    for dec in c.decs:
        total = getattr(dec.dec, champ_total) if champ_total else None
        if ctx.utilisable(total):
            assert total is not None
            out.append(total)
            continue
        arts = [getattr(a, champ_article) for a in dec.dec.articles]
        if not arts:
            return ctx.raison_inutilisable(total)
        for v in arts:
            if not ctx.utilisable(v):
                return ctx.raison_inutilisable(v)
            assert v is not None
            out.append(v)
    return out


def _source_txt(ctx: ControlContext, vals: Sequence[ValeurSourcee], c: Couple) -> str:
    docs = {v.document_id for v in vals}
    if docs <= {fc.id for fc in c.fcs}:
        return _refs_fc(c.fcs, [next((v for v in vals if v.document_id == fc.id), None) for fc in c.fcs])
    v = vals[0]
    doc = ctx.document(v.document_id or "")
    nom = "la liste de colisage" if doc is not None and doc.sous_type == SousTypeSupport.liste_colisage.value \
        else "le titre de transport" if doc is not None and doc.sous_type == SousTypeSupport.titre_transport.value \
        else "le document support"
    return nom + (f" (page {v.page})" if v.page else "")


def _a10(ctx: ControlContext, c: Couple) -> list[ResultatControle]:
    cid = "A10"
    out = []
    for sous, champ_fc, champ_sup, total_dec, champ_art, nom in (
        ("nette", "masse_nette_totale", "masse_nette", None, "masse_nette", "masse nette"),
        ("brute", "masse_brute_totale", "masse_brute", "masse_brute_totale", "masse_brute", "masse brute"),
    ):
        commun: dict = dict(unite=c.unite, sous_controle=sous, documents=c.doc_ids)
        ref = _valeurs_reference(ctx, c, champ_fc, champ_sup)
        if ref is None:
            out.append(ctx.non_verifiable(cid, RaisonCode.valeur_absente, **commun))
            continue
        decv = _valeurs_declaration(ctx, c, total_dec, champ_art)
        if isinstance(decv, RaisonCode):
            out.append(ctx.non_verifiable(cid, decv, **commun))
            continue
        fs, ds = _lire_somme(ctx, ref), _lire_somme(ctx, decv)
        if isinstance(fs, RaisonCode) or isinstance(ds, RaisonCode):
            out.append(ctx.non_verifiable(cid, RaisonCode.valeur_absente, **commun))
            continue
        a, b = fs[1], ds[1]
        t = ctx.tol.t_masse(a, b)
        ecart = b - a
        commun["documents"] = list(dict.fromkeys([*c.doc_ids, *(v.document_id for v in ref if v.document_id)]))
        commun.update(attendu=a, constate=b, ecart=ecart, tolerance=t,
                      entrees={**{f"masse_reference_{i}": v for i, v in enumerate(ref)},
                               **{f"masse_declaration_{i}": v for i, v in enumerate(decv)}})
        if abs(ecart) <= t:
            out.append(ctx.conforme(cid, **commun))
            continue
        confusion = _confusions_somme(decv, lambda x, a=a, t=t: abs(x - a) <= t)
        confusion += _confusions_somme(ref, lambda x, b=b, t=t: abs(b - x) <= t)
        cl = ctx.classify(cid, ecart=ecart, tolerance=t, seuil_certitude=None, valeurs_cles=[*ref, *decv],
                          confusion=confusion, documents=commun["documents"])
        libelle = (
            f"{_maj(_source_txt(ctx, ref, c))} indique une {nom} de {format_nombre(a)} kg ; "
            f"{_refs_dec(c.decs, decv)} indique {format_nombre(b)} kg (écart de {format_nombre(ecart)} kg)."
        )
        preuves = [preuve(v, RolePreuve.valeur_a) for v in ref] + [preuve(v, RolePreuve.valeur_b) for v in decv]
        out.append(ctx.constat(cid, cl, libelle=libelle, prochaine_action=ACTION_A10, preuves=preuves, **commun))
    return out


@control("A10")
def a10_masses(ctx: ControlContext) -> list[ResultatControle]:
    """A10 — masses nette et brute (facture, à défaut liste de colisage ou titre de transport) contre la
    déclaration (``T_MASSE``), séparément. Signal seulement."""
    return _par_couple(ctx, "A10", _a10)


def _a11(ctx: ControlContext, c: Couple) -> list[ResultatControle]:
    cid = "A11"
    commun: dict = dict(unite=c.unite, documents=c.doc_ids)
    ref = _valeurs_reference(ctx, c, "nombre_colis", "nombre_colis")
    if ref is None:
        return [ctx.non_verifiable(cid, RaisonCode.valeur_absente, **commun)]
    decv = _valeurs_declaration(ctx, c, "nombre_colis_total", "nombre_colis")
    if isinstance(decv, RaisonCode):
        return [ctx.non_verifiable(cid, decv, **commun)]
    fs, ds = _lire_somme(ctx, ref), _lire_somme(ctx, decv)
    if isinstance(fs, RaisonCode) or isinstance(ds, RaisonCode):
        return [ctx.non_verifiable(cid, RaisonCode.valeur_absente, **commun)]
    a, b = fs[1], ds[1]
    t = ctx.tol.t_colis()
    ecart = b - a
    commun["documents"] = list(dict.fromkeys([*c.doc_ids, *(v.document_id for v in ref if v.document_id)]))
    commun.update(attendu=a, constate=b, ecart=ecart, tolerance=t,
                  entrees={**{f"colis_reference_{i}": v for i, v in enumerate(ref)},
                           **{f"colis_declaration_{i}": v for i, v in enumerate(decv)}})
    if abs(ecart) <= t:
        return [ctx.conforme(cid, **commun)]
    confusion = _confusions_somme(decv, lambda x: abs(x - a) <= t) + _confusions_somme(ref, lambda x: abs(b - x) <= t)
    cl = ctx.classify(cid, ecart=ecart, tolerance=t, seuil_certitude=None, valeurs_cles=[*ref, *decv],
                      confusion=confusion, documents=commun["documents"])
    libelle = (
        f"{_maj(_source_txt(ctx, ref, c))} indique {format_nombre(a)} colis ; {_refs_dec(c.decs, decv)} "
        f"indique {format_nombre(b)} colis."
    )
    preuves = [preuve(v, RolePreuve.valeur_a) for v in ref] + [preuve(v, RolePreuve.valeur_b) for v in decv]
    return [ctx.constat(cid, cl, libelle=libelle, prochaine_action=ACTION_A11, preuves=preuves, **commun)]


@control("A11")
def a11_colis(ctx: ControlContext) -> list[ResultatControle]:
    """A11 — nombre de colis (facture, liste de colisage ou titre de transport) contre total déclaré, exact."""
    return _par_couple(ctx, "A11", _a11)


# =====================================================================================================
# A12 — Pays d'origine imprimés (signal + renvoi)
# =====================================================================================================


def _pays(ctx: ControlContext, v: ValeurSourcee | None) -> str | None:
    if not ctx.utilisable(v):
        return None
    assert v is not None
    return country_to_iso2(v.valeur)


def _comparer_origines(
    ctx: ControlContext, c: Couple, unite: str, sous: str, lignes: list[tuple[Document, int]],
    articles: list[tuple[Document, int]], code: str | None,
) -> ResultatControle:
    cid = "A12"
    commun: dict = dict(unite=unite, sous_controle=sous, documents=c.doc_ids)
    fvals = [v for fc, i in lignes if (v := fc.fc.lignes[i].pays_origine) is not None and _pays(ctx, v)]
    dvals = [(dec, i, v) for dec, i in articles if (v := dec.dec.articles[i].pays_origine) is not None and _pays(ctx, v)]
    if not fvals or not dvals:
        return ctx.non_verifiable(cid, RaisonCode.valeur_absente, **commun)
    of = sorted({_pays(ctx, v) or "" for v in fvals})
    od = sorted({_pays(ctx, v) or "" for _, _, v in dvals})
    # Origine préférentielle et code de préférence : affichés seulement, jamais comparés (§10 A12).
    pref = sorted({
        x.valeur or "" for dec, i in articles
        for x in (dec.dec.articles[i].pays_origine_preferentielle, dec.dec.articles[i].code_preference)
        if x is not None and x.valeur
    })
    commun.update(attendu=",".join(of), constate=",".join(od),
                  entrees={**{f"origine_facture_{i}": v for i, v in enumerate(fvals)},
                           **{f"origine_declaration_{i}": v for i, (_, _, v) in enumerate(dvals)}},
                  details={"sh6": code, "preferentiel_affiche": pref})
    if of == od:
        return ctx.conforme(cid, **commun)
    vals_d = [v for _, _, v in dvals]
    cl = ctx.classify(cid, ecart=None, tolerance=None, seuil_certitude=None, valeurs_cles=[*fvals, *vals_d],
                      documents=c.doc_ids, renvoi=True)
    arts = ", ".join(dict.fromkeys(_article_txt(dec, i) for dec, i, _ in dvals))
    pour = f" pour le code SH6 {code}" if code else ""
    page_f = f", page {fvals[0].page}" if fvals[0].page else ""
    page_d = f", page {vals_d[0].page}" if vals_d[0].page else ""
    libelle = (
        f"Le pays d'origine imprimé sur {_refs_fc(c.fcs)} ({', '.join(of)}{page_f}) diffère de celui indiqué sur "
        f"l'{arts} de {_refs_dec(c.decs)} ({', '.join(od)}{page_d}){pour}. {PHRASE_RENVOI}"
    )
    preuves = [preuve(v, RolePreuve.valeur_a) for v in fvals] + [preuve(v, RolePreuve.valeur_b) for v in vals_d]
    return ctx.constat(cid, cl, libelle=libelle, prochaine_action=ACTION_RENVOI, preuves=preuves, renvoi=True,
                       **commun)


def _a12(ctx: ControlContext, c: Couple) -> list[ResultatControle]:
    lignes, articles = _lignes_par_sh6(ctx, c), _articles_par_sh6(ctx, c)
    communs = sorted(set(lignes) & set(articles))
    ids_fc, ids_dec = [d.id for d in c.fcs], [d.id for d in c.decs]
    if communs:
        return [_comparer_origines(ctx, c, cle_unite(fc=ids_fc, dec=ids_dec, sh6=code), "sh6", lignes[code],
                                   articles[code], code) for code in communs]
    toutes_l = [(fc, i) for fc in c.fcs for i in range(len(fc.fc.lignes))]
    tous_a = [(dec, i) for dec in c.decs for i in range(len(dec.dec.articles))]
    return [_comparer_origines(ctx, c, c.unite, "ensemble", toutes_l, tous_a, None)]


@control("A12")
def a12_pays_origine(ctx: ControlContext) -> list[ResultatControle]:
    """A12 — pays d'origine imprimés, par code SH6 commun (sinon ensemble des origines). Note de renvoi :
    ``a_verifier``, ``renvoi = true``, montant ``null``."""
    return _par_couple(ctx, "A12", _a12)


# =====================================================================================================
# A13 — Codes marchandise imprimés (signal + renvoi)
# =====================================================================================================


def _a13(ctx: ControlContext, c: Couple) -> list[ResultatControle]:
    cid = "A13"
    commun: dict = dict(unite=c.unite, documents=c.doc_ids)
    fcodes: dict[str, list[ValeurSourcee]] = {}
    for fc in c.fcs:
        for ligne in fc.fc.lignes:
            v = ligne.code_marchandise_imprime
            if (code := _sh6(ctx, v)) is not None:
                assert v is not None
                fcodes.setdefault(code, []).append(v)
    if not fcodes:
        return [ctx.non_verifiable(cid, RaisonCode.valeur_absente,
                                   details={"motif": "la facture ne porte pas de code"}, **commun)]
    dcodes: dict[str, list[tuple[Document, int, ValeurSourcee]]] = {}
    for dec in c.decs:
        for i, art in enumerate(dec.dec.articles):
            v = art.code_marchandise
            if (code := _sh6(ctx, v)) is not None:
                assert v is not None
                dcodes.setdefault(code, []).append((dec, i, v))
    if not dcodes:
        return [ctx.non_verifiable(cid, RaisonCode.valeur_absente,
                                   details={"motif": "la déclaration ne porte pas de code lisible"}, **commun)]
    seuls_f = sorted(set(fcodes) - set(dcodes))
    seuls_d = sorted(set(dcodes) - set(fcodes))
    commun.update(attendu=",".join(sorted(fcodes)), constate=",".join(sorted(dcodes)),
                  details={"sh6_facture_seuls": seuls_f, "sh6_declaration_seuls": seuls_d})
    if not seuls_f and not seuls_d:
        return [ctx.conforme(cid, **commun)]
    douteux = any(codes_confondables(a, b) for a in seuls_f for b in seuls_d)
    vals_f = [v for code in seuls_f for v in fcodes[code]]
    vals_d = [v for code in seuls_d for _, _, v in dcodes[code]]
    cl = ctx.classify(cid, ecart=None, tolerance=None, seuil_certitude=None, valeurs_cles=[*vals_f, *vals_d],
                      documents=c.doc_ids, renvoi=True,
                      raisons_supplementaires=[RaisonCode.lecture_douteuse] if douteux else [])
    phrases = []
    if seuls_f:
        lst = ", ".join(f"{fcodes[k][0].valeur_brute or fcodes[k][0].valeur} (page {fcodes[k][0].page})" for k in seuls_f)
        phrases.append(
            f"sur {_refs_fc(c.fcs)}, {lst} sans équivalent (comparaison sur 6 chiffres) parmi les codes imprimés "
            f"sur {_refs_dec(c.decs)}"
        )
    if seuls_d:
        lst = ", ".join(
            f"{v.valeur_brute or v.valeur} ({_article_txt(dec, i)})" for k in seuls_d for dec, i, v in dcodes[k][:1]
        )
        phrases.append(f"sur la déclaration, {lst} sans équivalent parmi les codes imprimés sur la facture")
    libelle = "Codes marchandise imprimés : " + " ; ".join(phrases) + "."
    if douteux:
        libelle += " Certains codes ne diffèrent que par des chiffres souvent confondus à la lecture."
    libelle += f" {PHRASE_RENVOI}"
    preuves = [preuve(v, RolePreuve.valeur_a) for v in vals_f] + [preuve(v, RolePreuve.valeur_b) for v in vals_d]
    return [ctx.constat(cid, cl, libelle=libelle, prochaine_action=ACTION_RENVOI, preuves=preuves, renvoi=True,
                        **commun)]


@control("A13")
def a13_codes_marchandise(ctx: ControlContext) -> list[ResultatControle]:
    """A13 — codes marchandise imprimés comparés sur 6 chiffres (jamais validés ni jugés). Note de renvoi."""
    return _par_couple(ctx, "A13", _a13)


# =====================================================================================================
# A14 — Chronologie des dates
# =====================================================================================================


def _a14(ctx: ControlContext, c: Couple) -> list[ResultatControle]:
    cid = "A14"
    commun: dict = dict(unite=c.unite, documents=c.doc_ids)
    fcs = [fc for fc in c.fcs if fc.sous_type != SousTypeFactureCommerciale.pro_forma.value]
    if not fcs:
        return [ctx.non_applicable(cid, RaisonCode.valeur_absente, details={"motif": "pro_forma"}, **commun)]
    for v in [*(fc.fc.date for fc in fcs), *(dec.dec.date_acceptation for dec in c.decs)]:
        if _date(ctx, v) is None:
            return [ctx.non_verifiable(cid, ctx.raison_inutilisable(v) if not ctx.utilisable(v)
                                       else RaisonCode.valeur_absente, **commun)]
    anomalies = []
    for fc in fcs:
        vf = fc.fc.date
        assert vf is not None
        df = vf.date_iso()
        for dec in c.decs:
            vd = dec.dec.date_acceptation
            assert vd is not None
            dd = vd.date_iso()
            if (df - dd).days > 1:
                anomalies.append((fc, vf, df, dec, vd, dd))
    if not anomalies:
        return [ctx.conforme(cid, **commun)]
    vals = [x for a in anomalies for x in (a[1], a[4])]
    cl = ctx.classify(cid, ecart=None, tolerance=None, seuil_certitude=None, valeurs_cles=vals, documents=c.doc_ids)
    fc, vf, df, dec, vd, dd = anomalies[0]
    libelle = (
        f"{_maj(_ref_dec(dec, vd))} indique une date d'acceptation ({_date_fr(dd)}) antérieure de "
        f"{(df - dd).days} jours à la date de {_ref_fc(fc, vf)} ({_date_fr(df)})."
    )
    preuves = [preuve(a[1], RolePreuve.valeur_a) for a in anomalies] + [preuve(a[4], RolePreuve.valeur_b) for a in anomalies]
    return [ctx.constat(cid, cl, libelle=libelle, prochaine_action=ACTION_A14, preuves=preuves,
                        attendu=df.isoformat(), constate=dd.isoformat(), **commun)]


@control("A14")
def a14_chronologie(ctx: ControlContext) -> list[ResultatControle]:
    """A14 — date d'acceptation antérieure de plus d'un jour à la date de facture (pro forma exclues)."""
    return _par_couple(ctx, "A14", _a14)


# =====================================================================================================
# A15 — Références produit (signal)
# =====================================================================================================


_JETON_REF = re.compile(r"[A-Za-z0-9]+(?:[-/.][A-Za-z0-9]+)*[-/.]?")


def _jetons_reference(texte: str | None) -> list[str]:
    """Mots d'une désignation pouvant être une référence d'article : au moins 4 caractères, un chiffre."""
    return [j for j in _JETON_REF.findall(texte or "") if len(j) >= 4 and re.search(r"\d", j)]


def _forme_reference(ref: str | None) -> str:
    """Forme d'une référence : lettres -> A, chiffres -> 9, séparateurs conservés (« LA-1012-M » -> « AA-9999-A »)."""
    return re.sub(r"\d", "9", re.sub(r"[^\W\d_]", "A", (ref or "").strip().upper()))


def _a15(ctx: ControlContext, c: Couple) -> list[ResultatControle]:
    cid = "A15"
    commun: dict = dict(unite=c.unite, documents=c.doc_ids)
    refs: dict[str, ValeurSourcee] = {}
    for fc in c.fcs:
        for ligne in fc.fc.lignes:
            v = ligne.reference_article
            if ctx.utilisable(v):
                assert v is not None
                cle = norm_ref(v.valeur)
                if len(cle) >= 4:
                    refs.setdefault(cle, v)
    articles = [a for dec in c.decs for a in dec.dec.articles]
    designations = [v for a in articles if (v := a.description) is not None and ctx.utilisable(v)]
    if not designations or len(designations) < len(articles):
        # Une désignation illisible peut contenir la référence cherchée : on ne conclut pas (D-810).
        return [ctx.non_verifiable(cid, RaisonCode.valeur_absente, **commun)]
    if not refs:
        return [ctx.non_applicable(cid, RaisonCode.valeur_absente, details={"motif": "aucune_reference_article"},
                                   **commun)]
    cles_d = [norm_ref(v.valeur) for v in designations]
    jetons_d = [_jetons_reference(v.valeur) for v in designations]
    formes = {_forme_reference(v.valeur) for v in refs.values()}

    def citee(r: str, i: int) -> bool:
        # présence normalisée, ou référence tronquée dans la désignation (§8.4, ``ref_compatibles``)
        return r in cles_d[i] or any(ref_compatibles(j, refs[r].valeur) for j in jetons_d[i])

    # Une désignation « contient une référence d'article » si elle cite une référence de la facture ou un mot
    # de même forme (lettres, chiffres, séparateurs) qu'une référence de la facture (D-810).
    if not all(any(citee(r, i) for r in refs) or any(_forme_reference(j) in formes for j in jetons_d[i])
               for i in range(len(designations))):
        # Le déclarant ne reprend manifestement pas les références : contrôle sans objet.
        return [ctx.non_applicable(cid, RaisonCode.controle_signal_seulement,
                                   details={"motif": "references_non_reprises"}, **commun)]
    absentes = [v for r, v in refs.items() if not any(citee(r, i) for i in range(len(designations)))]
    commun.update(details={"references": sorted(refs), "absentes": [norm_ref(v.valeur) for v in absentes]})
    if not absentes:
        return [ctx.conforme(cid, **commun)]
    cl = ctx.classify(cid, ecart=None, tolerance=None, seuil_certitude=None, valeurs_cles=absentes,
                      documents=c.doc_ids)
    lst = ", ".join(f"{v.valeur_brute or v.valeur} (page {v.page})" if v.page else str(v.valeur) for v in absentes)
    libelle = (
        f"Les références d'article {lst} imprimées sur {_refs_fc(c.fcs)} ne figurent dans aucune désignation "
        f"des articles de {_refs_dec(c.decs)}, alors que les autres désignations reprennent les références."
    )
    preuves = [preuve(v, RolePreuve.valeur_a) for v in absentes] + [preuve(v, RolePreuve.contexte) for v in designations]
    return [ctx.constat(cid, cl, libelle=libelle, prochaine_action=ACTION_A15, preuves=preuves, **commun)]


@control("A15")
def a15_references_produit(ctx: ControlContext) -> list[ResultatControle]:
    """A15 — références d'article (≥ 4 caractères) recherchées dans les désignations ; seulement si toutes
    les désignations reprennent au moins une référence. Signal seulement."""
    return _par_couple(ctx, "A15", _a15)
