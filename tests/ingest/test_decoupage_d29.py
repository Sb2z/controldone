"""Découpage (D-2901) et feuille « deux pages » écartée (D-2902) : documents fictifs construits dans les tests."""

from __future__ import annotations

import fabriques as fab

from controldone.ids import IdGenerator
from controldone.ingest import OptionsPages, decouper_fichier, extraire_refs, recevoir_octets
from controldone.ingest.classement import ClassementPage, RefsPage
from controldone.ingest.decoupage import _regrouper
from controldone.ingest.pages import moities_separees
from controldone.ingest.texte import Ligne, Mot
from controldone.model.enums import TypeDocument

LOCAL = OptionsPages(isoler=False)
FT = TypeDocument.facture_transitaire


def _decouper(contenu: bytes, nom: str = "f.pdf"):
    rec = recevoir_octets([(nom, contenu)], ids=IdGenerator.deterministe(3))
    fr = rec.fichiers[0]
    return decouper_fichier(fr.fichier, fr.contenu, options=LOCAL, ids=IdGenerator.deterministe(4))


# --- références d'une page --------------------------------------------------------------------------------------


def test_numero_apres_intitule_sans_libelle():
    assert extraire_refs("Transports Fictifs SAS   FACTURE FIC2026-47293").numero_facture == "FIC202647293"
    assert extraire_refs("AVOIR FIC-AV-09866").numero_facture == "FICAV09866"
    assert extraire_refs("ANNEXE Relación de suplidos - FACTURA FT26-71174").numero_facture == "FT2671174"
    assert extraire_refs("FAKTURA UZUPELNAJACA Nr FV/03342/07/2026").numero_facture == "FV03342072026"
    assert extraire_refs("FACTURE COMPLÉMENT DE PRESTATIONS FIC2026-61136").numero_facture == "FIC202661136"


def test_numero_sans_libelle_ni_date_ni_citation():
    assert extraire_refs("Facture du 12/03/2026").numero_facture is None
    assert extraire_refs("Invoice 2026").numero_facture is None
    assert extraire_refs("Facture 12,50").numero_facture is None
    assert extraire_refs("Avoir sur facture FIC2026-1234").numero_facture is None
    assert extraire_refs("AVOIR FIC-AV-09866 sur facture FIC2026-1").numero_facture == "FICAV09866"
    # loin du haut de la page : pas un intitulé
    texte = "\n".join(["Société Fictive"] * 9 + ["voir facture FIC2026-99999"])
    assert extraire_refs(texte).numero_facture is None


def test_numero_de_page_en_fin_de_ligne():
    r = extraire_refs("FIC SAS   FACTURE FIC2026-1\nÉmise le 12 juillet 2026 — page 2")
    assert r.page_n == 2 and r.page_total is None
    r = extraire_refs("DOUANESOFT (FICTIF)   ANNEXE A1   MRN 26FR000000000000A1   2/2")
    assert (r.page_n, r.page_total) == (2, 2)
    assert extraire_refs("Data wystawienia: 17.05.2026 — str. 2").page_n == 2


# --- regroupement des pages -------------------------------------------------------------------------------------


def _page(numero, type_=FT, *, num=None, pn=None, pt=None, jetons=(), conf=0.95, suite=False, mrns=()):
    return ClassementPage(
        numero=numero,
        type=type_,
        confiance=conf,
        intitulee=True,
        suite=suite,
        refs=RefsPage(
            mrns=tuple(mrns), numero_facture=num, page_n=pn, page_total=pt, jetons=frozenset(jetons)
        ),
    )


def test_numero_lu_sur_la_page_2_et_imprime_sur_la_page_1():
    groupes = _regrouper([_page(1, jetons={"FIC202647293", "99940679332"}), _page(2, num="FIC202647293")])
    assert [g.pages for g in groupes] == [[1, 2]]


def test_numero_de_page_2_absent_de_la_page_1_nouveau_document():
    groupes = _regrouper([_page(1, jetons={"FIC202647293"}), _page(2, num="FIC202600001")])
    assert [g.pages for g in groupes] == [[1], [2]]


