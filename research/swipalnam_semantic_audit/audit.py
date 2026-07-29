from __future__ import annotations
import argparse, json, math
from pathlib import Path
import numpy as np
import pandas as pd

MINUTE_MS=60_000
DAY_MS=86_400_000
EPS=1e-12
LEVEL_HIGH=['last_swing_high','equal_high_level','opening_range_high','prev_4h_high','prev_session_high','prev_day_high','prev_week_high']
LEVEL_LOW=['last_swing_low','equal_low_level','opening_range_low','prev_4h_low','prev_session_low','prev_day_low','prev_week_low']

def confirmed_pivots(df,left=2,right=2):
    h=df.high.to_numpy(float); l=df.low.to_numpy(float); n=len(df)
    dh=np.full(n,np.nan); dl=np.full(n,np.nan)
    for origin in range(left,n-right):
        detect=origin+right
        if h[origin] >= np.nanmax(h[origin-left:origin+right+1]): dh[detect]=h[origin]
        if l[origin] <= np.nanmin(l[origin-left:origin+right+1]): dl[detect]=l[origin]
    return pd.DataFrame({'last_swing_high':pd.Series(dh).ffill(), 'last_swing_low':pd.Series(dl).ffill(),
                         'new_swing_high':np.isfinite(dh),'new_swing_low':np.isfinite(dl)})

