# VISTA-D 구현 계약 커버리지

> 이 문서는 백테스트 성과가 아니라 숙련된 트레이더의 판단 질문과 코드 상태전이의 일치 여부를 검증한다.

- 핵심 조항: **26/26 통과**
- 장기평가 전 구현 게이트: **PASS**

| ID | 인간 트레이더의 질문 | 경제적 역할 | 코드 위치 | 상태 | 증거 |
|---|---|---|---|---|---|
| C01 | Which already-known prices can contain forced orders? | Causal multi-timeframe liquidity candidates, not hindsight pivots. | `liquidity.PivotDetector/period_nodes` | PASS (CORE) | Three-bar causal pivots and completed period levels. |
| C02 | Has the market actually done two-sided business between the boundaries? | Promote a candidate pair only after a completed rotation and one causal information quantum. | `liquidity.AuctionCandidate` | PASS (CORE) | Active auction is market-proven; internal pivots cannot silently replace it. |
| C03 | Was one live auction boundary genuinely consumed? | Start observation, not an automatic trade direction. | `liquidity.process_market_bar` | PASS (CORE) | Simultaneous two-sided consumption remains ambiguous. |
| C04 | Are several same-direction sweeps one inventory episode? | Do not duplicate one transfer across nested timeframes. | `scenario.InventoryEpisode.merge_consumption` | PASS (CORE) | Same opposite boundary and direction merge; value observation restarts at outermost consumption. |
| C05 | Did completed market business accept OLD value, NEW value, or neither? | Separate reversal, continuation, and unresolved repricing. | `information.InformationBarBuilder/value_side` | PASS (CORE) | Crossing minutes remain TRANSITION; close must agree with dominant completed business. |
| C06 | Did accepted value remain directional or become a new two-sided auction? | Live hypotheses can switch once; a complete return after both sides were accepted ends the original event. | `scenario._set_accepted/on_market_bar` | PASS (CORE) | Value is a live hypothesis, not a permanent label. |
| C07 | Who is newly taking risk and sponsoring price after the event? | Fresh OI plus completed price discovery; signed flow strengthens evidence when truly observed. | `sponsorship.SponsorshipAccumulator` | PASS (CORE) | Price movement alone cannot create sponsorship. |
| C08 | Is the original sponsor still evidenced now? | Historical sponsorship cannot be reused after fresh inventory is causally exhausted. | `scenario._maintain_live_sponsor` | PASS (CORE) | Exhaustion returns to WAIT_SPONSOR without an elapsed-time rule. |
| C09 | Did the counter-auction create genuine opposing sponsorship? | Distinguish a pullback from a competing inventory transfer. | `sponsorship.OpposingSponsorshipTracker` | PASS (CORE) | Each sponsorship contest is retained as immutable causal evidence. |
| C10 | Did the counter-auction actually fail? | MSS/CSD role: body reclaim of the counter origin plus resumed sponsored price discovery. | `scenario._defense_confirmed` | PASS (CORE) | A wick or last opposite-colour candle alone cannot create a defense. |
| C11 | What is the economically meaningful order origin? | OB role: the open of the completed counter-auction that was actually defeated. | `scenario._begin_counter/_emit_setup` | PASS (CORE) | No automatic last-opposite-candle OB. |
| C12 | Is an FVG required or fabricated? | FVG is optional evidence of one-sided delivery, not a mandatory gate or substitute body. | `scenario sponsorship/defense sequence` | PASS (OPTIONAL_SENSOR) | Core logic uses observed delivery and defense; an actual FVG can later be recorded as optional evidence without changing the contract. |
| C13 | Where is this exact scenario wrong? | Reversal invalidates beyond the rejected event extreme; continuation invalidates back inside the consumed separator. | `scenario._emit_setup` | PASS (CORE) | Stop geometry comes from the same hypothesis as entry. |
| C14 | What completes the scenario naturally? | Reversal rotates to the opposite boundary of the same reaccepted auction; continuation seeks the next live qualified pool. | `scenario._target` | PASS (CORE) | No fixed-R target or post-hoc extension. |
| C15 | What known liquidity lies on the delivery path? | Preserve internal path evidence without turning it into arbitrary extra exits. | `liquidity.qualified_pools_between/ScenarioEvidence` | PASS (CORE) | Path evidence is available for semantic audit/future state estimation. |
| C16 | When is the resting order actually live and fillable? | 500 ms activation, first retest, clear one-tick trade-through; touch/ambiguous order stays unfilled. | `execution.WorkingOrderState` | PASS (CORE) | Simple period-independent historical fill contract. |
| C17 | Does quantity preserve the fixed normal-stop budget? | NAV x 3% including entry fee, stop fee, and fixed adverse exit allowance. | `execution.evaluate_order_plan_from_reference` | PASS (CORE) | ML/score cannot change risk. |
| C18 | Can the declared objective increase NAV after unavoidable costs? | Refuse an internally coherent scenario whose own destination cannot cover its execution costs. | `execution.evaluate_order_plan_from_reference` | PASS (CORE) | Economic executability, not a fixed minimum-R filter. |
| C19 | Does the live premise still exist while the order/position is active? | Cancel/exit only after all supporting hypotheses accept opposite value, defend opposite sponsorship, or re-auction their boundary. | `execution.ScenarioPremiseState` | PASS (CORE) | Same premise lifecycle before and after fill. |
| C20 | What are the only strategy outcomes? | Full natural objective, full invalidation, or no fill; no partial/reanchor/trailing policy. | `domain.Outcome/execution.PositionState` | PASS (CORE) | Observed outcomes: ['STOP_LOSS', 'TAKE_PROFIT', 'UNFILLED']. |
| C21 | How is the single global slot allocated? | One working order or one position; simultaneous candidates prefer direct evidence then lower unavoidable burden. | `online.GlobalAccountState.submit_candidates` | PASS (CORE) | No historical PnL ranking in the runtime. |
| C22 | Can a third party reconstruct every selected scenario? | Immutable evidence records event, auction, value, sponsor, competition, defense, invalidation, path, and destination. | `domain.ScenarioEvidence` | PASS (CORE) | Independent semantic audits: Jan 26/26, Mar 29/29. |
| C23 | Can a third party reconstruct actual order and account chronology? | Independent price, cost, and NAV recomputation must match the online engine. | `independent_trade_lifecycle_audit` | PASS (CORE) | Trade audits Jan 26/26, Mar 29/29; account audits pass. |
| C24 | Can future data alter prior decisions? | The exact event histories, orders, outcomes, and NAV prefix are invariant when future months are appended. | `prefix_2023_01_vs_01_to_03` | PASS (CORE) | All prefix surfaces including per-episode state histories pass. |
| C25 | Is the runtime structurally isolated from future outcomes and period fitting? | Scenario modules cannot access realized returns, future labels, or evaluation-period branches. | `runtime architecture` | PASS (CORE) | No future outcome selector or evaluation-period literal in runtime modules. |
| C26 | Does the baseline cover both legitimate competing directions and all execution outcomes? | The implementation must exercise reversal, continuation, TP, SL, and unfilled paths before long evaluation. | `Jan+Mar semantic replays` | PASS (CORE) | Branches ['CONTINUATION', 'REVERSAL']; outcomes ['STOP_LOSS', 'TAKE_PROFIT', 'UNFILLED']. |
| C27 | Which SMC concepts are observations rather than rigid gates? | Liquidity sweep starts inquiry; MSS/CSD confirms transfer; OB is defended origin; FVG/BPR/SMT may add evidence only when genuinely observed. | `implementation contract` | PASS (CORE) | Economic roles are explicit; optional sensors are neither prohibited nor fabricated. |
| C28 | Where does ML belong? | After baseline fidelity/economic evidence, estimate uncertainty and global action value without generating geometry or risk multipliers. | `deferred ML boundary` | PASS (DEFERRED_AFTER_BASELINE) | ML is deliberately outside the semantic baseline until the core mechanism is measured. |

