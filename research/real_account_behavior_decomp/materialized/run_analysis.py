from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd

CUTOFF = pd.Timestamp("2023-12-31T23:59:59.999Z")
BTC_RE = re.compile(r"(?:XBT|BTC)", re.IGNORECASE)
DURATION_BINS = [-np.inf, 60, 360, 1440, 4320, 10080, np.inf]
DURATION_LABELS = ["<1h", "1-6h", "6-24h", "1-3d", "3-7d", ">7d"]


@dataclass
class Episode:
    episode_id: str
    symbol: str
    settlement_currency: str
    side: str
    start_time: pd.Timestamp
    start_price: float
    start_qty: float
    start_home_notional: float
    start_foreign_notional: float
    direct_reversal_entry: bool = False
    entry_after_flat_min: float | None = None
    end_time: pd.Timestamp | None = None
    end_price: float | None = None
    closed: bool = False
    settlement_closed: bool = False
    fill_count: int = 0
    discretionary_fill_count: int = 0
    add_count: int = 0
    reduce_count: int = 0
    winning_add_count: int = 0
    losing_add_count: int = 0
    flat_add_count: int = 0
    favorable_reduce_count: int = 0
    adverse_reduce_count: int = 0
    flat_reduce_count: int = 0
    maker_fill_count: int = 0
    taker_fill_count: int = 0
    unknown_liquidity_fill_count: int = 0
    maker_add_count: int = 0
    taker_add_count: int = 0
    max_abs_position: float = 0.0
    max_home_notional_proxy: float = 0.0
    max_foreign_notional_proxy: float = 0.0
    gross_realised_pnl_native: float = 0.0
    exec_comm_native: float = 0.0
    realised_minus_comm_proxy_native: float = 0.0
    first_order_type: str = ""
    first_time_in_force: str = ""
    first_exec_inst: str = ""
    reversal_from_episode_id: str | None = None
    previous_episode_outcome: str | None = None
    previous_episode_pnl_native: float | None = None


@dataclass
class PositionState:
    symbol: str
    position: float = 0.0
    avg_reference_price: float = math.nan
    current_episode: Episode | None = None
    last_flat_time: pd.Timestamp | None = None
    last_closed_episode: Episode | None = None
    episode_counter: int = 0


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def parse_numeric(s: pd.Series) -> pd.Series:
    return pd.to_numeric(s, errors="coerce").fillna(0.0)


def parse_effective_time(df: pd.DataFrame) -> pd.Series:
    transact = pd.to_datetime(df.get("transactTime"), utc=True, errors="coerce")
    stamp = pd.to_datetime(df.get("timestamp"), utc=True, errors="coerce")
    return transact.fillna(stamp)


def load_pre2024_csv(path: Path, usecols: list[str] | None = None) -> tuple[pd.DataFrame, dict[str, Any]]:
    # Full-file hashing establishes source identity. Economic analysis sees only retained rows.
    df = pd.read_csv(path, dtype=str, low_memory=False, usecols=usecols)
    effective = parse_effective_time(df)
    if effective.isna().any():
        raise RuntimeError(f"{path.name}: {int(effective.isna().sum())} rows lack effective timestamp")
    future = effective > CUTOFF
    stats = {
        "raw_rows": int(len(df)),
        "retained_rows": int((~future).sum()),
        "future_rows_transport_only_discarded": int(future.sum()),
        "first_effective_time": effective.min().isoformat(),
        "last_retained_effective_time": effective.loc[~future].max().isoformat() if (~future).any() else None,
    }
    out = df.loc[~future].copy()
    out["effective_time"] = effective.loc[~future]
    out["source_row"] = np.flatnonzero(~future) + 2
    return out, stats


def liquidity_class(row: pd.Series) -> str:
    val = str(row.get("lastLiquidityInd", "") or "").lower()
    fee_type = str(row.get("feeType", "") or "").lower()
    if any(k in val for k in ("added", "maker")) or "maker" in fee_type:
        return "maker"
    if any(k in val for k in ("removed", "taker")) or "taker" in fee_type:
        return "taker"
    comm = float(row.get("execComm_num", 0.0))
    if comm < 0:
        return "maker"
    if comm > 0:
        return "taker"
    return "unknown"


def sign(x: float, eps: float = 1e-12) -> int:
    if x > eps:
        return 1
    if x < -eps:
        return -1
    return 0


def favorable_state(position: float, avg_price: float, fill_price: float) -> str:
    if not np.isfinite(avg_price) or not np.isfinite(fill_price) or avg_price <= 0 or fill_price <= 0:
        return "unknown"
    move = sign(position) * (fill_price / avg_price - 1.0)
    if move > 1e-9:
        return "favorable"
    if move < -1e-9:
        return "adverse"
    return "flat"


def weighted_price(old_qty: float, old_price: float, add_qty: float, fill_price: float) -> float:
    # This is a directional reference, not an exchange margin/PnL reconstruction.
    if old_qty <= 0 or not np.isfinite(old_price):
        return fill_price
    return (old_qty * old_price + add_qty * fill_price) / (old_qty + add_qty)


