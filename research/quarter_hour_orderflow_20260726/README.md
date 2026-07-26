# Quarter-hour structural ML fatal screen

Claim: `CLM-20260726-0240-QHOUR-001`  
Planned result: `RES-20260726-ML-QHOUR-STRUCTURAL-FATAL-001`  
Branch: `agent/r19-ml-qhour-structural-001`

## Why this is a takeover rather than a new claim

The revision-11 branch completed an official Binance archive audit and computed no strategy or PnL. Its lease expired. This revision reuses that verified source path but amends the unexecuted economic design before any market outcome is seen. The old fixed 1/4/8/12-hour exits and large parameter grid are removed.

## Frozen information unit

At each UTC quarter-hour boundary, aggressive quote-notional imbalance is measured only over the completed first ten seconds. The same rule is measured at matched minute offsets 07/22/37/52 as a placebo. Strictly prior 1-minute price state and 5-minute Binance metrics supply volatility, taker-flow and open-interest context.

One pooled HGBT estimates whether a pre-known structural target is reached before a structural stop for two rule-owned routes:

- flow continuation toward the prior four-hour directional extreme, stopped at the prior 15-minute opposite extreme;
- flow rejection/reversal toward the prior four-hour opposite extreme, stopped beyond the completed ten-second event extreme.

The signal enters only at the next exact one-minute open. There is no elapsed-time exit. Three later days are loaded solely to observe a frozen target or stop; a selected unresolved path fails the gate rather than being force-closed.

## Chronology

- Train: 2022-01-01, 2022-03-01, 2022-05-01.
- Calibrate once: 2022-07-01.
- Fatal confirmation: 2022-09-01 and 2022-11-01.
- 2022 secondary confirmation, 2023 and every official 2024-2026 interval remain closed.

## Reproduce

```bash
python -m pip install numpy==2.1.3 pandas==2.2.3 scikit-learn==1.6.1 requests==2.32.4 pytest==8.3.4
cd research/quarter_hour_orderflow_20260726
PYTHONPATH=. pytest -q
PYTHONPATH=. python run.py \
  --output ../../research_runs/quarter_hour_orderflow_20260726/fatal \
  --cache /tmp/qhour-cache
```

Every downloaded archive must match its adjacent official `CHECKSUM`. The run uses one global slot, recorded funding, adverse same-minute ordering, 0.1% preceding-minute participation, 5x notional cap and 12/18/24 bp round-trip replays. This fatal screen cannot enter the strategy ranking or authorize orders.
