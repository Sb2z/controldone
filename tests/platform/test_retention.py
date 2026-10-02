"""Conservation (§20.4), effacement RGPD d'un client, export de restitution."""

from __future__ import annotations

import json
import zipfile
from datetime import timedelta

import pytest
from aides_plateforme import FONDATEUR, SYSTEME, T0

from controldone.storage import (
    AccesRefuse,
    exporter_client,
    purger_expires,
    supprimer_client,
    verifier_chaine,
)
from controldone.storage.models import (
    MODELES_CLIENT,
    AuditLog,
    Dossier,
    DossierFichier,
    Fichier,
    Job,
    Lot,
    PageTexte,
    Tenant,
    User,
)


def _cloturer(monde, tenant, dossier_id, le):
    with monde.db.tenant(tenant, SYSTEME) as sc:
        sc.cloturer_dossier(dossier_id, le)


def _fichier(monde, tenant, fid):
    with monde.db.tenant(tenant, SYSTEME) as sc:
        f = sc.obtenir(Fichier, fid)
        return f.coffre_ref, f.purge_le, f.sha256


def test_rien_n_est_purge_avant_l_echeance(monde):
    _cloturer(monde, "cli_a", "dos_a", T0)
    rapport = purger_expires(monde.db, monde.vault, T0 + timedelta(days=179))
    assert rapport.total == 0
    ref, purge, _ = _fichier(monde, "cli_a", "fic_a")
    assert ref and purge is None and monde.vault.existe("cli_a", ref)


def test_purge_apres_retention(monde):
    _cloturer(monde, "cli_a", "dos_a", T0)
    ref, _, sha = _fichier(monde, "cli_a", "fic_a")
    with monde.db.tenant("cli_a", SYSTEME) as sc:
        texte_ref = sc.obtenir(PageTexte, "pag_a").texte_ref
    rapport = purger_expires(monde.db, monde.vault, T0 + timedelta(days=180))
    assert rapport.fichiers == {"cli_a": 1} and rapport.textes == {"cli_a": 1}
    ref2, purge, sha2 = _fichier(monde, "cli_a", "fic_a")
    assert ref2 is None and purge is not None and sha2 == sha  # métadonnées conservées
    assert not monde.vault.existe("cli_a", ref) and not monde.vault.existe("cli_a", texte_ref, espace="textes")
    with monde.db.tenant("cli_a", SYSTEME) as sc:
        assert sc.obtenir(Dossier, "dos_a") is not None  # le dossier et ses constats restent
    # client B intact (dossier non clôturé)
    ref_b, purge_b, _ = _fichier(monde, "cli_b", "fic_b")
    assert ref_b and purge_b is None and monde.vault.existe("cli_b", ref_b)
    # idempotent
    assert purger_expires(monde.db, monde.vault, T0 + timedelta(days=400)).total == 0
    with monde.db.transaction_systeme() as s:
        assert s.query(AuditLog).filter_by(action="purge_retention", tenant_id="cli_a").count() == 1


def test_retention_propre_au_client(monde):
    with monde.db.operateur(FONDATEUR) as op:
        op.modifier_client("cli_a", retention_jours=30)
    _cloturer(monde, "cli_a", "dos_a", T0)
    assert purger_expires(monde.db, monde.vault, T0 + timedelta(days=31)).fichiers == {"cli_a": 1}


def test_fichier_commun_attend_tous_ses_dossiers(monde):
    with monde.db.tenant("cli_a", SYSTEME) as sc:
        sc._ajouter_interne(Dossier(id="dos_a2", reference="D-2026-00002"))
        sc._ajouter_interne(DossierFichier(dossier_id="dos_a2", fichier_id="fic_a"))
    _cloturer(monde, "cli_a", "dos_a", T0)
    assert purger_expires(monde.db, monde.vault, T0 + timedelta(days=200)).total == 0
    _cloturer(monde, "cli_a", "dos_a2", T0 + timedelta(days=100))
    assert purger_expires(monde.db, monde.vault, T0 + timedelta(days=279)).total == 0
    assert purger_expires(monde.db, monde.vault, T0 + timedelta(days=280)).fichiers == {"cli_a": 1}


def test_contenu_partage_conserve_tant_qu_une_ligne_le_reference(monde):
    ref, _, sha = _fichier(monde, "cli_a", "fic_a")
    with monde.db.tenant("cli_a", SYSTEME) as sc:  # même contenu reçu dans un autre lot, non clôturé
        sc._ajouter_interne(Lot(id="lot_a2"))
        sc._ajouter_interne(Fichier(id="fic_a2", lot_id="lot_a2", nom_original="copie.pdf",
                                    chemin_relatif="copie.pdf", sha256=sha, coffre_ref=ref))
    _cloturer(monde, "cli_a", "dos_a", T0)
    purger_expires(monde.db, monde.vault, T0 + timedelta(days=181))
    assert monde.vault.existe("cli_a", ref)
    assert _fichier(monde, "cli_a", "fic_a")[0] is None


