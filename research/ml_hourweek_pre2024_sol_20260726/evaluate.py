from __future__ import annotations

import argparse
import hashlib
import json
import math
import shutil
import zipfile
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.linear_model import Ridge
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT"]
CONTINUOUS = [
    "ret1", "ret3", "ret6", "ret12", "ret24", "ret72",
    "rv24", "rv72", "eff24", "eff72", "qv_z168",
    "flow1", "flow6", "flow24", "range_pos24", "range_pos168",
    "xsec_ret6", "xsec_ret24",
]
CATEGORICAL = ["symbol", "symbol_hour", "symbol_how"]
FEATURES = CONTINUOUS + CATEGORICAL
ARTIFACT_SHA256 = "fd3c20704cf4b8b1dc80023298920456d4ec7cf2dfe9986237d94ea8cbd51f4c"
CLAIM_ID = "CLM-20260726-2237-ML-HOURWEEK-PRE2024-001"
RESULT_ID = "RES-20260726-ML-HOURWEEK-PRE2024-SOL-001"
TRAIN_START = pd.Timestamp("2023-01-08T00:00:00Z")
TRAIN_END = pd.Timestamp("2023-07-01T00:00:00Z")
Q3_START = pd.Timestamp("2023-07-01T00:00:00Z")
Q3_END = pd.Timestamp("2023-10-01T00:00:00Z")
Q4_START = pd.Timestamp("2023-10-01T00:00:00Z")
Q4_END = pd.Timestamp("2024-01-01T00:00:00Z")
OFFICIAL_START = pd.Timestamp("2024-01-01T00:00:00Z")
OFFICIAL_END = pd.Timestamp("2024-07-01T00:00:00Z")
FULL_REFIT_END = pd.Timestamp("2024-01-01T00:00:00Z")
SESSIONS = {
    "ALL": tuple(range(24)),
    "UTC00_07": tuple(range(0, 8)),
    "UTC08_15": tuple(range(8, 16)),
    "UTC16_23": tuple(range(16, 24)),
    "UTC00_05": tuple(range(0, 6)),
    "UTC06_11": tuple(range(6, 12)),
    "UTC12_17": tuple(range(12, 18)),
    "UTC18_23": tuple(range(18, 24)),
    "UTC00_11": tuple(range(0, 12)),
    "UTC12_23": tuple(range(12, 24)),
}
SIDE_FILTERS = ("BOTH", "LONG", "SHORT")
MULTIPLIERS = (0.75, 1.0, 1.25, 1.5, 2.0, 2.5)
SELECTED_ROUTE = {"session": "UTC00_11", "side_filter": "SHORT", "symbol": "SOLUSDT", "multiplier": 0.75}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_npz(root: Path, symbol: str) -> pd.DataFrame:
    path = root / "cross-asset-leadlag-baseline-20260725" / "data" / f"{symbol}-5m-2023-2025.npz"
    with np.load(path) as payload:
        ts = pd.to_datetime(payload["timestamp"], unit="ms", utc=True)
        frame = pd.DataFrame(
            {
                "open": payload["open"].astype(float),
                "high": payload["high"].astype(float),
                "low": payload["low"].astype(float),
                "close": payload["close"].astype(float),
                "quote_volume": payload["quote_volume"].astype(float),
                "taker_buy_quote": payload["taker_buy_quote"].astype(float),
            },
            index=ts,
        )
    expected = pd.date_range(frame.index.min(), frame.index.max(), freq="5min", tz="UTC")
    frame = frame.reindex(expected)
    valid = frame[["open", "high", "low", "close", "quote_volume", "taker_buy_quote"]].notna().all(axis=1)
    frame["source_valid"] = valid
    return frame


def contiguous_hourly(frame: pd.DataFrame) -> pd.DataFrame:
    group = frame.resample("1h", label="left", closed="left")
    hourly = pd.DataFrame(
        {
            "open": group["open"].first(),
            "high": group["high"].max(),
            "low": group["low"].min(),
            "close": group["close"].last(),
            "quote_volume": group["quote_volume"].sum(min_count=12),
            "taker_buy_quote": group["taker_buy_quote"].sum(min_count=12),
            "count": group["source_valid"].sum(),
        }
    )
    hourly["source_valid"] = hourly["count"].eq(12) & hourly[["open", "high", "low", "close"]].notna().all(axis=1)
    invalid = ~hourly["source_valid"]
    segment = invalid.cumsum()
    hourly["segment"] = segment
    return hourly


