        entry_time,
        entry_index,
        entry_price,
        entry_fee_rate,
        exit_time,
        exit_index,
        exit_price,
        exit_fee_rate,
        exit_reason,
        True,
        funding_cash,
        float(net_cash),
        loss_budget_per_unit,
        float(net_cash / loss_budget_per_unit),
    )


def build_trade_plans(
    candidates: Sequence[Candidate],
    symbol_data: Mapping[str, SymbolData],
    execution: FeeExecutionConfig,
    *,
    end_exclusive_ms: int,
) -> list[TradePlan]:
    plans: list[TradePlan] = []
    for candidate in candidates:
        data = symbol_data.get(candidate.symbol)
        if data is None:
            raise KeyError(f"missing SymbolData for {candidate.symbol}")
        plans.append(simulate_candidate_plan(candidate, data, execution, end_exclusive_ms=end_exclusive_ms))
    return plans


def candidates_frame(candidates: Sequence[Candidate]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for candidate in candidates:
        rows.append(
            {
                "candidate_id": candidate.candidate_id,
                "setup_id": candidate.setup_id,
                "signal_available_ms": candidate.signal_available_ms,
                "activation_ms": candidate.activation_ms,
                **dict(candidate.feature_values),
            }
        )
    return pd.DataFrame(rows)


def plans_frame(plans: Sequence[TradePlan]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for plan in plans:
        candidate = plan.candidate
        rows.append(
            {
                "candidate_id": candidate.candidate_id,
                "setup_id": candidate.setup_id,
                "symbol": candidate.symbol,
                "direction": candidate.direction,
                "activation_ms": candidate.activation_ms,
                "signal_available_ms": candidate.signal_available_ms,
                "entry_mode": candidate.entry_mode,
                "liquidity_source": candidate.liquidity_source,
                "target_source": candidate.target_source,
                "order_terminal_ms": plan.order_terminal_ms,
                "order_status": plan.order_status,
                "entry_time_ms": plan.entry_time_ms,
                "exit_time_ms": plan.exit_time_ms,
                "exit_reason": plan.exit_reason,
                "resolved": plan.resolved,
                "executed": plan.executed,
                "net_r": plan.net_r,
                "net_cash_per_unit": plan.net_cash_per_unit,
                "loss_budget_per_unit": plan.loss_budget_per_unit,
                **dict(candidate.feature_values),
            }
        )
    return pd.DataFrame(rows)


def feature_columns(frame: pd.DataFrame) -> list[str]:
    excluded = {
        "candidate_id",
        "setup_id",
        "signal_available_ms",
        "activation_ms",
        "order_terminal_ms",
        "order_status",
        "entry_time_ms",
        "exit_time_ms",
        "exit_reason",
        "resolved",
        "executed",
        "net_r",
        "net_cash_per_unit",
        "loss_budget_per_unit",
        "score",
    }
    return [column for column in frame.columns if column not in excluded]


def fit_ranker(
    plan_rows: pd.DataFrame,
    *,
    cutoff_ms: int,
    model_config: ModelConfig,
) -> FittedRanker:
    eligible = plan_rows[
        plan_rows["executed"].fillna(False).astype(bool)
        & plan_rows["resolved"].fillna(False).astype(bool)
        & plan_rows["net_r"].notna()
        & (plan_rows["signal_available_ms"] < cutoff_ms)
        & (plan_rows["exit_time_ms"].fillna(cutoff_ms + 1) < cutoff_ms)
    ].copy()
    if len(eligible) < max(80, model_config.min_samples_leaf * 3):
        raise ValueError(f"insufficient resolved causal training candidates: {len(eligible)}")
    features = eligible[feature_columns(eligible)]
    encoder = FeatureEncoder()
    x = encoder.fit_transform(features)
    y = eligible["net_r"].clip(-3.0, 8.0).to_numpy(float)
    # Recent observations receive more weight without changing feature values.
    age_days = (cutoff_ms - eligible["signal_available_ms"].to_numpy(np.int64)) / 86_400_000.0
    sample_weight = np.exp(-np.maximum(age_days, 0.0) / 540.0)
    model = HistGradientBoostingRegressor(
        learning_rate=model_config.learning_rate,
        max_iter=model_config.max_iter,
        max_leaf_nodes=model_config.max_leaf_nodes,
        min_samples_leaf=model_config.min_samples_leaf,
        l2_regularization=model_config.l2_regularization,
        max_bins=model_config.max_bins,
        random_state=model_config.random_state,
        loss="squared_error",
    )
    model.fit(x, y, sample_weight=sample_weight)
    return FittedRanker(encoder=encoder, model=model, training_rows=len(eligible), training_end_ms=cutoff_ms)


def score_rows(ranker: FittedRanker, rows: pd.DataFrame) -> pd.Series:
    features = rows[feature_columns(rows)]
    return pd.Series(ranker.predict(features), index=rows.index, name="score")


def score_walk_forward(
    plan_rows: pd.DataFrame,
    *,
    evaluation_start_ms: int,
    evaluation_end_exclusive_ms: int,
    model_config: ModelConfig,
    initial_training_cutoff_ms: int,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Causally score an interval with optional fixed-schedule monthly refits."""
    scored = plan_rows.copy()
    scored["score"] = np.nan
    diagnostics: dict[str, Any] = {"refits": []}
    initial_ranker = fit_ranker(scored, cutoff_ms=initial_training_cutoff_ms, model_config=model_config)
    if not model_config.monthly_refit:
        mask = (scored["activation_ms"] >= evaluation_start_ms) & (scored["activation_ms"] < evaluation_end_exclusive_ms)
        scored.loc[mask, "score"] = score_rows(initial_ranker, scored.loc[mask]).to_numpy()
        diagnostics["refits"].append({"effective_ms": evaluation_start_ms, "training_cutoff_ms": initial_training_cutoff_ms, "training_rows": initial_ranker.training_rows})
        return scored, diagnostics

    month_starts = pd.date_range(ms_to_timestamp(evaluation_start_ms).floor("D"), ms_to_timestamp(evaluation_end_exclusive_ms), freq="MS", inclusive="left")
    previous_ranker = initial_ranker
    for month_start in month_starts:
        month_start_ms = int(month_start.timestamp() * 1000)
        month_end = min(month_start + pd.offsets.MonthBegin(1), ms_to_timestamp(evaluation_end_exclusive_ms))
        month_end_ms = int(month_end.timestamp() * 1000)
        activation_ms = month_start_ms + model_config.refit_activation_delay_minutes * MS_MINUTE
        early_mask = (
            (scored["activation_ms"] >= max(month_start_ms, evaluation_start_ms))
            & (scored["activation_ms"] < min(activation_ms, month_end_ms, evaluation_end_exclusive_ms))
        )
        if early_mask.any():
            scored.loc[early_mask, "score"] = score_rows(previous_ranker, scored.loc[early_mask]).to_numpy()
        try:
            ranker = fit_ranker(scored, cutoff_ms=month_start_ms, model_config=model_config)
        except ValueError:
            ranker = previous_ranker
        regular_mask = (
            (scored["activation_ms"] >= max(activation_ms, evaluation_start_ms))
            & (scored["activation_ms"] < min(month_end_ms, evaluation_end_exclusive_ms))
        )
        if regular_mask.any():
            scored.loc[regular_mask, "score"] = score_rows(ranker, scored.loc[regular_mask]).to_numpy()
        diagnostics["refits"].append(
            {
                "month_start_ms": month_start_ms,
                "effective_ms": activation_ms,
                "training_cutoff_ms": ranker.training_end_ms,
                "training_rows": ranker.training_rows,
            }
        )
        previous_ranker = ranker
    return scored, diagnostics


def _impact_rate(notional: float, turnover: float, config: FeeExecutionConfig) -> float:
    if notional <= 0:
        return 0.0
    if not np.isfinite(turnover) or turnover <= 0:
        return config.max_impact_bps / 10_000.0
    participation = max(notional / turnover, 0.0)
    bps = config.impact_coefficient_bps * math.sqrt(participation)
    return min(config.max_impact_bps, bps) / 10_000.0


def _choose_leverage(
    *,
    notional: float,
    nav: float,
    entry_price: float,
    stop_price: float,
    direction: int,
    config: FeeExecutionConfig,
) -> tuple[float | None, float | None]:
    if nav <= 0 or notional <= 0:
        return None, None
    required = notional / (nav * config.margin_utilization_limit)
    for leverage in config.leverage_grid:
        if leverage + 1e-12 < required:
            continue
