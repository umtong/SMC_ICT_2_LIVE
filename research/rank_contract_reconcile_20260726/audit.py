from __future__ import annotations

import base64
import hashlib
import json
import re
import tarfile
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
SOURCE_ROOT = ROOT / "research" / "dynamic_factor_residual_20260725"
DONCHIAN_RESULT = (
    ROOT
    / "research"
    / "donchian_trade_dependence_20260726"
    / "results"
    / "result.json"
)
RANKING = ROOT / "control" / "ranking.json"
OUT = ROOT / "research_results" / "rank_contract_reconcile_20260726"

PARTS = (
    "extension_bundle.tar.gz.b64.part00",
    "extension_bundle.tar.gz.b64.part01a",
    "extension_bundle.tar.gz.b64.part01b",
    "extension_bundle.tar.gz.b64.part01c",
    "extension_bundle.tar.gz.b64.part02",
)


def sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def stable_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def line_windows(text: str, pattern: str, radius: int = 4) -> list[dict[str, Any]]:
    lines = text.splitlines()
    hits: list[dict[str, Any]] = []
    regex = re.compile(pattern, re.IGNORECASE)
    seen: set[tuple[int, int]] = set()
    for index, line in enumerate(lines):
        if not regex.search(line):
            continue
        start = max(0, index - radius)
        end = min(len(lines), index + radius + 1)
        key = (start, end)
        if key in seen:
            continue
        seen.add(key)
        hits.append(
            {
                "match_line": index + 1,
                "start_line": start + 1,
                "end_line": end,
                "text": "\n".join(
                    f"{line_number + 1:04d}: {lines[line_number]}"
                    for line_number in range(start, end)
                ),
            }
        )
    return hits


def recursive_find(value: Any, key_pattern: str) -> list[dict[str, Any]]:
    regex = re.compile(key_pattern, re.IGNORECASE)
    found: list[dict[str, Any]] = []

    def walk(item: Any, path: str) -> None:
        if isinstance(item, dict):
            for key, child in item.items():
                child_path = f"{path}.{key}" if path else str(key)
                if regex.search(str(key)):
                    found.append({"path": child_path, "value": child})
                walk(child, child_path)
        elif isinstance(item, list):
            for index, child in enumerate(item):
                walk(child, f"{path}[{index}]")

    walk(value, "")
    return found