def rolling_by_segment(series: pd.Series, segment: pd.Series, window: int, function: str) -> pd.Series:
    grouped = series.groupby(segment)
    roller = grouped.rolling(window=window, min_periods=window)
    if function == "sum":
        out = roller.sum()
    elif function == "mean":
        out = roller.mean()
    elif function == "std":
        out = roller.std(ddof=0)
    elif function == "max":
        out = roller.max()
    elif function == "min":
        out = roller.min()
    else:
        raise ValueError(function)
    return out.reset_index(level=0, drop=True)


def shift_by_segment(series: pd.Series, segment: pd.Series, periods: int) -> pd.Series:
    return series.groupby(segment).shift(periods)


def build_symbol_rows(hourly: pd.DataFrame, symbol: str) -> pd.DataFrame:
    h = hourly.copy()
    seg = h["segment"]
    log_close = np.log(h["close"])
    for n in (1, 3, 6, 12, 24, 72):
        h[f"ret{n}"] = log_close - shift_by_segment(log_close, seg, n)
    one = h["ret1"]
    h["rv24"] = rolling_by_segment(one, seg, 24, "std") * math.sqrt(24)
    h["rv72"] = rolling_by_segment(one, seg, 72, "std") * math.sqrt(72)
    abs_one = one.abs()
    for n in (24, 72):
        denom = rolling_by_segment(abs_one, seg, n, "sum")
        h[f"eff{n}"] = h[f"ret{n}"].abs() / denom.replace(0.0, np.nan)
    log_qv = np.log1p(h["quote_volume"])
    qv_mean = rolling_by_segment(log_qv, seg, 168, "mean")
    qv_std = rolling_by_segment(log_qv, seg, 168, "std")
    h["qv_z168"] = (log_qv - qv_mean) / qv_std.replace(0.0, np.nan)
    flow_num = 2.0 * h["taker_buy_quote"] - h["quote_volume"]
    flow = flow_num / h["quote_volume"].replace(0.0, np.nan)
    h["flow1"] = flow
    for n in (6, 24):
        num = rolling_by_segment(flow_num, seg, n, "sum")
        den = rolling_by_segment(h["quote_volume"], seg, n, "sum")
        h[f"flow{n}"] = num / den.replace(0.0, np.nan)
    for n in (24, 168):
        low = rolling_by_segment(h["low"], seg, n, "min")
        high = rolling_by_segment(h["high"], seg, n, "max")
        h[f"range_pos{n}"] = (h["close"] - low) / (high - low).replace(0.0, np.nan)
    h["entry_time"] = h.index + pd.Timedelta(hours=1)
    h["exit_time"] = h.index + pd.Timedelta(hours=25)
    h["entry_open"] = shift_by_segment(h["open"], seg, -1)
    h["exit_close"] = shift_by_segment(h["close"], seg, -24)
    h["target_return"] = h["exit_close"] / h["entry_open"] - 1.0
    h["symbol"] = symbol
    h["hour"] = h["entry_time"].dt.hour
    h["hour_of_week"] = h["entry_time"].dt.dayofweek * 24 + h["hour"]
    h["symbol_hour"] = h["symbol"] + "_h" + h["hour"].astype(str)
    h["symbol_how"] = h["symbol"] + "_w" + h["hour_of_week"].astype(str)
    h["start_key_long"] = h["entry_time"].astype(str) + "|" + symbol + "|+1"
    h["start_key_short"] = h["entry_time"].astype(str) + "|" + symbol + "|-1"
    h = h[h["source_valid"]].copy()
    return h


