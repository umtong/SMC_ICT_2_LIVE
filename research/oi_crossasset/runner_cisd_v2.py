from __future__ import annotations
import gc,hashlib,itertools,json,math,sys,time
from dataclasses import dataclass,asdict
from pathlib import Path
import numpy as np,pandas as pd
sys.path.insert(0,str(Path(__file__).resolve().parent))
import runner_v1 as base
OUT=Path('/mnt/data/oi_crossasset_run/cisd_output');OUT.mkdir(parents=True,exist_ok=True)
FAMILIES=['btc_cisd_open_reclaim','btc_mid_reclaim','eth_cisd_reversal','eth_nonconfirm_reversal']
GRID={'pz':[1.75,2.5],'oiz':[1.25,2.0],'flowz':[0.5,1.0],'window':[3,6],'stop_atr':[1.25,1.75],'target_r':[1.5,2.5]}
@dataclass(frozen=True)
class P:
 family:str;pz:float;oiz:float;flowz:float;window:int;stop_atr:float;target_r:float
 @property
 def id(self):return f'{self.family}__p{self.pz:g}_o{self.oiz:g}_f{self.flowz:g}_w{self.window}_s{self.stop_atr:g}_r{self.target_r:g}'

def sig(d,p):
 rz=d.btc_ret1_z.to_numpy(float);shock_side=np.sign(rz);oi=d.oi_chg3_z.to_numpy(float);bf=d.btc_flow_z.to_numpy(float);ef=d.eth_flow_z.to_numpy(float);bo=d.btc_open.to_numpy(float);bh=d.btc_high.to_numpy(float);bl=d.btc_low.to_numpy(float);bc=d.btc_close.to_numpy(float);eo=d.eth_open.to_numpy(float);eh=d.eth_high.to_numpy(float);el=d.eth_low.to_numpy(float);ec=d.eth_close.to_numpy(float)
 shock=np.flatnonzero(np.isfinite(rz)&np.isfinite(oi)&(np.abs(rz)>=p.pz)&(oi<=-p.oiz)&(shock_side!=0));out=[];skip=-1;n=len(d)
 for i in shock:
  if i<=skip:continue
  s=int(shock_side[i]);mid=(bh[i]+bl[i])/2;found=None;ext_low=bl[i];ext_high=bh[i]
  for j in range(i+1,min(n-1,i+1+p.window)):
   ext_low=min(ext_low,bl[j]);ext_high=max(ext_high,bh[j]);trade_side=-s;bflow=np.isfinite(bf[j]) and s*bf[j]<=-p.flowz;eflow=np.isfinite(ef[j]) and s*ef[j]<=-p.flowz
   if p.family=='btc_cisd_open_reclaim':confirm=bflow and trade_side*(bc[j]-bo[i])>0;sym=1;score=abs(rz[i])-oi[i]+max(0,-s*bf[j])
   elif p.family=='btc_mid_reclaim':
    swept=(ext_low<bl[i] if s<0 else ext_high>bh[i]);confirm=swept and bflow and trade_side*(bc[j]-mid)>0;sym=1;score=abs(rz[i])-oi[i]+max(0,-s*bf[j])
   elif p.family=='eth_cisd_reversal':confirm=eflow and trade_side*(ec[j]-eo[i])>0 and s*np.log(ec[j]/ec[i])<s*np.log(bc[j]/bc[i]);sym=2;score=abs(rz[i])-oi[i]+max(0,-s*ef[j])
   else:
    bmove=s*np.log(bc[j]/bc[i]);emove=s*np.log(ec[j]/ec[i]);confirm=eflow and emove<=0 and bmove>0;sym=2;score=abs(rz[i])-oi[i]+max(0,-s*ef[j])+(bmove-emove)*100
   if confirm:found=(j,trade_side,sym,score);break
  if found:out.append(found);skip=found[0]
 if not out:return np.array([],int),np.array([],np.int8),np.array([],np.int8),np.array([],float)
 a=np.array(out,dtype=object);return a[:,0].astype(int),a[:,1].astype(np.int8),a[:,2].astype(np.int8),a[:,3].astype(float)

def simulate(d,p):
 ix,ss,sy,sc=sig(d,p);rows=[];free=0;n=len(d);times=d.time.to_numpy();A={1:{c:d[f'btc_{c}'].to_numpy(float) for c in ['open','high','low','close','atr','flow_z','ret1_z']},2:{c:d[f'eth_{c}'].to_numpy(float) for c in ['open','high','low','close','atr','flow_z','ret1_z']}}
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
   if mf>=dist:
    if side>0:cur=max(cur,np.nanmin(a['low'][max(entry_i,j-2):j+1])-.05*atr,entry+.05*dist)
    else:cur=min(cur,np.nanmax(a['high'][max(entry_i,j-2):j+1])+.05*atr,entry-.05*dist)
   if flip or br:exit_i=j+1;px=a['open'][j+1];reason='state';break
  if exit_i is None:continue
  free=exit_i+1;rows.append({'candidate':p.id,'family':p.family,'signal_i':i,'entry_i':entry_i,'exit_i':exit_i,'signal_time':times[i],'entry_time':times[entry_i],'exit_time':times[exit_i],'symbol':'BTCUSDT' if symi==1 else 'ETHUSDT','side':side,'score':score,'entry_raw':entry,'exit_raw':px,'stop_raw':stop,'target_raw':target,'stop_distance':dist,'atr':atr,'reason':reason,'holding_bars':exit_i-entry_i+1,'max_fav_r':mf/dist})
 return pd.DataFrame(rows)

