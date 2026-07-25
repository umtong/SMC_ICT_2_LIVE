# Bybit USDC-to-USDT same-venue price-discovery screen

This claim tests whether the segmented participant and collateral pool in Bybit's USDC-settled BTC/ETH perpetuals produces a causal signal for the more liquid USDT-settled perpetuals traded by the project.

The execution market remains `BTCUSDT`/`ETHUSDT`. `BTCPERP`/`ETHPERP` are signal-only instruments. The study is not a delta-neutral arbitrage, funding trade, session-settlement trade, mark/index/premium trade, dated-futures curve trade or cross-venue latency strategy.

## Mechanism

Raw USDC perpetual fills are grouped by exact exchange timestamp. At each completed group the study measures:

- the USDC price change since the previous USDC event;
- the synchronous USDT price change over the identical event interval;
- their residual, which removes the movement USDT had already completed;
- USDC aggressor-side imbalance and executed notional;
- the first USDT trade available at least 100 ms after event completion.

Four frozen hypotheses are evaluated: USDC move continuation, residual continuation, residual reversal and USDC aggressor-flow continuation. All thresholds are learned only from disclosed discovery dates. Frozen validation dates stay unopened until the preregistered workflow runs.

## Stage

This is a sparse pre-2024 fatal-alpha screen, never a ranking result. The discovery probe found that USDC perpetual trades were far sparser than USDT trades and that the best observed gross short-horizon effects did not cover 12 bp. The validation stage therefore asks only whether a reproducible after-cost exception exists before broader reconstruction is justified.

## Reproduction

```bash
python research/usdc_leadlag_20260726/reconstruct.py
python -m py_compile research/usdc_leadlag_20260726/run_screen.py
python research/usdc_leadlag_20260726/run_screen.py self-test
python research/usdc_leadlag_20260726/run_screen.py run \
  --cache /tmp/bybit-usdc-leadlag \
  --output artifacts/usdc_leadlag
```

The workflow downloads only the preregistered 2023 public archives, records byte counts and SHA-256 values, evaluates the exact 320-policy grid with one global BTC/ETH slot, and replays identical gross markout paths at 12/18/24 bp. Official 2024-2026 data remain sealed and no order endpoint is used.
