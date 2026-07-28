#!/usr/bin/env python3
"""Build one immutable, strategy-agnostic Bybit USDT-linear market-data shard."""
from __future__ import annotations

import argparse
import json
import os
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

try:
    from .bybit_client import BybitPublicClient, PageAudit, SourceError
    from .bybit_fetch import fetch_cursor_series, fetch_funding, fetch_kline_stream
    from .canonical_spec import (
        MS_MINUTE, SEGMENTS, SYMBOLS, TRADE_BAR_RULES, canonicalize_grid,
        derive_trade_bars, sha256_file, utc_ms, write_parquet,
    )
except ImportError:  # direct script execution
    from bybit_client import BybitPublicClient, PageAudit, SourceError
    from bybit_fetch import fetch_cursor_series, fetch_funding, fetch_kline_stream
    from canonical_spec import (
        MS_MINUTE, SEGMENTS, SYMBOLS, TRADE_BAR_RULES, canonicalize_grid,
        derive_trade_bars, sha256_file, utc_ms, write_parquet,
    )


def code_identity() -> dict[str, str | None]:
    repo = Path(__file__).resolve().parents[2]
    targets = {
        "builder_sha256": repo / "scripts/market_data/build_canonical_bybit.py",
        "client_sha256": repo / "scripts/market_data/bybit_client.py",
        "fetch_sha256": repo / "scripts/market_data/bybit_fetch.py",
        "spec_sha256": repo / "scripts/market_data/canonical_spec.py",
        "loader_sha256": repo / "scripts/market_data/load_canonical_bybit.py",
        "verifier_sha256": repo / "scripts/market_data/verify_canonical_bybit.py",
        "contract_sha256": repo / "data/contracts/canonical_bybit_usdt_linear_v1.json",
    }
    return {name: sha256_file(path) if path.is_file() else None for name, path in targets.items()}


