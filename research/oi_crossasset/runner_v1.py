from __future__ import annotations
import csv, gc, gzip, hashlib, io, itertools, json, math, os, time, zipfile
from dataclasses import dataclass, asdict
from pathlib import Path
import numpy as np
import pandas as pd

ROOT=Path('/mnt/data')
WORK=ROOT/'oi_crossasset_run'
INPUT=WORK/'input'
OUT=WORK/'output'
INPUT.mkdir(parents=True,exist_ok=True);OUT.mkdir(parents=True,exist_ok=True)

CLAIM_ID='claim-20260725-001-btc-oi-crossasset'
BASE_REVISION=3
RISK=0.01
LEV_CAP=5.0
BASE_COST={'fee_entry':0.00055,'fee_exit':0.00055,'slip_entry':0.00020,'slip_exit':0.00020,'slip_stop':0.00040,'funding_8h':0.00010}
FAMILIES=['delev_rev_btc','delev_cont_btc','newlev_cont_btc','delev_contagion_eth','newlev_leader_eth','absorb_eth','crowd_unwind_btc','crowd_exhaust_rev_btc']
GRID={'pz':[1.75,2.5],'oiz':[1.25,2.0],'flowz':[0.75],'close_thr':[0.25],'stop_atr':[1.25,1.75],'target_r':[1.5,2.5]}

@dataclass(frozen=True)
class Param:
    family:str;pz:float;oiz:float;flowz:float;close_thr:float;stop_atr:float;target_r:float
    @property
    def id(self):return f'{self.family}__p{self.pz:g}_o{self.oiz:g}_f{self.flowz:g}_c{self.close_thr:g}_s{self.stop_atr:g}_r{self.target_r:g}'

def sha_file(p:Path):
    h=hashlib.sha256()
    with p.open('rb') as f:
        for b in iter(lambda:f.read(1<<20),b''):h.update(b)
    return h.hexdigest()

def extract_inputs():
    kdir=INPUT/'klines';mdir=INPUT/'metrics';kdir.mkdir(exist_ok=True);mdir.mkdir(exist_ok=True)
    with zipfile.ZipFile(ROOT/'binance-usdm-5m-2020-12_2026-06.zip') as z:
        for n in ['BTCUSDT_5m.csv.gz','ETHUSDT_5m.csv.gz','manifest.json']:(kdir/n).write_bytes(z.read(n))
    with zipfile.ZipFile(ROOT/'wave7-positioning-metrics-2021_2023.zip') as z:
        for n in ['BTCUSDT_metrics.csv.gz','manifest.json']:(mdir/('wave7_'+Path(n).name)).write_bytes(z.read(n))
    with zipfile.ZipFile(ROOT/'v211-btc-metrics-2024.zip') as z:
        for n in z.namelist():(mdir/('y2024_'+Path(n).name)).write_bytes(z.read(n))
    with zipfile.ZipFile(ROOT/'v211-btc-metrics-2025.zip') as z:
        for n in z.namelist():(mdir/('y2025_'+Path(n).name)).write_bytes(z.read(n))
    km=json.loads((kdir/'manifest.json').read_text());series={x['symbol']:x for x in km['series']}
    assert sha_file(kdir/'BTCUSDT_5m.csv.gz')==series['BTCUSDT']['output_sha256']
    assert sha_file(kdir/'ETHUSDT_5m.csv.gz')==series['ETHUSDT']['output_sha256']
    w=json.loads((mdir/'wave7_manifest.json').read_text());assert w['error_count']==0
    assert all(r.get('status')!='verified' or r.get('official_sha256')==r.get('actual_sha256') for r in w['records'])
    out={'user_provided_artifacts':[],'verified_provenance':{'kline_source':km['source'],'kline_archive_root':km['archive_root'],'kline_series':[{k:v for k,v in x.items() if k!='source_archives'} for x in km['series']],'metrics_source':w['source'],'metrics_verified_archive_count':w['verified_archive_count'],'metrics_error_count':w['error_count']}}
    for p in [ROOT/'binance-usdm-5m-2020-12_2026-06.zip',ROOT/'wave7-positioning-metrics-2021_2023.zip',ROOT/'v211-btc-metrics-2024.zip',ROOT/'v211-btc-metrics-2025.zip']:
        out['user_provided_artifacts'].append({'name':p.name,'sha256':sha_file(p),'bytes':p.stat().st_size})
    (OUT/'input_audit.json').write_text(json.dumps(out,indent=2)+'\n');return kdir,mdir

