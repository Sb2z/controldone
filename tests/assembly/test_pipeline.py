"""Pipeline (§7) avec des doubles d'ingestion et d'extraction — données fictives."""

from __future__ import annotations

import json
from decimal import Decimal

import pytest
from doubles import DecoupeurDouble, ExtracteurDouble, ecrire_pdf

from controldone.controls.registry import control, registre_temporaire
from controldone.findings_io import findings_json
from controldone.model import (
    ChampsDeclaration,
    ChampsFactureCommerciale,
    ChampsFactureTransitaire,
    DocumentReference,
    ForceLien,
    LigneFactureTransitaire,
    NatureLigne,
    Outcome,
    Partie,
    RaisonCode,
    TypeDocument,
)
from controldone.pipeline import (
    Composants,
    OptionsPipeline,
    autres_dossiers_de,
    controler_lot,
    preparer_lot,
    traiter_lot,
)
from controldone.testing import taxation, vs

MRN = "26FR0000000000AAA1"
TVA = "FR32000123459"
PROFIL = {
    "schema": "controldone.bench.profil/1.0.0", "client_id": "CL99",
    "entites": [{"raison_sociale": "IMPORT FICTIF SAS", "tva": TVA, "siren": "000123459", "alias": []}],
    "transitaires": [{"transitaire_id": "T9", "nom": "TRANSIT FICTIF", "tva": "FR11000000017", "alias": []}],
    "tolerances": {},
}


def fabrique(doc, pages):
    i = doc.id
    if doc.type is TypeDocument.facture_commerciale:
        return ChampsFactureCommerciale(
            numero=vs("facture_commerciale.numero", "INV-10001", document_id=i),
            devise=vs("facture_commerciale.devise", "USD", document_id=i),
            total_facture=vs("facture_commerciale.total_facture", "1000.00", document_id=i),
            acheteur=Partie(tva=vs("facture_commerciale.acheteur.tva", TVA, document_id=i)),
        )
    if doc.type is TypeDocument.declaration:
        return ChampsDeclaration(
            mrn=vs("declaration.mrn", MRN, document_id=i),
            devise_facture=vs("declaration.devise_facture", "USD", document_id=i),
            montant_total_facture=vs("declaration.montant_total_facture", "1000.00", document_id=i),
            importateur=Partie(tva=vs("declaration.importateur.tva", TVA, document_id=i)),
            documents_references=[DocumentReference(
                type_code=vs("declaration.documents_references[].type_code", "N380", document_id=i),
                reference=vs("declaration.documents_references[].reference", "INV-10001", document_id=i))],
            # B1 : 1 000,00 × 5 % = 50,00 ; imprimé 60,00 -> écart de calcul
            taxations=[taxation(i, base="1000.00", taux="5", montant="60.00")],
            # Total imprimé qui reprend la ligne : lecture corroborée (D-1700).
            total_a_payer=vs("declaration.total_a_payer", "60.00", document_id=i),
        )
    if doc.type is TypeDocument.facture_transitaire:
        return ChampsFactureTransitaire(
            numero=vs("facture_transitaire.numero", "FT-500", document_id=i),
            refs_mrn=[vs("facture_transitaire.refs_mrn[]", MRN, document_id=i)],
            lignes=[LigneFactureTransitaire(nature=NatureLigne.debours_droits,
                                            montant_ht=vs("facture_transitaire.lignes[].montant_ht", "60.00",
                                                          document_id=i))],
        )
    return None


@pytest.fixture
def lot(tmp_path):
    racine = tmp_path / "BX9001"
    ecrire_pdf(racine / "docs" / "fc_invoice.pdf", ["COMMERCIAL INVOICE INV-10001", "TOTAL USD 1,000.00"])
    ecrire_pdf(racine / "docs" / "dec_h1.pdf", ["DECLARATION MRN 26FR0000000000AAA1"], ["Taxes A00 60.00"])
    ecrire_pdf(racine / "docs" / "ft_facture.pdf", ["FACTURE FT-500 debours 60,00"])
    ecrire_pdf(racine / "docs" / "annexe.pdf", ["Liste de colisage"])
    return racine


def _composants(**kw):
    return Composants(decoupeur=DecoupeurDouble(**{k: v for k, v in kw.items() if k in ("echec", "inconnus")}),
                      extracteurs=[ExtracteurDouble(fabrique, **{k: v for k, v in kw.items()
                                                                  if k in ("echec_types", "cout")})])


