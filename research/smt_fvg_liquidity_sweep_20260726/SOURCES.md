# Sources and mechanism translation

## Market-data source

- Bybit official public historical trades: `https://public.bybit.com/trading/`
- The workflow records the exact URL, raw gzip SHA-256, byte size, row count and CSV header for every file before use.

## Economic mechanism

- Carol L. Osler, *Currency Orders and Exchange Rate Dynamics: An Explanation for the Predictive Success of Technical Analysis*, Journal of Finance 58(5), 2003. Stop-loss and take-profit orders cluster near visible technical levels; stop orders beyond levels can create rapid continuation while take-profit liquidity can support reversal.
- Carol L. Osler, *Stop-loss orders and price cascades in currency markets*, Journal of International Money and Finance 24(2), 2005. Stop-loss activation can generate self-reinforcing price cascades.
- Paraskevi Katsiampa, *Volatility co-movement between Bitcoin and Ether*, Finance Research Letters 30, 2019. BTC and ETH exhibit material conditional interdependence.
- Mudassar Hasan et al., *Liquidity connectedness in cryptocurrency market*, Financial Innovation 8, 2022. Major crypto markets are connected through liquidity states.

These sources motivate the distinction between a genuine stop cascade and a failed raid. They do not define or validate the strategy. Every SMC/ICT term is translated into a frozen numerical rule in `preregistration.json`.
