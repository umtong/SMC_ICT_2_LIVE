from __future__ import annotations
import json
from pathlib import Path
import numpy as np
import pandas as pd
from dynamic_policy_fast import prepare, RT_COST, HALF, RISK, LEV_CAP
OUT=Path('/mnt/data/work/ml_inventory_state')


def next_true(mask:np.ndarray)->np.ndarray:
    n=len(mask);out=np.full(n,n,np.int64);nxt=n
    for i in range(n-1,-1,-1):
        out[i]=nxt
        if bool(mask[i]):nxt=i
    return out


def events(f,year,filter_name):
    x=f[(f.year==year)&f.event_gate&f.entry_price.notna()&(f.oi_shock_3>1)].copy()
    if filter_name=='uncrowded':x=x[(x.ratio_z<1)&(x.premium_z<1)]
    elif filter_name=='ratio':x=x[x.ratio_z<1]
    elif filter_name=='premium':x=x[x.premium_z<1]
    x['quality']=x.price_shock_3.abs()*np.maximum(x.oi_shock_3,0)*np.maximum(x.volume_z,0)
    keep=[]
    for sym,g in x.groupby('symbol',sort=False):
        last=-10**18
        for i,t in zip(g.index,g.start_time_ms):
            if int(t)-last>=1_800_000:keep.append(i);last=int(t)
    x=x.loc[keep]
    return x.sort_values(['decision_ms','quality','symbol'],ascending=[True,False,True]).drop_duplicates('decision_ms')


def sim(f,mk,year,filter_name,exit_name):
    evs=events(f,year,filter_name)
    state={}
    for sym,g in f[f.year==year].groupby('symbol'):
        g=g.sort_values('decision_ms').reset_index(drop=True)
        if exit_name=='trend12':
            long=(g.ret_12<=0); short=(g.ret_12>=0)
        elif exit_name=='trend24':
            long=(g.ret_24<=0); short=(g.ret_24>=0)
        elif exit_name=='trend48':
            long=(g.ret_48<=0); short=(g.ret_48>=0)
        elif exit_name=='trend12_oi':
            long=(g.ret_12<=0)&(g.oi_chg_12<=0); short=(g.ret_12>=0)&(g.oi_chg_12<=0)
        elif exit_name=='trend24_oi':
            long=(g.ret_24<=0)&(g.oi_chg_24<=0); short=(g.ret_24>=0)&(g.oi_chg_24<=0)
        elif exit_name=='momentum_flip':
            long=(g.ret_3<0)&(g.ret_12<=0);short=(g.ret_3>0)&(g.ret_12>=0)
        else:raise ValueError(exit_name)
        state[sym]=(g,g.decision_ms.to_numpy(np.int64),next_true(long.fillna(False).to_numpy()),next_true(short.fillna(False).to_numpy()))
    nav=10000.;peak=nav;mdd=0.;free=-1;trs=[];boundary=int(pd.Timestamp(f'{year+1}-01-01',tz='UTC').timestamp()*1000)-60000
    for ev in evs.itertuples(index=False):
        entry_ts=int(ev.entry_ts_ms)
        if entry_ts<free:continue
        side=1 if ev.ret_3>0 else -1;entry=float(ev.entry_price);atr=float(ev.atr_12*ev.close);stop=float(ev.pre_shock_close-side*.1*atr)
        if not np.isfinite(stop) or (side>0 and stop>=entry) or (side<0 and stop<=entry):continue
        loss=abs(entry-stop)/entry+RT_COST;notional=min(nav*LEV_CAP,nav*RISK/max(loss,1e-6));qty=notional/entry
        g,times,nlong,nshort=state[ev.symbol];i=np.searchsorted(times,int(ev.decision_ms),side='right');j=(nlong[i] if side>0 else nshort[i]) if i<len(g) else len(g)
        state_exit=int(g.decision_ms.iloc[j])+60000 if j<len(g) else boundary
        hit=mk[ev.symbol].stop_hit(entry_ts,state_exit,side,stop)
        if hit:xt,xp=hit;reason='STOP'
        else:xt=state_exit;xp=mk[ev.symbol].exact_open(xt);xp=xp if np.isfinite(xp) else mk[ev.symbol].mark(xt);reason='STATE_LOSS' if j<len(g) else 'BOUNDARY_MARK'
        gross=qty*side*(xp-entry);cost=HALF*qty*(entry+xp);fund=mk[ev.symbol].funding(entry_ts,xt,side,qty);pnl=gross-cost+fund
        before=nav;nav=max(0.,nav+pnl);peak=max(peak,nav);mdd=max(mdd,1-nav/peak)
        trs.append({'year':year,'decision_ms':int(ev.decision_ms),'entry_ts_ms':entry_ts,'exit_ts_ms':xt,'symbol':ev.symbol,'side':side,'entry':entry,'stop':stop,'exit':xp,'reason':reason,'quality':float(ev.quality),'oi_shock_3':float(ev.oi_shock_3),'ratio_z':float(ev.ratio_z),'premium_z':float(ev.premium_z),'notional':notional,'leverage':notional/before,'pnl':pnl,'account_return':pnl/before,'nav_after':nav})
        free=xt
    p=np.array([t['pnl'] for t in trs]);a=np.array([t['account_return'] for t in trs]);w=p[p>0];l=p[p<0]
    return {'year':year,'filter':filter_name,'exit':exit_name,'nav':nav,'multiple':nav/10000,'return':nav/10000-1,'gd':(nav/10000)**(1/365)-1 if nav>0 else -1,'trades':len(trs),'pf':w.sum()/(-l.sum()) if len(l) else (np.inf if len(w) else 0),'mdd':mdd,'median':float(np.median(a)) if len(a) else np.nan,'top5_share':np.sort(w)[-5:].sum()/w.sum() if w.sum()>0 else np.nan,'trade_list':trs}

