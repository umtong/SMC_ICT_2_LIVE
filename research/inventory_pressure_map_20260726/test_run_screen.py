from __future__ import annotations

import gzip
import math
from pathlib import Path

import numpy as np

from run_screen import (
    ALL_DATES,
    DEVELOPMENT_DATES,
    EXPECTED_CANDIDATE_COUNT,
    FIT_DATES,
    LATENCIES_MS,
    MAP_SPECS,
    PRESSURE_QUANTILES,
    SYMBOLS,
    Event,
    InventoryMap,
    Sample,
    SideInventory,
    compound,
    compute_execution_arrays,
    gather_events,
    load_trades,
    matched_baseline_accuracy,
    maximum_drawdown,
    metrics,
)


def test_frozen_grid_count() -> None:
    assert EXPECTED_CANDIDATE_COUNT == 1296
    assert len(MAP_SPECS) == 18
    assert ALL_DATES == FIT_DATES + DEVELOPMENT_DATES


def test_trade_vwap_is_amount_weighted(tmp_path: Path) -> None:
    path = tmp_path / "trades.csv.gz"
    rows = (
        "exchange,symbol,timestamp,local_timestamp,id,side,price,amount\n"
        "bybit,BTCUSDT,1,1000000,a,buy,100,2\n"
        "bybit,BTCUSDT,2,2000000,b,sell,110,1\n"
    )
    with gzip.open(path, "wt", encoding="utf-8") as handle:
        handle.write(rows)
    boundaries = np.array([5_000_000, 10_000_000], dtype=np.int64)
    loaded = load_trades(path, 0, 15_000_000, boundaries)
    assert math.isclose(float(loaded["vwap"][0]), 310.0 / 3.0, rel_tol=0, abs_tol=1e-12)
    assert math.isclose(float(loaded["total_notional"][0]), 310.0, rel_tol=0, abs_tol=1e-12)
    assert math.isclose(float(loaded["flow"][0]), 90.0 / 310.0, rel_tol=0, abs_tol=1e-12)


def test_quote_execution_is_first_causal_quote_after_latency() -> None:
    boundaries = np.array([1_000_000], dtype=np.int64)
    quote_ts = np.array([1_099_999, 1_100_000, 31_100_000], dtype=np.int64)
    bid = np.array([99.0, 100.0, 101.0])
    ask = np.array([100.0, 101.0, 102.0])
    entry_ts, exit_ts, gross_long, gross_short, valid = compute_execution_arrays(
        boundaries, quote_ts, bid, ask
    )
    assert LATENCIES_MS[0] == 100
    assert int(entry_ts[0, 0]) == 1_100_000
    assert int(exit_ts[0, 0, 0]) == 31_100_000
    assert bool(valid[0, 0, 0])
    assert math.isclose(float(gross_long[0, 0, 0]), 101.0 / 101.0 - 1.0, abs_tol=1e-12)
    assert math.isclose(float(gross_short[0, 0, 0]), 100.0 / 102.0 - 1.0, abs_tol=1e-12)


def test_inventory_add_decay_and_pro_rata_closure() -> None:
    side = SideInventory()
    side.add(math.log(100.0), 1.0)
    near = side.density(math.log(100.0), 0.001)
    far = side.density(math.log(110.0), 0.001)
    assert near > far
    assert math.isclose(side.remove_pro_rata(0.25), 0.25, abs_tol=1e-12)
    assert math.isclose(side.total, 0.75, abs_tol=1e-12)

    state = InventoryMap(1800)
    state.update(math.log(100.0), 0.01, 0.8)
    assert state.long.total > 0
    assert state.short.total == 0
    before = state.long.total
    state.update(float("nan"), 0.0, 0.0)
    assert state.long.total < before
    state.update(math.log(99.0), -0.002, -0.8)
    assert state.long.total < before - 0.001


def test_six_symbol_date_breadth_and_concentration_metrics() -> None:
    events = [
        Event(1, 1, 2, "BTCUSDT", DEVELOPMENT_DATES[0], 1, 0.01, 1.0),
        Event(2, 2, 3, "ETHUSDT", DEVELOPMENT_DATES[0], 1, 0.01, 1.0),
        Event(3, 3, 4, "BTCUSDT", DEVELOPMENT_DATES[1], 1, 0.01, 1.0),
        Event(4, 4, 5, "ETHUSDT", DEVELOPMENT_DATES[2], 1, 0.01, 1.0),
    ]
    result = metrics(events, 0.0, segment_dates=DEVELOPMENT_DATES)
    assert result["positive_symbol_date_segments"] == 4
    assert len(result["symbol_date_segment_returns"]) == 6
    assert compound(np.array([0.01, -0.005, 0.002])) > 0
    assert maximum_drawdown(np.array([0.01, -0.005, 0.002])) > 0