def start_episode(state: PositionState, row: pd.Series, residual_qty: float, direct_reversal: bool,
                  reversal_from: Episode | None, fee_fraction: float) -> Episode:
    state.episode_counter += 1
    ts = row.effective_time
    price = float(row.fill_price)
    side = "LONG" if residual_qty > 0 else "SHORT"
    ep = Episode(
        episode_id=f"{state.symbol}-{state.episode_counter:06d}",
        symbol=state.symbol,
        settlement_currency=str(row.get("settlCurrency", "") or row.get("currency", "") or "UNKNOWN"),
        side=side,
        start_time=ts,
        start_price=price,
        start_qty=abs(residual_qty),
        start_home_notional=abs(float(row.get("homeNotional_num", 0.0))) * fee_fraction,
        start_foreign_notional=abs(float(row.get("foreignNotional_num", 0.0))) * fee_fraction,
        direct_reversal_entry=direct_reversal,
        entry_after_flat_min=((ts - state.last_flat_time).total_seconds() / 60.0
                              if state.last_flat_time is not None else None),
        first_order_type=str(row.get("ordType", "") or ""),
        first_time_in_force=str(row.get("timeInForce", "") or ""),
        first_exec_inst=str(row.get("execInst", "") or ""),
        reversal_from_episode_id=reversal_from.episode_id if reversal_from else None,
        previous_episode_outcome=(
            "WIN" if state.last_closed_episode and state.last_closed_episode.gross_realised_pnl_native > 0
            else "LOSS" if state.last_closed_episode and state.last_closed_episode.gross_realised_pnl_native < 0
            else "FLAT" if state.last_closed_episode else None
        ),
        previous_episode_pnl_native=(state.last_closed_episode.gross_realised_pnl_native
                                     if state.last_closed_episode else None),
    )
    state.current_episode = ep
    state.position = residual_qty
    state.avg_reference_price = price
    return ep


def add_fill_accounting(ep: Episode, row: pd.Series, fee_fraction: float = 1.0,
                        realised_fraction: float = 1.0) -> None:
    ep.fill_count += 1
    if str(row.execType).lower() == "trade":
        ep.discretionary_fill_count += 1
    liq = liquidity_class(row)
    if liq == "maker":
        ep.maker_fill_count += 1
    elif liq == "taker":
        ep.taker_fill_count += 1
    else:
        ep.unknown_liquidity_fill_count += 1
    realised = float(row.get("realisedPnl_num", 0.0)) * realised_fraction
    comm = float(row.get("execComm_num", 0.0)) * fee_fraction
    ep.gross_realised_pnl_native += realised
    ep.exec_comm_native += comm
    ep.realised_minus_comm_proxy_native += realised - comm


def close_episode(state: PositionState, ep: Episode, row: pd.Series, settlement_closed: bool) -> None:
    ep.end_time = row.effective_time
    ep.end_price = float(row.fill_price)
    ep.closed = True
    ep.settlement_closed = settlement_closed
    state.last_closed_episode = ep
    state.last_flat_time = row.effective_time
    state.current_episode = None


