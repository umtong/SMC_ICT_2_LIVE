#!/usr/bin/env python3
"""Causal killzone liquidity-raid, SMT, CISD, first-retrace ML alpha.

Design contract
---------------
* completed 5-minute information only; raw 1-minute bars are execution data;
* previous-day, completed opening-range, and completed six-hour session levels only;
* BTC/ETH relative-liquidity divergence is a context feature, never future confirmation;
* a raid must be followed by close-confirmed delivery change/displacement and the first
  causal FVG/last-opposing-candle retrace;
* fixed 500 ms activation, strict trade-through passive entry, stop-first ambiguity;
* one global pending/open slot, structural target/stop only, funding and costs included;
* H1 train/calibrate/threshold selection, frozen H2 validation, conditional 2024H1;
* ML remains mandatory: calibrated win probability plus conditional net-R regression.
"""
from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import asdict, dataclass
import hashlib
import json
from math import floor, log
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor
from sklearn.isotonic import IsotonicRegression

MAKER_FEE = 0.0002
TAKER_FEE = 0.00055
MARKET_SLIPPAGE = 0.0002
STOP_SLIPPAGE = 0.0004
MIN_SPREAD_BPS = 0.5
LATENCY_MS = 500
SYMBOLS = ("BTCUSDT", "ETHUSDT")


@dataclass(frozen=True)
class Event:
    timestamp: pd.Timestamp
    symbol: str
    side: int
    entry: float
    stop: float
    target: float
    features: Mapping[str, float]


@dataclass(frozen=True)
class Outcome:
    event: Event
    status: str
    entry_time: pd.Timestamp | None
    end_time: pd.Timestamp | None
    entry_price: float | None
    exit_price: float | None
    net_r: float | None
    funding_per_unit: float


@dataclass(frozen=True)
class Scored:
    event: Event
    score: float
    win_probability: float
    expected_net_r: float


def _read_time(frame: pd.DataFrame) -> pd.DatetimeIndex:
    if "start_time_ms" in frame.columns:
        return pd.to_datetime(frame["start_time_ms"], unit="ms", utc=True)
    if "timestamp_ms" in frame.columns:
        return pd.to_datetime(frame["timestamp_ms"], unit="ms", utc=True)
    if isinstance(frame.index, pd.DatetimeIndex):
        return pd.to_datetime(frame.index, utc=True)
    raise ValueError("no timestamp column")


def load_bars(path: Path) -> pd.DataFrame:
    frame = pd.read_parquet(path)
    for source, target in {
        "open_price": "open", "high_price": "high", "low_price": "low", "close_price": "close"
    }.items():
        if source in frame.columns and target not in frame.columns:
            frame[target] = frame[source]
    required = {"open", "high", "low", "close", "volume"}
    if not required.issubset(frame.columns):
        raise ValueError(f"bar columns missing: {sorted(required-set(frame.columns))}")
    result = frame.copy()
    result.index = _read_time(frame)
    for column in required:
        result[column] = pd.to_numeric(result[column], errors="coerce")
    if "spread_bps" in result.columns:
        result["spread_bps"] = pd.to_numeric(result["spread_bps"], errors="coerce").fillna(MIN_SPREAD_BPS)
    else:
        result["spread_bps"] = MIN_SPREAD_BPS
    return result[["open","high","low","close","volume","spread_bps"]].dropna().sort_index()


def load_optional_series(path: Path | None, names: Sequence[str]) -> pd.Series:
    if path is None or not path.exists():
        return pd.Series(dtype=float)
    frame = pd.read_parquet(path)
    column = next((name for name in names if name in frame.columns), None)
    if column is None:
        return pd.Series(dtype=float)
    result = pd.to_numeric(frame[column], errors="coerce")
    result.index = _read_time(frame)
    return result.dropna().sort_index()


def load_funding(path: Path | None) -> list[tuple[pd.Timestamp,float]]:
    values = load_optional_series(path, ("funding_rate","fundingRate"))
    return [(pd.Timestamp(t),float(v)) for t,v in values.items()]


def resample_ohlcv(one: pd.DataFrame, rule: str) -> pd.DataFrame:
    aggregated = one.resample(rule, label="right", closed="left", origin="epoch").agg(
        open=("open","first"), high=("high","max"), low=("low","min"), close=("close","last"), volume=("volume","sum")
    )
    return aggregated.dropna()


