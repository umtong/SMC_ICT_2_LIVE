from __future__ import annotations
import argparse,csv,gc,hashlib,json,math
from dataclasses import asdict
from datetime import datetime,timezone
from pathlib import Path
import numpy as np
import pandas as pd
import requests
import base_probe as base

CLAIM='CLM-20260726-1130-ALTLAG-DECISIONTREE-001'
STAGE1=('2023-09-17','2023-10-15','2023-11-19')
DECEMBER=('2023-12-03','2023-12-10','2023-12-17','2023-12-24')
SYMBOLS=('BTCUSDT','SOLUSDT','XRPUSDT')
FOLLOWERS=('SOLUSDT','XRPUSDT')
H=(1,2,5)
FLOORS=(0.0012,0.0018,0.0024)


def rsum(x,w):
    return pd.Series(x).rolling(w,min_periods=1).sum().to_numpy(np.float64)


def attention(leader,follower,h):
    n=len(leader['mark'])
    ltc=leader['trade_count'].reshape(-1,10).sum(axis=1).astype(float)
    ftc=follower['trade_count'].reshape(-1,10).sum(axis=1).astype(float)
    lsum,fsum=rsum(ltc,1800),rsum(ftc,1800)
    tr=np.divide(fsum,lsum,out=np.full_like(fsum,np.nan),where=lsum>0)
    lr=pd.Series(np.log(leader['mark'][9::10])).diff()
    fr=pd.Series(np.log(follower['mark'][9::10])).diff()
    def state(s):
        finite=s.notna()
        count=finite.astype(np.int16).rolling(900,min_periods=1).sum().to_numpy(float)
        nonzero=(s.fillna(0).abs()>0).astype(np.int16).rolling(900,min_periods=1).sum().to_numpy(float)
        ss=(s.fillna(0)**2).rolling(900,min_periods=1).sum().to_numpy(float)
        return ss,count,nonzero
    lss,lc,ln=state(lr); fss,fc,fn=state(fr)
    ok=(lc>=600)&(fc>=600)&(ln>=60)&(fn>=60)&(lss>0)
    vr=np.full_like(lss,np.nan); vr[ok]=np.sqrt(fss[ok]/lss[ok])
    k=np.arange(n,dtype=np.int64); pre=(k+1-h*10)//10-1
    valid=(pre>=0)&(pre<len(tr))
    tout=np.full(n,np.nan); vout=np.full(n,np.nan)
    tout[valid]=tr[pre[valid]]; vout[valid]=vr[pre[valid]]
    return tout,vout


def select_events(f,tr,vr,floor,mode):
    common=(np.isfinite(f['z'])&np.isfinite(f['gap'])&np.isfinite(f['under'])&
            np.isfinite(f['activity'])&np.isfinite(tr)&np.isfinite(vr)&
            (f['z']>=3)&(f['leader_align']>=.5)&(f['activity']>=2)&
            (tr>=1)&(vr>=1.5))
    if mode=='under':
        mask=common&(f['under']<=.75)&(f['follower_align']<=.5)&(f['gap']>=floor)
    elif mode=='over':
        mask=common&(f['under']>=1.25)&(f['follower_align']>=.5)&((-f['gap'])>=floor)
    else: raise ValueError(mode)
    q=np.flatnonzero(mask); out=[]; allowed=0; mark=f['leader_mark']
    for raw in q:
        i=int(raw)
        if i<allowed: continue
        start=int(f['start_idx'][i]); direction=int(f['direction'][i]); shock=abs(float(f['btc_return'][i]))
        if start<0 or direction==0 or not np.isfinite(mark[start]): continue
        signed=direction*np.log(mark[i:]/mark[start]); cond=np.isfinite(signed)&(signed<=.25*shock)
        run=0; release=len(mark)
        for off,flag in enumerate(cond):
            run=run+1 if flag else 0
            if run>=10: release=i+off+1; break
        allowed=max(i+1,release)
        gap=float(f['gap'][i] if mode=='under' else -f['gap'][i])
        out.append({'decision_bin':i,'start_idx':start,'direction':direction,
                    'z':float(f['z'][i]),'gap':gap,'expected':float(f['expected'][i]),
                    'beta':float(f['beta'][i]),'btc_return':float(f['btc_return'][i]),
                    'follower_return':float(f['follower_return'][i]),'under':float(f['under'][i]),
                    'activity':float(f['activity'][i]),'leader_align':float(f['leader_align'][i]),
                    'follower_align':float(f['follower_align'][i]),'trade_ratio':float(tr[i]),
                    'vol_ratio':float(vr[i]),'release_bin':int(release)})
    return out


