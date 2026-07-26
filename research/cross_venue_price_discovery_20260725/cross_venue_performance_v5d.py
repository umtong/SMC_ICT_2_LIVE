from __future__ import annotations

import numpy as np
import pandas as pd

import cross_venue_execution_v5 as base

_PATCHED = False
_CACHE_KEY = "_v5d_first_quote_index_cache"
_ORIGINAL_FIRST_QUOTE_INDEX = base._first_quote_index


def first_quote_index_cached(frame: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    """Return the exact V5 first-quote index, computing it once per immutable frame.

    V5 previously scanned the full ``bn_first_event_us`` column for every
    prospective entry and exit. A pilot frame has roughly 864,000 100-ms rows,
    so that repeated scan dominated the 768-policy replay. The aligned market
    frame is immutable after construction; caching the identical positions and
    times arrays changes no decision, fill, global-slot, fee or account path.
    """

    cached = frame.attrs.get(_CACHE_KEY)
    if cached is not None:
        return cached

    raw = pd.to_numeric(frame["bn_first_event_us"], errors="coerce").to_numpy(float)
    positions = np.flatnonzero(np.isfinite(raw))
    times = raw[positions].astype(np.int64)
    if len(times) and np.any(np.diff(times) < 0):
        raise ValueError("Binance first local-arrival quote times are not monotonic")

    positions.setflags(write=False)
    times.setflags(write=False)
    result = (positions, times)
    frame.attrs[_CACHE_KEY] = result
    return result


def clear_frame_cache(frame: pd.DataFrame) -> None:
    frame.attrs.pop(_CACHE_KEY, None)


def patch() -> None:
    global _PATCHED
    if _PATCHED:
        return
    base._first_quote_index = first_quote_index_cached
    _PATCHED = True