def build_panel(markets: dict[str, pd.DataFrame]) -> pd.DataFrame:
    rows = []
    ret6 = {}
    ret24 = {}
    for symbol, frame in markets.items():
        built = build_symbol_rows(frame, symbol)
        rows.append(built)
        ret6[symbol] = built.set_index("entry_time")["ret6"]
        ret24[symbol] = built.set_index("entry_time")["ret24"]
    panel = pd.concat(rows, ignore_index=False).reset_index(names="decision_time")
    x6 = pd.concat(ret6, axis=1).mean(axis=1, skipna=False)
    x24 = pd.concat(ret24, axis=1).mean(axis=1, skipna=False)
    panel["xsec_ret6"] = panel["entry_time"].map(x6)
    panel["xsec_ret24"] = panel["entry_time"].map(x24)
    panel = panel.dropna(subset=FEATURES + ["target_return", "entry_open", "exit_close"])
    panel = panel.sort_values(["entry_time", "symbol"], kind="stable").reset_index(drop=True)
    return panel


def make_model() -> Pipeline:
    transformer = ColumnTransformer(
        [
            ("continuous", StandardScaler(), CONTINUOUS),
            ("categorical", OneHotEncoder(handle_unknown="ignore"), CATEGORICAL),
        ],
        sparse_threshold=0.3,
    )
    return Pipeline([("features", transformer), ("model", Ridge(alpha=10.0))])


def fit_predict(train: pd.DataFrame, test: pd.DataFrame) -> np.ndarray:
    model = make_model()
    model.fit(train[FEATURES], train["target_return"])
    return model.predict(test[FEATURES])


@dataclass(frozen=True)
class Route:
    session: str
    side_filter: str
    symbol: str
    multiplier: float


def max_drawdown(nav: np.ndarray) -> float:
    if len(nav) == 0:
        return 0.0
    peak = np.maximum.accumulate(nav)
    return float(np.max(1.0 - nav / peak))


def profit_factor(trades: list[dict]) -> float | str:
    gross_profit = sum(max(0.0, item["net_return"]) for item in trades)
    gross_loss = sum(max(0.0, -item["net_return"]) for item in trades)
    if gross_loss == 0.0:
        return "infinity_no_completed_loser" if gross_profit > 0 else 0.0
    return float(gross_profit / gross_loss)


def active_signal(row: pd.Series, route: Route, threshold: float) -> int:
    if row["symbol"] != route.symbol or int(row["hour"]) not in SESSIONS[route.session]:
        return 0
    pred = float(row["prediction"])
    if route.side_filter in {"BOTH", "LONG"} and pred >= threshold:
        return 1
    if route.side_filter in {"BOTH", "SHORT"} and pred <= -threshold:
        return -1
    return 0


