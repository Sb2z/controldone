"""Découpage en documents logiques (SPEC §6.2.6, §7.2) et point d'entrée des étapes 2 et 3 du pipeline.

Règles :

- une page ``continuation`` est absorbée par le document précédent du même fichier, **sauf** si une
  référence clé change (nouveau numéro de facture, nouveau préfixe MRN) : un nouveau document du même
  type commence ;
- une page typée rejoint le document en cours si c'est la suite du même document (même type, « page n/m »
  avec n > 1, même numéro de facture, même préfixe MRN pour une déclaration) ;
- plusieurs déclarations dans un même PDF : découpe sur changement de préfixe MRN ;
- un fichier structuré (Factur-X, CII, UBL, export de déclaration reconnu par une fiche) est classé
  d'après son contenu et forme **un** document ;
- confiance de classement < 0,70 -> ``inconnu`` (§7.2).

``Decoupeur.decouper(source, ids=, client_id=)`` est le composant découvert par ``controldone.pipeline``.
Les textes positionnés (``PageText``) des pages produites restent disponibles pour les extracteurs via
``texte_positionne(page)`` (registre mémoire borné ; à défaut, reconstruits sans géométrie).
"""

from __future__ import annotations

import hashlib
from collections import Counter, OrderedDict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path
from threading import Lock
from typing import Any

from controldone.ids import IdGenerator, Prefixe, nouvel_id
from controldone.model import Document, Fichier, Page, PageRef
from controldone.model.enums import MotifNonExploitable, TypeDocument

from .classement import CONTINUATION, SEUIL_CONFIANCE, VERSION_CLASSIFIEUR, ClassementPage, classer_page
from .pages import VERSION_PAGES, OptionsPages, PageExtraite, extraire_pages, textes_pages, version_ocr
from .reception import MIME_CORPS_COURRIEL
from .sniff import MIME_CSV, MIME_PDF, MIME_XML
from .structure import FicheCorrespondance, InfoStructure, analyser_contenu_structure
from .texte import Ligne, Mot, PageText

__all__ = [
    "VERSION_DECOUPAGE",
    "Decoupeur",
    "ResultatIngestion",
    "cle_classement",
    "decouper_fichier",
    "decouper_pages",
    "enregistrer_textes",
    "liberer_textes",
    "texte_positionne",
]

VERSION_DECOUPAGE = f"pages-{VERSION_PAGES}+classement-{VERSION_CLASSIFIEUR}"

#: Bornes de l'étape 3 sur une page démesurée (D-1607), exécutée dans le processus principal (worker) : au-delà,
#: l'arbre XML d'un fichier de 50 Mo à millions d'éléments pesait ~1 Go (lxml), et le classement de son texte
#: (normalisation caractère par caractère) ~1 Go de plus. Les documents réels en sont très loin (facture UBL de
#: 10 000 lignes : ~300 000 balises ; pages du corpus : quelques Ko).
MAX_BALISES_STRUCTURE = 1_000_000
MAX_CARACTERES_CLASSEMENT = 1_000_000
MAX_CARACTERES_LIGNE_CLASSEMENT = 10_000
MAX_LIGNES_CLASSEMENT = 20_000

_FACTURES = (TypeDocument.facture_commerciale, TypeDocument.facture_transitaire, TypeDocument.avoir)


def cle_classement(textes: Iterable[str]) -> str:
    """Clé de l'étape 3 (§7) : ``sha256(textes des pages) + version_classifieur``."""
    h = hashlib.sha256()
    for t in textes:
        h.update(hashlib.sha256(t.encode("utf-8")).digest())
    h.update(VERSION_CLASSIFIEUR.encode())
    return h.hexdigest()


# --- registre des textes positionnés -----------------------------------------------------------------------

_REGISTRE: OrderedDict[str, PageText] = OrderedDict()
_REGISTRE_MAX = 20_000
_VERROU = Lock()


