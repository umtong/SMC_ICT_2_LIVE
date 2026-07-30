"""Causal, transcript-grounded SMC/ICT candidate generation and ML evaluation.

The system deliberately separates three layers:

1. deterministic SMC/ICT event semantics create candidates only after
   liquidity sweep/reclaim, displacement, and a confirmed structure break;
2. machine learning ranks those already-valid candidates using only features
   available at the signal timestamp;
3. a single-slot event simulator applies 500 ms latency, realistic fees,
   slippage/impact, funding, risk-based sizing, leverage/liquidation checks,
   and continuous UTC-day NAV accounting.

No timeout exit exists. Pending orders cancel only when the setup is logically
invalidated or its objective is delivered without a fill. Open positions exit
only at their stop or opposing-liquidity objective; positions still open at an
evaluation boundary are marked to a conservative immediate-close value.
"""
from __future__ import annotations

import dataclasses
import json
import math
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping, MutableMapping, Sequence

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor

MS_MINUTE = 60_000
MS_5MIN = 5 * MS_MINUTE
UTC = "UTC"


@dataclass(frozen=True)
class StructuralConfig:
    """SMC/ICT semantics fixed before an evaluation interval."""

    pivot_left: int = 3
    pivot_right: int = 3
    atr_period: int = 14
    volume_z_window: int = 96
    equal_level_tolerance_atr: float = 0.12
    sweep_min_depth_atr: float = 0.025
    sweep_max_age_bars: int = 3
    internal_structure_lookback: int = 5
    displacement_body_atr: float = 0.45
    displacement_range_atr: float = 0.72
    displacement_close_location: float = 0.68
    stop_buffer_atr: float = 0.08
    min_target_distance_atr: float = 0.75
    fallback_target_atr: float = 2.75
    min_rr: float = 0.90
    max_rr: float = 9.0
    limit_penetration_bps: float = 0.50
    make_market_candidates: bool = True
    make_limit_candidates: bool = True


@dataclass(frozen=True)
class FeeExecutionConfig:
    """Fee and execution assumptions.

    The default maker/taker rates are Bybit non-VIP USDT perpetual rates at
    the research date. Slippage is an explicit model assumption and can be
    stressed independently from the exchange fee schedule.
    """

    maker_fee_rate: float = 0.00020
    taker_fee_rate: float = 0.00055
    market_slippage_bps: float = 1.50
    stop_slippage_bps: float = 2.50
    mark_close_slippage_bps: float = 1.50
    maker_penetration_bps: float = 0.50
    impact_coefficient_bps: float = 8.0
    max_impact_bps: float = 35.0
    maintenance_margin_rate: float = 0.005
    margin_utilization_limit: float = 0.95
    leverage_grid: tuple[float, ...] = (1, 2, 3, 5, 8, 12, 20, 30, 50, 75, 100)

    def stressed(self, multiplier: float) -> "FeeExecutionConfig":
        if multiplier <= 0:
            raise ValueError("stress multiplier must be positive")
        return dataclasses.replace(
            self,
            maker_fee_rate=self.maker_fee_rate * multiplier,
            taker_fee_rate=self.taker_fee_rate * multiplier,
            market_slippage_bps=self.market_slippage_bps * multiplier,
            stop_slippage_bps=self.stop_slippage_bps * multiplier,
            mark_close_slippage_bps=self.mark_close_slippage_bps * multiplier,
            impact_coefficient_bps=self.impact_coefficient_bps * multiplier,
        )


@dataclass(frozen=True)
class ModelConfig:
    learning_rate: float = 0.045
    max_iter: int = 240
    max_leaf_nodes: int = 15
    min_samples_leaf: int = 24
    l2_regularization: float = 2.0
    max_bins: int = 127
    random_state: int = 20260727
    monthly_refit: bool = True
    refit_activation_delay_minutes: int = 15


@dataclass(frozen=True)
class Candidate:
    candidate_id: str
    setup_id: str
    symbol: str
    direction: int
    signal_available_ms: int
    activation_ms: int
    entry_mode: str
    planned_entry: float
    stop_price: float
    target_price: float
    liquidity_source: str
    target_source: str
    feature_values: Mapping[str, Any]


