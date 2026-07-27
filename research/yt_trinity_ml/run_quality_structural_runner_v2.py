#!/usr/bin/env python3
"""Exact-account wrapper for the quality-gated structural runner.

This module reuses the causal entry/exit simulator and candidate reconstruction from
v1, but owns the account ledger.  Quantity is computed from the *planned* candidate
entry/stop and the same fee/slippage/liquidation budget as the shared engine.  The
2024H1 full-target baseline must reproduce the frozen official account before any
runner result is considered valid.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict, replace
import hashlib
import json
from math import floor
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

import run_quality_structural_runner_v1 as base

MAINTENANCE_MARGIN = 0.005
LIQUIDATION_BUFFER = 0.0025


def key_candidate(candidate: base.Candidate) -> tuple[Any,...]:
    return (candidate.timestamp,candidate.symbol,candidate.family,candidate.side,candidate.action)


def key_outcome(outcome: base.Outcome) -> tuple[Any,...]:
    return (outcome.decision_time,outcome.symbol,outcome.family,outcome.side,outcome.action)


def frozen_candidates(path: Path) -> list[base.Candidate]:
    payload=json.loads(path.read_text(encoding="utf-8")); result=[]
    for row in payload.get("result",{}).get("candidate_scores",[]):
        if not row.get("passes_threshold"): continue
        action=str(row.get("preferred_action") or "PASSIVE_RETEST")
        score=float(row.get("predicted_passive_budget_r") if action=="PASSIVE_RETEST" else row.get("predicted_market_budget_r"))
        entry=float(row["entry_reference"]); stop=float(row["stop_reference"]); target=float(row["target_reference"])
        stop_distance=abs(entry-stop); stop_atr=float(row.get("stop_distance_atr") or 4.0)
        result.append(base.Candidate(pd.Timestamp(row["timestamp"]),str(row["symbol"]),str(row["family"]),int(row["side"]),entry,stop,target,max(stop_distance/max(stop_atr,1e-9),1e-12),action,score))
    return sorted(result,key=lambda c:(c.timestamp,-c.priority_score,c.symbol))


def account_replay(
    outcomes: Sequence[base.Outcome],
    candidates: Sequence[base.Candidate],
    start: pd.Timestamp,
    end: pd.Timestamp,
    risk_fraction: float,
    maximum_leverage: float,
    initial_nav: float=10000.0,
) -> base.AccountResult:
    candidate_map={key_candidate(c):c for c in candidates}; grouped:dict[pd.Timestamp,list[base.Outcome]]={}
    for outcome in outcomes:
        if start<=outcome.decision_time<end: grouped.setdefault(outcome.decision_time,[]).append(outcome)
    nav=float(initial_nav); peak=nav; mdd=0.0; release=start; pnl_values=[]; budget_rs=[]; holds=[]; trades=[]; filled=0
    for decision_time in sorted(grouped):
        if decision_time<release: continue
        outcome=sorted(grouped[decision_time],key=lambda row:(-row.priority_score,row.symbol,row.family))[0]
        release=min(max(outcome.exit_time,decision_time),end)
        candidate=candidate_map[key_outcome(outcome)]
        if outcome.entry_time is None or outcome.entry_price is None:
            trades.append({**asdict(outcome),"quantity":0.0,"net_pnl":0.0,"budget_r":0.0,"nav_after":nav}); continue
        filled+=1
        planned_stop_distance=abs(candidate.entry-candidate.stop)
        entry_fee=base.MAKER_FEE if candidate.action=="PASSIVE_RETEST" else base.TAKER_FEE
        entry_slippage=0.0 if candidate.action=="PASSIVE_RETEST" else base.ENTRY_SLIPPAGE
        planned_per_unit=(planned_stop_distance+candidate.entry*(entry_fee+entry_slippage)+candidate.stop*(base.TAKER_FEE+base.STOP_SLIPPAGE))
        risk_quantity=nav*risk_fraction/max(planned_per_unit,1e-12)
        leverage_quantity=nav*maximum_leverage/candidate.entry
        safe_leverage=1.0/max(planned_stop_distance/candidate.entry+MAINTENANCE_MARGIN+LIQUIDATION_BUFFER,1e-12)
        liquidation_quantity=nav*min(maximum_leverage,safe_leverage)/candidate.entry
        raw=max(0.0,min(risk_quantity,leverage_quantity,liquidation_quantity)); step=0.001 if candidate.symbol=="BTCUSDT" else 0.01; minimum=step
        quantity=floor(raw/step)*step
        if quantity<minimum: quantity=0.0
        pnl=quantity*outcome.per_unit_pnl; entry_nav=nav; nav+=pnl; peak=max(peak,nav); mdd=max(mdd,1-nav/max(peak,1e-12))
        budget_r=outcome.per_unit_pnl/max(planned_per_unit,1e-12); pnl_values.append(pnl); budget_rs.append(budget_r); holds.append(outcome.hold_hours)
        trades.append({**asdict(outcome),"candidate":asdict(candidate),"quantity":quantity,"net_pnl":pnl,"budget_r":budget_r,"entry_nav":entry_nav,"nav_after":nav})
        if nav<=0: nav=0.0; break
    days=max(1,int((end-start).total_seconds()//86400)); multiple=nav/initial_nav; values=np.asarray(pnl_values,float); positives=values[values>0]; negatives=values[values<0]
    top_share=float(np.sort(positives)[-5:].sum()/positives.sum()) if positives.size and positives.sum()>0 else None; winner_removed=nav-float(positives.max()) if positives.size else nav
    return base.AccountResult(initial_nav,nav,multiple,multiple**(1/days)-1 if multiple>0 else -1.0,mdd,len(trades),filled,float((values>0).mean()) if values.size else None,float(np.mean(budget_rs)) if budget_rs else None,float(np.median(budget_rs)) if budget_rs else None,float(positives.sum()/abs(negatives.sum())) if positives.size and negatives.size and negatives.sum()!=0 else None,top_share,winner_removed/initial_nav-1.0,float(np.mean(holds)) if holds else None,tuple(trades))


def simulate(candidates:Sequence[base.Candidate],bars:Mapping[str,pd.DataFrame],marks:Mapping[str,pd.Series],funding:Mapping[str,Sequence[tuple[pd.Timestamp,float]]],variant:base.Variant,end:pd.Timestamp)->list[base.Outcome]:
    return [base.simulate_one(c,bars[c.symbol],marks[c.symbol],funding[c.symbol],variant,end) for c in candidates]


def run(args:argparse.Namespace)->dict[str,Any]:
    args.output.mkdir(parents=True,exist_ok=True)
    candidates23=base.candidates_from_labels(args.labels); bars23,marks23,funding23=base.load_symbol_inputs(args,"2023")
    h1s=pd.Timestamp("2023-01-01T00:00:00Z");h1e=pd.Timestamp("2023-07-01T00:00:00Z");h2s=h1e;h2e=pd.Timestamp("2024-01-01T00:00:00Z")
    h1=[c for c in candidates23 if h1s<=c.timestamp<h1e]; h2=[c for c in candidates23 if h2s<=c.timestamp<h2e]
    discovery=[]
    for variant in base.variants():
        outcomes=simulate(h1,bars23,marks23,funding23,variant,h1e); basic=account_replay(outcomes,h1,h1s,h1e,0.01,5.0); growth=account_replay(outcomes,h1,h1s,h1e,0.17,20.0)
        discovery.append({"variant":asdict(variant),"basic_h1":asdict(basic),"growth_h1":asdict(growth)})
    eligible=[row for row in discovery if row["basic_h1"]["filled_trades"]>=8]
    if not eligible: raise RuntimeError("no H1 exit survivor")
    selected_row=max(eligible,key=lambda row:(row["basic_h1"]["geometric_daily_growth"],-row["basic_h1"]["maximum_drawdown"],row["basic_h1"]["filled_trades"],row["variant"]["name"])); selected=base.Variant(**selected_row["variant"])
    outcomes_h2=simulate(h2,bars23,marks23,funding23,selected,h2e); basic_h2=account_replay(outcomes_h2,h2,h2s,h2e,0.01,5.0); growth_h2=account_replay(outcomes_h2,h2,h2s,h2e,0.17,20.0); passed=basic_h2.geometric_daily_growth>0 and basic_h2.filled_trades>=8
    official=json.loads(args.official_result.read_text(encoding="utf-8")); candidates24=frozen_candidates(args.frozen_pointer); bars24,marks24,funding24=base.load_symbol_inputs(args,"2024h1");s24=pd.Timestamp("2024-01-01T00:00:00Z");e24=pd.Timestamp("2024-07-01T00:00:00Z")
    baseline_outcomes=simulate(candidates24,bars24,marks24,funding24,base.Variant("BASELINE_FULL_TARGET"),e24); baseline=account_replay(baseline_outcomes,candidates24,s24,e24,0.17,20.0); expected=float(official["metrics"]["account_multiple"]); baseline_error=abs(baseline.account_multiple-expected); accounting_valid=baseline_error<=1e-6
    frozen=None
    if passed and accounting_valid:
        runner_outcomes=simulate(candidates24,bars24,marks24,funding24,selected,e24); frozen={"basic":asdict(account_replay(runner_outcomes,candidates24,s24,e24,0.01,5.0)),"growth":asdict(account_replay(runner_outcomes,candidates24,s24,e24,0.17,20.0))}
    result={"schema_version":2,"stage":"EXACT_ACCOUNT_QUALITY_STRUCTURAL_RUNNER","candidate_count_2023":len(candidates23),"selected_variant":asdict(selected),"discovery":discovery,"validation_2023H2":{"basic":asdict(basic_h2),"growth":asdict(growth_h2),"passed":passed},"baseline_crosscheck":{"expected_official_multiple":expected,"custom":asdict(baseline),"absolute_error":baseline_error,"valid":accounting_valid},"frozen_2024H1":frozen,"ranking_effect":"NONE_PROVISIONAL_1M_NOT_EVENT_TAPE_VALIDATED"}
    path=args.output/"QUALITY_STRUCTURAL_RUNNER_V2_RESULT.json";path.write_text(json.dumps(result,ensure_ascii=False,indent=2,sort_keys=True,default=str)+'\n');(args.output/"QUALITY_STRUCTURAL_RUNNER_V2_RESULT.sha256").write_text(f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}\n");return result


def main(argv:Sequence[str]|None=None)->int:
    p=argparse.ArgumentParser();p.add_argument("--labels",type=Path,required=True);p.add_argument("--frozen-pointer",type=Path,required=True);p.add_argument("--official-result",type=Path,required=True);p.add_argument("--output",type=Path,required=True)
    for symbol in ("btc","eth"):
        for period in ("2023","2024h1"):
            p.add_argument(f"--{symbol}-{period}-bars",dest=f"{symbol}_{period}_bars",type=Path,required=True);p.add_argument(f"--{symbol}-{period}-marks",dest=f"{symbol}_{period}_marks",type=Path,required=True);p.add_argument(f"--{symbol}-{period}-funding",dest=f"{symbol}_{period}_funding",type=Path,required=True)
    result=run(p.parse_args(argv));print(json.dumps({"selected_variant":result["selected_variant"],"validation":result["validation_2023H2"],"crosscheck":result["baseline_crosscheck"],"frozen":result["frozen_2024H1"]},indent=2,default=str));return 0 if result["baseline_crosscheck"]["valid"] else 3
if __name__=="__main__":raise SystemExit(main())
