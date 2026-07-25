from __future__ import annotations
import argparse,gzip,hashlib,io,json,math
from pathlib import Path
import numpy as np,pandas as pd
from numpy.lib.stride_tricks import sliding_window_view

DATES=("2023-03-01","2023-06-01","2023-09-01","2023-12-01");SYMBOLS=("BTCUSDT","ETHUSDT")
INC=2500.;PRE_MIN=10000.;MIN_N=25000.;N=4;JIT=.10;LAT=.10;HOLD=3600.;PRIOR=3600.;PRIOR_MAX=-20.
CONTRACT="50d460417cde00229df71309a2976edcdb3cb39f"

def sha(path):
 h=hashlib.sha256()
 with path.open('rb') as f:
  for b in iter(lambda:f.read(1<<20),b''):h.update(b)
 return h.hexdigest()
def open_auto(path):
 f=path.open('rb');magic=f.read(2);f.seek(0)
 return gzip.open(f,'rt',newline='') if magic==b'\x1f\x8b' else io.TextIOWrapper(f,encoding='utf-8',newline='')
def load(path):
 with open_auto(path) as f:d=pd.read_csv(f,usecols=['timestamp','side','size','price'])
 ts=pd.to_numeric(d.timestamp,errors='coerce').to_numpy(float);q=pd.to_numeric(d['size'],errors='coerce').to_numpy(float);p=pd.to_numeric(d.price,errors='coerce').to_numpy(float);s=np.where(d.side.to_numpy()=='Buy',1,-1).astype(np.int8)
 ok=np.isfinite(ts)&np.isfinite(q)&np.isfinite(p)&(q>0)&(p>0);ts,s,q,p=ts[ok],s[ok],q[ok],p[ok]
 if np.any(np.diff(ts)<0):ix=np.argsort(ts,kind='stable');ts,s,q,p=ts[ix],s[ix],q[ix],p[ix]
 return ts,s,q,p
def px_at(ts,p,q):
 q=np.asarray(q,float);ix=np.searchsorted(ts,q,'left');out=np.full(len(q),np.nan);ok=ix<len(ts);out[ok]=p[ix[ok]];return out
def px_before(ts,p,q):
 q=np.asarray(q,float);ix=np.searchsorted(ts,q,'left')-1;out=np.full(len(q),np.nan);ok=ix>=0;out[ok]=p[ix[ok]];return out
def clusters(raw):
 ts,s,q,p=raw;st=np.ones(len(ts),bool)
 if len(ts)>1:st[1:]=(s[1:]!=s[:-1])|((ts[1:]-ts[:-1])>1e-12)
 ix=np.flatnonzero(st);en=np.r_[ix[1:],len(ts)]
 return pd.DataFrame({'timestamp':ts[ix],'side':s[ix],'quantity':np.add.reduceat(q,ix),'notional':np.add.reduceat(q*p,ix),'fill_count':en-ix})
def detect(c,raw,fname,date,symbol):
 ts,_,_,p=raw;x=c[c.notional>=PRE_MIN].copy();x['fingerprint']=np.rint(x.notional/INC).astype(np.int64);out=[]
 for (side,key),g in x.groupby(['side','fingerprint'],sort=False):
  t=g.timestamp.to_numpy(float);n=g.notional.to_numpy(float)
  if len(t)<N:continue
  gaps=sliding_window_view(np.diff(t),N-1);period=np.median(gaps,axis=1);jr=np.max(np.abs(gaps-period[:,None]),axis=1)/np.maximum(period,1e-9);nw=sliding_window_view(n,N);ii=np.arange(N-1,len(t))
  valid=(period>=1)&(period<=600)&(jr<=JIT)&(nw.min(axis=1)>=MIN_N)
  if not np.any(valid):continue
  jj=ii[valid];nxt=np.full(valid.sum(),np.nan);has=jj+1<len(t);nxt[has]=t[jj[has]+1]
  out.append(pd.DataFrame({'timestamp':t[jj],'window_start_time':t[jj-(N-1)],'side':int(side),'fingerprint':int(key),'period':period[valid],'jitter_ratio':jr[valid],'window_mean_notional':nw.mean(axis=1)[valid],'window_total_notional':nw.sum(axis=1)[valid],'next_same_time':nxt}))
 if not out:return pd.DataFrame()
 z=pd.concat(out,ignore_index=True);z['score']=3/(z.jitter_ratio+.01)*np.log1p(z.window_mean_notional/1000)
 keep=[]
 for _,g in z.groupby(['side','fingerprint'],sort=False):
  active=-np.inf;g=g.sort_values('timestamp')
  for i,t,period in zip(g.index,g.timestamp,g.period):
   if t>active:keep.append(i);active=t+4*period
   else:active=max(active,t+period)
 z=z.loc[keep].copy();z['detection_time']=z.timestamp+LAT;z['detection_price']=px_at(ts,p,z.detection_time);z['sequence_start_time']=z.window_start_time+LAT;z['sequence_start_price']=px_at(ts,p,z.sequence_start_time)
 z['sequence_move_bps']=z.side*(z.detection_price/z.sequence_start_price-1)*1e4;z['prior_start_price']=px_at(ts,p,z.window_start_time.to_numpy()-PRIOR);z['prior_end_price']=px_before(ts,p,z.window_start_time.to_numpy());z['signed_prior_1h_bps']=z.side*(z.prior_end_price/z.prior_start_price-1)*1e4
 tol=np.maximum(.1,JIT*z.period.to_numpy());forecast=z.timestamp.to_numpy()+z.period.to_numpy();nxt=z.next_same_time.to_numpy();miss=(~np.isfinite(nxt))|(nxt>forecast+tol);z=z.loc[miss].copy();z['entry_time']=forecast[miss]+tol[miss]+LAT;z['entry_price']=px_at(ts,p,z.entry_time);z['post_detection_move_bps']=z.side*(z.entry_price/z.detection_price-1)*1e4
 z=z[(z.sequence_move_bps>=0)&(z.post_detection_move_bps<=0)&(z.signed_prior_1h_bps<=PRIOR_MAX)].copy();z['exit_time']=z.entry_time+HOLD;z['exit_price']=px_at(ts,p,z.exit_time);z['gross_bps']=-z.side*(z.exit_price/z.entry_price-1)*1e4;z['source_file']=fname;z['date']=date;z['symbol']=symbol
 return z.replace([np.inf,-np.inf],np.nan).dropna(subset=['entry_price','exit_price','gross_bps','signed_prior_1h_bps'])
