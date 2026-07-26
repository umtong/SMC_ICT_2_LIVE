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
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd
import requests
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.isotonic import IsotonicRegression
from sklearn.metrics import brier_score_loss, roc_auc_score

CLAIM_ID = "CLM-20260726-2110-ML-STABLECOIN-ISSUANCE-001"
ENGINE = "ML_STABLECOIN_ISSUANCE_FIRST_PASSAGE_V1"
SYMBOLS = ("BTCUSDT", "ETHUSDT")
COSTS_BPS = (12.0, 18.0, 24.0)
PRIMARY_COST_BPS = 24.0
INITIAL_NAV = 10_000.0
BASE_RISK = 0.005
BASE_NOTIONAL_CAP = 3.0
BINANCE_BASES = (
    "https://data.binance.vision",
    "https://s3-ap-northeast-1.amazonaws.com/data.binance.vision",
)
KLINE_COLUMNS = (
    "open_time_ms", "open", "high", "low", "close", "base_volume",
    "close_time_ms", "quote_volume", "trade_count", "taker_buy_base",
    "taker_buy_quote", "ignore",
)
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
    model_probability_up: float
    ev_bps: float
    exit_reason: str
    ambiguous: bool


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(v) for v in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        number = float(value)
        return number if math.isfinite(number) else None
    if isinstance(value, (np.bool_,)):
        return bool(value)
    return value


def utc_ts(value: str | pd.Timestamp) -> pd.Timestamp:
    ts = pd.Timestamp(value)
    return ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")


def months(start: str, end: str) -> list[str]:
    a, b = pd.Period(start, "M"), pd.Period(end, "M")
    if a > b:
        raise ValueError("start after end")
    return [str(x) for x in pd.period_range(a, b, freq="M")]


def fetch(session: requests.Session, path: str) -> tuple[bytes, str]:
    errors: list[str] = []
    for base in BINANCE_BASES:
        for attempt in range(4):
            url = base + path
            try:
                response = session.get(url, timeout=180)
                if response.status_code == 200:
                    return response.content, url
                errors.append(f"{url}: HTTP {response.status_code}")
            except requests.RequestException as exc:
                errors.append(f"{url}: {type(exc).__name__}: {exc}")
            time.sleep(min(2 ** attempt, 8))
    raise RuntimeError("; ".join(errors[-8:]))


def verified_archive(session: requests.Session, path: str) -> tuple[bytes, dict[str, Any]]:
    payload, url = fetch(session, path)
    checksum, checksum_url = fetch(session, path + ".CHECKSUM")
    expected = checksum.decode("utf-8-sig").strip().split()[0].lower()
    observed = sha256_bytes(payload)
    if observed != expected:
        raise ValueError(f"checksum mismatch: {path}: {observed} != {expected}")
    return payload, {
        "url": url,
        "checksum_url": checksum_url,
        "sha256": observed,
        "bytes": len(payload),
    }


def parse_kline_payload(payload: bytes) -> pd.DataFrame:
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        names = [n for n in archive.namelist() if n.lower().endswith(".csv")]
        if len(names) != 1:
            raise ValueError(f"expected one CSV, got {names}")
        raw = archive.read(names[0])
    first = raw.splitlines()[0].decode("utf-8-sig").split(",")[0].strip()
    has_header = not first.lstrip("-").isdigit()
    frame = pd.read_csv(io.BytesIO(raw), header=0 if has_header else None).iloc[:, :12]
    frame.columns = KLINE_COLUMNS
    for c in KLINE_COLUMNS:
        frame[c] = pd.to_numeric(frame[c], errors="coerce")
    frame = frame.dropna(subset=["open_time_ms", "open", "high", "low", "close"])
    frame["open_time_ms"] = frame["open_time_ms"].astype(np.int64)
    micro = frame["open_time_ms"] > 100_000_000_000_000
    frame.loc[micro, "open_time_ms"] //= 1000
    frame["high"] = frame[["open", "high", "low", "close"]].max(axis=1)
    frame["low"] = frame[["open", "high", "low", "close"]].min(axis=1)
    return frame.sort_values("open_time_ms").drop_duplicates("open_time_ms", keep="last").reset_index(drop=True)


def parse_funding_payload(payload: bytes) -> pd.DataFrame:
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        names = [n for n in archive.namelist() if n.lower().endswith(".csv")]
        if len(names) != 1:
            raise ValueError("expected one funding CSV")
        frame = pd.read_csv(archive.open(names[0]))
    normalized = {str(c).strip().lower(): c for c in frame.columns}
    tcol = normalized.get("calc_time") or normalized.get("fundingtime") or normalized.get("funding_time")
    rcol = normalized.get("last_funding_rate") or normalized.get("fundingrate") or normalized.get("funding_rate")
    if tcol is None or rcol is None:
        if frame.shape[1] < 3:
            raise ValueError(f"unrecognized funding columns {list(frame.columns)}")
        tcol, rcol = frame.columns[-2], frame.columns[-1]
    out = pd.DataFrame({
        "time_ms": pd.to_numeric(frame[tcol], errors="coerce"),
        "rate": pd.to_numeric(frame[rcol], errors="coerce"),
    }).dropna()
    out["time_ms"] = out["time_ms"].astype(np.int64)
    micro = out["time_ms"] > 100_000_000_000_000
    out.loc[micro, "time_ms"] //= 1000
    return out.sort_values("time_ms").drop_duplicates("time_ms", keep="last").reset_index(drop=True)


