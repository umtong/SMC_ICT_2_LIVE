# L1 execution toxicity benchmark

Claim: `CLM-20260725-1510-L1-EXEC-001`

## Scope

This experiment measures three execution surfaces without claiming directional alpha:

1. queue-aware L1 maker fill and post-fill toxicity;
2. taker Slippage-at-Risk under explicit submission latency;
3. a causal maker/taker gate selected on the first chronological half and evaluated on later quarters.

The scope is deliberately separate from active absorption-flow and general Binance causal-baseline claims.

## Point-in-time contract

- A decision at second `t` uses only book and trade events whose exchange event time is at or before the end of `t`.
- Orders become active no earlier than the next millisecond.
- Maker fill requires subsequent eligible aggressor volume to exceed modeled queue-ahead plus order quantity.
- A non-filled maker order falls back only after its deterministic TTL.
- Development, validation and confirmation are chronological.
- The nine-day 10-second sample is used only for state-toxicity validation; it is not treated as exact queue evidence.

## Reproduction

Research dependencies are intentionally isolated from the control-plane package:

```bash
python -m pip install numpy pandas numba
python research/experiments/l1_execution_toxicity/run.py \
  --btc-root /path/to/BTC/raw/root \
  --eth-root /path/to/ETH/raw/root \
  --micro10s-root /path/to/micro10s \
  --out /tmp/l1-exec
```

The raw archives are identified in `data/catalog/dataset-registry.jsonl` by canonical URL and SHA-256.

## Decision

The best causal gate lowered five-second round-trip drag by roughly 0.20 bp in development and validation and 0.11 bp in confirmation. This is useful as an execution component but is far too small to constitute the project alpha target. The result is research-only until prospective local-receive-time and private-execution evidence exists.
