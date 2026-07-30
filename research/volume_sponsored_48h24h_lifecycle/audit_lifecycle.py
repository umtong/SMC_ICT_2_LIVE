from __future__ import annotations

import argparse
import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent
DATA = ROOT / 'data'
OUT = ROOT / 'results'

SEGS = ['PRE_2024_2021','PRE_2024_2022','PRE_2024_2023','2024_H1','2024_H2','2025_H1','2025_H2','2026_H1']
SYMBOLS = ['BTCUSDT','ETHUSDT']
SYMBOL_SIDES = {('BTCUSDT',1),('ETHUSDT',1),('ETHUSDT',-1)}
ENTRY_LB = 48
EXIT_LB = 24
ATR_LB = 20
STOP_ATR = 2.0
VOL_Z = 2.2706072565238586
RISK = 0.005
CAP = 3.0
COSTS = [15.0,18.0,24.0]
ROUTES = ['reclaim1','reclaim2','reclaim_mid','parent']
ROUTE_TIE_ORDER = {x:i for i,x in enumerate(ROUTES)}


def ts_ms(x: str | pd.Timestamp) -> int:
    return int(pd.Timestamp(x).timestamp()*1000)


def load_concat(symbol: str, rel: str, columns: list[str] | None = None) -> pd.DataFrame:
    xs=[]
    for seg in SEGS:
        p=DATA/seg/symbol/rel
        if p.exists():
            xs.append(pd.read_parquet(p, columns=columns))
    if not xs:
        raise FileNotFoundError((symbol,rel))
    col='start_time_ms' if 'start_time_ms' in xs[0].columns else 'timestamp_ms'
    return pd.concat(xs,ignore_index=True).sort_values(col).drop_duplicates(col).reset_index(drop=True)


@dataclass
class Market:
    symbol: str
    h: pd.DataFrame
    mt: np.ndarray
    mo: np.ndarray
    mh: np.ndarray
    ml: np.ndarray
    mc: np.ndarray
    mark_start: np.ndarray
    mark_avail: np.ndarray
    mark_open: np.ndarray
    mark_close: np.ndarray
    ft: np.ndarray
    fr: np.ndarray

    @classmethod
    def load(cls, symbol: str) -> 'Market':
        h=load_concat(symbol,'trade_bars/1h.parquet',[
            'start_time_ms','open','high','low','close','turnover','is_complete','available_at_ms'
        ])
        h=h[h.is_complete & h.available_at_ms.notna()].copy().sort_values('start_time_ms').reset_index(drop=True)
        prev=h.close.shift(1)
        tr=pd.concat([(h.high-h.low),(h.high-prev).abs(),(h.low-prev).abs()],axis=1).max(axis=1)
        h['atr20']=tr.rolling(ATR_LB,min_periods=ATR_LB).mean()
        h['entry_high']=h.high.shift(1).rolling(ENTRY_LB,min_periods=ENTRY_LB).max()
        h['entry_low']=h.low.shift(1).rolling(ENTRY_LB,min_periods=ENTRY_LB).min()
        h['exit_high']=h.high.shift(1).rolling(EXIT_LB,min_periods=EXIT_LB).max()
        h['exit_low']=h.low.shift(1).rolling(EXIT_LB,min_periods=EXIT_LB).min()
        lv=np.log(h.turnover.where(h.turnover>0))
        pm=lv.shift(1).rolling(168,min_periods=168).mean()
        ps=lv.shift(1).rolling(168,min_periods=168).std(ddof=0)
        h['vol_z168']=(lv-pm)/ps.replace(0,np.nan)
        h['body_mid']=(h.open+h.close)/2

        m=load_concat(symbol,'trade_bars/1m.parquet',[
            'start_time_ms','open','high','low','close','is_complete','available_at_ms'
        ])
        m=m[m.is_complete & m.available_at_ms.notna()].copy().sort_values('start_time_ms').reset_index(drop=True)
        mark=load_concat(symbol,'streams/mark_price_1m.parquet',[
            'start_time_ms','open','close','is_complete','available_at_ms'
        ])
        mark=mark[mark.is_complete & mark.available_at_ms.notna()].copy().sort_values('start_time_ms').reset_index(drop=True)
        fund=load_concat(symbol,'streams/funding_events.parquet')
        fund=fund.sort_values('timestamp_ms').reset_index(drop=True)
        return cls(symbol,h,
            m.start_time_ms.to_numpy(np.int64),m.open.to_numpy(float),m.high.to_numpy(float),m.low.to_numpy(float),m.close.to_numpy(float),
            mark.start_time_ms.to_numpy(np.int64),mark.available_at_ms.to_numpy(np.int64),mark.open.to_numpy(float),mark.close.to_numpy(float),
            fund.timestamp_ms.to_numpy(np.int64),fund.funding_rate.to_numpy(float))

    def first_minute_after(self, activation_ms: int) -> tuple[int,float] | None:
        i=int(np.searchsorted(self.mt,activation_ms,side='right'))
        if i>=len(self.mt): return None
        return i,float(self.mo[i])

    def mark_before(self, t: int) -> float:
        i=int(np.searchsorted(self.mark_avail,t,side='right'))-1
        if i<0: return float('nan')
        return float(self.mark_close[i])

    def funding_sum(self, start: int, end: int) -> float:
        a=int(np.searchsorted(self.ft,start,side='left')); b=int(np.searchsorted(self.ft,end,side='left'))
        return float(self.fr[a:b].sum())