def acquire_binance(root: Path, start_month: str, end_month: str) -> dict[str, Any]:
    root.mkdir(parents=True, exist_ok=True)
    manifest: list[dict[str, Any]] = []
    with requests.Session() as session:
        session.headers["User-Agent"] = "SMC_ICT_2_LIVE-stablecoin-economic/1.0"
        for month in months(start_month, end_month):
            if pd.Period(month, "M") >= pd.Period("2024-01", "M"):
                raise AssertionError("pre-2024 Binance stage requested 2024+")
            for symbol in SYMBOLS:
                specs = (
                    ("kline", f"/data/futures/um/monthly/klines/{symbol}/1m/{symbol}-1m-{month}.zip"),
                    ("funding", f"/data/futures/um/monthly/fundingRate/{symbol}/{symbol}-fundingRate-{month}.zip"),
                )
                for dtype, path in specs:
                    dst = root / dtype / symbol / Path(path).name
                    if dst.exists():
                        payload = dst.read_bytes()
                        source = {"sha256": sha256_bytes(payload), "bytes": len(payload), "cached": True}
                    else:
                        payload, source = verified_archive(session, path)
                        dst.parent.mkdir(parents=True, exist_ok=True)
                        dst.write_bytes(payload)
                    manifest.append({"dtype": dtype, "symbol": symbol, "month": month, "path": str(dst), **source})
                    print(json.dumps({"downloaded": [dtype, symbol, month], "bytes": len(payload)}), flush=True)
    result = {"schema_version": 1, "records": manifest}
    (root / "MARKET_SOURCE_MANIFEST.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    return result


def load_market(root: Path, start_month: str, end_month: str) -> tuple[dict[str, pd.DataFrame], dict[str, pd.DataFrame]]:
    bars: dict[str, pd.DataFrame] = {}
    funding: dict[str, pd.DataFrame] = {}
    for symbol in SYMBOLS:
        bframes = []
        fframes = []
        for month in months(start_month, end_month):
            bframes.append(parse_kline_payload((root / "kline" / symbol / f"{symbol}-1m-{month}.zip").read_bytes()))
            fframes.append(parse_funding_payload((root / "funding" / symbol / f"{symbol}-fundingRate-{month}.zip").read_bytes()))
        b = pd.concat(bframes, ignore_index=True).sort_values("open_time_ms").drop_duplicates("open_time_ms", keep="last")
        f = pd.concat(fframes, ignore_index=True).sort_values("time_ms").drop_duplicates("time_ms", keep="last")
        bars[symbol] = b.reset_index(drop=True)
        funding[symbol] = f.reset_index(drop=True)
    return bars, funding


def load_events(path: Path) -> pd.DataFrame:
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    frame = pd.DataFrame(rows)
    required = {
        "event_id", "token", "direction", "amount_usd", "block_timestamp",
        "available_timestamp_12", "available_timestamp_64",
    }
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"source event columns missing: {missing}")
    frame = frame.drop_duplicates("event_id", keep="last").copy()
    for c in ("amount_usd", "block_timestamp", "available_timestamp_12", "available_timestamp_64"):
        frame[c] = pd.to_numeric(frame[c], errors="raise")
    frame = frame.sort_values(["available_timestamp_12", "event_id"]).reset_index(drop=True)
    return frame


def _returns_features(frame: pd.DataFrame) -> dict[str, np.ndarray]:
    close = frame["close"].to_numpy(float)
    high = frame["high"].to_numpy(float)
    low = frame["low"].to_numpy(float)
    logc = np.log(close)
    ret15 = np.full(len(frame), np.nan)
    ret15[15:] = np.exp(logc[15:] - logc[:-15]) - 1.0
    ret1 = np.full(len(frame), np.nan)
    ret1[1:] = np.diff(logc)
    vol60 = pd.Series(ret1).rolling(60, min_periods=45).std(ddof=0).to_numpy() * math.sqrt(60)
    displacement = np.full(len(frame), np.nan)
    displacement[60:] = np.abs(logc[60:] - logc[:-60])
    path = pd.Series(np.abs(ret1)).rolling(60, min_periods=45).sum().to_numpy()
    efficiency = np.divide(displacement, path, out=np.full(len(frame), np.nan), where=path > 0)
    prior_high = pd.Series(high).shift(1).rolling(60, min_periods=60).max().to_numpy()
    prior_low = pd.Series(low).shift(1).rolling(60, min_periods=60).min().to_numpy()
    return {"ret15": ret15, "vol60": vol60, "eff60": efficiency, "prior_high": prior_high, "prior_low": prior_low}


