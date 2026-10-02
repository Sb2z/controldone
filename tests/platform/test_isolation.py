"""Tests adverses du cloisonnement par client (SPEC §20.1) : chaque tentative d'accès croisé doit
échouer avec ``AccesRefuse`` (ou ne rien voir / ne rien toucher)."""

from __future__ import annotations

import re
from decimal import Decimal
from pathlib import Path

import pytest
from aides_plateforme import FONDATEUR, SYSTEME
from sqlalchemy import delete, insert, select, update
from sqlalchemy.orm import aliased

from controldone.auth.cles_api import creer_cle_api, verifier_cle_api
from controldone.auth.roles import Acteur, Role
from controldone.storage import AccesRefuse, ErreurCoffre, ErreurIntegrite, TenantScope
from controldone.storage.models import (
    MODELES_CLIENT,
    AiUsage,
    AuditLog,
    Constat,
    Dossier,
    EvenementRecouvrement,
    Fichier,
    Grille,
    Lot,
    Outbox,
    Resultat,
    Tenant,
    User,
)

NOMS = [m.__name__ for m in MODELES_CLIENT]
MODELES = {m.__name__: m for m in MODELES_CLIENT}
APPEND_ONLY = {"AiUsage", "EvenementRecouvrement"}


# --- lecture / écriture par devinette d'identifiant ---------------------------------------------------


@pytest.mark.parametrize("nom", NOMS)
def test_lecture_croisee_par_id_refusee(monde, nom):
    id_a = monde.ids["cli_a"][nom]
    with monde.db.tenant("cli_b", SYSTEME) as sc, pytest.raises(AccesRefuse):
        sc.obtenir(MODELES[nom], id_a)


@pytest.mark.parametrize("nom", NOMS)
def test_liste_ne_contient_jamais_autre_client(monde, nom):
    with monde.db.tenant("cli_b", SYSTEME) as sc:
        lignes = sc.lister(MODELES[nom])
    assert lignes, "le client B a ses propres lignes"
    assert all(lig.tenant_id == "cli_b" for lig in lignes)
    assert monde.ids["cli_a"][nom] not in {lig.id for lig in lignes}


@pytest.mark.parametrize("nom", [n for n in NOMS if n not in APPEND_ONLY])
def test_modification_croisee_refusee(monde, nom):
    modele = MODELES[nom]
    colonne = next(c for c in ("nom", "statut", "type", "reference", "role", "outcome", "nom_original",
                               "transitaire_id", "fichier_id", "numero", "raison_sociale", "kind", "niveau")
                   if c in modele.__table__.columns)
    with monde.db.tenant("cli_b", SYSTEME) as sc, pytest.raises(AccesRefuse):
        sc.modifier(modele, monde.ids["cli_a"][nom], **{colonne: "pirate"})


@pytest.mark.parametrize("nom", [n for n in NOMS if n not in APPEND_ONLY])
def test_suppression_croisee_refusee(monde, nom):
    with monde.db.tenant("cli_b", SYSTEME) as sc, pytest.raises(AccesRefuse):
        sc.supprimer(MODELES[nom], monde.ids["cli_a"][nom])
    with monde.db.tenant("cli_a", SYSTEME) as sc:
        assert sc.obtenir(MODELES[nom], monde.ids["cli_a"][nom]) is not None


def test_id_inexistant_et_id_etranger_meme_erreur(monde):
    with monde.db.tenant("cli_b", SYSTEME) as sc:
        with pytest.raises(AccesRefuse) as e1:
            sc.obtenir(Lot, "lot_a")
        with pytest.raises(AccesRefuse) as e2:
            sc.obtenir(Lot, "lot_inexistant")
    assert str(e1.value) == str(e2.value)


def test_ajout_avec_tenant_etranger_refuse(monde):
    with monde.db.tenant("cli_b", SYSTEME) as sc, pytest.raises(AccesRefuse):
        sc.ajouter(Lot(id="lot_pirate", tenant_id="cli_a"))
    with monde.db.tenant("cli_a", SYSTEME) as sc, pytest.raises(AccesRefuse):
        sc.obtenir(Lot, "lot_pirate")


def test_ajout_avec_id_existant_d_un_autre_client_refuse(monde):
    with monde.db.tenant("cli_b", SYSTEME) as sc, pytest.raises(AccesRefuse):
        sc.ajouter(Lot(id="lot_a"))  # collision de clé primaire : pas d'écrasement, erreur générique
    with monde.db.tenant("cli_a", SYSTEME) as sc:
        assert sc.obtenir(Lot, "lot_a").tenant_id == "cli_a"


