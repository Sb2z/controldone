"""Couverture des services d'administration du fondateur (``services.admin``, bloc O4, D-4901) : réservés au
fondateur, saisies refusées (raison sociale, courriel, rôle, SIREN), import de grilles mal formées (CSV, JSON),
clés d'API. Toute saisie refusée donne ``RequeteInvalide`` (400), jamais une erreur 500. Données fictives."""

from __future__ import annotations

import json
from decimal import Decimal

import pytest
from aides_plateforme import FONDATEUR, SYSTEME

from controldone.auth.motdepasse import hacher_mot_de_passe
from controldone.auth.roles import Role
from controldone.services import admin
from controldone.services.plateforme import Interdit, Plateforme, RequeteInvalide
from controldone.storage import AccesRefuse
from controldone.storage.comptes import creer_utilisateur, utilisateur_par_email
from controldone.storage.models import Entite, Grille, Membership, Tenant


@pytest.fixture
def pf(monde):
    return Plateforme(db=monde.db, vault=monde.vault, cles_maitresses=[])


# --- réservé au fondateur ---------------------------------------------------------------------------------------


@pytest.mark.parametrize("nom", ["admin_a", "lecteur_a", "systeme"])
def test_services_reserves_au_fondateur(pf, monde, nom):
    acteur = monde.acteurs[nom]
    with pytest.raises(Interdit):
        admin.creer_client(pf, acteur, "CLIENT FICTIF")
    with pytest.raises(Interdit):
        admin.creer_utilisateur_client(pf, acteur, "cli_a", "x@exemple-fictif.test", "client_lecteur")
    with pytest.raises(Interdit):
        admin.tableau_de_bord(pf, acteur)
    with pytest.raises(Interdit):
        admin.fiche_client(pf, acteur, "cli_a")


# --- clients ----------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("raison", ["", "   ", None, "x" * 301])
def test_creer_client_raison_sociale_invalide(pf, raison):
    with pytest.raises(RequeteInvalide, match="raison sociale"):
        admin.creer_client(pf, FONDATEUR, raison)


def test_creer_client_offre_inconnue(pf):
    with pytest.raises(RequeteInvalide, match="offre"):
        admin.creer_client(pf, FONDATEUR, "CLIENT FICTIF", offre="premium")


@pytest.mark.parametrize("plafond", ["-1", "abc", "10000.01", "NaN", "1e3"])
def test_creer_client_plafond_invalide(pf, plafond):
    with pytest.raises(RequeteInvalide):
        admin.creer_client(pf, FONDATEUR, "CLIENT FICTIF", plafond=plafond)


def test_creer_client_identifiant_derive_et_demo(pf):
    tid = admin.creer_client(
        pf, FONDATEUR, "  Société Générale d'Import FICTIF  ", plafond="12,50", demo=True
    )
    assert tid.startswith("cli_soci_t_g_n_rale_d_import_") and len(tid.rsplit("_", 1)[1]) == 6
    tid2 = admin.creer_client(pf, FONDATEUR, "+++")  # aucun caractère retenu : nom générique
    assert tid2.startswith("cli_client_")
    with pf.db.transaction_systeme() as s:
        t = s.get(Tenant, tid)
        assert t.plafond_cout_ia_mensuel_eur == Decimal("12.50") and t.reglages == {"demo": True}


# --- comptes ----------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "email", ["", "sans-arobase", "a@b@c", "deux mots@exemple-fictif.test", "x" * 65 + "@exemple-fictif.test"]
)
def test_creer_utilisateur_courriel_invalide(pf, email):
    with pytest.raises(RequeteInvalide, match="adresse"):
        admin.creer_utilisateur_client(pf, FONDATEUR, "cli_a", email, "client_lecteur")


@pytest.mark.parametrize(
    "role, motif", [("dieu", "inconnu"), ("fondateur", "client attendu"), ("systeme", "client")]
)
def test_creer_utilisateur_role_refuse(pf, role, motif):
    with pytest.raises(RequeteInvalide, match=motif):
        admin.creer_utilisateur_client(pf, FONDATEUR, "cli_a", "nouveau@exemple-fictif.test", role)


def test_creer_utilisateur_nouveau_puis_rattache_ailleurs(pf):
    mdp = admin.creer_utilisateur_client(
        pf, FONDATEUR, "cli_a", "  Nouveau@Exemple-Fictif.test ", "client_lecteur", nom="  " + "N" * 300
    )
    assert len(mdp) >= 12
    u = utilisateur_par_email(pf.db, "nouveau@exemple-fictif.test")
    assert u is not None
    # compte existant : rattaché au client B sans nouveau mot de passe
    assert (
        admin.creer_utilisateur_client(pf, FONDATEUR, "cli_b", "nouveau@exemple-fictif.test", "client_admin")
        == ""
    )
    with pf.db.tenant("cli_b", SYSTEME) as sc:
        assert any(m.user_id == u.id and m.role == "client_admin" for m in sc.lister(Membership))


