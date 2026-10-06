"""``ControlContext`` : vue figée d'un dossier pour les contrôles (SPEC §7.6, §8).

Les contrôles sont des fonctions pures ``(ControlContext) -> list[ResultatControle]`` : ils n'ont accès
qu'à ce contexte (aucun réseau, aucune base, aucun modèle). Le contexte est construit par
``ControlContext.construire(...)``, qui **copie en profondeur** les documents : un contrôle ne peut pas
modifier les données sources.

Le contexte fournit aussi les **constructeurs** de résultats (``resultat``, ``conforme``,
``non_applicable``, ``non_verifiable``, ``constat``) qui remplissent les champs communs (dossier,
version, exécution, empreinte des tolérances) et donnent des identifiants **stables** (même dossier,
même version, même unité -> même identifiant), condition de la reproductibilité (§6.2.12).
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from types import MappingProxyType
from typing import Any

from controldone.controls import corroboration as _corroboration
from controldone.controls.classify import Classement, classify, montant_pour_spec, sens_pour, trier_raisons
from controldone.controls.confusion import confusion_applicable, confusion_test, confusion_test_fn
from controldone.controls.specs import ControlSpec, get_spec
from controldone.controls.tolerances import Tolerances
from controldone.ids import IdGenerator, Prefixe, id_stable
from controldone.model.documents import Document
from controldone.model.dossier import Allocation, Dossier, LienDocument
from controldone.model.enums import (
    Composante,
    Methode,
    MethodeAllocation,
    NatureMontant,
    Niveau,
    Outcome,
    QualiteTexte,
    RaisonCode,
    RoleLien,
    RolePreuve,
    TypeDocument,
)
from controldone.model.recouvrement import EcartARecouvrer
from controldone.model.referentiel import (
    Entite,
    GrilleTarifaire,
    ParametresPetitsEnvois,
    ProfilTolerances,
    Transitaire,
)
from controldone.model.resultats import Constat, Preuve, ResultatControle
from controldone.model.valeur import ValeurSourcee
from controldone.normalize.fiscal import normalize_vat
from controldone.normalize.refs import cle_confusion_ocr, mrn_prefixe
from controldone.taux_reference import TableTauxReference

__all__ = ["AutreDossier", "Confusion", "ControlContext", "cle_unite", "preuve"]


@dataclass(frozen=True, slots=True)
class AutreDossier:
    """Autre dossier du même client (famille F), avec ses documents. Jamais d'un autre client."""

    dossier: Dossier
    documents: Mapping[str, Document]


@dataclass(frozen=True, slots=True)
class Confusion:
    """Candidat au test de confusion (§8.5.4) pour ``ControlContext.classify``.

    Forme simple : ``Confusion(valeur, autre=..., tolerance=...)`` — la valeur lue devrait valoir ``autre``.
    Forme générale : ``Confusion(valeur, accepte=fn)`` — ``fn(variante) -> bool`` dit si la variante de
    lecture ferait disparaître l'écart (utile pour un opérande : base, taux, ligne d'une somme).
    """

    valeur: ValeurSourcee
    autre: Decimal | None = None
    tolerance: Decimal | None = None
    accepte: Callable[[Decimal], bool] | None = None


def cle_unite(**parties: str | Iterable[str] | int | None) -> str:
    """Clé canonique d'une unité de comparaison : ``cle_unite(ft="doc_a", dec=["doc_c", "doc_b"])``
    -> ``"dec:doc_b+doc_c|ft:doc_a"``. Clés triées, listes triées, ``None`` ignorés.

    Conventions partagées (règles de non-double-comptage, §8.6) : familles C et G4 utilisent
    ``cle_unite(ft=..., dec=[...])`` ; A3–A7 ``cle_unite(fc=[...], dec=[...])``.
    """
    morceaux = []
    for k in sorted(parties):
        v = parties[k]
        if v is None:
            continue
        if isinstance(v, str | int):
            morceaux.append(f"{k}:{v}")
        else:
            morceaux.append(f"{k}:{'+'.join(sorted(str(x) for x in v))}")
    return "|".join(morceaux) or "dossier"


def preuve(
    valeur: ValeurSourcee | None,
    role: RolePreuve | str,
    *,
    calcul: str | None = None,
) -> Preuve:
    """Preuve à partir d'une valeur sourcée (document, page, valeur brute recopiés) ou d'un calcul."""
    if valeur is None:
        return Preuve(role=RolePreuve(role), calcul=calcul)
    return Preuve(
        valeur_sourcee_id=valeur.id,
        role=RolePreuve(role),
        document_id=valeur.document_id,
        page=valeur.page,
        valeur_brute=valeur.valeur_brute if valeur.valeur_brute is not None else valeur.valeur,
        chemin=valeur.chemin,
        calcul=calcul,
    )


