# Bybit consensus-lag executable upper-bound screen

Work Claim: `CLM-20260726-0616-BYBIT-CONSENSUS-LAG-001`

This experiment tests a deliberately narrow, non-overlapping microstructure mechanism. It trades the **Bybit USDT linear perpetual** only when **Binance USDT perpetual** and **Bybit spot** deliver a same-direction completed 100 ms price shock while the Bybit perpetual remains behind its prior-only cross-venue basis.

The first question is not whether a polished strategy can be optimized. It is whether the strongest executable 30-second payoff upper bound can survive 100–500 ms latency, completed same-message signal groups, adverse equal-timestamp execution, exact bid/ask crossing, modeled top-quote impact and 12/18/24 bp extra round-trip cost. A negative future-oracle result is fatal for this exact family and prevents wasting time on exit, risk or leverage tuning.

## Causal boundaries

- Tardis `local_timestamp` is the only cross-feed availability clock.
- All signal state comes from completed `[t-100ms,t)` buckets and is usable only at `t`.
- Joint rolling basis state resets after unavailable observations; no time compression or gap filling occurs.
- Quote rows sharing one `local_timestamp` are consumed as a complete captured-message group; only the final reconstructed BBO row is read after the bucket boundary. Entry and exit quote groups are still resolved against the requested side.
- Development data are downloaded only after a candidate passes every fit upper-bound gate.
- 2024, 2025 and 2026 remain sealed.

## Execution and costs

Entry uses the first Bybit quote group after 100, 250 or 500 ms. A 10,000 USDT full fill is rejected if convex top-quote impact breaches its 1- or 2-signal-spread marketable limit. The ledger crosses the observed spread and then subtracts 12, 18 or 24 bp of additional round-trip fees and non-book friction. One global BTC/ETH slot is enforced by actual executable entry time.

The 30-second oracle chooses the best future **executable** exit only to establish an upper bound. It uses no favorable same-timestamp ordering, but it has impossible zero exit-decision latency and therefore cannot be a live strategy rule.

## Reproduction

```bash
python research/bybit_consensus_lag_v1/reconstruct.py
python -m py_compile research/bybit_consensus_lag_v1/run.py
python research/bybit_consensus_lag_v1/run.py self-test
python research/bybit_consensus_lag_v1/run.py probe \
  --cache /tmp/bybit-consensus-lag-v1 \
  --output research_runs/bybit_consensus_lag_v1/probe
python research/bybit_consensus_lag_v1/run.py run \
  --cache /tmp/bybit-consensus-lag-v1 \
  --output research_runs/bybit_consensus_lag_v1/screen
```

No credentials, paper orders, testnet orders or live orders are used.

## V1B source-semantic correction

The first diagnostic run incorrectly invalidated completed quote state whenever the prior row shared the same `local_timestamp`; it is preserved as non-decision evidence in `DIAGNOSTIC_INVALIDATION_001.md`. `PREREGISTRATION_AMENDMENT_001.json` freezes the only correction and records that candidate PnL had already been observed. No threshold, date, cost, gate or execution parameter changed.
