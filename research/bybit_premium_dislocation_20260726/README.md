# Bybit-native last/mark/index/premium dislocation fatal screen

This claim changes the information source rather than retuning an existing candlestick, funding or cross-venue rule. It measures how Bybit's own executable last price departs from its mark and index prices, and whether the premium-index state says that departure is transient, persistent or exhausted.

The first GitHub-hosted probe was blocked by Bybit's documented US-IP restriction before any economic data were opened. A checksum-identified transport amendment therefore retains the same endpoints and parameters while adding only Bybit's official regional mainnet hosts; no hypothesis, candidate, date, cost, risk or execution rule changed.

The workflow tests three frozen mechanisms on BTCUSDT and ETHUSDT:

1. **Transient last/mark reversion** — fade an extreme completed last-minus-mark gap when mark remains comparatively close to index.
2. **Aligned stress continuation** — follow an extreme mark-minus-index premium when last, mark, premium and completed price response remain aligned.
3. **Premium-clamp exhaustion** — fade an extreme premium after premium change and last-price response turn against the prior pressure.

## Historical and causal boundary

- Warmup begins on 2021-12-20.
- All thresholds are learned from 2022 only.
- The 72 candidates are evaluated on 2023 without re-estimation.
- 2024, 2025 and 2026 are prohibited from the workflow.
- A signal exists only after a five-minute bar completes; entry is the next exact five-minute open.
- Exits are pricing-state convergence or flip, or an adverse protective stop. There is no arbitrary maximum holding time.
- One global BTC/ETH slot, actual historical funding, 0.5% planned NAV risk, a 3x notional cap, adverse gap stops and 12/18/24-bp account replays are enforced.

The screen is intentionally not rank eligible. A survivor only justifies exact BBO/depth, spread, latency, intratrade marked-NAV and broader pre-2024 validation before any sequential 2024 opening.

## Reproduction

```bash
python research/bybit_premium_dislocation_20260726/reconstruct.py
python -m py_compile research/bybit_premium_dislocation_20260726/run_screen.py
python research/bybit_premium_dislocation_20260726/run_screen.py self-test
python research/bybit_premium_dislocation_20260726/run_screen.py probe \
  --cache /tmp/bybit-premium-cache \
  --output /tmp/bybit-premium-probe
python research/bybit_premium_dislocation_20260726/run_screen.py run \
  --cache /tmp/bybit-premium-cache \
  --output artifacts/bybit_premium_dislocation
```

A zero-survivor result closes this exact completed-five-minute formulation. It does not justify adjacent threshold tuning without a materially different observation or payoff.
