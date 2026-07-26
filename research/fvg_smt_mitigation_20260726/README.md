# FVG-Mitigation SMT Continuation fatal screen

This claim converts an ICT/SMC idea into a causal, reproducible fatal screen whose final execution venue remains Bybit.

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

## Frozen stage and source amendment

The first GitHub Actions run reconstructed and validated the strategy implementation, then both Bybit public REST hosts returned a country-level CloudFront 403 before any market row was opened. `amendment_001_source_proxy_after_geo_block.json` therefore changes only the initial data source:

- official Binance USD-M 15-minute and funding archives are used as a checksum-verified fatal-screen proxy;
- symbols remain `BTCUSDT`, `ETHUSDT`, `SOLUSDT`, `XRPUSDT`;
- 2022 is fit and 2023 is development;
- all 256 candidates, signal rules, exits, gates, one-global-slot rule and 12/18/24 bp replay remain unchanged;
- no forced elapsed-time exit;
- 2024–2026 remain mechanically prohibited;
- no credentials or orders.

A proxy survivor cannot rank or open 2024. It must first be replayed with exact Bybit BBO/depth, funding, execution and NAV under a new frozen contract.

## Reproduction

```bash
python research/fvg_smt_mitigation_20260726/reconstruct.py
python research/fvg_smt_mitigation_20260726/run_screen.py self-test
cd research/fvg_smt_mitigation_20260726
python proxy_source.py self-test
python proxy_source.py run \
  --cache /tmp/bybit-fvg-smt \
  --output ../../artifacts/fvg_smt
```

This is a fatal alpha screen and is not rank eligible. A zero-survivor result closes only this exact synchronized-FVG/asymmetric-mitigation dependency under the proxy; a survivor requires exact Bybit validation before any strategy promotion.
