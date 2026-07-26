from __future__ import annotations

import argparse
import json
import re
import urllib.parse
from dataclasses import asdict
from pathlib import Path
from typing import Any

from inventory_hf_source import (
    BASE,
    PARQUET_OR_LZ4_RE,
    REPOSITORY,
    extract_date_hour,
    fetch_json,
    normalize_tree_item,
)


def normalize_sibling(item: Any) -> dict[str, Any] | None:
    if not isinstance(item, dict):
        return None
    path = item.get("rfilename")
    if not isinstance(path, str) or not path:
        return None
    return {
        "path": path,
        "type": "file",
        "size": None,
        "oid": None,
        "lfs_oid": None,
        "lfs_size": None,
        "xet_hash": None,
        "last_commit": None,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output
    output.mkdir(parents=True, exist_ok=True)

    probes = []
    metadata_probe, metadata = fetch_json(
        "dataset_metadata", f"{BASE}/api/datasets/{REPOSITORY}", output
    )
    probes.append(metadata_probe)
    commits_probe, commits = fetch_json(
        "commits_main", f"{BASE}/api/datasets/{REPOSITORY}/commits/main?limit=100", output
    )
    probes.append(commits_probe)

    metadata_siblings: list[dict[str, Any]] = []
    if isinstance(metadata, dict) and isinstance(metadata.get("siblings"), list):
        for item in metadata["siblings"]:
            normalized = normalize_sibling(item)
            if normalized is not None:
                metadata_siblings.append(normalized)

    quoted_revision = urllib.parse.quote("main", safe="")
    next_url: str | None = (
        f"{BASE}/api/datasets/{REPOSITORY}/tree/{quoted_revision}/data"
        "?recursive=false&expand=false&limit=100"
    )
    tree_items: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    page = 0
    terminal_tree_success = False
    while next_url:
        if next_url in seen_urls:
            raise RuntimeError("Hugging Face tree pagination repeated a URL")
        seen_urls.add(next_url)
        probe, parsed = fetch_json(f"tree_data_page_{page:04d}", next_url, output)
        probes.append(probe)
        if probe.status != 200 or not isinstance(parsed, list):
            break
        for item in parsed:
            normalized = normalize_tree_item(item)
            if normalized is not None:
                tree_items.append(normalized)
        page += 1
        next_url = probe.next_url
        terminal_tree_success = next_url is None
        if page > 50:
            raise RuntimeError("Unexpectedly large tree pagination")

    by_path: dict[str, dict[str, Any]] = {}
    for item in metadata_siblings:
        by_path[item["path"]] = item
    for item in tree_items:
        existing = by_path.get(item["path"], {})
        by_path[item["path"]] = {**existing, **item}
    files = [by_path[path] for path in sorted(by_path)]
    data_files = [
        item
        for item in files
        if item.get("type") == "file"
        and item["path"].startswith("data/")
        and PARQUET_OR_LZ4_RE.search(item["path"])
    ]

    dates: dict[str, list[int]] = {}
    unknown_date_paths: list[str] = []
    for item in data_files:
        parsed = extract_date_hour(item["path"])
        if parsed is None:
            unknown_date_paths.append(item["path"])
            continue
        date, hour = parsed
        dates.setdefault(date, [])
        if hour not in dates[date]:
            dates[date].append(hour)
    for hours in dates.values():
        hours.sort()

    tree_paths = {item["path"] for item in tree_items}
    metadata_data_paths = {
        item["path"] for item in metadata_siblings if item["path"].startswith("data/")
    }
    complete_tree = terminal_tree_success and metadata_data_paths.issubset(tree_paths)
    complete_metadata_path_inventory = bool(metadata_siblings) and len(metadata_siblings) >= 1000
    complete_inventory = complete_tree or complete_metadata_path_inventory

    metadata_sha = metadata.get("sha") if isinstance(metadata, dict) else None
    metadata_last_modified = metadata.get("lastModified") if isinstance(metadata, dict) else None
    metadata_used_storage = metadata.get("usedStorage") if isinstance(metadata, dict) else None
    commit_ids: list[str] = []
    if isinstance(commits, list):
        for record in commits:
            if isinstance(record, dict):
                commit_id = record.get("id") or record.get("commitId") or record.get("oid")
                if isinstance(commit_id, str) and commit_id not in commit_ids:
                    commit_ids.append(commit_id)

    pre_2026_dates = sorted(date for date in dates if date < "2026-01-01")
    post_2025_dates = sorted(date for date in dates if date >= "2026-01-01")
    listed_bytes = sum(int(item.get("size") or item.get("lfs_size") or 0) for item in data_files)
    gate = {
        "minimum_60_distinct_pre_2026_dates": len(pre_2026_dates) >= 60,
        "latest_explicit_filename_date_not_after_2025_12_31": bool(dates) and max(dates) <= "2025-12-31",
        "immutable_revision_observed": bool(metadata_sha or commit_ids),
        "complete_repository_path_inventory": complete_inventory,
        "source_inventory_only": True,
        "strategy_pnl_computed": False,
    }
    inventory = {
        "claim_id": "CLM-20260726-1040-HL-WALLET-FLOW-001",
        "amendment_id": "002",
        "script_version": 2,
        "stage": "SOURCE_INVENTORY_ONLY",
        "repository": REPOSITORY,
        "source_probe_only": True,
        "strategy_pnl_computed": False,
        "parquet_or_lz4_rows_read": False,
        "event_json_read": False,
        "official_2026_evaluation_opened": False,
        "orders_submitted": False,
        "metadata_sha": metadata_sha,
        "metadata_last_modified": metadata_last_modified,
        "metadata_used_storage": metadata_used_storage,
        "commit_ids": commit_ids,
        "metadata_sibling_count": len(metadata_siblings),
        "tree_pages": page,
        "tree_item_count": len(tree_items),
        "complete_tree": complete_tree,
        "complete_metadata_path_inventory": complete_metadata_path_inventory,
        "inventory_basis": "complete_tree" if complete_tree else "dataset_metadata_siblings",
        "data_file_count": len(data_files),
        "listed_data_bytes_from_tree": listed_bytes,
        "date_count": len(dates),
        "pre_2026_date_count": len(pre_2026_dates),
        "first_explicit_filename_date": min(dates) if dates else None,
        "last_explicit_filename_date": max(dates) if dates else None,
        "pre_2026_dates": pre_2026_dates,
        "post_2025_dates": post_2025_dates,
        "hours_by_date": dict(sorted(dates.items())),
        "unknown_date_path_count": len(unknown_date_paths),
        "unknown_date_paths": unknown_date_paths,
        "files": data_files,
        "probes": [asdict(probe) for probe in probes],
        "promotion_gate": gate,
        "promotion_gate_passed": all(gate.values()),
        "promotion_status": (
            "READY_FOR_PRE_2026_DATE_SPECIFIC_PREREGISTRATION"
            if all(gate.values())
            else "SOURCE_COVERAGE_OR_INVENTORY_GATE_FAILED"
        ),
    }
    (output / "HF_SOURCE_INVENTORY.json").write_text(
        json.dumps(inventory, indent=2, sort_keys=True), encoding="utf-8"
    )
    (output / "HF_DATA_FILES.txt").write_text(
        "\n".join(item["path"] for item in data_files) + ("\n" if data_files else ""),
        encoding="utf-8",
    )
    (output / "HF_DATES.txt").write_text(
        "\n".join(f"{date}\t{','.join(map(str, dates[date]))}" for date in sorted(dates))
        + ("\n" if dates else ""),
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "metadata_sha": metadata_sha,
                "metadata_last_modified": metadata_last_modified,
                "metadata_used_storage": metadata_used_storage,
                "metadata_sibling_count": len(metadata_siblings),
                "tree_pages": page,
                "tree_item_count": len(tree_items),
                "complete_tree": complete_tree,
                "data_file_count": len(data_files),
                "pre_2026_date_count": len(pre_2026_dates),
                "first_explicit_filename_date": inventory["first_explicit_filename_date"],
                "last_explicit_filename_date": inventory["last_explicit_filename_date"],
                "promotion_gate": gate,
                "promotion_status": inventory["promotion_status"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
