from __future__ import annotations
import importlib.util, sys
from pathlib import Path
import numpy as np, pandas as pd
p=Path(__file__).resolve().parents[1]/'research/dollar_bar_absorption_v2.py';s=importlib.util.spec_from_file_location('dbar',p);m=importlib.util.module_from_spec(s);sys.modules[s.name]=m;s.loader.exec_module(m)

def fixture(days=25):
 idx=pd.date_range('2023-01-01',periods=days*1440,freq='1min',tz='UTC');x=pd.DataFrame(index=idx);x['open']=100.;x['high']=100.1;x['low']=99.9;x['close']=100.;x['volume']=1.;x['quote_volume']=100.;x['num_trades']=1.;x['signed_quote']=0.;return x

def test_current_day_does_not_change_threshold():
 x=fixture();a=m.prior_daily_thresholds(x,144);y=x.copy();day=y.index[-1].floor('D');y.loc[day:,'quote_volume']*=100;b=m.prior_daily_thresholds(y,144);assert a.loc[day]==b.loc[day]

def test_minute_is_not_split():
 x=fixture();b=m.build_dollar_bars(x,144);assert b.source_minutes.ge(1).all();assert b.quote_volume.mod(100).abs().lt(1e-9).all()

def test_gap_creates_new_segment():
 x=fixture().drop(pd.Timestamp('2023-01-25 12:00',tz='UTC'));b=m.build_dollar_bars(x,144);assert b.segment_id.nunique()>=2

def test_candidate_ids_unique():
 ids=[c.candidate_id for c in m.candidate_grid()];assert len(ids)==324 and len(ids)==len(set(ids))
