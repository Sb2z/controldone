"""Sélection des lignes d'import dont le code imprimé figure dans la liste MACF (annexe I).

Source : les déclarations des dossiers **déjà traités** du client. Chaque article dont le code
marchandise imprimé correspond à la liste (``StatutCode.dans_liste`` ou ``a_preciser``) donne une
``LigneMACF``. Rien n'est déduit : masse, pays d'origine et fournisseur sont recopiés tels que lus,
avec leur provenance (document, page). Toute ligne est « à faire vérifier ».
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING

from controldone.macf.codes import ListeCodesMACF, StatutCode, charger_liste
from controldone.model.documents import Document
from controldone.model.dossier import Dossier
from controldone.model.enums import TypeDocument
from controldone.model.valeur import ValeurSourcee

if TYPE_CHECKING:
    from controldone.storage.scope import TenantScope

__all__ = [
    "MENTION_LIGNE",
    "LigneMACF",
    "lignes_depuis_scope",
    "masse_kg",
    "selectionner_lignes",
]

MENTION_LIGNE = "à faire vérifier"

_FACTEURS = {None: Decimal(1), "": Decimal(1), "KGM": Decimal(1), "KG": Decimal(1),
             "TNE": Decimal(1000), "T": Decimal(1000), "GRM": Decimal("0.001"), "G": Decimal("0.001")}


def masse_kg(v: ValeurSourcee | None) -> Decimal | None:
    """Masse nette lue, en kg (valeur normalisée en kg, ou unité imprimée t / g). ``None`` si illisible."""
    if v is None or not v.valeur:
        return None
    facteur = _FACTEURS.get((v.unite or "").strip().upper())
    if facteur is None:
        return None
    try:
        d = Decimal(v.valeur)
    except (InvalidOperation, ValueError):
        return None
    if d < 0:
        return None
    return (d * facteur).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)


def _txt(v: ValeurSourcee | None) -> str | None:
    if v is None:
        return None
    return v.valeur_brute or v.valeur


def _date(v: ValeurSourcee | None) -> date | None:
    if v is None or not v.valeur:
        return None
    try:
        return date.fromisoformat(v.valeur[:10])
    except ValueError:
        return None


@dataclass(frozen=True)
class LigneMACF:
    dossier_id: str
    dossier_reference: str | None
    declaration_id: str
    mrn: str | None
    date_acceptation: date | None
    numero_article: str | None
    code_imprime: str | None
    description: str | None
    statut_code: StatutCode
    code_liste: str | None
    secteur: str | None
    secteur_libelle: str | None
    hors_cumul_50t: bool
    pays_origine: str | None
    masse_nette_kg: Decimal | None
    masse_nette_brut: str | None
    fournisseur: str | None  # nom du vendeur tel qu'imprimé sur la facture commerciale du dossier
    installation: str | None  # jamais lue sur ces documents : à demander au fournisseur
    page: int | None
    motif: str
    verification: str = MENTION_LIGNE

    @property
    def annee(self) -> int | None:
        return self.date_acceptation.year if self.date_acceptation else None

    @property
    def periode(self) -> str:
        """``2026-T3`` (trimestre de la date d'acceptation imprimée) ou ``date non lue``."""
        d = self.date_acceptation
        return f"{d.year}-T{(d.month - 1) // 3 + 1}" if d else "date non lue"


def _fournisseurs(documents: Iterable[Document]) -> str | None:
    noms = []
    for d in documents:
        if d.type is TypeDocument.facture_commerciale and d.champs is not None:
            n = _txt(d.fc.vendeur.nom)
            if n and n not in noms:
                noms.append(n)
    return " / ".join(noms) if noms else None


def selectionner_lignes(dossier: Dossier, documents: Mapping[str, Document] | Iterable[Document], *,
                        liste: ListeCodesMACF | None = None) -> list[LigneMACF]:
    """Lignes MACF d'un dossier (articles des déclarations dont le code imprimé est retenu)."""
    liste = liste or charger_liste()
    docs = list(documents.values()) if isinstance(documents, Mapping) else list(documents)
    ids = set(dossier.document_ids()) if dossier.liens else {d.id for d in docs}
    docs = [d for d in docs if d.id in ids]
    fournisseur = _fournisseurs(docs)
    lignes: list[LigneMACF] = []
    for d in docs:
        if d.type is not TypeDocument.declaration or d.champs is None or d.doublon_de:
            continue
        dec = d.dec
        for art in dec.articles:
            code = _txt(art.code_marchandise)
            corr = liste.classer(code)
            if not corr.retenue:
                continue
            lignes.append(LigneMACF(
                dossier_id=dossier.id, dossier_reference=dossier.reference, declaration_id=d.id,
                mrn=_txt(dec.mrn), date_acceptation=_date(dec.date_acceptation),
                numero_article=_txt(art.numero_article), code_imprime=code, description=_txt(art.description),
                statut_code=corr.statut, code_liste=corr.entree.code if corr.entree else None,
                secteur=corr.secteur.id if corr.secteur else None,
                secteur_libelle=corr.secteur.libelle if corr.secteur else None,
                hors_cumul_50t=bool(corr.secteur and corr.secteur.hors_cumul_50t),
                pays_origine=(art.pays_origine.valeur if art.pays_origine else None),
                masse_nette_kg=masse_kg(art.masse_nette), masse_nette_brut=_txt(art.masse_nette),
                fournisseur=fournisseur, installation=None,
                page=(art.code_marchandise.page if art.code_marchandise else None),
                motif=corr.motif,
            ))
    return lignes


def lignes_depuis_scope(scope: TenantScope, *, liste: ListeCodesMACF | None = None) -> list[LigneMACF]:
    """Lignes MACF de tous les dossiers traités du client du périmètre (lecture seule)."""
    from controldone.services.lecture import documents_du_dossier
    from controldone.storage.models import Dossier as DossierLigne

    liste = liste or charger_liste()
    lignes: list[LigneMACF] = []
    for row in scope.lister(DossierLigne):
        if not row.contenu:
            continue
        modele = Dossier.model_validate(row.contenu)
        lignes += selectionner_lignes(modele, documents_du_dossier(scope, modele), liste=liste)
    return lignes
