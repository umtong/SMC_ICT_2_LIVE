from __future__ import annotations

import argparse
import hashlib
import io
import json
import math
import shutil
import time
import urllib.request
import zipfile
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
import pandas as pd
from huggingface_hub import hf_hub_download
from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression, Ridge
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

STUDY_ID = "L2_MAKER_TOXICITY_V1_20260725"
HF_REPO = "predict-quant/binance-future-orderbook"
HF_REVISION = "b8590b83452d7a32fbb274ff7741b6db000b3984"
SYMBOLS = ("BTCUSDT", "ETHUSDT")
FIT_DATES = ("2026-03-05", "2026-03-09", "2026-03-13", "2026-03-16")
CALIB_DATES = ("2026-03-19", "2026-03-23")
VALID_DATES = ("2026-03-27", "2026-03-31")
SEALED_DATES = ("2026-04-03", "2026-04-04", "2026-04-05", "2026-04-06", "2026-04-07")
QUEUE_MULTIPLIERS = (1.0, 2.0, 3.0)
TTLS = (1, 3, 10)
HORIZONS = (3, 10, 30)
SCORE_QUANTILES = (0.95, 0.975, 0.99, 0.995)
ROUTES = ("unrestricted", "aligned_continuation", "absorption_reversal")
COST_BPS = (9.0, 13.0, 17.0)
DECISION_STEP_SECONDS = 5
ACK_LATENCY_MS = 100
EXIT_LATENCY_MS = 100
MAX_BBO_GAP_MS = 60_000
FEATURE_COLUMNS = [
    "side", "spread_bp", "microprice_skew_bp", "imbalance_1", "imbalance_5", "imbalance_10", "imbalance_20",
    "inner_bid_share", "inner_ask_share", "bid_slope_bp", "ask_slope_bp", "bid_q1_change_1s", "ask_q1_change_1s",
    "bid_refill_1s", "ask_refill_1s", "mid_ret_1s_bp", "mid_ret_3s_bp", "signed_quote_1s_norm",
    "signed_quote_3s_norm", "total_quote_1s_log", "total_quote_3s_log", "trade_count_1s_log", "trade_count_3s_log",
    "flow_response_efficiency_1s", "flow_response_efficiency_3s", "update_intensity_1s_log", "hour_sin", "hour_cos",
]

@dataclass(frozen=True)
class SourceFile:
    symbol: str
    date: str
    kind: str
    url: str
    sha256: str
    size_bytes: int

def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()

def atomic_download(url: str, path: Path, retries: int = 5) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.stat().st_size > 0:
        return
    tmp = path.with_suffix(path.suffix + ".part")
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "SMC-ICT-2-LIVE-research/1.0"})
            with urllib.request.urlopen(req, timeout=300) as r, tmp.open("wb") as f:
                shutil.copyfileobj(r, f, length=1 << 20)
            tmp.replace(path)
            return
        except Exception:
            tmp.unlink(missing_ok=True)
            if attempt == retries - 1:
                raise
            time.sleep(2 ** attempt)

def download_binance_verified(symbol: str, date: str, kind: str, raw_dir: Path) -> SourceFile:
    stem = f"{symbol}-{kind}-{date}.zip"
    base = f"https://data.binance.vision/data/futures/um/daily/{kind}/{symbol}"
    zip_url = f"{base}/{stem}"
    checksum_url = f"{zip_url}.CHECKSUM"
    zip_path = raw_dir / kind / symbol / stem
    checksum_path = raw_dir / kind / symbol / f"{stem}.CHECKSUM"
    atomic_download(checksum_url, checksum_path)
    atomic_download(zip_url, zip_path)
    expected = checksum_path.read_text(encoding="utf-8").strip().split()[0]
    actual = sha256_file(zip_path)
    if actual != expected:
        raise ValueError(f"checksum mismatch {zip_path}: {actual} != {expected}")
    return SourceFile(symbol, date, kind, zip_url, actual, zip_path.stat().st_size)