def raw_times_prices(path):
    chunks=[]
    for chunk in pd.read_csv(path,usecols=['timestamp','price'],chunksize=500000):
        t=pd.to_numeric(chunk['timestamp'],errors='coerce').to_numpy(float)
        p=pd.to_numeric(chunk['price'],errors='coerce').to_numpy(float)
        ok=np.isfinite(t)&np.isfinite(p)&(p>0)
        if ok.any(): chunks.append((t[ok],p[ok]))
    if not chunks: return np.array([],float),np.array([],float)
    ts=np.concatenate([x[0] for x in chunks]); px=np.concatenate([x[1] for x in chunks])
    order=np.argsort(ts,kind='stable')
    return ts[order],px[order]


def acquire_day(session,cache,date,with_raw=False):
    arrays={}; records=[]; raw={}
    for symbol in SYMBOLS:
        url=f'https://public.bybit.com/trading/{symbol}/{symbol}{date}.csv.gz'
        target=cache/symbol/f'{symbol}{date}.csv.gz'
        status,payload,error=base._download(session,url,target)
        if status!=200: raise RuntimeError(f'source unavailable {url}: {status} {error}')
        rec=base.inspect_source(target,symbol,date,url,payload)
        if not rec.timestamp_monotonic: raise RuntimeError(f'nonmonotonic {url}')
        arrays[symbol]=base.aggregate(target,date); records.append(rec)
        if with_raw and symbol in FOLLOWERS: raw[symbol]=raw_times_prices(target)
        print(json.dumps(asdict(rec),sort_keys=True),flush=True)
    return arrays,records,raw


def day_counts(arrays,date,mode):
    counts={}; rows=[]; signals=[]; leader=arrays['BTCUSDT']
    for sym in FOLLOWERS:
        follower=arrays[sym]
        for h in H:
            f=base.continuous_features(leader,follower,h); tr,vr=attention(leader,follower,h)
            for floor in FLOORS:
                events=select_events(f,tr,vr,floor,mode)
                key=f'{sym}|{date}|h{h}|gap{int(round(floor*10000))}bp'; counts[key]=len(events)
                for e in events:
                    row={'symbol':sym,'date':date,'horizon':h,'floor':floor,**e}; rows.append(row)
                    if floor==0.0012: signals.append(row)
            del f,tr,vr; gc.collect()
    return counts,rows,signals


def count_aggregate(counts,dates,max_share_limit,date_min,cell_min,total_min=15,total24_min=5):
    date12={d:0 for d in dates}; cell12={f'{s}|{d}':0 for s in FOLLOWERS for d in dates}
    total12=total24=0
    for key,v in counts.items():
        sym,date,_,floor=key.split('|')
        if floor=='gap12bp': total12+=v; date12[date]+=v; cell12[f'{sym}|{date}']+=v
        elif floor=='gap24bp': total24+=v
    share=max(date12.values())/total12 if total12 else 1.0
    agg={'total_12bp':total12,'total_24bp':total24,'date_12bp':date12,
         'follower_date_12bp':cell12,'maximum_single_date_share_12bp':share}
    checks={'total_12bp_at_least_'+str(total_min):total12>=total_min,
            'total_24bp_at_least_'+str(total24_min):total24>=total24_min,
            'dates_with_at_least_3_events':sum(v>=3 for v in date12.values())>=date_min,
            'follower_date_cells_with_at_least_3_events':sum(v>=3 for v in cell12.values())>=cell_min,
            'maximum_single_date_share':share<=max_share_limit}
    return agg,checks,all(checks.values())


