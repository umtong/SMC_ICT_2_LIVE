from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

from direct_core_common import ALL_SEGS, BASE_COST_RT, RESULT_DIR, ts_ms
from direct_core_account import (
    Q_GRID, COST_GRID, concentration_tables, daily_and_mdd, exact_reroute,
    halfyear_table, load_market_cache, load_scores, metrics, simulate_event_path,
)

PRE_START='2022-01-01'; PRE_END='2024-01-01'
OFF_START='2024-01-01'; OFF_END='2026-07-01'
PRE_SEGS=('PRE_2024_2022','PRE_2024_2023')
OFF_SEGS=('2024_H1','2024_H2','2025_H1','2025_H2','2026_H1')


def jdump(x):
    if isinstance(x,(np.integer,)): return int(x)
    if isinstance(x,(np.floating,)): return float(x)
    if isinstance(x,(pd.Timestamp,)): return x.isoformat()
    raise TypeError(type(x))


def year_from_ms(x):
    return pd.to_datetime(x,unit='ms',utc=True).year


def annual_from_day(day:pd.DataFrame,trades:pd.DataFrame, years=(2022,2023)):
    rows=[]
    for y in years:
        a=ts_ms(f'{y}-01-01');b=ts_ms(f'{y+1}-01-01')
        start_nav=10000.0 if y==years[0] else float(day.loc[day.timestamp_ms<=a,'nav'].iloc[-1])
        end_nav=float(day.loc[day.timestamp_ms<=b,'nav'].iloc[-1])
        z=trades[(trades.entry_ms>=a)&(trades.entry_ms<b)&trades.completed]
        mult=end_nav/start_nav
        pos=z.net_pnl>0 if len(z) else pd.Series(dtype=bool)
        pf=(float(z.loc[pos,'net_pnl'].sum()/-z.loc[~pos,'net_pnl'].sum())
            if len(z) and (~pos).any() else (float('inf') if len(z) else float('nan')))
        rows.append({
            'year':y,'start_nav':start_nav,'end_nav':end_nav,'return':mult-1,
            'geo_daily':mult**(1/365)-1 if mult>0 else -1,
            'trades':int(len(z)),'profit_factor':pf,
            'positive_pnl':float(z.loc[pos,'net_pnl'].sum()) if len(z) else 0.0,
            'negative_pnl':float(z.loc[~pos,'net_pnl'].sum()) if len(z) else 0.0,
        })
    return pd.DataFrame(rows)


def annual_top_forbidden(trades:pd.DataFrame,k=5):
    forbidden=set()
    for y in (2022,2023):
        a=ts_ms(f'{y}-01-01');b=ts_ms(f'{y+1}-01-01')
        z=trades[(trades.entry_ms>=a)&(trades.entry_ms<b)&trades.completed&(trades.net_pnl>0)]
        forbidden.update(z.nlargest(min(k,len(z)),'net_pnl').candidate_id.tolist())
    return forbidden


def pre_grid(force=False):
    out=RESULT_DIR/'pre_grid.csv'
    detail=RESULT_DIR/'pre_grid_detail.json'
    if out.exists() and detail.exists() and not force:
        return pd.read_csv(out), json.loads(detail.read_text())
    scores=load_scores([2022,2023])
    cache=load_market_cache(PRE_SEGS)
    rows=[];details={}
    for q in Q_GRID:
        base,_=simulate_event_path(scores,PRE_START,PRE_END,q,BASE_COST_RT)
        day,mdd,pts=daily_and_mdd(base,PRE_START,PRE_END,cache,BASE_COST_RT)
        ann=annual_from_day(day,base)
        forbidden=annual_top_forbidden(base,5)
        rr,_=simulate_event_path(scores,PRE_START,PRE_END,q,BASE_COST_RT,forbidden)
        rday,rmdd,rpts=daily_and_mdd(rr,PRE_START,PRE_END,cache,BASE_COST_RT)
        rann=annual_from_day(rday,rr)
        vals=[float(ann.loc[ann.year==y,'geo_daily'].iloc[0]) for y in (2022,2023)] + \
             [float(rann.loc[rann.year==y,'geo_daily'].iloc[0]) for y in (2022,2023)]
        counts=[int(ann.loc[ann.year==y,'trades'].iloc[0]) for y in (2022,2023)]
        eligible=(all(v>0 for v in vals) and all(n>=60 for n in counts))
        row={
            'q':q,'eligible':eligible,'robust_score':min(vals),'tie_score':float(np.mean(vals)),
            'base_end_nav':float(day.nav.iloc[-1]),'base_mdd':mdd,'base_trades':int(base.completed.sum()),
            'reroute_end_nav':float(rday.nav.iloc[-1]),'reroute_mdd':rmdd,'reroute_trades':int(rr.completed.sum()),
            'forbidden_count':len(forbidden),
        }
        for label,frame in [('base',ann),('reroute',rann)]:
            for y in (2022,2023):
                r=frame[frame.year==y].iloc[0]
                row[f'{label}_{y}_return']=float(r['return']);row[f'{label}_{y}_geo']=float(r.geo_daily)
                row[f'{label}_{y}_trades']=int(r.trades);row[f'{label}_{y}_pf']=float(r.profit_factor)
        rows.append(row)
        details[str(q)]={
            'base_annual':ann.to_dict('records'),'reroute_annual':rann.to_dict('records'),
            'forbidden':sorted(forbidden),'base_minute_points':pts,'reroute_minute_points':rpts,
        }
        print('PRE',json.dumps(row,default=jdump),flush=True)
    grid=pd.DataFrame(rows).sort_values(['eligible','robust_score','tie_score','q'],ascending=[False,False,False,True])
    grid.to_csv(out,index=False)
    detail.write_text(json.dumps(details,indent=2,default=jdump))
    return grid,details


