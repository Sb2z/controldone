"""Couverture du cloisonnement (``storage.scope``, bloc O4, D-4901) : chemins d'erreur et de refus du
``TenantScope`` et de l'``OperatorScope`` qui n'étaient pas exercés (constructeur, filtres interdits, mises à jour,
validations du fondateur, journal, statistiques). Données toutes fictives (``conftest.monde``)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from aides_plateforme import FONDATEUR, SYSTEME

from controldone.auth.roles import Acteur, Role
from controldone.model.dossier import Dossier as DossierModele
from controldone.model.enums import NatureMontant, Niveau, Outcome, RaisonCode
from controldone.model.referentiel import Entite as EntiteModele
from controldone.model.referentiel import Transitaire as TransitaireModele
from controldone.model.resultats import Constat as ConstatModele
from controldone.model.resultats import ResultatControle
from controldone.storage import AccesRefuse, TenantScope
from controldone.storage.models import (
    Alerte,
    CleApi,
    Constat,
    Document,
    Dossier,
    Entite,
    EvenementRecouvrement,
    Fichier,
    Resultat,
    Transitaire,
)

# --- constructeur du périmètre ----------------------------------------------------------------------------------


def test_fondateur_sans_operateur_refuse(monde):
    s = monde.db.session()
    try:
        with pytest.raises(AccesRefuse, match="OperatorScope"):
            TenantScope(s, "cli_a", FONDATEUR)
    finally:
        s.close()


@pytest.mark.parametrize("tenant", ["", None, 42])
def test_client_invalide_refuse(monde, tenant):
    s = monde.db.session()
    try:
        with pytest.raises(AccesRefuse, match="client invalide"):
            TenantScope(s, tenant, SYSTEME)  # type: ignore[arg-type]
    finally:
        s.close()


def test_acteur_invalide_refuse(monde):
    s = monde.db.session()
    try:
        with pytest.raises(AccesRefuse, match="acteur invalide"):
            TenantScope(s, "cli_a", "usr_admin_a")  # type: ignore[arg-type]
    finally:
        s.close()


@pytest.mark.parametrize("effacement", [False, True])
def test_session_systeme_non_cloisonnable(monde, effacement):
    """Une session de plateforme (non filtrée) ne peut pas devenir un périmètre client."""
    s = monde.db.session_systeme(effacement=effacement)
    try:
        with pytest.raises(AccesRefuse, match="non cloisonnée"):
            TenantScope(s, "cli_a", SYSTEME)
    finally:
        s.close()


def test_session_operateur_non_cloisonnable(monde):
    with monde.db.operateur(FONDATEUR) as op, pytest.raises(AccesRefuse, match="non cloisonnée"):
        TenantScope(op.session, "cli_a", SYSTEME)


def test_session_deja_liee_a_un_autre_client(monde):
    s = monde.db.session()
    try:
        TenantScope(s, "cli_a", SYSTEME)
        with pytest.raises(AccesRefuse, match="autre client"):
            TenantScope(s, "cli_b", SYSTEME)
        TenantScope(s, "cli_a", SYSTEME)  # le même client reste possible
    finally:
        s.close()


def test_client_inexistant_ou_desactive(monde):
    with pytest.raises(AccesRefuse, match="introuvable"), monde.db.tenant("cli_zz", SYSTEME):
        pass
    with monde.db.operateur(FONDATEUR) as op:
        op.modifier_client("cli_b", actif=False)
    with pytest.raises(AccesRefuse, match="introuvable"), monde.db.tenant("cli_b", SYSTEME):
        pass
    with pytest.raises(AccesRefuse, match="introuvable"), monde.db.tenant("cli_b", monde.acteurs["admin_b"]):
        pass


def test_role_client_hors_de_son_client(monde):
    with pytest.raises(AccesRefuse, match="autre client"), monde.db.tenant("cli_b", monde.acteurs["admin_a"]):
        pass


def test_membre_au_mauvais_role_refuse(monde):
    """Un lecteur ne s'élève pas en se présentant comme administrateur (rôle lu en base)."""
    usurpe = Acteur("usr_lecteur_a", Role.client_admin, "cli_a")
    with pytest.raises(AccesRefuse, match="non membre"), monde.db.tenant("cli_a", usurpe):
        pass


