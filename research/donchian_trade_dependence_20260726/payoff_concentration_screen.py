from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
import json, math, os
import numpy as np
import pandas as pd
try:
    from .donchian_dependence_screen import SYMBOLS,Spec,Event,load_snapshot,aggregate,theoretical_events,events_for_mode
except ImportError:
    from donchian_dependence_screen import SYMBOLS,Spec,Event,load_snapshot,aggregate,theoretical_events,events_for_mode

@dataclass
class Leg:
    idx:int;time_ms:int;fraction:float;price:float;reason:str
@dataclass
class Payoff:
    base:Event;variant:str;legs:list[Leg]
    @property
    def symbol(self):return self.base.symbol
    @property
    def entry_idx(self):return self.base.entry_idx
    @property
    def entry_time_ms(self):return self.base.entry_time_ms
    @property
    def entry_price(self):return self.base.entry_price
    @property
    def side(self):return self.base.side
    @property
    def stop_price(self):return self.base.stop_price
    @property
    def score(self):return self.base.score
    @property
    def final_leg(self):return self.legs[-1]

def make_payoff(d,e:Event,variant):
    if variant=="full_channel":return Payoff(e,variant,[Leg(e.exit_idx,e.exit_time_ms,1.,e.exit_price,e.exit_reason)])
    settings={"full_1R":(1.,1.,False),"full_2R":(2.,1.,False),"half_1R":(1.,.5,False),"half_2R":(2.,.5,False),"half_1R_BE":(1.,.5,True),"BE_after_1R":(1.,0.,True)}
    if variant not in settings:raise ValueError(variant)
    target_r,take,move_be=settings[variant];risk=abs(e.entry_price-e.stop_price);target=e.entry_price+e.side*target_r*risk
    legs=[];active=1.;triggered=False;be=False
    for j in range(e.entry_idx,e.exit_idx+1):
        o,h,l=map(float,(d["open"][j],d["high"][j],d["low"][j]));stop=e.entry_price if be else e.stop_price
        if e.side>0:
            if o<=stop:return Payoff(e,variant,legs+[Leg(j,int(d["open_time_ms"][j]),active,o,"gap_be" if be else "gap_stop")])
            if l<=stop:return Payoff(e,variant,legs+[Leg(j,int(d["open_time_ms"][j]),active,float(stop),"be_stop" if be else "stop")])
        else:
            if o>=stop:return Payoff(e,variant,legs+[Leg(j,int(d["open_time_ms"][j]),active,o,"gap_be" if be else "gap_stop")])
            if h>=stop:return Payoff(e,variant,legs+[Leg(j,int(d["open_time_ms"][j]),active,float(stop),"be_stop" if be else "stop")])
        if j==e.exit_idx:return Payoff(e,variant,legs+[Leg(j,e.exit_time_ms,active,e.exit_price,e.exit_reason)])
        if not triggered and ((h>=target) if e.side>0 else (l<=target)):
            triggered=True
            if take>0:
                f=min(active,take);legs.append(Leg(j,int(d["open_time_ms"][j]),f,float(target),f"target_{target_r:g}R"));active-=f
                if active<=1e-12:return Payoff(e,variant,legs)
            if move_be:
                be=True;cross=(l<=e.entry_price) if e.side>0 else (h>=e.entry_price)
                if cross and active>0:return Payoff(e,variant,legs+[Leg(j,int(d["open_time_ms"][j]),active,e.entry_price,"same_bar_be")])
    if active>0:legs.append(Leg(e.exit_idx,e.exit_time_ms,active,e.exit_price,e.exit_reason))
    return Payoff(e,variant,legs)

