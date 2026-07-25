from pathlib import Path
import sys
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from donchian_dependence_screen import Event,events_for_mode,exit_path,prior_extreme,simulate
from payoff_concentration_screen import make_payoff


def event(symbol="BTCUSDT",score=1.0,prev=None,kind="base",entry_time=60_000):
    return Event(symbol,1,entry_time,100.0,1,95.0,2,120_000,105.0,"channel_exit",0.05,score,prev,kind,0,1)


def market():
    return {
        "open_time_ms":np.array([0,60_000,120_000,180_000],dtype=np.int64),
        "open":np.array([100.0,100.0,105.0,105.0]),
        "high":np.array([101.0,106.0,106.0,106.0]),
        "low":np.array([99.0,94.0,104.0,104.0]),
        "close":np.array([100.0,105.0,105.0,105.0]),
    }


def test_channel_extreme_is_strictly_prior_only():
    out=prior_extreme(np.array([1.0,2.0,100.0]),2,"max")
    assert np.isnan(out[1]) and out[2]==2.0


def test_channel_exit_waits_for_completed_close_then_next_open():
    d=market();d["close"][1]=90.0
    idx,time_ms,price,reason=exit_path(d,1,100.0,1,80.0,np.array([np.nan,95.0,95.0,95.0]),np.full(4,np.nan))
    assert idx==2 and time_ms==120_000 and price==d["open"][2] and reason=="channel_exit"


def test_theoretical_state_filter_uses_skipped_sequence_and_failsafe():
    initial=event(prev=None);winner=event(prev=1,entry_time=180_000);loser=event(prev=-1,entry_time=240_000);failsafe=event(prev=1,kind="failsafe",entry_time=300_000)
    source=[initial,winner,loser,failsafe]
    assert events_for_mode(source,"after_loser")==[initial,loser]
    assert events_for_mode(source,"after_winner")==[winner]
    assert events_for_mode(source,"turtle_failsafe")==[initial,loser,failsafe]


def test_one_global_slot_selects_highest_normalized_breakout_score():
    data={"BTCUSDT":market(),"ETHUSDT":market()}
    result=simulate(data,[event("BTCUSDT",1.0),event("ETHUSDT",2.0)],0,240_000,1,12.0)
    assert result["trade_count"]==1
    assert result["symbol_counts"]["ETHUSDT"]==1


def test_payoff_same_bar_stop_is_adverse_before_target():
    d=market();e=event();e.stop_price=95.0;e.exit_idx=3;e.exit_time_ms=180_000;e.exit_price=105.0
    payoff=make_payoff(d,e,"full_1R")
    assert payoff.legs[0].reason=="stop" and payoff.legs[0].price==95.0
