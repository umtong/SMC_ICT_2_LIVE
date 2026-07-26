from __future__ import annotations

import argparse
import hashlib
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

REPOSITORY = "gionuibk/hyperliquid-node-fills-by-block"
BASE = "https://huggingface.co"
DATE_HOUR_RE = re.compile(r"(?<!\d)(20\d{6})_(\d{1,2})(?!\d)")
PARQUET_OR_LZ4_RE = re.compile(r"\.(?:parquet|lz4)$", re.IGNORECASE)


@dataclass(frozen=True)
class Probe:
    name: str
    url: str
    status: int
    content_type: str | None
    bytes: int
    sha256: str
    json_valid: bool
    error: str | None
    response_file: str
    next_url: str | None


def sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def parse_next_link(value: str | None) -> str | None:
    if not value:
        return None
    for part in value.split(","):
        section = part.strip()
        if 'rel="next"' not in section:
            continue
        match = re.match(r"<([^>]+)>", section)
        if match:
            return match.group(1)
    return None


def fetch_json(name: str, url: str, output: Path) -> tuple[Probe, Any | None]:
    req = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "SMC-ICT-2-LIVE-causal-source-inventory/1.0",
        },
        method="GET",
    )
    status = 0
    content_type: str | None = None
    raw = b""
    error: str | None = None
    next_url: str | None = None
    try:
        with urllib.request.urlopen(req, timeout=120) as response:
            status = int(response.status)
            content_type = response.headers.get("Content-Type")
            next_url = parse_next_link(response.headers.get("Link"))
            raw = response.read()
    except urllib.error.HTTPError as exc:
        status = int(exc.code)
        content_type = exc.headers.get("Content-Type") if exc.headers else None
        next_url = parse_next_link(exc.headers.get("Link") if exc.headers else None)
        raw = exc.read()
        error = f"HTTPError: {exc}"
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"

    parsed: Any | None = None
    json_valid = False
    if raw:
        try:
            parsed = json.loads(raw)
            json_valid = True
        except Exception:
            parsed = None

    suffix = ".json" if json_valid else ".bin"
    response_file = f"responses/{name}{suffix}"
    target = output / response_file
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(raw)
    return (
        Probe(
            name=name,
            url=url,
            status=status,
            content_type=content_type,
            bytes=len(raw),
            sha256=sha256_bytes(raw),
            json_valid=json_valid,
            error=error,
            response_file=response_file,
            next_url=next_url,
        ),
        parsed,
    )


def normalize_tree_item(item: Any) -> dict[str, Any] | None:
    if not isinstance(item, dict):
        return None
    path = item.get("path")
    if not isinstance(path, str) or not path:
        return None
    size = item.get("size")
    if not isinstance(size, int):
        size = None
    return {
        "path": path,
        "type": item.get("type"),
        "size": size,
        "oid": item.get("oid"),
        "lfs_oid": (item.get("lfs") or {}).get("oid") if isinstance(item.get("lfs"), dict) else None,
        "lfs_size": (item.get("lfs") or {}).get("size") if isinstance(item.get("lfs"), dict) else None,
        "xet_hash": (item.get("xetHash") or item.get("xet_hash")),
        "last_commit": item.get("lastCommit") or item.get("last_commit"),
    }


def extract_date_hour(path: str) -> tuple[str, int] | None:
    match = DATE_HOUR_RE.search(path)
    if not match:
        return None
    raw_date, raw_hour = match.groups()
    hour = int(raw_hour)
    if hour < 0 or hour > 23:
        return None
    date = f"{raw_date[:4]}-{raw_date[4:6]}-{raw_date[6:8]}"
    return date, hour


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output
    output.mkdir(parents=True, exist_ok=True)

    probes: list[Probe] = []
    metadata_url = f"{BASE}/api/datasets/{REPOSITORY}"
    metadata_probe, metadata = fetch_json("dataset_metadata", metadata_url, output)
    probes.append(metadata_probe)

    commits_url = f"{BASE}/api/datasets/{REPOSITORY}/commits/main?limit=100"
    commits_probe, commits = fetch_json("commits_main", commits_url, output)
    probes.append(commits_probe)

    quoted_revision = urllib.parse.quote("main", safe="")
    first_tree_url = (
        f"{BASE}/api/datasets/{REPOSITORY}/tree/{quoted_revision}/data"
        "?recursive=false&expand=true&limit=1000"
    )
    tree_items: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    next_url: str | None = first_tree_url
    page = 0
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
        next_url = probe.next_url
        page += 1
        if page > 100:
            raise RuntimeError("Unexpectedly large tree pagination")

    by_path: dict[str, dict[str, Any]] = {}
    for item in tree_items:
        by_path[item["path"]] = item
    files = [by_path[path] for path in sorted(by_path)]
    data_files = [item for item in files if item.get("type") == "file" and PARQUET_OR_LZ4_RE.search(item["path"])]

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

    dated_files = [item for item in data_files if extract_date_hour(item["path"]) is not None]
    total_bytes = sum(int(item.get("size") or item.get("lfs_size") or 0) for item in data_files)
    pre_2026_dates = sorted(date for date in dates if date < "2026-01-01")
    post_2025_dates = sorted(date for date in dates if date >= "2026-01-01")

    metadata_sha = metadata.get("sha") if isinstance(metadata, dict) else None
    metadata_last_modified = metadata.get("lastModified") if isinstance(metadata, dict) else None
    metadata_private = metadata.get("private") if isinstance(metadata, dict) else None
    metadata_disabled = metadata.get("disabled") if isinstance(metadata, dict) else None

    commit_ids: list[str] = []
    if isinstance(commits, list):
        for record in commits:
            if isinstance(record, dict):
                commit_id = record.get("id") or record.get("commitId") or record.get("oid")
                if isinstance(commit_id, str) and commit_id not in commit_ids:
                    commit_ids.append(commit_id)

    complete_tree = bool(
        tree_items
        and probes[-1].status == 200
        and probes[-1].json_valid
        and probes[-1].next_url is None
    )
    gate = {
        "minimum_60_distinct_pre_2026_dates": len(pre_2026_dates) >= 60,
        "latest_filename_date_not_after_2025_12_31": bool(dates) and max(dates) <= "2025-12-31",
        "immutable_revision_observed": bool(metadata_sha or commit_ids),
        "complete_paginated_tree_inventory": complete_tree,
        "source_inventory_only": True,
        "strategy_pnl_computed": False,
    }
    inventory = {
        "claim_id": "CLM-20260726-1040-HL-WALLET-FLOW-001",
        "amendment_id": "002",
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
        "metadata_private": metadata_private,
        "metadata_disabled": metadata_disabled,
        "commit_ids": commit_ids,
        "tree_pages": page,
        "tree_item_count": len(files),
        "data_file_count": len(data_files),
        "dated_data_file_count": len(dated_files),
        "total_listed_data_bytes": total_bytes,
        "date_count": len(dates),
        "pre_2026_date_count": len(pre_2026_dates),
        "first_filename_date": min(dates) if dates else None,
        "last_filename_date": max(dates) if dates else None,
        "pre_2026_dates": pre_2026_dates,
        "post_2025_dates": post_2025_dates,
        "hours_by_date": dict(sorted(dates.items())),
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
                "tree_pages": page,
                "data_file_count": len(data_files),
                "total_listed_data_bytes": total_bytes,
                "pre_2026_date_count": len(pre_2026_dates),
                "first_filename_date": inventory["first_filename_date"],
                "last_filename_date": inventory["last_filename_date"],
                "promotion_gate": gate,
                "promotion_status": inventory["promotion_status"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