def enregistrer_textes(pages: Iterable[PageExtraite]) -> None:
    with _VERROU:
        for p in pages:
            for cle in (p.page.id, f"sha:{p.page.sha256_texte}"):
                _REGISTRE[cle] = p.texte
                _REGISTRE.move_to_end(cle)
        while len(_REGISTRE) > _REGISTRE_MAX:
            _REGISTRE.popitem(last=False)


def liberer_textes(pages: Iterable[Page]) -> None:
    """Retire du registre les textes des pages d'un lot dont l'extraction est terminée (D-1403 : texte de document
    en clair, ~85 Ko par page, gardé sinon jusqu'à 20 000 entrées dans un worker de longue durée). La clé
    ``sha:`` n'est retirée que si elle désigne encore le texte de cette page (un autre lot en cours peut l'avoir
    enregistrée pour une page de même texte)."""
    with _VERROU:
        for p in pages:
            t = _REGISTRE.pop(p.id, None)
            cle = f"sha:{p.sha256_texte}"
            if t is not None and _REGISTRE.get(cle) is t:
                del _REGISTRE[cle]


def texte_positionne(page: Page) -> PageText:
    """``PageText`` (mots positionnés) d'une page produite par l'ingestion ; à défaut, texte sans géométrie
    (une ligne par ligne de texte, boîtes nulles)."""
    with _VERROU:
        t = _REGISTRE.get(page.id) or _REGISTRE.get(f"sha:{page.sha256_texte}")
    if t is not None:
        return t
    lignes = []
    for li in page.texte.splitlines():
        if li.strip():
            mots = tuple(Mot(texte=m, x0=0.0, y0=0.0, x1=0.0, y1=0.0) for m in li.split())
            lignes.append(Ligne(texte=li.strip(), mots=mots))
    return PageText(numero=page.numero, texte=page.texte, lignes=lignes, qualite=page.qualite_texte,
                    source="inconnue", score_ocr=page.score_ocr, feuille=page.feuille)


# --- découpage -----------------------------------------------------------------------------------------------


@dataclass
class _EnCours:
    type: TypeDocument
    sous_type: str | None
    motif: MotifNonExploitable | None
    confiance: float
    pages: list[int] = field(default_factory=list)
    numero_facture: str | None = None
    mrn_prefixes: list[str] = field(default_factory=list)
    page_total: int | None = None
    langues: list[str] = field(default_factory=list)


def _proches(a: str, b: str) -> bool:
    """Références égales à une ou deux erreurs de lecture près (OCR : 5/S, 0/O…), même longueur."""
    if a == b:
        return True
    if len(a) != len(b) or len(a) < 6:
        return False
    diff = [(x, y) for x, y in zip(a, b, strict=True) if x != y]
    return len(diff) <= 2 and all(frozenset(d) in _CONFUSABLES for d in diff)


#: Paires de caractères confondues par l'OCR (une référence qui ne diffère que par elles est la même).
_CONFUSABLES = {frozenset(p) for p in ("5S", "0O", "0D", "1I", "1L", "IL", "8B", "2Z", "6G", "QO", "UV")}


def _mrn_connu(p: str, connus: list[str]) -> bool:
    return any(_proches(p, q) for q in connus)


def _changement_ref(cur: _EnCours, c: ClassementPage) -> bool:
    r = c.refs
    if r.numero_facture and cur.numero_facture and not _proches(r.numero_facture, cur.numero_facture) \
            and cur.type in (*_FACTURES, TypeDocument.document_non_exploitable):
        return True
    if cur.type is TypeDocument.declaration and r.mrn_prefixes and cur.mrn_prefixes:
        return not _mrn_connu(r.mrn_prefixes[0], cur.mrn_prefixes)
    return False


