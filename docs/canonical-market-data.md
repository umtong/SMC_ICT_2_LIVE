# Canonical Bybit half-year market-data foundation

## Purpose

This foundation ends per-chat reconstruction of the same market history. A worker must reuse the immutable Drive shard and its manifest before any external acquisition. Data construction is strategy-agnostic and cannot open a market outcome, select a model, or reset account NAV.

## Logical periods

- `PRE_2024`: information available through the end of 2023, physically sharded by year for reliable builds.
- `2024_H1`, `2024_H2`, `2025_H1`, `2025_H2`, `2026_H1`: evaluation storage partitions.

Partitions are file boundaries only. Evaluation remains one chronological account path from 10,000 USDT at the start of 2024 through the end of 2026 H1. Model updates may use only information available by their declared completion time.

## Core streams and bars

Each symbol shard contains official Bybit linear-perpetual trade-price, mark-price, index-price and premium-index one-minute bars; five-minute open interest and account ratios; exact funding events; and deterministic trade bars at 1m, 5m, 15m, 1h, 4h and 1d.

The one-minute series is the canonical bar source. Coarser bars are UTC-anchored deterministic derivatives. A window with one or more missing source minutes is marked incomplete and its OHLCV values are invalidated rather than partially aggregated. No forward-fill, interpolation or compressed time is allowed.

Sub-minute 1s/5s/15s bars belong to the separate event-tape lane sourced from official daily Bybit trade archives. That large lane is preserved once built; it is not reacquired by each strategy.

## Information availability

A completed bar becomes usable at `start_time + interval`. Funding becomes usable at `fundingRateTimestamp`. A strategy order generated from the latest available row may activate only after the project-wide 500 ms delay. Stored future rows do not authorize future access.

## Storage contract

GitHub stores the contract, builders, common loader, verifier, tests, small manifests and hashes. Drive stores immutable large artifacts under:

`02_DATA/70_MARKET_AND_REFERENCE_DATA/00_CANONICAL_BYBIT_USDT_LINEAR`

Each artifact is identified by dataset ID, symbol, physical segment, retrieval timestamp, source-page hashes, file hashes, code SHA and coverage audit. A changed source or builder produces a new dataset revision; existing shards are never silently overwritten.

## Worker rule

Before downloading market data, search the Drive canonical folder and GitHub dataset records for the required symbol, stream and period. External acquisition is allowed only for a missing or invalid shard, and the repaired shard must be registered for all later workers.