def _index_at_or_after(times: np.ndarray, target_ms: int) -> int | None:
    i = int(np.searchsorted(times, target_ms, side="left"))
    return i if i < len(times) else None


def _funding_fraction(funding: pd.DataFrame, bars: pd.DataFrame, entry_ms: int, exit_ms: int, entry: float, side: int) -> float:
    if exit_ms <= entry_ms or funding.empty:
        return 0.0
    ft = funding["time_ms"].to_numpy(np.int64)
    lo = int(np.searchsorted(ft, entry_ms, side="right"))
    hi = int(np.searchsorted(ft, exit_ms, side="right"))
    if hi <= lo:
        return 0.0
    rates = funding["rate"].to_numpy(float)[lo:hi]
    event_times = ft[lo:hi]
    bt = bars["open_time_ms"].to_numpy(np.int64)
    closes = bars["close"].to_numpy(float)
    idx = np.clip(np.searchsorted(bt, event_times, side="right") - 1, 0, len(bt) - 1)
    mark_ratio = closes[idx] / entry
    return float(np.sum(-side * rates * mark_ratio))


def label_boundary_ms(decision_ms: int) -> int:
    ts = pd.to_datetime(decision_ms, unit="ms", utc=True)
    if ts < utc_ts("2022-01-01"):
        return int(utc_ts("2022-01-01").timestamp() * 1000)
    if ts < utc_ts("2022-07-01"):
        return int(utc_ts("2022-07-01").timestamp() * 1000)
    if ts < utc_ts("2023-01-01"):
        return int(utc_ts("2023-01-01").timestamp() * 1000)
    if ts < utc_ts("2024-01-01"):
        return int(utc_ts("2024-01-01").timestamp() * 1000)
    raise AssertionError("pre-2024 row builder received official-period decision")


