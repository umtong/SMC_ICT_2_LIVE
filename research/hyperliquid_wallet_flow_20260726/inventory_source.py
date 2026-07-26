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

OWNER = "marvingozo"
SLUG = "hyperliquid-l1-order-flow-microstructure-10-perps"
BASE = "https://www.kaggle.com"
DATE_RE = re.compile(r"(?<!\d)(20\d{2}[-_/]?\d{2}[-_/]?\d{2})(?!\d)")


@dataclass(frozen=True)
class Probe:
    name: str
    method: str
    url: str
    status: int
    content_type: str | None
    bytes: int
    sha256: str
    json_valid: bool
    error: str | None
    response_file: str


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def request(name: str, method: str, url: str, output: Path, payload: dict[str, Any] | None = None) -> tuple[Probe, Any | None]:
    body = None if payload is None else canonical_json(payload)
    headers = {
        "Accept": "application/json",
        "User-Agent": "SMC-ICT-2-LIVE-causal-source-inventory/1.0",
    }
    if body is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    status = 0
    content_type: str | None = None
    raw = b""
    error: str | None = None
    try:
        with urllib.request.urlopen(req, timeout=90) as response:
            status = int(response.status)
            content_type = response.headers.get("Content-Type")
            raw = response.read()
    except urllib.error.HTTPError as exc:
        status = int(exc.code)
        content_type = exc.headers.get("Content-Type") if exc.headers else None
        raw = exc.read()
        error = f"HTTPError: {exc}"
    except Exception as exc:  # inventory records the exact access failure
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
    digest = hashlib.sha256(raw).hexdigest()
    return (
        Probe(
            name=name,
            method=method,
            url=url,
            status=status,
            content_type=content_type,
            bytes=len(raw),
            sha256=digest,
            json_valid=json_valid,
            error=error,
            response_file=response_file,
        ),
        parsed,
    )


def normalize_date(token: str) -> str:
    digits = token.replace("_", "-").replace("/", "-")
    if "-" not in digits and len(digits) == 8:
        digits = f"{digits[:4]}-{digits[4:6]}-{digits[6:]}"
    return digits


def collect_file_records(value: Any, path: str = "$") -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    if isinstance(value, list):
        for index, child in enumerate(value):
            records.extend(collect_file_records(child, f"{path}[{index}]"))
        return records
    if not isinstance(value, dict):
        return records

    name = None
    for key in ("name", "fileName", "filename", "path", "ref"):
        candidate = value.get(key)
        if isinstance(candidate, str) and candidate.strip():
            name = candidate.strip()
            break
    byte_value = None
    for key in ("totalBytes", "size", "bytes", "fileSize"):
        candidate = value.get(key)
        if isinstance(candidate, (int, float)):
            byte_value = int(candidate)
            break
    file_like = bool(name and ("." in Path(name).name or any(token in name.lower() for token in ("parquet", "csv", "json", "zip"))))
    if file_like:
        records.append(
            {
                "source_path": path,
                "name": name,
                "bytes": byte_value,
                "creation_date": value.get("creationDate") or value.get("creation_date"),
                "raw_keys": sorted(value.keys()),
            }
        )
    for key, child in value.items():
        records.extend(collect_file_records(child, f"{path}.{key}"))
    return records


