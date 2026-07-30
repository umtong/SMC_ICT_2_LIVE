from __future__ import annotations
import json,pickle
from pathlib import Path
import numpy as np,pandas as pd
from direct_core_common import ALL_SEGS,BASE_COST_RT,MODEL_DIR,OUTCOME_DIR,SCORE_DIR,STATE_DIR,SYMS,load_minute_market,ts_ms
from direct_core_account import candidate_financial,load_scores,simulate_event_path

checks=[]
def check(name,cond,detail=''):
    ok=bool(cond);checks.append({'name':name,'pass':ok,'detail':str(detail)})
    if not ok:raise AssertionError(f'{name}: {detail}')

# Label and account outcome contract must agree exactly at the selected base cost.
s=load_scores([2022,2023,2024,2025,2026])
rng=np.random.default_rng(495)
z=s[s.resolved].sample(min(5000,int(s.resolved.sum())),random_state=495)
errs=[]
for r in z.itertuples(index=False):
    fin=candidate_financial(r,BASE_COST_RT,10000.)
    acct_r=fin['ret_frac']/fin['effective_risk_fraction']
    errs.append(acct_r-float(r.net_r_base))
check('label_account_net_r_equivalence',np.max(np.abs(errs))<1e-10,np.max(np.abs(errs)))
check('entry_is_decision_plus_60s',(z.entry_ms-z.decision_ms).eq(60000).all())
check('exit_not_before_entry',(z.exit_ms>=z.entry_ms).all())
check('no_elapsed_time_label_cap',s.loc[s.resolved,'duration_min'].max()>10080,s.loc[s.resolved,'duration_min'].max())

# Check a deterministic random sample against the raw minute barriers, including
# adverse stop-first semantics and absence of earlier hits.
for sym in SYMS:
    m=load_minute_market(sym,ALL_SEGS)
    times=m.start_time_ms.to_numpy(np.int64);hi=m.high.to_numpy(float);lo=m.low.to_numpy(float)
    zz=z[z.symbol==sym].sample(min(100,len(z[z.symbol==sym])),random_state=496)
    for r in zz.itertuples(index=False):
        a=int(np.searchsorted(times,int(r.entry_ms)));e=int(np.searchsorted(times,int(r.exit_ms)))
        side=int(r.side);stop=float(r.stop_raw);target=float(r.target_raw)
        if side>0:
            sh=lo[a:e+1]<=stop;th=hi[a:e+1]>=target
        else:
            sh=hi[a:e+1]>=stop;th=lo[a:e+1]<=target
        hit=np.flatnonzero(sh|th)
        check('raw_first_hit_exists',len(hit)>0,f'{r.candidate_id}')
        first=int(hit[0])
        check('raw_first_hit_minute',a+first==e,f'{r.candidate_id} {a+first} {e}')
        expected=-1 if sh[first] else 1
        check('same_minute_stop_first',int(r.outcome)==expected,f'{r.candidate_id} {r.outcome} {expected}')

# Model chronology.
for y in (2022,2023,2024,2025,2026):
    st=json.loads((MODEL_DIR/f'direct_net_r_{y}_stats.json').read_text())
    check(f'model_{y}_cutoff',int(st['cutoff_ms'])==ts_ms(f'{y}-01-01'))

# Global-slot invariants on the selected official path.
off=load_scores([2024,2025,2026])
t,_=simulate_event_path(off,'2024-01-01','2026-07-01',.985,BASE_COST_RT)
completed=t[t.completed].sort_values('entry_ms')
check('one_global_slot_no_overlap',(completed.entry_ms.iloc[1:].to_numpy()>=completed.exit_ms.iloc[:-1].to_numpy()+120000).all())
check('continuous_nav',(np.abs(completed.nav_before.iloc[1:].to_numpy()-completed.nav_after.iloc[:-1].to_numpy())<1e-8).all())
check('risk_budget_cap',(completed.effective_risk_fraction<=.005+1e-12).all(),completed.effective_risk_fraction.max())
check('notional_cap',(completed.effective_leverage<=3+1e-12).all(),completed.effective_leverage.max())

out={'status':'PASS','checks':checks,'check_count':len(checks)}
Path('/mnt/data/direct_core_work/results/VALIDATION.json').write_text(json.dumps(out,indent=2))
print(json.dumps({'status':'PASS','checks':len(checks)},indent=2))
