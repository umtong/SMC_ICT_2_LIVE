# CME NDOG/NWOG Delivery

This claim tests an ICT opening-gap model whose state comes from the institutional futures market rather than from another crypto candle pattern.

## Trader explanation

- CME Bitcoin and Ether futures stop trading at 17:00 New York and reopen at 18:00.
- The previous close and new open form a true New Day Opening Gap; Friday close to Sunday open is the New Week Opening Gap.
- The CME percentage gap is mapped to the BTCUSDT or ETHUSDT execution chart at 18:00.
- A completed 15-minute move through CE routes rebalancing toward the prior close equivalent.
- Strong displacement and acceptance away from the gap routes continuation toward known previous-day or previous-week liquidity.
- Entry is the next 15-minute open. The gap thesis supplies the stop and target. There is no elapsed-time liquidation.

## Stage 0

The first workflow performs no PnL. It verifies:

- Yahoo Finance `BTC=F` and `ETH=F` daily open/close history from 2021 through 2023;
- optional Nasdaq Data Link continuous-futures cross-checks;
- official Binance USD-M BTCUSDT and ETHUSDT 15-minute archives against their adjacent SHA-256 checksum files.

Only a passing source probe opens the already-preregistered 432-policy fatal screen. A proxy survivor still cannot rank or open 2024 until an exact CME-source and Bybit BBO/depth account replay is frozen and completed.

```bash
python research/cme_opening_gap_20260726/probe.py self-test
python research/cme_opening_gap_20260726/probe.py run --output artifacts/cme_opening_gap_probe
```
