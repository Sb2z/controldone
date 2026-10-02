"""Extracteur déterministe des documents support (SPEC §5.3.5).

Sous-types : ``titre_transport`` (LTA, connaissement, CMR), ``liste_colisage``, ``pre_alerte``,
``certificat``, ``preuve_paiement``, ``autre`` — et ``lettre_accompagnement``, ``conditions_generales``,
``courriel`` dont on ne lit que les références de facture citées.

Champs : ``ref_transport_maitre`` / ``ref_transport_maison`` (LTA mère / maison ; une référence sans
précision est rangée en « maître »), ``expediteur``, ``destinataire`` (nom, TVA du pavé), ``nombre_colis``,
``masse_brute``, ``masse_taxable``, ``masse_nette``, ``refs_facture[]``.

Lecture : libellés multilingues (fr/en/es) suivis de leur valeur (même segment, à droite, ou dessous) et
tableaux « ligne d'en-tête + ligne de valeurs » (n° LTA | colis | poids brut | poids taxable | date) lus par
colonnes. Ces documents ne portent jamais de valeur marchande : aucun montant n'est lu (§5.3.5).
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from controldone.extract.base import ExtractionContext, ExtractionResult
from controldone.extract.deterministe._mise_en_page import (
    Fabrique,
    Lecture,
    VueDocument,
    VueLigne,
    accepte_entier,
    accepte_masse,
    attribuer,
    chercher,
    confiance_mots,
    lecture_mots,
    lire_tva_mots,
    motifs,
    nombres_dans,
    pages_du_document,
    pave,
    reconnaitre_entete,
    separateur_masse,
    texte_nombre,
    valeur_apres,
    vue_document,
)
from controldone.ingest.texte import Mot
from controldone.model.champs import ChampsSupport
from controldone.model.documents import Document, Page
from controldone.model.enums import Methode, TypeDocument, TypeValeur
from controldone.model.valeur import ExtracteurInfo
from controldone.normalize import parse_weight_kg, tva_fr_valide

__all__ = ["ExtracteurSupport", "extraire_support"]

VERSION = "1.0.0"
INFO = ExtracteurInfo(type="deterministe", id="support_regles", version=VERSION)

#: Sous-types sans masses ni colis (pièces jointes textuelles) : seules les références de facture sont lues.
SOUS_TYPES_TEXTUELS = frozenset({"lettre_accompagnement", "conditions_generales", "courriel"})

_NO = r"(?:no\b\.?|n\.?\s?[°o]\.?|nr\.?|number|num(?:ero)?\.?|#)"
_REF = r"(?:b/?l|bill of lading|awb|air ?waybill|lta|connaissement|conocimiento|guia aerea|cmr|waybill|bol)"
LIB_MAISON = motifs(
    rf"(?:house\s*{_REF}|h(?:awb|bl|b/l)|{_REF}\s*(?:maison|house|hija)|lta\s*maison)\s*{_NO}?\s*:?",
)
LIB_MAITRE = motifs(
    rf"(?:master\s*{_REF}|m(?:awb|bl|b/l)|{_REF}\s*(?:mere|master|madre)|lta\s*mere)\s*{_NO}?\s*:?",
)
LIB_TRANSPORT = motifs(rf"{_REF}(?:\s*/\s*{_REF})*\s*{_NO}?\s*:?", r"(?:tracking|shipment|expedition)\s*" + _NO + r"\s*:?")
_TITRE_TRANSPORT = re.compile(
    r"^(?:air\s*waybill|bill of lading|sea\s*waybill|lettre de transport|lta\b|connaissement|conocimiento|"
    r"guia aerea|cmr\b|lettre de voiture|house air waybill|master air waybill)"
)
LIB_EXPEDITEUR = motifs(r"(?:shipper|expediteur|exportateur|exporter|remitente|cargador|sender)\b\s*:?")
LIB_DESTINATAIRE = motifs(r"(?:consignee|destinataire|consignatario|destinatario|receiver)\b\s*:?")
LIB_FIN_PAVE = motifs(
    r"(?:shipper|consignee|notify|expediteur|destinataire|issuing|carrier|routing|agent|remitente|consignatario)\b"
)
LIB_COLIS = motifs(
    r"(?:total\s*)?(?:number|no\.?|nbr|nb)\s*of\s*(?:packages|pkgs|pieces|cartons|parcels)\s*:?",
    r"(?:total\s*)?(?:packages|pkgs|pieces|colis|cartons)\s*:", r"total\s*(?:packages|pkgs|pieces|colis)\s*:?",
    r"(?:nombre|nb|nbre)\s*(?:total\s*)?(?:de\s*)?colis\s*:?", r"(?:numero|n\.?o|cantidad|total)\s*(?:de\s*)?bultos\s*:?",
    r"bultos\s*:",
)
LIB_BRUT = motifs(
    r"(?:total\s*)?gross\s*(?:weight|wt)\.?(?:\s*\(?kgs?\)?)?\s*:?", r"(?:total\s*)?poids\s*brut(?:\s*total)?\s*:?",
    r"(?:total\s*)?peso\s*bruto(?:\s*total)?\s*:?",
)
LIB_NET = motifs(
    r"(?:total\s*)?net\s*(?:weight|wt)\.?(?:\s*\(?kgs?\)?)?\s*:?", r"(?:total\s*)?poids\s*net(?:\s*total)?\s*:?",
    r"(?:total\s*)?peso\s*neto(?:\s*total)?\s*:?",
)
LIB_TAXABLE = motifs(
    r"(?:total\s*)?(?:chargeable|taxable)\s*(?:weight|wt)\.?(?:\s*\(?kgs?\)?)?\s*:?",
    r"(?:total\s*)?poids\s*taxable\s*:?", r"(?:total\s*)?peso\s*(?:tasable|facturable)\s*:?",
)
LIB_FACTURE = motifs(
    rf"(?:commercial\s*|supplier\s*)?invoice\s*(?:{_NO}|ref(?:erence)?\.?)\s*:?",
    rf"(?:notre\s*|votre\s*)?facture(?:\s*(?:commerciale|fournisseur))?\s*(?:{_NO}|ref\.?)\s*:?",
    rf"factura(?:\s*comercial)?\s*{_NO}\s*:?",
    r"ref(?:erence)?\.?\s*(?:facture|invoice|factura)?\s*:",
    r"ref\.\s*",
)
VOCAB_TABLEAU: dict[str, list[str]] = {
    "ref": ["b/l no", "b/l", "awb no", "awb", "lta", "lta no", "n° lta", "bl no", "awb/bl", "hawb", "mawb",
            "connaissement", "conocimiento", "guia", "cmr", "waybill no", "air waybill no", "bill of lading no"],
    "colis": ["pieces", "pcs", "packages", "pkgs", "colis", "nb colis", "no. of pieces", "bultos", "number of packages",
              "cartons", "qty pkgs"],
    "masse_brute": ["gross weight (kg)", "gross weight", "gross wt", "gross kg", "poids brut (kg)", "poids brut",
                    "peso bruto", "peso bruto (kg)", "g.w", "g.w. (kg)", "gross weight kg"],
    "masse_taxable": ["chargeable weight (kg)", "chargeable weight", "chargeable wt", "poids taxable (kg)",
                      "poids taxable", "peso tasable", "taxable weight", "chargeable kg"],
    "masse_nette": ["net weight (kg)", "net weight", "net kg", "poids net", "peso neto", "n.w"],
    "date": ["date", "fecha", "date of issue"],
}


class ExtracteurSupport:
    """Extracteur ``deterministe`` des documents support (titres de transport, listes de colisage…)."""

    id = INFO.id
    version = VERSION
    type = "deterministe"

    def supports(self, document: Document, pages: Sequence[Page]) -> bool:
        t = getattr(document.type, "value", document.type)
        return t == TypeDocument.document_support.value and any((getattr(p, "texte", "") or "").strip()
                                                                  for p in pages)

    def extract(self, document: Document, pages: Sequence[Page], context: ExtractionContext) -> ExtractionResult:
        choisies = pages_du_document(document, pages, context.options)
        vue = vue_document(choisies, separateur_decimal=context.separateur_decimal)
        champs = extraire_support(vue, document_id=document.id, sous_type=document.sous_type, ids=context.ids)
        return ExtractionResult(extracteur=INFO, champs=champs)


def _accepte_ref(mots: Sequence[Mot]) -> tuple[int, int] | None:
    """Référence de transport : un mot (« 999-12345675 », « DEMO123456789 ») ou des groupes de chiffres
    séparés par des espaces (« 999 1234 5675 »)."""
    for k, m in enumerate(mots[:3]):
        t = m.texte.strip(":;,|")
        if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9\-/.]{5,}", t) and len(re.sub(r"\D", "", t)) >= 5:
            j = k + 1
            while j < len(mots) and re.fullmatch(r"\d{3,5}", mots[j].texte) and len(re.sub(r"\D", "", t)) < 11:
                t += mots[j].texte
                j += 1
            return k, j
    return None


def _conf_ref(lec: Lecture) -> float:
    if lec.methode is not Methode.ocr:
        return 0.95
    c = confiance_mots(lec, plafond_ocr=0.85)
    if re.search(r"[A-Za-z]", lec.texte) and re.search(r"\d", lec.texte):
        c = min(c, 0.8)
    return c


def extraire_support(vue: VueDocument, *, document_id: str, sous_type: str | None = None, ids=None) -> ChampsSupport:
    fab = Fabrique(TypeDocument.document_support, document_id, INFO, vue, ids)
    ch = ChampsSupport()
    textuel = sous_type in SOUS_TYPES_TEXTUELS
    _refs_facture(vue, fab, ch)
    if textuel:
        return ch
    # références de transport : libellés explicites maison / maître
    for chemin, libs in (("ref_transport_maison", LIB_MAISON), ("ref_transport_maitre", LIB_MAITRE)):
        for t in chercher(vue, libs):
            lec = valeur_apres(vue, t, _accepte_ref)
            if lec is not None:
                setattr(ch, chemin, fab.valeur(chemin, lec, confiance=_conf_ref(lec)))
                break
    tab = _tableau(vue)
    if ch.ref_transport_maitre is None:
        # référence sans précision (titre, tableau, libellé « AWB / B/L No. ») : rangée en « maître »,
        # sauf si c'est la référence maison déjà lue
        maison = re.sub(r"[^A-Z0-9]", "", (ch.ref_transport_maison.valeur_brute or "").upper()) \
            if ch.ref_transport_maison else None
        candidats = [tab.get("ref"), _ref_titre(vue)]
        for t in chercher(vue, LIB_TRANSPORT):
            candidats.append(valeur_apres(vue, t, _accepte_ref))
        for lec in candidats:
            if lec is not None and re.sub(r"[^A-Z0-9]", "", lec.texte.upper()) != maison:
                ch.ref_transport_maitre = fab.valeur("ref_transport_maitre", lec, confiance=_conf_ref(lec))
                break
    # masses et colis : tableau d'en-tête, sinon libellés
    for chemin, libs, acc in (("nombre_colis", LIB_COLIS, accepte_entier), ("masse_brute", LIB_BRUT, None),
                              ("masse_taxable", LIB_TAXABLE, None), ("masse_nette", LIB_NET, None)):
        lec = tab.get(chemin)
        if lec is None:
            lec = _premier(vue, libs, acc or accepte_masse(vue))
        if lec is None:
            continue
        if chemin == "nombre_colis":
            setattr(ch, chemin, fab.valeur(chemin, lec, type_valeur=TypeValeur.entier))
            continue
        sep, presume = separateur_masse(vue, lec.texte)
        if parse_weight_kg(texte_nombre(lec.texte), separateur_decimal=sep) is None:
            continue
        conf = confiance_mots(lec)
        if presume:
            conf = min(conf, 0.7)
        if lec.methode is Methode.ocr and re.search(r"\d{7,}", lec.texte):
            conf = min(conf, 0.4)  # séparateurs perdus par l'OCR (« 2739523277 »)
        setattr(ch, chemin, fab.valeur(chemin, lec, type_valeur=TypeValeur.masse, separateur=sep, confiance=conf))
    _recouper_masses(ch)
    _parties(vue, fab, ch)
    return ch


def _recouper_masses(ch: ChampsSupport) -> None:
    """Poids brut et poids taxable lus tous deux : un rapport aberrant (≥ 10) trahit un séparateur mal lu."""
    b, t = ch.masse_brute, ch.masse_taxable
    if b is None or t is None or not b.valeur or not t.valeur:
        return
    from decimal import Decimal

    vb, vt = Decimal(b.valeur), Decimal(t.valeur)
    if vb > 0 and vt > 0 and (vb / vt >= 10 or vt / vb >= 10):
        ch.masse_brute = b.model_copy(update={"confiance": min(b.confiance, 0.4)})
        ch.masse_taxable = t.model_copy(update={"confiance": min(t.confiance, 0.4)})


def _premier(vue: VueDocument, libs, acc) -> Lecture | None:
    for t in chercher(vue, libs):
        lec = valeur_apres(vue, t, acc, lignes_dessous=1)
        if lec is not None:
            return lec
    return None


def _ref_titre(vue: VueDocument) -> Lecture | None:
    """Référence imprimée sur la ligne de titre d'un titre de transport (« AIR WAYBILL … 999-12345675 »)."""
    for p in vue.pages[:1]:
        for li in p.lignes[:6]:
            if not _TITRE_TRANSPORT.match(li.cle):
                continue
            for s in li.segments:
                r = _accepte_ref(s.mots[-1:])
                if r is not None:
                    return lecture_mots(s.mots[-1:], p, li)
    return None


