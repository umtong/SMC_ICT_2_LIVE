
from pathlib import Path
import json, math, numpy as np, pandas as pd
import run

def test_contract():
    c=run.Contract()
    assert c.elapsed_time_liquidation is False
    assert c.global_slot==1
    assert c.decision_hours_utc==tuple(range(6,14))
    assert c.threshold_multiplier==1.25

def test_target_alignment():
    ix=pd.date_range("2023-01-01",periods=300,freq="1h",tz="UTC");frames={}
    for i,s in enumerate(run.SYMBOLS):
        op=np.exp(np.arange(len(ix))*.001)*(i+1);cl=op*1.0001
        frames[s]=pd.DataFrame({"open":op,"high":cl*1.001,"low":op*.999,"close":cl,
            "quote_volume":1e6,"taker_buy_quote":510000.},index=ix)
    _,_,y,_=run.matrix(frames)
    assert math.isclose(y[0,0],math.log(frames["BTCUSDT"].iloc[25].open/frames["BTCUSDT"].iloc[1].open),abs_tol=1e-15)

def test_funding_pro_rata():
    a=pd.Timestamp("2025-01-01T00:00:00Z");b=a+pd.Timedelta(hours=20)
    v,m,n=run.fund_frac(None,a,b,1)
    assert m=="ADVERSE_FALLBACK" and n==2 and math.isclose(v,-2.5/10000,abs_tol=1e-15)

def test_reference_if_artifact_present(tmp_path):
    here=Path(__file__).resolve().parent
    snap=here/"source_artifact"/"snapshot"
    if not snap.exists(): return
    actual=run.proxy(snap,tmp_path)
    ref=json.loads((here/"DEVELOPMENT_REFERENCE.json").read_text())
    for c in ("12","24","72","96"):
        a=actual["paths"][c];e=ref["paths"][c]
        for k in ("trade_count","ending_nav_multiple_marked","geometric_daily_growth","profit_factor",
                  "median_trade_return","maximum_drawdown_closed_nav","long_trade_count",
                  "short_trade_count","mean_duration_hours"):
            if isinstance(e[k],int): assert a[k]==e[k]
            else: assert math.isclose(a[k],e[k],rel_tol=0,abs_tol=1e-12)
        assert [x["entry_time"] for x in a["trade_records"]]==e["entry_times"]
        assert [x["exit_time"] for x in a["trade_records"]]==e["exit_times"]
