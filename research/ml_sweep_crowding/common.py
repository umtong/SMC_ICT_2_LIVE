#!/usr/bin/env python3
"""Shared contract types, deterministic helpers, and cached HTTP access.

No live orders are submitted.
"""
from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator, Mapping

import numpy as np
import pandas as pd
import requests

UTC = "UTC"
EPS = 1e-12
CONTRACT_PATH = Path(__file__).with_name("contract.json")

FEATURE_COLUMNS = [
    "sweep_side",
    "candidate_direction",
    "is_continuation",
    "sweep_depth_atr",
    "close_location",
    "reclaim_atr",
    "body_atr",
    "upper_wick_atr",
    "lower_wick_atr",
    "range_atr",
    "volume_z_24h",
    "return_5m_atr",
    "return_1h_atr",
    "realized_vol_1h",
    "distance_opposing_liquidity_atr",
    "open_interest_log",
    "open_interest_change_15m",
    "open_interest_change_1h",
    "open_interest_change_6h",
    "open_interest_z_24h",
    "top_account_ls",
    "top_position_ls",
    "global_account_ls",
    "taker_buy_sell_ratio",
    "top_account_change_1h",
    "top_position_change_1h",
    "global_account_change_1h",
    "taker_ratio_change_1h",
    "top_account_z_24h",
    "top_position_z_24h",
    "global_account_z_24h",
    "taker_ratio_z_24h",
    "oi_x_sweep",
    "oi_x_reclaim",
    "crowding_x_direction",
    "taker_x_direction",
    "crowding_flow_disagreement",
    "asset_flag",
]


class SourceGateError(RuntimeError):
    """The frozen source/schema/coverage contract could not be satisfied."""


class EconomicGateError(RuntimeError):
    """The fixed economic route could not produce a valid account result."""


@dataclass(frozen=True)
class MarketData:
    symbol: str
    one_minute: pd.DataFrame
    five_minute: pd.DataFrame
    funding: pd.DataFrame
    funding_long_cum: pd.Series
    minute_open: np.ndarray
    minute_high: np.ndarray
    minute_low: np.ndarray
    minute_close: np.ndarray
    coverage: float
    one_minute_sha256: str
    metrics_sha256: str
    funding_sha256: str


@dataclass(frozen=True)
class StageSpec:
    name: str
    start: pd.Timestamp
    end_exclusive: pd.Timestamp
    calendar_days: int


@dataclass(frozen=True)
class SimConfig:
    threshold: float
    risk_fraction: float
    leverage: float
    round_trip_bps: float


@dataclass
class SimResult:
    valid: bool
    forced_liquidation: bool
    start_nav: float
    final_nav: float
    geometric_daily_growth: float
    max_drawdown: float
    daily_nav: pd.Series
    trades: pd.DataFrame
    invalid_reason: str | None = None


class CachedDownloader:
    def __init__(self, cache_dir: Path, timeout: float = 120.0) -> None:
        self.cache_dir = cache_dir
        self.timeout = timeout
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": "SMC-ICT-2-research/1.0 (+https://github.com/umtong/SMC_ICT_2_LIVE)"
            }
        )

    def get(self, url: str, relative_path: str, min_bytes: int = 32) -> Path:
        path = self.cache_dir / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists() and path.stat().st_size >= min_bytes:
            return path
        temp = path.with_suffix(path.suffix + ".part")
        last_error: Exception | None = None
        for attempt in range(6):
            try:
                with self.session.get(url, timeout=self.timeout, stream=True) as response:
                    response.raise_for_status()
                    with temp.open("wb") as handle:
                        for chunk in response.iter_content(chunk_size=1 << 20):
                            if chunk:
                                handle.write(chunk)
                if temp.stat().st_size < min_bytes:
                    raise SourceGateError(f"download too small: {url}")
                temp.replace(path)
                return path
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                temp.unlink(missing_ok=True)
                time.sleep(min(2**attempt, 20))
        raise SourceGateError(f"download failed after retries: {url}: {last_error}")

    def get_json(self, url: str, params: Mapping[str, Any]) -> Mapping[str, Any]:
        last_error: Exception | None = None
        for attempt in range(8):
            try:
                response = self.session.get(url, params=params, timeout=self.timeout)
                if response.status_code == 403 and "api.bybit.com" in url:
                    alt = url.replace("api.bybit.com", "api.bytick.com")
                    response = self.session.get(alt, params=params, timeout=self.timeout)
                response.raise_for_status()
                return response.json()
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                time.sleep(min(2**attempt, 30))
        raise SourceGateError(f"JSON request failed after retries: {url}: {last_error}")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_json(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(encoded).hexdigest()


def utc_timestamp(value: Any) -> pd.Timestamp:
    ts = pd.Timestamp(value)
    if ts.tzinfo is None:
        return ts.tz_localize(UTC)
    return ts.tz_convert(UTC)


def month_range(start: pd.Timestamp, end_exclusive: pd.Timestamp) -> Iterator[tuple[int, int]]:
    cursor = pd.Timestamp(start.year, start.month, 1, tz=UTC)
    final = pd.Timestamp(end_exclusive.year, end_exclusive.month, 1, tz=UTC)
    while cursor <= final:
        if cursor >= end_exclusive:
            break
        yield cursor.year, cursor.month
        cursor = cursor + pd.offsets.MonthBegin(1)


def load_contract(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        contract = json.load(handle)
    if contract.get("claim_id") != "CLM-20260727-0245-ML-SWEEP-CROWDING-001":
        raise SourceGateError("unexpected contract identity")
    return contract