def prior_z(s,w,minp):
    p=s.shift(1);m=p.rolling(w,min_periods=minp).mean();sd=p.rolling(w,min_periods=minp).std(ddof=0).replace(0,np.nan);return (s-m)/sd

def load_kline(path:Path,prefix:str):
    use=['open_time','open','high','low','close','quote_volume','taker_buy_quote_volume']
    d=pd.read_csv(path,usecols=use);d.open_time=pd.to_datetime(d.open_time,utc=True)
    d=d.sort_values('open_time').drop_duplicates('open_time',keep='last').set_index('open_time')
    d=d[(d.index>=pd.Timestamp('2021-01-01',tz='UTC'))&(d.index<pd.Timestamp('2026-01-01',tz='UTC'))]
    for c in use[1:]:d[c]=pd.to_numeric(d[c],errors='coerce')
    prev=d.close.shift(1);tr=pd.concat([d.high-d.low,(d.high-prev).abs(),(d.low-prev).abs()],axis=1).max(axis=1)
    d['atr']=tr.shift(1).rolling(48,min_periods=24).mean();r=np.log(d.close).diff();d['ret1_z']=prior_z(r,288,96)
    d['flow']=2*d.taker_buy_quote_volume/d.quote_volume.replace(0,np.nan)-1;d['flow_z']=prior_z(d.flow,288,96)
    d['close_loc']=(d.close-d.low)/(d.high-d.low).replace(0,np.nan)
    return d.rename(columns={c:f'{prefix}_{c}' for c in d.columns})

def load_metrics(mdir:Path):
    fs=[mdir/'wave7_BTCUSDT_metrics.csv.gz',mdir/'y2024_BTCUSDT_metrics_2024.csv.gz',mdir/'y2025_BTCUSDT_metrics_2025.csv.gz'];ds=[]
    for p in fs:
        d=pd.read_csv(p);d['metric_time']=pd.to_datetime(d.create_time,utc=True,errors='coerce');keep=['metric_time','sum_open_interest','count_long_short_ratio'];d=d[keep]
        for c in keep[1:]:d[c]=pd.to_numeric(d[c],errors='coerce')
        ds.append(d)
    d=pd.concat(ds,ignore_index=True).sort_values('metric_time').drop_duplicates('metric_time',keep='last')
    d=d[(d.metric_time>=pd.Timestamp('2021-01-01',tz='UTC'))&(d.metric_time<pd.Timestamp('2026-01-01',tz='UTC'))].set_index('metric_time')
    oi=np.log(d.sum_open_interest.replace(0,np.nan));d['oi_chg3_z']=prior_z(oi.diff(3),288,96)
    crowd=np.log(d.count_long_short_ratio.replace(0,np.nan));d['crowd_z']=prior_z(crowd,2016,672)
    return d[['oi_chg3_z','crowd_z']]

def build_panel(kdir,mdir):
    b=load_kline(kdir/'BTCUSDT_5m.csv.gz','btc');e=load_kline(kdir/'ETHUSDT_5m.csv.gz','eth');idx=b.index.intersection(e.index);p=b.loc[idx].join(e.loc[idx],how='inner')
    m=load_metrics(mdir).reset_index().sort_values('metric_time');left=pd.DataFrame({'open_time':idx,'decision_time':idx+pd.Timedelta(minutes=5)}).sort_values('decision_time')
    mm=pd.merge_asof(left,m,left_on='decision_time',right_on='metric_time',direction='backward',allow_exact_matches=False,tolerance=pd.Timedelta(minutes=15)).set_index('open_time')
    p['oi_chg3_z']=mm.oi_chg3_z;p['crowd_z']=mm.crowd_z;p['metric_age_s']=(mm.decision_time-mm.metric_time).dt.total_seconds();p=p.reset_index().rename(columns={'open_time':'time'}).replace([np.inf,-np.inf],np.nan)
    manifest={'rows':len(p),'start':str(p.time.min()),'end':str(p.time.max()),'metric_age_median_s':float(p.metric_age_s.median()),'metric_age_p95_s':float(p.metric_age_s.quantile(.95)),'metric_missing':int(p.metric_age_s.isna().sum()),'columns':list(p.columns),'information_boundary':'completed 5m bar; strictly earlier metric timestamp; entry at next 5m open'}
    raw=json.dumps(manifest,sort_keys=True,separators=(',',':')).encode();manifest['dependency_sha256']=hashlib.sha256(raw).hexdigest();(OUT/'panel_manifest.json').write_text(json.dumps(manifest,indent=2)+'\n');return p

