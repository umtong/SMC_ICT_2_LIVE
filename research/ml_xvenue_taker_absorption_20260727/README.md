# ML cross-venue taker propagation/absorption screen

Claim: `CLM-20260727-ML-XVENUE-TAKER-ABSORPTION-001`  
Result: `RES-20260727-ML-XVENUE-TAKER-ABSORPTION-001`

This is a new profit-first information unit. It does not continue the retired passive maker strategy. It reuses only normalized quote/trade parsing and completed 100 ms state construction.

## Mechanism

A completed Binance Futures displacement can imply either:

1. **propagation** — Bybit has not yet delivered the external fair value, so continuation toward frozen fair value or a 1.5-shock measured move is attractive; or
2. **absorption/overshoot** — Bybit has overreacted relative to the pre-shock origin and frozen fair value, so reversal is attractive.

One HistGradientBoosting regressor estimates the gross structural payoff of both candidate actions. The system chooses continuation, reversal, or flat. Costs are then subtracted before authorization.

## Causal contract

- Features use completed 100 ms states only.
- The signal state completes before the fixed 500 ms latency starts.
- Entry is at the executable Bybit BBO immediately before activation, with a marketable-limit protection.
- A resting structural target or stop can execute without a new discretionary decision.
- Target/stop contact uses within-bin executable BBO extrema; a same-bin ambiguity is assigned to the stop, never the favorable target.
- External-reference and opposite-displacement exits use a fresh completed state plus 500 ms latency and the last BBO observable before activation.
- There is no maximum holding time or scheduled liquidation.
- Exposure still open at a source boundary is marked to executable BBO for NAV and remains strategy-open.
- The four symbols share one global pending-entry/open-position slot.

## Frozen initial screen

- train: 2022-07-01
- calibration: 2023-03-01
- untouched confirmation: 2023-07-01
- symbols: BTCUSDT, ETHUSDT, SOLUSDT, XRPUSDT
- costs: 12, 18, and 24 bp all-in round trip
- starting NAV: 10,000 USDT
- planned risk: 1% of current NAV per filled position
- initial leverage cap: 10x
- capacity cap: 10% of the displayed opposing Bybit best quote

A route advances only when its selected calibration path and untouched confirmation path are both positive at 24 bp and confirmation avoids forced liquidation. A survivor must expand across additional pre-2024 dates, add actual Bybit funding, then freeze before official 2024H1. Otherwise the exact route is retired without adjacent rescue.

## Run

```bash
python reconstruct.py
python run.py self-test
python run.py extract \
  --data-root /path/to/data \
  --date 2022-07-01 \
  --symbol BTCUSDT \
  --stage train \
  --output events_train_BTCUSDT.csv.gz
python run.py evaluate --events-root /path/to/events --output /path/to/output
python audit.py --root /path/to/output --research-root . --output /path/to/output/AUDIT.json
```

The GitHub Actions workflow downloads only the frozen public pre-2024 dates, extracts twelve symbol-date partitions in parallel, combines them once, runs the global-slot account, and independently audits the result.
