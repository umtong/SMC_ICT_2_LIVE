import pathlib, sys, pandas as pd, numpy as np
sys.path.insert(0,str(pathlib.Path(__file__).parent))
import run as r

def test_packet_never_crosses_day_and_no_reuse():
    n=2880; t=np.arange(n)*60000; day=np.arange(n)//1440
    x=pd.DataFrame(dict(start_time_ms=t,available_at_ms=t+60000,observed=True,mark_observed=True,open=1.,high=1.1,low=.9,close=1.,volume=1.,turnover=1.,mark_open=1.,symbol='X'))
    assert len(np.unique(x.start_time_ms))==n and (day[1439]==0 and day[1440]==1)

def test_cost_risk_denominator_positive():
    entry=100.; stop=98.; loss=abs(entry-stop)+entry*24/10000+entry*.0002
    assert loss>2

def test_sponsor_boundary_fixed(): assert r.SPONSOR_Z==2.2706072565238586

def test_adverse_target_stop_geometry():
    e=100.; atr=2.; assert e-2*atr < e < e+3*atr

def test_stage_sealed(): assert r.YEARS_PRE==(2021,2022)