def atr(frame: pd.DataFrame, window: int=14) -> pd.Series:
    previous = frame["close"].shift(1)
    tr = pd.concat([(frame["high"]-frame["low"]),(frame["high"]-previous).abs(),(frame["low"]-previous).abs()],axis=1).max(axis=1)
    return tr.ewm(alpha=1/window,adjust=False,min_periods=window).mean()


def add_completed_period_levels(frame: pd.DataFrame) -> pd.DataFrame:
    out=frame.copy()
    day=out.index.floor("D")
    daily=pd.DataFrame({"day":day,"high":out.high,"low":out.low},index=out.index).groupby("day").agg({"high":"max","low":"min"})
    previous=daily.shift(1)
    out["previous_day_high"]=pd.Series(day,index=out.index).map(previous.high)
    out["previous_day_low"]=pd.Series(day,index=out.index).map(previous.low)
    block=out.index.floor("6h")
    blocks=pd.DataFrame({"block":block,"high":out.high,"low":out.low},index=out.index).groupby("block").agg({"high":"max","low":"min"})
    prev_blocks=blocks.shift(1)
    out["previous_block_high"]=pd.Series(block,index=out.index).map(prev_blocks.high)
    out["previous_block_low"]=pd.Series(block,index=out.index).map(prev_blocks.low)
    return out


def opening_range_levels(frame: pd.DataFrame) -> pd.DataFrame:
    out=frame.copy()
    day=out.index.floor("D")
    minute=out.index.hour*60+out.index.minute
    specs=((0,"asia"),(420,"london"),(780,"newyork"))
    for start,name in specs:
        active=(minute>=start)&(minute<start+60)
        table=pd.DataFrame({"day":day[active],"high":out.loc[active,"high"],"low":out.loc[active,"low"]}).groupby("day").agg({"high":"max","low":"min"})
        completed=minute>=start+60
        out[f"{name}_or_high"]=pd.Series(day,index=out.index).map(table.high).where(completed)
        out[f"{name}_or_low"]=pd.Series(day,index=out.index).map(table.low).where(completed)
    return out


def build_features(one: pd.DataFrame, oi: pd.Series) -> pd.DataFrame:
    five=resample_ohlcv(one,"5min")
    five=add_completed_period_levels(opening_range_levels(five))
    five["atr"]=atr(five)
    body=five.close-five.open
    five["body_atr"]=body/five.atr
    five["close_location"]=(five.close-five.low)/(five.high-five.low).replace(0,np.nan)
    five["volume_z"]=(five.volume-five.volume.rolling(48,min_periods=24).mean())/five.volume.rolling(48,min_periods=24).std(ddof=0).replace(0,np.nan)
    five["compression"]=(five.high.rolling(24,min_periods=12).max()-five.low.rolling(24,min_periods=12).min())/(five.atr*6)
    hour=resample_ohlcv(one,"1h")
    hour["ema20"]=hour.close.ewm(span=20,adjust=False,min_periods=20).mean()
    hour["ema50"]=hour.close.ewm(span=50,adjust=False,min_periods=50).mean()
    hour["bias"]=np.sign(hour.ema20-hour.ema50)
    five["htf_bias"]=hour.bias.reindex(five.index,method="ffill")
    if not oi.empty:
        aligned=oi.reindex(five.index,method="ffill")
        five["oi_change_1h"]=np.log(aligned.replace(0,np.nan)).diff(12)
    else:
        five["oi_change_1h"]=np.nan
    five["hour_sin"]=np.sin(2*np.pi*five.index.hour/24)
    five["hour_cos"]=np.cos(2*np.pi*five.index.hour/24)
    return five


def external_levels(row: pd.Series, side: int) -> list[float]:
    suffix="low" if side>0 else "high"
    names=[f"previous_day_{suffix}",f"previous_block_{suffix}",f"asia_or_{suffix}",f"london_or_{suffix}",f"newyork_or_{suffix}"]
    return [float(row[name]) for name in names if name in row and pd.notna(row[name])]


