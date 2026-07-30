#!/usr/bin/env python3
from __future__ import annotations

import argparse, hashlib, json, math, os, shutil, sys, zipfile
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd

ROOT = Path(os.environ.get('SMC_ICT_ROOT', '/mnt/data'))
if not ROOT.exists() or not os.access(ROOT, os.W_OK):
    ROOT = Path.cwd()
WORK = Path(os.environ.get('TURNOVER_TIME_WORK', str(ROOT / 'turnover_time_sponsored_core')))
CACHE = WORK / 'cache'
DEFAULT_OUT = WORK / 'result'
OUT = DEFAULT_OUT
for p in (CACHE, OUT):
    p.mkdir(parents=True, exist_ok=True)
REPO_ROOT = Path(os.environ.get('SMC_ICT_REPO_ROOT', str(ROOT / 'smc_work' / 'repo')))
if REPO_ROOT.exists():
    sys.path.insert(0, str(REPO_ROOT))
try:
    from scripts.market_data.minimal_parquet_numeric import read_parquet_numeric
except ModuleNotFoundError:
    read_parquet_numeric = None

SYMBOLS = ('BTCUSDT','ETHUSDT')
YEARS_PRE = (2021,2022)
SPONSOR_Z = 2.2706072565238586
DAY_MS=86_400_000
MIN_MS=60_000
HOUR_MS=3_600_000
COSTS=(0,12,18,24)

@dataclass
class Event:
    event_key:str; symbol:str; side:int; packet_idx:int; decision_ms:int; entry_idx:int
    entry_ms:int; entry:float; stop:float; target:float; boundary:float; atr:float
    intensity_z:float; displacement_atr:float; state_exec_idx:int|None; state_exec_ms:int|None
    outcome_end_idx:int; outcome_end_ms:int; outcome_price:float; outcome_reason:str
    funding_per_unit:float; year:int


def sha(path:Path)->str:
    h=hashlib.sha256()
    with path.open('rb') as f:
        for b in iter(lambda:f.read(1<<20),b''): h.update(b)
    return h.hexdigest()


def archives(symbol:str, year:int)->Path:
    return ROOT / f'DS-BYBIT-LINEAR-{symbol}-PRE_2024_{year}-CANONICAL-V1.zip'


def extract(symbol:str, year:int)->Path:
    dest=CACHE/f'{symbol}_{year}'
    need=['streams/trade_price_1m.parquet','streams/mark_price_1m.parquet','streams/funding_events.parquet','DATASET_MANIFEST.json']
    if not all((dest/x).exists() for x in need):
        dest.mkdir(parents=True,exist_ok=True)
        with zipfile.ZipFile(archives(symbol,year)) as z:
            for x in need: z.extract(x,dest)
    return dest


def load_symbol(symbol:str)->tuple[pd.DataFrame,pd.DataFrame]:
    if read_parquet_numeric is None:
        raise RuntimeError('shared minimal_parquet_numeric loader is unavailable; set SMC_ICT_REPO_ROOT')
    frames=[]; funds=[]
    for year in YEARS_PRE:
        d=extract(symbol,year)
        tr=read_parquet_numeric(d/'streams/trade_price_1m.parquet', ['start_time_ms','observed','open','high','low','close','volume','turnover','available_at_ms'])
        mk=read_parquet_numeric(d/'streams/mark_price_1m.parquet', ['start_time_ms','observed','open'])
        tr=tr.merge(mk.rename(columns={'observed':'mark_observed','open':'mark_open'}),on='start_time_ms',how='left',validate='one_to_one')
        tr['symbol']=symbol
        frames.append(tr)
        fu=read_parquet_numeric(d/'streams/funding_events.parquet',['timestamp_ms','funding_rate','available_at_ms'])
        fu['symbol']=symbol; funds.append(fu)
    x=pd.concat(frames,ignore_index=True).sort_values('start_time_ms').reset_index(drop=True)
    f=pd.concat(funds,ignore_index=True).sort_values('timestamp_ms').drop_duplicates('timestamp_ms').reset_index(drop=True)
    mark_map=x.set_index('start_time_ms')['mark_open']
    f['mark_open']=f['timestamp_ms'].map(mark_map)
    f['cash_coeff']=(f['funding_rate']*f['mark_open']).fillna(0.0)
    f['cum_coeff']=f['cash_coeff'].cumsum()
    assert x['start_time_ms'].is_monotonic_increasing
    return x,f


