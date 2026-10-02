"""Pipeline de traitement d'un lot (SPEC §7) : réception -> pages -> découpage et classement ->
extraction -> normalisation -> regroupement -> contrôles -> rédaction -> findings.

Point d'entrée : ``traiter_lot(source, client_profile, grilles, autres_dossiers=..., options=...)``
-> ``list[ResultatDossier]``. Synchrone et sans base : une file de tâches en base (D-004) l'enveloppera
plus tard en appelant les étapes une à une avec les **clés d'idempotence** de §7 (``cles_*``).

Deux phases séparables (banc, famille F) :

- ``preparer_lot(...) -> LotPrepare`` : étapes 1 à 6 (jusqu'au regroupement) ;
- ``controler_lot(prepare, autres_dossiers=...) -> list[ResultatDossier]`` : étapes 7 à 8 et sortie.

Robustesse (§20.6) : une erreur sur un fichier ou un composant n'arrête jamais le lot ; le fichier est
listé dans ``non_lus`` avec un motif technique (sans contenu de document, §20.8).

Composants (``Composants``) : la réception vient de ``controldone.ingest.reception`` ; le découpage et le
classement (``Decoupeur``) et les extracteurs (``Extracteur``, ``controldone.extract.base``) sont
découverts à l'exécution dans ``controldone.ingest`` et ``controldone.extract`` (équipes ingestion et
extraction) ou injectés (tests : doubles).
"""

from __future__ import annotations

import hashlib
import importlib
import logging
import time
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from controldone import VERSION_NORMALISATION, VERSION_REGLES
from controldone.controls.context import AutreDossier, ControlContext
from controldone.controls.runner import run_controls
from controldone.extract.base import (
    CoutExtraction,
    Extracteur,
    ExtractionContext,
    ExtractionResult,
    fusionner_resultats,
)
from controldone.findings_io import Findings, construire_findings
from controldone.guardrails import MOTIF_FORMULATION_INTERDITE, check_text
from controldone.ids import IdGenerator, Prefixe
from controldone.model.base import horodatage
from controldone.model.documents import Document, Fichier, Lot, Page
from controldone.model.dossier import Dossier
from controldone.model.enums import StatutFichier, StatutGlobal, TypeDocument
from controldone.model.referentiel import GrilleTarifaire
from controldone.model.resultats import Constat, Execution, ResultatControle
from controldone.normalize.refs import norm_ref
from controldone.referentiel_io import ProfilClient, charger_grilles, charger_profil_client
from controldone.regroupement import (
    VERSION_REGROUPEMENT,
    OptionsRegroupement,
    cle_idempotence_regroupement,
    regrouper,
)
from controldone.taux_reference import TableTauxReference, table_par_defaut

__all__ = [
    "VERSION_GABARITS",
    "VERSION_PIPELINE",
    "Composants",
    "Decoupeur",
    "FichierSource",
    "LotPrepare",
    "NonLu",
    "OptionsPipeline",
    "ResultatDecoupage",
    "ResultatDossier",
    "cle_classement",
    "cle_controles",
    "cle_extraction",
    "cle_pages",
    "cle_redaction",
    "composants_par_defaut",
    "controler_lot",
    "preparer_lot",
    "traiter_lot",
]

log = logging.getLogger("controldone.pipeline")

VERSION_PIPELINE = "1.0.0"
#: Version des gabarits de texte (clé d'idempotence de l'étape 8).
VERSION_GABARITS = "1.0.0"

TYPES_EXTRAITS = (
    TypeDocument.facture_commerciale,
    TypeDocument.declaration,
    TypeDocument.facture_transitaire,
    TypeDocument.avoir,
    TypeDocument.document_support,
)
_RANG_EXTRACTEUR = {"structure": 0, "deterministe": 1, "llm": 2}


# --- clés d'idempotence (§7, tableau) ----------------------------------------------------------------


def _h(*parties: object) -> str:
    return hashlib.sha256("\x1f".join("" if p is None else str(p) for p in parties).encode("utf-8")).hexdigest()


def cle_pages(sha256_fichier: str, numero: int, version_ocr: str) -> str:
    """Étape 2 : ``sha256(fichier) + n° page + version_ocr``."""
    return _h("pages", sha256_fichier, numero, version_ocr)


