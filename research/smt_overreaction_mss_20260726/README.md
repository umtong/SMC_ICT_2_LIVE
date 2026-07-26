# Attention-conditioned intermarket SMT overreaction and MSS

Claim: `CLM-20260726-SMT-OVERREACTION-MSS-001`  
Branch: `agent/r11-smt-overreaction-mss-001`

## SMC/ICT explanation

The setup is an intermarket SMT overextension, not an immediate statistical fade.

1. **BTC displacement establishes delivery direction.** A completed 1/2/5-second BTC move must be abnormal, accompanied by aligned BTC aggressive flow and abnormal BTC activity.
2. **SOL is the high-attention market.** Its prior 30-minute trade-count share versus BTC must be at least one and its prior 15-minute realized-volatility ratio must be at least 1.5.
3. **SOL overdelivers relative to BTC.** Prior-only beta maps the BTC displacement into a causal SOL fair move. SOL must move at least 1.25 times that amount with aligned SOL aggressive flow, leaving a 12/18/24-bp excess residual.
4. **No immediate countertrend entry.** The system waits for the excess residual to compress by at least 25%, opposite SOL aggressive flow to appear, and a completed break of the prior 1- or 3-second SOL micro pivot. This is the quantitative MSS/CISD.
5. **Entry after confirmation.** The trade is opposite the original BTC/SOL displacement and enters only at the first actual SOL trade at least 100 or 300 ms after the completed MSS.
6. **Invalidation.** The stop is outside the most adverse SOL extreme observed through the MSS decision, plus 1 bp.
7. **Objectives.** Either the current beta-implied fair value or a 1.5R structural objective. There is no elapsed-time forced exit.
8. **Adverse execution.** For any triggered stop or target, the closing fill uses the adverse of the trigger trade and the first post-latency trade. A favorable latency rebound cannot rescue a stop. A source-boundary position receives the full stop.

In discretionary language: BTC delivers displacement, SOL forms an attention-driven SMT overextension, the residual begins to mean-revert, order flow changes hands, SOL prints an MSS, and the trade targets fair value or the next internal liquidity objective.

## Frozen fatal PnL screen

- signal leader: Bybit `BTCUSDT` USDT-linear perpetual trades;
- executed target: Bybit `SOLUSDT` USDT-linear perpetual trades;
- one global slot;
- untouched pre-2024 dates: 2023-12-25, 2023-12-27, 2023-12-29, 2023-12-31;
- completed 100-ms state and prior-only beta, volatility and attention features;
- 288 immutable policies;
- 100/300-ms entry and exit latency;
- actual first post-latency trade execution;
- state-derived stop and fair-value/1.5R target;
- 12/18/24-bp additional round-trip cost replay;
- 2-bp adverse funding reserve per crossed funding boundary;
- 0.5% planned NAV risk per trade;
- largest 10% positive 12-bp event keys removed before global rerouting;
- 2024-2026 sealed;
- no credentials or orders.

The four prior December opportunity dates were used only for frequency and breadth selection. They produced no strategy PnL and are excluded from this screen. The execution dates above were fixed before their outcomes were read.

## Economic gate

A survivor must satisfy all of the following at both allowed latencies where applicable:

- at least 20 trades at 18 bp;
- positive mean and median trade at 24 bp;
- positive 12-bp account return after counterfactual top-10% event removal and rerouting;
- at least three positive dates at 18 bp;
- top-five positive-PnL share at most 40%;
- unresolved fraction at most 10%;
- 18-bp maximum drawdown below 20%.

This four-day fatal screen can reject the payoff but is not cumulative-rank eligible. A survivor must be expanded without changing the rule across broader pre-2024 dates with exact BBO/depth, funding and capacity before official 2024 can open.

## Validation

- scientific implementation SHA-256: `2efcf2fb17fe76462b67560c8b07416462b9e2f6e2cb851d1c64cdf0016775aa`;
- per-part, Base64, GZIP and raw-source verification;
- Python compilation: PASS;
- six local causal/execution tests: PASS;
- candidate count: 288;
- prefix-invariant MSS state;
- post-decision entry;
- stop-first and adverse rebound handling;
- terminal full-stop accounting;
- one-global-slot arbitration;
- counterfactual winner exclusion.