def test_utilisateur_inconnu_refuse(monde):
    fantome = Acteur("usr_fantome", Role.client_lecteur, "cli_a")
    with pytest.raises(AccesRefuse, match="non membre"), monde.db.tenant("cli_a", fantome):
        pass


def _cle(monde, tenant, cle_id, **champs):
    with monde.db.tenant(tenant, SYSTEME) as sc:
        sc._ajouter_interne(
            CleApi(
                id=cle_id, nom="cle FICTIVE", prefixe=cle_id[-6:], hash="1" * 64, cree_par="tests", **champs
            )
        )


def test_acteur_cle_api_valide(monde):
    _cle(monde, "cli_a", "key_ok_a", role="client_lecteur")
    with monde.db.tenant("cli_a", Acteur("api:key_ok_a", Role.client_lecteur, "cli_a")) as sc:
        assert sc.compter(Dossier) == 1


@pytest.mark.parametrize(
    "cle_id, role_acteur, motif",
    [
        ("key_absente", Role.client_admin, "inconnue"),
        ("key_rev_a", Role.client_admin, "révoquée"),
        ("key_lec_a", Role.client_admin, "rôle différent de la clé"),
        ("key_b", Role.client_admin, "clé d'un autre client"),
    ],
)
def test_acteur_cle_api_non_valable(monde, cle_id, role_acteur, motif):
    _cle(monde, "cli_a", "key_rev_a", role="client_admin", revoquee_le=datetime(2026, 9, 2, tzinfo=UTC))
    _cle(monde, "cli_a", "key_lec_a", role="client_lecteur")
    acteur = Acteur(f"api:{cle_id}", role_acteur, "cli_a")
    with pytest.raises(AccesRefuse, match="clé d'API"), monde.db.tenant("cli_a", acteur):
        pass


# --- API générique : filtres et écritures --------------------------------------------------------------------------


def test_filtre_tenant_id_interdit_partout(monde):
    with monde.db.tenant("cli_a", SYSTEME) as sc:
        with pytest.raises(AccesRefuse):
            sc.lister_parmi(Dossier, "tenant_id", ["cli_b"])
        with pytest.raises(AccesRefuse):
            sc.compter(Dossier, tenant_id="cli_b")
        with pytest.raises(AccesRefuse):
            sc.lister(Dossier, tenant_id="cli_b")


def test_lister_parmi_ignore_none_doublons_et_autre_client(monde):
    with monde.db.tenant("cli_a", SYSTEME) as sc:
        lignes = sc.lister_parmi(Dossier, "id", ["dos_a", None, "dos_a", "dos_b"], ordre=Dossier.id)
    assert [d.id for d in lignes] == ["dos_a"]


def test_lister_parmi_par_paquets(monde):
    ids = [f"absent_{i}" for i in range(1200)] + ["fic_a"]
    with monde.db.tenant("cli_a", SYSTEME) as sc:
        assert [f.id for f in sc.lister_parmi(Fichier, "id", ids)] == ["fic_a"]


def test_modifier_colonne_inconnue(monde):
    with monde.db.tenant("cli_a", SYSTEME) as sc, pytest.raises(AttributeError):
        sc.modifier(Transitaire, "tra_a", colonne_qui_n_existe_pas="x")


def test_modifier_champ_protege(monde):
    with monde.db.tenant("cli_a", SYSTEME) as sc, pytest.raises(AccesRefuse, match="non modifiable"):
        sc.modifier(Transitaire, "tra_a", tenant_id="cli_b")


def test_supprimer_par_admin_client_puis_introuvable(monde):
    with monde.db.tenant("cli_a", monde.acteurs["admin_a"]) as sc:
        sc.supprimer(Transitaire, "tra_a")
    with monde.db.tenant("cli_a", SYSTEME) as sc:
        assert sc.lister(Transitaire) == []
    with monde.db.tenant("cli_b", SYSTEME) as sc:
        assert [t.id for t in sc.lister(Transitaire)] == ["tra_b"]