def main():
 t0=time.time();kdir=base.INPUT/'klines';mdir=base.INPUT/'metrics';dall=base.build_panel(kdir,mdir);d=dall[dall.time<pd.Timestamp('2024-01-01',tz='UTC')].reset_index(drop=True);ps=[P(*x) for x in itertools.product(FAMILIES,GRID['pz'],GRID['oiz'],GRID['flowz'],GRID['window'],GRID['stop_atr'],GRID['target_r'])]
 contract={'version':'btc_oi_cisd_v2','claim_id':base.CLAIM_ID,'base_revision':3,'change_from_v1':'two-stage shock then causal confirmation within a fixed observation window; window is signal validity, not position expiry','families':FAMILIES,'grid':GRID,'splits':{'development':['2022-01-01','2023-01-01'],'selection':['2023-01-01','2024-01-01'],'validation':['2024-01-01','2025-01-01'],'conditional_holdout':['2025-01-01','2026-01-01']},'costs':base.BASE_COST,'cost_mults':[1,1.5,2],'same_path_across_costs':True,'position_exit':['stop','target','post-1R causal trailing','opposite flow or prior-three-bar structure break'],'no_position_time_exit':True};raw=json.dumps(contract,sort_keys=True,separators=(',',':')).encode();contract['sha256']=hashlib.sha256(raw).hexdigest();(OUT/'evaluation_contract.json').write_text(json.dumps(contract,indent=2)+'\n');rows=[]
 for k,p in enumerate(ps,1):
  tr=simulate(d,p);rec={'candidate':p.id,**asdict(p),'raw_trades':len(tr)}
  for m,label in [(1,'base'),(1.5,'stress')]:
   rr=base.replay(tr,m)
   for name,(a,b) in {'dev2022':('2022-01-01','2023-01-01'),'sel2023':('2023-01-01','2024-01-01')}.items():rec.update({f'{name}_{label}_{x}':v for x,v in base.metrics(rr,a,b).items()})
  rows.append(rec);del tr,rr;gc.collect()
  if k%32==0:print(f'CISD {k}/{len(ps)} elapsed={time.time()-t0:.1f}s',flush=True)
 s=pd.DataFrame(rows);g=(s.dev2022_base_trades>=50)&(s.sel2023_base_trades>=50)&(s.dev2022_base_multiple>1)&(s.sel2023_base_multiple>1)&(s.dev2022_stress_multiple>1)&(s.sel2023_stress_multiple>1)&(s.dev2022_base_pf>=1.05)&(s.sel2023_base_pf>=1.05)&(s.dev2022_base_positive_month_ratio>=.5)&(s.sel2023_base_positive_month_ratio>=.5)&(s.dev2022_base_top10_contrib<=.6)&(s.sel2023_base_top10_contrib<=.6)&(s.dev2022_base_without_top10_multiple>1)&(s.sel2023_base_without_top10_multiple>1);s['eligible']=g;s['score']=np.minimum(np.log(s.dev2022_stress_multiple.clip(lower=1e-9)),np.log(s.sel2023_stress_multiple.clip(lower=1e-9)))+.25*(s.dev2022_base_mdd+s.sel2023_base_mdd)-.2*(s.dev2022_base_top10_contrib+s.sel2023_base_top10_contrib);s=s.sort_values(['eligible','score'],ascending=False);s.to_csv(OUT/'candidate_screen.csv',index=False);e=s[s.eligible]
 summary={'status':'DEV_SELECTION_PASS' if len(e) else 'DEV_SELECTION_FAIL','candidate_count':len(s),'eligible_count':len(e),'contract_sha256':contract['sha256'],'validation_2024_opened':False,'holdout_2025_opened':False,'best':s.head(20).replace([np.nan,np.inf,-np.inf],None).to_dict('records')}
 if len(e):
  row=e.iloc[0];p=next(x for x in ps if x.id==row.candidate);tr=simulate(dall,p);summary['chosen_candidate']=p.id;v={k:base.metrics(base.replay(tr,m),'2024-01-01','2025-01-01') for m,k in [(1,'base'),(1.5,'stress'),(2,'hard')]};summary['validation_2024_opened']=True;summary['validation_2024']=v;vg=v['base']['trades']>=50 and v['base']['multiple']>1 and v['stress']['multiple']>1 and v['base']['pf']>=1.05 and v['base']['positive_month_ratio']>=.5 and v['base']['top10_contrib']<=.6 and v['base']['without_top10_multiple']>1;summary['validation_2024_pass']=vg
  if vg:
   h={k:base.metrics(base.replay(tr,m),'2025-01-01','2026-01-01') for m,k in [(1,'base'),(1.5,'stress'),(2,'hard')]};summary['holdout_2025_opened']=True;summary['holdout_2025']=h;summary['holdout_2025_pass']=h['base']['trades']>=50 and h['base']['multiple']>1 and h['stress']['multiple']>1 and h['base']['top10_contrib']<=.6 and h['base']['without_top10_multiple']>1
  tr.to_csv(OUT/'chosen_raw_trades.csv',index=False)
 summary['runtime_seconds']=time.time()-t0;(OUT/'summary.json').write_text(json.dumps(summary,indent=2,default=str)+'\n');print(json.dumps({k:v for k,v in summary.items() if k!='best'},indent=2),flush=True)
if __name__=='__main__':main()
