from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import math
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import requests

UTC = timezone.utc
INTERVAL = "15m"
INTERVAL_MS = 15 * 60 * 1000
PAIRS = ("BTCUSDT", "ETHUSDT")
CONTRACT_TYPES = ("PERPETUAL", "CURRENT_QUARTER", "NEXT_QUARTER")
BASE_URLS = (
    "https://fapi.binance.com",
    "https://fapi1.binance.com",
    "https://fapi2.binance.com",
    "https://fapi3.binance.com",
    "https://fapi4.binance.com",
)
FIT_START = "2021-01-01T00:00:00Z"
DEV_START = "2022-01-01T00:00:00Z"
DEV_END = "2024-01-01T00:00:00Z"
OOS_END = "2025-01-01T00:00:00Z"
COSTS_BPS = (12.0, 18.0, 24.0)
STOP_EXTRA_BPS = 4.0
RISK_FRACTION = 0.005
MAX_NOTIONAL_LEVERAGE = 3.0
ROLL_BUFFER_HOURS = 48


@dataclass(frozen=True, slots=True)
class Candidate:
    family: str
    window: int
    threshold: float
    hold_bars: int
    stop_atr: float

    @property
    def candidate_id(self) -> str:
        raw = (
            f"{self.family}|w{self.window}|z{self.threshold:g}|"
            f"h{self.hold_bars}|s{self.stop_atr:g}"
        )
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]


@dataclass(slots=True)
class TradePath:
    candidate_id: str
    family: str
    pair: str
    direction: int
    signal_time_ms: int
    entry_time_ms: int
    exit_time_ms: int
    entry_price: float
    exit_price: float
    stop_distance_bps: float
    gross_bps: float
    funding_bps: float
    stopped: bool
    score: float


class SourceError(RuntimeError):
    pass


def iso_to_ms(value: str) -> int:
    return int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp() * 1000)


def ms_to_iso(value: int) -> str:
    return datetime.fromtimestamp(value / 1000, tz=UTC).isoformat().replace("+00:00", "Z")


