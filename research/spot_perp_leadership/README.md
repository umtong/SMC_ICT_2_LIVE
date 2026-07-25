# Spot–perpetual leadership screen

This directory implements `CLM-20260726-0017-SPOTPERP-TAKEOVER-001`, a revision-8 continuation of the expired spot/perpetual price-discovery claim. Target-market evidence is acquired only from checksum-verified Binance public archives.

## Economic mechanisms

The screen separates four hypotheses instead of retuning the rejected five-minute cross-asset lead/lag family:

1. **Spot-leading continuation** — a completed spot impulse and spot taker flow lead a muted USD-M move while a prior-only rolling leadership score favors spot.
2. **Perpetual overshoot reversal** — USD-M price and flow overshoot a weak spot response, widen the spot/perpetual basis, and revert toward the spot anchor.
3. **Basis convergence** — an extreme prior-standardized USD-M premium/discount is accompanied by market-specific flow disagreement and converges.
4. **Leadership-state routing** — a prior-only rolling lead score selects continuation when spot leads and reversal when perpetuals lead.

## Frozen evaluation contract

- BTCUSDT and ETHUSDT spot plus USD-M perpetual one-minute archives;
- 2021-Q4 warm-up, calendar-2022 development, conditional frozen 2023 selection, and conditional 2024 validation; 2025 and 2026 are physically sealed;
- 496 deterministic candidate IDs across the four mechanism families;
- completed one-minute information only, with entry at the next contiguous USD-M minute open;
- adverse same-minute stop priority and gap-stop execution at the observed open;
- official funding-rate cashflows valued at the official mark-price open at the exact settlement timestamp;
- one global account slot, 0.5% planned-loss sizing, 3x notional cap, and 0.1% participation in the completed signal minute’s USD-M quote volume;
- the same signal and exit paths replayed at 12, 18, and 24 basis points round trip; stopped paths add two adverse basis points;
- development passage requires positive 12/18bp geometric growth, positive top-10%-removed return at both costs, at least 150 trades, PF ≥1.10, MDD ≤15%, top-five positive-trade share ≤35%, positive median trade, and both half-years positive.

One representative per mechanism family is frozen before any 2023 archive is downloaded. The 2024 archive is downloaded only if a frozen candidate passes 2023. No credentials, private endpoints, paper orders, or live orders are used.

## Reproduction

```bash
python -m research.spot_perp_leadership.pipeline self-test
python -m research.spot_perp_leadership.pipeline staged-run \
  --output artifacts/spot_perp_leadership
```

The output includes the preregistration, official-source manifest, complete candidate table, best development ledger, stage decision, compact result summary, and SHA-256 inventory. The implementation SHA-256 at claim start is `941e1b99e4bc015282e0f459a0ddd4a291cebb87060a145ef403bedce2884755`.
