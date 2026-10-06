"""Bloc I3 — interface : tableaux de bord en SQL, langue par compte, bandeau des alertes graves, historique des
notifications, coût IA par client. Données FICTIVES."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from aides_web import ADMIN_A, ADMIN_B, LECTEUR_A, connecter, connecter_client, connecter_fondateur, poster
from sqlalchemy import create_engine, inspect, text
from test_listes_sql import _grossir

from controldone.auth.roles import Acteur, Role
from controldone.calendrier import mois_paris
from controldone.services.lecture import constats_courants, hors_totaux, lister_dossiers
from controldone.storage.alertes import emettre_alerte
from controldone.storage.comptes import definir_langue, utilisateur, utilisateur_par_email
from controldone.storage.erreurs import AccesRefuse
from controldone.storage.migrations import MIGRATIONS, appliquer
from controldone.storage.models import Alerte, Membership, NotificationAlerte, User
from controldone.web.graphes import donnees_client
from controldone.web.i18n import COOKIE_LANGUE
from controldone.web.listes_sql import indicateurs

A, B = "demo_ateliers", "demo_nord"


@pytest.fixture
def gros(monde):
    _grossir(monde.pf, A, 90)
    _grossir(monde.pf, B, 40)
    return monde


def _acteurs(pf):
    with pf.db.transaction_systeme() as s:
        membres = {m.role: m.user_id for m in s.query(Membership).filter(Membership.tenant_id == A)}
    return [Acteur(membres[r], Role(r), A) for r in ("client_admin", "client_lecteur") if r in membres]


def _reference(scope):
    """Calcul d'avant le bloc I3 (listes complètes en Python), pris comme référence."""
    dossiers = lister_dossiers(scope)
    return {
        "dossiers": len(dossiers),
        "constats": len(constats_courants(scope)),
        "proposes": sum(d.nb_proposes for d in dossiers),
        "certain": sum((d.recouvrable_certain for d in dossiers), Decimal(0)),
        "a_verifier": sum((d.recouvrable_a_verifier for d in dossiers), Decimal(0)),
    }


def _graphes_reference(scope):
    from controldone.storage.models import Dossier

    dossiers = {d.id: d for d in scope.lister(Dossier)}
    mois: dict[str, Decimal] = {}
    familles: dict[str, Decimal] = {}
    for c in constats_courants(scope):
        if c.statut_validation != "valide":
            continue
        familles[(c.controle_id or "?")[0]] = familles.get((c.controle_id or "?")[0], Decimal(0)) + 1
        if hors_totaux(c) or c.niveau != "ecart_certain" or c.nature_montant != "recouvrable":
            continue
        if c.montant_en_jeu and c.montant_en_jeu > 0:
            m = mois_paris(dossiers[c.dossier_id].cree_le)
            mois[m] = mois.get(m, Decimal(0)) + c.montant_en_jeu
    return mois, familles


# --- 1. tableaux de bord en SQL ------------------------------------------------------------------------------------


def test_indicateurs_sql_identiques_au_calcul_python(gros):
    acteurs = _acteurs(gros.pf)
    assert acteurs
    for acteur in acteurs:
        with gros.pf.db.tenant(A, acteur, lecture=True) as scope:
            ind = indicateurs(scope)
            ref = _reference(scope)
            assert {k: getattr(ind, k) for k in ref} == ref, acteur.role
            assert ind.proposes == 0  # rôle client : constats publiés seuls
            assert all(isinstance(x, Decimal) for x in (ind.certain, ind.a_verifier))
            mois, familles = _graphes_reference(scope)
            g_mois, g_fam, _g_tr = donnees_client(scope, ind.lignes)
            assert sum(b.valeur for b in g_mois.barres) == sum(mois.values())  # dossiers fictifs récents
            assert sorted(b.valeur for b in g_fam.barres) == sorted(familles.values())
    fondateur = Acteur("fondateur-test", Role.fondateur)
    with gros.pf.db.operateur(fondateur) as op:
        scope = op.client(A, "test indicateurs", lecture=True)
        ind = indicateurs(scope)
        ref = _reference(scope)
        assert {k: getattr(ind, k) for k in ref} == ref
        assert ind.proposes > 0


def test_indicateurs_cloisonnes(monde):
    """Grossir le client B ne change rien aux indicateurs de A."""
    acteur = _acteurs(monde.pf)[0]
    with monde.pf.db.tenant(A, acteur, lecture=True) as scope:
        avant = indicateurs(scope)
    _grossir(monde.pf, B, 30)
    with monde.pf.db.tenant(A, acteur, lecture=True) as scope:
        apres = indicateurs(scope)
        assert (avant.dossiers, avant.constats, avant.certain) == (
            apres.dossiers,
            apres.constats,
            apres.certain,
        )
        assert apres.dossiers == len(lister_dossiers(scope))


