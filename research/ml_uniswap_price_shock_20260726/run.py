from __future__ import annotations

import argparse
import calendar
import gzip
import hashlib
import json
import math
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd
import requests
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.isotonic import IsotonicRegression
from sklearn.metrics import brier_score_loss, roc_auc_score

CLAIM_ID = "CLM-20260726-2350-ML-UNISWAP-PRICE-SHOCK-001"
RESULT_ID = "RES-20260726-ML-UNISWAP-PRICE-SHOCK-001"
UNISWAP_DATASET = "arthurneuron/USDC-WETH-Uniswap-V3-2021-to-2023"
BLOCK_DATASET = "vnegi10/Ethereum_blockchain_parquet"
UNISWAP_MIN_BLOCK = 12_376_729
UNISWAP_MAX_BLOCK = 18_700_000
PARQUET_API = f"https://datasets-server.huggingface.co/parquet?dataset={UNISWAP_DATASET}"
BLOCK_META_API = f"https://huggingface.co/api/datasets/{BLOCK_DATASET}"
BLOCK_TREE_API = f"https://huggingface.co/api/datasets/{BLOCK_DATASET}/tree/main/blocks?recursive=true&expand=false&limit=1000"
BYBIT_BASE = "https://public.bybit.com/kline_for_metatrader4"
UTC = timezone.utc
DECISION_COST_BPS = 18.0
ADVERSE_FUNDING_BPS = 1.0
MAINTENANCE_MARGIN_FRACTION = 0.005
FEATURES = [
    "log1p_usdc_increment",
    "log1p_weth_increment",
    "signed_pool_return",
    "absolute_pool_return",
    "pool_impact_efficiency",
    "transaction_increment",
    "usdc_to_weth_value_ratio_log",
    "prior_completed_15m_eth_return",
    "prior_completed_60m_eth_realized_volatility",
    "prior_completed_60m_path_efficiency",
    "pool_to_eth_basis_z",
    "upper_external_liquidity_distance",
    "lower_external_liquidity_distance",
]
PARTITIONS = {
    "fit": (pd.Timestamp("2021-07-01", tz="UTC"), pd.Timestamp("2022-07-01", tz="UTC")),
    "calibration": (pd.Timestamp("2022-07-01", tz="UTC"), pd.Timestamp("2023-01-01", tz="UTC")),
    "confirmation": (pd.Timestamp("2023-01-01", tz="UTC"), pd.Timestamp("2023-07-01", tz="UTC")),
    "development": (pd.Timestamp("2023-07-01", tz="UTC"), pd.Timestamp("2024-01-01", tz="UTC")),
}


class ScreenError(RuntimeError):
    pass


@dataclass(frozen=True)
class Event:
    event_id: str
    partition: str
    bucket_start: str
    decision_time: str
    entry_time: str
    entry_index: int
    entry_price: float
    upper_price: float
    lower_price: float
    upper_distance: float
    lower_distance: float
    label: int | None
    ambiguous: bool
    features: dict[str, float]


@dataclass(frozen=True)
class Pivot:
    kind: str
    pivot_time_ns: int
    confirm_time_ns: int
    level: float


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def request_json(session: requests.Session, url: str, attempts: int = 6) -> Any:
    last: Exception | None = None
    for attempt in range(attempts):
        try:
            response = session.get(url, timeout=(30, 180))
            response.raise_for_status()
            return response.json()
        except Exception as exc:
            last = exc
            if attempt + 1 >= attempts:
                break
            time.sleep(min(20.0, 2**attempt))
    raise ScreenError(f"request failed {url}: {last}")


def download(session: requests.Session, url: str, path: Path, attempts: int = 6) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists() or path.stat().st_size == 0:
        tmp = path.with_suffix(path.suffix + ".part")
        last: Exception | None = None
        for attempt in range(attempts):
            try:
                with session.get(url, stream=True, timeout=(30, 300), allow_redirects=True) as response:
                    response.raise_for_status()
                    with tmp.open("wb") as handle:
                        for chunk in response.iter_content(1 << 20):
                            if chunk:
                                handle.write(chunk)
                tmp.replace(path)
                break
            except Exception as exc:
                last = exc
                tmp.unlink(missing_ok=True)
                if attempt + 1 >= attempts:
                    break
                time.sleep(min(20.0, 2**attempt))
        if not path.exists():
            raise ScreenError(f"download failed {url}: {last}")
    return {"url": url, "path": str(path), "bytes": path.stat().st_size, "sha256": sha256_file(path)}


def parquet_entries(payload: Any) -> list[dict[str, str]]:
    candidates = payload.get("parquet_files") or payload.get("files") or [] if isinstance(payload, dict) else []
    rows: list[dict[str, str]] = []
    for item in candidates:
        if not isinstance(item, dict) or not item.get("url"):
            continue
        url = str(item["url"])
        rows.append({"url": url, "filename": str(item.get("filename") or item.get("path") or url.rsplit("/", 1)[-1])})
    return rows


