from __future__ import annotations

import argparse, hashlib, json, math
from dataclasses import dataclass, asdict
from pathlib import Path
from zoneinfo import ZoneInfo
from typing import Iterable, Any

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import roc_auc_score, average_precision_score, brier_score_loss
from numba import njit

NY=ZoneInfo('America/New_York')
ATR_BARS=96
DECISION_BARS=2
DECISION_COST_BPS=18.0
MAX_ABS_ROLL_RESIDUAL_BPS=35.0
MIN_GAP_ATR=0.15
FEATURES=(
    'gap_signed_atr','residual_in_gap_direction','response_in_gap_direction_atr',
    'rebalance_progress','log_continuation_to_rebalance_distance'
)
CME_MAP={'BTC=F':'BTCUSDT','ETH=F':'ETHUSDT'}

@njit(cache=True)
def _first_competing_hit(high, low, start, end, direction, continuation, rebalance):
    for i in range(start, end):
        if direction > 0:
            ch = high[i] >= continuation
            rh = low[i] <= rebalance
        else:
            ch = low[i] <= continuation
            rh = high[i] >= rebalance
        if ch or rh:
            if ch and rh:
                return i, 2
            return i, 1 if ch else 0
    return -1, -1

@njit(cache=True)
def _first_trade_hit(open_, high, low, start, end, side, target, stop):
    for i in range(start, end):
        if side > 0:
            if open_[i] <= stop:
                return i, 1
            if low[i] <= stop:
                return i, 2
            if open_[i] >= target:
                return i, 3
            if high[i] >= target:
                return i, 4
        else:
            if open_[i] >= stop:
                return i, 1
            if high[i] >= stop:
                return i, 2
            if open_[i] <= target:
                return i, 3
            if low[i] <= target:
                return i, 4
    return -1, -1

@dataclass(frozen=True)
class GapEvent:
    symbol:str; cme_symbol:str; trading_date:str; previous_trading_date:str; gap_kind:str
    open_ts:pd.Timestamp; prior_close_ts:pd.Timestamp
    cme_open:float; cme_prior_close:float; gap_return_bps:float; crypto_halt_return_bps:float
    roll_residual_bps:float; execution_open:float; mapped_prior_close:float
    atr:float; previous_day_high:float; previous_day_low:float; previous_week_high:float; previous_week_low:float

@dataclass(frozen=True)
class Opportunity:
    symbol:str; gap_kind:str; trading_date:str; event_open_ts:pd.Timestamp; decision_ts:pd.Timestamp
    entry_ts:pd.Timestamp; direction:int; entry_observed_open:float; entry_price:float
    rebalance_level:float; continuation_level:float; features:tuple[float,...]
    continuation_label:int|None; resolution:str; resolution_ts:pd.Timestamp|None

@dataclass(frozen=True)
class Candidate:
    opportunity:Opportunity; probability_continuation:float; ev_continuation_bps:float
    ev_rebalance_bps:float; selected_ev_bps:float; route:str; side:int; target:float; stop:float

@dataclass
class Trade:
    symbol:str; gap_kind:str; trading_date:str; route:str; side:int
    decision_ts:pd.Timestamp; entry_ts:pd.Timestamp; exit_ts:pd.Timestamp
    observed_open:float; entry_price:float; exit_price:float; stop_price:float; target_price:float
    probability_continuation:float; selected_ev_bps:float
    qty:float; nav_before:float; entry_fee:float; exit_fee:float; funding_pnl:float; price_pnl:float
    net_pnl:float; account_return:float; nav_after:float; exit_reason:str


def parse_cme_json(path:Path)->pd.DataFrame:
    doc=json.loads(path.read_text())
    result=doc['chart']['result'][0]
    ts=result.get('timestamp') or []
    q=result['indicators']['quote'][0]
    rows=[]
    for i,t in enumerate(ts):
        vals={}
        ok=True
        for k in ('open','high','low','close','volume'):
            arr=q.get(k) or []
            v=arr[i] if i<len(arr) else None
            if k=='volume' and v is None: v=0.0
            try: v=float(v)
            except Exception: ok=False; break
            if not math.isfinite(v) or (k!='volume' and v<=0): ok=False; break
            vals[k]=v
        if ok:
            stamp=pd.Timestamp(int(t),unit='s',tz='UTC')
            rows.append({'timestamp':stamp,'date':stamp.date(),**vals})
    return pd.DataFrame(rows).drop_duplicates('date',keep='last').set_index('date').sort_index()


