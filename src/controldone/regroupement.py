"""Regroupement des documents en dossiers (SPEC §7.5, §6.2.7, §6.2.8 ; D-013).

Fonction pure et déterministe : ``regrouper(documents, ...) -> ResultatRegroupement``.

Algorithme (ordonné) :

1. **Frontière dure** : la frontière d'un document est le dossier parent le plus profond de son fichier
   qui contient des documents de types différents (arborescence de dépôt ou de ZIP). Deux documents ne
   sont regroupés que si leurs frontières sont égales ou si l'une contient l'autre (un document posé à
   la racine peut rejoindre un sous-dossier ; deux sous-dossiers frères jamais). Les courriels forment
   chacun une frontière, sauf référence explicite commune (MRN ou référence de transport).
2. **Graines** : chaque facture commerciale exploitable (ni doublon, avec champs).
3. **Déclarations** rattachées aux graines : référence de facture citée (forte), référence de transport
   commune (forte), même fichier source (moyenne), montant facturé égal dans ``T_VALEUR`` (moyenne),
   même TVA importateur + codes SH6 communs (faible), nom de fichier (faible). Une déclaration rattachée
   à plusieurs graines les réunit (plusieurs factures pour une déclaration).
4. **Factures transitaires** : MRN cité (forte), référence de transport (forte), total des débours égal
   au total des taxes dans ``T_DEBOURS`` (moyenne), même fichier source (moyenne). Une facture
   transitaire peut appartenir à plusieurs dossiers (facture mensuelle).
5. **Avoirs** : facture d'origine citée (forte), MRN ou référence de transport (moyenne).
6. Score = somme des poids (forte 3, moyenne 2, faible 1) ; lien créé si score ≥ 2. Force du lien :
   score 2 -> ``faible`` (P4) ; score ≥ 3 avec au moins un signal fort -> ``forte`` ; sinon ``moyenne``
   (qui n'est pas un rattachement solide au sens de §8.5.1 condition 5 : prudence).
7. Documents restants : chaque déclaration ou facture transitaire orpheline devient son propre dossier
   ``incomplet``. Rien n'est silencieusement abandonné (les documents non rattachables sont rendus dans
   ``non_rattaches``). Option ``meme_source`` : quand une frontière ne contient qu'un seul dossier
   candidat, un document sans autre lien y est rattaché par le signal ``meme_dossier_source`` (poids 2,
   donc ``faible``), et un dossier incomplet est fusionné avec l'unique dossier complet de sa frontière.
8. Allocations : facture commerciale -> déclaration (``totalite``, ``reference_explicite`` ou
   ``prorata``) ; ligne de facture transitaire -> MRN (``ligne_par_mrn``, ``totalite`` ou ``prorata``).
   Les versions rectificatives d'une même déclaration (même préfixe MRN) sont toutes rattachées, mais
   seule la dernière version sert aux allocations et aux clés.

Le document graine (ou le document orphelin qui forme son dossier) porte ``force = forte`` et le signal
``graine`` (D-013). Identifiants stables : ``id_stable`` sur l'ensemble trié des documents et la version
du regroupement (clé d'idempotence §7 étape 6).
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from pathlib import PurePosixPath

from controldone.controls.tolerances import Tolerances
from controldone.ids import Prefixe, id_stable
from controldone.model.documents import Document, Fichier
from controldone.model.dossier import (
    POIDS_FORCE,
    Allocation,
    ClesDossier,
    Dossier,
    LienDocument,
)
from controldone.model.enums import (
    ForceLien,
    MethodeAllocation,
    NatureLigne,
    RoleLien,
    SignalLien,
    TypeDocument,
)
from controldone.model.referentiel import ProfilTolerances, Transitaire
from controldone.model.valeur import ValeurSourcee
from controldone.normalize.fiscal import normalize_vat
from controldone.normalize.parties import identifier_transitaire
from controldone.normalize.refs import (
    est_mrn,
    mrn_egaux,
    mrn_prefixe,
    mrn_proches,
    norm_ref,
    norm_ref_transport,
    ref_compatibles,
    ref_egales,
    ref_transport_compatibles,
    ref_transport_proches,
)

__all__ = [
    "POIDS_SIGNAL",
    "SIGNAUX_FORTS",
    "VERSION_REGROUPEMENT",
    "OptionsRegroupement",
    "ResultatRegroupement",
    "cle_idempotence_regroupement",
    "force_depuis_score",
    "frontieres",
    "regrouper",
]

VERSION_REGROUPEMENT = "1.0.0"

_F, _M, _f = ForceLien.forte, ForceLien.moyenne, ForceLien.faible

#: Poids d'un signal selon le type de document rattaché (§7.5 étapes 3 à 5).
POIDS_SIGNAL: dict[TypeDocument, dict[SignalLien, ForceLien]] = {
    TypeDocument.declaration: {
        SignalLien.ref_facture_citee: _F,
        SignalLien.ref_transport: _F,
        SignalLien.meme_fichier_source: _M,
        SignalLien.montant_egal: _M,
        SignalLien.tva: _f,  # TVA importateur + codes SH6 communs : faible (un seul poids pour le couple)
        SignalLien.nom_fichier: _f,
        SignalLien.meme_dossier_source: _M,
        # MRN de la déclaration cité par une facture de transitaire elle-même rattachée au dossier par une
        # référence explicite (corroboration, D-2407)
        SignalLien.mrn_cite: _F,
    },
    TypeDocument.facture_transitaire: {
        SignalLien.mrn_cite: _F,
        SignalLien.ref_transport: _F,
        SignalLien.ref_facture_citee: _F,
        SignalLien.montant_egal: _M,
        SignalLien.meme_fichier_source: _M,
        SignalLien.meme_dossier_source: _M,
    },
    TypeDocument.avoir: {
        SignalLien.ref_facture_citee: _F,
        SignalLien.mrn_cite: _M,
        SignalLien.ref_transport: _M,
        SignalLien.meme_fichier_source: _M,
        SignalLien.meme_dossier_source: _M,
    },
    TypeDocument.document_support: {
        SignalLien.ref_transport: _F,
        SignalLien.ref_facture_citee: _F,
        SignalLien.mrn_cite: _F,
        # Un document support n'est jamais comparé avec certitude (A10, A11 : a_verifier ; CG et lettres
        # écartées, §5.3.3) : la co-localisation (même fichier, seul dossier de la frontière) suffit à un lien
        # « moyenne » (score 3 sans référence explicite, D-401), sans alerte P4 (D-708).
        SignalLien.meme_fichier_source: _F,
        SignalLien.meme_dossier_source: _F,
    },
    TypeDocument.facture_commerciale: {
        # facture commerciale rattachée à un dossier existant (fusion de frontière, §7.5 étape 7)
        SignalLien.meme_dossier_source: _M,
    },
}
POIDS_SIGNAL[TypeDocument.document_non_exploitable] = POIDS_SIGNAL[TypeDocument.document_support]
POIDS_SIGNAL[TypeDocument.inconnu] = POIDS_SIGNAL[TypeDocument.document_support]

#: Signaux « explicites » (référence citée) : seuls ils peuvent donner un lien ``forte``.
SIGNAUX_FORTS = frozenset({SignalLien.ref_facture_citee, SignalLien.ref_transport, SignalLien.mrn_cite})

_ROLE: dict[TypeDocument, RoleLien] = {
    TypeDocument.facture_commerciale: RoleLien.facture_commerciale,
    TypeDocument.declaration: RoleLien.declaration,
    TypeDocument.facture_transitaire: RoleLien.facture_transitaire,
    TypeDocument.avoir: RoleLien.avoir,
}

_ORDRE_SIGNAUX = list(SignalLien)


# --- options et résultat ------------------------------------------------------------------------------


@dataclass(frozen=True)
class OptionsRegroupement:
    """Paramètres du regroupement.

    - ``meme_source`` : rattachement de repli par la frontière (voir étape 7 du module) ;
    - ``annee`` / ``numero_depart`` : références lisibles ``D-AAAA-NNNNN`` ;
    - ``courriels`` : ``fichier_id -> Message-ID`` des fichiers reçus par courriel (une frontière chacun).
    """

    meme_source: bool = True
    annee: int | None = None
    numero_depart: int = 1
    courriels: Mapping[str, str] = field(default_factory=dict)
    lot_ids: tuple[str, ...] = ()


@dataclass
class ResultatRegroupement:
    dossiers: list[Dossier]
    #: Documents non rattachés à un dossier (inconnus isolés, supports sans lien) : listés au rapport.
    non_rattaches: list[str] = field(default_factory=list)
    #: Frontière de chaque document (informatif, tests).
    frontiere_document: dict[str, str] = field(default_factory=dict)


def cle_idempotence_regroupement(document_ids: Iterable[str]) -> str:
    """Clé §7 étape 6 : ensemble trié des ``document_id`` + version du regroupement."""
    return id_stable("grp", VERSION_REGROUPEMENT, *sorted(set(document_ids))).split("_", 1)[1]


def force_depuis_score(score: int, signaux: Iterable[SignalLien]) -> ForceLien | None:
    """Force d'un lien d'après son score (§7.5 étape 6). ``None`` si aucun lien (score < 2)."""
    if score < 2:
        return None
    if score == 2:
        return ForceLien.faible
    if set(signaux) & SIGNAUX_FORTS:
        return ForceLien.forte
    return ForceLien.moyenne


# --- lecture prudente des champs --------------------------------------------------------------------


def _txt(v: ValeurSourcee | None) -> str | None:
    if v is None or not v.est_lisible:
        return None
    return v.valeur


def _dec(v: ValeurSourcee | None) -> Decimal | None:
    if v is None or not v.est_lisible:
        return None
    try:
        return v.decimal()
    except (ValueError, InvalidOperation):
        return None


def _exploitable(d: Document) -> bool:
    return d.champs is not None and not d.doublon_de


def _numero(d: Document) -> str | None:
    c = d.champs
    return _txt(getattr(c, "numero", None)) if c is not None else None


def _refs_documents_declaration(d: Document) -> list[str]:
    c = d.dec
    refs = [_txt(r.reference) for r in c.documents_references]
    for a in c.articles:
        refs.extend(_txt(r) for r in a.references_facture)
    return [r for r in refs if r]


def _mrns_ft(d: Document) -> list[str]:
    c = d.ft
    mrns = [_txt(v) for v in c.refs_mrn]
    mrns += [_txt(t.mrn) for t in c.tableau_mrn]
    mrns += [_txt(li.mrn) for li in c.lignes]
    return [m for m in mrns if m]


def _transports_ft(d: Document) -> list[str]:
    c = d.ft
    refs = [_txt(v) for v in c.refs_transport]
    refs += [_txt(t.ref_transport) for t in c.tableau_mrn]
    refs += [_txt(li.ref_transport) for li in c.lignes]
    return [r for r in refs if r]


def _transports_support(d: Document) -> list[str]:
    c = d.sup
    return [r for r in (_txt(c.ref_transport_maitre), _txt(c.ref_transport_maison)) if r]


def _rang_version(d: Document, ordre: int) -> tuple:
    c = d.dec
    v = _dec(c.version)
    dt = _txt(c.date_acceptation) or ""
    return (v if v is not None else Decimal(-1), dt, ordre)


def _total_taxes(d: Document) -> Decimal | None:
    c = d.dec
    total = _dec(c.total_droits_taxes)
    if total is not None:
        return total
    montants = [_dec(t.montant) for t in c.taxations]
    if montants and all(m is not None for m in montants):
        return sum(montants, Decimal(0))  # type: ignore[arg-type]
    return _dec(c.total_a_payer)


def _total_debours(d: Document) -> Decimal | None:
    c = d.ft
    total = _dec(c.total_debours)
    if total is not None:
        return total
    montants = [_dec(li.montant_ht) for li in c.lignes if li.nature.est_debours]
    if montants and all(m is not None for m in montants):
        return sum(montants, Decimal(0))  # type: ignore[arg-type]
    return None


def _sh6(code: str | None) -> str | None:
    if not code:
        return None
    chiffres = re.sub(r"\D", "", code)
    return chiffres[:6] if len(chiffres) >= 6 else None


# --- frontières (§7.5 étape 1) ------------------------------------------------------------------------


def _dossier_parent(chemin: str | None) -> tuple[str, ...]:
    if not chemin:
        return ()
    parts = PurePosixPath(chemin.replace("\\", "/")).parts
    return tuple(p for p in parts[:-1] if p not in ("", "."))


def frontieres(documents: Sequence[Document], fichiers: Mapping[str, Fichier]) -> dict[str, tuple[str, ...]]:
    """Frontière de chaque document : dossier parent le plus profond (de son fichier) dont le sous-arbre
    contient des documents de types différents ; à défaut, la racine ``()``."""
    chemins: dict[str, tuple[str, ...]] = {}
    for d in documents:
        fic = fichiers.get(d.pages[0].fichier_id) if d.pages else None
        chemins[d.id] = _dossier_parent(fic.chemin_relatif if fic else None)
    types_sous_arbre: dict[tuple[str, ...], set[TypeDocument]] = {}
    for d in documents:
        p = chemins[d.id]
        for k in range(len(p) + 1):
            types_sous_arbre.setdefault(p[:k], set()).add(d.type)
    sortie: dict[str, tuple[str, ...]] = {}
    for d in documents:
        p = chemins[d.id]
        retenu: tuple[str, ...] = ()
        for k in range(len(p), -1, -1):
            if len(types_sous_arbre.get(p[:k], set())) >= 2:
                retenu = p[:k]
                break
        sortie[d.id] = retenu
    return sortie


def _frontieres_compatibles(a: tuple[str, ...], b: tuple[str, ...]) -> bool:
    court, long_ = (a, b) if len(a) <= len(b) else (b, a)
    return long_[: len(court)] == court


# --- moteur ----------------------------------------------------------------------------------------------


@dataclass
class _Groupe:
    """Dossier en construction."""

    graine: str
    membres: dict[str, tuple[int, list[SignalLien]]] = field(default_factory=dict)  # doc -> (score, signaux)
    frontiere: tuple[str, ...] = ()
    courriel: str | None = None
    #: membres dont le lien, renforcé par une référence retrouvée (D-3702), reste au plus « moyenne »
    plafond_moyenne: set[str] = field(default_factory=set)


class _Regroupeur:
    def __init__(
        self,
        documents: Sequence[Document],
        fichiers: Mapping[str, Fichier],
        profil: ProfilTolerances,
        transitaires: Sequence[Transitaire],
        options: OptionsRegroupement,
    ) -> None:
        self.docs = list(documents)
        self.par_id = {d.id: d for d in self.docs}
        self.ordre = {d.id: i for i, d in enumerate(self.docs)}
        self.fichiers = fichiers
        self.tol = Tolerances(profil)
        self.transitaires = list(transitaires)
        self.options = options
        self.front = frontieres(self.docs, fichiers)
        self.groupes: list[_Groupe] = []
        self._cache_numeros: dict[TypeDocument, list[str]] = {}

    # -- outils --

    def _fichier(self, d: Document) -> Fichier | None:
        return self.fichiers.get(d.pages[0].fichier_id) if d.pages else None

    def _courriel(self, d: Document) -> str | None:
        for fid in d.fichier_ids():
            if fid in self.options.courriels:
                return self.options.courriels[fid]
        return None

    def _numeros(self, type_doc: TypeDocument) -> list[str]:
        if type_doc not in self._cache_numeros:
            self._cache_numeros[type_doc] = [
                n for x in self.docs if x.type is type_doc and _exploitable(x) and (n := _numero(x))
            ]
        return self._cache_numeros[type_doc]

    def _cite(self, ref: str | None, num: str | None, type_doc: TypeDocument) -> bool:
        """``ref`` (référence citée) désigne le document numéroté ``num`` : égalité, ou compatibilité (§8.4)
        **univoque** — une référence tronquée (« ODH 2026 ») compatible avec les numéros de plusieurs documents
        du lot ne désigne aucun d'eux (D-2112)."""
        if not ref or not num:
            return False
        if ref_egales(ref, num):
            return True
        if not ref_compatibles(ref, num):
            return False
        return not any(ref_compatibles(ref, n) for n in self._numeros(type_doc) if not ref_egales(n, num))

    def _meme_fichier(self, a: Document, b: Document) -> bool:
        return bool(set(a.fichier_ids()) & set(b.fichier_ids()))

    def _refs_explicites(self, d: Document) -> set[str]:
        """MRN (préfixes) et références de transport normalisées citées par un document."""
        out: set[str] = set()
        if not _exploitable(d):
            return out
        if d.type is TypeDocument.declaration:
            p = mrn_prefixe(_txt(d.dec.mrn))
            if p:
                out.add("mrn:" + p)
            for r in _refs_documents_declaration(d):
                out.add("tr:" + norm_ref_transport(r))
                out.add("fac:" + norm_ref(r))
        elif d.type is TypeDocument.facture_transitaire:
            out |= {"mrn:" + mrn_prefixe(m) for m in _mrns_ft(d)}
            out |= {"tr:" + norm_ref_transport(r) for r in _transports_ft(d)}
        elif d.type is TypeDocument.avoir:
            out |= {"mrn:" + mrn_prefixe(_txt(m) or "") for m in d.av.refs_mrn if _txt(m)}
            out |= {"tr:" + norm_ref_transport(_txt(r)) for r in d.av.refs_transport if _txt(r)}
        elif d.type is TypeDocument.facture_commerciale:
            r = _txt(d.fc.ref_transport)
            if r:
                out.add("tr:" + norm_ref_transport(r))
            if _numero(d):
                out.add("fac:" + norm_ref(_numero(d)))  # numéro de la facture, cité tel quel (D-2408)
        elif d.type is TypeDocument.document_support:
            out |= {"tr:" + norm_ref_transport(r) for r in _transports_support(d)}
        return {x for x in out if len(x) > 4}

    def _compatible(self, d: Document, g: _Groupe) -> bool:
        """Frontière dure (§7.5 étape 1) entre un document et un dossier en construction. Deux sous-dossiers
        frères ne se rejoignent que sur une référence explicite commune (MRN, titre de transport), comme deux
        courriels (D-2408) : les pièces d'un même envoi rangées au hasard de sous-dossiers mixtes."""
        if self._meme_frontiere(d, g):
            return True
        # Courriels différents (ou courriel / dépôt), sous-dossiers frères : seulement sur référence explicite
        # commune.
        refs_d = self._refs_explicites(d)
        if not refs_d:
            return False
        refs_g: set[str] = set()
        for mid in g.membres:
            refs_g |= self._refs_explicites(self.par_id[mid])
        return bool(refs_d & refs_g)

    def _meme_frontiere(self, d: Document, g: _Groupe) -> bool:
        return _frontieres_compatibles(self.front[d.id], g.frontiere) and self._courriel(d) == g.courriel

    def _nouveau_groupe(self, d: Document) -> _Groupe:
        g = _Groupe(graine=d.id, frontiere=self.front[d.id], courriel=self._courriel(d))
        g.membres[d.id] = (POIDS_FORCE[ForceLien.forte], [SignalLien.graine])
        self.groupes.append(g)
        return g

    def _ajouter(self, g: _Groupe, doc_id: str, score: int, signaux: list[SignalLien]) -> None:
        existant = g.membres.get(doc_id)
        if existant is None or score > existant[0]:
            union = sorted(set(signaux) | set(existant[1] if existant else []), key=_ORDRE_SIGNAUX.index)
            g.membres[doc_id] = (score, union)
        else:
            union = sorted(set(signaux) | set(existant[1]), key=_ORDRE_SIGNAUX.index)
            g.membres[doc_id] = (existant[0], union)

    def _fusionner(self, groupes: list[_Groupe]) -> _Groupe:
        """Réunit plusieurs groupes (plusieurs factures pour une déclaration) dans le premier."""
        groupes = sorted(groupes, key=lambda g: self.ordre[g.graine])
        cible = groupes[0]
        for g in groupes[1:]:
            for mid, (score, sig) in g.membres.items():
                self._ajouter(cible, mid, score, sig)
            if len(g.frontiere) > len(cible.frontiere):
                cible.frontiere = g.frontiere  # la plus spécifique : n'absorbe pas un dossier frère
            self.groupes.remove(g)
        return cible

    def _score(self, type_doc: TypeDocument, signaux: Iterable[SignalLien]) -> int:
        poids = POIDS_SIGNAL.get(type_doc, {})
        return sum(POIDS_FORCE[poids[s]] for s in set(signaux) if s in poids)

    # -- signaux par type --

    def _supports_citant(self, fc: Document) -> list[str]:
        """Références de transport des documents support qui citent la facture (chaîne BL -> facture)."""
        num = _numero(fc)
        if not num:
            return []
        refs: list[str] = []
        for d in self.docs:
            if d.type is TypeDocument.document_support and _exploitable(d) and any(
                self._cite(_txt(r), num, TypeDocument.facture_commerciale) for r in d.sup.refs_facture
            ):
                refs.extend(_transports_support(d))
        return refs

    def signaux_declaration(self, dec: Document, fc: Document) -> list[SignalLien]:
        s: list[SignalLien] = []
        c = dec.dec
        num = _numero(fc)
        refs = _refs_documents_declaration(dec)
        if num and any(self._cite(r, num, TypeDocument.facture_commerciale) for r in refs):
            s.append(SignalLien.ref_facture_citee)
        transports = [r for r in [_txt(fc.fc.ref_transport), *self._supports_citant(fc)] if r]
        if transports and any(ref_transport_compatibles(r, t) for r in refs for t in transports):
            s.append(SignalLien.ref_transport)
        if self._meme_fichier(dec, fc):
            s.append(SignalLien.meme_fichier_source)
        total_fc, total_dec = _dec(fc.fc.total_facture), _dec(c.montant_total_facture)
        dev_fc, dev_dec = _txt(fc.fc.devise), _txt(c.devise_facture)
        if (
            total_fc is not None and total_dec is not None and dev_fc and dev_dec and dev_fc == dev_dec
            and abs(total_dec - total_fc) <= self.tol.t_valeur(total_fc, total_dec)
        ):
            s.append(SignalLien.montant_egal)
        tva_fc, tva_dec = normalize_vat(_txt(fc.fc.acheteur.tva)), normalize_vat(_txt(c.importateur.tva))
        if tva_fc and tva_fc == tva_dec:
            sh_fc = {_sh6(_txt(li.code_marchandise_imprime)) for li in fc.fc.lignes} - {None}
            sh_dec = {a.code_sh6 for a in c.articles} - {None}
            if sh_fc & sh_dec:
                s.append(SignalLien.tva)
                s.append(SignalLien.codes_communs)
        if num and len(norm_ref(num)) >= 5:
            fic = self._fichier(dec)
            if fic and norm_ref(num) in norm_ref(PurePosixPath(fic.chemin_relatif).stem):
                s.append(SignalLien.nom_fichier)
        return s

    def signaux_ft(self, ft: Document, cible: Document) -> list[SignalLien]:
        """Signaux d'une facture transitaire envers une déclaration (ou une facture commerciale)."""
        s: list[SignalLien] = []
        if cible.type is TypeDocument.declaration:
            mrn = _txt(cible.dec.mrn)
            if mrn and any(mrn_egaux(m, mrn) for m in _mrns_ft(ft)):
                s.append(SignalLien.mrn_cite)
            refs_dec = _refs_documents_declaration(cible)
            if any(ref_transport_compatibles(a, b) for a in _transports_ft(ft) for b in refs_dec):
                s.append(SignalLien.ref_transport)
            deb, tax = _total_debours(ft), _total_taxes(cible)
            nb = len(cible.dec.articles)
            if deb is not None and tax is not None and deb > 0 and abs(deb - tax) <= self.tol.t_debours(nb):
                s.append(SignalLien.montant_egal)
        elif cible.type is TypeDocument.facture_commerciale:
            num = _numero(cible)
            if num and any(self._cite(_txt(r), num, TypeDocument.facture_commerciale)
                           for r in ft.ft.refs_facture_commerciale):
                s.append(SignalLien.ref_facture_citee)
            t = _txt(cible.fc.ref_transport)
            if t and any(ref_transport_compatibles(a, t) for a in _transports_ft(ft)):
                s.append(SignalLien.ref_transport)
        elif cible.type is TypeDocument.document_support:
            if any(ref_transport_compatibles(a, b) for a in _transports_ft(ft) for b in _transports_support(cible)):
                s.append(SignalLien.ref_transport)
        if self._meme_fichier(ft, cible):
            s.append(SignalLien.meme_fichier_source)
        return s

    def signaux_avoir(self, av: Document, cible: Document) -> list[SignalLien]:
        s: list[SignalLien] = []
        c = av.av
        if cible.type is TypeDocument.facture_transitaire:
            num = _numero(cible)
            if num and any(self._cite(_txt(r), num, TypeDocument.facture_transitaire) for r in c.refs_facture_origine):
                s.append(SignalLien.ref_facture_citee)
            if any(mrn_egaux(_txt(m), x) for m in c.refs_mrn for x in _mrns_ft(cible)):
                s.append(SignalLien.mrn_cite)
            if any(ref_transport_compatibles(_txt(r), x) for r in c.refs_transport for x in _transports_ft(cible)):
                s.append(SignalLien.ref_transport)
        elif cible.type is TypeDocument.declaration:
            mrn = _txt(cible.dec.mrn)
            if mrn and any(mrn_egaux(_txt(m), mrn) for m in c.refs_mrn):
                s.append(SignalLien.mrn_cite)
        if self._meme_fichier(av, cible):
            s.append(SignalLien.meme_fichier_source)
        return s

    def signaux_support(self, sup: Document, cible: Document) -> list[SignalLien]:
        s: list[SignalLien] = []
        if _exploitable(sup) and sup.type is TypeDocument.document_support:
            refs = _transports_support(sup)
            if cible.type is TypeDocument.facture_commerciale:
                num = _numero(cible)
                if num and any(self._cite(_txt(r), num, TypeDocument.facture_commerciale) for r in sup.sup.refs_facture):
                    s.append(SignalLien.ref_facture_citee)
                t = _txt(cible.fc.ref_transport)
                if t and any(ref_transport_compatibles(r, t) for r in refs):
                    s.append(SignalLien.ref_transport)
            elif cible.type is TypeDocument.declaration:
                if any(ref_transport_compatibles(r, x) for r in refs for x in _refs_documents_declaration(cible)):
                    s.append(SignalLien.ref_transport)
            elif cible.type is TypeDocument.facture_transitaire:
                if any(ref_transport_compatibles(r, x) for r in refs for x in _transports_ft(cible)):
                    s.append(SignalLien.ref_transport)
                num = _numero(cible)
                if num and any(self._cite(_txt(r), num, TypeDocument.facture_transitaire) for r in sup.sup.refs_facture):
                    s.append(SignalLien.ref_facture_citee)  # lettre d'accompagnement de la facture (D-708)
        if self._meme_fichier(sup, cible):
            s.append(SignalLien.meme_fichier_source)
        return s

    # -- rattachement générique --

    def _meilleur_par_groupe(
        self, d: Document, cibles_types: tuple[TypeDocument, ...], fn_signaux
    ) -> dict[int, tuple[int, list[SignalLien]]]:
        """Pour chaque groupe compatible : meilleur score (et signaux réunis) du document envers ses
        membres des types cibles."""
        sortie: dict[int, tuple[int, list[SignalLien]]] = {}
        for gi, g in enumerate(self.groupes):
            if d.id in g.membres or not self._compatible(d, g):
                continue
            meilleur, union = 0, set()
            for mid in g.membres:
                m = self.par_id[mid]
                if m.type not in cibles_types or not _exploitable(m):
                    continue
                sig = fn_signaux(d, m)
                union |= set(sig)
                meilleur = max(meilleur, self._score(d.type, sig))
            # score sur l'union des signaux envers le dossier (plusieurs membres concordants)
            score = max(meilleur, self._score(d.type, union))
            if score > 0:
                sortie[gi] = (score, sorted(union, key=_ORDRE_SIGNAUX.index))
        return sortie

    def _departager(
        self, d: Document, retenus: dict[int, tuple[int, list[SignalLien]]]
    ) -> dict[int, tuple[int, list[SignalLien]]]:
        """Plusieurs dossiers candidats (D-2110). Une référence explicite (facture, transport, MRN) peut rattacher
        un document à plusieurs dossiers (plusieurs factures pour une déclaration, facture de transitaire
        mensuelle) : seuls ces dossiers sont gardés. Sans référence explicite, le meilleur score l'emporte ; à
        égalité (cas type : PDF fusionné où « même fichier » vaut pour tous les dossiers), une déclaration va au
        seul dossier qui n'en a pas encore, puis tout document au dossier du document qui le **précède
        immédiatement** dans le même fichier (« facture, puis sa déclaration »). Sinon, règle antérieure : tous les
        candidats à égalité."""
        if len(retenus) <= 1:
            return retenus
        # Un dossier rejoint hors de la frontière par une référence commune s'efface devant un dossier de la même
        # frontière qui porte la même référence (référence ambiguë : deux envois au même numéro). Une référence
        # propre à ce dossier (MRN d'une facture mensuelle) le garde (D-2408).
        natifs = {gi for gi in retenus if self._meme_frontiere(d, self.groupes[gi])}
        if natifs and len(natifs) < len(retenus):
            refs_d = self._refs_explicites(d)
            refs_natifs = {r for gi in natifs for m in self.groupes[gi].membres
                           for r in self._refs_explicites(self.par_id[m])}

            def garder(gi: int) -> bool:
                if gi in natifs:
                    return True
                communes = refs_d & {r for m in self.groupes[gi].membres for r in self._refs_explicites(self.par_id[m])}
                valeurs_natives = {r.split(":", 1)[1] for r in refs_natifs}
                return any(r.split(":", 1)[1] not in valeurs_natives for r in communes)

            retenus = {gi: v for gi, v in retenus.items() if garder(gi)}
            if len(retenus) == 1:
                return retenus
        explicites = {gi: v for gi, v in retenus.items() if set(v[1]) & SIGNAUX_FORTS}
        if explicites:
            return explicites
        meilleur = max(v[0] for v in retenus.values())
        tete = {gi: v for gi, v in retenus.items() if v[0] == meilleur}
        if len(tete) == 1:
            return tete
        libres = tete
        if d.type is TypeDocument.declaration:
            libres = {gi: v for gi, v in tete.items() if not any(
                self.par_id[m].type is TypeDocument.declaration and _exploitable(self.par_id[m])
                for m in self.groupes[gi].membres)}
            if len(libres) == 1:
                return libres
        precedent = self._precedent_dans_fichier(d)
        if precedent is not None:
            for ensemble in (libres, tete):
                avec = [gi for gi in ensemble if precedent in self.groupes[gi].membres]
                if len(avec) == 1:
                    return {avec[0]: tete[avec[0]]}
        return tete

    def _precedent_dans_fichier(self, d: Document) -> str | None:
        """Document qui précède immédiatement ``d`` dans son fichier (pages), ou ``None``."""
        if not d.pages:
            return None
        fid, num = d.pages[0].fichier_id, min(p.numero for p in d.pages)
        meilleur: tuple[int, str] | None = None
        for x in self.docs:
            if x.id == d.id or x.doublon_de:
                continue
            nums = [p.numero for p in x.pages if p.fichier_id == fid and p.numero < num]
            if nums and (meilleur is None or max(nums) > meilleur[0]):
                meilleur = (max(nums), x.id)
        return meilleur[1] if meilleur else None

    def _repli_meme_source(self, d: Document, score_actuel: int = 0) -> tuple[int, _Groupe] | None:
        """Unique dossier candidat de la frontière : rattachement ``meme_dossier_source``."""
        if not self.options.meme_source:
            return None
        candidats = [g for g in self.groupes if d.id not in g.membres and self._compatible(d, g)]
        if len(candidats) != 1:
            return None
        if d.type is TypeDocument.declaration and self._autre_declaration(d, candidats[0]):
            return None  # dossier sans facture qui a déjà une déclaration d'un autre MRN : dossier distinct (D-2111)
        poids = POIDS_SIGNAL.get(d.type, {}).get(SignalLien.meme_dossier_source, ForceLien.moyenne)
        return score_actuel + POIDS_FORCE[poids], candidats[0]

    def _autre_declaration(self, d: Document, g: _Groupe) -> bool:
        """Le dossier, **sans facture commerciale**, contient déjà une déclaration exploitable d'un autre MRN
        (préfixe) que ``d`` : rien ne justifie de les réunir (avec une facture, une facture répartie sur plusieurs
        déclarations reste possible, §7.5 étape 8)."""
        p = mrn_prefixe(_txt(d.dec.mrn)) if _exploitable(d) else ""
        if len(p) != 15:
            return False
        if any(self.par_id[m].type is TypeDocument.facture_commerciale and _exploitable(self.par_id[m])
               for m in g.membres):
            return False
        for mid in g.membres:
            m = self.par_id[mid]
            if m.type is TypeDocument.declaration and _exploitable(m):
                q = mrn_prefixe(_txt(m.dec.mrn))
                if len(q) == 15 and q != p:
                    return True
        return False

    def executer(self) -> ResultatRegroupement:
        exploitables = [d for d in self.docs if _exploitable(d)]
        # 2. graines
        for d in exploitables:
            if d.type is TypeDocument.facture_commerciale:
                self._nouveau_groupe(d)
        # 3. déclarations (y compris versions rectificatives)
        orphelines_dec: list[Document] = []
        for d in exploitables:
            if d.type is not TypeDocument.declaration:
                continue
            cands = self._meilleur_par_groupe(d, (TypeDocument.facture_commerciale,), self.signaux_declaration)
            retenus = self._departager(d, {gi: v for gi, v in cands.items() if v[0] >= 2})
            if retenus:
                groupes = [self.groupes[gi] for gi in retenus]
                vals = [retenus[gi] for gi in retenus]
                cible = self._fusionner(groupes) if len(groupes) > 1 else groupes[0]
                score = max(v[0] for v in vals)
                sig = sorted({s for v in vals for s in v[1]}, key=_ORDRE_SIGNAUX.index)
                self._ajouter(cible, d.id, score, sig)
            else:
                orphelines_dec.append(d)
        # versions rectificatives : rejoignent le dossier d'une autre version du même préfixe MRN
        for d in list(orphelines_dec):
            p = mrn_prefixe(_txt(d.dec.mrn))
            if len(p) != 15:
                continue
            for g in self.groupes:
                autres = [self.par_id[m] for m in g.membres if self.par_id[m].type is TypeDocument.declaration]
                if any(mrn_prefixe(_txt(a.dec.mrn)) == p for a in autres) and self._compatible(d, g):
                    sc, sg = next(
                        (g.membres[a.id] for a in autres if mrn_prefixe(_txt(a.dec.mrn)) == p),
                        (3, [SignalLien.mrn_cite]),
                    )
                    self._ajouter(g, d.id, sc, [*sg, SignalLien.mrn_cite])
                    orphelines_dec.remove(d)
                    break
        for d in orphelines_dec:
            score_partiel = 0
            cands = self._meilleur_par_groupe(d, (TypeDocument.facture_commerciale,), self.signaux_declaration)
            if cands:
                score_partiel = max(v[0] for v in cands.values())
            repli = self._repli_meme_source(d, score_partiel)
            if repli is not None:
                score, g = repli
                sig = [*(cands[self.groupes.index(g)][1] if self.groupes.index(g) in cands else []),
                       SignalLien.meme_dossier_source]
                self._ajouter(g, d.id, score, sig)
            else:
                # 7. déclaration orpheline : son propre dossier ; ses versions la rejoignent
                p = mrn_prefixe(_txt(d.dec.mrn))
                existant = next(
                    (g for g in self.groupes if len(p) == 15 and self.par_id[g.graine].type is TypeDocument.declaration
                     and mrn_prefixe(_txt(self.par_id[g.graine].dec.mrn)) == p), None,
                )
                if existant is not None:
                    self._ajouter(existant, d.id, 3, [SignalLien.mrn_cite])
                else:
                    self._nouveau_groupe(d)
        # 4. factures transitaires (plusieurs dossiers possibles)
        self._rattacher_type(
            TypeDocument.facture_transitaire,
            (TypeDocument.declaration, TypeDocument.facture_commerciale, TypeDocument.document_support),
            self.signaux_ft,
            orphelin_dossier=True,
        )
        # 5. avoirs
        self._rattacher_type(
            TypeDocument.avoir, (TypeDocument.facture_transitaire, TypeDocument.declaration), self.signaux_avoir,
            orphelin_dossier=True,
        )
        # documents support, non exploitables, inconnus
        non_rattaches: list[str] = []
        for d in self.docs:
            if d.doublon_de or any(d.id in g.membres for g in self.groupes):
                continue
            # restent : supports, non exploitables, inconnus, et documents typés sans champs (extraction
            # en échec), rattachés comme des supports
            cands = self._meilleur_par_groupe(
                d,
                (TypeDocument.facture_commerciale, TypeDocument.declaration, TypeDocument.facture_transitaire),
                self.signaux_support,
            )
            retenus = self._departager(d, {gi: v for gi, v in cands.items() if v[0] >= 2})
            if retenus:
                for gi, (score, sig) in sorted(retenus.items()):
                    self._ajouter(self.groupes[gi], d.id, score, sig)
                continue
            repli = self._repli_meme_source(d, max((v[0] for v in cands.values()), default=0))
            if repli is not None:
                score, g = repli
                self._ajouter(g, d.id, score, [SignalLien.meme_dossier_source])
            elif d.type is TypeDocument.document_non_exploitable or (
                d.type in _ROLE and d.champs is None
            ):
                self._nouveau_groupe(d)  # « intitulé facture » : P1/P2 doivent le voir
            else:
                non_rattaches.append(d.id)
        # 7 bis. fusion des dossiers incomplets avec l'unique dossier complet de leur frontière
        if self.options.meme_source:
            self._consolider()
        self._corroborer()
        self._corroborer_faibles()
        # doublons : suivent leur original
        for d in self.docs:
            if not d.doublon_de:
                continue
            places = False
            for g in self.groupes:
                if d.doublon_de in g.membres:
                    sc, sg = g.membres[d.doublon_de]
                    self._ajouter(g, d.id, sc, [s for s in sg if s is not SignalLien.graine] or [SignalLien.meme_dossier_source])
                    places = True
            if not places:
                non_rattaches.append(d.id)
        return ResultatRegroupement(
            dossiers=self._construire_dossiers(),
            non_rattaches=non_rattaches,
            frontiere_document={k: "/".join(v) for k, v in self.front.items()},
        )

    def _rattacher_type(self, type_doc, cibles, fn_signaux, *, orphelin_dossier: bool) -> None:
        for d in self.docs:
            if d.type is not type_doc or not _exploitable(d):
                continue
            cands = self._meilleur_par_groupe(d, cibles, fn_signaux)
            retenus = self._departager(d, {gi: v for gi, v in cands.items() if v[0] >= 2})
            if retenus:
                for gi, (score, sig) in sorted(retenus.items()):
                    self._ajouter(self.groupes[gi], d.id, score, sig)
                continue
            repli = self._repli_meme_source(d, max((v[0] for v in cands.values()), default=0))
            if repli is not None:
                score, g = repli
                gi = self.groupes.index(g)
                sig = [*(cands[gi][1] if gi in cands else []), SignalLien.meme_dossier_source]
                self._ajouter(g, d.id, score, sig)
            elif orphelin_dossier:
                self._nouveau_groupe(d)

    def _corroborer(self) -> None:
        """Déclaration rattachée sans référence explicite à la facture (même dossier source, TVA et codes) : une
        facture de transitaire ou un document support du **même dossier**, lui-même rattaché à la facture
        commerciale par une référence explicite (facture citée, transport), qui cite le MRN de la déclaration ou un
        titre de transport qu'elle cite, apporte la référence manquante (``mrn_cite`` / ``ref_transport``) :
        le lien n'est plus faible (D-2407). Rien n'est réuni ni déplacé ; seuls les signaux d'un lien existant
        sont complétés."""
        for g in self.groupes:
            fcs = [self.par_id[m] for m in g.membres if self.par_id[m].type is TypeDocument.facture_commerciale
                   and _exploitable(self.par_id[m])]
            if not fcs:
                continue
            relais: list[Document] = []
            for mid in g.membres:
                m = self.par_id[mid]
                if not _exploitable(m) or m.doublon_de:
                    continue
                if m.type is TypeDocument.facture_transitaire:
                    sig = {x for fc in fcs for x in self.signaux_ft(m, fc)}
                elif m.type is TypeDocument.document_support:
                    sig = {x for fc in fcs for x in self.signaux_support(m, fc)}
                else:
                    continue
                if sig & SIGNAUX_FORTS:
                    relais.append(m)
            if not relais:
                continue
            for mid, (score, sig) in list(g.membres.items()):
                d = self.par_id[mid]
                if mid == g.graine or d.type is not TypeDocument.declaration or not _exploitable(d) or (
                        set(sig) & SIGNAUX_FORTS):
                    continue
                mrn = _txt(d.dec.mrn)
                refs = _refs_documents_declaration(d)
                ajout: set[SignalLien] = set()
                for r in relais:
                    if r.type is TypeDocument.facture_transitaire:
                        if mrn and any(mrn_egaux(x, mrn) for x in _mrns_ft(r)):
                            ajout.add(SignalLien.mrn_cite)
                    elif any(ref_transport_compatibles(a, b) for a in _transports_support(r) for b in refs):
                        ajout.add(SignalLien.ref_transport)
                if ajout:
                    nouveaux = sorted(set(sig) | ajout, key=_ORDRE_SIGNAUX.index)
                    g.membres[mid] = (max(score, self._score(TypeDocument.declaration, nouveaux)), nouveaux)

    def _refs_lues(self, d: Document) -> dict[str, list[str]]:
        """Références lues d'un document, par genre : ``mrn`` (MRN de la déclaration, à défaut celui de son nom de
        fichier ; MRN cités), ``transport`` (titres de transport ; références citées par une déclaration),
        ``numero`` (numéro propre), ``cite`` (numéros de facture cités)."""
        out: dict[str, list[str]] = {"mrn": [], "transport": [], "numero": [], "cite": []}
        if not _exploitable(d):
            return out
        num = _numero(d)
        if num and d.type is not TypeDocument.declaration:
            out["numero"].append(num)
        if d.type is TypeDocument.declaration:
            mrn = _txt(d.dec.mrn)
            if not mrn:
                fic = self._fichier(d)
                nom = PurePosixPath(fic.chemin_relatif).stem if fic else ""
                mrn = next((t for t in re.split(r"[^A-Za-z0-9]+", nom) if est_mrn(t)), None)
            out["mrn"] += [mrn] if mrn else []
            refs = _refs_documents_declaration(d)
            out["transport"] += refs
            out["cite"] += refs
        elif d.type is TypeDocument.facture_transitaire:
            out["mrn"] += _mrns_ft(d)
            out["transport"] += _transports_ft(d)
            out["cite"] += [r for r in (_txt(v) for v in d.ft.refs_facture_commerciale) if r]
        elif d.type is TypeDocument.avoir:
            out["mrn"] += [m for m in (_txt(v) for v in d.av.refs_mrn) if m]
            out["transport"] += [r for r in (_txt(v) for v in d.av.refs_transport) if r]
            out["cite"] += [r for r in (_txt(v) for v in d.av.refs_facture_origine) if r]
        elif d.type is TypeDocument.facture_commerciale:
            out["transport"] += [r for r in [_txt(d.fc.ref_transport)] if r]
        elif d.type is TypeDocument.document_support:
            out["transport"] += _transports_support(d)
            out["cite"] += [r for r in (_txt(v) for v in d.sup.refs_facture) if r]
        return out

    def _reference_retrouvee(self, faible: Document, refs_f: dict[str, list[str]], appui: Document,
                             refs_a: dict[str, list[str]]) -> bool:
        """Le document faiblement rattaché et un document solidement rattaché au même dossier partagent une
        référence, à une lecture imparfaite près : MRN (``mrn_proches``), titre de transport
        (``ref_transport_proches`` ; entre deux déclarations, égalité ou inclusion seulement : leurs références
        mêlent numéros de facture et titres), numéro de facture cité par l'un et porté par l'autre (égaux)."""
        if any(mrn_proches(a, b) for a in refs_f["mrn"] for b in refs_a["mrn"]):
            return True
        deux_dec = faible.type is TypeDocument.declaration and appui.type is TypeDocument.declaration
        comparer = ref_transport_compatibles if deux_dec else ref_transport_proches
        if any(comparer(a, b) for a in refs_f["transport"] for b in refs_a["transport"]):
            return True
        return any(ref_egales(a, b) for a in refs_f["numero"] for b in refs_a["cite"]) or any(
            ref_egales(a, b) for a in refs_f["cite"] for b in refs_a["numero"])

    def _corroborer_faibles(self) -> None:
        """Lien faible (score 2, P4) d'un document dont une référence se retrouve, à une lecture imparfaite près,
        sur un document **solidement** rattaché au même dossier (graine ou score ≥ 3) : le lien devient
        « moyenne » (signal ``reference_proche``), jamais « forte » (D-3702). Un document qui ne porte que des
        références étrangères au dossier (facture d'un autre envoi rangée ici) reste faible. Un document lu sans
        aucune référence, dans le **même fichier** qu'un document solidement rattaché, est renforcé de même : rien
        ne le contredit. Rien n'est réuni ni déplacé. Répété tant qu'un lien change (un document renforcé peut
        appuyer le suivant)."""
        for g in self.groupes:
            refs = {mid: self._refs_lues(self.par_id[mid]) for mid in g.membres}
            change = True
            while change:
                change = False
                solides = [mid for mid, (score, sig) in g.membres.items()
                           if (score >= 3 or SignalLien.graine in sig) and _exploitable(self.par_id[mid])
                           and not self.par_id[mid].doublon_de]
                for mid, (score, sig) in list(g.membres.items()):
                    d = self.par_id[mid]
                    if score > 2 or SignalLien.graine in sig or d.doublon_de:
                        continue
                    retrouvee = any(self._reference_retrouvee(d, refs[mid], self.par_id[a], refs[a])
                                    for a in solides if a != mid)
                    sans_reference = not any(refs[mid].values())
                    meme_fichier = sans_reference and any(self._meme_fichier(d, self.par_id[a])
                                                          for a in solides if a != mid)
                    if retrouvee or meme_fichier:
                        g.membres[mid] = (3, sorted(set(sig) | {SignalLien.reference_proche},
                                                    key=_ORDRE_SIGNAUX.index))
                        g.plafond_moyenne.add(mid)
                        change = True

    def _complet(self, g: _Groupe) -> bool:
        types = {self.par_id[m].type for m in g.membres if _exploitable(self.par_id[m])}
        return TypeDocument.facture_commerciale in types and TypeDocument.declaration in types

    def _consolider(self) -> None:
        changement = True
        while changement:
            changement = False
            for g in list(self.groupes):
                if self._complet(g):
                    continue
                autres = [
                    h for h in self.groupes
                    if h is not g and _frontieres_compatibles(h.frontiere, g.frontiere) and h.courriel == g.courriel
                ]
                complets = [h for h in autres if self._complet(h)]
                if len(complets) != 1 or len(autres) != 1:
                    continue
                cible = complets[0]
                for mid, (score, sig) in g.membres.items():
                    if mid in cible.membres:
                        continue
                    if mid == g.graine:
                        # l'ancienne graine n'a qu'un rattachement de frontière
                        self._ajouter(cible, mid, POIDS_FORCE[ForceLien.moyenne], [SignalLien.meme_dossier_source])
                    else:
                        nouveau = min(score, POIDS_FORCE[ForceLien.moyenne])
                        sig2 = [s for s in sig if s is not SignalLien.graine]
                        self._ajouter(cible, mid, nouveau, [*sig2, SignalLien.meme_dossier_source])
                self.groupes.remove(g)
                changement = True
                break

    # -- construction des objets du modèle --

    def _construire_dossiers(self) -> list[Dossier]:
        annee = self.options.annee or date.today().year
        groupes = sorted(self.groupes, key=lambda g: self.ordre[g.graine])
        dossiers = []
        for n, g in enumerate(groupes):
            membres = sorted(g.membres, key=lambda i: (0 if i == g.graine else 1, self.ordre[i]))
            liens = []
            for mid in membres:
                score, sig = g.membres[mid]
                d = self.par_id[mid]
                if mid == g.graine:
                    force = ForceLien.forte
                    sig = sorted(set(sig) | {SignalLien.graine}, key=_ORDRE_SIGNAUX.index)
                    score = max(score, POIDS_FORCE[ForceLien.forte])
                else:
                    force = force_depuis_score(score, sig) or ForceLien.faible
                    if mid in g.plafond_moyenne and force is ForceLien.forte:
                        force = ForceLien.moyenne
                liens.append(
                    LienDocument(
                        id=id_stable(Prefixe.lien, VERSION_REGROUPEMENT, g.graine, mid),
                        document_id=mid,
                        role=_ROLE.get(d.type, RoleLien.support),
                        force=force,
                        signaux=list(sig),
                        score=score,
                    )
                )
            docs = [self.par_id[m] for m in membres]
            types_exp = {d.type for d in docs if _exploitable(d)}
            manquants = [t.value for t in (TypeDocument.facture_commerciale, TypeDocument.declaration)
                         if t not in types_exp]
            cle = cle_idempotence_regroupement(membres)
            dossiers.append(
                Dossier(
                    id=id_stable(Prefixe.dossier, VERSION_REGROUPEMENT, *sorted(membres)),
                    reference=f"D-{annee:04d}-{self.options.numero_depart + n:05d}",
                    cles=self._cles(docs),
                    liens=liens,
                    allocations=self._allocations(docs, cle),
                    transitaire_id=self._transitaire(docs),
                    incomplet=bool(manquants),
                    documents_manquants=manquants,
                    lot_ids=list(self.options.lot_ids),
                    frontiere="/".join(g.frontiere) or None,
                )
            )
        return dossiers

    def _dernieres_declarations(self, docs: Sequence[Document]) -> list[Document]:
        decs = [d for d in docs if d.type is TypeDocument.declaration and _exploitable(d)]
        groupes: dict[str, list[Document]] = {}
        sans: list[Document] = []
        for d in decs:
            p = mrn_prefixe(_txt(d.dec.mrn))
            if len(p) == 15:
                groupes.setdefault(p, []).append(d)
            else:
                sans.append(d)
        retenues = {max(g, key=lambda x: _rang_version(x, self.ordre[x.id])).id for g in groupes.values()}
        return [d for d in decs if d.id in retenues or d in sans]

    def _cles(self, docs: Sequence[Document]) -> ClesDossier:
        def uniq(xs: Iterable[str | None], norm=norm_ref) -> list[str]:
            vus: dict[str, str] = {}
            for x in xs:
                if x and norm(x) and norm(x) not in vus:
                    vus[norm(x)] = x
            return list(vus.values())

        fts = [d for d in docs if d.type is TypeDocument.facture_transitaire and _exploitable(d)]
        fcs = [d for d in docs if d.type is TypeDocument.facture_commerciale and _exploitable(d)]
        transports: list[str | None] = []
        for d in docs:
            if not _exploitable(d):
                continue
            if d.type is TypeDocument.facture_commerciale:
                transports.append(_txt(d.fc.ref_transport))
            elif d.type is TypeDocument.facture_transitaire:
                transports.extend(_txt(v) for v in d.ft.refs_transport)
            elif d.type is TypeDocument.document_support:
                transports.extend(_transports_support(d))
        return ClesDossier(
            num_facture_transitaire=uniq(_numero(d) for d in fts),
            ref_transport=uniq(transports, norm_ref_transport),
            mrn=uniq(_txt(d.dec.mrn) for d in self._dernieres_declarations(docs)),
            num_facture_commerciale=uniq(_numero(d) for d in fcs),
        )

    def _transitaire(self, docs: Sequence[Document]) -> str | None:
        for d in docs:
            if d.type is not TypeDocument.facture_transitaire or not _exploitable(d):
                continue
            em = d.ft.emetteur
            tid = identifier_transitaire(_txt(em.tva), _txt(em.nom), self.transitaires)
            if tid is not None:
                return tid
        return None

    def _allocations(self, docs: Sequence[Document], cle: str) -> list[Allocation]:
        out: list[Allocation] = []
        fcs = [d for d in docs if d.type is TypeDocument.facture_commerciale and _exploitable(d)]
        decs = self._dernieres_declarations(docs)
        fts = [d for d in docs if d.type is TypeDocument.facture_transitaire and _exploitable(d)]

        def alloc(source: str, cible: str | None, methode: MethodeAllocation, montant: Decimal | None,
                  ligne: int | None = None, mrn: str | None = None) -> Allocation:
            return Allocation(
                id=id_stable(Prefixe.allocation, cle, source, ligne if ligne is not None else "", cible or "", mrn or ""),
                source_document_id=source, source_ligne=ligne, cible_document_id=cible, mrn=mrn,
                montant_alloue=montant, methode=methode,
            )

        # facture commerciale -> déclaration (§7.5 étape 8)
        for fc in fcs:
            num = _numero(fc)
            total = _dec(fc.fc.total_facture)
            cibles = decs
            if not cibles:
                continue
            if len(cibles) == 1:
                d = cibles[0]
                refs = _refs_documents_declaration(d)
                explicite = bool(num) and any(ref_compatibles(r, num) for r in refs)
                autres_fc = len(fcs) > 1
                if autres_fc and explicite:
                    out.append(alloc(fc.id, d.id, MethodeAllocation.reference_explicite,
                                     self._montant_explicite(d, fc, len(fcs)) or total))
                else:
                    out.append(alloc(fc.id, d.id, MethodeAllocation.totalite, total))
                continue
            # facture répartie sur plusieurs déclarations
            explicites = {d.id: self._montant_explicite(d, fc, len(fcs)) for d in cibles
                          if num and any(ref_compatibles(r, num) for r in _refs_documents_declaration(d))}
            if explicites and len(explicites) == len(cibles) and all(m is not None for m in explicites.values()):
                for d in cibles:
                    out.append(alloc(fc.id, d.id, MethodeAllocation.reference_explicite, explicites[d.id]))
                continue
            declares = [_dec(d.dec.montant_total_facture) for d in cibles]
            for d, part in zip(cibles, repartir_prorata(total, declares), strict=True):
                out.append(alloc(fc.id, d.id, MethodeAllocation.prorata, part))

        # lignes de facture transitaire -> MRN
        par_prefixe = {mrn_prefixe(_txt(d.dec.mrn)): d for d in decs if len(mrn_prefixe(_txt(d.dec.mrn))) == 15}
        for ft in fts:
            mrns_cites = {mrn_prefixe(m) for m in _mrns_ft(ft)} - {""}
            if len(decs) == 1 and len(mrns_cites) <= 1:
                d = decs[0]
                out.append(alloc(ft.id, d.id, MethodeAllocation.totalite, _total_debours(ft), mrn=_txt(d.dec.mrn)))
                continue
            if not decs:
                continue
            # plusieurs MRN : chaque ligne de débours vers son MRN, sinon prorata des taxes déclarées
            dans_dossier = [p for p in mrns_cites if p in par_prefixe]
            taxes = [_total_taxes(d) for d in decs]
            for i, li in enumerate(ft.ft.lignes):
                if not li.nature.est_debours and li.nature is not NatureLigne.debours_combines:
                    continue
                m = _txt(li.mrn)
                p = mrn_prefixe(m) if m else ""
                montant = _dec(li.montant_ht)
                if p and p in par_prefixe:
                    d = par_prefixe[p]
                    out.append(alloc(ft.id, d.id, MethodeAllocation.ligne_par_mrn, montant, ligne=i, mrn=m))
                elif p:
                    continue  # ligne d'un MRN d'un autre dossier
                elif len(decs) == 1 and dans_dossier:
                    # ligne sans MRN, facture multi-MRN : part de ce dossier inconnue -> prorata
                    d = decs[0]
                    out.append(alloc(ft.id, d.id, MethodeAllocation.prorata, None, ligne=i, mrn=_txt(d.dec.mrn)))
                else:
                    for d, part in zip(decs, repartir_prorata(montant, taxes), strict=True):
                        out.append(alloc(ft.id, d.id, MethodeAllocation.prorata, part, ligne=i, mrn=_txt(d.dec.mrn)))
        return out

    def _montant_explicite(self, dec: Document, fc: Document, nb_fc: int) -> Decimal | None:
        """Montant déclaré pour cette facture : somme des articles qui la citent, ou total déclaré si la
        déclaration ne cite qu'une facture."""
        num = _numero(fc)
        if not num:
            return None
        c = dec.dec
        montants = [
            _dec(a.montant_facture_article) for a in c.articles
            if any(ref_compatibles(_txt(r), num) for r in a.references_facture)
        ]
        if montants and all(m is not None for m in montants):
            return sum(montants, Decimal(0))  # type: ignore[arg-type]
        factures_citees = {norm_ref(r.reference.valeur) for r in c.documents_references
                           if r.reference is not None and r.reference.valeur
                           and r.type_code is not None and (r.type_code.valeur or "").upper() in ("N380", "N325", "380", "325")}
        if nb_fc == 1 or len(factures_citees) <= 1:
            return _dec(c.montant_total_facture)
        return None


