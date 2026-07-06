"""Client profile: all per-client configuration, injected at the pipeline edge.

The engine contains NO client data.  A :class:`ClientProfile` is loaded from
``config/clients/<name>/`` and made the *active* profile for the duration of an
analysis through a :mod:`contextvars` variable, so several clients can be
processed in the same process without shared mutable state (multi-tenant).

Injection point: ``pipeline.analyze(input_path, profile=...)``.  Business
modules never read client data from disk or from a global; they call
:func:`current_profile` to obtain the profile active for the current run.
"""
from __future__ import annotations

import contextlib
import contextvars
from dataclasses import dataclass
import os
from pathlib import Path
import re
from typing import Optional

try:  # pragma: no cover - setup installs PyYAML
    import yaml
except ImportError:
    yaml = None


from controldone.paths import app_root
_REPO_ROOT = app_root()
_CLIENTS_DIR = _REPO_ROOT / "config" / "clients"
_RULES_DIR = _REPO_ROOT / "config" / "rules"


# Generic, NON-client market data: indicative FX rates used only to catch gross
# currency mistakes (e.g. 10 000 JPY declared as 10 000 EUR).  Shared default;
# a profile may override individual rates via its own fx_rates.yaml.
DEFAULT_FX_RATES = {
    "USD": 1.08, "GBP": 0.84, "CHF": 0.95, "CAD": 1.50,
    "JPY": 165.0, "CNY": 7.85, "HKD": 8.45, "KRW": 1480.0,
    "SGD": 1.45, "MXN": 22.0, "BRL": 5.50, "INR": 90.0,
    "AED": 3.97, "SAR": 4.05, "AUD": 1.65, "NZD": 1.80,
    "NOK": 11.6, "SEK": 11.0, "DKK": 7.46, "TWD": 35.0,
    "THB": 39.0, "MYR": 5.0, "EUR": 1.0,
}


class ProfileError(RuntimeError):
    """Raised when no usable client profile can be resolved."""


def norm_vat(value: object) -> str:
    return "".join(ch for ch in str(value or "").upper() if ch.isalnum())


def _digits(value: object) -> str:
    return re.sub(r"\D", "", str(value or ""))


@dataclass(frozen=True)
class ClientProfile:
    """All configuration specific to one controlled client/entity set."""

    name: str
    entity_name: str
    our_vats: frozenset[str]
    # Ordered (UPPER match, vat) pairs; most specific first.
    name_aliases: tuple[tuple[str, str], ...]
    address_aliases: tuple[tuple[str, str], ...]
    # Ordered (vat, 9-digit SIREN) pairs.
    siren_by_vat: tuple[tuple[str, str], ...]
    entity_label_by_vat: dict[str, str]
    related_out_of_scope_vats: frozenset[str]
    informational_eoris: tuple[str, ...]
    hs_scope: frozenset[str]
    fx_rates: dict[str, float]
    # Digit strings known to be tax IDs (our VAT/SIREN/EORI + third-party
    # numbers seen in documents) so they are never read as HS codes.
    known_tax_ids: frozenset[str]
    # Digit prefixes that disqualify a numeric token from being an HS code.
    hs_exclude_prefixes: tuple[str, ...]
    # UPPER keywords identifying the controlled entity's own documents
    # (used to detect its invoice/proforma/delivery-note formats).
    invoice_keywords: tuple[str, ...]

    # -- identity resolution (was hard-coded & duplicated in parsing/validation) --

    def siren_evidence(self, text: object) -> Optional[str]:
        """Unambiguous SIREN-digit evidence for exactly one entity, else None.

        A printed SIREN beats any name guess (OCR mangles the FR key digits but
        rarely the 9-digit SIREN).  Returns None when several entities' SIRENs
        appear, or none do.
        """
        digits = _digits(text)
        hits = {vat for vat, siren in self.siren_by_vat if siren and siren in digits}
        return next(iter(hits)) if len(hits) == 1 else None

    def identity_vat(self, text: object) -> Optional[str]:
        """Resolve one of our VATs from free text: SIREN, then name, address."""
        if not text:
            return None
        direct = self.siren_evidence(text)
        if direct:
            return direct
        up = str(text).upper()
        for match, vat in self.name_aliases:
            if match in up:
                return vat
        for match, vat in self.address_aliases:
            if match in up:
                return vat
        # Tail: any entity SIREN or full VAT digits present (first wins, no
        # uniqueness requirement — matches the legacy fallback behaviour).
        digits = _digits(text)
        for vat, siren in self.siren_by_vat:
            if (siren and siren in digits) or _digits(vat) in digits:
                return vat
        return None

    def our_vats_in_text(self, text: object, *extra_vats: object) -> set[str]:
        """Which of our VATs appear, by VAT normalisation or SIREN digits."""
        vals = {norm_vat(v) for v in extra_vats}
        digits = _digits(text)
        for vat, siren in self.siren_by_vat:
            if (siren and siren in digits) or _digits(vat) in digits:
                vals.add(vat)
        return {v for v in vals if v in self.our_vats}


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------


def _read_yaml(path: Path) -> dict:
    if yaml is None or not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return data if isinstance(data, dict) else {}


def _load_hs_scope(path: Path) -> frozenset[str]:
    if not path.exists():
        return frozenset()
    out = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        code = re.sub(r"\D", "", stripped)
        if len(code) == 6:
            out.add(code)
    return frozenset(out)


def _load_fx_rates(client_path: Path) -> dict[str, float]:
    rates = dict(DEFAULT_FX_RATES)
    for src in (_RULES_DIR / "fx_rates.yaml", client_path):
        data = _read_yaml(src)
        for code, rate in (data.get("rates") or {}).items():
            try:
                rates[str(code).upper()] = float(rate)
            except (TypeError, ValueError):
                continue
    rates["EUR"] = 1.0
    return rates


