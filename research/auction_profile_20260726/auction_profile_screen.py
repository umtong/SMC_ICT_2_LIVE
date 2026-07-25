from __future__ import annotations

from dataclasses import dataclass, asdict
from pathlib import Path
import math, json, itertools, hashlib
import numpy as np
import pandas as pd

SYMBOLS=("BTCUSDT","ETHUSDT","SOLUSDT","XRPUSDT")
BAR_MS=5*60*1000

@dataclass(frozen=True)
class Candidate:
    family: str
    session_hours: int
    bins: int=32
    confirm_minutes: int=30
    confirm_count: int=2
    target_mode: str="opposite_va"
    stop_buffer: float=0.10
    target_mult: float=1.0

    @property
    def id(self)->str:
        s=json.dumps(asdict(self),sort_keys=True,separators=(",",":"))
        return hashlib.sha256(s.encode()).hexdigest()[:20]

@dataclass
class Event:
    symbol: str
    entry_idx: int
    entry_time_ms: int
    entry_price: float
    side: int
    stop: float
    target: float
    score: float
    session_id: int
    family: str


def load_data(snapshot: Path):
    out={}
    for sym in SYMBOLS:
        z=np.load(snapshot/f"{sym}_5m.npz")
        out[sym]={k:z[k] for k in z.files}
        assert np.all(np.diff(out[sym]['open_time_ms'])==BAR_MS)
    return out


def profile_for_slice(d, i0:int, i1:int, bins:int=32, method='typical'):
    lo=float(np.min(d['low'][i0:i1])); hi=float(np.max(d['high'][i0:i1]))
    if not np.isfinite(lo+hi) or hi<=lo:
        return None
    edges=np.linspace(lo,hi,bins+1)
    hist=np.zeros(bins,dtype=float)
    vol=d['quote_volume'][i0:i1]
    if method=='typical':
        px=(d['high'][i0:i1]+d['low'][i0:i1]+d['close'][i0:i1])/3.0
        idx=np.searchsorted(edges,px,side='right')-1
        idx=np.clip(idx,0,bins-1)
        np.add.at(hist,idx,vol)
    elif method=='close':
        px=d['close'][i0:i1]
        idx=np.searchsorted(edges,px,side='right')-1
        idx=np.clip(idx,0,bins-1)
        np.add.at(hist,idx,vol)
    elif method=='uniform':
        lows=d['low'][i0:i1].astype(float); highs=d['high'][i0:i1].astype(float)
        ranges=highs-lows
        nz=ranges>1e-15
        if np.any(nz):
            overlaps=np.maximum(0.0, np.minimum(highs[nz,None],edges[None,1:]) - np.maximum(lows[nz,None],edges[None,:-1]))
            hist += np.sum((overlaps/ranges[nz,None])*vol[nz,None],axis=0)
        if np.any(~nz):
            px=d['close'][i0:i1][~nz]
            idx=np.searchsorted(edges,px,side='right')-1
            idx=np.clip(idx,0,bins-1)
            np.add.at(hist,idx,vol[~nz])
    else:
        raise ValueError(method)
    total=hist.sum()
    if total<=0:
        return None
    poc=int(np.argmax(hist)); left=right=poc; cum=hist[poc]
    target=0.70*total
    while cum<target and (left>0 or right<bins-1):
        lv=hist[left-1] if left>0 else -1.0
        rv=hist[right+1] if right<bins-1 else -1.0
        if rv>lv:
            right+=1; cum+=hist[right]
        else:
            left-=1; cum+=hist[left]
    val=float(edges[left]); vah=float(edges[right+1]); poc_px=float((edges[poc]+edges[poc+1])/2)
    return {
        'low':lo,'high':hi,'val':val,'vah':vah,'poc':poc_px,'va_width':vah-val,
        'range':hi-lo,'volume':float(total),'poc_idx':poc,'va_lo_idx':left,'va_hi_idx':right,
    }