def cle_classement(textes_pages: Iterable[str], version_classifieur: str) -> str:
    """Étape 3 : ``sha256(textes des pages) + version_classifieur``."""
    return _h("classement", _h(*textes_pages), version_classifieur)


def cle_extraction(identite: str | None, extracteur_id: str, version: str, *, normalisation: bool = True) -> str:
    """Étapes 4 et 5 : ``document.identite + extracteur.id + version`` (+ ``version_normalisation``)."""
    return _h("extraction", identite, extracteur_id, version, VERSION_NORMALISATION if normalisation else "")


def cle_controles(dossier_id: str, dossier_version: int, empreinte_tolerances: str) -> str:
    """Étape 7 : ``dossier_id + dossier_version + version_regles + empreinte_tolerances``."""
    return _h("controles", dossier_id, dossier_version, VERSION_REGLES, empreinte_tolerances)


def cle_redaction(constat_id: str) -> str:
    """Étape 8 : ``constat_id + version_gabarits``."""
    return _h("redaction", constat_id, VERSION_GABARITS)


# --- composants -----------------------------------------------------------------------------------------


@dataclass
class FichierSource:
    """Fichier reçu à découper : métadonnées, octets et chemin local (rognages du rapport)."""

    fichier: Fichier
    contenu: bytes | None
    chemin_local: Path | None = None
    courriel: str | None = None
    corps_courriel: bool = False


@dataclass
class ResultatDecoupage:
    pages: list[Page] = field(default_factory=list)
    documents: list[Document] = field(default_factory=list)
    avertissements: list[str] = field(default_factory=list)


@runtime_checkable
class Decoupeur(Protocol):
    """Étapes 2 et 3 (équipe ingestion) : pages (texte natif ou OCR) puis documents logiques classés
    (``champs = None``). Ne lève que pour une erreur de programmation ; le pipeline isole l'exception."""

    version: str

    def decouper(self, source: FichierSource, *, ids: IdGenerator, client_id: str | None) -> ResultatDecoupage: ...


Reception = Callable[..., Any]


@dataclass
class Composants:
    """Composants du pipeline. ``None`` : découverte automatique (``composants_par_defaut``)."""

    decoupeur: Decoupeur | None = None
    extracteurs: list[Extracteur] = field(default_factory=list)
    #: Normalisation dépendant du lot (codes reconstitués…) : ``fn(documents) -> documents``.
    normaliseur: Callable[[list[Document]], list[Document]] | None = None


def _tenter(module: str, *noms: str) -> Any:
    try:
        m = importlib.import_module(module)
    except Exception:
        return None
    for nom in noms:
        obj = getattr(m, nom, None)
        if obj is not None:
            return obj
    return None


class _DecoupeurFonction:
    """Adaptateur : fonction ``fn(source|fichier, contenu, ...)`` de l'équipe ingestion -> ``Decoupeur``."""

    def __init__(self, fn: Callable[..., Any], version: str = "?") -> None:
        self.fn = fn
        self.version = version

    def decouper(self, source: FichierSource, *, ids: IdGenerator, client_id: str | None) -> ResultatDecoupage:
        r = self.fn(source.fichier, source.contenu, ids=ids)
        if isinstance(r, ResultatDecoupage):
            return r
        if isinstance(r, tuple) and len(r) >= 2:
            return ResultatDecoupage(pages=list(r[0]), documents=list(r[1]))
        pages = list(getattr(r, "pages", []) or [])
        docs = list(getattr(r, "documents", []) or [])
        return ResultatDecoupage(pages=pages, documents=docs, avertissements=list(getattr(r, "avertissements", []) or []))


def _decoupeur_ingestion() -> Decoupeur | None:
    """Découpeur publié par l'équipe ingestion, s'il existe (plusieurs noms acceptés)."""
    for module in ("controldone.ingest", "controldone.ingest.decoupage", "controldone.ingest.pipeline",
                   "controldone.ingest.documents", "controldone.ingest.classement"):
        cls = _tenter(module, "Decoupeur", "DecoupeurDocuments", "Ingestion")
        if cls is not None and isinstance(cls, type):
            try:
                obj = cls()
            except Exception:
                continue
            if hasattr(obj, "decouper"):
                return obj  # type: ignore[return-value]
        fn = _tenter(module, "decouper_fichier", "decouper", "ingerer_fichier")
        if fn is not None and callable(fn):
            return _DecoupeurFonction(fn, str(_tenter(module, "VERSION_CLASSIFIEUR", "VERSION") or "?"))
    return None


