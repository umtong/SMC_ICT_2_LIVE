from datetime import date, datetime, timedelta, timezone
from pathlib import Path
import numpy as np
from research.ml_macro_oco_20260727.run import DayData,Geometry,MemoryArchive,TEMPLATES,compute_features_and_geometry,event_to_utc,load_events,simulate_oco

UTC=timezone.utc

def day(event_ts,shift=0.0):
    ts=np.arange(event_ts-3600,event_ts+600,.25); rel=ts-event_ts
    price=100+.02*np.sin(rel/30)+np.where(rel>=0,shift,0); size=np.ones_like(price)
    signed=np.where(np.diff(np.r_[price[0],price])>=0,1.,-1.)*price
    return DayData("BTCUSDT",date(2024,1,11),ts,price,size,signed)

def geom():
    return Geometry("fixture",99.,101.,100.,2.,101.2,98.8,100.4,99.6,.8,.8,2.5)

def test_dst_and_snapshot():
    assert event_to_utc("2024-01-11","08:30:00","America/New_York")==datetime(2024,1,11,13,30,tzinfo=UTC)
    assert event_to_utc("2024-05-15","08:30:00","America/New_York")==datetime(2024,5,15,12,30,tzinfo=UTC)
    assert event_to_utc("2024-05-01","14:00:00","America/New_York")==datetime(2024,5,1,18,0,tzinfo=UTC)
    e=load_events(Path("research/ml_macro_oco_20260727/events.csv"))
    assert len(e)==80 and e.groupby("stage").size().to_dict()=={"calibration":16,"confirmation":16,"official_2024h1":16,"train":32}

def test_post_release_path_cannot_change_features():
    t=datetime(2024,1,11,13,30,tzinfo=UTC).timestamp()
    a=compute_features_and_geometry(day(t),t,"CPI","BTCUSDT",TEMPLATES[1])
    b=compute_features_and_geometry(day(t,50),t,"CPI","BTCUSDT",TEMPLATES[1])
    assert a==b

def test_activation_latency_blocks_pre_event_fill():
    event=datetime(2024,1,11,13,30,tzinfo=UTC); t=event.timestamp()
    ts=np.array([t-2,t-1,t+.1,t+.6,t+1,t+2]); price=np.array([102,100,100,101.3,103.6,103.6],float)
    d=DayData("BTCUSDT",event.date(),ts,price,np.ones_like(price),price.copy())
    s=simulate_oco(MemoryArchive({("BTCUSDT",event.date()):d}),"BTCUSDT",event,geom(),event+timedelta(hours=1))
    assert s.trade and s.entry_ts==t+.6 and s.exit_reason=="expansion_target"

def test_pending_order_needs_completed_central_reversion_to_cancel():
    event=datetime(2024,1,11,13,30,tzinfo=UTC); t=event.timestamp(); ts=np.arange(t,t+600)
    price=100+.05*np.sin(np.arange(len(ts))/20); size=np.ones_like(price)
    signed=np.where(np.diff(np.r_[price[0],price])>=0,1.,-1.)*price
    d=DayData("BTCUSDT",event.date(),ts,price,size,signed)
    s=simulate_oco(MemoryArchive({("BTCUSDT",event.date()):d}),"BTCUSDT",event,geom(),event+timedelta(hours=1))
    assert not s.trade and s.exit_reason=="pending_state_invalidated" and s.pending_end_ts==t+300
