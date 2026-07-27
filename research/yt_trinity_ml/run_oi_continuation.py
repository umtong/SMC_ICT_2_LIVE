#!/usr/bin/env python3
from __future__ import annotations

import argparse, json, math
from pathlib import Path
from typing import Any, Mapping
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression, Ridge
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

SYMBOLS=("BTCUSDT","ETHUSDT","SOLUSDT","XRPUSDT")
TAKER=0.00055; MAKER=0.00020; MARKET_BPS=2.0; STOP_BPS=3.0; PASSIVE_THROUGH=0.0001
FEATURES=("side","family_squeeze","family_build","family_reversal","move_15_atr","move_30_atr",
"body_atr","close_pos","volume_surprise","oi_chg_5","oi_chg_15","oi_chg_60","ratio_z","premium_z",
"trend","breakout_1h","breakout_4h","wick_atr","fvg_present","crowd_against","dow","utc_sin","utc_cos",
"symbol_btc","symbol_eth","symbol_sol","symbol_xrp")


def read(root:Path,symbol:str,rel:str)->pd.DataFrame:
    p=root/symbol/rel
    if not p.exists():
        matches=list((root/symbol).rglob(Path(rel).name))
        if not matches: raise FileNotFoundError(p)
        p=matches[0]
    return pd.read_parquet(p)

def col(frame:pd.DataFrame,*names:str)->str:
    for name in names:
        if name in frame.columns:return name
    raise KeyError(f"missing {names}; have={list(frame.columns)}")

def ms(frame:pd.DataFrame,*names:str)->pd.Series:
    return pd.to_datetime(frame[col(frame,*names)],unit="ms",utc=True)

def values(frame:pd.DataFrame,*names:str)->pd.Series:
    return pd.to_numeric(frame[col(frame,*names)],errors="coerce")

def aux(frame:pd.DataFrame,mapping:Mapping[str,tuple[str,...]])->pd.DataFrame:
    out=pd.DataFrame({"available_at":ms(frame,"available_at_ms")})
    for target,names in mapping.items():out[target]=values(frame,*names)
    return out.sort_values("available_at").drop_duplicates("available_at")

def load_symbol(root:Path,symbol:str):
    m5=read(root,symbol,"trade_bars/5m.parquet").copy()
    m1=read(root,symbol,"trade_bars/1m.parquet").copy()
    for frame in (m5,m1):
        frame["bar_start"]=ms(frame,"start_time_ms","timestamp_ms")
        frame["available_at"]=ms(frame,"available_at_ms")
        for n in ("open","high","low","close","volume"):
            frame[n]=values(frame,n,f"{n}_price")
        frame.sort_values("bar_start",inplace=True);frame.drop_duplicates("bar_start",inplace=True)
    oi=aux(read(root,symbol,"streams/open_interest_5m.parquet"),{"oi":("open_interest",)})
    ratio=aux(read(root,symbol,"streams/account_ratio_5m.parquet"),{"buy_ratio":("buy_ratio",),"sell_ratio":("sell_ratio",),"long_short_ratio":("long_short_ratio",)})
    premium=aux(read(root,symbol,"streams/premium_index_1m.parquet"),{"premium":("close","close_price")})
    mark=read(root,symbol,"streams/mark_price_1m.parquet").copy()
    mark["bar_start"]=ms(mark,"start_time_ms","timestamp_ms");mark["mark"]=values(mark,"close","close_price")
    mark=mark.sort_values("bar_start").drop_duplicates("bar_start").set_index("bar_start")
    funding=read(root,symbol,"streams/funding_events.parquet").copy()
    funding["time"]=ms(funding,"timestamp_ms","start_time_ms")
    funding["rate"]=values(funding,"funding_rate","fundingRate")
    funding=funding.sort_values("time").drop_duplicates("time")
    base=m5.sort_values("available_at")
    for right in (oi,ratio,premium):
        base=pd.merge_asof(base,right,on="available_at",direction="backward",allow_exact_matches=True)
    return base.sort_values("bar_start").reset_index(drop=True),m1.set_index("bar_start").sort_index(),mark,funding