def test_compte_fondateur_jamais_rattache_a_un_client(pf):
    creer_utilisateur(
        pf.db,
        user_id="usr_fondateur",
        email="fondateur@exemple-fictif.test",
        mot_de_passe_hash=hacher_mot_de_passe("phrase-FICTIVE-123"),
        role=Role.fondateur,
        acteur=FONDATEUR,
    )
    with pytest.raises(RequeteInvalide, match="ne peut pas"):
        admin.creer_utilisateur_client(
            pf, FONDATEUR, "cli_a", "fondateur@exemple-fictif.test", "client_admin"
        )
    with pf.db.tenant("cli_a", SYSTEME) as sc:
        assert "usr_fondateur" not in {m.user_id for m in sc.lister(Membership)}


def test_creer_utilisateur_client_inconnu(pf):
    with pytest.raises(AccesRefuse):
        admin.creer_utilisateur_client(pf, FONDATEUR, "cli_zz", "z@exemple-fictif.test", "client_lecteur")


# --- entités et transitaires -------------------------------------------------------------------------------------


def test_ajouter_entite_saisies(monde):
    with monde.db.tenant("cli_a", monde.acteurs["admin_a"]) as sc:
        with pytest.raises(RequeteInvalide, match="raison sociale"):
            admin.ajouter_entite(sc, "  ")
        for siren in ("12345678", "1234567890", "12345678A"):
            with pytest.raises(RequeteInvalide, match="SIREN"):
                admin.ajouter_entite(sc, "ENTITE FICTIF", siren=siren)
        e = admin.ajouter_entite(
            sc, "ENTITE FICTIF", tva="fr 40 303 265 045", siren=" 303265045 ", eori=" fr123 ", alias="a; ;b"
        )
        assert e.tva == "FR40303265045"
        assert e.contenu["siren"] == "303265045" and e.contenu["eori"] == "FR123"
        assert e.contenu["alias"] == ["a", "b"]
        # même raison sociale et même TVA : même identifiant (mise à jour, pas de doublon)
        assert admin.ajouter_entite(sc, "ENTITE FICTIF", tva="FR40303265045").id == e.id


def test_entite_tva_ecrite_autrement_pas_de_doublon(monde):
    """Régression D-4902 : l'identifiant était dérivé de la TVA **saisie** ; « fr 40 303 265 045 » puis
    « FR40303265045 » créaient deux entités de même TVA."""
    with monde.db.tenant("cli_a", monde.acteurs["admin_a"]) as sc:
        a = admin.ajouter_entite(sc, "ENTITE FICTIF", tva="fr 40 303 265 045")
        b = admin.ajouter_entite(sc, "ENTITE FICTIF", tva="FR40303265045")
        c = admin.ajouter_entite(sc, "ENTITE FICTIF", tva="FR 40.303.265.045")
        assert a.id == b.id == c.id
        assert sc.compter(Entite, tva="FR40303265045") == 1


def test_ajouter_transitaire_saisies(monde):
    with monde.db.tenant("cli_a", monde.acteurs["admin_a"]) as sc:
        with pytest.raises(RequeteInvalide, match="nom"):
            admin.ajouter_transitaire(sc, "")
        t = admin.ajouter_transitaire(
            sc, "TRANSIT FICTIF", alias=";".join(f"a{i}" for i in range(30)), adresse="  ", contact="c" * 600
        )
        assert len(t.contenu["alias"]) == 20 and t.contenu["adresse"] is None
        assert len(t.contenu["contact_reclamation"]) == 500


def test_lecteur_ne_peut_pas_ajouter(monde):
    with monde.db.tenant("cli_a", monde.acteurs["lecteur_a"]) as sc, pytest.raises(AccesRefuse):
        admin.ajouter_transitaire(sc, "TRANSIT FICTIF")


# --- grilles ------------------------------------------------------------------------------------------------------

CSV_OK = (
    "code_poste;nature;mode;prix;franchise_jours;inclus;unite_base;libelles_reconnus\n"
    "DEDOUANEMENT;honoraires;forfait;45,00;;;;Dédouanement|Frais de dossier\n"
    ";;;;;;;\n"
    "MAGASINAGE;magasinage;par_jour;12;3;1;jour;Magasinage\n"
    "STOCKAGE;magasinage;par_palette;5;;;;Stockage\n"
)


def _importer(monde, contenu, nom="grille.csv", acteur="admin_a", **kw):
    with monde.db.tenant("cli_a", monde.acteurs[acteur]) as sc:
        return admin.importer_grille(sc, contenu, nom, transitaire_id=kw.pop("transitaire_id", "tra_a"), **kw)


