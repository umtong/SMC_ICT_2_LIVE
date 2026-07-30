from __future__ import annotations

import gc
import json
import pickle
import time
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor

from direct_core_common import (
    FEATURES, MODEL_DIR, OUT, OUTCOME_DIR, SCORE_DIR, STATE_DIR, SYMS,
    YEAR_BOUNDS, build_training_frame, side_feature_frame, ts_ms,
)


def empirical_cdf(sorted_values: np.ndarray, values: np.ndarray) -> np.ndarray:
    return np.searchsorted(sorted_values, values, side='right') / len(sorted_values)


def load_or_build_training(max_operation_year: int) -> pd.DataFrame:
    # A model used in year Y may only use outcomes resolved before Y. Load only
    # the calendar partitions that can possibly contribute to the requested
    # operation years, avoiding a needless full-history materialization during
    # the 2022/2023 preselection gate.
    max_sample_year = min(max_operation_year - 1, 2025)
    if max_sample_year <= 2023:
        p = OUT / 'training_samples_2021_2023.parquet'
        if p.exists():
            return pd.read_parquet(p)
        df = build_training_frame(range(2021, max_sample_year + 1))
        df.to_parquet(p, index=False, compression='zstd')
        return df
    p = OUT / 'training_samples_2021_2025.parquet'
    if p.exists():
        return pd.read_parquet(p)
    early = OUT / 'training_samples_2021_2023.parquet'
    parts = [pd.read_parquet(early)] if early.exists() else [build_training_frame([2021,2022,2023])]
    if max_sample_year >= 2024:
        parts.append(build_training_frame([2024]))
    if max_sample_year >= 2025:
        parts.append(build_training_frame([2025]))
    df = pd.concat(parts, ignore_index=True)
    df.to_parquet(p, index=False, compression='zstd')
    return df


def fit_year_model(operation_year: int, samples: pd.DataFrame, force: bool = False):
    mp = MODEL_DIR / f'direct_net_r_{operation_year}.pkl'
    cp = MODEL_DIR / f'direct_net_r_{operation_year}_train_pred.npy'
    sp = MODEL_DIR / f'direct_net_r_{operation_year}_stats.json'
    if mp.exists() and cp.exists() and sp.exists() and not force:
        with mp.open('rb') as fh:
            return pickle.load(fh), np.load(cp), json.loads(sp.read_text())
    cutoff = ts_ms(f'{operation_year}-01-01')
    train = samples[samples.exit_ms < cutoff].copy()
    x = train[FEATURES].astype('float32')
    y = train.net_r.to_numpy(dtype=np.float64)
    model = HistGradientBoostingRegressor(
        loss='squared_error', learning_rate=0.04, max_iter=160,
        max_leaf_nodes=7, min_samples_leaf=1000,
        l2_regularization=50, random_state=71,
    )
    t0 = time.time()
    model.fit(x, y)
    pred = model.predict(x)
    sec = time.time() - t0
    sorted_pred = np.sort(pred)
    stats = {
        'operation_year': operation_year,
        'cutoff_ms': cutoff,
        'n_train': int(len(train)),
        'fit_seconds': sec,
        'target_mean': float(y.mean()),
        'target_std': float(y.std()),
        'pred_mean': float(pred.mean()),
        'pred_std': float(pred.std()),
        'train_corr': float(np.corrcoef(pred, y)[0,1]),
        **{f'pred_q{int(q*10000):04d}': float(np.quantile(pred,q)) for q in (0.90,0.925,0.95,0.975,0.99,0.995)},
    }
    with mp.open('wb') as fh:
        pickle.dump(model, fh)
    np.save(cp, sorted_pred)
    sp.write_text(json.dumps(stats, indent=2))
    del x, train, pred
    gc.collect()
    return model, sorted_pred, stats


def score_year(operation_year: int, model, sorted_pred: np.ndarray,
               previous_model=None, previous_sorted=None, six_hour_lag: bool = False,
               force: bool = False) -> pd.DataFrame:
    p = SCORE_DIR / f'scores_outcomes_{operation_year}.parquet'
    if p.exists() and not force:
        return pd.read_parquet(p)
    rows = []
    lag_end = ts_ms(f'{operation_year}-01-01 06:00') if six_hour_lag else -1
    for sym in SYMS:
        states = pd.read_parquet(STATE_DIR / f'states_{operation_year}_{sym}.parquet')
        outcomes = pd.read_parquet(OUTCOME_DIR / f'outcomes_{operation_year}_{sym}.parquet')
        for side in (1,-1):
            x = side_feature_frame(states, side)
            u = model.predict(x)
            q = empirical_cdf(sorted_pred, u)
            if six_hour_lag and previous_model is not None:
                mask = states.decision_ms.to_numpy(dtype=np.int64) < lag_end
                if mask.any():
                    old_u = previous_model.predict(x.loc[mask])
                    u[mask] = old_u
                    q[mask] = empirical_cdf(previous_sorted, old_u)
            s = pd.DataFrame({
                'candidate_id': [f'{sym}:{int(t)}:{side}' for t in states.decision_ms],
                'decision_ms': states.decision_ms.astype('int64'),
                'symbol': sym, 'side': side,
                'u': u.astype('float32'), 'q': q.astype('float32'),
                'model_year': operation_year,
            })
            s = s.merge(outcomes, on=['candidate_id','decision_ms','symbol','side'], how='inner', suffixes=('','_out'))
            rows.append(s)
            del x, s
        del states, outcomes
        gc.collect()
    result = pd.concat(rows, ignore_index=True).sort_values(['decision_ms','symbol','side']).reset_index(drop=True)
    result.to_parquet(p, index=False, compression='zstd')
    return result


def main(years: list[int], force: bool = False):
    samples = load_or_build_training(max(years))
    models = {}
    cdfs = {}
    stats = []
    for y in years:
        model,cdf,st = fit_year_model(y,samples,force=force)
        models[y]=model;cdfs[y]=cdf;stats.append(st)
        prev = models.get(y-1)
        prevcdf = cdfs.get(y-1)
        six = y in (2025,2026)
        scored = score_year(y,model,cdf,prev,prevcdf,six_hour_lag=six,force=force)
        print('SCORED',y,len(scored),pd.to_datetime(scored.decision_ms.min(),unit='ms',utc=True),pd.to_datetime(scored.decision_ms.max(),unit='ms',utc=True),flush=True)
    pd.DataFrame(stats).to_csv(MODEL_DIR/'model_stats.csv',index=False)


if __name__ == '__main__':
    import argparse
    ap=argparse.ArgumentParser()
    ap.add_argument('years', nargs='+', type=int)
    ap.add_argument('--force', action='store_true')
    a=ap.parse_args()
    main(a.years,a.force)
