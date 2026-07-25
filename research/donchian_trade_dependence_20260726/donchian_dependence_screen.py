from __future__ import annotations
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional
import hashlib, json, math, os
import numpy as np
import pandas as pd

SYMBOLS=("BTCUSDT","ETHUSDT","SOLUSDT","XRPUSDT")
BAR5_MS=300_000

@dataclass(frozen=True)
class Spec:
    timeframe_min:int
    entry_lb:int
    exit_lb:int
    stop_atr:float=2.0
    atr_lb:int=20
    failsafe_mult:float=2.5
    @property
    def failsafe_lb(self)->int:return int(round(self.entry_lb*self.failsafe_mult))
    @property
    def id(self)->str:
        b=json.dumps(asdict(self),sort_keys=True,separators=(",",":")).encode()
        return hashlib.sha256(b).hexdigest()[:20]

@dataclass
class Event:
    symbol:str; entry_idx:int; entry_time_ms:int; entry_price:float; side:int
    stop_price:float; exit_idx:int; exit_time_ms:int; exit_price:float
    exit_reason:str; gross_return:float; score:float; prev_outcome:Optional[int]
    event_type:str; signal_idx:int; theoretical_trade_no:int

def load_snapshot(path:Path):
    out={}
    for s in SYMBOLS:
        with np.load(path/f"{s}_5m.npz") as z:d={k:z[k].copy() for k in z.files}
        if not np.all(np.diff(d["open_time_ms"])==BAR5_MS):raise ValueError(f"clock gap {s}")
        out[s]=d
    return out

def aggregate(d,minutes:int):
    f=minutes//5
    if f<1 or minutes%5:raise ValueError(minutes)
    n=len(d["open_time_ms"]);n-=n%f
    out={"open_time_ms":d["open_time_ms"][:n:f].copy(),"open":d["open"][:n].reshape(-1,f)[:,0].copy(),"high":d["high"][:n].reshape(-1,f).max(1),"low":d["low"][:n].reshape(-1,f).min(1),"close":d["close"][:n].reshape(-1,f)[:,-1].copy(),"quote_volume":d["quote_volume"][:n].reshape(-1,f).sum(1)}
    if not np.all(np.diff(out["open_time_ms"])==minutes*60_000):raise ValueError("aggregate gap")
    return out

def prior_extreme(x,lb,mode):
    r=pd.Series(x).shift(1).rolling(lb,min_periods=lb)
    return (r.max() if mode=="max" else r.min()).to_numpy(float)

def atr(d,lb):
    pc=np.r_[np.nan,d["close"][:-1]]
    tr=np.maximum(d["high"]-d["low"],np.maximum(abs(d["high"]-pc),abs(d["low"]-pc)))
    return pd.Series(tr).rolling(lb,min_periods=lb).mean().to_numpy(float)

def exit_path(d,entry_idx,entry_price,side,stop,exit_low,exit_high,end_idx=None):
    last=len(d["open_time_ms"])-1 if end_idx is None else min(end_idx,len(d["open_time_ms"])-1)
    for j in range(entry_idx,last+1):
        o,h,l,c=map(float,(d["open"][j],d["high"][j],d["low"][j],d["close"][j]))
        if side>0:
            if o<=stop:return j,int(d["open_time_ms"][j]),o,"gap_stop"
            if l<=stop:return j,int(d["open_time_ms"][j]),float(stop),"stop"
            hit=np.isfinite(exit_low[j]) and c<exit_low[j]
        else:
            if o>=stop:return j,int(d["open_time_ms"][j]),o,"gap_stop"
            if h>=stop:return j,int(d["open_time_ms"][j]),float(stop),"stop"
            hit=np.isfinite(exit_high[j]) and c>exit_high[j]
        if hit:
            if j+1<=last:return j+1,int(d["open_time_ms"][j+1]),float(d["open"][j+1]),"channel_exit"
            return j,int(d["open_time_ms"][j]),c,"evaluation_mtm"
    return last,int(d["open_time_ms"][last]),float(d["close"][last]),"evaluation_mtm"