def opposing_levels(row: pd.Series, side: int, entry: float) -> list[float]:
    suffix="high" if side>0 else "low"
    names=[f"previous_day_{suffix}",f"previous_block_{suffix}",f"asia_or_{suffix}",f"london_or_{suffix}",f"newyork_or_{suffix}"]
    values=[float(row[name]) for name in names if name in row and pd.notna(row[name])]
    return sorted([v for v in values if (v>entry if side>0 else v<entry)],reverse=side<0)


def smt_feature(frames: Mapping[str,pd.DataFrame]) -> dict[str,pd.Series]:
    common=frames["BTCUSDT"].index.intersection(frames["ETHUSDT"].index)
    result={}
    for symbol,other in (("BTCUSDT","ETHUSDT"),("ETHUSDT","BTCUSDT")):
        own=frames[symbol].reindex(common); peer=frames[other].reindex(common)
        own_low=(own.low<own.previous_block_low)&(own.close>own.previous_block_low)
        peer_low=(peer.low<peer.previous_block_low)&(peer.close>peer.previous_block_low)
        own_high=(own.high>own.previous_block_high)&(own.close<own.previous_block_high)
        peer_high=(peer.high>peer.previous_block_high)&(peer.close<peer.previous_block_high)
        values=(own_low&~peer_low).astype(float)-(own_high&~peer_high).astype(float)
        result[symbol]=values.reindex(frames[symbol].index).fillna(0.0)
    return result


def generate_events(frames: Mapping[str,pd.DataFrame]) -> list[Event]:
    smt=smt_feature(frames)
    events=[]
    for symbol,frame in frames.items():
        state: dict[int,dict[str,Any]|None]={1:None,-1:None}
        for i in range(2,len(frame)):
            row=frame.iloc[i]; timestamp=pd.Timestamp(frame.index[i]); a=float(row.atr) if pd.notna(row.atr) else np.nan
            if not np.isfinite(a) or a<=0: continue
            for side in (1,-1):
                current=state[side]
                if current is not None and i-current["armed_i"]>16: state[side]=None; current=None
                levels=external_levels(row,side)
                if current is None and levels:
                    if side>0:
                        swept=[v for v in levels if row.low<v-0.04*a and row.close>v]
                    else:
                        swept=[v for v in levels if row.high>v+0.04*a and row.close<v]
                    if swept:
                        level=min(swept) if side>0 else max(swept)
                        state[side]={"stage":"RAID","armed_i":i,"extreme":float(row.low if side>0 else row.high),"level":level,"sweep_depth":abs(float((row.low if side>0 else row.high)-level))/a,"raid_open":float(row.open)}
                        current=state[side]
                if current is None: continue
                if current["stage"]=="RAID":
                    displacement=(row.body_atr>=0.45 and row.close_location>=0.7) if side>0 else (row.body_atr<=-0.45 and row.close_location<=0.3)
                    cisd=(row.close>current["raid_open"]) if side>0 else (row.close<current["raid_open"])
                    if displacement and cisd:
                        prior=frame.iloc[i-2:i+1]
                        if side>0 and float(row.low)>float(frame.iloc[i-2].high):
                            lower=float(frame.iloc[i-2].high); upper=float(row.low); kind=1.0
                        elif side<0 and float(row.high)<float(frame.iloc[i-2].low):
                            lower=float(row.high); upper=float(frame.iloc[i-2].low); kind=1.0
                        else:
                            opposing=frame.iloc[max(0,i-6):i+1]
                            subset=opposing[opposing.close<opposing.open] if side>0 else opposing[opposing.close>opposing.open]
                            source=subset.iloc[-1] if not subset.empty else frame.iloc[i-1]
                            lower=float(min(source.open,source.close)); upper=float(max(source.open,source.close)); kind=2.0
                        current.update({"stage":"CONFIRMED","confirm_i":i,"zone_low":lower,"zone_high":upper,"zone_mid":0.5*(lower+upper),"confirm_body":abs(float(row.body_atr)),"zone_kind":kind})
                elif current["stage"]=="CONFIRMED":
                    if i==current["confirm_i"]: continue
                    if i-current["confirm_i"]>12: state[side]=None; continue
                    zone=float(current["zone_mid"])
                    touch=(row.low<zone and row.close>zone) if side>0 else (row.high>zone and row.close<zone)
                    invalid=(row.low<=current["extreme"]) if side>0 else (row.high>=current["extreme"])
                    if invalid: state[side]=None; continue
                    if touch:
                        stop=float(current["extreme"]-0.08*a if side>0 else current["extreme"]+0.08*a)
                        distance=abs(zone-stop)
                        targets=opposing_levels(row,side,zone)
                        structural=targets[0] if targets else zone+side*4*distance
                        target=structural if abs(structural-zone)/distance>=2.0 else zone+side*4*distance
                        rr=abs(target-zone)/distance
                        if distance>0 and rr>=2.0:
                            session=0 if timestamp.hour<7 else (1 if timestamp.hour<13 else 2)
                            features={
                                "side":float(side),"symbol_btc":float(symbol=="BTCUSDT"),"sweep_depth_atr":float(current["sweep_depth"]),
                                "smt_divergence":float(side*smt[symbol].iloc[i]),"htf_alignment":float(side*row.htf_bias),"body_atr":float(current["confirm_body"]),
                                "zone_kind":float(current["zone_kind"]),"retrace_bars":float(i-current["confirm_i"]),"raw_rr":float(rr),
                                "volume_z":float(row.volume_z) if pd.notna(row.volume_z) else 0.0,"compression":float(row.compression) if pd.notna(row.compression) else 0.0,
                                "oi_change_1h":float(row.oi_change_1h) if pd.notna(row.oi_change_1h) else 0.0,"session":float(session),
                                "hour_sin":float(row.hour_sin),"hour_cos":float(row.hour_cos),
                            }
                            events.append(Event(timestamp,symbol,side,zone,stop,float(target),features))
                        state[side]=None
    return sorted(events,key=lambda e:(e.timestamp,e.symbol,e.side))


