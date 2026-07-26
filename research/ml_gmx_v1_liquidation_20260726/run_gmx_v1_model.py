from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
import math
import time
import zipfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd
import requests
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.isotonic import IsotonicRegression
from sklearn.metrics import brier_score_loss, roc_auc_score

CLAIM_ID = "CLM-20260726-2324-ML-GMX-V1-LIQUIDATION-001"
ENGINE = "ML_GMX_V1_REMOVED_EXPOSURE_FIRST_PASSAGE_V1"
SYMBOLS = ("BTCUSDT", "ETHUSDT")
COSTS_BPS = (12.0, 18.0, 24.0)
PRIMARY_COST_BPS = 24.0
INITIAL_NAV = 10_000.0
BASE_RISK = 0.005
BASE_NOTIONAL_CAP = 3.0
MAINTENANCE_MARGIN = 0.005
CURRENT_FIRST_GDG = 0.0003873170703223572
BINANCE_BASES = (
    "https://data.binance.vision",
    "https://s3-ap-northeast-1.amazonaws.com/data.binance.vision",
)
PARTITIONS = {
    "train": (
        pd.Timestamp("2021-09-01", tz="UTC"),
        pd.Timestamp("2022-07-01", tz="UTC"),
    ),
    "calibration": (
        pd.Timestamp("2022-07-01", tz="UTC"),
        pd.Timestamp("2023-01-01", tz="UTC"),
    ),
    "confirmation": (
        pd.Timestamp("2023-01-01", tz="UTC"),
        pd.Timestamp("2023-07-01", tz="UTC"),
    ),
    "development": (
        pd.Timestamp("2023-07-01", tz="UTC"),
        pd.Timestamp("2024-01-01", tz="UTC"),
    ),
}
FEATURES = (
    "log_total_removed_size_usd",
    "signed_removed_exposure_share",
    "long_removed_fraction",
    "btc_removed_fraction",
    "log_event_count",
    "log_unique_accounts",
    "source_hhi",
    "source_max_share",
    "source_realised_pnl_ratio",
    "source_collateral_ratio",
    "prior_15m_return",
    "prior_60m_realized_volatility",
    "prior_60m_path_efficiency",
    "prior_60m_taker_flow_imbalance",
    "log_prior_60m_quote_volume",
    "distance_to_frozen_upper_60m_liquidity",
    "distance_to_frozen_lower_60m_liquidity",
    "btc_eth_completed_return_breadth",
)
KLINE_COLUMNS = (
    "open_time_ms",
    "open",
    "high",
    "low",
    "close",
    "base_volume",
    "close_time_ms",
    "quote_volume",
    "trade_count",
    "taker_buy_base",
    "taker_buy_quote",
    "ignore",
)


@dataclass(frozen=True)
class Trade:
    event_id: str
    symbol: str
    decision_ms: int
    entry_ms: int
    exit_ms: int
    side: int
    entry: float
    exit_price: float
    stop_price: float
    target_price: float
    stop_fraction: float
    gross_fraction: float
    funding_fraction: float
    probability_up: float
    ev_bps: float
    exit_reason: str
    ambiguous: bool
    completed: bool


def json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(item) for item in value]
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, (np.floating, float)):
        number = float(value)
        return number if math.isfinite(number) else None
    if isinstance(value, np.bool_):
        return bool(value)
    return value


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def months(start: str, end: str) -> list[str]:
    return [
        str(value)
        for value in pd.period_range(pd.Period(start, "M"), pd.Period(end, "M"), freq="M")
    ]


def fetch(session: requests.Session, path: str) -> tuple[bytes, str]:
    errors: list[str] = []
    for base_url in BINANCE_BASES:
        for attempt in range(4):
            url = base_url + path
            try:
                response = session.get(url, timeout=180)
                if response.status_code == 200:
                    return response.content, url
                errors.append(f"{url}: HTTP {response.status_code}")
            except requests.RequestException as exc:
                errors.append(f"{url}: {type(exc).__name__}: {exc}")
            time.sleep(min(2**attempt, 8))
    raise RuntimeError("; ".join(errors[-8:]))


def verified_archive(
    session: requests.Session, path: str
) -> tuple[bytes, dict[str, Any]]:
    payload, url = fetch(session, path)
    checksum, checksum_url = fetch(session, path + ".CHECKSUM")
    expected = checksum.decode("utf-8-sig").strip().split()[0].lower()
    observed = sha256_bytes(payload)
    if observed != expected:
        raise ValueError(f"checksum mismatch {path}: {observed} != {expected}")
    return payload, {
        "url": url,
        "checksum_url": checksum_url,
        "sha256": observed,
        "bytes": len(payload),
    }


def _normalize_timestamp(values: pd.Series) -> pd.Series:
    output = pd.to_numeric(values, errors="coerce")
    micro = output > 100_000_000_000_000
    output.loc[micro] = np.floor(output.loc[micro] / 1000)
    return output


def parse_kline(payload: bytes) -> pd.DataFrame:
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        names = [name for name in archive.namelist() if name.lower().endswith(".csv")]
        if len(names) != 1:
            raise ValueError(f"expected one kline CSV: {names}")
        raw = archive.read(names[0])
    first = raw.splitlines()[0].decode("utf-8-sig").split(",")[0].strip()
    has_header = not first.lstrip("-").isdigit()
    frame = pd.read_csv(io.BytesIO(raw), header=0 if has_header else None).iloc[:, :12]
    frame.columns = KLINE_COLUMNS
    for column in KLINE_COLUMNS:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame["open_time_ms"] = _normalize_timestamp(frame["open_time_ms"])
    frame = frame.dropna(
        subset=[
            "open_time_ms",
            "open",
            "high",
            "low",
            "close",
            "quote_volume",
            "taker_buy_quote",
        ]
    )
    frame["open_time_ms"] = frame["open_time_ms"].astype(np.int64)
    frame["high"] = frame[["open", "high", "low", "close"]].max(axis=1)
    frame["low"] = frame[["open", "high", "low", "close"]].min(axis=1)
    return (
        frame.sort_values("open_time_ms")
        .drop_duplicates("open_time_ms", keep="last")
        .reset_index(drop=True)
    )


