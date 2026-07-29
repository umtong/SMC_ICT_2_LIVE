from __future__ import annotations
import sys
from pathlib import Path
import pandas as pd
from build_outcomes import prepare,build_events,outcome,StateView

step=float(sys.argv[1]);vf=float(sys.argv[2]);sb=float(sys.argv[3]);th=int(sys.argv[4])
OUT=Path('/mnt/data/work/auction_value')
KEEP=['symbol','decision_ms','entry_ts_ms','time','year','side','close','high','low','open','volume','turnover','hour','dow','close_location','body_ratio',
'break_depth_atr','node_distance_atr','extreme_distance_atr','poc_distance_atr','value_width_atr','corridor_mean_ratio','corridor_min_ratio','corridor_max_ratio','profile_entropy','profile_skew','poc_position','value_fraction_observed','prev_day_return_side','side_ret_1','side_ret_3','side_ret_12','price_shock_3','price_shock_6','volume_z','turnover_z','oi_shock_3','oi_shock_6','side_oi_3','side_ratio_z','side_premium_z','basis_z','side_rel_ret_3','rel_oi_3','rel_oi_6','rv_288','rv_2016','atr_12','atr_48','entry_price']

f,mk=prepare(step,vf)
events=build_events(f)
groups={s:StateView(g) for s,g in f.groupby('symbol')}
maps={s:pd.Series(range(len(st.g)),index=st.decision).to_dict() for s,st in groups.items()}
print('START',step,vf,sb,th,len(events),flush=True)
rows=[]
for evd in events.to_dict('records'):
    evd['_gidx']=maps[evd['symbol']][evd['decision_ms']]
    class E:pass
    ev=E();[setattr(ev,k,v) for k,v in evd.items()]
    base={k:evd.get(k) for k in KEEP}
    for action in ('CONT','REV'):
        o=outcome(ev,groups[ev.symbol],mk[ev.symbol],action,sb,th)
        if o:rows.append({**base,'log_step':step,'value_fraction':vf,**o})
out=pd.DataFrame(rows)
name=f'variant_s{int(step*10000):02d}_v{int(vf*100):02d}_b{int(sb*100):02d}_t{th}.parquet'
out.to_parquet(OUT/name,index=False)
print(name,out.groupby(['action','year']).unit_return.agg(['count','mean','median',lambda x:(x>0).mean()]).to_string(),flush=True)
