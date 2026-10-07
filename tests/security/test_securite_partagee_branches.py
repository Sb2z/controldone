"""Couverture de l'état de sécurité partagé (``storage.securite``) et du registre des sessions
(``auth.revocation``) — bloc O4, D-4901 : insertions concurrentes rejouées, base indisponible, purge périodique,
détection du chiffrement du volume (``/sys`` simulé), alerte de démarrage. Données fictives seulement."""

from __future__ import annotations

import logging
from contextlib import contextmanager
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, OperationalError

from controldone.auth import GestionnaireSessions, RegistreRevocations
from controldone.auth.roles import Acteur, Role
from controldone.storage import Database
from controldone.storage import securite as sec
from controldone.storage.models import Alerte, AuditLog

T = 1_800_000_000.0
SECRET = "s" * 40  # pragma: allowlist secret


@pytest.fixture
def db(tmp_path):
    d = Database(f"sqlite:///{tmp_path}/securite.db")
    d.creer_schema()
    yield d
    d.fermer()


def _conflits(monkeypatch, db, n: int) -> list[int]:
    """Les ``n`` prochaines transactions système échouent sur un conflit de clé (insertion concurrente)."""
    vraie = db.transaction_systeme
    appels = [0]

    @contextmanager
    def transaction(**kw):
        appels[0] += 1
        if appels[0] <= n:
            raise IntegrityError("INSERT", {}, Exception("conflit FICTIF"))
        with vraie(**kw) as s:
            yield s

    monkeypatch.setattr(db, "transaction_systeme", transaction)
    return appels


# --- insertions concurrentes rejouées (PostgreSQL), au plus trois essais ---------------------------------------------


def test_debit_conflit_rejoue_puis_reussit(db, monkeypatch):
    appels = _conflits(monkeypatch, db, 2)
    ok, reste = sec.consommer_jetons(
        db, "connexion_ip:abc", portee="connexion_ip", capacite=5, par_seconde=0.1, cout=1, maintenant=T
    )
    assert ok and reste == 4 and appels[0] == 3
    assert sec.jetons_disponibles(db, "connexion_ip:abc", capacite=5, par_seconde=0.1, maintenant=T) == 4


def test_debit_conflit_persistant_remonte(db, monkeypatch):
    _conflits(monkeypatch, db, 3)
    with pytest.raises(IntegrityError):
        sec.consommer_jetons(db, "k", portee="p", capacite=5, par_seconde=0.1, cout=1, maintenant=T)


def test_revocation_conflit_rejoue(db, monkeypatch):
    _conflits(monkeypatch, db, 2)
    sec.revoquer_sessions_utilisateur(db, "usr_x", apres=T, expire=T + 100)
    monkeypatch.undo()
    assert sec.session_revoquee(db, sid="autre", user_id="usr_x", debut=T - 1)
    assert not sec.session_revoquee(db, sid="autre", user_id="usr_x", debut=T)


def test_revocation_conflit_persistant_remonte(db, monkeypatch):
    _conflits(monkeypatch, db, 3)
    with pytest.raises(IntegrityError):
        sec.revoquer_session(db, "sid_x", expire=T + 100)


def test_enregistrer_session_conflit_rejoue_et_persistant(db, monkeypatch):
    _conflits(monkeypatch, db, 2)
    sec.enregistrer_session(db, sid="sid_1", user_id="usr_x", debut=T, vu=T, expire=T + 100)
    monkeypatch.undo()
    assert [s.sid for s in sec.sessions_utilisateur(db, "usr_x", maintenant=T)] == ["sid_1"]
    _conflits(monkeypatch, db, 3)
    with pytest.raises(IntegrityError):
        sec.enregistrer_session(db, sid="sid_2", user_id="usr_x", debut=T, vu=T, expire=T + 100)


