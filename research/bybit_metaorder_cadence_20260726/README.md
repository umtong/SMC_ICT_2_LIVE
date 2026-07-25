# Bybit latent metaorder cadence study

Claim: `CLM-20260726-0501-METAORDER-CADENCE-001`  
Result: `RES-20260726-METAORDER-CADENCE-001`  
Status: hard-valid, tested below gate, exact dependency retired

## Economic hypothesis

Large parent orders are often split into smaller aggressive child fills. A public-trade observer may therefore detect a latent execution schedule when same-side child clusters recur with a stable notional fingerprint and quasi-periodic cadence. The preregistered payoff tested here was not generic tape momentum:

1. recognize a four-child schedule only after all four completed children are observable;
2. require that the scheduled flow has temporarily pushed against the immediately preceding one-hour trend;
3. forecast the next child from the completed gap sequence;
4. wait until the child is causally late and price has already begun to relax;
5. trade opposite the schedule side for one hour, seeking resumption of the prior trend.

YouTube/order-flow material supplied the mechanism—order splitting, repeated execution algorithms, iceberg-style reconstruction and post-flow relaxation—but no external performance claim was accepted. All economic conclusions below come from this repository's own frozen Bybit replay.

## Frozen information and execution contract

The complete contract is in `preregistration_v1.json`, committed before the four validation partitions were opened.

- Venue and data: official Bybit public BTCUSDT and ETHUSDT linear-perpetual trades.
- Child cluster: contiguous fills with identical exchange timestamp and taker side.
- Fingerprint: nearest USD 2,500 of completed cluster notional.
- Schedule: four same-side, same-fingerprint clusters, each at least USD 25,000, with a median period from 1 to 600 seconds and at most 10% relative gap deviation.
- Causal miss: no matching child by forecast plus the frozen tolerance.
- State filter: completed schedule-direction move non-negative; post-detection move non-positive; schedule direction opposed the completed prior one-hour return by at least 20 basis points.
- Entry: first public trade after the miss decision plus 100 milliseconds, opposite the schedule side.
- Exit: first public trade at or after one hour.
- Account: one global BTC/ETH slot; collisions ranked only by completed schedule regularity and observed notional.
- Cost screen: 12, 18 and 24 basis points round trip.

The fatal screen intentionally stops before bid/ask, exact funding and full account sizing if the signal cannot survive even this simpler adverse-cost test.

## Staging

Exploration and development used eight disjoint first-of-month partitions from 2023. The unfiltered exhaustion rule had a positive average in one intermediate selection sample but failed top-trade removal. The rounded 20-basis-point prior-trend condition was therefore frozen before opening the remaining four preregistered validation partitions.

No 2024 or later partition was opened.

## Preregistered validation result

| Metric | Result |
|---|---:|
| Global-slot trades | 18 |
| Gross mean | -10.2479 bp/trade |
| Gross median | -5.4051 bp/trade |
| Net mean at 12 bp | -22.2479 bp/trade |
| Net mean at 18 bp | -28.2479 bp/trade |
| Net mean at 24 bp | -34.2479 bp/trade |
| Top-10%-removed net mean at 12 bp | -32.8042 bp/trade |
| Positive validation partitions at 12 bp | 0 of 4 |
| Largest winner share of positive gross PnL | 57.9453% |

Only the minimum sample-count gate passed. Net expectancy, median, partition breadth, top-trade removal and concentration gates all failed.

BTCUSDT produced 13 trades with a gross mean of -14.9147 bp. ETHUSDT produced five trades with a gross mean of +1.8858 bp, but remained negative after 12 bp cost and was highly concentrated. The apparent exploratory edge did not reproduce.

## Decision

`RETIRE_EXACT_DEPENDENCY`.

Do not open 2024, do not tune neighboring fingerprint increments, cadence tolerances, trend thresholds or holding periods, and do not promote this family to the strategy ranking. Reopen only if the information unit materially changes—for example, participant identity unavailable in the public tape, independently observed parent-order evidence, or a distinct displayed-depth refill mechanism not already claimed elsewhere.

## Reproduction

```bash
python research/bybit_metaorder_cadence_20260726/evaluate_validation.py \
  --data-dir /path/to/bybit-public-trades \
  --output-dir /tmp/metaorder-validation
```

The evaluator requires all eight preregistered BTCUSDT/ETHUSDT source partitions, checks their presence, applies the frozen global slot, writes the trade ledger, and reproduces the gate decision. Source SHA-256 values are recorded in `validation_manifest.json`.
