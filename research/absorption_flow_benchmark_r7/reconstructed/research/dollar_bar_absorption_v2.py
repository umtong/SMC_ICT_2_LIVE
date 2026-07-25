#!/usr/bin/env python3
from __future__ import annotations

import argparse
import dataclasses
import importlib.util
import json
import math
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

BASE_PATH = Path(__file__).with_name("absorption_flow_benchmark.py")
spec = importlib.util.spec_from_file_location("absbench_base", BASE_PATH)
base = importlib.util.module_from_spec(spec)
assert spec and spec.loader
sys.modules[spec.name] = base
spec.loader.exec_module(base)

TARGET_BARS = (144, 288, 576)
LOOKBACK_DAYS = 20
MAX_CLOCK_MINUTES = 30
DEVELOPMENT_START = base.DEVELOPMENT_START
DEVELOPMENT_END = base.DEVELOPMENT_END
SELECTION_START = pd.Timestamp("2024-01-01T00:00:00Z")
SELECTION_END = pd.Timestamp("2025-01-01T00:00:00Z")
CONFIRMATION_START = SELECTION_END
CONFIRMATION_END = base.VALIDATION_END


@dataclass(frozen=True)
class DollarCandidate:
    target_bars_per_day: int
    family: str
    horizon_bars: int
    z_min: float
    z_max: float
    terminal_bars: int
    flow_threshold: float
    efficiency_min: float
    hold_min: float
    stop_buffer_atr: float
    reward_risk: float
    maximum_holding_minutes: int

    @property
    def signal_key(self) -> str:
        zmax = "inf" if not np.isfinite(self.z_max) else f"{self.z_max:g}"
        return (
            f"bpd{self.target_bars_per_day}|{self.family}|h{self.horizon_bars}|"
            f"z{self.z_min:g}-{zmax}|t{self.terminal_bars}|f{self.flow_threshold:g}|"
            f"e{self.efficiency_min:g}|hold{self.hold_min:g}|buf{self.stop_buffer_atr:g}"
        )

    @property
    def candidate_id(self) -> str:
        return f"{self.signal_key}|rr{self.reward_risk:g}|life{self.maximum_holding_minutes}"


def candidate_grid() -> list[DollarCandidate]:
    out: list[DollarCandidate] = []
    for bpd in TARGET_BARS:
        for family in ("absorption_continuation", "aligned_continuation", "absorption_reversal"):
            for horizon in (6, 12, 24):
                for zmin, zmax in ((2.0, 4.5), (3.0, math.inf)):
                    for terminal in (2, 4):
                        if family == "absorption_continuation":
                            flow, eff, hold = -0.05, 0.35, 0.70
                        elif family == "aligned_continuation":
                            flow, eff, hold = 0.10, 0.45, 0.70
                        else:
                            flow, eff, hold = -0.05, 0.25, 0.50
                        for rr in (1.0, 2.0, 4.0):
                            out.append(DollarCandidate(
                                target_bars_per_day=bpd,
                                family=family,
                                horizon_bars=horizon,
                                z_min=zmin,
                                z_max=zmax,
                                terminal_bars=terminal,
                                flow_threshold=flow,
                                efficiency_min=eff,
                                hold_min=hold,
                                stop_buffer_atr=0.25 if horizon <= 12 else 0.50,
                                reward_risk=rr,
                                maximum_holding_minutes={1.0: 120, 2.0: 240, 4.0: 480}[rr],
                            ))
    return out


def prior_daily_thresholds(minute: pd.DataFrame, target_bars_per_day: int) -> pd.Series:
    daily = minute.quote_volume.resample("1D").sum(min_count=1)
    complete = minute.open.resample("1D").count().eq(1440)
    daily = daily.where(complete)
    median = daily.shift(1).rolling(LOOKBACK_DAYS, min_periods=LOOKBACK_DAYS).median()
    return median / float(target_bars_per_day)