def simulate(data,events,start,end,bps,risk=.005,max_lev=5.,initial=10_000.):
    evs=sorted((e for e in events if start<=e.entry_time_ms<end),key=lambda e:(e.entry_time_ms,-e.score,e.symbol,e.variant));fee=bps/20_000.;nav=initial;free=start;trades=[];points=[(start,nav)];i=0
    while i<len(evs):
        t=evs[i].entry_time_ms;group=[]
        while i<len(evs) and evs[i].entry_time_ms==t:group.append(evs[i]);i+=1
        if t<free:continue
        e=max(group,key=lambda x:(x.score,x.symbol));unit=abs(e.entry_price-e.stop_price)+fee*(e.entry_price+e.stop_price)
        if unit<=0 or not np.isfinite(unit):continue
        qty=min(nav*risk/unit,nav*max_lev/e.entry_price)
        if qty<=0:continue
        before=nav;after=nav-qty*e.entry_price*fee;active=1.;realized=0.;by={};d=data[e.symbol]
        for leg in e.legs:by.setdefault(leg.idx,[]).append(leg)
        for j in range(e.entry_idx,e.final_leg.idx+1):
            for leg in by.get(j,[]):realized+=e.side*qty*leg.fraction*(leg.price-e.entry_price)-qty*leg.fraction*leg.price*fee;active-=leg.fraction
            px=float(d["close"][j]);points.append((int(d["open_time_ms"][j]),after+realized+e.side*qty*active*(px-e.entry_price)-qty*active*px*fee))
        nav=after+sum(e.side*qty*l.fraction*(l.price-e.entry_price)-qty*l.fraction*l.price*fee for l in e.legs);trades.append({"symbol":e.symbol,"account_return":nav/before-1,"net_pnl":nav-before});points.append((e.final_leg.time_ms,nav));free=e.final_leg.time_ms+3_600_000
        if nav<=0:break
    days=max(1,(end-start)//86_400_000);gdg=(nav/initial)**(1/days)-1 if nav>0 else -1;r=np.array([x["account_return"] for x in trades]);p=np.array([x["net_pnl"] for x in trades]);pos=p[p>0];neg=p[p<0]
    pf=float(pos.sum()/-neg.sum()) if len(pos) and len(neg) else (float("inf") if len(pos) else 0.);points.sort();ts=np.array([x[0] for x in points]);v=np.array([x[1] for x in points]);mdd=float(np.max(1-v/np.maximum.accumulate(v)))
    if len(r):
        k=max(1,math.ceil(len(r)*.10));w=[q for q in np.argsort(r)[::-1] if r[q]>0][:k];keep=np.ones(len(r),bool);keep[w]=False;removed=float(np.prod(1+r[keep])-1);top5=float(np.sort(pos)[-5:].sum()/pos.sum()) if len(pos) else 1.
    else:removed=0.;top5=1.
    july=int(pd.Timestamp("2023-07-01",tz="UTC").value//1_000_000);q=max(0,int(np.searchsorted(ts,july,side="right")-1));mid=float(v[q])
    return {"total_return":nav/initial-1,"geometric_daily_growth":gdg,"maximum_drawdown":mdd,"trade_count":len(trades),"profit_factor":pf,"median_account_return_bps":float(np.median(r)*10_000) if len(r) else np.nan,"win_rate":float(np.mean(r>0)) if len(r) else np.nan,"top5_positive_share":top5,"top10pct_removed_return":removed,"h1_return":mid/initial-1,"h2_return":nav/mid-1}

def main():
    snap=Path(os.environ.get("DONCHIAN_SNAPSHOT","snapshot"));out=Path(os.environ.get("DONCHIAN_PAYOFF_OUTPUT","payoff_results"));out.mkdir(parents=True,exist_ok=True);raw=load_snapshot(snap);data={s:aggregate(raw[s],60) for s in SYMBOLS};start=int(pd.Timestamp("2023-01-01",tz="UTC").value//1_000_000);end=int(pd.Timestamp("2024-01-01",tz="UTC").value//1_000_000)
    specs=[Spec(60,48,12),Spec(60,48,24),Spec(60,96,24),Spec(60,96,48)];modes=("after_loser","turtle_failsafe");variants=("full_channel","full_1R","full_2R","half_1R","half_2R","half_1R_BE","BE_after_1R");rows=[]
    for spec in specs:
        by={s:theoretical_events(data[s],s,spec) for s in SYMBOLS};all_events=[e for s in SYMBOLS for e in by[s]]
        for mode in modes:
            eligible=events_for_mode(all_events,mode)
            for variant in variants:
                row={"spec_id":spec.id,"entry_lb":spec.entry_lb,"exit_lb":spec.exit_lb,"mode":mode,"variant":variant};pe=[make_payoff(data[e.symbol],e,variant) for e in eligible]
                for b in (12.,18.,24.):
                    for k,v in simulate(data,pe,start,end,b).items():row[f"{int(b)}bps_{k}"]=v
                rows.append(row)
    df=pd.DataFrame(rows);df["pass"]=(df["24bps_geometric_daily_growth"]>0)&(df["24bps_trade_count"]>=100)&(df["24bps_top10pct_removed_return"]>0)&(df["24bps_h1_return"]>0)&(df["24bps_h2_return"]>0);df.to_csv(out/"payoff_screen.csv",index=False)
    ranked=df.sort_values(["pass","24bps_geometric_daily_growth","24bps_top10pct_removed_return"],ascending=[False,False,False]);summary={"candidate_count":len(df),"pass_count":int(df["pass"].sum()),"best":ranked.iloc[0].replace({np.nan:None}).to_dict()};(out/"summary.json").write_text(json.dumps(summary,indent=2,sort_keys=True,default=str))
if __name__=="__main__":main()
