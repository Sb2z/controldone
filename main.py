"""Local launcher for ControlDOne.

This wrapper keeps `python main.py` working without requiring an editable
install first.  Production/app integrations should import `controldone.pipeline`
or run `python -m controldone.cli` after installing the package.
"""
from __future__ import annotations

import os
import sys


ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
SRC_DIR = os.path.join(ROOT_DIR, "src")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

from controldone.cli import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main())
