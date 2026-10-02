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

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from types import MappingProxyType
from typing import Any

from controldone.controls.classify import Classement, classify, montant_pour_spec, sens_pour
from controldone.controls.confusion import confusion_applicable, confusion_test, confusion_test_fn
from controldone.controls.specs import ControlSpec, get_spec
from controldone.controls.tolerances import Tolerances
from controldone.ids import IdGenerator, Prefixe, id_stable
from controldone.model.documents import Document
from controldone.model.dossier import Allocation, Dossier, LienDocument
from controldone.model.enums import (
    Composante,
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
from controldone.normalize.refs import mrn_prefixe
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
        )

    def __post_init__(self) -> None:
        index: dict[str, ValeurSourcee] = {}
        for d in self.documents.values():
            for v in d.valeurs():
                index[v.id] = v
        object.__setattr__(self, "_index_valeurs", MappingProxyType(index))
        object.__setattr__(self, "_tol", Tolerances(self.profil))
        object.__setattr__(self, "_empreinte", self.profil.empreinte())

    # --- accès de base ----------------------------------------------------------------------------

    @property
    def tol(self) -> Tolerances:
        return self._tol  # type: ignore[attr-defined]

    @property
    def empreinte_tolerances(self) -> str:
        return self._empreinte  # type: ignore[attr-defined]

    @property
    def other_dossiers(self) -> tuple[AutreDossier, ...]:
        """Alias anglais de ``autres_dossiers``."""
        return self.autres_dossiers

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
                groupes.setdefault(p, []).append(d)
            else:
                sans_mrn.append(d)
        retenues = {max(g, key=self._rang_version).id for g in groupes.values()}
        ids_sans_mrn = {d.id for d in sans_mrn}
        return [d for d in decs if d.id in retenues or d.id in ids_sans_mrn]

    def versions_anterieures(self, declaration: Document) -> list[Document]:
        """Autres versions (rectificatives ou initiales) du même préfixe MRN (condition 7 de §8.5.1)."""
        p = declaration.dec.mrn_prefixe
        if not p:
            return []
        return [
            d for d in self.declarations(dernieres_versions=False)
            if d.id != declaration.id and d.dec.mrn_prefixe == p
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
            brut = c.valeur.valeur_brute or c.valeur.valeur
            if c.accepte is not None:
                if confusion_test_fn(brut, c.accepte):
                    return True
            elif c.autre is not None and c.tolerance is not None and confusion_test(brut, c.autre, c.tolerance):
                return True
        return False

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
        **kwargs: Any,
    ) -> Classement:
        """``classify`` (§8.5.1) avec collecte automatique :

        - des liens des documents des valeurs clés (et de ``documents``) — condition 5 ;
        - des allocations touchant ces documents (sauf si ``allocations`` est fourni) — condition 5 ;
        - du test de confusion sur ``confusion`` — condition 6.

        Les autres paramètres (``explication``, ``renvoi``, ``eligible``, ``nature_montant``, ``montant``,
        ``raisons_supplementaires``) sont transmis à ``classify``.
        """
        doc_ids = [v.document_id for v in valeurs_cles if v.document_id] + list(documents)
        if allocations is None:
            vues: dict[str, Allocation] = {}
            for i in dict.fromkeys(doc_ids):
                for a in self.allocations_pour(i):
                    vues.setdefault(a.id, a)
            allocations = list(vues.values())
        return classify(
            spec,
            ecart=ecart,
            tolerance=tolerance,
            seuil_certitude=seuil_certitude,
            valeurs_cles=valeurs_cles,
            c_min_certain=self.profil.c_min_certain,
            liens=self.liens_pour(doc_ids),
            allocations=allocations,
            lecture_douteuse=kwargs.pop("lecture_douteuse", False) or self.lecture_douteuse(confusion),
            **kwargs,
        )

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
