from __future__ import annotations
from pathlib import Path
import pandas as pd
import numpy as np

ROOT=Path('/mnt/data/work/canonical')


def load_asset(asset:str)->pd.DataFrame:
    frames=[]
    for year in (2021,2022,2023):
        d=ROOT/f'{asset}{year}'
        b=pd.read_parquet(d/'trade_bars/5m.parquet', columns=['start_time_ms','open','high','low','close','volume','turnover','is_complete','available_at_ms'])
        oi=pd.read_parquet(d/'streams/open_interest_5m.parquet', columns=['timestamp_ms','observed','open_interest','available_at_ms']).rename(columns={'timestamp_ms':'start_time_ms','available_at_ms':'oi_available_at_ms','observed':'oi_observed'})
        ar=pd.read_parquet(d/'streams/account_ratio_5m.parquet', columns=['timestamp_ms','observed','buy_ratio','sell_ratio','available_at_ms']).rename(columns={'timestamp_ms':'start_time_ms','available_at_ms':'ar_available_at_ms','observed':'ar_observed'})
        p=pd.read_parquet(d/'streams/premium_index_1m.parquet', columns=['start_time_ms','observed','close','available_at_ms'])
        p['start_time_ms']=(p['start_time_ms']//300000)*300000
        p=p.groupby('start_time_ms',sort=False).agg(premium=('close','last'),premium_observed=('observed','all'),premium_available_at_ms=('available_at_ms','max')).reset_index()
        m=pd.read_parquet(d/'streams/mark_price_1m.parquet', columns=['start_time_ms','observed','close','available_at_ms'])
        m['start_time_ms']=(m['start_time_ms']//300000)*300000
        m=m.groupby('start_time_ms',sort=False).agg(mark=('close','last'),mark_observed=('observed','all'),mark_available_at_ms=('available_at_ms','max')).reset_index()
        ix=pd.read_parquet(d/'streams/index_price_1m.parquet', columns=['start_time_ms','observed','close','available_at_ms'])
        ix['start_time_ms']=(ix['start_time_ms']//300000)*300000
        ix=ix.groupby('start_time_ms',sort=False).agg(index=('close','last'),index_observed=('observed','all'),index_available_at_ms=('available_at_ms','max')).reset_index()
        x=b.merge(oi,on='start_time_ms',how='left',validate='one_to_one').merge(ar,on='start_time_ms',how='left',validate='one_to_one').merge(p,on='start_time_ms',how='left',validate='one_to_one').merge(m,on='start_time_ms',how='left',validate='one_to_one').merge(ix,on='start_time_ms',how='left',validate='one_to_one')
        x['year']=year
        frames.append(x)
    x=pd.concat(frames,ignore_index=True).sort_values('start_time_ms').reset_index(drop=True)
    x['symbol']=asset+'USDT'
    x['time']=pd.to_datetime(x.start_time_ms,unit='ms',utc=True)
    x['decision_ms']=x['available_at_ms'].astype('int64')
    for c in ['oi_available_at_ms','ar_available_at_ms','premium_available_at_ms','mark_available_at_ms','index_available_at_ms']:
        x[c+'_ok']=x[c].fillna(np.iinfo(np.int64).max).astype('int64')<=x['decision_ms']
    return x


def rolling_z(s:pd.Series, w:int, minp:int|None=None)->pd.Series:
    minp=minp or max(20,w//4)
    mean=s.rolling(w,min_periods=minp).mean().shift(1)
    std=s.rolling(w,min_periods=minp).std(ddof=0).shift(1)
    return (s-mean)/std.replace(0,np.nan)


def features(x:pd.DataFrame)->pd.DataFrame:
    x=x.copy();lc=np.log(x['close']);lo=np.log(x['open_interest'].where(x['open_interest']>0))
    for h in [1,3,6,12,24,48,96,288]:
        x[f'ret_{h}']=lc.diff(h);x[f'oi_chg_{h}']=lo.diff(h)
    prev=x['close'].shift(1)
    tr=pd.concat([(x.high-x.low).abs(),(x.high-prev).abs(),(x.low-prev).abs()],axis=1).max(axis=1)
    x['tr_pct']=tr/x['close'];x['atr_12']=x['tr_pct'].rolling(12,min_periods=6).mean().shift(1);x['atr_48']=x['tr_pct'].rolling(48,min_periods=24).mean().shift(1)
    x['rv_288']=x['ret_1'].rolling(288,min_periods=96).std(ddof=0).shift(1);x['rv_2016']=x['ret_1'].rolling(2016,min_periods=288).std(ddof=0).shift(1)
    x['price_shock_3']=x['ret_3']/x['rv_2016'].replace(0,np.nan)/np.sqrt(3);x['price_shock_6']=x['ret_6']/x['rv_2016'].replace(0,np.nan)/np.sqrt(6)
    x['oi_shock_3']=rolling_z(x['oi_chg_3'],2016,288);x['oi_shock_6']=rolling_z(x['oi_chg_6'],2016,288)
    x['volume_z']=rolling_z(np.log1p(x['volume']),2016,288);x['turnover_z']=rolling_z(np.log1p(x['turnover']),2016,288)
    br=x['buy_ratio'].clip(1e-5,1-1e-5);x['ratio_logit']=np.log(br/(1-br));x['ratio_chg_3']=x['ratio_logit'].diff(3);x['ratio_chg_12']=x['ratio_logit'].diff(12);x['ratio_z']=rolling_z(x['ratio_logit'],2016,288)
    x['premium_z']=rolling_z(x['premium'],2016,288);x['premium_chg_3']=x['premium'].diff(3);x['basis']=(x['mark']-x['index'])/x['index'];x['basis_z']=rolling_z(x['basis'],2016,288)
    x['range_pos_12']=(x['close']-x['low'].rolling(12,min_periods=12).min().shift(1))/(x['high'].rolling(12,min_periods=12).max().shift(1)-x['low'].rolling(12,min_periods=12).min().shift(1)).replace(0,np.nan)
    x['range_pos_48']=(x['close']-x['low'].rolling(48,min_periods=48).min().shift(1))/(x['high'].rolling(48,min_periods=48).max().shift(1)-x['low'].rolling(48,min_periods=48).min().shift(1)).replace(0,np.nan)
    x['hour']=x['time'].dt.hour;x['dow']=x['time'].dt.dayofweek
    x['entry']=x['open'].shift(-1)
    for h in [3,6,12,24,48,96,288]:x[f'fwd_{h}']=np.log(x['close'].shift(-h)/x['entry'])
    return x


def add_cross(a:pd.DataFrame,b:pd.DataFrame)->tuple[pd.DataFrame,pd.DataFrame]:
    cols=['start_time_ms','ret_3','ret_6','ret_12','oi_chg_3','oi_chg_6','premium_z','ratio_z']
    aa=a.merge(b[cols],on='start_time_ms',how='left',suffixes=('','_peer'));bb=b.merge(a[cols],on='start_time_ms',how='left',suffixes=('','_peer'))
    for x in [aa,bb]:
        for h in [3,6,12]:x[f'rel_ret_{h}']=x[f'ret_{h}']-x[f'ret_{h}_peer']
        for h in [3,6]:x[f'rel_oi_{h}']=x[f'oi_chg_{h}']-x[f'oi_chg_{h}_peer']
    return aa,bb

if __name__=='__main__':
    btc=features(load_asset('BTC'));eth=features(load_asset('ETH'));btc,eth=add_cross(btc,eth)
    out=Path('/mnt/data/work/auction_value');pd.concat([btc,eth],ignore_index=True).to_parquet(out/'features_2021_2023.parquet',index=False)