def enrich_15m(df):
    out=df[df.get('is_complete',True)].copy().reset_index(drop=True)
    pc=out.close.shift(1)
    tr=pd.concat([(out.high-out.low),(out.high-pc).abs(),(out.low-pc).abs()],axis=1).max(axis=1)
    out['atr']=tr.ewm(alpha=1/14,adjust=False,min_periods=14).mean()
    out['atr_pct']=out.atr/out.close
    out['range']=out.high-out.low
    out['body_signed']=out.close-out.open
    out['body_atr']=out.body_signed.abs()/out.atr
    out['range_atr']=out['range']/out.atr
    out['lower_wick']=out[['open','close']].min(axis=1)-out.low
    out['upper_wick']=out.high-out[['open','close']].max(axis=1)
    out['close_location']=(out.close-out.low)/out['range'].replace(0,np.nan)
    out=pd.concat([out,confirmed_pivots(out,2,2)],axis=1)
    out['internal_high']=out.high.shift(1).rolling(12,min_periods=6).max()
    out['internal_low']=out.low.shift(1).rolling(12,min_periods=6).min()
    dt=pd.to_datetime(out.start_time_ms,unit='ms',utc=True)
    day=dt.dt.floor('D')
    daily=out.assign(_day=day).groupby('_day').agg(day_high=('high','max'),day_low=('low','min')).shift(1)
    out['prev_day_high']=daily.day_high.reindex(day).to_numpy(); out['prev_day_low']=daily.day_low.reindex(day).to_numpy()
    hour=dt.dt.hour.to_numpy(); bucket=np.select([hour<7,hour<13,hour<21],[0,1,2],default=3)
    day_no=(dt.dt.floor('D').astype('int64')//(DAY_MS*1_000_000)).to_numpy(); sid=day_no*4+bucket
    sessions=out.assign(_sid=sid).groupby('_sid').agg(high=('high','max'),low=('low','min')).shift(1)
    out['prev_session_high']=sessions.high.reindex(sid).to_numpy(); out['prev_session_low']=sessions.low.reindex(sid).to_numpy()
    out['session_bucket']=bucket
    week=dt.dt.to_period('W-SUN').dt.start_time.dt.tz_localize('UTC')
    weekly=out.assign(_week=week).groupby('_week').agg(week_high=('high','max'),week_low=('low','min')).shift(1)
    out['prev_week_high']=weekly.week_high.reindex(week).to_numpy(); out['prev_week_low']=weekly.week_low.reindex(week).to_numpy()
    h4=(out.start_time_ms//(240*MINUTE_MS)).astype('int64')
    four=out.assign(_h4=h4).groupby('_h4').agg(h4_high=('high','max'),h4_low=('low','min')).shift(1)
    out['prev_4h_high']=four.h4_high.reindex(h4).to_numpy(); out['prev_4h_low']=four.h4_low.reindex(h4).to_numpy()
    rank=out.groupby(pd.Series(sid,index=out.index)).cumcount(); opening_bars=4
    first=rank<opening_bars
    oph=out.high.where(first).groupby(pd.Series(sid,index=out.index)).transform('max')
    opl=out.low.where(first).groupby(pd.Series(sid,index=out.index)).transform('min')
    out['opening_range_high']=oph.where(rank>=opening_bars); out['opening_range_low']=opl.where(rank>=opening_bars)
    she=out.last_swing_high.where(out.new_swing_high); sle=out.last_swing_low.where(out.new_swing_low)
    ph=she.ffill().shift(1); pl=sle.ffill().shift(1); tol=out.atr*0.18
    out['equal_high_level']=((out.last_swing_high+ph)/2).where(out.new_swing_high & ((out.last_swing_high-ph).abs()<=tol)).ffill()
    out['equal_low_level']=((out.last_swing_low+pl)/2).where(out.new_swing_low & ((out.last_swing_low-pl).abs()<=tol)).ffill()
    out['timeframe_min']=15
    return out

def level_values(row,direction):
    names=LEVEL_HIGH if direction>0 else LEVEL_LOW
    vals=[]
    for name in names:
        v=float(row.get(name,np.nan))
        if np.isfinite(v): vals.append((name,v))
    return vals

def target_from_known(row,direction,reference,risk):
    vals=[(n,v) for n,v in level_values(row,direction) if (v-reference)*direction>0]
    vals=sorted(vals,key=lambda x:x[1],reverse=direction<0)
    for n,v in vals:
        if (v-reference)*direction >= 1.35*risk:
            return n,v,True
    atr=float(row.get('atr',risk))
    return 'measured_delivery', reference+direction*3*max(risk,atr), False

def swept_level(row,direction):
    atr=float(row.atr)
    if not np.isfinite(atr) or atr<=0:return None
    names=LEVEL_LOW if direction>0 else LEVEL_HIGH
    hit=[]
    for name in names:
        v=float(row.get(name,np.nan))
        if not np.isfinite(v):continue
        if direction>0 and float(row.low)<v<float(row.close): hit.append((name,v,(v-float(row.low))/atr))
        if direction<0 and float(row.high)>v>float(row.close): hit.append((name,v,(float(row.high)-v)/atr))
    if not hit:return None
    levels=np.array([x[1] for x in hit]); tolerance=max(atr*.12,float(row.close)*.0003)
    confluence=max(int(np.sum(np.abs(levels-level)<=tolerance)) for level in levels)
    chosen=max(hit,key=lambda x:x[2])
    return *chosen,confluence

def make_zone(open_,close,high,low,direction,ob_i,fvg_low,fvg_high,actual_ob):
    if direction>0: ob_low,ob_high=float(low[ob_i]),float(max(open_[ob_i],close[ob_i]))
    else: ob_low,ob_high=float(min(open_[ob_i],close[ob_i])),float(high[ob_i])
    ol=max(ob_low,fvg_low); oh=min(ob_high,fvg_high); overlap=oh>ol
    zl,zh=(ol,oh) if overlap else (min(ob_low,fvg_low),max(ob_high,fvg_high))
    return ob_low,ob_high,overlap,zl,zh

def continuation_candidates(symbol,frame):
    c=frame.close.to_numpy(float); o=frame.open.to_numpy(float); h=frame.high.to_numpy(float); l=frame.low.to_numpy(float)
    atr=frame.atr.to_numpy(float); body=frame.body_atr.to_numpy(float); rng=frame.range_atr.to_numpy(float); loc=frame.close_location.to_numpy(float)
    ih=frame.internal_high.to_numpy(float); il=frame.internal_low.to_numpy(float); signed=frame.body_signed.to_numpy(float)
    prior_long=np.r_[False,c[:-1]<=ih[:-1]]; prior_short=np.r_[False,c[:-1]>=il[:-1]]
    valid=np.isfinite(atr)&(atr>0)&np.isfinite(body)&np.isfinite(rng)
    longs=np.flatnonzero(valid&(signed>0)&(c>ih)&prior_long&(body>=.35)&(rng>=.65)&(loc>=.58))
    shorts=np.flatnonzero(valid&(signed<0)&(c<il)&prior_short&(body>=.35)&(rng>=.65)&(loc<=.42))
    rows=[]
    for direction,inds in ((1,longs),(-1,shorts)):
      for i in inds:
        if i<2:continue
        row=frame.iloc[int(i)]; break_level=float(ih[i] if direction>0 else il[i]); ext=(c[i]-break_level)*direction/max(atr[i],EPS)
        if not np.isfinite(ext) or ext<=0:continue
        if direction>0: gl,gh=float(h[i-2]),float(l[i])
        else: gl,gh=float(h[i]),float(l[i-2])
        gap=gh-gl; genuine_fvg=gap>0
        if not genuine_fvg: gl,gh=sorted((float(o[i]),float(c[i]))); fvg_atr=0.0
        else:fvg_atr=gap/max(atr[i],EPS)
        ob_i=max(0,int(i)-1); genuine_ob=False
        for j in range(int(i)-1,max(-1,int(i)-11),-1):
            opposite=c[j]<o[j] if direction>0 else c[j]>o[j]
            if opposite:ob_i=j;genuine_ob=True;break
        ob_low,ob_high,overlap,zl,zh=make_zone(o,c,h,l,direction,ob_i,gl,gh,genuine_ob)
        if not(np.isfinite(zl) and np.isfinite(zh) and zh>zl>0):continue
        ref=(zl+zh)/2; recent=slice(max(0,int(i)-10),int(i)+1)
        stop_anchor=min(ob_low,float(np.min(l[recent]))) if direction>0 else max(ob_high,float(np.max(h[recent])))
        risk=abs(ref-stop_anchor)
        if risk<=0:continue
        tname,target,target_known=target_from_known(row,direction,ref,risk); rr=(target-ref)*direction/risk
        if not np.isfinite(rr) or rr<1:continue
        rows.append(dict(candidate_id=f'{symbol}-CONT15-{int(row.start_time_ms)}-{direction:+d}',symbol=symbol,direction=direction,
            model_family='continuation',decision_time_ms=int(row.available_at_ms),bar_index=int(i),sweep_depth_atr=ext,
            displacement_body_atr=float(body[i]),displacement_range_atr=float(rng[i]),fvg_low=gl,fvg_high=gh,fvg_atr=fvg_atr,
            genuine_fvg=genuine_fvg,genuine_ob=genuine_ob,ob_low=ob_low,ob_high=ob_high,fvg_ob_overlap=overlap,
            union_zone=not overlap,zone_low=zl,zone_high=zh,stop_anchor=stop_anchor,target_price=target,target_name=tname,
            target_is_known=target_known,structural_rr=rr,atr=float(atr[i]),pd_aligned=False))
    return pd.DataFrame(rows)

def sweep_candidates(symbol,frame):
    c=frame.close.to_numpy(float); o=frame.open.to_numpy(float); h=frame.high.to_numpy(float); l=frame.low.to_numpy(float)
    atr=frame.atr.to_numpy(float); body=frame.body_atr.to_numpy(float); rng=frame.range_atr.to_numpy(float); loc=frame.close_location.to_numpy(float)
    signed=frame.body_signed.to_numpy(float); ih=frame.internal_high.to_numpy(float); il=frame.internal_low.to_numpy(float)
    rows=[]; n=len(frame)
    for sweep_i in range(60,n-5):
      sweep=frame.iloc[sweep_i]; sa=float(sweep.atr)
      if not np.isfinite(sa):continue
      for direction in (1,-1):
        ev=swept_level(sweep,direction)
        if ev is None:continue
        level_name,level,sweep_atr,confluence=ev
        di=None; gl=gh=fvg_atr=np.nan; genuine_fvg=False
        for i in range(sweep_i,min(n,sweep_i+5)):
            if signed[i]*direction<=0:continue
            break_level=float(ih[i] if direction>0 else il[i]); broke=c[i]>break_level if direction>0 else c[i]<break_level
            lok=loc[i]>=.55 if direction>0 else loc[i]<=.45
            if not(broke and lok and body[i]>=.25 and rng[i]>=.55):continue
            if direction>0:glo,ghi=float(h[i-2]),float(l[i])
            else:glo,ghi=float(h[i]),float(l[i-2])
            gap=ghi-glo; genuine_fvg=gap>0
            if not genuine_fvg:glo,ghi=sorted((float(o[i]),float(c[i])));gap=0.0
            di=i;gl,gh=glo,ghi;fvg_atr=gap/max(atr[i],EPS);break
        if di is None:continue
        disp=frame.iloc[di]; ob_i=max(sweep_i-2,di-1); genuine_ob=False
        for j in range(di-1,max(-1,sweep_i-3),-1):
            opposite=c[j]<o[j] if direction>0 else c[j]>o[j]
            if opposite:ob_i=j;genuine_ob=True;break
        ob_low,ob_high,overlap,zl,zh=make_zone(o,c,h,l,direction,ob_i,gl,gh,genuine_ob)
        if not(np.isfinite(zl) and np.isfinite(zh) and zh>zl>0):continue
        ref=(zl+zh)/2; stop_anchor=float(np.min(l[sweep_i:di+1]) if direction>0 else np.max(h[sweep_i:di+1]));risk=abs(ref-stop_anchor)
        if risk<=0:continue
        basic=[float(disp.get(nm,np.nan)) for nm in (['last_swing_high','prev_day_high','prev_session_high'] if direction>0 else ['last_swing_low','prev_day_low','prev_session_low'])]
        basic=[v for v in basic if np.isfinite(v) and (v-ref)*direction>0]
        if basic: base_target=min(basic) if direction>0 else max(basic); base_known=True
        else: base_target=ref+direction*3*float(disp.atr);base_known=False
        targets=[(level_name,base_target,base_known)]
        targets += [(nm,v,True) for nm,v in level_values(disp,direction)]
        valid=[]
        for nm,v,known in targets:
            dist=(v-ref)*direction
            if np.isfinite(v) and dist>0 and dist/risk>=1:valid.append((nm,v,dist/risk,known))
        valid.sort(key=lambda x:x[1],reverse=direction<0)
        ded=[]; tolerance=max(float(disp.atr)*.10,ref*.00025)
        for item in valid:
            if all(abs(item[1]-p[1])>tolerance for p in ded):ded.append(item)
        if not ded:
            fb=ref+direction*2.5*max(risk,float(disp.atr));ded=[('measured_delivery',fb,abs(fb-ref)/risk,False)]
        selected=[]
        for idx in (0,len(ded)//2,len(ded)-1):
            if ded[idx] not in selected:selected.append(ded[idx])
        for variant,(nm,target,rr,known) in enumerate(selected[:3]):
            rows.append(dict(candidate_id=f'{symbol}-15-{int(disp.start_time_ms)}-{direction:+d}-{sweep_i}-T{variant}',symbol=symbol,direction=direction,
              model_family='sweep',decision_time_ms=int(disp.available_at_ms),bar_index=int(di),sweep_index=int(sweep_i),swept_level_name=level_name,
              sweep_depth_atr=sweep_atr,displacement_body_atr=float(body[di]),displacement_range_atr=float(rng[di]),
              fvg_low=gl,fvg_high=gh,fvg_atr=fvg_atr,genuine_fvg=genuine_fvg,genuine_ob=genuine_ob,ob_low=ob_low,ob_high=ob_high,
              fvg_ob_overlap=overlap,union_zone=not overlap,zone_low=zl,zone_high=zh,stop_anchor=stop_anchor,target_price=target,target_name=nm,
              target_is_known=known,structural_rr=rr,atr=float(disp.atr),pd_aligned=False))
    return pd.DataFrame(rows)

def main():
 ap=argparse.ArgumentParser();ap.add_argument('--root',default='/mnt/data/alds_core');ap.add_argument('--start',default='2023-01-01');ap.add_argument('--end',default='2024-07-01');ap.add_argument('--out',default='/mnt/data/swipalnam_candidates.pkl.gz');args=ap.parse_args()
 lo=int(pd.Timestamp(args.start,tz='UTC').timestamp()*1000);hi=int(pd.Timestamp(args.end,tz='UTC').timestamp()*1000)
 parts=[]
 for sym in ['BTCUSDT','ETHUSDT']:
    df=pd.read_pickle(Path(args.root)/sym/'bars_15m.pkl.gz');df=df[(df.start_time_ms>=lo)&(df.start_time_ms<hi)]
    f=enrich_15m(df); print(sym,'bars',len(f),flush=True)
    a=sweep_candidates(sym,f); print(sym,'sweep',len(a),flush=True)
    b=continuation_candidates(sym,f); print(sym,'cont',len(b),flush=True)
    parts.extend([a,b])
 cand=pd.concat(parts,ignore_index=True).sort_values('decision_time_ms').reset_index(drop=True)
 cand['selected_config']=(cand.sweep_depth_atr>=.1)&(cand.displacement_body_atr>=1.0)&(cand.fvg_atr>=0)&(cand.structural_rr>=.875)
 cand['strict_fvg_overlap']=(cand.fvg_atr>=.03)&cand.genuine_fvg&cand.genuine_ob&cand.fvg_ob_overlap
 cand['strict_all']=cand.strict_fvg_overlap&cand.target_is_known
 cand.to_pickle(args.out,compression='gzip')
 print('total',len(cand),'selected',int(cand.selected_config.sum()),'strict',int((cand.selected_config&cand.strict_all).sum()))
 print(cand[cand.selected_config].groupby(['model_family','genuine_fvg','genuine_ob','fvg_ob_overlap','target_is_known']).size().sort_values(ascending=False).head(30))

if __name__=='__main__':main()
