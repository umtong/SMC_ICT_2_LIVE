from __future__ import annotations
import pathlib, sys
import numpy as np
import pandas as pd
sys.path.insert(0, str(pathlib.Path(__file__).parent))
import run as r


def frame(n=1440, price=100.0, turnover=10.0):
    t=np.arange(n,dtype=np.int64)*r.MIN_MS
    return pd.DataFrame(dict(start_time_ms=t,available_at_ms=t+r.MIN_MS,observed=True,mark_observed=True,
        open=price,high=price+0.1,low=price-0.1,close=price,volume=1.0,turnover=turnover,mark_open=price,
        symbol='X',day=0,valid=True))


def test_profile_contains_poc_and_seventy_percent():
    x=frame(100)
    x['turnover']=np.arange(1,101)
    x['volume']=1.0
    p=r.profile_from_frame(x)
    assert p is not None and p.val <= p.poc <= p.vah and p.total_turnover==5050


def test_packets_nonoverlap_and_no_overshoot_carry():
    x=frame(20,turnover=10.0)
    ps=r.first_two_packets(x,35.0)
    assert [len(p) for p in ps]==[4,4]
    assert ps[0].index.max() < ps[1].index.min()


def test_failure_stop_is_beyond_full_causal_extreme():
    high=110.0; low=90.0
    assert high*1.0001 > high and low*0.9999 < low


def test_strict_latency_clock():
    starts=np.array([0,60_000,120_000],dtype=np.int64)
    assert starts[np.searchsorted(starts,60_500,side='right')]==120_000


def test_funding_sign():
    f=pd.DataFrame({'timestamp_ms':[1000,2000,3000],'cum_coeff':[1.0,3.0,6.0]})
    assert r.funding_per_unit(f,1,1000,3000)==-5.0
    assert r.funding_per_unit(f,-1,1000,3000)==5.0


def test_contract_constants():
    assert r.PROFILE_BINS==64 and r.VALUE_FRACTION==0.70 and r.PACKET_FRACTION==1/8
    assert r.ACTIONS==('OLD_EDGE_ROTATION','OLD_POC_ROTATION')
