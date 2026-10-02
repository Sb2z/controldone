"""Doubles de test des composants d'ingestion et d'extraction (données fictives)."""

from __future__ import annotations

import io
from collections.abc import Callable, Sequence
from pathlib import Path

from controldone.extract.base import CoutExtraction, ExtractionContext, ExtractionResult
from controldone.ids import IdGenerator, Prefixe
from controldone.model import Document, ExtracteurInfo, Page, PageRef, QualiteTexte, TypeDocument, TypeExtracteur
from controldone.pipeline import FichierSource, ResultatDecoupage


def pdf_texte(lignes_par_page: Sequence[Sequence[str]]) -> bytes:
    """PDF réel minimal (ReportLab) : une liste de lignes par page."""
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4, invariant=1)
    for lignes in lignes_par_page:
        y = 800
        for li in lignes:
            c.drawString(60, y, li)
            y -= 18
        c.showPage()
    c.save()
    return buf.getvalue()


def ecrire_pdf(chemin: Path, *pages: Sequence[str]) -> Path:
    chemin.parent.mkdir(parents=True, exist_ok=True)
    chemin.write_bytes(pdf_texte(pages))
    return chemin


class DecoupeurDouble:
    """Classe chaque fichier d'après son nom : ``fc*``, ``dec*``, ``ft*``, ``av*`` ; sinon support.
    ``echec`` : noms de fichiers pour lesquels le découpage lève (robustesse)."""

    version = "double-1"

    def __init__(self, *, echec: Sequence[str] = (), inconnus: Sequence[str] = ()) -> None:
        self.echec = set(echec)
        self.inconnus = set(inconnus)

    def decouper(self, source: FichierSource, *, ids: IdGenerator, client_id: str | None) -> ResultatDecoupage:
        f = source.fichier
        if f.nom_original in self.echec:
            raise RuntimeError("lecture impossible")
        import pypdfium2 as pdfium

        doc_pdf = pdfium.PdfDocument(source.contenu)
        pages = []
        for i in range(len(doc_pdf)):
            texte = doc_pdf[i].get_textpage().get_text_range()
            pages.append(Page(id=ids.nouveau(Prefixe.page), fichier_id=f.id, numero=i + 1, texte=texte,
                              qualite_texte=QualiteTexte.natif))
        nom = f.nom_original
        type_ = TypeDocument.document_support
        for prefixe, t in (("fc", TypeDocument.facture_commerciale), ("dec", TypeDocument.declaration),
                           ("ft", TypeDocument.facture_transitaire), ("av", TypeDocument.avoir)):
            if nom.startswith(prefixe):
                type_ = t
        if nom in self.inconnus:
            type_ = TypeDocument.inconnu
        doc = Document(
            id=ids.nouveau(Prefixe.document), type=type_, confiance_classement=0.95 if type_ is not TypeDocument.inconnu
            else 0.4, pages=[PageRef(fichier_id=f.id, numero=p.numero, qualite_texte=p.qualite_texte) for p in pages],
        )
        return ResultatDecoupage(pages=pages, documents=[doc])


class ExtracteurDouble:
    """Extracteur déterministe de test : ``fabrique(document, pages) -> champs`` (ou ``None``)."""

    type = "deterministe"

    def __init__(self, fabrique: Callable[[Document, Sequence[Page]], object], *, id: str = "double",
                 version: str = "0.1", echec_types: Sequence[TypeDocument] = (), cout: str = "0") -> None:
        self.fabrique = fabrique
        self.id = id
        self.version = version
        self.echec_types = set(echec_types)
        self.appels = 0
        self.cout = cout

    def supports(self, document: Document, pages: Sequence[Page]) -> bool:
        return document.type is not TypeDocument.inconnu

    def extract(self, document: Document, pages: Sequence[Page], context: ExtractionContext) -> ExtractionResult:
        self.appels += 1
        if document.type in self.echec_types:
            raise ValueError("extracteur en panne")
        from decimal import Decimal

        champs = self.fabrique(document, pages)
        return ExtractionResult(
            extracteur=ExtracteurInfo(type=TypeExtracteur.deterministe, id=self.id, version=self.version),
            champs=champs, cout=CoutExtraction(cout_eur=Decimal(self.cout)),
        )
