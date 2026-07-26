from __future__ import annotations

import base64
import gzip
import hashlib
import importlib.util
import sys
import tempfile
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
_PARTS = sorted(_ROOT.glob("implementation.b64.part*"))
if not _PARTS:
    raise RuntimeError("compressed path-continuity implementation parts are missing")
_ENCODED = "".join(path.read_text(encoding="utf-8").strip() for path in _PARTS)
_RAW = gzip.decompress(base64.b64decode(_ENCODED, validate=True))
_EXPECTED = (_ROOT / "implementation.sha256").read_text(encoding="utf-8").strip()
_OBSERVED = hashlib.sha256(_RAW).hexdigest()
if _OBSERVED != _EXPECTED:
    raise RuntimeError(f"implementation SHA-256 mismatch: {_OBSERVED} != {_EXPECTED}")

_TEMP = Path(tempfile.gettempdir()) / f"ml_path_continuity_{_OBSERVED}.py"
if not _TEMP.exists() or _TEMP.read_bytes() != _RAW:
    _TEMP.write_bytes(_RAW)
_SPEC = importlib.util.spec_from_file_location("_ml_path_continuity_impl", _TEMP)
if _SPEC is None or _SPEC.loader is None:
    raise RuntimeError("unable to load verified implementation")
_IMPL = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = _IMPL
_SPEC.loader.exec_module(_IMPL)

# Mechanical transport failover only. The scientific implementation, model,
# features, partitions, costs, execution rules and gates remain SHA-frozen.
# These are Bybit's documented mainnet and regional REST hosts. A request is
# accepted only when the same frozen endpoint succeeds; no market row or
# response is altered, merged or selected by outcome.
_IMPL.API_BASES = (
    "https://api.bybit.com",
    "https://api.bytick.com",
    "https://api.bybit.nl",
    "https://api.bybit.tr",
    "https://api.bybit.kz",
    "https://api.bybitgeorgia.ge",
    "https://api.bybit.ae",
    "https://api.bybit.eu",
    "https://api.bybit.id",
    "https://api.manepa.jp",
)

for _name in dir(_IMPL):
    if not _name.startswith("__"):
        globals()[_name] = getattr(_IMPL, _name)

IMPLEMENTATION_SHA256 = _OBSERVED
IMPLEMENTATION_PART_COUNT = len(_PARTS)
TRANSPORT_FAILOVER_HOSTS = _IMPL.API_BASES

if __name__ == "__main__":
    raise SystemExit(_IMPL.main())
