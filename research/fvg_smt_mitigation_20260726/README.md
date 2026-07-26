# FVG-Mitigation SMT Continuation fatal screen

This claim converts an ICT/SMC idea into a causal, reproducible Bybit test.

## Trader explanation

1. BTC/ETH or SOL/XRP displace in the same direction and complete a same-time 15-minute fair value gap.
2. One contract retraces into its own FVG while the correlated peer refuses to mitigate its FVG.
3. That asymmetry is the SMT divergence: the peer is holding relative strength/weakness.
4. The retracing contract must reclaim consequent encroachment or the near FVG edge on a completed bar.
5. Entry is the next 15-minute open, never the touch.
6. Stop is beyond the failed mitigation; target is previous-day or previous-week external liquidity.

A sweep, FVG touch, or correlation divergence alone is not an entry.

## Why this is new inside the project

The reported cross-asset SMT study used generic rolling 12/48-bar highs and lows and entered immediate sweep reversal or laggard catch-up. This model anchors the relational signal to synchronized FVG creation and **asymmetric later mitigation**.

It also does not overlap the active Unicorn model: there is no external liquidity raid, pivot MSS, order block, breaker conversion, or breaker–FVG overlap.

## Frozen stage

- Bybit `BTCUSDT`, `ETHUSDT`, `SOLUSDT`, `XRPUSDT`
- 15-minute completed klines
- 2022 fit; 2023 development
- 256 frozen candidates
- actual historical funding
- one global position
- identical 12/18/24 bp round-trip cost replay
- no forced elapsed-time exit
- 2024–2026 mechanically prohibited
- no credentials or orders

## Reproduction

```bash
python research/fvg_smt_mitigation_20260726/run_screen.py self-test
python research/fvg_smt_mitigation_20260726/run_screen.py run \
  --cache /tmp/bybit-fvg-smt \
  --output artifacts/fvg_smt
```

This is a fatal alpha screen and is not rank eligible. A survivor still requires broader pre-2024 replication and exact Bybit BBO/depth execution before official 2024 can be opened.
