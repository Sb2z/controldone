"""Extracteur déterministe des avoirs (SPEC §5.3.4).

Deux familles d'avoirs :

- **avoir de transitaire** (le cas courant) : mêmes lignes et même énumération ``nature`` que la facture
  transitaire. La lecture est déléguée au moteur de la facture transitaire
  (``facture_transitaire.ExtracteurFactureTransitaire``, qui sait produire des ``ChampsAvoir`` : lignes et
  nature, totaux crédités, facture(s) d'origine, MRN, motif) ;
- **avoir fournisseur** (« credit note » d'un vendeur de marchandises, présenté comme une facture) : tableau
  d'articles (quantité, prix, montant) lu par le moteur de la facture commerciale, puis converti en
  ``ChampsAvoir`` (lignes ``autre_prestation`` : l'énumération ``nature`` ne connaît que des prestations
  de transitaire), numéro d'avoir lu sur ses propres libellés, facture(s) d'origine citées.

Règles communes (§5.2, §5.3.4) : montants **positifs** (un montant imprimé négatif ou entre parenthèses
garde ``signe_imprime = negatif``) ; le ``motif`` est stocké comme une donnée, jamais interprété ; un avoir
sans référence garde ``refs_facture_origine`` vide.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from controldone.extract.base import ExtractionContext, ExtractionResult
from controldone.extract.deterministe._mise_en_page import (
    Fabrique,
    Lecture,
    VueDocument,
    accepte_reference,
    chercher,
    confiance_mots,
    motifs,
    pages_du_document,
    reconnaitre_entete,
    valeur_apres,
    vue_document,
)
from controldone.extract.deterministe.facture_commerciale import (
    LIB_DATE,
    VOCAB_COLONNES,
    extraire_facture_commerciale,
)
from controldone.model.champs import ChampsAvoir, ChampsFactureCommerciale, LigneFactureTransitaire
from controldone.model.documents import Document, Page
from controldone.model.enums import NatureLigne, TypeDocument, TypeValeur
from controldone.model.valeur import ExtracteurInfo, ValeurSourcee
from controldone.normalize.refs import norm_alnum

__all__ = ["ExtracteurAvoir", "est_avoir_fournisseur"]

VERSION = "1.0.0"
INFO = ExtracteurInfo(type="deterministe", id="avoir_regles", version=VERSION)

_NO = r"(?:no\b\.?|n\.?\s?[°o2]\.?|nr\.?|nro\.?|num(?:ero|ber)?\.?|#)"
LIB_NUMERO_AVOIR = motifs(
    rf"(?:credit\s*(?:note|memo)|avoir|nota\s*de\s*credito|abono|factura\s*rectificativa)\s*{_NO}\s*:?",
    rf"(?:{_NO}|numero)\s*(?:de\s*l'|d'|del?\s*)?(?:avoir|nota\s*de\s*credito|credit\s*note|abono)\s*:?",
)
LIB_ORIGINE = motifs(
    rf"(?:original|related|credited|corrected)\s*invoice(?:\s*{_NO})?\s*:?",
    rf"(?:against|re|ref(?:erence)?\.?)\s*(?:to\s*)?invoice(?:\s*{_NO})?\s*:?",
    rf"invoice\s*(?:{_NO}|ref(?:erence)?\.?)\s*:?",
    rf"facture\s*(?:d'origine|origine|initiale|concernee|creditee|{_NO})\s*:?",
    rf"factura\s*(?:original|rectificada|de\s*origen|{_NO})\s*:?",
    r"(?:ref\.?|referencia)\s*(?:de\s*la\s*)?(?:facture|factura)\s*:?",
)
LIB_MOTIF = motifs(r"(?:reason|motif|motivo|objet|raison)\s*(?:/\s*reason)?\s*:?")


_MRN = re.compile(r"(?<![A-Z0-9])\d{2}[A-Z]{2}[A-Z0-9]{14}(?![A-Z0-9])")


def _signes_transitaire(vue: VueDocument) -> bool:
    """Un MRN cité, ou une ligne dont le libellé est une prestation ou un débours de transitaire (§5.3.3) :
    l'avoir est celui d'un transitaire, même si son tableau a l'allure d'un tableau d'articles."""
    from controldone.normalize.natures import nature_libelle

    for li in vue.lignes():
        if _MRN.search(li.texte):
            return True
        if any(nature_libelle(s.texte) is not None for s in li.segments if len(s.texte) <= 60):
            return True
    return False