def collect_metadata(value: Any) -> dict[str, Any]:
    wanted = {
        "id",
        "datasetId",
        "ref",
        "title",
        "subtitle",
        "ownerName",
        "ownerRef",
        "licenseName",
        "lastUpdated",
        "currentVersionNumber",
        "totalBytes",
        "downloadCount",
        "isPrivate",
        "datasetSlug",
        "ownerUser",
    }
    found: dict[str, list[Any]] = {}

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            for key, child in node.items():
                if key in wanted and child is not None:
                    found.setdefault(key, [])
                    if child not in found[key]:
                        found[key].append(child)
                walk(child)
        elif isinstance(node, list):
            for child in node:
                walk(child)

    walk(value)
    return found


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output
    output.mkdir(parents=True, exist_ok=True)

    encoded_slug = urllib.parse.quote(SLUG, safe="")
    get_endpoints = {
        "rest_view": f"{BASE}/api/v1/datasets/view/{OWNER}/{encoded_slug}",
        "rest_metadata": f"{BASE}/api/v1/datasets/metadata/{OWNER}/{encoded_slug}",
        "rest_file_list": f"{BASE}/api/v1/datasets/list/{OWNER}/{encoded_slug}?pageSize=1000",
        "rest_search": f"{BASE}/api/v1/datasets/list?search={encoded_slug}&pageSize=100",
    }
    rpc_endpoint = {
        "rpc_get_dataset": "datasets.DatasetApiService/GetDataset",
        "rpc_get_metadata": "datasets.DatasetApiService/GetDatasetMetadata",
        "rpc_list_files": "datasets.DatasetApiService/ListDatasetFiles",
    }
    payload = {"ownerSlug": OWNER, "datasetSlug": SLUG, "pageSize": 1000}

    probes: list[Probe] = []
    parsed_responses: dict[str, Any] = {}
    for name, url in get_endpoints.items():
        probe, parsed = request(name, "GET", url, output)
        probes.append(probe)
        if parsed is not None:
            parsed_responses[name] = parsed
    for name, operation in rpc_endpoint.items():
        url = f"{BASE}/kaggle/v1/{operation}"
        probe, parsed = request(name, "POST", url, output, payload)
        probes.append(probe)
        if parsed is not None:
            parsed_responses[name] = parsed

    all_records: list[dict[str, Any]] = []
    metadata: dict[str, list[Any]] = {}
    for probe_name, parsed in parsed_responses.items():
        for record in collect_file_records(parsed):
            record["probe"] = probe_name
            all_records.append(record)
        for key, values in collect_metadata(parsed).items():
            metadata.setdefault(key, [])
            for value in values:
                if value not in metadata[key]:
                    metadata[key].append(value)

    deduplicated: dict[str, dict[str, Any]] = {}
    for record in all_records:
        name = record["name"]
        current = deduplicated.get(name)
        if current is None or (current.get("bytes") is None and record.get("bytes") is not None):
            deduplicated[name] = record
    files = [deduplicated[name] for name in sorted(deduplicated)]

    dates: set[str] = set()
    stream_counts: dict[str, int] = {}
    for record in files:
        name = record["name"]
        for match in DATE_RE.finditer(name):
            dates.add(normalize_date(match.group(1)))
        lower = name.lower()
        stream = "other"
        for candidate in ("orders", "fills", "book", "funding", "snapshot", "candle"):
            if candidate in lower:
                stream = candidate
                break
        stream_counts[stream] = stream_counts.get(stream, 0) + 1

    usable_probes = [p.name for p in probes if p.status == 200 and p.json_valid]
    inventory = {
        "claim_id": "CLM-20260726-1040-HL-WALLET-FLOW-001",
        "stage": "SOURCE_INVENTORY_ONLY",
        "dataset_ref": f"{OWNER}/{SLUG}",
        "source_probe_only": True,
        "strategy_pnl_computed": False,
        "wallet_performance_read": False,
        "forward_returns_read": False,
        "official_2024_2026_opened": False,
        "orders_submitted": False,
        "usable_json_probes": usable_probes,
        "file_inventory_observed": bool(files),
        "file_count": len(files),
        "files": files,
        "dates_in_filenames": sorted(dates),
        "stream_file_counts": dict(sorted(stream_counts.items())),
        "metadata_values": metadata,
        "probes": [asdict(probe) for probe in probes],
        "promotion_status": "INVENTORY_READY_FOR_DATE_SPECIFIC_PREREGISTRATION" if files else "SOURCE_ACCESS_OR_INVENTORY_INSUFFICIENT",
    }
    (output / "SOURCE_INVENTORY.json").write_text(json.dumps(inventory, indent=2, sort_keys=True), encoding="utf-8")
    (output / "FILE_LIST.txt").write_text("\n".join(record["name"] for record in files) + ("\n" if files else ""), encoding="utf-8")
    print(json.dumps({key: inventory[key] for key in ("usable_json_probes", "file_count", "dates_in_filenames", "stream_file_counts", "promotion_status")}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
