# Causal vulnerable-inventory pressure map — pre-2024 fatal screen

Claim: `CLM-20260726-1058-INVENTORY-MAP-001`  
Result placeholder: `RES-20260726-INVENTORY-MAP-001`  
Issue: #83  
Stage: sparse pre-2024 diagnostic; **not rank eligible**.

## Economic hypothesis

The strategy reconstructs a path-dependent stock of outstanding long and short cohorts by causal entry-price region. A completed five-second rise in open interest adds a cohort to the dominant aggressor side at the bucket VWAP; a fall in open interest removes the dominant closing side pro rata. Cohorts decay in calendar time. Prior-only realized volatility projects each cohort's adverse stop/liquidation-hazard band, and local kernel density defines the pressure of that quantitative liquidity pool.

The three frozen families are:

1. **Cluster attraction:** displacement and aggression advance toward a dense, un-crossed vulnerable-inventory band.
2. **Cascade follow-through:** price crosses the mapped band while open interest contracts and aggression remains aligned.
3. **Depletion reversal:** after a crossed band loses at least half its pressure, price and flow reclaim the opposite side.

For an SMC/ICT explanation, the estimated vulnerable inventory is the liquidity pool; the move toward it is displacement, the OI-contracting crossing is the liquidity run, and the pressure-loss reclaim is sweep exhaustion. No later-confirmed swing or future MFE/MAE defines the setup.

## Frozen sample and grid

The source manifest reuses 36 SHA-identified Tardis public first-day files for Bybit BTCUSDT and ETHUSDT normalized trades, quotes and derivative ticker:

- Fit: 2023-01-01, 2023-03-01, 2023-05-01.
- Development: 2023-07-01, 2023-09-01, 2023-11-01.
- 2024-2026: prohibited in this workflow.

The 1,296 cells are 18 inventory maps × 2 fit pressure quantiles × 2 flow-purity floors × 3 families × 2 entry latencies × 3 diagnostic horizons. Executable bid/ask quotes include observed spread; the same gross paths are replayed with an additional 12/18/24 bp round-trip cost stress. One global BTC/ETH slot is enforced.

See `preregistration.json` for the exact state equations, matching baseline, breadth/concentration gates and survivor action.

## Reproduction

```bash
python -m pip install numpy==2.1.3 pandas==2.2.3 requests==2.32.4 pytest==8.3.4
python -m py_compile run_screen.py test_run_screen.py
python -m pytest -q test_run_screen.py
python run_screen.py --self-test --output /tmp/inventory-self-test --cache /tmp/inventory-cache
python run_screen.py --output /tmp/inventory-output --cache /tmp/inventory-cache
(cd /tmp/inventory-output && sha256sum --check SHA256SUMS.txt)
```

Outputs:

- `CANDIDATES.csv`: all frozen cells and cost-stressed development metrics.
- `RESULT.json`: gate count, best diagnostic cell and sealed-period assertions.
- `SOURCE_MANIFEST.csv`: source URLs, byte counts, hashes and cache status.
- `SHA256SUMS.txt`: output integrity.

A positive sparse result is not a strategy promotion. It only authorizes all remaining pre-2024 first-day samples followed by structural exits, exact funding, risk sizing and continuous NAV replay before any 2024 opening.
