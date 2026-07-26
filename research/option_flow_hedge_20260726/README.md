# Deribit option-flow hedge-pressure research

This claim tests a structurally different options information unit from implied-volatility level, risk reversal, butterfly or term-structure studies. Completed Deribit BTC/ETH option trades are treated as observable customer/taker pressure. The intended causal translation is:

- aggressive call buying and put selling contribute positive signed delta demand;
- aggressive put buying and call selling contribute negative signed delta demand;
- near-expiry, near-the-money option demand receives higher gamma-pressure weight;
- short-gamma pressure aligned with underlying movement may amplify continuation;
- long-gamma supply or failed delta pressure may support reversal;
- BTC-versus-ETH option-flow disagreement may route the single allowed Bybit perpetual slot.

Options are signal-only instruments. Any later strategy execution remains restricted to Bybit `BTCUSDT` and `ETHUSDT`, with one global pending/open slot and realistic 12/18/24 bp screening. No option order is placed.

## Current stage

The first workflow is a source-availability and schema probe only. It opens one pre-2024 sample date and checks:

- Deribit grouped `OPTIONS` trades;
- Deribit grouped `OPTIONS` option-chain snapshots and Greeks;
- Bybit BTCUSDT/ETHUSDT executable quotes and trades;
- timestamp, symbol, side, price, amount, delta, gamma and underlying-price fields needed for a causal join.

No strategy PnL, candidate selection, 2024-2026 data, credentials or orders are opened by the probe. A full screen is implemented only after the probe freezes exact source identities, clock handling, stage dates and the option-flow translation.
