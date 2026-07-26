from __future__ import annotations

import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / "local_trigger_runner.py"
ORIGINAL_SHA256 = "b47d6a0f0ef7a007798bf64cc6102a364b42569739600eb898bbb8ea2e363f70"
CORRECTED_SHA256 = "46b3ba0f1875ba66c827d3e48c044dabf3108890446fba9e3f0542e4ada3bb0d"
CORRECTED_BYTES = 32593

REPLACEMENTS = (
    (
        '    "update_intensity_1s", "volatility_30s_bps", "valid", "segment", "bin",\n'
        '    "date", "symbol",\n',
        '    "update_intensity_1s", "volatility_30s_bps", "valid", "segment",\n'
        '    "date", "symbol",\n',
    ),
    (
        '              "flow_1s", "update_intensity_1s", "volatility_30s_bps", "state_age_us", "segment", "bin"):\n',
        '              "flow_1s", "update_intensity_1s", "volatility_30s_bps", "state_age_us", "segment"):\n',
    ),
    (
        '        & ((states["bin"].to_numpy(np.int64) % DECISION_STRIDE) == 0)\n',
        '        & ((((states["decision_us"].to_numpy(np.int64) // BIN_US) % DECISION_STRIDE) == 0))\n',
    ),
)


def sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def main() -> int:
    raw = SOURCE.read_bytes()
    if sha256(raw) != ORIGINAL_SHA256:
        raise RuntimeError("unexpected original local-trigger runner identity")
    text = raw.decode("utf-8")
    for old, new in REPLACEMENTS:
        if text.count(old) != 1:
            raise RuntimeError("expected correction anchor not found exactly once")
        text = text.replace(old, new, 1)
    corrected = text.encode("utf-8")
    if len(corrected) != CORRECTED_BYTES:
        raise RuntimeError("corrected byte count mismatch")
    if sha256(corrected) != CORRECTED_SHA256:
        raise RuntimeError("corrected source identity mismatch")
    compile(corrected, str(SOURCE), "exec")
    SOURCE.write_bytes(corrected)
    print(f"APPLIED_DECISION_TIME_CORRECTION sha256={sha256(corrected)} bytes={len(corrected)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
