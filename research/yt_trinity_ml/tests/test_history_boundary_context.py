from __future__ import annotations
import numpy as np
import pandas as pd
from system.core import FeatureConfig
from system.corpus_alpha import build_corpus_features

def test_pre2024_rows_carry_completed_day_context_into_h1() -> None:
    index = pd.date_range('2023-12-30T00:00:00Z', '2024-01-02T00:00:00Z', freq='5min', inclusive='left')
    base = 100.0 + np.linspace(0.0, 5.0, len(index))
    frame = pd.DataFrame({
        'open': base,
        'high': base + 1.0,
        'low': base - 1.0,
        'close': base + 0.2,
        'volume': np.full(len(index), 100.0),
    }, index=index)
    config = FeatureConfig(atr_window=5, fast_ema=5, slow_ema=8, long_ema=13, volume_window=5)
    full = build_corpus_features(frame, config)
    h1_only = build_corpus_features(frame.loc[frame.index >= pd.Timestamp('2024-01-01T00:00:00Z')], config)
    first_h1 = pd.Timestamp('2024-01-01T00:00:00Z')
    assert pd.notna(full.loc[first_h1, 'previous_day_high'])
    assert pd.isna(h1_only.loc[first_h1, 'previous_day_high'])
    assert pd.notna(full.loc[first_h1, 'ema_slow'])
