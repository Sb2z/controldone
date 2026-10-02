"""Offres, paliers, commission, coupon de lancement, TVA (fonctions pures sur config/offres.yaml)."""

from __future__ import annotations

from decimal import Decimal

import pytest
from aides_facturation import CONFIG

from controldone.facturation.offres import A_COMPLETER, Consentement, CouponRefuse, charger_offres

SIGNE = Consentement(signe=True, signe_par="Mme FICTIVE, gérante", signe_le="2026-10-01",
                     reference_document="accord-FICTIF.pdf")


def test_offres_par_defaut():
    c = charger_offres(CONFIG, env={})
    assert c.prix_diagnostic_ht == Decimal("390.00")
    assert c.taux_commission == Decimal("0.20")
    assert [(p.prix_mensuel_ht, p.dossiers_par_mois) for p in c.paliers] == [
        (Decimal("99.00"), 20), (Decimal("199.00"), 60), (Decimal("349.00"), 150)]
    # Franchise en base au démarrage (art. 293 B du CGI) ; taux conservé pour la sortie de franchise.
    assert not c.tva.tva_applicable and c.tva.taux == Decimal("20.00") and c.tva.categorie == "E"
    assert c.tva.mention_franchise == "TVA non applicable, art. 293 B du CGI"
    assert c.prefixe_facture == "F" and c.prefixe_avoir == "AV"
    assert c.vendeur.siren == A_COMPLETER and not c.vendeur.complet
    assert "siren" in c.vendeur.champs_a_completer()


def test_palier_selon_volume():
    c = charger_offres(CONFIG, env={})
    assert c.palier_pour(0).code == "essentiel"
    assert c.palier_pour(20).code == "essentiel"
    assert c.palier_pour(21).code == "pro"
    assert c.palier_pour(150).code == "intensif"
    assert c.palier_pour(1000).code == "intensif"
    with pytest.raises(ValueError):
        c.palier_pour(-1)


def test_commission_vingt_pour_cent_au_centime():
    c = charger_offres(CONFIG, env={})
    assert c.commission(Decimal("300.00")) == Decimal("60.00")
    assert c.commission(Decimal("123.45")) == Decimal("24.69")  # 24,690
    assert c.commission(Decimal("0.025")) == Decimal("0.01")  # demi supérieur
    with pytest.raises(ValueError):
        c.commission(Decimal("-1"))


def test_coupon_sans_accord_de_publication():
    """D-1313 : la remise de lancement ne dépend d'aucun accord de publication (acte distinct, facultatif)."""
    c = charger_offres(CONFIG, env={})
    code = "LANCEMENT-3-DIAGNOSTICS"
    assert c.coupon(code).consentement_requis is False
    for consentement in (None, SIGNE, Consentement(signe=False, signe_par="X", signe_le="2026-10-01")):
        cp = c.verifier_coupon(code, offre="diagnostic", consentement=consentement, utilisations=0,
                               deja_utilise_par_client=False)
        assert cp.remise(Decimal("390.00")) == Decimal("390.00")  # 100 %


def test_coupon_ancien_reglage_consentement_requis():
    """Un coupon configuré avec ``consentement_requis: true`` exige toujours un accord signé."""
    from dataclasses import replace

    c = charger_offres(CONFIG, env={})
    code = "LANCEMENT-3-DIAGNOSTICS"
    c = replace(c, coupons={code: replace(c.coupon(code), consentement_requis=True)})
    assert c.verifier_coupon(code, offre="diagnostic", consentement=SIGNE, utilisations=0,
                             deja_utilise_par_client=False)
    for consentement in (None, Consentement(signe=False, signe_par="X", signe_le="2026-10-01"),
                         Consentement(signe=True, signe_par="", signe_le="2026-10-01")):
        with pytest.raises(CouponRefuse, match="accord"):
            c.verifier_coupon(code, offre="diagnostic", consentement=consentement, utilisations=0,
                              deja_utilise_par_client=False)


def test_coupon_quota_offre_et_client():
    c = charger_offres(CONFIG, env={})
    code = "lancement-3-diagnostics"  # casse indifférente
    with pytest.raises(CouponRefuse, match="épuisé"):
        c.verifier_coupon(code, offre="diagnostic", consentement=SIGNE, utilisations=3, deja_utilise_par_client=False)
    with pytest.raises(CouponRefuse, match="déjà utilisé"):
        c.verifier_coupon(code, offre="diagnostic", consentement=SIGNE, utilisations=1, deja_utilise_par_client=True)
    with pytest.raises(CouponRefuse, match="réservé"):
        c.verifier_coupon(code, offre="continu", consentement=SIGNE, utilisations=0, deja_utilise_par_client=False)
    with pytest.raises(CouponRefuse, match="inconnu"):
        c.coupon("GRATUIT")


def test_franchise_en_base_et_vendeur_par_environnement():
    c = charger_offres(CONFIG, env={"CONTROLDONE_TVA_APPLICABLE": "false", "CONTROLDONE_VENDEUR_SIREN": "999999999"})
    assert not c.tva.tva_applicable and c.tva.taux_effectif == Decimal("0.00") and c.tva.categorie == "E"
    assert c.tva.mention_franchise == "TVA non applicable, art. 293 B du CGI"
    assert c.vendeur.siren == "999999999" and c.vendeur.adresse_electronique_effective == "999999999"


def test_taux_de_commission_invalide(tmp_path):
    texte = CONFIG.read_text(encoding="utf-8").replace('taux: "0.20"', 'taux: "1.50"')
    p = tmp_path / "offres.yaml"
    p.write_text(texte, encoding="utf-8")
    with pytest.raises(ValueError):
        charger_offres(p, env={})
