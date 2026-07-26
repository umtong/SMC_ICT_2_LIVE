from __future__ import annotations

import hashlib
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent
TARGET = ROOT / "run.py"
ORIGINAL_SHA256 = "12a03ca81fe5ff4d85524832804b0600062081b2e69fcb8458e2e1bc77428bfe"


def sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def main() -> int:
    raw = TARGET.read_bytes()
    observed = sha256(raw)
    if observed != ORIGINAL_SHA256:
        raise RuntimeError(f"unexpected reconstructed source SHA-256: {observed}")

    text = raw.decode("utf-8")
    text, sentinel_count = re.subn(
        r"(?m)^([ \t]*)last_event_time\s*=\s*pd\.Timestamp\.min(?:\.tz_localize\((?:\"UTC\"|'UTC')\))?\s*$",
        r"\1last_event_time: pd.Timestamp | None = None",
        text,
    )
    text, guard_count = re.subn(
        r"(?m)^([ \t]*)if decision_time - last_event_time < pd\.Timedelta\(minutes=EVENT_COOLDOWN_MINUTES\):\s*$",
        r"\1if last_event_time is not None and decision_time - last_event_time < pd.Timedelta(minutes=EVENT_COOLDOWN_MINUTES):",
        text,
    )
    if sentinel_count != 1 or guard_count != 1:
        raise RuntimeError(
            f"cooldown sentinel patch count mismatch: sentinel={sentinel_count}, guard={guard_count}"
        )

    patched = text.encode("utf-8")
    TARGET.write_bytes(patched)
    print(
        f"applied pre-outcome cooldown-sentinel fix: original={observed} patched={sha256(patched)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