def build(args: argparse.Namespace) -> Path:
    if args.symbol not in SYMBOLS:
        raise ValueError(f"unsupported symbol {args.symbol}; allowed={SYMBOLS}")
    if args.segment not in SEGMENTS:
        raise ValueError(f"unsupported segment {args.segment}; allowed={sorted(SEGMENTS)}")
    start_iso, end_iso, logical_segment = SEGMENTS[args.segment]
    start_ms, end_ms = utc_ms(start_iso), utc_ms(end_iso)
    out = Path(args.out).resolve() / args.segment / args.symbol
    out.mkdir(parents=True, exist_ok=True)

    client = BybitPublicClient(
        base_url=args.base_url,
        timeout_s=args.timeout,
        min_request_interval_s=args.min_request_interval,
        max_attempts=args.max_attempts,
    )
    audits: list[PageAudit] = []
    streams: dict[str, pd.DataFrame] = {}
    coverage: dict[str, Any] = {}

    for stream, path in (
        ("trade_price_1m", "/v5/market/kline"),
        ("mark_price_1m", "/v5/market/mark-price-kline"),
        ("index_price_1m", "/v5/market/index-price-kline"),
        ("premium_index_1m", "/v5/market/premium-index-price-kline"),
    ):
        raw, page_audits = fetch_kline_stream(
            client, symbol=args.symbol, stream=stream, path=path,
            start_ms=start_ms, end_exclusive_ms=end_ms,
        )
        audits.extend(page_audits)
        grid, stats = canonicalize_grid(
            raw, timestamp_col="start_time_ms", start_ms=start_ms,
            end_exclusive_ms=end_ms, step_ms=MS_MINUTE,
            available_delay_ms=MS_MINUTE,
        )
        streams[stream] = grid
        coverage[stream] = stats

    funding, page_audits = fetch_funding(
        client, symbol=args.symbol, start_ms=start_ms, end_exclusive_ms=end_ms
    )
    audits.extend(page_audits)
    funding["available_at_ms"] = (
        funding["timestamp_ms"] if "timestamp_ms" in funding else pd.Series(dtype="int64")
    )
    streams["funding_events"] = funding
    coverage["funding_events"] = {"rows": int(len(funding))}

    oi, page_audits = fetch_cursor_series(
        client, symbol=args.symbol, stream="open_interest_5m",
        path="/v5/market/open-interest", interval_param=("intervalTime", "5min"),
        start_ms=start_ms, end_exclusive_ms=end_ms,
    )
    audits.extend(page_audits)
    oi_grid, oi_stats = canonicalize_grid(
        oi, timestamp_col="timestamp_ms", start_ms=start_ms,
        end_exclusive_ms=end_ms, step_ms=5 * MS_MINUTE,
        available_delay_ms=5 * MS_MINUTE,
    )
    streams["open_interest_5m"] = oi_grid
    coverage["open_interest_5m"] = oi_stats

    ratio, page_audits = fetch_cursor_series(
        client, symbol=args.symbol, stream="account_ratio_5m",
        path="/v5/market/account-ratio", interval_param=("period", "5min"),
        start_ms=start_ms, end_exclusive_ms=end_ms,
    )
    audits.extend(page_audits)
    ratio_grid, ratio_stats = canonicalize_grid(
        ratio, timestamp_col="timestamp_ms", start_ms=start_ms,
        end_exclusive_ms=end_ms, step_ms=5 * MS_MINUTE,
        available_delay_ms=5 * MS_MINUTE,
    )
    streams["account_ratio_5m"] = ratio_grid
    coverage["account_ratio_5m"] = ratio_stats

    market_stats = coverage["trade_price_1m"]
    market_coverage = float(market_stats["coverage_after_first_observed"])
    allow_empty_prelaunch = logical_segment == "PRE_2024" and market_stats["observed_rows"] == 0
    if not allow_empty_prelaunch and market_coverage < args.min_market_coverage:
        raise SourceError(
            f"trade_price_1m coverage after first observation {market_coverage:.6f} "
            f"below {args.min_market_coverage:.6f}"
        )

    files: list[dict[str, Any]] = []
    for stream, frame in streams.items():
        path = out / "streams" / f"{stream}.parquet"
        write_parquet(frame, path)
        files.append({
            "kind": "stream", "name": stream, "path": str(path.relative_to(out)),
            "rows": int(len(frame)), "bytes": path.stat().st_size, "sha256": sha256_file(path),
        })

    base = streams["trade_price_1m"]
    for bar_name, rule in TRADE_BAR_RULES.items():
        frame = base if bar_name == "1m" else derive_trade_bars(base, rule)
        path = out / "trade_bars" / f"{bar_name}.parquet"
        write_parquet(frame, path)
        files.append({
            "kind": "trade_bar", "name": bar_name, "path": str(path.relative_to(out)),
            "rows": int(len(frame)), "bytes": path.stat().st_size, "sha256": sha256_file(path),
        })

    pages_path = out / "SOURCE_PAGES.jsonl"
    pages_path.write_text(
        "".join(json.dumps(asdict(audit), sort_keys=True) + "\n" for audit in audits),
        encoding="utf-8",
    )
    files.append({
        "kind": "source_audit", "name": "source_pages", "path": pages_path.name,
        "rows": len(audits), "bytes": pages_path.stat().st_size,
        "sha256": sha256_file(pages_path),
    })

    manifest: dict[str, Any] = {
        "schema_version": 1,
        "dataset_id": f"DS-BYBIT-LINEAR-{args.symbol}-{args.segment}-CANONICAL-V1",
        "dataset_family_id": "DSF-BYBIT-LINEAR-4ASSET-CANONICAL-HALFYEAR-V1",
        "claim_id": "CLM-20260727-CANONICAL-HALFYEAR-DATA-001",
        "provider": "Bybit V5 public market API",
        "venue": "Bybit",
        "product": "USDT linear perpetual",
        "symbol": args.symbol,
        "physical_segment": args.segment,
        "logical_segment": logical_segment,
        "start": start_iso,
        "end_exclusive": end_iso,
        "retrieved_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "source_base_url": args.base_url,
        "github_sha": os.environ.get("GITHUB_SHA"),
        "code_identity": code_identity(),
        "causal_availability": (
            "Completed bars become usable only at start_time plus interval; funding at its exact "
            "timestamp; missing rows remain explicit; downstream new orders activate no earlier "
            "than 500 ms after the last input became available."
        ),
        "coverage": coverage,
        "files": files,
        "source_page_count": len(audits),
        "orders_submitted": False,
        "credentials_used": False,
    }
    manifest_path = out / "DATASET_MANIFEST.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (out / "DATASET_MANIFEST.sha256").write_text(
        f"{sha256_file(manifest_path)}  {manifest_path.name}\n", encoding="utf-8"
    )
    return out


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--segment", required=True, choices=sorted(SEGMENTS))
    parser.add_argument("--symbol", required=True, choices=SYMBOLS)
    parser.add_argument("--out", required=True)
    parser.add_argument("--base-url", default="https://api.bybit.com")
    parser.add_argument("--timeout", type=int, default=30)
    parser.add_argument("--max-attempts", type=int, default=8)
    parser.add_argument("--min-request-interval", type=float, default=0.08)
    parser.add_argument("--min-market-coverage", type=float, default=0.995)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    out = build(args)
    print(json.dumps({"status": "BUILT", "output": str(out)}, indent=2))


if __name__ == "__main__":
    main()