def signals(d,p):
    rz=d.btc_ret1_z.to_numpy(float);s=np.sign(rz);ar=np.abs(rz);oi=d.oi_chg3_z.to_numpy(float);bf=d.btc_flow_z.to_numpy(float);ef=d.eth_flow_z.to_numpy(float);bcl=2*d.btc_close_loc.to_numpy(float)-1;ecl=2*d.eth_close_loc.to_numpy(float)-1;erz=d.eth_ret1_z.to_numpy(float);crowd=d.crowd_z.to_numpy(float)
    valid=np.isfinite(ar)&np.isfinite(oi)&np.isfinite(bf)&np.isfinite(ef)&np.isfinite(bcl)&(s!=0);shock=ar>=p.pz;drop=oi<=-p.oiz;rise=oi>=p.oiz;ab=s*bf>=p.flowz;ob=s*bf<=-p.flowz;ae=s*ef>=p.flowz;oe=s*ef<=-p.flowz;db=s*bcl;de=s*ecl
    side=np.zeros(len(d),np.int8);sym=np.zeros(len(d),np.int8);mask=np.zeros(len(d),bool);score=np.full(len(d),np.nan)
    if p.family=='delev_rev_btc':mask=valid&shock&drop&((db<=-p.close_thr)|ob);side[mask]=-s[mask];sym[mask]=1;score[mask]=ar[mask]-oi[mask]-s[mask]*bf[mask]
    elif p.family=='delev_cont_btc':mask=valid&shock&drop&ab&(db>=p.close_thr);side[mask]=s[mask];sym[mask]=1;score[mask]=ar[mask]-oi[mask]+s[mask]*bf[mask]
    elif p.family=='newlev_cont_btc':mask=valid&shock&rise&ab&(db>=p.close_thr);side[mask]=s[mask];sym[mask]=1;score[mask]=ar[mask]+oi[mask]+s[mask]*bf[mask]
    elif p.family=='delev_contagion_eth':
        lag=(s*erz>0)&(np.abs(erz)<=np.maximum(.5,ar*.85));mask=valid&shock&drop&ab&ae&lag&(db>=p.close_thr);side[mask]=s[mask];sym[mask]=2;score[mask]=ar[mask]-oi[mask]+s[mask]*ef[mask]
    elif p.family=='newlev_leader_eth':
        lag=(s*erz>=0)&(np.abs(erz)<=np.maximum(.5,ar*.85));mask=valid&shock&rise&ab&ae&lag&(db>=p.close_thr);side[mask]=s[mask];sym[mask]=2;score[mask]=ar[mask]+oi[mask]+s[mask]*ef[mask]
    elif p.family=='absorb_eth':mask=valid&shock&drop&(s*erz>0)&oe&(de<=-p.close_thr);side[mask]=-s[mask];sym[mask]=2;score[mask]=ar[mask]-oi[mask]-s[mask]*ef[mask]
    elif p.family=='crowd_unwind_btc':
        cs=-np.sign(crowd);cv=np.isfinite(crowd)&(np.abs(crowd)>=2)&(cs!=0);mask=valid&cv&shock&drop&(s==cs)&ab&(db>=p.close_thr);side[mask]=cs[mask];sym[mask]=1;score[mask]=ar[mask]-oi[mask]+np.abs(crowd[mask])
    elif p.family=='crowd_exhaust_rev_btc':
        cs=-np.sign(crowd);cv=np.isfinite(crowd)&(np.abs(crowd)>=2)&(cs!=0);mask=valid&cv&shock&drop&(s==cs)&((s*bf<=-p.flowz)|(db<=-p.close_thr));side[mask]=-cs[mask];sym[mask]=1;score[mask]=ar[mask]-oi[mask]+np.abs(crowd[mask])
    return np.flatnonzero(mask),side[mask],sym[mask],score[mask]

