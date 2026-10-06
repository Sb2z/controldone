"""Interface d'extraction (SPEC §6.3, §7.3, D-006).

Trois familles d'extracteurs implémentent ``Extracteur`` : ``structure`` (XML/CSV/Factur-X, sans IA),
``deterministe`` (texte natif ou OCR + règles) et ``llm`` (modèle de langage, si une clé est configurée).
Chacun transforme un ``Document`` (et ses ``Page``) en champs typés dont chaque feuille est une
``ValeurSourcee``.

Règles transverses implémentées ici :

- ``anchor`` : une valeur est **ancrée** si sa valeur brute figure littéralement dans le texte de la page
  citée, après normalisation des espaces (§6.3) ;
- ``ancrer`` : applique l'ancrage à une valeur (et le plafond 0,50 d'une valeur ``llm`` non ancrée) ;
- ``fusionner_valeurs`` / ``fusionner_resultats`` : fusion de plusieurs extracteurs (§7.3, dernier
  point) — en cas de désaccord sur un champ clé, la valeur de plus haute confiance est retenue, sa
  confiance est plafonnée à 0,80 et la raison ``extracteurs_en_desaccord`` est mémorisée.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Literal, Protocol, runtime_checkable

from pydantic import Field, model_validator

from controldone.ids import IdGenerator
from controldone.model.base import Modele
from controldone.model.champs import CHAMPS_CLES, Champs, ChampsDocument, chemin_relatif, classe_champs
from controldone.model.documents import Document, Page
from controldone.model.enums import Methode, RaisonCode, TypeDocument
from controldone.model.referentiel import Entite
from controldone.model.valeur import (
    PLAFOND_CONFIANCE_DESACCORD,
    PLAFOND_CONFIANCE_LLM_NON_ANCREE,
    ExtracteurInfo,
    ValeurSourcee,
)
from controldone.normalize.text import normaliser_espaces

__all__ = [
    "PRIORITE_METHODE",
    "CoutExtraction",
    "Extracteur",
    "ExtractionContext",
    "ExtractionResult",
    "anchor",
    "ancrer",
    "fusionner_resultats",
    "fusionner_valeurs",
]

TypeExtracteurLitteral = Literal["structure", "deterministe", "llm"]

#: Ordre de préférence des méthodes (§7.3) : structure > texte natif > llm > OCR ; la saisie humaine
#: (correction, §6.2.11) remplace toujours la valeur précédente.
PRIORITE_METHODE: dict[Methode, int] = {
    Methode.saisie_humaine: -1,
    Methode.xml_structure: 0,
    Methode.csv_structure: 0,
    Methode.texte_natif: 1,
    Methode.llm: 2,
    Methode.ocr: 3,
    Methode.derive: 4,
}


class CoutExtraction(Modele):
    """Coût d'une extraction (§20.5). Nul pour ``structure`` et ``deterministe``."""

    jetons_entree: int = 0
    jetons_sortie: int = 0
    cout_eur: Decimal = Decimal("0")
    modele: str | None = None
    depuis_cache: bool = False

    def __add__(self, autre: CoutExtraction) -> CoutExtraction:
        return CoutExtraction(
            jetons_entree=self.jetons_entree + autre.jetons_entree,
            jetons_sortie=self.jetons_sortie + autre.jetons_sortie,
            cout_eur=self.cout_eur + autre.cout_eur,
            modele=self.modele or autre.modele,
            depuis_cache=self.depuis_cache and autre.depuis_cache,
        )


class ExtractionResult(Modele):
    """Sortie d'un extracteur. ``valeurs`` = toutes les feuilles de ``champs`` (rempli automatiquement)."""

    extracteur: ExtracteurInfo
    champs: ChampsDocument | None = None
    valeurs: list[ValeurSourcee] = Field(default_factory=list)
    cout: CoutExtraction = Field(default_factory=CoutExtraction)
    #: Messages techniques sans contenu de document (ex. « plafond de coût atteint »).
    avertissements: list[str] = Field(default_factory=list)
    #: Vrai si l'extraction n'a pas pu couvrir tout le document (plafond de coût, pages illisibles…).
    partielle: bool = False

    @model_validator(mode="after")
    def _valeurs(self) -> ExtractionResult:
        if self.champs is not None and not self.valeurs:
            object.__setattr__(self, "valeurs", list(self.champs.iter_valeurs()))
        return self


