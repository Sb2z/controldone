"""Coffre chiffré : chiffrement au repos, adressage par contenu, intégrité, rotation, clés."""

from __future__ import annotations

import hashlib
import os
import stat

import pytest
from cryptography.fernet import Fernet

from controldone.storage import CleManquante, ErreurIntegrite, FileVault, charger_cles_maitresses
from controldone.storage.cles import chiffrer_secret, dechiffrer_secret


def test_aller_retour_et_chiffrement_au_repos(vault):
    contenu = b"%PDF-1.7 FACTURE FICTIVE 12 540,00 USD"
    sha = vault.deposer("cli_a", contenu)
    assert sha == hashlib.sha256(contenu).hexdigest()
    assert vault.lire("cli_a", sha) == contenu
    brut = vault._chemin("cli_a", sha, "fichiers").read_bytes()
    assert b"FACTURE" not in brut and b"12 540" not in brut
    assert stat.S_IMODE(os.stat(vault._chemin("cli_a", sha, "fichiers")).st_mode) == 0o600


def test_dedoublonnage_par_client(vault):
    a = vault.deposer("cli_a", b"x")
    b = vault.deposer("cli_a", b"x")
    assert a == b and list(vault.lister("cli_a")) == [a]
    vault.deposer("cli_b", b"x")
    assert vault._chemin("cli_a", a, "fichiers") != vault._chemin("cli_b", a, "fichiers")


def test_textes_de_page_chiffres(vault):
    sha = vault.deposer_texte("cli_a", "TOTAL AMOUNT DUE USD 12,540.00")
    assert vault.lire_texte("cli_a", sha) == "TOTAL AMOUNT DUE USD 12,540.00"
    assert b"TOTAL" not in vault._chemin("cli_a", sha, "textes").read_bytes()
    assert list(vault.lister("cli_a", espace="fichiers")) == []


def test_alteration_detectee(vault):
    sha = vault.deposer("cli_a", b"contenu")
    chemin = vault._chemin("cli_a", sha, "fichiers")
    donnees = bytearray(chemin.read_bytes())
    donnees[20] ^= 1
    chemin.write_bytes(bytes(donnees))
    with pytest.raises(ErreurIntegrite):
        vault.lire("cli_a", sha)


def test_substitution_de_contenu_detectee(vault):
    sha_a = vault.deposer("cli_a", b"premier")
    sha_b = vault.deposer("cli_a", b"second")
    vault._chemin("cli_a", sha_a, "fichiers").write_bytes(
        vault._chemin("cli_a", sha_b, "fichiers").read_bytes()
    )
    with pytest.raises(ErreurIntegrite):
        vault.lire("cli_a", sha_a)


def test_mauvaise_cle_maitresse(tmp_path, vault):
    sha = vault.deposer("cli_a", b"contenu")
    autre = FileVault(vault.racine, [Fernet.generate_key()])
    with pytest.raises(ErreurIntegrite):
        autre.lire("cli_a", sha)


def test_rotation_des_cles(tmp_path, cles):
    v = FileVault(tmp_path / "c", cles)
    shas = [v.deposer("cli_a", b"un"), v.deposer("cli_b", b"deux")]
    t = v.deposer_texte("cli_a", "trois")
    nouvelle = Fernet.generate_key()
    assert v.tourner_cles([nouvelle, *cles]) == 3
    seule_nouvelle = FileVault(tmp_path / "c", [nouvelle])
    assert seule_nouvelle.lire("cli_a", shas[0]) == b"un"
    assert seule_nouvelle.lire("cli_b", shas[1]) == b"deux"
    assert seule_nouvelle.lire_texte("cli_a", t) == "trois"
    with pytest.raises(ErreurIntegrite):
        FileVault(tmp_path / "c", cles).lire("cli_a", shas[0])


def test_supprimer_client(vault):
    vault.deposer("cli_a", b"a")
    sha_b = vault.deposer("cli_b", b"b")
    vault.supprimer_client("cli_a")
    assert vault.clients() == ["cli_b"]
    assert vault.lire("cli_b", sha_b) == b"b"


def test_cle_dev_generee_avec_avertissement(monkeypatch, tmp_path):
    monkeypatch.delenv("CONTROLDONE_MASTER_KEY")
    with pytest.warns(UserWarning, match="DÉVELOPPEMENT"):
        cles = charger_cles_maitresses(mode="dev", data_dir=tmp_path)
    fichier = tmp_path / "dev_master.key"
    assert fichier.exists() and stat.S_IMODE(os.stat(fichier).st_mode) == 0o600
    with pytest.warns(UserWarning):
        assert charger_cles_maitresses(mode="dev", data_dir=tmp_path) == cles  # stable


def test_prod_sans_cle_refuse_de_demarrer(monkeypatch, tmp_path):
    monkeypatch.delenv("CONTROLDONE_MASTER_KEY")
    with pytest.raises(CleManquante):
        charger_cles_maitresses(mode="prod", data_dir=tmp_path)
    assert not (tmp_path / "dev_master.key").exists()
    monkeypatch.setenv("CONTROLDONE_ENV", "production-typo")  # mode inconnu -> le plus strict
    with pytest.raises(CleManquante):
        FileVault.depuis_env(tmp_path / "c")


def test_cle_invalide_refusee(monkeypatch):
    monkeypatch.setenv("CONTROLDONE_MASTER_KEY", "trop-courte")
    with pytest.raises(CleManquante):
        charger_cles_maitresses(mode="prod")


def test_plusieurs_cles_dans_l_environnement(monkeypatch, tmp_path):
    k1, k2 = Fernet.generate_key().decode(), Fernet.generate_key().decode()
    monkeypatch.setenv("CONTROLDONE_MASTER_KEY", f"{k1},{k2}")
    assert [c.decode() for c in charger_cles_maitresses(mode="prod")] == [k1, k2]


def test_secrets_chiffres(cles):
    jeton = chiffrer_secret(cles, "JBSWY3DPEHPK3PXP")
    assert "JBSWY3DP" not in jeton
    assert dechiffrer_secret(cles, jeton) == "JBSWY3DPEHPK3PXP"
    with pytest.raises(ErreurIntegrite):
        dechiffrer_secret([Fernet.generate_key()], jeton)
