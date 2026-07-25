from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
import pandas as pd
from numba import njit


@dataclass(frozen=True)
class CostContract:
    maker_entry_bps: float = 2.0
    taker_entry_bps: float = 6.0
    taker_exit_bps: float = 6.0
    stress_multiplier: float = 1.5


@dataclass(frozen=True)
class MakerRoute:
    queue_fraction: float
    ttl_seconds: int
    order_fraction_of_top: float = 0.05

    @property
    def route_id(self) -> str:
        return f"M_Q{self.queue_fraction:g}_T{self.ttl_seconds}_O{self.order_fraction_of_top:g}"


ROUTES = (
    MakerRoute(0.25, 1),
    MakerRoute(0.50, 1),
    MakerRoute(0.50, 3),
    MakerRoute(1.00, 3),
)
HORIZONS = (1, 5, 15, 60)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def load_book(path: Path) -> dict[str, np.ndarray]:
    cols = ["best_bid_price", "best_bid_qty", "best_ask_price", "best_ask_qty", "event_time"]
    chunks: dict[str, list[np.ndarray]] = {k: [] for k in cols}
    dtypes = {
        "best_bid_price": "float64",
        "best_bid_qty": "float64",
        "best_ask_price": "float64",
        "best_ask_qty": "float64",
        "event_time": "int64",
    }
    for c in pd.read_csv(path, usecols=cols, dtype=dtypes, chunksize=750_000):
        for k in cols:
            chunks[k].append(c[k].to_numpy(copy=True))
    out = {k: np.concatenate(v) for k, v in chunks.items()}
    order = np.argsort(out["event_time"], kind="stable")
    return {k: v[order] for k, v in out.items()}


def load_trades(path: Path) -> dict[str, np.ndarray]:
    cols = ["price", "quantity", "transact_time", "is_buyer_maker"]
    chunks: dict[str, list[np.ndarray]] = {k: [] for k in cols}
    dtypes = {
        "price": "float64",
        "quantity": "float64",
        "transact_time": "int64",
        "is_buyer_maker": "bool",
    }
    for c in pd.read_csv(path, usecols=cols, dtype=dtypes, chunksize=750_000):
        for k in cols:
            chunks[k].append(c[k].to_numpy(copy=True))
    out = {k: np.concatenate(v) for k, v in chunks.items()}
    order = np.argsort(out["transact_time"], kind="stable")
    return {k: v[order] for k, v in out.items()}