@dataclass(frozen=True)
class TradePlan:
    candidate: Candidate
    order_terminal_ms: int
    order_status: str
    entry_time_ms: int | None
    entry_index: int | None
    entry_price: float | None
    entry_fee_rate: float | None
    exit_time_ms: int | None
    exit_index: int | None
    exit_price: float | None
    exit_fee_rate: float | None
    exit_reason: str | None
    resolved: bool
    funding_cash_per_unit: float
    net_cash_per_unit: float | None
    loss_budget_per_unit: float | None
    net_r: float | None

    @property
    def executed(self) -> bool:
        return self.entry_time_ms is not None

    @property
    def slot_end_ms(self) -> int:
        return self.order_terminal_ms


@dataclass
class SymbolData:
    symbol: str
    minute: pd.DataFrame
    five_minute: pd.DataFrame
    funding: pd.DataFrame = field(default_factory=pd.DataFrame)
    mark_minute: pd.DataFrame = field(default_factory=pd.DataFrame)
    index_minute: pd.DataFrame = field(default_factory=pd.DataFrame)
    premium_minute: pd.DataFrame = field(default_factory=pd.DataFrame)
    open_interest_5m: pd.DataFrame = field(default_factory=pd.DataFrame)
    account_ratio_5m: pd.DataFrame = field(default_factory=pd.DataFrame)


@dataclass
class BacktestResult:
    start_ms: int
    end_exclusive_ms: int
    initial_nav: float
    terminal_nav: float
    daily_geometric_growth: float
    max_drawdown: float
    min_nav: float
    selected_orders: int
    executed_trades: int
    wins: int
    losses: int
    canceled_orders: int
    unresolved_orders: int
    gross_pnl: float
    fees_and_execution_cost: float
    funding_pnl: float
    liquidation_count: int
    rejected_for_margin: int
    risk_fraction: float
    score_threshold: float
    score_quantile: float | None
    daily_nav: pd.DataFrame
    trades: pd.DataFrame

    def summary(self) -> dict[str, Any]:
        return {
            "start_ms": self.start_ms,
            "end_exclusive_ms": self.end_exclusive_ms,
            "initial_nav": self.initial_nav,
            "terminal_nav": self.terminal_nav,
            "account_multiple": self.terminal_nav / self.initial_nav if self.initial_nav else math.nan,
            "daily_geometric_growth": self.daily_geometric_growth,
            "max_drawdown": self.max_drawdown,
            "min_nav": self.min_nav,
            "selected_orders": self.selected_orders,
            "executed_trades": self.executed_trades,
            "wins": self.wins,
            "losses": self.losses,
            "win_rate": self.wins / self.executed_trades if self.executed_trades else math.nan,
            "canceled_orders": self.canceled_orders,
            "unresolved_orders": self.unresolved_orders,
            "gross_pnl": self.gross_pnl,
            "fees_and_execution_cost": self.fees_and_execution_cost,
            "funding_pnl": self.funding_pnl,
            "liquidation_count": self.liquidation_count,
            "rejected_for_margin": self.rejected_for_margin,
            "risk_fraction": self.risk_fraction,
            "score_threshold": self.score_threshold,
            "score_quantile": self.score_quantile,
        }


class FeatureEncoder:
    """Deterministic numeric encoding with stable training columns."""

    categorical = ("symbol", "entry_mode", "liquidity_source", "target_source")

    def __init__(self) -> None:
        self.columns_: list[str] = []

    def _frame(self, rows: pd.DataFrame) -> pd.DataFrame:
        frame = rows.copy()
        existing = [column for column in self.categorical if column in frame.columns]
        frame = pd.get_dummies(frame, columns=existing, prefix=existing, dtype=float)
        for column in frame.columns:
            if frame[column].dtype == bool:
                frame[column] = frame[column].astype(float)
            elif not pd.api.types.is_numeric_dtype(frame[column]):
                frame[column] = pd.to_numeric(frame[column], errors="coerce")
        return frame.astype(float)

    def fit_transform(self, rows: pd.DataFrame) -> pd.DataFrame:
        frame = self._frame(rows)
        self.columns_ = sorted(frame.columns)
        return frame.reindex(columns=self.columns_)

    def transform(self, rows: pd.DataFrame) -> pd.DataFrame:
        if not self.columns_:
            raise RuntimeError("FeatureEncoder is not fitted")
        frame = self._frame(rows)
        return frame.reindex(columns=self.columns_, fill_value=0.0)


