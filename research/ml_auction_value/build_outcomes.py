from __future__ import annotations
from pathlib import Path
import numpy as np
import pandas as pd

ROOT=Path('/mnt/data/work/canonical')
OUT=Path('/mnt/data/work/auction_value')
SRC=OUT/'features_2021_2023.parquet'
RT_COST=.0024; HALF=RT_COST/2; RISK=.005; LEV=3.0

class FirstCrossIndex:
    """Segment-tree index for first threshold crossing in an interval."""
    def __init__(self, values):
        v=np.asarray(values,float)
        self.length=len(v);size=1
        while size<self.length:size*=2
        self.size=size
        self.min_tree=np.full(2*size,np.inf,float);self.max_tree=np.full(2*size,-np.inf,float)
        self.min_tree[size:size+self.length]=np.where(np.isfinite(v),v,np.inf)
        self.max_tree[size:size+self.length]=np.where(np.isfinite(v),v,-np.inf)
        for i in range(size-1,0,-1):
            self.min_tree[i]=min(self.min_tree[2*i],self.min_tree[2*i+1])
            self.max_tree[i]=max(self.max_tree[2*i],self.max_tree[2*i+1])
    def _first(self,node,nl,nr,left,right,threshold,want_le):
        if nr<=left or right<=nl:return self.length
        bound=self.min_tree[node] if want_le else self.max_tree[node]
        if (want_le and bound>threshold) or ((not want_le) and bound<threshold):return self.length
        if nr-nl==1:return nl if nl<self.length else self.length
        mid=(nl+nr)//2
        hit=self._first(node*2,nl,mid,left,right,threshold,want_le)
        return hit if hit<self.length else self._first(node*2+1,mid,nr,left,right,threshold,want_le)
    def first_le(self,left,right,threshold):
        if left>=right:return self.length
        return self._first(1,0,self.size,max(0,left),min(right,self.length),threshold,True)
    def first_ge(self,left,right,threshold):
        if left>=right:return self.length
        return self._first(1,0,self.size,max(0,left),min(right,self.length),threshold,False)


class Market:
    def __init__(self,short):
        ms=[];fs=[]
        for y in (2021,2022,2023):
            d=ROOT/f'{short}{y}'
            m=pd.read_parquet(d/'trade_bars/1m.parquet',columns=['start_time_ms','observed','open','high','low','close'])
            ms.append(m[m.observed].drop(columns='observed'))
            f=pd.read_parquet(d/'streams/funding_events.parquet',columns=['timestamp_ms','funding_rate'])
            mark=pd.read_parquet(d/'streams/mark_price_1m.parquet',columns=['start_time_ms','open','observed'])
            mark=mark[mark.observed].rename(columns={'start_time_ms':'timestamp_ms','open':'mark'})[['timestamp_ms','mark']]
            fs.append(f.merge(mark,on='timestamp_ms',how='left'))
        m=pd.concat(ms).drop_duplicates('start_time_ms').sort_values('start_time_ms')
        self.ts=m.start_time_ms.to_numpy(np.int64);self.op=m.open.to_numpy(float);self.hi=m.high.to_numpy(float);self.lo=m.low.to_numpy(float);self.cl=m.close.to_numpy(float)
        self.hi_index=FirstCrossIndex(self.hi);self.lo_index=FirstCrossIndex(self.lo)
        f=pd.concat(fs).drop_duplicates('timestamp_ms').sort_values('timestamp_ms')
        self.fts=f.timestamp_ms.to_numpy(np.int64);self.fr=f.funding_rate.to_numpy(float);self.fm=f.mark.to_numpy(float)
    def exact_open(self,ts):
        i=np.searchsorted(self.ts,ts);return float(self.op[i]) if i<len(self.ts) and self.ts[i]==ts else np.nan
    def mark(self,ts):
        i=np.searchsorted(self.ts,ts,side='right')-1;return float(self.cl[max(0,min(i,len(self.cl)-1))])
    def funding(self,start,end,side,qty):
        i=np.searchsorted(self.fts,start,side='right');j=np.searchsorted(self.fts,end,side='right')
        return float(np.nansum(-side*self.fr[i:j]*self.fm[i:j]*qty)) if i<j else 0.0
    def resolve(self,start,end,side,stop,target=None):
        i=int(np.searchsorted(self.ts,start));j=int(np.searchsorted(self.ts,end,side='right'))
        if i>=j:return None
        if side>0:
            si=self.lo_index.first_le(i,j,stop);ti=self.hi_index.first_ge(i,j,target) if target is not None else len(self.ts)
        else:
            si=self.hi_index.first_ge(i,j,stop);ti=self.lo_index.first_le(i,j,target) if target is not None else len(self.ts)
        if si>=j and ti>=j:return None
        if si<=ti:
            k=si;return int(self.ts[k]),float(min(self.op[k],stop) if side>0 else max(self.op[k],stop)),'STOP'
        k=ti;return int(self.ts[k]),float(max(self.op[k],target) if side>0 else min(self.op[k],target)),'TARGET'