def simulate(d,p):
    ix,ss,sy,sc=signals(d,p);rows=[];free=0;n=len(d);times=d.time.to_numpy();oi=d.oi_chg3_z.to_numpy(float);A={1:{c:d[f'btc_{c}'].to_numpy(float) for c in ['open','high','low','close','atr','flow_z','ret1_z']},2:{c:d[f'eth_{c}'].to_numpy(float) for c in ['open','high','low','close','atr','flow_z','ret1_z']}}
    for i,side,symi,score in zip(ix,ss,sy,sc):
        i=int(i);side=int(side);entry_i=i+1
        if entry_i>=n or entry_i<free:continue
        a=A[int(symi)];entry=a['open'][entry_i];atr=a['atr'][i]
        if not np.isfinite(entry) or not np.isfinite(atr) or atr<=0:continue
        structure=entry-(a['low'][i]-.05*atr) if side>0 else (a['high'][i]+.05*atr)-entry;dist=max(p.stop_atr*atr,structure)
        if not np.isfinite(dist) or dist<=0 or dist>4*atr:continue
        stop=entry-side*dist;target=entry+side*p.target_r*dist;cur=stop;mf=0.;exit_i=None;px=None;reason=''
        for j in range(entry_i,n-1):
            if (a['low'][j]<=cur if side>0 else a['high'][j]>=cur):exit_i=j;px=cur;reason='stop';break
            if (a['high'][j]>=target if side>0 else a['low'][j]<=target):exit_i=j;px=target;reason='target';break
            mf=max(mf,a['high'][j]-entry if side>0 else entry-a['low'][j]);flow=a['flow_z'][j];ret=a['ret1_z'][j];flip=np.isfinite(flow) and np.isfinite(ret) and side*flow<0 and side*ret<0;br=False
            if j>=entry_i+3:br=(a['close'][j]<np.nanmin(a['low'][j-3:j])) if side>0 else (a['close'][j]>np.nanmax(a['high'][j-3:j]))
            invalid=flip or br
            if p.family in {'delev_cont_btc','delev_contagion_eth','crowd_unwind_btc'} and np.isfinite(oi[j]):invalid=invalid or (oi[j]>=1 and np.isfinite(ret) and side*ret<0)
            if mf>=dist:
                if side>0:cur=max(cur,np.nanmin(a['low'][max(entry_i,j-2):j+1])-.05*atr,entry+.05*dist)
                else:cur=min(cur,np.nanmax(a['high'][max(entry_i,j-2):j+1])+.05*atr,entry-.05*dist)
            if invalid:exit_i=j+1;px=a['open'][j+1];reason='state';break
        if exit_i is None:continue
        free=exit_i+1;rows.append({'candidate':p.id,'family':p.family,'signal_i':i,'entry_i':entry_i,'exit_i':exit_i,'signal_time':times[i],'entry_time':times[entry_i],'exit_time':times[exit_i],'symbol':'BTCUSDT' if symi==1 else 'ETHUSDT','side':side,'score':score,'entry_raw':entry,'exit_raw':px,'stop_raw':stop,'target_raw':target,'stop_distance':dist,'atr':atr,'reason':reason,'holding_bars':exit_i-entry_i+1,'max_fav_r':mf/dist})
    return pd.DataFrame(rows)

def funding_n(a,b):
    a=pd.Timestamp(a);b=pd.Timestamp(b);return sum(a<t<=b for t in pd.date_range(a.floor('D'),b.ceil('D'),freq='8h',tz='UTC'))

def replay(t,mult):
    if t.empty:return t.copy()
    z=t.copy();rets=[];gross=[];cost=[];lev=[]
    for r in z.itertuples(index=False):
        e=r.entry_raw*(1+r.side*BASE_COST['slip_entry']*mult);sl=BASE_COST['slip_stop'] if r.reason=='stop' else BASE_COST['slip_exit'];x=r.exit_raw*(1-r.side*sl*mult);sf=r.stop_raw*(1-r.side*BASE_COST['slip_stop']*mult);loss=abs(e-sf)+e*BASE_COST['fee_entry']*mult+sf*BASE_COST['fee_exit']*mult;q=min(RISK/loss,LEV_CAP/e);fees=e*BASE_COST['fee_entry']*mult+x*BASE_COST['fee_exit']*mult;fund=e*BASE_COST['funding_8h']*mult*funding_n(r.entry_time,r.exit_time);rets.append(q*(r.side*(x-e)-fees-fund));gross.append(q*r.side*(r.exit_raw-r.entry_raw));cost.append(q*(fees+fund+abs(e-r.entry_raw)+abs(x-r.exit_raw)));lev.append(q*e)
    z['equity_return']=rets;z['gross_return']=gross;z['cost_return']=cost;z['effective_leverage']=lev;z['cost_mult']=mult;return z

