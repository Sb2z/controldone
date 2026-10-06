"""Relais des étapes fines du pipeline vers ``JobContext.etape`` (D-3709) — sans base de données."""

from __future__ import annotations

from controldone.jobs.handlers import executer_avec_delai, relais_progression


class _Ctx:
    def __init__(self) -> None:
        self.etapes: list[str] = []

    def etape(self, nom: str) -> None:
        self.etapes.append(nom)


def test_relais_limite_les_ecritures():
    ctx, t = _Ctx(), [0.0]
    relais = relais_progression(ctx, intervalle_s=2.0, horloge=lambda: t[0])
    relais("pages", 0, 3)
    relais("pages", 1, 3)  # même étape, trop tôt : pas d'écriture
    t[0] = 2.5
    relais("pages", 2, 3)
    relais("pages", 3, 3)  # fin d'étape : toujours écrite
    relais("regroupement", 0, 1)
    relais("controles", 0, 2)
    assert ctx.etapes == ["pages 0/3", "pages 2/3", "pages 3/3", "regroupement", "controles 0/2"]
    assert all(len(e) <= 32 for e in ctx.etapes)


class _Options:
    progression = None


def _pipeline_qui_progresse(n, *, options):
    for i in range(n):
        options.progression("extraction", i, n)
    return n * 10


def test_progression_relayee_depuis_le_processus_fils():
    vus: list[tuple[str, int, int]] = []
    out = executer_avec_delai(
        _pipeline_qui_progresse, (3,), {"options": _Options()}, 60.0, progression=lambda *a: vus.append(a)
    )
    assert out == 30
    assert vus == [("extraction", 0, 3), ("extraction", 1, 3), ("extraction", 2, 3)]
