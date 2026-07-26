# ICT Unicorn: liquidity raid → breaker/FVG overlap → first retest

Claim: `CLM-20260726-1539-UNICORN-001`

This is a mechanically testable SMC/ICT strategy for Bybit USDT-linear perpetuals. It is not a generic “sweep plus candle” rule and it does not rename the previously rejected engulf/FVG first-touch family.

## Trader explanation

A bullish setup has six ordered facts:

1. **External sell-side liquidity is raided.** Price trades below a previously confirmed 15-minute swing low and closes back above it.
2. **Short-term structure shifts.** Within a small fixed window, a completed one-minute displacement candle closes above a previously confirmed short-term swing high.
3. **The old bearish Order Block fails.** The last bearish candle before displacement is actually closed through. It is therefore treated as a bullish Breaker, not called an Order Block forever after invalidation.
4. **The displacement leaves a bullish FVG.** The low of the displacement candle is above the high two candles earlier.
5. **Breaker and FVG overlap exactly.** Only the intersection is the Unicorn zone. Merely having both objects somewhere on the chart is insufficient.
6. **The first managed retracement is accepted.** A completed candle must enter the overlap and satisfy the frozen close rule. Entry is the next minute open. A failed first touch kills the setup.

A bearish setup is the exact mirror image. The stop is beyond the original raid extreme, and the target is opposing external liquidity that was already confirmed before entry. An open position has no elapsed-time liquidation: it leaves through the target, protective stop, or a completed close invalidating the Breaker.

## Causal contract

- Every pivot becomes usable only after its right-hand confirmation bars have closed.
- Every signal uses completed bars only.
- Entry is never earlier than the next one-minute open after the completed first-retest candle.
- Missing bars are never filled or compressed. A source gap after entry is terminal account loss in this fatal screen, not deletion of the trade.
- Stop wins same-minute stop/target ambiguity; adverse gap-open stop execution is used.
- The global account has one pending/open position across `BTCUSDT`, `ETHUSDT`, `SOLUSDT`, and `XRPUSDT`.
- There is no arbitrary position time exit.

## Staging

- 2022: fit/screen all 128 frozen policy cells.
- 2023: downloaded and evaluated only if 2022 produces frozen survivors.
- 2024–2026: physically unopened in this workflow.

The screen uses native Bybit monthly one-minute USDT-linear files. Identical account paths are replayed at 12/18/24 bps, with an additional adverse 1 bp reserve for every crossed UTC eight-hour funding boundary. A survivor is still not ranking-eligible: exact historical Bybit funding and BBO/depth execution must replace this bar proxy before any 2024 opening.

## Reproduction

```bash
python -m pip install numpy==2.1.3 pandas==2.2.3 requests==2.32.4 pytest==8.3.4
python -m py_compile research/ict_unicorn_20260726/run.py
PYTHONPATH=research/ict_unicorn_20260726 \
  pytest -q research/ict_unicorn_20260726/test_run.py
PYTHONPATH=research/ict_unicorn_20260726 \
  python research/ict_unicorn_20260726/run.py --self-test
PYTHONPATH=research/ict_unicorn_20260726 \
  python research/ict_unicorn_20260726/run.py \
    --cache /tmp/ict-unicorn-cache \
    --output research_runs/ict_unicorn_20260726/v1
```

No credentials, paper orders, testnet orders, or live orders are used.