def market_spread(row: pd.Series) -> float:
    return max(float(row.get("spread_bps",MIN_SPREAD_BPS)),MIN_SPREAD_BPS)/10000


def mark_asof(series: pd.Series,timestamp:pd.Timestamp,default:float)->float:
    if series.empty:return default
    pos=int(np.searchsorted(series.index.as_unit("ns").asi8,timestamp.value,side="right"))-1
    if pos<0:return default
    return float(series.iloc[min(pos,len(series)-1)])


def label_event(event:Event,bars:pd.DataFrame,marks:pd.Series,funding:Sequence[tuple[pd.Timestamp,float]],period_end:pd.Timestamp)->Outcome:
    times=bars.index.as_unit("ns").asi8; activation=event.timestamp+pd.Timedelta(milliseconds=LATENCY_MS)
    start=int(np.searchsorted(times,activation.value,side="right")); end=min(len(bars),int(np.searchsorted(times,period_end.value,side="left")))
    if start>=end:return Outcome(event,"NO_EXECUTION_BAR",None,None,None,None,None,0.0)
    entry_position=None
    for i in range(start,end):
        row=bars.iloc[i]
        invalid=float(row.low)<=event.stop if event.side>0 else float(row.high)>=event.stop
        passed=float(row.high)>=event.target if event.side>0 else float(row.low)<=event.target
        crossed=float(row.low)<event.entry if event.side>0 else float(row.high)>event.entry
        if invalid or passed:return Outcome(event,"CANCELLED_BEFORE_FILL",None,pd.Timestamp(bars.index[i]),None,None,0.0,0.0)
        if crossed:entry_position=i;break
    if entry_position is None:return Outcome(event,"UNFILLED",None,period_end,None,None,0.0,0.0)
    entry_time=pd.Timestamp(bars.index[entry_position]); entry_price=event.entry; stop_distance=abs(entry_price-event.stop)
    for i in range(entry_position,end):
        row=bars.iloc[i]; stop_hit=float(row.low)<=event.stop if event.side>0 else float(row.high)>=event.stop; target_hit=float(row.high)>=event.target if event.side>0 else float(row.low)<=event.target
        if not(stop_hit or target_hit):continue
        timestamp=pd.Timestamp(bars.index[i]); fund=sum(-event.side*mark_asof(marks,t,entry_price)*r for t,r in funding if entry_time<=t<timestamp)
        if stop_hit:
            exit_price=event.stop*(1-STOP_SLIPPAGE if event.side>0 else 1+STOP_SLIPPAGE); fee=entry_price*MAKER_FEE+exit_price*TAKER_FEE; gross=event.side*(exit_price-entry_price); status="STOP"
        else:
            exit_price=event.target; fee=entry_price*MAKER_FEE+exit_price*MAKER_FEE; gross=event.side*(exit_price-entry_price); status="TARGET"
        return Outcome(event,status,entry_time,timestamp,entry_price,exit_price,(gross-fee+fund)/stop_distance,fund)
    return Outcome(event,"CENSORED",entry_time,None,entry_price,None,None,0.0)