def test_bout_en_bout(lot):
    res = traiter_lot(lot / "docs", PROFIL, [], options=OptionsPipeline(seed=1, dossier_id_sortie="BX9001",
                                                                       annee=2026), composants=_composants())
    assert len(res) == 1
    r = res[0]
    f = r.findings
    assert f.dossier_id == "BX9001"
    assert sorted(d.file for d in f.documents) == [
        "docs/annexe.pdf", "docs/dec_h1.pdf", "docs/fc_invoice.pdf", "docs/ft_facture.pdf"]
    assert all(d.pages == [1] or d.pages == [1, 2] for d in f.documents)
    forces = {lien.role: lien.force for lien in f.liens}
    assert forces["declaration"] == ForceLien.forte.value and forces["facture_transitaire"] == "forte"
    b1 = [c for c in f.constats if c.controle_id == "B1"]
    assert b1 and b1[0].montant_en_jeu == "10.00" and b1[0].niveau == "ecart_certain"
    assert f.statut_global == "ecart_certain"
    # exécution : versions et empreinte
    assert r.execution.empreinte_tolerances == r.profil.tolerances.empreinte()
    assert r.execution.versions_extracteurs == {"double": "0.1"}
    assert f.execution.duree_s is not None and f.execution.duree_s >= 0
    # clés d'idempotence des étapes
    assert {"reception", "pages", "classement", "extraction", "regroupement", "controles"} <= set(r.cles)
    assert len(r.cles["reception"]) == 4


def test_composant_en_erreur_ne_bloque_pas_le_lot(lot):
    res = traiter_lot(lot / "docs", PROFIL, [], options=OptionsPipeline(seed=1),
                      composants=_composants(echec=["annexe.pdf"]))
    assert len(res) == 1
    motifs = {(n.fichier, n.motif) for n in res[0].non_lus}
    assert ("docs/annexe.pdf", "lecture_en_erreur:RuntimeError") in motifs
    assert any(c.controle_id == "B1" for c in res[0].findings.constats)


def test_extracteur_en_panne(lot):
    res = traiter_lot(lot / "docs", PROFIL, [], options=OptionsPipeline(seed=1),
                      composants=_composants(echec_types=[TypeDocument.facture_transitaire]))
    assert len(res) == 1
    r = res[0]
    ft = [d for d in r.documents.values() if d.type is TypeDocument.facture_transitaire]
    assert len(ft) == 1 and ft[0].champs is None  # gardé, visible, sans champs


def test_sans_decoupeur_tous_les_fichiers_sont_non_lus(lot):
    res = traiter_lot(lot / "docs", PROFIL, [], options=OptionsPipeline(seed=1),
                      composants=Composants(decoupeur=None, extracteurs=[]))
    assert res == []
    prep = preparer_lot(lot / "docs", PROFIL, [], options=OptionsPipeline(seed=1),
                        composants=Composants(decoupeur=None, extracteurs=[]))
    assert {n.motif for n in prep.non_lus} == {"ingestion_indisponible"} and len(prep.non_lus) == 4


def test_fichier_refuse_liste(lot):
    (lot / "docs" / "casse.pdf").write_bytes(b"%PDF-1.4 tronque")
    prep = preparer_lot(lot / "docs", PROFIL, [], options=OptionsPipeline(seed=1), composants=_composants())
    assert any(n.fichier == "docs/casse.pdf" and n.motif.startswith("refuse:") for n in prep.non_lus)


def test_document_inconnu_liste(lot):
    prep = preparer_lot(lot / "docs", PROFIL, [], options=OptionsPipeline(seed=1),
                        composants=_composants(inconnus=["annexe.pdf"]))
    assert any(n.motif == "document_non_reconnu" for n in prep.non_lus)


def _sans_duree(f):
    d = json.loads(findings_json(f))
    d["execution"].pop("duree_s")
    return d


def test_reproductible_avec_graine(lot):
    a = traiter_lot(lot / "docs", PROFIL, [], options=OptionsPipeline(seed=7, annee=2026), composants=_composants())
    b = traiter_lot(lot / "docs", PROFIL, [], options=OptionsPipeline(seed=7, annee=2026), composants=_composants())
    assert _sans_duree(a[0].findings) == _sans_duree(b[0].findings)


def test_memo_des_etapes(lot):
    memo: dict = {}
    comp = _composants()
    traiter_lot(lot / "docs", PROFIL, [], options=OptionsPipeline(seed=3, memo=memo), composants=comp)
    appels = comp.extracteurs[0].appels
    traiter_lot(lot / "docs", PROFIL, [], options=OptionsPipeline(seed=3, memo=memo), composants=comp)
    assert comp.extracteurs[0].appels == appels  # extraction rejouée depuis la clé d'idempotence


def test_cout_ia_agrege(lot):
    res = traiter_lot(lot / "docs", PROFIL, [], options=OptionsPipeline(seed=1),
                      composants=_composants(cout="0.05"))
    # 4 documents extraits (fc, dec, ft, support) à 0,05 EUR
    assert res[0].execution.cout_ia_eur == Decimal("0.20")
    assert res[0].findings.execution.cout_ia_eur == "0.20"


