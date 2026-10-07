"""Conteneurs typés des champs par type de document (SPEC §5.3.1 à §5.3.5).

Chaque feuille est une ``ValeurSourcee`` (ou ``None`` si le champ n'a pas été trouvé). Les sous-objets
(``acheteur``, ``importateur``…) existent toujours (jamais ``None``) pour éviter les tests en cascade.

Chemins
-------
Le chemin **relatif** d'une feuille suit les noms de la spécification : ``acheteur.tva``,
``total_facture``, ``lignes[2].montant_ht`` (index **0-based**), ``refs_mrn[0]``. Le chemin stocké dans
``ValeurSourcee.chemin`` est préfixé du type de document : ``facture_commerciale.total_facture``
(``chemin_complet``). ``Champs.obtenir`` / ``Champs.definir`` lisent et écrivent par chemin relatif.

Les classifications normalisées tirées d'une valeur lue (``categorie`` d'une taxe, ``nature`` d'une ligne,
``paiement_normalise``) sont des énumérations simples : leur provenance est celle de la valeur lue dont
elles découlent (``type_taxe``, ``libelle``, ``mode_paiement``).
"""

from __future__ import annotations

import re
import types
import typing
from collections.abc import Iterator
from enum import Enum
from typing import Any, ClassVar, Literal

from pydantic import BaseModel, Field

from controldone.model.base import Modele
from controldone.model.enums import (
    CategorieTaxe,
    NatureLigne,
    PaiementNormalise,
    TauxNature,
    TypeDocument,
    TypeIndiceAutoliquidation,
    TypeSousTotal,
    TypeValeur,
)
from controldone.model.valeur import ValeurSourcee

__all__ = [
    "CHAMPS_CLES",
    "ArticleDeclaration",
    "Champs",
    "ChampsAvoir",
    "ChampsDeclaration",
    "ChampsDocument",
    "ChampsFactureCommerciale",
    "ChampsFactureTransitaire",
    "ChampsSupport",
    "DocumentReference",
    "FeuilleChamp",
    "IndiceAutoliquidation",
    "LigneFactureCommerciale",
    "LigneFactureTransitaire",
    "LigneTableauMrn",
    "Partie",
    "SousTotal",
    "TaxationDeclaration",
    "TotalTaxeCode",
    "chemin_complet",
    "chemin_relatif",
    "classe_champs",
    "type_valeur_pour",
]

VS = ValeurSourcee
Opt = VS | None

_SEGMENT_RE = re.compile(r"^(?P<nom>[a-z_][a-z0-9_]*)(?:\[(?P<idx>\d*)\])?$")


class FeuilleChamp(typing.NamedTuple):
    """Description d'une feuille du modèle (pour schémas fermés, correspondances, documentation)."""

    chemin: str  # relatif, listes notées « [] » : ``lignes[].montant_ht``
    genre: Literal["valeur", "liste_valeurs", "enum", "bool"]
    enum: type[Enum] | None = None


def _analyser(annotation: Any) -> tuple[str, Any]:
    """Retourne (genre, cible) : 'vs', 'vs_list', 'model', 'model_list', 'enum', 'bool', 'autre'."""
    origine = typing.get_origin(annotation)
    args = typing.get_args(annotation)
    if origine in (typing.Union, types.UnionType):
        non_none = [a for a in args if a is not type(None)]
        if len(non_none) == 1:
            return _analyser(non_none[0])
        return "autre", annotation
    if origine is list:
        genre, cible = _analyser(args[0])
        if genre == "vs":
            return "vs_list", cible
        if genre == "model":
            return "model_list", cible
        return "autre", annotation
    if annotation is ValeurSourcee:
        return "vs", annotation
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return "model", annotation
    if isinstance(annotation, type) and issubclass(annotation, Enum):
        return "enum", annotation
    if annotation is bool:
        return "bool", annotation
    return "autre", annotation