def test_changer_tenant_id_refuse_par_api(monde):
    with monde.db.tenant("cli_b", SYSTEME) as sc, pytest.raises(AccesRefuse):
        sc.modifier(Lot, "lot_b", tenant_id="cli_a")
    with monde.db.tenant("cli_b", SYSTEME) as sc, pytest.raises(AccesRefuse):
        sc.modifier(Lot, "lot_b", id="lot_a")


def test_changer_tenant_id_par_attribut_refuse_au_flush(monde):
    with pytest.raises(AccesRefuse), monde.db.tenant("cli_b", SYSTEME) as sc:
        lot = sc.obtenir(Lot, "lot_b")
        lot.tenant_id = "cli_a"
        sc.flush()
    with monde.db.tenant("cli_b", SYSTEME) as sc:
        assert sc.obtenir(Lot, "lot_b").tenant_id == "cli_b"


def test_filtre_tenant_id_interdit(monde):
    with monde.db.tenant("cli_b", SYSTEME) as sc, pytest.raises(AccesRefuse):
        sc.lister(Lot, tenant_id="cli_a")


@pytest.mark.parametrize("modele", [User, AuditLog, Tenant])
def test_tables_plateforme_inaccessibles_par_api_generique(monde, modele):
    with monde.db.tenant("cli_b", SYSTEME) as sc, pytest.raises(AccesRefuse):
        sc.lister(modele)


# --- contournements par requêtes ORM sur la session du périmètre --------------------------------------


def test_requete_select_brute_filtree_automatiquement(monde):
    with monde.db.tenant("cli_b", SYSTEME) as sc:
        lignes = sc.session.execute(select(Lot)).scalars().all()
        assert {lig.tenant_id for lig in lignes} == {"cli_b"}
        assert sc.session.execute(select(Lot).where(Lot.id == "lot_a")).scalar_one_or_none() is None


def test_session_get_ne_charge_pas_autre_client(monde):
    with monde.db.tenant("cli_b", SYSTEME) as sc:
        assert sc.session.get(Lot, "lot_a") is None
        assert sc.session.get(Constat, "f_a") is None


def test_jointures_alias_et_sous_requetes_filtrees(monde):
    with monde.db.tenant("cli_b", SYSTEME) as sc:
        s = sc.session
        jointure = s.execute(select(Lot, Fichier).join(Fichier, Fichier.lot_id == Lot.id)).all()
        assert all(lot.tenant_id == fic.tenant_id == "cli_b" for lot, fic in jointure)
        alias = aliased(Lot)
        assert {x.tenant_id for x in s.execute(select(alias)).scalars()} == {"cli_b"}
        sous = s.execute(select(Lot).where(Lot.id.in_(select(Fichier.lot_id)))).scalars().all()
        assert [x.id for x in sous] == ["lot_b"]
        # jointure explicite sur la table d'un autre client : rien ne remonte
        croise = s.execute(select(Dossier).join(Lot, Lot.id == "lot_a")).all()
        assert croise == []


def test_update_et_delete_en_masse_restent_dans_le_perimetre(monde):
    with monde.db.tenant("cli_b", SYSTEME) as sc:
        sc.session.execute(update(Lot).values(statut="pirate"))
        sc.session.execute(update(Lot).where(Lot.id == "lot_a").values(statut="pirate2"))
        sc.session.execute(delete(Constat).where(Constat.id == "f_a"))
    with monde.db.tenant("cli_a", SYSTEME) as sc:
        assert sc.obtenir(Lot, "lot_a").statut == "recu"
        assert sc.obtenir(Constat, "f_a") is not None
    with monde.db.tenant("cli_b", SYSTEME) as sc:
        assert sc.obtenir(Lot, "lot_b").statut == "pirate"


def test_insert_en_masse_refuse(monde):
    with monde.db.tenant("cli_b", SYSTEME) as sc, pytest.raises(AccesRefuse):
        sc.session.execute(insert(Lot).values(id="lot_x", tenant_id="cli_a"))


def test_ajout_direct_a_la_session_d_un_objet_etranger_refuse(monde):
    with pytest.raises(AccesRefuse), monde.db.tenant("cli_b", SYSTEME) as sc:
        sc.session.add(Lot(id="lot_y", tenant_id="cli_a"))
        sc.session.flush()


def test_session_brute_sans_perimetre_refusee(monde):
    s = monde.db.session()
    try:
        with pytest.raises(AccesRefuse):
            s.execute(select(Lot)).all()
        with pytest.raises(AccesRefuse):
            s.get(Constat, "f_a")
        s.rollback()
        s.add(Lot(id="lot_z", tenant_id="cli_a"))
        with pytest.raises(AccesRefuse):
            s.flush()
    finally:
        s.rollback()
        s.close()