def build_candidate_bases(markets: dict[str,Market]) -> pd.DataFrame:
    rows=[]
    for symbol,m in markets.items():
        h=m.h
        for i,r in h.iterrows():
            if not np.isfinite(r.atr20) or not np.isfinite(r.vol_z168): continue
            side=0; boundary=np.nan
            if r.close>r.entry_high: side=1; boundary=float(r.entry_high)
            elif r.close<r.entry_low: side=-1; boundary=float(r.entry_low)
            if side==0 or (symbol,side) not in SYMBOL_SIDES or r.vol_z168<=VOL_Z: continue
            fill=m.first_minute_after(int(r.available_at_ms)+500)
            if fill is None: continue
            mi,entry=fill
            if not np.isfinite(entry) or entry<=0: continue
            stop=entry-side*2*float(r.atr20)
            if stop<=0: continue
            yr=pd.Timestamp(int(m.mt[mi]),unit='ms',tz='UTC').year
            rows.append(dict(event_key=f'{symbol}|{int(m.mt[mi])}|{side}',symbol=symbol,side=side,
                decision_ms=int(r.available_at_ms),entry_i=mi,entry_ms=int(m.mt[mi]),entry=entry,stop=stop,
                boundary=boundary,body_mid=float(r.body_mid),signal_hour=int(r.start_time_ms),year=yr))
    return pd.DataFrame(rows).sort_values(['entry_ms','event_key']).reset_index(drop=True)


def first_parent_channel_exit(m: Market, side: int, entry_ms: int) -> int | None:
    h=m.h; start=int(np.searchsorted(h.start_time_ms.to_numpy(np.int64),entry_ms,side='right'))
    for j in range(start,len(h)):
        r=h.iloc[j]
        if side>0 and r.close<r.exit_low or side<0 and r.close>r.exit_high:
            fill=m.first_minute_after(int(r.available_at_ms)+500)
            if fill is not None: return fill[0]
    return None


def first_state_exit(m: Market, base: pd.Series, route: str) -> int | None:
    if route=='parent': return None
    h=m.h; side=int(base.side); boundary=float(base.boundary); mid=float(base.body_mid)
    start=int(np.searchsorted(h.start_time_ms.to_numpy(np.int64),int(base.entry_ms),side='right'))
    inside_count=0; reclaimed=False
    for j in range(start,len(h)):
        r=h.iloc[j]
        inside=(r.close<boundary if side>0 else r.close>boundary)
        inside_count=inside_count+1 if inside else 0
        if inside: reclaimed=True
        hit=False
        if route=='reclaim1': hit=inside
        elif route=='reclaim2': hit=inside_count>=2
        elif route=='reclaim_mid': hit=reclaimed and (r.close<mid if side>0 else r.close>mid)
        if hit:
            fill=m.first_minute_after(int(r.available_at_ms)+500)
            if fill is not None: return fill[0]
    return None


