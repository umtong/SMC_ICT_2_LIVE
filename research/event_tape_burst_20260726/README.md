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

The run downloads only the preregistered 2023 BTCUSDT/ETHUSDT daily archives. It writes source hashes, fit thresholds, development diagnostics, all candidate metrics, a compact result summary and an artifact inventory. The checked-in transport verifies the original base64, gzip and raw-source SHA-256 values, applies one checksum-verified correction to the absorption threshold key, and verifies the final executable source hash.

## Result

`RES-20260726-EVENT-TAPE-FATAL-001` is a hard-valid negative result:

- 28,141 labeled development events and 256 frozen candidates;
- zero development-gate survivors;
- zero positive total-return candidates at 12, 18 or 24 bp;
- the best candidate with at least 60 accepted trades had 64 trades and lost 6.9762%, 10.4855% and 13.8645% at 12, 18 and 24 bp respectively;
- at 18 bp that candidate averaged -17.2837 bp per trade, had zero positive symbol-date segments and lost 11.1916% after removing the largest 10% of positive trades;
- all official 2024-2026 periods remained unopened and no order was submitted.

The successful CI run is `30173874538`; the evidence artifact is `8623675977` with SHA-256 `00bde8111a31838a05cb58f25e3b448ebb9918b5bf0600fd694e884035a76f13`. Exact machine-readable evidence is in `RESULT.json` and `CI_ATTESTATION.json`.

## Decision

Close this exact event-time pace/control continuation and absorption-reversal formulation. It did not produce a positive after-cost candidate even at 12 bp, so broadening the reconstruction, opening 2024 or refining execution would be low information value. The project-wide first place and live permission are unchanged.
