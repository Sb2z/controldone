"""Resolution of the application root and derived data directories.

Historically ``data/cache`` and friends were resolved against the current
working directory, which broke cache reuse and job folders as soon as the
process was started from anywhere else (scheduled task, orchestrator step,
installed package). Everything now anchors on a single root:

- ``CONTROLDONE_HOME`` when set (recommended for installed/automated runs);
- otherwise the repository root (detected from this file's location);
- otherwise the current working directory.
"""
from __future__ import annotations

import os
from pathlib import Path


def app_root() -> Path:
    env = os.environ.get("CONTROLDONE_HOME")
    if env:
        return Path(env).expanduser().resolve()
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "config" / "clients").is_dir() or (parent / "pyproject.toml").is_file():
            return parent
    return Path.cwd()


def data_dir(*parts: str) -> Path:
    return app_root().joinpath("data", *parts)