def build_packets(x:pd.DataFrame, symbol:str)->pd.DataFrame:
    valid=x['observed'].fillna(False)&x['mark_observed'].fillna(False)
    x=x.copy(); x['valid']=valid
    x['hour']=x.start_time_ms//HOUR_MS
    hg=x.groupby('hour',sort=True).agg(n=('valid','size'),ok=('valid','sum'),turnover=('turnover','sum'))
    full=hg.turnover.where((hg.n==60)&(hg.ok==60))
    all_hours=pd.RangeIndex(int(x.hour.min()),int(x.hour.max())+1)
    full=full.reindex(all_hours)
    med168=full.rolling(168,min_periods=168).median()
    x['day']=x.start_time_ms//DAY_MS
    day_ids=np.sort(x.day.unique())
    target_by_day={int(d):float(med168.get(int(d*24-1),np.nan)) for d in day_ids}
    rec=[]
    for day,g in x.groupby('day',sort=True):
        target=target_by_day.get(int(day),np.nan)
        if not np.isfinite(target) or target<=0 or len(g)!=1440 or int(g.valid.sum())!=1440: continue
        idxs=g.index.to_numpy(); acc=0.0; start=None
        for idx in idxs:
            if start is None: start=idx; acc=0.0
            acc+=float(x.at[idx,'turnover'])
            if acc>=target:
                sl=x.loc[start:idx]
                rec.append(dict(symbol=symbol,day=int(day),start_idx=int(start),end_idx=int(idx),
                    start_ms=int(sl.start_time_ms.iloc[0]),available_at_ms=int(sl.available_at_ms.iloc[-1]),
                    open=float(sl.open.iloc[0]),high=float(sl.high.max()),low=float(sl.low.min()),close=float(sl.close.iloc[-1]),
                    turnover=float(sl.turnover.sum()),duration_minutes=int(len(sl)),target_turnover=float(target)))
                start=None; acc=0.0
    p=pd.DataFrame(rec)
    if p.empty: return p
    p=p.sort_values('available_at_ms').reset_index(drop=True)
    prev=p.close.shift(1)
    p['true_range']=np.maximum.reduce([(p.high-p.low).to_numpy(),(p.high-prev).abs().to_numpy(),(p.low-prev).abs().to_numpy()])
    p['atr20']=p.true_range.shift(1).rolling(20,min_periods=20).mean()
    p['intensity']=np.log1p(p.turnover/p.duration_minutes)
    pm=p.intensity.shift(1).rolling(168,min_periods=168).mean(); ps=p.intensity.shift(1).rolling(168,min_periods=168).std(ddof=0)
    p['intensity_z']=(p.intensity-pm)/ps.replace(0,np.nan)
    p['ext96_high']=p.high.shift(1).rolling(96,min_periods=96).max(); p['ext96_low']=p.low.shift(1).rolling(96,min_periods=96).min()
    p['opp48_high']=p.high.shift(1).rolling(48,min_periods=48).max(); p['opp48_low']=p.low.shift(1).rolling(48,min_periods=48).min()
    p['year']=pd.to_datetime(p.available_at_ms,unit='ms',utc=True).dt.year
    return p


def funding_per_unit(funds:pd.DataFrame, marks:pd.DataFrame|None, side:int, entry_ms:int, exit_ms:int)->float:
    if funds.empty or exit_ms<=entry_ms:return 0.0
    ts=funds.timestamp_ms.to_numpy(np.int64); cum=funds.cum_coeff.to_numpy(float)
    hi=int(np.searchsorted(ts,exit_ms,side='right')-1)
    lo=int(np.searchsorted(ts,entry_ms,side='right')-1)
    if hi<0 or hi<=lo:return 0.0
    gross=cum[hi]-(cum[lo] if lo>=0 else 0.0)
    return float(-side*gross)