## SMC/ICT 개념의 현재 역할

- **Liquidity sweep:** 활성 경매 경계의 실제 소비이며 판단 시작 사건이다.
- **MSS/CSD:** counter-auction 원점 재장악과 기존 sponsor 가격발견의 완료 몸통 재개다.
- **OB:** 아무 반대색 봉이 아니라 실제 실패한 counter-auction의 시작가격이다.
- **FVG/BPR:** 실제로 관측되면 가격전달 효율·재조정 증거가 될 수 있으나, 없을 때 대체 도형을 만들지 않는다.
- **SMT/교차시장:** 향후 불확실성 모델의 확인·반박 센서이며 현재 baseline의 필수 게이트가 아니다.

## 현재 원인 판정

현재 VISTA-D의 핵심 시나리오 논리는 유동성 소비, 가치 수용, 신규 위험 후원, 경쟁 후원, counter-auction 실패, 방어가격, 무효화와 자연 목적지를 하나의 인과적 생애주기로 연결한다. 두 개발 월과 기간 절단 감사에서 확인된 부족점은 핵심 논리의 공백보다 과거 구현·증거·직렬화의 불일치였고, 현재 핵심 조항은 모두 독립 재현된다.

ML과 선택적 FVG/BPR/SMT 센서는 baseline 메커니즘의 경제성을 가리기 전에 추가하지 않는다. 이는 금지가 아니라 역할과 한계가 증명된 뒤 결합하기 위한 계층 분리다.
