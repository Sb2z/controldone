"""Couverture des commandes d'exploitation de sécurité (``auth.cli_securite``) et des clés maîtresses
(``storage.cles``) — bloc O4, D-4901 : déblocage ciblé ou total, réinitialisation de mot de passe refusée ou
réussie (sessions révoquées), clé maîtresse absente en production, clé de développement, secrets indéchiffrables.
Données fictives seulement."""

from __future__ import annotations

import argparse
import io
import os
import stat
import time

import pytest
from aides_plateforme import FONDATEUR
from cryptography.fernet import Fernet

from controldone.auth import cli_securite
from controldone.auth.debit import cle_debit, sel_debit
from controldone.auth.motdepasse import hacher_mot_de_passe, verifier_mot_de_passe
from controldone.auth.roles import Role
from controldone.storage import Database
from controldone.storage import cles as mod_cles
from controldone.storage import securite as sec
from controldone.storage.comptes import creer_utilisateur, utilisateur_par_email
from controldone.storage.erreurs import CleManquante, ErreurIntegrite

EMAIL = "exploitant@exemple-fictif.test"
T = time.time()


@pytest.fixture
def base(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path}/cli.db"
    monkeypatch.setenv("CONTROLDONE_DATABASE_URL", url)
    db = Database(url)
    db.creer_schema()
    creer_utilisateur(
        db,
        user_id="usr_exploitant",
        email=EMAIL,
        mot_de_passe_hash=hacher_mot_de_passe("ancienne-phrase-FICTIVE"),
        role=Role.client_admin,
        acteur=FONDATEUR,
    )
    yield db
    db.fermer()


def _lancer(*argv: str) -> int:
    ap = argparse.ArgumentParser()
    cli_securite.ajouter_commandes(ap.add_subparsers(dest="commande", required=True))
    args = ap.parse_args(list(argv))
    return args.fn(args)


def _sel() -> bytes:
    return sel_debit(mod_cles.charger_cles_maitresses())


def _seau(db, portee: str, identifiant: str) -> str:
    cle = cle_debit(portee, identifiant, _sel())
    sec.consommer_jetons(db, cle, portee=portee, capacite=5, par_seconde=0.001, cout=5, maintenant=T)
    return cle


def _cles(db) -> set[str]:
    return {x.cle for x in sec.lister_debit(db, maintenant=T)}


# --- debit lister / effacer ---------------------------------------------------------------------------------------


def test_lister_sans_compteur(base, capsys):
    assert _lancer("debit", "lister") == 0
    assert "Aucun compteur" in capsys.readouterr().out


def test_lister_n_affiche_que_l_empreinte(base, capsys):
    _seau(base, "connexion_ip", "192.0.2.7")
    assert _lancer("debit", "lister", "--limite", "5") == 0
    sortie = capsys.readouterr().out
    assert "connexion_ip" in sortie and "BLOQUÉ" in sortie and "192.0.2.7" not in sortie


def test_effacer_sans_cible_refuse(base, capsys):
    _seau(base, "connexion_ip", "192.0.2.7")
    assert _lancer("debit", "effacer") == 2
    assert "--tout" in capsys.readouterr().err
    assert len(_cles(base)) == 1


def test_effacer_par_ip_puis_par_cle_api_puis_tout(base, capsys):
    ip = _seau(base, "connexion_ip", "192.0.2.7")
    api_ip = _seau(base, "api", "ip:192.0.2.7")
    api_cle = _seau(base, "api", "api:pfx123")
    autre = _seau(base, "connexion_ip", "198.51.100.1")
    assert _lancer("debit", "effacer", "--ip", "192.0.2.7", "--motif", "test FICTIF") == 0
    assert _cles(base) == {api_cle, autre}
    assert ip not in _cles(base) and api_ip not in _cles(base)
    assert _lancer("debit", "effacer", "--cle-api", "pfx123") == 0
    assert _cles(base) == {autre}
    assert _lancer("debit", "effacer", "--tout") == 0
    assert _cles(base) == set()
    assert "débloquées" in capsys.readouterr().out


def test_effacer_par_courriel_vise_les_seaux_du_compte(base):
    seaux = {
        _seau(base, "connexion_compte", EMAIL),
        _seau(base, "connexion_compte", "2fa:usr_exploitant"),
        _seau(base, "connexion_compte", "mdp:usr_exploitant"),
    }
    autre = _seau(base, "connexion_compte", "autre@exemple-fictif.test")
    assert _lancer("debit", "effacer", "--email", "  " + EMAIL.upper()) == 0
    assert _cles(base) == {autre} and not (seaux & _cles(base))


def test_effacer_courriel_inconnu_ne_vise_que_le_courriel(base):
    s = _seau(base, "connexion_compte", "inconnu@exemple-fictif.test")
    assert _lancer("debit", "effacer", "--email", "inconnu@exemple-fictif.test") == 0
    assert s not in _cles(base)


# --- réinitialisation du mot de passe ---------------------------------------------------------------------------------


def test_reinitialiser_compte_inconnu(base, capsys):
    assert _lancer("reinitialiser-mot-de-passe", "--email", "personne@exemple-fictif.test") == 1
    assert "Aucun compte" in capsys.readouterr().err


def test_reinitialiser_mot_de_passe_faible(base, monkeypatch, capsys):
    monkeypatch.setattr("sys.stdin", io.StringIO("court\n"))
    assert _lancer("reinitialiser-mot-de-passe", "--email", EMAIL, "--mot-de-passe-stdin") == 2
    assert "refusé" in capsys.readouterr().err
    assert verifier_mot_de_passe(
        utilisateur_par_email(base, EMAIL).mot_de_passe_hash, "ancienne-phrase-FICTIVE"
    )


