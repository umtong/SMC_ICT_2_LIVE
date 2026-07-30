from __future__ import annotations

import json
from pathlib import Path
import pandas as pd

OUT=Path('/mnt/data/work/auction_value')
actions=pd.read_parquet(OUT/'action_outcomes.parquet')
policies=pd.read_csv(OUT/'variant_model_2022.csv')

decision_year=pd.to_datetime(actions.decision_ms,unit='ms',utc=True).dt.year
exit_time=pd.to_datetime(actions.exit_ts_ms,unit='ms',utc=True)
stage_end=pd.to_datetime((decision_year+1).astype(str)+'-01-01',utc=True)

assert (actions.entry_ts_ms-actions.decision_ms==60_000).all()
assert (decision_year==actions.year).all()
assert (exit_time<=stage_end).all()
assert not ((policies.trades>=60)&(policies.gd>0)&(policies.pf>1)).any()
assert (actions[actions.year.isin([2021,2022])].groupby('action').unit_return.mean()<0).all()

summary={
    'action_rows':int(len(actions)),
    'entry_delay_ms':60_000,
    'cross_stage_exit_count':int((exit_time>stage_end).sum()),
    'policy_routes_2022':int(len(policies)),
    'eligible_routes_2022':int(((policies.trades>=60)&(policies.gd>0)&(policies.pf>1)).sum()),
    'best_traded_return_2022':float(policies.loc[policies.trades>0,'return'].max()),
    'best_dense_return_2022':float(policies.loc[policies.trades>=60,'return'].max()),
    'status':'PASS_NEGATIVE_DECISION',
}
print(json.dumps(summary,indent=2,sort_keys=True))