def build_route_outcomes(markets: dict[str,Market], bases: pd.DataFrame, route: str, legacy_parent: bool=False) -> pd.DataFrame:
    out=[]
    for _,b in bases.iterrows():
        m=markets[b.symbol]; side=int(b.side); ei=int(b.entry_i); stop=float(b.stop)
        channel_i=first_parent_channel_exit(m,side,int(b.entry_ms)); state_i=first_state_exit(m,b,route)
        possible=[x for x in [channel_i,state_i] if x is not None]
        structural=min(possible) if possible else len(m.mt)-1
        xi=structural; xp=float(m.mo[xi]); reason='state' if state_i is not None and xi==state_i else 'channel'
        last=min(structural,len(m.mt)-1)
        for j in range(ei,last+1):
            if legacy_parent and j==structural: break
            o,h,l=float(m.mo[j]),float(m.mh[j]),float(m.ml[j])
            touched=(l<=stop if side>0 else h>=stop)
            if touched:
                xi=j; xp=o if (side>0 and o<stop) or (side<0 and o>stop) else stop; reason='stop'; break
        funding=-side*m.funding_sum(int(b.entry_ms),int(m.mt[xi]))
        gross=side*(xp/float(b.entry)-1)
        out.append({**b.to_dict(),'route':route,'exit_i':xi,'exit_ms':int(m.mt[xi]),'exit':xp,'reason':reason,
                    'gross_return':gross,'funding_return':funding,'hold_h':(int(m.mt[xi])-int(b.entry_ms))/3_600_000})
    return pd.DataFrame(out)


def replay(outcomes: pd.DataFrame, markets: dict[str,Market], start: str, end: str, cost_bp: float, deleted: set[str] | None=None):
    start_ms,end_ms=ts_ms(start),ts_ms(end); deleted=deleted or set(); nav=10000.; free=start_ms
    trades=[]; ordered=outcomes[(outcomes.entry_ms>=start_ms)&(outcomes.entry_ms<end_ms)].sort_values(['entry_ms','event_key'])
    for _,r in ordered.iterrows():
        if r.event_key in deleted or int(r.entry_ms)<free: continue
        stop_frac=abs(float(r.entry)-float(r.stop))/float(r.entry); planned=stop_frac+cost_bp/10000
        notional=min(nav*RISK/planned,nav*CAP); net=float(r.gross_return)+float(r.funding_return)-cost_bp/10000
        pnl=notional*net; before=nav; nav+=pnl; free=int(r.exit_ms)+60_000
        trades.append({**r.to_dict(),'nav_before':before,'notional':notional,'net_return':net,'pnl':pnl,'nav_after':nav})
    t=pd.DataFrame(trades)
    daily=[]; peak=-np.inf; mdd=0.
    for d in pd.date_range(pd.Timestamp(start),pd.Timestamp(end),inclusive='left',freq='1D'):
        ts=int((d+pd.Timedelta(days=1)).timestamp()*1000); v=10000.
        if len(t):
            closed=t[t.exit_ms<ts]; v=float(closed.nav_after.iloc[-1]) if len(closed) else 10000.
            op=t[(t.entry_ms<ts)&(t.exit_ms>=ts)]
            if len(op):
                r=op.iloc[-1]; m=markets[r.symbol]; mark=m.mark_before(ts); v=float(r.nav_before)+float(r.notional)*(int(r.side)*(mark/float(r.entry)-1)-int(r.side)*m.funding_sum(int(r.entry_ms),ts)-cost_bp/10000)
        peak=max(peak,v); dd=v/peak-1 if peak>0 else 0.; mdd=min(mdd,dd); daily.append((d,v,dd))
    daily=pd.DataFrame(daily,columns=['day','nav','drawdown'])
    days=(pd.Timestamp(end)-pd.Timestamp(start)).days; geo=(nav/10000.)**(1/days)-1
    pos=t[t.pnl>0].pnl.to_numpy() if len(t) else np.array([]); neg=-t[t.pnl<0].pnl.to_numpy() if len(t) else np.array([])
    pf=pos.sum()/neg.sum() if len(neg) else (np.inf if len(pos) else 0.)
    median=float(t.net_return.median()) if len(t) else np.nan; holds=float(t.hold_h.median()) if len(t) else np.nan
    mid=pd.Timestamp(start)+(pd.Timestamp(end)-pd.Timestamp(start))/2
    h1=float(daily[daily.day<mid].nav.iloc[-1]/10000-1); h2=float(daily.nav.iloc[-1]/daily[daily.day<mid].nav.iloc[-1]-1)
    shares=[]
    for n in [1,5,10]: shares.append(float(np.sort(pos)[-n:].sum()/pos.sum()) if len(pos) else 1.)
    s=dict(end_nav=nav,multiple=nav/10000,geo=geo,trades=len(t),pf=pf,median_net_return=median,median_hold_h=holds,mean_hold_h=float(t.hold_h.mean()) if len(t) else np.nan,daily_mdd=mdd,h1_return=h1,h2_return=h2,h1_geo=(1+h1)**(1/max(1,int((mid-pd.Timestamp(start)).days)))-1,h2_geo=(1+h2)**(1/max(1,int((pd.Timestamp(end)-mid).days)))-1,top1_share=shares[0],top5_share=shares[1],top10_share=shares[2])
    return t,daily,s