def build_profiles(d, session_hours:int, bins:int=32, method='typical'):
    session_ms=session_hours*3600*1000
    ts=d['open_time_ms']
    sid=ts//session_ms
    changes=np.flatnonzero(np.r_[True, sid[1:]!=sid[:-1]])
    ends=np.r_[changes[1:],len(ts)]
    profiles={}
    slices={}
    for i0,i1 in zip(changes,ends):
        s=int(sid[i0])
        p=profile_for_slice(d,int(i0),int(i1),bins,method)
        if p is not None:
            p['i0']=int(i0);p['i1']=int(i1);p['session_id']=s
            p['open']=float(d['open'][i0]);p['close']=float(d['close'][i1-1])
            profiles[s]=p; slices[s]=(int(i0),int(i1))
    return profiles,slices


def generate_events(d, symbol:str, cand:Candidate, profile_method='typical') -> list[Event]:
    profiles,slices=build_profiles(d,cand.session_hours,cand.bins,profile_method)
    events=[]
    interval_bars=cand.confirm_minutes//5
    assert interval_bars>=1 and cand.confirm_minutes%5==0
    for s,(i0,i1) in slices.items():
        prior=profiles.get(s-1)
        if prior is None or prior['va_width']<=0:
            continue
        val,vah,poc,w=prior['val'],prior['vah'],prior['poc'],prior['va_width']
        op=float(d['open'][i0])
        open_side=1 if op>vah else (-1 if op<val else 0)
        if i1-i0 < interval_bars*cand.confirm_count+1:
            continue
        if cand.family=='outside_rotation':
            if open_side==0:
                continue
            consec=0
            max_end=i0+(i1-i0)//2
            for end_excl in range(i0+interval_bars, min(i1,max_end)+1, interval_bars):
                c=float(d['close'][end_excl-1])
                inside=(val <= c <= vah)
                consec=consec+1 if inside else 0
                if consec>=cand.confirm_count:
                    entry_idx=end_excl
                    if entry_idx>=i1 or entry_idx>=len(d['open']):
                        break
                    entry=float(d['open'][entry_idx])
                    if open_side>0:
                        side=-1
                        excursion=float(np.max(d['high'][i0:end_excl]))
                        stop=excursion+cand.stop_buffer*w
                        target=poc if cand.target_mode=='poc' else val
                        rr=(entry-target)/(stop-entry) if stop>entry and entry>target else -1
                    else:
                        side=1
                        excursion=float(np.min(d['low'][i0:end_excl]))
                        stop=excursion-cand.stop_buffer*w
                        target=poc if cand.target_mode=='poc' else vah
                        rr=(target-entry)/(entry-stop) if entry>stop and target>entry else -1
                    if rr>0 and np.isfinite(rr):
                        dist=(abs(op-(vah if open_side>0 else val))/max(w,1e-12))
                        score=float(rr+0.05*dist)
                        events.append(Event(symbol,entry_idx,int(d['open_time_ms'][entry_idx]),entry,side,float(stop),float(target),score,s,cand.family))
                    break
        elif cand.family=='outside_continuation':
            if open_side==0:
                continue
            consec=0
            max_end=i0+(i1-i0)//2
            for end_excl in range(i0+interval_bars, min(i1,max_end)+1, interval_bars):
                c=float(d['close'][end_excl-1])
                outside=(c>vah) if open_side>0 else (c<val)
                consec=consec+1 if outside else 0
                if consec>=cand.confirm_count:
                    entry_idx=end_excl
                    if entry_idx>=i1 or entry_idx>=len(d['open']):
                        break
                    entry=float(d['open'][entry_idx])
                    if open_side>0:
                        side=1; stop=vah-cand.stop_buffer*w; target=entry+cand.target_mult*w
                        rr=(target-entry)/(entry-stop) if entry>stop else -1
                    else:
                        side=-1; stop=val+cand.stop_buffer*w; target=entry-cand.target_mult*w
                        rr=(entry-target)/(stop-entry) if stop>entry else -1
                    if rr>0 and np.isfinite(rr):
                        dist=abs(entry-(vah if open_side>0 else val))/max(w,1e-12)
                        events.append(Event(symbol,entry_idx,int(d['open_time_ms'][entry_idx]),entry,side,float(stop),float(target),float(rr+0.05*dist),s,cand.family))
                    break
        elif cand.family=='poc_reaction':
            if abs(op-poc) < 0.25*w:
                continue
            approach=1 if op>poc else -1
            max_end=i0+(i1-i0)*3//4
            for j in range(i0,min(i1-1,max_end)):
                if d['low'][j] <= poc <= d['high'][j]:
                    entry_idx=j+1; entry=float(d['open'][entry_idx])
                    if approach>0 and entry>=poc:
                        side=1; stop=poc-cand.stop_buffer*w; target=entry+cand.target_mult*w
                        rr=(target-entry)/(entry-stop) if entry>stop else -1
                    elif approach<0 and entry<=poc:
                        side=-1; stop=poc+cand.stop_buffer*w; target=entry-cand.target_mult*w
                        rr=(entry-target)/(stop-entry) if stop>entry else -1
                    else:
                        rr=-1
                    if rr>0 and np.isfinite(rr):
                        events.append(Event(symbol,entry_idx,int(d['open_time_ms'][entry_idx]),entry,side,float(stop),float(target),float(rr),s,cand.family))
                    break
        else:
            raise ValueError(cand.family)
    return events