def main():
    f,mk=prepare();rows=[]
    for filt in ['all','ratio','premium','uncrowded']:
      for ex in ['trend12','trend24','trend48','trend12_oi','trend24_oi','momentum_flip']:
        ss=[]
        for y in [2021,2022,2023]:
            s=sim(f,mk,y,filt,ex);rows.append({k:v for k,v in s.items() if k!='trade_list'});ss.append(s)
        print(filt,ex,[(s['year'],round(s['return'],3),s['trades'],round(s['pf'],2),round(s['mdd'],2)) for s in ss],flush=True)
    r=pd.DataFrame(rows);r.to_csv(OUT/'continuation_rule_grid.csv',index=False)
    p=r[r.year.isin([2021,2022])].pivot(index=['filter','exit'],columns='year',values=['gd','trades','pf','mdd'])
    eligible=[]
    for idx,row in p.iterrows():
        if min(row[('trades',2021)],row[('trades',2022)])>=60:
            eligible.append({'filter':idx[0],'exit':idx[1],'worst_gd':min(row[('gd',2021)],row[('gd',2022)]),'avg_gd':(row[('gd',2021)]+row[('gd',2022)])/2,'max_mdd':max(row[('mdd',2021)],row[('mdd',2022)])})
    e=pd.DataFrame(eligible).sort_values(['worst_gd','avg_gd'],ascending=False);print('\nSELECTION 2021-22\n',e.head(10).to_string(index=False))
    best=e.iloc[0];s23=sim(f,mk,2023,best['filter'],best['exit']);print('\nFROZEN 2023',json.dumps({k:v for k,v in s23.items() if k!='trade_list'},indent=2,default=float))
    pd.DataFrame(s23['trade_list']).to_parquet(OUT/'continuation_rule_frozen_2023_trades.parquet',index=False)
    (OUT/'continuation_rule_result.json').write_text(json.dumps({'selection':best.to_dict(),'confirmation_2023':{k:v for k,v in s23.items() if k!='trade_list'}},indent=2,default=lambda o:float(o) if isinstance(o,(np.floating,np.integer)) else str(o)))
if __name__=='__main__':main()