def _meme_document(cur: _EnCours, c: ClassementPage) -> bool:
    if c.type != cur.type:
        return False
    if c.type is TypeDocument.document_support and c.sous_type != cur.sous_type:
        return False
    if c.type is TypeDocument.document_non_exploitable and c.motif_non_exploitable != cur.motif:
        return False
    if _changement_ref(cur, c):
        return False
    r = c.refs
    if r.page_n == 1:
        return False
    if r.page_n and r.page_n > 1 and (not cur.page_total or not r.page_total or r.page_total == cur.page_total):
        return True
    if cur.type is TypeDocument.declaration:
        return (not r.mrn_prefixes) or (bool(cur.mrn_prefixes) and _mrn_connu(r.mrn_prefixes[0], cur.mrn_prefixes))
    if cur.type in _FACTURES:
        if r.numero_facture and cur.numero_facture:
            return _proches(r.numero_facture, cur.numero_facture)
        return False
    # supports : une page qui porte son propre intitulé (LTA, liste de colisage…) commence un document ;
    # conditions générales, courriel et pages sans intitulé suivent le document en cours.
    if cur.type is TypeDocument.document_support:
        return cur.sous_type in ("conditions_generales", "courriel") or not c.intitulee
    return cur.type is TypeDocument.document_non_exploitable and not c.intitulee


def _nouveau(c: ClassementPage, *, type_=None, conf=None) -> _EnCours:
    t = type_ if type_ is not None else c.type
    e = _EnCours(type=t, sous_type=c.sous_type if type_ is None else None,
                 motif=c.motif_non_exploitable if type_ is None else None,
                 confiance=c.confiance if conf is None else conf)
    _absorber(e, c)
    return e


def _absorber(e: _EnCours, c: ClassementPage) -> None:
    e.pages.append(c.numero)
    if c.refs.numero_facture and not e.numero_facture:
        e.numero_facture = c.refs.numero_facture
    for p in c.refs.mrn_prefixes:
        if e.type is TypeDocument.declaration and p not in e.mrn_prefixes and not e.mrn_prefixes:
            e.mrn_prefixes.append(p)
    if c.refs.page_total and not e.page_total:
        e.page_total = c.refs.page_total
    if c.langue:
        e.langues.append(c.langue)


def _regrouper(classements: Sequence[ClassementPage]) -> list[_EnCours]:
    docs: list[_EnCours] = []
    cur: _EnCours | None = None
    for c in classements:
        if c.type == CONTINUATION:
            if cur is None:
                cur = _nouveau(c, type_=TypeDocument.inconnu, conf=min(0.5, c.confiance))
                docs.append(cur)
            elif _changement_ref(cur, c):
                cur = _nouveau(c, type_=cur.type, conf=round(cur.confiance * 0.9, 3))
                if cur.type is TypeDocument.declaration:
                    cur.sous_type = docs[-1].sous_type
                docs.append(cur)
            else:
                _absorber(cur, c)
            continue
        if cur is not None and _meme_document(cur, c):
            _absorber(cur, c)
            continue
        cur = _nouveau(c)
        docs.append(cur)
    return docs


def decouper_pages(
    classements: Sequence[ClassementPage],
    pages: Sequence[Page],
    *,
    fichier: Fichier,
    ids: IdGenerator | None = None,
) -> list[Document]:
    """Documents logiques d'un fichier à partir du classement de ses pages (ordre du fichier)."""
    par_numero = {p.numero: p for p in pages}
    groupes = _regrouper(classements)
    docs: list[Document] = []
    for g in groupes:
        type_ = g.type if isinstance(g.type, TypeDocument) else TypeDocument.inconnu
        sous_type, motif = g.sous_type, g.motif
        if g.confiance < SEUIL_CONFIANCE and type_ is not TypeDocument.inconnu:
            type_, sous_type, motif = TypeDocument.inconnu, None, None
        if type_ is not TypeDocument.document_non_exploitable:
            motif = None
        refs = [PageRef(fichier_id=fichier.id, numero=n,
                        qualite_texte=par_numero[n].qualite_texte if n in par_numero else None) for n in g.pages]
        if len(groupes) == 1:
            identite = fichier.sha256
        else:
            identite = hashlib.sha256(f"{fichier.sha256}:{','.join(map(str, g.pages))}".encode()).hexdigest()
        langue = Counter(g.langues).most_common(1)[0][0] if g.langues else None
        docs.append(Document(
            id=ids.nouveau(Prefixe.document) if ids is not None else nouvel_id(Prefixe.document),
            client_id=fichier.client_id, type=type_, sous_type=sous_type, pages=refs,
            confiance_classement=round(min(1.0, max(0.0, g.confiance)), 3), motif_non_exploitable=motif,
            identite=identite, champs=None, langue=langue,
        ))
    return docs