def test_famille_f_voit_les_autres_dossiers(tmp_path, lot):
    autre = tmp_path / "BX9002"
    ecrire_pdf(autre / "docs" / "fc_invoice.pdf", ["COMMERCIAL INVOICE INV-10001"])
    vus = {}
    with registre_temporaire():
        @control("F1")
        def f1(ctx):
            vus[ctx.dossier.id] = len(ctx.autres_dossiers)
            return [ctx.non_applicable("F1", RaisonCode.document_manquant)]

        opts = OptionsPipeline(seed=1)
        p1 = preparer_lot(lot / "docs", PROFIL, [], options=opts, composants=_composants())
        p2 = preparer_lot(autre / "docs", PROFIL, [], options=opts, composants=_composants())
        res = controler_lot(p1, autres_dossiers=autres_dossiers_de([p2]), options=opts)
    assert list(vus.values()) == [1]
    assert res[0].resultats[0].outcome is Outcome.non_applicable


def test_controle_en_erreur_isole(lot):
    with registre_temporaire():
        @control("B2")
        def b2(ctx):
            raise ZeroDivisionError

        res = traiter_lot(lot / "docs", PROFIL, [], options=OptionsPipeline(seed=1), composants=_composants())
    r = next(x for x in res[0].resultats if x.controle_id == "B2")
    assert r.outcome is Outcome.non_verifiable and r.raison_code is RaisonCode.erreur_interne


def test_fichier_en_double_rattache_et_signale(lot):
    """D-802 : un fichier identique (sha256) n'est pas retraité, mais il est rattaché au lot (mention « doublon
    de fichier ») comme copie de l'original : F1 le signale, aucun montant n'est compté deux fois."""
    (lot / "docs" / "courriel").mkdir()
    (lot / "docs" / "courriel" / "ft_facture.pdf").write_bytes((lot / "docs" / "ft_facture.pdf").read_bytes())
    res = traiter_lot(lot / "docs", PROFIL, [], options=OptionsPipeline(seed=1, dossier_id_sortie="BX9001",
                                                                       annee=2026), composants=_composants())
    assert len(res) == 1
    r = res[0]
    doubles = [n.fichier for n in r.non_lus if n.motif == "doublon_de_fichier"]
    assert len(doubles) == 1 and doubles[0].endswith("ft_facture.pdf")
    copies = [d for d in r.documents.values() if d.doublon_de]
    assert len(copies) == 1 and copies[0].type is TypeDocument.facture_transitaire
    assert {"docs/courriel/ft_facture.pdf", "docs/ft_facture.pdf"} <= {d.file for d in r.findings.documents}
    f1 = [c for c in r.findings.constats if c.controle_id == "F1"]
    assert len(f1) == 1 and f1[0].documents_concernes == [copies[0].id] and f1[0].niveau == "a_verifier"
    # une seule facture transitaire comptée par les contrôles (pas de second C1/C5 ni de second P4)
    assert len([x for x in r.resultats if x.controle_id == "C1" and x.constat is not None]) <= 1
    assert not [c for c in r.findings.constats if c.controle_id == "P4" and copies[0].id in c.documents_concernes]


def test_progression_etapes_fines(lot):
    """D-3709 : rappel de progression (étapes, compteurs croissants) ; un rappel en erreur n'arrête rien."""
    from controldone.pipeline import ETAPES_PROGRESSION

    vus: list[tuple[str, int, int]] = []
    opts = OptionsPipeline(seed=1, progression=lambda e, f, t: vus.append((e, f, t)))
    res = traiter_lot(lot / "docs", PROFIL, [], options=opts, composants=_composants())
    assert len(res) == 1
    etapes = [e for e, _f, _t in vus]
    assert set(etapes) == set(ETAPES_PROGRESSION)
    # ordre des étapes respecté (première apparition)
    premieres = sorted(set(etapes), key=etapes.index)
    assert premieres == list(ETAPES_PROGRESSION)
    assert ("pages", 4, 4) in vus and ("regroupement", 1, 1) in vus and ("controles", 1, 1) in vus
    extraction = [(f, t) for e, f, t in vus if e == "extraction"]
    assert extraction[-1][0] == extraction[-1][1] and [f for f, _t in extraction] == sorted(f for f, _t in extraction)

    def casse(*_a):
        raise RuntimeError("affichage indisponible")

    res2 = traiter_lot(lot / "docs", PROFIL, [], options=OptionsPipeline(seed=1, progression=casse),
                       composants=_composants())
    assert [c.controle_id for c in res2[0].findings.constats] == [c.controle_id for c in res[0].findings.constats]