def test_session_liee_a_un_client_ne_peut_pas_servir_a_un_autre(monde):
    s = monde.db.session()
    try:
        TenantScope(s, "cli_a", SYSTEME)
        with pytest.raises(AccesRefuse):
            TenantScope(s, "cli_b", SYSTEME)
    finally:
        s.close()


def test_client_inconnu_ou_vide(monde):
    for t in ("cli_inexistant", "", None):
        s = monde.db.session()
        try:
            with pytest.raises(AccesRefuse):
                TenantScope(s, t, SYSTEME)  # type: ignore[arg-type]
        finally:
            s.close()


# --- rôles -------------------------------------------------------------------------------------------


def test_utilisateur_client_ne_peut_ouvrir_autre_client(monde):
    admin_a = monde.acteurs["admin_a"]
    with pytest.raises(AccesRefuse), monde.db.tenant("cli_b", admin_a):
        pass
    # acteur forgé : se dit rattaché à B mais n'est pas membre de B
    faux = Acteur(admin_a.id, Role.client_admin, "cli_b")
    with pytest.raises(AccesRefuse), monde.db.tenant("cli_b", faux):
        pass
    # rôle forgé : lecteur qui se prétend administrateur
    lecteur = monde.acteurs["lecteur_a"]
    with pytest.raises(AccesRefuse), monde.db.tenant("cli_a", Acteur(lecteur.id, Role.client_admin, "cli_a")):
        pass


def test_fondateur_ne_peut_pas_contourner_operator_scope(monde):
    with pytest.raises(AccesRefuse), monde.db.tenant("cli_a", FONDATEUR):
        pass


def test_operator_scope_reserve_au_fondateur_et_audite(monde):
    with pytest.raises(AccesRefuse), monde.db.operateur(monde.acteurs["admin_a"]):
        pass
    with monde.db.operateur(FONDATEUR) as op:
        with pytest.raises(AccesRefuse):
            op.client("cli_a", "  ")
        avant = len([e for e in op.journal() if e.action == "acces_admin" and e.tenant_id == "cli_a"])
        sc = op.client("cli_a", "vérification d'un constat")
        assert sc.obtenir(Lot, "lot_a").id == "lot_a"
        sc.modifier(Lot, "lot_a", statut="en_cours")
    with monde.db.operateur(FONDATEUR) as op:
        entrees = op.journal()
        assert len([e for e in entrees if e.action == "acces_admin" and e.tenant_id == "cli_a"]) == avant + 1
        modif = [e for e in entrees if e.action == "modifier" and e.target == "lots:lot_a"]
        assert modif and modif[0].actor == FONDATEUR.id
        assert op.verifier_journal() == []


def test_session_operateur_lecture_seule(monde):
    with monde.db.operateur(FONDATEUR) as op:
        lot = op.session.execute(select(Lot).where(Lot.id == "lot_a")).scalar_one()
        lot.statut = "pirate"
        with pytest.raises(AccesRefuse):
            op.session.flush()
        op.session.rollback()
        with pytest.raises(AccesRefuse):
            op.session.execute(update(Lot).values(statut="x"))
        op.rollback()


def test_lecteur_ne_peut_rien_ecrire(monde):
    lecteur = monde.acteurs["lecteur_a"]
    with monde.db.tenant("cli_a", lecteur) as sc:
        assert sc.obtenir(Lot, "lot_a")
        for tentative in (
            lambda: sc.ajouter(Lot(id="lot_l")),
            lambda: sc.modifier(Lot, "lot_a", statut="x"),
            lambda: sc.supprimer(Lot, "lot_a"),
            lambda: sc.creer_lot("lot_l2"),
        ):
            with pytest.raises(AccesRefuse):
                tentative()


def test_admin_client_ne_peut_pas_ecrire_constats_ni_valider(monde):
    admin = monde.acteurs["admin_a"]
    with monde.db.tenant("cli_a", admin) as sc:
        with pytest.raises(AccesRefuse):
            sc.ajouter(Constat(id="f_faux", dossier_id="dos_a", dossier_version=1, controle_id="C1",
                               niveau="ecart_certain", statut_validation="valide"))
        with pytest.raises(AccesRefuse):
            sc.modifier(Constat, "fv_a", statut_validation="valide")
        with pytest.raises(AccesRefuse):
            sc.valider_constat("fv_a", "valide")
        with pytest.raises(AccesRefuse):
            sc.ajouter(Grille(id="g@v1", grille_id="g", version=1, statut="validee"))
        with pytest.raises(AccesRefuse):
            sc.modifier(Grille, "grl_a@v1", statut="validee")
        with pytest.raises(AccesRefuse):
            sc.valider_grille("grl_a", 1)
        with pytest.raises(AccesRefuse):
            sc.enregistrer_usage_ia(cout_eur=Decimal("0"), mois="2026-09")
        # brouillon de grille autorisé
        sc.ajouter(Grille(id="g@v1", grille_id="g", version=1, statut="brouillon"))


