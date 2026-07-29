#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import io
import json
import re
import zipfile
from pathlib import Path
from typing import Any

import pandas as pd
import requests

RECORD_ID = "17898640"
DOI = "10.5281/zenodo.17898640"
TITLE = "A Cross-Chain Event-Driven Data Infrastructure for Aave Protocol Analytics and Applications"
ZENODO = "https://zenodo.org"
QUERIES = [
    ("record_id", f"{ZENODO}/api/records/{RECORD_ID}"),
    ("doi", f"{ZENODO}/api/records?q=doi:%22{DOI}%22&size=10"),
    ("exact_title", f"{ZENODO}/api/records?q=metadata.title:%22{TITLE.replace(' ', '%20')}%22&size=10"),
    ("title_words", f"{ZENODO}/api/records?q=Aave%20V3%20LiquidationCall%20cross-chain%20event&size=25"),
    ("doi_resolver", f"https://doi.org/{DOI}"),
]


def sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def request(session: requests.Session, name: str, url: str) -> dict[str, Any]:
    try:
        response = session.get(url, timeout=90, allow_redirects=True)
        return {
            "name": name,
            "request_url": url,
            "final_url": response.url,
            "status_code": response.status_code,
            "headers": {k.lower(): v for k, v in response.headers.items() if k.lower() in {"content-type", "content-length", "location", "etag", "last-modified"}},
            "bytes": len(response.content),
            "sha256": sha256(response.content),
            "body": response.content,
        }
    except Exception as exc:
        return {"name": name, "request_url": url, "status_code": None, "error": f"{type(exc).__name__}: {exc}", "body": b""}


def json_body(result: dict[str, Any]) -> Any | None:
    if result.get("status_code") != 200:
        return None
    try:
        return json.loads(result["body"])
    except Exception:
        return None