def reconstruct_episodes(execs: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    work = execs.copy()
    for col in ["lastQty", "lastPx", "price", "avgPx", "realisedPnl", "execComm", "homeNotional", "foreignNotional"]:
        work[f"{col}_num"] = parse_numeric(work.get(col, pd.Series(index=work.index, dtype=str)))
    work["fill_price"] = work["lastPx_num"].where(work["lastPx_num"] > 0, work["avgPx_num"])
    work["fill_price"] = work["fill_price"].where(work["fill_price"] > 0, work["price_num"])
    work["execType"] = work.get("execType", "").fillna("")
    work["side"] = work.get("side", "").fillna("")
    work["symbol"] = work.get("symbol", "").fillna("")
    work = work[
        work.symbol.str.contains(BTC_RE, na=False)
        & work.side.str.lower().isin(["buy", "sell"])
        & (work.lastQty_num > 0)
        & work.execType.str.lower().isin(["trade", "settlement"])
        & (work.fill_price > 0)
    ].copy()
    work = work.sort_values(["effective_time", "source_row", "execID"], kind="mergesort").reset_index(drop=True)

    states: dict[str, PositionState] = {}
    episodes: list[Episode] = []
    actions: list[dict[str, Any]] = []
    rows_used = 0

    for _, row in work.iterrows():
        rows_used += 1
        sym = str(row.symbol)
        state = states.setdefault(sym, PositionState(symbol=sym))
        qty = float(row.lastQty_num)
        dq = qty if str(row.side).lower() == "buy" else -qty
        old_pos = state.position
        old_sign = sign(old_pos)
        dq_sign = sign(dq)
        new_pos = old_pos + dq
        new_sign = sign(new_pos)
        ep = state.current_episode
        settlement = str(row.execType).lower() == "settlement"
        liq = liquidity_class(row)

        if old_sign == 0:
            ep = start_episode(state, row, dq, False, None, 1.0)
            episodes.append(ep)
            add_fill_accounting(ep, row)
            ep.max_abs_position = max(ep.max_abs_position, abs(state.position))
            ep.max_home_notional_proxy = max(ep.max_home_notional_proxy, abs(float(row.homeNotional_num)))
            ep.max_foreign_notional_proxy = max(ep.max_foreign_notional_proxy, abs(float(row.foreignNotional_num)))
            actions.append({"episode_id": ep.episode_id, "time": row.effective_time, "action": "OPEN",
                            "state": "flat", "liquidity": liq, "qty": qty, "price": float(row.fill_price),
                            "exec_type": row.execType})
            continue

        if ep is None:
            raise RuntimeError(f"{sym}: nonzero position without active episode")

        if dq_sign == old_sign:
            condition = favorable_state(old_pos, state.avg_reference_price, float(row.fill_price))
            ep.add_count += 1
            if condition == "favorable":
                ep.winning_add_count += 1
            elif condition == "adverse":
                ep.losing_add_count += 1
            else:
                ep.flat_add_count += 1
            if liq == "maker":
                ep.maker_add_count += 1
            elif liq == "taker":
                ep.taker_add_count += 1
            add_fill_accounting(ep, row)
            state.avg_reference_price = weighted_price(abs(old_pos), state.avg_reference_price, qty, float(row.fill_price))
            state.position = new_pos
            ep.max_abs_position = max(ep.max_abs_position, abs(new_pos))
            ep.max_home_notional_proxy += abs(float(row.homeNotional_num))
            ep.max_foreign_notional_proxy += abs(float(row.foreignNotional_num))
            actions.append({"episode_id": ep.episode_id, "time": row.effective_time, "action": "ADD",
                            "state": condition, "liquidity": liq, "qty": qty, "price": float(row.fill_price),
                            "exec_type": row.execType})
            continue

        # Opposite-side execution: reduction, flat close, or direct reversal.
        close_qty = min(abs(old_pos), qty)
        open_qty = max(0.0, qty - close_qty)
        close_fraction = close_qty / qty if qty > 0 else 1.0
        condition = favorable_state(old_pos, state.avg_reference_price, float(row.fill_price))
        ep.reduce_count += 1
        if condition == "favorable":
            ep.favorable_reduce_count += 1
        elif condition == "adverse":
            ep.adverse_reduce_count += 1
        else:
            ep.flat_reduce_count += 1
        add_fill_accounting(ep, row, fee_fraction=close_fraction, realised_fraction=1.0)
        actions.append({"episode_id": ep.episode_id, "time": row.effective_time, "action": "REDUCE",
                        "state": condition, "liquidity": liq, "qty": close_qty,
                        "price": float(row.fill_price), "exec_type": row.execType})

        if new_sign == old_sign:
            state.position = new_pos
            # Average entry reference is preserved on reductions.
            continue

        old_episode = ep
        close_episode(state, old_episode, row, settlement)

        if new_sign == 0:
            state.position = 0.0
            state.avg_reference_price = math.nan
            actions.append({"episode_id": old_episode.episode_id, "time": row.effective_time,
                            "action": "CLOSE", "state": condition, "liquidity": liq,
                            "qty": close_qty, "price": float(row.fill_price), "exec_type": row.execType})
            continue

        # A single fill crossed through zero. Split its fee between close and residual opening.
        residual_signed = new_pos
        state.position = 0.0
        state.avg_reference_price = math.nan
        new_ep = start_episode(state, row, residual_signed, True, old_episode,
                               fee_fraction=(open_qty / qty if qty else 0.0))
        episodes.append(new_ep)
        # Realised PnL belongs to the closing side; only residual fee/liquidity count belongs to new side.
        new_ep.fill_count += 1
        if str(row.execType).lower() == "trade":
            new_ep.discretionary_fill_count += 1
        if liq == "maker":
            new_ep.maker_fill_count += 1
        elif liq == "taker":
            new_ep.taker_fill_count += 1
        else:
            new_ep.unknown_liquidity_fill_count += 1
        residual_fee = float(row.execComm_num) * (open_qty / qty if qty else 0.0)
        new_ep.exec_comm_native += residual_fee
        new_ep.realised_minus_comm_proxy_native -= residual_fee
        new_ep.max_abs_position = abs(residual_signed)
        new_ep.max_home_notional_proxy = abs(float(row.homeNotional_num)) * (open_qty / qty if qty else 0.0)
        new_ep.max_foreign_notional_proxy = abs(float(row.foreignNotional_num)) * (open_qty / qty if qty else 0.0)
        actions.append({"episode_id": new_ep.episode_id, "time": row.effective_time,
                        "action": "DIRECT_REVERSAL_OPEN", "state": "reversal", "liquidity": liq,
                        "qty": open_qty, "price": float(row.fill_price), "exec_type": row.execType})

    records: list[dict[str, Any]] = []
    for ep in episodes:
        rec = asdict(ep)
        for k in ("start_time", "end_time"):
            if rec[k] is not None:
                rec[k] = pd.Timestamp(rec[k]).isoformat()
        rec["duration_min"] = ((ep.end_time - ep.start_time).total_seconds() / 60.0
                               if ep.closed and ep.end_time is not None else np.nan)
        rec["directional_price_move"] = (
            (1 if ep.side == "LONG" else -1) * (float(ep.end_price) / ep.start_price - 1.0)
            if ep.closed and ep.end_price and ep.start_price > 0 else np.nan
        )
        rec["episode_outcome"] = (
            "WIN" if ep.gross_realised_pnl_native > 0 else "LOSS" if ep.gross_realised_pnl_native < 0 else "FLAT"
        )
        rec["maker_share"] = ep.maker_fill_count / ep.fill_count if ep.fill_count else np.nan
        rec["winning_add_share"] = ep.winning_add_count / ep.add_count if ep.add_count else np.nan
        records.append(rec)

    ep_df = pd.DataFrame(records)
    act_df = pd.DataFrame(actions)
    if not act_df.empty:
        act_df["time"] = pd.to_datetime(act_df.time, utc=True)
    diagnostics = {
        "position_effect_rows_used": rows_used,
        "symbols": sorted(states),
        "cutoff_open_positions": {s: st.position for s, st in states.items() if abs(st.position) > 1e-12},
        "episodes_total": int(len(ep_df)),
        "episodes_closed": int(ep_df.closed.sum()) if not ep_df.empty else 0,
        "episodes_open_at_cutoff": int((~ep_df.closed).sum()) if not ep_df.empty else 0,
    }
    return ep_df, act_df, diagnostics


def safe_share(top_values: Iterable[float], total: float) -> float | None:
    if total <= 0:
        return None
    return float(sum(top_values) / total)


def summary_by_group(ep: pd.DataFrame, group_cols: list[str]) -> pd.DataFrame:
    closed = ep[ep.closed & ~ep.settlement_closed].copy()
    if closed.empty:
        return pd.DataFrame()
    grouped = []
    for keys, g in closed.groupby(group_cols, dropna=False):
        if not isinstance(keys, tuple):
            keys = (keys,)
        pos = g.loc[g.gross_realised_pnl_native > 0, "gross_realised_pnl_native"].sort_values(ascending=False)
        neg = g.loc[g.gross_realised_pnl_native < 0, "gross_realised_pnl_native"]
        rec = dict(zip(group_cols, keys))
        rec.update({
            "episodes": int(len(g)),
            "wins": int((g.gross_realised_pnl_native > 0).sum()),
            "losses": int((g.gross_realised_pnl_native < 0).sum()),
            "win_rate": float((g.gross_realised_pnl_native > 0).mean()),
            "gross_realised_pnl_native": float(g.gross_realised_pnl_native.sum()),
            "realised_minus_comm_proxy_native": float(g.realised_minus_comm_proxy_native.sum()),
            "positive_pnl_native": float(pos.sum()),
            "negative_pnl_native": float(neg.sum()),
            "median_pnl_native": float(g.gross_realised_pnl_native.median()),
            "median_duration_min": float(g.duration_min.median()),
            "mean_duration_min": float(g.duration_min.mean()),
            "median_fills": float(g.fill_count.median()),
            "median_adds": float(g.add_count.median()),
            "median_reductions": float(g.reduce_count.median()),
            "maker_share": float(g.maker_fill_count.sum() / g.fill_count.sum()) if g.fill_count.sum() else None,
            "top1_positive_share": safe_share(pos.head(1), float(pos.sum())),
            "top5_positive_share": safe_share(pos.head(5), float(pos.sum())),
            "top10_positive_share": safe_share(pos.head(10), float(pos.sum())),
            "top10pct_positive_share": safe_share(pos.head(max(1, int(math.ceil(len(pos) * 0.10)))), float(pos.sum())),
        })
        grouped.append(rec)
    return pd.DataFrame(grouped)


def behavior_comparison(ep: pd.DataFrame) -> pd.DataFrame:
    closed = ep[ep.closed & ~ep.settlement_closed].copy()
    rows = []

    def add_row(name: str, mask: pd.Series) -> None:
        g = closed.loc[mask]
        rows.append({
            "behavior": name,
            "episodes": int(len(g)),
            "episode_share": float(len(g) / len(closed)) if len(closed) else None,
            "win_rate": float((g.gross_realised_pnl_native > 0).mean()) if len(g) else None,
            "median_pnl_native": float(g.gross_realised_pnl_native.median()) if len(g) else None,
            "sum_pnl_native": float(g.gross_realised_pnl_native.sum()) if len(g) else 0.0,
            "median_duration_min": float(g.duration_min.median()) if len(g) else None,
            "median_max_position": float(g.max_abs_position.median()) if len(g) else None,
            "maker_share": float(g.maker_fill_count.sum() / g.fill_count.sum()) if len(g) and g.fill_count.sum() else None,
        })

    add_row("ANY_WINNING_ADD", closed.winning_add_count > 0)
    add_row("ANY_LOSING_ADD", closed.losing_add_count > 0)
    add_row("WINNING_ADDS_ONLY", (closed.winning_add_count > 0) & (closed.losing_add_count == 0))
    add_row("LOSING_ADDS_ONLY", (closed.losing_add_count > 0) & (closed.winning_add_count == 0))
    add_row("ANY_FAVORABLE_REDUCE", closed.favorable_reduce_count > 0)
    add_row("ANY_ADVERSE_REDUCE", closed.adverse_reduce_count > 0)
    add_row("DIRECT_REVERSAL_ENTRY", closed.direct_reversal_entry)
    add_row("REENTRY_WITHIN_60M", closed.entry_after_flat_min.notna() & (closed.entry_after_flat_min <= 60))
    add_row("NO_SCALE_IN", closed.add_count == 0)
    add_row("SCALED_IN", closed.add_count > 0)
    add_row("MAKER_MAJORITY", closed.maker_share > 0.5)
    add_row("TAKER_MAJORITY", closed.maker_share < 0.5)
    add_row("AFTER_PREVIOUS_WIN", closed.previous_episode_outcome == "WIN")
    add_row("AFTER_PREVIOUS_LOSS", closed.previous_episode_outcome == "LOSS")
    return pd.DataFrame(rows)


def duration_summary(ep: pd.DataFrame) -> pd.DataFrame:
    closed = ep[ep.closed & ~ep.settlement_closed].copy()
    if closed.empty:
        return pd.DataFrame()
    closed["duration_bucket"] = pd.cut(closed.duration_min, bins=DURATION_BINS,
                                        labels=DURATION_LABELS, ordered=True)
    return summary_by_group(closed, ["settlement_currency", "duration_bucket"])



def order_crosscheck(orders: pd.DataFrame, execs: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, Any]]:
    o = orders.copy()
    e = execs.copy()
    for c in ("orderQty", "cumQty", "leavesQty", "price", "avgPx"):
        o[f"{c}_num"] = parse_numeric(o.get(c, pd.Series(index=o.index, dtype=str)))
    e["lastQty_num"] = parse_numeric(e.get("lastQty", pd.Series(index=e.index, dtype=str)))
    e = e[
        e.get("symbol", "").fillna("").str.contains(BTC_RE, na=False)
        & e.get("execType", "").fillna("").str.lower().eq("trade")
        & (e.lastQty_num > 0)
    ].copy()
    order_ids = set(o.get("orderID", pd.Series(dtype=str)).dropna().astype(str))
    e["order_id_matched"] = e.get("orderID", "").fillna("").astype(str).isin(order_ids)
    matched_ratio = float(e.order_id_matched.mean()) if len(e) else None

    ex_by_order = (e.groupby(["orderID", "symbol"], dropna=False)
                   .agg(execution_rows=("effective_time", "size"), executed_qty=("lastQty_num", "sum"),
                        first_execution=("effective_time", "min"), last_execution=("effective_time", "max"))
                   .reset_index())
    if "orderID" in o:
        latest = (o.sort_values(["effective_time", "source_row"], kind="mergesort")
                  .drop_duplicates("orderID", keep="last"))
        cols = [c for c in ["orderID", "symbol", "ordStatus", "ordType", "timeInForce", "execInst",
                            "workingIndicator", "triggered", "orderQty_num", "cumQty_num", "leavesQty_num",
                            "effective_time"] if c in latest.columns]
        latest = latest[cols].rename(columns={"effective_time": "last_order_state_time"})
        merged = ex_by_order.merge(latest, on=["orderID", "symbol"], how="left")
    else:
        merged = ex_by_order
    if "cumQty_num" in merged:
        merged["executed_minus_order_cum_qty"] = merged.executed_qty - merged.cumQty_num
    diagnostics = {
        "btc_trade_execution_rows": int(len(e)),
        "unique_execution_order_ids": int(e.get("orderID", pd.Series(dtype=str)).nunique()),
        "execution_order_id_match_ratio": matched_ratio,
        "orders_with_execution": int(len(ex_by_order)),
        "matched_final_order_states": int(merged.get("ordStatus", pd.Series(dtype=str)).notna().sum()) if "ordStatus" in merged else 0,
    }
    return merged, diagnostics