def load_bars(root:Path,symbol:str,name:str)->pd.DataFrame:
    df=pd.read_pickle(root/symbol/f'{name}.pkl.gz',compression='gzip').copy()
    if name.startswith('bars_'):
        df['timestamp']=pd.to_datetime(df['start_time_ms'].astype('int64'),unit='ms',utc=True)
        if name=='bars_1m':
            df=df[df['observed'] & df['open'].notna()].copy()
        else:
            df=df[df['is_complete'] & df['open'].notna()].copy()
        return df.set_index('timestamp').sort_index()
    if name=='funding_events':
        df['timestamp']=pd.to_datetime(df['timestamp_ms'].astype('int64'),unit='ms',utc=True)
        return df.set_index('timestamp').sort_index()
    raise KeyError(name)


def final_business_days(year:int,month:int,count:int=5):
    start=pd.Timestamp(year=year,month=month,day=1)
    end=start+pd.offsets.MonthEnd(0)
    return set(pd.bdate_range(start,end)[-count:].date)

def ordinary_gap_kind(cur,prev):
    d=(cur-prev).days
    if cur.weekday()==0 and d==3 and prev.weekday()==4: return 'NWOG'
    if cur.weekday() in (1,2,3,4) and d==1: return 'NDOG'
    return None

def ny_ts(d,h):
    return pd.Timestamp(year=d.year,month=d.month,day=d.day,hour=h,tz=NY).tz_convert('UTC')

def exact_row(bars:pd.DataFrame,ts:pd.Timestamp):
    if ts not in bars.index:return None
    r=bars.loc[ts]
    return r.iloc[-1] if isinstance(r,pd.DataFrame) else r

def true_range_at(bars,ts):
    p=int(bars.index.searchsorted(ts,side='left'))
    if p<ATR_BARS+1:return None
    w=bars.iloc[p-ATR_BARS:p]
    prev=w['close'].shift(1)
    tr=pd.concat([w['high']-w['low'],(w['high']-prev).abs(),(w['low']-prev).abs()],axis=1).max(axis=1)
    v=float(tr.dropna().median())
    return v if math.isfinite(v) and v>0 else None

def prior_day_levels(bars,open_ts):
    d=(open_ts-pd.Timedelta(days=1)).date()
    s=bars[bars.index.date==d]
    if s.empty:return None
    return float(s.high.max()),float(s.low.min())

def prior_week_levels(bars,open_ts):
    local=open_ts.tz_convert(NY).date()
    mon=pd.Timestamp(local)-pd.Timedelta(days=local.weekday())
    a=(mon-pd.Timedelta(days=7)).date(); b=(mon-pd.Timedelta(days=1)).date()
    dates=bars.index.date; s=bars[(dates>=a)&(dates<=b)]
    if s.empty:return None
    return float(s.high.max()),float(s.low.min())

def build_events(cme_symbol,cme,bars15):
    symbol=CME_MAP[cme_symbol]; out=[]; dates=list(cme.index); exc={}
    for prev,cur in zip(dates,dates[1:]):
        kind=ordinary_gap_kind(cur,prev)
        if not kind:continue
        for d in (prev,cur): exc.setdefault((d.year,d.month),final_business_days(d.year,d.month))
        if prev in exc[(prev.year,prev.month)] or cur in exc[(cur.year,cur.month)]:continue
        pr=cme.loc[prev]; cr=cme.loc[cur]
        cprev=float(pr.close); cop=float(cr.open)
        open_local=cur-pd.Timedelta(days=1)
        ots=ny_ts(open_local,18); cts=ny_ts(prev,17)
        ob=exact_row(bars15,ots); cb=exact_row(bars15,cts-pd.Timedelta(minutes=15))
        if ob is None or cb is None:continue
        eopen=float(ob.open); cclose=float(cb.close)
        atr=true_range_at(bars15,ots); dl=prior_day_levels(bars15,ots); wl=prior_week_levels(bars15,ots)
        if atr is None or dl is None or wl is None:continue
        gap=1e4*math.log(cop/cprev); halt=1e4*math.log(eopen/cclose)
        mapped=eopen/math.exp(gap/1e4)
        out.append(GapEvent(symbol,cme_symbol,str(cur),str(prev),kind,ots,cts,cop,cprev,gap,halt,gap-halt,eopen,mapped,atr,dl[0],dl[1],wl[0],wl[1]))
    return out

