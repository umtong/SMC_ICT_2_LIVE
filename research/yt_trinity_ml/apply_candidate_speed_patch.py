#!/usr/bin/env python3
"""Apply output-equivalent candidate-generation speed improvements."""
from pathlib import Path

PATH = Path("research/yt_trinity_ml/system/corpus_alpha.py")
source = PATH.read_text(encoding="utf-8")

old = '''def _last_level_origin_pos(
    features: pd.DataFrame,
    pos: int,
    value: float,
    side: int,
) -> int:
    """Locate the protected swing that owns a continuation OB search window."""

    segment = features.iloc[: pos + 1]
    series = segment["low"] if side > 0 else segment["high"]
    atr = float(features.iloc[pos]["atr"])
    tolerance = max(0.15 * atr, abs(float(value)) * 1e-8, 1e-12)
    matches = np.flatnonzero((series - float(value)).abs().le(tolerance).to_numpy())
    if len(matches):
        return int(matches[-1])
    return max(0, pos - 12)
'''
new = '''def _last_level_origin_pos(
    features: pd.DataFrame,
    pos: int,
    value: float,
    side: int,
) -> int:
    """Return the same last match without allocating a full-history mask each time."""

    column = "low" if side > 0 else "high"
    values = features[column].to_numpy(dtype=float, copy=False)
    atr = float(features.iloc[pos]["atr"])
    tolerance = max(0.15 * atr, abs(float(value)) * 1e-8, 1e-12)
    target = float(value)
    for candidate_pos in range(pos, -1, -1):
        observed = float(values[candidate_pos])
        if np.isfinite(observed) and abs(observed - target) <= tolerance:
            return candidate_pos
    return max(0, pos - 12)
'''
if old not in source:
    raise RuntimeError("origin-position implementation base mismatch")
source = source.replace(old, new)

old = '''def _new_reversal_states(
    features: pd.DataFrame,
    pos: int,
    consumed_high: set[tuple[str, float]],
    consumed_low: set[tuple[str, float]],
    config: CorpusAlphaConfig,
    diagnostics: Counter[str] | None = None,
) -> list[_NarrativeState]:
    row = features.iloc[pos]
    atr = float(row["atr"])
    buffer = config.sweep_buffer_atr * atr
    high_pools = _liquidity_pools(row, True, atr, config.liquidity_dedup_tolerance_atr)
    low_pools = _liquidity_pools(row, False, atr, config.liquidity_dedup_tolerance_atr)
'''
new = '''def _new_reversal_states(
    features: pd.DataFrame,
    pos: int,
    consumed_high: set[tuple[str, float]],
    consumed_low: set[tuple[str, float]],
    config: CorpusAlphaConfig,
    diagnostics: Counter[str] | None = None,
    *,
    high_pools: list[_LiquidityPool] | None = None,
    low_pools: list[_LiquidityPool] | None = None,
) -> list[_NarrativeState]:
    row = features.iloc[pos]
    atr = float(row["atr"])
    buffer = config.sweep_buffer_atr * atr
    if high_pools is None:
        high_pools = _liquidity_pools(row, True, atr, config.liquidity_dedup_tolerance_atr)
    if low_pools is None:
        low_pools = _liquidity_pools(row, False, atr, config.liquidity_dedup_tolerance_atr)
'''
if old not in source:
    raise RuntimeError("reversal-state implementation base mismatch")
source = source.replace(old, new)

old = '''def _new_continuation_state(
    features: pd.DataFrame,
    pos: int,
    side: int,
    consumed_high: set[tuple[str, float]],
    consumed_low: set[tuple[str, float]],
    config: CorpusAlphaConfig,
    diagnostics: Counter[str] | None = None,
) -> _NarrativeState | None:
'''
new = '''def _new_continuation_state(
    features: pd.DataFrame,
    pos: int,
    side: int,
    consumed_high: set[tuple[str, float]],
    consumed_low: set[tuple[str, float]],
    config: CorpusAlphaConfig,
    diagnostics: Counter[str] | None = None,
    *,
    high_pools: list[_LiquidityPool] | None = None,
    low_pools: list[_LiquidityPool] | None = None,
) -> _NarrativeState | None:
'''
if old not in source:
    raise RuntimeError("continuation-state signature base mismatch")
source = source.replace(old, new)

old = '''        high_pools = _liquidity_pools(row, True, float(row["atr"]), config.liquidity_dedup_tolerance_atr)
        target = _select_draw_target(high_pools, 1, float(row["high"]), float(row["low"]), consumed_high)
'''
new = '''        if high_pools is None:
            high_pools = _liquidity_pools(row, True, float(row["atr"]), config.liquidity_dedup_tolerance_atr)
        target = _select_draw_target(high_pools, 1, float(row["high"]), float(row["low"]), consumed_high)
'''
if old not in source:
    raise RuntimeError("continuation high-pool base mismatch")
source = source.replace(old, new)

old = '''        low_pools = _liquidity_pools(row, False, float(row["atr"]), config.liquidity_dedup_tolerance_atr)
        target = _select_draw_target(low_pools, -1, float(row["high"]), float(row["low"]), consumed_low)
'''
new = '''        if low_pools is None:
            low_pools = _liquidity_pools(row, False, float(row["atr"]), config.liquidity_dedup_tolerance_atr)
        target = _select_draw_target(low_pools, -1, float(row["high"]), float(row["low"]), consumed_low)
'''
if old not in source:
    raise RuntimeError("continuation low-pool base mismatch")
source = source.replace(old, new)

old = '''        new_reversals = _new_reversal_states(features, pos, consumed_high, consumed_low, config, diagnostics)
        continuation_long = _new_continuation_state(features, pos, 1, consumed_high, consumed_low, config, diagnostics)
        continuation_short = _new_continuation_state(features, pos, -1, consumed_high, consumed_low, config, diagnostics)
        states.extend(new_reversals)
        if continuation_long is not None:
            states.append(continuation_long)
        if continuation_short is not None:
            states.append(continuation_short)

        atr = float(row["atr"])
        high_pools = _liquidity_pools(row, True, atr, config.liquidity_dedup_tolerance_atr)
        low_pools = _liquidity_pools(row, False, atr, config.liquidity_dedup_tolerance_atr)
        _mark_consumed(row, high_pools, low_pools, consumed_high, consumed_low)
'''
new = '''        atr = float(row["atr"])
        high_pools = _liquidity_pools(row, True, atr, config.liquidity_dedup_tolerance_atr)
        low_pools = _liquidity_pools(row, False, atr, config.liquidity_dedup_tolerance_atr)
        new_reversals = _new_reversal_states(
            features,
            pos,
            consumed_high,
            consumed_low,
            config,
            diagnostics,
            high_pools=high_pools,
            low_pools=low_pools,
        )
        continuation_long = _new_continuation_state(
            features,
            pos,
            1,
            consumed_high,
            consumed_low,
            config,
            diagnostics,
            high_pools=high_pools,
            low_pools=low_pools,
        )
        continuation_short = _new_continuation_state(
            features,
            pos,
            -1,
            consumed_high,
            consumed_low,
            config,
            diagnostics,
            high_pools=high_pools,
            low_pools=low_pools,
        )
        states.extend(new_reversals)
        if continuation_long is not None:
            states.append(continuation_long)
        if continuation_short is not None:
            states.append(continuation_short)
        _mark_consumed(row, high_pools, low_pools, consumed_high, consumed_low)
'''
if old not in source:
    raise RuntimeError("candidate-loop implementation base mismatch")
source = source.replace(old, new)

PATH.write_text(source, encoding="utf-8")