def _extracteurs_disponibles() -> list[Extracteur]:
    """Extracteurs publiés (``structure``, ``deterministe``) + ``llm`` (actif seulement avec une clé)."""
    out: list[Extracteur] = []
    for module, noms in (
        ("controldone.ingest.structure", ("extracteurs",)),
        ("controldone.extract.structure", ("extracteurs", "EXTRACTEURS", "ExtracteurStructure")),
        ("controldone.extract.deterministe", ("extracteurs", "EXTRACTEURS", "ExtracteurDeterministe")),
    ):
        obj = _tenter(module, *noms)
        if obj is None:
            continue
        try:
            produits = obj() if callable(obj) else obj
        except Exception as e:
            log.warning("extracteur_indisponible module=%s exception=%s", module, type(e).__name__)
            continue
        if isinstance(produits, list | tuple):
            out.extend(p for p in produits if isinstance(p, Extracteur) and p.id not in {x.id for x in out})
        elif isinstance(produits, Extracteur) and produits.id not in {x.id for x in out}:
            out.append(produits)
    from controldone.extract.llm import LLMExtracteur

    llm = LLMExtracteur()
    if llm.disponible():
        out.append(llm)
    return out


def composants_par_defaut() -> Composants:
    return Composants(decoupeur=_decoupeur_ingestion(), extracteurs=_extracteurs_disponibles())


# --- options, résultats ---------------------------------------------------------------------------------


@dataclass
class OptionsPipeline:
    """Options d'exécution.

    - ``seed`` : identifiants reproductibles (banc) ;
    - ``dossier_id_sortie`` : identifiant écrit dans ``findings.json`` (banc : ``BXnnnn``) ;
    - ``memo`` : mémoire des étapes indexée par clé d'idempotence (rejeu sans recalcul) ;
    - ``controles`` : sous-ensemble de contrôles à exécuter (``None`` = tous).
    """

    seed: int | None = None
    annee: int | None = None
    meme_source: bool = True
    llm: bool = True
    taux_reference: TableTauxReference | None = None
    controles: Iterable[str] | None = None
    dossier_id_sortie: str | None = None
    memo: dict[str, Any] | None = None
    racine: Path | None = None
    plafond_ia_dossier_eur: Decimal = Decimal("0.50")


@dataclass
class NonLu:
    """Fichier ou document non lu / non reconnu (rapport §18.3 point 7)."""

    fichier: str  # chemin relatif
    motif: str
    document_id: str | None = None
    pages: list[int] = field(default_factory=list)


@dataclass
class LotPrepare:
    """Sortie des étapes 1 à 6 (sérialisable : envoyée entre processus par le banc)."""

    lot: Lot
    profil: ProfilClient
    grilles: list[GrilleTarifaire]
    fichiers: dict[str, Fichier]
    chemins: dict[str, str]  # fichier_id -> chemin local (str) pour les rognages
    pages: dict[str, list[Page]]  # fichier_id -> pages
    documents: dict[str, Document]
    dossiers: list[Dossier]
    non_lus: list[NonLu]
    cout: CoutExtraction
    versions_extracteurs: dict[str, str]
    duree_s: float
    cles: dict[str, Any]
    extraction_partielle: bool = False
    avertissements: list[str] = field(default_factory=list)


@dataclass
class ResultatDossier:
    """Résultat complet d'un dossier : la sortie ``findings`` et tout ce qu'il faut au rapport."""

    dossier: Dossier
    documents: dict[str, Document]
    fichiers: dict[str, Fichier]
    chemins: dict[str, str]
    pages: dict[str, list[Page]]
    resultats: list[ResultatControle]
    findings: Findings
    execution: Execution
    statut_global: StatutGlobal
    non_lus: list[NonLu]
    profil: ProfilClient
    cles: dict[str, Any] = field(default_factory=dict)

    @property
    def constats(self) -> list[Constat]:
        return [r.constat for r in self.resultats if r.constat is not None]


# --- étapes -----------------------------------------------------------------------------------------