def block_entries(payload: Any) -> list[dict[str, Any]]:
    import re

    pattern = re.compile(r"__(\d+)_to_(\d+)\.parquet$")
    rows = []
    for item in payload if isinstance(payload, list) else []:
        path = str(item.get("path") or "") if isinstance(item, dict) else ""
        match = pattern.search(path)
        if not match:
            continue
        lo, hi = map(int, match.groups())
        if hi < UNISWAP_MIN_BLOCK or lo > UNISWAP_MAX_BLOCK:
            continue
        rows.append({"path": path, "lo": lo, "hi": hi})
    return sorted(rows, key=lambda row: row["lo"])


def build_uniswap_5m(cache: Path, session: requests.Session) -> tuple[pd.DataFrame, dict[str, Any]]:
    output = cache / "derived" / "uniswap_5m.parquet"
    manifest_path = cache / "derived" / "uniswap_manifest.json"
    if output.exists() and manifest_path.exists():
        return pd.read_parquet(output), json.loads(manifest_path.read_text())

    uni_payload = request_json(session, PARQUET_API)
    uni_entries = parquet_entries(uni_payload)
    if not uni_entries:
        raise ScreenError("no Uniswap parquet entries")
    uni_frames = []
    uni_records = []
    for index, item in enumerate(uni_entries):
        path = cache / "uniswap" / f"part-{index:03d}.parquet"
        record = download(session, item["url"], path)
        frame = pd.read_parquet(path, columns=["Block", "USDC", "WETH", "Transactions", "Price"])
        frame.columns = ["block", "usdc", "weth", "transactions", "price"]
        for column in frame.columns:
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
        frame = frame.dropna().astype({"block": "int64"})
        uni_frames.append(frame)
        record.update({"rows": int(len(frame)), "filename": item["filename"]})
        uni_records.append(record)
    uni = pd.concat(uni_frames, ignore_index=True)
    del uni_frames
    uni = uni.sort_values("block").drop_duplicates("block", keep="last")
    if len(uni) < 6_000_000:
        raise ScreenError(f"Uniswap rows below source contract: {len(uni)}")

    block_meta = request_json(session, BLOCK_META_API)
    block_sha = str(block_meta.get("sha") or "main") if isinstance(block_meta, dict) else "main"
    tree = request_json(session, BLOCK_TREE_API)
    entries = block_entries(tree)
    if not entries:
        raise ScreenError("no block timestamp parquet entries")
    block_frames = []
    block_records = []
    for item in entries:
        url = f"https://huggingface.co/datasets/{BLOCK_DATASET}/resolve/{block_sha}/{item['path']}?download=true"
        path = cache / "blocks" / Path(item["path"]).name
        record = download(session, url, path)
        frame = pd.read_parquet(path, columns=["block_number", "timestamp"])
        frame.columns = ["block", "timestamp"]
        frame["block"] = pd.to_numeric(frame["block"], errors="coerce")
        frame["timestamp"] = pd.to_numeric(frame["timestamp"], errors="coerce")
        frame = frame.dropna().astype({"block": "int64", "timestamp": "int64"})
        block_frames.append(frame)
        record.update({"rows": int(len(frame)), "source_path": item["path"]})
        block_records.append(record)
    blocks = pd.concat(block_frames, ignore_index=True).drop_duplicates("block", keep="last")
    del block_frames
    joined = uni.merge(blocks, on="block", how="left", validate="one_to_one")
    if joined["timestamp"].isna().any():
        raise ScreenError(f"missing timestamps for {int(joined['timestamp'].isna().sum())} Uniswap rows")
    joined = joined.sort_values("block")
    for source, target in (("usdc", "delta_usdc"), ("weth", "delta_weth"), ("transactions", "delta_transactions")):
        joined[target] = joined[source].diff()
        joined.loc[~np.isfinite(joined[target]) | (joined[target] < 0), target] = 0.0
    joined["bucket_ns"] = (joined["timestamp"].astype("int64") // 300 * 300) * 1_000_000_000
    grouped = joined.groupby("bucket_ns", sort=True).agg(
        usdc_increment=("delta_usdc", "sum"),
        weth_increment=("delta_weth", "sum"),
        transaction_increment=("delta_transactions", "sum"),
        price_first=("price", "first"),
        price_last=("price", "last"),
        block_first=("block", "first"),
        block_last=("block", "last"),
        source_rows=("block", "size"),
    ).reset_index()
    grouped["timestamp"] = pd.to_datetime(grouped.pop("bucket_ns"), utc=True)
    grouped = grouped[["timestamp", "usdc_increment", "weth_increment", "transaction_increment", "price_first", "price_last", "block_first", "block_last", "source_rows"]]
    grouped.to_parquet(output, index=False)
    manifest = {
        "uniswap_dataset": UNISWAP_DATASET,
        "block_dataset": BLOCK_DATASET,
        "block_revision": block_sha,
        "uniswap_records": uni_records,
        "block_records": block_records,
        "uniswap_rows": int(len(uni)),
        "block_rows": int(len(blocks)),
        "five_minute_rows": int(len(grouped)),
        "output_sha256": sha256_file(output),
    }
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    return grouped, manifest


def bybit_url(year: int, month: int) -> str:
    last = calendar.monthrange(year, month)[1]
    filename = f"ETHUSDT_5_{year:04d}-{month:02d}-01_{year:04d}-{month:02d}-{last:02d}.csv.gz"
    return f"{BYBIT_BASE}/ETHUSDT/{year}/{filename}"


def load_bybit(cache: Path, session: requests.Session) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    output = cache / "derived" / "bybit_ethusdt_5m.parquet"
    manifest_path = cache / "derived" / "bybit_manifest.json"
    if output.exists() and manifest_path.exists():
        return pd.read_parquet(output), json.loads(manifest_path.read_text())["records"]
    frames = []
    records = []
    for year in (2021, 2022, 2023):
        start_month = 6 if year == 2021 else 1
        for month in range(start_month, 13):
            url = bybit_url(year, month)
            path = cache / "bybit" / str(year) / url.rsplit("/", 1)[-1]
            record = download(session, url, path)
            frame = pd.read_csv(path, compression="gzip", header=None, low_memory=False)
            if frame.shape[1] < 6:
                raise ScreenError(f"Bybit schema has {frame.shape[1]} columns: {path}")
            frame = frame.iloc[:, :6]
            frame.columns = ["timestamp", "open", "high", "low", "close", "volume"]
            frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True, errors="coerce", format="mixed")
            for column in ["open", "high", "low", "close", "volume"]:
                frame[column] = pd.to_numeric(frame[column], errors="coerce")
            frame = frame.dropna().sort_values("timestamp")
            frames.append(frame)
            record.update({"rows": int(len(frame)), "year": year, "month": month})
            records.append(record)
    bars = pd.concat(frames, ignore_index=True).sort_values("timestamp").drop_duplicates("timestamp", keep="last")
    bars = bars[(bars["timestamp"] >= pd.Timestamp("2021-06-01", tz="UTC")) & (bars["timestamp"] < pd.Timestamp("2024-01-01", tz="UTC"))].reset_index(drop=True)
    diff = bars["timestamp"].diff().dt.total_seconds().fillna(300)
    bars["segment"] = (diff != 300).cumsum().astype("int64")
    if len(bars) < 250_000:
        raise ScreenError(f"Bybit coverage insufficient: {len(bars)} rows")
    output.parent.mkdir(parents=True, exist_ok=True)
    bars.to_parquet(output, index=False)
    manifest_path.write_text(json.dumps({"records": records, "rows": int(len(bars)), "output_sha256": sha256_file(output)}, indent=2, sort_keys=True) + "\n")
    return bars, records