def nearest_cont(event,entry,direction):
    if direction>0:
        xs=[x for x in (event.previous_day_high,event.previous_week_high) if math.isfinite(x) and x>entry]
        return min(xs) if xs else None
    xs=[x for x in (event.previous_day_low,event.previous_week_low) if math.isfinite(x) and x<entry]
    return max(xs) if xs else None

def first_touch(bars1,entry_ts,direction,cont,reb,cutoff=None):
    idx=bars1.index
    p=int(idx.searchsorted(entry_ts,side='left'))
    if p>=len(bars1) or idx[p]!=entry_ts:return None,'entry_missing',None
    q=len(bars1) if cutoff is None else int(idx.searchsorted(cutoff,side='right'))
    if q<=p:return None,'censored_at_cutoff',None
    high=bars1['high'].to_numpy(dtype=np.float64,copy=False)
    low=bars1['low'].to_numpy(dtype=np.float64,copy=False)
    hit,code=_first_competing_hit(high,low,p,q,direction,float(cont),float(reb))
    if hit<0:return None,('censored_at_cutoff' if cutoff is not None else 'censored'),None
    ts=idx[hit]
    if code==2:return None,'ambiguous_same_minute',ts
    return (1,'continuation_first',ts) if code==1 else (0,'rebalance_first',ts)

def build_opportunity(event,b15,b1,entry_slip_bps=1.0,cutoff=None):
    direction=1 if event.gap_return_bps>0 else -1 if event.gap_return_bps<0 else 0
    if not direction or abs(event.roll_residual_bps)>MAX_ABS_ROLL_RESIDUAL_BPS:return None
    gd=abs(event.execution_open-event.mapped_prior_close)
    if gd<=0 or gd/event.atr<MIN_GAP_ATR:return None
    rows=[]
    for off in range(DECISION_BARS):
        r=exact_row(b15,event.open_ts+pd.Timedelta(minutes=15*off))
        if r is None:return None
        rows.append(r)
    decision_ts=event.open_ts+pd.Timedelta(minutes=30)
    entry_ts=decision_ts+pd.Timedelta(minutes=1)
    er=exact_row(b1,entry_ts)
    if er is None:return None
    observed=float(er.open); fill=observed*(1+direction*entry_slip_bps/1e4)
    reb=float(event.mapped_prior_close); cont=nearest_cont(event,observed,direction)
    if cont is None:return None
    if direction*(observed-reb)<=0 or direction*(cont-observed)<=0:return None
    ao=float(rows[0].open); ac=float(rows[-1].close); ah=max(float(r.high) for r in rows); al=min(float(r.low) for r in rows)
    if direction>0: pre=ah>=cont or al<=reb
    else: pre=al<=cont or ah>=reb
    if pre:return None
    rb=abs(math.log(reb/observed))*1e4; cb=abs(math.log(cont/observed))*1e4
    if min(rb,cb)<=0:return None
    feats=((event.execution_open-event.mapped_prior_close)/event.atr,
           direction*event.roll_residual_bps/max(abs(event.gap_return_bps),1.0),
           direction*(ac-event.execution_open)/event.atr,
           direction*(event.execution_open-ac)/gd,
           math.log(cb/rb))
    if not np.isfinite(np.asarray(feats)).all():return None
    lab,res,rts=first_touch(b1,entry_ts,direction,cont,reb,cutoff)
    return Opportunity(event.symbol,event.gap_kind,event.trading_date,event.open_ts,decision_ts,entry_ts,direction,observed,fill,reb,cont,tuple(map(float,feats)),lab,res,rts)

def fit_model(rows):
    lab=[r for r in rows if r.continuation_label in (0,1)]
    X=np.asarray([r.features for r in lab]); y=np.asarray([r.continuation_label for r in lab])
    model=Pipeline([('scale',StandardScaler()),('logit',LogisticRegression(C=.25,penalty='l2',solver='lbfgs',max_iter=5000,random_state=0))])
    model.fit(X,y); return model

def probability(model,o):
    return float(model.predict_proba(np.asarray([o.features]))[0,list(model.named_steps['logit'].classes_).index(1)])

def route(model,o):
    p=probability(model,o)
    cb=abs(math.log(o.continuation_level/o.entry_observed_open))*1e4
    rb=abs(math.log(o.rebalance_level/o.entry_observed_open))*1e4
    ec=p*cb-(1-p)*rb-DECISION_COST_BPS
    er=(1-p)*rb-p*cb-DECISION_COST_BPS
    ev=max(ec,er)
    if not math.isfinite(ev) or ev<=0:return None
    if ec>=er:return Candidate(o,p,ec,er,ev,'continuation',o.direction,o.continuation_level,o.rebalance_level)
    return Candidate(o,p,ec,er,ev,'rebalance',-o.direction,o.rebalance_level,o.continuation_level)