def read_zip_csv(path: Path) -> pd.DataFrame:
    with zipfile.ZipFile(path) as zf:
        names = [n for n in zf.namelist() if not n.endswith("/")]
        if len(names) != 1:
            raise ValueError(f"expected one file in {path}, got {names}")
        with zf.open(names[0]) as f:
            data = f.read()
    frame = pd.read_csv(io.BytesIO(data), header=None, low_memory=False)
    first = str(frame.iloc[0, 0]).lower()
    if any(token in first for token in ("agg_trade", "update_id", "transaction_time", "best_bid")):
        frame = frame.iloc[1:].reset_index(drop=True)
    return frame

def read_aggtrades(path: Path) -> pd.DataFrame:
    f = read_zip_csv(path)
    if f.shape[1] != 7:
        raise ValueError(f"unexpected aggTrades columns {f.shape[1]} in {path}")
    f.columns = ["agg_id", "price", "qty", "first_id", "last_id", "time", "buyer_maker"]
    for col in ("price", "qty", "time"):
        f[col] = pd.to_numeric(f[col], errors="coerce")
    f["buyer_maker"] = f["buyer_maker"].astype(str).str.lower().map({"true": True, "false": False})
    f = f.dropna(subset=["price", "qty", "time", "buyer_maker"]).copy()
    f["time"] = f["time"].astype(np.int64)
    f["quote"] = f["price"] * f["qty"]
    f["signed_quote"] = np.where(f["buyer_maker"], -f["quote"], f["quote"])
    return f.sort_values("time").reset_index(drop=True)

def read_bookticker(path: Path) -> pd.DataFrame:
    f = read_zip_csv(path)
    n = f.shape[1]
    if n == 7:
        f.columns = ["update_id", "bid", "bid_qty", "ask", "ask_qty", "transaction_time", "event_time"]
    elif n == 6:
        f.columns = ["update_id", "bid", "bid_qty", "ask", "ask_qty", "transaction_time"]
        f["event_time"] = f["transaction_time"]
    elif n == 8:
        f.columns = ["update_id", "symbol", "bid", "bid_qty", "ask", "ask_qty", "transaction_time", "event_time"]
    else:
        raise ValueError(f"unexpected bookTicker columns {n} in {path}")
    for col in ("bid", "bid_qty", "ask", "ask_qty", "transaction_time", "event_time"):
        f[col] = pd.to_numeric(f[col], errors="coerce")
    f = f.dropna(subset=["bid", "bid_qty", "ask", "ask_qty", "transaction_time"]).copy()
    f["transaction_time"] = f["transaction_time"].astype(np.int64)
    f["event_time"] = f["event_time"].fillna(f["transaction_time"]).astype(np.int64)
    f = f[(f["bid"] > 0) & (f["ask"] > f["bid"]) & (f["bid_qty"] >= 0) & (f["ask_qty"] >= 0)]
    return f.sort_values("transaction_time").drop_duplicates("transaction_time", keep="last").reset_index(drop=True)

def parse_levels(text: str) -> tuple[np.ndarray, np.ndarray]:
    value = json.loads(text)
    return np.array([float(x[0]) for x in value]), np.array([float(x[1]) for x in value])

def continuity_audit(depth: pd.DataFrame) -> dict[str, float | int]:
    d = depth[depth["e"].astype(str).eq("depthUpdate")].copy()
    u = pd.to_numeric(d["u"], errors="coerce").to_numpy()
    pu = pd.to_numeric(d["pu"], errors="coerce").to_numpy()
    valid = np.isfinite(u) & np.isfinite(pu)
    u, pu = u[valid], pu[valid]
    if len(u) < 2:
        return {"updates": int(len(u)), "pu_match_rate": 0.0, "backward_time_count": 0}
    match = pu[1:] == u[:-1]
    t = pd.to_numeric(d.loc[valid, "T"], errors="coerce").to_numpy(dtype=np.int64)
    return {"updates": int(len(u)), "pu_match_rate": float(match.mean()), "discontinuities": int((~match).sum()), "backward_time_count": int((np.diff(t) < 0).sum())}

