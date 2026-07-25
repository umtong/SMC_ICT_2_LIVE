from pathlib import Path
import sys
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from auction_profile_screen import Event, profile_for_slice, trade_exit, simulate, BAR_MS


def _data(n=20, start=0):
    t=np.arange(n,dtype=np.int64)*BAR_MS+start
    o=np.full(n,100.0); h=np.full(n,101.0); l=np.full(n,99.0); c=np.full(n,100.0)
    v=np.full(n,10.0)
    return {'open_time_ms':t,'open':o,'high':h,'low':l,'close':c,'quote_volume':v,'taker_buy_quote':v/2}


def test_profile_is_bounded_and_volume_conserved():
    d=_data(12)
    d['low'][:]=99.0; d['high'][:]=101.0; d['close'][:]=100.0
    p=profile_for_slice(d,0,12,bins=8,method='uniform')
    assert 99.0 <= p['val'] <= p['poc'] <= p['vah'] <= 101.0
    assert abs(p['volume']-120.0)<1e-9


def test_adverse_same_bar_orders_stop_before_target():
    d=_data(3)
    d['high'][0]=106.0; d['low'][0]=94.0
    ev=Event('BTCUSDT',0,0,100.0,1,95.0,105.0,1.0,0,'synthetic')
    _,_,px,reason=trade_exit(d,ev,3*BAR_MS)
    assert px==95.0 and reason=='stop'


def test_gap_stop_fills_at_worse_open():
    d=_data(3)
    d['open'][0]=93.0; d['high'][0]=94.0; d['low'][0]=92.0; d['close'][0]=93.0
    ev=Event('BTCUSDT',0,0,100.0,1,95.0,105.0,1.0,0,'synthetic')
    _,_,px,reason=trade_exit(d,ev,3*BAR_MS)
    assert px==93.0 and reason=='gap_stop'


def test_one_global_slot_uses_highest_score_at_same_time():
    data={'BTCUSDT':_data(5),'ETHUSDT':_data(5)}
    data['BTCUSDT']['high'][0]=102; data['BTCUSDT']['low'][0]=98
    data['ETHUSDT']['high'][0]=106; data['ETHUSDT']['low'][0]=99
    a=Event('BTCUSDT',0,0,100,1,99,101,1.0,0,'a')
    b=Event('ETHUSDT',0,0,100,1,99,105,2.0,0,'b')
    r=simulate(data,[a,b],0,5*BAR_MS,roundtrip_bps=12)
    assert r['trade_count']==1
    assert r['trades'][0]['symbol']=='ETHUSDT'