def _recevoir(
    source: Any, client_id: str | None, ids: IdGenerator, racine: Path | None,
    doublons: list[tuple[Fichier, str | None]] | None = None,
) -> tuple[Lot, list[FichierSource], list[NonLu]]:
    """Étape 1 : réception (dossier, fichier, liste de chemins).

    Un fichier identique (sha256) déjà reçu n'est pas retraité (§7.1) : il est mentionné « doublon de
    fichier » dans ``non_lus`` et, si ``doublons`` est fourni, ajouté à cette liste (avec son chemin local)
    pour être rattaché au lot comme copie de l'original (D-802)."""
    from controldone.ingest.reception import recevoir_chemin

    chemins = [Path(s) for s in source] if isinstance(source, list | tuple) else [Path(source)]
    lot: Lot | None = None
    sources: list[FichierSource] = []
    non_lus: list[NonLu] = []
    for ch in chemins:
        base = racine if racine is not None else (ch.parent if ch.is_dir() else None)
        rec = recevoir_chemin(ch, client_id=client_id, racine=base, ids=ids)
        lot = lot or rec.lot
        for fr in rec.fichiers:
            f = fr.fichier
            if f.statut is StatutFichier.refuse:
                non_lus.append(NonLu(fichier=f.chemin_relatif, motif=f"refuse:{f.motif_refus or 'inconnu'}"))
                continue
            local = None
            if base is not None and "!" not in f.chemin_relatif and (fr.origine is None):
                cand = Path(base) / f.chemin_relatif
                local = cand if cand.exists() else None
            elif ch.is_file() and fr.origine is None:
                local = ch
            if f.doublon_de:
                non_lus.append(NonLu(fichier=f.chemin_relatif, motif="doublon_de_fichier"))
                if doublons is not None:
                    doublons.append((f, str(local) if local is not None else None))
                continue
            sources.append(FichierSource(fichier=f, contenu=fr.contenu, chemin_local=local,
                                         courriel=(fr.origine if (fr.origine or "").startswith("courriel:") else None),
                                         corps_courriel=fr.corps_courriel))
    if lot is None:
        lot = Lot(id=ids.nouveau(Prefixe.lot), client_id=client_id)
    return lot, sources, non_lus


def _identite(doc: Document, fichier: Fichier | None, nb_docs_fichier: int) -> str:
    """Clé de dédoublonnage (§6.2.6) : sha256 du fichier si le document est le fichier entier, sinon
    ``(type, norm_ref(numero), émetteur, total)``."""
    if fichier is not None and nb_docs_fichier == 1:
        return fichier.sha256
    c = doc.champs
    numero = getattr(c, "numero", None) if c is not None else None
    numero = numero.valeur if numero is not None else None
    emetteur = None
    for nom in ("vendeur", "emetteur"):
        p = getattr(c, nom, None) if c is not None else None
        if p is not None and getattr(p, "tva", None) is not None:
            emetteur = p.tva.valeur
    total = None
    for nom in ("total_facture", "total_ttc", "total_credite_ttc", "montant_total_facture"):
        v = getattr(c, nom, None) if c is not None else None
        if v is not None:
            total = v.valeur
            break
    pages = ",".join(f"{p.fichier_id}:{p.numero}" for p in doc.pages)
    if numero is None:
        return _h("doc", doc.type.value, pages)
    return _h("doc", doc.type.value, norm_ref(numero), norm_ref(emetteur), total)


