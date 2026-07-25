from __future__ import annotations
import importlib.util, sys, json
from pathlib import Path
import numpy as np
P=Path(__file__).with_name('dynamic_factor_residual.py');S=importlib.util.spec_from_file_location('dyn',P);assert S and S.loader;M=importlib.util.module_from_spec(S);sys.modules[S.name]=M;S.loader.exec_module(M)
def test_prior_beta_excludes_current():
 x=np.arange(1.,50.);y=1.7*x;b=M.prior_beta(x,y.copy(),12,6);y[30]=1e8;a=M.prior_beta(x,y,12,6);assert a[30]==b[30] and a[31]!=b[31]
def test_grid_deterministic():
 a=M.signal_specs();b=M.signal_specs();assert len(a)==1296 and [x.signal_id for x in a]==[x.signal_id for x in b] and len(a)*9==11664
def test_gap_stop_and_next_open():
 t=np.arange(20,dtype=np.int64)*M.BAR_MS+1672531200000;shape=(4,20);op=np.full(shape,100.);hi=np.full(shape,101.);lo=np.full(shape,99.);q=np.full(shape,1e8);atr=np.full(shape,1.);op[0,2]=95.;hi[0,2]=96.;lo[0,2]=94.;o=M.sim(t,op,hi,lo,q,atr,np.array([0]),np.array([0],dtype=np.int8),np.array([1],dtype=np.int8),3,1.5,0.,t[0],t[-1]+M.BAR_MS,np.zeros(len(t),dtype=np.int16),np.zeros(len(t),dtype=np.int8));assert int(o[0])==1 and o[1]<0 and o[14]==1.
def test_later_periods_sealed():
 r=json.loads(Path('/mnt/data/dynamic_factor_work/output/result.json').read_text());assert r['development_audit']['gate_pass_count']==0 and r['selection_audit'] is None and r['confirmation_audit'] is None and r['2026_opened'] is False and r['orders_submitted'] is False