class StateView:
    def __init__(self,g):
        self.g=g.sort_values('decision_ms').reset_index(drop=True)
        self.decision=self.g.decision_ms.to_numpy(np.int64)
        self.close=self.g.close.to_numpy(float)
        self.cross=FirstCrossIndex(self.close)
        self.trail_hits={}
        for h in (12,24):
            lo=self.g[f'trail_lo_{h}'].to_numpy(float);hi=self.g[f'trail_hi_{h}'].to_numpy(float)
            self.trail_hits[(h,1)]=np.flatnonzero(self.close<lo)
            self.trail_hits[(h,-1)]=np.flatnonzero(self.close>hi)
    def first_trail(self,start,end,h,side):
        hits=self.trail_hits[(h,side)];k=int(np.searchsorted(hits,start,side='left'))
        return int(hits[k]) if k<len(hits) and hits[k]<end else end
    def continuation_exit(self,start,end,side,edge,h):
        reenter=self.cross.first_le(start+1,end,edge) if side>0 else self.cross.first_ge(start+1,end,edge)
        trail=self.first_trail(start+1,end,h,side)
        return min(reenter,trail,end)
    def excursion_exit(self,start,end,event_side,threshold):
        if event_side>0:return self.cross.first_ge(start+1,end,np.nextafter(threshold,np.inf))
        return self.cross.first_le(start+1,end,np.nextafter(threshold,-np.inf))


def prepare(config_step=.0005,config_vf=.70):
    f=pd.read_parquet(SRC).sort_values(['symbol','start_time_ms']).reset_index(drop=True).replace([np.inf,-np.inf],np.nan)
    f['date']=f.time.dt.floor('D')
    p=pd.read_parquet(OUT/'daily_profiles.parquet')
    p=p[(p.log_step==config_step)&(p.value_fraction==config_vf)].copy()
    f=f.merge(p,on=['symbol','date'],how='left',suffixes=('','_profile'))
    g=f.groupby('symbol',sort=False)
    f['prev_close5']=g.close.shift(1)
    f['recent3_hi']=g.high.rolling(3,min_periods=3).max().reset_index(level=0,drop=True)
    f['recent3_lo']=g.low.rolling(3,min_periods=3).min().reset_index(level=0,drop=True)
    for h in (12,24):
        f[f'trail_lo_{h}']=g.low.rolling(h,min_periods=h).min().shift(1).reset_index(level=0,drop=True)
        f[f'trail_hi_{h}']=g.high.rolling(h,min_periods=h).max().shift(1).reset_index(level=0,drop=True)
    f['body_ratio']=(f.close-f.open).abs()/(f.high-f.low).replace(0,np.nan)
    f['close_location']=(f.close-f.low)/(f.high-f.low).replace(0,np.nan)
    f['entry_ts_ms']=f.decision_ms.astype(np.int64)+60_000
    mk={'BTCUSDT':Market('BTC'),'ETHUSDT':Market('ETH')}
    f['entry_price']=np.nan
    for sym,idx in f.groupby('symbol').groups.items():
        m=mk[sym];ts=f.loc[idx,'entry_ts_ms'].to_numpy(np.int64);pos=np.searchsorted(m.ts,ts);vals=np.full(len(ts),np.nan);ok=pos<len(m.ts);eq=np.zeros(len(ts),bool);eq[ok]=m.ts[pos[ok]]==ts[ok];vals[eq]=m.op[pos[eq]];f.loc[idx,'entry_price']=vals
    return f,mk


def build_events(f):
    upper=(f.close>f.vah)&(f.prev_close5<=f.vah)
    lower=(f.close<f.val)&(f.prev_close5>=f.val)
    x=f[(upper|lower)&f.entry_price.notna()&f.is_complete&f.poc.notna()].copy()
    x['side']=np.where(upper.loc[x.index],1,-1)
    x['edge']=np.where(x.side>0,x.vah,x.val)
    x['node']=np.where(x.side>0,x.upper_node,x.lower_node)
    x['corridor_mean_ratio']=np.where(x.side>0,x.upper_corridor_mean_ratio,x.lower_corridor_mean_ratio)
    x['corridor_min_ratio']=np.where(x.side>0,x.upper_corridor_min_ratio,x.lower_corridor_min_ratio)
    x['corridor_max_ratio']=np.where(x.side>0,x.upper_corridor_max_ratio,x.lower_corridor_max_ratio)
    x['profile_extreme']=np.where(x.side>0,x.prev_high,x.prev_low)
    atrp=x.atr_12*x.close
    x['break_depth_atr']=x.side*(x.close-x.edge)/atrp
    x['node_distance_atr']=x.side*(x.node-x.entry_price)/atrp
    x['extreme_distance_atr']=x.side*(x.profile_extreme-x.entry_price)/atrp
    x['poc_distance_atr']=x.side*(x.entry_price-x.poc)/atrp
    x['value_width_atr']=(x.vah-x.val)/atrp
    x['prev_day_return_side']=x.side*np.log(x.prev_close/x.prev_open)
    x['side_ret_1']=x.side*x.ret_1;x['side_ret_3']=x.side*x.ret_3;x['side_ret_12']=x.side*x.ret_12
    x['side_oi_3']=x.side*x.oi_chg_3;x['side_ratio_z']=x.side*x.ratio_z;x['side_premium_z']=x.side*x.premium_z
    x['side_rel_ret_3']=x.side*x.rel_ret_3
    return x.sort_values(['decision_ms','symbol']).reset_index(drop=True)