def test_tableau_client_et_fiche_fondateur(gros):
    c = gros.client()
    connecter_client(c, gros, ADMIN_A)
    r = c.get("/espace")
    assert r.status_code == 200
    acteur = _acteurs(gros.pf)[0]
    with gros.pf.db.tenant(A, acteur, lecture=True) as scope:
        n = len(lister_dossiers(scope))
    assert f'<a href="/espace/dossiers">{n}</a>' in r.text
    assert r.text.count('<a href="/espace/dossiers/dos_') <= 8
    f = gros.client()
    connecter_fondateur(f, gros)
    r = f.get(f"/admin/clients/{A}")
    assert r.status_code == 200 and ">Dossiers<" in r.text and 'id="plafond-ia"' in r.text
    r = f.get(f"/admin/clients/{A}?q=FICTIF-0001")
    assert r.status_code == 200 and "1 dossier (filtré)." in r.text
    assert f.get(f"/admin/clients/{A}?statut=inconnu").status_code == 400


def test_tableau_client_cloisonne(gros):
    """Le tableau de bord de B ne montre aucune référence de dossier de A."""
    c = gros.client()
    connecter_client(c, gros, ADMIN_B)
    r = c.get("/espace")
    assert r.status_code == 200
    assert "dos_sql_demo_ateliers" not in r.text


def test_cout_ia_plafond_sur_la_fiche(monde):
    from controldone.jobs.couts import enregistrer_cout

    f = monde.client()
    connecter_fondateur(f, monde)
    r = f.get(f"/admin/clients/{A}")
    assert "Plafond atteint" not in r.text and "jauge" in r.text
    with monde.pf.db.tenant(A, Acteur.systeme("test-couts")) as scope:
        enregistrer_cout(scope, cout_eur=Decimal("500.00"), modele="modele-fictif")
    r = f.get(f"/admin/clients/{A}")
    assert "Plafond atteint : appels au modèle arrêtés" in r.text and "jauge-stop" in r.text


# --- 2. langue par compte ------------------------------------------------------------------------------------------


def _uid(monde, email):
    return utilisateur_par_email(monde.pf.db, email).id


def test_langue_enregistree_sur_le_compte_et_reprise_a_la_connexion(monde):
    c = monde.client()
    connecter_client(c, monde, ADMIN_A)
    assert utilisateur(monde.pf.db, _uid(monde, ADMIN_A)).langue is None
    r = c.get("/compte")
    assert r.status_code == 200 and 'id="t-langue"' in r.text
    r = poster(c, "/compte", "/compte/langue", {"langue": "en"})
    assert r.status_code == 303 and r.headers["location"] == "/compte"
    assert utilisateur(monde.pf.db, _uid(monde, ADMIN_A)).langue == "en"
    assert c.cookies.get(COOKIE_LANGUE) == "en"
    assert '<html lang="en">' in c.get("/compte").text
    # autre navigateur, sans cookie : la connexion repose la langue du compte
    d = monde.client()
    r = connecter(d, ADMIN_A, monde.comptes[ADMIN_A])
    assert r.status_code == 303 and "cd_langue=en" in r.headers.get("set-cookie", "")
    assert '<html lang="en">' in d.get("/espace").text
    # le bouton FR/EN de l'en-tête, connecté, enregistre aussi sur le compte
    r = poster(d, "/espace", "/preferences/langue", {"langue": "fr", "retour": "/espace"})
    assert r.status_code == 303 and utilisateur(monde.pf.db, _uid(monde, ADMIN_A)).langue == "fr"
    # valeur inconnue : refusée, rien d'enregistré
    r = poster(d, "/compte", "/compte/langue", {"langue": "de"})
    assert r.status_code == 303 and utilisateur(monde.pf.db, _uid(monde, ADMIN_A)).langue == "fr"
    # un autre compte n'est pas touché
    assert utilisateur(monde.pf.db, _uid(monde, LECTEUR_A)).langue is None


def test_langue_sans_session_reste_un_cookie(monde):
    c = monde.client()
    r = poster(c, "/connexion", "/preferences/langue", {"langue": "en", "retour": "/connexion"})
    assert r.status_code == 303 and c.cookies.get(COOKIE_LANGUE) == "en"
    assert all(utilisateur(monde.pf.db, _uid(monde, e)).langue is None for e in (ADMIN_A, LECTEUR_A))
    # sans préférence de compte, la connexion ne touche pas au cookie du navigateur
    r = connecter(c, ADMIN_A, monde.comptes[ADMIN_A])
    assert "cd_langue" not in r.headers.get("set-cookie", "")
    assert '<html lang="en">' in c.get("/espace").text


