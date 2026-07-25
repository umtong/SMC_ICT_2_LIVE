from __future__ import annotations

import argparse
import json
import math
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
import pandas as pd
from numba import njit, prange

MINUTE_MS = 60_000
TF_MS = 15 * MINUTE_MS
FUNDING_MS = 8 * 60 * MINUTE_MS
SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT")
SYMBOL_RANK = {s: i for i, s in enumerate(SYMBOLS)}


@dataclass(frozen=True)
class CostModel:
    entry_fee_bps: float = 5.0
    entry_slippage_bps: float = 2.0
    target_fee_bps: float = 2.0
    target_slippage_bps: float = 1.0
    stop_fee_bps: float = 5.0
    stop_slippage_bps: float = 3.0
    funding_stress_bps_per_8h: float = 1.0
    strict_target_trade_through_bps: float = 1.0

    def scaled(self, multiplier: float) -> "CostModel":
        return CostModel(**{key: value * multiplier for key, value in asdict(self).items()})


def load_minutes(path: Path, end_ms: int) -> pd.DataFrame:
    cols = ["open_time", "open", "high", "low", "close", "volume", "close_time", "quote_volume", "n_trades", "taker_buy_base", "taker_buy_quote"]
    dtype = {column: "float64" for column in cols if column not in {"open_time", "close_time", "n_trades"}} | {"open_time": "int64", "close_time": "int64", "n_trades": "int64"}
    frame = pd.read_csv(path, compression="gzip", usecols=cols, dtype=dtype)
    frame = frame[frame.open_time < end_ms].copy().sort_values("open_time").reset_index(drop=True)
    timestamps = frame.open_time.to_numpy(np.int64)
    if len(timestamps) > 1 and not np.all(np.diff(timestamps) == MINUTE_MS):
        raise ValueError(f"minute gaps: {path}")
    return frame


def bars15(minutes: pd.DataFrame) -> pd.DataFrame:
    groups = minutes.open_time.to_numpy(np.int64) // TF_MS
    bars = minutes.assign(_g=groups).groupby("_g", sort=True, observed=True).agg(
        open_time=("open_time", "first"), open=("open", "first"), high=("high", "max"), low=("low", "min"), close=("close", "last"),
        quote_volume=("quote_volume", "sum"), n_trades=("n_trades", "sum"), taker_buy_quote=("taker_buy_quote", "sum")
    ).reset_index(drop=True)
    previous_close = bars.close.shift(1)
    true_range = pd.concat([(bars.high-bars.low), (bars.high-previous_close).abs(), (bars.low-previous_close).abs()], axis=1).max(axis=1)
    bars["atr"] = true_range.rolling(20, min_periods=20).mean().shift(1)
    bars["external_high"] = bars.high.shift(1).rolling(20, min_periods=20).max()
    bars["external_low"] = bars.low.shift(1).rolling(20, min_periods=20).min()
    bars["flow_imbalance"] = (2 * bars.taker_buy_quote - bars.quote_volume) / bars.quote_volume.replace(0, np.nan)
    return bars