def build_second_panel(book: dict[str, np.ndarray], trades: dict[str, np.ndarray]) -> pd.DataFrame:
    bt = book["event_time"]
    sec = bt // 1000
    last = np.r_[np.flatnonzero(np.diff(sec) != 0), len(sec) - 1]
    first = np.r_[0, last[:-1] + 1]
    unique_sec = sec[last]
    counts = last - first + 1
    bidq = book["best_bid_qty"]
    askq = book["best_ask_qty"]
    churn = np.abs(np.diff(bidq, prepend=bidq[0])) + np.abs(np.diff(askq, prepend=askq[0]))
    churn_sum = np.add.reduceat(churn, first)

    start = int(unique_sec[0])
    end = int(unique_sec[-1])
    full_sec = np.arange(start, end + 1, dtype=np.int64)
    loc = unique_sec - start
    n = len(full_sec)
    frame = pd.DataFrame(index=pd.Index(full_sec, name="sec"))
    for key in ("best_bid_price", "best_bid_qty", "best_ask_price", "best_ask_qty"):
        arr = np.full(n, np.nan)
        arr[loc] = book[key][last]
        frame[key] = pd.Series(arr, index=frame.index).ffill().to_numpy()
    update_count = np.zeros(n)
    update_count[loc] = counts
    qchurn = np.zeros(n)
    qchurn[loc] = churn_sum
    frame["book_updates"] = update_count
    frame["quote_churn"] = qchurn

    tt = trades["transact_time"]
    ts = tt // 1000
    price = trades["price"]
    qty = trades["quantity"]
    quote = price * qty
    signed = np.where(trades["is_buyer_maker"], -quote, quote)
    in_range = (ts >= start) & (ts <= end)
    rel = (ts[in_range] - start).astype(np.int64)
    frame["trade_quote"] = np.bincount(rel, weights=quote[in_range], minlength=n)
    frame["signed_trade_quote"] = np.bincount(rel, weights=signed[in_range], minlength=n)
    frame["trade_count"] = np.bincount(rel, minlength=n)

    bid = frame["best_bid_price"].to_numpy()
    ask = frame["best_ask_price"].to_numpy()
    bq = frame["best_bid_qty"].to_numpy()
    aq = frame["best_ask_qty"].to_numpy()
    mid = (bid + ask) / 2.0
    micro = (ask * bq + bid * aq) / np.where(bq + aq > 0, bq + aq, np.nan)
    frame["mid"] = mid
    frame["spread_bps"] = (ask / bid - 1.0) * 10_000.0
    frame["imbalance"] = (bq - aq) / np.where(bq + aq > 0, bq + aq, np.nan)
    frame["micro_bps"] = (micro / mid - 1.0) * 10_000.0
    frame["flow_1s"] = frame["signed_trade_quote"] / frame["trade_quote"].replace(0, np.nan)
    for w in (5, 15, 60):
        q = frame["signed_trade_quote"].rolling(w, min_periods=max(2, w // 3)).sum()
        z = frame["trade_quote"].rolling(w, min_periods=max(2, w // 3)).sum()
        frame[f"flow_{w}s"] = q / z.replace(0, np.nan)
        frame[f"ret_{w}s_bps"] = (frame["mid"] / frame["mid"].shift(w) - 1.0) * 10_000.0
    for key in ("book_updates", "quote_churn", "trade_quote"):
        med = frame[key].rolling(300, min_periods=120).median().shift(1)
        frame[f"{key}_ratio"] = frame[key] / med.replace(0, np.nan)
    return frame


@njit(cache=True)
def _simulate_routes(
    decision_idx: np.ndarray,
    panel_sec: np.ndarray,
    bid: np.ndarray,
    ask: np.ndarray,
    bid_qty: np.ndarray,
    ask_qty: np.ndarray,
    mid: np.ndarray,
    trade_time: np.ndarray,
    trade_price: np.ndarray,
    trade_qty: np.ndarray,
    buyer_maker: np.ndarray,
    book_time: np.ndarray,
    book_bid: np.ndarray,
    book_ask: np.ndarray,
    queue_fraction: float,
    ttl_seconds: int,
    order_fraction: float,
    maker_fee: float,
    taker_fee: float,
) -> np.ndarray:
    out = np.full((len(decision_idx) * 2, 19), np.nan)
    row = 0
    for q in range(len(decision_idx)):
        di = int(decision_idx[q])
        decision_ms = (panel_sec[di] + 1) * 1000 - 1
        active_ms = decision_ms + 1
        expiry_ms = active_ms + ttl_seconds * 1000
        for side in (-1, 1):
            limit = bid[di] if side > 0 else ask[di]
            top_qty = bid_qty[di] if side > 0 else ask_qty[di]
            need = (queue_fraction + order_fraction) * top_qty
            start = np.searchsorted(trade_time, active_ms)
            stop = np.searchsorted(trade_time, expiry_ms)
            cum = 0.0
            fill_ms = -1
            for j in range(start, stop):
                eligible = buyer_maker[j] and trade_price[j] <= limit if side > 0 else (not buyer_maker[j]) and trade_price[j] >= limit
                if eligible:
                    cum += trade_qty[j]
                    if cum >= need:
                        fill_ms = int(trade_time[j])
                        break
            filled = fill_ms >= 0
            ti = np.searchsorted(book_time, active_ms + 250)
            taker_entry = np.nan
            if ti < len(book_time):
                taker_entry = book_ask[ti] if side > 0 else book_bid[ti]
            out[row, 0] = di
            out[row, 1] = side
            out[row, 2] = 1.0 if filled else 0.0
            out[row, 3] = fill_ms
            out[row, 4] = limit
            out[row, 5] = top_qty
            out[row, 6] = cum
            out[row, 7] = taker_entry
            if np.isfinite(taker_entry):
                out[row, 8] = side * (taker_entry / mid[di] - 1.0) * 10_000.0 + taker_fee
            if filled:
                entry_price = limit
                entry_time = fill_ms
                entry_fee = maker_fee
            else:
                bi = np.searchsorted(book_time, expiry_ms)
                if bi < len(book_time):
                    entry_price = book_ask[bi] if side > 0 else book_bid[bi]
                    entry_time = int(book_time[bi])
                    entry_fee = taker_fee
                else:
                    entry_price = np.nan
                    entry_time = -1
                    entry_fee = taker_fee
            out[row, 9] = entry_price
            out[row, 10] = entry_time
            for hi, horizon in enumerate((1, 5, 15, 60)):
                base_col = 11 + hi * 2
                if entry_time >= 0 and np.isfinite(entry_price):
                    future_sec = entry_time // 1000 + horizon
                    pi = np.searchsorted(panel_sec, future_sec)
                    if pi < len(panel_sec) and panel_sec[pi] == future_sec:
                        exit_touch = bid[pi] if side > 0 else ask[pi]
                        out[row, base_col] = side * (exit_touch / entry_price - 1.0) * 10_000.0 - entry_fee - taker_fee
                        out[row, base_col + 1] = side * (mid[pi] / entry_price - 1.0) * 10_000.0
            row += 1
    return out[:row]


def route_frame(symbol: str, panel: pd.DataFrame, book: dict[str, np.ndarray], trades: dict[str, np.ndarray], route: MakerRoute, costs: CostContract) -> pd.DataFrame:
    valid = np.arange(120, len(panel) - 121, 10, dtype=np.int64)
    state_ok = np.isfinite(panel[["flow_5s", "flow_15s", "imbalance", "micro_bps"]].to_numpy()).all(axis=1)
    valid = valid[state_ok[valid]]
    arr = _simulate_routes(
        valid,
        panel.index.to_numpy(np.int64),
        panel["best_bid_price"].to_numpy(float),
        panel["best_ask_price"].to_numpy(float),
        panel["best_bid_qty"].to_numpy(float),
        panel["best_ask_qty"].to_numpy(float),
        panel["mid"].to_numpy(float),
        trades["transact_time"].astype(np.int64),
        trades["price"].astype(float),
        trades["quantity"].astype(float),
        trades["is_buyer_maker"].astype(np.bool_),
        book["event_time"].astype(np.int64),
        book["best_bid_price"].astype(float),
        book["best_ask_price"].astype(float),
        route.queue_fraction,
        route.ttl_seconds,
        route.order_fraction_of_top,
        costs.maker_entry_bps,
        costs.taker_entry_bps,
    )
    names = ["decision_idx", "side", "filled", "fill_ms", "limit", "top_qty", "eligible_qty", "taker_entry", "taker_acquisition_cost_bps", "route_entry", "route_entry_ms"]
    for h in HORIZONS:
        names += [f"route_net_{h}s_bps", f"route_mid_markout_{h}s_bps"]
    df = pd.DataFrame(arr, columns=names)
    df["decision_idx"] = df["decision_idx"].astype(int)
    df["side"] = df["side"].astype(int)
    df["symbol"] = symbol
    df["route_id"] = route.route_id
    df["decision_sec"] = panel.index.to_numpy(np.int64)[df["decision_idx"]]
    for key in ["spread_bps", "imbalance", "micro_bps", "flow_1s", "flow_5s", "flow_15s", "flow_60s", "book_updates_ratio", "quote_churn_ratio", "trade_quote_ratio", "ret_5s_bps", "ret_15s_bps", "ret_60s_bps"]:
        df[key] = panel[key].to_numpy()[df["decision_idx"]]
    for key in ["imbalance", "micro_bps", "flow_1s", "flow_5s", "flow_15s", "flow_60s", "ret_5s_bps", "ret_15s_bps", "ret_60s_bps"]:
        df[f"side_{key}"] = df["side"] * df[key]
    return df


def trimmed_mean(x: pd.Series, n: int) -> float:
    z = np.sort(x.dropna().to_numpy(float))
    return float(z[:-n].mean()) if len(z) > n else float("nan")


def split_labels(sec: pd.Series) -> pd.Series:
    lo = int(sec.min())
    hi = int(sec.max()) + 1
    a = lo + (hi - lo) // 2
    b = lo + 3 * (hi - lo) // 4
    return pd.Series(np.where(sec < a, "dev", np.where(sec < b, "val", "conf")), index=sec.index)


def score_routes(all_routes: pd.DataFrame, costs: CostContract) -> tuple[pd.DataFrame, dict, pd.DataFrame, pd.DataFrame]:
    all_routes = all_routes.copy()
    all_routes["split"] = all_routes.groupby("symbol", group_keys=False)["decision_sec"].apply(split_labels)
    summaries = []
    for (symbol, route_id, split), g in all_routes.groupby(["symbol", "route_id", "split"]):
        rec = {"symbol": symbol, "route_id": route_id, "split": split, "n": len(g), "fill_rate": float(g["filled"].mean())}
        for h in HORIZONS:
            s = g[f"route_net_{h}s_bps"]
            m = g.loc[g.filled == 1, f"route_mid_markout_{h}s_bps"]
            rec[f"net_{h}s_mean_bps"] = float(s.mean())
            rec[f"net_{h}s_median_bps"] = float(s.median())
            rec[f"net_{h}s_trim10_bps"] = trimmed_mean(s, 10)
            rec[f"filled_markout_{h}s_mean_bps"] = float(m.mean())
            rec[f"filled_markout_{h}s_q10_bps"] = float(m.quantile(.10)) if len(m) else float("nan")
        summaries.append(rec)
    summary_df = pd.DataFrame(summaries)
    gates = []
    for route_id, route_rows in all_routes.groupby("route_id"):
        for flow_min in (-0.25, 0.0, 0.25):
            for micro_min in (0.0, 0.02):
                for update_cap in (1.0, 2.0, 4.0):
                    mask = (
                        (route_rows["side_flow_5s"] >= flow_min)
                        & (route_rows["side_micro_bps"] >= micro_min)
                        & (route_rows["book_updates_ratio"] <= update_cap)
                    )
                    for split in ("dev", "val", "conf"):
                        g = route_rows[route_rows.split == split]
                        use_maker = mask.loc[g.index]
                        taker_net = -g["taker_acquisition_cost_bps"] - costs.taker_exit_bps
                        routed = np.where(use_maker, g["route_net_5s_bps"], taker_net)
                        gates.append({
                            "route_id": route_id,
                            "flow_min": flow_min,
                            "micro_min": micro_min,
                            "update_cap": update_cap,
                            "split": split,
                            "n": len(g),
                            "maker_share": float(use_maker.mean()),
                            "routed_mean_bps": float(np.nanmean(routed)),
                            "routed_median_bps": float(np.nanmedian(routed)),
                            "always_taker_mean_bps": float(np.nanmean(taker_net)),
                            "improvement_bps": float(np.nanmean(routed) - np.nanmean(taker_net)),
                        })
    gate_df = pd.DataFrame(gates)
    eligible = gate_df[(gate_df.split == "dev") & (gate_df.maker_share >= .05) & (gate_df.maker_share <= .80)]
    selected = None if eligible.empty else eligible.sort_values(["improvement_bps", "routed_mean_bps"], ascending=False).iloc[0].to_dict()
    result = {"selected_gate": selected, "cost_contract": asdict(costs)}
    if selected:
        q = gate_df[
            (gate_df.route_id == selected["route_id"])
            & (gate_df.flow_min == selected["flow_min"])
            & (gate_df.micro_min == selected["micro_min"])
            & (gate_df.update_cap == selected["update_cap"])
        ].sort_values("split")
        result["selected_gate_by_split"] = q.to_dict("records")
    return summary_df, result, gate_df, all_routes


def analyze_micro10s(root: Path, out_dir: Path) -> dict:
    rows = []
    for symbol in ("BTCUSDT", "ETHUSDT"):
        for path in sorted((root / symbol).glob("*.csv.gz")):
            d = pd.read_csv(path)
            d["timestamp"] = pd.to_datetime(d["timestamp"], utc=True)
            d["symbol"] = symbol
            d["date"] = d["timestamp"].dt.strftime("%Y-%m-%d")
            d["spread_bps"] = (d["spread_sum"] / d["book_events"].replace(0, np.nan)) / d["last_mid"] * 10_000.0
            d["flow_ratio"] = d["signed_trade_quote"] / d["total_trade_quote"].replace(0, np.nan)
            for h in (1, 3, 6):
                d[f"future_mid_{h}"] = d["last_mid"].shift(-h)
                d[f"future_bid_{h}"] = d["last_bid"].shift(-h)
                d[f"future_ask_{h}"] = d["last_ask"].shift(-h)
            rows.append(d)
    x = pd.concat(rows, ignore_index=True).sort_values(["symbol", "timestamp"])
    month = x.timestamp.dt.month
    x["split"] = np.where(month == 7, "dev", np.where(month == 10, "val", "conf"))
    out_rows = []
    for side in (-1, 1):
        for h in (1, 3, 6):
            maker_entry = np.where(side > 0, x.last_bid, x.last_ask)
            maker_exit = np.where(side > 0, x[f"future_bid_{h}"], x[f"future_ask_{h}"])
            maker_net = side * (maker_exit / maker_entry - 1.0) * 10_000.0 - 8.0
            toxicity = side * (x[f"future_mid_{h}"] / maker_entry - 1.0) * 10_000.0
            side_flow = side * x.flow_ratio
            side_imb = side * x.last_book_imbalance
            for flow_min in (-0.25, 0.0, 0.25):
                for imb_min in (0.0, 0.25, 0.5):
                    safe = (side_flow >= flow_min) & (side_imb >= imb_min)
                    for split in ("dev", "val", "conf"):
                        m = (x.split == split) & safe & np.isfinite(maker_net)
                        z = maker_net[m]
                        t = toxicity[m]
                        out_rows.append({
                            "side": side,
                            "horizon_10s_bars": h,
                            "flow_min": flow_min,
                            "imbalance_min": imb_min,
                            "split": split,
                            "n": int(m.sum()),
                            "maker_proxy_mean_bps": float(np.nanmean(z)) if len(z) else np.nan,
                            "maker_proxy_trim10_bps": float(np.sort(z)[:-10].mean()) if len(z) > 10 else np.nan,
                            "toxicity_mean_bps": float(np.nanmean(t)) if len(t) else np.nan,
                        })
    out = pd.DataFrame(out_rows)
    out.to_csv(out_dir / "micro10s_state_validation.csv", index=False)
    dev = out[(out.split == "dev") & (out.n >= 100)]
    selected = dev.sort_values(["maker_proxy_trim10_bps", "maker_proxy_mean_bps"], ascending=False).head(1)
    result = {"rows": len(x), "dates": sorted(x.date.unique().tolist()), "selected_dev_state": selected.to_dict("records")}
    if len(selected):
        r = selected.iloc[0]
        q = out[(out.side == r.side) & (out.horizon_10s_bars == r.horizon_10s_bars) & (out.flow_min == r.flow_min) & (out.imbalance_min == r.imbalance_min)]
        result["selected_state_by_split"] = q.to_dict("records")
    return result


def run(args: argparse.Namespace) -> None:
    args.out.mkdir(parents=True, exist_ok=True)
    costs = CostContract()
    route_frames = []
    audit = []
    for symbol, root in (("BTCUSDT", args.btc_root), ("ETHUSDT", args.eth_root)):
        book_path = next(root.glob(f"**/{symbol}-bookTicker-*.zip"))
        trade_path = next(root.glob(f"**/{symbol}-aggTrades-*.zip"))
        book = load_book(book_path)
        trades = load_trades(trade_path)
        panel = build_second_panel(book, trades)
        for route in ROUTES:
            route_frames.append(route_frame(symbol, panel, book, trades, route, costs))
        audit.append({
            "symbol": symbol,
            "book_sha256": sha256_file(book_path),
            "agg_sha256": sha256_file(trade_path),
            "book_events": int(len(book["event_time"])),
            "agg_trades": int(len(trades["transact_time"])),
            "panel_seconds": int(len(panel)),
            "start_utc": pd.to_datetime(panel.index.min(), unit="s", utc=True).isoformat(),
            "end_utc": pd.to_datetime(panel.index.max(), unit="s", utc=True).isoformat(),
        })
    routes = pd.concat(route_frames, ignore_index=True)
    summary_df, gate_result, gate_df, routes = score_routes(routes, costs)
    summary_df.to_csv(args.out / "route_summary.csv", index=False)
    gate_df.to_csv(args.out / "gate_grid.csv", index=False)
    micro_result = analyze_micro10s(args.micro10s_root, args.out)
    report = {
        "schema_version": 1,
        "objective": "L1 maker toxicity and causal maker/taker routing",
        "status": "EXECUTION_RESEARCH_ONLY",
        "dataset_audit": audit,
        "raw_gate": gate_result,
        "micro10s_validation": micro_result,
        "limitations": [
            "one partial raw bookTicker day per symbol",
            "exchange timestamps only",
            "modeled displayed-quantity queue",
            "no private execution or actual account queue position",
            "not a standalone directional alpha test",
        ],
    }
    (args.out / "summary.json").write_text(json.dumps(report, indent=2, sort_keys=True, default=str) + "\n")
    print(json.dumps(report, indent=2, sort_keys=True, default=str))


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--btc-root", type=Path, required=True)
    p.add_argument("--eth-root", type=Path, required=True)
    p.add_argument("--micro10s-root", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    return p.parse_args()


if __name__ == "__main__":
    run(parse_args())