def test_fichier_orphelin_suit_la_cloture_du_lot(monde):
    with monde.db.tenant("cli_b", SYSTEME) as sc:
        sc._ajouter_interne(Lot(id="lot_b2", cloture_le=T0))
        sc._ajouter_interne(Fichier(id="fic_b2", lot_id="lot_b2", nom_original="inconnu.png",
                                    chemin_relatif="inconnu.png", sha256="c" * 64,
                                    coffre_ref=monde.vault.deposer("cli_b", b"image")))
    assert purger_expires(monde.db, monde.vault, T0 + timedelta(days=181)).fichiers == {"cli_b": 1}


def test_supprimer_client_efface_tout(monde):
    ref_b, _, _ = _fichier(monde, "cli_b", "fic_b")
    with monde.db.transaction_systeme() as s:
        s.add(Job(id="job_a", kind="traiter_lot", idempotency_key="k_a", tenant_id="cli_a"))
    comptes = supprimer_client(monde.db, monde.vault, "cli_a", FONDATEUR, "demande RGPD du client (FICTIF)")
    assert comptes["lots"] == 1 and comptes["users"] == 2 and comptes["jobs"] == 1
    with monde.db.transaction_systeme() as s:
        for modele in MODELES_CLIENT:
            assert s.query(modele).filter(modele.tenant_id == "cli_a").count() == 0, modele.__name__
        assert s.get(Tenant, "cli_a") is None
        assert s.get(User, "usr_admin_a") is None and s.get(User, "usr_admin_b") is not None
        assert s.query(Job).filter_by(tenant_id="cli_a").count() == 0
        trace = s.query(AuditLog).filter_by(action="supprimer_client", tenant_id="cli_a").one()
        assert trace.details["motif"].startswith("demande RGPD")
        assert verifier_chaine(s) == []
    assert "cli_a" not in monde.vault.clients()
    assert monde.vault.existe("cli_b", ref_b)
    with pytest.raises(AccesRefuse), monde.db.tenant("cli_a", SYSTEME):
        pass
    with monde.db.tenant("cli_b", SYSTEME) as sc:
        assert sc.obtenir(Lot, "lot_b")


def test_supprimer_client_reserve_au_fondateur(monde):
    for acteur in (monde.acteurs["admin_a"], SYSTEME):
        with pytest.raises(AccesRefuse):
            supprimer_client(monde.db, monde.vault, "cli_a", acteur, "motif")
    with pytest.raises(ValueError):
        supprimer_client(monde.db, monde.vault, "cli_a", FONDATEUR, " ")


def test_export_fondateur_complet(monde, tmp_path):
    chemin = exporter_client(monde.db, monde.vault, "cli_a", FONDATEUR, tmp_path / "export_a.zip")
    with zipfile.ZipFile(chemin) as z:
        noms = set(z.namelist())
        assert {"client.json", "entites.json", "grilles.json", "recouvrement.json", "manifest.json",
                "dossiers/dos_a.json", "pieces/fic_a/facture.pdf"} <= noms
        assert z.read("pieces/fic_a/facture.pdf") == b"PDF FICTIF cli_a"
        dossier = json.loads(z.read("dossiers/dos_a.json"))
        assert {c["id"] for c in dossier["constats"]} == {"f_a", "fv_a"} and dossier["resultats"]
        tout = b"".join(z.read(n) for n in noms)
        assert b"cli_b" not in tout and b"PDF FICTIF cli_b" not in tout
        manifeste = json.loads(z.read("manifest.json"))
        assert manifeste["client"] == "cli_a" and "client.json" in manifeste["contenu"]
    with monde.db.transaction_systeme() as s:
        assert s.query(AuditLog).filter_by(action="exporter_client", tenant_id="cli_a").count() == 1
        assert s.query(AuditLog).filter_by(action="acces_admin", tenant_id="cli_a").count() >= 1


def test_export_admin_client_constats_publies_seulement(monde, tmp_path):
    chemin = exporter_client(monde.db, monde.vault, "cli_a", monde.acteurs["admin_a"], tmp_path / "e.zip")
    with zipfile.ZipFile(chemin) as z:
        dossier = json.loads(z.read("dossiers/dos_a.json"))
    assert dossier["constats"] == [] and dossier["resultats"] == []


def test_export_refuse_hors_perimetre(monde, tmp_path):
    with pytest.raises(AccesRefuse):
        exporter_client(monde.db, monde.vault, "cli_b", monde.acteurs["admin_a"], tmp_path / "x.zip")
    with pytest.raises(AccesRefuse):
        exporter_client(monde.db, monde.vault, "cli_a", monde.acteurs["lecteur_a"], tmp_path / "y.zip")