def test_meme_numero_autre_type_de_facture():
    groupes = _regrouper(
        [
            _page(1, num="FV03342072026"),
            _page(2, TypeDocument.facture_commerciale, num="FV03342072026", conf=0.78),
        ]
    )
    assert [(g.type, g.pages) for g in groupes] == [(FT, [1, 2])]
    # page sûre de son type : deux documents
    groupes = _regrouper(
        [
            _page(1, num="FV03342072026"),
            _page(2, TypeDocument.facture_commerciale, num="FV03342072026", conf=0.97),
        ]
    )
    assert len(groupes) == 2


def test_page_2_sur_2_numero_voisin():
    groupes = _regrouper(
        [
            _page(1, TypeDocument.facture_commerciale, num="IHM2026001860", pn=1, pt=2),
            _page(2, TypeDocument.facture_commerciale, num="IHM2026001869", pn=2, pt=2),
        ]
    )
    assert [g.pages for g in groupes] == [[1, 2]]
    groupes = _regrouper(
        [
            _page(1, TypeDocument.facture_commerciale, num="IHM2026001860", pn=1, pt=2),
            _page(2, TypeDocument.facture_commerciale, num="IHM2026007777", pn=2, pt=2),
        ]
    )
    assert len(groupes) == 2


def test_suite_de_declaration_dont_le_mrn_de_tete_est_illisible():
    d = TypeDocument.declaration
    groupes = _regrouper([_page(1, d), _page(2, d, suite=True, pn=2, pt=2, mrns=("26FR000000000000A1",))])
    assert [g.pages for g in groupes] == [[1, 2]]


def test_facture_en_deux_pages_pdf():
    p1 = [
        "Transports Fictifs SAS   FACTURE FIC2026-47293",
        "Émise le 12 juillet 2026 — page 1",
        "MRN: 26FR000000000000A1",
        "Désignation Qté P.U. HT Montant HT TVA % TVA",
        "Frais de dédouanement 1 72,00 72,00 20,00 14,40",
        "Droits de douane 1 15,44 15,44 0,00 0,00",
    ]
    p2 = [
        "Transports Fictifs SAS   FACTURE FIC2026-47293",
        "Émise le 12 juillet 2026 — page 2",
        "RÉCAPITULATIF DE LA FACTURE",
        "Total débours 15,44 €",
        "Total HT 87,44 €",
        "TVA 20 % 14,40 €",
        "Total TTC 101,84 €",
    ]
    r = _decouper(fab.pdf([p1, p2]))
    assert [[p.numero for p in d.pages] for d in r.documents] == [[1, 2]]


# --- feuille « deux pages » -------------------------------------------------------------------------------------


def _ligne(*mots):
    return Ligne(
        texte=" ".join(m[0] for m in mots), mots=tuple(Mot(t, x0, y, x1, y + 0.01) for t, x0, x1, y in mots)
    )


def test_moities_separees_par_des_marges():
    lignes = [
        _ligne(("Facture", 0.05, 0.15, 0.1), ("FIC-1", 0.16, 0.45, 0.1)),
        _ligne(("Invoice", 0.55, 0.65, 0.1), ("FIC-2", 0.66, 0.95, 0.1)),
    ]
    assert moities_separees(lignes, 0.5)


def test_texte_qui_touche_la_coupure_page_unique():
    # colonne « Unité » qui finit juste avant la coupure, colonne « P.U. HT » juste après : un seul tableau
    lignes = [
        _ligne(("Désignation", 0.05, 0.2, 0.3), ("Unité", 0.45, 0.495, 0.3)),
        _ligne(("P.U.", 0.51, 0.55, 0.3), ("HT", 0.56, 0.6, 0.3)),
    ]
    assert not moities_separees(lignes, 0.5)
    # un trait isolé près de la coupure ne compte pas
    lignes = [
        _ligne(("Désignation", 0.05, 0.2, 0.3)),
        _ligne(("—", 0.499, 0.501, 0.5)),
        _ligne(("Montant", 0.6, 0.7, 0.3)),
    ]
    assert moities_separees(lignes, 0.5)


def test_deux_declarations_au_meme_titre_dans_un_pdf():
    d = TypeDocument.declaration

    def page(n, titre, suite, mrns=()):
        c = _page(n, d, suite=suite, mrns=mrns)
        c.titre = titre
        return c

    groupes = _regrouper(
        [
            page(1, "document administratif unique", False, ("26FR000000000000A1",)),
            page(2, "dau-bis (suite)", True),
            page(3, "document administratif unique", False),
            page(4, "dau-bis (suite)", True),
        ]
    )
    assert [g.pages for g in groupes] == [[1, 2], [3, 4]]
