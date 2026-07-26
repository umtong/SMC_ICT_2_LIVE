from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import pandas as pd
import requests

import cross_venue_basis_v5d as basis_v5d
import cross_venue_failclosed_v5d as failclosed_v5d
import cross_venue_performance_v5d as performance_v5d
import cross_venue_pilot as v1
import cross_venue_pilot_fast_exit_v5d as fast_exit_v5d
import cross_venue_pilot_v2 as v2
import cross_venue_signals_v5d as signals_v5d

OBSERVATION_WINDOWS_MS = (1000, 3000)
REQUIRED_PREPARED_ATTRS = frozenset({
    "_v5d_signal_common",
    "_v5d_signal_observation",
    "_v5d_basis_prepared",
    "_v5d_first_quote_index_cache",
    "_v5d_fast_exit_arrays",
})


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def index_sha256(frame: pd.DataFrame) -> str:
    return hashlib.sha256(frame.index.to_numpy("int64").tobytes()).hexdigest()


def _precompute(frame: pd.DataFrame) -> dict[str, Any]:
    common = signals_v5d._common(frame)
    for observation_ms in OBSERVATION_WINDOWS_MS:
        signals_v5d._observation(frame, observation_ms)
    basis_v5d.prepare_basis_v5d(frame)
    positions, times = performance_v5d.first_quote_index_cached(frame)
    fast_arrays = fast_exit_v5d._arrays(frame)
    return {
        "rows": int(len(frame)),
        "first_bucket_ms": int(frame.index[0]),
        "last_bucket_ms": int(frame.index[-1]),
        "index_sha256": index_sha256(frame),
        "common_cache_keys": sorted(common),
        "observation_windows_ms": list(OBSERVATION_WINDOWS_MS),
        "first_quote_count": int(len(positions)),
        "first_quote_times_count": int(len(times)),
        "fast_exit_array_keys": sorted(fast_arrays),
        "attrs": sorted(frame.attrs),
    }


def prepare(day: str, output: Path, source_cache: Path) -> dict[str, Any]:
    if day not in v1.PILOT_DAYS:
        raise ValueError(f"day is not in the frozen V5D pilot set: {day}")
    output.mkdir(parents=True, exist_ok=True)
    source_cache.mkdir(parents=True, exist_ok=True)

    performance_v5d.patch()
    failclosed_v5d.patch()
    fast_exit_v5d.patch()
    v2.LATENCY_DIAGNOSTICS.clear()

    source_records_by_symbol: dict[str, list[dict[str, Any]]] = {}
    frames: dict[str, dict[str, Any]] = {}
    with requests.Session() as session:
        session.headers["User-Agent"] = "SMC_ICT_2_LIVE-cross-venue-v5d-prepare/1.0"
        for symbol in v1.SYMBOLS:
            before = len(v2.LATENCY_DIAGNOSTICS)
            frame, records = v1.load_day(source_cache, session, day, symbol)
            diagnostics = v2.LATENCY_DIAGNOSTICS[before:]
            cache_summary = _precompute(frame)
            path = output / f"{symbol}.pkl.gz"
            frame.to_pickle(
                path,
                compression={"method": "gzip", "compresslevel": 1},
                protocol=5,
            )
            reloaded = pd.read_pickle(path, compression="gzip")
            if len(reloaded) != len(frame):
                raise AssertionError(f"prepared frame row count changed for {day} {symbol}")
            if index_sha256(reloaded) != cache_summary["index_sha256"]:
                raise AssertionError(f"prepared frame index changed for {day} {symbol}")
            if not REQUIRED_PREPARED_ATTRS.issubset(reloaded.attrs):
                raise AssertionError(
                    f"prepared frame lost causal caches for {day} {symbol}: "
                    f"{sorted(REQUIRED_PREPARED_ATTRS.difference(reloaded.attrs))}"
                )
            source_records_by_symbol[symbol] = records
            frames[symbol] = {
                **cache_summary,
                "file": path.name,
                "file_bytes": path.stat().st_size,
                "file_sha256": sha256_file(path),
                "source_records": records,
                "latency_diagnostics": diagnostics,
            }
            print(json.dumps({
                "stage": "v5d_prepare",
                "day": day,
                "symbol": symbol,
                "rows": len(frame),
                "prepared_bytes": path.stat().st_size,
                "source_files": len(records),
            }, sort_keys=True), flush=True)

    manifest = {
        "schema_version": 1,
        "claim_id": "CLM-20260725-1850-XVENUE-001",
        "day": day,
        "causal_engine_version": "5D",
        "source_clock": "Tardis local_timestamp",
        "bucket_ms": v1.BUCKET_MS,
        "symbols": list(v1.SYMBOLS),
        "observation_windows_ms": list(OBSERVATION_WINDOWS_MS),
        "frames": frames,
        "scientific_dependencies_changed": False,
        "strategy_or_pnl_computed": False,
        "development_opened": False,
        "selection_opened": False,
        "confirmation_opened": False,
        "2026_opened": False,
        "orders_submitted": False,
    }
    manifest_path = output / "PREPARED_MANIFEST.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )
    (output / "PREPARED_MANIFEST.sha256").write_text(
        f"{sha256_file(manifest_path)}  {manifest_path.name}\n",
        encoding="utf-8",
    )
    return manifest


