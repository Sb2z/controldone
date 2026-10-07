"""Couverture du suivi des avoirs (``services.reclamations``, bloc O4, D-4901) : visibilité des écarts pour un
rôle client, transitions refusées, montants d'avoir invalides, échéances de rappel mal saisies, voie directe des
façades, préparation du relevé réservée au fondateur. Données fictives (``conftest.monde``)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from aides_plateforme import FONDATEUR, SYSTEME

from controldone.litiges import RELANCES_DEFAUT
from controldone.model.enums import Composante
from controldone.model.recouvrement import EcartARecouvrer
from controldone.services import reclamations as rec
from controldone.services.plateforme import Interdit, Plateforme, RequeteInvalide
from controldone.storage import AccesRefuse
from controldone.storage.models import Ecart, EvenementRecouvrement


@pytest.fixture
def pf(monde):
    return Plateforme(db=monde.db, vault=monde.vault, cles_maitresses=[])


def _ecart(monde, ecart_id="eca_n", constat="f_a", montant="120.00", **kw):
    with monde.db.tenant("cli_a", SYSTEME) as sc:
        sc.enregistrer_ecart(
            EcartARecouvrer(
                id=ecart_id,
                constat_id=constat,
                dossier_id="dos_a",
                transitaire_id=kw.pop("transitaire_id", "tra_a"),
                composante=kw.pop("composante", Composante.droit),
                montant_initial=Decimal(montant),
                reste=Decimal(montant),
                mrn="26FR00000000000001",
                **kw,
            )
        )


def _publier(monde, constat="f_a"):
    with monde.db.operateur(FONDATEUR) as op:
        op.client("cli_a", "publication (test FICTIF)").valider_constat(constat, "valide")


@pytest.fixture
def admin_a(monde):
    return monde.acteurs["admin_a"]


# --- échéances des rappels ------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "reglages, attendu",
    [
        (None, tuple(RELANCES_DEFAUT)),
        ({"relances_jours": [30, 10, 10, -5, 0]}, (10, 30)),
        ({"relances_jours": ["x", 3]}, tuple(RELANCES_DEFAUT)),
        ({"relances_jours": [None]}, tuple(RELANCES_DEFAUT)),
        ({"relances_jours": [0, -1]}, tuple(RELANCES_DEFAUT)),
        ({"relances_jours": 7}, tuple(RELANCES_DEFAUT)),
    ],
)
def test_jours_relance_saisies_invalides(reglages, attendu):
    assert rec.jours_relance(reglages) == attendu


def test_relance_suggeree_selon_age_et_statut():
    assert rec._relance(None, "reclame") is None
    assert rec._relance(100, "credite") is None
    assert rec._relance(5, "reclame", (10, 20)) is None
    assert rec._relance(25, "conteste", (10, 20)) == "rappel suggéré (20 jours)"


# --- registre et visibilité -------------------------------------------------------------------------------------------


def test_ecart_d_un_constat_non_publie_invisible_au_client(monde, admin_a):
    _ecart(monde)
    with monde.db.tenant("cli_a", admin_a) as sc:
        assert rec.registre(sc) == []
        with pytest.raises(AccesRefuse):
            rec.registre(sc, ecart_id="eca_n")
        with pytest.raises(AccesRefuse):
            rec.declarer_envoi(sc, "eca_n")
    with monde.db.tenant("cli_a", SYSTEME) as sc:  # le moteur le voit
        assert "eca_n" in {x.id for x in rec.registre(sc)}


def test_registre_date_d_envoi_illisible_et_composante_inconnue(monde, admin_a):
    _ecart(monde)
    _publier(monde)
    with monde.db.tenant("cli_a", SYSTEME) as sc:
        ligne = sc.obtenir(Ecart, "eca_n")
        ligne.contenu = {**ligne.contenu, "reclame_le": "pas une date", "composante": "inconnue_fictive"}
    with monde.db.tenant("cli_a", admin_a) as sc:
        (x,) = [x for x in rec.registre(sc) if x.id == "eca_n"]
    assert x.age_jours is None and x.relance is None and x.composante == "inconnue_fictive"
    d = x.en_dict()
    assert d["litige_id"] == d["ecart_id"] == "eca_n" and d["reste_eur"] == "120.00"
    assert "ne préjuge pas" in d["nature"]


def test_registre_page_par_identifiants(monde, admin_a):
    _ecart(monde, "eca_1")
    _ecart(monde, "eca_2")
    _publier(monde)
    with monde.db.tenant("cli_a", admin_a) as sc:
        page = rec.registre(sc, ecart_ids=["eca_2", "eca_absent", "eca_b", "eca_1"])
    assert [x.id for x in page] == ["eca_2", "eca_1"]  # ordre demandé, autre client et absent ignorés


def test_age_et_rappel_apres_envoi(monde, admin_a):
    _ecart(monde)
    _publier(monde)
    with monde.db.tenant("cli_a", admin_a) as sc:
        rec.declarer_envoi(sc, "eca_n", "  envoyé par courrier FICTIF  ")
    with monde.db.tenant("cli_a", SYSTEME) as sc:
        ligne = sc.obtenir(Ecart, "eca_n")
        il_y_a = (datetime.now(UTC) - timedelta(days=50)).isoformat().replace("+00:00", "Z")
        ligne.contenu = {**ligne.contenu, "reclame_le": il_y_a}
    with monde.db.tenant("cli_a", admin_a) as sc:
        (x,) = rec.registre(sc, ecart_id="eca_n")
    assert x.statut_code == "reclame" and x.age_jours == 50
    assert x.relance == f"rappel suggéré ({max(j for j in RELANCES_DEFAUT if j <= 50)} jours)"
    assert x.evenements[-1]["commentaire"] == "envoyé par courrier FICTIF"


# --- transitions directes ----------------------------------------------------------------------------------------------


def test_declarer_envoi_deux_fois_refuse_proprement(monde, admin_a):
    _ecart(monde)
    _publier(monde)
    with monde.db.tenant("cli_a", admin_a) as sc:
        rec.declarer_envoi(sc, "eca_n")
        with pytest.raises(RequeteInvalide, match="transition"):
            rec.declarer_envoi(sc, "eca_n")


def test_lecteur_ne_declare_rien(monde):
    _ecart(monde)
    _publier(monde)
    with monde.db.tenant("cli_a", monde.acteurs["lecteur_a"]) as sc:
        with pytest.raises(Interdit):
            rec.declarer_envoi(sc, "eca_n")
        with pytest.raises(Interdit):
            rec.enregistrer_avoir(sc, "eca_n", Decimal("1"))


@pytest.mark.parametrize(
    "montant, motif",
    [
        (Decimal("NaN"), "invalide"),
        (Decimal("Infinity"), "invalide"),
        (Decimal("1000000000.01"), "invalide"),
        (120.0, "invalide"),
        (Decimal("0"), "positif"),
        (Decimal("-5"), "positif"),
    ],
)
def test_avoir_montant_refuse(monde, admin_a, montant, motif):
    _ecart(monde)
    _publier(monde)
    with monde.db.tenant("cli_a", admin_a) as sc, pytest.raises(RequeteInvalide, match=motif):
        rec.enregistrer_avoir(sc, "eca_n", montant)


def test_avoirs_partiel_puis_total_puis_refus(monde, admin_a):
    _ecart(monde)
    _publier(monde)
    with monde.db.tenant("cli_a", admin_a) as sc:
        rec.enregistrer_avoir(sc, "eca_n", Decimal("20.004"), reference=" AV-1 FICTIF ")
        (x,) = rec.registre(sc, ecart_id="eca_n")
        assert (x.statut_code, x.reste, x.montant_credite) == (
            "partiellement_credite",
            Decimal("100.00"),
            Decimal("20.00"),
        )
        assert x.evenements[-1]["piece"] == "AV-1 FICTIF"
        rec.enregistrer_avoir(sc, "eca_n", Decimal("150"))  # au-delà du reste : soldé
        (x,) = rec.registre(sc, ecart_id="eca_n")
        assert x.statut_code == "credite" and x.reste == Decimal("0.00")
        with pytest.raises(RequeteInvalide, match="transition"):
            rec.enregistrer_avoir(sc, "eca_n", Decimal("1"))
        assert sc.compter(EvenementRecouvrement, ecart_id="eca_n") == 2


# --- façades (voie directe : écart sans relevé) ------------------------------------------------------------------------


def test_facades_reservees_aux_roles_autorises(pf, monde):
    _ecart(monde)
    _publier(monde)
    lecteur = monde.acteurs["lecteur_a"]
    with pytest.raises(Interdit):
        rec.declarer_envoi_releve(pf, lecteur, "eca_n")
    with pytest.raises(Interdit):
        rec.enregistrer_avoir_recu(pf, lecteur, "eca_n", Decimal("1"))


@pytest.mark.parametrize(
    "montant, origine, motif",
    [
        (Decimal("NaN"), "transitaire", "invalide"),
        ("12", "transitaire", "invalide"),
        (Decimal("0"), "transitaire", "positif"),
        (Decimal("5"), "client", "origine"),
    ],
)
def test_avoir_recu_saisies_refusees(pf, monde, admin_a, montant, origine, motif):
    _ecart(monde)
    _publier(monde)
    with pytest.raises(RequeteInvalide, match=motif):
        rec.enregistrer_avoir_recu(pf, admin_a, "eca_n", montant, origine=origine)


def test_facades_voie_directe(pf, monde, admin_a):
    _ecart(monde)
    _publier(monde)
    rec.declarer_envoi_releve(pf, admin_a, "eca_n", "envoyé FICTIF")
    r = rec.enregistrer_avoir_recu(pf, admin_a, "eca_n", Decimal("30.005"), origine="administration")
    assert r == {"voie": "directe", "impute": "30.00"}
    with monde.db.tenant("cli_a", admin_a) as sc:
        (x,) = rec.registre(sc, ecart_id="eca_n")
    assert x.statut_code == "partiellement_credite"
    assert "administration" in x.evenements[-1]["commentaire"]


def test_facade_releve_d_un_autre_client_ignore(pf, monde, admin_a):
    """Un ``reclamation_id`` qui ne désigne pas un relevé de ce client est ignoré (voie directe)."""
    _ecart(monde, reclamation_id="rec_b")
    _publier(monde)
    rec.declarer_envoi_releve(pf, admin_a, "eca_n")
    with monde.db.tenant("cli_a", admin_a) as sc:
        assert rec.registre(sc, ecart_id="eca_n")[0].statut_code == "reclame"


def test_facade_ecart_d_un_autre_client(pf, monde):
    with pytest.raises(AccesRefuse):
        rec.declarer_envoi_releve(pf, monde.acteurs["admin_b"], "eca_n_absent")
    _ecart(monde)
    _publier(monde)
    with pytest.raises(AccesRefuse):
        rec.enregistrer_avoir_recu(pf, monde.acteurs["admin_b"], "eca_n", Decimal("1"))


# --- relevé d'écarts (fondateur) -------------------------------------------------------------------------------------


def test_preparer_dossier_reserve_au_fondateur(pf, admin_a):
    with pytest.raises(Interdit):
        rec.preparer_dossier(pf, admin_a, "cli_a", "tra_a")


def test_preparer_dossier_sans_ecart_valide(pf):
    with pytest.raises(RequeteInvalide, match="aucun écart"):
        rec.preparer_dossier(pf, FONDATEUR, "cli_a", "tra_a")