def replay(rows: pd.DataFrame, route: Route, threshold: float, cost_bps: float, blocked: set[str] | None = None) -> dict:
    blocked = blocked or set()
    nav = 1.0
    position: dict | None = None
    trades: list[dict] = []
    nav_path = []
    grouped = list(rows.groupby("entry_time", sort=True))
    last_time = None
    for timestamp, group in grouped:
        timestamp = pd.Timestamp(timestamp)
        if last_time is not None and timestamp != last_time + pd.Timedelta(hours=1):
            if position is not None:
                marked = float(position["last_price"])
                gross = position["side"] * (marked / position["entry_price"] - 1.0)
                cost = position["quantity"] * (cost_bps / 20000.0)
                pnl = position["quantity"] * gross - cost
                nav += pnl
                trades.append({**position, "exit_time": last_time, "exit_price": marked, "net_return": pnl / position["nav_at_entry"], "reason": "SOURCE_GAP_ADVERSE_CLOSE"})
                position = None
        by_symbol = {str(row.symbol): row for row in group.itertuples(index=False)}
        if position is not None:
            record = by_symbol.get(position["symbol"])
            if record is None:
                marked = float(position["last_price"])
            else:
                marked = float(record.entry_open)
                position["last_price"] = marked
            if timestamp.hour in {0, 8, 16}:
                nav -= position["quantity"] * marked * 0.0001
            signed_edge = position["side"] * float(getattr(record, "prediction", 0.0)) if record is not None else -1.0
            if signed_edge <= 0.0:
                exit_cost = position["quantity"] * marked * (cost_bps / 20000.0)
                pnl = position["quantity"] * position["side"] * (marked - position["entry_price"]) - exit_cost
                nav += pnl
                trades.append({**position, "exit_time": timestamp, "exit_price": marked, "net_return": pnl / position["nav_at_entry"], "reason": "EDGE_NONPOSITIVE"})
                position = None
        candidates = []
        if position is None:
            for row in group.itertuples(index=False):
                side = active_signal(pd.Series(row._asdict()), route, threshold)
                if side == 0:
                    continue
                key = row.start_key_long if side > 0 else row.start_key_short
                if key in blocked:
                    continue
                candidates.append((abs(float(row.prediction)), str(row.symbol), side, row, key))
            if candidates:
                _, symbol, side, row, key = max(candidates, key=lambda item: (item[0], -SYMBOLS.index(item[1])))
                price = float(row.entry_open)
                nav_at_entry = nav
                quantity = nav / price
                entry_cost = quantity * price * (cost_bps / 20000.0)
                nav -= entry_cost
                position = {
                    "start_key": key,
                    "symbol": symbol,
                    "side": side,
                    "entry_time": timestamp,
                    "entry_price": price,
                    "last_price": price,
                    "quantity": quantity,
                    "nav_at_entry": nav_at_entry,
                    "prediction": float(row.prediction),
                }
        marked_nav = nav
        if position is not None:
            marked_nav += position["quantity"] * position["side"] * (position["last_price"] - position["entry_price"])
        nav_path.append((timestamp, marked_nav))
        last_time = timestamp
    if position is not None:
        marked = float(position["last_price"])
        reserve = position["quantity"] * marked * (cost_bps / 20000.0)
        nav += position["quantity"] * position["side"] * (marked - position["entry_price"]) - reserve
    nav_values = np.asarray([item[1] for item in nav_path], dtype=float)
    days = max(1, (rows["entry_time"].max().normalize() - rows["entry_time"].min().normalize()).days + 1)
    returns = [item["net_return"] for item in trades]
    return {
        "route": asdict(route),
        "completed_trade_count": len(trades),
        "final_nav": float(nav),
        "total_return": float(nav - 1.0),
        "geometric_daily_growth": float(nav ** (1.0 / days) - 1.0) if nav > 0 else -1.0,
        "maximum_drawdown": max_drawdown(nav_values),
        "median_trade_return": float(np.median(returns)) if returns else None,
        "profit_factor": profit_factor(trades),
        "open_position_at_end": position is not None,
        "trades": trades,
    }


def remove_winners(rows: pd.DataFrame, route: Route, threshold: float, cost_bps: float, base: dict) -> dict:
    positives = [item for item in base["trades"] if item["net_return"] > 0]
    if not positives:
        return replay(rows, route, threshold, cost_bps)
    count = max(1, math.ceil(len(base["trades"]) * 0.10))
    blocked = {item["start_key"] for item in sorted(positives, key=lambda item: item["net_return"], reverse=True)[:count]}
    return replay(rows, route, threshold, cost_bps, blocked)


def economic_gate(result: dict, winner_removed: dict, minimum_trades: int) -> bool:
    pf = result["profit_factor"]
    pf_value = math.inf if isinstance(pf, str) else float(pf)
    return (
        result["completed_trade_count"] >= minimum_trades
        and result["total_return"] > 0
        and (result["median_trade_return"] or -1.0) > 0
        and pf_value > 1.0
        and result["maximum_drawdown"] < 0.35
        and winner_removed["total_return"] > 0
    )


