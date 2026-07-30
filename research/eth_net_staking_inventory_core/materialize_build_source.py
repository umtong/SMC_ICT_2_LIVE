from __future__ import annotations

import argparse
import shutil
from pathlib import Path

REPLACEMENTS = [
    (
        '    "deposit_data_signature",\n}',
        '    "deposit_data_signature",\n    "deposit_proof",\n}',
    ),
    (
        '    signatures = [normalize_text(value) for value in table["deposit_data_signature"].to_pylist()]\n',
        '    signatures = [normalize_text(value) for value in table["deposit_data_signature"].to_pylist()]\n'
        '    proofs = table["deposit_proof"].to_pylist()\n',
    ),
    (
        '    event_keys = {\n'
        '        f"{root}:{pubkey}:{signature}"\n'
        '        for root, pubkey, signature in zip(roots, pubkeys, signatures, strict=True)\n'
        '    }\n',
        '    event_keys: set[str] = set()\n'
        '    for root, pubkey, signature, proof in zip(\n'
        '        roots, pubkeys, signatures, proofs, strict=True\n'
        '    ):\n'
        '        proof_parts = [normalize_text(item) for item in (proof or [])]\n'
        '        proof_hash = hashlib.sha256("|".join(proof_parts).encode()).hexdigest()\n'
        '        event_keys.add(f"{root}:{pubkey}:{signature}:{proof_hash}")\n',
    ),
]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    text = (root / "build_source.py").read_text()
    for old, new in REPLACEMENTS:
        count = text.count(old)
        if count != 1:
            raise SystemExit(f"expected one source occurrence, found {count}: {old[:60]!r}")
        text = text.replace(old, new)
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "build_source.py").write_text(text)
    shutil.copy2(root / "test_build_source.py", args.out / "test_build_source.py")
    print("materialized deposit-proof-aware source reader")


if __name__ == "__main__":
    main()