def wallet_crosscheck(wallet: pd.DataFrame, execs: pd.DataFrame) -> pd.DataFrame:
    if wallet.empty:
        return pd.DataFrame()
    w = wallet.copy()
    w["amount_num"] = parse_numeric(w.get("amount", pd.Series(index=w.index, dtype=str)))
    trans = w.get("transactType", "").fillna("").astype(str)
    w["type_norm"] = trans.str.lower()
    out = (w.groupby(["currency", "type_norm"], dropna=False)
           .agg(rows=("amount_num", "size"), amount_native=("amount_num", "sum"))
           .reset_index())

    e = execs.copy()
    for c in ("realisedPnl", "execComm"):
        e[f"{c}_num"] = parse_numeric(e.get(c, pd.Series(index=e.index, dtype=str)))
    e = e[e.get("symbol", "").fillna("").str.contains(BTC_RE, na=False)]
    es = (e.groupby("settlCurrency", dropna=False)
          .agg(execution_rows=("effective_time", "size"), realised_pnl_native=("realisedPnl_num", "sum"),
               exec_comm_native=("execComm_num", "sum"))
          .reset_index().rename(columns={"settlCurrency": "currency"}))
    # Return wallet types plus execution aggregates as separate rows; equality is not assumed.
    es["type_norm"] = "__execution_aggregate__"
    es["rows"] = es.execution_rows
    es["amount_native"] = es.realised_pnl_native
    cols = ["currency", "type_norm", "rows", "amount_native", "realised_pnl_native", "exec_comm_native"]
    for c in cols:
        if c not in out:
            out[c] = np.nan
        if c not in es:
            es[c] = np.nan
    return pd.concat([out[cols], es[cols]], ignore_index=True)


