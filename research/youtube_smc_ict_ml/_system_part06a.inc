        if direction == 1:
            liquidation = entry_price * (1.0 - 1.0 / leverage + config.maintenance_margin_rate)
            adverse_stop = stop_price * (1.0 - config.stop_slippage_bps / 10_000.0)
            safe = liquidation < adverse_stop
        else:
            liquidation = entry_price * (1.0 + 1.0 / leverage - config.maintenance_margin_rate)
            adverse_stop = stop_price * (1.0 + config.stop_slippage_bps / 10_000.0)
            safe = liquidation > adverse_stop
        if safe:
            return float(leverage), float(liquidation)
    return None, None


def _minute_value_at(data: SymbolData, timestamp_ms: int, column: str = "close") -> float:
    frame = data.minute
    times = frame["start_time_ms"].astype("int64").to_numpy()
    idx = int(np.searchsorted(times, timestamp_ms, side="right") - 1)
    if idx < 0:
        return math.nan
    return float(frame.iloc[idx][column])


def _turnover_at(data: SymbolData, timestamp_ms: int) -> float:
    frame = data.minute
    times = frame["start_time_ms"].astype("int64").to_numpy()
    idx = int(np.searchsorted(times, timestamp_ms, side="right") - 1)
    if idx < 0:
        return math.nan
    if "turnover" in frame.columns:
        return float(frame.iloc[idx]["turnover"])
    return float(frame.iloc[idx]["volume"] * frame.iloc[idx]["close"])


def _funding_cash_until(plan: TradePlan, data: SymbolData, end_ms: int) -> float:
    if plan.entry_time_ms is None:
        return 0.0
    funding_times, funding_rates, funding_marks = _funding_arrays(data)
    return _funding_cash_between(
        funding_times,
        funding_rates,
        funding_marks,
        start_ms=plan.entry_time_ms,
        end_ms=end_ms,
        direction=plan.candidate.direction,
    )


def run_single_slot_backtest(
    scored_rows: pd.DataFrame,
    plans_by_id: Mapping[str, TradePlan],
    symbol_data: Mapping[str, SymbolData],
    execution: FeeExecutionConfig,
    *,
    start_ms: int,
    end_exclusive_ms: int,
    risk_fraction: float,
    score_threshold: float,
    score_quantile: float | None = None,
    initial_nav: float = 10_000.0,
) -> BacktestResult:
    if risk_fraction <= 0:
        raise ValueError("risk_fraction must be positive")
    pool = scored_rows[
        (scored_rows["activation_ms"] >= start_ms)
        & (scored_rows["activation_ms"] < end_exclusive_ms)
        & scored_rows["score"].notna()
        & (scored_rows["score"] >= score_threshold)
    ].copy()
    pool = pool.sort_values(["activation_ms", "score", "candidate_id"], ascending=[True, False, True])

    selected: list[dict[str, Any]] = []
    slot_free_ms = start_ms
    nav = float(initial_nav)
    rejected_for_margin = 0
    liquidation_count = 0
    gross_pnl_total = 0.0
    fees_execution_total = 0.0
    funding_total = 0.0
    canceled = unresolved = wins = losses = 0

    for activation_ms, group in pool.groupby("activation_ms", sort=True):
        activation_ms = int(activation_ms)
        if activation_ms < slot_free_ms or nav <= 0:
            continue
        row = group.iloc[0]
        plan = plans_by_id[str(row["candidate_id"])]
        slot_free_ms = max(activation_ms, min(plan.slot_end_ms, end_exclusive_ms))
        record: dict[str, Any] = {
            "candidate_id": plan.candidate.candidate_id,
            "setup_id": plan.candidate.setup_id,
            "symbol": plan.candidate.symbol,
            "direction": plan.candidate.direction,
            "entry_mode": plan.candidate.entry_mode,
            "activation_ms": activation_ms,
            "score": float(row["score"]),
            "order_status": plan.order_status,
            "nav_before": nav,
            "slot_end_ms": slot_free_ms,
            "executed": False,
        }
        if not plan.executed:
            if plan.resolved:
                canceled += 1
            else:
                unresolved += 1
            selected.append(record)
            continue
        if plan.entry_price is None or plan.loss_budget_per_unit is None or plan.entry_time_ms is None:
            unresolved += 1
            selected.append(record)