def empty_metrics():return {'trades':0,'multiple':1.,'geo_daily':0.,'mdd':0.,'pf':0.,'win_rate':0.,'positive_month_ratio':0.,'top1_contrib':0.,'top5_contrib':0.,'top10_contrib':0.,'without_top5_multiple':1.,'without_top10_multiple':1.,'worst_trade':0.,'max_loss_streak':0,'median_holding_bars':0.,'avg_leverage':0.}
def metrics(t,a,b):
    a=pd.Timestamp(a,tz='UTC');b=pd.Timestamp(b,tz='UTC');z=t[(pd.to_datetime(t.entry_time,utc=True)>=a)&(pd.to_datetime(t.entry_time,utc=True)<b)&(pd.to_datetime(t.exit_time,utc=True)<b)].sort_values('exit_time') if not t.empty else t
    if z.empty:return empty_metrics()
    v=z.equity_return.to_numpy(float);eq=np.cumprod(1+v);curve=np.r_[1.,eq];dd=curve/np.maximum.accumulate(curve)-1;pos=v[v>0].sum();neg=-v[v<0].sum();p=np.sort(v[v>0])[::-1];psum=p.sum();order=np.argsort(v)[::-1]
    def con(frac):return float(p[:max(1,math.ceil(len(v)*frac))].sum()/psum) if psum>0 else 0.
    def wo(k):m=np.ones(len(v),bool);m[order[:min(k,len(v))]]=False;return float(np.prod(1+v[m]))
    mr=z.assign(month=pd.to_datetime(z.exit_time,utc=True).dt.strftime('%Y-%m')).groupby('month').equity_return.apply(lambda x:np.prod(1+x)-1);st=mx=0
    for x in v:st=st+1 if x<0 else 0;mx=max(mx,st)
    return {'trades':len(z),'multiple':float(eq[-1]),'geo_daily':float(eq[-1]**(1/(b-a).days)-1),'mdd':float(dd.min()),'pf':float(pos/neg) if neg else 999.,'win_rate':float((v>0).mean()),'positive_month_ratio':float((mr>0).mean()),'top1_contrib':con(.01),'top5_contrib':con(.05),'top10_contrib':con(.10),'without_top5_multiple':wo(5),'without_top10_multiple':wo(10),'worst_trade':float(v.min()),'max_loss_streak':mx,'median_holding_bars':float(z.holding_bars.median()),'avg_leverage':float(z.effective_leverage.mean())}

