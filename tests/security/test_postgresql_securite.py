"""Limitation de débit partagée, révocations et sessions actives **sous PostgreSQL** (D-3201, D-3202, D-3603,
D-3610) : chemin ``SELECT … FOR UPDATE`` et nouvel essai sur conflit de clé, que la suite SQLite n'exerce pas.

Sautés sans ``CONTROLDONE_TEST_PG_URL`` (URL d'administration d'un serveur **jetable**, ex. celle qu'affiche
``scripts/pg_jetable.sh demarrer``) ; ``make test-pg-securite`` démarre ce serveur, lance ces tests et l'efface.
Chaque test travaille dans une base neuve, supprimée ensuite. Données fictives seulement."""

from __future__ import annotations

import os
import secrets
import threading

import pytest

from controldone.auth import GestionnaireSessions, LimiteurDebitPartage, RegistreRevocations, sel_debit
from controldone.auth.roles import Acteur, Role

pytestmark = pytest.mark.postgresql

URL_ADMIN = os.environ.get("CONTROLDONE_TEST_PG_URL", "")
SECRET = "secret-de-session-des-tests-postgresql-FICTIF-0123"
SEL = sel_debit([b"cle-maitresse-de-test-FICTIVE-0123456789abcdef="])
ACTEUR = Acteur("usr_fictif_pg", Role.client_admin, "demo_ateliers")

if not URL_ADMIN:
    pytest.skip(
        "CONTROLDONE_TEST_PG_URL absente (serveur PostgreSQL jetable : make test-pg-securite)",
        allow_module_level=True,
    )


class Horloge:
    def __init__(self, t: float = 1_800_000_000.0) -> None:
        self.t = t

    def __call__(self) -> float:
        return self.t


@pytest.fixture
def db():
    from sqlalchemy import create_engine, text
    from sqlalchemy.engine import make_url

    from controldone.storage import Database

    nom = f"cd_securite_{secrets.token_hex(4)}"
    admin = create_engine(URL_ADMIN, isolation_level="AUTOCOMMIT")
    with admin.connect() as cx:
        cx.execute(text(f'CREATE DATABASE "{nom}"'))
    d = Database(make_url(URL_ADMIN).set(database=nom).render_as_string(hide_password=False))
    assert not d.est_sqlite
    d.creer_schema()
    try:
        yield d
    finally:
        d.fermer()
        with admin.connect() as cx:
            cx.execute(text(f'DROP DATABASE IF EXISTS "{nom}" WITH (FORCE)'))
        admin.dispose()


def _autre(db):
    from controldone.storage import Database

    return Database(db.url)


def test_pg_limiteur_seuils_partage_et_recharge(db):
    h = Horloge()
    a = LimiteurDebitPartage("connexion_compte", 3, 1.0, db=db, sel=SEL, horloge=h)
    db2 = _autre(db)
    try:
        b = LimiteurDebitPartage("connexion_compte", 3, 1.0, db=db2, sel=SEL, horloge=h)
        assert [
            a.autoriser("a@exemple.test"),
            b.autoriser("a@exemple.test"),
            a.autoriser("a@exemple.test"),
            b.autoriser("a@exemple.test"),
        ] == [True, True, True, False]
        h.t += 1.0
        assert b.autoriser("a@exemple.test") and not a.autoriser("a@exemple.test")
        a.effacer("a@exemple.test")
        assert b.autoriser("a@exemple.test")
    finally:
        db2.fermer()


def test_pg_limiteur_atomique_sous_concurrence_et_premiere_insertion(db):
    """Six « processus » partent ensemble sur une clé **absente** : conflits d'insertion (clé primaire) rejoués,
    puis ``FOR UPDATE`` : exactement 20 jetons accordés sur 60 demandes."""
    autorises = []
    verrou = threading.Lock()
    depart = threading.Barrier(6)
    erreurs = []

    def essayer():
        base = _autre(db)
        try:
            local = LimiteurDebitPartage("connexion_ip", 20, 1e-6, db=base, sel=SEL)
            depart.wait()
            n = sum(local.autoriser("192.0.2.1") for _ in range(10))
            with verrou:
                autorises.append(n)
        except Exception as exc:  # pragma: no cover - affiché par l'assertion
            erreurs.append(repr(exc))
        finally:
            base.fermer()

    fils = [threading.Thread(target=essayer) for _ in range(6)]
    for f in fils:
        f.start()
    for f in fils:
        f.join()
    assert not erreurs
    assert sum(autorises) == 20
    assert not LimiteurDebitPartage("connexion_ip", 20, 1e-6, db=db, sel=SEL).autoriser("192.0.2.1")