def candidate_records(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for result in results:
        data = json_body(result)
        if not isinstance(data, dict):
            continue
        records: list[dict[str, Any]] = []
        if "id" in data and ("metadata" in data or "files" in data):
            records.append(data)
        hits = data.get("hits", {}).get("hits") if isinstance(data.get("hits"), dict) else None
        if isinstance(hits, list):
            records.extend(x for x in hits if isinstance(x, dict))
        for record in records:
            rid = str(record.get("id") or record.get("recid") or record.get("uuid") or "")
            metadata = record.get("metadata") if isinstance(record.get("metadata"), dict) else {}
            title = str(metadata.get("title") or record.get("title") or "")
            doi = str(metadata.get("doi") or record.get("doi") or "")
            fingerprint = rid or sha256(json.dumps(record, sort_keys=True, default=str).encode())
            if fingerprint in seen:
                continue
            text = f"{title} {doi}".lower()
            if "aave" in text or DOI.lower() in text or rid == RECORD_ID:
                out.append(record)
                seen.add(fingerprint)
    return out


def normalize_files(record: dict[str, Any]) -> list[dict[str, Any]]:
    files = record.get("files")
    if isinstance(files, dict) and isinstance(files.get("entries"), dict):
        values = list(files["entries"].values())
    elif isinstance(files, list):
        values = files
    else:
        values = []
    out = []
    for item in values:
        if not isinstance(item, dict):
            continue
        key = str(item.get("key") or item.get("filename") or item.get("name") or "")
        links = item.get("links") if isinstance(item.get("links"), dict) else {}
        url = links.get("content") or links.get("self") or item.get("download") or item.get("url")
        checksum = item.get("checksum")
        size = item.get("size") or item.get("filesize")
        out.append({"key": key, "url": url, "checksum": checksum, "size": size, "raw": item})
    return out


def matching_file(files: list[dict[str, Any]]) -> dict[str, Any] | None:
    ranked = []
    for item in files:
        key = item["key"].lower()
        score = 0
        if "ethereum" in key:
            score += 4
        if "liquidationcall" in key or "liquidation_call" in key:
            score += 5
        elif "liquidation" in key:
            score += 3
        if key.endswith((".csv", ".csv.gz", ".zip", ".parquet")):
            score += 1
        if score:
            ranked.append((score, item))
    ranked.sort(key=lambda x: (-x[0], x[1]["key"]))
    return ranked[0][1] if ranked and ranked[0][0] >= 8 else None


def verify_checksum(raw: bytes, checksum: Any) -> tuple[bool | None, str | None, str | None]:
    if not checksum:
        return None, None, None
    text = str(checksum)
    if ":" in text:
        algorithm, expected = text.split(":", 1)
    else:
        algorithm, expected = ("md5" if len(text) == 32 else "sha256"), text
    algorithm = algorithm.lower()
    if algorithm not in hashlib.algorithms_available:
        return None, algorithm, expected
    actual = hashlib.new(algorithm, raw).hexdigest()
    return actual.lower() == expected.lower(), algorithm, actual


def read_table(raw: bytes, key: str) -> pd.DataFrame:
    lower = key.lower()
    if lower.endswith(".zip"):
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            members = [n for n in archive.namelist() if not n.endswith("/")]
            csv_members = [n for n in members if n.lower().endswith(".csv")]
            if len(csv_members) != 1:
                raise ValueError(f"expected one CSV in {key}, found {members}")
            return pd.read_csv(io.BytesIO(archive.read(csv_members[0])))
    if lower.endswith(".parquet"):
        return pd.read_parquet(io.BytesIO(raw))
    if lower.endswith(".csv.gz"):
        return pd.read_csv(io.BytesIO(raw), compression="gzip")
    return pd.read_csv(io.BytesIO(raw))


def timestamp_column(frame: pd.DataFrame) -> str | None:
    priorities = ["timestamp", "block_timestamp", "block_time", "blocktime", "time", "date", "datetime"]
    lowered = {str(c).lower(): str(c) for c in frame.columns}
    for name in priorities:
        if name in lowered:
            return lowered[name]
    for c in frame.columns:
        low = str(c).lower()
        if "timestamp" in low or "block_time" in low:
            return str(c)
    return None


def parse_timestamp(series: pd.Series) -> pd.Series:
    numeric = pd.to_numeric(series, errors="coerce")
    if numeric.notna().mean() > 0.9:
        median = numeric.dropna().abs().median()
        unit = "ms" if median > 10**11 else "s"
        return pd.to_datetime(numeric, unit=unit, utc=True, errors="coerce")
    return pd.to_datetime(series, utc=True, errors="coerce")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    raw_dir = args.output / "raw_responses"
    raw_dir.mkdir(exist_ok=True)

    session = requests.Session()
    session.headers.update({"User-Agent": "SMC-ICT-Aave-Zenodo-source-gate/1.0"})
    results = [request(session, name, url) for name, url in QUERIES]
    response_manifest = []
    for result in results:
        body = result.pop("body")
        path = raw_dir / f"{result['name']}.bin"
        path.write_bytes(body)
        result["path"] = str(path.relative_to(args.output))
        response_manifest.append(result)

    records = candidate_records([{**r, "body": (args.output / r["path"]).read_bytes()} for r in response_manifest])
    selected = None
    selected_files: list[dict[str, Any]] = []
    selected_match = None
    for record in records:
        files = normalize_files(record)
        match = matching_file(files)
        if match:
            selected, selected_files, selected_match = record, files, match
            break

    decision: dict[str, Any] = {
        "schema_version": 1,
        "claim_id": "CLM-20260730-AAVE-ZENODO-LIQUIDATION-001",
        "result_id": "RES-20260730-AAVE-ZENODO-LIQUIDATION-SOURCE-001",
        "paper": {"title": TITLE, "arxiv": "2512.11363", "claimed_doi": DOI},
        "responses": response_manifest,
        "candidate_record_count": len(records),
        "source_status": "FAIL",
        "market_outcomes_opened": False,
        "orders_submitted": False,
    }

    if selected is None or selected_match is None:
        decision["reason"] = "No public Zenodo record exposed a retrievable Ethereum Aave V3 LiquidationCall file under the claimed record ID, DOI, or title searches."
    else:
        metadata = selected.get("metadata") if isinstance(selected.get("metadata"), dict) else {}
        decision["selected_record"] = {
            "id": selected.get("id"),
            "title": metadata.get("title"),
            "doi": metadata.get("doi") or selected.get("doi"),
            "file_count": len(selected_files),
            "matching_file": {k: selected_match.get(k) for k in ("key", "url", "checksum", "size")},
        }
        if not selected_match.get("url"):
            decision["reason"] = "Matching file metadata lacks a public content URL."
        else:
            file_response = request(session, "ethereum_liquidation_file", str(selected_match["url"]))
            raw = file_response.pop("body")
            file_path = args.output / selected_match["key"]
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_bytes(raw)
            checksum_ok, algorithm, actual = verify_checksum(raw, selected_match.get("checksum"))
            size_ok = None if selected_match.get("size") is None else len(raw) == int(selected_match["size"])
            decision["file_download"] = {
                **file_response,
                "path": str(file_path.relative_to(args.output)),
                "sha256": sha256(raw),
                "checksum_algorithm": algorithm,
                "checksum_actual": actual,
                "checksum_ok": checksum_ok,
                "size_ok": size_ok,
            }
            if file_response.get("status_code") != 200 or not raw:
                decision["reason"] = "Matching file could not be downloaded publicly."
            elif checksum_ok is False or size_ok is False:
                decision["reason"] = "Downloaded file failed Zenodo checksum or size verification."
            else:
                try:
                    frame = read_table(raw, selected_match["key"])
                    tcol = timestamp_column(frame)
                    if tcol is None:
                        raise ValueError("no recognizable timestamp column")
                    ts = parse_timestamp(frame[tcol])
                    pre2024 = ts < pd.Timestamp("2024-01-01T00:00:00Z")
                    year_counts = ts[pre2024].dt.year.value_counts().sort_index()
                    decision["parsed"] = {
                        "rows": len(frame),
                        "columns": [str(c) for c in frame.columns],
                        "timestamp_column": tcol,
                        "valid_timestamps": int(ts.notna().sum()),
                        "pre2024_count": int(pre2024.fillna(False).sum()),
                        "pre2024_year_counts": {str(int(k)): int(v) for k, v in year_counts.items()},
                        "minimum_timestamp": ts.min().isoformat() if ts.notna().any() else None,
                        "maximum_timestamp": ts.max().isoformat() if ts.notna().any() else None,
                    }
                    if int(pre2024.fillna(False).sum()) >= 100 and int((ts.dt.year == 2023).fillna(False).sum()) > 0:
                        decision["source_status"] = "PASS"
                        decision["reason"] = "Public hash-verified Ethereum LiquidationCall data has sufficient pre-2024 coverage for a separate causal economic contract."
                    else:
                        decision["reason"] = "The matching file is valid but has fewer than 100 pre-2024 Ethereum liquidation events or no 2023 coverage."
                except Exception as exc:
                    decision["reason"] = f"Matching file could not be parsed deterministically: {type(exc).__name__}: {exc}"

    (args.output / "SOURCE_DECISION.json").write_text(json.dumps(decision, indent=2, default=str), encoding="utf-8")
    print(json.dumps({"source_status": decision["source_status"], "reason": decision.get("reason"), "candidate_record_count": len(records)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