def funding_pnl(funding,b1,entry_ts,exit_ts,side,qty,entry_price):
    f=funding[(funding.index>entry_ts)&(funding.index<=exit_ts)]
    pnl=0.0
    for ts,row in f.iterrows():
        p=int(b1.index.searchsorted(ts,side='left'))-1
        px=float(b1.iloc[p].close) if p>=0 else entry_price
        pnl += -side*qty*px*float(row.funding_rate)
    return pnl

def resolve_candidate(c,b1,funding,nav,cutoff,entry_fee_rate=.00055,target_fee=.00020,stop_fee=.00055,entry_slip_bps=1.,stop_slip_bps=2.,cap=3.,risk=.005):
    observed=c.opportunity.entry_observed_open
    fill=observed*(1+c.side*entry_slip_bps/1e4)
    if c.side>0 and not(c.stop<fill<c.target):return None
    if c.side<0 and not(c.target<fill<c.stop):return None
    stop_exec=c.stop*(1-c.side*stop_slip_bps/1e4)
    per_unit=abs(fill-stop_exec)+fill*entry_fee_rate+stop_exec*stop_fee
    if per_unit<=0:return None
    qty=min(nav*risk/per_unit,nav*cap/fill)
    if qty<=0:return None
    idx=b1.index
    p=int(idx.searchsorted(c.opportunity.entry_ts,side='left'))
    if p>=len(b1) or idx[p]!=c.opportunity.entry_ts:return None
    q=int(idx.searchsorted(cutoff,side='right'))
    if q<=p:return None
    open_=b1['open'].to_numpy(dtype=np.float64,copy=False); high=b1['high'].to_numpy(dtype=np.float64,copy=False); low=b1['low'].to_numpy(dtype=np.float64,copy=False)
    hit,code=_first_trade_hit(open_,high,low,p,q,c.side,float(c.target),float(c.stop))
    if hit<0:return None
    exit_ts=idx[hit]
    if code in (1,2):
        fee_rate=stop_fee
        if code==1: exit_price=float(open_[hit])*(1-c.side*stop_slip_bps/2/1e4); reason='stop_gap'
        else: exit_price=stop_exec; reason='protective_stop'
    else:
        fee_rate=target_fee; exit_price=c.target; reason='target_gap_limit' if code==3 else 'target'
    ef=qty*fill*entry_fee_rate; xf=qty*exit_price*fee_rate
    pp=c.side*qty*(exit_price-fill); fp=funding_pnl(funding,b1,c.opportunity.entry_ts,exit_ts,c.side,qty,fill)
    net=pp-ef-xf+fp; after=nav+net
    return Trade(c.opportunity.symbol,c.opportunity.gap_kind,c.opportunity.trading_date,c.route,c.side,c.opportunity.decision_ts,c.opportunity.entry_ts,exit_ts,observed,fill,exit_price,c.stop,c.target,c.probability_continuation,c.selected_ev_bps,qty,nav,ef,xf,fp,pp,net,net/nav,after,reason)

def replay(model,opps,b1s,funds,start,end,start_nav=10000.):
    cs=[]
    for o in opps:
        if start<=o.entry_ts<=end:
            c=route(model,o)
            if c:cs.append(c)
    cs.sort(key=lambda c:(c.opportunity.entry_ts,-c.selected_ev_bps,c.opportunity.symbol))
    nav=start_nav; free=pd.Timestamp.min.tz_localize('UTC'); trades=[]; skipped=0; unresolved=0
    for c in cs:
        if c.opportunity.entry_ts<=free: skipped+=1;continue
        t=resolve_candidate(c,b1s[c.opportunity.symbol],funds[c.opportunity.symbol],nav,end)
        if t is None: unresolved+=1;free=end;continue
        trades.append(t);nav=t.nav_after;free=t.exit_ts
    return trades,{'routed':len(cs),'skipped':skipped,'unresolved':unresolved,'end_nav':nav}