def _extraire(
    doc: Document, pages: Sequence[Page], extracteurs: Sequence[Extracteur], ctx: ExtractionContext,
    memo: dict[str, Any] | None,
) -> tuple[Document, CoutExtraction, list[str], dict[str, str], bool]:
    """Étapes 4 et 5 : extracteurs dans l'ordre de §7.3 (structure > déterministe > llm), fusion (§7.3).

    Un extracteur ``structure`` complet suffit ; sinon les extracteurs ``deterministe`` (texte natif ou
    OCR) et ``llm`` (si disponible) tournent tous et leurs valeurs sont fusionnées champ par champ
    (préférence des méthodes : structure > texte natif > llm > OCR ; désaccord : confiance plafonnée).
    """
    candidats = []
    for e in extracteurs:
        try:
            if e.supports(doc, pages):
                candidats.append(e)
        except Exception as ex:
            log.warning("extracteur_supports_en_erreur extracteur=%s exception=%s", getattr(e, "id", "?"),
                        type(ex).__name__)
    candidats.sort(key=lambda e: (_RANG_EXTRACTEUR.get(e.type, 9), e.id))
    resultats: list[ExtractionResult] = []
    avert: list[str] = []
    versions: dict[str, str] = {}
    cout = CoutExtraction()
    partielle = False
    for e in candidats:
        if resultats and e.type != "structure" and any(
            r.extracteur.type.value == "structure" and r.champs is not None and not r.partielle for r in resultats
        ):
            break  # un export structuré complet fait foi
        cle = cle_extraction(doc.identite, e.id, e.version)
        try:
            if memo is not None and cle in memo:
                r = memo[cle]
            else:
                r = e.extract(doc, pages, ctx)
                if memo is not None:
                    memo[cle] = r
        except Exception as ex:  # §20.6 : jamais bloquant
            log.warning("extraction_en_erreur extracteur=%s document=%s exception=%s", e.id, doc.id,
                        type(ex).__name__)
            avert.append(f"extraction_en_erreur:{e.id}")
            partielle = True
            continue
        versions[e.id] = e.version
        cout = cout + r.cout
        avert.extend(r.avertissements)
        partielle = partielle or r.partielle
        if r.champs is not None:
            resultats.append(r)
    if not resultats:
        return doc, cout, avert, versions, partielle
    try:
        fusion = resultats[0] if len(resultats) == 1 else fusionner_resultats(resultats, doc.type)
    except Exception as ex:
        log.warning("fusion_en_erreur document=%s exception=%s", doc.id, type(ex).__name__)
        fusion = sorted(resultats, key=lambda r: _RANG_EXTRACTEUR.get(r.extracteur.type.value, 9))[0]
    nouveau = doc.model_copy(update={"champs": fusion.champs})
    return nouveau, cout, avert, versions, partielle


