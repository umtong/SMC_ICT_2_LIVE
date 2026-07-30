    viable = [item for item in preliminary if item[2].daily_geometric_growth > 0 and item[2].terminal_nav > initial_nav]
    if not viable:
        best = max(preliminary, key=lambda item: (item[2].daily_geometric_growth, item[2].terminal_nav))
        table = pd.DataFrame([{**item[2].summary(), "phase": "preliminary"} for item in preliminary])
        return {
            "alpha_confirmed": False,
            "score_quantile": best[0],
            "score_threshold": best[1],
            "risk_fraction": 0.01,
            "calibration_summary": best[2].summary(),
        }, table

    stressed_execution = execution.stressed(1.35)
    for quantile, threshold, _ in viable:
        for risk in risk_grid:
            base = run_single_slot_backtest(
                calibration,
                plans_by_id,
                symbol_data,
                execution,
                start_ms=calibration_start_ms,
                end_exclusive_ms=calibration_end_exclusive_ms,
                risk_fraction=float(risk),
                score_threshold=threshold,
                score_quantile=quantile,
                initial_nav=initial_nav,
            )
            stress = run_single_slot_backtest(
                calibration,
                plans_by_id,
                symbol_data,
                stressed_execution,
                start_ms=calibration_start_ms,
                end_exclusive_ms=calibration_end_exclusive_ms,
                risk_fraction=float(risk),
                score_threshold=threshold,
                score_quantile=quantile,
                initial_nav=initial_nav,
            )
            robust_growth = min(base.daily_geometric_growth, stress.daily_geometric_growth)
            valid = (
                base.terminal_nav > 0
                and stress.terminal_nav > 0
                and base.liquidation_count == 0
                and stress.liquidation_count == 0
                and base.max_drawdown < 0.98
                and stress.max_drawdown < 0.98
            )
            records.append(
                {
                    "phase": "risk_search",
                    "score_quantile": quantile,
                    "score_threshold": threshold,
                    "risk_fraction": risk,
                    "base_daily_growth": base.daily_geometric_growth,
                    "stress_daily_growth": stress.daily_geometric_growth,
                    "robust_daily_growth": robust_growth,
                    "base_terminal_nav": base.terminal_nav,
                    "stress_terminal_nav": stress.terminal_nav,
                    "base_max_drawdown": base.max_drawdown,
                    "stress_max_drawdown": stress.max_drawdown,
                    "base_trades": base.executed_trades,
                    "stress_trades": stress.executed_trades,
                    "valid": valid,
                    "base_result": base,
                }
            )
    valid_records = [record for record in records if record["valid"]]
    if not valid_records:
        valid_records = records
    best_record = max(
        valid_records,
        key=lambda record: (
            record["robust_daily_growth"],
            record["base_daily_growth"],
            record["base_terminal_nav"],
        ),
    )
    best_result: BacktestResult = best_record["base_result"]
    serializable_records = []
    for record in records:
        serializable_records.append({key: value for key, value in record.items() if key != "base_result"})
    table = pd.DataFrame(serializable_records)
    return {
        "alpha_confirmed": True,
        "score_quantile": float(best_record["score_quantile"]),
        "score_threshold": float(best_record["score_threshold"]),
        "risk_fraction": float(best_record["risk_fraction"]),
        "calibration_summary": best_result.summary(),
        "stressed_daily_growth": float(best_record["stress_daily_growth"]),
    }, table


def quantile_threshold(rows: pd.DataFrame, quantile: float) -> float:
    values = rows["score"].dropna()
    if values.empty:
        return math.inf
    return float(values.quantile(quantile))


def save_backtest_result(result: BacktestResult, output: str | Path, prefix: str) -> None:
    out = Path(output)
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{prefix}_metrics.json").write_text(json.dumps(result.summary(), ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    result.daily_nav.to_csv(out / f"{prefix}_daily_nav.csv", index=False)
    result.trades.to_csv(out / f"{prefix}_trades.csv", index=False)
