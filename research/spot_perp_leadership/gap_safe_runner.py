from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from . import pipeline as p

GAP_AUDIT_SCHEMA_VERSION = 2


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


def _funding_mark_values(
    event_times: np.ndarray,
    grid: np.ndarray,
    mark_open: np.ndarray,
    contract_open: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    containing_minute = (event_times // p.BAR_MS) * p.BAR_MS
    positions = ((containing_minute - grid[0]) // p.BAR_MS).astype(np.int64)
    if np.any(positions < 0) or np.any(positions >= len(grid)):
        raise AssertionError("funding event outside the regular source grid")
    if not np.all(grid[positions] == containing_minute):
        raise AssertionError("funding containing-minute mapping failed")
    exact_mark = mark_open[positions]
    exact_contract = contract_open[positions]
    use_fallback = ~np.isfinite(exact_mark)
    values = np.where(use_fallback, exact_contract, exact_mark)
    if not np.isfinite(values).all():
        raise AssertionError("funding event lacks both containing-minute mark and contract open")
    sources = np.where(use_fallback, "exact_contract_open_fallback", "containing_minute_mark_open")
    return values.astype(float), sources.astype(str), positions


def _write_gap_audit(root: Path, record: dict) -> None:
    path = root / "GAP_AUDIT.json"
    if path.exists():
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("schema_version") != GAP_AUDIT_SCHEMA_VERSION:
            payload = {
                "schema_version": GAP_AUDIT_SCHEMA_VERSION,
                "policy": (
                    "regular UTC minute grid; source absences remain NaN; no forward fill, "
                    "backfill, interpolation, synthetic OHLC or timeline compression; funding keeps "
                    "actual calc_time and uses the containing-minute official mark open, with exact "
                    "same-minute USD-M contract open only when that mark observation is absent"
                ),
                "loads": [],
            }
    else:
        payload = {
            "schema_version": GAP_AUDIT_SCHEMA_VERSION,
            "policy": (
                "regular UTC minute grid; source absences remain NaN; no forward fill, "
                "backfill, interpolation, synthetic OHLC or timeline compression; funding keeps "
                "actual calc_time and uses the containing-minute official mark open, with exact "
                "same-minute USD-M contract open only when that mark observation is absent"
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
        event_times = frame.time_ms.to_numpy(np.int64)
        containing_minute = (event_times // p.BAR_MS) * p.BAR_MS
        inside = (containing_minute >= grid[0]) & (containing_minute <= grid[-1])
        frame = frame.loc[inside].copy().reset_index(drop=True)
        event_times = frame.time_ms.to_numpy(np.int64)
        mark_values, mark_sources, _ = _funding_mark_values(
            event_times,
            grid,
            fields["mark_open"][si],
            fields["perp_open"][si],
        )
        frame["mark_price"] = mark_values
        frame["mark_source"] = mark_sources
        funding[symbol] = frame
        offsets = event_times % p.BAR_MS
        funding_audit[symbol] = {
            "event_count": int(len(frame)),
            "nonzero_calc_time_offset_count": int((offsets != 0).sum()),
            "maximum_calc_time_offset_ms": int(offsets.max()) if len(offsets) else 0,
            "containing_minute_mark_open_count": int((mark_sources == "containing_minute_mark_open").sum()),
            "exact_contract_open_fallback_count": int((mark_sources == "exact_contract_open_fallback").sum()),
            "unvalued_event_count": 0,
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
    aligned_start = (1_600_000_000_000 // p.BAR_MS) * p.BAR_MS
    grid = np.arange(aligned_start, aligned_start + 4 * p.BAR_MS, p.BAR_MS, dtype=np.int64)
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
    mark = np.array([100.0, np.nan, 102.0, 103.0])
    contract = np.array([99.0, 101.0, 102.0, 103.0])
    values, sources, positions = _funding_mark_values(
        np.array([grid[0] + 6, grid[1] + 31], dtype=np.int64), grid, mark, contract
    )
    assert np.array_equal(positions, np.array([0, 1]))
    assert np.allclose(values, np.array([100.0, 101.0]))
    assert sources.tolist() == ["containing_minute_mark_open", "exact_contract_open_fallback"]
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