def parse_funding(payload: bytes) -> pd.DataFrame:
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        names = [name for name in archive.namelist() if name.lower().endswith(".csv")]
        if len(names) != 1:
            raise ValueError("expected one funding CSV")
        frame = pd.read_csv(archive.open(names[0]))
    normalized = {str(column).strip().lower(): column for column in frame.columns}
    time_column = (
        normalized.get("calc_time")
        or normalized.get("fundingtime")
        or normalized.get("funding_time")
    )
    rate_column = (
        normalized.get("last_funding_rate")
        or normalized.get("fundingrate")
        or normalized.get("funding_rate")
    )
    if time_column is None or rate_column is None:
        if frame.shape[1] < 3:
            raise ValueError(f"unrecognized funding columns: {list(frame.columns)}")
        time_column, rate_column = frame.columns[-2], frame.columns[-1]
    output = pd.DataFrame(
        {
            "time_ms": _normalize_timestamp(frame[time_column]),
            "rate": pd.to_numeric(frame[rate_column], errors="coerce"),
        }
    ).dropna()
    output["time_ms"] = output["time_ms"].astype(np.int64)
    return (
        output.sort_values("time_ms")
        .drop_duplicates("time_ms", keep="last")
        .reset_index(drop=True)
    )


def acquire_market(
    root: Path, start_month: str = "2021-09", end_month: str = "2023-12"
) -> dict[str, Any]:
    root.mkdir(parents=True, exist_ok=True)
    records: list[dict[str, Any]] = []
    with requests.Session() as session:
        session.headers["User-Agent"] = "SMC_ICT_2_LIVE-GMX-V1-economic/1.0"
        for month in months(start_month, end_month):
            if pd.Period(month, "M") >= pd.Period("2024-01", "M"):
                raise AssertionError("pre-2024 downloader requested 2024+")
            for symbol in SYMBOLS:
                specifications = (
                    (
                        "kline",
                        f"/data/futures/um/monthly/klines/{symbol}/1m/"
                        f"{symbol}-1m-{month}.zip",
                    ),
                    (
                        "funding",
                        f"/data/futures/um/monthly/fundingRate/{symbol}/"
                        f"{symbol}-fundingRate-{month}.zip",
                    ),
                )
                for kind, path in specifications:
                    destination = root / kind / symbol / Path(path).name
                    if destination.is_file():
                        payload = destination.read_bytes()
                        metadata = {
                            "sha256": sha256_bytes(payload),
                            "bytes": len(payload),
                            "cached": True,
                        }
                    else:
                        payload, metadata = verified_archive(session, path)
                        destination.parent.mkdir(parents=True, exist_ok=True)
                        destination.write_bytes(payload)
                    records.append(
                        {
                            "kind": kind,
                            "symbol": symbol,
                            "month": month,
                            "path": str(destination),
                            **metadata,
                        }
                    )
                    print(
                        json.dumps(
                            {
                                "downloaded": [kind, symbol, month],
                                "bytes": len(payload),
                            }
                        ),
                        flush=True,
                    )
    manifest = {"schema_version": 1, "records": records}
    (root / "MARKET_SOURCE_MANIFEST.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    )
    return manifest


def load_market(
    root: Path, start_month: str = "2021-09", end_month: str = "2023-12"
) -> tuple[dict[str, pd.DataFrame], dict[str, pd.DataFrame]]:
    bars: dict[str, pd.DataFrame] = {}
    funding: dict[str, pd.DataFrame] = {}
    for symbol in SYMBOLS:
        bar_frames: list[pd.DataFrame] = []
        funding_frames: list[pd.DataFrame] = []
        for month in months(start_month, end_month):
            bar_frames.append(
                parse_kline(
                    (
                        root
                        / "kline"
                        / symbol
                        / f"{symbol}-1m-{month}.zip"
                    ).read_bytes()
                )
            )
            funding_frames.append(
                parse_funding(
                    (
                        root
                        / "funding"
                        / symbol
                        / f"{symbol}-fundingRate-{month}.zip"
                    ).read_bytes()
                )
            )
        bars[symbol] = (
            pd.concat(bar_frames, ignore_index=True)
            .sort_values("open_time_ms")
            .drop_duplicates("open_time_ms", keep="last")
            .reset_index(drop=True)
        )
        funding[symbol] = (
            pd.concat(funding_frames, ignore_index=True)
            .sort_values("time_ms")
            .drop_duplicates("time_ms", keep="last")
            .reset_index(drop=True)
        )
    return bars, funding


def load_source(path: Path) -> pd.DataFrame:
    opener = gzip.open if path.suffix == ".gz" else open
    rows: list[dict[str, Any]] = []
    with opener(path, "rt", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    frame = pd.DataFrame(rows)
    required = {
        "block_hash",
        "transaction_hash",
        "log_index",
        "account",
        "asset",
        "removed_trader_exposure",
        "signed_removed_exposure_raw_1e30",
        "size_usd",
        "collateral_usd",
        "realised_pnl_usd",
        "causal_available_timestamp",
        "external_market_order_direction_asserted",
    }
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"source columns missing: {missing}")
    if frame.empty:
        return frame
    if frame["external_market_order_direction_asserted"].astype(bool).any():
        raise ValueError("source asserts an external market order")
    frame["event_identity"] = (
        frame["block_hash"].astype(str).str.lower()
        + "|"
        + frame["transaction_hash"].astype(str).str.lower()
        + "|"
        + frame["log_index"].astype(str)
    )
    if frame["event_identity"].duplicated().any():
        raise ValueError("duplicate source event identities")
    for column in (
        "signed_removed_exposure_raw_1e30",
        "size_usd",
        "collateral_usd",
        "realised_pnl_usd",
        "causal_available_timestamp",
    ):
        frame[column] = pd.to_numeric(frame[column], errors="raise")
    frame = frame[frame["asset"].isin(["BTC", "ETH"])].copy()
    return frame.sort_values(
        ["causal_available_timestamp", "event_identity"]
    ).reset_index(drop=True)


def aggregate_source(events: pd.DataFrame) -> pd.DataFrame:
    if events.empty:
        return pd.DataFrame()
    frame = events.copy()
    timestamps = frame["causal_available_timestamp"].to_numpy(np.int64)
    frame["decision_s"] = ((timestamps + 299) // 300) * 300
    frame["signed_size"] = (
        frame["signed_removed_exposure_raw_1e30"].astype(float) / 1e30
    )
    frame["absolute_size"] = frame["size_usd"].astype(float).abs()
    frame["is_long_removed"] = (
        frame["removed_trader_exposure"].eq("LONG_REMOVED").astype(float)
    )
    frame["is_btc"] = frame["asset"].eq("BTC").astype(float)
    rows: list[dict[str, Any]] = []
    for decision_s, group in frame.groupby("decision_s", sort=True):
        total = float(group["absolute_size"].sum())
        if total <= 0:
            continue
        weights = group["absolute_size"].to_numpy(float) / total
        signed = float(group["signed_size"].sum())
        realised = float(group["realised_pnl_usd"].sum())
        collateral = float(group["collateral_usd"].sum())
        rows.append(
            {
                "event_id": f"GMX5M|{int(decision_s)}",
                "decision_s": int(decision_s),
                "total_removed_size_usd": total,
                "signed_removed_exposure_share": float(
                    np.clip(signed / total, -1.0, 1.0)
                ),
                "long_removed_fraction": float(
                    np.dot(weights, group["is_long_removed"].to_numpy(float))
                ),
                "btc_removed_fraction": float(
                    np.dot(weights, group["is_btc"].to_numpy(float))
                ),
                "event_count": int(len(group)),
                "unique_accounts": int(group["account"].nunique()),
                "source_hhi": float(np.sum(weights * weights)),
                "source_max_share": float(np.max(weights)),
                "source_realised_pnl_ratio": float(
                    np.clip(realised / total, -5.0, 5.0)
                ),
                "source_collateral_ratio": float(
                    np.clip(collateral / total, 0.0, 5.0)
                ),
                "source_event_identities": sorted(
                    group["event_identity"].astype(str).tolist()
                ),
            }
        )
    return pd.DataFrame(rows).sort_values(
        ["decision_s", "event_id"]
    ).reset_index(drop=True)


def market_features(frame: pd.DataFrame) -> dict[str, np.ndarray]:
    close = frame["close"].to_numpy(float)
    quote = frame["quote_volume"].to_numpy(float)
    buy = frame["taker_buy_quote"].to_numpy(float)
    log_close = np.log(close)
    return_1 = np.full(len(frame), np.nan)
    return_1[1:] = np.diff(log_close)
    return_15 = np.full(len(frame), np.nan)
    return_15[15:] = np.exp(log_close[15:] - log_close[:-15]) - 1.0
    volatility_60 = (
        pd.Series(return_1).rolling(60, min_periods=45).std(ddof=0).to_numpy()
        * math.sqrt(60)
    )
    displacement = np.full(len(frame), np.nan)
    displacement[60:] = np.abs(log_close[60:] - log_close[:-60])
    path = pd.Series(np.abs(return_1)).rolling(60, min_periods=45).sum().to_numpy()
    efficiency = np.divide(
        displacement,
        path,
        out=np.full(len(frame), np.nan),
        where=path > 0,
    )
    signed_quote = 2.0 * buy - quote
    quote_60 = pd.Series(quote).rolling(60, min_periods=45).sum().to_numpy()
    signed_quote_60 = (
        pd.Series(signed_quote).rolling(60, min_periods=45).sum().to_numpy()
    )
    taker_flow_60 = np.divide(
        signed_quote_60,
        quote_60,
        out=np.full(len(frame), np.nan),
        where=quote_60 > 0,
    )
    return {
        "ret15": return_15,
        "vol60": volatility_60,
        "eff60": efficiency,
        "tfi60": taker_flow_60,
        "q60": quote_60,
    }


def partition_name(decision_ms: int) -> str | None:
    timestamp = pd.Timestamp(decision_ms, unit="ms", tz="UTC")
    for name, (start, end) in PARTITIONS.items():
        if start <= timestamp < end:
            return name
    return None


def latest_completed_index(times: np.ndarray, decision_ms: int) -> int:
    return int(np.searchsorted(times + 60_000, decision_ms, side="right")) - 1


def index_at_or_after(times: np.ndarray, timestamp_ms: int) -> int | None:
    index = int(np.searchsorted(times, timestamp_ms, side="left"))
    return index if 0 <= index < len(times) else None


def build_rows(
    source: pd.DataFrame, bars: dict[str, pd.DataFrame]
) -> pd.DataFrame:
    features = {symbol: market_features(frame) for symbol, frame in bars.items()}
    rows: list[dict[str, Any]] = []
    breadth_by_event: dict[str, float] = {}
    for _, event in source.iterrows():
        decision_ms = int(event["decision_s"]) * 1000
        partition = partition_name(decision_ms)
        if partition is None:
            continue
        partition_end_ms = int(PARTITIONS[partition][1].timestamp() * 1000)
        source_returns: list[float] = []
        candidate_rows: list[dict[str, Any]] = []
        for symbol in SYMBOLS:
            frame = bars[symbol]
            times = frame["open_time_ms"].to_numpy(np.int64)
            completed = latest_completed_index(times, decision_ms)
            next_open_ms = ((decision_ms // 60_000) + 1) * 60_000
            entry_index = index_at_or_after(times, next_open_ms)
            if entry_index is None or completed < 60 or completed >= entry_index:
                continue
            window = frame.iloc[completed - 59 : completed + 1]
            upper = float(window["high"].max())
            lower = float(window["low"].min())
            reference = float(frame.iloc[completed]["close"])
            entry = float(frame.iloc[entry_index]["open"])
            if not (
                np.isfinite(upper)
                and np.isfinite(lower)
                and upper > reference > lower > 0
                and entry > 0
            ):
                continue
            arrays = features[symbol]
            return_15 = float(arrays["ret15"][completed])
            source_returns.append(return_15)
            boundary_index = (
                int(np.searchsorted(times, partition_end_ms, side="left")) - 1
            )
            if boundary_index < entry_index:
                continue
            label = np.nan
            ambiguous = False
            reason = "UNRESOLVED_AT_STAGE_BOUNDARY"
            exit_index = boundary_index
            for index in range(entry_index, boundary_index + 1):
                high = float(frame.iloc[index]["high"])
                low = float(frame.iloc[index]["low"])
                hit_upper = high >= upper
                hit_lower = low <= lower
                if hit_upper and hit_lower:
                    ambiguous = True
                    exit_index = index
                    reason = "AMBIGUOUS"
                    break
                if hit_upper:
                    label = 1.0
                    exit_index = index
                    reason = "UPPER_FIRST"
                    break
                if hit_lower:
                    label = 0.0
                    exit_index = index
                    reason = "LOWER_FIRST"
                    break
            candidate_rows.append(
                {
                    "event_id": str(event["event_id"]),
                    "symbol": symbol,
                    "partition": partition,
                    "decision_ms": decision_ms,
                    "feature_available_through_ms": int(times[completed] + 60_000),
                    "entry_ms": int(times[entry_index]),
                    "entry_index": entry_index,
                    "exit_index": exit_index,
                    "exit_ms": int(times[exit_index]),
                    "stage_boundary_ms": partition_end_ms,
                    "entry": entry,
                    "reference": reference,
                    "upper": upper,
                    "lower": lower,
                    "entry_gap_invalidated": not (upper > entry > lower),
                    "label_up": label,
                    "ambiguous": ambiguous,
                    "path_reason": reason,
                    "log_total_removed_size_usd": math.log1p(
                        float(event["total_removed_size_usd"])
                    ),
                    "signed_removed_exposure_share": float(
                        event["signed_removed_exposure_share"]
                    ),
                    "long_removed_fraction": float(event["long_removed_fraction"]),
                    "btc_removed_fraction": float(event["btc_removed_fraction"]),
                    "log_event_count": math.log1p(float(event["event_count"])),
                    "log_unique_accounts": math.log1p(
                        float(event["unique_accounts"])
                    ),
                    "source_hhi": float(event["source_hhi"]),
                    "source_max_share": float(event["source_max_share"]),
                    "source_realised_pnl_ratio": float(
                        event["source_realised_pnl_ratio"]
                    ),
                    "source_collateral_ratio": float(
                        event["source_collateral_ratio"]
                    ),
                    "prior_15m_return": return_15,
                    "prior_60m_realized_volatility": float(
                        arrays["vol60"][completed]
                    ),
                    "prior_60m_path_efficiency": float(arrays["eff60"][completed]),
                    "prior_60m_taker_flow_imbalance": float(
                        arrays["tfi60"][completed]
                    ),
                    "log_prior_60m_quote_volume": math.log1p(
                        max(float(arrays["q60"][completed]), 0.0)
                    ),
                    "distance_to_frozen_upper_60m_liquidity": (
                        upper / reference - 1.0
                    ),
                    "distance_to_frozen_lower_60m_liquidity": (
                        1.0 - lower / reference
                    ),
                }
            )
        finite_returns = [value for value in source_returns if np.isfinite(value)]
        breadth_by_event[str(event["event_id"])] = (
            float(np.mean(np.sign(finite_returns)))
            if finite_returns
            else float("nan")
        )
        rows.extend(candidate_rows)
    output = pd.DataFrame(rows)
    if output.empty:
        return output
    output["btc_eth_completed_return_breadth"] = output["event_id"].map(
        breadth_by_event
    )
    return output.sort_values(
        ["decision_ms", "event_id", "symbol"]
    ).reset_index(drop=True)


def fit_model(rows: pd.DataFrame) -> dict[str, Any]:
    resolved = rows[
        rows["label_up"].notna()
        & ~rows["ambiguous"]
        & ~rows["entry_gap_invalidated"]
    ].copy()
    train = resolved[resolved["partition"] == "train"]
    calibration = resolved[resolved["partition"] == "calibration"]
    if len(train) < 100 or train["label_up"].nunique() < 2:
        raise ValueError(
            f"insufficient train labels: {len(train)} / "
            f"{train['label_up'].nunique()}"
        )
    medians = train[list(FEATURES)].median(numeric_only=True).fillna(0.0)
    model = HistGradientBoostingClassifier(
        learning_rate=0.05,
        max_iter=120,
        max_leaf_nodes=7,
        min_samples_leaf=20,
        l2_regularization=1.0,
        random_state=20260727,
    )
    model.fit(
        train[list(FEATURES)].fillna(medians).to_numpy(float),
        train["label_up"].to_numpy(int),
    )
    calibrator: IsotonicRegression | None = None
    if len(calibration) >= 50 and calibration["label_up"].nunique() == 2:
        raw = model.predict_proba(
            calibration[list(FEATURES)].fillna(medians).to_numpy(float)
        )[:, 1]
        calibrator = IsotonicRegression(out_of_bounds="clip").fit(
            raw, calibration["label_up"].to_numpy(int)
        )
    return {
        "model": model,
        "calibrator": calibrator,
        "medians": medians,
        "train_rows": len(train),
        "calibration_rows": len(calibration),
    }


def predict(bundle: dict[str, Any], rows: pd.DataFrame) -> np.ndarray:
    raw = bundle["model"].predict_proba(
        rows[list(FEATURES)].fillna(bundle["medians"]).to_numpy(float)
    )[:, 1]
    calibrator = bundle["calibrator"]
    return np.clip(
        calibrator.predict(raw) if calibrator is not None else raw, 0.0, 1.0
    )


def funding_cost(
    funding: pd.DataFrame, entry_ms: int, exit_ms: int, side: int
) -> float:
    if funding.empty or exit_ms <= entry_ms:
        return 0.0
    mask = (funding["time_ms"] > entry_ms) & (funding["time_ms"] <= exit_ms)
    return float(side * funding.loc[mask, "rate"].sum())


def trade_from_row(
    row: pd.Series,
    probability_up: float,
    cost_bps: float,
    bars: pd.DataFrame,
    funding: pd.DataFrame,
) -> Trade | None:
    upper_distance = float(row["distance_to_frozen_upper_60m_liquidity"])
    lower_distance = float(row["distance_to_frozen_lower_60m_liquidity"])
    cost = cost_bps / 10_000.0
    ev_long = (
        probability_up * upper_distance
        - (1.0 - probability_up) * lower_distance
        - cost
    )
    ev_short = (
        (1.0 - probability_up) * lower_distance
        - probability_up * upper_distance
        - cost
    )
    if max(ev_long, ev_short) <= 0:
        return None
    side = 1 if ev_long >= ev_short else -1
    entry = float(row["entry"])
    upper = float(row["upper"])
    lower = float(row["lower"])
    start_index = int(row["entry_index"])
    end_index = int(row["exit_index"])
    if bool(row["entry_gap_invalidated"]):
        return Trade(
            str(row["event_id"]),
            str(row["symbol"]),
            int(row["decision_ms"]),
            int(row["entry_ms"]),
            int(row["entry_ms"]),
            side,
            entry,
            entry,
            lower if side > 0 else upper,
            upper if side > 0 else lower,
            lower_distance if side > 0 else upper_distance,
            0.0,
            0.0,
            float(probability_up),
            float(max(ev_long, ev_short) * 10_000),
            "ENTRY_GAP_INVALIDATED_COST_ONLY",
            False,
            True,
        )
    reason = "MARK_TO_MARKET_STAGE_BOUNDARY"
    exit_price = float(bars.iloc[end_index]["close"])
    completed = False
    ambiguous = False
    for index in range(start_index, end_index + 1):
        record = bars.iloc[index]
        open_price = float(record["open"])
        high = float(record["high"])
        low = float(record["low"])
        hit_target = high >= upper if side > 0 else low <= lower
        hit_stop = low <= lower if side > 0 else high >= upper
        if hit_target and hit_stop:
            reason = "STOP_FIRST_AMBIGUOUS"
            exit_price = (
                min(lower, open_price) if side > 0 else max(upper, open_price)
            )
            end_index = index
            completed = True
            ambiguous = True
            break
        if hit_stop:
            reason = "STOP"
            exit_price = (
                min(lower, open_price) if side > 0 else max(upper, open_price)
            )
            end_index = index
            completed = True
            break
        if hit_target:
            reason = "TARGET"
            exit_price = upper if side > 0 else lower
            end_index = index
            completed = True
            break
    exit_ms = (
        int(bars.iloc[end_index]["open_time_ms"])
        if completed
        else int(row["stage_boundary_ms"])
    )
    gross = side * (exit_price / entry - 1.0)
    funding_fraction = funding_cost(
        funding, int(row["entry_ms"]), exit_ms, side
    )
    return Trade(
        str(row["event_id"]),
        str(row["symbol"]),
        int(row["decision_ms"]),
        int(row["entry_ms"]),
        exit_ms,
        side,
        entry,
        exit_price,
        lower if side > 0 else upper,
        upper if side > 0 else lower,
        lower_distance if side > 0 else upper_distance,
        float(gross),
        float(funding_fraction),
        float(probability_up),
        float(max(ev_long, ev_short) * 10_000),
        reason,
        ambiguous,
        completed,
    )


def route(
    rows: pd.DataFrame,
    probabilities: np.ndarray,
    bars: dict[str, pd.DataFrame],
    funding: dict[str, pd.DataFrame],
    cost_bps: float,
    excluded: set[str] | None = None,
) -> list[Trade]:
    excluded = excluded or set()
    work = rows.copy()
    work["probability_up"] = probabilities
    trades: list[Trade] = []
    free_ms = -1
    for decision_ms, group in work.groupby("decision_ms", sort=True):
        if int(decision_ms) < free_ms:
            continue
        candidates: list[Trade] = []
        for _, row in group.iterrows():
            if str(row["event_id"]) in excluded:
                continue
            trade = trade_from_row(
                row,
                float(row["probability_up"]),
                cost_bps,
                bars[str(row["symbol"])],
                funding[str(row["symbol"])],
            )
            if trade is not None:
                candidates.append(trade)
        if not candidates:
            continue
        chosen = max(
            candidates, key=lambda trade: (trade.ev_bps, trade.symbol, -trade.side)
        )
        trades.append(chosen)
        free_ms = chosen.exit_ms + 1
        if not chosen.completed:
            break
    return trades


def replay(
    trades: Iterable[Trade],
    cost_bps: float,
    start: pd.Timestamp,
    end: pd.Timestamp,
    risk: float = BASE_RISK,
    cap: float = BASE_NOTIONAL_CAP,
) -> dict[str, Any]:
    nav = INITIAL_NAV
    peak = nav
    maximum_drawdown = 0.0
    liquidation = False
    ledger: list[dict[str, Any]] = []
    cost = cost_bps / 10_000.0
    for trade in sorted(trades, key=lambda item: item.entry_ms):
        before = nav
        unit_loss = max(
            trade.stop_fraction + cost + max(trade.funding_fraction, 0.0), 1e-9
        )
        leverage = min(cap, risk / unit_loss)
        liquidation_distance = max(
            1.0 / max(leverage, 1e-12)
            - MAINTENANCE_MARGIN
            - cost / 2.0,
            0.0,
        )
        if leverage > 0 and trade.stop_fraction >= liquidation_distance:
            liquidation = True
        net_fraction = trade.gross_fraction - cost - trade.funding_fraction
        account_return = leverage * net_fraction
        nav = before * (1.0 + account_return)
        adverse_fraction = min(trade.stop_fraction, liquidation_distance)
        adverse_nav = before * (
            1.0 - leverage * (adverse_fraction + cost / 2.0)
        )
        peak = max(peak, before)
        maximum_drawdown = max(
            maximum_drawdown,
            1.0 - max(adverse_nav, 0.0) / peak,
            1.0 - max(nav, 0.0) / peak,
        )
        peak = max(peak, nav)
        ledger.append(
            {
                **asdict(trade),
                "leverage": leverage,
                "account_return": account_return,
                "net_pnl": nav - before,
                "nav_before": before,
                "nav_after": nav,
                "liquidation_distance_fraction": liquidation_distance,
            }
        )
        if nav <= 0:
            liquidation = True
            nav = 0.0
            break
    days = max(1, int((end - start).total_seconds() // 86_400))
    daily_growth = (
        (nav / INITIAL_NAV) ** (1.0 / days) - 1.0 if nav > 0 else -1.0
    )
    completed = [row for row in ledger if row["completed"]]
    pnl = np.array([row["net_pnl"] for row in completed], float)
    returns = np.array([row["account_return"] for row in completed], float)
    positive = pnl[pnl > 0]
    negative = pnl[pnl < 0]
    profit_factor = (
        float(positive.sum() / -negative.sum())
        if len(positive) and len(negative)
        else (float("inf") if len(positive) else 0.0)
    )
    top5 = (
        float(np.sort(positive)[-5:].sum() / positive.sum())
        if len(positive)
        else 1.0
    )
    return {
        "initial_nav": INITIAL_NAV,
        "ending_nav": nav,
        "total_return": nav / INITIAL_NAV - 1.0,
        "geometric_daily_growth": daily_growth,
        "calendar_days": days,
        "maximum_drawdown": maximum_drawdown,
        "liquidation": liquidation,
        "completed_trade_count": len(completed),
        "all_position_count": len(ledger),
        "profit_factor": profit_factor,
        "median_completed_trade_bps": (
            float(np.median(returns) * 10_000.0) if len(returns) else None
        ),
        "win_rate": float(np.mean(returns > 0)) if len(returns) else None,
        "top5_positive_pnl_share": top5,
        "open_position_at_boundary": any(not row["completed"] for row in ledger),
        "ledger": ledger,
    }


def probability_metrics(
    rows: pd.DataFrame, probabilities: np.ndarray
) -> dict[str, Any]:
    mask = (
        rows["label_up"].notna()
        & ~rows["ambiguous"]
        & ~rows["entry_gap_invalidated"]
    )
    labels = rows.loc[mask, "label_up"].to_numpy(int)
    predicted = probabilities[mask.to_numpy()]
    upper = rows.loc[
        mask, "distance_to_frozen_upper_60m_liquidity"
    ].to_numpy(float)
    lower = rows.loc[
        mask, "distance_to_frozen_lower_60m_liquidity"
    ].to_numpy(float)
    baseline = np.divide(
        lower,
        upper + lower,
        out=np.full(len(upper), 0.5),
        where=(upper + lower) > 0,
    )
    if len(labels) == 0 or len(np.unique(labels)) < 2:
        return {
            "rows": len(labels),
            "auc": None,
            "baseline_auc": None,
            "brier": None,
            "baseline_brier": None,
            "auc_lift": None,
            "brier_skill": None,
        }
    auc = roc_auc_score(labels, predicted)
    baseline_auc = roc_auc_score(labels, baseline)
    brier = brier_score_loss(labels, predicted)
    baseline_brier = brier_score_loss(labels, baseline)
    return {
        "rows": len(labels),
        "auc": auc,
        "baseline_auc": baseline_auc,
        "brier": brier,
        "baseline_brier": baseline_brier,
        "auc_lift": auc - baseline_auc,
        "brier_skill": (
            1.0 - brier / baseline_brier if baseline_brier > 0 else None
        ),
    }


def subset_replay(
    rows: pd.DataFrame,
    probabilities: np.ndarray,
    bars: dict[str, pd.DataFrame],
    funding: dict[str, pd.DataFrame],
    cost_bps: float,
    start: str,
    end: str,
    risk: float = BASE_RISK,
    cap: float = BASE_NOTIONAL_CAP,
    excluded: set[str] | None = None,
) -> dict[str, Any]:
    start_time = pd.Timestamp(start, tz="UTC")
    end_time = pd.Timestamp(end, tz="UTC")
    mask = (
        (rows["decision_ms"] >= int(start_time.timestamp() * 1000))
        & (rows["decision_ms"] < int(end_time.timestamp() * 1000))
    )
    trades = route(
        rows.loc[mask].reset_index(drop=True),
        probabilities[mask.to_numpy()],
        bars,
        funding,
        cost_bps,
        excluded,
    )
    return replay(trades, cost_bps, start_time, end_time, risk, cap)


def winner_removed(
    rows: pd.DataFrame,
    probabilities: np.ndarray,
    bars: dict[str, pd.DataFrame],
    funding: dict[str, pd.DataFrame],
    cost_bps: float,
    start: str,
    end: str,
    risk: float = BASE_RISK,
    cap: float = BASE_NOTIONAL_CAP,
) -> tuple[dict[str, Any], list[str]]:
    base_result = subset_replay(
        rows,
        probabilities,
        bars,
        funding,
        cost_bps,
        start,
        end,
        risk,
        cap,
    )
    positives = [
        row
        for row in base_result["ledger"]
        if row["completed"] and row["net_pnl"] > 0
    ]
    completed_count = sum(row["completed"] for row in base_result["ledger"])
    count = max(1, math.ceil(completed_count * 0.10)) if positives else 0
    excluded = {
        row["event_id"]
        for row in sorted(
            positives, key=lambda row: row["net_pnl"], reverse=True
        )[:count]
    }
    return (
        subset_replay(
            rows,
            probabilities,
            bars,
            funding,
            cost_bps,
            start,
            end,
            risk,
            cap,
            excluded,
        ),
        sorted(excluded),
    )


def gate_confirmation(
    metrics: dict[str, Any],
    accounts: dict[str, Any],
    halves: dict[str, Any],
    winner18: dict[str, Any],
) -> dict[str, bool]:
    gate = {
        "at_least_50_resolved_labels_and_both_classes": (
            int(metrics.get("rows") or 0) >= 50 and metrics.get("auc") is not None
        ),
        "model_auc_exceeds_distance_baseline": (
            (metrics.get("auc_lift") or -1.0) > 0
        ),
        "positive_brier_skill": (metrics.get("brier_skill") or -1.0) > 0,
        "at_least_30_completed_trades_18bps": (
            accounts["18"]["completed_trade_count"] >= 30
        ),
        "positive_both_confirmation_halves_18bps": (
            halves["H1"]["total_return"] > 0
            and halves["H2"]["total_return"] > 0
        ),
        "profit_factor_at_least_1_10_18bps": (
            accounts["18"]["profit_factor"] >= 1.10
        ),
        "nonnegative_24bps": accounts["24"]["total_return"] >= 0,
        "positive_winner_removed_18bps": winner18["total_return"] > 0,
        "no_liquidation_and_mdd_below_35pct": (
            not accounts["18"]["liquidation"]
            and accounts["18"]["maximum_drawdown"] < 0.35
        ),
    }
    gate["all"] = all(gate.values())
    return gate


def gate_development(
    accounts: dict[str, Any],
    quarters: dict[str, Any],
    winner18: dict[str, Any],
) -> dict[str, bool]:
    gate = {
        "positive_24bps": accounts["24"]["total_return"] > 0,
        "positive_both_2023h2_quarters_18bps": (
            quarters["Q3"]["total_return"] > 0
            and quarters["Q4"]["total_return"] > 0
        ),
        "positive_median_completed_trade_18bps": (
            (accounts["18"]["median_completed_trade_bps"] or -1.0) > 0
        ),
        "at_least_40_completed_trades_18bps": (
            accounts["18"]["completed_trade_count"] >= 40
        ),
        "positive_winner_removed_18bps": winner18["total_return"] > 0,
        "mdd_below_30pct_18bps": (
            accounts["18"]["maximum_drawdown"] < 0.30
        ),
        "24bps_growth_exceeds_current_first": (
            accounts["24"]["geometric_daily_growth"] > CURRENT_FIRST_GDG
        ),
        "no_liquidation": (
            not accounts["18"]["liquidation"]
            and not accounts["24"]["liquidation"]
        ),
    }
    gate["all"] = all(gate.values())
    return gate


def risk_frontier(
    rows: pd.DataFrame,
    probabilities: np.ndarray,
    bars: dict[str, pd.DataFrame],
    funding: dict[str, pd.DataFrame],
) -> dict[str, Any]:
    candidates: list[dict[str, Any]] = []
    for risk in (0.0025, 0.005, 0.01, 0.02, 0.04, 0.08, 0.15, 0.30, 0.60):
        for cap in (1.0, 2.0, 3.0, 5.0, 8.0, 12.0, 20.0, 35.0, 50.0, 75.0, 100.0):
            account = subset_replay(
                rows,
                probabilities,
                bars,
                funding,
                24.0,
                "2023-07-01",
                "2024-01-01",
                risk,
                cap,
            )
            removed, excluded = winner_removed(
                rows,
                probabilities,
                bars,
                funding,
                24.0,
                "2023-07-01",
                "2024-01-01",
                risk,
                cap,
            )
            eligible = (
                not account["liquidation"]
                and account["total_return"] > 0
                and removed["total_return"] > 0
            )
            account_compact = {
                key: value for key, value in account.items() if key != "ledger"
            }
            removed_compact = {
                key: value for key, value in removed.items() if key != "ledger"
            }
            candidates.append(
                {
                    "risk": risk,
                    "cap": cap,
                    "eligible": eligible,
                    "account": account_compact,
                    "winner_removed": removed_compact,
                    "excluded_event_ids": excluded,
                }
            )
    eligible = [item for item in candidates if item["eligible"]]
    selected = (
        max(
            eligible,
            key=lambda item: (
                item["account"]["geometric_daily_growth"],
                item["winner_removed"]["geometric_daily_growth"],
                -item["account"]["maximum_drawdown"],
            ),
        )
        if eligible
        else None
    )
    return {"candidates": candidates, "selected": selected}


def run(source_path: Path, market_root: Path, output: Path) -> dict[str, Any]:
    output.mkdir(parents=True, exist_ok=True)
    events = load_source(source_path)
    source = aggregate_source(events)
    bars, funding = load_market(market_root)
    rows = build_rows(source, bars)
    if rows.empty:
        result = {
            "schema_version": 1,
            "claim_id": CLAIM_ID,
            "engine": ENGINE,
            "status": "PREMODEL_NO_ROWS",
            "pre2024_survivor_ready_for_2024h1": False,
            "orders_submitted": False,
            "official_2024_2026_opened": False,
        }
        (output / "RESULT.json").write_text(
            json.dumps(result, indent=2, sort_keys=True) + "\n"
        )
        return result
    try:
        bundle = fit_model(rows)
    except ValueError as exc:
        result = {
            "schema_version": 1,
            "claim_id": CLAIM_ID,
            "engine": ENGINE,
            "status": "PREMODEL_EVENT_OR_CLASS_SCARCITY",
            "source_event_count": len(events),
            "source_bucket_count": len(source),
            "model_rows": {
                name: int((rows["partition"] == name).sum())
                for name in PARTITIONS
            },
            "failure": str(exc),
            "pre2024_survivor_ready_for_2024h1": False,
            "orders_submitted": False,
            "official_2024_2026_opened": False,
        }
        (output / "RESULT.json").write_text(
            json.dumps(result, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        rows.to_csv(
            output / "MODEL_ROWS.csv.gz", index=False, compression="gzip"
        )
        source.to_csv(
            output / "SOURCE_BUCKETS.csv.gz", index=False, compression="gzip"
        )
        return result
    probabilities = predict(bundle, rows)
    confirmation_mask = (rows["partition"] == "confirmation").to_numpy()
    confirmation_rows = rows.loc[confirmation_mask].reset_index(drop=True)
    confirmation_probabilities = probabilities[confirmation_mask]
    confirmation_prediction = probability_metrics(
        confirmation_rows, confirmation_probabilities
    )
    confirmation_accounts = {
        str(int(cost)): subset_replay(
            rows,
            probabilities,
            bars,
            funding,
            cost,
            "2023-01-01",
            "2023-07-01",
        )
        for cost in COSTS_BPS
    }
    confirmation_halves = {
        "H1": subset_replay(
            rows,
            probabilities,
            bars,
            funding,
            18.0,
            "2023-01-01",
            "2023-04-01",
        ),
        "H2": subset_replay(
            rows,
            probabilities,
            bars,
            funding,
            18.0,
            "2023-04-01",
            "2023-07-01",
        ),
    }
    confirmation_winner18, confirmation_excluded = winner_removed(
        rows,
        probabilities,
        bars,
        funding,
        18.0,
        "2023-01-01",
        "2023-07-01",
    )
    confirmation_gate = gate_confirmation(
        confirmation_prediction,
        confirmation_accounts,
        confirmation_halves,
        confirmation_winner18,
    )
    result: dict[str, Any] = {
        "schema_version": 1,
        "claim_id": CLAIM_ID,
        "engine": ENGINE,
        "status": "CONFIRMATION_BELOW_GATE",
        "source_event_count": len(events),
        "source_bucket_count": len(source),
        "model_rows": {
            name: int((rows["partition"] == name).sum())
            for name in PARTITIONS
        },
        "train_resolved_rows": bundle["train_rows"],
        "calibration_resolved_rows": bundle["calibration_rows"],
        "confirmation_prediction": confirmation_prediction,
        "confirmation_accounts": confirmation_accounts,
        "confirmation_halves_18bps": confirmation_halves,
        "confirmation_winner_removed_18bps": confirmation_winner18,
        "confirmation_excluded_event_ids": confirmation_excluded,
        "confirmation_gate": confirmation_gate,
        "development_opened": False,
        "risk_frontier": None,
        "pre2024_survivor_ready_for_2024h1": False,
        "orders_submitted": False,
        "official_2024_2026_opened": False,
    }
    if confirmation_gate["all"]:
        development_accounts = {
            str(int(cost)): subset_replay(
                rows,
                probabilities,
                bars,
                funding,
                cost,
                "2023-07-01",
                "2024-01-01",
            )
            for cost in COSTS_BPS
        }
        development_quarters = {
            "Q3": subset_replay(
                rows,
                probabilities,
                bars,
                funding,
                18.0,
                "2023-07-01",
                "2023-10-01",
            ),
            "Q4": subset_replay(
                rows,
                probabilities,
                bars,
                funding,
                18.0,
                "2023-10-01",
                "2024-01-01",
            ),
        }
        development_winner18, development_excluded = winner_removed(
            rows,
            probabilities,
            bars,
            funding,
            18.0,
            "2023-07-01",
            "2024-01-01",
        )
        development_gate = gate_development(
            development_accounts,
            development_quarters,
            development_winner18,
        )
        result.update(
            {
                "status": "PRE2024_BELOW_GATE",
                "development_opened": True,
                "development_accounts": development_accounts,
                "development_quarters_18bps": development_quarters,
                "development_winner_removed_18bps": development_winner18,
                "development_excluded_event_ids": development_excluded,
                "development_gate": development_gate,
            }
        )
        if development_gate["all"]:
            frontier = risk_frontier(rows, probabilities, bars, funding)
            result["risk_frontier"] = frontier
            if frontier["selected"] is not None:
                result["status"] = (
                    "PRE2024_SURVIVOR_READY_FOR_SEQUENTIAL_2024H1"
                )
                result["pre2024_survivor_ready_for_2024h1"] = True
    compact = json_safe(result)
    (output / "RESULT.json").write_text(
        json.dumps(compact, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    rows.to_csv(output / "MODEL_ROWS.csv.gz", index=False, compression="gzip")
    source.to_csv(
        output / "SOURCE_BUCKETS.csv.gz", index=False, compression="gzip"
    )
    (output / "SHA256SUMS.txt").write_text(
        "".join(
            f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}\n"
            for path in sorted(output.iterdir())
            if path.is_file() and path.name != "SHA256SUMS.txt"
        ),
        encoding="utf-8",
    )
    return compact


def self_test() -> None:
    minute_index = pd.date_range(
        "2021-09-01", periods=1_200, freq="1min", tz="UTC"
    )
    base_price = (
        100.0
        + np.sin(np.arange(len(minute_index)) / 30.0)
        + 0.002 * np.arange(len(minute_index))
    )
    frame = pd.DataFrame(
        {
            "open_time_ms": minute_index.view("int64") // 1_000_000,
            "open": base_price,
            "high": base_price + 0.4,
            "low": base_price - 0.4,
            "close": base_price
            + 0.05 * np.sin(np.arange(len(minute_index))),
            "quote_volume": np.full(len(minute_index), 1_000_000.0),
            "taker_buy_quote": np.full(len(minute_index), 520_000.0),
        }
    )
    events = pd.DataFrame(
        [
            {
                "block_hash": "0x" + f"{index:064x}",
                "transaction_hash": "0x" + f"{index + 1:064x}",
                "log_index": index,
                "account": f"0x{index:040x}",
                "asset": "BTC" if index % 2 == 0 else "ETH",
                "removed_trader_exposure": (
                    "LONG_REMOVED" if index % 3 else "SHORT_REMOVED"
                ),
                "signed_removed_exposure_raw_1e30": (
                    (-1 if index % 3 else 1)
                    * (10_000_000 + index)
                    * 10**30
                ),
                "size_usd": 10_000_000 + index,
                "collateral_usd": 1_000_000,
                "realised_pnl_usd": -100_000,
                "causal_available_timestamp": int(
                    minute_index[120 + index * 10].timestamp()
                ),
                "external_market_order_direction_asserted": False,
            }
            for index in range(60)
        ]
    )
    temporary = Path("/tmp/gmx_v1_model_selftest.jsonl.gz")
    with gzip.open(temporary, "wt", encoding="utf-8") as handle:
        for row in events.to_dict("records"):
            handle.write(json.dumps(row) + "\n")
    loaded = load_source(temporary)
    buckets = aggregate_source(loaded)
    rows = build_rows(buckets, {symbol: frame.copy() for symbol in SYMBOLS})
    if rows.empty:
        raise AssertionError("synthetic model rows are empty")
    if (rows["feature_available_through_ms"] > rows["decision_ms"]).any():
        raise AssertionError("feature availability exceeds decision time")
    if not set(FEATURES).issubset(rows.columns):
        raise AssertionError("feature contract missing")
    print("GMX_V1_CONDITIONAL_ECONOMIC_SELF_TEST_PASS")


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("self-test")
    download = subparsers.add_parser("download-market")
    download.add_argument("--market-root", type=Path, required=True)
    execute = subparsers.add_parser("run")
    execute.add_argument("--source", type=Path, required=True)
    execute.add_argument("--market-root", type=Path, required=True)
    execute.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "self-test":
        self_test()
        return 0
    if args.command == "download-market":
        acquire_market(args.market_root)
        return 0
    result = run(args.source, args.market_root, args.output)
    print(
        json.dumps(
            {
                "status": result["status"],
                "ready_2024h1": result[
                    "pre2024_survivor_ready_for_2024h1"
                ],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
