from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd

from direct_core_common import (
    BASE_COST_RT, NOTIONAL_CAP, RESULT_DIR, RISK_FRACTION, SCORE_DIR, SYMS,
    TAKER, YEAR_BOUNDS, load_funding, load_minute_market, ts_ms,
)

Q_GRID = (0.90,0.925,0.95,0.96,0.97,0.975,0.98,0.985,0.99,0.9925,0.995)
COST_GRID = (0.0015,0.0018,0.0024)


def slip_for_total_cost(total_cost_rt: float) -> float:
    slip = (total_cost_rt - 2*TAKER)/2
    if slip < 0:
        raise ValueError('total cost is below two taker fees')
    return slip


def load_scores(years: Iterable[int]) -> pd.DataFrame:
    parts=[pd.read_parquet(SCORE_DIR/f'scores_outcomes_{y}.parquet') for y in years]
    return pd.concat(parts,ignore_index=True).sort_values(['decision_ms','u'],ascending=[True,False]).reset_index(drop=True)


def candidate_financial(row, total_cost_rt: float, nav_before: float):
    slip=slip_for_total_cost(total_cost_rt)
    side=int(row.side)
    entry_fill=float(row.entry_raw)*(1+side*slip)
    stop_fill=float(row.stop_raw)*(1-side*slip)
    unit_loss=abs(entry_fill-stop_fill)+entry_fill*TAKER+stop_fill*TAKER
    qty_per_nav=min(RISK_FRACTION/unit_loss,NOTIONAL_CAP/entry_fill)
    qty=nav_before*qty_per_nav
    if bool(row.resolved):
        exit_fill=float(row.exit_raw)*(1-side*slip)
        net_unit=side*(exit_fill-entry_fill)-entry_fill*TAKER-exit_fill*TAKER+float(row.funding_unit)
        ret_frac=qty_per_nav*net_unit
    else:
        exit_fill=np.nan;net_unit=np.nan;ret_frac=np.nan
    return {
        'entry_fill':entry_fill,'stop_fill':stop_fill,'unit_loss':unit_loss,
        'qty_per_nav':qty_per_nav,'qty':qty,'effective_risk_fraction':qty_per_nav*unit_loss,
        'effective_leverage':qty_per_nav*entry_fill,'exit_fill':exit_fill,
        'net_unit':net_unit,'ret_frac':ret_frac,
    }


def choose_at_decision(group: pd.DataFrame, q_threshold: float, forbidden: set[str]):
    z=group[(group.q>=q_threshold)&(group.u>0)]
    if forbidden:
        z=z[~z.candidate_id.isin(forbidden)]
    if z.empty:return None
    return z.sort_values(['u','q','symbol','side'],ascending=[False,False,True,False]).iloc[0]


