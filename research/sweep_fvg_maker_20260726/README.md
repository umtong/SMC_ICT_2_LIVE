# Event-conditioned post-only maker at FVG CE / OTE

## Trader explanation

The setup is not “place limits everywhere and hope to earn the spread.” A post-only order is allowed only after a causal SMC sequence:

1. an external high or low is known before the event;
2. price raids that liquidity;
3. the raid is rejected and market structure shifts with displacement;
4. a fair value gap or a measurable displacement leg exists;
5. the order rests at FVG consequent encroachment or the 62%, 70.5% or 79% OTE retracement;
6. the stop is beyond the raid and the target is structural opposing liquidity or a fixed R multiple.

The economic change is the entry mechanism. Previous taker formulations paid the spread and full taker cost. This claim asks whether waiting at the retracement can improve price and capture maker economics without allowing imaginary fills. Queue ahead, post-only acknowledgement, trade-through, partial fill, cancellation TTL and adverse markout must all be modeled from information actually available at the time.

## Stage 0

No PnL is opened. The workflow reuses immutable artifact `8626087323` and checks whether its compact states—or the exact raw source identities they reference—contain the fields required for a conservative queue-aware maker simulation.

A second preregistration is mandatory before any strategy outcome is computed.