def theoretical_events(d,symbol,spec:Spec):
    a=atr(d,spec.atr_lb);eh=prior_extreme(d["high"],spec.entry_lb,"max");el=prior_extreme(d["low"],spec.entry_lb,"min")
    fh=prior_extreme(d["high"],spec.failsafe_lb,"max");fl=prior_extreme(d["low"],spec.failsafe_lb,"min")
    xl=prior_extreme(d["low"],spec.exit_lb,"min");xh=prior_extreme(d["high"],spec.exit_lb,"max")
    out=[];prev=None;no=0;i=max(spec.entry_lb,spec.atr_lb);n=len(d["close"])
    while i<n-1:
        c=float(d["close"][i]);long=np.isfinite(eh[i]) and c>eh[i];short=np.isfinite(el[i]) and c<el[i]
        if long==short:i+=1;continue
        side=1 if long else -1;ei=i+1;ep=float(d["open"][ei]);av=float(a[i])
        if not np.isfinite(av) or av<=0:i+=1;continue
        stop=ep-side*spec.stop_atr*av;xi,xt,xp,reason=exit_path(d,ei,ep,side,stop,xl,xh)
        gross=side*(xp/ep-1);level=eh[i] if side>0 else el[i];score=abs(c-level)/av;no+=1
        out.append(Event(symbol,ei,int(d["open_time_ms"][ei]),ep,side,float(stop),xi,xt,xp,reason,float(gross),float(score),prev,"base",i,no))
        if prev==1:
            for k in range(i+1,min(xi,n-2)+1):
                ck=float(d["close"][k]);hit=(np.isfinite(fh[k]) and ck>fh[k]) if side>0 else (np.isfinite(fl[k]) and ck<fl[k])
                if not hit:continue
                fe=k+1;fp=float(d["open"][fe]);ak=float(a[k])
                if not np.isfinite(ak) or ak<=0:continue
                fs=fp-side*spec.stop_atr*ak;fi,ft,fx,fr=exit_path(d,fe,fp,side,fs,xl,xh);lev=fh[k] if side>0 else fl[k]
                out.append(Event(symbol,fe,int(d["open_time_ms"][fe]),fp,side,float(fs),fi,ft,fx,fr,float(side*(fx/fp-1)),float(abs(ck-lev)/ak),prev,"failsafe",k,no));break
        if reason=="evaluation_mtm":break
        prev=1 if gross>0 else -1;i=max(i+1,xi+1)
    return out

def events_for_mode(events,mode):
    base=[e for e in events if e.event_type=="base"]
    if mode=="all":return base
    if mode=="after_loser":return [e for e in base if e.prev_outcome in (None,-1)]
    if mode=="after_winner":return [e for e in base if e.prev_outcome==1]
    if mode=="turtle_failsafe":return [e for e in events if (e.event_type=="base" and e.prev_outcome in (None,-1)) or e.event_type=="failsafe"]
    raise ValueError(mode)

def runs_z(signs):
    a=np.asarray(signs,int);a=a[np.isin(a,(-1,1))];n=len(a)
    if n<3:return float("nan")
    n1=int((a>0).sum());n2=int((a<0).sum())
    if not n1 or not n2:return float("nan")
    runs=1+int((a[1:]!=a[:-1]).sum());mean=1+2*n1*n2/n;var=2*n1*n2*(2*n1*n2-n)/(n*n*(n-1))
    return float((runs-mean)/math.sqrt(var)) if var>0 else float("nan")