def generate_events(x:pd.DataFrame,p:pd.DataFrame,funds:pd.DataFrame)->list[Event]:
    events=[]
    starts=x.start_time_ms.to_numpy(np.int64); n=len(x)
    for i,r in p.iterrows():
        if int(r.year) not in YEARS_PRE or not np.isfinite(r.intensity_z) or r.intensity_z<SPONSOR_Z or not np.isfinite(r.atr20): continue
        both=bool(r.high>r.ext96_high and r.low<r.ext96_low)
        side=1 if r.close>r.ext96_high else (-1 if r.close<r.ext96_low else 0)
        if side==0 or both: continue
        boundary=float(r.ext96_high if side==1 else r.ext96_low)
        activation=int(r.available_at_ms)+500
        entry_idx=int(np.searchsorted(starts,activation,side='right'))
        if entry_idx>=n: continue
        entry_ms=int(starts[entry_idx]); entry=float(x.open.iloc[entry_idx])
        atr=float(r.atr20); stop=entry-side*2*atr; target=entry+side*3*atr
        if not ((stop<entry<target) if side==1 else (target<entry<stop)): continue
        state_idx=None; state_exec_idx=None; state_exec_ms=None
        for j in range(i+1,len(p)):
            q=p.iloc[j]
            if side==1 and np.isfinite(q.opp48_low) and q.close<q.opp48_low: state_idx=j
            elif side==-1 and np.isfinite(q.opp48_high) and q.close>q.opp48_high: state_idx=j
            else: continue
            state_activation=int(q.available_at_ms)+500
            state_exec_idx=int(np.searchsorted(starts,state_activation,side='right'))
            if state_exec_idx<n: state_exec_ms=int(starts[state_exec_idx])
            break
        end_idx=n-1; price=float(x.close.iloc[-1]); reason='boundary_mark'
        for k in range(entry_idx,n):
            o=float(x.open.iloc[k]); h=float(x.high.iloc[k]); l=float(x.low.iloc[k])
            if side==1 and o<=stop: end_idx=k; price=o; reason='stop_gap'; break
            if side==-1 and o>=stop: end_idx=k; price=o; reason='stop_gap'; break
            if state_exec_idx is not None and k>=state_exec_idx:
                end_idx=k; price=o; reason='state_loss'; break
            if side==1:
                hit_s=l<=stop; hit_t=h>=target
            else:
                hit_s=h>=stop; hit_t=l<=target
            if hit_s: end_idx=k; price=stop; reason='stop'; break
            if hit_t: end_idx=k; price=target; reason='target'; break
        end_ms=int(starts[end_idx])
        fpu=funding_per_unit(funds,x[['start_time_ms','mark_open']],side,entry_ms,end_ms)
        disp=side*(float(r.close)-boundary)/atr if atr>0 else np.nan
        key=f"{r.symbol}|{int(r.available_at_ms)}|{side}|{i}"
        events.append(Event(key,str(r.symbol),side,int(i),int(r.available_at_ms),entry_idx,entry_ms,entry,stop,target,boundary,atr,float(r.intensity_z),float(disp),state_exec_idx,state_exec_ms,end_idx,end_ms,price,reason,fpu,int(r.year)))
    return events


