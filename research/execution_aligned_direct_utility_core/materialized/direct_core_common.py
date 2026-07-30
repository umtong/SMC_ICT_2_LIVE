from __future__ import annotations

import ctypes
import gc
import math
import os
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd

ROOT = Path(os.environ.get('DIRECT_CORE_DATA_ROOT','/mnt/data/smc_data')).expanduser().resolve()
OUT = Path(os.environ.get('DIRECT_CORE_OUTPUT_ROOT','/mnt/data/direct_core_work')).expanduser().resolve()
STATE_DIR = OUT / 'states'
OUTCOME_DIR = OUT / 'outcomes'
MODEL_DIR = OUT / 'models'
SCORE_DIR = OUT / 'scores'
RESULT_DIR = OUT / 'results'
for _p in (STATE_DIR, OUTCOME_DIR, MODEL_DIR, SCORE_DIR, RESULT_DIR):
    _p.mkdir(parents=True, exist_ok=True)

SYMS = ('BTCUSDT', 'ETHUSDT')
ALL_SEGS = (
    'PRE_2024_2021', 'PRE_2024_2022', 'PRE_2024_2023',
    '2024_H1', '2024_H2', '2025_H1', '2025_H2', '2026_H1',
)
YEAR_SEGMENTS = {
    2021: ('PRE_2024_2021',),
    2022: ('PRE_2024_2021', 'PRE_2024_2022'),
    2023: ('PRE_2024_2022', 'PRE_2024_2023'),
    2024: ('PRE_2024_2023', '2024_H1', '2024_H2'),
    2025: ('2024_H2', '2025_H1', '2025_H2'),
    2026: ('2025_H2', '2026_H1'),
}
YEAR_BOUNDS = {
    2021: ('2021-01-01', '2022-01-01'),
    2022: ('2022-01-01', '2023-01-01'),
    2023: ('2023-01-01', '2024-01-01'),
    2024: ('2024-01-01', '2025-01-01'),
    2025: ('2025-01-01', '2026-01-01'),
    2026: ('2026-01-01', '2026-07-01'),
}

TAKER = 0.00055
BASE_SLIP = 0.00020
BASE_COST_RT = 2 * (TAKER + BASE_SLIP)  # 15 bp before funding
STOP_MULT = 3.0
MIN_STOP_PCT = 0.003
TARGET_R = 1.5
MAX_RISK_PCT = 0.04
RISK_FRACTION = 0.005
NOTIONAL_CAP = 3.0
FEATURE_HISTORY = 2016  # seven days of 5-minute observations


def ts_ms(value: str | pd.Timestamp) -> int:
    return int(pd.Timestamp(value, tz='UTC').timestamp() * 1000)