def features(x:pd.DataFrame)->pd.DataFrame:
    x=x.copy();prev=x.close.shift(1)
    tr=pd.concat([x.high-x.low,(x.high-prev).abs(),(x.low-prev).abs()],axis=1).max(axis=1)
    x["atr"]=tr.ewm(alpha=1/48,adjust=False,min_periods=48).mean()
    x["body_atr"]=(x.close-x.open).abs()/x.atr
    x["close_pos"]=(x.close-x.low)/(x.high-x.low).replace(0,np.nan)
    x["ret5"]=x.close.pct_change();x["ret15"]=x.close.pct_change(3);x["ret30"]=x.close.pct_change(6)
    x["move_15_atr"]=(x.close-x.close.shift(3)).abs()/x.atr
    x["move_30_atr"]=(x.close-x.close.shift(6)).abs()/x.atr
    vm=x.volume.rolling(96,min_periods=48).median();x["volume_surprise"]=x.volume/vm.replace(0,np.nan)
    x["oi_chg_5"]=x.oi.pct_change();x["oi_chg_15"]=x.oi.pct_change(3);x["oi_chg_60"]=x.oi.pct_change(12)
    for source,target in (("buy_ratio","ratio_z"),("premium","premium_z")):
        mean=x[source].rolling(288,min_periods=96).mean();std=x[source].rolling(288,min_periods=96).std(ddof=0)
        x[target]=(x[source]-mean)/std.replace(0,np.nan)
    e48=x.close.ewm(span=48,adjust=False,min_periods=48).mean();e192=x.close.ewm(span=192,adjust=False,min_periods=192).mean()
    x["trend"]=np.log(e48/e192)
    x["prior_high_1h"]=x.high.shift(1).rolling(12,min_periods=12).max();x["prior_low_1h"]=x.low.shift(1).rolling(12,min_periods=12).min()
    x["prior_high_4h"]=x.high.shift(1).rolling(48,min_periods=48).max();x["prior_low_4h"]=x.low.shift(1).rolling(48,min_periods=48).min()
    x["breakout_1h"]=np.where(x.close>x.prior_high_1h,1,np.where(x.close<x.prior_low_1h,-1,0))
    x["breakout_4h"]=np.where(x.close>x.prior_high_4h,1,np.where(x.close<x.prior_low_4h,-1,0))
    x["upper_wick"]=(x.high-np.maximum(x.open,x.close))/x.atr;x["lower_wick"]=(np.minimum(x.open,x.close)-x.low)/x.atr
    x["fvg_bull_lower"]=x.high.shift(2).where(x.low>x.high.shift(2));x["fvg_bull_upper"]=x.low.where(x.low>x.high.shift(2))
    x["fvg_bear_lower"]=x.high.where(x.high<x.low.shift(2));x["fvg_bear_upper"]=x.low.shift(2).where(x.high<x.low.shift(2))
    x["dow"]=x.bar_start.dt.dayofweek;x["utc_minute"]=x.bar_start.dt.hour*60+x.bar_start.dt.minute
    return x