class _Noeud(Modele):
    """Nœud de l'arbre des champs : parcours, lecture et écriture par chemin."""

    def iter_valeurs(self) -> Iterator[ValeurSourcee]:
        """Toutes les ``ValeurSourcee`` du sous-arbre, dans l'ordre de déclaration des champs."""
        for nom in type(self).model_fields:
            v = getattr(self, nom)
            if isinstance(v, ValeurSourcee):
                yield v
            elif isinstance(v, _Noeud):
                yield from v.iter_valeurs()
            elif isinstance(v, list):
                for x in v:
                    if isinstance(x, ValeurSourcee):
                        yield x
                    elif isinstance(x, _Noeud):
                        yield from x.iter_valeurs()

    @classmethod
    def feuilles(cls, prefixe: str = "") -> list[FeuilleChamp]:
        out: list[FeuilleChamp] = []
        for nom, info in cls.model_fields.items():
            if nom == "type_document":
                continue
            genre, cible = _analyser(info.annotation)
            chemin = f"{prefixe}{nom}"
            if genre == "vs":
                out.append(FeuilleChamp(chemin, "valeur"))
            elif genre == "vs_list":
                out.append(FeuilleChamp(f"{chemin}[]", "liste_valeurs"))
            elif genre == "model":
                out.extend(cible.feuilles(f"{chemin}."))
            elif genre == "model_list":
                out.extend(cible.feuilles(f"{chemin}[]."))
            elif genre == "enum":
                out.append(FeuilleChamp(chemin, "enum", cible))
            elif genre == "bool":
                out.append(FeuilleChamp(chemin, "bool"))
        return out

    def obtenir(self, chemin: str) -> Any:
        """Lit une feuille ou un sous-objet par chemin relatif ; ``None`` si absent / hors limites."""
        courant: Any = self
        for seg in chemin.split("."):
            m = _SEGMENT_RE.match(seg)
            if not m or courant is None:
                return None
            courant = getattr(courant, m["nom"], None)
            if m["idx"] is not None and m["idx"] != "":
                i = int(m["idx"])
                if not isinstance(courant, list) or i >= len(courant):
                    return None
                courant = courant[i]
        return courant

    def definir(self, chemin: str, valeur: Any) -> None:
        """Écrit une feuille par chemin relatif, en créant les éléments de liste manquants.

        ``lignes[3].montant_ht`` crée au besoin les lignes 0 à 3 (vides). ``refs_mrn[]`` (index vide)
        ajoute en fin de liste.
        """
        segments = chemin.split(".")
        courant: Any = self
        for k, seg in enumerate(segments):
            m = _SEGMENT_RE.match(seg)
            if not m:
                raise KeyError(f"segment de chemin invalide : {seg!r}")
            nom, idx = m["nom"], m["idx"]
            if nom not in type(courant).model_fields:
                raise KeyError(f"champ inconnu : {nom!r} dans {type(courant).__name__}")
            dernier = k == len(segments) - 1
            genre, cible = _analyser(type(courant).model_fields[nom].annotation)
            if idx is None:
                if dernier:
                    setattr(courant, nom, valeur)
                    return
                courant = getattr(courant, nom)
                continue
            liste = getattr(courant, nom)
            if not isinstance(liste, list):
                raise KeyError(f"{nom!r} n'est pas une liste")
            if idx == "":
                if not dernier:
                    raise KeyError("index vide autorisé seulement en fin de chemin")
                liste.append(valeur)
                return
            i = int(idx)
            while len(liste) <= i:
                if genre == "model_list":
                    liste.append(cible())
                elif dernier:
                    liste.append(None)
                else:
                    raise KeyError(f"impossible de créer l'élément {i} de {nom!r}")
            if dernier:
                liste[i] = valeur
                return
            courant = liste[i]


class Champs(_Noeud):
    """Base des conteneurs de champs d'un document. ``type_document`` sert de discriminant."""

    TYPE: ClassVar[TypeDocument]


# --- Sous-objets communs --------------------------------------------------------------------------


class Partie(_Noeud):
    """Pavé d'une partie (vendeur, acheteur, importateur, déclarant, émetteur, client facturé…)."""

    nom: Opt = None
    adresse: Opt = None
    tva: Opt = None
    siren: Opt = None
    eori: Opt = None


class SousTotal(_Noeud):
    """Ligne de pied distincte de la facture commerciale (§5.3.1 ``sous_totaux``)."""

    type: TypeSousTotal = TypeSousTotal.autre
    libelle: Opt = None
    montant: Opt = None


# --- 5.3.1 Facture commerciale --------------------------------------------------------------------


