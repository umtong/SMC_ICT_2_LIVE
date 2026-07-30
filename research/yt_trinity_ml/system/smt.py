from __future__ import annotations

from typing import Mapping

import numpy as np
import pandas as pd


def _finite_frame(frame: pd.DataFrame) -> pd.DataFrame:
    required = {'high', 'low', 'close', 'last_swing_high', 'last_swing_low'}
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f'SMT frame missing columns: {sorted(missing)}')
    if not isinstance(frame.index, pd.DatetimeIndex) or frame.index.tz is None:
        raise ValueError('SMT frame requires timezone-aware decision index')
    return frame.sort_index().copy()


def add_pair_smt_features(features_by_symbol: Mapping[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    """Add causal same-decision-time BTC/ETH SMT features.

    Both inputs are completed decision bars indexed by their information-availability
    time. Exact timestamp alignment is used; no future peer bar is carried backward.
    A self-took flag means this instrument violated its confirmed swing while the
    peer did not violate its own corresponding confirmed swing.
    """

    result = {symbol: _finite_frame(frame) for symbol, frame in features_by_symbol.items()}
    if not {'BTCUSDT', 'ETHUSDT'}.issubset(result):
        for frame in result.values():
            for name in (
                'smt_self_took_high', 'smt_peer_took_high', 'smt_self_took_low',
                'smt_peer_took_low', 'smt_high_divergence', 'smt_low_divergence',
                'smt_relative_return_1', 'smt_relative_return_3', 'smt_relative_return_12',
            ):
                frame[name] = 0.0
        return result

    btc = result['BTCUSDT']
    eth = result['ETHUSDT']
    common = btc.index.intersection(eth.index)
    if common.empty:
        raise RuntimeError('BTC and ETH have no common causal decision timestamps')

    def flags(frame: pd.DataFrame) -> pd.DataFrame:
        out = pd.DataFrame(index=frame.index)
        out['take_high'] = (
            frame['last_swing_high'].notna() & (frame['high'] > frame['last_swing_high'])
        ).astype(float)
        out['take_low'] = (
            frame['last_swing_low'].notna() & (frame['low'] < frame['last_swing_low'])
        ).astype(float)
        for window in (1, 3, 12):
            out[f'return_{window}'] = np.log(frame['close'] / frame['close'].shift(window))
        return out

    btc_flags = flags(btc).loc[common]
    eth_flags = flags(eth).loc[common]

    def attach(symbol: str, peer: str, own: pd.DataFrame, other: pd.DataFrame) -> None:
        frame = result[symbol]
        aligned = pd.DataFrame(index=common)
        aligned['smt_self_took_high'] = ((own['take_high'] == 1) & (other['take_high'] == 0)).astype(float)
        aligned['smt_peer_took_high'] = ((own['take_high'] == 0) & (other['take_high'] == 1)).astype(float)
        aligned['smt_self_took_low'] = ((own['take_low'] == 1) & (other['take_low'] == 0)).astype(float)
        aligned['smt_peer_took_low'] = ((own['take_low'] == 0) & (other['take_low'] == 1)).astype(float)
        aligned['smt_high_divergence'] = (own['take_high'] != other['take_high']).astype(float)
        aligned['smt_low_divergence'] = (own['take_low'] != other['take_low']).astype(float)
        for window in (1, 3, 12):
            aligned[f'smt_relative_return_{window}'] = own[f'return_{window}'] - other[f'return_{window}']
        aligned['smt_peer_is_eth'] = float(peer == 'ETHUSDT')
        aligned['smt_peer_is_btc'] = float(peer == 'BTCUSDT')
        for name in aligned.columns:
            frame[name] = aligned[name].reindex(frame.index).fillna(0.0)

    attach('BTCUSDT', 'ETHUSDT', btc_flags, eth_flags)
    attach('ETHUSDT', 'BTCUSDT', eth_flags, btc_flags)
    return result
