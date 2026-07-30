from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

PARENT_COMMIT = "c9e805493048b9a0d8e9dab4cc05a0d3ae69853"
PARENT_PATH = "research/volume_sponsored_48h24h_lifecycle/audit_lifecycle.py"
PARENT_SOURCE_SHA256 = "e3bcb07a605fe3c6b8a20894f14ef820c60a48b3e9b8b633b4cebe76c8ff49ef"
EXPECTED = {
    "2022": {"multiple": 1.3031107602166192, "trades": 51},
    "2023": {"multiple": 1.1993842590180963, "trades": 75},
    "official_24bp": {"multiple": 1.3525318555240424, "trades": 143},
}


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def exact_replace(text: str, old: str, new: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"expected one exact source fragment, found {count}: {old!r}")
    return text.replace(old, new, 1)


def recover_parent_source(repo_root: Path) -> bytes:
    completed = subprocess.run(
        ["git", "-C", str(repo_root), "show", f"{PARENT_COMMIT}:{PARENT_PATH}"],
        check=True,
        capture_output=True,
    )
    source = completed.stdout
    observed = sha256(source)
    if observed != PARENT_SOURCE_SHA256:
        raise RuntimeError(f"parent source SHA mismatch: {observed} != {PARENT_SOURCE_SHA256}")
    return source


def patch_accessible_canonical_schema(source: bytes) -> bytes:
    """Map only the accessible 1m completed-row name; do not change strategy semantics."""
    text = source.decode("utf-8")
    text = exact_replace(
        text,
        "'start_time_ms','open','high','low','close','is_complete','available_at_ms'\n        ])\n        m=m[m.is_complete & m.available_at_ms.notna()]",
        "'start_time_ms','open','high','low','close','observed','available_at_ms'\n        ])\n        m=m[m.observed & m.available_at_ms.notna()]",
    )
    text = exact_replace(
        text,
        "'start_time_ms','open','close','is_complete','available_at_ms'\n        ])\n        mark=mark[mark.is_complete & mark.available_at_ms.notna()]",
        "'start_time_ms','open','close','observed','available_at_ms'\n        ])\n        mark=mark[mark.observed & mark.available_at_ms.notna()]",
    )
    return text.encode("utf-8")


def compare(observed: dict[str, Any], expected: dict[str, Any]) -> dict[str, Any]:
    error = abs(float(observed["multiple"]) - float(expected["multiple"]))
    return {
        "expected_multiple": expected["multiple"],
        "observed_multiple": observed["multiple"],
        "absolute_multiple_error": error,
        "expected_trades": expected["trades"],
        "observed_trades": observed["trades"],
        "trade_count_match": int(observed["trades"]) == int(expected["trades"]),
        "multiple_match_1e_8": error <= 1e-8,
    }


def main(repo_root: Path, data_root: Path, output_root: Path) -> None:
    output_root.mkdir(parents=True, exist_ok=True)
    work = output_root / "materialized_parent"
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)

    parent = recover_parent_source(repo_root)
    patched = patch_accessible_canonical_schema(parent)
    script = work / "audit_lifecycle.py"
    script.write_bytes(patched)
    parent_output = output_root / "parent_output"
    parent_output.mkdir(parents=True, exist_ok=True)

    run = subprocess.run(
        [
            sys.executable,
            str(script),
            "--data-root",
            str(data_root),
            "--output-root",
            str(parent_output),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    (output_root / "PARENT_STDOUT.log").write_text(run.stdout, encoding="utf-8")
    (output_root / "PARENT_STDERR.log").write_text(run.stderr, encoding="utf-8")

    parent_result = json.loads((parent_output / "RESULT.json").read_text(encoding="utf-8"))
    observed = {
        "2022": parent_result["pre2024"]["parent"]["2022"]["base"],
        "2023": parent_result["pre2024"]["parent"]["2023"]["base"],
        "official_24bp": parent_result["programization_audit"]["parent_corrected"],
    }
    parity = {key: compare(observed[key], EXPECTED[key]) for key in EXPECTED}
    exact = all(x["trade_count_match"] and x["multiple_match_1e_8"] for x in parity.values())
    result = {
        "schema_version": 1,
        "claim_id": "CLM-20260731-48H24H-GATE-AUDIT-001",
        "result_id": "RES-20260731-48H24H-GATE-AUDIT-001",
        "status": "EXACT_PARENT_PARITY" if exact else "HARD_INVALID_PARENT_PARITY_FAILURE",
        "parent_source_sha256": PARENT_SOURCE_SHA256,
        "patched_source_sha256": sha256(patched),
        "schema_patch": "1m trade and mark is_complete -> observed compatibility alias only",
        "parity": parity,
        "economic_interpretation_opened": exact,
        "orders_submitted": False,
    }
    path = output_root / "AUTHORITY_PARITY.json"
    path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    (output_root / "AUTHORITY_PARITY.sha256").write_text(
        f"{sha256(path.read_bytes())}  AUTHORITY_PARITY.json\n", encoding="utf-8"
    )
    print(json.dumps(result, indent=2), flush=True)
    if not exact:
        raise SystemExit(3)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args()
    main(args.repo_root, args.data_root, args.output_root)
