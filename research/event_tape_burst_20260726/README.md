# Bybit event-time trade-tape burst screen

This research claim tests a new information clock rather than another fixed-bar threshold. Raw Bybit public trades are grouped into causally completed activity episodes. The screen then asks whether aggressive **pace/control with efficient price response** continues, while aggressive **effort with weak price result and retracement** reverses.

The implementation is intentionally a **fatal alpha screen**, not a strategy backtest and not a ranking candidate. It uses six sparse Sundays in 2023, learns all distribution thresholds on the first three dates, evaluates 256 frozen candidates on the next three dates, applies a 100 ms decision-to-entry latency, enforces one global BTC/ETH slot for each forward-markout path, and replays identical gross paths at 12/18/24 bp all-in cost.

## Why this is non-overlapping

Reported project studies already rejected ordinary one-minute flow/impact thresholds, five-minute absorption and prior-volume dollar-clock absorption. This claim changes the primitive observation:

- episodes are formed from inter-trade timing and a causal quiet interval, not candles or volume bars;
- pace is notional per event-time second;
- control is aggressor-side signed-notional dominance;
- effort/result efficiency and retracement split initiative from absorption;
- the first admissible entry is the next trade after episode closure plus latency.

It does not test passive maker queues, L2 depletion/refill, cross-venue propagation, liquidation cascades, quarter-hour scheduling, OCO movement hazard, prior-session auction profile, positioning, collateral stress or option surfaces.

## Reproduction

```bash
python research/event_tape_burst_20260726/reconstruct.py
python -m py_compile research/event_tape_burst_20260726/run_screen.py
python research/event_tape_burst_20260726/run_screen.py self-test
python research/event_tape_burst_20260726/run_screen.py run \
  --cache /tmp/bybit-event-tape \
  --output artifacts/event_tape_burst
```

The run downloads only the preregistered 2023 BTCUSDT/ETHUSDT daily archives. It writes source hashes, fit thresholds, development diagnostics, all candidate metrics, a compact result summary and an artifact inventory. The checked-in transport reconstructs `run_screen.py` only after verifying the base64, gzip and raw-source SHA-256 values.

## Interpretation

A zero-survivor result closes this exact event-time pace/control formulation without opening 2024. A survivor is still not deployable: it must first be reconstructed on broader 2023 coverage, frozen before 2024, converted from markouts into structural entries/exits, and tested with exact Bybit BBO/depth, costs, funding, risk sizing and account NAV.
