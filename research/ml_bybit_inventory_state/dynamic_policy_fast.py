from __future__ import annotations
from pathlib import Path
import math, json, time
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor

ROOT=Path('/mnt/data/work/canonical')
OUT=Path('/mnt/data/work/ml_inventory_state')
RT_COST=0.0024
HALF=RT_COST/2
RISK=0.005
LEV_CAP=3.0
FEATURES=[
 'ret_1','ret_3','ret_6','ret_12','ret_24','ret_48','ret_96',
 'oi_chg_1','oi_chg_3','oi_chg_6','oi_chg_12','oi_chg_24','oi_chg_48','oi_chg_96',
 'price_shock_3','price_shock_6','oi_shock_3','oi_shock_6','volume_z','turnover_z',
 'tr_pct','atr_12','atr_48','rv_288','rv_2016','ratio_logit','ratio_chg_3','ratio_chg_12','ratio_z',
 'premium','premium_z','premium_chg_3','basis','basis_z','range_pos_12','range_pos_48',
 'ret_3_peer','ret_6_peer','ret_12_peer','oi_chg_3_peer','oi_chg_6_peer','premium_z_peer','ratio_z_peer',
 'rel_ret_3','rel_ret_6','rel_ret_12','rel_oi_3','rel_oi_6',
 'dir_feature','symbol_code','hour_sin','hour_cos','dow_sin','dow_cos',
]

class Market:
    def __init__(self,short):
        ms=[]; fs=[]
        for y in (2021,2022,2023):
            d=ROOT/f'{short}{y}'
            m=pd.read_parquet(d/'trade_bars/1m.parquet',columns=['start_time_ms','open','high','low','close','observed'])
            ms.append(m[m.observed].drop(columns='observed'))
            f=pd.read_parquet(d/'streams/funding_events.parquet',columns=['timestamp_ms','funding_rate'])
            mark=pd.read_parquet(d/'streams/mark_price_1m.parquet',columns=['start_time_ms','open','observed'])
            mark=mark[mark.observed].rename(columns={'start_time_ms':'timestamp_ms','open':'mark'})[['timestamp_ms','mark']]
            fs.append(f.merge(mark,on='timestamp_ms',how='left'))
        m=pd.concat(ms).drop_duplicates('start_time_ms').sort_values('start_time_ms')
        self.ts=m.start_time_ms.to_numpy(np.int64);self.op=m.open.to_numpy(float);self.hi=m.high.to_numpy(float);self.lo=m.low.to_numpy(float);self.cl=m.close.to_numpy(float)
        f=pd.concat(fs).drop_duplicates('timestamp_ms').sort_values('timestamp_ms')
        self.fts=f.timestamp_ms.to_numpy(np.int64);self.fr=f.funding_rate.to_numpy(float);self.fm=f.mark.to_numpy(float)
    def exact_open(self,ts):
        i=np.searchsorted(self.ts,ts)
        return float(self.op[i]) if i<len(self.ts) and self.ts[i]==ts else np.nan
    def mark(self,ts):
        i=np.searchsorted(self.ts,ts,side='right')-1
        return float(self.cl[max(0,min(i,len(self.cl)-1))])
    def stop_hit(self,start,end,side,stop):
        i=np.searchsorted(self.ts,start);j=np.searchsorted(self.ts,end,side='right')
        if i>=j:return None
        mask=(self.lo[i:j]<=stop) if side>0 else (self.hi[i:j]>=stop)
        hits=np.flatnonzero(mask)
        if not len(hits):return None
        k=i+int(hits[0]); px=min(self.op[k],stop) if side>0 else max(self.op[k],stop)
        return int(self.ts[k]),float(px)
    def funding(self,start,end,side,qty):
        i=np.searchsorted(self.fts,start,side='right');j=np.searchsorted(self.fts,end,side='right')
        if i>=j:return 0.0
        return float(np.nansum(-side*self.fr[i:j]*self.fm[i:j]*qty))