def test_supprimer_refuse_append_only_lecteur_et_autre_client(monde):
    with monde.db.tenant("cli_a", SYSTEME) as sc, pytest.raises(AccesRefuse, match="append-only"):
        sc.supprimer(EvenementRecouvrement, "evt_a")
    with monde.db.tenant("cli_a", monde.acteurs["lecteur_a"]) as sc, pytest.raises(AccesRefuse):
        sc.supprimer(Transitaire, "tra_a")
    with monde.db.tenant("cli_a", monde.acteurs["admin_a"]) as sc, pytest.raises(AccesRefuse):
        sc.supprimer(Dossier, "dos_a")  # réservé au moteur
    with monde.db.tenant("cli_b", monde.acteurs["admin_b"]) as sc, pytest.raises(AccesRefuse):
        sc.supprimer(Transitaire, "tra_a")


def test_suppression_par_fondateur_journalisee(monde):
    with monde.db.operateur(FONDATEUR) as op:
        sc = op.client("cli_a", "nettoyage (test FICTIF)")
        sc.supprimer(Transitaire, "tra_a")
    with monde.db.operateur(FONDATEUR) as op:
        actions = {(e.action, e.target) for e in op.journal()}
    assert ("supprimer", "transitaires:tra_a") in actions


def test_rollback_annule_les_ecritures(monde):
    with monde.db.tenant("cli_a", SYSTEME) as sc:
        sc.modifier(Transitaire, "tra_a", nom="RENOMME FICTIF")
        sc.rollback()
        assert sc.obtenir(Transitaire, "tra_a").nom == "TRANSITAIRE A FICTIF"


# --- référentiels : création puis mise à jour ---------------------------------------------------------------------


def test_enregistrer_entite_et_transitaire_mise_a_jour(monde):
    with monde.db.tenant("cli_a", monde.acteurs["admin_a"]) as sc:
        e = sc.enregistrer_entite(
            EntiteModele(id="ent_a", raison_sociale="NOUVELLE RAISON FICTIF", tva="FR00")
        )
        t = sc.enregistrer_transitaire(TransitaireModele(id="tra_a", nom="NOUVEAU NOM FICTIF"))
        assert (e.raison_sociale, e.tva, e.contenu["client_id"]) == (
            "NOUVELLE RAISON FICTIF",
            "FR00",
            "cli_a",
        )
        assert (t.nom, t.contenu["client_id"]) == ("NOUVEAU NOM FICTIF", "cli_a")
    with monde.db.tenant("cli_a", SYSTEME) as sc:
        assert len(sc.lister(Entite)) == 1 and len(sc.lister(Transitaire)) == 1


def test_meme_identifiant_d_un_autre_client_ne_le_modifie_pas(monde):
    """``enregistrer_transitaire`` avec l'identifiant d'une ligne de B, depuis A : nouvelle ligne refusée
    (conflit de clé) et la ligne de B reste intacte."""
    with pytest.raises(AccesRefuse), monde.db.tenant("cli_a", monde.acteurs["admin_a"]) as sc:
        sc.enregistrer_transitaire(TransitaireModele(id="tra_b", nom="PIRATE FICTIF"))
    with monde.db.tenant("cli_b", SYSTEME) as sc:
        assert sc.obtenir(Transitaire, "tra_b").nom == "TRANSITAIRE B FICTIF"


def test_valider_grille_introuvable(monde):
    with monde.db.operateur(FONDATEUR) as op:
        sc = op.client("cli_a", "validation (test FICTIF)")
        with pytest.raises(AccesRefuse, match="introuvable"):
            sc.valider_grille("grl_a", 99)
        with pytest.raises(AccesRefuse, match="introuvable"):
            sc.valider_grille("grl_b", 1)  # grille de B


