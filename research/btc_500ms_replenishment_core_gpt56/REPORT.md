# BTC 500ms local replenishment at consumed liquidity boundaries

**Result:** `RES-20260730-BYBIT-500MS-REPLENISHMENT-CORE-001`  
**Decision:** `RETIRED_BTC_500MS_REPLENISHMENT_PAYOFF_GEOMETRY_FAILURE`

## Economic question

The study tested whether urgent aggressive flow consuming a frozen short-horizon boundary can be separated into two economically distinct states:

- **acceptance:** outside price discovery remains efficient, so continuation is preferred;
- **absorption/replenishment:** aggressive flow fails to progress or closes back inside, so the breach is faded.

This is narrower than generic one-minute imbalance and does not use an FVG/OB/MSS checklist.

## Frozen event and action

Five-second states were built only from observed Bybit 500ms public-trade buckets. The frozen boundary was the prior completed 30-minute observed-trade high or low. The first rearmed breach required breach-direction turnover at least two prior-only 30-day standard deviations above baseline.

January-February fixed the efficiency median and lower quartile. March-April was development and May-June unchanged confirmation. Orders activated after 500ms and entered at the first later observed 500ms bucket. Acceptance continued the breach and absorption faded it. Structural stops, +1.5R, completed-five-second state loss, actual funding, one slot, 0.5% risk and 3x cap were fixed. No elapsed-time exit existed.

## Programization audit

The initial scalar execution path completed event construction but was too slow to finish the full 500ms account replay. No economic conclusion was taken from that interruption. A vectorized chunk scanner retained the same state and account semantics.

Sixteen deterministic events spanning acceptance, absorption, development and confirmation were replayed through both scanners. Entry/exit timestamps, reason, price, stop, target, duration and ending NAV matched exactly. The final result is therefore an economic decision rather than an unverified optimization artifact.

## Opportunity

| Stage | Accept | Absorb | Flat |
|---|---:|---:|---:|
| Jan-Feb fit | 439 | 302 | 199 |
| Mar-Apr development | 1,174 | 456 | 174 |
| May-Jun confirmation | 953 | 616 | 575 |

The opportunity was broad and frequent.

## Cost-after account result

| Cost | Development multiple | Confirmation multiple | Continuous multiple | Trades | PF | Winner-reroute multiple |
|---:|---:|---:|---:|---:|---:|---:|
| 12 bp | 0.019899x | 0.016496x | 0.000328x | 2,840 | 0.151 | 0.000305x |
| 18 bp | 0.009821x | 0.007595x | 0.0000746x | 2,844 | 0.0819 | 0.0000694x |
| 24 bp | 0.006657x | 0.005212x | 0.0000347x | 2,844 | 0.0430 | 0.0000325x |

At 24bp, the median hold was 14 seconds and the largest five winners supplied 19.96% of positive PnL. This was not a sparse-jackpot strategy.

## Payoff-geometry diagnosis

The median structural stop distance was only **8.66bp**, so the median +1.5R gross objective was **12.99bp**—smaller than the 24bp round-trip cost contract. Of 1,100 nominal target exits, only 242 (22%) were net profitable at 24bp. All 1,233 stop or gap-stop exits lost, and many state/target exits also remained net negative after cost.

The market state may describe very short-lived replenishment, but the executable price distance is too small. Increasing risk or adding ML cannot turn a negative payoff geometry into Core alpha.

## Decision

The exact family is retired. Do not rescue it with a different boundary length, flow-z threshold, efficiency quantile, target, stop, cost, symbol extension, model, risk or leverage. SOL/XRP, ML and official 2024-2026 remain unopened.

The next Core must either observe a materially larger remaining price-delivery distance or use execution mechanics capable of capturing the small replenishment effect without assuming impossible fills.

No credentials, paper orders, testnet orders or live orders were used.
