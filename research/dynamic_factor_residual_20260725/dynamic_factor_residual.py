from __future__ import annotations
import argparse, hashlib, itertools, json, math
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
import numpy as np
import pandas as pd
from numba import njit

BAR_MS=300_000
SYMBOLS=("BTCUSDT","ETHUSDT","SOLUSDT","XRPUSDT")
PERIODS={
 "development":(pd.Timestamp("2023-01-01",tz="UTC"),pd.Timestamp("2024-01-01",tz="UTC")),
 "selection":(pd.Timestamp("2024-01-01",tz="UTC"),pd.Timestamp("2025-01-01",tz="UTC")),
 "confirmation":(pd.Timestamp("2025-01-01",tz="UTC"),pd.Timestamp("2026-01-01",tz="UTC")),
}
@dataclass(frozen=True,slots=True)
class Market:
 times:np.ndarray; open:np.ndarray; high:np.ndarray; low:np.ndarray; close:np.ndarray; quote:np.ndarray; buy_quote:np.ndarray; atr:np.ndarray
@dataclass(frozen=True,slots=True)
class FeatureBlock:
 beta_window:int; horizon:int; residual_z:np.ndarray; flow_z:np.ndarray; activity_z:np.ndarray; efficiency:np.ndarray; dispersion_z:np.ndarray; prior_dispersion_z:np.ndarray
@dataclass(frozen=True,slots=True)
class SignalSpec:
 family:str; beta_window:int; residual_horizon:int; residual_z_threshold:float; flow_threshold:float; dispersion_z_min:float; compression_z_max:float|None=None; efficiency_max:float|None=None
 @property
 def signal_id(self): return hashlib.sha256(json.dumps(asdict(self),sort_keys=True,separators=(",",":")).encode()).hexdigest()[:16]
@dataclass(frozen=True,slots=True)
class Candidate:
 signal:SignalSpec; hold_bars:int; stop_atr:float
 @property
 def candidate_id(self): return hashlib.sha256(json.dumps({"signal":asdict(self.signal),"hold_bars":self.hold_bars,"stop_atr":self.stop_atr},sort_keys=True,separators=(",",":")).encode()).hexdigest()[:20]
SUMMARY_COLUMNS=("n","total_return","gmean_daily","profit_factor","max_drawdown","top5_positive_share","top10pct_removed_return","h1_return","h2_return","positive_month_fraction","worst_month","traded_symbols","max_single_symbol_trade_share","mean_net_bps","stop_rate","ending_equity")
def sha256_file(p:Path):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for c in iter(lambda:f.read(1<<20),b''):h.update(c)
 return h.hexdigest()
def rsum(x,w): return pd.Series(x).rolling(w,min_periods=w).sum().to_numpy(float)
def prior_z(x,w,m):
 s=pd.Series(x);h=s.shift(1);mu=h.rolling(w,min_periods=m).mean();sd=h.rolling(w,min_periods=m).std(ddof=0).replace(0,np.nan);return ((s-mu)/sd).to_numpy(float)
def prior_beta(xv,yv,w,m):
 x,y=pd.Series(xv),pd.Series(yv);mx=x.rolling(w,min_periods=m).mean().shift(1);my=y.rolling(w,min_periods=m).mean().shift(1);cov=(x*y).rolling(w,min_periods=m).mean().shift(1)-mx*my;var=(x*x).rolling(w,min_periods=m).mean().shift(1)-mx*mx;return (cov/var.replace(0,np.nan)).to_numpy(float)
