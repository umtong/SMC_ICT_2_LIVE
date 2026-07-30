from __future__ import annotations
from pathlib import Path
import math
import numpy as np
import pandas as pd

ROOT=Path('/mnt/data/work/canonical')
OUT=Path('/mnt/data/work/auction_value')


def profile_one(day: pd.DataFrame, log_step: float, value_fraction: float) -> dict:
    lo=np.log(day['low'].to_numpy(float)); hi=np.log(day['high'].to_numpy(float)); turn=day['turnover'].to_numpy(float)
    base=math.floor(float(np.nanmin(lo))/log_step)*log_step
    top=math.ceil(float(np.nanmax(hi))/log_step)*log_step
    n=max(3,int(round((top-base)/log_step))+1)
    li=np.floor((lo-base)/log_step).astype(int).clip(0,n-1)
    ui=np.floor((hi-base)/log_step).astype(int).clip(0,n-1)
    width=(ui-li+1).clip(1)
    val=np.nan_to_num(turn/width,nan=0.0,posinf=0.0,neginf=0.0)
    diff=np.zeros(n+1,float)
    np.add.at(diff,li,val); np.add.at(diff,ui+1,-val)
    prof=np.cumsum(diff[:-1]); total=float(prof.sum())
    if not np.isfinite(total) or total<=0: raise ValueError('empty profile')
    poc=int(np.nanargmax(prof)); left=right=poc; accum=float(prof[poc])
    while accum < value_fraction*total and (left>0 or right<n-1):
        lv=prof[left-1] if left>0 else -1.0; rv=prof[right+1] if right<n-1 else -1.0
        if rv>lv: right+=1;accum+=float(prof[right])
        else: left-=1;accum+=float(prof[left])
    centers=np.exp(base+(np.arange(n)+.5)*log_step)
    pocv=max(float(prof[poc]),1e-12)
    lower=prof[:left] if left>0 else np.array([],float); upper=prof[right+1:] if right+1<n else np.array([],float)
    def seg_stats(seg):
        return (float(seg.mean()/pocv),float(seg.min()/pocv),float(seg.max()/pocv)) if len(seg) else (np.nan,np.nan,np.nan)
    lmean,lmin,lmax=seg_stats(lower);umean,umin,umax=seg_stats(upper)
    p=prof/total; entropy=float(-(p[p>0]*np.log(p[p>0])).sum()/max(np.log(len(p)),1e-9))
    above=float(prof[poc+1:].sum());below=float(prof[:poc].sum())
    return {
      'profile_low':float(np.exp(base)), 'profile_high':float(np.exp(base+n*log_step)),
      'poc':float(centers[poc]), 'val':float(np.exp(base+left*log_step)), 'vah':float(np.exp(base+(right+1)*log_step)),
      'poc_density':pocv, 'value_fraction_observed':accum/total, 'profile_entropy':entropy,
      'profile_skew':(above-below)/total, 'poc_position':poc/max(n-1,1),
      'lower_corridor_mean_ratio':lmean,'lower_corridor_min_ratio':lmin,'lower_corridor_max_ratio':lmax,
      'upper_corridor_mean_ratio':umean,'upper_corridor_min_ratio':umin,'upper_corridor_max_ratio':umax,
      'lower_node':float(centers[int(np.argmax(lower))]) if len(lower) else np.nan,
      'upper_node':float(centers[right+1+int(np.argmax(upper))]) if len(upper) else np.nan,
      'bin_count':n,'log_step':log_step,'value_fraction':value_fraction,
      'prev_open':float(day.open.iloc[0]),'prev_high':float(day.high.max()),'prev_low':float(day.low.min()),'prev_close':float(day.close.iloc[-1]),
      'prev_vwap':float(day.turnover.sum()/day.volume.sum()),'prev_turnover':float(day.turnover.sum()),
    }


def build_symbol(short: str, log_step: float=.0005, value_fraction: float=.70) -> pd.DataFrame:
    parts=[]
    for y in (2021,2022,2023):
        p=ROOT/f'{short}{y}'/'trade_bars/1m.parquet'
        d=pd.read_parquet(p,columns=['start_time_ms','observed','open','high','low','close','volume','turnover'])
        d=d[d.observed].copy();d['date']=pd.to_datetime(d.start_time_ms,unit='ms',utc=True).dt.floor('D')
        parts.append(d)
    d=pd.concat(parts,ignore_index=True).sort_values('start_time_ms')
    rows=[]
    for date,g in d.groupby('date',sort=True):
        if len(g)<1200: continue
        r=profile_one(g,log_step,value_fraction);r['source_date']=date;r['date']=date+pd.Timedelta(days=1);r['symbol']=short+'USDT';rows.append(r)
    return pd.DataFrame(rows)

if __name__=='__main__':
    frames=[]
    for step in (.0005,.0010):
      for vf in (.70,.80):
       for short in ('BTC','ETH'):
        x=build_symbol(short,step,vf);frames.append(x);print(short,step,vf,len(x),flush=True)
    out=pd.concat(frames,ignore_index=True);out.to_parquet(OUT/'daily_profiles.parquet',index=False)
    print(out.groupby(['symbol','log_step','value_fraction']).size())
