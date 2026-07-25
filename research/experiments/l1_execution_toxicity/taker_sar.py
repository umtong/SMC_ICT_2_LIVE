from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

LATENCIES_MS = (0, 100, 250, 500, 1000)


def load_book(path: Path) -> dict[str, np.ndarray]:
    cols = ["best_bid_price", "best_ask_price", "event_time"]
    parts: dict[str, list[np.ndarray]] = {c: [] for c in cols}
    dtypes = {"best_bid_price": "float64", "best_ask_price": "float64", "event_time": "int64"}
    for chunk in pd.read_csv(path, usecols=cols, dtype=dtypes, chunksize=750_000):
        for col in cols:
            parts[col].append(chunk[col].to_numpy(copy=True))
    data = {col: np.concatenate(values) for col, values in parts.items()}
    order = np.argsort(data["event_time"], kind="stable")
    return {col: values[order] for col, values in data.items()}


def run(args: argparse.Namespace) -> None:
    rows = []
    state_rows = []
    for symbol, path in (("BTCUSDT", args.btc_book), ("ETHUSDT", args.eth_book)):
        book = load_book(path)
        panel = pd.read_csv(args.panel_dir / f"{symbol}_one_second_panel.csv.gz", index_col="sec")
        seconds = panel.index.to_numpy(np.int64)
        idx = np.arange(120, len(panel) - 121, 5, dtype=np.int64)
        mid = panel.mid.to_numpy(float)[idx]
        bid0 = panel.best_bid_price.to_numpy(float)[idx]
        ask0 = panel.best_ask_price.to_numpy(float)[idx]
        decision_ms = (seconds[idx] + 1) * 1000
        lo = int(seconds[idx].min())
        hi = int(seconds[idx].max()) + 1
        split_a = lo + (hi - lo) // 2
        split_b = lo + 3 * (hi - lo) // 4
        split = np.where(seconds[idx] < split_a, "dev", np.where(seconds[idx] < split_b, "val", "conf"))
        updates = panel.book_updates_ratio.to_numpy(float)[idx]
        spread = panel.spread_bps.to_numpy(float)[idx]
        flow = panel.flow_5s.to_numpy(float)[idx]
        imbalance = panel.imbalance.to_numpy(float)[idx]
        micro = panel.micro_bps.to_numpy(float)[idx]
        for side in (-1, 1):
            current_touch = np.where(side > 0, ask0, bid0)
            for latency in LATENCIES_MS:
                j = np.searchsorted(book["event_time"], decision_ms + latency)
                valid = j < len(book["event_time"])
                j = np.minimum(j, len(book["event_time"]) - 1)
                touch = np.where(side > 0, book["best_ask_price"][j], book["best_bid_price"][j])
                acquisition = side * (touch / mid - 1.0) * 10_000.0 + 6.0
                slippage = side * (touch / current_touch - 1.0) * 10_000.0
                for label in ("dev", "val", "conf"):
                    mask = (split == label) & valid & np.isfinite(acquisition)
                    cost = acquisition[mask]
                    slip = slippage[mask]
                    rows.append({
                        "symbol": symbol,
                        "side": side,
                        "latency_ms": latency,
                        "split": label,
                        "n": int(mask.sum()),
                        "mean_cost_bps": float(np.mean(cost)),
                        "median_cost_bps": float(np.median(cost)),
                        "sar95_bps": float(np.quantile(cost, .95)),
                        "sar99_bps": float(np.quantile(cost, .99)),
                        "mean_slippage_over_touch_bps": float(np.mean(slip)),
                        "slippage95_bps": float(np.quantile(slip, .95)),
                    })
                if latency == 250:
                    state_rows.append(pd.DataFrame({
                        "symbol": symbol,
                        "side": side,
                        "split": split,
                        "cost_bps": acquisition,
                        "slippage_bps": slippage,
                        "spread_bps": spread,
                        "side_flow5": side * flow,
                        "side_imbalance": side * imbalance,
                        "side_micro_bps": side * micro,
                        "update_ratio": updates,
                    }))
    summary = pd.DataFrame(rows)
    summary.to_csv(args.out, index=False)
    states = pd.concat(state_rows, ignore_index=True)
    grid = []
    for flow_min in (-.25, 0.0, .25):
        for imbalance_min in (0.0, .25, .5):
            for update_cap in (1.0, 2.0, 4.0):
                safe = (
                    (states.side_flow5 >= flow_min)
                    & (states.side_imbalance >= imbalance_min)
                    & (states.update_ratio <= update_cap)
                )
                for label in ("dev", "val", "conf"):
                    mask = (states.split == label) & safe
                    cost = states.loc[mask, "cost_bps"]
                    grid.append({
                        "flow_min": flow_min,
                        "imbalance_min": imbalance_min,
                        "update_cap": update_cap,
                        "split": label,
                        "n": len(cost),
                        "share": float(mask.mean()),
                        "mean_cost_bps": float(cost.mean()),
                        "sar95_bps": float(cost.quantile(.95)),
                        "sar99_bps": float(cost.quantile(.99)),
                    })
    grid_df = pd.DataFrame(grid)
    grid_df.to_csv(args.out.with_name("taker_sar_state_grid.csv"), index=False)
    selected = grid_df[(grid_df.split == "dev") & (grid_df.share >= .05)].sort_values(["sar95_bps", "mean_cost_bps"]).head(1)
    result = {"selected_dev_low_sar_state": selected.to_dict("records")}
    if len(selected):
        row = selected.iloc[0]
        result["selected_state_by_split"] = grid_df[
            (grid_df.flow_min == row.flow_min)
            & (grid_df.imbalance_min == row.imbalance_min)
            & (grid_df.update_cap == row.update_cap)
        ].to_dict("records")
    args.out.with_name("taker_sar_summary.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--btc-book", type=Path, required=True)
    parser.add_argument("--eth-book", type=Path, required=True)
    parser.add_argument("--panel-dir", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    return parser.parse_args()


if __name__ == "__main__":
    run(parse_args())