def crosses_funding(entry,exit_):
    start=datetime.fromtimestamp(entry,tz=timezone.utc)
    day=datetime(start.year,start.month,start.day,tzinfo=timezone.utc)
    while day.timestamp()<=exit_:
        for hour in (0,8,16):
            boundary=day.timestamp()+hour*3600
            if entry < boundary <= exit_: return True
        day=(pd.Timestamp(day)+pd.Timedelta(days=1)).to_pydatetime()
    return False


def first_trade(raw,ts):
    times,prices=raw; idx=int(np.searchsorted(times,ts,side='left'))
    if idx>=len(times): return None
    return float(times[idx]),float(prices[idx])


def exit_trade(arrays,raw,event,entry_time,entry_price,date):
    leader=arrays['BTCUSDT']; follower=arrays[event['symbol']]
    direction=int(event['direction']); start=int(event['start_idx']); beta=float(event['beta']); gap0=float(event['gap'])
    day0=base.utc_start(date); first_bin=max(int(math.ceil((entry_time-day0)*10)),int(event['decision_bin'])+1)
    close_run=leader_run=0
    for i in range(first_bin,len(leader['mark'])):
        lm=leader['mark'][i]; fm=follower['mark'][i]
        if not (np.isfinite(lm) and np.isfinite(fm) and np.isfinite(leader['mark'][start]) and np.isfinite(follower['mark'][start])):
            close_run=leader_run=0; continue
        btc_move=math.log(lm/leader['mark'][start]); fol_move=math.log(fm/follower['mark'][start])
        gap=direction*(beta*btc_move-fol_move); leader_signed=direction*btc_move
        close_run=close_run+1 if gap<=.25*gap0 else 0
        leader_run=leader_run+1 if leader_signed<=0 else 0
        adverse=direction*math.log(fm/entry_price)<=(-.5*gap0)
        if close_run>=10 or leader_run>=10 or adverse:
            trigger=day0+(i+1)*.1; found=first_trade(raw,trigger)
            if found is None: return None,'NO_EXIT_TRADE'
            return found,'GAP_CLOSE' if close_run>=10 else ('LEADER_INVALID' if leader_run>=10 else 'ADVERSE')
    return None,'NO_STATE_EXIT'


def replay_pnl(day_data,signals,latency_ms,costs=(12,18,24)):
    trades=[]; unvalued=[]; by_date={d:[] for d in DECEMBER}
    for s in signals: by_date[s['date']].append(s)
    for date in DECEMBER:
        arrays,raw=day_data[date]; groups={}
        for s in by_date[date]: groups.setdefault(int(s['decision_bin']),[]).append(s)
        slot_free=-math.inf; day0=base.utc_start(date)
        for decision_bin in sorted(groups):
            decision_time=day0+(decision_bin+1)*.1
            if decision_time<slot_free: continue
            s=sorted(groups[decision_bin],key=lambda x:(-x['gap'],-x['z'],x['symbol'],x['horizon']))[0]
            found=first_trade(raw[s['symbol']],decision_time+latency_ms/1000)
            if found is None:
                unvalued.append({'date':date,'latency_ms':latency_ms,'reason':'NO_ENTRY_TRADE',**s}); continue
            entry_time,entry_price=found; exited,reason=exit_trade(arrays,raw[s['symbol']],s,entry_time,entry_price,date)
            if exited is None:
                unvalued.append({'date':date,'latency_ms':latency_ms,'reason':reason,**s}); continue
            exit_time,exit_price=exited
            if crosses_funding(entry_time,exit_time):
                unvalued.append({'date':date,'latency_ms':latency_ms,'reason':'FUNDING_BOUNDARY',**s}); continue
            gross=float(s['direction']*math.log(exit_price/entry_price)*10000)
            row={'date':date,'symbol':s['symbol'],'horizon':s['horizon'],'latency_ms':latency_ms,
                 'decision_time':decision_time,'entry_time':entry_time,'exit_time':exit_time,
                 'entry_price':entry_price,'exit_price':exit_price,'gross_bps':gross,'exit_reason':reason,
                 'gap_bps':s['gap']*10000,'z':s['z']}
            for c in costs: row[f'net_{c}bps']=gross-c
            trades.append(row); slot_free=exit_time
    return trades,unvalued


