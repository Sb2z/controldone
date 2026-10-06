"""Limitation de débit (auth/debit.py) : branches non couvertes avant D-3902 — base indisponible (repli en
mémoire, jamais d'ouverture totale), remboursement, attente, effacement, pseudonymisation des clés."""

from __future__ import annotations

import logging

import pytest

from controldone.auth import debit
from controldone.auth.debit import LimiteurDebit, LimiteurDebitPartage, cle_debit, sel_debit


class _Horloge:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t


class _BaseEnPanne:
    """Toute opération sur la base échoue (base verrouillée, réseau coupé…)."""

    def __getattr__(self, nom):
        raise RuntimeError("base indisponible")


def _partage(capacite=2, par_seconde=1.0, horloge=None):
    return LimiteurDebitPartage("connexion_ip", capacite, par_seconde, db=_BaseEnPanne(), sel=b"sel-fictif",
                                horloge=horloge or _Horloge())


class _Releve(logging.Handler):
    def __init__(self) -> None:
        super().__init__(logging.DEBUG)
        self.lignes: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.lignes.append(record.getMessage())


def test_base_en_panne_repli_en_memoire_qui_limite_encore():
    # gestionnaire posé sur le journal du module : indépendant de la configuration de journalisation des autres tests
    releve, journal = _Releve(), debit.log
    niveau, desactive, global_ = journal.level, journal.disabled, logging.root.manager.disable
    journal.addHandler(releve)
    journal.setLevel(logging.DEBUG)
    journal.disabled = False  # un dictConfig d'un autre test peut l'avoir désactivé
    logging.disable(logging.NOTSET)  # bench_run appelle logging.disable(WARNING) au niveau global
    try:
        lim = _partage(capacite=2)
        assert lim.autoriser("203.0.113.7")
        assert lim.autoriser("203.0.113.7")
        assert not lim.autoriser("203.0.113.7")  # le repli limite toujours : pas d'ouverture en cas de panne
        assert lim.autoriser("198.51.100.1")  # clés indépendantes
    finally:
        journal.removeHandler(releve)
        journal.setLevel(niveau)
        journal.disabled = desactive
        logging.disable(global_)
    texte = "\n".join(releve.lignes)
    assert "debit_base_indisponible" in texte
    assert "203.0.113.7" not in texte  # l'adresse n'est jamais journalisée


def test_base_en_panne_attente_remboursement_effacement():
    lim = _partage(capacite=1, par_seconde=0.5)
    assert lim.autoriser("a")
    assert lim.attente("a") > 0
    lim.rembourser("a")
    assert lim.attente("a") == 0
    assert lim.autoriser("a") and not lim.autoriser("a")
    lim.effacer("a")  # ne lève jamais, efface aussi le repli
    assert lim.autoriser("a")


def test_parametres_invalides_refuses():
    with pytest.raises(ValueError):
        LimiteurDebitPartage("api", 0, 1, db=_BaseEnPanne(), sel=b"x")
    with pytest.raises(ValueError):
        LimiteurDebitPartage("api", 1, 1, db=_BaseEnPanne(), sel=b"")
    with pytest.raises(ValueError):
        LimiteurDebit(1, 0)


def test_limiteur_memoire_recharge_et_remboursement():
    h = _Horloge()
    lim = LimiteurDebit(2, 1.0, horloge=h)
    assert lim.autoriser("k") and lim.autoriser("k") and not lim.autoriser("k")
    assert lim.attente("k") == pytest.approx(1.0)
    h.t += 1.0
    assert lim.autoriser("k")
    lim.rembourser("inconnue")  # clé jamais vue : sans effet
    assert "inconnue" not in lim._seaux
    lim.rembourser("k", 10)
    assert lim.attente("k", 2) == 0  # plafonné à la capacité
    lim.effacer("k")
    assert lim.attente("k") == 0


def test_limiteur_memoire_borne_le_nombre_de_cles():
    lim = LimiteurDebit(1, 1.0, max_cles=3, horloge=_Horloge())
    for i in range(10):
        lim.autoriser(f"c{i}")
    assert len(lim._seaux) <= 3


def test_cle_pseudonymisee_et_salee():
    sel = sel_debit([b"cle-maitresse-fictive-1", b"ancienne"])
    assert sel == sel_debit([b"cle-maitresse-fictive-1"])
    assert sel != sel_debit([b"cle-maitresse-fictive-2"])
    k = cle_debit("connexion_ip", "203.0.113.7", sel)
    assert k.startswith("connexion_ip:") and "203.0.113.7" not in k
    assert k != cle_debit("connexion_compte", "203.0.113.7", sel)
    assert k != cle_debit("connexion_ip", "203.0.113.7", b"autre")