def replay(events:list[Event],xmap:dict[str,pd.DataFrame],fmap:dict[str,pd.DataFrame],cost_bp:int,year:int,remove:set[str]|None=None)->tuple[pd.DataFrame,dict,pd.DataFrame]:
    remove=remove or set(); cand=[e for e in events if e.year==year and e.event_key not in remove]
    cand=sorted(cand,key=lambda e:(e.entry_ms,-e.intensity_z,-e.displacement_atr,0 if e.symbol=='BTCUSDT' else 1))
    year_start_ms=int(pd.Timestamp(f'{year}-01-01',tz='UTC').timestamp()*1000)
    year_end_ms=int(pd.Timestamp(f'{year+1}-01-01',tz='UTC').timestamp()*1000)-1
    nav=10000.0; free_ms=year_start_ms; trades=[]
    for e in cand:
        if e.entry_ms<free_ms or e.entry_ms>year_end_ms: continue
        risk_budget=.005*nav; cost=e.entry*cost_bp/10000; reserve=e.entry*.0002
        per_loss=abs(e.entry-e.stop)+cost+reserve
        qty=min(risk_budget/per_loss,3*nav/e.entry) if per_loss>0 else 0
        if qty<=0: continue
        completed=e.outcome_reason!='boundary_mark' and e.outcome_end_ms<=year_end_ms
        if completed:
            exit_ms=e.outcome_end_ms; exit_price=e.outcome_price
            reason=e.outcome_reason; fpu=e.funding_per_unit
        else:
            sx=xmap[e.symbol]
            starts=sx.start_time_ms.to_numpy(np.int64)
            j=int(np.searchsorted(starts,year_end_ms,side='right')-1)
            if j<e.entry_idx: continue
            exit_ms=int(starts[j]); exit_price=float(sx.close.iloc[j])
            reason='boundary_mark'
            fpu=funding_per_unit(fmap[e.symbol],sx[['start_time_ms','mark_open']],e.side,e.entry_ms,year_end_ms)
        price_pu=e.side*(exit_price-e.entry); pnl=qty*(price_pu+fpu-cost)
        ret=pnl/nav; nav_before=nav; nav=max(0.0,nav+pnl)
        trades.append(dict(event_key=e.event_key,symbol=e.symbol,side=e.side,entry_ms=e.entry_ms,exit_ms=exit_ms,
            entry=e.entry,exit=exit_price,stop=e.stop,target=e.target,intensity_z=e.intensity_z,displacement_atr=e.displacement_atr,
            reason=reason,funding_per_unit=fpu,quantity=qty,nav_before=nav_before,nav_after=nav,account_return=ret,completed=completed))
        free_ms=exit_ms+1 if completed else 10**30
    t=pd.DataFrame(trades)
    dates=pd.date_range(f'{year}-01-01',f'{year}-12-31',freq='D',tz='UTC')
    daily=[]; realized=10000.0; ti=0
    rows=t.to_dict('records') if not t.empty else []
    for day in dates:
        end_ms=int((day+pd.Timedelta(days=1)).timestamp()*1000)-1
        while ti<len(rows) and rows[ti]['exit_ms']<=end_ms and rows[ti]['completed']:
            realized=rows[ti]['nav_after']; ti+=1
        val=realized
        if ti<len(rows):
            tr=rows[ti]
            if tr['entry_ms']<=end_ms<tr['exit_ms'] or (not tr['completed'] and tr['entry_ms']<=end_ms):
                sx=xmap[tr['symbol']]
                j=int(np.searchsorted(sx.start_time_ms.to_numpy(),end_ms,side='right')-1)
                if j>=0:
                    mark=float(sx.close.iloc[j]); cost=tr['entry']*cost_bp/10000
                    fpu=funding_per_unit(fmap[tr['symbol']],sx[['start_time_ms','mark_open']],int(tr['side']),int(tr['entry_ms']),end_ms)
                    val=tr['nav_before']+tr['quantity']*(tr['side']*(mark-tr['entry'])+fpu-cost)
        daily.append((day,val))
    d=pd.DataFrame(daily,columns=['date','nav'])
    completed=t[t.completed] if not t.empty else t
    pnl=(completed.nav_after-completed.nav_before) if not completed.empty else pd.Series(dtype=float)
    pos=pnl[pnl>0].sum(); neg=-pnl[pnl<0].sum(); pf=float(pos/neg) if neg>0 else (float('inf') if pos>0 else 0.0)
    mult=float(d.nav.iloc[-1]/10000); geo=float(mult**(1/365)-1) if mult>0 else -1
    dd=d.nav/d.nav.cummax()-1
    h1=float(d.loc[d.date<=pd.Timestamp(f'{year}-06-30',tz='UTC'),'nav'].iloc[-1]/10000)
    h2=float(d.nav.iloc[-1]/d.loc[d.date<=pd.Timestamp(f'{year}-06-30',tz='UTC'),'nav'].iloc[-1])
    metrics=dict(year=year,cost_bp=cost_bp,ending_nav=float(d.nav.iloc[-1]),multiple=mult,geometric_daily_growth=geo,
        completed_trades=int(len(completed)),selected_positions=int(len(t)),wins=int((completed.account_return>0).sum()) if not completed.empty else 0,
        profit_factor=pf,median_trade_return=float(completed.account_return.median()) if not completed.empty else np.nan,
        mean_trade_return=float(completed.account_return.mean()) if not completed.empty else np.nan,daily_mdd=float(-dd.min()),
        h1_multiple=h1,h2_multiple=h2,exit_reasons=completed.reason.value_counts().to_dict() if not completed.empty else {})
    return t,metrics,d


