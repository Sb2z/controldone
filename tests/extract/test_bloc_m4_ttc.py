"""Lignes imprimées seulement TVA comprise, marquées dès l'extraction (D-4602). Données entièrement fictives."""

from __future__ import annotations

import fixtures_fc as fx
import pytest

from controldone.extract.deterministe.facture_transitaire import ExtracteurFactureTransitaire, _mention_ttc
from controldone.model import LigneFactureTransitaire
from controldone.model.enums import Methode, NatureLigne, RaisonCode, TypeDocument
from controldone.normalize import tva_fr_depuis_siren
from controldone.recouvrement.imputation import montant_net_ligne
from controldone.testing import vs

TVA_EM = tva_fr_depuis_siren("000515151")
TVA_CL = tva_fr_depuis_siren("000626262")
MRN_A = "26FRK3M5P7R9T1V3X5"  # MRN FICTIF


def _v(x):
    return None if x is None else x.valeur


def pdf_entete_decoupe() -> bytes:
    """Facture FICTIVE dont l'en-tête de la colonne de montant est « Total : c/ IVA » : le deux-points coupe la
    locution et « IVA » serait reconnu seul comme une colonne de TVA (cas d'un scan, D-4602)."""
    p = fx.PagePdf()
    p.t(40, 50, "Despachos Imaginarios FICTIF Lda", taille=12, gras=True)
    p.t(40, 64, f"Rua da Fabula 3 · 69003 Lyon · NIF {TVA_EM}")
    p.t(430, 50, "FATURA", taille=14, gras=True)
    p.t(430, 66, "N.º DF 2026/0777")
    p.t(430, 80, "Data: 14-05-2026")
    p.t(40, 110, "Cliente")
    p.t(40, 124, "Societe Fictive SAS")
    p.t(40, 138, f"NIF/IVA: {TVA_CL}")
    p.t(330, 124, f"MRN: {MRN_A}")
    y = 200
    p.ligne(
        y,
        [
            (40, "Descrição", False),
            (330, "Qtd", True),
            (400, "Preço unit. c/ IVA", True),
            (450, "Taxa", True),
            (540, "Total : c/ IVA", True),
        ],
        taille=8,
    )
    linhas = [
        ("Direitos aduaneiros", "1", "80,25 €", "isento", "80,25 €"),
        ("Desalfandegamento", "1", "96,00 €", "20%", "96,00 €"),
        ("Entrega", "1", "120,00 €", "20%", "120,00 €"),
    ]
    for k, (d, q, pu, tx, tt) in enumerate(linhas):
        p.ligne(
            y + 16 * (k + 1),
            [(40, d, False), (330, q, True), (400, pu, True), (450, tx, True), (540, tt, True)],
            taille=8,
        )
    y += 16 * 5
    p.ligne(y + 40, [(330, "Total despesas (suplidos)", False), (540, "80,25 €", True)])
    p.ligne(y + 54, [(330, "Total sem IVA", False), (540, "260,25 €", True)])
    p.ligne(y + 68, [(330, "IVA", False), (540, "36,00 €", True)])
    p.ligne(y + 82, [(330, "Total com IVA", False), (540, "296,25 €", True)])
    return fx.pdf([p])


@pytest.fixture(scope="module")
def champs():
    r = fx.extraire(
        pdf_entete_decoupe(), TypeDocument.facture_transitaire, extracteur=ExtracteurFactureTransitaire()
    )
    assert r.champs is not None
    return r.champs


def test_entete_decoupe_lu_comme_colonne_ttc(champs):
    lignes = list(champs.lignes)
    assert [lg.nature for lg in lignes] == [
        NatureLigne.debours_droits,
        NatureLigne.frais_dedouanement,
        NatureLigne.transport,
    ]
    assert [_v(lg.montant_ttc) for lg in lignes] == ["80.25", "96.00", "120.00"]
    assert all(lg.tva_comprise for lg in lignes)
    # ligne taxée : hors-taxe déduit, jamais lu
    assert _v(lignes[1].montant_ht) == "80.00" and lignes[1].montant_ht.methode is Methode.derive


def test_montant_net_ligne_marque_les_lignes_ttc(champs):
    taxee = montant_net_ligne(champs.lignes[1])
    assert taxee is not None and RaisonCode.montant_tva_comprise in taxee.raisons and taxee.confiance <= 0.6
    exoneree = montant_net_ligne(champs.lignes[0])
    assert exoneree is not None and _v(exoneree) == "80.25"
    assert RaisonCode.montant_tva_comprise not in exoneree.raisons


@pytest.mark.parametrize(
    ("libelle", "attendu"),
    [
        ("Total : c/ IVA", True),
        ("Total c/IVA", True),
        ("Betrag inkl. MwSt", True),
        ("Montant TTC", True),
        ("Amount incl. VAT", True),
        ("Valor s/ IVA", False),
        ("Montant HT", False),
        ("Total", False),
        ("Netto", False),
    ],
)
def test_mention_ttc(libelle, attendu):
    assert _mention_ttc(libelle) is attendu


def test_drapeau_tva_comprise_sans_ht_lu():
    """Ligne marquée TVA comprise dont le montant a été rangé comme hors-taxe : toujours marqué (D-4602)."""
    lg = LigneFactureTransitaire(
        nature=NatureLigne.frais_dedouanement,
        montant_ht=vs("facture_transitaire.lignes[].montant_ht", "72.00"),
        taux_tva=vs("facture_transitaire.lignes[].taux_tva", "20"),
        tva_comprise=True,
    )
    v = montant_net_ligne(lg)
    assert v is not None and RaisonCode.montant_tva_comprise in v.raisons
    sans = lg.model_copy(update={"tva_comprise": False})
    assert RaisonCode.montant_tva_comprise not in montant_net_ligne(sans).raisons
