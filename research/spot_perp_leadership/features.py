from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Mapping

import numpy as np
import pandas as pd

from .data import PairMarket

@dataclass(frozen=True, slots=True)
class PairFeatures:
    perp_sigma: np.ndarray
    perp_atr: np.ndarray
    basis_z: np.ndarray
    basis_change_z: Mapping[int, np.ndarray]
    leadership: Mapping[int, np.ndarray]
    spot_ret: Mapping[int, np.ndarray]
    perp_ret: Mapping[int, np.ndarray]
    spot_retz: Mapping[int, np.ndarray]
    perp_retz: Mapping[int, np.ndarray]
    spot_tfi: Mapping[int, np.ndarray]
    perp_tfi: Mapping[int, np.ndarray]
    spot_to_perp_gap_z: Mapping[int, np.ndarray]
    perp_to_spot_gap_z: Mapping[int, np.ndarray]

def prior_z(values: np.ndarray, window: int, min_periods: int) -> np.ndarray:
    series = pd.Series(values)
    mean = series.rolling(window, min_periods=min_periods).mean().shift(1)
    std = series.rolling(window, min_periods=min_periods).std(ddof=0).shift(1)
    return ((series - mean) / std.replace(0, np.nan)).to_numpy(float)

def prior_beta(x_values: np.ndarray, y_values: np.ndarray, window: int, min_periods: int) -> np.ndarray:
    x, y = pd.Series(x_values), pd.Series(y_values)
    mx = x.rolling(window, min_periods=min_periods).mean().shift(1)
    my = y.rolling(window, min_periods=min_periods).mean().shift(1)
    covariance = (x * y).rolling(window, min_periods=min_periods).mean().shift(1) - mx * my
    variance = (x * x).rolling(window, min_periods=min_periods).mean().shift(1) - mx * mx
    return (covariance / variance.replace(0, np.nan)).to_numpy(float)

def prior_leadership(spot_one: np.ndarray, perp_one: np.ndarray, window: int) -> np.ndarray:
    minimum = window // 2
    spot, perp = pd.Series(spot_one), pd.Series(perp_one)
    spot_leads = spot.shift(1).rolling(window, min_periods=minimum).corr(perp).shift(1)
    perp_leads = perp.shift(1).rolling(window, min_periods=minimum).corr(spot).shift(1)
    return (spot_leads - perp_leads).to_numpy(float)

def make_features(market: PairMarket) -> PairFeatures:
    spot_log, perp_log = np.log(market.spot_close), np.log(market.perp_close)
    spot_one, perp_one = np.r_[np.nan, np.diff(spot_log)], np.r_[np.nan, np.diff(perp_log)]
    perp_sigma = pd.Series(perp_one).rolling(10_080, min_periods=4_320).std(ddof=0).shift(1).to_numpy()
    previous = np.r_[np.nan, market.perp_close[:-1]]
    true_range = np.maximum(
        market.perp_high - market.perp_low,
        np.maximum(abs(market.perp_high - previous), abs(market.perp_low - previous)),
    )
    perp_atr = pd.Series(true_range).rolling(60, min_periods=30).mean().shift(1).to_numpy()
    basis = perp_log - spot_log
    basis_z = prior_z(basis, 10_080, 4_320)
    leadership = {window: prior_leadership(spot_one, perp_one, window) for window in (2_880, 10_080)}
    spot_ret, perp_ret, spot_retz, perp_retz = {}, {}, {}, {}
    spot_tfi, perp_tfi, spot_gap, perp_gap, basis_change_z = {}, {}, {}, {}, {}
    spot_sigma = pd.Series(spot_one).rolling(10_080, min_periods=4_320).std(ddof=0).shift(1).to_numpy()
    spot_signed = 2 * market.spot_buy_quote - market.spot_quote
    perp_signed = 2 * market.perp_buy_quote - market.perp_quote
    for lag in (1, 3, 5, 15):
        sr = np.full_like(spot_log, np.nan)
        pr = np.full_like(perp_log, np.nan)
        sr[lag:] = spot_log[lag:] - spot_log[:-lag]
        pr[lag:] = perp_log[lag:] - perp_log[:-lag]
        spot_ret[lag], perp_ret[lag] = sr, pr
        spot_retz[lag] = sr / (spot_sigma * math.sqrt(lag))
        perp_retz[lag] = pr / (perp_sigma * math.sqrt(lag))
        spot_quote = pd.Series(market.spot_quote).rolling(lag, min_periods=lag).sum().to_numpy()
        perp_quote = pd.Series(market.perp_quote).rolling(lag, min_periods=lag).sum().to_numpy()
        spot_flow = pd.Series(spot_signed).rolling(lag, min_periods=lag).sum().to_numpy()
        perp_flow = pd.Series(perp_signed).rolling(lag, min_periods=lag).sum().to_numpy()
        spot_tfi[lag] = np.divide(spot_flow, spot_quote, out=np.full_like(spot_flow, np.nan), where=spot_quote > 0)
        perp_tfi[lag] = np.divide(perp_flow, perp_quote, out=np.full_like(perp_flow, np.nan), where=perp_quote > 0)
        spot_to_perp_beta = prior_beta(sr, pr, 10_080, 4_320)
        perp_to_spot_beta = prior_beta(pr, sr, 10_080, 4_320)
        perp_scale = perp_sigma * math.sqrt(lag)
        spot_scale = spot_sigma * math.sqrt(lag)
        spot_side = np.sign(spot_retz[lag])
        perp_side = np.sign(perp_retz[lag])
        spot_gap[lag] = np.divide(
            spot_side * (spot_to_perp_beta * sr - pr),
            perp_scale,
            out=np.full_like(pr, np.nan),
            where=perp_scale > 0,
        )
        perp_gap[lag] = np.divide(
            perp_side * (perp_to_spot_beta * pr - sr),
            spot_scale,
            out=np.full_like(sr, np.nan),
            where=spot_scale > 0,
        )
        basis_change = np.full_like(basis, np.nan)
        basis_change[lag:] = basis[lag:] - basis[:-lag]
        basis_change_z[lag] = prior_z(basis_change, 10_080, 4_320)
    return PairFeatures(
        perp_sigma, perp_atr, basis_z, basis_change_z, leadership,
        spot_ret, perp_ret, spot_retz, perp_retz, spot_tfi, perp_tfi,
        spot_gap, perp_gap,
    )
