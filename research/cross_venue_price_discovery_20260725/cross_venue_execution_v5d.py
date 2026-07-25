from __future__ import annotations

import math
from dataclasses import asdict
from typing import Iterable

import numpy as np
import pandas as pd

import cross_venue_development_v2 as d2
import cross_venue_execution_v5 as base
import cross_venue_execution_v5c as v5c
import cross_venue_pilot as v1
import cross_venue_signals_v5d as signals

CAUSAL_VERSION = base.CAUSAL_VERSION
ENGINE_VERSION = "5D"
BUCKET_US = base.BUCKET_US
MAX_EXECUTION_DELAY_US = v1.MAX_QUOTE_AGE_MS * 1_000
EntryCandidateV5 = base.EntryCandidateV5
ExitResolutionV5 = base.ExitResolutionV5
FixedTradeV5 = base.FixedTradeV5
AccountTradeV5 = base.AccountTradeV5

_V5C_RESOLVE_EXIT = None
_PATCHED = False
_NUMERICAL_PRICE_FLOOR = np.finfo(float).tiny


def _mandatory_exit_without_economic_floor(
    quote: dict[str, float],
    side: int,
    quantity: float,
) -> tuple[float, bool]:
    reference = quote["bid"] if side > 0 else quote["ask"]
    available = quote["bid_amount"] if side > 0 else quote["ask_amount"]
    spread = quote["ask"] - quote["bid"]
    values = (reference, available, spread, quantity)
    if not all(math.isfinite(float(value)) for value in values):
        raise ValueError("unusable V5D exit quote")
    if quantity <= 0 or reference <= 0 or available <= 0 or spread <= 0:
        raise ValueError("unusable V5D exit quote")
    participation = quantity / available
    normalized = participation / d2.MAX_TOP_QUOTE_PARTICIPATION
    impact_spreads = 0.25 * min(normalized, 1.0) + 2.0 * max(normalized - 1.0, 0.0)
    impact = spread * impact_spreads
    if side > 0:
        price = max(_NUMERICAL_PRICE_FLOOR, reference - impact)
    else:
        price = reference + impact
    if not math.isfinite(price) or price <= 0:
        raise ValueError("V5D exit impact produced a non-positive or non-finite price")
    return price, participation > d2.MAX_TOP_QUOTE_PARTICIPATION


def _validate_regular_grid(frame: pd.DataFrame) -> None:
    index = frame.index.to_numpy(np.int64)
    if len(index) < 2 or np.any(np.diff(index) != v1.BUCKET_MS):
        raise ValueError("V5D execution frame must preserve the complete 100-ms wall-clock grid")


def _validate_observed_position_path(
    frame: pd.DataFrame,
    candidate: EntryCandidateV5,
    result: ExitResolutionV5,
    config: v1.Config,
) -> None:
    _validate_regular_grid(frame)
    entry_target_us = (candidate.event.decision_ms + config.latency_ms) * 1_000
    entry_delay = candidate.entry_us - entry_target_us
    exit_target_us = result.trigger_boundary_us + config.latency_ms * 1_000
    exit_delay = result.exit_us - exit_target_us
    if entry_delay < 0 or entry_delay > MAX_EXECUTION_DELAY_US:
        raise ValueError("V5D accepted entry exceeded the maximum observable quote delay")
    if exit_delay < 0 or exit_delay > MAX_EXECUTION_DELAY_US:
        raise ValueError("V5D accepted exit exceeded the maximum observable quote delay")
    if result.exit_position < candidate.entry_position:
        raise ValueError("V5D exit precedes entry")
    window = frame.iloc[candidate.entry_position : result.exit_position + 1]
    columns = ["bn_mid", "bb_mid", "bn_spread", "bb_spread"]
    values = window[columns].apply(pd.to_numeric, errors="coerce")
    array = values.to_numpy(float)
    if not np.isfinite(array).all():
        raise ValueError("V5D accepted position crossed unavailable Binance/Bybit state")
    if (
        (values["bn_mid"] <= 0).any()
        or (values["bb_mid"] <= 0).any()
        or (values["bn_spread"] <= 0).any()
        or (values["bb_spread"] <= 0).any()
    ):
        raise ValueError("V5D accepted position crossed invalid Binance/Bybit state")