def setup_frame(symbol: str, bars: pd.DataFrame, variant: str, cost: CostModel) -> pd.DataFrame:
    o, c, h, l = bars.open, bars.close, bars.high, bars.low
    po, pc = bars.open.shift(1), bars.close.shift(1)
    body, previous_body = (c-o).abs(), (pc-po).abs()
    bull = (c>o) & (pc<po) & (np.minimum(o,c)<=np.minimum(po,pc)) & (np.maximum(o,c)>=np.maximum(po,pc)) & (body>=2*previous_body)
    bear = (c<o) & (pc>po) & (np.minimum(o,c)<=np.minimum(po,pc)) & (np.maximum(o,c)>=np.maximum(po,pc)) & (body>=2*previous_body)
    side = np.where(bull, 1, np.where(bear, -1, 0))
    p2o, p2c = bars.open.shift(2), bars.close.shift(2)
    combined_lo = pd.concat([po,pc,p2o,p2c], axis=1).min(axis=1)
    combined_hi = pd.concat([po,pc,p2o,p2c], axis=1).max(axis=1)
    double = (np.minimum(o,c)<=combined_lo) & (np.maximum(o,c)>=combined_hi) & (body>=2*pd.concat([previous_body,(p2c-p2o).abs()],axis=1).max(axis=1))
    fvg = np.where(side==1, l>bars.high.shift(2), np.where(side==-1, h<bars.low.shift(2), False)).astype(bool)
    sweep = np.where(side==1, (l<bars.external_low-0.02*bars.atr)&(c>bars.external_low), np.where(side==-1,(h>bars.external_high+0.02*bars.atr)&(c<bars.external_high),False)).astype(bool)
    eligible = side != 0
    if variant != "ordinary_engulf": eligible &= sweep
    if variant == "sweep_double_engulf": eligible &= double.to_numpy(bool)
    if variant == "sweep_fvg_engulf": eligible &= fvg
    midpoint = (o+c)/2
    stop = np.where(side==1, l-0.05*bars.atr, h+0.05*bars.atr)
    target = np.where(side==1, bars.external_high, bars.external_low)
    swept = np.where(side==1, bars.external_low, bars.external_high)
    entry_execution = midpoint * (1+side*cost.entry_slippage_bps/10000)
    normal_stop = np.where(side==1, stop*(1-cost.stop_slippage_bps/10000), stop*(1+cost.stop_slippage_bps/10000))
    target_execution = np.where(side==1, target*(1-cost.target_slippage_bps/10000), target*(1+cost.target_slippage_bps/10000))
    gross_loss = np.where(side==1, entry_execution-normal_stop, normal_stop-entry_execution)
    gross_win = np.where(side==1, target_execution-entry_execution, entry_execution-target_execution)
    maximum_loss = gross_loss + entry_execution*cost.entry_fee_bps/10000 + normal_stop*cost.stop_fee_bps/10000
    net_win = gross_win - entry_execution*cost.entry_fee_bps/10000 - target_execution*cost.target_fee_bps/10000
    rr = net_win/maximum_loss
    structure = np.where(side==1, (stop<midpoint)&(midpoint<target), (target<midpoint)&(midpoint<stop))
    eligible &= np.isfinite(bars.atr) & np.isfinite(target) & structure & (rr>=2.0)
    result = pd.DataFrame({"symbol":symbol,"variant":variant,"side":side,"signal_open_ms":bars.open_time,"available_ms":bars.open_time+TF_MS,"zone_mid":midpoint,"stop":stop,"target":target,"atr":bars.atr,"swept_level":swept,"net_rr_estimate":rr})
    result = result[eligible].copy().reset_index(drop=True)
    result["setup_id"] = [f"{symbol}:{variant}:{int(timestamp)}" for timestamp in result.signal_open_ms]
    return result


@njit(cache=True)
def _rr_est(side, entry_raw, stop, target, costs):
    entry_fee, entry_slip, target_fee, target_slip, stop_fee, stop_slip, _, _ = costs
    entry = entry_raw * (1 + side*entry_slip/10000)
    stop_execution = stop * (1 - side*stop_slip/10000)
    target_execution = target * (1 - side*target_slip/10000)
    if side == 1:
        gross_loss, gross_win = entry-stop_execution, target_execution-entry
    else:
        gross_loss, gross_win = stop_execution-entry, entry-target_execution
    loss = gross_loss + entry*entry_fee/10000 + stop_execution*stop_fee/10000
    win = gross_win - entry*entry_fee/10000 - target_execution*target_fee/10000
    return win/loss if loss > 0 else -1e99