def preparer_lot(
    source: Any,
    client_profile: ProfilClient | Mapping[str, Any] | str | Path | None = None,
    grilles: Sequence[GrilleTarifaire] | str | Path | None = None,
    *,
    options: OptionsPipeline | None = None,
    composants: Composants | None = None,
) -> LotPrepare:
    """Étapes 1 à 6 sur un lot (dossier, fichier ou liste de chemins)."""
    debut = time.perf_counter()
    options = options or OptionsPipeline()
    profil = charger_profil_client(client_profile)
    if isinstance(grilles, str | Path):
        grilles = charger_grilles(grilles, client_id=profil.client_id)
    grilles = list(grilles or [])
    comp = composants or composants_par_defaut()
    ids = IdGenerator.deterministe(options.seed) if options.seed is not None else IdGenerator()
    memo = options.memo
    cles: dict[str, Any] = {"reception": [], "pages": [], "classement": [], "extraction": []}

    # 1. réception
    non_lus: list[NonLu] = []
    doublons_fichiers: list[tuple[Fichier, str | None]] = []
    try:
        lot, sources, nl = _recevoir(source, profil.client_id, ids, options.racine, doublons_fichiers)
        non_lus.extend(nl)
    except Exception as e:
        log.error("reception_en_erreur exception=%s", type(e).__name__)
        lot, sources = Lot(id=ids.nouveau(Prefixe.lot), client_id=profil.client_id), []
        non_lus.append(NonLu(fichier=str(source), motif=f"reception_en_erreur:{type(e).__name__}"))
    fichiers = {s.fichier.id: s.fichier for s in sources}
    chemins = {s.fichier.id: str(s.chemin_local) for s in sources if s.chemin_local is not None}
    for s in sources:
        cles["reception"].append(_h("reception", s.fichier.sha256, profil.client_id, s.courriel))

    # 2-3. pages, découpage, classement
    pages: dict[str, list[Page]] = {}
    documents: list[Document] = []
    avertissements: list[str] = []
    for s in sources:
        if comp.decoupeur is None:
            non_lus.append(NonLu(fichier=s.fichier.chemin_relatif, motif="ingestion_indisponible"))
            continue
        try:
            r = comp.decoupeur.decouper(s, ids=ids, client_id=profil.client_id)
        except Exception as e:
            log.warning("decoupage_en_erreur fichier=%s exception=%s", s.fichier.id, type(e).__name__)
            non_lus.append(NonLu(fichier=s.fichier.chemin_relatif, motif=f"lecture_en_erreur:{type(e).__name__}"))
            continue
        pages[s.fichier.id] = list(r.pages)
        avertissements.extend(r.avertissements)
        version = getattr(comp.decoupeur, "version", "?")
        for p in r.pages:
            cles["pages"].append(cle_pages(s.fichier.sha256, p.numero, version))
        if not r.documents:
            non_lus.append(NonLu(fichier=s.fichier.chemin_relatif, motif="aucun_document_reconnu",
                                 pages=[p.numero for p in r.pages]))
        for d in r.documents:
            textes = [p.texte for p in r.pages if any(pr.numero == p.numero for pr in d.pages)]
            cles["classement"].append(cle_classement(textes, version))
            if d.identite is None:
                d = d.model_copy(update={"identite": _identite(d, s.fichier, len(r.documents))})
            documents.append(d)

    # 4-5. extraction (+ normalisation intégrée à la construction des valeurs)
    contenus = {s.fichier.id: s for s in sources}
    cost_guard = None
    if options.llm:
        from controldone.extract.llm import CostGuard, RegistreCoutsMemoire

        cost_guard = CostGuard(RegistreCoutsMemoire(), plafond_dossier=options.plafond_ia_dossier_eur)
    extracteurs = [e for e in comp.extracteurs if options.llm or e.type != "llm"]
    cout = CoutExtraction()
    versions: dict[str, str] = {}
    partielle = False
    extraits: list[Document] = []
    for d in documents:
        if d.type not in TYPES_EXTRAITS or d.champs is not None or not extracteurs:
            extraits.append(d)
            continue
        fid = d.pages[0].fichier_id if d.pages else None
        src = contenus.get(fid) if fid else None
        pages_doc = [p for p in pages.get(fid or "", []) if any(pr.numero == p.numero for pr in d.pages)]
        ctx = ExtractionContext(
            client_id=profil.client_id, dossier_id=lot.id, lot_id=lot.id, entites=tuple(profil.entites),
            contenu_fichier=src.contenu if src else None, type_mime=src.fichier.type_mime if src else None,
            ids=ids, cost_guard=cost_guard,
        )
        nouveau, c, av, vers, part = _extraire(d, pages_doc, extracteurs, ctx, memo)
        for e in extracteurs:
            if e.id in vers:
                cles["extraction"].append(cle_extraction(d.identite, e.id, e.version))
        cout, partielle = cout + c, partielle or part
        versions.update(vers)
        avertissements.extend(av)
        extraits.append(nouveau)
    documents = extraits
    if comp.normaliseur is not None:
        try:
            documents = list(comp.normaliseur(documents))
        except Exception as e:
            log.warning("normalisation_en_erreur exception=%s", type(e).__name__)
            avertissements.append("normalisation_en_erreur")
    documents += _copies_fichiers_doublons(doublons_fichiers, documents, fichiers, chemins, pages, ids)
    documents = _marquer_doublons(documents)

    # documents non reconnus (§7.2) : listés même s'ils sont rattachés
    for d in documents:
        if d.type is TypeDocument.inconnu:
            fic = fichiers.get(d.pages[0].fichier_id) if d.pages else None
            non_lus.append(NonLu(fichier=fic.chemin_relatif if fic else "?", motif="document_non_reconnu",
                                 document_id=d.id, pages=[p.numero for p in d.pages]))

    # 6. regroupement
    courriels = {s.fichier.id: s.courriel for s in sources if s.courriel}
    try:
        reg = regrouper(
            documents, fichiers, profil=profil.tolerances, transitaires=profil.transitaires,
            options=OptionsRegroupement(meme_source=options.meme_source, annee=options.annee or horodatage().year,
                                        courriels=courriels, lot_ids=(lot.id,)),
        )
        dossiers = reg.dossiers
        for doc_id in reg.non_rattaches:
            d = next(x for x in documents if x.id == doc_id)
            if d.type is TypeDocument.inconnu:
                continue  # déjà listé
            fic = fichiers.get(d.pages[0].fichier_id) if d.pages else None
            non_lus.append(NonLu(fichier=fic.chemin_relatif if fic else "?", motif="document_non_rattache",
                                 document_id=d.id, pages=[p.numero for p in d.pages]))
    except Exception as e:
        log.error("regroupement_en_erreur exception=%s", type(e).__name__)
        dossiers = []
        non_lus.append(NonLu(fichier="*", motif=f"regroupement_en_erreur:{type(e).__name__}"))
    cles["regroupement"] = [cle_idempotence_regroupement(d.document_ids()) for d in dossiers]
    cles["version_regroupement"] = VERSION_REGROUPEMENT
    return LotPrepare(
        lot=lot, profil=profil, grilles=grilles, fichiers=fichiers, chemins=chemins, pages=pages,
        documents={d.id: d for d in documents}, dossiers=dossiers, non_lus=non_lus, cout=cout,
        versions_extracteurs=versions, duree_s=time.perf_counter() - debut, cles=cles,
        extraction_partielle=partielle, avertissements=avertissements,
    )


