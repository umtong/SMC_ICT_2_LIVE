import json,sys
from pathlib import Path
import numpy as np,pandas as pd
sys.path.insert(0,'.')
from direct_core_common import BASE_COST_RT,OUT,RESULT_DIR
from direct_core_account import Q_GRID,load_market_cache,simulate_event_path,daily_and_mdd
from evaluate_direct_core import annual_from_day,annual_top_forbidden

def load_a(a):
    tag=str(a).replace('.','p');d=OUT/f'scores_duration_a{tag}'
    return pd.concat([pd.read_parquet(d/f'scores_outcomes_{y}.parquet') for y in (2022,2023)],ignore_index=True).sort_values(['decision_ms','u'],ascending=[True,False])
cache=load_market_cache(('PRE_2024_2022','PRE_2024_2023'))
rows=[]
# Include the already evaluated alpha=0 rows for one deterministic comparison.
base=pd.read_csv(RESULT_DIR/'pre_grid.csv')
for _,r in base.iterrows():rows.append({'alpha':0.0,**r.to_dict()})
for a in (.25,.5):
    scores=load_a(a)
    for q in Q_GRID:
        t,_=simulate_event_path(scores,'2022-01-01','2024-01-01',q,BASE_COST_RT)
        d,m,_=daily_and_mdd(t,'2022-01-01','2024-01-01',cache,BASE_COST_RT);ann=annual_from_day(d,t)
        forb=annual_top_forbidden(t,5)
        rr,_=simulate_event_path(scores,'2022-01-01','2024-01-01',q,BASE_COST_RT,forb)
        rd,rm,_=daily_and_mdd(rr,'2022-01-01','2024-01-01',cache,BASE_COST_RT);ra=annual_from_day(rd,rr)
        vals=[float(ann.loc[ann.year==y,'geo_daily'].iloc[0]) for y in (2022,2023)]+[float(ra.loc[ra.year==y,'geo_daily'].iloc[0]) for y in (2022,2023)]
        cnt=[int(ann.loc[ann.year==y,'trades'].iloc[0]) for y in (2022,2023)]
        row={'alpha':a,'q':q,'eligible':all(v>0 for v in vals) and all(n>=60 for n in cnt),'robust_score':min(vals),'tie_score':float(np.mean(vals)),'base_end_nav':float(d.nav.iloc[-1]),'base_mdd':m,'base_trades':int(t.completed.sum()),'reroute_end_nav':float(rd.nav.iloc[-1]),'reroute_mdd':rm,'reroute_trades':int(rr.completed.sum()),'forbidden_count':len(forb)}
        for label,f in [('base',ann),('reroute',ra)]:
            for y in (2022,2023):
                x=f[f.year==y].iloc[0];row[f'{label}_{y}_return']=float(x['return']);row[f'{label}_{y}_geo']=float(x.geo_daily);row[f'{label}_{y}_trades']=int(x.trades);row[f'{label}_{y}_pf']=float(x.profit_factor)
        rows.append(row);print(json.dumps(row),flush=True)
out=pd.DataFrame(rows)
out.to_csv(RESULT_DIR/'duration_pre_grid.csv',index=False)
z=out[out.eligible.astype(bool)].sort_values(['robust_score','tie_score','alpha','q'],ascending=[False,False,True,True])
sel=z.iloc[0].to_dict() if len(z) else None
(RESULT_DIR/'DURATION_PRE_DECISION.json').write_text(json.dumps(sel,indent=2))
print('SELECTED',json.dumps(sel,indent=2),flush=True)
