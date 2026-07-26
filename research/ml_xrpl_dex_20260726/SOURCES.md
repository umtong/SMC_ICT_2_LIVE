# Sources — XRPL DEX inventory route

## Authoritative protocol and server references

- XRP Ledger public servers: https://xrpl.org/docs/tutorials/public-servers
- Clio historical server: https://xrpl.org/docs/concepts/networks-and-servers/the-clio-server
- Clio `ledger_index`: https://xrpl.org/docs/references/http-websocket-apis/public-api-methods/clio-methods/ledger_index
- XRPL `book_changes`: https://xrpl.org/docs/references/http-websocket-apis/public-api-methods/path-and-order-book-methods/book_changes
- XRP Ledger decentralized exchange: https://xrpl.org/docs/concepts/tokens/decentralized-exchange

The official protocol source is the authority for finalized ledger identity, currency encoding, XRP drops conversion, moved volume, and per-ledger OHLC meaning.

## Historical aggregation transport

- XRPL.to API docs: https://xrpl.to/docs
- Historical OHLC endpoint description: https://xrpl.to/insights/xrpl-ohlc-historical-price-api
- Historical token data description: https://xrpl.to/insights/xrpl-historical-token-data

XRPL.to is used only as a bulk historical transport. A source pass additionally requires direct sample confirmation against an official-compatible full-history Clio response. The workflow hashes every received body because third-party historical aggregations can be revised.

## Frozen gateway identities

- GateHub USD issuer: `rhub8VRN55s94qWKDv6jmDy1pUykJzF3wq`
- Bitstamp USD issuer: `rvYAfWj5gh67oV6fW32ZzP3Aw4Eubs59B`
- Currency code: `USD`

The deterministic XRPL.to token identifier is `md5(issuer + "_" + currency)`. The source gate independently requires the token metadata response to contain the same issuer and currency when the endpoint provides identity metadata.
