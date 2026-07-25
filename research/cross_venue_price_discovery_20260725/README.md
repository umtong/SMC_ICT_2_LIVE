# Cross-venue informed-flow price discovery

## Claim

- `CLM-20260725-1850-XVENUE-001`
- branch: `agent/r5-cross-venue-price-discovery-001`
- execution venue: Binance USD-M, single BTCUSDT or ETHUSDT position
- signal venues: Binance USD-M and Bybit perpetuals

## Research question

Can a price-discovering venue's completed aggressive-flow and quote impulse predict a still-executable move on Binance after target spread, latency, fee and size impact, without relying on future events or simultaneously holding a hedge?

The SMC/ICT concepts are treated as state transitions rather than chart labels:

- a liquidity **run** requires persistent initiating flow, quote depletion and incomplete follower response;
- a liquidity **sweep/rejection** requires flow decay or reversal and target-side replenishment;
- a cross-venue fair-value gap is the contemporaneous executable-price discrepancy, not a retrospectively drawn candle gap.

## Current stage

The first workflow is source discovery only. It probes systematic public sample files for synchronized trades and quotes, records source SHA-256 and schemas, and computes no strategy or PnL. Missing quote history or incompatible timestamps cause a closed infrastructure result.

If the probe passes, a separate immutable experiment will run the preregistered development days. Selection and confirmation URLs are not requested until their preceding frozen gates pass. The 2026 interval remains sealed.

## Safety

No credentials, private endpoints, paper/testnet/live orders or deployment bundle are used. A passing public-sample experiment is never Champion-eligible without a full independently registered tick dataset and exchange-specific execution audit.
