from pathlib import Path
import sys

_ROOT = Path(__file__).resolve().parents[3]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

try:
    from shared.version import __version__
except ImportError:  # pragma: no cover
    __version__ = "0.1.0"
