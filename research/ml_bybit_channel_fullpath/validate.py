from __future__ import annotations
import hashlib, json
from pathlib import Path
import numpy as np
import pandas as pd

ROOT=Path('/mnt/data/bybit_donchian_exact/full_path')
RESULT=json.loads((ROOT/'RESULT.json').read_text())

def sha(path):
 h=hashlib.sha256()
 with path.open('rb') as f:
  for b in iter(lambda:f.read(1<<20),b''):h.update(b)
 return h.hexdigest()

def main():
 checks={}
 off=RESULT['official_2024_2026']
 checks['cost_monotone_end_nav']=off['13']['end_nav']>off['18']['end_nav']>off['24']['end_nav']
 checks['calendar_days_912']=all(off[str(c)]['calendar_days']==912 for c in (13,18,24))
 checks['no_liquidation']=all(not off[str(c)]['liquidated'] for c in (13,18,24))
 checks['model_fit_boundaries_causal']=all(pd.Timestamp(x['training_last_release'])<pd.Timestamp(x['fit_completed_at']) for x in RESULT['model_updates'])
 for c in (13,18,24):
  tr=pd.read_parquet(ROOT/f'TRADES_{c}bp.parquet').sort_values('entry_ts_ms')
  daily=pd.read_parquet(ROOT/f'DAILY_NAV_{c}bp.parquet')
  checks[f'{c}_one_global_slot']=bool((tr.entry_ts_ms.iloc[1:].to_numpy()>=tr.exit_ts_ms.iloc[:-1].to_numpy()+60_000).all()) if len(tr)>1 else True
  checks[f'{c}_entry_before_exit']=bool((tr.entry_ts_ms<tr.exit_ts_ms).all())
  checks[f'{c}_risk_budget']=bool(((tr.leverage*(abs(tr.entry-tr.stop)/tr.entry+c/10000))<=0.0500000001).all())
  checks[f'{c}_daily_points_913']=len(daily)==913
  checks[f'{c}_endpoint_match']=abs(float(daily.iloc[-1].nav)-off[str(c)]['end_nav'])<1e-6
  checks[f'{c}_log_identity']=abs(float(daily.log_return.sum())-np.log(off[str(c)]['end_nav']/10000))<1e-10
  checks[f'{c}_allowed_exit_reasons']=set(tr.exit_reason).issubset({'STOP','CHANNEL_EXIT','FINAL_NAV_MARK'})
  halves=off[str(c)]['half_years']
  checks[f'{c}_half_continuity']=all(abs(halves[i]['end_nav']-halves[i+1]['start_nav'])<1e-6 for i in range(len(halves)-1))
 wr=RESULT['winner_removed_13bp']
 checks['winner_removed_positive']=wr['end_nav']>10000 and wr['geometric_daily_growth']>0
 checks['winner_removed_rerouted']=wr['completed_trades']!=off['13']['completed_trades'] or wr['removed_event_count']>0
 checks['all_pass']=all(checks.values())
 files=[]
 for p in sorted(ROOT.iterdir()):
  if p.is_file() and p.name not in {'VALIDATION_ATTESTATION.json','SHA256SUMS','VALIDATION.log'}:
   files.append({'path':p.name,'bytes':p.stat().st_size,'sha256':sha(p)})
 att={'schema_version':1,'attestation_id':'VAL-20260730-BYBIT-DONCHIAN-ML-FULLPATH-001','result_id':RESULT['result_id'],'status':'PASS' if checks['all_pass'] else 'FAIL','checks':checks,'files':files,'orders_submitted':False}
 (ROOT/'VALIDATION_ATTESTATION.json').write_text(json.dumps(att,indent=2,sort_keys=True,default=lambda o: bool(o) if isinstance(o,np.bool_) else float(o) if isinstance(o,(np.floating,np.integer)) else str(o))+'\n')
 with (ROOT/'SHA256SUMS').open('w') as f:
  for x in files:f.write(f"{x['sha256']}  {x['path']}\n")
 print(json.dumps(att,indent=2,default=lambda o: bool(o) if isinstance(o,np.bool_) else float(o) if isinstance(o,(np.floating,np.integer)) else str(o)))
 if not checks['all_pass']:raise SystemExit(1)
if __name__=='__main__':main()