def main() -> int:
    manifest = load_json(SOURCE_ROOT / "EXTENSION_BUNDLE_MANIFEST.json")
    encoded = b"".join((SOURCE_ROOT / part).read_bytes() for part in PARTS)
    if sha256(encoded) != manifest["combined_base64_sha256"]:
        raise RuntimeError("combined base64 SHA-256 mismatch")
    archive = base64.b64decode(b"".join(encoded.split()), validate=True)
    if sha256(archive) != manifest["decoded_tar_gz_sha256"]:
        raise RuntimeError("decoded tar.gz SHA-256 mismatch")
    if len(archive) != int(manifest["decoded_tar_gz_bytes"]):
        raise RuntimeError("decoded tar.gz byte count mismatch")

    with tempfile.TemporaryDirectory(prefix="rank-contract-audit-") as temporary:
        temp = Path(temporary)
        archive_path = temp / "extension_bundle.tar.gz"
        archive_path.write_bytes(archive)
        with tarfile.open(archive_path, "r:gz") as bundle:
            bundle.extractall(temp / "bundle", filter="data")
        files = list((temp / "bundle").rglob("*"))
        extracted = {path.name: path for path in files if path.is_file()}

        expected = {item["path"]: item for item in manifest["contents"]}
        verified: dict[str, dict[str, Any]] = {}
        for name, item in expected.items():
            path = extracted.get(name)
            if path is None:
                raise RuntimeError(f"bundle member missing: {name}")
            payload = path.read_bytes()
            if len(payload) != int(item["bytes"]):
                raise RuntimeError(f"bundle member byte mismatch: {name}")
            if sha256(payload) != item["sha256"]:
                raise RuntimeError(f"bundle member SHA-256 mismatch: {name}")
            verified[name] = {"bytes": len(payload), "sha256": sha256(payload)}

        state_source = extracted["state_exit.py"].read_text(encoding="utf-8")
        state_result = load_json(extracted["state_exit_result.json"])
        state_summary = load_json(extracted["state_exit_result_summary.json"])
        comparison = load_json(extracted["revision5_champion_comparison.json"])

    ranking = load_json(RANKING)
    donchian = load_json(DONCHIAN_RESULT)
    current = ranking["first_place"]
    current_growth = float(current["metrics"]["geometric_daily_growth"])
    current_24_return = float(current["metrics"]["return_at_24bps"])
    donchian_path = donchian["highest_raw_path"]
    donchian_growth_24 = float(donchian_path["24bps"]["geometric_daily_growth"])

    hold_windows = line_windows(
        state_source,
        r"maximum_hold_bars|max_hold|hold_deadline|time[_ -]?exit|entry_bar\s*\+",
        radius=5,
    )
    exit_windows = line_windows(
        state_source,
        r"exit_reason|reason.*hold|hold.*reason|maximum.*hold|forced.*exit",
        radius=5,
    )
    result_hold_fields = {
        "state_exit_result": recursive_find(state_result, r"hold|elapsed|time"),
        "state_exit_result_summary": recursive_find(state_summary, r"hold|elapsed|time"),
        "revision5_champion_comparison": recursive_find(comparison, r"hold|elapsed|time"),
    }

    evidence = {
        "schema_version": 1,
        "claim_id": "CLM-20260726-2014-RANK-CONTRACT-RECONCILE-001",
        "status": "AUDIT_COMPLETE_NO_MARKET_REPLAY",
        "source_bundle": {
            "combined_base64_sha256": sha256(encoded),
            "decoded_tar_gz_sha256": sha256(archive),
            "verified_members": verified,
        },
        "current_first_place": {
            "first_place_id": current["first_place_id"],
            "source_result_id": current["source_result_id"],
            "candidate_id": current["metrics"]["candidate_id"],
            "geometric_daily_growth": current_growth,
            "return_at_24bps": current_24_return,
            "comparison_confidence": current["comparison_confidence"],
            "source_parameters_with_hold_or_time": result_hold_fields,
        },
        "state_exit_source_audit": {
            "state_exit_sha256": sha256(state_source.encode("utf-8")),
            "contains_maximum_hold_bars": "maximum_hold_bars" in state_source,
            "contains_hold_bar_arithmetic": bool(
                re.search(r"entry\w*\s*\+\s*\w*\.maximum_hold_bars", state_source)
                or re.search(r"maximum_hold_bars", state_source)
            ),
            "hold_related_windows": hold_windows,
            "exit_related_windows": exit_windows,
        },
        "higher_recorded_growth_challenger": {
            "source_result_id": donchian["result_id"],
            "candidate_label": (
                f"Donchian {donchian_path['mode']} "
                f"{donchian_path['timeframe_min']}m/{donchian_path['entry_lb']}/"
                f"{donchian_path['exit_lb']}"
            ),
            "geometric_daily_growth_at_24bps": donchian_growth_24,
            "growth_delta_vs_current_first_base_cost": donchian_growth_24 - current_growth,
            "growth_ratio_vs_current_first_base_cost": donchian_growth_24 / current_growth,
            "total_return_at_24bps": donchian_path["24bps"]["total_return"],
            "profit_factor_at_24bps": donchian_path["24bps"]["profit_factor"],
            "maximum_drawdown_at_24bps": donchian_path["24bps"]["maximum_drawdown"],
            "trade_count": donchian_path["24bps"]["trade_count"],
            "top10pct_removed_return": donchian_path["24bps"]["top10pct_removed_return"],
            "hard_validity_status": donchian["hard_validity_status"],
            "known_limitations": donchian["known_limitations"],
        },
        "authority": {
            "market_data_opened": False,
            "strategy_replayed": False,
            "model_fit_performed": False,
            "parameters_searched": False,
            "official_2024_2026_opened": False,
            "credentials_used": False,
            "orders_submitted": False,
        },
    }

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "AUDIT.json").write_text(
        json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    snippets: list[str] = []
    for section, windows in (
        ("HOLD RELATED SOURCE WINDOWS", hold_windows),
        ("EXIT RELATED SOURCE WINDOWS", exit_windows),
    ):
        snippets.append(f"===== {section} =====")
        for window in windows:
            snippets.append(window["text"])
            snippets.append("")
    snippets.append("===== RESULT FIELDS CONTAINING HOLD / ELAPSED / TIME =====")
    snippets.append(json.dumps(result_hold_fields, indent=2, sort_keys=True))
    (OUT / "SOURCE_EVIDENCE.txt").write_text(
        "\n".join(snippets) + "\n", encoding="utf-8"
    )
    (OUT / "SHA256SUMS.txt").write_text(
        "\n".join(
            f"{sha256(path.read_bytes())}  {path.name}"
            for path in sorted(OUT.glob("*"))
            if path.name != "SHA256SUMS.txt"
        )
        + "\n",
        encoding="utf-8",
    )
    print(stable_json(evidence))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