def choose_pre(grid:pd.DataFrame):
    z=grid[grid.eligible.astype(bool)]
    if z.empty:return None
    return float(z.sort_values(['robust_score','tie_score','q'],ascending=[False,False,True]).iloc[0].q)


def cost_pre_diagnostics(q:float):
    p=RESULT_DIR/'pre_cost_diagnostics.csv'
    scores=load_scores([2022,2023]);cache=load_market_cache(PRE_SEGS);rows=[]
    for cost in COST_GRID:
        base,_=simulate_event_path(scores,PRE_START,PRE_END,q,cost)
        day,mdd,_=daily_and_mdd(base,PRE_START,PRE_END,cache,cost)
        ann=annual_from_day(day,base)
        forbidden=annual_top_forbidden(base,5)
        rr,_=simulate_event_path(scores,PRE_START,PRE_END,q,cost,forbidden)
        rday,rmdd,_=daily_and_mdd(rr,PRE_START,PRE_END,cache,cost)
        rann=annual_from_day(rday,rr)
        for label,a,md in [('base',ann,mdd),('reroute',rann,rmdd)]:
            for _,r in a.iterrows():
                rows.append({'cost_rt':cost,'path':label,'mdd':md,**r.to_dict()})
    pd.DataFrame(rows).to_csv(p,index=False)
    return pd.DataFrame(rows)


def official(q:float):
    scores=load_scores([2024,2025,2026])
    cache=load_market_cache(OFF_SEGS)
    summaries={}
    for cost in COST_GRID:
        tag=f'{int(round(cost*10000))}bp'
        trades,_=simulate_event_path(scores,OFF_START,OFF_END,q,cost)
        day,mdd,pts=daily_and_mdd(trades,OFF_START,OFF_END,cache,cost)
        met=metrics(trades,day,OFF_START,OFF_END,mdd)
        hy=halfyear_table(day,trades)
        met['halfyears']=hy.to_dict('records');met['minute_points']=pts
        trades.to_parquet(RESULT_DIR/f'official_{tag}_trades.parquet',index=False,compression='zstd')
        day.to_csv(RESULT_DIR/f'official_{tag}_daily.csv',index=False)
        hy.to_csv(RESULT_DIR/f'official_{tag}_halfyears.csv',index=False)
        if cost==BASE_COST_RT:
            monthly,groups=concentration_tables(trades)
            monthly.to_csv(RESULT_DIR/'official_15bp_monthly.csv',index=False)
            groups.to_csv(RESULT_DIR/'official_15bp_symbol_side.csv',index=False)
            reroutes={}
            for k in (1,5,10):
                rr,forbidden=exact_reroute(scores,OFF_START,OFF_END,q,cost,trades,k)
                rd,rmdd,rpts=daily_and_mdd(rr,OFF_START,OFF_END,cache,cost)
                rmet=metrics(rr,rd,OFF_START,OFF_END,rmdd)
                rmet['halfyears']=halfyear_table(rd,rr).to_dict('records')
                rmet['forbidden_count']=len(forbidden);rmet['minute_points']=rpts
                reroutes[f'top{k}']=rmet
                rr.to_parquet(RESULT_DIR/f'official_15bp_reroute_top{k}_trades.parquet',index=False,compression='zstd')
                rd.to_csv(RESULT_DIR/f'official_15bp_reroute_top{k}_daily.csv',index=False)
            # Delete top 10% of positive winners, not merely top ten.
            pos=int(((trades.completed)&(trades.net_pnl>0)).sum());k=max(1,int(math.ceil(pos*.10)))
            rr,forbidden=exact_reroute(scores,OFF_START,OFF_END,q,cost,trades,k)
            rd,rmdd,rpts=daily_and_mdd(rr,OFF_START,OFF_END,cache,cost)
            rmet=metrics(rr,rd,OFF_START,OFF_END,rmdd);rmet['halfyears']=halfyear_table(rd,rr).to_dict('records')
            rmet['forbidden_count']=len(forbidden);rmet['minute_points']=rpts
            reroutes['top10pct_positive']=rmet
            met['exact_reroutes']=reroutes
        summaries[tag]=met
        print('OFFICIAL',tag,json.dumps(met,default=jdump)[:2000],flush=True)
    result={
        'result_id':'RES-20260730-EXEC-ALIGNED-DIRECT-UTILITY-CORE-001',
        'claim_id':'CLM-20260730-1255-EXEC-ALIGNED-DIRECT-UTILITY-CORE-001',
        'selected_q':q,'risk_fraction':0.005,'notional_cap':3.0,
        'official':summaries,
    }
    (RESULT_DIR/'RESULT.json').write_text(json.dumps(result,indent=2,default=jdump))
    return result


def main():
    grid,_=pre_grid()
    print(grid.to_string(index=False),flush=True)
    q=choose_pre(grid)
    decision={'selected_q':q,'status':'SURVIVED_PRE2024' if q is not None else 'RETIRED_PRE2024_CORE_GATE'}
    (RESULT_DIR/'PRE_DECISION.json').write_text(json.dumps(decision,indent=2))
    if q is None:
        print('NO_ELIGIBLE_ROUTE',flush=True);return
    cost_pre_diagnostics(q)
    # Official scores are intentionally built only after this function has
    # persisted a surviving pre-2024 decision.
    official(q)

if __name__=='__main__':
    main()
