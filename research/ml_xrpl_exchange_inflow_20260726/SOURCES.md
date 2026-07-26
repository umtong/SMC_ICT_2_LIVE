# Sources — XRPL exchange-inventory inflow

## Authoritative protocol and server references

- Public full-history servers: https://xrpl.org/docs/tutorials/public-servers
- Ledger history and full-history semantics: https://xrpl.org/docs/concepts/networks-and-servers/ledger-history
- Clio `ledger_index`: https://xrpl.org/docs/references/http-websocket-apis/public-api-methods/clio-methods/ledger_index
- `account_tx`: https://xrpl.org/docs/references/http-websocket-apis/public-api-methods/account-methods/account_tx
- Payment transaction type: https://xrpl.org/docs/references/protocol/transactions/types/payment
- Transaction metadata and delivered amount: https://xrpl.org/docs/references/protocol/transactions/metadata

The official XRPL responses are authoritative for ledger boundaries, validation status, transaction type, destination, delivered native-XRP amount and close time. Stable markers are followed until exhaustion; a capped or unresolved marker fails the source gate.

## Frozen account-label evidence

Label evidence is used only to select the account set before source inspection. It is not used as a transaction-value or price source.

- Binance legacy: https://bithomp.com/account/rEb8TK3gBgk5auZkwc6sHnwrGVJH8DuaLh
- Binance current: https://bithomp.com/account/rNxp4h8apvRis6mJf9Sh8C6iRxfrDWN7AV
- Bitstamp: https://bithomp.com/account/rDsbeomae4FXwgQTJp9Rs64Qg9vDiTCdBv
- Bybit legacy: https://bithomp.com/account/rJn2zAPdFA193sixJwuFixRkYDUtx3apQh
- Bybit current: https://bithomp.com/account/rMvCasZ9cohYrSZRNYPTZfoaaSUQMfgQ8G

The label source currently identifies each frozen account with the stated exchange and shows destination-tag-based activity. Labels are frozen at preregistration time. Later relabeling cannot retroactively change an opened result; material identity uncertainty invalidates the affected account family rather than being resolved from market outcomes.

## RPC priority

1. `https://honeycluster.io/` — documented full-history cluster with Clio.
2. `https://xrplcluster.com/` — documented full-history cluster.
3. `https://s2.ripple.com:51234/` — documented Ripple full-history cluster, used only for methods it supports.

A request is accepted only when the result is validated and the returned ledger range contains the frozen requested range. Endpoint fallback is recorded in the evidence manifest.