@dataclass(frozen=True)
class ControlContext:
    """Vue figée d'un dossier (§7.6). Construire avec ``ControlContext.construire``."""

    dossier: Dossier
    documents: Mapping[str, Document]
    profil: ProfilTolerances
    grilles: tuple[GrilleTarifaire, ...] = ()
    entites: tuple[Entite, ...] = ()
    transitaires: tuple[Transitaire, ...] = ()
    autres_dossiers: tuple[AutreDossier, ...] = ()
    taux_reference: TableTauxReference | None = None
    parametres_petits_envois: ParametresPetitsEnvois = field(default_factory=ParametresPetitsEnvois)
    ecarts_recouvrement: tuple[EcartARecouvrer, ...] = ()
    execution_id: str | None = None
    ids: IdGenerator = field(default_factory=lambda: IdGenerator.deterministe(0))
    #: Lecture corroborée exigée pour un ``ecart_certain`` (D-1700). Toujours vrai en production ; faux
    #: seulement dans les tests unitaires d'un contrôle bâtis sur des documents minimaux sans redondance.
    exiger_lecture_corroboree: bool = True
    # Résultats des contrôles déjà exécutés (rempli par le moteur, lu via ``anterieurs``).
    _journal: list[ResultatControle] = field(default_factory=list, repr=False, compare=False)

    # --- construction ---------------------------------------------------------------------------

    @classmethod
    def construire(
        cls,
        dossier: Dossier,
        documents: Iterable[Document],
        profil: ProfilTolerances | None = None,
        *,
        grilles: Iterable[GrilleTarifaire] = (),
        entites: Iterable[Entite] = (),
        transitaires: Iterable[Transitaire] = (),
        autres_dossiers: Iterable[AutreDossier] = (),
        taux_reference: TableTauxReference | None = None,
        parametres_petits_envois: ParametresPetitsEnvois | None = None,
        ecarts_recouvrement: Iterable[EcartARecouvrer] = (),
        execution_id: str | None = None,
        ids: IdGenerator | None = None,
        exiger_lecture_corroboree: bool = True,
    ) -> ControlContext:
        """Copie profonde et indexation. Seuls les documents liés au dossier sont retenus ; les grilles
        non validées sont écartées (§6.2.4)."""
        ids_lies = set(dossier.document_ids())
        docs = {d.id: d.model_copy(deep=True) for d in documents if d.id in ids_lies}
        return cls(
            dossier=dossier.model_copy(deep=True),
            documents=MappingProxyType(docs),
            profil=(profil or ProfilTolerances()).model_copy(deep=True),
            grilles=tuple(g.model_copy(deep=True) for g in grilles if g.statut.value == "validee"),
            entites=tuple(e.model_copy(deep=True) for e in entites),
            transitaires=tuple(t.model_copy(deep=True) for t in transitaires),
            autres_dossiers=tuple(autres_dossiers),
            taux_reference=taux_reference,
            parametres_petits_envois=parametres_petits_envois or ParametresPetitsEnvois(),
            ecarts_recouvrement=tuple(ecarts_recouvrement),
            execution_id=execution_id,
            ids=ids or IdGenerator.deterministe(0),
            exiger_lecture_corroboree=exiger_lecture_corroboree,
        )

    def __post_init__(self) -> None:
        index: dict[str, ValeurSourcee] = {}
        for d in self.documents.values():
            for v in d.valeurs():
                index[v.id] = v
        object.__setattr__(self, "_index_valeurs", MappingProxyType(index))
        object.__setattr__(self, "_tol", Tolerances(self.profil))
        object.__setattr__(self, "_empreinte", self.profil.empreinte())
        object.__setattr__(self, "_reseaux", {})
        object.__setattr__(self, "_rangees", {})

    # --- accès de base ----------------------------------------------------------------------------

    @property
    def tol(self) -> Tolerances:
        return self._tol  # type: ignore[attr-defined]

    @property
    def empreinte_tolerances(self) -> str:
        return self._empreinte  # type: ignore[attr-defined]

    def document(self, document_id: str) -> Document | None:
        return self.documents.get(document_id)

    def valeur(self, valeur_id: str) -> ValeurSourcee | None:
        return self._index_valeurs.get(valeur_id)  # type: ignore[attr-defined]

    def document_de(self, valeur: ValeurSourcee) -> Document | None:
        return self.documents.get(valeur.document_id) if valeur.document_id else None

    def qualite_page(self, valeur: ValeurSourcee) -> QualiteTexte | None:
        doc = self.document_de(valeur)
        ref = doc.page_ref(valeur.page) if doc else None
        return ref.qualite_texte if ref else None

    # --- documents par rôle ------------------------------------------------------------------------

    def documents_par_role(self, role: RoleLien | str, *, avec_doublons: bool = False) -> list[Document]:
        """Documents liés avec ce rôle, dans l'ordre des liens du dossier. Les doublons (F1, ``doublon_de``)
        sont exclus par défaut : une seule occurrence est comptée."""
        r = RoleLien(role)
        out = []
        for lien in self.dossier.liens:
            if lien.role is not r:
                continue
            doc = self.documents.get(lien.document_id)
            if doc is None or (doc.doublon_de and not avec_doublons):
                continue
            out.append(doc)
        return out

    def factures_commerciales(self) -> list[Document]:
        """Factures commerciales exploitables (type ``facture_commerciale`` avec champs)."""
        return [
            d for d in self.documents_par_role(RoleLien.facture_commerciale)
            if d.type is TypeDocument.facture_commerciale and d.champs is not None
        ]

    def declarations(self, *, dernieres_versions: bool = True) -> list[Document]:
        """Déclarations du dossier. Par défaut, seule la **dernière version** de chaque préfixe MRN est
        retenue (§5.3.2 : ne jamais additionner deux versions). Dernière = ``version`` imprimée la plus
        haute, puis ``date_acceptation`` la plus récente, puis ordre des liens."""
        decs = [
            d for d in self.documents_par_role(RoleLien.declaration)
            if d.type is TypeDocument.declaration and d.champs is not None
        ]
        if not dernieres_versions:
            return decs
        groupes: dict[str, list[Document]] = {}
        sans_mrn: list[Document] = []
        for d in decs:
            p = d.dec.mrn_prefixe
            if p and len(p) == 15:
                # D-2315 : deux préfixes égaux aux confusions OCR près (5/S, 0/O…) sont le même MRN lu deux fois
                # (version rectificative, copie) : jamais deux déclarations à additionner.
                groupes.setdefault(cle_confusion_ocr(p), []).append(d)
            else:
                sans_mrn.append(d)
        retenues = {max(g, key=self._rang_version).id for g in groupes.values()}
        ids_sans_mrn = {d.id for d in sans_mrn}
        return [d for d in decs if d.id in retenues or d.id in ids_sans_mrn]

    def version_retenue(self, declaration: Document) -> Document | None:
        """Version retenue (``declarations()``) du MRN de cette déclaration, préfixes comparés aux confusions OCR
        près (D-2315) ; ``None`` sans préfixe de 15 caractères."""
        p = declaration.dec.mrn_prefixe
        if not p or len(p) != 15:
            return None
        cle = cle_confusion_ocr(p)
        return next((d for d in self.declarations()
                     if d.dec.mrn_prefixe and len(d.dec.mrn_prefixe) == 15
                     and cle_confusion_ocr(d.dec.mrn_prefixe) == cle), None)

    def versions_anterieures(self, declaration: Document) -> list[Document]:
        """Autres versions (rectificatives ou initiales) du même préfixe MRN (condition 7 de §8.5.1), préfixes
        comparés aux confusions OCR près (D-2315)."""
        p = declaration.dec.mrn_prefixe
        if not p:
            return []
        cle = cle_confusion_ocr(p) if len(p) == 15 else p
        return [
            d for d in self.declarations(dernieres_versions=False)
            if d.id != declaration.id and d.dec.mrn_prefixe
            and (cle_confusion_ocr(d.dec.mrn_prefixe) if len(d.dec.mrn_prefixe) == 15 else d.dec.mrn_prefixe) == cle
        ]

    def _rang_version(self, d: Document) -> tuple:
        c = d.dec
        v = c.version.decimal_ou_none() if c.version else None
        dt = c.date_acceptation.valeur if c.date_acceptation and c.date_acceptation.valeur else ""
        ordre = self.dossier.document_ids().index(d.id)
        return (v if v is not None else Decimal(-1), dt, ordre)

    def factures_transitaires(self) -> list[Document]:
        return [
            d for d in self.documents_par_role(RoleLien.facture_transitaire)
            if d.type is TypeDocument.facture_transitaire and d.champs is not None
        ]

    def avoirs(self) -> list[Document]:
        return [d for d in self.documents_par_role(RoleLien.avoir) if d.type is TypeDocument.avoir and d.champs]

    def supports(self) -> list[Document]:
        return self.documents_par_role(RoleLien.support)

    # --- liens, allocations ------------------------------------------------------------------------

    def lien(self, document_id: str) -> LienDocument | None:
        return self.dossier.lien(document_id)

    def liens_pour(self, document_ids: Iterable[str]) -> list[LienDocument]:
        out = []
        for i in dict.fromkeys(document_ids):
            lien = self.lien(i)
            if lien is not None:
                out.append(lien)
        return out

    def allocations_pour(self, document_id: str) -> list[Allocation]:
        return [
            a for a in self.dossier.allocations
            if document_id in (a.source_document_id, a.cible_document_id)
        ]

    # --- référentiels ------------------------------------------------------------------------------

    def entite_par_tva(self, tva: str | None) -> Entite | None:
        t = normalize_vat(tva)
        if not t:
            return None
        for e in self.entites:
            if e.tva and normalize_vat(e.tva) == t:
                return e
        return None

    def grilles_applicables(self, transitaire_id: str | None, le: date | None) -> list[GrilleTarifaire]:
        """Grilles **validées** du transitaire, valides à la date (§13)."""
        if not transitaire_id:
            return []
        return [g for g in self.grilles if g.applicable(transitaire_id, le)]

    def taux_bce(self, devise: str, le: date) -> Decimal | None:
        """Taux de référence (devise par EUR) — **jamais** pour un montant en jeu (§8.7)."""
        return self.taux_reference.devise_par_eur(devise, le) if self.taux_reference else None

    def mrn_prefixes(self) -> dict[str, Document]:
        """Préfixe MRN -> déclaration retenue."""
        return {d.dec.mrn_prefixe: d for d in self.declarations() if d.dec.mrn_prefixe}

    @staticmethod
    def mrn_prefixe(valeur: str | None) -> str:
        return mrn_prefixe(valeur)

    # --- résultats antérieurs (exécution ordonnée, Annexe A) ---------------------------------------

    def anterieurs(self, controle_id: str | None = None, *, unite: str | None = None) -> tuple[ResultatControle, ...]:
        """Résultats déjà produits par les contrôles exécutés avant celui-ci (ordre de l'Annexe A)."""
        return tuple(
            r for r in self._journal
            if (controle_id is None or r.controle_id == controle_id) and (unite is None or r.unite == unite)
        )

    # --- confiance minimale utile (P3) -------------------------------------------------------------

    def utilisable(self, valeur: ValeurSourcee | None) -> bool:
        """Valeur présente, lisible et de confiance ≥ ``C_MIN_UTILE`` (sinon : ``non_verifiable``, P3)."""
        return valeur is not None and valeur.est_lisible and valeur.confiance >= self.profil.c_min_utile

    def raison_inutilisable(self, valeur: ValeurSourcee | None) -> RaisonCode:
        if valeur is None or not valeur.est_lisible:
            return RaisonCode.valeur_absente
        return RaisonCode.confiance_insuffisante

    # --- classement ----------------------------------------------------------------------------------

    def lecture_douteuse(self, candidats: Iterable[Confusion]) -> bool:
        """Test de confusion (§8.5.4) sur les candidats éligibles (méthode ocr/llm, page ocr/natif_faible)."""
        for c in candidats:
            if not confusion_applicable(c.valeur, self.qualite_page(c.valeur)):
                continue
            if self.confirmee_par_identite(c.valeur):
                # D-2303 : la valeur lue entre dans une identité imprimée du document qui tient (somme, produit,
                # écho) ; une autre lecture la romprait. La confusion n'explique donc pas l'écart.
                continue
            brut = c.valeur.valeur_brute or c.valeur.valeur
            if c.accepte is not None:
                if confusion_test_fn(brut, c.accepte):
                    return True
            elif c.autre is not None and c.tolerance is not None and confusion_test(brut, c.autre, c.tolerance):
                return True
        return False

    def confirmee_par_identite(self, valeur: ValeurSourcee) -> bool:
        """La valeur lue est membre (non inerte) d'une identité arithmétique de son document qui tient (D-2303).
        Confirmation directe seulement : la confirmation par la rangée (D-1701) prouve l'emplacement de la
        lecture, pas ses caractères."""
        doc = self.document_de(valeur)
        if doc is None:
            return False
        return any(i.tient and valeur.id in i.confirmes for i in self.reseau_identites(doc))

    def reseau_identites(self, document: Document) -> tuple[_corroboration.Identite, ...]:
        """Identités arithmétiques imprimées du document, sur ses valeurs lues (D-1700), mises en cache."""
        cache: dict[str, tuple[_corroboration.Identite, ...]] = self._reseaux  # type: ignore[attr-defined]
        if document.id not in cache:
            cache[document.id] = _corroboration.reseau(document, self.utilisable, self.tol)
        return cache[document.id]

    def rangees_valeurs(self, document: Document) -> dict[str, str]:
        """Valeur -> rangée de tableau qui la porte (D-1700), mis en cache."""
        cache: dict[str, dict[str, str]] = self._rangees  # type: ignore[attr-defined]
        if document.id not in cache:
            cache[document.id] = _corroboration.rangees(document)
        return cache[document.id]

    def lecture_corroboree(
        self, valeurs_cles: Sequence[ValeurSourcee], *, operandes_non_confirmees_max: int = 0
    ) -> tuple[bool, list[str]]:
        """Chaque montant lu des valeurs clés est-il confirmé par une autre identité de son document ?
        (voir ``controls/corroboration.py``, D-1700)."""
        return _corroboration.evaluer(
            valeurs_cles,
            index=self.valeur,
            document=self.document,
            reseau_de=self.reseau_identites,
            rangees_de=self.rangees_valeurs,
            operandes_non_confirmees_max=operandes_non_confirmees_max,
        )

    def classify(
        self,
        spec: ControlSpec | str,
        *,
        ecart: Decimal | None,
        tolerance: Decimal | None,
        seuil_certitude: Decimal | None,
        valeurs_cles: Sequence[ValeurSourcee],
        confusion: Iterable[Confusion] = (),
        documents: Iterable[str] = (),
        allocations: Sequence[Allocation] | None = None,
        operandes_non_confirmees_max: int = 0,
        liens_etablis: Iterable[str] = (),
        **kwargs: Any,
    ) -> Classement:
        """``classify`` (§8.5.1) avec collecte automatique :

        - des liens des documents des valeurs clés (et de ``documents``) — condition 5 ;
        - des allocations touchant ces documents (sauf si ``allocations`` est fourni) — condition 5 ;
        - du test de confusion sur ``confusion`` — condition 6 ;
        - de la lecture corroborée (D-1700) : un classement qui serait ``ecart_certain`` devient
          ``a_verifier`` (raison ``lecture_non_corroboree``) si un montant lu d'une valeur clé n'est confirmé
          par aucune autre identité arithmétique de son document. ``operandes_non_confirmees_max`` : lignes
          d'une somme contestée admises sans confirmation (B3).

        - ``liens_etablis`` : documents dont le rattachement est établi par la valeur comparée elle-même (F3 : le
          MRN lu sur les deux factures, D-4209) ; leur lien au dossier n'entre pas dans la condition 5.

        Les autres paramètres (``explication``, ``renvoi``, ``eligible``, ``nature_montant``, ``montant``,
        ``raisons_supplementaires``) sont transmis à ``classify``.
        """
        doc_ids = [v.document_id for v in valeurs_cles if v.document_id] + list(documents)
        etablis = set(liens_etablis)
        if allocations is None:
            vues: dict[str, Allocation] = {}
            for i in dict.fromkeys(doc_ids):
                for a in self.allocations_pour(i):
                    vues.setdefault(a.id, a)
            allocations = self._allocations_en_jeu(list(vues.values()), valeurs_cles, doc_ids)
        classement = classify(
            spec,
            ecart=ecart,
            tolerance=tolerance,
            seuil_certitude=seuil_certitude,
            valeurs_cles=self._confiance_par_identite(valeurs_cles),
            c_min_certain=self.profil.c_min_certain,
            liens=self.liens_pour([i for i in doc_ids if i not in etablis]),
            allocations=allocations,
            lecture_douteuse=kwargs.pop("lecture_douteuse", False) or self.lecture_douteuse(confusion),
            **kwargs,
        )
        if classement.niveau is Niveau.ecart_certain and self._avoir_non_ventile(spec, doc_ids, kwargs):
            raisons = trier_raisons([*classement.raisons, RaisonCode.avoir_non_ventile])
            return Classement(Niveau.a_verifier, raisons)
        if classement.niveau is Niveau.ecart_certain and self.exiger_lecture_corroboree:
            corroboree, _ = self.lecture_corroboree(
                valeurs_cles, operandes_non_confirmees_max=operandes_non_confirmees_max
            )
            if not corroboree:
                raisons = trier_raisons([*classement.raisons, RaisonCode.lecture_non_corroboree])
                return Classement(Niveau.a_verifier, raisons)
        return classement

    def _confiance_par_identite(self, valeurs_cles: Sequence[ValeurSourcee]) -> list[ValeurSourcee]:
        """D-2314 : une valeur clé lue sous ``C_MIN_CERTAIN`` (mais au moins ``C_LECTURE_CONFIRMABLE``) dont la
        lecture est confirmée par une identité arithmétique imprimée de son document qui tient (somme, produit,
        écho ; membre direct, hors identité formée des seules valeurs clés : le calcul contesté) satisfait la
        condition de confiance (§8.5.1 condition 3) : une autre lecture de ses caractères romprait cette
        identité. Les autres conditions (ancrage, corroboration D-1700…) restent appliquées."""
        seuil = self.profil.c_min_certain
        if all(v.confiance >= seuil for v in valeurs_cles):
            return list(valeurs_cles)
        ids = {v.id for v in valeurs_cles}
        out = []
        for v in valeurs_cles:
            if (seuil > v.confiance >= C_LECTURE_CONFIRMABLE and v.methode in _METHODES_LUES
                    and not v.est_reconstruite and v.est_lisible):
                doc = self.document_de(v)
                if doc is not None and any(
                    i.tient and v.id in i.confirmes and not i.membres <= ids for i in self.reseau_identites(doc)
                ):
                    v = v.model_copy(update={"confiance": seuil})
            out.append(v)
        return out

    def _allocations_en_jeu(
        self, allocations: Sequence[Allocation], valeurs_cles: Sequence[ValeurSourcee], doc_ids: Sequence[str]
    ) -> list[Allocation]:
        """Allocations dont dépend la comparaison (§8.5.1 condition 5, D-2304) : celles qui relient deux documents
        comparés (source **et** cible parmi les documents du constat ; un contrôle interne à un document ne dépend
        d'aucune répartition) ; pour une facture du transitaire dont des **lignes de débours** sont des valeurs
        clés, seules les allocations de ces lignes (et celles du document entier) comptent : la répartition au
        prorata d'une autre ligne ne touche pas les montants comparés."""
        ids = set(doc_ids)
        lignes_cles: dict[str, set[int]] = {}
        for v in valeurs_cles:
            doc = self.document_de(v)
            if doc is None or doc.type is not TypeDocument.facture_transitaire:
                continue
            k = _index_ligne(v.chemin)
            if k is None or k >= len(doc.ft.lignes):
                continue
            nature = doc.ft.lignes[k].nature
            if nature is not None and nature.est_debours:
                lignes_cles.setdefault(doc.id, set()).add(k)
        # Ligne répartie au prorata entre déclarations qui sont **toutes** comparées ensemble, sur une facture qui
        # ne cite aucun MRN hors du dossier : la somme comparée ne dépend pas de la clé de répartition.
        cibles_par_ligne: dict[tuple[str, int], list[Allocation]] = {}
        for a in self.dossier.allocations:
            if a.methode is MethodeAllocation.prorata and a.source_ligne is not None:
                cibles_par_ligne.setdefault((a.source_document_id, a.source_ligne), []).append(a)
        prefixes = set(self.mrn_prefixes())

        def repartition_neutre(a: Allocation) -> bool:
            groupe = cibles_par_ligne.get((a.source_document_id, a.source_ligne or 0), [])
            doc = self.document(a.source_document_id)
            if not groupe or doc is None or doc.type is not TypeDocument.facture_transitaire:
                return False
            cites = {mrn_prefixe(v.valeur) for v in doc.ft.refs_mrn if v is not None and v.valeur}
            cites |= {mrn_prefixe(lg.mrn.valeur) for lg in doc.ft.lignes if lg.mrn is not None and lg.mrn.valeur}
            cites.discard("")
            return (all(x.cible_document_id in ids and x.montant_alloue is not None for x in groupe)
                    and cites <= prefixes)

        out = []
        for a in allocations:
            if a.source_document_id not in ids or (a.cible_document_id is not None and a.cible_document_id not in ids):
                continue
            lignes = lignes_cles.get(a.source_document_id)
            if lignes and a.source_ligne is not None and a.source_ligne not in lignes:
                continue
            if (a.methode is MethodeAllocation.prorata and lignes and a.source_ligne in lignes
                    and repartition_neutre(a)):
                continue
            out.append(a)
        return out

    def _avoir_non_ventile(self, spec: ControlSpec | str, doc_ids: Sequence[str], kwargs: Mapping[str, Any]) -> bool:
        """§8.5.1 condition 7 (D-2205) : un montant ``recouvrable`` sur une facture du transitaire n'est pas
        certain quand un avoir du même émetteur, rattaché à cette facture, n'a pu être ventilé (il pourrait
        couvrir l'écart sans pouvoir être déduit)."""
        sp = get_spec(spec) if isinstance(spec, str) else spec
        nature = kwargs.get("nature_montant") or sp.nature_montant
        if nature is not NatureMontant.recouvrable:
            return False
        from controldone.controls._aides_befg import avoirs_non_ventiles_pour  # import circulaire évité

        for i in dict.fromkeys(doc_ids):
            doc = self.document(i)
            if doc is not None and doc.type is TypeDocument.facture_transitaire and avoirs_non_ventiles_pour(self, doc):
                return True
        return False

    # --- constructeurs de résultats ----------------------------------------------------------------

    def _ids(self, controle_id: str, sous_controle: str | None, unite: str) -> tuple[str, str]:
        parts = (self.dossier.id, self.dossier.version, controle_id, sous_controle or "", unite)
        return id_stable(Prefixe.resultat, *parts), id_stable(Prefixe.constat, *parts)

    def resultat(
        self,
        controle_id: str,
        *,
        outcome: Outcome,
        unite: str = "dossier",
        sous_controle: str | None = None,
        raison_code: RaisonCode | None = None,
        entrees: Mapping[str, ValeurSourcee | str] | None = None,
        attendu: Any = None,
        constate: Any = None,
        ecart: Decimal | None = None,
        tolerance: Decimal | None = None,
        seuil_certitude: Decimal | None = None,
        documents: Iterable[str] = (),
        details: Mapping[str, Any] | None = None,
        constat: Constat | None = None,
    ) -> ResultatControle:
        """Constructeur générique. ``entrees`` accepte des ``ValeurSourcee`` (leur ``id`` est retenu)."""
        get_spec(controle_id)
        rid, _ = self._ids(controle_id, sous_controle, unite)
        return ResultatControle(
            id=rid,
            controle_id=controle_id,
            sous_controle=sous_controle,
            unite=unite,
            dossier_id=self.dossier.id,
            dossier_version=self.dossier.version,
            execution_id=self.execution_id,
            outcome=outcome,
            raison_code=raison_code,
            entrees={k: (v.id if isinstance(v, ValeurSourcee) else v) for k, v in (entrees or {}).items()},
            attendu=None if attendu is None else str(attendu),
            constate=None if constate is None else str(constate),
            ecart=ecart,
            tolerance_appliquee=tolerance,
            seuil_certitude_applique=seuil_certitude,
            empreinte_tolerances=self.empreinte_tolerances,
            documents_concernes=list(dict.fromkeys(documents)),
            details=dict(details or {}),
            constat=constat,
        )

    def conforme(self, controle_id: str, *, unite: str = "dossier", **kwargs: Any) -> ResultatControle:
        return self.resultat(controle_id, outcome=Outcome.conforme, unite=unite, **kwargs)

    def non_applicable(
        self, controle_id: str, raison: RaisonCode, *, unite: str = "dossier", **kwargs: Any
    ) -> ResultatControle:
        return self.resultat(controle_id, outcome=Outcome.non_applicable, unite=unite, raison_code=raison, **kwargs)

    def non_verifiable(
        self, controle_id: str, raison: RaisonCode, *, unite: str = "dossier", **kwargs: Any
    ) -> ResultatControle:
        """P8 : « impossible de conclure » n'est jamais « conforme »."""
        return self.resultat(controle_id, outcome=Outcome.non_verifiable, unite=unite, raison_code=raison, **kwargs)

    def constat(
        self,
        controle_id: str,
        classement: Classement,
        *,
        unite: str = "dossier",
        sous_controle: str | None = None,
        libelle: str,
        prochaine_action: str = "",
        montant: Decimal | None = None,
        montant_brut: Decimal | None = None,
        montant_tva_associee: Decimal | None = None,
        composante: Composante | None = None,
        preuves: Sequence[Preuve] = (),
        documents: Iterable[str] = (),
        autres_dossiers: Iterable[str] = (),
        renvoi: bool = False,
        entrees: Mapping[str, ValeurSourcee | str] | None = None,
        attendu: Any = None,
        constate: Any = None,
        ecart: Decimal | None = None,
        tolerance: Decimal | None = None,
        seuil_certitude: Decimal | None = None,
        details: Mapping[str, Any] | None = None,
    ) -> ResultatControle:
        """Résultat + constat à partir d'un ``Classement``. Si le classement est ``conforme``, retourne un
        résultat ``conforme`` sans constat.

        Le montant suit la nature de l'Annexe A (``renvoi``/``aucun`` -> ``None``), est arrondi au
        centime, et ``sens`` est déduit (§8.6). Les documents concernés sont ceux passés et ceux des
        preuves.
        """
        spec = get_spec(controle_id)
        docs = list(dict.fromkeys([*documents, *(p.document_id for p in preuves if p.document_id)]))
        commun = dict(
            unite=unite, sous_controle=sous_controle, entrees=entrees, attendu=attendu, constate=constate,
            ecart=ecart, tolerance=tolerance, seuil_certitude=seuil_certitude, documents=docs, details=details,
        )
        if classement.niveau is None:
            return self.resultat(controle_id, outcome=Outcome.conforme, **commun)
        if lecture_improbable(controle_id, classement.raisons):
            # D-2310 : l'écart ne repose que sur des lectures peu sûres qu'une seule confusion de caractère
            # explique : impossible de conclure (P8), le résultat garde les raisons ; pas de constat.
            commun["details"] = {**(details or {}), "motif": "ecart_explique_par_une_lecture_douteuse",
                                 "raisons": [r.value for r in classement.raisons]}
            return self.resultat(controle_id, outcome=Outcome.non_verifiable,
                                 raison_code=RaisonCode.lecture_douteuse, **commun)
        if spec.nature_montant is None:
            raise ValueError(f"{controle_id} ne produit jamais de constat (Annexe A)")
        renvoi = renvoi or spec.est_renvoi
        niveau = Niveau.a_verifier if renvoi else classement.niveau
        raisons = list(classement.raisons)
        if renvoi and RaisonCode.renvoi_reglementaire not in raisons:
            raisons.append(RaisonCode.renvoi_reglementaire)
        m = montant_pour_spec(spec, montant, renvoi=renvoi)
        _, fid = self._ids(controle_id, sous_controle, unite)
        c = Constat(
            id=fid,
            controle_id=controle_id,
            sous_controle=sous_controle,
            niveau=niveau,
            raisons=sorted(set(raisons), key=list(RaisonCode).index),
            libelle=libelle,
            montant_en_jeu=m,
            montant_brut=(montant_brut if montant_brut is not None else m) if m is not None else None,
            montant_tva_associee=montant_tva_associee,
            nature_montant=spec.nature_montant,
            composante=composante,
            sens=sens_pour(spec.nature_montant, m),
            documents_concernes=docs,
            autres_dossiers=list(autres_dossiers),
            preuves=list(preuves),
            renvoi=renvoi,
            prochaine_action=prochaine_action,
        )
        return self.resultat(controle_id, outcome=niveau.outcome, constat=c, **commun)