def test_enregistrer_session_existante_met_a_jour_et_tronque(db):
    long_sid = "x" * 100
    sec.enregistrer_session(
        db,
        sid=long_sid,
        user_id="u" * 100,
        debut=T,
        vu=T,
        expire=T + 10,
        appareil="a" * 200,
        reseau="r" * 200,
    )
    sec.enregistrer_session(db, sid=long_sid, user_id="u" * 100, debut=T, vu=T + 5, expire=T + 50)
    (s,) = sec.sessions_utilisateur(db, "u" * 64, maintenant=T + 20, sid_courant="x" * 64)
    assert s.vu == T + 5 and s.courante and len(s.appareil) == 80 and len(s.reseau) == 64


def test_revocation_cumulee_garde_le_plus_strict(db):
    sec.revoquer_sessions_utilisateur(db, "usr_x", apres=T + 10, expire=T + 500)
    sec.revoquer_sessions_utilisateur(db, "usr_x", apres=T, expire=T + 100)  # plus ancienne : sans effet
    assert sec.session_revoquee(db, sid="s", user_id="usr_x", debut=T + 5)
    assert sec.purger_revocations(db, maintenant=T + 200) == 0  # l'expiration la plus lointaine est gardée
    assert sec.purger_revocations(db, maintenant=T + 500) == 1


# --- limitation de débit : effacement et purge -----------------------------------------------------------------------


def _remplir(db, n, portee="p"):
    for i in range(n):
        sec.consommer_jetons(
            db, f"{portee}:{i}", portee=portee, capacite=5, par_seconde=0.01 * (i + 1), cout=3, maintenant=T
        )


def test_effacer_debit_sans_critere_ne_fait_rien(db):
    _remplir(db, 2)
    assert sec.effacer_debit(db) == 0
    assert len(sec.lister_debit(db, maintenant=T)) == 2


def test_effacer_debit_tout_journalise(db):
    _remplir(db, 2, "a")
    _remplir(db, 1, "b")
    assert sec.effacer_debit(db, portee="a", journal=False) == 2
    assert sec.effacer_debit(db, tout=True, acteur="usr_fondateur", motif="m" * 500) == 1
    with db.transaction_systeme() as s:
        e = s.execute(select(AuditLog).where(AuditLog.action == "debit_effacer")).scalar_one()
        assert e.details["tout"] is True and len(e.details["motif"]) == 200


def test_purger_debit_borne_le_nombre_de_lignes(db):
    _remplir(db, 5)
    assert sec.purger_debit(db, maintenant=T, max_lignes=2) == 3
    restantes = sec.lister_debit(db, maintenant=T)
    # restent les seaux qui expirent le plus tard (remplissage le plus lent)
    assert sorted(x.cle for x in restantes) == ["p:0", "p:1"]


# --- chiffrement du volume (``/sys`` simulé) --------------------------------------------------------------------------


def _bloc(sys_dir: Path, dev: str, uuid: str | None = None, esclaves: tuple[str, ...] = ()) -> Path:
    d = sys_dir / "devices" / dev
    d.mkdir(parents=True, exist_ok=True)
    if uuid is not None:
        (d / "dm").mkdir(exist_ok=True)
        (d / "dm" / "uuid").write_text(uuid + "\n")
    (d / "slaves").mkdir(exist_ok=True)
    for e in esclaves:
        lien = d / "slaves" / e
        if not lien.exists():
            lien.symlink_to(sys_dir / "devices" / e)
    return d


def _lier(sys_dir: Path, majmin: str, dev: str) -> None:
    (sys_dir / "dev" / "block").mkdir(parents=True, exist_ok=True)
    (sys_dir / "dev" / "block" / majmin).symlink_to(sys_dir / "devices" / dev)


@pytest.fixture
def faux_sys(tmp_path, monkeypatch):
    monkeypatch.setattr(sec, "_peripherique", lambda chemin: (253, 1))
    return tmp_path / "sys"


def test_volume_luks_direct(faux_sys):
    _bloc(faux_sys, "dm-1", "CRYPT-LUKS2-0000-FICTIF")
    _lier(faux_sys, "253:1", "dm-1")
    assert sec.chiffrement_volume("/x", sys_dir=faux_sys) == "chiffre"


