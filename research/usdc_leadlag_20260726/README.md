# Bybit USDC-to-USDT same-venue price-discovery screen

This claim tested whether the segmented participant and collateral pool in Bybit's USDC-settled BTC/ETH perpetuals produced a causal signal for the more liquid USDT-settled perpetuals traded by the project.

The execution market remained `BTCUSDT`/`ETHUSDT`. `BTCPERP`/`ETHPERP` were signal-only instruments. The study was not a delta-neutral arbitrage, funding trade, session-settlement trade, mark/index/premium trade, dated-futures curve trade or cross-venue latency strategy.

## Mechanism

Raw USDC perpetual fills were grouped by exact exchange timestamp. At each completed group the study measured:

- the USDC price change since the previous USDC event;
- the synchronous USDT price change over the identical event interval;
- their residual, which removed movement already completed by USDT;
- USDC aggressor-side imbalance and executed notional;
- the first USDT trade available at least 100 ms after event completion.

Four frozen hypotheses were evaluated: USDC move continuation, residual continuation, residual reversal and USDC aggressor-flow continuation. All thresholds were learned only from the three disclosed discovery dates. The four frozen validation dates were opened only by the preregistered workflow.

## Result

`RES-20260726-USDC-LEAD-FATAL-001` is hard-valid negative evidence. All 320 candidates failed the frozen validation gate and no candidate had positive total return at 12, 18 or 24 bps. The best candidate satisfying the 40-trade minimum made 42 trades and lost 3.7521%/6.1472%/8.4827% at 12/18/24 bps. Official 2024-2026 periods remained unopened.

This exact dependency family is closed. Do not expand coverage or tune adjacent thresholds, execution, leverage or risk under the same formulation.

## Reproduction

```bash
python -m py_compile research/usdc_leadlag_20260726/run_screen.py
python research/usdc_leadlag_20260726/run_screen.py self-test
python research/usdc_leadlag_20260726/run_screen.py run \
  --cache /tmp/bybit-usdc-leadlag \
  --output artifacts/usdc_leadlag
```

The workflow downloads only the seven preregistered 2023 dates, records byte counts, decompressed row counts and SHA-256 values for 28 archives, evaluates the exact 320-policy grid with one global BTC/ETH slot, and replays identical gross markout paths at 12/18/24 bps. See `RESULT.json` and `CI_ATTESTATION.json` for the durable decision-ready record.