def est_avoir_fournisseur(vue: VueDocument) -> bool:
    """Vrai si le document porte un tableau d'articles de marchandises (quantité, prix ou montant, et
    description ou code), signe d'un avoir de vendeur plutôt que d'un avoir de transitaire — sauf si le
    document porte les signes d'un avoir de transitaire (MRN, libellés de prestations ou de débours)."""
    if _signes_transitaire(vue):
        return False
    for li in vue.lignes():
        cols = reconnaitre_entete(li, VOCAB_COLONNES)
        if not cols:
            continue
        types = {c.type for c in cols}
        if "quantite" in types and ({"prix_unitaire", "montant"} & types) and ({"description", "code"} & types):
            return True
    return False


class ExtracteurAvoir:
    """Extracteur ``deterministe`` des avoirs (transitaire ou fournisseur)."""

    id = INFO.id
    version = VERSION
    type = "deterministe"

    def supports(self, document: Document, pages: Sequence[Page]) -> bool:
        t = getattr(document.type, "value", document.type)
        return t == TypeDocument.avoir.value and any((getattr(p, "texte", "") or "").strip() for p in pages)

    def extract(self, document: Document, pages: Sequence[Page], context: ExtractionContext) -> ExtractionResult:
        choisies = pages_du_document(document, pages, context.options)
        vue = vue_document(choisies, separateur_decimal=context.separateur_decimal)
        if est_avoir_fournisseur(vue):
            champs = extraire_avoir_fournisseur(vue, document_id=document.id, ids=context.ids)
            return ExtractionResult(extracteur=INFO, champs=champs, avertissements=["avoir_fournisseur"])
        try:
            from controldone.extract.deterministe.facture_transitaire import ExtracteurFactureTransitaire
        except Exception:  # moteur transitaire indisponible : lecture « fournisseur » en repli
            champs = extraire_avoir_fournisseur(vue, document_id=document.id, ids=context.ids)
            return ExtractionResult(extracteur=INFO, champs=champs, partielle=True,
                                    avertissements=["moteur_transitaire_indisponible"])
        moteur = ExtracteurFactureTransitaire()
        r = moteur.extract(document, pages, context)
        info = ExtracteurInfo(type="deterministe", id=INFO.id, version=f"{VERSION}+{moteur.id}-{moteur.version}")
        return r.model_copy(update={"extracteur": info})


# --- avoir fournisseur ---------------------------------------------------------------------------------------


def _requalifier(v: ValeurSourcee | None, rel: str) -> ValeurSourcee | None:
    """Valeur lue par le moteur facture commerciale, rattachée au chemin de l'avoir."""
    if v is None:
        return None
    return v.model_copy(update={"chemin": f"avoir.{rel}"})


def extraire_avoir_fournisseur(vue: VueDocument, *, document_id: str, ids=None) -> ChampsAvoir:
    fc, _ = extraire_facture_commerciale(vue, document_id=document_id, ids=ids)
    return convertir_fc_en_avoir(fc, vue, document_id=document_id, ids=ids)