@dataclass
class ResultatIngestion:
    """Sortie des étapes 2 et 3 pour un fichier (compatible ``pipeline.ResultatDecoupage``)."""

    pages: list[Page] = field(default_factory=list)
    documents: list[Document] = field(default_factory=list)
    avertissements: list[str] = field(default_factory=list)
    textes: dict[int, PageText] = field(default_factory=dict)
    classements: list[ClassementPage] = field(default_factory=list)
    structure: InfoStructure | None = None


def decouper_fichier(
    fichier: Fichier,
    contenu: bytes | None,
    *,
    ids: IdGenerator | None = None,
    options: OptionsPages | None = None,
    corps_courriel: bool = False,
    fiches: Iterable[FicheCorrespondance] | None = None,
    textes: list[PageText] | None = None,
    **_: Any,
) -> ResultatIngestion:
    """Étapes 2 et 3 (§7) pour un fichier accepté : pages avec texte, classement, documents logiques.
    ``textes`` : texte des pages déjà calculé (``Decoupeur.precharger``)."""
    if contenu is None:
        return ResultatIngestion(avertissements=["contenu_absent"])
    mime = fichier.type_mime
    corps = corps_courriel or mime == MIME_CORPS_COURRIEL
    extraites = extraire_pages(contenu, fichier=fichier, options=options, ids=ids, textes=textes)
    enregistrer_textes(extraites)
    pages = [p.page for p in extraites]
    textes = {p.page.numero: p.texte for p in extraites}
    avert = sorted({a for p in extraites for a in p.texte.avertissements})
    info = None
    if not corps and mime == MIME_XML and contenu.count(b"<") > MAX_BALISES_STRUCTURE:
        avert.append("structure_non_analysee:trop_d_elements")  # XML de format inconnu (D-1607)
    elif not corps and mime in (MIME_XML, MIME_CSV, MIME_PDF):
        try:
            info = analyser_contenu_structure(contenu, mime, fiches=fiches)
        except Exception:
            info = None
    if info is not None:
        langue = None
        from .classement import detecter_langue

        langue = detecter_langue(" ".join(t.texte for t in textes.values())[:20000])
        doc = Document(
            id=ids.nouveau(Prefixe.document) if ids is not None else nouvel_id(Prefixe.document),
            client_id=fichier.client_id, type=info.type, sous_type=info.sous_type,
            pages=[PageRef(fichier_id=fichier.id, numero=p.numero, qualite_texte=p.qualite_texte) for p in pages],
            confiance_classement=info.confiance, identite=fichier.sha256, langue=langue,
            motif_non_exploitable=info.motif,
        )
        return ResultatIngestion(pages=pages, documents=[doc], avertissements=[*avert, f"structure:{info.format}"],
                                 textes=textes, structure=info)
    classements = []
    for p in extraites:
        c = classer_page(_pour_classement(p.texte), numero_dans_fichier=p.page.numero, corps_courriel=corps)
        if mime == MIME_XML:  # XML de format inconnu : jamais classé avec certitude sur ses balises
            c.confiance = min(c.confiance, 0.6)
            c.indices.append("xml_format_inconnu")
        classements.append(c)
    docs = decouper_pages(classements, pages, fichier=fichier, ids=ids)
    return ResultatIngestion(pages=pages, documents=docs, avertissements=avert, textes=textes,
                             classements=classements)


