from __future__ import annotations

import argparse
import calendar
import gzip
import hashlib
import io
import json
import math
import time
from collections import deque
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import numpy as np
import pandas as pd
import requests
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.isotonic import IsotonicRegression
from sklearn.metrics import brier_score_loss, roc_auc_score

CLAIM_ID = "CLM-20260726-2110-ML-STABLECOIN-ISSUANCE-001"
ENGINE_VERSION = "ML-STABLECOIN-ISSUANCE-FIRST-PASSAGE-V1"
SYMBOLS = ("BTCUSDT", "ETHUSDT")
FEATURES = (
    "log_event_usd_notional",
    "mint_or_burn",
    "usdt_or_usdc",
    "prior_60m_same_direction_event_notional",
    "prior_24h_net_issuance",
    "event_block_gas_utilization",
    "prior_15m_return",
    "prior_60m_realized_volatility",
    "prior_60m_path_efficiency",
    "distance_to_frozen_upper_60m_liquidity",
    "distance_to_frozen_lower_60m_liquidity",
    "btc_eth_completed_return_breadth",
)
PRIMARY_COST_BPS = 24.0
COSTS_BPS = (12.0, 18.0, 24.0)
BASE_RISK = 0.005
BASE_NOTIONAL_CAP = 3.0
MODEL_PARAMS = {
    "learning_rate": 0.05,
    "max_iter": 250,
    "max_leaf_nodes": 31,
    "min_samples_leaf": 80,
    "l2_regularization": 1.0,
    "early_stopping": False,
    "random_state": 20260726,
}
SPLITS = {
    "train": (pd.Timestamp("2021-01-01", tz="UTC"), pd.Timestamp("2022-01-01", tz="UTC")),
    "calibration": (pd.Timestamp("2022-01-01", tz="UTC"), pd.Timestamp("2022-07-01", tz="UTC")),
    "confirmation": (pd.Timestamp("2022-07-01", tz="UTC"), pd.Timestamp("2023-01-01", tz="UTC")),
    "development": (pd.Timestamp("2023-01-01", tz="UTC"), pd.Timestamp("2024-01-01", tz="UTC")),
}
BYBIT_BASE = "https://public.bybit.com/kline_for_metatrader4"


@dataclass(frozen=True)
class SourceEvent:
    event_id: str
    token: str
    direction: str
    amount_usd: float
    block_timestamp: int
    available_timestamp_12: int
    available_timestamp_64: int
    event_block_gas_utilization: float = math.nan


@dataclass
class Market:
    symbol: str
    frame: pd.DataFrame


@dataclass(frozen=True)
class EventRow:
    event_id: str
    symbol: str
    availability_ts: int
    entry_ts: int
    split: str
    features: tuple[float, ...]
    upper: float
    lower: float
    entry: float
    up_distance: float
    down_distance: float
    outcome: int | None
    outcome_reason: str
    exit_ts: int | None
    ambiguous: bool
    source_gap: bool


@dataclass(frozen=True)
class CandidateAction:
    event_id: str
    symbol: str
    entry_ts: int
    side: int
    score: float
    probability_up: float
    upper: float
    lower: float
    entry: float
    exit_ts: int | None
    outcome: int | None
    ambiguous: bool
    source_gap: bool
    split: str

    @property
    def key(self) -> str:
        return f"{self.event_id}|{self.symbol}"


@dataclass(frozen=True)
class Trade:
    event_id: str
    symbol: str
    entry_ts: int
    exit_ts: int
    side: int
    entry: float
    exit: float
    stop: float
    target: float
    outcome_reason: str
    probability_up: float
    score: float
    cost_bps: float
    notional: float
    pnl: float
    account_return: float
    nav_before: float
    nav_after: float
    net_return_bps_on_notional: float


class DownloadError(RuntimeError):
    pass


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def month_tokens(start: str, end: str) -> list[tuple[int, int]]:
    a = pd.Period(start, freq="M")
    b = pd.Period(end, freq="M")
    if a > b:
        raise ValueError("start after end")
    return [(period.year, period.month) for period in pd.period_range(a, b, freq="M")]


def bybit_month_url(symbol: str, year: int, month: int) -> str:
    last = calendar.monthrange(year, month)[1]
    name = f"{symbol}_1_{year:04d}-{month:02d}-01_{year:04d}-{month:02d}-{last:02d}.csv.gz"
    return f"{BYBIT_BASE}/{symbol}/{year:04d}/{name}"