def rolling_z(s: pd.Series, window: int, min_periods: int | None = None) -> pd.Series:
    if min_periods is None:
        min_periods = max(24, window // 4)
    m = s.rolling(window, min_periods=min_periods).mean()
    sd = s.rolling(window, min_periods=min_periods).std(ddof=0)
    return (s - m) / sd.replace(0, np.nan)


DIR_BASE = [
    'ret1','ret3','ret6','ret12','ret24','ret48','ret96','ret288','ret576',
    'oi1','oi3','oi12','oi48','oi96','oi288','oi1_z','oi3_z','oi12_z','oi48_z',
    'premium_close','prem_z','prem_z_slow','prem_delta_z','ratio_imb','ratio_z','ratio_z_slow',
    'body_atr','ema_dist12','ema_dist48','ema_dist144','ema_dist576',
    'dist_high12','dist_low12','dist_high48','dist_low48','dist_high96','dist_low96',
    'dist_high288','dist_low288','x_ret3','x_ret12','x_ret48','x_ret288',
    'x_oi3','x_oi12','x_oi48','x_prem_z','x_ratio_z',
    'div_ret3','div_ret12','div_ret48','div_oi12',
]
ABS_BASE = [
    'atr_pct','atr_z','range_atr','clv','vol_z','vol_z_slow',
    'eff12','eff48','eff96','eff288','range_pos12','range_pos48','range_pos96','range_pos288',
    'x_vol_z','x_atr_pct',
]
FEATURES = [f'side_{c}' for c in DIR_BASE] + ABS_BASE + [
    'hour_sin','hour_cos','dow_sin','dow_cos','side',
]


def _read_concat(sym: str, segs: Iterable[str], rel: str, columns: list[str] | None = None) -> pd.DataFrame:
    parts = [pd.read_parquet(ROOT / seg / sym / rel, columns=columns) for seg in segs]
    return pd.concat(parts, ignore_index=True)


def build_base_features(sym: str, segs: Iterable[str]) -> pd.DataFrame:
    """Build features on the full regular grid; missing observations are never compressed."""
    segs = tuple(segs)
    b = _read_concat(sym, segs, 'trade_bars/5m.parquet').sort_values('start_time_ms').drop_duplicates('start_time_ms')
    if len(b) > 1 and not b.start_time_ms.diff().dropna().eq(300_000).all():
        raise RuntimeError(f'{sym}: non-regular 5m grid')

    oi = _read_concat(sym, segs, 'streams/open_interest_5m.parquet').rename(columns={
        'timestamp_ms': 'start_time_ms', 'observed': 'oi_observed'
    }).sort_values('start_time_ms').drop_duplicates('start_time_ms')
    ar = _read_concat(sym, segs, 'streams/account_ratio_5m.parquet').rename(columns={
        'timestamp_ms': 'start_time_ms', 'observed': 'ar_observed'
    }).sort_values('start_time_ms').drop_duplicates('start_time_ms')
    p = _read_concat(sym, segs, 'streams/premium_index_1m.parquet')
    p['bucket'] = (p.start_time_ms // 300_000) * 300_000
    p['_obs'] = p.observed.astype('int8')
    p = p.groupby('bucket', sort=True).agg(
        premium_close=('close','last'), premium_mean=('close','mean'),
        premium_high=('high','max'), premium_low=('low','min'),
        premium_rows=('close','size'), premium_observed=('_obs','sum'),
    ).reset_index().rename(columns={'bucket':'start_time_ms'})

    d = (b.merge(oi[['start_time_ms','oi_observed','open_interest']], on='start_time_ms', how='left')
          .merge(ar[['start_time_ms','ar_observed','buy_ratio','sell_ratio']], on='start_time_ms', how='left')
          .merge(p, on='start_time_ms', how='left'))
    d = d.sort_values('start_time_ms').reset_index(drop=True)
    d['source_valid'] = (
        d.is_complete.fillna(False)
        & d.oi_observed.fillna(False)
        & d.ar_observed.fillna(False)
        & d.premium_rows.eq(5)
        & d.premium_observed.eq(5)
    )
    # Keep the regular rows, but null unavailable values so shifts/rolling windows do not bridge gaps.
    price_cols = ['open','high','low','close','volume','turnover']
    d.loc[~d.is_complete.fillna(False), price_cols] = np.nan
    d.loc[~d.oi_observed.fillna(False), 'open_interest'] = np.nan
    d.loc[~d.ar_observed.fillna(False), ['buy_ratio','sell_ratio']] = np.nan
    d.loc[~(d.premium_rows.eq(5) & d.premium_observed.eq(5)),
          ['premium_close','premium_mean','premium_high','premium_low']] = np.nan

    d['symbol'] = sym
    d['ts'] = pd.to_datetime(d.start_time_ms, unit='ms', utc=True)
    prev = d.close.shift(1)
    tr = np.maximum(d.high-d.low, np.maximum((d.high-prev).abs(), (d.low-prev).abs()))
    d['tr'] = tr
    d['atr24'] = tr.ewm(alpha=1/24, adjust=False, min_periods=24).mean()
    d['atr72'] = tr.ewm(alpha=1/72, adjust=False, min_periods=72).mean()
    d['atr_pct'] = d.atr24 / d.close
    d['atr_z'] = rolling_z(np.log(d.atr_pct), 288)
    d['ret1'] = np.log(d.close / d.close.shift(1))
    for n in (1,3,6,12,24,48,96,288,576):
        d[f'ret{n}'] = np.log(d.close / d.close.shift(n))
        d[f'oi{n}'] = np.log(d.open_interest / d.open_interest.shift(n))
    d['range_atr'] = (d.high-d.low) / d.atr24
    d['body_atr'] = (d.close-d.open) / d.atr24
    d['clv'] = (d.close-d.low) / (d.high-d.low).replace(0,np.nan)
    d['vol_z'] = rolling_z(np.log1p(d.turnover), 288)
    d['vol_z_slow'] = rolling_z(np.log1p(d.turnover), 2016)
    d['oi1_z'] = rolling_z(d.oi1, 288)
    d['oi3_z'] = rolling_z(d.oi3, 288)
    d['oi12_z'] = rolling_z(d.oi12, 288)
    d['oi48_z'] = rolling_z(d.oi48, 2016)
    d['prem_z'] = rolling_z(d.premium_close, 288)
    d['prem_z_slow'] = rolling_z(d.premium_close, 2016)
    d['prem_delta_z'] = rolling_z(d.premium_close-d.premium_close.shift(3), 288)
    d['ratio_imb'] = d.buy_ratio-d.sell_ratio
    d['ratio_z'] = rolling_z(d.ratio_imb, 288)
    d['ratio_z_slow'] = rolling_z(d.ratio_imb, 2016)
    for n in (12,48,96,288):
        hi = d.high.shift(1).rolling(n, min_periods=n).max()
        lo = d.low.shift(1).rolling(n, min_periods=n).min()
        d[f'range_pos{n}'] = (d.close-lo)/(hi-lo).replace(0,np.nan)
        d[f'dist_high{n}'] = (d.close-hi)/d.atr24
        d[f'dist_low{n}'] = (d.close-lo)/d.atr24
        d[f'eff{n}'] = (d.close-d.close.shift(n)).abs() / (
            d.high.rolling(n, min_periods=n).max()-d.low.rolling(n, min_periods=n).min()
        ).replace(0,np.nan)
    for span in (12,48,144,576):
        ema = d.close.ewm(span=span, adjust=False, min_periods=span).mean()
        d[f'ema_dist{span}'] = (d.close-ema)/d.atr24
    d['hour'] = d.ts.dt.hour + d.ts.dt.minute/60
    d['dow'] = d.ts.dt.dayofweek
    # Any unavailable core observation invalidates the next seven days of state history.
    bad = (~d.source_valid).astype('int8')
    d['history_valid'] = bad.rolling(FEATURE_HISTORY, min_periods=FEATURE_HISTORY).sum().eq(0)
    return d


def build_year_states(year: int, force: bool = False) -> dict[str, pd.DataFrame]:
    start, end = YEAR_BOUNDS[year]
    s0, s1 = ts_ms(start), ts_ms(end)
    outputs: dict[str, pd.DataFrame] = {}
    paths = {sym: STATE_DIR / f'states_{year}_{sym}.parquet' for sym in SYMS}
    if not force and all(p.exists() for p in paths.values()):
        return {sym: pd.read_parquet(p) for sym,p in paths.items()}

    bases = {sym: build_base_features(sym, YEAR_SEGMENTS[year]) for sym in SYMS}
    peer_cols = ['start_time_ms','ret3','ret12','ret48','ret288','oi3','oi12','oi48',
                 'premium_close','prem_z','ratio_z','vol_z','atr_pct','history_valid']
    for sym, peer in ((SYMS[0],SYMS[1]), (SYMS[1],SYMS[0])):
        d = bases[sym]
        p = bases[peer][peer_cols].rename(columns={
            c: ('x_'+c if c not in ('start_time_ms','history_valid') else ('peer_history_valid' if c=='history_valid' else c))
            for c in peer_cols
        })
        d = d.merge(p, on='start_time_ms', how='left')
        d['div_ret3'] = d.ret3-d.x_ret3
        d['div_ret12'] = d.ret12-d.x_ret12
        d['div_ret48'] = d.ret48-d.x_ret48
        d['div_oi12'] = d.oi12-d.x_oi12
        decision_clock = d.start_time_ms.astype('int64') + 300_000
        keep = (decision_clock >= s0) & (decision_clock < s1)
        cols = ['start_time_ms','symbol','close','atr24','hour','dow','history_valid','peer_history_valid'] + DIR_BASE + ABS_BASE
        z = d.loc[keep, cols].copy()
        feature_finite = np.isfinite(z[DIR_BASE+ABS_BASE].to_numpy(dtype='float64')).all(axis=1)
        z['state_valid'] = z.history_valid.fillna(False) & z.peer_history_valid.fillna(False) & feature_finite
        z['decision_ms'] = z.start_time_ms.astype('int64') + 300_000
        z['bar_number'] = (z.start_time_ms // 300_000).astype('int64')
        z = z[z.state_valid].drop(columns=['history_valid','peer_history_valid','state_valid']).reset_index(drop=True)
        # Store compact numeric types.
        for c in DIR_BASE+ABS_BASE+['close','atr24','hour','dow']:
            z[c] = z[c].astype('float32')
        z.to_parquet(paths[sym], index=False, compression='zstd')
        outputs[sym] = z
    del bases
    gc.collect()
    return outputs


def side_feature_frame(states: pd.DataFrame, side: int) -> pd.DataFrame:
    x = pd.DataFrame(index=np.arange(len(states)))
    for c in DIR_BASE:
        x[f'side_{c}'] = (side * states[c].to_numpy(dtype='float32')).astype('float32')
    for c in ABS_BASE:
        x[c] = states[c].to_numpy(dtype='float32')
    hour = states.hour.to_numpy(dtype='float32')
    dow = states.dow.to_numpy(dtype='float32')
    x['hour_sin'] = np.sin(2*np.pi*hour/24).astype('float32')
    x['hour_cos'] = np.cos(2*np.pi*hour/24).astype('float32')
    x['dow_sin'] = np.sin(2*np.pi*dow/7).astype('float32')
    x['dow_cos'] = np.cos(2*np.pi*dow/7).astype('float32')
    x['side'] = np.float32(side)
    return x[FEATURES]


class FirstHit:
    def __init__(self) -> None:
        lib = ctypes.CDLL(str(OUT / 'libfirst_hit.so'))
        fn = lib.first_hit_many
        fn.argtypes = [
            ctypes.POINTER(ctypes.c_double), ctypes.POINTER(ctypes.c_double), ctypes.c_int64,
            ctypes.POINTER(ctypes.c_int64), ctypes.POINTER(ctypes.c_double), ctypes.POINTER(ctypes.c_double),
            ctypes.POINTER(ctypes.c_int8), ctypes.c_int64, ctypes.c_int64,
            ctypes.POINTER(ctypes.c_int64), ctypes.POINTER(ctypes.c_int8),
        ]
        fn.restype = None
        self.fn = fn

    def __call__(self, high: np.ndarray, low: np.ndarray, entry_idx: np.ndarray,
                 stop: np.ndarray, target: np.ndarray, side: np.ndarray,
                 max_scan: int = 0) -> tuple[np.ndarray,np.ndarray]:
        high = np.ascontiguousarray(high, dtype=np.float64)
        low = np.ascontiguousarray(low, dtype=np.float64)
        entry_idx = np.ascontiguousarray(entry_idx, dtype=np.int64)
        stop = np.ascontiguousarray(stop, dtype=np.float64)
        target = np.ascontiguousarray(target, dtype=np.float64)
        side = np.ascontiguousarray(side, dtype=np.int8)
        exit_idx = np.full(len(entry_idx), -1, dtype=np.int64)
        outcome = np.zeros(len(entry_idx), dtype=np.int8)
        self.fn(
            high.ctypes.data_as(ctypes.POINTER(ctypes.c_double)),
            low.ctypes.data_as(ctypes.POINTER(ctypes.c_double)), ctypes.c_int64(len(high)),
            entry_idx.ctypes.data_as(ctypes.POINTER(ctypes.c_int64)),
            stop.ctypes.data_as(ctypes.POINTER(ctypes.c_double)),
            target.ctypes.data_as(ctypes.POINTER(ctypes.c_double)),
            side.ctypes.data_as(ctypes.POINTER(ctypes.c_int8)), ctypes.c_int64(len(entry_idx)),
            ctypes.c_int64(max_scan),
            exit_idx.ctypes.data_as(ctypes.POINTER(ctypes.c_int64)),
            outcome.ctypes.data_as(ctypes.POINTER(ctypes.c_int8)),
        )
        return exit_idx, outcome


def load_minute_market(sym: str, segs: Iterable[str] = ALL_SEGS) -> pd.DataFrame:
    t = _read_concat(sym, segs, 'streams/trade_price_1m.parquet').sort_values('start_time_ms').drop_duplicates('start_time_ms')
    m = _read_concat(sym, segs, 'streams/mark_price_1m.parquet', columns=['start_time_ms','observed','open','close'])
    m = m.sort_values('start_time_ms').drop_duplicates('start_time_ms').rename(columns={
        'observed':'mark_observed','open':'mark_open','close':'mark_close'
    })
    t = t.rename(columns={'observed':'trade_observed'}).merge(m, on='start_time_ms', how='left')
    t = t.sort_values('start_time_ms').reset_index(drop=True)
    if len(t)>1 and not t.start_time_ms.diff().dropna().eq(60_000).all():
        raise RuntimeError(f'{sym}: non-regular 1m grid')
    return t


def load_funding(sym: str, segs: Iterable[str] = ALL_SEGS) -> pd.DataFrame:
    return _read_concat(sym, segs, 'streams/funding_events.parquet').sort_values('timestamp_ms').drop_duplicates('timestamp_ms')


def funding_prefix_long(market: pd.DataFrame, funding: pd.DataFrame) -> np.ndarray:
    times = market.start_time_ms.to_numpy(dtype=np.int64)
    mark = market.mark_open.to_numpy(dtype=np.float64)
    flow = np.zeros(len(market), dtype=np.float64)
    idx = np.searchsorted(times, funding.timestamp_ms.to_numpy(dtype=np.int64))
    fts = funding.timestamp_ms.to_numpy(dtype=np.int64)
    rates_all = funding.funding_rate.to_numpy(dtype=np.float64)
    ok = (idx < len(times)) & (times[np.minimum(idx, len(times)-1)] == fts)
    ok &= np.isfinite(mark[np.minimum(idx, len(mark)-1)]) & np.isfinite(rates_all)
    idx = idx[ok]
    rates = rates_all[ok]
    flow[idx] += -mark[idx] * rates  # long pays positive funding
    return np.cumsum(flow)


def funding_between(prefix_long: np.ndarray, entry_idx: np.ndarray, exit_idx: np.ndarray, side: np.ndarray) -> np.ndarray:
    # Funding at the entry timestamp occurs before entry and is excluded; funding at exit-minute start is included.
    base = prefix_long[exit_idx] - prefix_long[entry_idx]
    return side.astype(np.float64) * base


def build_year_outcomes(year: int, sym: str, market: pd.DataFrame, fund_prefix: np.ndarray,
                        force: bool = False) -> pd.DataFrame:
    path = OUTCOME_DIR / f'outcomes_{year}_{sym}.parquet'
    if path.exists() and not force:
        return pd.read_parquet(path)
    states = pd.read_parquet(STATE_DIR / f'states_{year}_{sym}.parquet')
    mt = market.start_time_ms.to_numpy(dtype=np.int64)
    observed = market.trade_observed.fillna(False).to_numpy(bool)
    raw_open = market.open.to_numpy(dtype=np.float64)
    hi = market.high.to_numpy(dtype=np.float64)
    lo = market.low.to_numpy(dtype=np.float64)
    all_rows = []
    fh = FirstHit()
    for side in (1,-1):
        entry_ms = states.decision_ms.to_numpy(dtype=np.int64) + 60_000
        eidx = np.searchsorted(mt, entry_ms)
        valid = (eidx < len(mt)) & (mt[np.minimum(eidx,len(mt)-1)] == entry_ms)
        valid &= observed[np.minimum(eidx,len(mt)-1)]
        s = states.loc[valid].reset_index(drop=True)
        eidx = eidx[valid]
        eraw = raw_open[eidx]
        efill = eraw * (1 + side * BASE_SLIP)
        dist = np.maximum(STOP_MULT * s.atr24.to_numpy(dtype=np.float64), MIN_STOP_PCT * efill)
        risk_pct = dist / efill
        valid2 = np.isfinite(dist) & (dist > 0) & (risk_pct <= MAX_RISK_PCT)
        s = s.loc[valid2].reset_index(drop=True)
        eidx = eidx[valid2]
        eraw = eraw[valid2]
        efill = efill[valid2]
        dist = dist[valid2]
        risk_pct = risk_pct[valid2]
        stop = efill - side * dist
        target = efill + side * TARGET_R * dist
        sides = np.full(len(s), side, dtype=np.int8)
        xidx, hit = fh(hi, lo, eidx, stop, target, sides, max_scan=0)
        resolved = xidx >= 0
        stop_fill = stop * (1 - side * BASE_SLIP)
        target_fill = target * (1 - side * BASE_SLIP)
        exit_raw = np.where(hit < 0, stop, np.where(hit > 0, target, np.nan))
        exit_fill = np.where(hit < 0, stop_fill, np.where(hit > 0, target_fill, np.nan))
        unit_loss = np.abs(efill - stop_fill) + efill * TAKER + stop_fill * TAKER
        fund_unit = np.full(len(s), np.nan, dtype=np.float64)
        fund_unit[resolved] = funding_between(fund_prefix, eidx[resolved], xidx[resolved], sides[resolved])
        price_pnl_unit = side * (exit_fill - efill)
        net_unit = price_pnl_unit - efill * TAKER - exit_fill * TAKER + fund_unit
        net_r = net_unit / unit_loss
        exit_ms = np.full(len(s), -1, dtype=np.int64)
        exit_ms[resolved] = mt[xidx[resolved]]
        duration_min = np.full(len(s), -1, dtype=np.int32)
        duration_min[resolved] = (xidx[resolved] - eidx[resolved] + 1).astype(np.int32)
        out = pd.DataFrame({
            'candidate_id': [f'{sym}:{int(t)}:{side}' for t in s.decision_ms],
            'year': year, 'symbol': sym,
            'decision_ms': s.decision_ms.to_numpy(dtype=np.int64),
            'entry_ms': mt[eidx], 'exit_ms': exit_ms, 'side': side,
            'entry_raw': eraw, 'entry_fill_base': efill,
            'atr': s.atr24.to_numpy(dtype=np.float64),
            'stop_raw': stop, 'target_raw': target,
            'outcome': hit, 'resolved': resolved,
            'exit_raw': exit_raw, 'exit_fill_base': exit_fill,
            'funding_unit': fund_unit,
            'price_pnl_unit_base': price_pnl_unit,
            'unit_loss_base': unit_loss, 'net_unit_base': net_unit, 'net_r_base': net_r,
            'risk_pct': risk_pct, 'duration_min': duration_min,
            'bar_number': s.bar_number.to_numpy(dtype=np.int64),
        })
        sym_offset = 0 if sym == 'BTCUSDT' else 1
        side_offset = 0 if side == 1 else 2
        out['train_sample'] = ((out.bar_number + sym_offset + side_offset) % 3 == 0)
        all_rows.append(out)
    result = pd.concat(all_rows, ignore_index=True).sort_values(['decision_ms','side']).reset_index(drop=True)
    result.to_parquet(path, index=False, compression='zstd')
    return result


def build_training_frame(years: Iterable[int]) -> pd.DataFrame:
    frames = []
    for year in years:
        for sym in SYMS:
            states = pd.read_parquet(STATE_DIR / f'states_{year}_{sym}.parquet')
            outcomes = pd.read_parquet(OUTCOME_DIR / f'outcomes_{year}_{sym}.parquet')
            outcomes = outcomes[outcomes.train_sample & outcomes.resolved]
            # Join state values once, then expand directional features according to outcome side.
            m = outcomes.merge(states, on=['decision_ms','symbol','bar_number'], how='inner', suffixes=('','_state'))
            side = m.side.to_numpy(dtype=np.float32)
            x = pd.DataFrame({
                'candidate_id': m.candidate_id,
                'decision_ms': m.decision_ms.astype('int64'),
                'entry_ms': m.entry_ms.astype('int64'),
                'exit_ms': m.exit_ms.astype('int64'),
                'symbol': m.symbol,
                'side': m.side.astype('int8'),
                'net_r': m.net_r_base.astype('float32'),
                'duration_min': m.duration_min.astype('int32'),
            })
            for c in DIR_BASE:
                x[f'side_{c}'] = (side * m[c].to_numpy(dtype=np.float32)).astype('float32')
            for c in ABS_BASE:
                x[c] = m[c].to_numpy(dtype=np.float32)
            hour = m.hour.to_numpy(dtype=np.float32)
            dow = m.dow.to_numpy(dtype=np.float32)
            x['hour_sin'] = np.sin(2*np.pi*hour/24).astype('float32')
            x['hour_cos'] = np.cos(2*np.pi*hour/24).astype('float32')
            x['dow_sin'] = np.sin(2*np.pi*dow/7).astype('float32')
            x['dow_cos'] = np.cos(2*np.pi*dow/7).astype('float32')
            # side already exists in the metadata and is also the feature.
            frames.append(x)
    return pd.concat(frames, ignore_index=True).sort_values('decision_ms').reset_index(drop=True)
