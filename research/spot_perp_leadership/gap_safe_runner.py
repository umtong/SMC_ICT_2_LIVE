from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from . import pipeline as p

GAP_AUDIT_SCHEMA_VERSION = 1


def _regular_grid(streams: dict[tuple[str, str], pd.DataFrame]) -> np.ndarray:
    starts = [int(frame.open_time_ms.min()) for frame in streams.values() if not frame.empty]
    ends = [int(frame.open_time_ms.max()) for frame in streams.values() if not frame.empty]
    if len(starts) != len(streams) or len(ends) != len(streams):
        raise AssertionError("empty spot/perpetual/mark stream")
    start, end = max(starts), min(ends)
    if start > end or start % p.BAR_MS or end % p.BAR_MS:
        raise AssertionError("invalid common minute bounds")
    return np.arange(start, end + p.BAR_MS, p.BAR_MS, dtype=np.int64)


def _map_column(frame: pd.DataFrame, grid: np.ndarray, column: str) -> tuple[np.ndarray, int]:
    output = np.full(len(grid), np.nan, dtype=float)
    times = frame.open_time_ms.to_numpy(np.int64)
    inside = (times >= grid[0]) & (times <= grid[-1])
    times = times[inside]
    values = frame.loc[inside, column].to_numpy(float)
    positions = ((times - grid[0]) // p.BAR_MS).astype(np.int64)
    exact = grid[positions] == times
    if not exact.all():
        raise AssertionError(f"{column}: non-minute-aligned source timestamp")
    output[positions] = values
    return output, int(len(positions))


def _write_gap_audit(root: Path, record: dict) -> None:
    path = root / "GAP_AUDIT.json"
    if path.exists():
        payload = json.loads(path.read_text(encoding="utf-8"))
    else:
        payload = {
            "schema_version": GAP_AUDIT_SCHEMA_VERSION,
            "policy": (
                "regular UTC minute grid; source absences remain NaN; no forward fill, "
                "backfill, interpolation, synthetic OHLC or timeline compression"
            ),
            "loads": [],
        }
    payload["loads"].append(record)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def load_panel_gap_safe(root: Path, start: str, end: str) -> p.Panel:
    streams: dict[tuple[str, str], pd.DataFrame] = {}
    for symbol in p.SYMBOLS:
        for dtype in ("spot_klines", "perp_klines", "mark_klines"):
            streams[(dtype, symbol)] = p._concat_klines(root, dtype, symbol, start, end)

    grid = _regular_grid(streams)
    shape = (len(p.SYMBOLS), len(grid))
    fields = {
        key: np.full(shape, np.nan, dtype=float)
        for key in (
            "spot_open", "spot_high", "spot_low", "spot_close", "spot_quote", "spot_buy_quote",
            "perp_open", "perp_high", "perp_low", "perp_close", "perp_quote", "perp_buy_quote",
            "mark_open",
        )
    }
    stream_audit: dict[str, dict] = {}
    for si, symbol in enumerate(p.SYMBOLS):
        for prefix, dtype in (("spot", "spot_klines"), ("perp", "perp_klines")):
            frame = streams[(dtype, symbol)]
            matched = 0
            for target, source in (
                ("open", "open"),
                ("high", "high"),
                ("low", "low"),
                ("close", "close"),
                ("quote", "quote_volume"),
                ("buy_quote", "taker_buy_quote"),
            ):
                mapped, count = _map_column(frame, grid, source)
                fields[f"{prefix}_{target}"][si] = mapped
                matched = count
            stream_audit[f"{dtype}:{symbol}"] = {
                "grid_minutes": int(len(grid)),
                "observed_minutes": matched,
                "missing_minutes": int(len(grid) - matched),
            }
        mark = streams[("mark_klines", symbol)]
        mapped, matched = _map_column(mark, grid, "open")
        fields["mark_open"][si] = mapped
        stream_audit[f"mark_klines:{symbol}"] = {
            "grid_minutes": int(len(grid)),
            "observed_minutes": matched,
            "missing_minutes": int(len(grid) - matched),
        }

    funding: dict[str, pd.DataFrame] = {}
    funding_audit: dict[str, dict] = {}
    for si, symbol in enumerate(p.SYMBOLS):
        frame = p._concat_funding(root, symbol, start, end)
        times = frame.time_ms.to_numpy(np.int64)
        inside = (times >= grid[0]) & (times <= grid[-1])
        frame = frame.loc[inside].copy().reset_index(drop=True)
        times = frame.time_ms.to_numpy(np.int64)
        positions = ((times - grid[0]) // p.BAR_MS).astype(np.int64)
        exact = grid[positions] == times
        if not exact.all():
            raise AssertionError(f"{symbol}: funding timestamp is not on the regular minute grid")
        frame["mark_price"] = fields["mark_open"][si, positions]
        missing_mark = ~np.isfinite(frame.mark_price.to_numpy(float))
        if missing_mark.any():
            missing_times = frame.loc[missing_mark, "time_ms"].astype(int).tolist()
            raise AssertionError(
                f"{symbol}: {len(missing_times)} funding events lack an exact official mark open: "
                f"{missing_times[:8]}"
            )
        funding[symbol] = frame
        funding_audit[symbol] = {
            "event_count": int(len(frame)),
            "missing_exact_mark_count": int(missing_mark.sum()),
        }

    fully_observed = np.ones(len(grid), dtype=bool)
    for si in range(len(p.SYMBOLS)):
        fully_observed &= np.isfinite(fields["spot_close"][si])
        fully_observed &= np.isfinite(fields["perp_close"][si])
        fully_observed &= np.isfinite(fields["mark_open"][si])
    record = {
        "requested_start_month": start,
        "requested_end_month": end,
        "grid_start_ms": int(grid[0]),
        "grid_end_ms": int(grid[-1]),
        "grid_minutes": int(len(grid)),
        "all_six_price_streams_observed_minutes": int(fully_observed.sum()),
        "any_stream_missing_minutes": int((~fully_observed).sum()),
        "streams": stream_audit,
        "funding": funding_audit,
    }
    _write_gap_audit(root, record)
    print("GAP_AUDIT_JSON=" + json.dumps(record, sort_keys=True, separators=(",", ":")), flush=True)
    return p.Panel(times=grid, funding=funding, **fields)


def self_test() -> None:
    grid = np.arange(1_600_000_000_000, 1_600_000_240_000, p.BAR_MS, dtype=np.int64)
    frame = pd.DataFrame(
        {
            "open_time_ms": [grid[0], grid[1], grid[3]],
            "close": [100.0, 101.0, 103.0],
        }
    )
    mapped, matched = _map_column(frame, grid, "close")
    assert matched == 3
    assert mapped[0] == 100.0 and mapped[1] == 101.0 and np.isnan(mapped[2]) and mapped[3] == 103.0
    streams = {
        (dtype, symbol): frame.rename(columns={"close": "open"})
        for dtype in ("spot_klines", "perp_klines", "mark_klines")
        for symbol in p.SYMBOLS
    }
    regular = _regular_grid(streams)
    assert np.array_equal(regular, grid)
    print("GAP_SAFE_SELF_TEST_PASS")


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("self-test")
    staged = sub.add_parser("staged-run")
    staged.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "self-test":
        self_test()
    else:
        p.load_panel = load_panel_gap_safe
        p.staged_run(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