def _resolve_exit_v5d(
    frame: pd.DataFrame,
    candidate: EntryCandidateV5,
    config: v1.Config,
    quantity: float,
    entry_price: float,
    stop_mid: float,
    fee_bps: float,
    nav: float,
    account_peak: float,
) -> ExitResolutionV5:
    if _V5C_RESOLVE_EXIT is None:
        raise RuntimeError("V5D exit contract was not patched")
    result = _V5C_RESOLVE_EXIT(
        frame,
        candidate,
        config,
        quantity,
        entry_price,
        stop_mid,
        fee_bps,
        nav,
        account_peak,
    )
    _validate_observed_position_path(frame, candidate, result, config)
    return result


def _compound(values: Iterable[float]) -> float:
    array = np.asarray(list(values), dtype=float)
    if not len(array):
        return 0.0
    if np.any(~np.isfinite(array)):
        return -1.0
    if np.any(array <= -1.0):
        return -1.0
    return float(np.prod(1.0 + array) - 1.0)


def _daily_returns_from_nav(frame: pd.DataFrame, days: list[str]) -> pd.Series:
    values: dict[str, float] = {}
    for day, group in frame.groupby("day", sort=False):
        start = float(group.iloc[0].nav_before)
        finish = max(0.0, float(group.iloc[-1].nav_after))
        values[str(day)] = -1.0 if start <= 0 else finish / start - 1.0
    return pd.Series(values, dtype=float).reindex(days, fill_value=0.0)