def simulate_event_path(scores: pd.DataFrame,start: str,end: str,q_threshold: float,total_cost_rt: float=BASE_COST_RT,
                        forbidden: set[str] | None=None):
    forbidden=forbidden or set();s0=ts_ms(start);s1=ts_ms(end)
    s=scores[(scores.decision_ms>=s0)&(scores.decision_ms<s1)].copy()
    nav=10000.;next_entry_ms=s0;trades=[];open_row=None
    eligible=s[(s.q>=q_threshold)&(s.u>0)]
    if forbidden:
        eligible=eligible[~eligible.candidate_id.isin(forbidden)]
    if eligible.empty:
        return pd.DataFrame(),None
    # One action per decision is chosen before slot scheduling. Filtering first
    # ensures a forbidden winner is replaced by the next-best simultaneous
    # candidate rather than simply deleting the whole decision.
    eligible=(eligible.sort_values(['decision_ms','u','q','symbol','side'],ascending=[True,False,False,True,False])
                      .drop_duplicates('decision_ms',keep='first'))
    for r in eligible.itertuples(index=False):
        entry_ms=int(r.entry_ms)
        if entry_ms<next_entry_ms:continue
        fin=candidate_financial(r,total_cost_rt,nav)
        rec={
            'candidate_id':r.candidate_id,'decision_ms':int(r.decision_ms),'entry_ms':int(r.entry_ms),
            'exit_ms':int(r.exit_ms),'symbol':r.symbol,'side':int(r.side),'u':float(r.u),'q':float(r.q),
            'outcome':int(r.outcome),'resolved':bool(r.resolved),'entry_raw':float(r.entry_raw),
            'stop_raw':float(r.stop_raw),'target_raw':float(r.target_raw),'exit_raw':float(r.exit_raw) if bool(r.resolved) else np.nan,
            'funding_unit':float(r.funding_unit) if bool(r.resolved) else np.nan,
            'duration_min':int(r.duration_min),'nav_before':nav,**fin,
        }
        if (not bool(r.resolved)) or int(r.exit_ms)>=s1:
            rec['completed']=False;rec['net_pnl']=np.nan;rec['nav_after']=np.nan
            open_row=rec;trades.append(rec);break
        ret=float(fin['ret_frac']);nav_after=nav*(1+ret)
        rec['completed']=True;rec['net_pnl']=nav*ret;rec['nav_after']=nav_after
        trades.append(rec);nav=nav_after
        # Exit is detected during the exit minute. The earliest new order can be decided
        # at that minute's close and entered one further full minute later.
        next_entry_ms=int(r.exit_ms)+120_000
    return pd.DataFrame(trades),open_row


@dataclass
class MarketCache:
    market: dict[str,pd.DataFrame]
    funding_prefix: dict[str,np.ndarray]
    times: dict[str,np.ndarray]
    mark_close: dict[str,np.ndarray]


def load_market_cache(segs: Iterable[str]) -> MarketCache:
    market={};prefix={};times_cache={};mark_close={}
    for sym in SYMS:
        m=load_minute_market(sym,segs)
        f=load_funding(sym,segs)
        times=m.start_time_ms.to_numpy(np.int64);mark=m.mark_open.to_numpy(float)
        flow=np.zeros(len(m),float);fts=f.timestamp_ms.to_numpy(np.int64)
        idx=np.searchsorted(times,fts)
        clipped=np.minimum(idx,len(times)-1)
        ok=(idx<len(times))&(times[clipped]==fts)&np.isfinite(mark[clipped])
        flow[idx[ok]]+=-mark[idx[ok]]*f.funding_rate.to_numpy(float)[ok]
        market[sym]=m;prefix[sym]=np.cumsum(flow);times_cache[sym]=times
        mark_close[sym]=m.mark_close.to_numpy(float)
    return MarketCache(market,prefix,times_cache,mark_close)


def _minute_index_at_or_before(times:np.ndarray, mark_ms:int)->int:
    i=int(np.searchsorted(times,mark_ms))
    if i>=len(times) or times[i]!=mark_ms:
        i=max(0,min(len(times)-1,i-1))
    return i


def _fund_to(cache:MarketCache,sym:str,entry_ms:int,mark_ms:int,side:int)->float:
    times=cache.times[sym];p=cache.funding_prefix[sym]
    ei=int(np.searchsorted(times,entry_ms));mi=_minute_index_at_or_before(times,mark_ms)
    if ei>=len(times) or times[ei]!=entry_ms:raise RuntimeError('entry minute missing')
    return side*float(p[mi]-p[ei])


def liquidation_nav(nav_before:float,qty:float,entry_fill:float,entry_ms:int,mark_ms:int,sym:str,side:int,
                    cache:MarketCache,total_cost_rt:float)->float:
    times=cache.times[sym];i=_minute_index_at_or_before(times,mark_ms)
    mark=float(cache.mark_close[sym][i]);slip=slip_for_total_cost(total_cost_rt);liq=mark*(1-side*slip)
    entry_fee=qty*entry_fill*TAKER;exit_fee=qty*liq*TAKER
    fund=qty*_fund_to(cache,sym,entry_ms,int(times[i]),side)
    return nav_before-entry_fee+side*qty*(liq-entry_fill)-exit_fee+fund


