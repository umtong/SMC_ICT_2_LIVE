from __future__ import annotations

import argparse
import shutil
from pathlib import Path

OLD = "        values.append(int(value))\n"
NEW = """        if isinstance(value, (bytes, bytearray, memoryview)):
            # ClickHouse UInt128 is stored by Xatu Parquet as 16-byte
            # little-endian fixed binary.  Decode the physical representation
            # exactly before applying the protocol's Gwei scale.
            values.append(int.from_bytes(bytes(value), byteorder=\"little\", signed=False))
        else:
            values.append(int(value))
"""


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    root = Path(__file__).resolve().parent
    text = (root / "source_probe.py").read_text()
    count = text.count(OLD)
    if count != 1:
        raise SystemExit(f"expected one UInt128 decode site, found {count}")

    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "source_probe.py").write_text(text.replace(OLD, NEW))
    shutil.copy2(root / "test_source_probe.py", args.out / "test_source_probe.py")
    print("materialized UInt128-aware source probe")


if __name__ == "__main__":
    main()