@dataclass
class FittedRanker:
    encoder: FeatureEncoder
    model: HistGradientBoostingRegressor
    training_rows: int
    training_end_ms: int

    def predict(self, features: pd.DataFrame) -> np.ndarray:
        return self.model.predict(self.encoder.transform(features))


def utc_ms(value: str | pd.Timestamp) -> int:
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is None:
        timestamp = timestamp.tz_localize(UTC)
    else:
        timestamp = timestamp.tz_convert(UTC)
    return int(timestamp.timestamp() * 1000)


def ms_to_timestamp(value: int) -> pd.Timestamp:
    return pd.to_datetime(value, unit="ms", utc=True)


def ceil_to_minute_ms(value: int) -> int:
    return ((value + MS_MINUTE - 1) // MS_MINUTE) * MS_MINUTE


def safe_divide(numerator: pd.Series | np.ndarray | float, denominator: pd.Series | np.ndarray | float) -> Any:
    if isinstance(denominator, pd.Series):
        denominator = denominator.where(denominator.abs() > 1e-12)
    elif isinstance(denominator, np.ndarray):
        denominator = np.where(np.abs(denominator) > 1e-12, denominator, np.nan)
    elif abs(float(denominator)) <= 1e-12:
        denominator = math.nan
    return numerator / denominator


def _read_parquet_if_exists(path: Path) -> pd.DataFrame:
    if not path.is_file():
        return pd.DataFrame()
    return pd.read_parquet(path)


def discover_canonical_shards(root: Path) -> dict[tuple[str, str], Path]:
    """Discover immutable canonical shard roots by manifest contents."""
    shards: dict[tuple[str, str], Path] = {}
    for manifest_path in root.rglob("DATASET_MANIFEST.json"):
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            segment = str(manifest["physical_segment"])
            symbol = str(manifest["symbol"])
        except (OSError, KeyError, ValueError, TypeError):
            continue
        key = (segment, symbol)
        incumbent = shards.get(key)
        if incumbent is not None and incumbent != manifest_path.parent:
            raise ValueError(f"duplicate canonical shard for {key}: {incumbent} and {manifest_path.parent}")
        shards[key] = manifest_path.parent
    return shards


def _concat_stream(paths: Sequence[Path], relative: str, timestamp_column: str) -> pd.DataFrame:
    frames = [_read_parquet_if_exists(path / relative) for path in paths]
    frames = [frame for frame in frames if not frame.empty]
    if not frames:
        return pd.DataFrame()
    result = pd.concat(frames, ignore_index=True)
    if timestamp_column not in result.columns:
        raise ValueError(f"{relative} missing {timestamp_column}")
    result[timestamp_column] = pd.to_numeric(result[timestamp_column], errors="raise").astype("int64")
    return result.drop_duplicates(timestamp_column, keep="last").sort_values(timestamp_column).reset_index(drop=True)


def load_symbol_data(
    root: str | Path,
    *,
    symbol: str,
    segments: Sequence[str],
) -> SymbolData:
    root_path = Path(root)
    shards = discover_canonical_shards(root_path)
    paths: list[Path] = []
    missing: list[str] = []
    for segment in segments:
        shard = shards.get((segment, symbol))
        if shard is None:
            missing.append(segment)
        else:
            paths.append(shard)
    if missing:
        raise FileNotFoundError(f"missing canonical shards for {symbol}: {missing}")
    minute = _concat_stream(paths, "trade_bars/1m.parquet", "start_time_ms")
    five = _concat_stream(paths, "trade_bars/5m.parquet", "start_time_ms")
    if minute.empty or five.empty:
        raise ValueError(f"{symbol} canonical trade bars are empty")
    return SymbolData(
        symbol=symbol,
        minute=minute,
        five_minute=five,
        funding=_concat_stream(paths, "streams/funding_events.parquet", "timestamp_ms"),
        mark_minute=_concat_stream(paths, "streams/mark_price_1m.parquet", "start_time_ms"),
        index_minute=_concat_stream(paths, "streams/index_price_1m.parquet", "start_time_ms"),
        premium_minute=_concat_stream(paths, "streams/premium_index_1m.parquet", "start_time_ms"),
        open_interest_5m=_concat_stream(paths, "streams/open_interest_5m.parquet", "timestamp_ms"),
        account_ratio_5m=_concat_stream(paths, "streams/account_ratio_5m.parquet", "timestamp_ms"),
    )


def _confirmed_pivots(
    highs: np.ndarray,
    lows: np.ndarray,
    atr: np.ndarray,
    *,
    left: int,
    right: int,
    equal_tolerance_atr: float,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Return last causally confirmed swing and equal-liquidity levels.

    A pivot at index ``center`` is written only at ``center + right``. No row
    before that confirmation point can observe it.
    """
    n = len(highs)
    last_high = np.full(n, np.nan)
    last_low = np.full(n, np.nan)
    equal_high = np.full(n, np.nan)
    equal_low = np.full(n, np.nan)
    current_high = current_low = math.nan
    previous_pivot_high = previous_pivot_low = math.nan
    current_eq_high = current_eq_low = math.nan
    for confirm in range(n):
        center = confirm - right
        if center >= left and center + right < n:
            window_start = center - left
            window_end = center + right + 1
            center_high = highs[center]
            center_low = lows[center]
            if np.isfinite(center_high) and center_high >= np.nanmax(highs[window_start:window_end]):
                tolerance = equal_tolerance_atr * atr[confirm] if np.isfinite(atr[confirm]) else 0.0
                if np.isfinite(previous_pivot_high) and abs(center_high - previous_pivot_high) <= tolerance:
                    current_eq_high = (center_high + previous_pivot_high) / 2.0
                previous_pivot_high = center_high
                current_high = center_high
            if np.isfinite(center_low) and center_low <= np.nanmin(lows[window_start:window_end]):
                tolerance = equal_tolerance_atr * atr[confirm] if np.isfinite(atr[confirm]) else 0.0
                if np.isfinite(previous_pivot_low) and abs(center_low - previous_pivot_low) <= tolerance:
                    current_eq_low = (center_low + previous_pivot_low) / 2.0
                previous_pivot_low = center_low
                current_low = center_low
        last_high[confirm] = current_high
        last_low[confirm] = current_low
        equal_high[confirm] = current_eq_high
        equal_low[confirm] = current_eq_low
    return last_high, last_low, equal_high, equal_low


def _asof_feature(
    base: pd.DataFrame,
    stream: pd.DataFrame,
    *,
    stream_time: str,
    columns: Sequence[str],
    prefix: str,
) -> pd.DataFrame:
    if stream.empty:
        for column in columns:
            base[f"{prefix}{column}"] = np.nan
        return base
    source = stream.copy()
    if "available_at_ms" in source.columns:
        source_time = "available_at_ms"
    else:
        source_time = stream_time
    source = source[[source_time, *[c for c in columns if c in source.columns]]].copy()
    source[source_time] = pd.to_numeric(source[source_time], errors="coerce")
    source = source.dropna(subset=[source_time]).sort_values(source_time)
    source = source.rename(columns={column: f"{prefix}{column}" for column in columns if column in source.columns})
    merged = pd.merge_asof(
        base.sort_values("available_at_ms"),
        source,
        left_on="available_at_ms",
        right_on=source_time,
        direction="backward",
        allow_exact_matches=True,
    )
    if source_time != "available_at_ms" and source_time in merged.columns:
