from __future__ import annotations

import gzip
import hashlib
import json
from datetime import date

import pandas as pd

from scripts.market_data import build_public_trade_compact as compact
from scripts.market_data import build_public_trade_month as source
from scripts.market_data import load_public_trade_compact as loader
from scripts.market_data import verify_public_trade_compact as verifier


def _write_trade_gzip(path, rows: list[str]) -> None:
    header = (
        "timestamp,symbol,side,size,price,tickDirection,trdMatchID,"
        "grossValue,homeNotional,foreignNotional\n"
    )
    with gzip.open(path, "wt", encoding="utf-8", newline="") as handle:
        handle.write(header)
        for row in rows:
            handle.write(row + "\n")


def _sha(path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _fake_shard(tmp_path, frame: pd.DataFrame, *, leading_prelisting_days=None):
    root = tmp_path / "shard"
    data = root / "micro_bars" / "500ms_observed.parquet"
    data.parent.mkdir(parents=True)
    frame.to_parquet(data, index=False, compression="zstd")
    sources = root / "SOURCE_FILES.jsonl"
    sources.write_text(json.dumps({"date": "1970-01-02", "sha256": "x"}) + "\n", encoding="utf-8")
    manifest = {
        "schema_version": 3,
        "dataset_id": "DS-TEST-SPARSE500-V3",
        "dataset_family_id": "DSF-BYBIT-LINEAR-4ASSET-MONTHLY-SPARSE500-V3",
        "claim_id": "CLM-20260727-CANONICAL-HALFYEAR-DATA-001",
        "status": "VERIFIED",
        "stored_interval": "500ms_observed_sparse",
        "derived_intervals": ["1s", "5s", "15s"],
        "start": "1970-01-01T00:00:00Z",
        "end_exclusive": "1970-02-01T00:00:00Z",
        "coverage": {
            "unexpected_missing_days": [],
            "leading_prelisting_days": leading_prelisting_days or [],
            "observed_500ms_rows": len(frame),
        },
        "source_file_count": 1,
        "credentials_used": False,
        "orders_submitted": False,
        "files": [
            {
                "kind": "micro_bar", "name": "500ms_observed",
                "path": "micro_bars/500ms_observed.parquet", "rows": len(frame),
                "bytes": data.stat().st_size, "sha256": _sha(data),
            },
            {
                "kind": "source_audit", "name": "source_files",
                "path": "SOURCE_FILES.jsonl", "rows": 1,
                "bytes": sources.stat().st_size, "sha256": _sha(sources),
            },
        ],
    }
    manifest_path = root / "DATASET_MANIFEST.json"
    manifest_path.write_text(json.dumps(manifest, sort_keys=True), encoding="utf-8")
    (root / "DATASET_MANIFEST.sha256").write_text(
        f"{_sha(manifest_path)}  DATASET_MANIFEST.json\n", encoding="utf-8"
    )
    return root


def test_compact_halfseconds_preserves_exact_flow_and_offsets(tmp_path) -> None:
    path = tmp_path / "trades.csv.gz"
    _write_trade_gzip(path, [
        "0.1000,BTCUSDT,Buy,2,10,PlusTick,a,0,0,0",
        "0.2000,BTCUSDT,Sell,1,12,MinusTick,b,0,0,0",
        "0.3000,BTCUSDT,Buy,3,9,PlusTick,c,0,0,0",
        "0.4990,BTCUSDT,Buy,1,11,PlusTick,d,0,0,0",
        "0.5000,BTCUSDT,Sell,4,8,MinusTick,e,0,0,0",
    ])
    half, total = source.aggregate_trade_file(path, chunksize=2)
    out = compact.compact_halfseconds(half)
    assert total == 5
    assert out["start_time_ms"].tolist() == [0, 500]
    assert list(out.columns) == list(compact.COMPACT_COLUMNS)
    row = out.iloc[0]
    assert row["open"] == 10
    assert row["high"] == 12
    assert row["low"] == 9
    assert row["close"] == 11
    assert row["buy_volume"] == 6
    assert row["sell_volume"] == 1
    assert row["high_offset_ms"] == 200
    assert row["low_offset_ms"] == 300
    assert row["available_at_ms"] == 500


def test_materialize_distinguishes_prelisting_and_covered_no_trade(tmp_path) -> None:
    day2 = 86_400_000
    observed = pd.DataFrame({
        "start_time_ms": [day2 + 500],
        "open": [101.0], "high": [101.0], "low": [101.0], "close": [101.0],
        "buy_volume": [2.0], "sell_volume": [0.0],
        "buy_turnover": [202.0], "sell_turnover": [0.0],
        "trade_count": pd.Series([1], dtype="int32"),
        "first_offset_ms": pd.Series([123], dtype="int16"),
        "high_offset_ms": pd.Series([123], dtype="int16"),
        "low_offset_ms": pd.Series([123], dtype="int16"),
        "last_offset_ms": pd.Series([123], dtype="int16"),
        "available_at_ms": [day2 + 1_000],
    })
    root = _fake_shard(tmp_path, observed, leading_prelisting_days=["1970-01-01"])
    grid = loader.materialize_500ms(
        root, start_ms=day2 - 1_000, end_exclusive_ms=day2 + 1_500
    )
    assert grid["start_time_ms"].tolist() == [day2 - 1_000, day2 - 500, day2, day2 + 500, day2 + 1_000]
    assert grid["source_available"].tolist() == [False, False, True, True, True]
    assert grid["observed"].tolist() == [False, False, False, True, False]
    assert grid["trade_count"].tolist() == [-1, -1, 0, 1, 0]
    assert pd.isna(grid.iloc[0]["volume"])
    assert grid.iloc[2]["volume"] == 0
    assert grid.iloc[3]["volume"] == 2


def test_derive_seconds_and_first_executable_trade(tmp_path) -> None:
    observed = pd.DataFrame({
        "start_time_ms": [500, 1_000],
        "open": [101.0, 102.0], "high": [101.0, 102.0],
        "low": [101.0, 102.0], "close": [101.0, 102.0],
        "buy_volume": [1.0, 0.0], "sell_volume": [0.0, 2.0],
        "buy_turnover": [101.0, 0.0], "sell_turnover": [0.0, 204.0],
        "trade_count": pd.Series([1, 1], dtype="int32"),
        "first_offset_ms": pd.Series([123, 10], dtype="int16"),
        "high_offset_ms": pd.Series([123, 10], dtype="int16"),
        "low_offset_ms": pd.Series([123, 10], dtype="int16"),
        "last_offset_ms": pd.Series([123, 10], dtype="int16"),
        "available_at_ms": [1_000, 1_500],
    })
    root = _fake_shard(tmp_path, observed)
    grid = loader.materialize_500ms(root, start_ms=0, end_exclusive_ms=2_000)
    seconds = loader.derive_seconds(grid, 1)
    assert seconds["start_time_ms"].tolist() == [0, 1_000]
    assert seconds["open"].tolist() == [101.0, 102.0]
    assert seconds["trade_count"].tolist() == [1, 1]
    assert seconds["available_at_ms"].tolist() == [1_000, 2_000]
    fill = loader.first_executable_trade_after(observed, 0)
    assert fill == {
        "activation_time_ms": 500,
        "trade_time_ms": 623,
        "price": 101.0,
        "bucket_start_time_ms": 500,
    }
    result = verifier.verify(root)
    assert result["status"] == "PASS"
    assert result["observed_500ms_rows"] == 2


def test_oci_reference_is_deterministic() -> None:
    assert loader.oci_reference("BTCUSDT", "2024-01") == (
        "ghcr.io/umtong/smc-ict-2-live/bybit-microbar:btcusdt-2024-01-v3"
    )