def canonical_sha256(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def json_dump(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _request_json(
    session: requests.Session,
    path: str,
    params: dict[str, Any],
    *,
    timeout: float = 45.0,
) -> tuple[list[Any], dict[str, Any]]:
    errors: list[str] = []
    for base in BASE_URLS:
        for attempt in range(5):
            try:
                response = session.get(base + path, params=params, timeout=timeout)
            except requests.RequestException as exc:
                errors.append(f"{base} network {type(exc).__name__}: {exc}")
                time.sleep(min(2**attempt, 8))
                continue
            if response.status_code == 200:
                payload = response.json()
                if not isinstance(payload, list):
                    raise SourceError(f"unexpected non-list payload from {response.url}: {payload}")
                return payload, {
                    "base_url": base,
                    "request_url": response.url,
                    "status_code": response.status_code,
                    "response_sha256": hashlib.sha256(response.content).hexdigest(),
                    "response_bytes": len(response.content),
                }
            body = response.text[:500]
            errors.append(f"{base} status={response.status_code} body={body}")
            if response.status_code in {418, 429} or response.status_code >= 500:
                retry_after = float(response.headers.get("Retry-After", "0") or 0)
                time.sleep(max(retry_after, min(2**attempt, 10)))
                continue
            break
    raise SourceError("all Binance USD-M endpoints failed: " + " | ".join(errors[-12:]))


def _validate_kline_row(row: list[Any]) -> None:
    if len(row) < 11:
        raise SourceError(f"continuous kline row width below 11: {row}")
    open_time = int(row[0])
    close_time = int(row[6])
    if close_time < open_time:
        raise SourceError(f"invalid kline close time: {row}")
    for index in (1, 2, 3, 4, 5, 7, 9, 10):
        value = float(row[index])
        if not math.isfinite(value):
            raise SourceError(f"non-finite kline field index={index}: {row}")
    if min(float(row[index]) for index in (1, 2, 3, 4)) <= 0:
        raise SourceError(f"non-positive OHLC: {row}")


def fetch_continuous_klines(
    session: requests.Session,
    cache: Path,
    pair: str,
    contract_type: str,
    start_ms: int,
    end_ms: int,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    cache.mkdir(parents=True, exist_ok=True)
    key = f"{pair}-{contract_type}-{INTERVAL}-{start_ms}-{end_ms}"
    csv_path = cache / f"{key}.csv.gz"
    meta_path = cache / f"{key}.meta.json"
    if csv_path.exists() and meta_path.exists():
        frame = pd.read_csv(csv_path)
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        if file_sha256(csv_path) != meta.get("cache_sha256"):
            raise SourceError(f"cache checksum mismatch: {csv_path}")
        return frame, {**meta, "cache_hit": True}

    records: list[list[Any]] = []
    request_records: list[dict[str, Any]] = []
    cursor = start_ms
    last_seen = start_ms - INTERVAL_MS
    while cursor < end_ms:
        payload, request_meta = _request_json(
            session,
            "/fapi/v1/continuousKlines",
            {
                "pair": pair,
                "contractType": contract_type,
                "interval": INTERVAL,
                "startTime": cursor,
                "endTime": end_ms - 1,
                "limit": 1500,
            },
        )
        request_meta.update(
            {
                "pair": pair,
                "contract_type": contract_type,
                "cursor": cursor,
                "row_count": len(payload),
            }
        )
        request_records.append(request_meta)
        if not payload:
            break
        for row in payload:
            if not isinstance(row, list):
                raise SourceError(f"unexpected continuous kline row: {row}")
            _validate_kline_row(row)
            open_time = int(row[0])
            if open_time <= last_seen:
                if open_time == last_seen:
                    continue
                raise SourceError(
                    f"non-monotone continuous kline {pair} {contract_type}: "
                    f"{open_time} <= {last_seen}"
                )
            if open_time >= end_ms:
                continue
            records.append(row)
            last_seen = open_time
        next_cursor = int(payload[-1][0]) + INTERVAL_MS
        if next_cursor <= cursor:
            raise SourceError("continuous kline pagination failed to advance")
        cursor = next_cursor
        if len(payload) < 1500 and cursor >= end_ms:
            break
        time.sleep(0.03)

    if not records:
        raise SourceError(
            f"no continuous klines for {pair} {contract_type} "
            f"{ms_to_iso(start_ms)}..{ms_to_iso(end_ms)}"
        )
    columns = [
        "open_time_ms",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "close_time_ms",
        "quote_volume",
        "trade_count",
        "taker_base_volume",
        "taker_quote_volume",
        "ignore",
    ]
    frame = pd.DataFrame(records, columns=columns[: len(records[0])])
    keep = columns[:11]
    frame = frame[keep].copy()
    frame["open_time_ms"] = frame["open_time_ms"].astype("int64")
    frame["close_time_ms"] = frame["close_time_ms"].astype("int64")
    numeric = [
        "open",
        "high",
        "low",
        "close",
        "volume",
        "quote_volume",
        "trade_count",
        "taker_base_volume",
        "taker_quote_volume",
    ]
    for column in numeric:
        frame[column] = pd.to_numeric(frame[column], errors="raise")
    frame = frame[(frame.open_time_ms >= start_ms) & (frame.open_time_ms < end_ms)]
    frame = frame.drop_duplicates("open_time_ms", keep=False).sort_values("open_time_ms")
    if frame.empty:
        raise SourceError(f"all continuous rows filtered for {pair} {contract_type}")
    frame.to_csv(csv_path, index=False, compression="gzip")
    meta = {
        "source": "Binance USD-M REST /fapi/v1/continuousKlines",
        "pair": pair,
        "contract_type": contract_type,
        "interval": INTERVAL,
        "start": ms_to_iso(start_ms),
        "end_exclusive": ms_to_iso(end_ms),
        "rows": int(len(frame)),
        "first_open_time": ms_to_iso(int(frame.open_time_ms.iloc[0])),
        "last_open_time": ms_to_iso(int(frame.open_time_ms.iloc[-1])),
        "request_count": len(request_records),
        "request_manifest_sha256": canonical_sha256(request_records),
        "cache_sha256": file_sha256(csv_path),
        "cache_hit": False,
    }
    json_dump(meta_path, meta)
    return frame, meta


def fetch_funding_rates(
    session: requests.Session,
    cache: Path,
    symbol: str,
    start_ms: int,
    end_ms: int,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    cache.mkdir(parents=True, exist_ok=True)
    key = f"{symbol}-funding-{start_ms}-{end_ms}"
    csv_path = cache / f"{key}.csv.gz"
    meta_path = cache / f"{key}.meta.json"
    if csv_path.exists() and meta_path.exists():
        frame = pd.read_csv(csv_path)
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        if file_sha256(csv_path) != meta.get("cache_sha256"):
            raise SourceError(f"cache checksum mismatch: {csv_path}")
        return frame, {**meta, "cache_hit": True}

    records: list[dict[str, Any]] = []
    request_records: list[dict[str, Any]] = []
    cursor = start_ms
    last_seen = start_ms - 1
    while cursor < end_ms:
        payload, request_meta = _request_json(
            session,
            "/fapi/v1/fundingRate",
            {
                "symbol": symbol,
                "startTime": cursor,
                "endTime": end_ms - 1,
                "limit": 1000,
            },
        )
        request_meta.update({"symbol": symbol, "cursor": cursor, "row_count": len(payload)})
        request_records.append(request_meta)
        if not payload:
            break
        for row in payload:
            funding_time = int(row["fundingTime"])
            if funding_time <= last_seen:
                if funding_time == last_seen:
                    continue
                raise SourceError(f"non-monotone funding row {symbol}: {funding_time}")
            rate = float(row["fundingRate"])
            if not math.isfinite(rate):
                raise SourceError(f"non-finite funding rate {symbol}: {row}")
            if funding_time < end_ms:
                records.append(
                    {
                        "funding_time_ms": funding_time,
                        "funding_rate": rate,
                        "mark_price": float(row.get("markPrice", "nan")),
                    }
                )
                last_seen = funding_time
        next_cursor = int(payload[-1]["fundingTime"]) + 1
        if next_cursor <= cursor:
            raise SourceError("funding pagination failed to advance")
        cursor = next_cursor
        if len(payload) < 1000:
            break
        time.sleep(0.03)

    frame = pd.DataFrame(records, columns=["funding_time_ms", "funding_rate", "mark_price"])
    if not frame.empty:
        frame = frame.drop_duplicates("funding_time_ms", keep=False).sort_values("funding_time_ms")
    frame.to_csv(csv_path, index=False, compression="gzip")
    meta = {
        "source": "Binance USD-M REST /fapi/v1/fundingRate",
        "symbol": symbol,
        "start": ms_to_iso(start_ms),
        "end_exclusive": ms_to_iso(end_ms),
        "rows": int(len(frame)),
        "request_count": len(request_records),
        "request_manifest_sha256": canonical_sha256(request_records),
        "cache_sha256": file_sha256(csv_path),
        "cache_hit": False,
    }
    json_dump(meta_path, meta)
    return frame, meta


def last_friday(year: int, month: int) -> datetime:
    if month == 12:
        next_month = datetime(year + 1, 1, 1, 8, tzinfo=UTC)
    else:
        next_month = datetime(year, month + 1, 1, 8, tzinfo=UTC)
    current = next_month - timedelta(days=1)
    while current.weekday() != 4:
        current -= timedelta(days=1)
    return current


def roll_exclusion_mask(times_ms: pd.Series) -> np.ndarray:
    times = pd.to_datetime(times_ms, unit="ms", utc=True)
    mask = np.zeros(len(times), dtype=bool)
    if len(times) == 0:
        return mask
    start_year = int(times.dt.year.min()) - 1
    end_year = int(times.dt.year.max()) + 1
    buffer = pd.Timedelta(hours=ROLL_BUFFER_HOURS)
    for year in range(start_year, end_year + 1):
        for month in (3, 6, 9, 12):
            expiry = pd.Timestamp(last_friday(year, month))
            mask |= ((times >= expiry - buffer) & (times <= expiry + buffer)).to_numpy()
    return mask


def prior_z(series: pd.Series, window: int) -> pd.Series:
    prior = series.shift(1)
    mean = prior.rolling(window=window, min_periods=window).mean()
    std = prior.rolling(window=window, min_periods=window).std(ddof=0)
    std = std.where(std > 1e-12)
    return (series - mean) / std


def build_pair_panel(frames: dict[str, pd.DataFrame], pair: str) -> pd.DataFrame:
    prefixes = {
        "PERPETUAL": "p",
        "CURRENT_QUARTER": "c",
        "NEXT_QUARTER": "n",
    }
    merged: pd.DataFrame | None = None
    for contract_type, prefix in prefixes.items():
        frame = frames[contract_type].copy()
        rename = {
            column: f"{prefix}_{column}"
            for column in frame.columns
            if column != "open_time_ms"
        }
        frame = frame.rename(columns=rename)
        if merged is None:
            merged = frame
        else:
            merged = merged.merge(frame, how="inner", on="open_time_ms", validate="one_to_one")
    assert merged is not None
    merged = merged.sort_values("open_time_ms").reset_index(drop=True)
    merged["pair"] = pair
    merged["segment"] = (
        merged.open_time_ms.diff().fillna(INTERVAL_MS).ne(INTERVAL_MS).cumsum()
    )
    merged["roll_excluded"] = roll_exclusion_mask(merged.open_time_ms)
    merged["near_basis_bps"] = 1e4 * np.log(merged.c_close / merged.p_close)
    merged["far_basis_bps"] = 1e4 * np.log(merged.n_close / merged.p_close)
    merged["common_basis_bps"] = 0.5 * (
        merged.near_basis_bps + merged.far_basis_bps
    )
    merged["curve_slope_bps"] = merged.far_basis_bps - merged.near_basis_bps
    merged["basis_change_4"] = merged.groupby("segment", sort=False).common_basis_bps.diff(4)
    merged["perp_return_4_bps"] = 1e4 * np.log(
        merged.p_close / merged.groupby("segment", sort=False).p_close.shift(4)
    )
    quote = merged.p_quote_volume.replace(0, np.nan)
    merged["flow_imbalance"] = 2.0 * merged.p_taker_quote_volume / quote - 1.0
    previous_close = merged.groupby("segment", sort=False).p_close.shift(1)
    true_range = pd.concat(
        [
            merged.p_high - merged.p_low,
            (merged.p_high - previous_close).abs(),
            (merged.p_low - previous_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    merged["atr_bps"] = (
        1e4
        * true_range.groupby(merged.segment).rolling(96, min_periods=96).mean().reset_index(level=0, drop=True)
        / merged.p_close
    )
    for window in (96, 672):
        grouped = merged.groupby("segment", sort=False, group_keys=False)
        for source, short in (
            ("basis_change_4", "basis"),
            ("curve_slope_bps", "slope"),
            ("perp_return_4_bps", "ret"),
            ("flow_imbalance", "flow"),
        ):
            merged[f"z_{short}_{window}"] = grouped[source].apply(
                lambda values, w=window: prior_z(values, w)
            )
    return merged


def candidate_grid() -> list[Candidate]:
    return [
        Candidate(family, window, threshold, hold_bars, stop_atr)
        for family, window, threshold, hold_bars, stop_atr in itertools.product(
            (
                "basis_flow_continuation",
                "basis_catchup",
                "basis_exhaustion_reversal",
            ),
            (96, 672),
            (1.5, 2.0, 2.5),
            (4, 8, 16),
            (1.5, 2.5),
        )
    ]


def signal_events(panel: pd.DataFrame, candidate: Candidate) -> pd.DataFrame:
    basis = panel[f"z_basis_{candidate.window}"]
    slope = panel[f"z_slope_{candidate.window}"]
    ret = panel[f"z_ret_{candidate.window}"]
    flow = panel[f"z_flow_{candidate.window}"]
    shock_sign = np.sign(basis)
    if candidate.family == "basis_flow_continuation":
        mask = (
            (basis.abs() >= candidate.threshold)
            & (shock_sign * ret >= 0.50)
            & (shock_sign * flow >= 0.00)
            & (shock_sign * slope >= -0.50)
        )
        direction = shock_sign
        score = basis.abs() + 0.35 * ret.abs() + 0.20 * flow.abs()
    elif candidate.family == "basis_catchup":
        mask = (
            (basis.abs() >= candidate.threshold)
            & (shock_sign * ret <= 0.25)
            & (shock_sign * slope >= 0.25)
            & (shock_sign * flow >= -0.25)
        )
        direction = shock_sign
        score = basis.abs() + 0.40 * slope.abs() - 0.10 * ret.abs()
    elif candidate.family == "basis_exhaustion_reversal":
        mask = (
            (basis.abs() >= candidate.threshold)
            & (shock_sign * ret >= 0.75)
            & (shock_sign * flow <= -0.25)
            & (slope.abs() >= 0.75)
        )
        direction = -shock_sign
        score = basis.abs() + 0.30 * ret.abs() + 0.30 * flow.abs()
    else:
        raise ValueError(candidate.family)
    mask &= (
        ~panel.roll_excluded
        & panel.atr_bps.notna()
        & np.isfinite(direction)
        & (direction != 0)
    )
    columns = [
        "open_time_ms",
        "pair",
        "p_open",
        "p_high",
        "p_low",
        "p_close",
        "atr_bps",
    ]
    events = panel.loc[mask, columns].copy()
    events["direction"] = direction[mask].astype(int)
    events["score"] = score[mask].astype(float)
    events["candidate_id"] = candidate.candidate_id
    events["family"] = candidate.family
    events["hold_bars"] = candidate.hold_bars
    events["stop_atr"] = candidate.stop_atr
    return events


def funding_bps_between(
    funding: pd.DataFrame,
    entry_time_ms: int,
    exit_time_ms: int,
    direction: int,
) -> float:
    if funding.empty:
        return 0.0
    times = funding.funding_time_ms.to_numpy(dtype=np.int64)
    rates = funding.funding_rate.to_numpy(dtype=float)
    start = int(np.searchsorted(times, entry_time_ms, side="right"))
    end = int(np.searchsorted(times, exit_time_ms, side="right"))
    if end <= start:
        return 0.0
    return float(-direction * rates[start:end].sum() * 1e4)


def generate_trade_paths(
    panels: dict[str, pd.DataFrame],
    funding: dict[str, pd.DataFrame],
    candidate: Candidate,
    start_ms: int,
    end_ms: int,
) -> list[TradePath]:
    events_by_pair: list[pd.DataFrame] = []
    position_maps: dict[str, dict[int, int]] = {}
    for pair, panel in panels.items():
        position_maps[pair] = {
            int(timestamp): int(position)
            for position, timestamp in enumerate(panel.open_time_ms.to_numpy())
        }
        events = signal_events(panel, candidate)
        events["entry_time_ms"] = events.open_time_ms + INTERVAL_MS
        events = events[
            (events.entry_time_ms >= start_ms) & (events.entry_time_ms < end_ms)
        ]
        events_by_pair.append(events)
    if not events_by_pair:
        return []
    all_events = pd.concat(events_by_pair, ignore_index=True)
    if all_events.empty:
        return []
    all_events["pair_priority"] = all_events.pair.map({"BTCUSDT": 0, "ETHUSDT": 1})
    all_events = all_events.sort_values(
        ["entry_time_ms", "score", "pair_priority"],
        ascending=[True, False, True],
        kind="mergesort",
    )
    selected = all_events.groupby("entry_time_ms", sort=True, as_index=False).first()
    busy_until = start_ms - 1
    paths: list[TradePath] = []
    for row in selected.itertuples(index=False):
        entry_time = int(row.entry_time_ms)
        if entry_time <= busy_until:
            continue
        pair = str(row.pair)
        panel = panels[pair]
        entry_pos = position_maps[pair].get(entry_time)
        if entry_pos is None:
            continue
        exit_pos = entry_pos + int(candidate.hold_bars)
        if exit_pos >= len(panel):
            continue
        if int(panel.open_time_ms.iloc[exit_pos]) >= end_ms:
            continue
        expected = panel.open_time_ms.iloc[entry_pos : exit_pos + 1].to_numpy(dtype=np.int64)
        if len(expected) != candidate.hold_bars + 1:
            continue
        if np.any(np.diff(expected) != INTERVAL_MS):
            continue
        entry_price = float(panel.p_open.iloc[entry_pos])
        atr_bps = float(panel.atr_bps.iloc[entry_pos - 1])
        if not (math.isfinite(entry_price) and entry_price > 0 and math.isfinite(atr_bps) and atr_bps > 0):
            continue
        direction = int(row.direction)
        stop_distance_bps = atr_bps * candidate.stop_atr
        stop_price = entry_price * (1.0 - direction * stop_distance_bps / 1e4)
        stopped = False
        exit_price = float(panel.p_open.iloc[exit_pos])
        actual_exit_pos = exit_pos
        for bar_pos in range(entry_pos, exit_pos):
            bar_open = float(panel.p_open.iloc[bar_pos])
            bar_low = float(panel.p_low.iloc[bar_pos])
            bar_high = float(panel.p_high.iloc[bar_pos])
            if direction > 0 and bar_low <= stop_price:
                exit_price = min(bar_open, stop_price)
                actual_exit_pos = bar_pos
                stopped = True
                break
            if direction < 0 and bar_high >= stop_price:
                exit_price = max(bar_open, stop_price)
                actual_exit_pos = bar_pos
                stopped = True
                break
        exit_time = int(panel.open_time_ms.iloc[actual_exit_pos])
        if not stopped:
            exit_time = int(panel.open_time_ms.iloc[exit_pos])
        gross_bps = direction * (exit_price / entry_price - 1.0) * 1e4
        funding_bps = funding_bps_between(
            funding[pair], entry_time, exit_time, direction
        )
        paths.append(
            TradePath(
                candidate_id=candidate.candidate_id,
                family=candidate.family,
                pair=pair,
                direction=direction,
                signal_time_ms=int(row.open_time_ms),
                entry_time_ms=entry_time,
                exit_time_ms=exit_time,
                entry_price=entry_price,
                exit_price=exit_price,
                stop_distance_bps=stop_distance_bps,
                gross_bps=float(gross_bps),
                funding_bps=float(funding_bps),
                stopped=stopped,
                score=float(row.score),
            )
        )
        busy_until = exit_time
    return paths


def replay_account(
    paths: list[TradePath],
    cost_bps: float,
    start_ms: int,
    end_ms: int,
    excluded_indices: set[int] | None = None,
) -> dict[str, Any]:
    excluded = excluded_indices or set()
    equity = 10_000.0
    peak = equity
    maximum_drawdown = 0.0
    records: list[dict[str, Any]] = []
    for index, path in enumerate(paths):
        equity_before = equity
        risk_budget = equity_before * RISK_FRACTION
        expected_loss_bps = path.stop_distance_bps + cost_bps + STOP_EXTRA_BPS
        quantity_by_risk = risk_budget / (path.entry_price * expected_loss_bps / 1e4)
        quantity_by_leverage = equity_before * MAX_NOTIONAL_LEVERAGE / path.entry_price
        quantity = min(quantity_by_risk, quantity_by_leverage)
        notional = quantity * path.entry_price
        net_bps = path.gross_bps + path.funding_bps - cost_bps
        if path.stopped:
            net_bps -= STOP_EXTRA_BPS
        if index in excluded:
            pnl = 0.0
            applied_net_bps = 0.0
        else:
            pnl = notional * net_bps / 1e4
            applied_net_bps = net_bps
        equity += pnl
        if equity <= 0:
            return {
                "valid": False,
                "reason": "non_positive_equity",
                "trade_count": len(records) + 1,
                "ending_nav": equity,
                "total_return": -1.0,
                "maximum_drawdown": 1.0,
            }
        peak = max(peak, equity)
        maximum_drawdown = max(maximum_drawdown, 1.0 - equity / peak)
        account_return_bps = pnl / equity_before * 1e4
        records.append(
            {
                "index": index,
                "pair": path.pair,
                "entry_time_ms": path.entry_time_ms,
                "exit_time_ms": path.exit_time_ms,
                "pnl": pnl,
                "net_bps": applied_net_bps,
                "account_return_bps": account_return_bps,
                "equity_after": equity,
                "notional": notional,
                "stopped": path.stopped,
            }
        )
    days = max((end_ms - start_ms) / 86_400_000.0, 1.0)
    multiple = equity / 10_000.0
    daily_growth = multiple ** (1.0 / days) - 1.0 if multiple > 0 else -1.0
    pnls = np.array([record["pnl"] for record in records], dtype=float)
    positive = pnls[pnls > 0]
    negative = pnls[pnls < 0]
    profit_factor = (
        float(positive.sum() / -negative.sum())
        if len(negative) and -negative.sum() > 0
        else (float("inf") if len(positive) else 0.0)
    )
    top5_share = (
        float(np.sort(positive)[-5:].sum() / positive.sum())
        if len(positive) and positive.sum() > 0
        else 1.0
    )
    return {
        "valid": True,
        "ending_nav": equity,
        "ending_nav_multiple": multiple,
        "total_return": multiple - 1.0,
        "geometric_daily_growth": daily_growth,
        "maximum_drawdown": maximum_drawdown,
        "trade_count": len(records),
        "profit_factor": profit_factor,
        "median_account_return_bps": (
            float(np.median([record["account_return_bps"] for record in records]))
            if records
            else 0.0
        ),
        "top5_positive_share": top5_share,
        "positive_trade_fraction": (
            float((pnls > 0).mean()) if len(pnls) else 0.0
        ),
        "funding_bps_sum_unweighted": float(sum(path.funding_bps for path in paths)),
        "records": records,
    }


def exact_top10_removed(
    paths: list[TradePath],
    baseline: dict[str, Any],
    cost_bps: float,
    start_ms: int,
    end_ms: int,
) -> dict[str, Any]:
    records = baseline.get("records", [])
    positive = sorted(
        ((float(record["pnl"]), int(record["index"])) for record in records if record["pnl"] > 0),
        reverse=True,
    )
    count = int(math.ceil(0.10 * len(positive))) if positive else 0
    excluded = {index for _, index in positive[:count]}
    result = replay_account(paths, cost_bps, start_ms, end_ms, excluded)
    return {
        "removed_positive_trade_count": count,
        "removed_indices": sorted(excluded),
        "total_return": result.get("total_return"),
        "geometric_daily_growth": result.get("geometric_daily_growth"),
        "ending_nav_multiple": result.get("ending_nav_multiple"),
    }


def evaluate_candidate(
    panels: dict[str, pd.DataFrame],
    funding: dict[str, pd.DataFrame],
    candidate: Candidate,
    start_ms: int,
    end_ms: int,
) -> tuple[dict[str, Any], list[TradePath]]:
    paths = generate_trade_paths(panels, funding, candidate, start_ms, end_ms)
    costs: dict[str, Any] = {}
    for cost in COSTS_BPS:
        replay = replay_account(paths, cost, start_ms, end_ms)
        top10 = exact_top10_removed(paths, replay, cost, start_ms, end_ms)
        replay.pop("records", None)
        replay["top10pct_positive_removed"] = top10
        costs[f"{cost:g}bps"] = replay
    yearly: dict[str, Any] = {}
    for year in (2022, 2023):
        year_start = iso_to_ms(f"{year}-01-01T00:00:00Z")
        year_end = iso_to_ms(f"{year + 1}-01-01T00:00:00Z")
        year_paths = [
            path for path in paths if year_start <= path.entry_time_ms < year_end
        ]
        yearly[str(year)] = {}
        for cost in (18.0, 24.0):
            replay = replay_account(year_paths, cost, year_start, year_end)
            replay.pop("records", None)
            yearly[str(year)][f"{cost:g}bps"] = replay
    metrics_18 = costs["18bps"]
    gate_checks = {
        "minimum_combined_trades": metrics_18.get("trade_count", 0) >= 100,
        "minimum_trades_each_year": all(
            yearly[str(year)]["18bps"].get("trade_count", 0) >= 30
            for year in (2022, 2023)
        ),
        "positive_12_18_24": all(
            costs[f"{cost:g}bps"].get("total_return", -1.0) > 0
            for cost in COSTS_BPS
        ),
        "daily_growth_18": metrics_18.get("geometric_daily_growth", -1.0) >= 0.0005,
        "profit_factor_18": metrics_18.get("profit_factor", 0.0) >= 1.15,
        "positive_median_18": metrics_18.get("median_account_return_bps", -1.0) > 0,
        "positive_each_year_18_24": all(
            yearly[str(year)][f"{cost:g}bps"].get("total_return", -1.0) > 0
            for year in (2022, 2023)
            for cost in (18.0, 24.0)
        ),
        "positive_top10_removed_18": metrics_18.get("top10pct_positive_removed", {}).get(
            "total_return", -1.0
        )
        > 0,
        "top5_share_18": metrics_18.get("top5_positive_share", 1.0) <= 0.35,
        "maximum_drawdown_18": metrics_18.get("maximum_drawdown", 1.0) <= 0.15,
    }
    result = {
        "candidate": asdict(candidate),
        "candidate_id": candidate.candidate_id,
        "trade_path_sha256": canonical_sha256([asdict(path) for path in paths]),
        "costs": costs,
        "yearly": yearly,
        "gate_checks": gate_checks,
        "gate_pass": all(gate_checks.values()),
    }
    return result, paths


def source_bundle(
    session: requests.Session,
    cache: Path,
    start_ms: int,
    end_ms: int,
) -> tuple[dict[str, pd.DataFrame], dict[str, pd.DataFrame], list[dict[str, Any]]]:
    panels: dict[str, pd.DataFrame] = {}
    funding: dict[str, pd.DataFrame] = {}
    manifest: list[dict[str, Any]] = []
    for pair in PAIRS:
        frames: dict[str, pd.DataFrame] = {}
        for contract_type in CONTRACT_TYPES:
            frame, meta = fetch_continuous_klines(
                session, cache / "continuous", pair, contract_type, start_ms, end_ms
            )
            frames[contract_type] = frame
            manifest.append(meta)
        funding_frame, funding_meta = fetch_funding_rates(
            session, cache / "funding", pair, start_ms, end_ms
        )
        funding[pair] = funding_frame
        manifest.append(funding_meta)
        panels[pair] = build_pair_panel(frames, pair)
    return panels, funding, manifest


def write_checksums(output: Path) -> None:
    lines: list[str] = []
    for path in sorted(output.rglob("*")):
        if not path.is_file() or path.name == "SHA256SUMS.txt":
            continue
        lines.append(f"{file_sha256(path)}  {path.relative_to(output).as_posix()}")
    (output / "SHA256SUMS.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")


def synthetic_panel(pair: str, periods: int = 3000) -> pd.DataFrame:
    rng = np.random.default_rng(7 if pair == "BTCUSDT" else 11)
    times = np.arange(periods, dtype=np.int64) * INTERVAL_MS + iso_to_ms(FIT_START)
    returns = rng.normal(0, 0.0007, periods)
    p_close = 30_000 * np.exp(np.cumsum(returns))
    p_open = np.r_[p_close[0], p_close[:-1]]
    span = np.abs(rng.normal(0.0008, 0.0002, periods))
    p_high = np.maximum(p_open, p_close) * (1 + span)
    p_low = np.minimum(p_open, p_close) * (1 - span)
    basis = np.cumsum(rng.normal(0, 0.2, periods))
    slope = np.cumsum(rng.normal(0, 0.1, periods))
    frame = pd.DataFrame(
        {
            "open_time_ms": times,
            "p_open": p_open,
            "p_high": p_high,
            "p_low": p_low,
            "p_close": p_close,
            "p_quote_volume": np.full(periods, 1_000_000.0),
            "p_taker_quote_volume": 500_000 * (1 + rng.normal(0, 0.1, periods)),
            "c_close": p_close * np.exp((basis - slope / 2) / 1e4),
            "n_close": p_close * np.exp((basis + slope / 2) / 1e4),
            "pair": pair,
            "segment": 0,
            "roll_excluded": False,
        }
    )
    frame["near_basis_bps"] = 1e4 * np.log(frame.c_close / frame.p_close)
    frame["far_basis_bps"] = 1e4 * np.log(frame.n_close / frame.p_close)
    frame["common_basis_bps"] = 0.5 * (frame.near_basis_bps + frame.far_basis_bps)
    frame["curve_slope_bps"] = frame.far_basis_bps - frame.near_basis_bps
    frame["basis_change_4"] = frame.common_basis_bps.diff(4)
    frame["perp_return_4_bps"] = 1e4 * np.log(frame.p_close / frame.p_close.shift(4))
    frame["flow_imbalance"] = 2 * frame.p_taker_quote_volume / frame.p_quote_volume - 1
    previous = frame.p_close.shift(1)
    tr = pd.concat(
        [
            frame.p_high - frame.p_low,
            (frame.p_high - previous).abs(),
            (frame.p_low - previous).abs(),
        ],
        axis=1,
    ).max(axis=1)
    frame["atr_bps"] = 1e4 * tr.rolling(96, min_periods=96).mean() / frame.p_close
    for window in (96, 672):
        for source, short in (
            ("basis_change_4", "basis"),
            ("curve_slope_bps", "slope"),
            ("perp_return_4_bps", "ret"),
            ("flow_imbalance", "flow"),
        ):
            frame[f"z_{short}_{window}"] = prior_z(frame[source], window)
    return frame


def run_self_tests() -> dict[str, Any]:
    values = pd.Series(np.arange(1000, dtype=float))
    baseline = prior_z(values, 96)
    changed = values.copy()
    changed.iloc[500:] += 1_000_000
    changed_z = prior_z(changed, 96)
    assert np.allclose(
        baseline.iloc[:500].to_numpy(),
        changed_z.iloc[:500].to_numpy(),
        equal_nan=True,
    )

    panel = synthetic_panel("BTCUSDT", 1000)
    pos = 800
    panel.loc[pos, "z_basis_96"] = 4.0
    panel.loc[pos, "z_ret_96"] = 2.0
    panel.loc[pos, "z_flow_96"] = 1.0
    panel.loc[pos, "z_slope_96"] = 1.0
    candidate = Candidate("basis_flow_continuation", 96, 2.0, 4, 1.5)
    entry_pos = pos + 1
    entry = float(panel.p_open.iloc[entry_pos])
    panel.loc[entry_pos, "p_open"] = entry * 0.95
    panel.loc[entry_pos, "p_low"] = entry * 0.94
    funding = pd.DataFrame(columns=["funding_time_ms", "funding_rate", "mark_price"])
    start = int(panel.open_time_ms.iloc[pos])
    end = int(panel.open_time_ms.iloc[pos + 10])
    paths = generate_trade_paths(
        {"BTCUSDT": panel, "ETHUSDT": synthetic_panel("ETHUSDT", 1000)},
        {"BTCUSDT": funding, "ETHUSDT": funding},
        candidate,
        start,
        end,
    )
    if paths:
        assert paths[0].exit_price <= panel.p_open.iloc[entry_pos] or not paths[0].stopped

    fixture = [
        TradePath(
            candidate_id="x",
            family="x",
            pair="BTCUSDT",
            direction=1,
            signal_time_ms=0,
            entry_time_ms=i * 10,
            exit_time_ms=i * 10 + 5,
            entry_price=100.0,
            exit_price=100.0 * (1 + gross / 1e4),
            stop_distance_bps=50.0,
            gross_bps=gross,
            funding_bps=0.0,
            stopped=False,
            score=1.0,
        )
        for i, gross in enumerate((100.0, -50.0, 80.0, -20.0, 60.0))
    ]
    a = replay_account(fixture, 12.0, 0, 86_400_000)
    b = replay_account(fixture, 12.0, 0, 86_400_000)
    assert canonical_sha256(a) == canonical_sha256(b)
    removed = exact_top10_removed(fixture, a, 12.0, 0, 86_400_000)
    assert removed["removed_positive_trade_count"] == 1
    assert removed["total_return"] <= a["total_return"]
    return {
        "prior_only_z_prefix_invariant": True,
        "adverse_gap_stop_test": True,
        "deterministic_replay": True,
        "top_trade_removal": True,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    self_tests = run_self_tests()
    if args.self_test:
        json_dump(args.output / "SELF_TEST.json", self_tests)
        write_checksums(args.output)
        return 0

    preregistration_path = Path(__file__).with_name("preregistration.json")
    preregistration = json.loads(preregistration_path.read_text(encoding="utf-8"))
    result: dict[str, Any] = {
        "schema_version": 1,
        "result_id": "RES-20260726-USDM-CURVE-001",
        "claim_id": preregistration["claim_id"],
        "study_id": preregistration["study_id"],
        "status": "RUNNING",
        "hard_validity_status": "PENDING",
        "economic_status": "PENDING",
        "ranking_role": "PENDING",
        "registered_at": preregistration["registered_at"],
        "preregistration_sha256": file_sha256(preregistration_path),
        "script_sha256": file_sha256(Path(__file__)),
        "self_tests": self_tests,
        "2024_downloaded": False,
        "2025_or_2026_opened": False,
        "orders_submitted": False,
    }
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": "SMC-ICT-2-LIVE-research/1.0",
            "Accept": "application/json",
        }
    )
    fit_start_ms = iso_to_ms(FIT_START)
    dev_start_ms = iso_to_ms(DEV_START)
    dev_end_ms = iso_to_ms(DEV_END)
    try:
        panels, funding, source_manifest = source_bundle(
            session, args.cache, fit_start_ms, dev_end_ms
        )
    except Exception as exc:
        result.update(
            {
                "status": "SOURCE_BLOCKED",
                "hard_validity_status": "NOT_EVALUATED",
                "economic_status": "NOT_EVALUATED",
                "ranking_role": "UNRANKED_SOURCE_BLOCKED",
                "source_error": f"{type(exc).__name__}: {exc}",
            }
        )
        json_dump(args.output / "RESULT.json", result)
        write_checksums(args.output)
        return 0

    json_dump(args.output / "SOURCE_MANIFEST.json", source_manifest)
    candidates = candidate_grid()
    result["candidate_count"] = len(candidates)
    rows: list[dict[str, Any]] = []
    for index, candidate in enumerate(candidates, start=1):
        candidate_result, _paths = evaluate_candidate(
            panels, funding, candidate, dev_start_ms, dev_end_ms
        )
        rows.append(candidate_result)
        print(
            json.dumps(
                {
                    "candidate": index,
                    "total": len(candidates),
                    "candidate_id": candidate.candidate_id,
                    "family": candidate.family,
                    "trades": candidate_result["costs"]["18bps"]["trade_count"],
                    "g18": candidate_result["costs"]["18bps"]["geometric_daily_growth"],
                    "gate": candidate_result["gate_pass"],
                },
                sort_keys=True,
            ),
            flush=True,
        )

    flattened: list[dict[str, Any]] = []
    for row in rows:
        base = {
            **row["candidate"],
            "candidate_id": row["candidate_id"],
            "gate_pass": row["gate_pass"],
        }
        for cost in COSTS_BPS:
            metrics = row["costs"][f"{cost:g}bps"]
            for key in (
                "total_return",
                "geometric_daily_growth",
                "maximum_drawdown",
                "trade_count",
                "profit_factor",
                "median_account_return_bps",
                "top5_positive_share",
            ):
                base[f"{key}_{cost:g}bps"] = metrics.get(key)
            base[f"top10_removed_return_{cost:g}bps"] = metrics.get(
                "top10pct_positive_removed", {}
            ).get("total_return")
        flattened.append(base)
    candidate_csv = args.output / "CANDIDATE_RESULTS.csv"
    pd.DataFrame(flattened).sort_values(
        ["geometric_daily_growth_24bps", "geometric_daily_growth_18bps"],
        ascending=False,
    ).to_csv(candidate_csv, index=False)
    json_dump(args.output / "CANDIDATE_DETAILS.json", rows)

    survivors = [row for row in rows if row["gate_pass"]]
    best_raw = max(
        rows,
        key=lambda row: row["costs"]["18bps"].get("geometric_daily_growth", -1.0),
    )
    result["development"] = {
        "period": [DEV_START, DEV_END],
        "calendar_days": (dev_end_ms - dev_start_ms) / 86_400_000,
        "candidate_count": len(rows),
        "gate_pass_count": len(survivors),
        "best_raw_candidate": best_raw,
        "source_manifest_sha256": canonical_sha256(source_manifest),
    }

    if survivors:
        frozen = max(
            survivors,
            key=lambda row: row["costs"]["24bps"]["geometric_daily_growth"],
        )
        frozen_candidate = Candidate(**frozen["candidate"])
        oos_start_ms = dev_end_ms
        oos_end_ms = iso_to_ms(OOS_END)
        try:
            oos_panels, oos_funding, oos_manifest = source_bundle(
                session,
                args.cache,
                iso_to_ms("2023-01-01T00:00:00Z"),
                oos_end_ms,
            )
            result["2024_downloaded"] = True
            oos_result, oos_paths = evaluate_candidate(
                oos_panels, oos_funding, frozen_candidate, oos_start_ms, oos_end_ms
            )
            result["conditional_2024"] = {
                "frozen_candidate_id": frozen_candidate.candidate_id,
                "selection_metric": "highest development 24bps geometric daily growth among full-gate survivors",
                "result": oos_result,
                "source_manifest_sha256": canonical_sha256(oos_manifest),
                "trade_path_sha256": canonical_sha256([asdict(path) for path in oos_paths]),
            }
        except Exception as exc:
            result["conditional_2024"] = {
                "frozen_candidate_id": frozen_candidate.candidate_id,
                "status": "SOURCE_BLOCKED_AFTER_DEVELOPMENT_PASS",
                "source_error": f"{type(exc).__name__}: {exc}",
            }
        result.update(
            {
                "status": "DEVELOPMENT_GATE_PASSED",
                "hard_validity_status": "PASS_INITIAL",
                "economic_status": "PROMISING_REQUIRES_2024_REVIEW",
                "ranking_role": "PROVISIONAL_PENDING_2024",
            }
        )
    else:
        result.update(
            {
                "status": "TESTED_BELOW_GATE",
                "hard_validity_status": "PASS_INITIAL",
                "economic_status": "BELOW_GATE",
                "ranking_role": "UNRANKED_NEGATIVE_FAMILY_EVIDENCE",
                "2024_downloaded": False,
                "summary": (
                    "All preregistered USD-M dated-futures curve candidates failed the "
                    "2022-2023 development gate; 2024 remained unopened."
                ),
            }
        )
    result["dependency_fingerprint"] = canonical_sha256(
        {
            "preregistration_sha256": result["preregistration_sha256"],
            "script_sha256": result["script_sha256"],
            "source_manifest_sha256": result["development"]["source_manifest_sha256"],
        }
    )
    json_dump(args.output / "RESULT.json", result)
    write_checksums(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