def build_second_states(depth_path: Path, trades: pd.DataFrame, book: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    depth = pd.read_parquet(depth_path, columns=["e", "E", "T", "U", "u", "pu", "bids", "asks"])
    audit = continuity_audit(depth)
    depth["T"] = pd.to_numeric(depth["T"], errors="coerce")
    depth = depth.dropna(subset=["T", "bids", "asks"]).sort_values("T")
    depth["T"] = depth["T"].astype(np.int64)
    depth["second"] = (depth["T"] // 1000).astype(np.int64)
    counts = depth.groupby("second", sort=False).size().rename("update_count")
    one = depth.groupby("second", sort=False).tail(1).copy().merge(counts, left_on="second", right_index=True, how="left")
    rows = []
    for row in one.itertuples(index=False):
        bp, bq = parse_levels(row.bids); ap, aq = parse_levels(row.asks)
        if len(bp) < 20 or len(ap) < 20: continue
        bid, ask = bp[0], ap[0]
        if not np.isfinite(bid + ask) or ask <= bid: continue
        mid = 0.5 * (bid + ask)
        micro = (ask * bq[0] + bid * aq[0]) / max(bq[0] + aq[0], 1e-12)
        out = {"second": int(row.second), "state_time": int(row.T), "bid": bid, "ask": ask, "bid_qty": bq[0], "ask_qty": aq[0], "mid": mid,
               "spread_bp": (ask-bid)/mid*1e4, "microprice_skew_bp": (micro-mid)/mid*1e4, "update_intensity_1s_log": math.log1p(int(row.update_count)),
               "inner_bid_share": bq[:5].sum()/max(bq[:20].sum(),1e-12), "inner_ask_share": aq[:5].sum()/max(aq[:20].sum(),1e-12),
               "bid_slope_bp": (bp[0]-bp[19])/mid*1e4, "ask_slope_bp": (ap[19]-ap[0])/mid*1e4}
        for k in (1,5,10,20):
            bd, ad = bq[:k].sum(), aq[:k].sum(); out[f"imbalance_{k}"]=(bd-ad)/max(bd+ad,1e-12)
        rows.append(out)
    s = pd.DataFrame(rows).sort_values("second").reset_index(drop=True)
    b = book[["transaction_time","bid","bid_qty","ask","ask_qty"]].rename(columns={"bid":"off_bid","bid_qty":"off_bid_qty","ask":"off_ask","ask_qty":"off_ask_qty"})
    check = pd.merge_asof(s[["state_time","bid","ask"]].sort_values("state_time"), b.sort_values("transaction_time"), left_on="state_time", right_on="transaction_time", direction="backward")
    comparable = check["off_bid"].notna()
    audit["official_bbo_comparable"] = int(comparable.sum())
    audit["official_bbo_price_match_rate"] = float((np.isclose(check.loc[comparable,"bid"],check.loc[comparable,"off_bid"],rtol=0,atol=1e-12)&np.isclose(check.loc[comparable,"ask"],check.loc[comparable,"off_ask"],rtol=0,atol=1e-12)).mean()) if comparable.any() else 0.0
    for lag in (1,3):
        for col in ("mid","bid_qty","ask_qty"): s[f"{col}_lag{lag}"]=s[col].shift(lag)
    s["bid_q1_change_1s"]=(s["bid_qty"]-s["bid_qty_lag1"])/(s["bid_qty_lag1"].abs()+1e-9)
    s["ask_q1_change_1s"]=(s["ask_qty"]-s["ask_qty_lag1"])/(s["ask_qty_lag1"].abs()+1e-9)
    s["bid_refill_1s"]=s["bid_q1_change_1s"].clip(lower=0); s["ask_refill_1s"]=s["ask_q1_change_1s"].clip(lower=0)
    s["mid_ret_1s_bp"]=(s["mid"]/s["mid_lag1"]-1)*1e4; s["mid_ret_3s_bp"]=(s["mid"]/s["mid_lag3"]-1)*1e4
    tr=trades.copy(); tr["second"]=(tr["time"]//1000).astype(np.int64)
    agg=tr.groupby("second").agg(signed_quote=("signed_quote","sum"),total_quote=("quote","sum"),trade_count=("agg_id","size"))
    s=s.merge(agg,left_on="second",right_index=True,how="left"); s[["signed_quote","total_quote","trade_count"]]=s[["signed_quote","total_quote","trade_count"]].fillna(0.0)
    for win in (1,3):
        signed=s["signed_quote"].rolling(win,min_periods=win).sum(); total=s["total_quote"].rolling(win,min_periods=win).sum(); count=s["trade_count"].rolling(win,min_periods=win).sum()
        s[f"signed_quote_{win}s_norm"]=signed/(total+1e-9); s[f"total_quote_{win}s_log"]=np.log1p(total); s[f"trade_count_{win}s_log"]=np.log1p(count)
        s[f"flow_response_efficiency_{win}s"]=s[f"mid_ret_{win}s_bp"]/(signed.abs()/(total+1e-9)+1e-3)
    ts=pd.to_datetime(s["second"],unit="s",utc=True); angle=2*np.pi*(ts.dt.hour*3600+ts.dt.minute*60+ts.dt.second)/86400
    s["hour_sin"]=np.sin(angle); s["hour_cos"]=np.cos(angle)
    return s,audit

def lookup_last_bbo(book: pd.DataFrame, ts_ms: int):
    arr=book["transaction_time"].to_numpy(dtype=np.int64); idx=int(np.searchsorted(arr,ts_ms,side="right")-1); return idx if idx>=0 else None

def lookup_first_bbo(book: pd.DataFrame, ts_ms: int):
    arr=book["transaction_time"].to_numpy(dtype=np.int64); idx=int(np.searchsorted(arr,ts_ms,side="left")); return idx if idx<len(arr) else None

def order_outcome(book, trades, decision_ms, side, queue_mult, ttl_s, horizon_s):
    ack_ms=decision_ms+ACK_LATENCY_MS; bi=lookup_last_bbo(book,ack_ms)
    if bi is None: return {"filled":False,"reason":"no_ack_bbo"}
    br=book.iloc[bi]
    if ack_ms-int(br.transaction_time)>MAX_BBO_GAP_MS: return {"filled":False,"reason":"stale_ack_bbo"}
    price=float(br.bid if side>0 else br.ask); displayed=float(br.bid_qty if side>0 else br.ask_qty)
    if price<=0 or displayed<=0: return {"filled":False,"reason":"invalid_quote"}
    order_qty=min(displayed*0.01,1000.0/price)
    times=trades["time"].to_numpy(dtype=np.int64); start=int(np.searchsorted(times,ack_ms,side="right")); stop_ms=ack_ms+ttl_s*1000; end=int(np.searchsorted(times,stop_ms,side="right"))
    if end<=start: return {"filled":False,"reason":"no_trades"}
    sub=trades.iloc[start:end]
    eligible=sub[sub["buyer_maker"]&(sub["price"]<=price)] if side>0 else sub[(~sub["buyer_maker"])&(sub["price"]>=price)]
    if eligible.empty: return {"filled":False,"reason":"no_opposing_trade"}
    hit=np.flatnonzero(eligible["qty"].cumsum().to_numpy()>=displayed*queue_mult+order_qty)
    if len(hit)==0: return {"filled":False,"reason":"queue_not_consumed"}
    fill_row=eligible.iloc[int(hit[0])]; fill_ms=int(fill_row.time); exit_target=fill_ms+horizon_s*1000+EXIT_LATENCY_MS; ei=lookup_first_bbo(book,exit_target)
    if ei is None: return {"filled":False,"reason":"no_exit_bbo"}
    er=book.iloc[ei]
    if int(er.transaction_time)-exit_target>MAX_BBO_GAP_MS: return {"filled":False,"reason":"stale_exit_bbo"}
    exit_price=float(er.bid if side>0 else er.ask); gross=side*(exit_price-price)/price
    return {"filled":True,"reason":"filled","ack_ms":ack_ms,"fill_ms":fill_ms,"exit_ms":int(er.transaction_time),"entry_price":price,"exit_price":exit_price,"gross_return":gross,"order_qty":order_qty,"displayed_queue":displayed}

def make_orders(symbol,date,states,book,trades):
    states=states[states["second"]%DECISION_STEP_SECONDS==0].copy().dropna(subset=[c for c in FEATURE_COLUMNS if c!="side"])
    rows=[]
    directional={"microprice_skew_bp","imbalance_1","imbalance_5","imbalance_10","imbalance_20","bid_q1_change_1s","ask_q1_change_1s","bid_refill_1s","ask_refill_1s","mid_ret_1s_bp","mid_ret_3s_bp","signed_quote_1s_norm","signed_quote_3s_norm","flow_response_efficiency_1s","flow_response_efficiency_3s"}
    for state in states.itertuples(index=False):
        decision_ms=int(state.second*1000)
        for side in (1,-1):
            base={"symbol":symbol,"date":date,"decision_ms":decision_ms,"side":side}
            for col in FEATURE_COLUMNS:
                if col=="side": base[col]=side; continue
                value=float(getattr(state,col))
                if col in directional:
                    if col=="bid_q1_change_1s": value=side*(float(state.bid_q1_change_1s)-float(state.ask_q1_change_1s))
                    elif col=="ask_q1_change_1s": value=side*(float(state.ask_q1_change_1s)-float(state.bid_q1_change_1s))
                    elif col=="bid_refill_1s": value=float(state.bid_refill_1s if side>0 else state.ask_refill_1s)
                    elif col=="ask_refill_1s": value=float(state.ask_refill_1s if side>0 else state.bid_refill_1s)
                    else: value*=side
                base[col]=value
            for qm in QUEUE_MULTIPLIERS:
                for ttl in TTLS:
                    for h in HORIZONS:
                        out=order_outcome(book,trades,decision_ms,side,qm,ttl,h); tag=f"q{int(qm)}_ttl{ttl}_h{h}"
                        base[f"filled_{tag}"]=int(out.get("filled",False)); base[f"gross_{tag}"]=float(out.get("gross_return",np.nan)) if out.get("filled") else np.nan
                        base[f"fill_ms_{tag}"]=int(out.get("fill_ms",-1)) if out.get("filled") else -1; base[f"exit_ms_{tag}"]=int(out.get("exit_ms",-1)) if out.get("filled") else -1
            rows.append(base)
    return pd.DataFrame(rows)

def candidate_route_mask(frame,route):
    if route=="unrestricted": return np.ones(len(frame),dtype=bool)
    if route=="aligned_continuation": return ((frame["microprice_skew_bp"]>0)&(frame["signed_quote_3s_norm"]>0)&(frame["imbalance_5"]>0)).to_numpy()
    if route=="absorption_reversal": return ((frame["signed_quote_3s_norm"]<0)&(frame["mid_ret_3s_bp"]>-0.5)&(frame["bid_refill_1s"]>0)&(frame["flow_response_efficiency_3s"]>-10)).to_numpy()
    raise ValueError(route)

def fit_models(train,tag,model_family):
    X=train[FEATURE_COLUMNS]; yfill=train[f"filled_{tag}"].astype(int)
    if yfill.nunique()<2: return None,None
    if model_family=="linear":
        fill=make_pipeline(SimpleImputer(strategy="median"),StandardScaler(),LogisticRegression(C=.25,max_iter=500)); mark=make_pipeline(SimpleImputer(strategy="median"),StandardScaler(),Ridge(alpha=10))
    else:
        fill=make_pipeline(SimpleImputer(strategy="median"),HistGradientBoostingClassifier(max_depth=3,max_iter=80,learning_rate=.05,l2_regularization=5,random_state=20260725)); mark=make_pipeline(SimpleImputer(strategy="median"),HistGradientBoostingRegressor(max_depth=3,max_iter=80,learning_rate=.05,l2_regularization=5,random_state=20260725))
    fill.fit(X,yfill); filled=train[f"filled_{tag}"].eq(1)&train[f"gross_{tag}"].notna()
    if filled.sum()<100: return fill,None
    mark.fit(train.loc[filled,FEATURE_COLUMNS],train.loc[filled,f"gross_{tag}"]); return fill,mark

def score_frame(frame,fill,mark,cost_bps): return fill.predict_proba(frame[FEATURE_COLUMNS])[:,1]*(mark.predict(frame[FEATURE_COLUMNS])-cost_bps*1e-4)

def portfolio_metrics(ledger,cost_bps):
    if ledger.empty: return {"trades":0,"final_multiple":1.,"mean_bp":0.,"profit_factor":0.,"max_drawdown":0.,"top10_positive_share":1.,"after_top10_multiple":1.,"positive_dates":0,"date_returns":{}}
    r=ledger["gross_return"].to_numpy(float)-cost_bps*1e-4; valid=r>-.999; ledger=ledger.loc[valid].copy(); r=r[valid]; eq=np.cumprod(1+r); curve=np.r_[1.,eq]; peak=np.maximum.accumulate(curve); mdd=float(np.max(1-curve/peak)); pos=r[r>0]; neg=r[r<0]; pf=float(pos.sum()/max(-neg.sum(),1e-12)); topn=min(10,len(pos)); top=float(np.sort(pos)[-topn:].sum()/max(pos.sum(),1e-12)) if topn else 1.
    keep=np.ones(len(r),bool); keep[np.argsort(r)[-topn:]]=False if topn else True; after=float(np.prod(1+r[keep])) if len(r)>topn else 1.
    led=ledger.assign(net=r); led["date"]=pd.to_datetime(led["decision_ms"],unit="ms",utc=True).dt.strftime("%Y-%m-%d"); dr=led.groupby("date")["net"].apply(lambda x:float(np.prod(1+x.to_numpy())-1)).to_dict()
    return {"trades":int(len(r)),"final_multiple":float(eq[-1]),"mean_bp":float(r.mean()*1e4),"profit_factor":pf,"max_drawdown":mdd,"top10_positive_share":top,"after_top10_multiple":after,"positive_dates":int(sum(v>0 for v in dr.values())),"date_returns":dr}

def simulate(frame,tag,score,threshold,route):
    f=frame.copy(); f["score"]=score; mask=(score>=threshold)&candidate_route_mask(f,route)&f[f"filled_{tag}"].eq(1)&f[f"gross_{tag}"].notna(); f=f.loc[mask].sort_values(["decision_ms","score"],ascending=[True,False]); ledger=[]; busy=-1
    for decision_ms,group in f.groupby("decision_ms",sort=True):
        if int(decision_ms)<busy: continue
        row=group.iloc[0]; exit_ms=int(row[f"exit_ms_{tag}"])
        if exit_ms<=int(decision_ms): continue
        ledger.append({"decision_ms":int(decision_ms),"symbol":row["symbol"],"side":int(row["side"]),"score":float(row["score"]),"fill_ms":int(row[f"fill_ms_{tag}"]),"exit_ms":exit_ms,"gross_return":float(row[f"gross_{tag}"])}); busy=exit_ms
    return pd.DataFrame(ledger)

def run_screen(all_orders,out):
    train=all_orders[all_orders["date"].isin(FIT_DATES)].copy(); calib=all_orders[all_orders["date"].isin(CALIB_DATES)].copy(); valid=all_orders[all_orders["date"].isin(VALID_DATES)].copy(); screens=[]
    for mf in ("linear","hist"):
        for qm in QUEUE_MULTIPLIERS:
            for ttl in TTLS:
                for h in HORIZONS:
                    tag=f"q{int(qm)}_ttl{ttl}_h{h}"; fill,mark=fit_models(train,tag,mf)
                    if fill is None or mark is None: continue
                    cs=score_frame(calib,fill,mark,COST_BPS[0]); vs=score_frame(valid,fill,mark,COST_BPS[0]); finite=cs[np.isfinite(cs)]
                    if len(finite)<100: continue
                    for q in SCORE_QUANTILES:
                        threshold=float(np.quantile(finite,q))
                        for route in ROUTES:
                            cl=simulate(calib,tag,cs,threshold,route); vl=simulate(valid,tag,vs,threshold,route); row={"candidate_id":f"{mf}|{tag}|q{q}|{route}","model_family":mf,"queue_multiplier":qm,"ttl_s":ttl,"horizon_s":h,"score_quantile":q,"threshold":threshold,"route":route}
                            for cost in COST_BPS:
                                for name,led in (("calib",cl),("valid",vl)):
                                    m=portfolio_metrics(led,cost)
                                    for k,v in m.items():
                                        if k!="date_returns": row[f"{name}_{int(cost)}_{k}"]=v
                                    row[f"{name}_{int(cost)}_date_returns"]=json.dumps(m["date_returns"],sort_keys=True)
                            row["calib_gate"]=bool(row["calib_17_trades"]>=100 and row["calib_17_mean_bp"]>0 and row["calib_17_profit_factor"]>=1.05 and row["calib_17_top10_positive_share"]<=.25 and row["calib_17_after_top10_multiple"]>1 and row["calib_17_positive_dates"]>=2)
                            row["validation_gate"]=bool(row["calib_gate"] and row["valid_17_trades"]>=100 and row["valid_17_mean_bp"]>0 and row["valid_17_profit_factor"]>=1.05 and row["valid_17_top10_positive_share"]<=.25 and row["valid_17_after_top10_multiple"]>1 and row["valid_17_positive_dates"]>=2)
                            row["calib_robust_score"]=min(row["calib_9_mean_bp"],row["calib_13_mean_bp"],row["calib_17_mean_bp"])*math.log1p(row["calib_17_trades"])*max(0,1-row["calib_17_top10_positive_share"]); screens.append(row)
    screen=pd.DataFrame(screens)
    if screen.empty: raise RuntimeError("no candidates scored")
    screen=screen.sort_values(["calib_gate","calib_robust_score"],ascending=[False,False]).reset_index(drop=True); screen.to_csv(out/"candidate_screen.csv",index=False); eligible=screen[screen["calib_gate"]]; survivors=screen[screen["validation_gate"]]
    summary={"study_id":STUDY_ID,"status":"VALIDATED_COMPONENT_ONLY" if len(survivors) else "NO_VALIDATED_ALPHA","target_met":False,"candidate_count":int(len(screen)),"calibration_gate_count":int(screen["calib_gate"].sum()),"validation_gate_count":int(screen["validation_gate"].sum()),"primary_selected_before_validation":eligible.iloc[0].to_dict() if len(eligible) else None,"validation_survivors":survivors.head(20).to_dict(orient="records"),"terminal_dates_opened":False,"orders_submitted":False,"paper_live_enabled":False,"limitations":["Third-party depth20 reconstruction is discovery-only even after official BBO reconciliation.","Coverage is limited to March 2026 and cannot establish multi-regime durability.","No private queue position or actual account fill reports are available."]}
    (out/"summary.json").write_text(json.dumps(summary,indent=2,sort_keys=True),encoding="utf-8"); return summary

def process_day(symbol,date,cache,out):
    if date in SEALED_DATES: raise ValueError(f"sealed date prohibited: {date}")
    depth_path=Path(hf_hub_download(repo_id=HF_REPO,repo_type="dataset",revision=HF_REVISION,filename=f"{symbol}/{date}_{symbol}_depth20.parquet",cache_dir=str(cache/"hf"))); depth_sha=sha256_file(depth_path); sources=[SourceFile(symbol,date,"depth20_third_party",f"hf://{HF_REPO}@{HF_REVISION}/{symbol}/{date}_{symbol}_depth20.parquet",depth_sha,depth_path.stat().st_size)]; raw=cache/"binance"
    for kind in ("aggTrades","bookTicker"): sources.append(download_binance_verified(symbol,date,kind,raw))
    trades=read_aggtrades(raw/"aggTrades"/symbol/f"{symbol}-aggTrades-{date}.zip"); book=read_bookticker(raw/"bookTicker"/symbol/f"{symbol}-bookTicker-{date}.zip"); states,audit=build_second_states(depth_path,trades,book); audit.update({"symbol":symbol,"date":date,"depth_sha256":depth_sha,"states":int(len(states)),"trades":int(len(trades)),"book_updates":int(len(book))})
    if audit.get("pu_match_rate",0)<.995: raise RuntimeError(f"sequence continuity gate failed {symbol} {date}: {audit}")
    if audit.get("official_bbo_price_match_rate",0)<.995: raise RuntimeError(f"official BBO provenance gate failed {symbol} {date}: {audit}")
    orders=make_orders(symbol,date,states,book,trades); day=out/"days"; day.mkdir(parents=True,exist_ok=True); orders.to_parquet(day/f"{symbol}_{date}_orders.parquet",index=False); (day/f"{symbol}_{date}_audit.json").write_text(json.dumps(audit,indent=2,sort_keys=True),encoding="utf-8"); return orders,audit,sources

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--output",type=Path,required=True); ap.add_argument("--cache",type=Path,required=True); ap.add_argument("--dates",nargs="*",default=list(FIT_DATES+CALIB_DATES+VALID_DATES)); ap.add_argument("--symbols",nargs="*",default=list(SYMBOLS)); args=ap.parse_args(); args.output.mkdir(parents=True,exist_ok=True)
    prohibited=set(args.dates)&set(SEALED_DATES)
    if prohibited: raise SystemExit(f"sealed dates requested: {sorted(prohibited)}")
    if not set(args.symbols).issubset(SYMBOLS): raise SystemExit(f"symbols outside fixed scope: {args.symbols}")
    all_orders=[]; audits=[]; sources=[]
    for date in args.dates:
        for symbol in args.symbols:
            print(f"PROCESS {symbol} {date}",flush=True); orders,audit,src=process_day(symbol,date,args.cache,args.output); all_orders.append(orders); audits.append(audit); sources.extend(src)
    panel=pd.concat(all_orders,ignore_index=True); panel.to_parquet(args.output/"orders_panel.parquet",index=False); summary=run_screen(panel,args.output)
    manifest={"study_id":STUDY_ID,"hf_repo":HF_REPO,"hf_revision":HF_REVISION,"symbols":args.symbols,"fit_dates":FIT_DATES,"calibration_dates":CALIB_DATES,"validation_dates":VALID_DATES,"sealed_dates":SEALED_DATES,"decision_step_seconds":DECISION_STEP_SECONDS,"ack_latency_ms":ACK_LATENCY_MS,"exit_latency_ms":EXIT_LATENCY_MS,"queue_multipliers":QUEUE_MULTIPLIERS,"ttls":TTLS,"horizons":HORIZONS,"cost_bps":COST_BPS,"sources":[asdict(s) for s in sources],"audits":audits,"orders_rows":int(len(panel)),"orders_panel_sha256":sha256_file(args.output/"orders_panel.parquet"),"summary_sha256":sha256_file(args.output/"summary.json"),"terminal_opened":False}; (args.output/"manifest.json").write_text(json.dumps(manifest,indent=2,sort_keys=True),encoding="utf-8"); print(json.dumps(summary,sort_keys=True)); return 0

if __name__=="__main__": raise SystemExit(main())