def parse_args():
    ap=argparse.ArgumentParser(description='Turnover-time sponsored acceptance Core fatal screen')
    ap.add_argument('--out', type=Path, default=DEFAULT_OUT, help='scientific output directory')
    return ap.parse_args()


def main():
    global OUT
    args=parse_args(); OUT=args.out.resolve(); OUT.mkdir(parents=True,exist_ok=True)
    xmap={}; fmap={}; packets=[]; events=[]
    for s in SYMBOLS:
        x,f=load_symbol(s); xmap[s]=x; fmap[s]=f
        p=build_packets(x,s); packets.append(p); events.extend(generate_events(x,p,f))
    P=pd.concat(packets,ignore_index=True)
    E=pd.DataFrame([asdict(e) for e in events])
    P.to_csv(OUT/'PACKETS.csv.gz',index=False,compression={'method':'gzip','mtime':0})
    E.to_csv(OUT/'EVENTS.csv.gz',index=False,compression={'method':'gzip','mtime':0})
    results={}; trade_files=[]
    for year in (2021,2022):
        for c in COSTS:
            t,m,d=replay(events,xmap,fmap,c,year)
            results[f'{year}_{c}bp']=m
            t.to_csv(OUT/f'TRADES_{year}_{c}BP.csv',index=False); d.to_csv(OUT/f'DAILY_NAV_{year}_{c}BP.csv',index=False)
    base_t=pd.read_csv(OUT/'TRADES_2022_24BP.csv')
    comp=base_t[base_t.completed.astype(bool)&(base_t.account_return>0)].nlargest(5,'account_return') if not base_t.empty else base_t
    removed=set(comp.event_key.tolist())
    wr_t,wr_m,wr_d=replay(events,xmap,fmap,24,2022,removed)
    wr_t.to_csv(OUT/'TRADES_2022_24BP_WINNER_REMOVED.csv',index=False); wr_d.to_csv(OUT/'DAILY_NAV_2022_24BP_WINNER_REMOVED.csv',index=False)
    gate_m=results['2022_24bp']
    gate=(gate_m['completed_trades']>=60 and gate_m['multiple']>1 and gate_m['profit_factor']>1 and gate_m['median_trade_return']>=0 and gate_m['h1_multiple']>1 and gate_m['h2_multiple']>1 and wr_m['multiple']>1)
    result=dict(schema_version=1,claim_id='CLM-20260730-TURNOVER-TIME-SPONSORED-CORE-001',result_id='RES-20260730-TURNOVER-TIME-SPONSORED-CORE-001',
        loaded_market_years=[2021,2022],opened_2023=False,sponsor_z=SPONSOR_Z,packet_count_by_symbol_year=P.groupby(['symbol','year']).size().unstack(fill_value=0).to_dict(),
        event_count=int(len(E)),event_count_by_symbol_year=E.groupby(['symbol','year']).size().unstack(fill_value=0).to_dict() if len(E) else {},paths=results,
        winner_removed_2022_24bp=wr_m,removed_event_keys=sorted(removed),gate_2022=bool(gate),
        decision='PASS_2022_GATE_OPEN_2023' if gate else 'RETIRED_2022_TURNOVER_TIME_SPONSORED_CORE_FAILURE')
    (OUT/'RESULT.json').write_text(json.dumps(result,indent=2,sort_keys=True,default=str)+'\n')
    print(json.dumps(result,indent=2,default=str))

if __name__=='__main__': main()