def _nettoyer(mots: Sequence[Mot]) -> list[Mot]:
    """Retire les filets de tableau lus par l'OCR (« | », « 1,840| »)."""
    out = []
    for m in mots:
        t = m.texte.strip("|")
        if not t:
            continue
        out.append(m if t == m.texte else Mot(t, m.x0, m.y0, m.x1, m.y1, m.confiance, m.taille))
    return out


def _tableau(vue: VueDocument) -> dict[str, Lecture]:
    """Tableau « en-tête / valeurs » : ligne d'en-tête reconnue, valeurs sur la ligne suivante."""
    out: dict[str, Lecture] = {}
    for p in vue.pages:
        for k, li in enumerate(p.lignes[:-1]):
            li_net = VueLigne(li.page, li.rang, li.segments, li.ligne)
            cols = reconnaitre_entete(li_net, VOCAB_TABLEAU, min_colonnes=2)
            if not cols:
                continue
            types = {c.type for c in cols}
            # tableau « une ligne de valeurs » d'un titre de transport (n° | colis | poids | date) ; le
            # tableau des articles d'une liste de colisage (poids par ligne) n'en est pas un
            if not ({"colis", "masse_taxable", "ref"} & types) or not ({"colis", "masse_brute", "masse_taxable"} & types):
                continue
            suivante = p.lignes[k + 1]
            mots = _nettoyer(suivante.mots)
            # le texte brut retenu doit rester littéralement sur la page : on garde les mots d'origine
            # dont le texte n'a pas été retouché
            cellules = attribuer(mots, cols, tableur=p.tableur)
            for typ, ms in cellules.items():
                if typ in out or not ms:
                    continue
                if typ == "ref":
                    r = _accepte_ref(ms)
                    if r is not None:
                        out["ref"] = lecture_mots(ms[r[0]:r[1]], p, suivante)
                elif typ == "colis":
                    nb = nombres_dans(ms)
                    if nb and re.fullmatch(r"\d{1,6}", nb[0].texte.replace(",", "").replace(" ", "")):
                        out["nombre_colis"] = lecture_mots(ms[nb[0].i:nb[0].j], p, suivante)
                elif typ in ("masse_brute", "masse_taxable", "masse_nette"):
                    nb = [n for n in nombres_dans(ms) if not n.tronque]
                    if nb:
                        out[typ] = lecture_mots(ms[nb[0].i:nb[0].j], p, suivante)
            if out:
                return out
    return out