_RX_INDEX_LIGNE = re.compile(r"(?:^|\.)lignes\[(\d+)\]")


def _index_ligne(chemin: str | None) -> int | None:
    """Rang de la ligne de facture d'un chemin (``facture_transitaire.lignes[3].montant_ht`` -> 3)."""
    m = _RX_INDEX_LIGNE.search(chemin or "")
    return int(m.group(1)) if m else None


#: Contrôles dont le constat n'est jamais retiré pour une lecture douteuse (signaux de documents, P).
_FAMILLES_PROTEGEES = ("P",)


def lecture_improbable(controle_id: str, raisons: Iterable[RaisonCode]) -> bool:
    """D-2310 : un constat dont l'écart s'explique par une confusion de lecture (``lecture_douteuse``) **et**
    dont une valeur clé est sous la confiance minimale (``confiance_insuffisante``) n'est pas émis : sur les
    jeux de développement, cette conjonction ne correspond à aucune erreur réelle (bruit de lecture OCR).
    Une lecture douteuse sur des valeurs sûres reste un constat ``a_verifier``."""
    rs = set(raisons)
    return (not controle_id.startswith(_FAMILLES_PROTEGEES) and RaisonCode.lecture_douteuse in rs
            and RaisonCode.confiance_insuffisante in rs)


#: Confiance minimale d'une lecture que l'arithmétique imprimée du document peut confirmer (D-2314).
C_LECTURE_CONFIRMABLE = 0.7
_METHODES_LUES = (Methode.texte_natif, Methode.ocr, Methode.llm)