def simulate(data,events,start_ms,end_ms,minutes,bps,risk=.005,max_lev=5.,initial=10_000.):
    evs=sorted((e for e in events if start_ms<=e.entry_time_ms<end_ms),key=lambda e:(e.entry_time_ms,-e.score,e.symbol,e.event_type))
    fee=bps/20_000.;nav=initial;free=start_ms;step=minutes*60_000;trades=[];points=[(start_ms,nav)];i=0
    while i<len(evs):
        t=evs[i].entry_time_ms;group=[]
        while i<len(evs) and evs[i].entry_time_ms==t:group.append(evs[i]);i+=1
        if t<free:continue
        e=max(group,key=lambda x:(x.score,x.symbol,x.event_type));unit=abs(e.entry_price-e.stop_price)+fee*(e.entry_price+e.stop_price)
        if unit<=0 or not np.isfinite(unit):continue
        qty=min(nav*risk/unit,nav*max_lev/e.entry_price)
        if qty<=0:continue
        before=nav;after=nav-qty*e.entry_price*fee;d=data[e.symbol]
        for j in range(e.entry_idx,min(e.exit_idx,len(d["close"])-1)+1):
            px=float(d["close"][j]);points.append((int(d["open_time_ms"][j]),after+e.side*qty*(px-e.entry_price)-qty*px*fee))
        nav=after+e.side*qty*(e.exit_price-e.entry_price)-qty*e.exit_price*fee
        trades.append({"symbol":e.symbol,"entry_time_ms":e.entry_time_ms,"exit_time_ms":e.exit_time_ms,"account_return":nav/before-1,"net_pnl":nav-before,"holding_hours":(e.exit_time_ms-e.entry_time_ms)/3_600_000,"leverage":qty*e.entry_price/before})
        points.append((e.exit_time_ms,nav));free=e.exit_time_ms+step
        if nav<=0:break
    days=max(1,(end_ms-start_ms)//86_400_000);gdg=(nav/initial)**(1/days)-1 if nav>0 else -1
    r=np.array([x["account_return"] for x in trades],float);pnl=np.array([x["net_pnl"] for x in trades],float);pos=pnl[pnl>0];neg=pnl[pnl<0]
    pf=float(pos.sum()/-neg.sum()) if len(pos) and len(neg) else (float("inf") if len(pos) else 0.)
    points.sort();ts=np.array([x[0] for x in points]);vals=np.array([x[1] for x in points]);mdd=float(np.max(1-vals/np.maximum.accumulate(vals)))
    if len(r):
        k=max(1,math.ceil(len(r)*.10));w=[q for q in np.argsort(r)[::-1] if r[q]>0][:k];keep=np.ones(len(r),bool);keep[w]=False;removed=float(np.prod(1+r[keep])-1);top5=float(np.sort(pos)[-5:].sum()/pos.sum()) if len(pos) else 1.
    else:removed=0.;top5=1.
    july=int(pd.Timestamp("2023-07-01",tz="UTC").value//1_000_000);q=max(0,int(np.searchsorted(ts,july,side="right")-1));mid=float(vals[q])
    return {"final_nav":float(nav),"total_return":float(nav/initial-1),"geometric_daily_growth":float(gdg),"maximum_drawdown":mdd,"trade_count":len(trades),"profit_factor":pf,"median_account_return_bps":float(np.median(r)*10_000) if len(r) else np.nan,"mean_account_return_bps":float(np.mean(r)*10_000) if len(r) else np.nan,"win_rate":float(np.mean(r>0)) if len(r) else np.nan,"top5_positive_share":top5,"top10pct_removed_return":removed,"h1_return":mid/initial-1,"h2_return":nav/mid-1,"median_holding_hours":float(np.median([x["holding_hours"] for x in trades])) if trades else np.nan,"max_leverage_used":float(max((x["leverage"] for x in trades),default=0)),"symbol_counts":{s:sum(x["symbol"]==s for x in trades) for s in SYMBOLS}}

def flatten(m,prefix):
    out={}
    for k,v in m.items():
        if k=="symbol_counts":
            for s,n in v.items():out[f"{prefix}symbol_count_{s}"]=n
        else:out[f"{prefix}{k}"]=v
    return out

def main():
    snap=Path(os.environ.get("DONCHIAN_SNAPSHOT","snapshot"));out=Path(os.environ.get("DONCHIAN_OUTPUT","results"));out.mkdir(parents=True,exist_ok=True)
    raw=load_snapshot(snap);start=int(pd.Timestamp("2023-01-01",tz="UTC").value//1_000_000);end=int(pd.Timestamp("2024-01-01",tz="UTC").value//1_000_000)
    rows=[];meta=[];modes=("all","after_loser","after_winner","turtle_failsafe")
    for minutes in (30,60):
      data={s:aggregate(raw[s],minutes) for s in SYMBOLS}
      for entry in (12,24,48,96):
       for ex in sorted({max(3,entry//4),max(3,entry//2)}):
        if ex>=entry:continue
        spec=Spec(minutes,entry,ex);by={s:theoretical_events(data[s],s,spec) for s in SYMBOLS};all_events=[e for s in SYMBOLS for e in by[s]]
        rz={s:runs_z([1 if e.gross_return>0 else -1 for e in by[s] if e.event_type=="base" and e.exit_reason!="evaluation_mtm"]) for s in SYMBOLS}
        info={"spec_id":spec.id,"timeframe_min":minutes,"entry_lb":entry,"exit_lb":ex,"failsafe_lb":spec.failsafe_lb,"runs_z_median":float(np.nanmedian(list(rz.values()))),"runs_z_mean":float(np.nanmean(list(rz.values()))),"runs_z_positive_fraction":float(np.mean([z>0 for z in rz.values() if np.isfinite(z)]))};meta.append(info)
        for mode in modes:
            row={**info,"mode":mode}
            for bps in (12.,18.,24.):row.update(flatten(simulate(data,events_for_mode(all_events,mode),start,end,minutes,bps),f"{int(bps)}bps_"))
            rows.append(row)
    df=pd.DataFrame(rows);df.to_csv(out/"development_all.csv",index=False)
    key=["spec_id","timeframe_min","entry_lb","exit_lb","failsafe_lb"];metrics=["12bps_geometric_daily_growth","18bps_geometric_daily_growth","24bps_geometric_daily_growth","12bps_trade_count","24bps_top10pct_removed_return","24bps_h1_return","24bps_h2_return","24bps_profit_factor","24bps_maximum_drawdown","24bps_total_return"]
    p=df.pivot_table(index=key,columns="mode",values=metrics,aggfunc="first");p.columns=[f"{a}__{b}" for a,b in p.columns];comp=p.reset_index().merge(pd.DataFrame(meta),on=key)
    for b in (12,18,24):comp[f"{b}bps_gdg_delta_loser_vs_all"]=comp[f"{b}bps_geometric_daily_growth__after_loser"]-comp[f"{b}bps_geometric_daily_growth__all"]
    comp["loser_gate_pass"]=(comp["24bps_geometric_daily_growth__after_loser"]>0)&(comp["12bps_trade_count__after_loser"]>=100)&(comp["24bps_top10pct_removed_return__after_loser"]>0)&(comp["24bps_h1_return__after_loser"]>0)&(comp["24bps_h2_return__after_loser"]>0)&(comp["12bps_gdg_delta_loser_vs_all"]>0)&(comp["18bps_gdg_delta_loser_vs_all"]>0)&(comp["24bps_gdg_delta_loser_vs_all"]>0)
    comp["turtle_gate_pass"]=(comp["24bps_geometric_daily_growth__turtle_failsafe"]>0)&(comp["12bps_trade_count__turtle_failsafe"]>=100)&(comp["24bps_top10pct_removed_return__turtle_failsafe"]>0)&(comp["24bps_h1_return__turtle_failsafe"]>0)&(comp["24bps_h2_return__turtle_failsafe"]>0)
    comp=comp.sort_values(["loser_gate_pass","24bps_geometric_daily_growth__after_loser","12bps_gdg_delta_loser_vs_all"],ascending=[False,False,False]);comp.to_csv(out/"matched_comparison.csv",index=False)
    summary={"spec_count":len(comp),"policy_count":len(df),"loser_gate_pass_count":int(comp.loser_gate_pass.sum()),"turtle_gate_pass_count":int(comp.turtle_gate_pass.sum()),"best":comp.iloc[0].replace({np.nan:None}).to_dict()};(out/"summary.json").write_text(json.dumps(summary,indent=2,sort_keys=True,default=str))

if __name__=="__main__":main()