def top5_reroute(outcomes,markets,start,end,cost):
    t,d,s=replay(outcomes,markets,start,end,cost)
    ids=set(t[t.pnl>0].nlargest(5,'pnl').event_key.astype(str))
    rt,rd,rs=replay(outcomes,markets,start,end,cost,ids)
    return t,d,s,rt,rd,rs,ids


def pre_gate(base,reroute):
    return base['trades']>=60 and base['end_nav']>10000 and reroute['end_nav']>10000 and base['median_net_return']>0 and base['h1_return']>0 and base['h2_return']>0


def score_route(route,base,reroute):
    return (min(base['geo'],reroute['geo'],base['h1_geo'],base['h2_geo']),-abs(base['daily_mdd']),-base['median_hold_h'],-ROUTE_TIE_ORDER[route])


def halfyears_official(daily):
    out={}
    for y in [2024,2025,2026]:
        for h,(a,b) in enumerate([(f'{y}-01-01',f'{y}-07-01'),(f'{y}-07-01',f'{y+1}-01-01')],1):
            if pd.Timestamp(a,tz='UTC')>=pd.Timestamp('2026-07-01',tz='UTC'): continue
            x=daily[(daily.day>=pd.Timestamp(a,tz='UTC'))&(daily.day<pd.Timestamp(b,tz='UTC'))]
            if len(x): out[f'{y}H{h}']=float(x.nav.iloc[-1]/(x.nav.iloc[0] if len(x)>1 else 10000)-1)
    return out


def holding_buckets(trades):
    cuts=[(-np.inf,24,'<=24h'),(24,48,'24-48h'),(48,120,'48-120h'),(120,np.inf,'>120h')]; out={}
    for lo,hi,name in cuts:
        x=trades[(trades.hold_h>lo)&(trades.hold_h<=hi)]
        out[name]={'trades':len(x),'pnl':float(x.pnl.sum()) if len(x) else 0.}
    return out


def json_clean(x):
    if isinstance(x,dict): return {k:json_clean(v) for k,v in x.items()}
    if isinstance(x,list): return [json_clean(v) for v in x]
    if isinstance(x,(np.integer,)): return int(x)
    if isinstance(x,(np.floating,)): x=float(x)
    if isinstance(x,float) and (math.isnan(x) or math.isinf(x)): return None
    return x


