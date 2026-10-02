"""Fabriques d'objets pour les tests (toutes équipes). Données **fictives** uniquement.

    from controldone.testing import vs, declaration, taxation, dossier_pour, contexte

Toutes les valeurs créées sont ``texte_natif``, ancrées, de confiance 0,99 par défaut (lecture sûre) :
on dégrade explicitement ce qu'un test veut éprouver (``methode="ocr"``, ``confiance=0.7``…).
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Any

from controldone.controls.context import ControlContext
from controldone.ids import IdGenerator
from controldone.model import (
    CategorieTaxe,
    ChampsDeclaration,
    ChampsFactureCommerciale,
    ChampsFactureTransitaire,
    Document,
    Dossier,
    ExtracteurInfo,
    ForceLien,
    LienDocument,
    Methode,
    PageRef,
    PaiementNormalise,
    ProfilTolerances,
    QualiteTexte,
    RoleLien,
    SignalLien,
    TauxNature,
    TaxationDeclaration,
    TypeDocument,
    TypeExtracteur,
    TypeValeur,
    ValeurSourcee,
    type_valeur_pour,
)

__all__ = [
    "EXTRACTEUR_TEST",
    "contexte",
    "declaration",
    "document",
    "dossier_pour",
    "facture_commerciale",
    "facture_transitaire",
    "taxation",
    "vs",
]

EXTRACTEUR_TEST = ExtracteurInfo(type=TypeExtracteur.deterministe, id="test", version="0")
_ROLE = {
    TypeDocument.facture_commerciale: RoleLien.facture_commerciale,
    TypeDocument.declaration: RoleLien.declaration,
    TypeDocument.facture_transitaire: RoleLien.facture_transitaire,
    TypeDocument.avoir: RoleLien.avoir,
}
_ids = IdGenerator.deterministe(4242)


def vs(
    chemin: str,
    valeur: str | None,
    *,
    brut: str | None = None,
    document_id: str | None = "doc_test",
    page: int | None = 1,
    methode: Methode | str = Methode.texte_natif,
    confiance: float = 0.99,
    ancree: bool | None = None,
    type: TypeValeur | None = None,
    **kwargs: Any,
) -> ValeurSourcee:
    """Valeur sourcée de test. ``brut`` par défaut = ``valeur``."""
    m = Methode(methode)
    return ValeurSourcee(
        id=kwargs.pop("id", None) or _ids.nouveau("vs"),
        chemin=chemin,
        valeur=valeur,
        type=type or type_valeur_pour(chemin),
        valeur_brute=brut if brut is not None else valeur,
        document_id=document_id,
        page=page,
        extracteur=kwargs.pop("extracteur", EXTRACTEUR_TEST),
        methode=m,
        confiance=confiance,
        ancree=(m is not Methode.derive) if ancree is None else ancree,
        **kwargs,
    )


def document(
    type_document: TypeDocument,
    champs: Any = None,
    *,
    id: str | None = None,
    pages: Sequence[int] = (1,),
    qualite: QualiteTexte = QualiteTexte.natif,
    fichier_id: str = "fic_test",
    **kwargs: Any,
) -> Document:
    return Document(
        id=id or _ids.nouveau("doc"),
        type=type_document,
        pages=[PageRef(fichier_id=fichier_id, numero=n, qualite_texte=qualite) for n in pages],
        champs=champs,
        **kwargs,
    )


def taxation(
    doc_id: str,
    *,
    article: str | None = "1",
    type_taxe: str = "A00",
    categorie: CategorieTaxe = CategorieTaxe.droit,
    base: str | None = None,
    base_quantite: str | None = None,
    taux: str | None = None,
    montant: str | None = None,
    nature: TauxNature | None = TauxNature.ad_valorem,
    paiement: PaiementNormalise = PaiementNormalise.comptant,
    methode: Methode | str = Methode.texte_natif,
    confiance: float = 0.99,
    brut_montant: str | None = None,
    page: int = 1,
) -> TaxationDeclaration:
    """Ligne de taxation de test (valeurs décimales en notation point)."""

    def v(nom: str, val: str | None, brut: str | None = None) -> ValeurSourcee | None:
        if val is None:
            return None
        return vs(f"declaration.taxations[].{nom}", val, brut=brut, document_id=doc_id, methode=methode,
                  confiance=confiance, page=page)

    return TaxationDeclaration(
        article=v("article", article),
        type_taxe=v("type_taxe", type_taxe),
        categorie=categorie,
        base_montant=v("base_montant", base),
        base_quantite=v("base_quantite", base_quantite),
        taux=v("taux", taux),
        taux_nature=nature,
        montant=v("montant", montant, brut_montant),
        paiement_normalise=paiement,
    )


def declaration(
    *,
    id: str | None = None,
    mrn: str = "26FR00000000000001",
    taxations: Iterable[TaxationDeclaration] = (),
    version: str | None = None,
    qualite: QualiteTexte = QualiteTexte.natif,
    **champs: Any,
) -> Document:
    doc_id = id or _ids.nouveau("doc")
    c = ChampsDeclaration(
        mrn=vs("declaration.mrn", mrn, document_id=doc_id),
        version=vs("declaration.version", version, document_id=doc_id) if version else None,
        taxations=list(taxations),
        **champs,
    )
    return document(TypeDocument.declaration, c, id=doc_id, qualite=qualite)


def facture_commerciale(*, id: str | None = None, **champs: Any) -> Document:
    return document(TypeDocument.facture_commerciale, ChampsFactureCommerciale(**champs), id=id)


def facture_transitaire(*, id: str | None = None, **champs: Any) -> Document:
    return document(TypeDocument.facture_transitaire, ChampsFactureTransitaire(**champs), id=id)


def dossier_pour(
    documents: Iterable[Document], *, force: ForceLien = ForceLien.forte, id: str = "dos_test", version: int = 1
) -> Dossier:
    """Dossier liant chaque document avec son rôle naturel et la force donnée."""
    liens = []
    for d in documents:
        role = _ROLE.get(d.type, RoleLien.support)
        liens.append(LienDocument(document_id=d.id, role=role, force=force, signaux=[SignalLien.graine]))
    return Dossier(id=id, version=version, liens=liens)


def contexte(
    documents: Sequence[Document],
    *,
    force: ForceLien = ForceLien.forte,
    profil: ProfilTolerances | None = None,
    **kwargs: Any,
) -> ControlContext:
    """Contexte de contrôle prêt à l'emploi pour une liste de documents."""
    return ControlContext.construire(
        dossier_pour(documents, force=force), documents, profil or ProfilTolerances(id="tol_test"),
        execution_id="exe_test", **kwargs,
    )