def size_after_outcome(ep: pd.DataFrame) -> pd.DataFrame:
    closed = ep[ep.closed & ~ep.settlement_closed].copy()
    g = closed[closed.previous_episode_outcome.isin(["WIN", "LOSS", "FLAT"])]
    if g.empty:
        return pd.DataFrame()
    rows = []
    for (settle, outcome), x in g.groupby(["settlement_currency", "previous_episode_outcome"]):
        rows.append({
            "settlement_currency": settle,
            "previous_outcome": outcome,
            "episodes": int(len(x)),
            "median_start_qty": float(x.start_qty.median()),
            "median_start_home_notional": float(x.start_home_notional.median()),
            "median_start_foreign_notional": float(x.start_foreign_notional.median()),
            "median_max_position": float(x.max_abs_position.median()),
            "median_add_count": float(x.add_count.median()),
            "next_episode_win_rate": float((x.gross_realised_pnl_native > 0).mean()),
        })
    return pd.DataFrame(rows)


def generate_hypotheses(behavior: pd.DataFrame, ep: pd.DataFrame) -> list[dict[str, Any]]:
    hypotheses: list[dict[str, Any]] = []
    lookup = {r.behavior: r for r in behavior.itertuples(index=False)}

    win_add = lookup.get("WINNING_ADDS_ONLY")
    lose_add = lookup.get("LOSING_ADDS_ONLY")
    if win_add and lose_add and win_add.episodes >= 50 and lose_add.episodes >= 50:
        pnl_gap = (win_add.median_pnl_native or 0.0) - (lose_add.median_pnl_native or 0.0)
        rate_gap = (win_add.win_rate or 0.0) - (lose_add.win_rate or 0.0)
        if rate_gap > 0.08 and pnl_gap > 0:
            hypotheses.append({
                "id": "HYP-PROFIT-CONFIRMED-ADD-001",
                "status": "IDEA_EVIDENCE_ONLY",
                "mechanism": "Add risk only after the existing position is favorable and price has accepted beyond the prior position reference; do not average into adverse inventory.",
                "who_pays": "Late participants and opposing inventory that must cover as accepted delivery continues.",
                "persistence_reason": "Information arrives sequentially; favorable progress plus continued acceptance can reveal a stronger state than was known at initial entry.",
                "invalidation": "Price reaccepts through the protected origin or incremental flow no longer produces price progress.",
                "required_bybit_information": ["causal protected origin", "favorable progress", "price/volume efficiency", "OI and account-ratio migration", "peer confirmation"],
                "ledger_evidence": {"winning_add_only_episodes": int(win_add.episodes), "losing_add_only_episodes": int(lose_add.episodes),
                                    "win_rate_gap": float(rate_gap), "median_native_pnl_gap": float(pnl_gap)},
            })

    reversal = lookup.get("DIRECT_REVERSAL_ENTRY")
    non_scaled = lookup.get("NO_SCALE_IN")
    if reversal and reversal.episodes >= 40 and reversal.win_rate is not None:
        overall = ep[ep.closed & ~ep.settlement_closed]
        overall_wr = float((overall.gross_realised_pnl_native > 0).mean()) if len(overall) else 0.0
        if reversal.win_rate - overall_wr > 0.08 and (reversal.median_pnl_native or 0.0) > 0:
            hypotheses.append({
                "id": "HYP-FAILED-THESIS-DIRECT-REVERSAL-001",
                "status": "IDEA_EVIDENCE_ONLY",
                "mechanism": "When a held thesis is invalidated strongly enough to cross through flat, treat the same event as evidence for the opposite action rather than merely closing.",
                "who_pays": "Participants trapped in the invalidated direction who must unwind after the market accepts the opposite state.",
                "persistence_reason": "A decisive invalidation can reveal information asymmetry and forced inventory transfer, not only loss control.",
                "invalidation": "The opposite-side acceptance fails and price returns through the reversal origin.",
                "required_bybit_information": ["state-loss timing", "cross-zero price displacement", "aggressive flow", "OI reset/rebuild", "opposite liquidity path"],
                "ledger_evidence": {"direct_reversal_episodes": int(reversal.episodes), "win_rate": float(reversal.win_rate),
                                    "overall_win_rate": overall_wr, "median_native_pnl": float(reversal.median_pnl_native)},
            })

    maker = lookup.get("MAKER_MAJORITY")
    taker = lookup.get("TAKER_MAJORITY")
    if len(hypotheses) < 2 and maker and taker and maker.episodes >= 100 and taker.episodes >= 100:
        if (maker.win_rate or 0.0) - (taker.win_rate or 0.0) > 0.08 and (maker.median_pnl_native or 0.0) > (taker.median_pnl_native or 0.0):
            hypotheses.append({
                "id": "HYP-PASSIVE-REBALANCE-SELECTION-001",
                "status": "IDEA_EVIDENCE_ONLY",
                "mechanism": "Use passive execution only at a pre-known rebalance price after the directional thesis exists; abstain when price never returns rather than chase displacement.",
                "who_pays": "Urgent participants crossing the spread during temporary rebalancing against a still-valid directional state.",
                "persistence_reason": "Providing liquidity can improve entry and filter unreturned displacement, but only when the underlying state already has positive value.",
                "invalidation": "The directional state is lost before a causal strict trade-through fill.",
                "required_bybit_information": ["BBO or strict trade-through", "pending-slot occupancy", "structural cancellation", "post-fill state validity"],
                "ledger_evidence": {"maker_majority_episodes": int(maker.episodes), "taker_majority_episodes": int(taker.episodes),
                                    "win_rate_gap": float((maker.win_rate or 0.0) - (taker.win_rate or 0.0))},
            })

    return hypotheses[:2]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source-dir", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--source-commit", required=True)
    args = ap.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)

    manifest_path = args.source_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    file_map = {f["file"]: f for f in manifest["files"]}
    required = ["api-v1-execution-tradeHistory.csv", "api-v1-order.csv", "api-v1-user-walletHistory.csv"]
    verification = {}
    for name in required:
        p = args.source_dir / name
        actual = sha256_file(p)
        expected = file_map[name]["sha256"]
        if actual != expected:
            raise RuntimeError(f"hash mismatch for {name}: {actual} != {expected}")
        verification[name] = {"sha256": actual, "size_bytes": p.stat().st_size,
                              "manifest_rows": file_map[name]["rows"]}

    execs, exec_stats = load_pre2024_csv(args.source_dir / required[0])
    orders, order_stats = load_pre2024_csv(args.source_dir / required[1])
    wallet, wallet_stats = load_pre2024_csv(args.source_dir / required[2])

    for name, df, stats in [(required[0], execs, exec_stats), (required[1], orders, order_stats), (required[2], wallet, wallet_stats)]:
        if stats["raw_rows"] != int(file_map[name]["rows"]):
            raise RuntimeError(f"row-count mismatch for {name}: {stats['raw_rows']} != {file_map[name]['rows']}")
        if (df.effective_time > CUTOFF).any():
            raise RuntimeError(f"future row leaked into retained {name}")

    ep, actions, reconstruction = reconstruct_episodes(execs)
    if ep.empty:
        raise RuntimeError("no BTC-related position episodes reconstructed")

    instrument_summary = summary_by_group(ep, ["symbol", "settlement_currency", "side"])
    behavior = behavior_comparison(ep)
    duration = duration_summary(ep)
    size_response = size_after_outcome(ep)
    wallet_check = wallet_crosscheck(wallet, execs)
    order_check, order_diagnostics = order_crosscheck(orders, execs)
    hypotheses = generate_hypotheses(behavior, ep)

    ep_out = ep.copy()
    ep_out.to_csv(args.output / "EPISODES.csv", index=False)
    actions.to_csv(args.output / "ACTIONS.csv", index=False)
    instrument_summary.to_csv(args.output / "INSTRUMENT_SUMMARY.csv", index=False)
    behavior.to_csv(args.output / "BEHAVIOR_SUMMARY.csv", index=False)
    duration.to_csv(args.output / "DURATION_SUMMARY.csv", index=False)
    size_response.to_csv(args.output / "SIZE_AFTER_OUTCOME.csv", index=False)
    wallet_check.to_csv(args.output / "WALLET_CROSSCHECK.csv", index=False)
    order_check.to_csv(args.output / "ORDER_CROSSCHECK.csv", index=False)
    (args.output / "HYPOTHESES.json").write_text(json.dumps(hypotheses, indent=2, sort_keys=True) + "\n")

    closed = ep[ep.closed & ~ep.settlement_closed].copy()
    concentration = []
    for settle, g in closed.groupby("settlement_currency"):
        pos = g[g.gross_realised_pnl_native > 0].sort_values("gross_realised_pnl_native", ascending=False)
        total = float(pos.gross_realised_pnl_native.sum())
        concentration.append({
            "settlement_currency": settle,
            "closed_episodes": int(len(g)),
            "positive_episodes": int(len(pos)),
            "gross_realised_pnl_native": float(g.gross_realised_pnl_native.sum()),
            "median_episode_pnl_native": float(g.gross_realised_pnl_native.median()),
            "top1_positive_share": safe_share(pos.gross_realised_pnl_native.head(1), total),
            "top5_positive_share": safe_share(pos.gross_realised_pnl_native.head(5), total),
            "top10_positive_share": safe_share(pos.gross_realised_pnl_native.head(10), total),
            "top10pct_positive_share": safe_share(pos.gross_realised_pnl_native.head(max(1, int(math.ceil(len(pos) * 0.1)))), total),
            "pnl_from_gt3d_native": float(g.loc[g.duration_min > 4320, "gross_realised_pnl_native"].sum()),
            "episodes_gt3d": int((g.duration_min > 4320).sum()),
        })

    core_evidence = {
        "broad_repetition": int(len(closed)) >= 200,
        "positive_median_by_settlement": {
            str(k): bool(v > 0) for k, v in closed.groupby("settlement_currency").gross_realised_pnl_native.median().items()
        },
        "concentration": concentration,
        "hypotheses_generated": len(hypotheses),
    }
    tail_dominated = any(
        c["top10pct_positive_share"] is not None and c["top10pct_positive_share"] > 0.65
        for c in concentration
    )
    long_duration_dominated = any(
        c["gross_realised_pnl_native"] != 0
        and abs(c["pnl_from_gt3d_native"]) > abs(c["gross_realised_pnl_native"]) * 0.65
        for c in concentration
    )
    decision = (
        "IDEA_EVIDENCE_ONLY_NO_BYBIT_PREREGISTRATION"
        if not hypotheses or tail_dominated or long_duration_dominated
        else "IDEA_EVIDENCE_SUPPORTS_ONE_SEPARATE_BYBIT_PREREGISTRATION"
    )

    source_pin = {
        "source_repository": "bwjoke/BTC-Trading-Since-2020",
        "source_commit": args.source_commit,
        "manifest_sha256": sha256_file(manifest_path),
        "manifest_generated_at": manifest.get("generated_at"),
        "cutoff": CUTOFF.isoformat(),
        "verified_files": verification,
        "transport_note": "Full immutable bytes were hashed. Rows after the cutoff were discarded before behavior reconstruction and never entered summaries, hypotheses, or decisions.",
    }
    (args.output / "SOURCE_PIN.json").write_text(json.dumps(source_pin, indent=2, sort_keys=True) + "\n")

    result = {
        "schema_version": 1,
        "result_id": "RES-20260730-REAL-ACCOUNT-BEHAVIOR-DECOMP-001",
        "claim_id": "CLM-20260730-REAL-ACCOUNT-BEHAVIOR-DECOMP-001",
        "status": "COMPLETED_IDEA_EVIDENCE_ONLY",
        "decision": decision,
        "rank_eligible": False,
        "official_2024_2026_opened": False,
        "orders_submitted": False,
        "source_pin": source_pin,
        "row_filters": {required[0]: exec_stats, required[1]: order_stats, required[2]: wallet_stats},
        "reconstruction": {**reconstruction, "order_crosscheck": order_diagnostics},
        "core_expansion_diagnosis": core_evidence,
        "hypotheses": hypotheses,
        "limitations": [
            "This is one public discretionary account and cannot establish population-level causality.",
            "Position average price is a directional weighted reference, not an exchange margin-engine reproduction for every inverse/quanto contract.",
            "Execution realisedPnl and commission are preserved separately; realised-minus-commission is only a labeled proxy, not asserted wallet NAV.",
            "The ledger lacks the trader's private thesis, contemporaneous chart annotations, and full historical mark-to-market state.",
            "No 2024-2026 external-account action or performance was used to form rules.",
        ],
    }
    (args.output / "RESULT.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")

    def md_table(df: pd.DataFrame, n: int = 20) -> str:
        if df.empty:
            return "_No rows._"
        return df.head(n).to_markdown(index=False)

    report = f"""# Pre-2024 real-account decision-behavior decomposition

## Decision

`{decision}`. This study is **hypothesis-generation evidence only**. It is not a strategy, backtest, ranking result, or live authorization.

## Source boundary

- Repository: `bwjoke/BTC-Trading-Since-2020`
- Pinned commit: `{args.source_commit}`
- Manifest generated: `{manifest.get('generated_at')}`
- Economic cutoff: `{CUTOFF.isoformat()}`
- Execution rows retained: {exec_stats['retained_rows']:,} of {exec_stats['raw_rows']:,}
- Order rows retained: {order_stats['retained_rows']:,} of {order_stats['raw_rows']:,}
- Wallet rows retained: {wallet_stats['retained_rows']:,} of {wallet_stats['raw_rows']:,}

Every required file matched the manifest SHA-256. Later rows were transport-only and were discarded before episode reconstruction.

## Reconstruction

- BTC-related position-effect rows: {reconstruction['position_effect_rows_used']:,}
- Episodes: {reconstruction['episodes_total']:,}
- Closed episodes: {reconstruction['episodes_closed']:,}
- Open at cutoff: {reconstruction['episodes_open_at_cutoff']:,}
- Symbols: {', '.join(reconstruction['symbols'])}
- Execution/order-ID match ratio: {order_diagnostics['execution_order_id_match_ratio']}

## Instrument / side summary

{md_table(instrument_summary, 40)}

## Repeated behavior summary

{md_table(behavior, 30)}

## Holding-time decomposition

{md_table(duration, 40)}

## Size after prior outcome

{md_table(size_response, 20)}

## Core versus Expansion diagnosis

```json
{json.dumps(core_evidence, indent=2, sort_keys=True)}
```

## Falsifiable Bybit hypotheses

```json
{json.dumps(hypotheses, indent=2, sort_keys=True)}
```

## Boundary

No external-account threshold, position size, side, holding time, or 2024-2026 behavior may be copied into a Bybit strategy. Any surviving hypothesis must be independently defined and frozen with canonical Bybit data through 2023-12-31, then evaluated under the project execution and one-slot account contract.
"""
    (args.output / "REPORT.md").write_text(report)

    validation = {
        "status": "PASS",
        "checks": {
            "manifest_hashes_match": True,
            "manifest_row_counts_match": True,
            "cutoff_enforced": True,
            "future_rows_excluded_from_behavior": True,
            "rank_eligible_false": True,
            "orders_submitted_false": True,
            "hypotheses_at_most_two": len(hypotheses) <= 2,
        },
        "output_sha256": {p.name: sha256_file(p) for p in sorted(args.output.iterdir()) if p.is_file()},
    }
    (args.output / "VALIDATION.json").write_text(json.dumps(validation, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