def load_prepared(
    root: Path,
    day: str,
) -> tuple[dict[str, pd.DataFrame], dict[str, Any]]:
    manifest_path = root / "PREPARED_MANIFEST.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest["day"] != day:
        raise ValueError(f"prepared day mismatch: {manifest['day']} != {day}")
    if manifest["causal_engine_version"] != "5D":
        raise ValueError("prepared causal engine mismatch")
    if manifest["strategy_or_pnl_computed"] is not False:
        raise ValueError("prepared source artifact opened strategy PnL")
    frames: dict[str, pd.DataFrame] = {}
    for symbol in v1.SYMBOLS:
        record = manifest["frames"][symbol]
        path = root / record["file"]
        if sha256_file(path) != record["file_sha256"]:
            raise ValueError(f"prepared frame checksum mismatch for {day} {symbol}")
        frame = pd.read_pickle(path, compression="gzip")
        if len(frame) != int(record["rows"]):
            raise ValueError(f"prepared frame row count mismatch for {day} {symbol}")
        if index_sha256(frame) != record["index_sha256"]:
            raise ValueError(f"prepared frame index mismatch for {day} {symbol}")
        if not REQUIRED_PREPARED_ATTRS.issubset(frame.attrs):
            raise ValueError(
                f"prepared frame is missing causal caches for {day} {symbol}: "
                f"{sorted(REQUIRED_PREPARED_ATTRS.difference(frame.attrs))}"
            )
        frames[symbol] = frame
    return frames, manifest


def self_test() -> None:
    frame = pd.DataFrame(
        {"x": [1.0, 2.0]},
        index=pd.Index([100, 200], dtype="int64"),
    )
    frame.attrs["nested"] = {"array": [1, 2, 3]}
    for name in REQUIRED_PREPARED_ATTRS:
        frame.attrs[name] = {"sentinel": name}
    import tempfile

    with tempfile.TemporaryDirectory() as temporary:
        path = Path(temporary) / "frame.pkl.gz"
        frame.to_pickle(
            path,
            compression={"method": "gzip", "compresslevel": 1},
            protocol=5,
        )
        restored = pd.read_pickle(path, compression="gzip")
        assert restored.equals(frame)
        assert restored.attrs == frame.attrs
        assert REQUIRED_PREPARED_ATTRS.issubset(restored.attrs)
        assert index_sha256(restored) == index_sha256(frame)
    print("V5D_PREPARED_FRAME_ROUNDTRIP_PASS")


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("self-test")
    run_parser = subparsers.add_parser("run")
    run_parser.add_argument("--day", required=True)
    run_parser.add_argument("--output", type=Path, required=True)
    run_parser.add_argument("--source-cache", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "self-test":
        self_test()
    else:
        prepare(args.day, args.output, args.source_cache)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