def build_pivots(bars: pd.DataFrame) -> list[Pivot]:
    indexed = bars.set_index("timestamp")
    fifteen = indexed.groupby("segment").resample("15min", origin="epoch").agg(
        open=("open", "first"), high=("high", "max"), low=("low", "min"), close=("close", "last"), count=("close", "size")
    ).reset_index()
    fifteen = fifteen[fifteen["count"] == 3].sort_values("timestamp").reset_index(drop=True)
    pivots: list[Pivot] = []
    for _, group in fifteen.groupby("segment", sort=False):
        idx = group.index.to_numpy()
        h = group["high"].to_numpy(float)
        l = group["low"].to_numpy(float)
        t = group["timestamp"].astype("int64").to_numpy()
        for j in range(2, len(group) - 2):
            confirm = int(t[j + 2] + pd.Timedelta(minutes=15).value)
            if h[j] > max(h[j - 2], h[j - 1]) and h[j] >= max(h[j + 1], h[j + 2]):
                pivots.append(Pivot("upper", int(t[j]), confirm, float(h[j])))
            if l[j] < min(l[j - 2], l[j - 1]) and l[j] <= min(l[j + 1], l[j + 2]):
                pivots.append(Pivot("lower", int(t[j]), confirm, float(l[j])))
    return pivots


def partition_of(timestamp: pd.Timestamp) -> str | None:
    for name, (start, end) in PARTITIONS.items():
        if start <= timestamp < end:
            return name
    return None


def normalize_pool_price(uniswap: pd.DataFrame, bars: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, float]]:
    frame = uniswap.copy()
    joined = frame.merge(bars[["timestamp", "close"]], on="timestamp", how="inner")
    fit = joined[(joined["timestamp"] >= PARTITIONS["fit"][0]) & (joined["timestamp"] < PARTITIONS["fit"][1])]
    fit = fit[(fit["price_last"] > 0) & (fit["close"] > 0)]
    if len(fit) < 10_000:
        raise ScreenError("insufficient fit overlap for price orientation")
    direct_ret = np.log(fit["price_last"]).diff()
    inverse_ret = -direct_ret
    cex_ret = np.log(fit["close"]).diff()
    corr_direct = float(direct_ret.corr(cex_ret))
    corr_inverse = float(inverse_ret.corr(cex_ret))
    inverse = corr_inverse > corr_direct
    oriented_last = 1.0 / fit["price_last"] if inverse else fit["price_last"]
    log_scale = float(np.nanmedian(np.log(fit["close"].to_numpy(float)) - np.log(oriented_last.to_numpy(float))))
    scale = math.exp(log_scale)
    for column in ("price_first", "price_last"):
        raw = pd.to_numeric(frame[column], errors="coerce")
        frame[column + "_normalized"] = scale / raw if inverse else scale * raw
    return frame, {"inverse": bool(inverse), "scale": scale, "corr_direct": corr_direct, "corr_inverse": corr_inverse}