def candidate_rows(symbol:str,x:pd.DataFrame)->pd.DataFrame:
    rows=[];last={}
    for i in range(192,len(x)):
        r=x.iloc[i]
        if not np.isfinite(r.atr) or r.atr<=0:continue
        initial=1 if r.ret15>0 else -1
        close_extreme=(r.close_pos>=.70 if initial>0 else r.close_pos<=.30)
        breakout=(r.breakout_1h==initial)
        common=(r.move_15_atr>=1.15 and r.volume_surprise>=1.25 and close_extreme)
        families=[]
        if common and r.oi_chg_15<=-.002 and (breakout or r.body_atr>=.75):families.append(("SQUEEZE_CONTINUATION",initial))
        if common and r.oi_chg_15>=.002 and breakout:families.append(("POSITION_BUILD_CONTINUATION",initial))
        short_reversal=(r.high>r.prior_high_1h+.05*r.atr and r.close<r.prior_high_1h and r.close_pos<=.45 and r.oi_chg_15<=-.002 and r.volume_surprise>=1.25)
        long_reversal=(r.low<r.prior_low_1h-.05*r.atr and r.close>r.prior_low_1h and r.close_pos>=.55 and r.oi_chg_15<=-.002 and r.volume_surprise>=1.25)
        if short_reversal:families.append(("LIQUIDATION_EXHAUSTION_REVERSAL",-1))
        if long_reversal:families.append(("LIQUIDATION_EXHAUSTION_REVERSAL",1))
        for family,side in families:
            key=(family,side)
            if key in last and r.bar_start-last[key]<pd.Timedelta(minutes=60):continue
            last[key]=r.bar_start
            impulse=x.iloc[max(0,i-2):i+1]
            stop=float(impulse.low.min()-.05*r.atr if side>0 else impulse.high.max()+.05*r.atr)
            if side>0:
                fvg=(float(r.fvg_bull_lower)+float(r.fvg_bull_upper))/2 if pd.notna(r.fvg_bull_lower) else np.nan
            else:
                fvg=(float(r.fvg_bear_lower)+float(r.fvg_bear_upper))/2 if pd.notna(r.fvg_bear_lower) else np.nan
            midpoint=float((impulse.high.max()+impulse.low.min())/2)
            minute=float(r.utc_minute)
            rows.append({"symbol":symbol,"family":family,"side":side,"signal_time":pd.Timestamp(r.available_at),"bar_start":pd.Timestamp(r.bar_start),
                "stop_ref":stop,"fvg_entry":fvg,"mid_entry":midpoint,
                "family_squeeze":float(family=="SQUEEZE_CONTINUATION"),"family_build":float(family=="POSITION_BUILD_CONTINUATION"),
                "family_reversal":float(family=="LIQUIDATION_EXHAUSTION_REVERSAL"),"move_15_atr":float(r.move_15_atr),"move_30_atr":float(r.move_30_atr),
                "body_atr":float(r.body_atr),"close_pos":float(r.close_pos),"volume_surprise":float(r.volume_surprise),
                "oi_chg_5":float(r.oi_chg_5),"oi_chg_15":float(r.oi_chg_15),"oi_chg_60":float(r.oi_chg_60),
                "ratio_z":float(r.ratio_z),"premium_z":float(r.premium_z),"trend":float(r.trend),
                "breakout_1h":float(side*r.breakout_1h),"breakout_4h":float(side*r.breakout_4h),
                "wick_atr":float(r.lower_wick if side>0 else r.upper_wick),"fvg_present":float(np.isfinite(fvg)),
                "crowd_against":float(-side*(r.buy_ratio-.5)),"dow":float(r.dow),"utc_sin":math.sin(2*math.pi*minute/1440),"utc_cos":math.cos(2*math.pi*minute/1440),
                "symbol_btc":float(symbol=="BTCUSDT"),"symbol_eth":float(symbol=="ETHUSDT"),"symbol_sol":float(symbol=="SOLUSDT"),"symbol_xrp":float(symbol=="XRPUSDT")})
    return pd.DataFrame(rows)

class RangeIndex:
    def __init__(self,low,high):
        self.n=len(low);size=1
        while size<self.n:size<<=1
        self.size=size;self.mn=np.full(2*size,np.inf);self.mx=np.full(2*size,-np.inf)
        self.mn[size:size+self.n]=low;self.mx[size:size+self.n]=high
        for i in range(size-1,0,-1):self.mn[i]=min(self.mn[2*i],self.mn[2*i+1]);self.mx[i]=max(self.mx[2*i],self.mx[2*i+1])
    def _first(self,tree,start,threshold,lower):
        ok=(lambda v:v<=threshold) if lower else (lambda v:v>=threshold)
        if start>=self.n or not ok(float(tree[1])):return None
        def visit(node,l,r):
            if r<=start or not ok(float(tree[node])):return None
            if r-l==1:return l if l<self.n else None
            m=(l+r)//2;a=visit(node*2,l,m)
            return a if a is not None else visit(node*2+1,m,r)
        return visit(1,0,self.size)
    def low_le(self,s,t):return self._first(self.mn,s,t,True)
    def high_ge(self,s,t):return self._first(self.mx,s,t,False)
    def low_lt(self,s,t):return self.low_le(s,float(np.nextafter(t,-np.inf)))
    def high_gt(self,s,t):return self.high_ge(s,float(np.nextafter(t,np.inf)))