def prepare():
    f=pd.read_parquet(OUT/'features_2021_2023.parquet').sort_values(['symbol','start_time_ms']).reset_index(drop=True).replace([np.inf,-np.inf],np.nan)
    f['dir_feature']=np.sign(f.ret_3);f['symbol_code']=(f.symbol=='ETHUSDT').astype(float)
    f['hour_sin']=np.sin(2*np.pi*f.hour/24);f['hour_cos']=np.cos(2*np.pi*f.hour/24);f['dow_sin']=np.sin(2*np.pi*f.dow/7);f['dow_cos']=np.cos(2*np.pi*f.dow/7)
    g=f.groupby('symbol',sort=False)
    f['shock_hi']=g.high.rolling(3,min_periods=3).max().reset_index(level=0,drop=True)
    f['shock_lo']=g.low.rolling(3,min_periods=3).min().reset_index(level=0,drop=True)
    f['pre_shock_close']=g.close.shift(3)
    f['event_gate']=(f.price_shock_3.abs()>=2)&(f.volume_z>=.5)&f.oi_shock_3.notna()&f.is_complete
    f['entry_ts_ms']=f.decision_ms.astype(np.int64)+60_000
    mk={'BTCUSDT':Market('BTC'),'ETHUSDT':Market('ETH')}
    f['entry_price']=np.nan
    for sym,idx in f.groupby('symbol').groups.items():
        m=mk[sym];ts=f.loc[idx,'entry_ts_ms'].to_numpy(np.int64);pos=np.searchsorted(m.ts,ts);ok=(pos<len(m.ts));vals=np.full(len(ts),np.nan);eq=np.zeros(len(ts),bool);eq[ok]=m.ts[pos[ok]]==ts[ok];vals[eq]=m.op[pos[eq]];f.loc[idx,'entry_price']=vals
    return f,mk

def next_indices(pred):
    n=len(pred);le=np.full(n,n,dtype=np.int64);ge=np.full(n,n,dtype=np.int64);a=n;b=n
    for i in range(n-1,-1,-1):
        le[i]=a;ge[i]=b
        if np.isfinite(pred[i]):
            if pred[i]<=0:a=i
            if pred[i]>=0:b=i
    return le,ge

def make_events(f,year,col,h,th):
    x=f[(f.year==year)&f.event_gate&f.entry_price.notna()].copy()
    x['edge_score']=x[col]/(x.rv_2016*np.sqrt(h)).replace(0,np.nan)
    x=x[x.edge_score.abs()>=th]
    keep=[]
    for sym,g in x.groupby('symbol',sort=False):
        last=-10**18
        for i,t in zip(g.index,g.start_time_ms):
            if int(t)-last>=1_800_000:keep.append(i);last=int(t)
    x=x.loc[keep].copy();x['_abs']=x.edge_score.abs()
    return x.sort_values(['decision_ms','_abs','symbol'],ascending=[True,False,True]).drop_duplicates('decision_ms')

def simulate(f,mk,year,col,h,th):
    events=make_events(f,year,col,h,th)
    state={}
    for sym,g in f[f.year==year].groupby('symbol'):
        g=g.sort_values('decision_ms').reset_index(drop=True);pred=g[col].to_numpy(float);le,ge=next_indices(pred);state[sym]=(g,g.decision_ms.to_numpy(np.int64),le,ge)
    nav=10_000.;peak=nav;mdd=0.;free=-1;trs=[]
    boundary=int(pd.Timestamp(f'{year+1}-01-01',tz='UTC').timestamp()*1000)-60_000
    for ev in events.itertuples(index=False):
        if int(ev.entry_ts_ms)<free:continue
        side=1 if getattr(ev,col)>0 else -1;shock=1 if ev.ret_3>0 else -1;entry=float(ev.entry_price);atr=float(ev.atr_12*ev.close)
        stop=float(ev.pre_shock_close-side*.10*atr) if side==shock else float(ev.shock_lo-.10*atr if side>0 else ev.shock_hi+.10*atr)
        if not np.isfinite(stop) or (side>0 and stop>=entry) or (side<0 and stop<=entry):continue
        loss=abs(entry-stop)/entry+RT_COST;notional=min(nav*LEV_CAP,nav*RISK/max(loss,1e-6));qty=notional/entry
        g,times,le,ge=state[ev.symbol];i=np.searchsorted(times,int(ev.decision_ms),side='right');j=(le[i] if side>0 else ge[i]) if i<len(times) else len(times)
        edge_exit=int(g.decision_ms.iloc[j])+60_000 if j<len(g) else boundary
        hit=mk[ev.symbol].stop_hit(int(ev.entry_ts_ms),edge_exit,side,stop)
        if hit:exit_ts,exitp=hit;reason='STOP'
        else:exit_ts=edge_exit;exitp=mk[ev.symbol].exact_open(exit_ts);exitp=exitp if np.isfinite(exitp) else mk[ev.symbol].mark(exit_ts);reason='EDGE_LOSS' if j<len(g) else 'BOUNDARY_MARK'
        gross=qty*side*(exitp-entry);cost=HALF*qty*(entry+exitp);fund=mk[ev.symbol].funding(int(ev.entry_ts_ms),exit_ts,side,qty);pnl=gross-cost+fund
        before=nav;nav=max(0.,nav+pnl);peak=max(peak,nav);mdd=max(mdd,1-nav/peak)
        trs.append({'decision_ms':int(ev.decision_ms),'entry_ts_ms':int(ev.entry_ts_ms),'exit_ts_ms':exit_ts,'symbol':ev.symbol,'side':side,'action':'CONTINUATION' if side==shock else 'REVERSAL','pred':float(getattr(ev,col)),'edge_score':float(ev.edge_score),'entry':entry,'stop':stop,'exit':exitp,'reason':reason,'notional':notional,'leverage':notional/before,'pnl':pnl,'account_return':pnl/before,'nav_after':nav})
        free=exit_ts
        if nav<=0:break
    a=np.array([t['account_return'] for t in trs]);p=np.array([t['pnl'] for t in trs]);w=p[p>0];l=p[p<0]
    pf=w.sum()/(-l.sum()) if len(l) else (np.inf if len(w) else 0);top=np.sort(w)[-5:].sum()/w.sum() if w.sum()>0 else np.nan
    return {'nav':nav,'multiple':nav/10000,'return':nav/10000-1,'gd':(nav/10000)**(1/365)-1 if nav>0 else -1,'trades':len(trs),'pf':pf,'mdd':mdd,'median':float(np.median(a)) if len(a) else np.nan,'top5_share':top,'trade_list':trs}

