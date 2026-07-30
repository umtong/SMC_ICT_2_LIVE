# Ethereum validator-withdrawal supply absorption Core

This source-first study tests whether completed EIP-4895 validator withdrawals create a repeatable ETH supply-delivery or price-absorption state. Stage 0 is outcome sealed: it verifies the ethPandaOps Xatu `canonical_beacon_block_withdrawal` daily Parquet source, chronology, hashes, event semantics and 2023-2026 availability before any Bybit market outcome is opened.

The source event remains continuous; no market-outcome-selected full/partial threshold is permitted. Conditional economic work uses a fixed three-minute source-confirmation delay plus the project-wide 500ms order latency, one global slot, structural exits, exact funding and fixed small discovery risk.

No credentials or orders are used.
