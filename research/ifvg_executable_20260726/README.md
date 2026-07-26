# Executable ICT Inversion Fair Value Gap fatal screen

This study tests a complete SMC/ICT state machine rather than another one-bar sweep or immediate markout rule.

## Trader-language rule

A standard fair value gap is created only when a three-bar displacement leaves non-overlap between the first and third bars. The setup is not traded immediately. Price must subsequently **close through the far edge of that gap**, showing that the original imbalance failed and changed polarity into an **inversion fair value gap (IFVG)**. The first completed retest of the inverted zone must reject in the new direction. Entry occurs at the next executable Bybit bid or ask.

For a bearish setup:

1. bullish displacement creates a bullish FVG;
2. a completed bearish candle closes below the FVG;
3. price retests the failed gap from below and closes back below it;
4. sell at the next executable bid;
5. stop above the inverted zone or retest high, whichever is farther;
6. target the pre-event external sell-side liquidity that was still untouched at entry.

The bullish rule is symmetric. The position ends only at protective stop, opposing external liquidity, or completed IFVG invalidation. The sample boundary is a NAV mark, not a strategy-forced liquidation.

## Why this payoff is materially different

The economic edge, if present, comes from **polarity failure plus first-retest repricing**, not from a generic FVG fill. The original directional auction failed, trapped continuation participants, and left the former imbalance as a supply/demand barrier. The target is a pre-existing external-liquidity objective, so the reward is structural rather than a fixed time markout.

This is distinct from the active Unicorn claim, which requires an order block to fail into a breaker and overlap a same-direction FVG. It is also distinct from FVG-SMT, BPR, session, L2 cancellation/refill prediction, cross-venue and OCO scopes.

## Frozen first-stage contract

- instrument: Bybit BTCUSDT linear perpetual;
- source: immutable 500 ms executable BBO/trade states from GitHub Actions artifact `8626169763`;
- fit: `2022-07-01`;
- untouched development: `2023-07-01`, opened only after a fit survivor;
- `2024-2026`: mechanically prohibited;
- bars: exact complete 1, 3 and 5 second groups, reset after every source gap;
- 216 fixed candidates across displacement, gap width, lower-edge/CE retest, minimum structural R and stop buffer;
- next-bar executable BBO entry;
- adverse same-bar stop ordering;
- one global slot;
- 12/18/24 bp all-in cost replay;
- account paths at 0.5%, 1%, 2%, 4% and 8% planned risk, but risk does not select a negative trade path;
- largest 10% of positive 12 bp event keys removed before complete rerouting.

The fit gate requires at least 20 accepted events, positive 24 bp mean and median, PF above one, at least 1% sample-day NAV growth at 1% planned risk, and the same 1% growth after winner removal and rerouting. A zero-survivor result closes this exact formulation immediately.

## Reproduction

```bash
python run_screen.py self-test
pytest -q test_run_screen.py
python run_screen.py run \
  --fit reused/bybit_l2_resiliency/output/compact_states/2022-07-01_BTCUSDT_state.parquet \
  --development reused/bybit_l2_resiliency/output/compact_states/2023-07-01_BTCUSDT_state.parquet \
  --output research_runs/ifvg_exec/output
```

No credentials, private endpoints, paper orders, testnet orders or live orders exist in this branch.
