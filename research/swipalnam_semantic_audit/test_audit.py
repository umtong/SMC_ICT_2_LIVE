import numpy as np
import pandas as pd

from research.swipalnam_semantic_audit.audit import make_zone


def test_disjoint_fvg_ob_union_contains_non_array_price():
    # Bullish OB [100, 101], bullish FVG [110, 111]. The audited implementation
    # promotes [100, 111] to the entry zone even though 105 belongs to neither.
    open_ = np.array([101.0])
    close = np.array([100.5])
    high = np.array([101.5])
    low = np.array([100.0])
    ob_low, ob_high, overlap, zone_low, zone_high = make_zone(
        open_, close, high, low, 1, 0, 110.0, 111.0, True
    )
    assert (ob_low, ob_high) == (100.0, 101.0)
    assert not overlap
    assert (zone_low, zone_high) == (100.0, 111.0)
    assert not (ob_low <= 105.0 <= ob_high)
    assert not (110.0 <= 105.0 <= 111.0)
    assert zone_low <= 105.0 <= zone_high


def test_missing_fvg_body_substitute_passes_zero_fvg_threshold():
    previous_high = 105.0
    current_low = 104.0
    gap = current_low - previous_high
    assert gap <= 0
    body_low, body_high = sorted((100.0, 110.0))
    fvg_atr = 0.0
    assert body_high > body_low
    assert fvg_atr >= 0.0
    assert not (gap > 0)


def test_missing_opposite_candle_has_fallback_index():
    opens = np.array([100.0, 101.0, 102.0])
    closes = np.array([101.0, 102.0, 104.0])
    displacement_i = 2
    ob_i = displacement_i - 1
    genuine = False
    for i in range(displacement_i - 1, max(-1, displacement_i - 10), -1):
        if closes[i] < opens[i]:
            ob_i = i
            genuine = True
            break
    assert not genuine
    assert ob_i == displacement_i - 1


def test_strict_contract_rejects_any_fallback():
    rows = pd.DataFrame(
        {
            "genuine_fvg": [True, False, True, True],
            "fvg_atr": [0.04, 0.0, 0.04, 0.04],
            "genuine_ob": [True, True, False, True],
            "fvg_ob_overlap": [True, True, True, False],
            "target_is_known": [True, True, True, True],
        }
    )
    strict = (
        rows.genuine_fvg
        & (rows.fvg_atr >= 0.03)
        & rows.genuine_ob
        & rows.fvg_ob_overlap
        & rows.target_is_known
    )
    assert strict.tolist() == [True, False, False, False]