def find_pool_levels(entry_index: int, bars: pd.DataFrame, pivots: list[Pivot]) -> tuple[float, float] | None:
    entry_time_ns = int(bars.at[entry_index, "timestamp"].value)
    entry = float(bars.at[entry_index, "open"])
    start_ns = entry_time_ns - pd.Timedelta(days=14).value
    upper: list[float] = []
    lower: list[float] = []
    bar_times = bars["timestamp"].astype("int64").to_numpy()
    highs = bars["high"].to_numpy(float)
    lows = bars["low"].to_numpy(float)
    for pivot in pivots:
        if pivot.confirm_time_ns > entry_time_ns or pivot.pivot_time_ns < start_ns:
            continue
        confirm_idx = int(np.searchsorted(bar_times, pivot.confirm_time_ns, side="left"))
        if confirm_idx >= entry_index:
            continue
        if pivot.kind == "upper" and pivot.level > entry:
            if np.max(highs[confirm_idx:entry_index], initial=-np.inf) < pivot.level:
                upper.append(pivot.level)
        elif pivot.kind == "lower" and pivot.level < entry:
            if np.min(lows[confirm_idx:entry_index], initial=np.inf) > pivot.level:
                lower.append(pivot.level)
    if not upper or not lower:
        return None
    return min(upper), max(lower)


def first_passage(entry_index: int, upper: float, lower: float, bars: pd.DataFrame, partition_end: pd.Timestamp) -> tuple[int | None, bool]:
    for i in range(entry_index, len(bars)):
        if bars.at[i, "timestamp"] >= partition_end:
            break
        hit_upper = float(bars.at[i, "high"]) >= upper
        hit_lower = float(bars.at[i, "low"]) <= lower
        if hit_upper and hit_lower:
            return None, True
        if hit_upper:
            return 1, False
        if hit_lower:
            return 0, False
    return None, False


def build_events(uniswap: pd.DataFrame, bars: pd.DataFrame, pivots: list[Pivot]) -> tuple[pd.DataFrame, dict[str, Any]]:
    uni, orientation = normalize_pool_price(uniswap, bars)
    uni["pool_return"] = np.log(uni["price_last_normalized"] / uni["price_first_normalized"])
    fit_mask = (uni["timestamp"] >= PARTITIONS["fit"][0]) & (uni["timestamp"] < PARTITIONS["fit"][1]) & (uni["usdc_increment"] > 0)
    threshold = max(5_000_000.0, float(uni.loc[fit_mask, "usdc_increment"].quantile(0.995)))

    bar_times = bars["timestamp"].astype("int64").to_numpy()
    closes = bars["close"].to_numpy(float)
    event_rows: list[dict[str, Any]] = []
    raw_candidates = uni[(uni["usdc_increment"] >= threshold) & (uni["weth_increment"] > 0) & (uni["transaction_increment"] >= 2) & np.isfinite(uni["pool_return"]) & (uni["pool_return"] != 0)].copy()
    basis_fit: list[float] = []
    preliminary: list[dict[str, Any]] = []
    for row in raw_candidates.itertuples(index=False):
        decision = row.timestamp + pd.Timedelta(minutes=7)
        entry_index = int(np.searchsorted(bar_times, int(decision.value), side="left"))
        if entry_index >= len(bars):
            continue
        entry_time = bars.at[entry_index, "timestamp"]
        partition = partition_of(entry_time)
        if partition is None:
            continue
        if entry_index < 12 or bars.at[entry_index - 12, "segment"] != bars.at[entry_index, "segment"]:
            continue
        pools = find_pool_levels(entry_index, bars, pivots)
        if pools is None:
            continue
        upper, lower = pools
        entry = float(bars.at[entry_index, "open"])
        u = upper / entry - 1.0
        d = 1.0 - lower / entry
        if min(u, d) < 0.0012:
            continue
        prior = bars.iloc[entry_index - 12:entry_index]
        ret15 = float(bars.at[entry_index - 1, "close"] / bars.at[entry_index - 4, "close"] - 1.0)
        log_returns = np.diff(np.log(prior["close"].to_numpy(float)))
        vol60 = float(np.std(log_returns, ddof=1) * math.sqrt(12)) if len(log_returns) > 1 else 0.0
        path = prior["close"].to_numpy(float)
        efficiency = float(abs(path[-1] - path[0]) / max(np.sum(np.abs(np.diff(path))), 1e-12))
        dex_price = float(row.price_last_normalized)
        cex = float(bars.at[entry_index - 1, "close"])
        basis = math.log(dex_price / cex)
        features = {
            "log1p_usdc_increment": math.log1p(float(row.usdc_increment)),
            "log1p_weth_increment": math.log1p(float(row.weth_increment)),
            "signed_pool_return": float(row.pool_return),
            "absolute_pool_return": abs(float(row.pool_return)),
            "pool_impact_efficiency": abs(float(row.pool_return)) / max(float(row.usdc_increment) / 1_000_000.0, 1e-9),
            "transaction_increment": float(row.transaction_increment),
            "usdc_to_weth_value_ratio_log": math.log((float(row.usdc_increment) + 1.0) / (float(row.weth_increment) * max(dex_price, 1e-9) + 1.0)),
            "prior_completed_15m_eth_return": ret15,
            "prior_completed_60m_eth_realized_volatility": vol60,
            "prior_completed_60m_path_efficiency": efficiency,
            "pool_to_eth_basis_z": basis,
            "upper_external_liquidity_distance": u,
            "lower_external_liquidity_distance": d,
        }
        prelim = {
            "partition": partition,
            "bucket_start": row.timestamp,
            "decision_time": decision,
            "entry_time": entry_time,
            "entry_index": entry_index,
            "entry_price": entry,
            "upper_price": upper,
            "lower_price": lower,
            "upper_distance": u,
            "lower_distance": d,
            "features": features,
        }
        preliminary.append(prelim)
        if partition == "fit":
            basis_fit.append(basis)
    if len(basis_fit) < 20:
        raise ScreenError("insufficient fit events for basis normalization")
    basis_median = float(np.median(basis_fit))
    basis_scale = float(np.std(basis_fit, ddof=1))
    basis_scale = basis_scale if basis_scale > 1e-12 else 1.0
    for item in preliminary:
        item["features"]["pool_to_eth_basis_z"] = (item["features"]["pool_to_eth_basis_z"] - basis_median) / basis_scale
        partition_end = PARTITIONS[item["partition"]][1]
        label, ambiguous = first_passage(item["entry_index"], item["upper_price"], item["lower_price"], bars, partition_end)
        raw_id = f"{int(item['bucket_start'].value)}|{item['entry_index']}|{item['upper_price']:.12g}|{item['lower_price']:.12g}"
        event_id = hashlib.sha256(raw_id.encode()).hexdigest()[:24]
        event = Event(
            event_id=event_id,
            partition=item["partition"],
            bucket_start=item["bucket_start"].isoformat(),
            decision_time=item["decision_time"].isoformat(),
            entry_time=item["entry_time"].isoformat(),
            entry_index=int(item["entry_index"]),
            entry_price=float(item["entry_price"]),
            upper_price=float(item["upper_price"]),
            lower_price=float(item["lower_price"]),
            upper_distance=float(item["upper_distance"]),
            lower_distance=float(item["lower_distance"]),
            label=label,
            ambiguous=bool(ambiguous),
            features={name: float(item["features"][name]) for name in FEATURES},
        )
        row = asdict(event)
        row.update(event.features)
        row.pop("features")
        event_rows.append(row)
    events = pd.DataFrame(event_rows).sort_values("entry_time").reset_index(drop=True) if event_rows else pd.DataFrame()
    meta = {
        "event_threshold_usdc": threshold,
        "raw_candidate_count": int(len(raw_candidates)),
        "event_count": int(len(events)),
        "basis_median": basis_median,
        "basis_scale": basis_scale,
        "price_orientation": orientation,
    }
    return events, meta