def convertir_fc_en_avoir(fc: ChampsFactureCommerciale, vue: VueDocument, *, document_id: str,
                          ids=None) -> ChampsAvoir:
    fab = Fabrique(TypeDocument.avoir, document_id, INFO, vue, ids)
    av = ChampsAvoir()
    # numéro de l'avoir : libellés propres ; à défaut, le numéro « facture » imprimé (avoir présenté comme
    # une facture), confiance réduite
    lec = _premier(vue, LIB_NUMERO_AVOIR, accepte_reference)
    if lec is not None:
        av.numero = fab.valeur("numero", lec, confiance=_conf_ref(lec))
    elif fc.numero is not None:
        av.numero = _requalifier(fc.numero, "numero").model_copy(  # type: ignore[union-attr]
            update={"confiance": min(fc.numero.confiance, 0.8)})
    lec_d = _premier(vue, LIB_DATE, _accepte_date)
    if lec_d is not None:
        av.date = fab.valeur("date", lec_d)
    elif fc.date is not None:
        av.date = _requalifier(fc.date, "date")
    av.devise = _requalifier(fc.devise, "devise")
    av.emetteur.nom = _requalifier(fc.vendeur.nom, "emetteur.nom")
    av.emetteur.tva = _requalifier(fc.vendeur.tva, "emetteur.tva")
    # facture(s) d'origine
    vus: set[str] = set()
    numero_avoir = norm_alnum(av.numero.valeur_brute) if av.numero else ""
    for t in chercher(vue, LIB_ORIGINE):
        lec = valeur_apres(vue, t, accepte_reference, dessous=False)
        if lec is None:
            continue
        cle = norm_alnum(lec.texte)
        if cle in vus or cle == numero_avoir:
            continue
        vus.add(cle)
        v = fab.valeur(f"refs_facture_origine[{len(av.refs_facture_origine)}]", lec, confiance=_conf_ref(lec),
                       type_valeur=TypeValeur.reference)
        if v is not None:
            av.refs_facture_origine.append(v)
    # lignes
    for k, ln in enumerate(fc.lignes):
        lg = LigneFactureTransitaire(nature=NatureLigne.autre_prestation)
        lg.libelle = _requalifier(ln.description, f"lignes[{k}].libelle")
        lg.quantite = _requalifier(ln.quantite, f"lignes[{k}].quantite")
        lg.prix_unitaire = _requalifier(ln.prix_unitaire, f"lignes[{k}].prix_unitaire")
        lg.montant_ht = _requalifier(ln.montant_ligne, f"lignes[{k}].montant_ht")
        av.lignes.append(lg)
    # totaux : total général -> total crédité TTC (une facture de marchandises à l'export est hors TVA :
    # le total HT n'est renseigné que s'il est imprimé distinctement)
    if fc.total_facture is not None:
        av.total_credite_ttc = _requalifier(fc.total_facture, "total_credite_ttc")
    for st in fc.sous_totaux:
        if st.type.value == "marchandises" and st.montant is not None and av.total_credite_ht is None:
            av.total_credite_ht = _requalifier(st.montant, "total_credite_ht")
    lec_m = _premier(vue, LIB_MOTIF, _accepte_motif)
    if lec_m is not None:
        av.motif = fab.valeur("motif", lec_m, type_valeur=TypeValeur.texte)
    return av


def _premier(vue: VueDocument, libs, accepte) -> Lecture | None:
    for t in chercher(vue, libs):
        lec = valeur_apres(vue, t, accepte, dessous=False)
        if lec is not None:
            return lec
    return None


def _conf_ref(lec: Lecture) -> float:
    if lec.methode.value != "ocr":
        return 0.95
    c = confiance_mots(lec, plafond_ocr=0.85)
    return min(c, 0.8) if re.search(r"[A-Za-z]", lec.texte) and re.search(r"\d", lec.texte) else c


def _accepte_date(mots):
    from controldone.normalize import parse_date_detail

    for j in range(min(len(mots), 5), 0, -1):
        txt = " ".join(m.texte for m in mots[:j])
        if re.search(r"\d", txt) and parse_date_detail(txt) is not None:
            while j > 1 and parse_date_detail(" ".join(m.texte for m in mots[:j - 1])) is not None:
                j -= 1
            return 0, j
    return None


def _accepte_motif(mots):
    return (0, len(mots)) if mots and re.search(r"[A-Za-z]{3}", " ".join(m.texte for m in mots)) else None
