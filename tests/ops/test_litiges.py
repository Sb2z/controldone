"""Litiges (§17) : machine d'état, rédaction pour le client, relances au client, imputation des avoirs,
commission exacte, brouillons sortants."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from itertools import pairwise

import pytest
from aides_ops import SYSTEME, T0

from controldone.guardrails import AVERTISSEMENT, check_text
from controldone.litiges import (
    TRANSITIONS_RECLAMATION,
    AvoirRecu,
    ServiceLitiges,
    StatutReclamation,
    TransitionReclamationInterdite,
    base_commission,
    montant_commission,
    rendre_pdf,
    statut_depuis_ecarts,
    taux_commission,
    verifier_transition,
)
from controldone.model.enums import NatureLigne, StatutEcart
from controldone.outbox import FileSortante
from controldone.storage import AccesRefuse
from controldone.storage.models import Constat

S = StatutReclamation


# --- machine d'état (pure) ----------------------------------------------------------------------------------


def test_chemin_nominal_autorise():
    chemin = [S.brouillon, S.valide, S.envoyee, S.partiellement_credite, S.credite, S.clos]
    for de, vers in pairwise(chemin):
        verifier_transition(de, vers)


@pytest.mark.parametrize(
    "de,vers",
    [
        (S.brouillon, S.envoyee),
        (S.brouillon, S.credite),
        (S.clos, S.envoyee),
        (S.abandonnee, S.valide),
        (S.credite, S.envoyee),
        (S.valide, S.brouillon),
    ],
)
def test_transitions_interdites(de, vers):
    with pytest.raises(TransitionReclamationInterdite):
        verifier_transition(de, vers)


def test_motif_obligatoire_abandon_et_cloture_partielle():
    with pytest.raises(TransitionReclamationInterdite):
        verifier_transition(S.envoyee, S.abandonnee)
    with pytest.raises(TransitionReclamationInterdite):
        verifier_transition(S.partiellement_credite, S.clos, "  ")
    verifier_transition(S.partiellement_credite, S.clos, "le transitaire a refusé le reste")
    verifier_transition(S.credite, S.clos)  # sans motif


def test_terminaux_sans_sortie():
    assert TRANSITIONS_RECLAMATION[S.clos] == frozenset()
    assert TRANSITIONS_RECLAMATION[S.abandonnee] == frozenset()


def test_statut_depuis_ecarts():
    E = StatutEcart
    assert statut_depuis_ecarts(S.envoyee, [E.reclame, E.reclame]) is S.envoyee
    assert statut_depuis_ecarts(S.envoyee, [E.credite, E.reclame]) is S.partiellement_credite
    assert statut_depuis_ecarts(S.envoyee, [E.partiellement_credite]) is S.partiellement_credite
    assert statut_depuis_ecarts(S.envoyee, [E.credite, E.abandonne]) is S.credite


# --- commission (pure, Decimal exact) ----------------------------------------------------------------------


def test_commission_exacte_et_base_limitee_aux_constats_valides():
    imputations = {"e1": Decimal("240.00"), "e2": Decimal("33.33"), "e3": Decimal("100.00")}
    base = base_commission(imputations, {"e1", "e2"})
    assert base == Decimal("273.33")
    assert montant_commission(base, Decimal("0.20")) == Decimal("54.67")  # 54,666 -> 54,67
    assert isinstance(montant_commission(base, Decimal("0.20")), Decimal)


def test_taux_commission_reglages():
    assert taux_commission({}) == Decimal("0.20")
    assert taux_commission({"commission_taux": "0.15"}) == Decimal("0.15")
    with pytest.raises(ValueError):
        taux_commission({"commission_taux": "1.5"})


# --- service ------------------------------------------------------------------------------------------------


@pytest.fixture
def service(monde):
    return ServiceLitiges(monde.db, vault=monde.vault, horloge=lambda: T0)


def test_preparer_dossier_redige_pour_le_client(monde, service):
    d = service.preparer(SYSTEME, "cli_a", "tra_a")
    assert d.statut is S.brouillon
    # deux constats validés recouvrables ; le proposé, le « à vérifier » non coché et le renvoi sont exclus
    assert sorted(x.constat_id for x in d.lignes) == ["f_a1", "f_a2"]
    assert d.total_demande == Decimal("300.00")
    t = d.texte
    # relevé factuel puis modèle neutre à adapter par le client (brief juridique §1.3, §9 ; D-1315)
    assert t.startswith("RELEVÉ D'ÉCARTS ENTRE DOCUMENTS") and "MODÈLE À ADAPTER PAR LE CLIENT" in t
    assert t.index("RELEVÉ D'ÉCARTS") < t.index("MODÈLE À ADAPTER")
    assert d.objet == "Relevé d'écarts entre documents — factures n° FT-a-001"
    assert "Différence calculée" in t and "Valeur facturée" in t and "Valeur de comparaison" in t
    assert "vérifier ces montants et nous indiquer si vous émettrez un avoir" in t
    assert "page 1" in t and "1 240,00" in t and "1 000,00" in t and "MRN 26FR00000000000001" in t
    assert "controldone" not in t.casefold()  # jamais au nom du prestataire
    assert "[Nom, fonction — à compléter]" in t
    assert check_text(t) == []
    assert AVERTISSEMENT in t
    for mot in (
        "illégal",
        "dû",
        "fraude",
        "délai légal",
        "mise en demeure",
        "réclamons",
        "pénalit",
        "délai",
        "conformément",
        "article L",
        "code des douanes",
        "Demande d'avoir",
        "recouvrement",
    ):
        assert mot.casefold() not in t.casefold(), mot
    assert d.pdf_sha256 and monde.vault.lire("cli_a", d.pdf_sha256).startswith(b"%PDF")
    # rejouer : aucun écart déjà demandé n'est repris
    with pytest.raises(ValueError):
        service.preparer(SYSTEME, "cli_a", "tra_a")


def test_a_verifier_coche_par_le_client_mention_a_confirmer(monde, service):
    d = service.preparer(SYSTEME, "cli_a", "tra_a", a_confirmer=["f_a4"])
    ligne = next(x for x in d.lignes if x.constat_id == "f_a4")
    assert ligne.a_confirmer
    assert d.total_demande == Decimal("300.00") and d.total_a_confirmer == Decimal("30.00")
    assert "(à confirmer)" in d.texte


def test_pdf_genere(monde, service):
    d = service.preparer(SYSTEME, "cli_a", "tra_a")
    assert rendre_pdf(d).startswith(b"%PDF")


def test_client_ne_prepare_pas_et_ne_voit_pas_autre_client(monde, service):
    with pytest.raises(AccesRefuse):
        service.preparer(monde.acteurs["admin_a"], "cli_a", "tra_a")
    with pytest.raises(AccesRefuse):
        service.lister(monde.acteurs["admin_a"], "cli_b")


def test_cycle_complet_relances_avoir_commission(monde, service):
    admin = monde.acteurs["admin_a"]
    d = service.preparer(SYSTEME, "cli_a", "tra_a")
    with pytest.raises(AccesRefuse):
        service.valider(admin, "cli_a", d.id)  # validation : fondateur seulement
    d = service.valider(monde.acteurs["fondateur"], "cli_a", d.id)
    assert d.statut is S.valide and d.outbox_mise_a_disposition
    file = FileSortante(monde.db)
    mise = file.obtenir(d.outbox_mise_a_disposition, monde.acteurs["fondateur"])
    assert mise.kind.value == "reclamation_dossier" and mise.statut.value == "brouillon"
    assert mise.payload["destinataires"] == ["compta@client-a-fictif.test"]

    d = service.declarer_envoi(admin, "cli_a", d.id, le=T0)
    assert d.statut is S.envoyee
    assert [r.jours for r in d.relances] == [15, 30, 45]
    assert d.relances[0].due_le == (T0 + timedelta(days=15)).date()

    # J+16 : une seule relance échue -> un brouillon adressé au client, jamais au transitaire
    ids = service.creer_relances_dues("cli_a", maintenant_=T0 + timedelta(days=16))
    assert len(ids) == 1
    rel = file.obtenir(ids[0], monde.acteurs["fondateur"])
    assert rel.kind.value == "relance" and rel.statut.value == "brouillon"
    assert rel.payload["destinataires"] == ["compta@client-a-fictif.test"]
    assert "transit-fictif" not in str(rel.payload["destinataires"])
    assert check_text(rel.payload["corps"]) == []
    # idempotent
    assert service.creer_relances_dues("cli_a", maintenant_=T0 + timedelta(days=16)) == []

    # avoir partiel sur les droits : 200 sur 240
    avoir = AvoirRecu.declare(
        "av_1",
        "tra_a",
        {NatureLigne.debours_droits: Decimal("200.00")},
        numero="AV-1",
        factures_origine=["FT-a-001"],
    )
    res = service.enregistrer_avoir(admin, "cli_a", avoir)
    assert res.statuts[d.id] == "partiellement_credite"
    assert sum(res.imputations.values()) == Decimal("200.00")
    assert res.base_commission == Decimal("200.00") and res.commission == Decimal("40.00")
    fac = file.obtenir(res.outbox_facture, monde.acteurs["fondateur"])
    assert fac.kind.value == "facture_emise" and fac.statut.value == "brouillon"
    assert fac.payload["total_ht"] == "40.00" and fac.payload["type_facture"] == "commission"
    # même avoir déclaré deux fois : aucun effet
    assert service.enregistrer_avoir(admin, "cli_a", avoir).deja_traite

    # second avoir : solde des droits (40) + TVA (60) + 10 de trop -> crédité, reliquat signalé
    avoir2 = AvoirRecu.declare(
        "av_2",
        "tra_a",
        {NatureLigne.debours_droits: Decimal("40.00"), NatureLigne.debours_tva: Decimal("70.00")},
        numero="AV-2",
        factures_origine=["FT-a-001"],
    )
    res2 = service.enregistrer_avoir(admin, "cli_a", avoir2)
    assert res2.statuts[d.id] == "credite"
    assert res2.reliquat == Decimal("10.00")
    assert res2.commission == Decimal("20.00")
    d = service.lire(admin, "cli_a", d.id)
    assert sum((c.montant for c in d.commissions), Decimal(0)) == Decimal("60.00")  # 20 % de 300
    assert all(r.statut != "planifiee" for r in d.relances)
    with monde.db.operateur(monde.acteurs["fondateur"]) as op:
        assert any(a.kind == "avoir_reliquat" for a in op.alertes())
    d = service.cloturer(admin, "cli_a", d.id)
    assert d.statut is S.clos


def test_commission_exclut_constat_devalide(monde, service):
    admin = monde.acteurs["admin_a"]
    d = service.preparer(SYSTEME, "cli_a", "tra_a")
    service.valider(monde.acteurs["fondateur"], "cli_a", d.id)
    service.declarer_envoi(admin, "cli_a", d.id, le=T0)
    # le fondateur revient sur le constat TVA : l'avoir est imputé mais n'entre pas dans la base
    with monde.db.operateur(monde.acteurs["fondateur"]) as op:
        op.client("cli_a", "révision").valider_constat("f_a2", "rejete", "lecture douteuse")
    res = service.enregistrer_avoir(
        admin,
        "cli_a",
        AvoirRecu.declare(
            "av_t",
            "tra_a",
            {NatureLigne.debours_tva: Decimal("60.00"), NatureLigne.debours_droits: Decimal("240.00")},
            factures_origine=["FT-a-001"],
        ),
    )
    assert sum(res.imputations.values()) == Decimal("300.00")
    assert res.base_commission == Decimal("240.00") and res.commission == Decimal("48.00")


def test_contestation_reprise_abandon(monde, service):
    admin = monde.acteurs["admin_a"]
    d = service.preparer(SYSTEME, "cli_a", "tra_a")
    service.valider(monde.acteurs["fondateur"], "cli_a", d.id)
    service.declarer_envoi(admin, "cli_a", d.id, le=T0)
    d = service.contester(admin, "cli_a", d.id, "le transitaire conteste")
    assert d.statut is S.conteste
    d = service.reprendre(admin, "cli_a", d.id)
    assert d.statut is S.envoyee
    with pytest.raises(TransitionReclamationInterdite):
        service.abandonner(admin, "cli_a", d.id, "")
    d = service.abandonner(admin, "cli_a", d.id, "montants trop faibles")
    assert d.statut is S.abandonnee
    with monde.db.tenant("cli_a", SYSTEME, lecture=True) as sc:
        assert all(sc.lire_ecart(e).statut is StatutEcart.abandonne for e in d.ecart_ids)


def test_inactifs(monde, service):
    admin = monde.acteurs["admin_a"]
    d = service.preparer(SYSTEME, "cli_a", "tra_a")
    service.valider(monde.acteurs["fondateur"], "cli_a", d.id)
    service.declarer_envoi(admin, "cli_a", d.id, le=T0)
    assert service.inactifs(SYSTEME, "cli_a", jours=60, maintenant_=T0 + timedelta(days=10)) == []
    assert [
        x.id for x in service.inactifs(SYSTEME, "cli_a", jours=60, maintenant_=T0 + timedelta(days=61))
    ] == [d.id]


def test_constats_jamais_modifies_par_les_litiges(monde, service):
    with monde.db.tenant("cli_a", SYSTEME, lecture=True) as sc:
        avant = {c.id: (c.niveau, c.montant_en_jeu, c.statut_validation) for c in sc.lister(Constat)}
    d = service.preparer(SYSTEME, "cli_a", "tra_a")
    service.valider(monde.acteurs["fondateur"], "cli_a", d.id)
    with monde.db.tenant("cli_a", SYSTEME, lecture=True) as sc:
        apres = {c.id: (c.niveau, c.montant_en_jeu, c.statut_validation) for c in sc.lister(Constat)}
    assert avant == apres
