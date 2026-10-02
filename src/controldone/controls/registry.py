"""Registre des contrôles : ``@control("C3")`` (SPEC §8.1, Annexe A)."""

from __future__ import annotations

import importlib
import pkgutil
from collections.abc import Callable, Iterable, Iterator
from contextlib import contextmanager

from controldone.controls.specs import ORDRE_CONTROLES, get_spec
from controldone.model.resultats import ResultatControle

__all__ = [
    "ControlFn",
    "charger_controles",
    "control",
    "controles_enregistres",
    "desenregistrer",
    "registre_temporaire",
]

ControlFn = Callable[..., Iterable[ResultatControle]]

_REGISTRE: dict[str, ControlFn] = {}
_CHARGEMENT_AUTO = True


def control(controle_id: str) -> Callable[[ControlFn], ControlFn]:
    """Enregistre une fonction de contrôle ``fn(ctx: ControlContext) -> Iterable[ResultatControle]``.

    L'identifiant doit figurer à l'Annexe A. Un même identifiant ne peut être enregistré que par une
    seule fonction (le rechargement du même module est toléré).
    """
    get_spec(controle_id)

    def decorateur(fn: ControlFn) -> ControlFn:
        existant = _REGISTRE.get(controle_id)
        if existant is not None and (existant.__module__, existant.__qualname__) != (fn.__module__, fn.__qualname__):
            raise ValueError(
                f"contrôle {controle_id} déjà enregistré par {existant.__module__}.{existant.__qualname__}"
            )
        fn.controle_id = controle_id  # type: ignore[attr-defined]
        _REGISTRE[controle_id] = fn
        return fn

    return decorateur


def desenregistrer(controle_id: str) -> None:
    """Retire un contrôle du registre (tests)."""
    _REGISTRE.pop(controle_id, None)


def controles_enregistres() -> dict[str, ControlFn]:
    """Contrôles enregistrés, dans l'ordre d'exécution (Annexe A)."""
    return {cid: _REGISTRE[cid] for cid in ORDRE_CONTROLES if cid in _REGISTRE}


def charger_controles() -> None:
    """Importe tous les modules ``controldone.controls.famille_*`` (qui s'enregistrent à l'import)."""
    if not _CHARGEMENT_AUTO:
        return
    import controldone.controls as paquet

    for info in sorted(pkgutil.iter_modules(paquet.__path__), key=lambda m: m.name):
        if info.name.startswith("famille_"):
            importlib.import_module(f"{paquet.__name__}.{info.name}")


@contextmanager
def registre_temporaire() -> Iterator[dict[str, ControlFn]]:
    """Registre vide et isolé le temps d'un test (pas de chargement des familles) ; restauré ensuite."""
    global _REGISTRE, _CHARGEMENT_AUTO
    sauve, auto = _REGISTRE, _CHARGEMENT_AUTO
    _REGISTRE, _CHARGEMENT_AUTO = {}, False
    try:
        yield _REGISTRE
    finally:
        _REGISTRE, _CHARGEMENT_AUTO = sauve, auto