def test_reinitialiser_confirmation_differente(base, monkeypatch, capsys):
    saisies = iter(["nouvelle-phrase-FICTIVE-1", "nouvelle-phrase-FICTIVE-2"])
    monkeypatch.setattr("getpass.getpass", lambda invite="": next(saisies))
    assert _lancer("reinitialiser-mot-de-passe", "--email", EMAIL) == 2
    assert "diffèrent" in capsys.readouterr().err


def test_reinitialiser_revoque_les_sessions_et_debloque(base, monkeypatch, capsys):
    sec.enregistrer_session(
        base, sid="sid_ouverte", user_id="usr_exploitant", debut=T - 60, vu=T, expire=T + 600
    )
    s = _seau(base, "connexion_compte", EMAIL)
    monkeypatch.setattr("getpass.getpass", lambda invite="": "nouvelle-phrase-FICTIVE-1")
    assert _lancer("reinitialiser-mot-de-passe", "--email", EMAIL) == 0
    assert "sessions du compte sont fermées" in capsys.readouterr().out
    compte = utilisateur_par_email(base, EMAIL)
    assert verifier_mot_de_passe(compte.mot_de_passe_hash, "nouvelle-phrase-FICTIVE-1")
    assert sec.session_revoquee(base, sid="sid_ouverte", user_id="usr_exploitant", debut=T - 60)
    assert sec.sessions_utilisateur(base, "usr_exploitant", maintenant=T) == []
    assert s not in _cles(base)


# --- clés maîtresses -------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "valeur, attendu", [("PROD", "prod"), (" test ", "test"), ("staging", "prod"), ("", "prod")]
)
def test_mode_inconnu_le_plus_strict(monkeypatch, valeur, attendu):
    monkeypatch.setenv("CONTROLDONE_ENV", valeur)
    assert mod_cles.mode_execution() == attendu


def test_mode_par_defaut_dev(monkeypatch):
    monkeypatch.delenv("CONTROLDONE_ENV", raising=False)
    assert mod_cles.mode_execution() == "dev"


@pytest.mark.parametrize("valeur", ["pas-une-cle", "YWJj", Fernet.generate_key().decode()[:-4]])
def test_cle_maitresse_invalide(monkeypatch, valeur):
    monkeypatch.setenv("CONTROLDONE_MASTER_KEY", valeur)
    with pytest.raises(CleManquante, match="invalide"):
        mod_cles.charger_cles_maitresses()


def test_plusieurs_cles_la_premiere_chiffre(monkeypatch):
    k1, k2 = Fernet.generate_key(), Fernet.generate_key()
    monkeypatch.setenv("CONTROLDONE_MASTER_KEY", f" {k2.decode()} ,, {k1.decode()} ")
    assert mod_cles.charger_cles_maitresses() == [k2, k1]
    jeton = mod_cles.chiffrer_secret([k1], "secret TOTP FICTIF")
    assert (
        mod_cles.dechiffrer_secret([k2, k1], jeton) == "secret TOTP FICTIF"
    )  # rotation : l'ancienne déchiffre
    with pytest.raises(ErreurIntegrite):
        mod_cles.dechiffrer_secret([k2], jeton)
    with pytest.raises(ErreurIntegrite):
        mod_cles.dechiffrer_secret([k1], jeton[:-2] + "AA")


def test_cle_absente_refusee_en_production(monkeypatch, tmp_path):
    monkeypatch.delenv("CONTROLDONE_MASTER_KEY", raising=False)
    with pytest.raises(CleManquante, match="production"):
        mod_cles.charger_cles_maitresses(mode="prod", data_dir=tmp_path)
    assert not (tmp_path / "dev_master.key").exists()


def test_cle_de_developpement_creee_une_fois_en_0600(monkeypatch, tmp_path):
    monkeypatch.delenv("CONTROLDONE_MASTER_KEY", raising=False)
    with pytest.warns(UserWarning, match="DÉVELOPPEMENT"):
        c1 = mod_cles.charger_cles_maitresses(mode="dev", data_dir=tmp_path / "neuf")
    fichier = tmp_path / "neuf" / "dev_master.key"
    assert stat.S_IMODE(os.stat(fichier).st_mode) == 0o600
    with pytest.warns(UserWarning):
        assert mod_cles.charger_cles_maitresses(mode="test", data_dir=tmp_path / "neuf") == c1


def test_cle_de_developpement_dans_le_dossier_des_donnees(monkeypatch, tmp_path):
    monkeypatch.delenv("CONTROLDONE_MASTER_KEY", raising=False)
    monkeypatch.setenv("CONTROLDONE_DATA_DIR", str(tmp_path / "donnees"))
    from controldone.config import reset_settings

    reset_settings()
    with pytest.warns(UserWarning):
        mod_cles.charger_cles_maitresses(mode="dev")
    assert (tmp_path / "donnees" / "dev_master.key").exists()


def test_derivation_par_usage_et_cles_vides():
    k = Fernet.generate_key()
    a, b = mod_cles.deriver_fernet(k, "vault:cli_a"), mod_cles.deriver_fernet(k, "vault:cli_b")
    with pytest.raises(Exception):  # noqa: B017 - une clé d'un client n'ouvre pas le coffre d'un autre
        b.decrypt(a.encrypt(b"x"))
    with pytest.raises(CleManquante):
        mod_cles.deriver_multifernet([], "secrets")


def test_empreinte_publique_stable_et_groupee():
    k = Fernet.generate_key()
    e = mod_cles.empreinte_cle(k)
    assert e == mod_cles.empreinte_cle(k.decode() + "\n")  # espaces ignorés, str ou bytes
    assert len(e) == 19 and e.count(" ") == 3
    assert e != mod_cles.empreinte_cle(Fernet.generate_key())
    assert k.decode()[:8] not in e.replace(" ", "")