def _refs_facture(vue: VueDocument, fab: Fabrique, ch: ChampsSupport) -> None:
    vus: set[str] = set()
    for t in chercher(vue, LIB_FACTURE, debut_segment=False):
        lec = valeur_apres(vue, t, _accepte_ref_facture, dessous=False)
        if lec is None:
            continue
        # ponctuation de fin de phrase (« facture n° FAC-1. ») : hors de la référence, qui reste une
        # sous-chaîne littérale de la page
        lec.texte_force = lec.texte.strip(":;,.()")
        cle = re.sub(r"[^A-Z0-9]", "", lec.texte.upper())
        if cle in vus:
            continue
        vus.add(cle)
        k = len(ch.refs_facture)
        v = fab.valeur(f"refs_facture[{k}]", lec, confiance=_conf_ref(lec), type_valeur=TypeValeur.reference)
        if v is not None:
            ch.refs_facture.append(v)


def _accepte_ref_facture(mots: Sequence[Mot]) -> tuple[int, int] | None:
    for k, m in enumerate(mots[:2]):
        t = m.texte.strip(":;,.()")
        if len(t) >= 4 and re.search(r"\d", t) and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9/\-_.]*", t):
            return k, k + 1
    return None


def _parties(vue: VueDocument, fab: Fabrique, ch: ChampsSupport) -> None:
    for partie, libs in (("expediteur", LIB_EXPEDITEUR), ("destinataire", LIB_DESTINATAIRE)):
        for t in chercher(vue, libs, pages=[vue.pages[0].numero] if vue.pages else None):
            lignes = pave(t, fin=LIB_FIN_PAVE, max_lignes=6)
            if not lignes:
                continue
            li0, mots0 = lignes[0]
            p0 = vue.page(li0.page)
            nom = fab.valeur(f"{partie}.nom", lecture_mots(mots0, p0, li0), type_valeur=TypeValeur.texte)
            getattr(ch, partie).nom = nom
            for li, ms in lignes:
                r = lire_tva_mots(ms)
                if r is not None:
                    lec = lecture_mots(ms[r[0]:r[1]], vue.page(li.page), li)
                    conf = confiance_mots(lec)
                    if r[2].startswith("FR") and not tva_fr_valide(r[2]):
                        conf = min(conf, 0.5)
                    getattr(ch, partie).tva = fab.valeur(f"{partie}.tva", lec, confiance=conf)
                    break
            break

