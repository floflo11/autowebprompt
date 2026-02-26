"""Root conftest.py — ensure src/autowebprompt is importable without pip install."""

import sys
from pathlib import Path

# Insert src/ directory at the front of sys.path so that
# `import autowebprompt` resolves to src/autowebprompt/ (the real package)
# rather than falling back to a namespace-package stub.
_src_dir = str(Path(__file__).resolve().parent / "src")
if _src_dir not in sys.path:
    sys.path.insert(0, _src_dir)