def slot(x):
 if x.empty:return x
 x=x.sort_values(['entry_time','score'],ascending=[True,False]);keep=[];flat=-np.inf
 for i,t,e in zip(x.index,x.entry_time,x.exit_time):
  if t>=flat:keep.append(i);flat=e
 return x.loc[keep].copy()
def summary(x):
 v=x.gross_bps.to_numpy(float);n=len(v)
 if n==0:return {'n':0}
 rm=max(1,math.ceil(.1*n));kept=np.sort(v)[:max(0,n-rm)];pos=v[v>0];share=float(np.max(pos)/np.sum(pos)) if len(pos) else 1.
 return {'n':n,'gross_mean_bps':float(v.mean()),'gross_median_bps':float(np.median(v)),'positive_fraction':float((v>0).mean()),'gross_sum_bps':float(v.sum()),'net12_mean_bps':float((v-12).mean()),'net18_mean_bps':float((v-18).mean()),'net24_mean_bps':float((v-24).mean()),'top10_removed_net12_mean_bps':float((kept-12).mean()) if len(kept) else None,'top10_removed_net24_mean_bps':float((kept-24).mean()) if len(kept) else None,'largest_positive_trade_share':share,'max_gross_bps':float(v.max()),'min_gross_bps':float(v.min())}
def run(data_dir,out_dir):
 out_dir.mkdir(parents=True,exist_ok=True);manifest=[];frames={}
 for path in sorted(data_dir.glob('*USDT2023-*.csv.gz')):
  symbol=next((s for s in SYMBOLS if path.name.startswith(s)),None);date=next((d for d in DATES if d in path.name),None)
  if not symbol or not date:continue
  manifest.append({'file':path.name,'sha256':sha(path),'size_bytes':path.stat().st_size});raw=load(path);z=detect(clusters(raw),raw,path.name,date,symbol)
  if not z.empty:frames.setdefault(date,[]).append(z)
 expected={(s,d) for s in SYMBOLS for d in DATES};observed={(next(s for s in SYMBOLS if m['file'].startswith(s)),next(d for d in DATES if d in m['file'])) for m in manifest};missing=sorted(expected-observed)
 if missing:raise FileNotFoundError(f'missing preregistered validation partitions: {missing}')
 days=[slot(pd.concat(frames.get(d,[]),ignore_index=True)) if frames.get(d) else pd.DataFrame() for d in DATES];trades=pd.concat([x for x in days if not x.empty],ignore_index=True) if any(not x.empty for x in days) else pd.DataFrame();trades.to_csv(out_dir/'validation_trades.csv',index=False)
 total=summary(trades);by_date={d:summary(trades[trades.date==d]) for d in DATES};by_symbol={s:summary(g) for s,g in trades.groupby('symbol')} if not trades.empty else {};pos_dates=sum(1 for x in by_date.values() if x.get('n',0)>0 and x.get('net12_mean_bps',-1)>0)
 gates={'minimum_completed_global_slot_trades':total.get('n',0)>=10,'net_mean_positive_at_24bp':total.get('net24_mean_bps',-1)>0,'top_10_percent_trade_removed_net_mean_positive_at_12bp':(total.get('top10_removed_net12_mean_bps') or -1)>0,'minimum_positive_dates_at_12bp':pos_dates>=3,'median_net_positive_at_12bp':total.get('gross_median_bps',-1)>12,'maximum_single_trade_share_of_positive_gross_pnl':total.get('largest_positive_trade_share',1)<=.5}
 result={'schema_version':1,'result_id':'RES-20260726-METAORDER-CADENCE-001','claim_id':'CLM-20260726-0501-METAORDER-CADENCE-001','contract_commit':CONTRACT,'stage':'PREREGISTERED_PRE_2024_FATAL_VALIDATION','hard_validity_status':'PASS','economic_status':'TESTED_BELOW_GATE','2024_or_later_opened':False,'summary':total,'by_date':by_date,'by_symbol':by_symbol,'positive_dates_at_12bp':pos_dates,'gates':gates,'gate_pass':all(gates.values()),'manifest':manifest,'decision':'RETIRE_EXACT_DEPENDENCY; do not open 2024 and do not adjacent-threshold tune. Reopen only with a materially different information unit.'}
 (out_dir/'validation_result.json').write_text(json.dumps(result,indent=2,sort_keys=True)+'\n');(out_dir/'validation_manifest.json').write_text(json.dumps(manifest,indent=2,sort_keys=True)+'\n');return result
def main():
 p=argparse.ArgumentParser();p.add_argument('--data-dir',type=Path,required=True);p.add_argument('--output-dir',type=Path,required=True);a=p.parse_args();r=run(a.data_dir,a.output_dir);print(json.dumps(r,indent=2,sort_keys=True));return 0
if __name__=='__main__':raise SystemExit(main())