def test_contenus_references_et_fichier_par_sha(monde):
    with monde.db.tenant("cli_a", SYSTEME) as sc:
        assert sc.contenus_references([]) == set()
        sha = sc.obtenir(Fichier, "fic_a").sha256
        assert sc.fichier_par_sha(sha).id == "fic_a"
        assert sc.fichier_par_sha("0" * 64) is None
    with monde.db.tenant("cli_b", SYSTEME) as sc:
        sha_b = sc.obtenir(Fichier, "fic_b").sha256
        assert sc.contenus_references([sha, sha_b]) == {sha_b}


# --- dossiers, documents, résultats --------------------------------------------------------------------------------


def test_dossier_version_anterieure_refusee(monde):
    with monde.db.tenant("cli_a", SYSTEME) as sc:
        sc.enregistrer_dossier(DossierModele(id="dos_a", reference="D-2026-00001", version=3))
        with pytest.raises(ValueError, match="antérieure"):
            sc.enregistrer_dossier(DossierModele(id="dos_a", reference="D-2026-00001", version=2))


def test_dossier_ecriture_reservee_au_moteur(monde):
    with monde.db.tenant("cli_a", monde.acteurs["admin_a"]) as sc, pytest.raises(AccesRefuse, match="moteur"):
        sc.enregistrer_dossier(DossierModele(id="dos_nv", reference="D-2026-00002"))


def test_dossier_rattache_fichier_d_un_autre_client_refuse(monde):
    with pytest.raises(AccesRefuse), monde.db.tenant("cli_a", SYSTEME) as sc:
        sc.enregistrer_dossier(
            DossierModele(id="dos_a", reference="D-2026-00001", version=2), fichier_ids=["fic_b"]
        )


def test_document_mis_a_jour(monde):
    from controldone.model.documents import Document as DocumentModele

    with monde.db.tenant("cli_a", SYSTEME) as sc:
        doc = sc.enregistrer_document(DocumentModele(id="doc_a", type="declaration"))
        assert doc.type == "declaration" and doc.dossier_id == "dos_a"  # dossier conservé
        assert doc.contenu["client_id"] == "cli_a"


def _resultat(cid, niveau=Niveau.ecart_certain, montant="120.00", version=1):
    c = ConstatModele(
        id=cid,
        controle_id="C1",
        niveau=niveau,
        montant_en_jeu=Decimal(montant),
        nature_montant=NatureMontant.recouvrable,
        raisons=[] if niveau is Niveau.ecart_certain else [next(iter(RaisonCode))],
    )
    return ResultatControle(
        id=f"res_{cid}",
        controle_id="C1",
        dossier_id="dos_a",
        dossier_version=version,
        outcome=Outcome.ecart_certain if niveau is Niveau.ecart_certain else Outcome.a_verifier,
        constat=c,
    )


def _valider(monde, constat_id, statut="valide", commentaire=None):
    with monde.db.operateur(FONDATEUR) as op:
        op.client("cli_a", "validation (test FICTIF)").valider_constat(constat_id, statut, commentaire)


def test_recontrole_inchange_conserve_la_validation(monde):
    with monde.db.tenant("cli_a", SYSTEME) as sc:
        sc.enregistrer_resultats([_resultat("f_rc")])
    _valider(monde, "f_rc")
    with monde.db.tenant("cli_a", SYSTEME) as sc:
        assert sc.enregistrer_resultats([_resultat("f_rc")]) == 1  # même niveau, même montant
        c = sc.obtenir(Constat, "f_rc")
        assert c.statut_validation == "valide" and c.valide_par == FONDATEUR.id
        assert c.contenu["statut_validation"] == "valide"
        assert sc.compter(Resultat, id="res_f_rc") == 1  # mise à jour, pas de doublon


@pytest.mark.parametrize(
    "niveau, montant",
    [(Niveau.ecart_certain, "130.00"), (Niveau.a_verifier, "120.00")],
    ids=["montant", "niveau"],
)
def test_recontrole_modifie_repropose_le_constat(monde, niveau, montant):
    with monde.db.tenant("cli_a", SYSTEME) as sc:
        sc.enregistrer_resultats([_resultat("f_rc")])
    _valider(monde, "f_rc")
    with monde.db.tenant("cli_a", SYSTEME) as sc:
        sc.enregistrer_resultats([_resultat("f_rc", niveau, montant)])
        c = sc.obtenir(Constat, "f_rc")
        assert (c.statut_validation, c.valide_par, c.valide_le) == ("propose", None, None)
        assert c.niveau == str(niveau) and c.montant_en_jeu == Decimal(montant)
    with monde.db.tenant("cli_a", monde.acteurs["admin_a"]) as sc:
        assert sc.compter(Constat, id="f_rc") == 0  # redevenu invisible pour le client