def pnl_metrics(trades,unvalued,latency):
    rows=[r for r in trades if r['latency_ms']==latency]; gross=np.array([r['gross_bps'] for r in rows],float)
    metrics={'trades':len(rows),'unvalued':sum(r['latency_ms']==latency for r in unvalued)}
    for c in (12,18,24):
        x=gross-c; metrics[f'mean_{c}bps']=float(x.mean()) if len(x) else None
        metrics[f'median_{c}bps']=float(np.median(x)) if len(x) else None
        remove=max(1,int(math.ceil(.1*len(x)))) if len(x) else 0
        kept=np.sort(x)[:len(x)-remove] if len(x)>remove else np.array([])
        metrics[f'top10_removed_mean_{c}bps']=float(kept.mean()) if len(kept) else None
    date_net={d:sum(r['net_12bps'] for r in rows if r['date']==d) for d in DECEMBER}
    metrics['date_net_12bps']=date_net; metrics['positive_dates_12bps']=sum(v>0 for v in date_net.values())
    pos=gross[gross>0]; metrics['largest_winner_share_positive_gross']=float(pos.max()/pos.sum()) if len(pos) and pos.sum()>0 else 1.0
    return metrics


def write_rows(path,rows):
    path.parent.mkdir(parents=True,exist_ok=True)
    if not rows: path.write_text(''); return
    fields=sorted({k for r in rows for k in r})
    with path.open('w',newline='',encoding='utf-8') as f:
        w=csv.DictWriter(f,fieldnames=fields); w.writeheader(); w.writerows(rows)


def source_manifest(records):
    b=json.dumps([asdict(r) for r in records],sort_keys=True,separators=(',',':')).encode()
    return hashlib.sha256(b).hexdigest()