def test_fit_only_matched_baseline_fallback_hierarchy() -> None:
    baseline = [
        Event(
            i,
            i,
            i + 1,
            "BTCUSDT",
            FIT_DATES[0],
            1,
            0.01 if i < 6 else -0.01,
            1.0,
            "BTCUSDT|low|near",
        )
        for i in range(10)
    ]
    selected = [
        Event(
            20,
            20,
            21,
            "BTCUSDT",
            DEVELOPMENT_DATES[0],
            1,
            0.01,
            1.0,
            "BTCUSDT|low|near",
        )
    ]
    assert math.isclose(matched_baseline_accuracy(baseline, selected), 0.6, abs_tol=1e-12)


def _sample(
    symbol: str,
    pressure: list[float],
    entry: list[int],
    exit_: list[int],
) -> Sample:
    n = len(pressure)
    maps = len(MAP_SPECS)
    p_up = np.zeros((n, maps), dtype=np.float32)
    p_up[:, 0] = np.asarray(pressure, dtype=np.float32)
    p_down = np.zeros((n, maps), dtype=np.float32)
    o_up = np.full((n, maps), np.nan, dtype=np.float32)
    o_up[:, 0] = 0.5
    o_down = np.full((n, maps), np.nan, dtype=np.float32)
    entry_ts = np.tile(np.asarray(entry, dtype=np.int64)[:, None], (1, 2))
    exit_ts = np.zeros((n, 2, 3), dtype=np.int64)
    gross_long = np.full((n, 2, 3), 0.01, dtype=np.float64)
    gross_short = np.full((n, 2, 3), -0.01, dtype=np.float64)
    valid = np.ones((n, 2, 3), dtype=bool)
    for latency in range(2):
        for horizon in range(3):
            exit_ts[:, latency, horizon] = np.asarray(exit_, dtype=np.int64)
    return Sample(
        symbol=symbol,
        date=FIT_DATES[0],
        partition="fit",
        times_us=np.arange(n, dtype=np.int64) * 10,
        mid=np.full(n, 100.0),
        log_mid=np.full(n, math.log(100.0)),
        ret5=np.full(n, 0.001),
        flow=np.full(n, 1.0),
        oi_delta_rel=np.zeros(n),
        sigma=np.full(n, 0.001),
        pressure_up=p_up,
        pressure_down=p_down,
        offset_up=o_up,
        offset_down=o_down,
        entry_ts=entry_ts,
        exit_ts=exit_ts,
        gross_long=gross_long,
        gross_short=gross_short,
        execution_valid=valid,
    )


def _thresholds() -> dict[tuple[str, int, int, float], float]:
    values: dict[tuple[str, int, int, float], float] = {}
    for symbol in SYMBOLS:
        for direction in (-1, 1):
            for quantile in PRESSURE_QUANTILES:
                values[(symbol, 0, direction, quantile)] = 1.0
    return values


def test_global_slot_chooses_highest_normalized_pressure_score() -> None:
    btc = _sample("BTCUSDT", [2.0], [100], [200])
    eth = _sample("ETHUSDT", [3.0], [100], [200])
    events, raw, unavailable = gather_events(
        [btc, eth],
        "fit",
        0,
        "cluster_attraction",
        0.4,
        0.9,
        0,
        0,
        _thresholds(),
        {"BTCUSDT": 0.001, "ETHUSDT": 0.001},
        {},
        selected=True,
    )
    assert raw == 2
    assert unavailable == 0
    assert len(events) == 1
    assert events[0].symbol == "ETHUSDT"


def test_global_slot_prohibits_exact_exit_timestamp_reentry() -> None:
    sample = _sample("BTCUSDT", [2.0, 2.0], [100, 200], [200, 300])
    events, _, _ = gather_events(
        [sample],
        "fit",
        0,
        "cluster_attraction",
        0.4,
        0.9,
        0,
        0,
        _thresholds(),
        {"BTCUSDT": 0.001, "ETHUSDT": 0.001},
        {},
        selected=True,
    )
    assert len(events) == 1
    assert events[0].entry_ts == 100
