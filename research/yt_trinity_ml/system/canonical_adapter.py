from __future__ import annotations

import importlib.util
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Iterable, Mapping

import pandas as pd


@dataclass(frozen=True)
class CanonicalInputConfig:
    trade_timeframe: str = "5m"
    decision_timeframe_ms: int = 5 * 60 * 1000
    require_complete: bool = True


def load_loader(repo_root: str | Path) -> ModuleType:
    path = Path(repo_root) / "scripts" / "market_data" / "load_canonical_bybit.py"
    spec = importlib.util.spec_from_file_location("canonical_bybit_loader", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load canonical data loader: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _index_by_available(frame: pd.DataFrame, *, timestamp_column: str) -> pd.DataFrame:
    if timestamp_column not in frame.columns:
        raise ValueError(f"missing {timestamp_column}")
    result = frame.copy()
    if "available_at_ms" not in result.columns:
        raise ValueError("canonical frame lacks available_at_ms")
    result["timestamp"] = pd.to_datetime(result[timestamp_column], unit="ms", utc=True)
    result["available_at"] = pd.to_datetime(result["available_at_ms"], unit="ms", utc=True)
    result = result.sort_values(timestamp_column, kind="stable")
    if result[timestamp_column].duplicated().any():
        raise ValueError("duplicate canonical timestamps")
    if not (result["available_at"] >= result["timestamp"]).all():
        raise RuntimeError("canonical observation became available before its source timestamp")
    return result.set_index("timestamp", drop=False)


def normalize_trade_bars(frame: pd.DataFrame, config: CanonicalInputConfig = CanonicalInputConfig()) -> pd.DataFrame:
    bars = _index_by_available(frame, timestamp_column="start_time_ms")
    aliases = {
        "open_price": "open",
        "high_price": "high",
        "low_price": "low",
        "close_price": "close",
        "turnover": "turnover",
    }
    for source, target in aliases.items():
        if source in bars.columns and target not in bars.columns:
            bars[target] = bars[source]
    required = {"open", "high", "low", "close", "volume", "available_at_ms"}
    missing = required - set(bars.columns)
    if missing:
        raise ValueError(f"canonical trade bars missing: {sorted(missing)}")
    if config.require_complete:
        complete_column = next((name for name in ("complete", "is_complete", "source_complete") if name in bars.columns), None)
        if complete_column is not None:
            bars = bars[bars[complete_column].fillna(False).astype(bool)].copy()
    for name in ("open", "high", "low", "close", "volume"):
        bars[name] = pd.to_numeric(bars[name], errors="coerce")
    bars["bar_start"] = bars["timestamp"]
    bars = bars.set_index("available_at", drop=False).sort_index()
    if bars.index.has_duplicates:
        raise ValueError("duplicate canonical availability timestamps")
    return bars


def normalize_stream(frame: pd.DataFrame, value_map: Mapping[str, str]) -> pd.DataFrame:
    timestamp_column = "start_time_ms" if "start_time_ms" in frame.columns else "timestamp_ms"
    data = _index_by_available(frame, timestamp_column=timestamp_column)
    selected = pd.DataFrame(index=data.index)
    selected["available_at_ms"] = data["available_at_ms"]
    for source, target in value_map.items():
        if source in data.columns:
            selected[target] = pd.to_numeric(data[source], errors="coerce")
    return selected


def causal_asof_join(base: pd.DataFrame, auxiliary: pd.DataFrame) -> pd.DataFrame:
    """Join only auxiliary rows available by each base decision timestamp."""
    if "available_at_ms" not in base.columns or "available_at_ms" not in auxiliary.columns:
        raise ValueError("both frames require available_at_ms")
    left = base.reset_index(drop=True).sort_values("available_at_ms", kind="stable")
    index_column = auxiliary.index.name or "index"
    right = auxiliary.reset_index(drop=False).rename(columns={index_column: "source_timestamp"})
    right = right.sort_values("available_at_ms", kind="stable")
    value_columns = [name for name in right.columns if name not in {"available_at_ms", "source_timestamp"}]
    joined = pd.merge_asof(
        left,
        right[["available_at_ms", "source_timestamp", *value_columns]],
        on="available_at_ms",
        direction="backward",
        allow_exact_matches=True,
    )
    joined.index = pd.to_datetime(joined["available_at_ms"], unit="ms", utc=True)
    joined.index.name = "decision_time"
    return joined.sort_index()


def assemble_symbol_frame(
    data_root: str | Path,
    repo_root: str | Path,
    symbol: str,
    segments: Iterable[str],
    config: CanonicalInputConfig = CanonicalInputConfig(),
) -> tuple[pd.DataFrame, pd.DataFrame]:
    loader = load_loader(repo_root)
    segments = tuple(segments)
    trade = loader.concatenate_segments(data_root, symbol, kind="trade_bar", name=config.trade_timeframe, segments=segments)
    result = normalize_trade_bars(trade, config)

    stream_specs = [
        ("mark_price_1m", {"close": "mark_close", "close_price": "mark_close"}),
        ("index_price_1m", {"close": "index_close", "close_price": "index_close"}),
        ("premium_index_1m", {"close": "premium_close", "close_price": "premium_close"}),
        ("open_interest_5m", {"open_interest": "open_interest"}),
        ("account_ratio_5m", {"buy_ratio": "buy_ratio", "sell_ratio": "sell_ratio", "long_short_ratio": "long_short_ratio"}),
    ]
    for stream_name, mapping in stream_specs:
        try:
            stream = loader.concatenate_segments(data_root, symbol, kind="stream", name=stream_name, segments=segments)
        except KeyError:
            continue
        normalized = normalize_stream(stream, mapping)
        result = causal_asof_join(result, normalized)

    funding = loader.concatenate_segments(data_root, symbol, kind="stream", name="funding_events", segments=segments)
    funding = _index_by_available(funding, timestamp_column="timestamp_ms")
    funding_rate_column = next((name for name in ("funding_rate", "fundingRate") if name in funding.columns), None)
    if funding_rate_column is None:
        raise ValueError("funding events lack funding rate")
    funding_output = pd.DataFrame(
        {
            "funding_rate": pd.to_numeric(funding[funding_rate_column], errors="coerce"),
            "available_at_ms": funding["available_at_ms"],
        },
        index=funding.index,
    )
    result = result.sort_index()
    bar_start = pd.DatetimeIndex(pd.to_datetime(result["bar_start"], utc=True))
    available = pd.DatetimeIndex(result.index)
    if not (available >= bar_start).all():
        raise RuntimeError("canonical bar became available before its own start")
    return result, funding_output.sort_index()