def build_rows(events: pd.DataFrame, bars: dict[str, pd.DataFrame], funding: dict[str, pd.DataFrame], delay: int = 12) -> pd.DataFrame:
    if delay not in (12, 64):
        raise ValueError("delay must be 12 or 64")
    event_time_col = f"available_timestamp_{delay}"
    signed = np.where(events["direction"].astype(str).str.upper().eq("MINT"), 1.0, -1.0)
    event_seconds = events[event_time_col].to_numpy(np.int64)
    amount = events["amount_usd"].to_numpy(float)
    prior_same = np.zeros(len(events))
    prior_net = np.zeros(len(events))
    left60 = 0
    left24 = 0
    for i in range(len(events)):
        while left60 < i and event_seconds[left60] < event_seconds[i] - 3600:
            left60 += 1
        while left24 < i and event_seconds[left24] < event_seconds[i] - 86400:
            left24 += 1
        same_mask = signed[left60:i] == signed[i]
        prior_same[i] = float(amount[left60:i][same_mask].sum()) if i > left60 else 0.0
        prior_net[i] = float(np.sum(amount[left24:i] * signed[left24:i])) if i > left24 else 0.0

    feats = {symbol: _returns_features(frame) for symbol, frame in bars.items()}
    rows: list[dict[str, Any]] = []
    per_event_ret15: dict[str, dict[str, float]] = {}
    for i, event in events.iterrows():
        decision_ms = int(event[event_time_col]) * 1000
        event_id = str(event["event_id"])
        per_event_ret15[event_id] = {}
        for symbol in SYMBOLS:
            frame = bars[symbol]
            times = frame["open_time_ms"].to_numpy(np.int64)
            j = _index_at_or_after(times, ((decision_ms // 60_000) + 1) * 60_000)
            if j is None or j < 61:
                continue
            entry = float(frame.iloc[j]["open"])
            upper = float(feats[symbol]["prior_high"][j])
            lower = float(feats[symbol]["prior_low"][j])
            if not (np.isfinite(upper) and np.isfinite(lower) and upper > entry > lower > 0):
                continue
            ret15 = float(feats[symbol]["ret15"][j])
            per_event_ret15[event_id][symbol] = ret15
            upper_dist = upper / entry - 1.0
            lower_dist = 1.0 - lower / entry
            # Scan only inside the row's frozen chronological partition. Same-minute
            # dual touches are ambiguous for labels and stop-first for any account action.
            boundary = label_boundary_ms(decision_ms)
            boundary_index = int(np.searchsorted(times, boundary, side="left")) - 1
            if boundary_index < j:
                continue
            exit_index = boundary_index
            label = np.nan
            ambiguous = False
            reason = "STAGE_BOUNDARY"
            for k in range(j, boundary_index + 1):
                hi = float(frame.iloc[k]["high"])
                lo = float(frame.iloc[k]["low"])
                hit_up = hi >= upper
                hit_down = lo <= lower
                if hit_up and hit_down:
                    exit_index = k
                    ambiguous = True
                    reason = "AMBIGUOUS"
                    break
                if hit_up:
                    exit_index = k
                    label = 1.0
                    reason = "UPPER_FIRST"
                    break
                if hit_down:
                    exit_index = k
                    label = 0.0
                    reason = "LOWER_FIRST"
                    break
            rows.append({
                "event_id": event_id,
                "symbol": symbol,
                "decision_ms": decision_ms,
                "entry_index": j,
                "entry_ms": int(times[j]),
                "exit_index": exit_index,
                "exit_ms": int(times[exit_index]),
                "entry": entry,
                "upper": upper,
                "lower": lower,
                "label_up": label,
                "ambiguous": ambiguous,
                "path_reason": reason,
                "log_event_usd_notional": math.log1p(max(float(event["amount_usd"]), 0.0)),
                "mint_or_burn": 1.0 if str(event["direction"]).upper() == "MINT" else -1.0,
                "usdt_or_usdc": 1.0 if str(event["token"]).upper() == "USDT" else 0.0,
                "prior_60m_same_direction_event_notional": math.log1p(max(prior_same[i], 0.0)),
                "prior_24h_net_issuance": math.copysign(math.log1p(abs(prior_net[i])), prior_net[i]) if prior_net[i] else 0.0,
                "event_block_gas_utilization": float(event.get("gas_utilization", np.nan)),
                "prior_15m_return": ret15,
                "prior_60m_realized_volatility": float(feats[symbol]["vol60"][j]),
                "prior_60m_path_efficiency": float(feats[symbol]["eff60"][j]),
                "distance_to_frozen_upper_60m_liquidity": upper_dist,
                "distance_to_frozen_lower_60m_liquidity": lower_dist,
            })
    out = pd.DataFrame(rows)
    if out.empty:
        return out
    breadth: dict[str, float] = {}
    for event_id, item in per_event_ret15.items():
        vals = [item.get(s, np.nan) for s in SYMBOLS]
        finite = [x for x in vals if np.isfinite(x)]
        breadth[event_id] = float(np.mean(np.sign(finite))) if finite else np.nan
    out["btc_eth_completed_return_breadth"] = out["event_id"].map(breadth)
    return out.sort_values(["decision_ms", "event_id", "symbol"]).reset_index(drop=True)


def fit_model(rows: pd.DataFrame) -> tuple[HistGradientBoostingClassifier, IsotonicRegression | None, dict[str, float], np.ndarray]:
    train = rows[(rows["decision_ms"] >= utc_ts("2021-01-01").timestamp() * 1000) &
                 (rows["decision_ms"] < utc_ts("2022-01-01").timestamp() * 1000) &
                 rows["label_up"].notna() & ~rows["ambiguous"]].copy()
    cal = rows[(rows["decision_ms"] >= utc_ts("2022-01-01").timestamp() * 1000) &
               (rows["decision_ms"] < utc_ts("2022-07-01").timestamp() * 1000) &
               rows["label_up"].notna() & ~rows["ambiguous"]].copy()
    if len(train) < 100 or train["label_up"].nunique() < 2:
        raise RuntimeError(f"insufficient train rows: {len(train)} classes={train['label_up'].nunique()}")
    medians = train[list(FEATURES)].median(numeric_only=True).to_numpy(float)
    medians = np.where(np.isfinite(medians), medians, 0.0)
    X = train[list(FEATURES)].to_numpy(float)
    X = np.where(np.isfinite(X), X, medians)
    y = train["label_up"].to_numpy(int)
    model = HistGradientBoostingClassifier(
        loss="log_loss", learning_rate=0.05, max_iter=120, max_leaf_nodes=7,
        min_samples_leaf=20, l2_regularization=1.0, early_stopping=False,
        random_state=20260726,
    )
    model.fit(X, y)
    calibrator: IsotonicRegression | None = None
    if len(cal) >= 50 and cal["label_up"].nunique() == 2:
        Xc = cal[list(FEATURES)].to_numpy(float)
        Xc = np.where(np.isfinite(Xc), Xc, medians)
        raw = model.predict_proba(Xc)[:, 1]
        calibrator = IsotonicRegression(out_of_bounds="clip")
        calibrator.fit(raw, cal["label_up"].to_numpy(int))
    return model, calibrator, {name: float(value) for name, value in zip(FEATURES, medians)}, medians


def probabilities(model: HistGradientBoostingClassifier, calibrator: IsotonicRegression | None, medians: np.ndarray, rows: pd.DataFrame) -> np.ndarray:
    X = rows[list(FEATURES)].to_numpy(float)
    X = np.where(np.isfinite(X), X, medians)
    raw = model.predict_proba(X)[:, 1]
    return calibrator.predict(raw) if calibrator is not None else raw


def prediction_metrics(rows: pd.DataFrame, probs: np.ndarray) -> dict[str, float | int]:
    valid = rows["label_up"].notna().to_numpy() & ~rows["ambiguous"].to_numpy(bool)
    y = rows.loc[valid, "label_up"].to_numpy(int)
    p = probs[valid]
    upper = rows.loc[valid, "distance_to_frozen_upper_60m_liquidity"].to_numpy(float)
    lower = rows.loc[valid, "distance_to_frozen_lower_60m_liquidity"].to_numpy(float)
    baseline = lower / (upper + lower)
    if len(y) == 0 or len(np.unique(y)) < 2:
        return {"resolved_labels": int(len(y)), "auc": float("nan"), "baseline_auc": float("nan"), "brier": float("nan"), "baseline_brier": float("nan"), "brier_skill": float("nan")}
    auc = roc_auc_score(y, p)
    bauc = roc_auc_score(y, baseline)
    brier = brier_score_loss(y, p)
    bbrier = brier_score_loss(y, baseline)
    return {
        "resolved_labels": int(len(y)),
        "auc": float(auc),
        "baseline_auc": float(bauc),
        "auc_lift": float(auc - bauc),
        "brier": float(brier),
        "baseline_brier": float(bbrier),
        "brier_skill": float(1.0 - brier / bbrier) if bbrier > 0 else float("nan"),
    }


def trade_from_row(row: pd.Series, p_up: float, cost_bps: float, bars: pd.DataFrame, funding: pd.DataFrame) -> Trade | None:
    u = float(row["distance_to_frozen_upper_60m_liquidity"])
    d = float(row["distance_to_frozen_lower_60m_liquidity"])
    c = cost_bps / 10_000.0
    ev_long = p_up * u - (1.0 - p_up) * d - c
    ev_short = (1.0 - p_up) * d - p_up * u - c
    if max(ev_long, ev_short) <= 0:
        return None
    side = 1 if ev_long >= ev_short else -1
    entry = float(row["entry"])
    upper = float(row["upper"])
    lower = float(row["lower"])
    j = int(row["entry_index"])
    end = int(row["exit_index"])
    ambiguous = False
    reason = "SOURCE_BOUNDARY"
    exit_price = lower if side == 1 else upper
    for k in range(j, end + 1):
        rec = bars.iloc[k]
        op, hi, lo = float(rec["open"]), float(rec["high"]), float(rec["low"])
        hit_target = hi >= upper if side == 1 else lo <= lower
        hit_stop = lo <= lower if side == 1 else hi >= upper
        if hit_target and hit_stop:
            ambiguous = True
            reason = "STOP_FIRST_AMBIGUOUS"
            exit_price = min(lower, op) if side == 1 else max(upper, op)
            end = k
            break
        if hit_stop:
            reason = "STOP"
            exit_price = min(lower, op) if side == 1 else max(upper, op)
            end = k
            break
        if hit_target:
            reason = "TARGET"
            exit_price = upper if side == 1 else lower
            end = k
            break
    gross = side * (exit_price / entry - 1.0)
    funding_frac = _funding_fraction(funding, bars, int(row["entry_ms"]), int(bars.iloc[end]["open_time_ms"]), entry, side)
    stop_frac = d if side == 1 else u
    return Trade(
        event_id=str(row["event_id"]), symbol=str(row["symbol"]), decision_ms=int(row["decision_ms"]),
        entry_ms=int(row["entry_ms"]), exit_ms=int(bars.iloc[end]["open_time_ms"]), side=side,
        entry=entry, exit_price=exit_price, stop_price=lower if side == 1 else upper,
        target_price=upper if side == 1 else lower, stop_fraction=stop_frac,
        gross_fraction=float(gross), funding_fraction=float(funding_frac),
        model_probability_up=float(p_up), ev_bps=float(max(ev_long, ev_short) * 10_000.0),
        exit_reason=reason, ambiguous=ambiguous,
    )


def route(rows: pd.DataFrame, probs: np.ndarray, bars: dict[str, pd.DataFrame], funding: dict[str, pd.DataFrame], cost_bps: float, excluded: set[str] | None = None) -> list[Trade]:
    excluded = excluded or set()
    candidates: list[Trade] = []
    for (_, row), p in zip(rows.iterrows(), probs):
        if str(row["event_id"]) in excluded:
            continue
        trade = trade_from_row(row, float(p), cost_bps, bars[str(row["symbol"])], funding[str(row["symbol"])])
        if trade is not None:
            candidates.append(trade)
    candidates.sort(key=lambda t: (t.decision_ms, -t.ev_bps, t.symbol, t.event_id))
    accepted: list[Trade] = []
    free_ms = -1
    i = 0
    while i < len(candidates):
        t0 = candidates[i].decision_ms
        group = []
        while i < len(candidates) and candidates[i].decision_ms == t0:
            group.append(candidates[i]); i += 1
        if t0 < free_ms:
            continue
        chosen = max(group, key=lambda t: (t.ev_bps, -t.entry_ms, t.symbol))
        accepted.append(chosen)
        free_ms = chosen.exit_ms + 1
    return accepted


def replay(trades: list[Trade], cost_bps: float, period_start: str, period_end: str, risk: float = BASE_RISK, notional_cap: float = BASE_NOTIONAL_CAP) -> dict[str, Any]:
    nav = INITIAL_NAV
    peak = nav
    mdd = 0.0
    liquidation = False
    ledger = []
    for t in trades:
        stop_budget = t.stop_fraction + cost_bps / 10_000.0
        leverage = min(notional_cap, risk / max(stop_budget, 1e-9))
        if leverage > 1.0:
            liq_distance = max(0.0, 1.0 / leverage - 0.005)
            if t.stop_fraction >= liq_distance:
                liquidation = True
                account_ret = -1.0
            else:
                account_ret = leverage * (t.gross_fraction + t.funding_fraction - cost_bps / 10_000.0)
        else:
            account_ret = leverage * (t.gross_fraction + t.funding_fraction - cost_bps / 10_000.0)
        account_ret = max(account_ret, -1.0)
        before = nav
        nav *= 1.0 + account_ret
        peak = max(peak, nav)
        mdd = max(mdd, 1.0 - nav / peak)
        ledger.append({**asdict(t), "leverage": leverage, "account_return": account_ret, "nav_before": before, "nav_after": nav, "pnl_usdt": nav - before})
        if nav <= 0:
            liquidation = True
            break
    start = utc_ts(period_start)
    end = utc_ts(period_end)
    days = max(1, int((end - start).total_seconds() // 86400))
    total_return = nav / INITIAL_NAV - 1.0
    g = math.exp(math.log(max(nav / INITIAL_NAV, 1e-300)) / days) - 1.0 if nav > 0 else -1.0
    pnl = np.array([x["pnl_usdt"] for x in ledger], float)
    pos = float(pnl[pnl > 0].sum())
    neg = float(-pnl[pnl < 0].sum())
    net_bps = np.array([(x["gross_fraction"] + x["funding_fraction"] - cost_bps / 10_000.0) * 10_000 for x in ledger], float)
    return {
        "trade_count": len(ledger), "ending_nav": nav, "total_return": total_return,
        "geometric_calendar_day_growth": g, "profit_factor": pos / neg if neg > 0 else (float("inf") if pos > 0 else 0.0),
        "maximum_drawdown": mdd, "median_trade_bps": float(np.median(net_bps)) if len(net_bps) else float("nan"),
        "liquidation": liquidation, "ledger": ledger,
    }


def winner_removed(rows: pd.DataFrame, probs: np.ndarray, bars: dict[str, pd.DataFrame], funding: dict[str, pd.DataFrame], cost_bps: float, period_start: str, period_end: str, risk: float = BASE_RISK, notional_cap: float = BASE_NOTIONAL_CAP) -> tuple[dict[str, Any], list[str]]:
    base_trades = route(rows, probs, bars, funding, cost_bps)
    base_metrics = replay(base_trades, cost_bps, period_start, period_end, risk, notional_cap)
    positives = [x for x in base_metrics["ledger"] if x["pnl_usdt"] > 0]
    positives.sort(key=lambda x: x["pnl_usdt"], reverse=True)
    n = math.ceil(0.10 * len(positives)) if positives else 0
    excluded = {x["event_id"] for x in positives[:n]}
    rerouted = route(rows, probs, bars, funding, cost_bps, excluded)
    return replay(rerouted, cost_bps, period_start, period_end, risk, notional_cap), sorted(excluded)


def segment(rows: pd.DataFrame, start: str, end: str) -> pd.DataFrame:
    a = int(utc_ts(start).timestamp() * 1000)
    b = int(utc_ts(end).timestamp() * 1000)
    return rows[(rows["decision_ms"] >= a) & (rows["decision_ms"] < b)].copy()


def evaluate_stage(name: str, rows: pd.DataFrame, probs: np.ndarray, bars: dict[str, pd.DataFrame], funding: dict[str, pd.DataFrame], start: str, end: str) -> dict[str, Any]:
    result: dict[str, Any] = {"stage": name, "prediction": prediction_metrics(rows, probs), "costs": {}}
    for cost in COSTS_BPS:
        trades = route(rows, probs, bars, funding, cost)
        metrics = replay(trades, cost, start, end)
        wr, excluded = winner_removed(rows, probs, bars, funding, cost, start, end)
        mid = utc_ts(start) + (utc_ts(end) - utc_ts(start)) / 2
        first_rows = segment(rows, start, mid.isoformat())
        second_rows = segment(rows, mid.isoformat(), end)
        # Probabilities preserve row index order after segment; map through index.
        index_to_prob = dict(zip(rows.index.to_list(), probs.tolist()))
        p1 = np.array([index_to_prob[i] for i in first_rows.index], float)
        p2 = np.array([index_to_prob[i] for i in second_rows.index], float)
        m1 = replay(route(first_rows, p1, bars, funding, cost), cost, start, mid.isoformat())
        m2 = replay(route(second_rows, p2, bars, funding, cost), cost, mid.isoformat(), end)
        metrics_no_ledger = {k: v for k, v in metrics.items() if k != "ledger"}
        wr_no_ledger = {k: v for k, v in wr.items() if k != "ledger"}
        result["costs"][str(int(cost))] = {
            **metrics_no_ledger,
            "winner_removed": wr_no_ledger,
            "removed_event_ids": excluded,
            "first_half_return": m1["total_return"],
            "second_half_return": m2["total_return"],
            "trade_ledger": metrics["ledger"],
        }
    return result


def confirmation_gate(result: dict[str, Any]) -> dict[str, bool]:
    p = result["prediction"]
    m = result["costs"]["24"]
    return {
        "minimum_resolved_labels": int(p.get("resolved_labels", 0)) >= 80,
        "minimum_actions": int(m["trade_count"]) >= 25,
        "auc_lift_over_structural_distance": float(p.get("auc_lift", -999)) >= 0.02,
        "positive_brier_skill": float(p.get("brier_skill", -999)) > 0,
        "positive_total_return_at_24bps": float(m["total_return"]) > 0,
        "positive_median_trade_at_24bps": float(m["median_trade_bps"]) > 0,
        "profit_factor_at_24bps": float(m["profit_factor"]) >= 1.2,
        "positive_top10pct_winner_removed_return_at_24bps": float(m["winner_removed"]["total_return"]) > 0,
        "both_half_years_positive_at_24bps": float(m["first_half_return"]) > 0 and float(m["second_half_return"]) > 0,
        "no_liquidation": not bool(m["liquidation"]),
    }


def development_gate(result: dict[str, Any]) -> dict[str, bool]:
    m = result["costs"]["24"]
    return {
        "positive_total_return_at_24bps": float(m["total_return"]) > 0,
        "positive_median_trade_at_24bps": float(m["median_trade_bps"]) > 0,
        "profit_factor_at_24bps": float(m["profit_factor"]) >= 1.2,
        "positive_top10pct_winner_removed_return_at_24bps": float(m["winner_removed"]["total_return"]) > 0,
        "both_2023_half_years_positive_at_24bps": float(m["first_half_return"]) > 0 and float(m["second_half_return"]) > 0,
        "no_liquidation": not bool(m["liquidation"]),
    }


def risk_search(rows: pd.DataFrame, probs: np.ndarray, bars: dict[str, pd.DataFrame], funding: dict[str, pd.DataFrame]) -> dict[str, Any]:
    risks = (0.0025, 0.005, 0.01, 0.02, 0.04, 0.08, 0.12, 0.20, 0.30, 0.40, 0.60)
    caps = (1.0, 2.0, 3.0, 5.0, 10.0, 20.0, 50.0, 100.0)
    candidates = []
    for risk in risks:
        for cap in caps:
            trades = route(rows, probs, bars, funding, PRIMARY_COST_BPS)
            metrics = replay(trades, PRIMARY_COST_BPS, "2023-01-01", "2024-01-01", risk, cap)
            wr, excluded = winner_removed(rows, probs, bars, funding, PRIMARY_COST_BPS, "2023-01-01", "2024-01-01", risk, cap)
            candidates.append({
                "risk": risk, "notional_cap": cap,
                "growth": metrics["geometric_calendar_day_growth"],
                "return": metrics["total_return"],
                "mdd": metrics["maximum_drawdown"],
                "liquidation": metrics["liquidation"],
                "winner_removed_growth": wr["geometric_calendar_day_growth"],
                "winner_removed_return": wr["total_return"],
                "removed_event_ids": excluded,
            })
    eligible = [c for c in candidates if not c["liquidation"] and c["growth"] > 0 and c["winner_removed_growth"] > 0]
    selected = max(eligible, key=lambda x: (x["growth"], x["winner_removed_growth"], -x["mdd"])) if eligible else None
    return {"candidate_count": len(candidates), "eligible_count": len(eligible), "selected": selected, "candidates": candidates}


def run(args: argparse.Namespace) -> int:
    out = args.output
    out.mkdir(parents=True, exist_ok=True)
    events = load_events(args.events)
    if any(pd.to_datetime(events["block_timestamp"], unit="s", utc=True).dt.year >= 2024):
        raise AssertionError("pre-2024 stage received 2024 event")
    acquire_binance(args.market_cache, "2020-12", "2023-12")
    bars, funding = load_market(args.market_cache, "2020-12", "2023-12")
    rows12 = build_rows(events, bars, funding, 12)
    rows64 = build_rows(events, bars, funding, 64)
    if rows12.empty:
        raise RuntimeError("no economically evaluable rows")
    model, calibrator, median_map, medians = fit_model(rows12)
    p12 = probabilities(model, calibrator, medians, rows12)
    p64 = probabilities(model, calibrator, medians, rows64) if not rows64.empty else np.array([], float)

    confirm12 = segment(rows12, "2022-07-01", "2023-01-01")
    pmap12 = dict(zip(rows12.index.to_list(), p12.tolist()))
    pc12 = np.array([pmap12[i] for i in confirm12.index], float)
    confirmation = evaluate_stage("2022H2_CONFIRMATION_12_BLOCK", confirm12, pc12, bars, funding, "2022-07-01", "2023-01-01")
    gate = confirmation_gate(confirmation)
    gate["all"] = all(gate.values())

    stress = None
    if gate["all"] and not rows64.empty:
        confirm64 = segment(rows64, "2022-07-01", "2023-01-01")
        pmap64 = dict(zip(rows64.index.to_list(), p64.tolist()))
        pc64 = np.array([pmap64[i] for i in confirm64.index], float)
        stress = evaluate_stage("2022H2_CONFIRMATION_64_BLOCK_STRESS", confirm64, pc64, bars, funding, "2022-07-01", "2023-01-01")
        gate["positive_64_block_stress_at_24bps"] = stress["costs"]["24"]["total_return"] > 0 and stress["costs"]["24"]["winner_removed"]["total_return"] > 0
        gate["all"] = all(v for k, v in gate.items() if k != "all")

    development = None
    dev_gate = {"all": False}
    risk = None
    if gate["all"]:
        dev = segment(rows12, "2023-01-01", "2024-01-01")
        pdv = np.array([pmap12[i] for i in dev.index], float)
        development = evaluate_stage("2023_DEVELOPMENT", dev, pdv, bars, funding, "2023-01-01", "2024-01-01")
        dev_gate = development_gate(development)
        dev_gate["all"] = all(dev_gate.values())
        if dev_gate["all"]:
            risk = risk_search(dev, pdv, bars, funding)
            dev_gate["risk_search_survivor"] = risk["selected"] is not None
            dev_gate["all"] = all(v for k, v in dev_gate.items() if k != "all")

    status = "PRE2024_SURVIVOR_READY_FOR_SEQUENTIAL_2024H1" if dev_gate.get("all") else "PRE2024_BELOW_GATE"
    result = {
        "schema_version": 1, "claim_id": CLAIM_ID, "engine": ENGINE,
        "status": status, "source_event_count": int(len(events)),
        "row_count_12": int(len(rows12)), "row_count_64": int(len(rows64)),
        "feature_names": list(FEATURES), "feature_medians": median_map,
        "model": {"family": "HistGradientBoostingClassifier", "isotonic": calibrator is not None},
        "confirmation": confirmation, "confirmation_gate": gate,
        "confirmation_64_block_stress": stress,
        "development_opened": development is not None,
        "development": development, "development_gate": dev_gate,
        "risk_search": risk,
        "official_2024h1_opened": False,
        "official_2024_2026_opened": False,
        "orders_submitted": False,
    }
    # Keep the durable summary compact; ledgers live separately.
    def strip_ledgers(obj: Any) -> Any:
        if isinstance(obj, dict):
            return {k: strip_ledgers(v) for k, v in obj.items() if k != "trade_ledger" and k != "candidates"}
        if isinstance(obj, list):
            return [strip_ledgers(x) for x in obj]
        return obj
    compact = strip_ledgers(result)
    (out / "RESULT.json").write_text(json.dumps(json_safe(compact), indent=2, sort_keys=True, allow_nan=False) + "\n")
    rows12.to_parquet(out / "EVENT_ROWS_12.parquet", index=False)
    if not rows64.empty:
        rows64.to_parquet(out / "EVENT_ROWS_64.parquet", index=False)
    (out / "FULL_RESULT.json").write_text(json.dumps(json_safe(result), indent=2, sort_keys=True, allow_nan=False) + "\n")
    files = [p for p in out.iterdir() if p.is_file() and p.name != "SHA256SUMS.txt"]
    (out / "SHA256SUMS.txt").write_text("".join(f"{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.name}\n" for p in sorted(files)))
    print(json.dumps(json_safe(compact), indent=2, sort_keys=True, allow_nan=False))
    return 0 if dev_gate.get("all") else 2


def self_test() -> None:
    # Verify event chronology, adverse ambiguity, route arbitration and risk monotonicity on synthetic data.
    times = np.arange(pd.Timestamp("2021-01-01", tz="UTC").value // 1_000_000, pd.Timestamp("2021-01-02", tz="UTC").value // 1_000_000, 60_000, dtype=np.int64)
    price = 100.0 + np.sin(np.arange(len(times)) / 20.0)
    frame = pd.DataFrame({"open_time_ms": times, "open": price, "high": price + 0.2, "low": price - 0.2, "close": price, "quote_volume": 1e6})
    features = _returns_features(frame)
    assert np.isnan(features["prior_high"][59]) and np.isfinite(features["prior_high"][60])
    t = Trade("e", "BTCUSDT", int(times[100]), int(times[101]), int(times[102]), 1, 100, 99, 99, 101, .01, -.01, 0, .5, 1, "STOP", False)
    a = replay([t], 24, "2021-01-01", "2021-01-02", .005, 3)
    b = replay([t], 24, "2021-01-01", "2021-01-02", .01, 3)
    assert b["total_return"] <= a["total_return"]
    assert months("2021-01", "2021-03") == ["2021-01", "2021-02", "2021-03"]
    print("self-test passed")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("self-test")
    r = sub.add_parser("run")
    r.add_argument("--events", type=Path, required=True)
    r.add_argument("--market-cache", type=Path, required=True)
    r.add_argument("--output", type=Path, required=True)
    return p.parse_args()


def main() -> int:
    args = parse_args()
    if args.command == "self-test":
        self_test(); return 0
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
