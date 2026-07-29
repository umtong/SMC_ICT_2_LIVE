from __future__ import annotations
from pathlib import Path
import json,glob
import numpy as np,pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
OUT=Path('/mnt/data/work/auction_value')
FEATURES=['side','break_depth_atr','node_distance_atr','extreme_distance_atr','poc_distance_atr','value_width_atr','corridor_mean_ratio','corridor_min_ratio','corridor_max_ratio','profile_entropy','profile_skew','poc_position','value_fraction_observed','prev_day_return_side','body_ratio','side_close_location','side_ret_1','side_ret_3','side_ret_12','price_shock_3','price_shock_6','volume_z','turnover_z','oi_shock_3','oi_shock_6','side_oi_3','side_ratio_z','side_premium_z','basis_z','side_rel_ret_3','rel_oi_3','rel_oi_6','rv_288','rv_2016','atr_12','atr_48','hour_sin','hour_cos','dow_sin','dow_cos','symbol_code']
KEY=['symbol','decision_ms','stop_buffer','trail_h','log_step','value_fraction']

def load(path):
 d=pd.read_parquet(path).replace([np.inf,-np.inf],np.nan);d['side_close_location']=np.where(d.side>0,d.close_location,1-d.close_location);d['hour_sin']=np.sin(2*np.pi*d.hour/24);d['hour_cos']=np.cos(2*np.pi*d.hour/24);d['dow_sin']=np.sin(2*np.pi*d.dow/7);d['dow_cos']=np.cos(2*np.pi*d.dow/7);d['symbol_code']=(d.symbol=='ETHUSDT').astype(float)
 base=d.drop_duplicates(KEY)[KEY+['year','time','entry_ts_ms']+FEATURES];x=base
 for a in ['CONT','REV']:
  q=d[d.action==a][KEY+['unit_return','exit_ts_ms','duration_min','reason']].rename(columns={c:f'{a.lower()}_{c}' for c in ['unit_return','exit_ts_ms','duration_min','reason']});x=x.merge(q,on=KEY,how='left')
 return x.sort_values(['decision_ms','symbol']).reset_index(drop=True)

def models(x,years):
 out={}
 for a in ['cont','rev']:
  y=x[f'{a}_unit_return'];m=x.year.isin(years)&y.notna();X=x.loc[m,FEATURES].astype(float);yy=y[m].astype(float)
  mean=HistGradientBoostingRegressor(max_leaf_nodes=9,min_samples_leaf=50,l2_regularization=2,learning_rate=.04,max_iter=140,early_stopping=False,random_state=729).fit(X,yy)
  q=HistGradientBoostingRegressor(loss='quantile',quantile=.35,max_leaf_nodes=9,min_samples_leaf=50,l2_regularization=2,learning_rate=.04,max_iter=140,early_stopping=False,random_state=730).fit(X,yy)
  out[a]=(mean,q)
 return out

def pred(x,year,mods):
 m=x.year==year;X=x.loc[m,FEATURES].astype(float)
 for a,(mean,q) in mods.items():x.loc[m,f'{a}_mean']=mean.predict(X);x.loc[m,f'{a}_q35']=q.predict(X)

def acct(x,year,gate):
 z=x[x.year==year].copy()
 cs={'mean':z.cont_mean,'blend':.5*(z.cont_mean+z.cont_q35),'q35':z.cont_q35,'both':np.minimum(z.cont_mean,z.cont_q35)}[gate]
 rs={'mean':z.rev_mean,'blend':.5*(z.rev_mean+z.rev_q35),'q35':z.rev_q35,'both':np.minimum(z.rev_mean,z.rev_q35)}[gate]
 z['a']=np.where(cs>=rs,'cont','rev');z['score']=np.maximum(cs,rs)
 z=z[z.score>0].sort_values(['decision_ms','score','symbol'],ascending=[True,False,True])
 nav=10000.;peak=nav;mdd=0.;free=-1;rets=[];pnls=[]
 for r in z.itertuples(index=False):
  if int(r.entry_ts_ms)<free:continue
  a=r.a;ret=getattr(r,f'{a}_unit_return');xt=getattr(r,f'{a}_exit_ts_ms')
  if not np.isfinite(ret) or not np.isfinite(xt):continue
  before=nav;pnl=before*ret;nav=max(0,nav+pnl);peak=max(peak,nav);mdd=max(mdd,1-nav/peak);rets.append(ret);pnls.append(pnl);free=int(xt)
 p=np.array(pnls);w=p[p>0];l=p[p<0]
 return {'return':nav/10000-1,'gd':(nav/10000)**(1/365)-1 if nav>0 else -1,'trades':len(rets),'pf':w.sum()/(-l.sum()) if len(l) else (np.inf if len(w) else 0),'mdd':mdd,'median':float(np.median(rets)) if rets else np.nan,'top5_share':np.sort(w)[-5:].sum()/w.sum() if w.sum()>0 else np.nan,'nav':nav}

def main():
 files=[OUT/'action_outcomes.parquet']+[Path(x) for x in glob.glob(str(OUT/'variant_*.parquet'))]
 rows=[]
 for path in files:
  x=load(path);cfg={k:x[k].iloc[0] for k in ['log_step','value_fraction','stop_buffer','trail_h']};mods=models(x,[2021]);pred(x,2022,mods)
  for gate in ['mean','blend','q35','both']:
   s=acct(x,2022,gate);row={'file':path.name,**cfg,'gate':gate,**s};rows.append(row);print(row,flush=True)
 r=pd.DataFrame(rows);r.to_csv(OUT/'variant_model_2022.csv',index=False)
 elig=r[(r.trades>=60)&(r.gd>0)&(r.pf>1)].sort_values(['gd','mdd'],ascending=[False,True])
 print('\nELIGIBLE\n',elig.to_string(index=False) if len(elig) else 'NONE')
 if len(elig):
  best=elig.iloc[0];x=load(OUT/best.file);mods=models(x,[2021,2022]);pred(x,2023,mods);s=acct(x,2023,best.gate);print('CONFIRM',best.to_dict(),s);(OUT/'variant_confirmation.json').write_text(json.dumps({'selected':best.to_dict(),'confirmation':s},indent=2,default=float))
if __name__=='__main__':main()