def parse_timestamp(values: pd.Series) -> pd.DatetimeIndex:
    numeric = pd.to_numeric(values, errors="coerce")
    finite = numeric.notna()
    if finite.mean() > 0.99:
        observed = numeric.loc[finite].abs().median()
        if observed > 1e14:
            unit = "us"
        elif observed > 1e11:
            unit = "ms"
        elif observed > 1e8:
            unit = "s"
        else:
            raise ValueError("numeric timestamp scale is unknown")
        parsed = pd.to_datetime(numeric, unit=unit, utc=True, errors="coerce")
    else:
        parsed = pd.to_datetime(values.astype(str), utc=True, errors="coerce")
    return pd.DatetimeIndex(parsed)


def parse_bybit_month(payload: bytes, symbol: str) -> pd.DataFrame:
    try:
        raw = gzip.decompress(payload)
    except OSError as exc:
        raise ValueError(f"{symbol}: invalid gzip") from exc
    frame = pd.read_csv(io.BytesIO(raw), header=None)
    if frame.shape[1] < 5:
        raise ValueError(f"{symbol}: invalid width {frame.shape[1]}")
    timestamp = parse_timestamp(frame.iloc[:, 0])
    out = pd.DataFrame({
        "timestamp": timestamp,
        "open": pd.to_numeric(frame.iloc[:, 1], errors="coerce"),
        "high": pd.to_numeric(frame.iloc[:, 2], errors="coerce"),
        "low": pd.to_numeric(frame.iloc[:, 3], errors="coerce"),
        "close": pd.to_numeric(frame.iloc[:, 4], errors="coerce"),
        "volume": pd.to_numeric(frame.iloc[:, 5], errors="coerce") if frame.shape[1] > 5 else np.nan,
    })
    out = out.dropna(subset=["timestamp", "open", "high", "low", "close"])
    out = out[(out.open > 0) & (out.high > 0) & (out.low > 0) & (out.close > 0)]
    out["high"] = out[["open", "high", "low", "close"]].max(axis=1)
    out["low"] = out[["open", "high", "low", "close"]].min(axis=1)
    out = out.sort_values("timestamp").drop_duplicates("timestamp", keep="last")
    return out.set_index("timestamp")


def fetch_bytes(session: requests.Session, url: str, retries: int = 5) -> bytes:
    errors: list[str] = []
    for attempt in range(retries):
        try:
            response = session.get(url, timeout=180)
            if response.status_code == 200:
                return response.content
            errors.append(f"HTTP {response.status_code}")
        except requests.RequestException as exc:
            errors.append(f"{type(exc).__name__}: {exc}")
        time.sleep(min(2**attempt, 16))
    raise DownloadError(f"{url}: {' | '.join(errors[-5:])}")


def download_market(
    symbol: str,
    cache: Path,
    start_month: str = "2020-12",
    end_month: str = "2023-12",
) -> tuple[Market, list[dict[str, Any]]]:
    root = cache / symbol
    root.mkdir(parents=True, exist_ok=True)
    frames: list[pd.DataFrame] = []
    manifest: list[dict[str, Any]] = []
    with requests.Session() as session:
        session.headers["User-Agent"] = "SMC_ICT_2_LIVE-stablecoin-model/1.0"
        for year, month in month_tokens(start_month, end_month):
            url = bybit_month_url(symbol, year, month)
            path = root / url.rsplit("/", 1)[-1]
            if not path.exists():
                path.write_bytes(fetch_bytes(session, url))
            payload = path.read_bytes()
            parsed = parse_bybit_month(payload, symbol)
            frames.append(parsed)
            manifest.append({
                "symbol": symbol,
                "year": year,
                "month": month,
                "url": url,
                "path": str(path),
                "bytes": len(payload),
                "sha256": sha256_bytes(payload),
                "rows": len(parsed),
                "first_timestamp": parsed.index.min().isoformat(),
                "last_timestamp": parsed.index.max().isoformat(),
            })
    merged = pd.concat(frames).sort_index().loc[lambda x: ~x.index.duplicated(keep="last")]
    start = pd.Timestamp(start_month + "-01", tz="UTC")
    end_period = pd.Period(end_month, freq="M") + 1
    end = pd.Timestamp(str(end_period) + "-01", tz="UTC")
    index = pd.date_range(start, end, freq="1min", inclusive="both")
    merged = merged.reindex(index)
    merged.index.name = "timestamp"
    return Market(symbol, merged), manifest


def load_source_events(path: Path) -> list[SourceEvent]:
    events: list[SourceEvent] = []
    seen: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        event_id = str(row["event_id"])
        if event_id in seen:
            raise ValueError(f"duplicate event {event_id}")
        seen.add(event_id)
        event = SourceEvent(
            event_id=event_id,
            token=str(row["token"]),
            direction=str(row["direction"]),
            amount_usd=float(row["amount_usd"]),
            block_timestamp=int(row["block_timestamp"]),
            available_timestamp_12=int(row["available_timestamp_12"]),
            available_timestamp_64=int(row["available_timestamp_64"]),
            event_block_gas_utilization=float(row.get("event_block_gas_utilization", math.nan)),
        )
        if event.available_timestamp_64 >= int(pd.Timestamp("2024-01-01", tz="UTC").timestamp()):
            raise ValueError(f"event stress availability enters 2024: {event_id}")
        events.append(event)
    return sorted(events, key=lambda event: (event.available_timestamp_12, event.event_id))


