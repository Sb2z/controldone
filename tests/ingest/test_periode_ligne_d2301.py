"""Période de facturation d'une ligne structurée (CII BG-26) : magasinage (D-2301). Données fictives."""

from __future__ import annotations

import fabriques as fab
from test_ingest_structure import _extraire

from controldone.model.enums import NatureLigne, TypeDocument

_PERIODE = ("<ram:BillingSpecifiedPeriod><ram:StartDateTime><udt:DateTimeString format=\"102\">20260602"
            "</udt:DateTimeString></ram:StartDateTime><ram:EndDateTime><udt:DateTimeString format=\"102\">"
            "20260611</udt:DateTimeString></ram:EndDateTime></ram:BillingSpecifiedPeriod>")
_ANCRE = "<ram:SpecifiedTradeSettlementLineMonetarySummation>"


def _ft_cii(avec_periode: bool) -> bytes:
    xml = fab.cii(numero="FT-FICTIF-2301", devise="EUR", incoterm=None, refs_doc=["26FR000000000001A1"],
                  lignes=[("Frais de dédouanement", "1", "55.00", "55.00", None, None, "20"),
                          ("Magasinage", "10", "12.50", "125.00", None, None, "20")],
                  vendeur="FICTIF TRANSIT SARL", tva_vendeur="FR40000987651").decode()
    if avec_periode:
        avant, _, apres = xml.rpartition(_ANCRE)
        xml = avant + _PERIODE + _ANCRE + apres
    return fab.facturx_pdf(xml.encode(), fab.FACTURE_TRANSITAIRE)


def test_cii_periode_de_la_ligne_lue():
    doc, res = _extraire(_ft_cii(True), "ft.pdf")
    assert doc.type is TypeDocument.facture_transitaire
    mag = res.champs.lignes[1]
    assert mag.nature is NatureLigne.magasinage
    assert mag.date_debut.valeur == "2026-06-02" and mag.date_fin.valeur == "2026-06-11"
    assert mag.date_debut.confiance == 1.0


def test_cii_sans_periode_aucune_date():
    _, res = _extraire(_ft_cii(False), "ft.pdf")
    assert res.champs.lignes[1].date_debut is None and res.champs.lignes[1].date_fin is None