def main():
    t0=time.time();kdir,mdir=extract_inputs();dall=build_panel(kdir,mdir);d=dall[dall.time<pd.Timestamp('2024-01-01',tz='UTC')].reset_index(drop=True);params=[Param(*x) for x in itertools.product(FAMILIES,GRID['pz'],GRID['oiz'],GRID['flowz'],GRID['close_thr'],GRID['stop_atr'],GRID['target_r'])]
    contract={'version':'btc_oi_crossasset_v1','claim_id':CLAIM_ID,'base_revision':BASE_REVISION,'families':FAMILIES,'grid':GRID,'splits':{'warmup':['2021-01-01','2022-01-01'],'development':['2022-01-01','2023-01-01'],'selection':['2023-01-01','2024-01-01'],'validation':['2024-01-01','2025-01-01'],'conditional_holdout':['2025-01-01','2026-01-01']},'costs':BASE_COST,'cost_mults':[1.,1.5,2.],'risk':RISK,'leverage_cap':LEV_CAP,'same_raw_signal_and_exit_path_across_costs':True,'exit_rules':['protective stop','fixed R target','post-1R causal trailing stop','confirmed opposite flow or prior-3-bar structure break','OI state invalidation for deleveraging continuation'],'no_arbitrary_time_exit':True,'gate':'2024 only after 2022+2023; 2025 only after 2024'}
    raw=json.dumps(contract,sort_keys=True,separators=(',',':')).encode();contract['sha256']=hashlib.sha256(raw).hexdigest();(OUT/'evaluation_contract.json').write_text(json.dumps(contract,indent=2)+'\n');rows=[]
    for k,p in enumerate(params,1):
        tr=simulate(d,p);rec={'candidate':p.id,**asdict(p),'raw_trades':len(tr)}
        for mult,label in [(1.,'base'),(1.5,'stress')]:
            rr=replay(tr,mult)
            for period,(a,b) in {'dev2022':('2022-01-01','2023-01-01'),'sel2023':('2023-01-01','2024-01-01')}.items():rec.update({f'{period}_{label}_{x}':v for x,v in metrics(rr,a,b).items()})
        rows.append(rec);del tr,rr;gc.collect()
        if k%16==0:print(f'SCREEN {k}/{len(params)} elapsed={time.time()-t0:.1f}s',flush=True)
    s=pd.DataFrame(rows);gate=(s.dev2022_base_trades>=75)&(s.sel2023_base_trades>=75)&(s.dev2022_base_multiple>1)&(s.sel2023_base_multiple>1)&(s.dev2022_stress_multiple>1)&(s.sel2023_stress_multiple>1)&(s.dev2022_base_pf>=1.05)&(s.sel2023_base_pf>=1.05)&(s.dev2022_base_positive_month_ratio>=.5)&(s.sel2023_base_positive_month_ratio>=.5)&(s.dev2022_base_top10_contrib<=.6)&(s.sel2023_base_top10_contrib<=.6)&(s.dev2022_base_without_top10_multiple>1)&(s.sel2023_base_without_top10_multiple>1);s['eligible']=gate;s['score']=np.minimum(np.log(s.dev2022_stress_multiple.clip(lower=1e-9)),np.log(s.sel2023_stress_multiple.clip(lower=1e-9)))+.25*(s.dev2022_base_mdd+s.sel2023_base_mdd)-.2*(s.dev2022_base_top10_contrib+s.sel2023_base_top10_contrib);s=s.sort_values(['eligible','score'],ascending=False);s.to_csv(OUT/'candidate_screen.csv',index=False);elig=s[s.eligible]
    summary={'status':'DEV_SELECTION_PASS' if len(elig) else 'DEV_SELECTION_FAIL','candidate_count':len(s),'eligible_count':len(elig),'contract_sha256':contract['sha256'],'panel_dependency_sha256':json.loads((OUT/'panel_manifest.json').read_text())['dependency_sha256'],'validation_2024_opened':False,'holdout_2025_opened':False,'best':s.head(20).replace([np.nan,np.inf,-np.inf],None).to_dict('records')}
    if len(elig):
        row=elig.iloc[0];p=next(x for x in params if x.id==row.candidate);tr=simulate(dall,p);summary['chosen_candidate']=p.id;val={k:metrics(replay(tr,m),'2024-01-01','2025-01-01') for m,k in [(1.,'base'),(1.5,'stress'),(2.,'hard')]};summary['validation_2024_opened']=True;summary['validation_2024']=val;vg=val['base']['trades']>=75 and val['base']['multiple']>1 and val['stress']['multiple']>1 and val['base']['pf']>=1.05 and val['base']['positive_month_ratio']>=.5 and val['base']['top10_contrib']<=.6 and val['base']['without_top10_multiple']>1;summary['validation_2024_pass']=vg
        if vg:
            hold={k:metrics(replay(tr,m),'2025-01-01','2026-01-01') for m,k in [(1.,'base'),(1.5,'stress'),(2.,'hard')]};summary['holdout_2025_opened']=True;summary['holdout_2025']=hold;summary['holdout_2025_pass']=hold['base']['trades']>=75 and hold['base']['multiple']>1 and hold['stress']['multiple']>1 and hold['base']['top10_contrib']<=.6 and hold['base']['without_top10_multiple']>1
        tr.to_csv(OUT/'chosen_raw_trades.csv',index=False)
        for m,k in [(1.,'base'),(1.5,'stress'),(2.,'hard')]:replay(tr,m).to_csv(OUT/f'chosen_trades_{k}.csv',index=False)
    summary['runtime_seconds']=time.time()-t0;(OUT/'summary.json').write_text(json.dumps(summary,indent=2,default=str)+'\n');print(json.dumps({k:v for k,v in summary.items() if k!='best'},indent=2,default=str),flush=True)
if __name__=='__main__':main()
