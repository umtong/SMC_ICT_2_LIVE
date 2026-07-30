from __future__ import annotations

import base64
import gzip
from pathlib import Path

_PAYLOAD = Path(__file__).with_name("audit.py.gz.b64")
_SOURCE = gzip.decompress(base64.b64decode(_PAYLOAD.read_text(encoding="utf-8").strip())).decode("utf-8")
exec(compile(_SOURCE, str(Path(__file__).with_name("audit_impl.py")), "exec"), globals(), globals())