def account_metrics_v5d(
    trades: list[AccountTradeV5],
    state: dict[str, float],
    days: Iterable[str],
) -> dict:
    day_list = list(days)
    terminal = float(state.get("nav", d2.INITIAL_NAV)) <= 0
    if not trades:
        return {
            "n": 0,
            "eligible_days": len(day_list),
            "trades_per_day_median": 0.0,
            "positive_day_fraction": 0.0,
            "total_return": -1.0 if terminal else 0.0,
            "geometric_sample_day_return": -1.0 if terminal else 0.0,
            "profit_factor": None,
            "maximum_drawdown": 1.0 if terminal else float(state.get("maximum_drawdown", 0.0)),
            "closed_path_drawdown": 1.0 if terminal else 0.0,
            "conservative_combined_drawdown": 1.0 if terminal else float(state.get("maximum_drawdown", 0.0)),
            "top10pct_removed_return": None,
            "top10_counterfactual_status": "NOT_RUN",
            "top5_positive_share": 1.0,
            "return_2022": -1.0 if terminal else 0.0,
            "return_2023": -1.0 if terminal else 0.0,
            "maximum_single_symbol_positive_pnl_share": 1.0,
            "exit_liquidity_overrun_count": 0,
            "maximum_intratrade_drawdown": 1.0 if terminal else 0.0,
            "ending_nav": max(0.0, float(state.get("nav", d2.INITIAL_NAV))),
            "terminal_account_loss": terminal,
        }

    frame = pd.DataFrame([asdict(item) for item in trades])
    terminal = terminal or bool((frame.nav_after <= 0).any())
    daily = _daily_returns_from_nav(frame, day_list)
    positive = frame.loc[frame.net_pnl > 0, "net_pnl"].to_numpy(float)
    negative = frame.loc[frame.net_pnl < 0, "net_pnl"].to_numpy(float)
    positive_sum = float(positive.sum())
    counts = frame.groupby("day").size().reindex(day_list, fill_value=0)
    nav_path = np.r_[d2.INITIAL_NAV, np.maximum(frame.nav_after.to_numpy(float), 0.0)]
    nav_peak = np.maximum.accumulate(nav_path)
    closed_drawdown = float(np.max(1.0 - nav_path / np.maximum(nav_peak, 1e-12)))
    maximum_intratrade = float(frame.maximum_intratrade_drawdown.max())
    maximum_drawdown = max(float(state.get("maximum_drawdown", 0.0)), closed_drawdown)
    if terminal:
        maximum_drawdown = 1.0
    by_symbol = frame.groupby("symbol").net_pnl.sum()
    positive_symbol = by_symbol.clip(lower=0.0)
    symbol_denominator = float(positive_symbol.sum())
    year_returns: dict[int, float] = {}
    for year in (2022, 2023):
        selected = daily.loc[[day.startswith(str(year)) for day in daily.index]].to_numpy(float)
        year_returns[year] = _compound(selected)
    geometric = -1.0 if np.any(daily.to_numpy(float) <= -1.0) else float(
        np.expm1(np.log1p(daily.to_numpy(float)).mean())
    )
    ending_nav = max(0.0, float(state.get("nav", d2.INITIAL_NAV)))
    return {
        "n": int(len(frame)),
        "eligible_days": len(day_list),
        "trades_per_day_median": float(counts.median()),
        "positive_day_fraction": float((daily > 0).mean()),
        "total_return": ending_nav / d2.INITIAL_NAV - 1.0,
        "geometric_sample_day_return": geometric,
        "profit_factor": float(positive.sum() / -negative.sum()) if len(negative) else None,
        "maximum_drawdown": maximum_drawdown,
        "closed_path_drawdown": closed_drawdown,
        "conservative_combined_drawdown": maximum_drawdown,
        "top10pct_removed_return": None,
        "top10_counterfactual_status": "NOT_RUN",
        "top5_positive_share": float(np.sort(positive)[-5:].sum() / positive_sum) if positive_sum > 0 else 1.0,
        "return_2022": year_returns[2022],
        "return_2023": year_returns[2023],
        "maximum_single_symbol_positive_pnl_share": (
            float(positive_symbol.max() / symbol_denominator) if symbol_denominator > 0 else 1.0
        ),
        "symbol_net_pnl": by_symbol.to_dict(),
        "symbol_positive_pnl": positive_symbol.to_dict(),
        "day_returns": daily.to_dict(),
        "exit_liquidity_overrun_count": int(frame.exit_liquidity_overrun.sum()),
        "maximum_intratrade_drawdown": maximum_intratrade,
        "ending_nav": ending_nav,
        "terminal_account_loss": terminal,
    }


def patch_v5() -> None:
    global _PATCHED, _V5C_RESOLVE_EXIT
    v5c.patch_v5()
    signals.patch()
    if _PATCHED:
        return
    _V5C_RESOLVE_EXIT = base._resolve_exit
    base._mandatory_exit = _mandatory_exit_without_economic_floor
    base._resolve_exit = _resolve_exit_v5d
    base.account_metrics_v5 = account_metrics_v5d
    _PATCHED = True


def timestamp_us(raw: str) -> int:
    return base.timestamp_us(raw)


def read_quotes_v5(path):
    return base.read_quotes_v5(path)


def align_v5(*args, **kwargs):
    return base.align_v5(*args, **kwargs)


def simulate_fixed_day_v5(*args, **kwargs):
    patch_v5()
    return base.simulate_fixed_day_v5(*args, **kwargs)


def apply_fixed_fee(*args, **kwargs):
    return base.apply_fixed_fee(*args, **kwargs)


def initial_account_state():
    return base.initial_account_state()


def simulate_account_day_v5(*args, **kwargs):
    patch_v5()
    return base.simulate_account_day_v5(*args, **kwargs)


def account_metrics_v5(*args, **kwargs):
    patch_v5()
    return base.account_metrics_v5(*args, **kwargs)