def test_volume_lvm_sur_luks(faux_sys):
    _bloc(faux_sys, "dm-0", "crypt-luks2-0000-fictif")  # casse indifférente
    _bloc(faux_sys, "dm-1", "LVM-0000-FICTIF", ("dm-0",))
    _lier(faux_sys, "253:1", "dm-1")
    assert sec.chiffrement_volume("/x", sys_dir=faux_sys) == "chiffre"


def test_volume_non_chiffre_avec_cycle(faux_sys):
    """Une boucle dans ``slaves`` (``/sys`` incohérent) ne bloque pas le parcours."""
    _bloc(faux_sys, "dm-0")
    _bloc(faux_sys, "dm-1", "LVM-0000-FICTIF", ("dm-0",))
    _bloc(faux_sys, "dm-0", esclaves=("dm-1",))
    _lier(faux_sys, "253:1", "dm-1")
    assert sec.chiffrement_volume("/x", sys_dir=faux_sys) == "non_chiffre"


def test_volume_peripherique_absent_de_sys(faux_sys):
    faux_sys.mkdir()
    assert sec.chiffrement_volume("/x", sys_dir=faux_sys) == "inconnu"


def test_volume_chemin_illisible_ou_peripherique_nul(tmp_path, monkeypatch):
    assert sec._peripherique(tmp_path / "absent") is None
    assert sec.chiffrement_volume(tmp_path / "absent", sys_dir=tmp_path) == "inconnu"
    monkeypatch.setattr(sec, "_peripherique", lambda chemin: (0, 0))
    assert sec.chiffrement_volume(tmp_path, sys_dir=tmp_path) == "inconnu"


# --- alerte de démarrage (RS-21) ---------------------------------------------------------------------------------


def _alertes(db) -> list[Alerte]:
    with db.transaction_systeme() as s:
        return list(s.execute(select(Alerte).where(Alerte.kind == "volume_non_chiffre")).scalars())


def test_signaler_volume_hors_prod_et_declare(db, monkeypatch):
    assert sec.signaler_volume_non_chiffre(db, mode="dev") == "hors_prod"
    monkeypatch.setenv("CONTROLDONE_VOLUME_CHIFFRE", "1")
    assert sec.signaler_volume_non_chiffre(db, mode="prod") == "declare"
    assert _alertes(db) == []


def test_signaler_volume_hors_sqlite():
    class Pg:
        def chemin_sqlite(self):
            return None

    assert sec.signaler_volume_non_chiffre(Pg(), mode="prod") == "hors_sqlite"  # type: ignore[arg-type]


def test_signaler_volume_non_chiffre_une_alerte_par_mois(db, monkeypatch, caplog):
    monkeypatch.delenv("CONTROLDONE_VOLUME_CHIFFRE", raising=False)
    monkeypatch.setattr(sec, "chiffrement_volume", lambda chemin, sys_dir: "non_chiffre")
    with caplog.at_level(logging.WARNING, "controldone.storage.securite"):
        assert sec.signaler_volume_non_chiffre(db, mode="prod") == "non_chiffre"
        assert sec.signaler_volume_non_chiffre(db, mode="prod") == "non_chiffre"
    assert len(_alertes(db)) == 1
    assert "volume_non_chiffre" in caplog.text


def test_signaler_volume_alerte_impossible_non_bloquante(db, monkeypatch, caplog):
    monkeypatch.delenv("CONTROLDONE_VOLUME_CHIFFRE", raising=False)
    monkeypatch.setattr(sec, "chiffrement_volume", lambda chemin, sys_dir: "non_chiffre")

    @contextmanager
    def en_panne(**kw):
        raise OperationalError("BEGIN", {}, Exception("base verrouillée FICTIVE"))
        yield

    monkeypatch.setattr(db, "transaction_systeme", en_panne)
    with caplog.at_level(logging.WARNING, "controldone.storage.securite"):
        assert sec.signaler_volume_non_chiffre(db, mode="prod") == "non_chiffre"
    assert "alerte_volume_impossible erreur=OperationalError" in caplog.text