class LigneFactureCommerciale(_Noeud):
    """Ligne de facture commerciale. ``quantite.unite`` porte le code UN/ECE (ou ``inconnue``)."""

    numero_ligne: Opt = None
    reference_article: Opt = None
    description: Opt = None
    quantite: Opt = None
    prix_unitaire: Opt = None
    montant_ligne: Opt = None
    devise_ligne: Opt = None
    code_marchandise_imprime: Opt = None
    pays_origine: Opt = None
    masse_nette: Opt = None
    masse_brute: Opt = None


class ChampsFactureCommerciale(Champs):
    TYPE: ClassVar[TypeDocument] = TypeDocument.facture_commerciale
    type_document: Literal["facture_commerciale"] = "facture_commerciale"

    numero: Opt = None
    date: Opt = None
    vendeur: Partie = Field(default_factory=Partie)
    acheteur: Partie = Field(default_factory=Partie)
    destinataire: Partie = Field(default_factory=Partie)
    eori_importateur: Opt = None
    devise: Opt = None
    #: ``total_facture.total_origine`` = ``imprime`` ou ``reconstruit`` (§5.3.1).
    total_facture: Opt = None
    sous_totaux: list[SousTotal] = Field(default_factory=list)
    incoterm: Opt = None
    incoterm_lieu: Opt = None
    ref_transport: Opt = None
    masse_nette_totale: Opt = None
    masse_brute_totale: Opt = None
    nombre_colis: Opt = None
    quantite_totale: Opt = None
    lignes: list[LigneFactureCommerciale] = Field(default_factory=list)


# --- 5.3.2 Déclaration -----------------------------------------------------------------------------


class DocumentReference(_Noeud):
    """DG 12 03 : ``{type_code, reference}`` (factures N380, N325, titres de transport, 1008…)."""

    type_code: Opt = None
    reference: Opt = None


class IndiceAutoliquidation(_Noeud):
    """Indice d'autoliquidation lu (§5.3.2, §12.1) ; ``valeur`` cite le texte lu."""

    type: TypeIndiceAutoliquidation
    valeur: Opt = None
    #: Numéro de TVA suivant le code 1008, s'il est lu.
    tva: Opt = None


class ArticleDeclaration(_Noeud):
    numero_article: Opt = None
    code_marchandise: Opt = None
    description: Opt = None
    pays_origine: Opt = None
    pays_origine_preferentielle: Opt = None
    code_preference: Opt = None
    regime: Opt = None
    regime_complementaire: Opt = None
    montant_facture_article: Opt = None
    #: Lue, **jamais jugée** (§5.3.2).
    valeur_statistique: Opt = None
    masse_nette: Opt = None
    masse_brute: Opt = None
    #: Quantité en unité supplémentaire ; ``.unite`` porte le code.
    quantite_unite_supplementaire: Opt = None
    nombre_colis: Opt = None
    references_facture: list[ValeurSourcee] = Field(default_factory=list)

    @property
    def code_sh6(self) -> str | None:
        """Code SH6 dérivé (6 premiers chiffres du code marchandise)."""
        if self.code_marchandise is None or not self.code_marchandise.valeur:
            return None
        chiffres = re.sub(r"\D", "", self.code_marchandise.valeur)
        return chiffres[:6] if len(chiffres) >= 6 else None


class TaxationDeclaration(_Noeud):
    """Ligne de taxation (DG 14 03). ``article`` = ``None`` si niveau déclaration."""

    article: Opt = None
    type_taxe: Opt = None
    categorie: CategorieTaxe = CategorieTaxe.inconnue
    base_montant: Opt = None
    base_quantite: Opt = None
    base_unite: Opt = None
    taux: Opt = None
    taux_nature: TauxNature | None = None
    montant: Opt = None
    montant_a_payer: Opt = None
    mode_paiement: Opt = None
    paiement_normalise: PaiementNormalise = PaiementNormalise.inconnu