def first(*x):
    z=[v for v in x if v is not None];return min(z) if z else None

class Simulator:
    def __init__(self,m1,mark,funding):
        self.times=m1.index;self.ns=self.times.as_unit("ns").asi8
        self.o=m1.open.to_numpy(float);self.h=m1.high.to_numpy(float);self.l=m1.low.to_numpy(float);self.c=m1.close.to_numpy(float)
        self.ix=RangeIndex(self.l,self.h);self.mark=mark
        self.ft=pd.DatetimeIndex(funding.time);self.fr=funding.rate.to_numpy(float)
    def funding_pnl(self,side,start,end):
        a=self.ft.searchsorted(start,side="right");b=self.ft.searchsorted(end,side="right");total=0.
        for t,rate in zip(self.ft[a:b],self.fr[a:b]):
            pos=self.mark.index.searchsorted(t,side="right")-1
            if pos>=0:total+=-side*float(self.mark.iloc[pos].mark)*float(rate)
        return total
    def run(self,row,action,target_r):
        side=int(row.side);activation=pd.Timestamp(row.signal_time)+pd.Timedelta(milliseconds=500)
        start=int(np.searchsorted(self.ns,activation.value,side="right"));stop=float(row.stop_ref)
        if start>=len(self.times):return None
        if action=="market":entry=float(self.o[start])*(1+side*MARKET_BPS/10000);ep=start;etime=self.times[start];efee=TAKER
        else:
            entry=float(row.fvg_entry if action=="fvg" else row.mid_entry)
            if not np.isfinite(entry):return None
            efee=MAKER
            price_risk=side*(entry-stop)
            if price_risk<=0:return None
            target=entry+side*target_r*price_risk
            invalid=self.ix.low_le(start,stop) if side>0 else self.ix.high_ge(start,stop)
            before_target=self.ix.high_ge(start,target) if side>0 else self.ix.low_le(start,target)
            crossed=self.ix.low_lt(start,entry*(1-PASSIVE_THROUGH)) if side>0 else self.ix.high_gt(start,entry*(1+PASSIVE_THROUGH))
            ep=first(invalid,before_target,crossed)
            if ep is None:return {"filled":0,"status":"UNRESOLVED_NO_FILL","budget_r":0.,"entry_time":pd.NaT,"end_time":self.times[-1]}
            if ep in {invalid,before_target}:return {"filled":0,"status":"CANCELLED_BEFORE_FILL","budget_r":0.,"entry_time":pd.NaT,"end_time":self.times[ep]}
            etime=self.times[ep]
        price_risk=side*(entry-stop)
        if price_risk<=0:return None
        target=entry+side*target_r*price_risk
        stop_fill=stop*(1-side*STOP_BPS/10000);planned=-(side*(stop_fill-entry)-entry*efee-abs(stop_fill)*TAKER)
        if planned<=0:return None
        sp=self.ix.low_le(ep,stop) if side>0 else self.ix.high_ge(ep,stop)
        tp=self.ix.high_ge(ep,target) if side>0 else self.ix.low_le(ep,target);xp=first(sp,tp)
        if xp is None:return None
        if sp==xp:exit_price=stop_fill;xfee=TAKER;status="STOP"
        else:exit_price=target;xfee=MAKER;status="TARGET"
        end=self.times[xp];fund=self.funding_pnl(side,etime,end)
        pnl=side*(exit_price-entry)-entry*efee-abs(exit_price)*xfee+fund
        return {"filled":1,"status":status,"budget_r":float(pnl/planned),"entry_time":etime,"end_time":end,"entry":entry,"stop":stop,"target":target,"funding_per_unit":fund}

