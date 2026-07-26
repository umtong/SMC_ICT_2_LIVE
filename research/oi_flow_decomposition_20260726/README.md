# Bybit sub-second OI × aggressive-flow decomposition

Claim: `CLM-20260726-0958-OI-FLOW-DECOMP-001`  
Result target: `RES-20260726-OI-FLOW-DECOMP-001`

## Why this scope

Completed-bar OI rules cannot distinguish who initiated a position change or whether the price response was efficient. This screen joins Bybit's tick-level open-interest updates with same-symbol aggressor flow, trade response and executable BBO state on the common local-arrival clock.

The study does **not** assume that OI alone predicts direction. It tests four different inventory transitions: new-position continuation, trapped new positions, closing cascade and closing exhaustion. No existing project claim uses tick-level Bybit OI as the primary event variable.

## Causal and execution boundary

- OI, trades and quotes are ordered by `local_timestamp`.
- Every signal uses only a completed 1s, 2s or 5s window.
- OI and activity scales are shifted and prior-only.
- Entry occurs at the causally current BBO after 100ms or 500ms latency; a BBO older than one second is unavailable.
- Observed spread, historical funding, 5% top-quote participation, 0.5% NAV risk and a 3x notional cap are applied.
- An adverse stop cannot be improved by a rebound during exit latency.
- Exits are price/state barriers only. There is no arbitrary maximum holding-time liquidation.
- One global BTC/ETH slot is enforced and same-time re-entry is prohibited.

## Staging

The first workflow opens only six pre-2024 public first-day samples. It evaluates all 1,152 frozen policies under additional 12/18/24bp round-trip stress. The output is not rank eligible.

A full-gate survivor must be frozen and expanded to every remaining available pre-2024 first-day sample before any 2024 data can be requested. Zero survivors close this exact information/payoff dependency; they do not authorize threshold or leverage retuning.

## Reproduction

```bash
python -m pytest -q research/oi_flow_decomposition_20260726/test_run_screen.py
python research/oi_flow_decomposition_20260726/run_screen.py \
  --output research_runs/oi_flow_decomposition/output \
  --cache /tmp/oi-flow-cache
```
