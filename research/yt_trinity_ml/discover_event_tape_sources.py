#!/usr/bin/env python3
"""Discover reusable local and public Bybit event-tape sources.

The scan is deliberately restricted to strategy-agnostic market-data code and
manifests.  It never opens prior strategy results, PnL, rankings or model output.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import io
import json
import os
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urljoin

import requests


SAFE_PATH_PATTERNS = (
    re.compile(r"(^|/)(scripts?|src|data|datasets?|manifests?|contracts?|config)(/|$)", re.I),
    re.compile(r"market[_-]?data|canonical[_-]?bybit|event[_-]?tape|order[_-]?book|trades?|quotes?|tick|subsecond|1s", re.I),
)
FORBIDDEN_PATH_PATTERN = re.compile(r"result|ranking|pnl|backtest|strategy|research/.+/(run|report)|registry", re.I)
TEXT_SUFFIXES = {".json", ".jsonl", ".yaml", ".yml", ".toml", ".md", ".txt", ".py"}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def git(*args: str, cwd: Path) -> str:
    completed = subprocess.run(["git", *args], cwd=cwd, text=True, capture_output=True, check=True)
    return completed.stdout


def safe_candidate(path: str) -> bool:
    return (
        any(pattern.search(path) for pattern in SAFE_PATH_PATTERNS)
        and not FORBIDDEN_PATH_PATTERN.search(path)
    )


def local_inventory(repo: Path, ref: str) -> list[dict[str, Any]]:
    names = [line.strip() for line in git("ls-tree", "-r", "--name-only", ref, cwd=repo).splitlines() if line.strip()]
    rows: list[dict[str, Any]] = []
    for path in names:
        if not safe_candidate(path):
            continue
        try:
            size_text = git("cat-file", "-s", f"{ref}:{path}", cwd=repo).strip()
            size = int(size_text)
        except Exception:
            continue
        row: dict[str, Any] = {"path": path, "size": size, "ref": ref}
        suffix = Path(path).suffix.lower()
        if suffix in TEXT_SUFFIXES and size <= 1_000_000:
            try:
                raw = subprocess.run(
                    ["git", "show", f"{ref}:{path}"],
                    cwd=repo,
                    capture_output=True,
                    check=True,
                ).stdout
                text = raw.decode("utf-8", "replace")
                keywords = sorted({
                    match.group(0).lower()
                    for match in re.finditer(
                        r"bybit|trade|orderbook|order_book|bid|ask|quote|depth|1s|millisecond|microsecond|event[_ -]?tape|available_at_ms|public\.bybit",
                        text,
                        flags=re.I,
                    )
                })
                row["text_sha256"] = hashlib.sha256(raw).hexdigest()
                row["keywords"] = keywords
                row["relevant_line_samples"] = [
                    line[:500]
                    for line in text.splitlines()
                    if re.search(r"bybit|order.?book|event.?tape|public\.bybit|trade.?bar|available_at_ms|millisecond|microsecond|(^|[^0-9])1s([^0-9]|$)", line, re.I)
                ][:20]
            except Exception as exc:
                row["read_error"] = f"{type(exc).__name__}: {exc}"
        rows.append(row)
    rows.sort(key=lambda row: row["path"])
    return rows


def request_sample(url: str, maximum_bytes: int = 250_000) -> dict[str, Any]:
    try:
        response = requests.get(
            url,
            headers={"User-Agent": "SMC-ICT-2-LIVE/1.0", "Range": f"bytes=0-{maximum_bytes - 1}"},
            timeout=35,
            stream=True,
            allow_redirects=True,
        )
        raw = b""
        for chunk in response.iter_content(65_536):
            raw += chunk
            if len(raw) >= maximum_bytes:
                raw = raw[:maximum_bytes]
                break
        result = {
            "url": url,
            "final_url": response.url,
            "status_code": response.status_code,
            "content_type": response.headers.get("content-type"),
            "content_length": response.headers.get("content-length"),
            "accept_ranges": response.headers.get("accept-ranges"),
            "sample_bytes": len(raw),
            "sample_sha256": hashlib.sha256(raw).hexdigest() if raw else None,
        }
        content = raw
        if url.endswith(".gz") and raw[:2] == b"\x1f\x8b":
            try:
                content = gzip.GzipFile(fileobj=io.BytesIO(raw)).read(500_000)
                result["gzip_sample_decompressed"] = True
            except Exception as exc:
                result["gzip_sample_error"] = f"{type(exc).__name__}: {exc}"
        text = content.decode("utf-8", "replace")
        result["text_prefix"] = text[:2000]
        first_line = next((line for line in text.splitlines() if line.strip()), "")
        if first_line:
            try:
                result["csv_header"] = next(csv.reader([first_line]))
            except Exception:
                pass
        return result
    except Exception as exc:
        return {"url": url, "exception": f"{type(exc).__name__}: {exc}"}


def directory_links(url: str) -> list[str]:
    try:
        response = requests.get(url, headers={"User-Agent": "SMC-ICT-2-LIVE/1.0"}, timeout=30)
        if response.status_code != 200:
            return []
        links = re.findall(r'href=["\']([^"\']+)["\']', response.text, flags=re.I)
        return sorted({urljoin(response.url, link) for link in links})[:1000]
    except Exception:
        return []


def public_probes() -> dict[str, Any]:
    date = "2024-01-01"
    symbol = "BTCUSDT"
    candidates = [
        f"https://public.bybit.com/trading/{symbol}/{symbol}{date}.csv.gz",
        f"https://public.bybit.com/trading/{symbol}/{symbol}_{date}.csv.gz",
        f"https://public.bybit.com/orderbook/{symbol}/{symbol}{date}.csv.gz",
        f"https://public.bybit.com/orderBookL2/{symbol}/{symbol}{date}.csv.gz",
        f"https://public.bybit.com/order_book/{symbol}/{symbol}{date}.csv.gz",
        f"https://public.bybit.com/quote/{symbol}/{symbol}{date}.csv.gz",
        f"https://public.bybit.com/quotes/{symbol}/{symbol}{date}.csv.gz",
        f"https://public.bybit.com/tick/{symbol}/{symbol}{date}.csv.gz",
        f"https://public.bybit.com/ticks/{symbol}/{symbol}{date}.csv.gz",
    ]
    directories = [
        "https://public.bybit.com/",
        "https://public.bybit.com/trading/",
        f"https://public.bybit.com/trading/{symbol}/",
        "https://public.bybit.com/orderbook/",
        "https://public.bybit.com/orderBookL2/",
    ]
    links = {url: directory_links(url) for url in directories}
    discovered = sorted({
        link for values in links.values() for link in values
        if any(token in link.lower() for token in ("trade", "book", "quote", "depth", "tick"))
    })
    for link in discovered:
        if link.endswith(".gz") and date in link and link not in candidates:
            candidates.append(link)
    return {
        "directory_links": links,
        "candidate_samples": [request_sample(url) for url in candidates],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--ref", default="origin/main")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    inventory = local_inventory(args.repo, args.ref)
    public = public_probes()
    usable_public = [
        row for row in public["candidate_samples"]
        if row.get("status_code") in {200, 206} and row.get("sample_bytes", 0) > 100
    ]
    likely_event_tape = [
        row for row in inventory
        if any(token in " ".join(row.get("keywords", [])) for token in ("orderbook", "order_book", "bid", "ask", "microsecond", "millisecond", "event_tape"))
    ]
    payload = {
        "schema_version": 1,
        "claim_id": "CLM-20260727-0346-YT-TRINITY-ML-001",
        "built_at_utc": utc_now(),
        "source_ref": args.ref,
        "source_ref_sha": git("rev-parse", args.ref, cwd=args.repo).strip(),
        "strategy_agnostic_local_candidate_count": len(inventory),
        "likely_local_event_tape_count": len(likely_event_tape),
        "likely_local_event_tape": likely_event_tape,
        "local_inventory": inventory,
        "public_archive": public,
        "usable_public_samples": usable_public,
        "decision": (
            "LOCAL_OR_PUBLIC_EVENT_TAPE_SOURCE_FOUND"
            if likely_event_tape or usable_public
            else "NO_EVENT_TAPE_SOURCE_FOUND"
        ),
        "prior_strategy_results_inspected": False,
    }
    payload["payload_sha256_before_field"] = hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "decision": payload["decision"],
        "local_candidates": len(inventory),
        "likely_event_tape": len(likely_event_tape),
        "usable_public": len(usable_public),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