def test_pg_limiteur_table_bornee(db):
    from controldone.storage.securite import CompteurDebit

    h = Horloge()
    lim = LimiteurDebitPartage("api", 2, 2.0, db=db, sel=SEL, horloge=h, max_lignes=50, purge_toutes_s=0)
    for i in range(200):
        lim.autoriser(f"api:{i:06x}")
    with db.transaction_systeme() as s:
        assert s.query(CompteurDebit).count() <= 51
    h.t += 5
    lim.autoriser("api:dernier")
    with db.transaction_systeme() as s:
        assert s.query(CompteurDebit).count() == 1


def test_pg_revocations_entre_processus(db):
    h = Horloge()
    a = GestionnaireSessions(SECRET, horloge=h, registre=RegistreRevocations(db, horloge=h))
    db2 = _autre(db)
    try:
        b = GestionnaireSessions(SECRET, horloge=h, registre=RegistreRevocations(db2, horloge=h))
        j = a.emettre(ACTEUR)
        d = b.lire(j)
        a.revoquer(d.sid, debut=d.debut)
        a.revoquer(d.sid, debut=d.debut)  # deuxième révocation du même sid : mise à jour, pas de conflit
        with pytest.raises(PermissionError):
            b.lire(j)
        autre = a.emettre(ACTEUR)
        h.t += 10
        coupure = b.revoquer_utilisateur(ACTEUR.id)
        with pytest.raises(PermissionError):
            a.lire(autre)
        assert a.lire(b.emettre(ACTEUR)).debut >= coupure
    finally:
        db2.fermer()


def test_pg_revocations_concurrentes_du_meme_utilisateur(db):
    """Plusieurs processus révoquent en même temps le même utilisateur (première insertion de ``user:…``)."""
    h = Horloge()
    depart = threading.Barrier(5)
    erreurs = []

    def revoquer(i: int):
        base = _autre(db)
        try:
            g = GestionnaireSessions(SECRET, horloge=lambda: h.t + i, registre=RegistreRevocations(base))
            depart.wait()
            g.revoquer_utilisateur(ACTEUR.id)
        except Exception as exc:  # pragma: no cover
            erreurs.append(repr(exc))
        finally:
            base.fermer()

    fils = [threading.Thread(target=revoquer, args=(i,)) for i in range(5)]
    for f in fils:
        f.start()
    for f in fils:
        f.join()
    assert not erreurs
    from controldone.storage.securite import RevocationSession

    with db.transaction_systeme() as s:
        lignes = s.query(RevocationSession).all()
    assert len(lignes) == 1 and lignes[0].apres == h.t + 4  # la coupure la plus tardive l'emporte


def test_pg_sessions_actives(db):
    h = Horloge()
    a = GestionnaireSessions(SECRET, horloge=h, registre=RegistreRevocations(db, horloge=h))
    db2 = _autre(db)
    try:
        b = GestionnaireSessions(SECRET, horloge=h, registre=RegistreRevocations(db2, horloge=h))
        ja = a.emettre(ACTEUR, appareil="Firefox · Linux", reseau="203.0.113.0/24")
        h.t += 1
        jb = b.emettre(ACTEUR)
        sa, sb = a.lire(ja).sid, b.lire(jb).sid
        assert [x.sid for x in a.sessions_actives(ACTEUR.id, sid_courant=sa)] == [sb, sa]
        h.t += a.rotation_s + 1
        _, nouveau = b.rafraichir(ja)
        assert a.sessions_actives(ACTEUR.id)[0].sid == sa
        assert a.fermer_autres_sessions(ACTEUR.id, sa) == 1
        with pytest.raises(PermissionError):
            a.lire(jb)
        assert [x.sid for x in b.sessions_actives(ACTEUR.id)] == [sa] and b.lire(nouveau).sid == sa
    finally:
        db2.fermer()
