# Algebraic synthetic cross-rate lag — fatal executable upper-bound screen

## Question

Can the executable Binance spot cross-rate

```text
ALT/BTC × BTC/USDT = synthetic ALT/USDT
```

lead the executable Bybit `ALTUSDT` USDT-linear perpetual quote after removing only a prior-observable basis?

This is not another free-form direction model. The leader is an algebraic identity built from two independently quoted spot markets. A useful lag would have to survive the complete executable path: completed message groups, target latency, bid/ask crossing, capacity impact, a marketable-limit cap and 12/18/24 bp account cost replay.

## Frozen scope

- Bybit targets: `ETHUSDT`, `SOLUSDT`, `XRPUSDT` linear perpetual quotes.
- Binance spot leaders: `ETHBTC`, `SOLBTC`, `XRPBTC`, and `BTCUSDT`.
- Common clock: Tardis Tokyo `local_timestamp`.
- Signal information: final reconstructed BBO in each fully completed 100 ms same-local-timestamp group.
- Synthetic executable bid/ask: `cross_bid × btc_bid` and `cross_ask × btc_ask`.
- Prior basis: segmented prior-only EWM, span 600 completed buckets, minimum 300.
- Candidate grid: 324 fixed combinations.
- Entry latency: 100, 250 or 500 ms.
- Fixed notional: 10,000 USDT.
- Costs: 12, 18 and 24 bp round trip.
- One global target slot across ETH, SOL and XRP.
- Fit samples: first public monthly sample days in March, May and July 2023.
- Development: September, November and December 2023, opened only after a fit survivor.
- 2024 through 2026 are sealed.

The future best executable exit within 30 seconds is an impossible zero-decision-latency upper bound, not a strategy. It is used only as a fatal screen. A fit survivor must also have a positive causal fixed-10-second mean at 18 bp, at least 20 trades, positive median and top-10%-winner-removal mean, and positive results on at least two of three calendar days.

## Source identity

The readable engine is reconstructed from four hash-bound base64 fragments.

- raw source bytes: `41582`
- raw source SHA-256: `1aa1f4d93ec4d5500491a923812ed210997b2fb026129ecbb2d3a44af4e21339`
- gzip bytes: `11317`
- gzip SHA-256: `327da831fe816b55462c556b1393a1b43aaebcb9039c4766e1906d707adc4f99`
- base64 bytes: `15092`
- base64 SHA-256: `457b4e55dc5cfc564ee3055ed5b7b87313b0d7ae5544685a255d0dda2d5fd1e1`

Run locally:

```bash
python research/synthetic_crossrate_v1/reconstruct.py
python -m py_compile research/synthetic_crossrate_v1/run.py
python research/synthetic_crossrate_v1/run.py self-test
python research/synthetic_crossrate_v1/run.py probe \
  --cache /tmp/synthetic-crossrate-v1 \
  --output /tmp/synthetic-crossrate-v1-probe
python research/synthetic_crossrate_v1/run.py run \
  --cache /tmp/synthetic-crossrate-v1 \
  --output /tmp/synthetic-crossrate-v1-screen
```

Research only. No credentials, private endpoints, testnet orders, paper orders or live orders are enabled.