def build(root):
    all_rows=[]
    for symbol in SYMBOLS:
        print("load",symbol,flush=True);m5,m1,mark,funding=load_symbol(root,symbol);x=features(m5);cand=candidate_rows(symbol,x);print("candidates",len(cand),flush=True)
        sim=Simulator(m1,mark,funding)
        for row in cand.itertuples(index=False):
            base=row._asdict()
            for action in ("market","mid","fvg"):
                for target_r in (1.0,1.5,2.0,3.0):
                    out=sim.run(row,action,target_r)
                    if out is not None:all_rows.append({**base,"action":action,"target_r":target_r,**out})
    return pd.DataFrame(all_rows)

def model_pair(kind):
    if kind=="ridge":return (make_pipeline(SimpleImputer(strategy="median"),StandardScaler(),Ridge(alpha=20.)),make_pipeline(SimpleImputer(strategy="median"),StandardScaler(),LogisticRegression(C=.1,max_iter=2000,class_weight="balanced")))
    return (HistGradientBoostingRegressor(max_leaf_nodes=7,max_iter=180,learning_rate=.04,min_samples_leaf=25,l2_regularization=10.,random_state=51),HistGradientBoostingClassifier(max_leaf_nodes=7,max_iter=160,learning_rate=.04,min_samples_leaf=25,l2_regularization=10.,random_state=51))

def fit_models(train,kind):
    models={}
    for key,g in train.groupby(["action","target_r"]):
        if len(g)<50:continue
        reg,clf=model_pair(kind);fill=g.filled.astype(int)
        if key[0]=="market":fm=None
        elif fill.nunique()>1:clf.fit(g[list(FEATURES)],fill);fm=clf
        else:fm=float(fill.iloc[0])
        f=g[g.filled==1]
        if len(f)<35:continue
        reg.fit(f[list(FEATURES)],f.budget_r.clip(-1,2.5));models[key]=(reg,fm)
    return models

def score(data,models):
    out=[]
    for (action,target),(reg,fm) in models.items():
        z=data[(data.action==action)&(data.target_r==target)].copy()
        if z.empty:continue
        cond=np.asarray(reg.predict(z[list(FEATURES)]),float)
        if action=="market":pf=np.ones(len(z))
        elif isinstance(fm,float):pf=np.full(len(z),fm)
        else:pf=fm.predict_proba(z[list(FEATURES)])[:,list(fm.classes_).index(1)]
        z["score"]=cond*pf;z["pred_fill"]=pf;out.append(z)
    return pd.concat(out,ignore_index=True)

def replay(z,start,end,threshold,rho):
    z=z[(z.signal_time>=start)&(z.signal_time<end)].copy();nav=10000.;until=start;tr=[]
    for t,g in z.sort_values(["signal_time","score"],ascending=[True,False]).groupby("signal_time",sort=True):
        t=pd.Timestamp(t)
        if t<until:continue
        e=g[g.score>threshold]
        if e.empty:continue
        r=e.sort_values(["score","pred_fill"],ascending=False).iloc[0];before=nav;rr=float(r.budget_r);nav*=1+rho*rr
        until=min(max(pd.Timestamp(r.end_time),t+pd.Timedelta(minutes=1)),end)
        tr.append({"signal_time":t,"end_time":until,"symbol":r.symbol,"family":r.family,"action":r.action,"target_r":float(r.target_r),"score":float(r.score),"filled":int(r.filled),"budget_r":rr,"nav_before":before,"nav_after":nav})
        if nav<=0:break
    t=pd.DataFrame(tr);days=int((end-start)/pd.Timedelta(days=1));path=np.r_[10000.,t.nav_after.to_numpy()] if len(t) else np.array([10000.]);mdd=float(np.max(1-path/np.maximum.accumulate(path)))
    vals=t.budget_r.to_numpy() if len(t) else np.array([])
    def rem(n):
        a=vals.copy();p=np.flatnonzero(a>0)
        if len(p):a[p[np.argsort(a[p])[-min(n,len(p)):]]]=0
        return float(10000*np.prod(1+rho*a))
    gd=math.exp(math.log(nav/10000)/days)-1 if nav>0 else -1
    return {"nav":float(nav),"multiple":float(nav/10000),"g_daily":float(gd),"mdd":mdd,"selected":len(t),"filled":int(t.filled.sum()) if len(t) else 0,"mean_r":float(t.budget_r.mean()) if len(t) else None,"sum_r":float(t.budget_r.sum()) if len(t) else 0.,"top1_nav":rem(1),"top3_nav":rem(3),"top5_nav":rem(5),"trades":t}

