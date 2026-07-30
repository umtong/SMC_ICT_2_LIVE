# Causal high-/low-resistance liquidity control-transfer Core — final report

Result ID: `RES-20260730-CAUSAL-LIQUIDITY-RESISTANCE-TRANSFER-001`

Verdict: `RETIRED_PROGRAMIZATION_CORRECTED_2022_ECONOMIC_FAILURE`

## Question

Can prior, causal evidence that an external level genuinely resisted price distinguish high-resistance liquidity from ordinary structural waypoints, and can the later role transition of that level produce repeatable ACCEPT continuation or REJECT rotation after realistic costs?

The symbols were testbeds. The thesis was intended to generalize to liquid auctions: repeated defense implies outstanding inventory; a later intrusion either transfers control and turns the level into low-resistance liquidity, or fails and traps breakout inventory.

## Final programization

The authority used:

- previous completed day/week highs/lows and causal width-two 4h pivots;
- two distinct completed 15m defenses, each followed by at least 0.50 ATR favorable excursion;
- wick intrusion separated from completed-body consumption;
- mutually exclusive ACCEPT and REJECT state machines;
- one first-repricing limit at the defended level with one-tick trade-through;
- pending-order global-slot occupancy and structural cancellation;
- nearest still-unconsumed external target, without skipping a closer high-resistance obstacle;
- full-path structural stop for ACCEPT and REJECT;
- fixed 500ms activation, actual funding, adverse ambiguity, 0.5% NAV planned loss including costs, and a 3x notional cap;
- no elapsed-time or scheduled position close.

Two complete fresh executions produced 20 byte-identical scientific output files.

## Programization corrections before the final verdict

### 1. Wick intrusion was incorrectly treated as full consumption

The preliminary generator retired a level on the first strict one-minute trade beyond it, leaving almost no repeated-defense states. That contradicted the tested logic: a defended level can be wicked or swept and still reject completed value.

The final implementation distinguishes:

- intrusion: strict one-minute trade beyond the level;
- defense: completed 15m close on the old side plus subsequent favorable excursion;
- full consumption: completed 15m body acceptance beyond the level, or completion of the first high-resistance control-transfer event.

All preliminary outputs were invalidated and rebuilt.

### 2. ACCEPT invalidation used only the last retest bar

The preliminary ACCEPT stop used only the final five-minute retest-confirmation bar. Median stops were approximately 11–13bp, below the 24bp cost contract, and many fills stopped in the same minute.

The final stop uses the full one-minute path from the first outside 15m acceptance bar through the retest decision. All second-run outputs were invalidated and rebuilt.

## State and event coverage

| Item | BTCUSDT | ETHUSDT | Total |
|---|---:|---:|---:|
| Causal external levels | 2,908 | 2,604 | 5,512 |
| Levels reaching high-resistance state | 381 | 334 | 715 |
| Final candidates | 93 | 93 | 186 |

Candidate composition:

- 110 ACCEPT and 76 REJECT;
- 81 candidates in 2021 and 105 in 2022.

The failure was not caused by an empty event generator.

## 2022 forward economics

| Cost | Trades | NAV multiple | PF | Median trade | Positive trades | Top-five positive-PnL share |
|---:|---:|---:|---:|---:|---:|---:|
| 0bp diagnostic | 71 | 1.10389x | 1.516 | -0.2419% | 11 | 98.32% |
| 12bp | 71 | 0.95510x | 0.805 | -0.4409% | 7 | 98.67% |
| 18bp | 71 | 0.91964x | 0.658 | -0.4756% | 6 | 98.69% |
| 24bp | 71 | 0.89516x | 0.558 | -0.4811% | 6 | 98.63% |

At 24bp:

- MDD: 12.35%;
- both half-years were negative;
- exits: 38 stops, 27 structural state losses, 6 targets;
- ACCEPT: 40 trades, approximately -957.86 USDT, four positive trades;
- REJECT: 31 trades, approximately -90.53 USDT, two positive trades.

Exact deletion of the five largest positive event keys before complete one-slot rerouting produced:

- 66 trades;
- 0.77957x NAV;
- PF 0.0071;
- one positive trade.

## 2021 diagnostic

The 2021 24bp path made 57 trades and ended 0.90458x with PF 0.5126. Its three positive trades supplied effectively all positive PnL. Winner deletion and full rerouting ended 0.81371x.

The sign was therefore not a one-year 2022 anomaly.

## Economic interpretation

Repeated defense is more meaningful than an arbitrary pivot, but it still does not directly reveal:

- the amount and ownership of outstanding defended inventory;
- whether the later intrusion is the last forced order or newly sponsored price discovery;
- whether passive liquidity is replenishing or withdrawing;
- whether the path to the next target is genuinely low resistance.

The zero-cost 2022 result showed a small gross relation, almost entirely supplied by a few events. Realistic 12bp already removed it. This is neither a broad Core nor a hidden ML opportunity: the deterministic action surface has no cost headroom and the ordinary median trade is negative.

The exact family is retired. It must not be rescued with extra SMC nouns, narrower defense geometry, symbol/side exceptions, another target/stop, lower costs, ML selection, risk, or leverage.

## Reproducibility

- Implementation SHA-256: `abf16d846f399a04d4851224fa6175cc8e37904ca45df09ccc6c9ff2fd71ae96`
- Result SHA-256: `80e60f18436b0c00dc601d0a0b7c385899deb813c18cf36717f6d0bde305cc51`
- Deterministic output hash manifest: `DETERMINISM_SHA256.json`
- Two fresh runs: `output5` and `output6`, all 20 common files byte-identical.

Calendar 2023, ML, risk/leverage work, and official 2024–2026 remained sealed. No credentials or orders were used.