def _alias_pairs(raw: object) -> tuple[tuple[str, str], ...]:
    out = []
    for item in (raw or []):
        if isinstance(item, (list, tuple)) and len(item) == 2:
            match, vat = item
        elif isinstance(item, dict):
            match, vat = item.get("match"), item.get("vat")
        else:
            continue
        if match and vat:
            out.append((str(match).upper(), norm_vat(vat)))
    return tuple(out)


def list_profiles() -> list[str]:
    """Names of the client profiles available under config/clients/ (template excluded)."""
    if not _CLIENTS_DIR.is_dir():
        return []
    return sorted(
        p.name for p in _CLIENTS_DIR.iterdir()
        if p.is_dir() and not p.name.startswith("_")
    )


def load_profile(name: str | None = None, *, client_dir: Path | str | None = None) -> ClientProfile:
    """Load a profile from ``config/clients/<name>/`` (or an explicit dir)."""
    if client_dir is not None:
        cdir = Path(client_dir)
        name = name or cdir.name
    else:
        if not name:
            raise ProfileError("load_profile: 'name' ou 'client_dir' requis")
        cdir = _CLIENTS_DIR / name
    if not (cdir / "entities.yaml").exists():
        raise ProfileError(
            f"profil client introuvable: {cdir}/entities.yaml — "
            "créer le dossier à partir de config/clients/_template/"
        )
    ent = _read_yaml(cdir / "entities.yaml")

    entities = ent.get("entities") or []
    siren_by_vat = tuple(
        (norm_vat(e.get("vat")), _digits(e.get("siren")))
        for e in entities if e.get("vat")
    )
    entity_label_by_vat = {
        norm_vat(e.get("vat")): str(e.get("label") or "")
        for e in entities if e.get("vat")
    }
    our_vats = frozenset(
        norm_vat(v) for v in (ent.get("our_vats") or []) if norm_vat(v)
    )
    our_sirens = tuple(siren for _, siren in siren_by_vat if siren)
    our_id_digits = set(our_sirens) | {_digits(vat) for vat, _ in siren_by_vat if _digits(vat)}
    known_non_hs_ids = {_digits(x) for x in (ent.get("known_non_hs_ids") or []) if _digits(x)}
    hs_exclude_prefixes = our_sirens + tuple(
        _digits(x) for x in (ent.get("hs_exclude_prefixes") or []) if _digits(x)
    )
    return ClientProfile(
        name=name,
        entity_name=str(ent.get("entity_name") or name),
        our_vats=our_vats,
        name_aliases=_alias_pairs(ent.get("name_aliases")),
        address_aliases=_alias_pairs(ent.get("address_aliases")),
        siren_by_vat=siren_by_vat,
        entity_label_by_vat=entity_label_by_vat,
        related_out_of_scope_vats=frozenset(
            norm_vat(v) for v in (ent.get("related_but_out_of_scope_vats") or []) if norm_vat(v)
        ),
        informational_eoris=tuple(str(e) for e in (ent.get("informational_eoris") or [])),
        hs_scope=_load_hs_scope(cdir / "hs_scope.txt"),
        fx_rates=_load_fx_rates(cdir / "fx_rates.yaml"),
        known_tax_ids=frozenset(our_id_digits | known_non_hs_ids),
        hs_exclude_prefixes=hs_exclude_prefixes,
        invoice_keywords=tuple(
            str(k).upper() for k in (ent.get("invoice_keywords") or []) if str(k).strip()
        ),
    )


def resolve_default_profile() -> ClientProfile:
    """Resolve the profile to use when none was passed explicitly.

    Order: ``CONTROLDONE_CLIENT`` env var, else the single client directory
    present in ``config/clients/`` (excluding ``_template``).  Raises when the
    choice is ambiguous or no profile exists.
    """
    env = os.environ.get("CONTROLDONE_CLIENT")
    if env:
        return load_profile(env)
    candidates = []
    if _CLIENTS_DIR.exists():
        candidates = [
            d for d in sorted(_CLIENTS_DIR.iterdir())
            if d.is_dir() and d.name != "_template" and (d / "entities.yaml").exists()
        ]
    if len(candidates) == 1:
        return load_profile(client_dir=candidates[0])
    if len(candidates) > 1:
        names = ", ".join(d.name for d in candidates)
        raise ProfileError(
            f"plusieurs profils clients ({names}) — définir CONTROLDONE_CLIENT"
        )
    raise ProfileError(
        "aucun profil client — créer config/clients/<client>/ à partir de _template"
    )


# ---------------------------------------------------------------------------
# Active profile (per-context, multi-tenant safe)
# ---------------------------------------------------------------------------


_active: contextvars.ContextVar[Optional[ClientProfile]] = contextvars.ContextVar(
    "controldone_active_profile", default=None
)


def current_profile() -> ClientProfile:
    """Return the profile active for the current run.

    If none was injected (the normal path injects via ``use_profile`` at the
    pipeline edge), the default profile is resolved as a convenience for direct
    callers and scripts — without being pinned to the current context.
    """
    profile = _active.get()
    if profile is None:
        # No profile injected (direct caller/script outside use_profile):
        # resolve a default but do NOT pin it, so a default never persists in a
        # reused context/thread and leaks across clients.
        return resolve_default_profile()
    return profile


def set_active_profile(profile: Optional[ClientProfile]) -> None:
    """Set (or clear with ``None``) the active profile for the current context."""
    _active.set(profile)


@contextlib.contextmanager
def use_profile(profile: ClientProfile):
    """Activate ``profile`` for the duration of the ``with`` block."""
    token = _active.set(profile)
    try:
        yield profile
    finally:
        _active.reset(token)