def fit_model(events: pd.DataFrame) -> tuple[Any, dict[str, Any], np.ndarray, np.ndarray]:
    fit = events[(events["partition"] == "fit") & events["label"].notna() & ~events["ambiguous"]]
    cal = events[(events["partition"] == "calibration") & events["label"].notna() & ~events["ambiguous"]]
    if len(fit) < 100 or fit["label"].nunique() < 2:
        raise ScreenError(f"insufficient fit labels: {len(fit)}, classes={fit['label'].nunique()}")
    medians = fit[FEATURES].median().to_dict()
    x_fit = fit[FEATURES].fillna(medians).to_numpy(float)
    y_fit = fit["label"].to_numpy(int)
    model = HistGradientBoostingClassifier(
        learning_rate=0.05,
        max_iter=120,
        max_leaf_nodes=7,
        min_samples_leaf=20,
        l2_regularization=1.0,
        random_state=20260726,
    )
    model.fit(x_fit, y_fit)
    calibrator: IsotonicRegression | None = None
    if len(cal) >= 50 and cal["label"].nunique() == 2:
        raw = model.predict_proba(cal[FEATURES].fillna(medians).to_numpy(float))[:, 1]
        calibrator = IsotonicRegression(out_of_bounds="clip")
        calibrator.fit(raw, cal["label"].to_numpy(int))

    def predict(frame: pd.DataFrame) -> np.ndarray:
        raw = model.predict_proba(frame[FEATURES].fillna(medians).to_numpy(float))[:, 1]
        return calibrator.predict(raw) if calibrator is not None else raw

    probabilities = predict(events)
    baseline = events["lower_distance"].to_numpy(float) / (events["upper_distance"].to_numpy(float) + events["lower_distance"].to_numpy(float))
    contract = {
        "fit_rows": int(len(fit)),
        "fit_class_counts": fit["label"].value_counts().sort_index().to_dict(),
        "calibration_rows": int(len(cal)),
        "calibration_used": calibrator is not None,
        "training_medians": {key: float(value) for key, value in medians.items()},
        "features": FEATURES,
    }
    return predict, contract, probabilities, baseline


def event_actions(events: pd.DataFrame, probabilities: np.ndarray, excluded: set[str] | None = None) -> pd.DataFrame:
    frame = events.copy()
    frame["p_up"] = probabilities
    c = DECISION_COST_BPS / 10_000.0
    frame["ev_long"] = frame["p_up"] * frame["upper_distance"] - (1.0 - frame["p_up"]) * frame["lower_distance"] - c
    frame["ev_short"] = (1.0 - frame["p_up"]) * frame["lower_distance"] - frame["p_up"] * frame["upper_distance"] - c
    frame["side"] = np.where((frame["ev_long"] > frame["ev_short"]) & (frame["ev_long"] > 0), 1, np.where(frame["ev_short"] > 0, -1, 0))
    if excluded:
        frame.loc[frame["event_id"].isin(excluded), "side"] = 0
    return frame