def load_market(snapshot:Path,stage:str):
 start,end=PERIODS[stage];warm=pd.Timedelta(days=0 if stage=='development' else 35);lo=int((start-warm).value//1_000_000);up=int(end.value//1_000_000);payload={}
 for sym in SYMBOLS:
  with np.load(snapshot/f'{sym}_5m.npz',allow_pickle=False) as z:
   t=z['open_time_ms'];a=int(np.searchsorted(t,lo));b=int(np.searchsorted(t,up));payload[sym]={k:z[k][a:b].copy() for k in z.files}
 first=max(int(payload[s]['open_time_ms'][0]) for s in SYMBOLS);last=min(int(payload[s]['open_time_ms'][-1]) for s in SYMBOLS);times=np.arange(first,last+BAR_MS,BAR_MS,dtype=np.int64);shape=(4,len(times));fields={n:np.full(shape,np.nan) for n in ('open','high','low','close','quote_volume','taker_buy_quote')}
 for si,sym in enumerate(SYMBOLS):
  item=payload[sym];pos=np.searchsorted(times,item['open_time_ms']);valid=(pos<len(times))&(times[np.minimum(pos,len(times)-1)]==item['open_time_ms'])
  for n in fields:fields[n][si,pos[valid]]=item[n][valid]
 finite=np.isfinite(np.stack(list(fields.values()),axis=0)).all(axis=(0,1))
 if not finite.all():raise ValueError(f'{stage} incomplete bars {int((~finite).sum())}')
 atr=np.full(shape,np.nan)
 for si in range(4):
  prev=np.r_[np.nan,fields['close'][si,:-1]];tr=np.maximum(fields['high'][si]-fields['low'][si],np.maximum(abs(fields['high'][si]-prev),abs(fields['low'][si]-prev)));atr[si]=pd.Series(tr).rolling(288,min_periods=144).mean().to_numpy(float)
 return Market(times,fields['open'],fields['high'],fields['low'],fields['close'],fields['quote_volume'],fields['taker_buy_quote'],atr)
def build_blocks(m:Market):
 lc=np.log(m.close);ret=np.full_like(m.close,np.nan);ret[:,1:]=lc[:,1:]-lc[:,:-1];signed=2*m.buy_quote-m.quote;factor=np.full_like(ret,np.nan)
 for si in range(4):factor[si]=np.median(np.delete(ret,si,axis=0),axis=0)
 rawf={};rawa={}
 for h in (3,12,48):
  f=np.full_like(ret,np.nan);a=np.full_like(ret,np.nan)
  for si in range(4):
   q=rsum(m.quote[si],h);s=rsum(signed[si],h);f[si]=np.divide(s,q,out=np.full_like(s,np.nan),where=q>0);a[si]=np.log1p(q)
  rawf[h]=f;rawa[h]=a
 out={}
 for w in (2016,8640):
  mp=w//2;r1=np.full_like(ret,np.nan)
  for si in range(4):r1[si]=ret[si]-prior_beta(factor[si],ret[si],w,mp)*factor[si]
  disp=np.std(r1,axis=0);dz=prior_z(disp,w,mp);pdz=np.r_[np.nan,dz[:-1]]
  for h in (3,12,48):
   rz=np.full_like(r1,np.nan);fz=np.full_like(r1,np.nan);az=np.full_like(r1,np.nan);eff=np.full_like(r1,np.nan)
   for si in range(4):
    cum=rsum(r1[si],h);path=rsum(abs(r1[si]),h);rz[si]=prior_z(cum,w,mp);fz[si]=prior_z(rawf[h][si],w,mp);az[si]=prior_z(rawa[h][si],w,mp);eff[si]=np.divide(abs(cum),path,out=np.full_like(path,np.nan),where=path>0)
   out[(w,h)]=FeatureBlock(w,h,rz,fz,az,eff,dz,pdz)
 return out
def signal_specs():
 o=[]
 for w,h,z,f,d in itertools.product((2016,8640),(3,12,48),(1.5,2,2.5,3),(0,.5,1),(0,1,2)):o.append(SignalSpec('residual_flow_continuation',w,h,z,f,d))
 for w,h,z,f,d in itertools.product((2016,8640),(3,12,48),(1.5,2,2.5,3),(-.5,0,.5),(0,1,2)):o.append(SignalSpec('residual_mean_reversion',w,h,z,f,d))
 for w,h,z,f,d,e in itertools.product((2016,8640),(3,12,48),(1.5,2,2.5,3),(0,.5,1),(0,1,2),(.3,.5)):o.append(SignalSpec('dispersion_absorption',w,h,z,f,d,efficiency_max=e))
 for w,h,z,f,d,c in itertools.product((2016,8640),(3,12,48),(1.5,2,2.5,3),(0,.5,1),(0,1,2),(-.5,0)):o.append(SignalSpec('dispersion_breakout',w,h,z,f,d,compression_z_max=c))
 assert len(o)==1296 and len({x.signal_id for x in o})==1296;return o
def select_events(b:FeatureBlock,s:SignalSpec,m:Market,stage:str):
 rz=b.residual_z;rs=np.where(np.isfinite(rz),np.sign(rz),0).astype(np.int8);sf=rs*b.flow_z;disp=b.dispersion_z[None,:];pdisp=b.prior_dispersion_z[None,:];base=np.isfinite(rz)&np.isfinite(b.flow_z)&np.isfinite(b.activity_z)&np.isfinite(b.efficiency)&np.isfinite(disp)&(abs(rz)>=s.residual_z_threshold)&(disp>=s.dispersion_z_min)&(rs!=0)
 if s.family=='residual_flow_continuation':mask=base&(sf>=s.flow_threshold)&(b.activity_z>=0);direction=rs;score=abs(rz)+np.maximum(sf,0)+np.maximum(disp,0)+np.maximum(b.activity_z,0)
 elif s.family=='residual_mean_reversion':mask=base&(sf<=s.flow_threshold);direction=-rs;score=abs(rz)+np.maximum(-sf,0)+np.maximum(disp,0)
 elif s.family=='dispersion_absorption':mask=base&(sf>=s.flow_threshold)&(b.efficiency<=s.efficiency_max)&(b.activity_z>=0);direction=-rs;score=abs(rz)+np.maximum(sf,0)+(1-b.efficiency)+np.maximum(disp,0)
 else:mask=base&(pdisp<=s.compression_z_max)&(sf>=s.flow_threshold)&(b.activity_z>=0);direction=rs;score=abs(rz)+np.maximum(sf,0)+np.maximum(disp,0)+np.maximum(-pdisp,0)
 start,end=PERIODS[stage];lo=int(start.value//1_000_000);up=int(end.value//1_000_000);mask&=((m.times>=lo)&(m.times<up))[None,:];scores=np.where(mask,score,-np.inf);sy=np.argmax(scores,axis=0).astype(np.int8);best=scores[sy,np.arange(scores.shape[1])];bars=np.flatnonzero(np.isfinite(best));return bars.astype(np.int64),sy[bars],direction[sy[bars],bars].astype(np.int8)
@njit(cache=True)
def sim(times,op,hi,lo,qv,atr,bars,sy,sides,hold,stop_atr,cost,start_ms,end_ms,month,half):
 nmax=len(bars);ar=np.empty(nmax);pnl=np.empty(nmax);ex=np.empty(nmax,np.int64);sym=np.empty(nmax,np.int8);stp=np.empty(nmax,np.int8);equity=10000.;peak=equity;mdd=0.;free=-1;n=0
 for k in range(nmax):
  b=int(bars[k])
  if b<free:continue
  s=int(sy[k]);side=int(sides[k]);ei=b+1;ti=ei+hold
  if ti>=len(times) or times[ei]!=times[b]+BAR_MS or times[ti]-times[ei]!=hold*BAR_MS:continue
  entry=op[s,ei];a=atr[s,b]
  if not np.isfinite(entry) or not np.isfinite(a) or entry<=0 or a<=0:continue
  dist=max(stop_atr*a,entry*.0015)
  if dist>entry*.05:continue
  stop=entry-side*dist;xi=ti;xp=op[s,ti];stopped=0;valid=True
  for j in range(ei,ti):
   o=op[s,j];h=hi[s,j];l=lo[s,j]
   if not(np.isfinite(o) and np.isfinite(h) and np.isfinite(l)):valid=False;break
   if side>0 and l<=stop:xi=j;xp=o if o<stop else stop;stopped=1;break
   if side<0 and h>=stop:xi=j;xp=o if o>stop else stop;stopped=1;break
  if not valid or not np.isfinite(xp):continue
  net=side*(xp/entry-1)-cost/10000.;planned=dist/entry+cost/10000.;notional=min(equity*.005/planned,equity*3,qv[s,b]*.001)
  if notional<=0 or not np.isfinite(notional):continue
  before=equity;pp=net*notional;equity=max(1e-12,equity+pp);ar[n]=pp/before;pnl[n]=pp;ex[n]=times[xi]+BAR_MS;sym[n]=s;stp[n]=stopped;n+=1;peak=max(peak,equity);mdd=max(mdd,1-equity/peak);free=xi+1
 if n==0:return np.array([0.,0.,0.,0.,0.,1.,0.,0.,0.,0.,0.,0.,1.,0.,0.,10000.])
 ar=ar[:n];pnl=pnl[:n];ex=ex[:n];sym=sym[:n];stp=stp[:n];pos=pnl[pnl>0];neg=-pnl[pnl<0];pf=pos.sum()/neg.sum() if len(neg) else np.inf;top5=np.sort(pos)[-5:].sum()/pos.sum() if len(pos) else 1.;sar=np.sort(ar);rm=max(1,int(math.ceil(n*.1)));kept=n-rm;rg=np.prod(1+sar[:kept])-1 if kept>0 else -1.;h=[1.,1.];mg=np.ones(12);sc=np.zeros(4,np.int64)
 for i in range(n):
  eb=np.searchsorted(times,ex[i]-BAR_MS);eb=min(eb,len(times)-1);h[half[eb]]*=1+ar[i];mi=month[eb]
  if 0<=mi<12:mg[mi]*=1+ar[i]
  sc[sym[i]]+=1
 pm=(mg-1>0).sum()/12.;worst=(mg-1).min();traded=(sc>0).sum();mx=sc.max()/n;days=max(1.,(end_ms-start_ms)/86400000.);gd=math.exp(math.log(equity/10000.)/days)-1
 return np.array([float(n),equity/10000.-1,gd,pf,mdd,top5,rg,h[0]-1,h[1]-1,pm,worst,float(traded),mx,ar.mean()*10000.,stp.mean(),equity])
def sd(v):
 d={k:float(v[i]) for i,k in enumerate(SUMMARY_COLUMNS)};d['n']=int(round(d['n']));d['traded_symbols']=int(round(d['traded_symbols']));return d
def dev_gate(a,b,c):return a['n']>=60 and min(a['total_return'],b['total_return'],c['total_return'])>0 and a['profit_factor']>=1.1 and a['max_drawdown']<=.2 and a['top5_positive_share']<=.4 and a['positive_month_fraction']>=.55 and a['worst_month']>=-.05 and min(a['h1_return'],a['h2_return'])>0 and a['top10pct_removed_return']>0 and a['traded_symbols']>=2 and a['max_single_symbol_trade_share']<=.8
def later_gate(a,b,c):return a['n']>=30 and min(a['total_return'],b['total_return'],c['total_return'])>0 and a['profit_factor']>=1.05 and a['max_drawdown']<=.2 and a['top5_positive_share']<=.6 and a['positive_month_fraction']>=.5
def robust(r):return (min(r['base']['h1_return'],r['base']['h2_return'],r['cost18']['total_return'],r['cost24']['total_return']),r['base']['top10pct_removed_return'],-r['base']['max_drawdown'],-r['base']['top5_positive_share'],r['candidate_id'])
def cfrom(r):
 p=dict(r['params']);h=int(p.pop('hold_bars'));st=float(p.pop('stop_atr'));return Candidate(SignalSpec(**p),h,st)
def run_stage(snapshot,stage,cands=None):
 m=load_market(snapshot,stage);blocks=build_blocks(m);start,end=PERIODS[stage];sms=int(start.value//1_000_000);ems=int(end.value//1_000_000);dt=pd.to_datetime(m.times,unit='ms',utc=True);months=np.asarray((dt.year-start.year)*12+(dt.month-start.month),dtype=np.int16);half=np.asarray(dt>=start+(end-start)/2,dtype=np.int8);rows=[]
 if cands is None:
  for idx,spec in enumerate(signal_specs(),1):
   bars,sy,sides=select_events(blocks[(spec.beta_window,spec.residual_horizon)],spec,m,stage)
   for hold,stop in itertools.product((3,12,48),(1.5,2.5,4.0)):
    c=Candidate(spec,hold,stop);a=sd(sim(m.times,m.open,m.high,m.low,m.quote,m.atr,bars,sy,sides,hold,stop,12.,sms,ems,months,half));b=sd(sim(m.times,m.open,m.high,m.low,m.quote,m.atr,bars,sy,sides,hold,stop,18.,sms,ems,months,half));d=sd(sim(m.times,m.open,m.high,m.low,m.quote,m.atr,bars,sy,sides,hold,stop,24.,sms,ems,months,half));rows.append({'candidate_id':c.candidate_id,'signal_id':spec.signal_id,'family':spec.family,'params':{**asdict(spec),'hold_bars':hold,'stop_atr':stop},'base':a,'cost18':b,'cost24':d,'gate_pass':dev_gate(a,b,d) if stage=='development' else later_gate(a,b,d)})
   if idx%100==0:print(json.dumps({'stage':stage,'done':idx,'total':1296,'rows':len(rows)}),flush=True)
 else:
  cache={}
  for c in cands:
   s=c.signal
   if s.signal_id not in cache:cache[s.signal_id]=select_events(blocks[(s.beta_window,s.residual_horizon)],s,m,stage)
   bars,sy,sides=cache[s.signal_id];a=sd(sim(m.times,m.open,m.high,m.low,m.quote,m.atr,bars,sy,sides,c.hold_bars,c.stop_atr,12.,sms,ems,months,half));b=sd(sim(m.times,m.open,m.high,m.low,m.quote,m.atr,bars,sy,sides,c.hold_bars,c.stop_atr,18.,sms,ems,months,half));d=sd(sim(m.times,m.open,m.high,m.low,m.quote,m.atr,bars,sy,sides,c.hold_bars,c.stop_atr,24.,sms,ems,months,half));rows.append({'candidate_id':c.candidate_id,'signal_id':s.signal_id,'family':s.family,'params':{**asdict(s),'hold_bars':c.hold_bars,'stop_atr':c.stop_atr},'base':a,'cost18':b,'cost24':d,'gate_pass':later_gate(a,b,d)})
 return rows,{'stage':stage,'period':[str(start),str(end)],'bars_loaded':len(m.times),'first_loaded':pd.Timestamp(int(m.times[0]),unit='ms',tz='UTC').isoformat(),'last_loaded':pd.Timestamp(int(m.times[-1]),unit='ms',tz='UTC').isoformat(),'rows':len(rows),'gate_pass_count':sum(bool(x['gate_pass']) for x in rows),'2026_opened':False,'orders_submitted':False,'funding_included':False,'champion_eligible':False}
def freeze(rows,cap=12):
 p=sorted([x for x in rows if x['gate_pass']],key=robust,reverse=True);sel=[];used=set()
 for fam in ('residual_flow_continuation','residual_mean_reversion','dispersion_absorption','dispersion_breakout'):
  x=next((r for r in p if r['family']==fam),None)
  if x:sel.append(x);used.add(x['candidate_id'])
 for x in p:
  if len(sel)>=cap:break
  if x['candidate_id'] not in used:sel.append(x);used.add(x['candidate_id'])
 return sel
def writej(p,x):p.write_text(json.dumps(x,indent=2,sort_keys=True,allow_nan=False)+'\n')
def run(snapshot,output,artifact=None):
 output.mkdir(parents=True,exist_ok=True);mh=sha256_file(snapshot/'DATASET_MANIFEST.json');assert mh=='a6f8575eccfed2129daee4596f897351d84d85ae52f061f734dc991debed3ac4'
 if artifact:assert sha256_file(artifact)=='fd3c20704cf4b8b1dc80023298920456d4ec7cf2dfe9986237d94ea8cbd51f4c'
 dev,audit=run_stage(snapshot,'development');flat=[]
 for r in dev:
  q={'candidate_id':r['candidate_id'],'signal_id':r['signal_id'],'family':r['family'],'params_json':json.dumps(r['params'],sort_keys=True),'gate_pass':r['gate_pass']}
  for sc in ('base','cost18','cost24'):
   for k,v in r[sc].items():q[f'{sc}_{k}']=v
  flat.append(q)
 pd.DataFrame(flat).to_csv(output/'development_grid.csv',index=False);reps=freeze(dev);fr={'stage':'development','dataset_manifest_sha256':mh,'representatives':[{'candidate_id':x['candidate_id'],'family':x['family'],'params':x['params'],'robust_score':robust(x)[:-1]} for x in reps],'gate_pass_count':audit['gate_pass_count'],'2024_opened':bool(reps),'2025_opened':False,'2026_opened':False};fr['content_sha256']=hashlib.sha256(json.dumps(fr,sort_keys=True,separators=(",",":")).encode()).hexdigest();writej(output/'development_freeze.json',fr)
 sel=[];sa=None;primary=None
 if reps:
  sel,sa=run_stage(snapshot,'selection',[cfrom(x) for x in reps]);writej(output/'selection_results.json',sel);p=sorted([x for x in sel if x['gate_pass']],key=robust,reverse=True);primary=p[0] if p else None
 conf=[];ca=None
 if primary:conf,ca=run_stage(snapshot,'confirmation',[cfrom(primary)]);writej(output/'confirmation_results.json',conf)
 res={'schema_version':1,'claim_id':'CLM-20260725-1738-DYNAMIC-FACTOR-001','dataset_manifest_sha256':mh,'artifact_sha256':'fd3c20704cf4b8b1dc80023298920456d4ec7cf2dfe9986237d94ea8cbd51f4c','development_audit':audit,'development_representatives':fr['representatives'],'selection_audit':sa,'selection_primary':primary,'confirmation_audit':ca,'confirmation_result':conf[0] if conf else None,'target_pass':bool(conf and conf[0]['gate_pass'] and conf[0]['base']['gmean_daily']>=.01),'champion_eligible':False,'champion_reason':'Screen lacks actual funding and order-book execution; it cannot become Champion.','2026_opened':False,'orders_submitted':False};writej(output/'result.json',res);(output/'result.sha256').write_text(sha256_file(output/'result.json')+'  result.json\n');return res
def self_test():
 x=np.arange(1.,40.);y=2*x;b=prior_beta(x,y.copy(),10,5);y[20]=1e9;a=prior_beta(x,y,10,5);assert a[20]==b[20] and a[21]!=b[21];assert len(signal_specs())==1296
 t=np.arange(20,dtype=np.int64)*BAR_MS+1672531200000;shape=(4,20);op=np.full(shape,100.);hi=np.full(shape,101.);lo=np.full(shape,99.);q=np.full(shape,1e8);atr=np.full(shape,1.);op[0,2]=95;hi[0,2]=96;lo[0,2]=94;o=sim(t,op,hi,lo,q,atr,np.array([0]),np.array([0],dtype=np.int8),np.array([1],dtype=np.int8),3,1.5,0.,t[0],t[-1]+BAR_MS,np.zeros(len(t),dtype=np.int16),np.zeros(len(t),dtype=np.int8));assert int(o[0])==1 and o[1]<0 and o[14]==1.;print('self-test passed')
def main():
 ap=argparse.ArgumentParser();ap.add_argument('--snapshot',type=Path);ap.add_argument('--output',type=Path);ap.add_argument('--artifact',type=Path);ap.add_argument('--self-test',action='store_true');a=ap.parse_args()
 if a.self_test:self_test();return 0
 r=run(a.snapshot,a.output,a.artifact);print(json.dumps({'development_gate_pass':r['development_audit']['gate_pass_count'],'selection_primary':r['selection_primary'] is not None,'target_pass':r['target_pass']},indent=2));return 0
if __name__=='__main__':raise SystemExit(main())