def daily_and_mdd(trades:pd.DataFrame,start:str,end:str,cache:MarketCache,total_cost_rt:float):
    s0=ts_ms(start);s1=ts_ms(end);bounds=np.arange(((s0//86400000)+1)*86400000,s1+1,86400000,dtype=np.int64)
    daily=[];peak=10000.;mdd=0.;minute_points=0
    completed=trades[trades.completed].copy() if len(trades) else trades
    alltr=trades.sort_values('entry_ms').reset_index(drop=True) if len(trades) else trades
    # Daily marks.
    j=0;cash=10000.
    for b in bounds:
        while j<len(alltr) and bool(alltr.iloc[j].completed) and int(alltr.iloc[j].exit_ms)<b:
            cash=float(alltr.iloc[j].nav_after);j+=1
        if j<len(alltr) and int(alltr.iloc[j].entry_ms)<b and (not bool(alltr.iloc[j].completed) or int(alltr.iloc[j].exit_ms)>=b):
            r=alltr.iloc[j];nav=liquidation_nav(float(r.nav_before),float(r.qty),float(r.entry_fill),int(r.entry_ms),int(b-60000),r.symbol,int(r.side),cache,total_cost_rt)
        else:nav=cash
        daily.append((int(b),nav))
    # Intra-position liquidation-value MDD. A completed trade is marked only
    # through the minute before its barrier fill; the exact realized nav_after
    # then replaces the mark. This prevents treating the position as open after
    # it has already stopped or targeted inside the exit minute.
    peak=10000.;mdd=0.;slip=slip_for_total_cost(total_cost_rt)
    for r in alltr.itertuples(index=False):
        peak=max(peak,float(r.nav_before))
        times=cache.times[r.symbol];marks_all=cache.mark_close[r.symbol];pfx=cache.funding_prefix[r.symbol]
        a=int(np.searchsorted(times,int(r.entry_ms)))
        if a>=len(times) or times[a]!=int(r.entry_ms):
            raise RuntimeError('entry minute missing in market cache')
        last=(int(r.exit_ms)-60_000) if bool(r.completed) else (s1-60_000)
        z=_minute_index_at_or_before(times,last)
        if z>=a:
            for lo in range(a,z+1,20000):
                hi=min(z+1,lo+20000);marks=marks_all[lo:hi]
                liq=marks*(1-int(r.side)*slip)
                entry_fee=float(r.qty)*float(r.entry_fill)*TAKER;exit_fee=float(r.qty)*liq*TAKER
                fund=float(r.qty)*int(r.side)*(pfx[lo:hi]-pfx[a])
                nav=float(r.nav_before)-entry_fee+int(r.side)*float(r.qty)*(liq-float(r.entry_fill))-exit_fee+fund
                running=np.maximum.accumulate(np.r_[peak,nav])[1:];dd=nav/running-1
                if len(dd):mdd=min(mdd,float(dd.min()));peak=max(peak,float(nav.max()))
                minute_points+=len(nav)
        if bool(r.completed):
            realized=float(r.nav_after);mdd=min(mdd,realized/peak-1);peak=max(peak,realized)
    day=pd.DataFrame(daily,columns=['timestamp_ms','nav'])
    return day,mdd,minute_points


def metrics(trades:pd.DataFrame,day:pd.DataFrame,start:str,end:str,mdd:float):
    days=(pd.Timestamp(end)-pd.Timestamp(start)).days;endnav=float(day.nav.iloc[-1]) if len(day) else 10000.;multiple=endnav/10000.;res={
        'start':start,'end':end,'calendar_days':days,'end_nav':endnav,'multiple':multiple,
        'geo_daily':multiple**(1/days)-1 if multiple>0 else -1,'maximum_drawdown':mdd,
        'trades':int(trades.completed.sum()) if len(trades) else 0,'open_position':bool(len(trades) and not bool(trades.iloc[-1].completed)),
    }
    z=trades[trades.completed].copy() if len(trades) else pd.DataFrame()
    if len(z):
        pos=z.net_pnl>0;psum=float(z.loc[pos,'net_pnl'].sum());
        res.update({
            'win_rate':float(pos.mean()),'mean_return_fraction':float((z.net_pnl/z.nav_before).mean()),
            'mean_net_r':float((z.net_pnl/(z.nav_before*z.effective_risk_fraction)).mean()),
            'profit_factor':float(z.loc[pos,'net_pnl'].sum()/-z.loc[~pos,'net_pnl'].sum()) if (~pos).any() else np.inf,
            'median_holding_min':float(z.duration_min.median()),'mean_holding_min':float(z.duration_min.mean()),
            'active_time_fraction':float(z.duration_min.sum()/(days*1440)),
            'max_effective_leverage':float(z.effective_leverage.max()),
            'top1_positive_share':float(z.nlargest(1,'net_pnl').net_pnl.sum()/psum) if psum>0 else np.nan,
            'top5_positive_share':float(z.nlargest(min(5,len(z)),'net_pnl').net_pnl.sum()/psum) if psum>0 else np.nan,
            'top10_positive_share':float(z.nlargest(min(10,len(z)),'net_pnl').net_pnl.sum()/psum) if psum>0 else np.nan,
            'r_lag1_autocorr':float(z.net_pnl.corr(z.net_pnl.shift(1))) if len(z)>2 else np.nan,
        })
    return res


def halfyear_table(day:pd.DataFrame,trades:pd.DataFrame):
    periods=[('2024H1','2024-01-01','2024-07-01'),('2024H2','2024-07-01','2025-01-01'),('2025H1','2025-01-01','2025-07-01'),('2025H2','2025-07-01','2026-01-01'),('2026H1','2026-01-01','2026-07-01')]
    rows=[]
    for label,a,b in periods:
        a_ms=ts_ms(a);b_ms=ts_ms(b);start_nav=10000. if a=='2024-01-01' else float(day[day.timestamp_ms<=a_ms].nav.iloc[-1]);end_nav=float(day[day.timestamp_ms<=b_ms].nav.iloc[-1]);days=(pd.Timestamp(b)-pd.Timestamp(a)).days
        z=trades[(trades.entry_ms>=a_ms)&(trades.entry_ms<b_ms)&trades.completed]
        rows.append({'period':label,'start_nav':start_nav,'end_nav':end_nav,'return':end_nav/start_nav-1,'geo_daily':(end_nav/start_nav)**(1/days)-1,'trades':len(z),'pnl':float(z.net_pnl.sum())})
    return pd.DataFrame(rows)


def concentration_tables(trades:pd.DataFrame):
    z=trades[trades.completed].copy();z['exit_time']=pd.to_datetime(z.exit_ms,unit='ms',utc=True);z['month']=z.exit_time.dt.to_period('M').astype(str);z['symbol_side']=z.symbol+np.where(z.side>0,':LONG',':SHORT')
    monthly=z.groupby('month').agg(trades=('net_pnl','size'),pnl=('net_pnl','sum'),positive=('net_pnl',lambda x:float(x[x>0].sum())),negative=('net_pnl',lambda x:float(x[x<0].sum()))).reset_index()
    groups=z.groupby('symbol_side').agg(
        trades=('net_pnl','size'),pnl=('net_pnl','sum'),
        mean_r=('net_pnl',lambda x:float((x/(z.loc[x.index,'nav_before']*z.loc[x.index,'effective_risk_fraction'])).mean()))
    ).reset_index()
    return monthly,groups


def exact_reroute(scores,start,end,q,total_cost_rt,base_trades,k):
    z=base_trades[base_trades.completed & (base_trades.net_pnl>0)].nlargest(min(k,int((base_trades.net_pnl>0).sum())),'net_pnl')
    forbidden=set(z.candidate_id)
    return simulate_event_path(scores,start,end,q,total_cost_rt,forbidden)[0],forbidden
