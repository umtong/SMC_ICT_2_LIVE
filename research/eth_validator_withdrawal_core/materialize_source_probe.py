from __future__ import annotations

import argparse
import shutil
from pathlib import Path

OLD_INT = "        values.append(int(value))\n"
NEW_INT = """        if isinstance(value, (bytes, bytearray, memoryview)):
            # ClickHouse UInt128 is stored by Xatu Parquet as 16-byte
            # little-endian fixed binary. Decode the physical representation
            # exactly before applying the protocol's Gwei scale.
            values.append(int.from_bytes(bytes(value), byteorder=\"little\", signed=False))
        else:
            values.append(int(value))
"""

OLD_TIME = """        if isinstance(value, datetime):
            dt = value
        else:
            dt = datetime.fromisoformat(str(value).replace(\"Z\", \"+00:00\"))
"""
NEW_TIME = """        if isinstance(value, datetime):
            dt = value
        elif isinstance(value, (int, float)):
            # Xatu stores this DateTime physical column as Unix seconds in the
            # public Parquet export. Interpret it explicitly as UTC.
            dt = datetime.fromtimestamp(value, tz=timezone.utc)
        else:
            dt = datetime.fromisoformat(str(value).replace(\"Z\", \"+00:00\"))
"""


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"expected one {label} site, found {count}")
    return text.replace(old, new)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    root = Path(__file__).resolve().parent
    text = (root / "source_probe.py").read_text()
    text = replace_once(text, OLD_INT, NEW_INT, "UInt128 decode")
    text = replace_once(text, OLD_TIME, NEW_TIME, "Unix timestamp decode")

    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "source_probe.py").write_text(text)
    shutil.copy2(root / "test_source_probe.py", args.out / "test_source_probe.py")
    print("materialized UInt128- and Unix-time-aware source probe")


if __name__ == "__main__":
    main()