def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--output',type=Path,required=True); ap.add_argument('--cache',type=Path,required=True)
    a=ap.parse_args(); a.output.mkdir(parents=True,exist_ok=True)
    stage1_counts={}; stage1_rows=[]; stage1_records=[]
    with requests.Session() as session:
        session.headers['User-Agent']='SMC_ICT_2_LIVE-altlag-decision-tree/1.0'
        for date in STAGE1:
            arr,recs,_=acquire_day(session,a.cache,date,False); c,r,_=day_counts(arr,date,'under')
            stage1_counts.update(c); stage1_rows.extend(r); stage1_records.extend(recs); del arr; gc.collect()
        agg,checks,stage1_pass=count_aggregate(stage1_counts,STAGE1,.7,2,2)
        stage1={'schema_version':1,'claim_id':CLAIM,'stage':'ATTENTION_UNDERREACTION_REPLICATION',
                'status':'PASS' if stage1_pass else 'FAIL','gate_passed':stage1_pass,'aggregate':agg,
                'gate_checks':checks,'unique_event_counts':stage1_counts,'sources':[asdict(x) for x in stage1_records],
                'source_manifest_sha256':source_manifest(stage1_records),'pnl_computed':False,
                '2024_2026_opened':False,'orders_submitted':False}
        s1=a.output/'stage1'; s1.mkdir(parents=True,exist_ok=True)
        (s1/'result.json').write_text(json.dumps(stage1,indent=2,sort_keys=True)+'\n'); write_rows(s1/'events.csv',stage1_rows)
        dec_records=[]; dec_data={}; dec_counts={}; dec_rows=[]; dec_signals=[]
        for date in DECEMBER:
            arr,recs,raw=acquire_day(session,a.cache,date,stage1_pass)
            mode='under' if stage1_pass else 'over'; c,r,s=day_counts(arr,date,mode)
            dec_counts.update(c); dec_rows.extend(r); dec_signals.extend(s); dec_records.extend(recs)
            if stage1_pass: dec_data[date]=(arr,raw)
            else: del arr,raw; gc.collect()
    if stage1_pass:
        all_trades=[]; all_unvalued=[]; metrics={}
        for latency in (100,300):
            t,u=replay_pnl(dec_data,dec_signals,latency); all_trades.extend(t); all_unvalued.extend(u); metrics[str(latency)]=pnl_metrics(t,u,latency)
        m100,m300=metrics['100'],metrics['300']
        def positive(v): return v is not None and v>0
        gate={'minimum_20_trades':m100['trades']>=20 and m300['trades']>=20,
              'positive_mean_and_median_24bps':all(positive(m[f'{k}_24bps']) for m in (m100,m300) for k in ('mean','median')),
              'positive_top10_removed_mean_12bps':positive(m100['top10_removed_mean_12bps']) and positive(m300['top10_removed_mean_12bps']),
              'at_least_3_positive_dates_12bps':m100['positive_dates_12bps']>=3 and m300['positive_dates_12bps']>=3,
              'largest_winner_share_at_most_0_4':m100['largest_winner_share_positive_gross']<=.4 and m300['largest_winner_share_positive_gross']<=.4,
              'zero_unvalued':len(all_unvalued)==0}
        passed=all(gate.values())
        result={'schema_version':1,'claim_id':CLAIM,'mode':'UNDERREACTION_PNL_CONFIRMATION','status':'PASS' if passed else 'FAIL',
                'gate_passed':passed,'stage1_gate_passed':True,'metrics':metrics,'gate_checks':gate,
                'sources':[asdict(x) for x in dec_records],'source_manifest_sha256':source_manifest(dec_records),
                'pnl_computed':True,'funding_approximated':False,'2024_2026_opened':False,'orders_submitted':False,
                'next_action':'Freeze official 2024H1 account replay with exact funding and bid/ask execution.' if passed else 'Retire this underreaction payoff dependency.'}
        out=a.output/'stage2_underreaction_pnl'; out.mkdir(parents=True,exist_ok=True)
        (out/'result.json').write_text(json.dumps(result,indent=2,sort_keys=True)+'\n'); write_rows(out/'trades.csv',all_trades); write_rows(out/'unvalued.csv',all_unvalued)
    else:
        agg2,checks2,passed=count_aggregate(dec_counts,DECEMBER,.6,3,3)
        result={'schema_version':1,'claim_id':CLAIM,'mode':'OVERREACTION_OPPORTUNITY','status':'PASS' if passed else 'FAIL',
                'gate_passed':passed,'stage1_gate_passed':False,'aggregate':agg2,'gate_checks':checks2,
                'unique_event_counts':dec_counts,'sources':[asdict(x) for x in dec_records],
                'source_manifest_sha256':source_manifest(dec_records),'pnl_computed':False,
                '2024_2026_opened':False,'orders_submitted':False,
                'next_action':'Freeze a separate overreaction PnL contract on later pre-2024 dates.' if passed else 'Retire the BTC-to-alt residual family.'}
        out=a.output/'stage2_overreaction_opportunity'; out.mkdir(parents=True,exist_ok=True)
        (out/'result.json').write_text(json.dumps(result,indent=2,sort_keys=True)+'\n'); write_rows(out/'events.csv',dec_rows)
    summary={'claim_id':CLAIM,'stage1_passed':stage1_pass,'selected_mode':result['mode'],'stage2_passed':result['gate_passed'],'result_path':str(out/'result.json')}
    (a.output/'decision.json').write_text(json.dumps(summary,indent=2,sort_keys=True)+'\n')
    print(json.dumps(summary,sort_keys=True)); return 0

if __name__=='__main__': raise SystemExit(main())
