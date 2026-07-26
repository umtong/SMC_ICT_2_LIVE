# XRPL DEX source-gate report

## Decision

The outcome-sealed source gate **failed for historical-data transport**, not for economic performance.

- Claim: `CLM-20260726-2250-ML-XRPL-DEX-001`
- Pull request: `#248`
- Workflow run: `30205051874`
- Artifact: `8632819385`
- Artifact digest: `sha256:56a820fcc29a36da79644d6ebcb334764ecf34a12c2fe2a7daa82600922bd394`
- Source manifest root: `bdebe5292534300c76c648f3aab3495d6cfd145a91041e4afec8416e5c1c6217`
- Result SHA-256: `e9378c9be843705e7bf04da490946803f9678a01cec255ed2acf663e500d1deb`

Scientific decision: `CLOSE_XRPL_DEX_SOURCE_ROUTE_BEFORE_MARKET_OUTCOMES`.

This is not a strategy result, does not enter the Result Registry or cumulative strategy ranking, and does not change the current first place.

## What passed

- Python compilation, seven unit tests and the deterministic self-test passed before network access.
- GateHub USD and Bitstamp USD token identities matched the frozen issuer/currency pairs.
- All response bodies and source code were hashed and uploaded as an immutable Actions artifact.
- The repository project validation step passed on the branch.
- The outcome seal passed: no Bybit market data, future return, label, fitted model, strategy PnL, official 2024/2026 outcome, credential or order was opened.

## Fatal source finding

The historical OHLC endpoint returned parseable current 2026 candles while ignoring all three frozen date-window syntaxes:

1. `start` / `end` in Unix milliseconds;
2. `startTime` / `endTime` in Unix milliseconds;
3. `from` / `to` in Unix seconds.

Every accepted body therefore fell outside the five preregistered pre-2024 windows. The gate correctly retained zero in-window candles for both issuers, so no issuer qualified and no full-history Clio sample scan was opened.

The empty in-window result is not evidence that XRPL DEX activity was absent. It is evidence that this deployed bulk transport did not honor the requested historical range under the frozen request variants.

## Reuse boundary

Do not reopen this exact route with adjacent API parameter guesses, model changes, leverage, thresholds or market-outcome inspection. Reopen only after obtaining a materially different point-in-time historical transport whose date semantics are directly verified before outcome access, such as a self-indexed ledger reconstruction or an independently immutable archive.

The next research route should preserve the useful idea—ledger-native inventory movement—but use official full-history account-range queries that are bounded by ledger indexes and paginated with stable markers.
