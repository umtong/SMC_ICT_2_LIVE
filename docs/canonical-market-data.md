# Canonical Bybit market-data foundation

## Scope

The dataset covers Bybit USDT-linear perpetual markets for `BTCUSDT`, `ETHUSDT`, `SOLUSDT`, and `XRPUSDT` from 2021-01-01 through 2026-06-30 UTC. Storage is split into `PRE_2024_2021`, `PRE_2024_2022`, `PRE_2024_2023`, `2024_H1`, `2024_H2`, `2025_H1`, `2025_H2`, and `2026_H1`. These partitions do not reset model state or account NAV.

## Core market state

Each core symbol-period shard contains official Bybit trade-price, mark-price, index-price and premium-index one-minute bars, five-minute open interest and account ratios, exact funding events, and UTC-anchored trade bars at 1m, 5m, 15m, 1h, 4h and 1d.

A core bar is available only after its close. Missing source rows remain explicit. A derived bar containing an absent source minute is invalid rather than partially aggregated.

## Microbar layer

Official daily Bybit public trade archives are streamed into monthly immutable microbar shards. The daily gzip is SHA-256 identified and removed after aggregation.

Each monthly shard stores:

- a complete one-second UTC grid with price, turnover, volume, trade count and directional flow;
- two UTC-aligned 500 ms halves inside every one-second row, including OHLC, directional flow, trade count, first/high/low/last event offsets and separate availability timestamps;
- deterministic five-second and fifteen-second bars.

The common loader reshapes the two stored halves into explicit 500 ms bars. Covered no-trade intervals and unavailable source intervals have different flags and are never conflated. No price is carried through an interval without a trade.

## Causal timing

The first 500 ms half is available at `second_start + 500ms`. The second half and completed one-second bar are available at `second_start + 1000ms`. Five-second and fifteen-second bars are available at their interval close. Orders derived from available information are subject to the fixed project-wide 500 ms activation delay.

## Identity and validation

Every shard includes a Dataset ID, source-file SHA-256 ledger, file hashes, time boundaries, row counts, code identity and validation result. Existing Dataset IDs are immutable; corrected data uses a new revision.