def fit_predict(f,h,train_years,score_year):
    target=np.log(f.groupby('symbol').close.shift(-h)/f.entry_price)
    tr=f.year.isin(train_years)&target.notna();model=HistGradientBoostingRegressor(max_leaf_nodes=7,min_samples_leaf=200,l2_regularization=1.0,learning_rate=.05,max_iter=80,early_stopping=False,random_state=729)
    print('fit',h,train_years,'n',tr.sum(),flush=True);model.fit(f.loc[tr,FEATURES].astype(float),target[tr].astype(float))
    idx=f.year==score_year;return model,idx,model.predict(f.loc[idx,FEATURES].astype(float))

def main():
    t=time.time();f,mk=prepare();print('prepared',len(f),'sec',time.time()-t,flush=True)
    rows=[]
    for h in [24,48]:
        model,idx,p=fit_predict(f,h,[2021],2022);col=f'pred_{h}';f.loc[idx,col]=p
        score=f.loc[idx,col]/(f.loc[idx,'rv_2016']*np.sqrt(h));gate=f.loc[idx,'event_gate'].to_numpy()
        for q in [.50,.60,.70,.80,.90]:
            th=float(np.nanquantile(np.abs(score.to_numpy()[gate]),q));s=simulate(f,mk,2022,col,h,th);rows.append({'h':h,'q':q,'threshold':th,**{k:v for k,v in s.items() if k!='trade_list'}});print('2022',h,q,{k:s[k] for k in ['gd','return','trades','pf','mdd']},flush=True)
    r=pd.DataFrame(rows);eligible=r[(r.trades>=80)&(r.pf>1)].sort_values(['gd','mdd'],ascending=[False,True]);best=(eligible.iloc[0] if len(eligible) else r.sort_values('gd',ascending=False).iloc[0]).to_dict();print('BEST',best,flush=True)
    h=int(best['h']);q=float(best['q']);model,idx,p=fit_predict(f,h,[2021,2022],2023);col=f'pred_{h}';f.loc[idx,col]=p
    p22=model.predict(f.loc[f.year==2022,FEATURES].astype(float));score22=p22/(f.loc[f.year==2022,'rv_2016'].to_numpy()*np.sqrt(h));gate22=f.loc[f.year==2022,'event_gate'].to_numpy();th=float(np.nanquantile(np.abs(score22[gate22]),q))
    s=simulate(f,mk,2023,col,h,th);print('2023',json.dumps({k:v for k,v in s.items() if k!='trade_list'},indent=2,default=float),flush=True)
    tr=pd.DataFrame(s['trade_list']);
    if len(tr):tr['time']=pd.to_datetime(tr.entry_ts_ms,unit='ms',utc=True);tr['half']=np.where(tr.time.dt.month<=6,'H1','H2');print(tr.groupby(['half','symbol','action']).agg(n=('pnl','size'),pnl=('pnl','sum'),med=('account_return','median')).to_string());tr.to_parquet(OUT/'dynamic_fast_2023_trades.parquet',index=False)
    r.to_csv(OUT/'dynamic_fast_selection.csv',index=False);(OUT/'dynamic_fast_result.json').write_text(json.dumps({'selected':best,'threshold':th,'confirmation':{k:v for k,v in s.items() if k!='trade_list'}},indent=2,default=lambda o:float(o) if isinstance(o,(np.floating,np.integer)) else str(o)))
if __name__=='__main__':main()