def contiguous_segments(index: pd.DatetimeIndex) -> np.ndarray:
    if len(index) == 0:
        return np.array([], dtype=np.int64)
    gaps = index.to_series().diff().ne(pd.Timedelta(minutes=1)).to_numpy()
    gaps[0] = True
    return np.cumsum(gaps).astype(np.int64)


def build_dollar_bars(minute: pd.DataFrame, target_bars_per_day: int) -> pd.DataFrame:
    thresholds = prior_daily_thresholds(minute, target_bars_per_day)
    idx = minute.index
    days = idx.floor("D")
    segment_ids = contiguous_segments(idx)
    records: list[dict[str, Any]] = []
    # Day loops keep current-day information isolated from the threshold estimator.
    for day in pd.Index(days.unique()).sort_values():
        threshold = thresholds.get(day, np.nan)
        if not np.isfinite(threshold) or threshold <= 0:
            continue
        mask = days == day
        positions = np.flatnonzero(mask)
        if len(positions) == 0:
            continue
        # Never bridge a source gap even if it occurs inside a UTC day.
        for segment_id in np.unique(segment_ids[positions]):
            pos = positions[segment_ids[positions] == segment_id]
            if len(pos) == 0:
                continue
            frame = minute.iloc[pos]
            quote = frame.quote_volume.to_numpy(float)
            cumulative = np.cumsum(quote)
            start = 0
            while start < len(frame):
                before = cumulative[start - 1] if start else 0.0
                threshold_pos = int(np.searchsorted(cumulative, before + threshold, side="left"))
                cap_pos = min(start + MAX_CLOCK_MINUTES - 1, len(frame) - 1)
                end = min(threshold_pos, cap_pos)
                threshold_hit = threshold_pos <= cap_pos and threshold_pos < len(frame)
                block = frame.iloc[start:end + 1]
                if block.empty:
                    break
                signed = float(block.signed_quote.sum())
                quote_sum = float(block.quote_volume.sum())
                records.append({
                    "start_time": block.index[0],
                    "end_time": block.index[-1],
                    "decision_time": block.index[-1] + pd.Timedelta(minutes=1),
                    "open": float(block.open.iloc[0]),
                    "high": float(block.high.max()),
                    "low": float(block.low.min()),
                    "close": float(block.close.iloc[-1]),
                    "volume": float(block.volume.sum()),
                    "quote_volume": quote_sum,
                    "signed_quote": signed,
                    "num_trades": float(block.num_trades.sum()),
                    "source_minutes": int(len(block)),
                    "threshold": float(threshold),
                    "threshold_hit": bool(threshold_hit),
                    "segment_id": int(segment_id),
                    "day": day,
                })
                start = end + 1
    out = pd.DataFrame(records)
    if out.empty:
        return out
    out = out.set_index(pd.DatetimeIndex(pd.to_datetime(out.pop("decision_time"), utc=True), name="decision_time"))
    out = out.sort_index()
    return out


def prior_z(series: pd.Series, window: int, minimum: int) -> pd.Series:
    shifted = series.shift(1)
    mean = shifted.rolling(window, min_periods=minimum).mean()
    std = shifted.rolling(window, min_periods=minimum).std(ddof=0)
    return (series - mean) / std.replace(0, np.nan)


