"""Les doubles de test (``doubles.py``) sont importables depuis les tests d'assemblage."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