@njit(parallel=True, cache=True)
def simulate_many(timestamps, opens, highs, lows, available, midpoint, stop, target, side, costs):
    n_setups, n_bars = len(available), len(timestamps)
    state = np.zeros(n_setups, np.int16)
    entry_index = np.full(n_setups,-1,np.int64); exit_index=np.full(n_setups,-1,np.int64)
    entry_price=np.full(n_setups,np.nan); exit_price=np.full(n_setups,np.nan); r=np.full(n_setups,np.nan); rr=np.full(n_setups,np.nan); funding_count=np.zeros(n_setups,np.int32)
    entry_fee, entry_slip, target_fee, target_slip, stop_fee, stop_slip, funding_cost, trade_through = costs
    for setup_i in prange(n_setups):
        start = np.searchsorted(timestamps, available[setup_i])
        touched = -1
        for bar_i in range(start, n_bars-1):
            stop_pre = lows[bar_i] <= stop[setup_i] if side[setup_i] == 1 else highs[bar_i] >= stop[setup_i]
            target_pre = highs[bar_i] > target[setup_i]*(1+trade_through/10000) if side[setup_i] == 1 else lows[bar_i] < target[setup_i]*(1-trade_through/10000)
            touch = lows[bar_i] <= midpoint[setup_i] and highs[bar_i] >= midpoint[setup_i]
            if stop_pre: state[setup_i]=1; break
            if target_pre: state[setup_i]=2; break
            if touch: touched=bar_i; break
        if touched < 0:
            if state[setup_i] == 0: state[setup_i]=7
            continue
        ei = touched+1; entry_index[setup_i]=ei; raw=opens[ei]
        if (side[setup_i]==1 and (raw<=stop[setup_i] or raw>=target[setup_i])) or (side[setup_i]==-1 and (raw>=stop[setup_i] or raw<=target[setup_i])):
            state[setup_i]=8; continue
        rr_value = _rr_est(side[setup_i],raw,stop[setup_i],target[setup_i],costs); rr[setup_i]=rr_value
        entry = raw*(1+side[setup_i]*entry_slip/10000); entry_price[setup_i]=entry
        if rr_value < 2: state[setup_i]=3; continue
        found=False
        for bar_i in range(ei,n_bars):
            stop_hit = lows[bar_i]<=stop[setup_i] if side[setup_i]==1 else highs[bar_i]>=stop[setup_i]
            target_hit = highs[bar_i]>target[setup_i]*(1+trade_through/10000) if side[setup_i]==1 else lows[bar_i]<target[setup_i]*(1-trade_through/10000)
            if stop_hit or target_hit:
                stop_first = stop_hit
                normal_stop=stop[setup_i]*(1-side[setup_i]*stop_slip/10000)
                if side[setup_i] == 1:
                    stop_x=min(normal_stop,opens[bar_i]*(1-stop_slip/10000)) if opens[bar_i]<stop[setup_i] else normal_stop
                    target_x=target[setup_i]*(1-target_slip/10000)
                    gross=(stop_x-entry) if stop_first else (target_x-entry)
                else:
                    stop_x=max(normal_stop,opens[bar_i]*(1+stop_slip/10000)) if opens[bar_i]>stop[setup_i] else normal_stop
                    target_x=target[setup_i]*(1+target_slip/10000)
                    gross=(entry-stop_x) if stop_first else (entry-target_x)
                exit_x=stop_x if stop_first else target_x
                fee=entry*entry_fee/10000+exit_x*(stop_fee if stop_first else target_fee)/10000
                risk=(entry-normal_stop)+entry*entry_fee/10000+normal_stop*stop_fee/10000 if side[setup_i]==1 else (normal_stop-entry)+entry*entry_fee/10000+normal_stop*stop_fee/10000
                n_funding=max(0,timestamps[bar_i]//FUNDING_MS-timestamps[ei]//FUNDING_MS)
                net=gross-fee-entry*funding_cost/10000*n_funding
                r[setup_i]=net/risk; funding_count[setup_i]=n_funding; exit_index[setup_i]=bar_i; exit_price[setup_i]=exit_x; state[setup_i]=4 if stop_first else 5
                found=True; break
        if not found: state[setup_i]=6
    return state,entry_index,exit_index,entry_price,exit_price,r,rr,funding_count

STATE={1:"cancelled_structure",2:"cancelled_target_consumed",3:"entry_rr_rejected",4:"stop",5:"target",6:"position_unresolved",7:"setup_unresolved",8:"entry_gap_invalid"}


def simulate_setups(setups: pd.DataFrame, minutes: pd.DataFrame, cost: CostModel) -> pd.DataFrame:
    if setups.empty:
        return setups.assign(entry_ms=pd.Series(dtype="int64"),exit_ms=pd.Series(dtype="int64"),r=pd.Series(dtype="float64"),result=pd.Series(dtype="object"))
    costs=np.array([cost.entry_fee_bps,cost.entry_slippage_bps,cost.target_fee_bps,cost.target_slippage_bps,cost.stop_fee_bps,cost.stop_slippage_bps,cost.funding_stress_bps_per_8h,cost.strict_target_trade_through_bps],float)
    state,ei,xi,ep,xp,r,rr,fc=simulate_many(minutes.open_time.to_numpy(np.int64),minutes.open.to_numpy(float),minutes.high.to_numpy(float),minutes.low.to_numpy(float),setups.available_ms.to_numpy(np.int64),setups.zone_mid.to_numpy(float),setups.stop.to_numpy(float),setups.target.to_numpy(float),setups.side.to_numpy(np.int8),costs)
    out=setups.copy(); timestamps=minutes.open_time.to_numpy(np.int64)
    out["entry_ms"]=np.where(ei>=0,timestamps[np.maximum(ei,0)],-1); out["exit_ms"]=np.where(xi>=0,timestamps[np.maximum(xi,0)],-1)
    out["entry_price"]=ep; out["exit_price"]=xp; out["r"]=r; out["net_rr_at_entry"]=rr; out["funding_events"]=fc; out["result"]=[STATE.get(int(value),"unknown") for value in state]
    return out


def select_global(candidates: pd.DataFrame) -> pd.DataFrame:
    candidates=candidates[candidates.result.isin(["stop","target","position_unresolved"])&(candidates.entry_ms>=0)].copy()
    if candidates.empty: return candidates
    candidates["symbol_rank"]=candidates.symbol.map(SYMBOL_RANK)
    candidates=candidates.sort_values(["entry_ms","net_rr_at_entry","symbol_rank"],ascending=[True,False,True])
    selected=[]; busy=-1
    for row in candidates.itertuples(index=False):
        if row.entry_ms <= busy: continue
        selected.append(row._asdict())
        if row.exit_ms < 0: break
        busy=row.exit_ms
    return pd.DataFrame(selected)


def metrics(trades: pd.DataFrame, start: int, end: int, risk: float=0.03):
    q=trades[(trades.entry_ms>=start)&(trades.entry_ms<end)&trades.r.notna()].copy(); rs=q.r.to_numpy(float)
    positive=rs[rs>0]; negative=rs[rs<0]
    pf=positive.sum()/abs(negative.sum()) if len(negative) and abs(negative.sum()) else (math.inf if len(positive) else 0.0)
    equity=1.; peak=1.; maximum_drawdown=0.; liquidated=False
    for value in rs:
        equity*=1+risk*value
        if equity<=0: equity=0.; maximum_drawdown=-1.; liquidated=True; break
        peak=max(peak,equity); maximum_drawdown=min(maximum_drawdown,equity/peak-1)
    days=max(1.,(end-start)/86_400_000); daily=equity**(1/days)-1 if equity>0 else -1
    top5=np.sort(positive)[-5:].sum()/positive.sum() if len(positive) and positive.sum()>0 else 0.
    by_symbol={symbol:{"trades":int((q.symbol==symbol).sum()),"sum_r":float(q.loc[q.symbol==symbol,"r"].sum())} for symbol in SYMBOLS if (q.symbol==symbol).any()}
    return {"trades":len(rs),"sum_r":float(rs.sum()) if len(rs) else 0.,"mean_r":float(rs.mean()) if len(rs) else 0.,"profit_factor":float(pf),"wins":int((rs>0).sum()),"losses":int((rs<0).sum()),"ending_nav_multiple":equity,"daily_geometric_growth":daily,"max_drawdown":maximum_drawdown,"liquidated":liquidated,"top5_positive_r_share":float(top5),"by_symbol":by_symbol}


def run(data_dir: Path, output_dir: Path, end_exclusive: str, multiplier: float):
    end=int(pd.Timestamp(end_exclusive,tz="UTC").timestamp()*1000); cost=CostModel().scaled(multiplier); variants=["ordinary_engulf","sweep_engulf","sweep_double_engulf","sweep_fvg_engulf"]
    bags={variant:[] for variant in variants}; counts={variant:{} for variant in variants}
    for symbol in SYMBOLS:
        minutes=load_minutes(data_dir/f"{symbol}_1m_2025-01_2026-06.csv.gz",end); bars=bars15(minutes)
        for variant in variants:
            setups=setup_frame(symbol,bars,variant,cost); counts[variant][symbol]=len(setups); bags[variant].append(simulate_setups(setups,minutes,cost))
    splits={"DEV1":("2025-01-01","2025-04-01"),"DEV2":("2025-04-01","2025-07-01"),"VALID":("2025-07-01","2025-10-01"),"TEST1":("2025-10-01","2026-01-01"),"TEST2":("2026-01-01","2026-04-01")}
    output_dir.mkdir(parents=True,exist_ok=True); result={}
    for variant in variants:
        candidates=pd.concat(bags[variant],ignore_index=True) if bags[variant] else pd.DataFrame(); selected=select_global(candidates); selected.to_csv(output_dir/f"{variant}_selected_trades.csv",index=False)
        segments={}
        for name,(a_string,b_string) in splits.items():
            a=int(pd.Timestamp(a_string,tz="UTC").timestamp()*1000); b=int(pd.Timestamp(b_string,tz="UTC").timestamp()*1000); segments[name]=metrics(selected,a,b)
        development=all(segments[name]["trades"]>=20 and segments[name]["sum_r"]>0 and segments[name]["profit_factor"]>=1.2 and segments[name]["top5_positive_r_share"]<=0.4 for name in ("DEV1","DEV2"))
        forward=development and all(segments[name]["sum_r"]>0 and segments[name]["profit_factor"]>=1.1 for name in ("VALID","TEST1","TEST2"))
        result[variant]={"setup_counts":counts[variant],"candidate_states":candidates.result.value_counts().to_dict(),"selected_trades":len(selected),"segments":segments,"development_gate":development,"pre_holdout_forward_gate":forward}
    summary={"study_id":"YT20-ALPHA-001","implementation":"vectorized_range20_external_liquidity_v1","end_exclusive":end_exclusive,"cost_multiplier":multiplier,"cost_model":asdict(cost),"variants":result,"holdout_opened":False,"funding_note":"Conservative unsigned charge; actual signed funding not available in this dataset."}
    (output_dir/"summary.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2,allow_nan=True),encoding="utf-8")
    return summary


def main():
    parser=argparse.ArgumentParser(); parser.add_argument("--data-dir",type=Path,required=True); parser.add_argument("--output-dir",type=Path,required=True); parser.add_argument("--end-exclusive",default="2026-04-01"); parser.add_argument("--cost-multiplier",type=float,default=1.0); args=parser.parse_args()
    print(json.dumps(run(args.data_dir,args.output_dir,args.end_exclusive,args.cost_multiplier),ensure_ascii=False,indent=2,allow_nan=True))

if __name__ == "__main__": main()