def test_definir_langue_reservee_au_compte_lui_meme(monde):
    uid = _uid(monde, ADMIN_A)
    autre = Acteur(_uid(monde, LECTEUR_A), Role.client_lecteur, A)
    with pytest.raises(AccesRefuse):
        definir_langue(monde.pf.db, uid, "en", acteur=autre)
    with pytest.raises(AccesRefuse):
        definir_langue(monde.pf.db, uid, "en", acteur=Acteur("fondateur", Role.fondateur))
    with pytest.raises(ValueError):
        definir_langue(monde.pf.db, uid, "xx", acteur=Acteur(uid, Role.client_admin, A))
    definir_langue(monde.pf.db, uid, "en", acteur=Acteur(uid, Role.client_admin, A))
    assert utilisateur(monde.pf.db, uid).langue == "en"


def test_migration_langue_sur_une_base_existante(tmp_path):
    url = f"sqlite:///{tmp_path}/ancienne.db"
    moteur = create_engine(url)
    with moteur.begin() as conn:  # table users d'avant le bloc I3, étapes 1 à 4 déjà inscrites
        conn.execute(
            text(
                "CREATE TABLE users (id VARCHAR(64) PRIMARY KEY, email VARCHAR(320), role VARCHAR(32), "
                "mot_de_passe_hash VARCHAR(300))"
            )
        )
        conn.execute(
            text("INSERT INTO users VALUES ('usr_fictif', 'fictif@example.test', 'client_admin', 'x')")
        )
        conn.execute(
            text(
                "CREATE TABLE schema_version (version INTEGER PRIMARY KEY, nom VARCHAR(100), "
                "applique_le DATETIME)"
            )
        )
        for m in MIGRATIONS:
            if m.nom != "langue_utilisateur":
                conn.execute(
                    text("INSERT INTO schema_version VALUES (:v, :n, '2026-10-01')"),
                    {"v": m.version, "n": m.nom},
                )
    faites = appliquer(moteur)
    assert [m.nom for m in faites] == ["langue_utilisateur"]
    assert "langue" in {c["name"] for c in inspect(moteur).get_columns("users")}
    with moteur.connect() as conn:
        assert conn.execute(text("SELECT langue FROM users")).scalar() is None
    assert appliquer(moteur) == []  # idempotente
    moteur.dispose()


# --- 3. bandeau des alertes graves ---------------------------------------------------------------------------------


def _alertes(monde, *kinds):
    with monde.pf.db.transaction_systeme() as s:
        for i, k in enumerate(kinds):
            emettre_alerte(s, cle=f"test:{k}:{i}", kind=k, message=f"Alerte fictive {k}.")


def _non_lues(monde):
    with monde.pf.db.transaction_systeme() as s:
        return sorted(k for (k,) in s.query(Alerte.kind).filter(Alerte.lue_le.is_(None)))


def test_bandeau_alertes_graves(monde):
    _alertes(
        monde,
        "sauvegarde_echec",
        "sauvegarde_echec",
        "sauvegarde_hors_site_echec",
        "job_mort",
        "volume_non_chiffre",
        "cout_ia_plafond",
        "cout_ia_alerte",
        "litige_inactif",
    )
    f = monde.client()
    connecter_fondateur(f, monde)
    r = f.get("/admin")
    assert 'class="bandeau-alertes"' in r.text
    bandeau = r.text.split('class="bandeau-alertes"')[1].split("</section>")[0]
    for lib in (
        "Sauvegarde en échec",
        "Copie hors site en échec",
        "Tâche morte",
        "Volume de la base non chiffré",
        "Plafond IA atteint",
    ):
        assert lib in bandeau, lib
    assert "Coût IA 80 %" not in bandeau and "Écart sans suite" not in bandeau
    assert "2 non lue(s)" in bandeau
    r = poster(f, "/admin", "/admin/alertes/bandeau/lues", {"kind": "sauvegarde_echec"})
    assert r.status_code == 303 and r.headers["location"] == "/admin"
    assert "sauvegarde_echec" not in _non_lues(monde)
    # un type hors bandeau n'est jamais marqué par ce formulaire
    poster(f, "/admin", "/admin/alertes/bandeau/lues", {"kind": "cout_ia_alerte"})
    assert "cout_ia_alerte" in _non_lues(monde)
    r = poster(f, "/admin", "/admin/alertes/bandeau/lues", {"kind": "tous"})
    assert r.status_code == 303
    assert _non_lues(monde) == ["cout_ia_alerte", "litige_inactif"]
    assert 'class="bandeau-alertes"' not in f.get("/admin").text
    with monde.pf.db.transaction_systeme() as s:
        from controldone.storage.models import AuditLog

        assert s.query(AuditLog).filter(AuditLog.action == "alerte_lue").count() == 6


