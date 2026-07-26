# Sources and retained rationale

## Market data

- Bybit public historical MT4 kline archive root: `https://public.bybit.com/kline_for_metatrader4/`
- BTCUSDT archive directory: `https://public.bybit.com/kline_for_metatrader4/BTCUSDT/`
- ETHUSDT archive directory: `https://public.bybit.com/kline_for_metatrader4/ETHUSDT/`

The implementation downloads only the frozen pre-2024 monthly one-minute files and records URL, bytes and SHA-256 in the run artifact.

## Model choice

- scikit-learn `HistGradientBoostingClassifier`: `https://scikit-learn.org/stable/modules/generated/sklearn.ensemble.HistGradientBoostingClassifier.html`
- Zhang, Zohren and Roberts, *DeepLOB: Deep Convolutional Neural Networks for Limit Order Books*: `https://arxiv.org/abs/1808.03668`
- Gould and Bonart, *Queue Imbalance as a One-Tick-Ahead Price Predictor in a Limit Order Book*: `https://arxiv.org/abs/1512.03492`

The papers motivate nonlinear, state-dependent market prediction, but this study does not import their L2 features or claim their results transfer to Bybit. HGBT is used because the initial dataset is tabular, medium-sized and contains naturally missing rolling features; the project deliberately avoids an unnecessary deep-learning branch before a simpler nonlinear model proves economic value.
