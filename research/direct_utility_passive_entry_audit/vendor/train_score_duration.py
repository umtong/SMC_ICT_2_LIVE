from __future__ import annotations
import argparse,gc,json,pickle,time
from pathlib import Path
import numpy as np,pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
from direct_core_common import FEATURES,OUT,OUTCOME_DIR,STATE_DIR,SYMS,build_training_frame,side_feature_frame,ts_ms


def tag(alpha:float)->str:
    return str(alpha).replace('.','p')

def empirical_cdf(sorted_values,values):
    return np.searchsorted(sorted_values,values,side='right')/len(sorted_values)

def training(max_operation_year:int):
    p=OUT/'training_samples_2021_2025.parquet' if max_operation_year>2024 else OUT/'training_samples_2021_2023.parquet'
    if p.exists():return pd.read_parquet(p)
    yrs=range(2021,min(max_operation_year-1,2025)+1)
    d=build_training_frame(yrs);d.to_parquet(p,index=False,compression='zstd');return d

def fit(alpha,year,samples,force=False):
    d=OUT/f'models_duration_a{tag(alpha)}';d.mkdir(exist_ok=True)
    mp=d/f'model_{year}.pkl';cp=d/f'train_pred_{year}.npy';sp=d/f'stats_{year}.json'
    if mp.exists() and cp.exists() and sp.exists() and not force:
        return pickle.load(mp.open('rb')),np.load(cp),json.loads(sp.read_text())
    tr=samples[samples.exit_ms<ts_ms(f'{year}-01-01')].copy()
    x=tr[FEATURES].astype('float32');duration=np.maximum(tr.duration_min.to_numpy(float),1)
    y=tr.net_r.to_numpy(float)/np.power(duration,alpha)
    m=HistGradientBoostingRegressor(loss='squared_error',learning_rate=.04,max_iter=160,max_leaf_nodes=7,min_samples_leaf=1000,l2_regularization=50,random_state=7100+int(alpha*100)+year)
    t=time.time();m.fit(x,y);pred=m.predict(x)
    st={'alpha':alpha,'operation_year':year,'cutoff_ms':ts_ms(f'{year}-01-01'),'n_train':len(tr),'fit_seconds':time.time()-t,'target_mean':float(y.mean()),'pred_mean':float(pred.mean()),'pred_std':float(pred.std()),'train_corr':float(np.corrcoef(pred,y)[0,1])}
    pickle.dump(m,mp.open('wb'));np.save(cp,np.sort(pred));sp.write_text(json.dumps(st,indent=2));return m,np.sort(pred),st

def score(alpha,year,m,cdf,prev=None,prevcdf=None,force=False):
    d=OUT/f'scores_duration_a{tag(alpha)}';d.mkdir(exist_ok=True)
    p=d/f'scores_outcomes_{year}.parquet'
    if p.exists() and not force:return pd.read_parquet(p)
    rows=[];lag_end=ts_ms(f'{year}-01-01 06:00') if year in (2025,2026) else -1
    for sym in SYMS:
        states=pd.read_parquet(STATE_DIR/f'states_{year}_{sym}.parquet');out=pd.read_parquet(OUTCOME_DIR/f'outcomes_{year}_{sym}.parquet')
        for side in (1,-1):
            x=side_feature_frame(states,side);u=m.predict(x);q=empirical_cdf(cdf,u)
            if prev is not None and year in (2025,2026):
                mask=states.decision_ms.to_numpy(np.int64)<lag_end
                if mask.any():
                    ou=prev.predict(x.loc[mask]);u[mask]=ou;q[mask]=empirical_cdf(prevcdf,ou)
            s=pd.DataFrame({'candidate_id':[f'{sym}:{int(t)}:{side}' for t in states.decision_ms],'decision_ms':states.decision_ms.astype('int64'),'symbol':sym,'side':side,'u':u.astype('float32'),'q':q.astype('float32'),'model_year':year,'duration_alpha':alpha})
            rows.append(s.merge(out,on=['candidate_id','decision_ms','symbol','side'],how='inner'))
            del x,s
        del states,out;gc.collect()
    r=pd.concat(rows,ignore_index=True).sort_values(['decision_ms','symbol','side']).reset_index(drop=True);r.to_parquet(p,index=False,compression='zstd');return r

def main(alpha,years,force=False):
    samples=training(max(years));models={};cdfs={};stats=[]
    for y in years:
        m,c,st=fit(alpha,y,samples,force);models[y]=m;cdfs[y]=c;stats.append(st)
        r=score(alpha,y,m,c,models.get(y-1),cdfs.get(y-1),force)
        print('SCORED',alpha,y,len(r),flush=True)
    pd.DataFrame(stats).to_csv(OUT/f'models_duration_a{tag(alpha)}'/ 'model_stats.csv',index=False)

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('alpha',type=float);ap.add_argument('years',nargs='+',type=int);ap.add_argument('--force',action='store_true');a=ap.parse_args();main(a.alpha,a.years,a.force)
