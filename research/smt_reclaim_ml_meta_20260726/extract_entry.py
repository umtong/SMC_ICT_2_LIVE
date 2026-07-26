from __future__ import annotations

import numpy as np

import extract as engine


def corrected_rolling_realized_volatility(mark: np.ndarray, window: int = 100) -> np.ndarray:
    price = np.asarray(mark, dtype=np.float64)
    returns = np.full(len(price), np.nan, dtype=np.float64)
    valid = (
        np.isfinite(price[1:])
        & np.isfinite(price[:-1])
        & (price[1:] > 0)
        & (price[:-1] > 0)
    )
    valid_positions = np.flatnonzero(valid) + 1
    returns[valid_positions] = np.log(
        price[valid_positions] / price[valid_positions - 1]
    )
    squared = np.nan_to_num(returns * returns, nan=0.0)
    cumulative = np.concatenate(([0.0], np.cumsum(squared, dtype=np.float64)))
    end = np.arange(1, len(squared) + 1)
    start = np.maximum(0, end - window)
    return np.sqrt(np.maximum(0.0, cumulative[end] - cumulative[start]))


engine.rolling_realized_volatility = corrected_rolling_realized_volatility


if __name__ == "__main__":
    raise SystemExit(engine.main())