def test_resultats_d_un_dossier_d_un_autre_client_refuses(monde):
    r = _resultat("f_x").model_copy(update={"dossier_id": "dos_b"})
    with pytest.raises(AccesRefuse), monde.db.tenant("cli_a", SYSTEME) as sc:
        sc.enregistrer_resultats([r])


# --- validations du fondateur ---------------------------------------------------------------------------------------


def test_valider_constat_statut_inconnu_et_rejet_sans_motif(monde):
    with monde.db.operateur(FONDATEUR) as op:
        sc = op.client("cli_a", "validation (test FICTIF)")
        with pytest.raises(ValueError, match="inconnu"):
            sc.valider_constat("f_a", "publie")
        with pytest.raises(ValueError, match="motif"):
            sc.valider_constat("f_a", "rejete", "   ")
        assert sc.valider_constat("f_a", "rejete", "doublon FICTIF").statut_validation == "rejete"


def test_valider_constat_refuse_au_client(monde):
    with monde.db.tenant("cli_a", monde.acteurs["admin_a"]) as sc, pytest.raises(AccesRefuse):
        sc.valider_constat("f_a", "valide")


def test_retrograder_constat(monde):
    with monde.db.operateur(FONDATEUR) as op:
        sc = op.client("cli_a", "rétrogradation (test FICTIF)")
        with pytest.raises(ValueError, match="motif"):
            sc.retrograder_constat("f_a", "  ")
        with pytest.raises(ValueError, match="écart certain"):
            sc.retrograder_constat("fv_a", "motif FICTIF")
        c = sc.retrograder_constat("f_a", "  pièce douteuse FICTIF  ")
        assert (c.niveau, c.statut_validation, c.commentaire_validation) == (
            "a_verifier",
            "propose",
            "pièce douteuse FICTIF",
        )
        assert c.contenu["raisons"].count("retrograde_par_fondateur") == 1
        with pytest.raises(ValueError, match="écart certain"):
            sc.retrograder_constat("f_a", "deuxième fois")


def test_correction_sans_motif_ou_document_hors_dossier(monde):
    params = dict(
        correction_id="cor_nv",
        dossier_id="dos_a",
        document_id="doc_a",
        cible="v",
        chemin="facture_commerciale.total_facture",
        ancienne=None,
        nouvelle={"valeur": "3"},
        contenu_document={},
        role_auteur="client_admin",
    )
    with monde.db.tenant("cli_a", monde.acteurs["admin_a"]) as sc:
        with pytest.raises(ValueError, match="motif"):
            sc.appliquer_correction(motif=" ", **params)
        # doc_a n'est pas lié au dossier (liens vides) : traité comme hors périmètre
        with pytest.raises(AccesRefuse, match="introuvable"):
            sc.appliquer_correction(motif="erreur de lecture FICTIF", **params)
    with monde.db.tenant("cli_a", monde.acteurs["lecteur_a"]) as sc, pytest.raises(AccesRefuse):
        sc.appliquer_correction(motif="FICTIF", **params)


