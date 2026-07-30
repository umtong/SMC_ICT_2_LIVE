# Ethereum principal-scale validator exit-flow decision

**Result:** `RES-20260730-ETH-PRINCIPAL-EXIT-FLOW-001`  
**Status:** `RETIRED_PRINCIPAL_PARTIAL_SEMANTIC_SPLIT_FAILURE`  
**Comparison confidence:** low; aggregate-withdrawal outcomes for the same forward months were already research-exposed  
**Official 2024–2026:** unopened  
**Orders:** none

## Why this audit was necessary

The aggregate EIP-4895 withdrawal route failed even after source and timestamp corrections. A plausible remaining programization error was economic rather than mechanical: the source mixed millions of automatic reward skims with the much rarer withdrawal of validator-principal-scale balances.

The split was fixed before its market result:

- `principal-scale`: amount at least 16 ETH;
- `partial-reward control`: amount below 16 ETH.

Sixteen ETH is a conservative protocol-scale proxy, not an exact label for every full validator exit. It can miss slashed low-balance exits. It was chosen before the split outcome from the 32 ETH principal scale and a source-only gap, never from price or PnL.

## Source decision

The split source passed exactly:

- 264 daily partitions;
- 6,314 continuous hourly states;
- 29,982,950 unique, globally contiguous withdrawals `0..29,982,949`;
- 8,113,549.49 total ETH;
- exact row and ETH conservation.

The distinction was unusually clean:

| Stream | Rows | Row share | ETH | Amount share |
|---|---:|---:|---:|---:|
| Principal-scale ≥16 ETH | 202,571 | 0.6756% | 6,518,259.31 | 80.34% |
| Partial reward <16 ETH | 29,780,379 | 99.3244% | 1,595,290.18 | 19.66% |

There were exactly zero withdrawals between 8 ETH and 16 ETH in the complete 2023 source chronology. This confirms that the split separates a genuine source distribution, not a visually convenient market filter.

## Corrected economic boundary

The earlier aggregate prototype allowed a development event to resolve after the next stage had begun. This audit corrected the boundary:

- fit actions unresolved by September 1 never become training labels;
- development and confirmation positions are marked at their fixed boundary rather than strategy-closed;
- no outcome crosses into the next selection stage;
- no model refit occurs after the fit interval.

Both source streams then used the identical account contract:

- completed hourly stream amount at or above its prior-only rolling 720-hour q90;
- source hour plus 180 seconds, then fixed 500ms order latency;
- first later observable ETHUSDT one-minute open;
- long absorption or short supply acceptance versus flat;
- event-hour structural invalidation and prior-only 24-hour external objective;
- actual signed funding, adverse same-minute ordering;
- 0.5% current-NAV planned loss, 3x cap, one global slot;
- 13/18/24bp and no elapsed-time close.

The fixed action-value model was an eight-member event-bootstrap HGBT ensemble. It predicted direct 24bp account return; the action score was ensemble mean minus half its standard deviation.

## Source and action breadth

| Stream | Shock events | Action rows | Fit resolved | Development | Confirmation |
|---|---:|---:|---:|---:|---:|
| Principal-scale | 563 | 1,034 | 417 | 331 | 285 |
| Partial reward | 561 | 1,030 | 442 | 294 | 294 |

The failure is therefore not caused by a missing event tape.

## Principal-scale development

At 24bp, the observable event-response rule was only marginally positive:

- 73 trades;
- NAV `10,080.47`, return `+0.8047%`;
- PF `1.033`;
- 26 targets and 47 stops;
- median trade `-0.5%`;
- top five winners supplied `44.73%` of positive PnL.

The ML policy made the result worse:

- 21 trades;
- NAV `9,624.55`, return `-3.7545%`;
- PF `0.483`;
- 7 targets and 14 stops;
- every positive PnL unit was inside the largest five winners.

Deleting its three largest positive event keys before full slot rerouting left `9,376.52 USDT`, PF `0.130`.

The raw action surface was also weak. Principal-scale shorts had positive gross mean movement of `15.92bp`, but the 24bp account value was `-13.66bp`; longs were negative before cost. The source contained some direction information but insufficient tradable distance.

## Principal-scale frozen confirmation

The unchanged observable-response route collapsed:

- 74 trades;
- NAV `8,149.71`, return `-18.5029%`;
- PF `0.276`;
- 18 targets and 56 stops;
- top-five positive-PnL share `71.41%`.

The ML policy appeared positive only because it selected two trades:

- one target and one stop;
- NAV `10,031.85`, return `+0.3185%`;
- exact winner deletion left one stop and `9,950.00 USDT`.

This is not a repeatable Core. Confirmation longs had a positive mean of only `1.72bp` at 24bp, a full-loss median and 30.77% positive share. Selecting long-only after observing this sign change would be a prohibited regime rescue.

## Partial-reward control

The negative control did not establish a stable alternative.

- Development ML: 20 trades, `10,184.78 USDT`, PF `1.256`, but top-five positive-PnL share `97.31%`; winner deletion fell to `9,562.68`.
- Confirmation ML: 18 trades, `9,598.55 USDT`, PF `0.450`; winner deletion `9,354.90`.

Thus the rare principal-scale stream was not superior in development, and the much larger reward stream also changed sign in confirmation.

## Programization versus economics

The audit found and corrected a real label-boundary defect. It also showed that the 16 ETH source split is economically meaningful. Neither correction restored alpha:

1. the deterministic principal response changed from a small development gain to a large confirmation loss;
2. the ML policy lost in development and collapsed to two confirmation trades;
3. winner deletion invalidated both apparent ML survivors;
4. median trades remained the full planned loss;
5. the partial control was similarly unstable.

The failure is therefore economic, not a remaining source transport, timestamp, split, stage-boundary or slot-routing defect.

## Decision

Retire the complete validator-withdrawal action family represented by these contracts. Do not change the 16 ETH boundary, rolling window, q90 event, source delay, target, invalidation, cost, risk or leverage after observing the result. A more precise full-exit label would still need a materially different predeclared mechanism rather than an adjacent threshold rescue.

Official 2024–2026 remains unopened. The cumulative ranking and live permissions do not change.

## Reproduction

- Workflow `30517717123`.
- Split-source artifact `8749615475`, ZIP SHA-256 `001a60aedf845175164fbd14377bc350d698893b742d9fc09b7e51c2f1c01c54`.
- Economic artifact `8749623962`, ZIP SHA-256 `e3a68b9f14c3de4747b0c503c8960fc058065b5828744ba89b225cf455db63e0`.
- Full artifact `RESULT.json` SHA-256 `6f860f30f90523bbf14fd4c2279ca1b46d29a7c9f5ee24c85e1908bf0e0779be`.
- Canonical Bybit export ZIP SHA-256 `950ad2ee0f5d6df729c11a15b817e30e19ead754a35385e5535233d0af8e6c02`.