def trade_exit(d, ev:Event, end_ms:int):
    n=len(d['open_time_ms'])
    for j in range(ev.entry_idx,n):
        t=int(d['open_time_ms'][j])
        if t>=end_ms:
            break
        o,h,l,c=map(float,(d['open'][j],d['high'][j],d['low'][j],d['close'][j]))
        if ev.side>0:
            if o<=ev.stop:
                return j,t,o,'gap_stop'
            if o>=ev.target:
                return j,t,ev.target,'gap_target_conservative'
            hit_stop=l<=ev.stop; hit_target=h>=ev.target
            if hit_stop:
                return j,t,ev.stop,'stop'
            if hit_target:
                return j,t,ev.target,'target'
        else:
            if o>=ev.stop:
                return j,t,o,'gap_stop'
            if o<=ev.target:
                return j,t,ev.target,'gap_target_conservative'
            hit_stop=h>=ev.stop; hit_target=l<=ev.target
            if hit_stop:
                return j,t,ev.stop,'stop'
            if hit_target:
                return j,t,ev.target,'target'
    j=int(np.searchsorted(d['open_time_ms'],end_ms,side='left')-1)
    j=max(ev.entry_idx,min(j,n-1))
    return j,int(d['open_time_ms'][j]),float(d['close'][j]),'evaluation_mtm'


