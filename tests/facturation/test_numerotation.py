"""Numérotation continue par entité légale : séquence sans trou (y compris en concurrence), chronologie,
idempotence, immuabilité des factures émises."""

from __future__ import annotations

import threading
from datetime import date
from decimal import Decimal

import pytest
from aides_facturation import FONDATEUR, approuver
from sqlalchemy import text

from controldone.storage import AccesRefuse
from controldone.storage import facturation as stock
from controldone.storage.models_facturation import FactureEmise


def _champs(i: int = 0):
    def construire(numero: str) -> dict:
        return {"id": f"fac_test_{numero}_{i}", "type_code": "380", "type_facture": "diagnostic", "client_id": "cli_a",
                "date_echeance": date(2026, 11, 1), "total_ht": Decimal("390.00"), "total_tva": Decimal("78.00"),
                "total_ttc": Decimal("468.00"), "contenu": {}, "xml": "<x/>", "pdf": b"%PDF-", "pdf_sha256": "0" * 64}
    return construire


def _emettre(db, d=date(2026, 10, 2), **kw):
    return stock.emettre_numerotee(db, emetteur="fondateur", serie="F", date_emission=d, chiffres=4,
                                   construire=kw.pop("construire", _champs()), acteur_id=FONDATEUR.id,
                                   acteur_role="fondateur", **kw)


def test_sequence_continue_et_format(db):
    numeros = [_emettre(db).numero for _ in range(3)]
    assert numeros == ["F-2026-0001", "F-2026-0002", "F-2026-0003"]
    assert _emettre(db, date(2027, 1, 2)).numero == "F-2027-0001"  # nouvelle série annuelle
    autre = stock.emettre_numerotee(db, emetteur="fondateur", serie="AV", date_emission=date(2026, 10, 2), chiffres=4,
                                    construire=_champs(), acteur_id="x", acteur_role="fondateur")
    assert autre.numero == "AV-2026-0001"


def test_sans_trou_en_concurrence(db):
    n_fils, par_fil = 8, 5
    erreurs: list[BaseException] = []

    def travail(k: int) -> None:
        try:
            for j in range(par_fil):
                _emettre(db, construire=_champs(k * 100 + j))
        except BaseException as exc:  # pragma: no cover - remonté plus bas
            erreurs.append(exc)

    fils = [threading.Thread(target=travail, args=(k,)) for k in range(n_fils)]
    for f in fils:
        f.start()
    for f in fils:
        f.join()
    assert erreurs == []
    sequences = sorted(f.sequence for f in stock.factures(db))
    assert sequences == list(range(1, n_fils * par_fil + 1))  # ni trou ni doublon
    assert len({f.numero for f in stock.factures(db)}) == n_fils * par_fil


def test_echec_de_construction_ne_consomme_pas_de_numero(db):
    _emettre(db)

    def casse(numero: str) -> dict:
        raise ValueError("XSD invalide (simulé)")

    with pytest.raises(ValueError):
        _emettre(db, construire=casse)
    assert _emettre(db).numero == "F-2026-0002"


def test_chronologie(db):
    _emettre(db, date(2026, 10, 5))
    with pytest.raises(stock.ChronologieRompue):
        _emettre(db, date(2026, 10, 4))
    assert _emettre(db, date(2026, 10, 5)).numero == "F-2026-0002"


def test_idempotence_par_action(db):
    a = _emettre(db, outbox_id="out_1")
    b = _emettre(db, outbox_id="out_1", construire=_champs(9))
    assert a.id == b.id and len(stock.factures(db)) == 1


def test_facture_emise_immuable(db):
    f = _emettre(db)
    with pytest.raises(AccesRefuse), db.transaction_systeme() as s:
        s.get(FactureEmise, f.id).total_ht = Decimal("1.00")
        s.flush()
    with pytest.raises(AccesRefuse), db.transaction_systeme() as s:
        s.delete(s.get(FactureEmise, f.id))
        s.flush()
    # déclencheur SQL : même en contournant l'ORM
    with pytest.raises(Exception, match="immuable"), db.transaction_systeme() as s:
        s.execute(text("UPDATE factures SET total_ht = '1.00'"))
    assert stock.facture(db, f.id).total_ht == Decimal("390.00")


def test_brouillon_non_approuve_jamais_emis(service, db):
    from controldone.facturation import EmissionRefusee

    a = service.proposer_diagnostic("cli_a", FONDATEUR)
    with pytest.raises(EmissionRefusee, match="approuvé"):
        service.emettre(a.id, FONDATEUR)
    approuver(db, a.id)
    assert service.emettre(a.id, FONDATEUR, le=date(2026, 10, 2)).numero == "F-2026-0001"
