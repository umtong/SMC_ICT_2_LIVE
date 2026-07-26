# Primary-source basis

The external literature is used to define falsifiable state variables, not as evidence that this implementation is profitable.

- Cont, Kukanov and Stoikov, *The Price Impact of Order Book Events* (2014): short-interval price changes are primarily linked to order-flow imbalance across limit, market and cancellation events. https://arxiv.org/abs/1011.6402
- Gould and Bonart, *Queue Imbalance as a One-Tick-Ahead Price Predictor in a Limit Order Book* (2015): queue imbalance contains predictive information about the next mid-price move. https://arxiv.org/abs/1512.03492
- Kolm, Turiel and Westray, *Deep Order Flow Imbalance: Extracting Alpha at Multiple Horizons from the Limit Order Book* (2023): stationary order-flow inputs retain more stable predictive value than raw book states and the useful horizon is short. https://doi.org/10.1111/mafi.12413
- Jha et al., *Temporal Convolutional Networks for Financial Time Series Prediction* (2020): walk-forward digital-asset order-book experiments demonstrate that short-horizon LOB prediction can be evaluated causally rather than by random splits. https://arxiv.org/abs/1911.13288
- Tardis Bybit derivatives data documentation: linear-contract history is available from 2020-05-28 and first-day monthly CSV samples can be downloaded without an API key. https://docs.tardis.dev/historical-data-details/bybit
- Tardis normalized `book_snapshot_5`: top-five snapshots are emitted whenever tracked depth changes and include exchange and local-arrival clocks. https://docs.tardis.dev/downloadable-csv-data-types
- Bybit public order-book documentation: the live feed is snapshot/delta based and linear depth updates are published at millisecond frequencies. https://bybit-exchange.github.io/docs/v5/websocket/public/orderbook