def test_client_ne_voit_que_constats_publies_et_jamais_resultats_bruts(monde):
    lecteur = monde.acteurs["lecteur_a"]
    with monde.db.tenant("cli_a", lecteur) as sc:
        assert sc.constats() == []
        with pytest.raises(AccesRefuse):
            sc.obtenir(Constat, "f_a")
        with pytest.raises(AccesRefuse):
            sc.lister(Resultat)
        assert sc.session.execute(select(Constat)).scalars().all()  # filtre tenant seulement…
    with monde.db.operateur(FONDATEUR) as op:
        op.client("cli_a", "validation").valider_constat("f_a", "valide", "vérifié")
    with monde.db.tenant("cli_a", lecteur) as sc:
        assert [c.id for c in sc.constats()] == ["f_a"]


def test_append_only_non_modifiable(monde):
    with monde.db.tenant("cli_a", SYSTEME) as sc:
        with pytest.raises(AccesRefuse):
            sc.modifier(EvenementRecouvrement, "evt_a", vers="credite")
        with pytest.raises(AccesRefuse):
            sc.supprimer(AiUsage, monde.ids["cli_a"]["AiUsage"])
    with pytest.raises(AccesRefuse), monde.db.tenant("cli_a", SYSTEME) as sc:
        evt = sc.obtenir(EvenementRecouvrement, "evt_a")
        evt.vers = "credite"
        sc.flush()


def test_outbox_plateforme_invisible_des_clients(monde):
    with monde.db.transaction_systeme() as s:
        s.add(Outbox(id="out_plateforme", tenant_id=None, kind="post_linkedin", cree_par="tests"))
    with monde.db.tenant("cli_a", SYSTEME) as sc:
        ids = {o.id for o in sc.sorties()}
    assert ids == {"out_a"}


# --- coffre, clés d'API -----------------------------------------------------------------------------------


def test_coffre_cle_par_client(monde, tmp_path):
    v = monde.vault
    sha = v.deposer("cli_a", b"secret commercial FICTIF")
    src = v._chemin("cli_a", sha, "fichiers")
    dst = v._chemin("cli_b", sha, "fichiers")
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_bytes(src.read_bytes())  # copie du blob chiffré dans le coffre de B
    with pytest.raises(ErreurIntegrite):
        v.lire("cli_b", sha)


@pytest.mark.parametrize("tenant,sha", [
    ("../cli_a", "a" * 64), ("cli_a/../cli_b", "a" * 64), ("/etc", "a" * 64), ("cli_b", "../" * 3 + "x"),
    ("cli_b", "A" * 64), ("cli_b", "a" * 63), (".", "a" * 64), ("", "a" * 64),
])
def test_coffre_traversee_impossible(monde, tenant, sha):
    with pytest.raises(ErreurCoffre):
        monde.vault.lire(tenant, sha)


def test_cle_api_rattachee_a_son_client(monde):
    with monde.db.tenant("cli_a", monde.acteurs["admin_a"]) as sc:
        cree = creer_cle_api(sc, "intégration ERP FICTIVE")
    acteur = verifier_cle_api(monde.db, cree.cle)
    assert acteur is not None and acteur.tenant_id == "cli_a"
    with pytest.raises(AccesRefuse), monde.db.tenant("cli_b", acteur):
        pass


# --- règle d'architecture : pas de session brute hors du stockage ------------------------------------------

_INTERDITS = re.compile(
    r"session\.query\(|\bselect\(|\.execute\(|\bsessionmaker\(|\bcreate_engine\(|\bSession\(|"
    r"\.session_systeme\(|sqlalchemy"
)


def test_pas_de_session_brute_hors_storage():
    racine = Path(__file__).resolve().parents[2] / "src" / "controldone"
    fautes = []
    for p in sorted(racine.rglob("*.py")):
        if "storage" in p.relative_to(racine).parts:
            continue
        for n, ligne in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
            code = ligne.split("#", 1)[0]
            if _INTERDITS.search(code):
                fautes.append(f"{p.relative_to(racine)}:{n}: {ligne.strip()}")
    assert fautes == [], "accès base hors de controldone.storage :\n" + "\n".join(fautes)