class TotalTaxeCode(_Noeud):
    """Total imprimé d'un code de taxe (« Total A00 : 323,00 », récapitulatif « A00 Droits de douane 96,65 »,
    ``<TypeTotal type="A00">``), D-3101. **Jamais** une ligne de taxation : les contrôles qui somment les lignes
    (famille C, B2 au total) ne le voient pas ; il sert à B2 par code et au réseau d'identités (D-1700)."""

    type_taxe: Opt = None
    #: Base imprimée du total, quand le récapitulatif l'imprime.
    base_montant: Opt = None
    montant: Opt = None

    @property
    def deduit(self) -> bool:
        """Total retenu par déduction (D-3706, D-3710) : code sans ligne de taxation lue, admis parce que la somme
        des totaux par code redonne le total imprimé, ou total de catégorie sans code rattaché au seul code de sa
        catégorie. Il peut confirmer une lecture mais n'est jamais la seule preuve d'un écart certain, ni la valeur
        comparée d'un constat certain."""
        return self.montant is not None and (self.montant.regle_derivation or "") in REGLES_TOTAL_CODE_DEDUIT


#: ``ValeurSourcee.regle_derivation`` des totaux par code déduits (D-3706, D-3710).
REGLE_TOTAL_CODE_SANS_LIGNE = "total_code_sans_ligne_confirme_par_somme_des_codes"
REGLE_TOTAL_CATEGORIE_RATTACHE = "total_categorie_sans_code_rattache_au_seul_code"
REGLES_TOTAL_CODE_DEDUIT = frozenset({REGLE_TOTAL_CODE_SANS_LIGNE, REGLE_TOTAL_CATEGORIE_RATTACHE})


class ChampsDeclaration(Champs):
    TYPE: ClassVar[TypeDocument] = TypeDocument.declaration
    type_document: Literal["declaration"] = "declaration"

    mrn: Opt = None
    lrn: Opt = None
    numero_declaration: Opt = None
    date_acceptation: Opt = None
    version: Opt = None
    importateur: Partie = Field(default_factory=Partie)
    declarant: Partie = Field(default_factory=Partie)
    representant: Partie = Field(default_factory=Partie)
    destinataire: Partie = Field(default_factory=Partie)
    devise_facture: Opt = None
    montant_total_facture: Opt = None
    taux_change: Opt = None
    #: ``eur_par_devise`` ou ``devise_par_eur`` ; méthode ``derive`` (confiance 0,85) si déduit (§8.7).
    taux_change_sens: Opt = None
    incoterm: Opt = None
    incoterm_lieu: Opt = None
    pays_expedition: Opt = None
    pays_destination: Opt = None
    masse_brute_totale: Opt = None
    nombre_colis_total: Opt = None
    nombre_articles: Opt = None
    documents_references: list[DocumentReference] = Field(default_factory=list)
    indices_autoliquidation: list[IndiceAutoliquidation] = Field(default_factory=list)
    total_droits_taxes: Opt = None
    total_a_payer: Opt = None
    articles: list[ArticleDeclaration] = Field(default_factory=list)
    taxations: list[TaxationDeclaration] = Field(default_factory=list)
    #: Totaux imprimés par code de taxe (D-3101) ; pas des lignes de taxation.
    totaux_par_code: list[TotalTaxeCode] = Field(default_factory=list)

    @property
    def mrn_prefixe(self) -> str | None:
        """15 premiers caractères normalisés du MRN (§5.3.2, §8.4)."""
        from controldone.normalize.refs import mrn_prefixe

        if self.mrn is None or not self.mrn.valeur:
            return None
        return mrn_prefixe(self.mrn.valeur)


# --- 5.3.3 Facture du transitaire ------------------------------------------------------------------


class LigneFactureTransitaire(_Noeud):
    """Ligne de facture transitaire ou d'avoir (§5.3.3). Montants positifs, même sur un avoir."""

    libelle: Opt = None
    nature: NatureLigne = NatureLigne.autre_prestation
    quantite: Opt = None
    prix_unitaire: Opt = None
    #: Pourcentage imprimé sur la ligne (ex. frais d'avance de fonds), si présent.
    pourcentage: Opt = None
    montant_ht: Opt = None
    taux_tva: Opt = None
    marqueur_tva: Opt = None
    montant_tva: Opt = None
    montant_ttc: Opt = None
    mrn: Opt = None
    ref_transport: Opt = None
    code_marchandise: Opt = None
    base_droit: Opt = None
    base_tva: Opt = None
    date_debut: Opt = None
    date_fin: Opt = None
    #: D-4602 : la ligne n'imprime que des montants TVA comprise (colonne « TTC », « Total c/ IVA ») ; aucun hors-taxe
    #: n'est imprimé. ``montant_ht``, s'il existe, est déduit (ligne taxée) ou égal au TTC (ligne exonérée). Les
    #: contrôles ne comparent jamais ce montant comme un hors-taxe (``recouvrement.imputation.montant_net_ligne``).
    tva_comprise: bool = False


