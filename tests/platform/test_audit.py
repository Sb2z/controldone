"""Journal d'audit append-only chaîné : détection de toute altération."""

from __future__ import annotations

import sqlite3
from itertools import pairwise

import pytest
from aides_plateforme import FONDATEUR, SYSTEME

from controldone.storage import AccesRefuse, verifier_chaine
from controldone.storage.audit import GENESE, journaliser
from controldone.storage.models import AuditLog


def _chemin(db):
    return str(db.chemin_sqlite())


def test_chaine_intacte_et_liee(monde):
    with monde.db.transaction_systeme() as s:
        entrees = s.query(AuditLog).order_by(AuditLog.id).all()
        assert entrees[0].prev_hash == GENESE
        assert all(b.prev_hash == a.hash for a, b in pairwise(entrees))
        assert verifier_chaine(s) == []


def test_contenu_minimal_d_une_entree(monde):
    with monde.db.operateur(FONDATEUR, ip="203.0.113.7") as op:
        op.client("cli_a", "contrôle")
    with monde.db.operateur(FONDATEUR) as op:
        e = next(x for x in op.journal() if x.action == "acces_admin")
    assert (e.actor, e.role, e.tenant_id, e.ip) == (FONDATEUR.id, "fondateur", "cli_a", "203.0.113.7")
    assert e.ts is not None and e.target == "tenants:cli_a" and len(e.hash) == 64


def test_orm_ne_peut_ni_modifier_ni_supprimer(monde):
    with monde.db.transaction_systeme() as s:
        e = s.query(AuditLog).first()
        e.action = "falsifie"
        with pytest.raises(AccesRefuse):
            s.flush()
        s.rollback()
        s.delete(s.query(AuditLog).first())
        with pytest.raises(AccesRefuse):
            s.flush()
        s.rollback()


def test_declencheurs_sql_bloquent_update_et_delete(monde):
    monde.db.fermer()
    con = sqlite3.connect(_chemin(monde.db))
    try:
        with pytest.raises(sqlite3.DatabaseError, match="append-only"):
            con.execute("UPDATE audit_log SET action='x' WHERE id=1")
        with pytest.raises(sqlite3.DatabaseError, match="append-only"):
            con.execute("DELETE FROM audit_log WHERE id=1")
    finally:
        con.close()


@pytest.mark.parametrize("attaque", ["modifier", "supprimer", "inserer", "tronquer_recalcule"])
def test_falsification_detectee(monde, attaque):
    monde.db.fermer()
    con = sqlite3.connect(_chemin(monde.db))
    con.execute("DROP TRIGGER audit_log_sans_update")
    con.execute("DROP TRIGGER audit_log_sans_delete")
    if attaque == "modifier":
        con.execute("UPDATE audit_log SET actor='quelqu_un' WHERE id=2")
    elif attaque == "supprimer":
        con.execute("DELETE FROM audit_log WHERE id=2")
    elif attaque == "inserer":
        # premier caractère toujours changé (« f » si ce n'était pas déjà « f » : sinon test sans effet, 1 fois sur 16)
        con.execute("UPDATE audit_log SET prev_hash=(CASE WHEN substr(prev_hash,1,1)='f' THEN 'e' ELSE 'f' END)"
                    "||substr(prev_hash,2) WHERE id=3")
    else:  # recalcul de l'entrée 2 sans recalculer la suite
        con.execute("UPDATE audit_log SET details='{\"x\":1}', hash='" + "a" * 64 + "' WHERE id=2")
    con.commit()
    con.close()
    with monde.db.transaction_systeme() as s:
        assert verifier_chaine(s) != []


def test_ecritures_d_une_transaction_annulee_ne_cassent_pas_la_chaine(monde):
    with pytest.raises(RuntimeError), monde.db.tenant("cli_a", SYSTEME) as sc:
        sc._auditer("essai", "x", toujours=True)
        raise RuntimeError("annulation")
    with monde.db.transaction_systeme() as s:
        journaliser(s, actor="tests", role="systeme", action="apres")
    with monde.db.transaction_systeme() as s:
        assert verifier_chaine(s) == []
        assert s.query(AuditLog).filter_by(action="essai").count() == 0