def label_events(events:Sequence[Event],bars:Mapping[str,pd.DataFrame],marks:Mapping[str,pd.Series],funding:Mapping[str,Sequence[tuple[pd.Timestamp,float]]],end:pd.Timestamp)->pd.DataFrame:
    rows=[]
    for event in events:
        outcome=label_event(event,bars[event.symbol],marks[event.symbol],funding[event.symbol],end)
        if outcome.net_r is None:continue
        row={"event_start":event.timestamp,"event_end":outcome.end_time,"symbol":event.symbol,"side":event.side,"net_r":outcome.net_r,"win":int(outcome.net_r>0)};row.update(event.features);rows.append(row)
    return pd.DataFrame(rows).sort_values(["event_end","event_start"]).reset_index(drop=True) if rows else pd.DataFrame()


def feature_names(rows:pd.DataFrame)->list[str]:
    excluded={"event_start","event_end","symbol","net_r","win"}
    return [c for c in rows.columns if c not in excluded and pd.api.types.is_numeric_dtype(rows[c])]


def fit_model(train:pd.DataFrame,calibration:pd.DataFrame)->tuple[Any,Any,Any,list[str]]:
    features=feature_names(train); x=train[features].replace([np.inf,-np.inf],np.nan); xc=calibration[features].replace([np.inf,-np.inf],np.nan)
    classifier=HistGradientBoostingClassifier(max_leaf_nodes=15,min_samples_leaf=20,max_iter=250,learning_rate=0.05,l2_regularization=2.0,random_state=20260727).fit(x,train.win)
    regressor=HistGradientBoostingRegressor(max_leaf_nodes=15,min_samples_leaf=20,max_iter=250,learning_rate=0.05,l2_regularization=2.0,random_state=20260727).fit(x,train.net_r)
    raw=classifier.predict_proba(xc)[:,list(classifier.classes_).index(1)] if 1 in classifier.classes_ else np.zeros(len(xc)); calibrator=IsotonicRegression(out_of_bounds="clip").fit(raw,calibration.win)
    return classifier,regressor,calibrator,features


def score_rows(rows:pd.DataFrame,model:tuple[Any,Any,Any,list[str]])->pd.DataFrame:
    classifier,regressor,calibrator,features=model;x=rows[features].replace([np.inf,-np.inf],np.nan);raw=classifier.predict_proba(x)[:,list(classifier.classes_).index(1)] if 1 in classifier.classes_ else np.zeros(len(x));p=calibrator.predict(raw);r=regressor.predict(x);out=rows.copy();out["p"]=p;out["expected_r"]=r;out["score"]=0.5*r+0.5*(p*pd.to_numeric(out.raw_rr)-1);return out