def diagnostics(model,rows):
    rs=[r for r in rows if r.continuation_label in (0,1)]
    y=np.array([r.continuation_label for r in rs]); p=np.array([probability(model,r) for r in rs])
    return {'n':len(rs),'continuation':int(y.sum()),'auc':float(roc_auc_score(y,p)) if len(set(y))==2 else None,'ap':float(average_precision_score(y,p)) if y.sum() else None,'brier':float(brier_score_loss(y,p))}

def metrics(trades,start,end):
    if trades:
        vals=np.array([t.account_return for t in trades]); pnls=np.array([t.net_pnl for t in trades]); nav=np.array([10000.]+[t.nav_after for t in trades])
        peaks=np.maximum.accumulate(nav);mdd=float(np.max(1-nav/peaks)); pos=pnls[pnls>0];neg=pnls[pnls<0]
        top=float(np.sort(pos)[-5:].sum()/pos.sum()) if pos.sum()>0 else 1.; total=trades[-1].nav_after/10000-1
    else:
        vals=np.array([]);pnls=np.array([]);mdd=0;top=1;total=0;pos=np.array([]);neg=np.array([])
    days=(end.normalize()-start.normalize()).days+1
    return {'trades':len(trades),'return':float(total),'gd':float(math.expm1(math.log1p(total)/days)) if total>-1 else -1.,'pf':float(pos.sum()/-neg.sum()) if len(neg) else None,'median':float(np.median(vals)) if len(vals) else None,'mdd':mdd,'top5_share':top,'end_nav':float(10000*(1+total))}

def model_payload(m):
    s=m.named_steps['scale'];l=m.named_steps['logit']
    return {'features':FEATURES,'mean':dict(zip(FEATURES,map(float,s.mean_))),'scale':dict(zip(FEATURES,map(float,s.scale_))),'coef':dict(zip(FEATURES,map(float,l.coef_[0]))),'intercept':float(l.intercept_[0])}

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--core',type=Path,required=True);ap.add_argument('--artifact',type=Path,required=True);ap.add_argument('--out',type=Path,required=True);args=ap.parse_args();args.out.mkdir(parents=True,exist_ok=True)
    raw=args.artifact/'cme_opening_gap_source_probe/raw'
    cmes={'BTC=F':parse_cme_json(raw/'yahoo_BTC_F.json'),'ETH=F':parse_cme_json(raw/'yahoo_ETH_F.json')}
    b15={s:load_bars(args.core,s,'bars_15m') for s in CME_MAP.values()};b1={s:load_bars(args.core,s,'bars_1m') for s in CME_MAP.values()};fund={s:load_bars(args.core,s,'funding_events') for s in CME_MAP.values()}
    ev=[]
    for cs,df in cmes.items():ev+=build_events(cs,df,b15[CME_MAP[cs]])
    opp=[]
    for e in ev:
        cutoff=pd.Timestamp(f'{pd.Timestamp(e.trading_date).year}-12-31T23:59:59Z')
        o=build_opportunity(e,b15[e.symbol],b1[e.symbol],cutoff=cutoff)
        if o:opp.append(o)
    opp.sort(key=lambda x:(x.entry_ts,x.symbol)); byyear={y:[o for o in opp if o.entry_ts.year==y] for y in (2021,2022,2023)}
    m21=fit_model(byyear[2021]);m22=fit_model(byyear[2021]+byyear[2022]); stages=[]
    for y,m in [(2022,m21),(2023,m22)]:
        st=pd.Timestamp(f'{y}-01-01T00:00:00Z');en=pd.Timestamp(f'{y}-12-31T23:59:59Z')
        tr,rep=replay(m,byyear[y],b1,fund,st,en); met=metrics(tr,st,en); met.update({'year':y,'diagnostics':diagnostics(m,byyear[y]),**rep}); stages.append(met)
        pd.DataFrame([asdict(t) for t in tr]).to_csv(args.out/f'trades_{y}.csv',index=False)
    pd.DataFrame([{**{k:v for k,v in asdict(o).items() if k!='features'},**dict(zip(FEATURES,o.features))} for o in opp]).to_csv(args.out/'opportunities.csv',index=False)
    result={'event_count':len(ev),'opportunity_counts':{str(y):len(byyear[y]) for y in byyear},'labeled_counts':{str(y):sum(o.continuation_label in (0,1) for o in byyear[y]) for y in byyear},'model_2021':model_payload(m21),'model_2021_2022':model_payload(m22),'stages':stages}
    (args.out/'pre2024_result.json').write_text(json.dumps(result,indent=2,default=str)+'\n'); print(json.dumps(result,default=str))
if __name__=='__main__':main()