@dataclass
class ExtractionContext:
    """Contexte fourni par le pipeline à un extracteur (aucun accès base ni réseau, sauf ``llm``).

    - ``entites`` : entités du client (identification du pavé acheteur, §5.3.1) ;
    - ``codes_attendus`` : filtre **technique** des codes marchandise (jamais une validation, §5.3.1) ;
    - ``separateur_decimal`` : indice de langue (``","`` pour un document français) ;
    - ``contenu_fichier`` / ``type_mime`` : octets du fichier source (PDF pour l'extracteur ``llm``) ;
    - ``cost_guard`` / ``cache`` : utilisés par l'extracteur ``llm`` (voir ``extract/llm.py``).
    """

    client_id: str | None = None
    dossier_id: str | None = None
    lot_id: str | None = None
    entites: tuple[Entite, ...] = ()
    codes_attendus: frozenset[str] = frozenset()
    separateur_decimal: str | None = None
    contenu_fichier: bytes | None = None
    type_mime: str | None = None
    ids: IdGenerator = field(default_factory=IdGenerator)
    cost_guard: Any = None
    cache: Any = None
    options: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class Extracteur(Protocol):
    """Contrat d'un extracteur. ``id`` et ``version`` entrent dans la clé d'idempotence (§7 étape 4)."""

    id: str
    version: str
    type: TypeExtracteurLitteral

    def supports(self, document: Document, pages: Sequence[Page]) -> bool:
        """Vrai si l'extracteur sait traiter ce document (type, format, qualité de texte…)."""
        ...

    def extract(
        self, document: Document, pages: Sequence[Page], context: ExtractionContext
    ) -> ExtractionResult:
        """Extrait les champs. Ne lève pas pour un document difficile : retourne des champs ``None``
        (illisibles) et des avertissements ; lève seulement en cas d'erreur de programmation."""
        ...


# --- ancrage (§6.3) ---------------------------------------------------------------------------------


def anchor(valeur_brute: str | None, texte_page: str | None) -> bool:
    """Vrai si ``valeur_brute`` figure **littéralement** dans ``texte_page`` après normalisation des
    espaces (toute suite d'espaces, insécables ou fines, retours à la ligne -> une espace)."""
    if not valeur_brute or not texte_page:
        return False
    v = normaliser_espaces(valeur_brute)
    return bool(v) and v in normaliser_espaces(texte_page)


def ancrer(valeur: ValeurSourcee, textes_pages: Mapping[int, str]) -> ValeurSourcee:
    """Copie de ``valeur`` avec ``ancree`` calculé sur la page citée ; une valeur ``llm`` non ancrée a sa
    confiance plafonnée à 0,50 (§6.3). Les valeurs structurées / saisies ne sont pas modifiées."""
    if valeur.methode.est_structuree or valeur.methode is Methode.derive:
        return valeur
    texte = textes_pages.get(valeur.page) if valeur.page is not None else None
    ancree = anchor(valeur.valeur_brute, texte)
    conf = valeur.confiance
    if valeur.methode is Methode.llm and not ancree:
        conf = min(conf, PLAFOND_CONFIANCE_LLM_NON_ANCREE)
    return valeur.model_copy(update={"ancree": ancree, "confiance": conf})


# --- fusion de plusieurs extracteurs (§7.3) -----------------------------------------------------------


def _cle_tri(v: ValeurSourcee) -> tuple:
    # confiance décroissante, puis méthode préférée, puis identifiant d'extracteur (déterminisme)
    return (-v.confiance, PRIORITE_METHODE.get(v.methode, 9), v.extracteur.id, v.id)