def _copies_fichiers_doublons(
    doublons: Sequence[tuple[Fichier, str | None]], documents: Sequence[Document], fichiers: dict[str, Fichier],
    chemins: dict[str, str], pages: dict[str, list[Page]], ids: IdGenerator,
) -> list[Document]:
    """Fichier identique déjà reçu (§7.1) : il n'est pas retraité, mais il est rattaché au lot comme copie.

    Pour chaque document de l'original, une copie (mêmes type, champs et identité) pointe vers les pages du
    fichier en double et porte ``doublon_de`` = document original : le regroupement la place avec son
    original, les contrôles l'excluent de leurs sommes (``documents_par_role``), et F1/E3 peuvent la
    signaler (D-802). ``fichiers``, ``chemins`` et ``pages`` sont complétés sur place.
    """
    copies: list[Document] = []
    for f, local in doublons:
        originaux = [d for d in documents if d.pages and d.pages[0].fichier_id == f.doublon_de
                     and not d.doublon_de]
        if not originaux:
            continue
        fichiers[f.id] = f
        if local is not None:
            chemins[f.id] = local
        pages[f.id] = [p.model_copy(update={"id": ids.nouveau(Prefixe.page), "fichier_id": f.id})
                       for p in pages.get(f.doublon_de or "", [])]
        for d in originaux:
            copies.append(d.model_copy(update={
                "id": ids.nouveau(Prefixe.document),
                "pages": [pr.model_copy(update={"fichier_id": f.id}) for pr in d.pages],
                "doublon_de": d.id,
            }))
    return copies


def _marquer_doublons(documents: list[Document]) -> list[Document]:
    """Doublons intra-lot (même identité) : le second porte ``doublon_de`` (F1, une seule occurrence
    comptée par les contrôles)."""
    vus: dict[tuple[str, str], str] = {}
    sortie = []
    for d in documents:
        if d.identite and not d.doublon_de and d.type is not TypeDocument.inconnu:
            k = (d.type.value, d.identite)
            if k in vus:
                d = d.model_copy(update={"doublon_de": vus[k]})
            else:
                vus[k] = d.id
        sortie.append(d)
    return sortie


def autres_dossiers_de(prepares: Iterable[LotPrepare]) -> list[AutreDossier]:
    """Tous les dossiers de lots préparés, sous forme ``AutreDossier`` (famille F, même client)."""
    out = []
    for p in prepares:
        for d in p.dossiers:
            out.append(AutreDossier(dossier=d, documents={i: p.documents[i] for i in d.document_ids()
                                                           if i in p.documents}))
    return out


def _rediger(resultats: list[ResultatControle]) -> tuple[list[ResultatControle], list[str]]:
    """Étape 8 : les libellés viennent des gabarits des contrôles ; on vérifie ici le filtre §3.2 sur le
    texte final (le moteur l'a déjà fait ; un texte modifié après coup est rebloqué)."""
    cles = []
    sortie = []
    for r in resultats:
        c = r.constat
        if c is not None:
            cles.append(cle_redaction(c.id))
            if c.motif_blocage is None and check_text(f"{c.libelle} {c.prochaine_action}"):
                c2 = c.model_copy(update={"motif_blocage": MOTIF_FORMULATION_INTERDITE})
                r = r.model_copy(update={"constat": c2})
        sortie.append(r)
    return sortie, cles