def test_signaler_volume_inconnu(db, monkeypatch, caplog):
    monkeypatch.delenv("CONTROLDONE_VOLUME_CHIFFRE", raising=False)
    monkeypatch.setattr(sec, "chiffrement_volume", lambda chemin, sys_dir: "inconnu")
    with caplog.at_level(logging.INFO, "controldone.storage.securite"):
        assert sec.signaler_volume_non_chiffre(db, mode="prod") == "inconnu"
    assert "volume_chiffrement_inconnu" in caplog.text and _alertes(db) == []


# --- registre des révocations : base indisponible, purge périodique ---------------------------------------------------


class Horloge:
    def __init__(self, t: float = T) -> None:
        self.t = t

    def __call__(self) -> float:
        return self.t


@pytest.fixture
def base_en_panne(tmp_path):
    """Base dont les tables de sécurité n'existent pas : chaque opération lève une erreur SQL."""
    d = Database(f"sqlite:///{tmp_path}/vide.db")
    yield d
    d.fermer()


def test_registre_base_indisponible_ne_bloque_pas(base_en_panne, caplog):
    reg = RegistreRevocations(base_en_panne, horloge=Horloge())
    with caplog.at_level(logging.WARNING, "controldone.auth.revocation"):
        reg.revoquer("sid", expire=T + 10)
        reg.revoquer_utilisateur("usr", apres=T, expire=T + 10)
        reg.ouvrir("sid", "usr", debut=T, vu=T, expire=T + 10)
        reg.toucher("sid", vu=T, expire=T + 10)
        assert reg.sessions("usr", maintenant=T) == []
        assert reg.est_revoquee("sid", "usr", T) is False
    operations = {
        r.getMessage().split("operation=")[1].split()[0]
        for r in caplog.records
        if "operation=" in r.getMessage()
    }
    assert operations == {"revoquer", "purge", "revoquer_utilisateur", "ouvrir", "toucher", "lister", "lire"}
    assert "sid" not in caplog.text.replace("operation=", "")  # nom d'exception seulement, aucun identifiant


def test_gestionnaire_avec_base_en_panne_garde_la_revocation_locale(base_en_panne):
    h = Horloge()
    g = GestionnaireSessions(SECRET, horloge=h, registre=RegistreRevocations(base_en_panne, horloge=h))
    jeton = g.emettre(Acteur("usr_x", Role.client_admin, "cli_a"))
    d = g.lire(jeton)  # base illisible : pas de refus sur ce seul motif
    g.revoquer(d.sid, debut=d.debut)
    with pytest.raises(PermissionError):
        g.lire(jeton)
    assert g.sessions_actives("usr_x") == []


def test_registre_purge_au_plus_une_fois_par_periode(db, monkeypatch):
    h = Horloge()
    appels = []
    monkeypatch.setattr(sec, "purger_revocations", lambda db, maintenant: appels.append(maintenant) or 0)
    reg = RegistreRevocations(db, horloge=h, purge_toutes_s=60)
    reg.revoquer("a", expire=T + 10)
    reg.revoquer("b", expire=T + 10)
    h.t += 59
    reg.revoquer("c", expire=T + 10)
    h.t += 2
    reg.revoquer("d", expire=T + 10)
    assert appels == [T, T + 61]
    assert all(reg.est_revoquee(sid, "u", T) for sid in "abcd")


def test_registre_bout_en_bout(db):
    h = Horloge()
    reg = RegistreRevocations(db, horloge=h)
    reg.ouvrir("s1", "usr", debut=T, vu=T, expire=T + 100, appareil="Firefox · Linux", reseau="192.0.2.0/24")
    reg.ouvrir("s2", "usr", debut=T + 1, vu=T + 1, expire=T + 100)
    reg.toucher("s1", vu=T + 5, expire=T + 200)
    assert [s.sid for s in reg.sessions("usr", maintenant=T + 10, sid_courant="s2")] == ["s1", "s2"]
    reg.revoquer("s1", expire=T + 300)
    assert [s.sid for s in reg.sessions("usr", maintenant=T + 10)] == ["s2"]
    reg.revoquer_utilisateur("usr", apres=T + 2, expire=T + 300)
    assert reg.sessions("usr", maintenant=T + 10) == []
    assert reg.est_revoquee("s2", "usr", T + 1) and not reg.est_revoquee("s3", "usr", T + 3)