def fusionner_valeurs(candidats: Sequence[ValeurSourcee], *, champ_cle: bool) -> ValeurSourcee:
    """Fusionne les valeurs d'un même champ produites par plusieurs extracteurs.

    - une ``saisie_humaine`` l'emporte toujours ;
    - accord (même ``valeur``) : la valeur de plus haute confiance ;
    - désaccord : la valeur de plus haute confiance, avec la raison ``extracteurs_en_desaccord`` ; sur un
      **champ clé**, sa confiance est en outre plafonnée à 0,80 (§7.3). Sur un champ non clé, la raison
      est mémorisée sans plafond (D-017) : le classement la traite comme un doute.
    """
    if not candidats:
        raise ValueError("aucune valeur à fusionner")
    humaines = [v for v in candidats if v.methode is Methode.saisie_humaine]
    if humaines:
        return sorted(humaines, key=_cle_tri)[0]
    lisibles = [v for v in candidats if v.est_lisible]
    pool = lisibles or list(candidats)
    retenue = sorted(pool, key=_cle_tri)[0]
    valeurs_distinctes = {v.valeur for v in lisibles}
    if len(valeurs_distinctes) <= 1:
        return retenue
    raisons = list(dict.fromkeys([*retenue.raisons, RaisonCode.extracteurs_en_desaccord]))
    conf = min(retenue.confiance, PLAFOND_CONFIANCE_DESACCORD) if champ_cle else retenue.confiance
    return retenue.model_copy(update={"raisons": raisons, "confiance": conf})


def _priorite_resultat(r: ExtractionResult) -> tuple:
    prio = min((PRIORITE_METHODE.get(v.methode, 9) for v in r.valeurs), default=9)
    return (prio, r.extracteur.id)


def fusionner_resultats(
    resultats: Sequence[ExtractionResult], type_document: TypeDocument | str
) -> ExtractionResult:
    """Fusionne les résultats de plusieurs extracteurs sur un même document, champ par champ.

    La base est une copie des champs du résultat de meilleure méthode (pour les classifications non
    sourcées : ``nature`` des lignes, ``categorie`` des taxes…) ; chaque feuille présente dans au moins
    un résultat est remplacée par la fusion de ses candidats (``fusionner_valeurs``).
    """
    td = TypeDocument(type_document)
    utiles = [r for r in resultats if r.champs is not None]
    cout = CoutExtraction()
    for r in resultats:
        cout = cout + r.cout
    avert = [a for r in resultats for a in r.avertissements]
    if not utiles:
        info = (
            resultats[0].extracteur if resultats else ExtracteurInfo(type="derive", id="fusion", version="1")
        )
        return ExtractionResult(extracteur=info, champs=None, cout=cout, avertissements=avert)
    utiles = sorted(utiles, key=_priorite_resultat)
    base = utiles[0]
    cls = classe_champs(td)
    if cls is None or not isinstance(base.champs, cls):
        raise ValueError(f"champs incompatibles avec le type {td.value}")
    champs: Champs = base.champs.model_copy(deep=True)
    cles = CHAMPS_CLES.get(td, frozenset())
    candidats: dict[str, list[ValeurSourcee]] = {}
    for r in utiles:
        assert r.champs is not None
        for v in r.champs.iter_valeurs():
            candidats.setdefault(chemin_relatif(v.chemin), []).append(v)
    for rel, vs in candidats.items():
        if rel.endswith("]"):
            continue  # éléments de listes de références : on garde ceux de la base (pas d'alignement sûr)
        try:
            champs.definir(rel, fusionner_valeurs(vs, champ_cle=rel in cles))
        except KeyError:
            continue
    return ExtractionResult(
        extracteur=ExtracteurInfo(
            type=base.extracteur.type,
            id="+".join(sorted({r.extracteur.id for r in utiles})),
            version="+".join(r.extracteur.version for r in sorted(utiles, key=lambda x: x.extracteur.id)),
        ),
        champs=champs,  # type: ignore[arg-type]
        cout=cout,
        avertissements=avert,
        partielle=any(r.partielle for r in resultats),
    )