def controler_lot(
    prepare: LotPrepare,
    *,
    autres_dossiers: Sequence[AutreDossier] = (),
    options: OptionsPipeline | None = None,
) -> list[ResultatDossier]:
    """Étapes 7 et 8 + sortie ``findings`` pour chaque dossier du lot. ``autres_dossiers`` : autres
    dossiers du **même client** (famille F) ; les dossiers frères du lot y sont ajoutés automatiquement."""
    debut = time.perf_counter()
    options = options or OptionsPipeline()
    ids = IdGenerator.deterministe(options.seed + 1) if options.seed is not None else IdGenerator()
    profil = prepare.profil
    empreinte = profil.tolerances.empreinte()
    execution = Execution.nouvelle(
        id=ids.nouveau(Prefixe.execution), client_id=profil.client_id, empreinte_tolerances=empreinte,
        versions_extracteurs=dict(sorted(prepare.versions_extracteurs.items())),
        modele_llm=prepare.cout.modele, cout_ia_eur=prepare.cout.cout_eur,
        jetons_entree=prepare.cout.jetons_entree, jetons_sortie=prepare.cout.jetons_sortie,
    )
    freres = autres_dossiers_de([prepare])
    sortie: list[ResultatDossier] = []
    pour_sortie: list[tuple[Dossier, list[ResultatControle], dict[str, Any]]] = []
    for dossier in prepare.dossiers:
        autres = [a for a in [*autres_dossiers, *freres] if a.dossier.id != dossier.id]
        docs = [prepare.documents[i] for i in dossier.document_ids() if i in prepare.documents]
        cles = {"controles": cle_controles(dossier.id, dossier.version, empreinte)}
        memo = options.memo
        try:
            if memo is not None and cles["controles"] in memo and not autres:
                resultats = memo[cles["controles"]]
            else:
                ctx = ControlContext.construire(
                    dossier, docs, profil.tolerances, grilles=prepare.grilles, entites=profil.entites,
                    transitaires=profil.transitaires, autres_dossiers=autres,
                    taux_reference=options.taux_reference or table_par_defaut(),
                    parametres_petits_envois=profil.parametres_petits_envois,
                    execution_id=execution.id,
                )
                resultats = run_controls(ctx, controles=options.controles)
                if memo is not None and not autres:
                    memo[cles["controles"]] = resultats
        except Exception as e:  # le moteur isole déjà chaque contrôle ; ceci protège la construction
            log.error("controles_en_erreur dossier=%s exception=%s", dossier.id, type(e).__name__)
            resultats = []
        resultats, cles["redaction"] = _rediger(resultats)
        pour_sortie.append((dossier, resultats, cles))
    duree = prepare.duree_s + (time.perf_counter() - debut)
    execution = execution.model_copy(update={"termine_le": horodatage(), "duree_s": round(duree, 3)})
    for dossier, resultats, cles in pour_sortie:
        from controldone.findings_io import statut_global_depuis_resultats

        statut = statut_global_depuis_resultats(resultats)
        dossier = dossier.model_copy(update={"statut_global": statut})
        docs = {i: prepare.documents[i] for i in dossier.document_ids() if i in prepare.documents}
        findings = construire_findings(
            dossier, docs.values(), resultats, execution, fichiers=prepare.fichiers,
            dossier_id=options.dossier_id_sortie or dossier.reference or dossier.id, statut_global=statut,
        )
        sortie.append(
            ResultatDossier(
                dossier=dossier, documents=docs, fichiers=prepare.fichiers, chemins=prepare.chemins,
                pages=prepare.pages, resultats=resultats, findings=findings, execution=execution,
                statut_global=statut, non_lus=list(prepare.non_lus), profil=profil,
                cles={**{k: v for k, v in prepare.cles.items()}, **cles},
            )
        )
    return sortie


def traiter_lot(
    source: Any,
    client_profile: ProfilClient | Mapping[str, Any] | str | Path | None = None,
    grilles: Sequence[GrilleTarifaire] | str | Path | None = None,
    *,
    autres_dossiers: Sequence[AutreDossier] = (),
    options: OptionsPipeline | None = None,
    composants: Composants | None = None,
) -> list[ResultatDossier]:
    """Traite un lot de bout en bout (§7). ``source`` : dossier, fichier, liste de chemins, ou ``LotPrepare``
    déjà préparé. Ne lève pas pour un fichier ou un document difficile (§20.6)."""
    options = options or OptionsPipeline()
    prepare = source if isinstance(source, LotPrepare) else preparer_lot(
        source, client_profile, grilles, options=options, composants=composants
    )
    return controler_lot(prepare, autres_dossiers=autres_dossiers, options=options)


__all__ += ["autres_dossiers_de"]