class LigneTableauMrn(_Noeud):
    """Entrée d'un tableau ``transport / MRN / date`` (relevé, §5.3.3)."""

    ref_transport: Opt = None
    mrn: Opt = None
    date: Opt = None


class ChampsFactureTransitaire(Champs):
    TYPE: ClassVar[TypeDocument] = TypeDocument.facture_transitaire
    type_document: Literal["facture_transitaire"] = "facture_transitaire"

    numero: Opt = None
    date: Opt = None
    emetteur: Partie = Field(default_factory=Partie)
    client_facture: Partie = Field(default_factory=Partie)
    refs_transport: list[ValeurSourcee] = Field(default_factory=list)
    refs_mrn: list[ValeurSourcee] = Field(default_factory=list)
    tableau_mrn: list[LigneTableauMrn] = Field(default_factory=list)
    refs_facture_commerciale: list[ValeurSourcee] = Field(default_factory=list)
    devise: Opt = None
    lignes: list[LigneFactureTransitaire] = Field(default_factory=list)
    #: ``total_debours.total_origine`` = ``imprime`` ou ``reconstruit``.
    total_debours: Opt = None
    total_ht: Opt = None
    total_tva: Opt = None
    total_ttc: Opt = None
    #: Acomptes imprimés (D1 sous-contrôle ``net_a_payer``).
    acomptes: Opt = None
    net_a_payer: Opt = None
    est_releve: bool = False


# --- 5.3.4 Avoir -------------------------------------------------------------------------------------


class ChampsAvoir(Champs):
    TYPE: ClassVar[TypeDocument] = TypeDocument.avoir
    type_document: Literal["avoir"] = "avoir"

    numero: Opt = None
    date: Opt = None
    emetteur: Partie = Field(default_factory=Partie)
    refs_facture_origine: list[ValeurSourcee] = Field(default_factory=list)
    refs_mrn: list[ValeurSourcee] = Field(default_factory=list)
    refs_transport: list[ValeurSourcee] = Field(default_factory=list)
    lignes: list[LigneFactureTransitaire] = Field(default_factory=list)
    total_credite_ht: Opt = None
    total_tva: Opt = None
    total_credite_ttc: Opt = None
    devise: Opt = None
    #: Texte du motif, stocké comme **donnée** (jamais interprété).
    motif: Opt = None


# --- 5.3.5 Documents support -------------------------------------------------------------------------


class ChampsSupport(Champs):
    TYPE: ClassVar[TypeDocument] = TypeDocument.document_support
    type_document: Literal["document_support"] = "document_support"

    ref_transport_maitre: Opt = None
    ref_transport_maison: Opt = None
    expediteur: Partie = Field(default_factory=Partie)
    destinataire: Partie = Field(default_factory=Partie)
    nombre_colis: Opt = None
    masse_brute: Opt = None
    masse_taxable: Opt = None
    masse_nette: Opt = None
    refs_facture: list[ValeurSourcee] = Field(default_factory=list)


ChampsDocument = typing.Annotated[
    ChampsFactureCommerciale | ChampsDeclaration | ChampsFactureTransitaire | ChampsAvoir | ChampsSupport,
    Field(discriminator="type_document"),
]

_CLASSES: dict[TypeDocument, type[Champs]] = {
    c.TYPE: c
    for c in (
        ChampsFactureCommerciale,
        ChampsDeclaration,
        ChampsFactureTransitaire,
        ChampsAvoir,
        ChampsSupport,
    )
}


def classe_champs(type_document: TypeDocument | str) -> type[Champs] | None:
    """Classe de champs d'un type de document (``None`` pour non exploitable / inconnu)."""
    return _CLASSES.get(TypeDocument(type_document))


#: Champs clés (*) par type de document (§5.3) : leur confiance conditionne un ``ecart_certain`` et
#: un désaccord entre extracteurs y plafonne la confiance à 0,80 (§7.3).
CHAMPS_CLES: dict[TypeDocument, frozenset[str]] = {
    TypeDocument.facture_commerciale: frozenset({"numero", "acheteur.tva", "devise", "total_facture"}),
    TypeDocument.declaration: frozenset(
        {"mrn", "importateur.tva", "devise_facture", "montant_total_facture", "taux_change"}
    ),
    TypeDocument.facture_transitaire: frozenset({"numero"}),
    TypeDocument.avoir: frozenset({"numero"}),
    TypeDocument.document_support: frozenset(),
}


