"""Composants de **démonstration** (doubles) utilisés quand les équipes ingestion / extraction n'ont pas
encore publié le composant correspondant.

- ``ExtracteurDemo`` : reconnaît un document du jeu fictif par son numéro imprimé (texte de la page) et
  construit ses valeurs sourcées à partir de la description qui a servi à dessiner le PDF. Chaque valeur
  passe par ``valeur_sourcee`` (normalisation et **ancrage** sur le texte réel de la page) : rien n'est
  inventé, une valeur absente du texte n'est pas ancrée.
- ``DecoupeurDemo`` : une page = un document, type reconnu par le titre imprimé du jeu fictif.

Ces doubles ne servent qu'à la commande ``controldone demo`` ; ils ne reconnaissent que les documents
fictifs de ``controldone.demo.donnees``.
"""

from __future__ import annotations

from collections.abc import Sequence

from controldone.demo.donnees import dossiers_demo
from controldone.demo.modele import DocDemo
from controldone.extract.base import ExtractionContext, ExtractionResult
from controldone.extract.valeurs import valeur_sourcee
from controldone.ids import IdGenerator, Prefixe
from controldone.model.champs import (
    DocumentReference,
    IndiceAutoliquidation,
    classe_champs,
    type_valeur_pour,
)
from controldone.model.documents import Document, Page, PageRef
from controldone.model.enums import Methode, QualiteTexte, TypeDocument, TypeExtracteur
from controldone.model.valeur import ExtracteurInfo, Zone

__all__ = ["DecoupeurDemo", "ExtracteurDemo"]

CONFIANCE = 0.97


def _docs() -> list[DocDemo]:
    return [d for dossier in dossiers_demo() for d in dossier.documents]


class ExtracteurDemo:
    id = "demo_jeu_fictif"
    version = "1.0.0"
    type = "deterministe"

    def __init__(self) -> None:
        self._docs = _docs()
        self._zones: dict[str, dict] = {}

    def _zones_de(self, demo: DocDemo) -> dict:
        """Zones des valeurs, relevées en redessinant le document en mémoire (mise en page déterministe)."""
        if demo.cle not in self._zones:
            from controldone.demo.generateur import dessiner_document

            self._zones[demo.cle] = dessiner_document(demo)
        return self._zones[demo.cle]

    def _trouver(self, document: Document, pages: Sequence[Page]) -> DocDemo | None:
        texte = " ".join(p.texte for p in pages)
        if "DONNÉES FICTIVES" not in texte and "DONNEES FICTIVES" not in texte:
            return None
        for d in self._docs:
            if d.type is document.type and d.cle in texte:
                return d
        return None

    def supports(self, document: Document, pages: Sequence[Page]) -> bool:
        return self._trouver(document, pages) is not None

    def extract(self, document: Document, pages: Sequence[Page], context: ExtractionContext) -> ExtractionResult:
        info = ExtracteurInfo(type=TypeExtracteur.deterministe, id=self.id, version=self.version)
        demo = self._trouver(document, pages)
        cls = classe_champs(document.type)
        if demo is None or cls is None:
            return ExtractionResult(extracteur=info, champs=None, avertissements=["document_hors_demo"])
        textes = {p.numero: p.texte for p in pages}
        page = pages[0].numero if pages else 1
        champs = cls()
        devise = next((c.brut for c in demo.entete if c.chemin in ("devise", "devise_facture")), None)
        sep = "," if demo.langue == "fr" else "."
        zones = self._zones_de(demo)

        def vs(chemin: str, brut: str):
            z = zones.get(chemin)
            return valeur_sourcee(
                type_document=document.type, chemin=chemin, brut=brut, document_id=document.id, page=page,
                extracteur=info, methode=Methode.texte_natif, confiance=CONFIANCE, textes_pages=textes,
                zone=Zone(x0=z[0], y0=z[1], x1=z[2], y1=z[3]) if z else None,
                type_valeur=type_valeur_pour(chemin), separateur_decimal=sep, devise=devise,
                id_valeur=context.ids.nouveau(Prefixe.valeur),
            )

        for ch in [*demo.emetteur_champs, *demo.destinataire, *demo.entete, *demo.totaux]:
            if ch.chemin is None:
                continue
            v = vs(ch.chemin, ch.brut)
            if ch.valeur is not None:
                v = v.model_copy(update={"valeur": ch.valeur})
            champs.definir(ch.chemin, v)
        for t in demo.tableaux:
            for i, ligne in enumerate(t.lignes):
                if t.liste == "documents_references":
                    champs.documents_references.append(DocumentReference(
                        type_code=vs(f"documents_references[{i}].type_code", ligne["type_code"]),
                        reference=vs(f"documents_references[{i}].reference", ligne["reference"]),
                    ))
                    continue
                for feuille, brut in ligne.items():
                    champs.definir(f"{t.liste}[{i}].{feuille}", vs(f"{t.liste}[{i}].{feuille}", brut))
                for feuille, enum in (t.enums[i] if i < len(t.enums) else {}).items():
                    champs.definir(f"{t.liste}[{i}].{feuille}", enum)
        for liste, objets in demo.objets.items():
            if liste == "indices_autoliquidation":
                for i, o in enumerate(objets):
                    champs.indices_autoliquidation.append(IndiceAutoliquidation(
                        type=o["type"], valeur=vs(f"indices_autoliquidation[{i}].valeur", o["valeur"]),
                        tva=vs(f"indices_autoliquidation[{i}].tva", o["tva"]) if o.get("tva") else None,
                    ))
        if document.type is TypeDocument.facture_transitaire and champs.refs_mrn:
            # débours d'une facture mono-MRN : rattachés au MRN imprimé en en-tête (valeur ancrée sur la page)
            brut_mrn = champs.refs_mrn[0].valeur_brute or ""
            for i, li in enumerate(champs.lignes):
                if li.nature.est_debours and li.mrn is None:
                    champs.definir(f"lignes[{i}].mrn", vs(f"lignes[{i}].mrn", brut_mrn))
        return ExtractionResult(extracteur=info, champs=champs)


class DecoupeurDemo:
    """Une page = un document ; type reconnu par le titre imprimé du jeu fictif."""

    version = "demo-1.0.0"

    def decouper(self, source, *, ids: IdGenerator, client_id: str | None = None):
        import pypdfium2 as pdfium

        from controldone.pipeline import ResultatDecoupage

        f = source.fichier
        pdf = pdfium.PdfDocument(source.contenu)
        try:
            pages = [Page(id=ids.nouveau(Prefixe.page), client_id=client_id, fichier_id=f.id, numero=i + 1,
                          texte=pdf[i].get_textpage().get_text_range(), qualite_texte=QualiteTexte.natif)
                     for i in range(len(pdf))]
        finally:
            pdf.close()
        texte = " ".join(p.texte for p in pages)
        type_ = TypeDocument.inconnu
        for d in _docs():
            if d.cle in texte and d.titre in texte:
                type_ = d.type
        doc = Document(
            id=ids.nouveau(Prefixe.document), client_id=client_id, type=type_,
            confiance_classement=0.98 if type_ is not TypeDocument.inconnu else 0.3,
            pages=[PageRef(fichier_id=f.id, numero=p.numero, qualite_texte=p.qualite_texte) for p in pages],
            identite=f.sha256,
        )
        return ResultatDecoupage(pages=pages, documents=[doc])