def split_for_timestamp(timestamp: int) -> str | None:
    value = pd.Timestamp(timestamp, unit="s", tz="UTC")
    for name, (start, end) in SPLITS.items():
        if start <= value < end:
            return name
    return None


def split_end_seconds(split: str) -> int:
    return int(SPLITS[split][1].timestamp())


def ceil_minute(timestamp: int) -> int:
    return int(((timestamp + 59) // 60) * 60)


def finite_window(frame: pd.DataFrame, end_pos: int, length: int) -> pd.DataFrame | None:
    start = end_pos - length
    if start < 0:
        return None
    window = frame.iloc[start:end_pos]
    if len(window) != length:
        return None
    required = window[["open", "high", "low", "close"]].to_numpy(float)
    if not np.isfinite(required).all():
        return None
    return window


def market_position(market: Market, timestamp: int) -> int | None:
    key = pd.Timestamp(timestamp, unit="s", tz="UTC")
    location = market.frame.index.get_indexer([key])[0]
    return None if location < 0 else int(location)


def realized_volatility(close: np.ndarray) -> float:
    returns = np.diff(np.log(close))
    return float(np.std(returns, ddof=0)) if len(returns) else math.nan


def path_efficiency(close: np.ndarray) -> float:
    denominator = float(np.sum(np.abs(np.diff(close))))
    if denominator <= 0:
        return 0.0
    return float(abs(close[-1] - close[0]) / denominator)


def prior_event_features(events: Sequence[SourceEvent]) -> dict[str, tuple[float, float]]:
    result: dict[str, tuple[float, float]] = {}
    one_hour: deque[SourceEvent] = deque()
    one_day: deque[SourceEvent] = deque()
    index = 0
    while index < len(events):
        timestamp = events[index].available_timestamp_12
        group: list[SourceEvent] = []
        while index < len(events) and events[index].available_timestamp_12 == timestamp:
            group.append(events[index])
            index += 1
        while one_hour and one_hour[0].available_timestamp_12 <= timestamp - 3600:
            one_hour.popleft()
        while one_day and one_day[0].available_timestamp_12 <= timestamp - 86400:
            one_day.popleft()
        for event in group:
            same = sum(item.amount_usd for item in one_hour if item.direction == event.direction)
            net = sum(
                item.amount_usd * (1.0 if item.direction == "MINT" else -1.0)
                for item in one_day
            )
            result[event.event_id] = (math.log1p(same), math.copysign(math.log1p(abs(net)), net))
        one_hour.extend(group)
        one_day.extend(group)
    return result


def scan_outcome(
    market: Market,
    entry_pos: int,
    upper: float,
    lower: float,
    cutoff_ts: int,
) -> tuple[int | None, str, int | None, bool, bool]:
    frame = market.frame
    for pos in range(entry_pos, len(frame)):
        timestamp = int(frame.index[pos].timestamp())
        if timestamp >= cutoff_ts:
            return None, "partition_boundary", None, False, False
        row = frame.iloc[pos]
        values = row[["open", "high", "low", "close"]].to_numpy(float)
        if not np.isfinite(values).all():
            return None, "source_gap", timestamp, False, True
        hit_up = float(row.high) >= upper
        hit_down = float(row.low) <= lower
        if hit_up and hit_down:
            return None, "same_minute_ambiguous", timestamp, True, False
        if hit_up:
            return 1, "upper_first", timestamp, False, False
        if hit_down:
            return 0, "lower_first", timestamp, False, False
    return None, "source_end", None, False, True


def build_event_rows(events: Sequence[SourceEvent], markets: Mapping[str, Market]) -> list[EventRow]:
    prior = prior_event_features(events)
    rows: list[EventRow] = []
    for event in events:
        split = split_for_timestamp(event.available_timestamp_12)
        if split is None:
            continue
        entry_ts = ceil_minute(event.available_timestamp_12)
        symbol_features: dict[str, dict[str, float]] = {}
        symbol_positions: dict[str, int] = {}
        for symbol, market in markets.items():
            pos = market_position(market, entry_ts)
            if pos is None:
                continue
            window = finite_window(market.frame, pos, 60)
            if window is None:
                continue
            entry = float(market.frame.iloc[pos].open)
            if not np.isfinite(entry) or entry <= 0:
                continue
            upper = float(window.high.max())
            lower = float(window.low.min())
            if not (lower < entry < upper):
                continue
            close = window.close.to_numpy(float)
            symbol_positions[symbol] = pos
            symbol_features[symbol] = {
                "entry": entry,
                "upper": upper,
                "lower": lower,
                "prior15": float(close[-1] / close[-16] - 1.0),
                "rv60": realized_volatility(close),
                "efficiency": path_efficiency(close),
            }
        if not symbol_features:
            continue
        breadth = float(np.mean([np.sign(item["prior15"]) for item in symbol_features.values()]))
        same60, net24 = prior[event.event_id]
        for symbol, values in symbol_features.items():
            up_distance = values["upper"] / values["entry"] - 1.0
            down_distance = 1.0 - values["lower"] / values["entry"]
            if up_distance <= 0 or down_distance <= 0:
                continue
            outcome, reason, exit_ts, ambiguous, source_gap = scan_outcome(
                markets[symbol], symbol_positions[symbol], values["upper"], values["lower"], split_end_seconds(split)
            )
            features = (
                math.log1p(max(event.amount_usd, 0.0)),
                1.0 if event.direction == "MINT" else -1.0,
                1.0 if event.token == "USDT" else 0.0,
                same60,
                net24,
                event.event_block_gas_utilization,
                values["prior15"],
                values["rv60"],
                values["efficiency"],
                up_distance,
                down_distance,
                breadth,
            )
            rows.append(EventRow(
                event_id=event.event_id,
                symbol=symbol,
                availability_ts=event.available_timestamp_12,
                entry_ts=entry_ts,
                split=split,
                features=tuple(float(x) for x in features),
                upper=values["upper"],
                lower=values["lower"],
                entry=values["entry"],
                up_distance=up_distance,
                down_distance=down_distance,
                outcome=outcome,
                outcome_reason=reason,
                exit_ts=exit_ts,
                ambiguous=ambiguous,
                source_gap=source_gap,
            ))
    return rows


def matrix(rows: Sequence[EventRow]) -> np.ndarray:
    return np.asarray([row.features for row in rows], dtype=float)


def labels(rows: Sequence[EventRow]) -> np.ndarray:
    return np.asarray([int(row.outcome) for row in rows], dtype=int)


def resolved(rows: Iterable[EventRow]) -> list[EventRow]:
    return [row for row in rows if row.outcome in (0, 1) and not row.ambiguous and not row.source_gap]


def distance_probability(rows: Sequence[EventRow]) -> np.ndarray:
    return np.asarray([
        row.down_distance / (row.up_distance + row.down_distance)
        for row in rows
    ], dtype=float)


def fit_model(rows: Sequence[EventRow]) -> HistGradientBoostingClassifier:
    if len(rows) < 2 or len(set(labels(rows))) < 2:
        raise ValueError("training labels do not contain both classes")
    model = HistGradientBoostingClassifier(**MODEL_PARAMS)
    model.fit(matrix(rows), labels(rows))
    return model


def fit_calibrator(model: HistGradientBoostingClassifier, rows: Sequence[EventRow]) -> IsotonicRegression:
    if len(rows) < 2 or len(set(labels(rows))) < 2:
        raise ValueError("calibration labels do not contain both classes")
    raw = model.predict_proba(matrix(rows))[:, 1]
    calibrator = IsotonicRegression(out_of_bounds="clip", y_min=0.001, y_max=0.999)
    calibrator.fit(raw, labels(rows))
    return calibrator


def predict_probability(
    model: HistGradientBoostingClassifier,
    calibrator: IsotonicRegression,
    rows: Sequence[EventRow],
) -> np.ndarray:
    raw = model.predict_proba(matrix(rows))[:, 1]
    return np.asarray(calibrator.predict(raw), dtype=float)


def probability_metrics(y: np.ndarray, p: np.ndarray, baseline: np.ndarray) -> dict[str, float]:
    if len(set(y.tolist())) < 2:
        return {
            "rows": float(len(y)),
            "auc": math.nan,
            "distance_auc": math.nan,
            "auc_lift": math.nan,
            "brier": float(brier_score_loss(y, p)),
            "distance_brier": float(brier_score_loss(y, baseline)),
            "brier_skill": math.nan,
        }
    auc = float(roc_auc_score(y, p))
    distance_auc = float(roc_auc_score(y, baseline))
    brier = float(brier_score_loss(y, p))
    distance_brier = float(brier_score_loss(y, baseline))
    return {
        "rows": float(len(y)),
        "auc": auc,
        "distance_auc": distance_auc,
        "auc_lift": auc - distance_auc,
        "brier": brier,
        "distance_brier": distance_brier,
        "brier_skill": 1.0 - brier / distance_brier if distance_brier > 0 else math.nan,
    }


def make_candidates(rows: Sequence[EventRow], probabilities: np.ndarray) -> list[CandidateAction]:
    candidates: list[CandidateAction] = []
    cost = PRIMARY_COST_BPS / 10_000.0
    for row, p_up in zip(rows, probabilities, strict=True):
        long_ev = p_up * row.up_distance - (1.0 - p_up) * row.down_distance - cost
        short_ev = (1.0 - p_up) * row.down_distance - p_up * row.up_distance - cost
        if max(long_ev, short_ev) <= 0:
            continue
        side = 1 if long_ev >= short_ev else -1
        candidates.append(CandidateAction(
            event_id=row.event_id,
            symbol=row.symbol,
            entry_ts=row.entry_ts,
            side=side,
            score=float(max(long_ev, short_ev)),
            probability_up=float(p_up),
            upper=row.upper,
            lower=row.lower,
            entry=row.entry,
            exit_ts=row.exit_ts,
            outcome=row.outcome,
            ambiguous=row.ambiguous,
            source_gap=row.source_gap,
            split=row.split,
        ))
    return candidates


def action_exit(action: CandidateAction) -> tuple[float, str, int]:
    stop = action.lower if action.side > 0 else action.upper
    target = action.upper if action.side > 0 else action.lower
    if action.exit_ts is None:
        return stop, "punitive_source_boundary", action.entry_ts
    if action.ambiguous:
        return stop, "same_minute_stop_first", action.exit_ts
    if action.source_gap or action.outcome is None:
        return stop, "punitive_source_gap", action.exit_ts
    target_won = (action.side > 0 and action.outcome == 1) or (action.side < 0 and action.outcome == 0)
    return (target, "target", action.exit_ts) if target_won else (stop, "stop", action.exit_ts)


def arbitrate_candidates(
    candidates: Sequence[CandidateAction], excluded_event_ids: set[str] | None = None
) -> list[CandidateAction]:
    excluded = excluded_event_ids or set()
    ordered = sorted(
        (candidate for candidate in candidates if candidate.event_id not in excluded),
        key=lambda item: (item.entry_ts, -item.score, 0 if item.symbol == "BTCUSDT" else 1, -item.side),
    )
    selected: list[CandidateAction] = []
    free_at = -1
    index = 0
    while index < len(ordered):
        timestamp = ordered[index].entry_ts
        group: list[CandidateAction] = []
        while index < len(ordered) and ordered[index].entry_ts == timestamp:
            group.append(ordered[index])
            index += 1
        if timestamp < free_at:
            continue
        winner = group[0]
        _, _, exit_ts = action_exit(winner)
        selected.append(winner)
        free_at = max(timestamp + 60, exit_ts + 60)
    return selected


def replay(
    candidates: Sequence[CandidateAction],
    cost_bps: float,
    start: pd.Timestamp,
    end: pd.Timestamp,
    risk_fraction: float = BASE_RISK,
    notional_cap: float = BASE_NOTIONAL_CAP,
    excluded_event_ids: set[str] | None = None,
) -> tuple[list[Trade], dict[str, Any]]:
    selected = arbitrate_candidates(candidates, excluded_event_ids)
    nav = 10_000.0
    peak = nav
    maximum_drawdown = 0.0
    trades: list[Trade] = []
    for action in selected:
        stop = action.lower if action.side > 0 else action.upper
        target = action.upper if action.side > 0 else action.lower
        exit_price, reason, exit_ts = action_exit(action)
        stop_fraction = abs(stop / action.entry - 1.0)
        cost_fraction = cost_bps / 10_000.0
        planned_fraction = stop_fraction + cost_fraction
        if planned_fraction <= 0:
            continue
        notional = min(nav * risk_fraction / planned_fraction, nav * notional_cap)
        gross = action.side * (exit_price / action.entry - 1.0)
        net_on_notional = gross - cost_fraction
        pnl = notional * net_on_notional
        before = nav
        nav = nav + pnl
        if nav <= 0 or not np.isfinite(nav):
            nav = 0.0
        account_return = -1.0 if before <= 0 else pnl / before
        peak = max(peak, nav)
        maximum_drawdown = max(maximum_drawdown, 1.0 - nav / peak if peak > 0 else 1.0)
        trades.append(Trade(
            event_id=action.event_id,
            symbol=action.symbol,
            entry_ts=action.entry_ts,
            exit_ts=exit_ts,
            side=action.side,
            entry=action.entry,
            exit=exit_price,
            stop=stop,
            target=target,
            outcome_reason=reason,
            probability_up=action.probability_up,
            score=action.score,
            cost_bps=cost_bps,
            notional=notional,
            pnl=pnl,
            account_return=account_return,
            nav_before=before,
            nav_after=nav,
            net_return_bps_on_notional=net_on_notional * 10_000.0,
        ))
        if nav <= 0:
            break
    days = max(1.0, (end - start).total_seconds() / 86400.0)
    pnl_values = np.asarray([trade.pnl for trade in trades], dtype=float)
    positive = pnl_values[pnl_values > 0]
    negative = -pnl_values[pnl_values < 0]
    monthly: dict[str, float] = {}
    month_start = start.tz_localize(None).to_period("M")
    month_end = (end - pd.Timedelta(seconds=1)).tz_localize(None).to_period("M")
    for month in pd.period_range(month_start, month_end, freq="M"):
        returns = [
            trade.account_return
            for trade in trades
            if pd.Timestamp(trade.exit_ts, unit="s", tz="UTC").tz_localize(None).to_period("M") == month
        ]
        monthly[str(month)] = float(np.prod(1.0 + np.asarray(returns, dtype=float)) - 1.0) if returns else 0.0
    summary = {
        "cost_bps": cost_bps,
        "trade_count": len(trades),
        "final_nav": nav,
        "total_return": nav / 10_000.0 - 1.0,
        "geometric_daily_growth": math.exp(math.log(nav / 10_000.0) / days) - 1.0 if nav > 0 else -1.0,
        "maximum_drawdown": maximum_drawdown,
        "profit_factor": float(positive.sum() / negative.sum()) if negative.sum() > 0 else (math.inf if positive.sum() > 0 else 0.0),
        "median_net_return_bps_on_notional": float(np.median([trade.net_return_bps_on_notional for trade in trades])) if trades else math.nan,
        "positive_month_fraction": float(np.mean(np.asarray(list(monthly.values())) > 0)) if monthly else 0.0,
        "month_returns": monthly,
        "liquidated": nav <= 0,
    }
    return trades, summary


def winner_removed(
    candidates: Sequence[CandidateAction],
    base_trades: Sequence[Trade],
    cost_bps: float,
    start: pd.Timestamp,
    end: pd.Timestamp,
    risk_fraction: float = BASE_RISK,
    notional_cap: float = BASE_NOTIONAL_CAP,
) -> tuple[list[Trade], dict[str, Any], list[str]]:
    positive = sorted((trade for trade in base_trades if trade.pnl > 0), key=lambda trade: trade.pnl, reverse=True)
    remove_count = max(1, int(math.ceil(len(base_trades) * 0.10))) if base_trades else 0
    removed = {trade.event_id for trade in positive[:remove_count]}
    trades, summary = replay(candidates, cost_bps, start, end, risk_fraction, notional_cap, removed)
    summary["removed_event_count"] = len(removed)
    return trades, summary, sorted(removed)


def half_returns(trades: Sequence[Trade], start: pd.Timestamp, end: pd.Timestamp) -> dict[str, float]:
    midpoint = start + (end - start) / 2
    result: dict[str, float] = {}
    for name, a, b in (("first_half", start, midpoint), ("second_half", midpoint, end)):
        returns = [
            trade.account_return
            for trade in trades
            if a <= pd.Timestamp(trade.exit_ts, unit="s", tz="UTC") < b
        ]
        result[name] = float(np.prod(1.0 + np.asarray(returns, dtype=float)) - 1.0) if returns else 0.0
    return result


def evaluate_split(
    name: str, rows: Sequence[EventRow], probabilities: np.ndarray, metrics: dict[str, float]
) -> tuple[dict[str, Any], list[CandidateAction]]:
    candidates = make_candidates(rows, probabilities)
    start, end = SPLITS[name]
    paths: dict[str, Any] = {}
    base_primary: list[Trade] = []
    for cost in COSTS_BPS:
        trades, summary = replay(candidates, cost, start, end)
        if cost == PRIMARY_COST_BPS:
            base_primary = trades
            summary["half_returns"] = half_returns(trades, start, end)
        _, removed_summary, removed = winner_removed(candidates, trades, cost, start, end)
        summary["top10pct_removed_return"] = removed_summary["total_return"]
        summary["top10pct_removed_trade_count"] = removed_summary["trade_count"]
        summary["removed_event_ids"] = removed
        paths[str(int(cost))] = summary
    gate_checks = {
        "minimum_resolved_labels": metrics.get("rows", 0.0) >= 80,
        "minimum_actions": len(base_primary) >= 25,
        "auc_lift_over_structural_distance": metrics.get("auc_lift", math.nan) >= 0.02,
        "positive_brier_skill": metrics.get("brier_skill", math.nan) > 0,
        "positive_total_return_at_24bps": paths["24"]["total_return"] > 0,
        "positive_median_trade_at_24bps": paths["24"]["median_net_return_bps_on_notional"] > 0,
        "profit_factor_at_24bps": paths["24"]["profit_factor"] >= 1.2,
        "positive_top10pct_winner_removed_return_at_24bps": paths["24"]["top10pct_removed_return"] > 0,
        "both_confirmation_halves_positive_at_24bps": all(value > 0 for value in paths["24"]["half_returns"].values()),
    }
    return {
        "name": name,
        "resolved_rows": int(metrics.get("rows", 0.0)),
        "all_rows": len(rows),
        "prediction": metrics,
        "candidate_actions": len(candidates),
        "paths": paths,
        "gate_checks": gate_checks,
        "gate_passed": all(gate_checks.values()),
    }, candidates


def risk_search(candidates: Sequence[CandidateAction], start: pd.Timestamp, end: pd.Timestamp) -> dict[str, Any]:
    risk_grid = (0.0025, 0.005, 0.01, 0.02, 0.04, 0.08, 0.15, 0.30, 0.60)
    cap_grid = (1.0, 2.0, 3.0, 5.0, 10.0, 20.0, 50.0, 100.0)
    rows: list[dict[str, Any]] = []
    for risk in risk_grid:
        for cap in cap_grid:
            trades, summary = replay(candidates, PRIMARY_COST_BPS, start, end, risk, cap)
            _, removed, event_ids = winner_removed(candidates, trades, PRIMARY_COST_BPS, start, end, risk, cap)
            rows.append({
                "risk_fraction": risk,
                "notional_cap": cap,
                **summary,
                "top10pct_removed_return": removed["total_return"],
                "removed_event_ids": event_ids,
                "eligible": (
                    not summary["liquidated"]
                    and summary["total_return"] > 0
                    and removed["total_return"] > 0
                ),
            })
    eligible = [row for row in rows if row["eligible"]]
    selected = max(eligible, key=lambda row: row["geometric_daily_growth"]) if eligible else None
    return {"grid": rows, "selected": selected}


def run(source_dir: Path, output: Path, cache: Path) -> dict[str, Any]:
    output.mkdir(parents=True, exist_ok=True)
    source_result = json.loads((source_dir / "SOURCE_GATE_RESULT.json").read_text(encoding="utf-8"))
    if source_result.get("status") != "PASS" or not source_result.get("conditional_model_screen_authorized"):
        result = {
            "schema_version": 1,
            "claim_id": CLAIM_ID,
            "engine_version": ENGINE_VERSION,
            "status": "MODEL_NOT_AUTHORIZED_BY_SOURCE_GATE",
            "source_status": source_result.get("status"),
            "market_data_opened": False,
            "model_fit": False,
            "trade_or_pnl_opened": False,
            "official_2024_2026_opened": False,
            "orders_submitted": False,
        }
        (output / "RESULT.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
        return result

    events = load_source_events(source_dir / "EVENTS.jsonl")
    markets: dict[str, Market] = {}
    source_manifest: list[dict[str, Any]] = []
    for symbol in SYMBOLS:
        market, manifest = download_market(symbol, cache)
        markets[symbol] = market
        source_manifest.extend(manifest)
    (output / "BYBIT_SOURCE_MANIFEST.json").write_text(json.dumps(source_manifest, indent=2, sort_keys=True) + "\n")

    rows = build_event_rows(events, markets)
    all_rows_by_split = {name: [row for row in rows if row.split == name] for name in SPLITS}
    resolved_rows_by_split = {name: resolved(values) for name, values in all_rows_by_split.items()}
    train = resolved_rows_by_split["train"]
    calibration = resolved_rows_by_split["calibration"]
    confirmation_all = all_rows_by_split["confirmation"]
    confirmation_resolved = resolved_rows_by_split["confirmation"]
    model = fit_model(train)
    calibrator = fit_calibrator(model, calibration)

    confirmation_p_all = predict_probability(model, calibrator, confirmation_all)
    confirmation_p_resolved = predict_probability(model, calibrator, confirmation_resolved)
    confirmation_metrics = probability_metrics(
        labels(confirmation_resolved), confirmation_p_resolved, distance_probability(confirmation_resolved)
    )
    confirmation_result, _ = evaluate_split(
        "confirmation", confirmation_all, confirmation_p_all, confirmation_metrics
    )

    development_result: dict[str, Any] | None = None
    risk_result: dict[str, Any] | None = None
    if confirmation_result["gate_passed"]:
        development_all = all_rows_by_split["development"]
        development_resolved = resolved_rows_by_split["development"]
        development_p_all = predict_probability(model, calibrator, development_all)
        development_p_resolved = predict_probability(model, calibrator, development_resolved)
        development_metrics = probability_metrics(
            labels(development_resolved), development_p_resolved, distance_probability(development_resolved)
        )
        development_result, development_candidates = evaluate_split(
            "development", development_all, development_p_all, development_metrics
        )
        development_primary = development_result["paths"]["24"]
        if (
            development_primary["total_return"] > 0
            and development_primary["top10pct_removed_return"] > 0
            and not development_primary["liquidated"]
        ):
            risk_result = risk_search(development_candidates, *SPLITS["development"])

    result = {
        "schema_version": 1,
        "claim_id": CLAIM_ID,
        "engine_version": ENGINE_VERSION,
        "status": "DEVELOPMENT_COMPLETED" if development_result is not None else "CONFIRMATION_BELOW_GATE",
        "hard_validity": "PASS_INITIAL_CAUSAL_SCREEN",
        "model": {
            "type": "HistGradientBoostingClassifier plus frozen isotonic calibration",
            "parameters": MODEL_PARAMS,
            "features": list(FEATURES),
            "train_rows": len(train),
            "calibration_rows": len(calibration),
        },
        "event_count": len(events),
        "event_rows": len(rows),
        "split_row_counts": {
            name: {
                "all": len(all_rows_by_split[name]),
                "resolved": len(resolved_rows_by_split[name]),
                "unresolved_or_adverse_boundary": len(all_rows_by_split[name]) - len(resolved_rows_by_split[name]),
            }
            for name in SPLITS
        },
        "confirmation": confirmation_result,
        "development": development_result,
        "risk_search": risk_result,
        "one_global_slot": True,
        "no_elapsed_time_liquidation": True,
        "official_2024_2026_opened": False,
        "orders_submitted": False,
    }
    (output / "RESULT.json").write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=True) + "\n")
    (output / "MODEL_CONTRACT.json").write_text(json.dumps({
        "schema_version": 1,
        "engine_version": ENGINE_VERSION,
        "feature_columns": list(FEATURES),
        "model_parameters": MODEL_PARAMS,
        "splits": {name: [start.isoformat(), end.isoformat()] for name, (start, end) in SPLITS.items()},
        "primary_cost_bps": PRIMARY_COST_BPS,
        "same_path_costs_bps": list(COSTS_BPS),
        "one_model_family": True,
        "one_economic_decision_rule": True,
        "one_global_slot": True,
        "no_elapsed_time_liquidation": True,
        "prohibited_years": [2024, 2025, 2026],
    }, indent=2, sort_keys=True) + "\n")
    return result


def self_test() -> None:
    assert ceil_minute(61) == 120
    assert bybit_month_url("BTCUSDT", 2022, 2).endswith("BTCUSDT_1_2022-02-01_2022-02-28.csv.gz")
    assert split_for_timestamp(int(pd.Timestamp("2022-08-01", tz="UTC").timestamp())) == "confirmation"
    events = [
        SourceEvent("a", "USDT", "MINT", 100.0, 10, 100, 200),
        SourceEvent("b", "USDC", "MINT", 50.0, 20, 100, 210),
        SourceEvent("c", "USDT", "BURN", 25.0, 30, 3700, 3800),
    ]
    prior = prior_event_features(events)
    assert prior["a"] == (0.0, 0.0)
    assert prior["b"] == (0.0, 0.0)
    assert prior["c"][1] > 0
    candidates = [
        CandidateAction("a", "BTCUSDT", 100, 1, 0.2, 0.7, 110.0, 90.0, 100.0, 200, 1, False, False, "confirmation"),
        CandidateAction("b", "ETHUSDT", 100, 1, 0.1, 0.7, 110.0, 90.0, 100.0, 150, 1, False, False, "confirmation"),
        CandidateAction("c", "BTCUSDT", 160, 1, 0.3, 0.7, 110.0, 90.0, 100.0, 180, 1, False, False, "confirmation"),
        CandidateAction("d", "BTCUSDT", 260, -1, 0.2, 0.3, 110.0, 90.0, 100.0, 300, 0, False, False, "confirmation"),
    ]
    selected = arbitrate_candidates(candidates)
    assert [item.event_id for item in selected] == ["a", "d"]
    trades, summary = replay(
        candidates, 24.0, pd.Timestamp("2022-07-01", tz="UTC"), pd.Timestamp("2023-01-01", tz="UTC")
    )
    assert len(trades) == 2
    assert summary["total_return"] > 0
    print("stablecoin model self-test passed")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-dir", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--cache", type=Path, default=Path("/tmp/ml-stablecoin-model"))
    parser.add_argument("--self-test", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.self_test:
        self_test()
        return 0
    if args.source_dir is None or args.output is None:
        raise SystemExit("--source-dir and --output are required")
    result = run(args.source_dir, args.output, args.cache)
    print(json.dumps(result, indent=2, sort_keys=True, allow_nan=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