def main():
    ap=argparse.ArgumentParser();ap.add_argument("--data-root",type=Path,required=True);ap.add_argument("--output",type=Path,required=True);a=ap.parse_args();a.output.mkdir(parents=True,exist_ok=True)
    data=build(a.data_root);data.to_parquet(a.output/"EVENTS.parquet",index=False);print("dataset",data.shape,data.status.value_counts().to_dict(),flush=True)
    fit_end=pd.Timestamp("2023-05-01",tz="UTC");cal_end=pd.Timestamp("2023-07-01",tz="UTC");test_end=pd.Timestamp("2024-01-01",tz="UTC")
    train=data[(data.signal_time<fit_end)&(data.end_time<fit_end)];grid=[];scored={}
    for kind in ("ridge","hgb"):
        models=fit_models(train,kind);s=score(data,models);scored[kind]=s;cs=s[(s.signal_time>=fit_end)&(s.signal_time<cal_end)].score.dropna()
        for th in np.unique(np.r_[0,np.quantile(cs,[.4,.5,.6,.7,.8,.85,.9,.93,.95,.97])]):
            o=replay(s,fit_end,cal_end,float(th),.01);grid.append({"kind":kind,"threshold":float(th),**{k:v for k,v in o.items() if k!="trades"}})
    grid=pd.DataFrame(grid);grid.to_csv(a.output/"CALIBRATION_GRID.csv",index=False)
    robust=grid[(grid.selected>=10)&(grid.filled>=8)&(grid.nav>10000)&(grid.top5_nav>10000)]
    if robust.empty:summary={"status":"CALIBRATION_FAIL","candidate_count":int(data[["symbol","family","signal_time"]].drop_duplicates().shape[0]),"event_action_count":int(len(data))}
    else:
        best=robust.sort_values(["nav","top5_nav"],ascending=False).iloc[0];kind=str(best.kind);th=float(best.threshold)
        risk_rows=[]
        for rho in (.005,.01,.02,.04,.08,.12,.20,.30):
            o=replay(scored[kind],fit_end,cal_end,th,rho);risk_rows.append({"rho":rho,**{k:v for k,v in o.items() if k!="trades"}})
        rg=pd.DataFrame(risk_rows);rg.to_csv(a.output/"RISK_GRID.csv",index=False)
        valid=rg[(rg.nav>10000)&(rg.top5_nav>10000)&(rg.nav>0)]
        chosen=valid.sort_values("nav",ascending=False).iloc[0] if len(valid) else rg[rg.rho==.01].iloc[0];rho=float(chosen.rho)
        test=replay(scored[kind],cal_end,test_end,th,rho);test["trades"].to_csv(a.output/"H2_TRADES.csv",index=False)
        summary={"status":"H2_PASS" if test["nav"]>10000 and test["top5_nav"]>10000 else "H2_FAIL","selected_kind":kind,"threshold":th,"risk_fraction":rho,"calibration":{k:(v.item() if hasattr(v,"item") else v) for k,v in best.to_dict().items()},"h2":{k:v for k,v in test.items() if k!="trades"},"candidate_count":int(data[["symbol","family","signal_time"]].drop_duplicates().shape[0]),"event_action_count":int(len(data))}
    (a.output/"SUMMARY.json").write_text(json.dumps(summary,indent=2,default=str)+"\n");print(json.dumps(summary,indent=2,default=str),flush=True)
if __name__=="__main__":main()