def main(data_root: Path | None = None, output_root: Path | None = None):
    global DATA, OUT
    if data_root is not None:
        DATA = data_root
    if output_root is not None:
        OUT = output_root
    OUT.mkdir(parents=True, exist_ok=True)
    print('loading markets',flush=True)
    markets={s:Market.load(s) for s in SYMBOLS}
    bases=build_candidate_bases(markets)
    bases.to_parquet(OUT/'candidate_bases.parquet',index=False)
    print('candidate bases',len(bases),bases.year.value_counts().sort_index().to_dict(),flush=True)

    route_outcomes={}
    for route in ROUTES:
        print('route',route,flush=True)
        x=build_route_outcomes(markets,bases,route,legacy_parent=False)
        x.to_parquet(OUT/f'outcomes_{route}.parquet',index=False)
        route_outcomes[route]=x
    legacy=build_route_outcomes(markets,bases,'parent',legacy_parent=True)
    legacy.to_parquet(OUT/'outcomes_parent_legacy.parquet',index=False)

    parity={}
    for label,x in [('parent_corrected',route_outcomes['parent']),('parent_legacy',legacy)]:
        tr,daily,s=replay(x,markets,'2024-01-01T00:00:00Z','2026-07-01T00:00:00Z',24.0)
        parity[label]=s
    (OUT/'parent_programization_audit.json').write_text(json.dumps(json_clean(parity),indent=2))

    pre_rows=[]; pre_detail={}
    for route,x in route_outcomes.items():
        rdetail={}
        for year in [2022,2023]:
            start=f'{year}-01-01T00:00:00Z'; end=f'{year+1}-01-01T00:00:00Z'
            bt,bd,b,rt,rd,rr,ids=top5_reroute(x,markets,start,end,24.0)
            rdetail[str(year)]={'base':b,'reroute_top5':rr,'deleted_event_keys':sorted(ids)}
            if year==2022:
                eligible=pre_gate(b,rr); scr=score_route(route,b,rr) if eligible else None
                pre_rows.append({'route':route,'eligible_2022':eligible,'score_min_geo':scr[0] if scr else np.nan,**{f'base_{k}':v for k,v in b.items()},**{f'reroute_{k}':v for k,v in rr.items()}})
        pre_detail[route]=rdetail
    pre_df=pd.DataFrame(pre_rows).sort_values(['eligible_2022','score_min_geo'],ascending=[False,False])
    pre_df.to_csv(OUT/'pre2022_selection.csv',index=False)

    eligible=[]
    for route in ROUTES:
        b=pre_detail[route]['2022']['base']; rr=pre_detail[route]['2022']['reroute_top5']
        if pre_gate(b,rr): eligible.append((score_route(route,b,rr),route))
    selected=max(eligible)[1] if eligible else None
    confirmation_pass=False
    if selected:
        confirmation_pass=pre_gate(pre_detail[selected]['2023']['base'],pre_detail[selected]['2023']['reroute_top5'])

    result={
        'result_id':'RES-20260730-48H24H-SPONSORED-LIFECYCLE-001',
        'claim_id':'CLM-20260730-1830-48H24H-SPONSORED-LIFECYCLE-001',
        'parent':{'entry_lookback_h':ENTRY_LB,'exit_lookback_h':EXIT_LB,'volume_z168':VOL_Z,'sides':sorted([f'{s}:{"LONG" if q==1 else "SHORT"}' for s,q in SYMBOL_SIDES]),'risk':RISK,'cap':CAP},
        'programization_audit':parity,'pre2024':pre_detail,'selected_2022':selected,'unchanged_2023_pass':confirmation_pass,
        'official_opened':False,'orders_submitted':False,
    }

    if selected and confirmation_pass:
        result['official_opened']=True; result['status']='OFFICIAL_EVALUATED'
        off={}; x=route_outcomes[selected]
        for cost in COSTS:
            bt,bd,b,rt,rd,rr,ids=top5_reroute(x,markets,'2024-01-01T00:00:00Z','2026-07-01T00:00:00Z',cost)
            b['halfyears']=halfyears_official(bd); b['holding_buckets']=holding_buckets(bt)
            rr['halfyears']=halfyears_official(rd); rr['holding_buckets']=holding_buckets(rt)
            off[f'{int(cost)}bp']={'base':b,'reroute_top5':rr,'deleted_event_keys':sorted(ids)}
            bt.to_parquet(OUT/f'official_{int(cost)}bp_trades.parquet',index=False); bd.to_csv(OUT/f'official_{int(cost)}bp_daily.csv',index=False)
            rt.to_parquet(OUT/f'official_{int(cost)}bp_top5_rerouted_trades.parquet',index=False); rd.to_csv(OUT/f'official_{int(cost)}bp_top5_rerouted_daily.csv',index=False)
        result['official']=off
    else:
        result['status']='RETIRED_PRE2024_LIFECYCLE_FAILURE'

    result=json_clean(result)
    (OUT/'RESULT.json').write_text(json.dumps(result,indent=2,sort_keys=False)+'\n')
    digest=hashlib.sha256((OUT/'RESULT.json').read_bytes()).hexdigest()
    (OUT/'RESULT.sha256').write_text(f'{digest}  RESULT.json\n')
    print(json.dumps({'status':result['status'],'selected':selected,'confirmation_pass':confirmation_pass,'parent_audit':parity},indent=2,default=float),flush=True)


if __name__=='__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--data-root', type=Path, default=ROOT / 'data')
    ap.add_argument('--output-root', type=Path, default=ROOT / 'results')
    args = ap.parse_args()
    main(args.data_root, args.output_root)