def chemin_complet(type_document: TypeDocument | str, relatif: str) -> str:
    return f"{TypeDocument(type_document).value}.{relatif}"


def chemin_relatif(chemin: str) -> str:
    """``facture_commerciale.total_facture`` -> ``total_facture`` (inchangé si pas de préfixe connu)."""
    tete, _, reste = chemin.partition(".")
    if reste and tete in TypeDocument.__members__:
        return reste
    return chemin


def chemin_generique(relatif: str) -> str:
    """``lignes[3].montant_ht`` -> ``lignes[].montant_ht`` (pour retrouver la feuille du modèle)."""
    return re.sub(r"\[\d+\]", "[]", relatif)


_TYPES_EXACTS: dict[str, TypeValeur] = {
    "date": TypeValeur.date,
    "date_acceptation": TypeValeur.date,
    "date_debut": TypeValeur.date,
    "date_fin": TypeValeur.date,
    "devise": TypeValeur.devise,
    "devise_facture": TypeValeur.devise,
    "devise_ligne": TypeValeur.devise,
    "tva": TypeValeur.tva,
    "siren": TypeValeur.siren,
    "eori": TypeValeur.eori,
    "eori_importateur": TypeValeur.eori,
    "incoterm": TypeValeur.incoterm,
    "taux_change": TypeValeur.taux,
    "taux": TypeValeur.taux,
    "taux_tva": TypeValeur.taux,
    "pourcentage": TypeValeur.taux,
    "taux_change_sens": TypeValeur.enumeration,
    "quantite": TypeValeur.quantite,
    "quantite_totale": TypeValeur.quantite,
    "quantite_unite_supplementaire": TypeValeur.quantite,
    "base_quantite": TypeValeur.quantite,
    "base_unite": TypeValeur.unite,
    "nombre_colis": TypeValeur.entier,
    "nombre_colis_total": TypeValeur.entier,
    "nombre_articles": TypeValeur.entier,
    "numero_article": TypeValeur.entier,
    "numero_ligne": TypeValeur.entier,
    "version": TypeValeur.entier,
    "article": TypeValeur.entier,
    "code_marchandise": TypeValeur.code,
    "code_marchandise_imprime": TypeValeur.code,
    "type_taxe": TypeValeur.code,
    "type_code": TypeValeur.code,
    "code_preference": TypeValeur.code,
    "regime": TypeValeur.code,
    "regime_complementaire": TypeValeur.code,
    "mode_paiement": TypeValeur.code,
    "marqueur_tva": TypeValeur.code,
    "pays_origine": TypeValeur.pays,
    "pays_origine_preferentielle": TypeValeur.pays,
    "pays_expedition": TypeValeur.pays,
    "pays_destination": TypeValeur.pays,
    "mrn": TypeValeur.reference,
    "lrn": TypeValeur.reference,
    "numero": TypeValeur.reference,
    "numero_declaration": TypeValeur.reference,
    "reference": TypeValeur.reference,
    "reference_article": TypeValeur.reference,
    "ref_transport": TypeValeur.reference,
    "ref_transport_maitre": TypeValeur.reference,
    "ref_transport_maison": TypeValeur.reference,
}


def type_valeur_pour(chemin: str) -> TypeValeur:
    """Type attendu d'une feuille d'après son nom (chemin relatif ou complet)."""
    feuille = re.sub(r"\[\d*\]", "", chemin_relatif(chemin)).split(".")[-1]
    if feuille in _TYPES_EXACTS:
        return _TYPES_EXACTS[feuille]
    if feuille.startswith(("refs_", "references_")):
        return TypeValeur.reference
    if feuille.startswith("masse"):
        return TypeValeur.masse
    if feuille.startswith(
        (
            "montant",
            "total",
            "prix",
            "base_montant",
            "base_droit",
            "base_tva",
            "valeur_statistique",
            "net_a_payer",
            "acomptes",
        )
    ):
        return TypeValeur.montant
    return TypeValeur.texte


__all__ += ["chemin_generique"]