def prepare_clock_features(bars: pd.DataFrame, target_bars_per_day: int) -> pd.DataFrame:
    frame = bars.copy()
    prev = frame.close.shift(1)
    tr = pd.concat([(frame.high-frame.low),(frame.high-prev).abs(),(frame.low-prev).abs()],axis=1).max(axis=1)
    frame["atr"] = tr.rolling(max(24, target_bars_per_day // 6), min_periods=max(12, target_bars_per_day // 12)).mean()
    frame["ret_1"] = np.log(frame.close/frame.close.shift(1))
    frame["flow_1"] = frame.signed_quote/frame.quote_volume.replace(0,np.nan)
    roll_window = max(500, 20 * target_bars_per_day)
    roll_min = max(200, 5 * target_bars_per_day)
    for terminal in (2,4):
        s=frame.signed_quote.rolling(terminal,min_periods=terminal).sum()
        q=frame.quote_volume.rolling(terminal,min_periods=terminal).sum()
        frame[f"flow_{terminal}"]=s/q.replace(0,np.nan)
    for horizon in (6,12,24):
        disp=np.log(frame.close/frame.close.shift(horizon))
        frame[f"disp_{horizon}"]=disp
        frame[f"z_{horizon}"]=prior_z(disp,roll_window,roll_min)
        path=frame.ret_1.abs().rolling(horizon,min_periods=horizon).sum()
        frame[f"eff_{horizon}"]=disp.abs()/path.replace(0,np.nan)
        hi=frame.high.rolling(horizon+1,min_periods=horizon+1).max(); lo=frame.low.rolling(horizon+1,min_periods=horizon+1).min(); span=(hi-lo).replace(0,np.nan)
        frame[f"high_{horizon}"]=hi;frame[f"low_{horizon}"]=lo
        frame[f"long_hold_{horizon}"]=(frame.close-lo)/span
        frame[f"short_hold_{horizon}"]=(hi-frame.close)/span
        frame[f"exact_{horizon}"]=frame.segment_id.eq(frame.segment_id.shift(horizon))
    return frame


def generate_events(frame: pd.DataFrame, candidate: DollarCandidate, symbol: str, start: pd.Timestamp, end: pd.Timestamp) -> list[Any]:
    h=candidate.horizon_bars
    section=frame.loc[start-pd.Timedelta(days=40):end].copy()
    displacement=section[f"disp_{h}"];direction=np.sign(displacement).astype(float);abs_z=section[f"z_{h}"].abs()
    flow_dir=direction*section[f"flow_{candidate.terminal_bars}"]
    hold=pd.Series(np.where(direction>0,section[f"long_hold_{h}"],section[f"short_hold_{h}"]),index=section.index)
    condition=(
        section[f"exact_{h}"].fillna(False)&section.threshold_hit.fillna(False)&abs_z.ge(candidate.z_min)
        &(abs_z.lt(candidate.z_max) if np.isfinite(candidate.z_max) else True)
        &section[f"eff_{h}"].ge(candidate.efficiency_min)&section.atr.gt(0)&direction.ne(0)
    )
    if candidate.family=="absorption_continuation":
        condition &= flow_dir.le(candidate.flow_threshold)&hold.ge(candidate.hold_min); side=direction
    elif candidate.family=="aligned_continuation":
        condition &= flow_dir.ge(candidate.flow_threshold)&hold.ge(candidate.hold_min); side=direction
    else:
        last_dir=direction*section.ret_1
        condition &= flow_dir.le(candidate.flow_threshold)&last_dir.lt(0)&hold.between(0.30,0.70); side=-direction
    episode=condition&~condition.shift(1,fill_value=False)
    episode &= (episode.index>=start)&(episode.index<end)
    events=[]
    for i in np.flatnonzero(episode.to_numpy(bool)):
        row=section.iloc[i];signal_side=int(side.iloc[i]);decision=section.index[i]
        if candidate.family=="absorption_reversal":
            stop_ref=float(row[f"high_{h}"] if signal_side<0 else row[f"low_{h}"])
        else:
            terminal=section.iloc[max(0,i-candidate.terminal_bars+1):i+1]
            stop_ref=float(terminal.low.min() if signal_side>0 else terminal.high.max())
        score=float(abs_z.iloc[i]*max(section[f"eff_{h}"].iloc[i],0)*(1+abs(flow_dir.iloc[i])))
        events.append(base.Event(candidate.candidate_id,symbol,decision-pd.Timedelta(minutes=1),decision,decision,signal_side,score,float(row.atr),stop_ref,float(row[f"high_{h}"] if signal_side<0 else row[f"low_{h}"]),candidate.family))
    return events


def dev_gate(screen: pd.DataFrame) -> pd.DataFrame:
    return base.gate_development(screen)


def single_period_gate(group: pd.DataFrame, period: str) -> bool:
    for cost in ("base","stress_2x"):
        row=group[(group.period==period)&(group.cost_profile==cost)]
        if row.empty:return False
        r=row.iloc[0]
        if not (r.trade_count>=20 and r.total_return>0 and r.average_r>0 and r.profit_factor>=1.10):return False
        if not (r.max_drawdown>=-0.20 and r.top5_share<=0.55 and r.return_without_top5>-0.05):return False
    return True


def main()->int:
    ap=argparse.ArgumentParser();ap.add_argument('--data-root',type=Path,required=True);ap.add_argument('--output',type=Path,required=True);a=ap.parse_args();a.output.mkdir(parents=True,exist_ok=True)
    paths={"BTCUSDT":a.data_root/'btc_eth/BTCUSDT_preholdout.parquet',"ETHUSDT":a.data_root/'btc_eth/ETHUSDT_preholdout.parquet',"SOLUSDT":a.data_root/'sol_xrp_flow/SOLUSDT_official_preholdout.parquet',"XRPUSDT":a.data_root/'sol_xrp_flow/XRPUSDT_official_preholdout.parquet'}
    fpaths={"BTCUSDT":a.data_root/'btc_eth/BTCUSDT_funding_preholdout.parquet',"ETHUSDT":a.data_root/'btc_eth/ETHUSDT_funding_preholdout.parquet',"SOLUSDT":a.data_root/'sol_xrp_funding/SOLUSDT_funding_preholdout.parquet',"XRPUSDT":a.data_root/'sol_xrp_funding/XRPUSDT_funding_preholdout.parquet'}
    minute={s:base.load_minute(p) for s,p in paths.items()};funding={s:base.load_funding(p) for s,p in fpaths.items()}
    clocks={};features={}
    for bpd in TARGET_BARS:
        for symbol,source in minute.items():
            key=(bpd,symbol);cache=a.output/f'bars_{symbol}_{bpd}.parquet'
            if cache.exists():bars=pd.read_parquet(cache)
            else:
                bars=build_dollar_bars(source,bpd);bars.to_parquet(cache)
            clocks[key]=bars;features[key]=prepare_clock_features(bars,bpd)
        print('clock ready',bpd,flush=True)
    candidates=candidate_grid();engine=base.EngineConfig();rows=[];event_cache={}
    periods={'dev_2022':(DEVELOPMENT_START,pd.Timestamp('2023-01-01T00:00:00Z')),'dev_2023':(pd.Timestamp('2023-01-01T00:00:00Z'),DEVELOPMENT_END)}
    for n,c in enumerate(candidates,1):
        if c.signal_key not in event_cache:
            es=[]
            for symbol in base.SYMBOLS:es.extend(generate_events(features[(c.target_bars_per_day,symbol)],c,symbol,DEVELOPMENT_START,CONFIRMATION_END))
            event_cache[c.signal_key]=sorted(es,key=lambda e:(e.entry_time,-e.score,e.symbol))
        events=[dataclasses.replace(e,candidate_id=c.candidate_id) for e in event_cache[c.signal_key]]
        rr_candidate=c
        for pname,(start,end) in periods.items():
            for cost in base.COST_PROFILES:
                t,d=base.simulate(events,rr_candidate,minute,funding,cost,start,end,engine)
                rows.append({'candidate_id':c.candidate_id,'family':c.family,'target_bars_per_day':c.target_bars_per_day,'period':pname,'cost_profile':cost.name,**base.metrics(t,d,engine.initial_equity)})
        if n%12==0:
            pd.DataFrame(rows).to_parquet(a.output/'development_screen_checkpoint.parquet',index=False)
            print('development',n,len(candidates),flush=True)
    screen=pd.DataFrame(rows);screen.to_parquet(a.output/'development_screen.parquet',index=False);rank=dev_gate(screen);rank.to_csv(a.output/'development_ranking.csv',index=False)
    survivors=rank[rank.eligible_development].head(12);cmap={c.candidate_id:c for c in candidates};selrows=[];sellogs=[]
    for cid in survivors.candidate_id:
        c=cmap[cid];events=[dataclasses.replace(e,candidate_id=cid) for e in event_cache[c.signal_key]]
        for cost in base.COST_PROFILES:
            t,d=base.simulate(events,c,minute,funding,cost,SELECTION_START,SELECTION_END,engine);selrows.append({'candidate_id':cid,'period':'oos_2024','cost_profile':cost.name,**base.metrics(t,d,engine.initial_equity)})
            if len(t):x=t.copy();x['period']='oos_2024';x['cost_profile']=cost.name;sellogs.append(x)
    selection=pd.DataFrame(selrows);selection.to_csv(a.output/'selection_2024.csv',index=False)
    selection_pass=[]
    if len(selection):
        for cid,g in selection.groupby('candidate_id'):
            if single_period_gate(g,'oos_2024'):selection_pass.append(cid)
    confrows=[];conflogs=[]
    for cid in selection_pass[:6]:
        c=cmap[cid];events=[dataclasses.replace(e,candidate_id=cid) for e in event_cache[c.signal_key]]
        for cost in base.COST_PROFILES:
            t,d=base.simulate(events,c,minute,funding,cost,CONFIRMATION_START,CONFIRMATION_END,engine);confrows.append({'candidate_id':cid,'period':'oos_2025H1','cost_profile':cost.name,**base.metrics(t,d,engine.initial_equity)})
            if len(t):x=t.copy();x['period']='oos_2025H1';x['cost_profile']=cost.name;conflogs.append(x)
    confirmation=pd.DataFrame(confrows);confirmation.to_csv(a.output/'confirmation_2025H1.csv',index=False)
    ledgers=sellogs+conflogs;pd.concat(ledgers,ignore_index=True).to_parquet(a.output/'oos_trades.parquet',index=False) if ledgers else pd.DataFrame().to_parquet(a.output/'oos_trades.parquet')
    robust=[]
    for cid in selection_pass:
        cg=confirmation[confirmation.candidate_id==cid] if len(confirmation) else pd.DataFrame()
        ok=single_period_gate(cg,'oos_2025H1') if len(cg) else False
        sel2=selection[(selection.candidate_id==cid)&(selection.cost_profile=='stress_2x')]
        con2=cg[cg.cost_profile=='stress_2x'] if len(cg) else pd.DataFrame()
        ming=min(float(sel2.geometric_daily.iloc[0]) if len(sel2) else -1,float(con2.geometric_daily.iloc[0]) if len(con2) else -1)
        robust.append({'candidate_id':cid,'robust_oos':ok,'min_oos_2x_geometric_daily':ming})
    robust=pd.DataFrame(robust);robust.to_csv(a.output/'robust_oos.csv',index=False)
    best=robust.sort_values(['robust_oos','min_oos_2x_geometric_daily'],ascending=[False,False]).iloc[0].to_dict() if len(robust) else None
    target=bool(best and best['robust_oos'] and best['min_oos_2x_geometric_daily']>=0.01)
    summary={'status':'COMPLETE','study_id':'DOLLAR_BAR_ABSORPTION_V2','candidate_count':len(candidates),'development_survivors':int(rank.eligible_development.sum()),'selection_candidates':len(survivors),'selection_survivors':len(selection_pass),'confirmation_candidates':min(len(selection_pass),6),'robust_oos_count':int(robust.robust_oos.sum()) if len(robust) else 0,'best':best,'target_passed':target,'champion_eligible':target,'terminal_holdout_opened':False,'orders_submitted':False}
    (a.output/'summary.json').write_text(json.dumps(summary,indent=2,default=str));print(json.dumps(summary,indent=2,default=str));return 0

if __name__=='__main__':raise SystemExit(main())