def test_correction_appliquee_incremente_la_version(monde):
    with monde.db.tenant("cli_a", SYSTEME) as sc:
        sc.modifier(Dossier, "dos_a", contenu={"liens": [{"document_id": "doc_a"}], "version": 1})
    with monde.db.tenant("cli_a", monde.acteurs["admin_a"]) as sc:
        d = sc.appliquer_correction(
            correction_id="cor_nv",
            dossier_id="dos_a",
            document_id="doc_a",
            cible="v",
            chemin="x" * 400,
            ancienne={"valeur": "1"},
            nouvelle={"valeur": "3"},
            contenu_document={"client_id": "cli_b", "type": "facture_commerciale"},
            motif="erreur de lecture FICTIF",
            role_auteur="client_admin",
        )
        assert d.version == 2 and d.contenu["version"] == 2
        assert sc.obtenir(Document, "doc_a").contenu["client_id"] == "cli_a"  # jamais celui fourni
        cor = next(c for c in sc.corrections("dos_a") if c.id == "cor_nv")
        assert len(cor.chemin) == 300 and cor.auteur == "usr_admin_a"


# --- membres, clés, journal du client ------------------------------------------------------------------------------


def test_membre_et_cle_api_role_client_exige(monde):
    with monde.db.operateur(FONDATEUR) as op:
        sc = op.client("cli_a", "comptes (test FICTIF)")
        with pytest.raises(AccesRefuse, match="rôle client"):
            sc.ajouter_membre("usr_x", Role.fondateur)
        with pytest.raises(AccesRefuse, match="rôle client"):
            sc.creer_cle_api("key_x", "cle", "pfxx", "0" * 64, Role.systeme)


def test_admin_client_revoque_sa_cle_pas_celle_d_un_autre(monde):
    with monde.db.tenant("cli_a", monde.acteurs["admin_a"]) as sc:
        sc.revoquer_cle_api("key_a")
        assert sc.obtenir(CleApi, "key_a").revoquee_le is not None
        with pytest.raises(AccesRefuse):
            sc.revoquer_cle_api("key_b")
    with monde.db.tenant("cli_a", monde.acteurs["lecteur_a"]) as sc, pytest.raises(AccesRefuse):
        sc.revoquer_cle_api("key_a")


def test_journal_du_client_ne_montre_que_ses_entrees(monde):
    with monde.db.tenant("cli_b", monde.acteurs["admin_b"]) as sc:
        sc.revoquer_cle_api("key_b")
    with monde.db.tenant("cli_a", monde.acteurs["admin_a"]) as sc:
        sc.revoquer_cle_api("key_a")
        journal = sc.journal()
        assert journal and {e.tenant_id for e in journal} == {"cli_a"}
        assert "api_keys:key_b" not in {e.target for e in journal}
        assert len(sc.journal(limite=1)) == 1


def test_client_lit_sa_fiche(monde):
    with monde.db.tenant("cli_a", monde.acteurs["lecteur_a"]) as sc:
        assert sc.client().id == "cli_a"


# --- opérateur (fondateur) -------------------------------------------------------------------------------------------


def test_operateur_reserve_au_fondateur(monde):
    for acteur in (SYSTEME, monde.acteurs["admin_a"]):
        with pytest.raises(AccesRefuse, match="fondateur"), monde.db.operateur(acteur):
            pass


def test_acces_client_exige_un_motif(monde):
    with monde.db.operateur(FONDATEUR) as op, pytest.raises(AccesRefuse, match="motif"):
        op.client("cli_a", "  ")


def test_modifier_client_champs_et_client_inconnu(monde):
    with monde.db.operateur(FONDATEUR) as op:
        with pytest.raises(AccesRefuse, match="non modifiables"):
            op.modifier_client("cli_a", id="cli_z")
        with pytest.raises(AccesRefuse, match="introuvable"):
            op.modifier_client("cli_zz", offre="suivi")
        op.modifier_client("cli_a", retention_jours=90)
    with monde.db.tenant("cli_a", SYSTEME) as sc:
        assert sc.client().retention_jours == 90


def _lier(monde, tenant, dossier, liens):
    with monde.db.tenant(tenant, SYSTEME) as sc:
        sc.modifier(Dossier, dossier, contenu={"liens": liens})