def test_grille_csv_valide_en_brouillon(monde):
    g = _importer(monde, ("﻿" + CSV_OK).encode(), reference="  REF FICTIVE  ", valide_du="2026-01-01")
    assert (g.statut, g.version, g.reference) == ("brouillon", 1, "REF FICTIVE")
    postes = {p["code_poste"]: p for p in g.contenu["postes"]}
    assert set(postes) == {"DEDOUANEMENT", "MAGASINAGE"}  # ligne sans code ignorée, mode inconnu écarté
    assert postes["MAGASINAGE"]["franchise_jours"] == 3
    assert g.contenu["prestations_hors_grille"] == "tolerees"
    assert _importer(monde, CSV_OK.encode(), reference="REF FICTIVE").version == 2  # nouvelle version


def test_grille_csv_sans_separateur_reconnu(monde):
    """Le renifleur échoue : point-virgule par défaut, sans modifier ``csv.excel`` pour tout le processus."""
    import csv

    with pytest.raises(RequeteInvalide):
        _importer(monde, b"code_poste\n")
    assert csv.excel.delimiter == ","


@pytest.mark.parametrize(
    "contenu, motif",
    [
        (b"\xff\xfe\x00", "UTF-8"),
        (b"code_poste;prix\nX;\x00" + b"a" * 200_000 + b"\n", "illisible|invalide|aucun"),
        ("code_poste;prix\n" + "".join(f"P{i};1\n" for i in range(600)), "trop longue"),
        ("code_poste;prix\nX;-5\n", "prix"),
        ("code_poste;prix\nX;abc\n", "prix"),
        ("code_poste;franchise_jours\nX;trois\n", "entier"),
        ("code_poste;prix\n;1\n", "aucun poste"),
        (b"x" * (2 * 1024 * 1024 + 1), "volumineux"),
    ],
    ids=["binaire", "nul", "500", "negatif", "texte", "entier", "vide", "taille"],
)
def test_grille_csv_refusee(monde, contenu, motif):
    if isinstance(contenu, str):
        contenu = contenu.encode()
    with pytest.raises(RequeteInvalide, match=motif):
        _importer(monde, contenu)


@pytest.mark.parametrize(
    "contenu, motif",
    [
        ("{pas du json", "JSON illisible"),
        ("[1, 2]", "objet JSON"),
        (
            '{"postes": [{"code_poste": "X", "mode": "forfait"}], "valide_du": "pas-une-date"}',
            "grille invalide",
        ),
        ('{"postes": [{"code_poste": "X", "mode": "a_la_tete"}]}', "aucun poste"),
    ],
)
def test_grille_json_refusee(monde, contenu, motif):
    with pytest.raises(RequeteInvalide, match=motif):
        _importer(monde, contenu.encode(), nom="grille.JSON")


def test_grille_json_ne_choisit_ni_statut_ni_client(monde):
    data = {
        "id": "grl_force",
        "client_id": "cli_b",
        "statut": "validee",
        "grille_id": "grl_json",
        "postes": [{"code_poste": "DED", "nature": "honoraires", "mode": "forfait", "prix": "40"}],
    }
    g = _importer(
        monde, json.dumps(data).encode(), nom="g.txt", hors_grille="interdites", valide_au="2026-12-31"
    )
    assert (g.tenant_id, g.statut, g.grille_id) == ("cli_a", "brouillon", "grl_json")
    assert g.contenu["prestations_hors_grille"] == "interdites"


def test_grille_transitaire_d_un_autre_client(monde):
    with pytest.raises(AccesRefuse):
        _importer(monde, CSV_OK.encode(), transitaire_id="tra_b")
    with monde.db.tenant("cli_a", SYSTEME) as sc:
        assert sc.compter(Grille) == 1


# --- clés d'API et lectures -------------------------------------------------------------------------------------


def test_creer_cle_roles(monde):
    with monde.db.tenant("cli_a", monde.acteurs["admin_a"]) as sc:
        with pytest.raises(RequeteInvalide, match="inconnu"):
            admin.creer_cle(sc, "cle", role="root")
        with pytest.raises(RequeteInvalide, match="client attendu"):
            admin.creer_cle(sc, "cle", role="fondateur")
        cle = admin.creer_cle(sc, "   ", role="client_lecteur")
    assert cle.prefixe and cle.prefixe in cle.cle


def test_ratio_ia():
    ligne = admin.LigneClient("c", "C FICTIF", "diagnostic", False, True, {}, Decimal("7.5"), Decimal("10"))
    assert ligne.ratio_ia == 75
    ligne.plafond = Decimal(0)
    assert ligne.ratio_ia == 0


def test_tableau_de_bord_et_fiche(pf):
    tdb = admin.tableau_de_bord(pf, FONDATEUR)
    assert {c.id for c in tdb["clients"]} == {"cli_a", "cli_b"}
    assert tdb["totaux"]["dossiers"] == 2
    fiche = admin.fiche_client(pf, FONDATEUR, "cli_a", lire_dossiers=lambda sc: ["page FICTIVE"])
    assert fiche["dossiers"] == ["page FICTIVE"]
    assert {m["id"] for m in fiche["membres"]} == {"usr_admin_a", "usr_lecteur_a"}
    assert [t["id"] for t in fiche["transitaires"]] == ["tra_a"]