def simulate(data, events:list[Event], start_ms:int, end_ms:int, roundtrip_bps:float=12.0, rho:float=.005, max_leverage:float=5.0, initial_nav:float=10000.0):
    evs=[e for e in events if start_ms<=e.entry_time_ms<end_ms]
    evs.sort(key=lambda e:(e.entry_time_ms,-e.score,e.symbol))
    nav=initial_nav; free_ms=start_ms; trades=[]; nav_points=[(start_ms,nav)]
    i=0
    side_fee=roundtrip_bps/20000.0
    while i<len(evs):
        t=evs[i].entry_time_ms
        group=[]
        while i<len(evs) and evs[i].entry_time_ms==t:
            group.append(evs[i]); i+=1
        if t<free_ms:
            continue
        ev=max(group,key=lambda e:(e.score,e.symbol))
        per_unit_loss=abs(ev.entry_price-ev.stop)+ev.entry_price*side_fee+ev.stop*side_fee
        if per_unit_loss<=0 or not np.isfinite(per_unit_loss):
            continue
        qty=nav*rho/per_unit_loss
        max_qty=nav*max_leverage/ev.entry_price
        qty=min(qty,max_qty)
        if qty<=0:
            continue
        nav_before=nav
        entry_fee=qty*ev.entry_price*side_fee
        nav_after_entry=nav-entry_fee
        d=data[ev.symbol]
        exit_idx,exit_t,exit_px,reason=trade_exit(d,ev,end_ms)
        for j in range(ev.entry_idx,exit_idx+1):
            px=float(d['close'][j])
            mtm=nav_after_entry+ev.side*qty*(px-ev.entry_price)-qty*px*side_fee
            nav_points.append((int(d['open_time_ms'][j]),mtm))
        exit_fee=qty*exit_px*side_fee
        gross=ev.side*qty*(exit_px-ev.entry_price)
        nav=nav_after_entry+gross-exit_fee
        net=nav-nav_before
        r=net/nav_before
        trades.append({
            'symbol':ev.symbol,'family':ev.family,'entry_time_ms':ev.entry_time_ms,'exit_time_ms':exit_t,
            'entry':ev.entry_price,'exit':exit_px,'side':ev.side,'stop':ev.stop,'target':ev.target,
            'reason':reason,'qty':qty,'notional':qty*ev.entry_price,'leverage':qty*ev.entry_price/nav_before,
            'net_pnl':net,'account_return':r,'holding_bars':exit_idx-ev.entry_idx+1,
            'holding_hours':(exit_t-ev.entry_time_ms)/3600000.0,'nav_before':nav_before,'nav_after':nav,
            'score':ev.score,
        })
        nav_points.append((exit_t,nav))
        free_ms=exit_t+BAR_MS
        if nav<=0:
            break
    days=max(1,int((end_ms-start_ms)//86400000))
    gdg=(nav/initial_nav)**(1/days)-1 if nav>0 else -1.0
    n=len(trades)
    arr=np.array([x['account_return'] for x in trades],float) if n else np.array([],float)
    pnl=np.array([x['net_pnl'] for x in trades],float) if n else np.array([],float)
    positive=pnl[pnl>0]; negative=pnl[pnl<0]
    pf=float(positive.sum()/(-negative.sum())) if len(negative) and len(positive) else (float('inf') if len(positive) else 0.0)
    navvals=np.array([x[1] for x in sorted(nav_points,key=lambda x:x[0])],float)
    peaks=np.maximum.accumulate(navvals)
    mdd=float(np.max(1-navvals/peaks)) if len(navvals) else 0.0
    top5_share=float(np.sort(positive)[-5:].sum()/positive.sum()) if len(positive) else 1.0
    if n:
        remove=max(1,math.ceil(n*.10))
        order=np.argsort(arr)[::-1]
        keep=np.ones(n,dtype=bool)
        pos_order=[idx for idx in order if arr[idx]>0][:remove]
        keep[pos_order]=False
        top10_removed=float(np.prod(1+arr[keep])-1)
    else:
        top10_removed=0.0
    df=pd.DataFrame(trades)
    pos_month_frac=np.nan; worst_month=np.nan
    if n:
        dt=pd.to_datetime(df.entry_time_ms,unit='ms',utc=True)
        df['dt']=dt
        df['yearhalf']=dt.dt.year.astype(str)+'H'+np.where(dt.dt.month<=6,'1','2')
        half={k:float(np.prod(1+g.account_return.to_numpy())-1) for k,g in df.groupby('yearhalf')}
        df['month']=dt.dt.tz_localize(None).dt.to_period('M').astype(str)
        monthly=np.array([np.prod(1+g.account_return.to_numpy())-1 for _,g in df.groupby('month')])
        pos_month_frac=float(np.mean(monthly>0)) if len(monthly) else np.nan
        worst_month=float(np.min(monthly)) if len(monthly) else np.nan
    else:
        half={}
    return {
        'initial_nav':initial_nav,'final_nav':float(nav),'total_return':float(nav/initial_nav-1),
        'geometric_daily_growth':float(gdg),'maximum_drawdown':mdd,'trade_count':n,'profit_factor':pf,
        'median_account_return_bps':float(np.median(arr)*10000) if n else np.nan,
        'mean_account_return_bps':float(np.mean(arr)*10000) if n else np.nan,
        'win_rate':float(np.mean(arr>0)) if n else np.nan,'top5_positive_share':top5_share,
        'top10pct_removed_return':top10_removed,'positive_month_fraction':pos_month_frac,
        'worst_month':worst_month,'half_returns':half,
        'median_holding_hours':float(np.median([x['holding_hours'] for x in trades])) if n else np.nan,
        'p95_holding_hours':float(np.quantile([x['holding_hours'] for x in trades],.95)) if n else np.nan,
        'max_holding_hours':float(np.max([x['holding_hours'] for x in trades])) if n else np.nan,
        'max_leverage_used':float(np.max([x['leverage'] for x in trades])) if n else 0.0,
        'trades':trades,
    }


def candidate_grid():
    out=[]
    for sh,cm,cc,tm,sb in itertools.product([8,24],[15,30],[1,2],['poc','opposite_va'],[.05,.15]):
        out.append(Candidate('outside_rotation',sh,32,cm,cc,tm,sb,1.0))
    for sh,cm,cc,tm,sb in itertools.product([8,24],[15,30],[1,2],[.5,1.0],[0.0,.10]):
        out.append(Candidate('outside_continuation',sh,32,cm,cc,'extension',sb,tm))
    for sh,tm,sb in itertools.product([8,24],[.5,1.0],[.10,.25]):
        out.append(Candidate('poc_reaction',sh,32,30,1,'reaction',sb,tm))
    return out


def main():
    snapshot=Path(__import__('os').environ.get('AUCTION_PROFILE_SNAPSHOT','snapshot'))
    data=load_data(snapshot)
    start=pd.Timestamp('2023-01-01',tz='UTC').value//1_000_000
    end=pd.Timestamp('2024-01-01',tz='UTC').value//1_000_000
    rows=[]
    for k,c in enumerate(candidate_grid(),1):
        events=[]
        for sym in SYMBOLS:
            events += generate_events(data[sym],sym,c)
        metrics={}
        for bps in (12.,18.,24.):
            r=simulate(data,events,start,end,bps)
            metrics[str(int(bps))]={key:value for key,value in r.items() if key!='trades'}
        row={'candidate_id':c.id,**asdict(c),'event_count_all':len(events),'metrics':metrics}
        rows.append(row)
        if k%10==0:
            print(k,c.id,c.family,c.session_hours,metrics['12']['trade_count'],metrics['12']['geometric_daily_growth'],metrics['24']['geometric_daily_growth'])
    outdir=Path(__import__('os').environ.get('AUCTION_PROFILE_OUTPUT','results'))
    outdir.mkdir(parents=True,exist_ok=True)
    (outdir/'development.json').write_text(json.dumps(rows,indent=2,sort_keys=True,default=str))
    flat=[]
    for r in rows:
        x={key:value for key,value in r.items() if key!='metrics'}
        for b,m in r['metrics'].items():
            for key,val in m.items():
                if key!='half_returns':
                    x[f'{key}_{b}bps']=val
            for hk,hv in m.get('half_returns',{}).items():
                x[f'{hk}_{b}bps']=hv
        flat.append(x)
    pd.DataFrame(flat).to_csv(outdir/'development.csv',index=False)
    columns=['candidate_id','family','session_hours','confirm_minutes','confirm_count','target_mode','stop_buffer','target_mult','trade_count_12bps','geometric_daily_growth_12bps','geometric_daily_growth_24bps','top10pct_removed_return_12bps','median_account_return_bps_12bps','maximum_drawdown_12bps']
    print(pd.DataFrame(flat).sort_values('geometric_daily_growth_12bps',ascending=False)[columns].head(20).to_string(index=False))

if __name__=='__main__':
    main()
