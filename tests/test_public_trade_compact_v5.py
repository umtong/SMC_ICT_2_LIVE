from __future__ import annotations

import hashlib
import json

import pandas as pd
import pytest

from scripts.market_data import load_public_trade_compact_v5 as loader
from scripts.market_data import repack_public_trade_compact_v5 as repacker
from scripts.market_data import verify_public_trade_compact_v5 as verifier


def _sha(path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _v3_shard(tmp_path, symbol="BTCUSDT"):
    root = tmp_path / "shard"
    data = root / "micro_bars" / "500ms_observed.parquet"
    data.parent.mkdir(parents=True)
    quantum = repacker.PRICE_QUANTUM[symbol]
    prices = [101.0, 102.0] if symbol == "BTCUSDT" else [1.2345, 1.2350]
    frame = pd.DataFrame({
        "start_time_ms": [500, 1_000],
        "open": prices, "high": prices, "low": prices, "close": prices,
        "buy_volume": [1.0, 0.0], "sell_volume": [0.0, 2.0],
        "buy_turnover": [prices[0], 0.0], "sell_turnover": [0.0, prices[1] * 2],
        "trade_count": pd.Series([1, 1], dtype="int32"),
        "first_offset_ms": pd.Series([123, 10], dtype="int16"),
        "high_offset_ms": pd.Series([123, 10], dtype="int16"),
        "low_offset_ms": pd.Series([123, 10], dtype="int16"),
        "last_offset_ms": pd.Series([123, 10], dtype="int16"),
        "available_at_ms": [1_000, 1_500],
    })
    frame.to_parquet(data, index=False, compression="zstd")
    sources = root / "SOURCE_FILES.jsonl"
    sources.write_text(json.dumps({"date": "1970-01-01", "sha256": "x"}) + "\n", encoding="utf-8")
    manifest = {
        "schema_version": 3,
        "dataset_id": f"DS-{symbol}-TEST-SPARSE500-V3",
        "dataset_family_id": "DSF-BYBIT-LINEAR-4ASSET-MONTHLY-SPARSE500-V3",
        "symbol": symbol,
        "status": "VERIFIED",
        "stored_interval": "500ms_observed_sparse",
        "derived_intervals": ["1s", "5s", "15s"],
        "start": "1970-01-01T00:00:00Z",
        "end_exclusive": "1970-02-01T00:00:00Z",
        "coverage": {
            "unexpected_missing_days": [], "leading_prelisting_days": [],
            "observed_500ms_rows": len(frame),
        },
        "source_file_count": 1,
        "credentials_used": False,
        "orders_submitted": False,
        "files": [
            {"kind": "micro_bar", "name": "500ms_observed",
             "path": "micro_bars/500ms_observed.parquet", "rows": len(frame),
             "bytes": data.stat().st_size, "sha256": _sha(data)},
            {"kind": "source_audit", "name": "source_files",
             "path": "SOURCE_FILES.jsonl", "rows": 1,
             "bytes": sources.stat().st_size, "sha256": _sha(sources)},
        ],
    }
    path = root / "DATASET_MANIFEST.json"
    path.write_text(json.dumps(manifest, sort_keys=True), encoding="utf-8")
    (root / "DATASET_MANIFEST.sha256").write_text(
        f"{_sha(path)}  DATASET_MANIFEST.json\n", encoding="utf-8"
    )
    return root, frame, quantum


def test_v5_tick_roundtrip_and_verification(tmp_path) -> None:
    root, original, quantum = _v3_shard(tmp_path)
    repacker.repack(root)
    manifest = loader.load_manifest(root)
    assert manifest["schema_version"] == 5
    assert manifest["price_quantum"] == quantum
    packed = pd.read_parquet(root / "micro_bars" / "500ms_observed_v5.parquet")
    assert packed["bucket_index"].tolist() == [1, 2]
    assert packed["open_tick"].tolist() == [1010, 1020]
    assert "start_time_ms" not in packed.columns
    assert "available_at_ms" not in packed.columns
    observed = loader.load_observed_500ms(root)
    assert observed["start_time_ms"].tolist() == [500, 1_000]
    assert observed["open"].tolist() == original["open"].tolist()
    grid = loader.materialize_500ms(root, start_ms=0, end_exclusive_ms=2_000)
    seconds = loader.derive_seconds(grid, 1)
    assert seconds["open"].tolist() == [101.0, 102.0]
    assert verifier.verify(root)["status"] == "PASS"


def test_price_to_ticks_rejects_non_quantized_value() -> None:
    with pytest.raises(ValueError):
        repacker.price_to_ticks(pd.Series([100.05]), 0.1)


def test_v5_oci_reference() -> None:
    assert loader.oci_reference("XRPUSDT", "2026-01") == (
        "ghcr.io/umtong/smc-ict-2-live/bybit-microbar:xrpusdt-2026-01-v5"
    )