def outcome(ev,state,market,action,stop_buffer,trail_h):
    g=state.g
    side=int(ev.side if action=='CONT' else -ev.side);entry=float(ev.entry_price);atr=float(ev.atr_12*ev.close)
    if not np.isfinite(atr) or atr<=0:return None
    stage_end_ms=int(pd.Timestamp(f'{int(ev.year)+1}-01-01',tz='UTC').timestamp()*1000)
    end_i=int(np.searchsorted(state.decision,stage_end_ms,side='left'))
    if action=='CONT':
        stop=float(ev.edge-ev.side*stop_buffer*atr)
        target=float(ev.node) if np.isfinite(ev.node) and ev.side*(ev.node-entry)>.10*atr else None
        j=state.continuation_exit(int(ev._gidx),end_i,int(ev.side),float(ev.edge),trail_h)
    else:
        stop=float(ev.recent3_hi+stop_buffer*atr) if ev.side>0 else float(ev.recent3_lo-stop_buffer*atr)
        target=float(ev.poc)
        ext=float(ev.recent3_hi if ev.side>0 else ev.recent3_lo);threshold=ext+.10*atr if ev.side>0 else ext-.10*atr
        j=state.excursion_exit(int(ev._gidx),end_i,int(ev.side),threshold)
    state_ts=int(g.decision_ms.iloc[j])+60_000 if j<end_i else stage_end_ms
    if (side>0 and stop>=entry) or (side<0 and stop<=entry):return None
    search_end=min(state_ts,stage_end_ms-60_000)
    resolved=market.resolve(int(ev.entry_ts_ms),search_end,side,stop,target)
    if resolved:xt,xp,reason=resolved
    elif state_ts<stage_end_ms:
        xt=state_ts;xp=market.exact_open(xt);xp=xp if np.isfinite(xp) else market.mark(xt);reason='STATE_LOSS'
    else:
        xt=stage_end_ms;xp=market.mark(stage_end_ms-1);reason='BOUNDARY_MARK'
    loss=abs(entry-stop)/entry+RT_COST;notional=min(LEV,RISK/max(loss,1e-8));qty=notional/entry
    pnl=qty*side*(xp-entry)-HALF*qty*(entry+xp)+market.funding(int(ev.entry_ts_ms),xt,side,qty)
    return {'action':action,'action_side':side,'stop_buffer':stop_buffer,'trail_h':trail_h,'entry':entry,'stop':stop,'target':target,'exit':xp,'exit_ts_ms':xt,'reason':reason,'unit_return':pnl,'notional_fraction':notional,'duration_min':(xt-int(ev.entry_ts_ms))/60000}


def main():
  allout=[]
  for step,vf in [(.0005,.70)]:
    f,mk=prepare(step,vf);events=build_events(f);print('config',step,vf,'events',len(events),events.groupby(['symbol','year']).size().to_dict(),flush=True)
    groups={s:StateView(g) for s,g in f.groupby('symbol')}
    maps={s:pd.Series(np.arange(len(st.g)),index=st.decision).to_dict() for s,st in groups.items()}
    for evd in events.to_dict('records'):
      evd['_gidx']=maps[evd['symbol']][evd['decision_ms']]
      class E: pass
      ev=E();[setattr(ev,k,v) for k,v in evd.items()]
      state=groups[ev.symbol]
      base={k:evd[k] for k in evd if k!='_gidx'}
      for action in ('CONT','REV'):
          o=outcome(ev,state,mk[ev.symbol],action,.25,12)
          if o:allout.append({**base,'log_step':step,'value_fraction':vf,**o})
    print('done',step,vf,len(allout),flush=True)
  out=pd.DataFrame(allout);out.to_parquet(OUT/'action_outcomes.parquet',index=False)
  print(out.groupby(['log_step','value_fraction','action','stop_buffer','trail_h','year']).unit_return.agg(['count','mean','median',lambda x:(x>0).mean()]).to_string())
if __name__=='__main__':main()