def next_funding_boundaries(start: pd.Timestamp, end: pd.Timestamp) -> int:
    if end <= start:
        return 0
    first = start.floor("8h") + pd.Timedelta(hours=8)
    if first > end:
        return 0
    return int((end - first) // pd.Timedelta(hours=8)) + 1


def trade_outcome(row: pd.Series, bars: pd.DataFrame, partition_end: pd.Timestamp) -> tuple[int, float, str]:
    side = int(row["side"])
    stop = float(row["lower_price"] if side > 0 else row["upper_price"])
    target = float(row["upper_price"] if side > 0 else row["lower_price"])
    for i in range(int(row["entry_index"]), len(bars)):
        if bars.at[i, "timestamp"] >= partition_end:
            break
        o, h, l = (float(bars.at[i, column]) for column in ("open", "high", "low"))
        if side > 0:
            if o <= stop:
                return i, o, "gap_stop"
            if o >= target:
                return i, target, "target"
            if l <= stop:
                return i, stop, "stop"
            if h >= target:
                return i, target, "target"
        else:
            if o >= stop:
                return i, o, "gap_stop"
            if o <= target:
                return i, target, "target"
            if h >= stop:
                return i, stop, "stop"
            if l <= target:
                return i, target, "target"
    return min(len(bars) - 1, int(np.searchsorted(bars["timestamp"].astype("int64").to_numpy(), int(partition_end.value), side="left") - 1)), stop, "source_boundary_structural_loss"


def simulate(
    events: pd.DataFrame,
    probabilities: np.ndarray,
    bars: pd.DataFrame,
    partition: str,
    cost_bps: float,
    risk_fraction: float,
    cap_multiple: float,
    excluded: set[str] | None = None,
) -> dict[str, Any]:
    chosen = event_actions(events, probabilities, excluded)
    chosen = chosen[(chosen["partition"] == partition) & (chosen["side"] != 0)].sort_values("entry_time")
    start, end = PARTITIONS[partition]
    nav = 10_000.0
    initial = nav
    next_available = start
    trades = []
    daily: dict[str, float] = {}
    cost_fraction = cost_bps / 10_000.0
    for _, row in chosen.iterrows():
        entry_time = pd.Timestamp(row["entry_time"])
        if entry_time < next_available:
            continue
        entry = float(row["entry_price"])
        side = int(row["side"])
        stop_distance = float(row["lower_distance"] if side > 0 else row["upper_distance"])
        risk_per_notional = stop_distance + cost_fraction
        max_by_liquidation = 0.90 / max(stop_distance + MAINTENANCE_MARGIN_FRACTION, 1e-9)
        leverage = min(cap_multiple, max_by_liquidation, risk_fraction / max(risk_per_notional, 1e-9))
        if leverage <= 0:
            continue
        notional = nav * leverage
        quantity = notional / entry
        exit_index, exit_price, reason = trade_outcome(row, bars, end)
        exit_time = bars.at[exit_index, "timestamp"]
        entry_fee = 0.5 * cost_fraction * notional
        exit_notional = quantity * exit_price
        exit_fee = 0.5 * cost_fraction * exit_notional
        funding_count = next_funding_boundaries(entry_time, exit_time)
        funding = funding_count * (ADVERSE_FUNDING_BPS / 10_000.0) * notional
        gross = side * quantity * (exit_price - entry)
        pnl = gross - entry_fee - exit_fee - funding
        start_nav = nav
        nav = nav + pnl
        bankrupt = nav <= 0
        current_day = entry_time.normalize() + pd.Timedelta(days=1)
        while current_day <= min(exit_time, end):
            mark_index = int(np.searchsorted(bars["timestamp"].astype("int64").to_numpy(), int(current_day.value), side="left") - 1)
            if mark_index >= int(row["entry_index"]):
                mark = float(bars.at[mark_index, "close"])
                accrued = next_funding_boundaries(entry_time, current_day) * (ADVERSE_FUNDING_BPS / 10_000.0) * notional
                marked = start_nav - entry_fee - accrued + side * quantity * (mark - entry)
                daily[current_day.strftime("%Y-%m-%d")] = max(marked, 1e-12)
            current_day += pd.Timedelta(days=1)
        trades.append({
            "event_id": row["event_id"],
            "entry_time": entry_time.isoformat(),
            "exit_time": exit_time.isoformat(),
            "side": side,
            "entry_price": entry,
            "exit_price": exit_price,
            "reason": reason,
            "leverage": leverage,
            "funding_events": funding_count,
            "pnl": pnl,
            "return_on_start_nav": pnl / start_nav,
            "nav_after": nav,
        })
        next_available = exit_time + pd.Timedelta(nanoseconds=1)
        if bankrupt:
            break
    calendar_days = int((end - start) / pd.Timedelta(days=1))
    geometric = (nav / initial) ** (1.0 / calendar_days) - 1.0 if nav > 0 else -1.0
    pnl_values = np.array([trade["pnl"] for trade in trades], dtype=float)
    positive = float(pnl_values[pnl_values > 0].sum()) if len(pnl_values) else 0.0
    negative = float(-pnl_values[pnl_values < 0].sum()) if len(pnl_values) else 0.0
    pf = positive / negative if negative > 0 else (math.inf if positive > 0 else 0.0)
    returns = np.array([trade["return_on_start_nav"] for trade in trades], dtype=float)
    nav_series = [initial] + [trade["nav_after"] for trade in trades]
    peaks = np.maximum.accumulate(nav_series)
    mdd = float(np.max(1.0 - np.array(nav_series) / peaks)) if nav_series else 0.0
    half = start + (end - start) / 2
    first_nav = initial
    for trade in trades:
        if pd.Timestamp(trade["exit_time"]) < half:
            first_nav = trade["nav_after"]
    half_returns = {"H1": first_nav / initial - 1.0, "H2": nav / first_nav - 1.0 if first_nav > 0 else -1.0}
    return {
        "partition": partition,
        "cost_bps": cost_bps,
        "risk_fraction": risk_fraction,
        "cap_multiple": cap_multiple,
        "initial_nav": initial,
        "final_nav": nav,
        "total_return": nav / initial - 1.0,
        "geometric_daily_growth": geometric,
        "calendar_days": calendar_days,
        "trade_count": len(trades),
        "profit_factor": pf,
        "maximum_drawdown": mdd,
        "median_trade_return": float(np.median(returns)) if len(returns) else 0.0,
        "positive_trade_count": int(np.sum(returns > 0)) if len(returns) else 0,
        "negative_trade_count": int(np.sum(returns < 0)) if len(returns) else 0,
        "half_returns": half_returns,
        "bankrupt": nav <= 0,
        "daily_nav": daily,
        "trades": trades,
    }


def metrics_for_partition(events: pd.DataFrame, probabilities: np.ndarray, baseline: np.ndarray, partition: str) -> dict[str, Any]:
    mask = (events["partition"] == partition) & events["label"].notna() & ~events["ambiguous"]
    y = events.loc[mask, "label"].to_numpy(int)
    p = probabilities[mask.to_numpy()]
    b = baseline[mask.to_numpy()]
    result = {"resolved_rows": int(len(y)), "class_count": int(len(np.unique(y)))}
    if len(y) and len(np.unique(y)) == 2:
        result.update({
            "model_auc": float(roc_auc_score(y, p)),
            "baseline_auc": float(roc_auc_score(y, b)),
            "model_brier": float(brier_score_loss(y, p)),
            "baseline_brier": float(brier_score_loss(y, b)),
        })
        result["brier_skill"] = 1.0 - result["model_brier"] / result["baseline_brier"] if result["baseline_brier"] > 0 else None
    return result


def run_screen(output: Path, cache: Path) -> dict[str, Any]:
    output.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    session.headers["User-Agent"] = "SMC-ICT-2-uniswap-price-shock/1.0"
    uniswap, uni_manifest = build_uniswap_5m(cache, session)
    bars, bybit_manifest = load_bybit(cache, session)
    pivots = build_pivots(bars)
    events, event_meta = build_events(uniswap, bars, pivots)
    if events.empty:
        raise ScreenError("no causal events")
    _, model_contract, probabilities, baseline = fit_model(events)
    events["p_up"] = probabilities
    events["baseline_p_up"] = baseline
    events.to_parquet(output / "EVENTS.parquet", index=False)
    prediction_metrics = {name: metrics_for_partition(events, probabilities, baseline, name) for name in PARTITIONS}
    confirmation_ok = prediction_metrics["confirmation"].get("resolved_rows", 0) >= 50 and prediction_metrics["confirmation"].get("class_count", 0) == 2
    accounts: dict[str, Any] = {}
    if confirmation_ok:
        for cost in (12.0, 18.0, 24.0):
            accounts[str(cost)] = simulate(events, probabilities, bars, "development", cost, 0.005, 3.0)
    base24 = accounts.get("24.0")
    cost_possible = bool(base24 and base24["total_return"] > 0 and base24["trade_count"] >= 20 and not base24["bankrupt"])
    risk_search = []
    selected = None
    if cost_possible:
        for risk in (0.0025, 0.005, 0.01, 0.02, 0.04, 0.08, 0.15, 0.30, 0.60):
            for cap in (1, 2, 3, 5, 8, 12, 20, 35, 50, 75, 100):
                result = simulate(events, probabilities, bars, "development", 24.0, risk, float(cap))
                summary = {key: result[key] for key in ["risk_fraction", "cap_multiple", "total_return", "geometric_daily_growth", "trade_count", "profit_factor", "maximum_drawdown", "median_trade_return", "bankrupt"]}
                risk_search.append(summary)
                if not result["bankrupt"] and (selected is None or result["geometric_daily_growth"] > selected["geometric_daily_growth"]):
                    selected = result
    winner_removed = None
    if selected and selected["trades"]:
        winners = sorted((trade for trade in selected["trades"] if trade["pnl"] > 0), key=lambda trade: trade["pnl"], reverse=True)
        remove_n = max(1, math.ceil(0.10 * len(selected["trades"])))
        excluded = {trade["event_id"] for trade in winners[:remove_n]}
        winner_removed = simulate(events, probabilities, bars, "development", 24.0, selected["risk_fraction"], selected["cap_multiple"], excluded)
    status = "PRE2024_SURVIVOR_REQUIRES_CANONICAL_2024_SOURCE" if selected and selected["total_return"] > 0 else "TESTED_BELOW_GATE"
    result = {
        "schema_version": 1,
        "result_id": RESULT_ID,
        "claim_id": CLAIM_ID,
        "status": status,
        "hard_validity_status": "PASS_INITIAL_CAUSAL_BYBIT_PRE2024",
        "economic_status": "PRE2024_COST_POSITIVE" if status.startswith("PRE2024_SURVIVOR") else "BELOW_GATE",
        "ranking_role": "NONE_PRE2024_DISCOVERY",
        "source_semantics": "unsigned activity plus completed pool-price displacement; no signed inventory claim",
        "event_meta": event_meta,
        "partition_counts": events.groupby("partition").size().to_dict(),
        "resolved_counts": events[events["label"].notna() & ~events["ambiguous"]].groupby("partition").size().to_dict(),
        "model_contract": model_contract,
        "prediction_metrics": prediction_metrics,
        "confirmation_population_gate": confirmation_ok,
        "development_accounts": {key: {field: value for field, value in account.items() if field not in {"daily_nav", "trades"}} for key, account in accounts.items()},
        "risk_search_opened": cost_possible,
        "risk_search": risk_search,
        "selected_path": {field: value for field, value in selected.items() if field not in {"daily_nav", "trades"}} if selected else None,
        "winner_removed_selected_path": {field: value for field, value in winner_removed.items() if field not in {"daily_nav", "trades"}} if winner_removed else None,
        "next_action": "RECONSTRUCT_CANONICAL_2024_UNISWAP_PRICE_VOLUME_AND_OPEN_2024H1" if status.startswith("PRE2024_SURVIVOR") else "RETIRE_EXACT_PRICE_SHOCK_INFORMATION_UNIT",
        "uniswap_manifest": uni_manifest,
        "bybit_source_records": bybit_manifest,
        "pivots": len(pivots),
        "official_2024H1_opened": False,
        "2024H2_2026H1_opened": False,
        "credentials_used": False,
        "orders_submitted": False,
    }
    (output / "RESULT.json").write_text(json.dumps(result, indent=2, sort_keys=True, default=str) + "\n")
    if selected:
        pd.DataFrame(selected["trades"]).to_csv(output / "SELECTED_TRADES.csv", index=False)
        pd.DataFrame(risk_search).to_csv(output / "RISK_SEARCH.csv", index=False)
    if winner_removed:
        pd.DataFrame(winner_removed["trades"]).to_csv(output / "WINNER_REMOVED_TRADES.csv", index=False)
    manifest = output / "SHA256SUMS.txt"
    files = sorted(path for path in output.iterdir() if path.is_file() and path.name != manifest.name)
    manifest.write_text("".join(f"{sha256_file(path)}  {path.name}\n" for path in files))
    return result


def self_test() -> None:
    assert partition_of(pd.Timestamp("2022-01-01", tz="UTC")) == "fit"
    assert partition_of(pd.Timestamp("2023-10-01", tz="UTC")) == "development"
    assert next_funding_boundaries(pd.Timestamp("2023-01-01T01:00:00Z"), pd.Timestamp("2023-01-01T17:00:00Z")) == 2
    simple = pd.DataFrame({
        "timestamp": pd.date_range("2023-07-01", periods=3, freq="5min", tz="UTC"),
        "open": [100.0, 100.0, 100.0], "high": [101.0, 106.0, 101.0], "low": [99.0, 94.0, 99.0], "close": [100.0, 100.0, 100.0], "volume": [1, 1, 1], "segment": [0, 0, 0],
    })
    row = pd.Series({"side": 1, "lower_price": 95.0, "upper_price": 105.0, "entry_index": 0})
    idx, price, reason = trade_outcome(row, simple, pd.Timestamp("2023-07-02", tz="UTC"))
    assert idx == 1 and price == 95.0 and reason == "stop"
    rows = pd.DataFrame({
        "event_id": ["a"], "partition": ["development"], "p_up": [0.9], "upper_distance": [0.05], "lower_distance": [0.02], "side": [0]
    })
    acted = event_actions(rows.drop(columns=["p_up", "side"]), np.array([0.9]))
    assert int(acted.iloc[0]["side"]) == 1
    print("uniswap price-shock self-test passed")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["self-test", "run"])
    parser.add_argument("--output", type=Path, default=Path("research_runs/ml_uniswap_price_shock"))
    parser.add_argument("--cache", type=Path, default=Path("/tmp/ml_uniswap_price_shock_cache"))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.command == "self-test":
        self_test()
        return 0
    result = run_screen(args.output, args.cache)
    print(json.dumps({
        "status": result["status"],
        "events": result["event_meta"]["event_count"],
        "development_24bps": result["development_accounts"].get("24.0"),
        "selected_path": result["selected_path"],
        "next_action": result["next_action"],
    }, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
