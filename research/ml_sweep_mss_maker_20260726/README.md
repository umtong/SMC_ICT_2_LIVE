# Minimal ML sweep–MSS consequent-encroachment maker

Claim: `CLM-20260726-1900-ML-SWEEP-MSS-MAKER-001`  
Issue: `#144`

## Trader-readable rule

1. Freeze the prior completed two-minute buy-side and sell-side liquidity.
2. Price raids exactly one side and closes back inside.
3. Opposite displacement closes through the last causal opposing delivery-candle open with aligned aggressive flow. This is the quantitative MSS/CISD.
4. A post-only order rests at 50% of the raid-to-MSS displacement leg—the single consequent-encroachment entry.
5. Stop remains one tick beyond the raid. Target is the untouched opposite two-minute liquidity.
6. There is no elapsed-time liquidation.

The direction and structural prices are fixed before ML. One multinomial logistic model only decides whether the queue-aware order has positive net expected value.

## Quant interpretation

The three model classes are `no full fill`, `full fill then target`, and `full fill then stop/boundary loss`. At acknowledgement, a marketable order is rejected. A resting order fills only after actual opposing aggressive trades consume the complete displayed same-price queue and the full research quantity. Cancellations never improve modeled queue position, touch is never a fill, and partial fills are rejected.

The model produces one cost-aware decision:

```text
EV_12bp
= P(fill→target) × (target distance − 12bp)
− P(fill→stop) × (stop distance + 12bp)
```

The order exists only when `EV_12bp > 0`. There is no probability threshold, model family, CE level, target, stop, risk or leverage grid.

## Frozen stages

- fit: `2022-07-01 BTCUSDT`
- untouched development: `2023-07-01 BTCUSDT`, opened only after the fixed three-class model can be fitted
- 2024–2026: prohibited

The fatal screen cannot enter the cumulative rank. A survivor must retain the unchanged model, event and order path across all remaining pre-2024 samples with actual funding and broader queue evidence before official 2024 can open.
