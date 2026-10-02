import re

from controldone.ids import PREFIXE_RE, IdGenerator, Prefixe, id_stable, nouvel_id, uuid7_hex


def test_format_et_version():
    i = nouvel_id(Prefixe.document)
    assert PREFIXE_RE.match(i)
    h = i.split("_")[1]
    assert h[12] == "7"  # version 7
    assert h[16] in "89ab"  # variante RFC


def test_triable_et_unique():
    g = IdGenerator()
    ids = [g.nouveau("doc") for _ in range(2000)]
    assert ids == sorted(ids)
    assert len(set(ids)) == len(ids)


def test_mode_deterministe_reproductible():
    a = IdGenerator.deterministe(42)
    b = IdGenerator.deterministe(42)
    la = [a.nouveau("vs") for _ in range(50)]
    lb = [b.nouveau("vs") for _ in range(50)]
    assert la == lb
    assert la == sorted(la)
    assert IdGenerator.deterministe(43).nouveau("vs") != la[0]


def test_uuid7_hex_horodatage():
    h = uuid7_hex(0x0123456789AB, 0, 0)
    assert h.startswith("0123456789ab7")


def test_id_stable():
    a = id_stable(Prefixe.constat, "dos_1", 3, "C1", "", "ft:x|dec:y")
    assert a == id_stable("f", "dos_1", 3, "C1", "", "ft:x|dec:y")
    assert a != id_stable("f", "dos_1", 4, "C1", "", "ft:x|dec:y")
    assert re.match(r"^f_[0-9a-f]{32}$", a)
    assert a.split("_")[1][12] == "8"