def _pour_classement(texte: PageText) -> PageText:
    """Page bornée à ``MAX_CARACTERES_CLASSEMENT`` pour le classement (D-1607) ; le texte complet reste celui de
    la page (extraction, preuves). Sans effet sur une page ordinaire."""
    lmax = MAX_CARACTERES_LIGNE_CLASSEMENT
    if (len(texte.texte) <= MAX_CARACTERES_CLASSEMENT and len(texte.lignes) <= MAX_LIGNES_CLASSEMENT
            and all(len(li.texte) <= lmax for li in texte.lignes)):
        return texte
    lignes = [li if len(li.texte) <= lmax else Ligne(texte=li.texte[:lmax], mots=li.mots[: lmax // 2])
              for li in texte.lignes[:MAX_LIGNES_CLASSEMENT]]
    return replace(texte, texte=texte.texte[:MAX_CARACTERES_CLASSEMENT], lignes=lignes,
                   avertissements=[*texte.avertissements, "classement_sur_extrait"])


class Decoupeur:
    """Composant « découpage et classement » du pipeline (étapes 2 et 3)."""

    version = VERSION_DECOUPAGE

    def __init__(self, options: OptionsPages | None = None,
                 fiches: Iterable[FicheCorrespondance] | None = None) -> None:
        if options is None:
            import os

            from controldone.storage.cles import mode_execution

            # Le cache disque garde le texte des pages EN CLAIR, indexé par empreinte (sans client) et hors de
            # la purge de conservation et de l'effacement RGPD : banc et développement seulement, jamais en
            # production (revue de sécurité RS-03).
            cache = os.environ.get("CONTROLDONE_PAGES_CACHE_DIR") if mode_execution() != "prod" else None
            options = OptionsPages(cache_dir=cache or None)
        self.options = options
        self.fiches = tuple(fiches) if fiches is not None else None

    def decouper(self, source: Any, *, ids: IdGenerator | None = None, client_id: str | None = None
                 ) -> ResultatIngestion:
        fichier: Fichier = source.fichier
        contenu = _contenu(source)
        textes = getattr(source, "textes_pages", None)
        if textes is not None:
            source.textes_pages = None  # consommé : libéré avec le résultat du fichier
        return decouper_fichier(fichier, contenu, ids=ids, options=self.options,
                                corps_courriel=bool(getattr(source, "corps_courriel", False)), fiches=self.fiches,
                                textes=textes)

    def precharger(self, sources: Sequence[Any], paralleles: int) -> None:
        """Étape 2 des fichiers d'un lot en parallèle (D-1405) : ``paralleles`` processus isolés à la fois, les plus
        gros fichiers d'abord. Le texte de chaque fichier est posé sur sa source (``textes_pages``) ; ``decouper``
        le consomme ensuite dans l'ordre habituel (identifiants et sortie inchangés). Sans effet hors processus
        isolé (rendu PDF et OCR ne sont pas sûrs entre fils d'un même processus) ou pour un seul fichier ; un
        échec laisse simplement ``decouper`` refaire le travail."""
        if paralleles <= 1 or not self.options.isoler:
            return
        taches = [(s, c) for s in sources if (c := _contenu(s)) is not None and getattr(s, "fichier", None)]
        if len(taches) < 2:
            return
        from concurrent.futures import ThreadPoolExecutor

        version_ocr()  # mise en cache avant les fils
        taches.sort(key=lambda t: -len(t[1]) * (t[0].fichier.nombre_pages or 1))

        def _textes(tache):
            s, contenu = tache
            try:
                return textes_pages(contenu, fichier=s.fichier, options=self.options)
            except Exception:
                return None

        with ThreadPoolExecutor(min(paralleles, len(taches)), thread_name_prefix="cdo-pages") as ex:
            for (s, _c), textes in zip(taches, ex.map(_textes, taches), strict=True):
                if textes is not None:
                    s.textes_pages = textes

    def liberer(self, pages: Iterable[Page]) -> None:
        """Fin de lot : textes positionnés des pages retirés du registre (``liberer_textes``)."""
        liberer_textes(pages)


def _contenu(source: Any) -> bytes | None:
    contenu = getattr(source, "contenu", None)
    if contenu is None and getattr(source, "chemin_local", None):
        contenu = Path(source.chemin_local).read_bytes()
    return contenu