def repartir_prorata(total: Decimal | None, poids: Sequence[Decimal | None]) -> list[Decimal | None]:
    """Parts de ``total`` au prorata de ``poids`` (§8.2 : centime, demi vers le haut). Le reliquat d'arrondi
    va à la dernière part calculée, si bien que la somme des parts vaut ``total`` quand tous les poids sont
    connus (3 × 33,33 + 0,01). Part ``None`` si le total, le poids ou la somme des poids manque."""
    somme = sum((p for p in poids if p is not None), Decimal(0))
    if total is None or somme <= 0:
        return [None] * len(poids)
    parts: list[Decimal | None] = [
        None if p is None else (total * p / somme).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP) for p in poids
    ]
    connus = [i for i, p in enumerate(parts) if p is not None]
    if connus and len(connus) == len(parts):
        dernier = connus[-1]
        reste = total - sum((p for p in parts if p is not None), Decimal(0))
        parts[dernier] = (parts[dernier] or Decimal(0)) + reste
    return parts


def regrouper(
    documents: Sequence[Document],
    fichiers: Mapping[str, Fichier] | None = None,
    *,
    profil: ProfilTolerances | None = None,
    transitaires: Sequence[Transitaire] = (),
    options: OptionsRegroupement | None = None,
) -> ResultatRegroupement:
    """Regroupe les documents d'un lot en dossiers (§7.5). Fonction pure : les documents ne sont pas
    modifiés ; l'ordre d'entrée sert d'ordre de départage (déterminisme)."""
    return _Regroupeur(
        documents, fichiers or {}, profil or ProfilTolerances(id="tol_regroupement"), transitaires,
        options or OptionsRegroupement(),
    ).executer()
