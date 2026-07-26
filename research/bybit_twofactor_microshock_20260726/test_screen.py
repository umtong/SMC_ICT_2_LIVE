from __future__ import annotations

import numpy as np

import screen


def synthetic_asset(rng: np.random.Generator, returns: np.ndarray, base_price: float, flow_scale: float) -> dict[str, np.ndarray]:
    one_second_mark = base_price * np.exp(np.cumsum(returns))
    endpoint = np.repeat(one_second_mark, 10)
    micro = rng.normal(0.0, 1e-6, len(endpoint))
    mark = endpoint * np.exp(micro)
    total = rng.lognormal(mean=np.log(flow_scale), sigma=0.5, size=len(mark))
    signed = total * np.clip(rng.normal(0.0, 0.35, len(mark)), -1.0, 1.0)
    count = rng.poisson(3.0, len(mark)).astype(np.int32)
    return {"mark": mark, "total": total, "signed": signed, "trade_count": count}


def test_complete_synthetic_path() -> None:
    rng = np.random.default_rng(20260726)
    seconds = 4_000
    btc = rng.normal(0.0, 1.2e-4, seconds)
    eth_idio = rng.normal(0.0, 1.0e-4, seconds)
    eth = 0.85 * btc + eth_idio
    sol = 1.35 * btc + 0.55 * eth_idio + rng.normal(0.0, 1.8e-4, seconds)
    xrp = 1.05 * btc + 0.35 * eth_idio + rng.normal(0.0, 1.7e-4, seconds)
    arrays = {
        "BTCUSDT": synthetic_asset(rng, btc, 25_000.0, 200_000.0),
        "ETHUSDT": synthetic_asset(rng, eth, 1_700.0, 120_000.0),
        "SOLUSDT": synthetic_asset(rng, sol, 22.0, 80_000.0),
        "XRPUSDT": synthetic_asset(rng, xrp, 0.5, 75_000.0),
    }
    counts, rows = screen.evaluate_day(arrays, "2023-01-15")
    assert len(counts) == len(screen.FAMILIES) * len(screen.FOLLOWERS) * len(screen.HORIZONS) * len(screen.FLOORS)
    assert all(isinstance(value, int) and value >= 0 for value in counts.values())
    assert isinstance(rows, list)
    for family in screen.FAMILIES:
        aggregate, checks, passed = screen.summarize_family(counts, ("2023-01-15",), family, 1.0)
        assert aggregate["total_12bp"] >= aggregate["total_24bp"]
        assert isinstance(checks, dict)
        assert isinstance(passed, bool)