def test_points_attention_limite_et_total(monde):
    _lier(monde, "cli_a", "dos_a", [{"document_id": f"d{i}", "force": "faible"} for i in range(3)] + ["x"])
    _lier(monde, "cli_b", "dos_b", [{"document_id": "db", "force": "faible"}])
    with monde.db.tenant("cli_a", SYSTEME) as sc:
        sc.modifier(Document, "doc_a", type="inconnu")
    with monde.db.operateur(FONDATEUR) as op:
        tous, total = op.points_attention(["cli_a"], auditer=False)
        assert total == 4 and {p["type"] for p in tous} == {"faible", "inconnu"}
        assert {p["tenant_id"] for p in tous} == {"cli_a"}  # cli_b non demandé
        page, total2 = op.points_attention(["cli_a", "cli_b"], limite=2, auditer=False)
        assert len(page) == 2 and total2 == 5


def test_statistiques_a_verifier_et_hors_totaux(monde):
    with monde.db.tenant("cli_a", SYSTEME) as sc:
        sc.enregistrer_resultats(
            [_resultat("f_av", Niveau.a_verifier, "40.00"), _resultat("f_ec", Niveau.ecart_certain, "25.00")]
        )
    _valider(monde, "f_ec")
    with monde.db.operateur(FONDATEUR) as op:
        b = op.statistiques(auditer=False)["cli_a"]
    assert b["recouvrable_a_verifier"] == Decimal("40.00")
    assert b["recouvrable_certain"] == Decimal("25.00")
    assert sum(b["certain_par_mois"].values()) == Decimal("25.00")


def test_marquer_alerte_lue_journalisee(monde):
    with monde.db.tenant("cli_a", SYSTEME) as sc:
        assert sc.signaler_alerte(cle="k1", kind="essai", message="alerte FICTIVE")
        assert not sc.signaler_alerte(cle="k1", kind="essai", message="alerte FICTIVE")  # dédoublonnée
    with monde.db.operateur(FONDATEUR) as op:
        (alerte,) = op.alertes()
        op.marquer_alerte_lue(alerte.id)
    with monde.db.operateur(FONDATEUR) as op:
        assert op.alertes() == []
        assert len(op.alertes(non_lues=False)) == 1
        assert any(e.action == "alerte_lue" and e.target == f"alertes:{alerte.id}" for e in op.journal())
        assert op.marquer_alertes_lues([]) == 0


def test_rechercher_journal_filtres(monde):
    with monde.db.operateur(FONDATEUR) as op:
        avant_a = op.rechercher_journal(action="acces_admin", tenant_id="cli_a")[1]
        op.client("cli_a", "motif 1 FICTIF")
        op.client("cli_b", "motif 2 FICTIF")
    with monde.db.operateur(FONDATEUR) as op:
        tout, total = op.rechercher_journal(limite=10_000)
        assert total >= 2 and len(tout) <= 500
        a, n_a = op.rechercher_journal(action="acces_admin", tenant_id="cli_a", acteur="fondateur")
        assert n_a == avant_a + 1 and {e.tenant_id for e in a} == {"cli_a"}
        assert op.rechercher_journal(acteur="%")[1] == 0  # joker échappé
        futur = datetime.now(UTC) + timedelta(days=1)
        assert op.rechercher_journal(du=futur)[1] == 0
        assert op.rechercher_journal(au=futur)[1] == total
        croissant, _ = op.rechercher_journal(croissant=True, limite=2)
        assert croissant[0].id < croissant[1].id
        assert len(op.rechercher_journal(limite=0)[0]) == 1  # au moins une ligne par page
        actions, clients = op.valeurs_journal()
        assert "acces_admin" in actions and {"cli_a", "cli_b"} <= set(clients)
        assert op.verifier_journal() == []


def test_alertes_non_lues_par_type(monde):
    with monde.db.transaction_systeme() as s:
        for i, kind in enumerate(("a", "a", "b")):
            s.add(Alerte(cle=f"k{i}", kind=kind, message="alerte FICTIVE"))
    with monde.db.operateur(FONDATEUR) as op:
        par_type = op.alertes_non_lues_par_type()
        assert {k: n for k, (n, _) in par_type.items()} == {"a": 2, "b": 1}
        assert op.marquer_alertes_lues(["a", "a"]) == 2
    with monde.db.operateur(FONDATEUR) as op:
        assert set(op.alertes_non_lues_par_type()) == {"b"}
