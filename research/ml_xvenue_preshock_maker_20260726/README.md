# ML pre-shock inside-spread cross-venue maker

`CLM-20260726-2115-ML-XVENUE-PRESHOCK-MAKER-001`

## One material change

The reported reactive cross-venue maker screen placed a Bybit order only after a Binance displacement. It then sat behind the existing displayed best-quote queue; conservative fills arrived after the edge had decayed.

This route changes the order mechanism rather than loosening that screen. Before the displacement, a single pooled side-conditioned HGBT predicts the direct realized utility of:

- improving the current Bybit bid by one tick;
- improving the current Bybit ask by one tick;
- remaining flat.

The price-improving order becomes the new best quote, so initial queue ahead is zero. The label includes the full execution outcome: no placement or structural cancellation unfilled is zero; fill followed by external-liquidity delivery or opposite-liquidity invalidation is the realized gross basis-point target.

## SMC/ICT explanation

The prior completed five-minute Binance fair-value range is the frozen external liquidity. A long maker order rests one tick inside the Bybit spread before buy-side displacement and seeks delivery to prior external buy-side liquidity; a short order is symmetric. The opposite frozen range boundary is structural invalidation. ML chooses whether either side has positive direct economic utility; the setup name never authorizes a trade.

## Causal queue rules

- all features come from completed 100ms local-arrival states;
- activation occurs after 100ms and unchanged 300ms stress;
- order price uses only the last BBO before activation;
- the order must be strictly inside the spread;
- initial queue ahead is zero because the order improves the price;
- opposite aggressive amount counts only while the historical same-side quote is not better than the order;
- cancellation ahead receives no credit;
- pending cancellation and filled exit are structural only;
- one global pending/open slot starts at actual placement time;
- no elapsed-time liquidation exists.

## Initial fatal screen

- train: 2022-07-01
- isotonic calibration: 2023-03-01
- untouched confirmation: 2023-07-01
- BTCUSDT only
- 12/18/24bp stress
- 0.5% planned NAV risk, 3x cap, 5% displayed-quote participation
- both 100ms and 300ms paths must pass
- 2024-2026, credentials and every order path remain prohibited

A survivor still requires unchanged pre-2024 expansion and actual Bybit funding before it can enter the cumulative ranking.