def test_bandeau_refuse_sans_csrf_et_aux_clients(monde):
    _alertes(monde, "job_mort")
    f = monde.client()
    connecter_fondateur(f, monde)
    r = f.post("/admin/alertes/bandeau/lues", data={"kind": "tous"}, follow_redirects=False)
    assert r.status_code in (400, 403)
    c = monde.client()
    connecter_client(c, monde, ADMIN_A)
    r = poster(c, "/espace", "/admin/alertes/bandeau/lues", {"kind": "tous"})
    assert r.status_code in (403, 404)
    assert _non_lues(monde) == ["job_mort"]


# --- 4. historique des notifications -------------------------------------------------------------------------------


def test_historique_des_notifications(monde, monkeypatch):
    monkeypatch.setenv("CONTROLDONE_NOTIF_WEBHOOK_URL", "https://hooks.example.test/jeton-secret-FICTIF")
    t0 = datetime(2026, 10, 1, 8, 0, tzinfo=UTC)
    with monde.pf.db.transaction_systeme() as s:
        s.add(
            NotificationAlerte(
                cle="sauvegarde_echec:2026-10-01",
                kind="sauvegarde_echec",
                nombre=2,
                canaux="webhook,courriel",
                statut="envoyee",
                essais=1,
                cree_le=t0,
                envoyee_le=t0,
            )
        )
        s.add(
            NotificationAlerte(
                cle="job_mort:2026-10-02",
                kind="job_mort",
                nombre=1,
                canaux="courriel",
                statut="echec",
                essais=3,
                cree_le=t0 + timedelta(days=1),
            )
        )
        for i in range(30):
            s.add(
                NotificationAlerte(
                    cle=f"essai:2026-09-{i:02d}",
                    kind="essai",
                    nombre=1,
                    canaux="webhook",
                    statut="envoyee",
                    essais=1,
                    cree_le=t0 - timedelta(days=i + 1),
                    envoyee_le=t0 - timedelta(days=i + 1),
                )
            )
    f = monde.client()
    connecter_fondateur(f, monde)
    r = f.get("/admin/notifications")
    assert r.status_code == 200
    assert "jeton-secret-FICTIF" not in r.text and "hooks.example.test" not in r.text
    assert "1–25 sur 32" in r.text and "Sauvegarde en échec" in r.text and "Tâche morte" in r.text
    assert "En échec<" in r.text  # courriel : échec après le dernier succès
    assert "Mode test" in r.text  # hors production : rien n'est envoyé
    assert f.get("/admin/notifications?page=2").status_code == 200
    assert f.get("/admin/notifications?tri=-autre").status_code == 400
    assert 'href="/admin/notifications"' in f.get("/admin/alertes").text
    c = monde.client()
    connecter_client(c, monde, ADMIN_A)
    assert c.get("/admin/notifications").status_code in (403, 404)


def test_user_model_a_la_colonne_langue():
    assert "langue" in User.__table__.c


# --- 5. lecture par modèle de langage : opt-out du client (D-4007) -------------------------------------------------


def test_opt_out_lecture_llm_sur_la_fiche(monde):
    from controldone.jobs.couts import etat_plafond
    from controldone.storage.models import AuditLog

    f = monde.client()
    connecter_fondateur(f, monde)
    fiche = f"/admin/clients/{A}"
    assert 'name="llm_autorise" value="1" checked' in f.get(fiche).text
    r = poster(f, fiche, f"{fiche}/llm", {})  # case décochée
    assert r.status_code == 303
    assert etat_plafond(A, db=monde.pf.db).desactive is True
    assert etat_plafond(B, db=monde.pf.db).desactive is False
    page = f.get(fiche).text
    assert (
        "Désactivée pour ce client" in page
        and 'value="1" checked' not in page.split('id="lecture-llm"')[1][:900]
    )
    assert "Lecture par modèle désactivée" in f.get("/admin").text
    poster(f, fiche, f"{fiche}/llm", {"llm_autorise": "1"})
    assert etat_plafond(A, db=monde.pf.db).desactive is False
    with monde.pf.db.transaction_systeme() as s:
        assert (
            s.query(AuditLog).filter(AuditLog.action == "modifier_client", AuditLog.tenant_id == A).count()
            == 2
        )
    c = monde.client()
    connecter_client(c, monde, ADMIN_A)
    assert poster(c, "/espace", f"{fiche}/llm", {}).status_code in (403, 404)
    assert etat_plafond(A, db=monde.pf.db).desactive is False