def replay(scored:pd.DataFrame,events:Mapping[tuple[Any,...],Event],outcomes:Mapping[tuple[Any,...],Outcome],start:pd.Timestamp,end:pd.Timestamp,threshold:float,risk:float,leverage:float)->dict[str,Any]:
    selected=scored[(scored.event_start>=start)&(scored.event_start<end)&(scored.score>=threshold)].copy();selected=selected.sort_values(["event_start","score"],ascending=[True,False]);nav=10000.0;peak=nav;mdd=0.0;release=start;trades=[]
    for timestamp,group in selected.groupby("event_start",sort=True):
        if timestamp<release:continue
        row=group.iloc[0];key=(pd.Timestamp(row.event_start),str(row.symbol),int(row.side));outcome=outcomes.get(key)
        if outcome is None or outcome.entry_time is None or outcome.end_time is None or outcome.net_r is None:continue
        event=events[key];per_unit=abs(event.entry-event.stop)+event.entry*MAKER_FEE+event.stop*(TAKER_FEE+STOP_SLIPPAGE);qty=min(nav*risk/per_unit,nav*leverage/event.entry);step=0.001 if event.symbol=="BTCUSDT" else 0.01;qty=floor(qty/step)*step;pnl=qty*per_unit*outcome.net_r;entry_nav=nav;nav+=pnl;release=outcome.end_time;peak=max(peak,nav);mdd=max(mdd,1-nav/max(peak,1e-12));trades.append({"timestamp":timestamp.isoformat(),"symbol":event.symbol,"side":event.side,"score":float(row.score),"net_r":outcome.net_r,"pnl":pnl,"entry_nav":entry_nav,"nav_after":nav,"end_time":outcome.end_time.isoformat()})
        if nav<=0:break
    days=max(1,int((end-start).total_seconds()//86400));multiple=nav/10000;values=np.array([t["pnl"] for t in trades]);return {"start_nav":10000.0,"end_nav":nav,"account_multiple":multiple,"geometric_daily_growth":multiple**(1/days)-1 if multiple>0 else -1.0,"maximum_drawdown":mdd,"completed_trades":len(trades),"win_rate":float((values>0).mean()) if len(values) else None,"trades":trades}


def candidate_key(event:Event)->tuple[Any,...]:return (event.timestamp,event.symbol,event.side)


def run(args:argparse.Namespace)->dict[str,Any]:
    bars23={s:load_bars(getattr(args,f"{s.lower()}_2023_bars")) for s in SYMBOLS};bars24={s:load_bars(getattr(args,f"{s.lower()}_2024h1_bars")) for s in SYMBOLS}
    oi23={s:load_optional_series(getattr(args,f"{s.lower()}_2023_oi"),("open_interest","openInterest")) for s in SYMBOLS};oi24={s:load_optional_series(getattr(args,f"{s.lower()}_2024h1_oi"),("open_interest","openInterest")) for s in SYMBOLS}
    marks23={s:load_optional_series(getattr(args,f"{s.lower()}_2023_marks"),("close","close_price","mark_price")) for s in SYMBOLS};marks24={s:load_optional_series(getattr(args,f"{s.lower()}_2024h1_marks"),("close","close_price","mark_price")) for s in SYMBOLS}
    funding23={s:load_funding(getattr(args,f"{s.lower()}_2023_funding")) for s in SYMBOLS};funding24={s:load_funding(getattr(args,f"{s.lower()}_2024h1_funding")) for s in SYMBOLS}
    features23={s:build_features(bars23[s],oi23[s]) for s in SYMBOLS};events23=generate_events(features23);labels23=label_events(events23,bars23,marks23,funding23,pd.Timestamp("2024-01-01T00:00:00Z"))
    if len(labels23)<100:raise RuntimeError(f"insufficient labelled events: {len(labels23)}")
    train=labels23[labels23.event_start<pd.Timestamp("2023-05-01T00:00:00Z")];cal=labels23[(labels23.event_start>=pd.Timestamp("2023-05-01T00:00:00Z"))&(labels23.event_start<pd.Timestamp("2023-07-01T00:00:00Z"))];h2=labels23[labels23.event_start>=pd.Timestamp("2023-07-01T00:00:00Z")]
    if min(len(train),len(cal),len(h2))<20:raise RuntimeError("insufficient chronological split")
    model=fit_model(train,cal);cal_scored=score_rows(cal,model);h2_scored=score_rows(h2,model)
    event_map23={candidate_key(e):e for e in events23};outcome_map23={candidate_key(e):label_event(e,bars23[e.symbol],marks23[e.symbol],funding23[e.symbol],pd.Timestamp("2024-01-01T00:00:00Z")) for e in events23}
    thresholds=sorted(set(float(cal_scored.score.quantile(q)) for q in (0.5,0.6,0.7,0.8,0.85,0.9,0.93,0.95)))
    calibration_results=[]
    for threshold in thresholds:
        metrics=replay(cal_scored,event_map23,outcome_map23,pd.Timestamp("2023-05-01T00:00:00Z"),pd.Timestamp("2023-07-01T00:00:00Z"),threshold,0.01,5.0);calibration_results.append({"threshold":threshold,"metrics":metrics})
    eligible=[r for r in calibration_results if r["metrics"]["completed_trades"]>=5];selected=max(eligible,key=lambda r:(r["metrics"]["geometric_daily_growth"],r["metrics"]["completed_trades"]))
    threshold=selected["threshold"];h2_basic=replay(h2_scored,event_map23,outcome_map23,pd.Timestamp("2023-07-01T00:00:00Z"),pd.Timestamp("2024-01-01T00:00:00Z"),threshold,0.01,5.0)
    risk_results=[]
    for risk in (0.01,0.02,0.04,0.08,0.12,0.17,0.25):risk_results.append({"risk":risk,"metrics":replay(h2_scored,event_map23,outcome_map23,pd.Timestamp("2023-07-01T00:00:00Z"),pd.Timestamp("2024-01-01T00:00:00Z"),threshold,risk,20.0)})
    risk_selected=max([r for r in risk_results if r["metrics"]["account_multiple"]>0],key=lambda r:r["metrics"]["geometric_daily_growth"])
    official=None
    if h2_basic["geometric_daily_growth"]>0 and h2_basic["completed_trades"]>=8:
        final_model=fit_model(labels23[labels23.event_start<pd.Timestamp("2023-10-01T00:00:00Z")],labels23[labels23.event_start>=pd.Timestamp("2023-10-01T00:00:00Z")])
        features24={s:build_features(bars24[s],oi24[s]) for s in SYMBOLS};events24=generate_events(features24);labels24=label_events(events24,bars24,marks24,funding24,pd.Timestamp("2024-07-01T00:00:00Z"));scored24=score_rows(labels24,final_model);event_map24={candidate_key(e):e for e in events24};outcome_map24={candidate_key(e):label_event(e,bars24[e.symbol],marks24[e.symbol],funding24[e.symbol],pd.Timestamp("2024-07-01T00:00:00Z")) for e in events24};official=replay(scored24,event_map24,outcome_map24,pd.Timestamp("2024-01-01T00:00:00Z"),pd.Timestamp("2024-07-01T00:00:00Z"),threshold,float(risk_selected["risk"]),20.0)
    result={"schema_version":1,"stage":"KILLZONE_SMT_CISD_FIRST_RETRACE_H1_SELECTION_H2_VALIDATION_CONDITIONAL_2024H1","event_count_2023":len(events23),"label_count_2023":len(labels23),"split_counts":{"train":len(train),"calibration":len(cal),"h2":len(h2)},"calibration_results":calibration_results,"selected_threshold":threshold,"h2_basic":h2_basic,"risk_results":risk_results,"selected_risk":risk_selected,"official_2024h1":official,"ranking_effect":"NONE_PROVISIONAL_1M_NOT_EVENT_TAPE_VALIDATED"}
    args.output.mkdir(parents=True,exist_ok=True);path=args.output/"KILLZONE_SMT_CISD_RESULT.json";path.write_text(json.dumps(result,ensure_ascii=False,indent=2,sort_keys=True,default=str)+'\n');(args.output/"KILLZONE_SMT_CISD_RESULT.sha256").write_text(f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}\n");return result


def main(argv:Sequence[str]|None=None)->int:
    p=argparse.ArgumentParser();p.add_argument("--output",type=Path,required=True)
    for symbol in ("btcusdt","ethusdt"):
        for period in ("2023","2024h1"):
            p.add_argument(f"--{symbol}-{period}-bars",dest=f"{symbol}_{period}_bars",type=Path,required=True);p.add_argument(f"--{symbol}-{period}-marks",dest=f"{symbol}_{period}_marks",type=Path,required=True);p.add_argument(f"--{symbol}-{period}-oi",dest=f"{symbol}_{period}_oi",type=Path,required=True);p.add_argument(f"--{symbol}-{period}-funding",dest=f"{symbol}_{period}_funding",type=Path,required=True)
    result=run(p.parse_args(argv));print(json.dumps({"h2_basic":result["h2_basic"],"selected_risk":result["selected_risk"],"official_2024h1":result["official_2024h1"]},indent=2,default=str));return 0
if __name__=="__main__":raise SystemExit(main())