def period_rows(frame: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    return frame[(frame["entry_time"] >= start) & (frame["entry_time"] < end) & (frame["exit_time"] <= end)].copy()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact", type=Path, required=True)
    parser.add_argument("--work", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if sha256_file(args.artifact) != ARTIFACT_SHA256:
        raise RuntimeError("artifact SHA-256 mismatch")
    shutil.rmtree(args.work, ignore_errors=True)
    args.work.mkdir(parents=True)
    with zipfile.ZipFile(args.artifact) as archive:
        archive.extractall(args.work)
    markets = {symbol: contiguous_hourly(load_npz(args.work, symbol)) for symbol in SYMBOLS}
    panel = build_panel(markets)
    train = period_rows(panel, TRAIN_START, TRAIN_END)
    q3 = period_rows(panel, Q3_START, Q3_END)
    q4 = period_rows(panel, Q4_START, Q4_END)
    q3["prediction"] = fit_predict(train, q3)
    base_threshold = float(np.quantile(np.abs(q3["prediction"]), 0.95))
    routes = [Route(session, side, symbol, multiplier) for session in SESSIONS for side in SIDE_FILTERS for symbol in SYMBOLS for multiplier in MULTIPLIERS]
    survivors = []
    for route in routes:
        threshold = base_threshold * route.multiplier
        ordinary = replay(q3, route, threshold, 24.0)
        removed = remove_winners(q3, route, threshold, 24.0, ordinary)
        if economic_gate(ordinary, removed, 5):
            survivors.append((route, ordinary, removed))
    q4["prediction"] = fit_predict(train, q4)
    confirmed = []
    for route, q3_result, q3_removed in survivors:
        threshold = base_threshold * route.multiplier
        ordinary = replay(q4, route, threshold, 24.0)
        removed = remove_winners(q4, route, threshold, 24.0, ordinary)
        if economic_gate(ordinary, removed, 3):
            confirmed.append({"route": asdict(route), "q3": q3_result, "q3_winner_removed": q3_removed, "q4": ordinary, "q4_winner_removed": removed})
    if len(confirmed) != 1 or confirmed[0]["route"] != SELECTED_ROUTE:
        raise RuntimeError("pre-2024 selected route parity failure")
    full_train = period_rows(panel, TRAIN_START, FULL_REFIT_END)
    official = period_rows(panel, OFFICIAL_START, OFFICIAL_END)
    official["prediction"] = fit_predict(full_train, official)
    route = Route(**SELECTED_ROUTE)
    threshold = base_threshold * route.multiplier
    paths = {}
    for cost in (12.0, 18.0, 24.0):
        ordinary = replay(official, route, threshold, cost)
        removed = remove_winners(official, route, threshold, cost, ordinary)
        paths[f"{int(cost)}bps"] = {"ordinary": ordinary, "winner_removed": removed}
    eligible = official[(official["symbol"] == route.symbol) & official["hour"].isin(SESSIONS[route.session]) & (official["prediction"] <= -threshold)]
    session_predictions = official[(official["symbol"] == route.symbol) & official["hour"].isin(SESSIONS[route.session])]["prediction"]
    result = {
        "schema_version": 1,
        "result_id": RESULT_ID,
        "claim_id": CLAIM_ID,
        "status": "OFFICIAL_2024H1_ZERO_ACTION",
        "hard_validity_status": "PASS_CAUSAL_PRE2024_SELECTION_BINANCE_PROXY",
        "economic_status": "BELOW_GATE_ZERO_ACTION",
        "ranking_role": "NONE",
        "artifact_sha256": ARTIFACT_SHA256,
        "q3_survivor_count": len(survivors),
        "q4_confirmed_count": len(confirmed),
        "selected_route": SELECTED_ROUTE,
        "base_threshold": base_threshold,
        "absolute_entry_threshold": threshold,
        "official_2024h1": {
            "eligible_entry_count": int(len(eligible)),
            "minimum_session_prediction": float(session_predictions.min()),
            "entry_threshold": -threshold,
            "paths": paths,
        },
        "opened_periods": ["2024H1"],
        "unopened_periods": ["2024H2", "2025H1", "2025H2", "2026H1"],
        "orders_submitted": False,
        "decision": "Retire this exact pre-2024-selected route. The unchanged 2023 refit generated no eligible 2024H1 entry and cannot approach the objective. Do not tune adjacent sessions, symbols, sides, threshold, features or Ridge alpha.",
    }
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "RESULT.json").write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    (args.output / "Q3_Q4_SELECTION.json").write_text(
        json.dumps(
            {
                "q3_survivor_count": len(survivors),
                "confirmed": [
                    {
                        key: value
                        for key, value in record.items()
                        if key not in {"trades"}
                    }
                    for record in confirmed
                ],
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "result_id": result["result_id"],
        "status": result["status"],
        "eligible_entry_count": result["official_2024h1"]["eligible_entry_count"],
        "primary_24bps_return": result["official_2024h1"]["paths"]["24bps"]["ordinary"]["total_return"],
    }, sort_keys=True))


if __name__ == "__main__":
    main()
