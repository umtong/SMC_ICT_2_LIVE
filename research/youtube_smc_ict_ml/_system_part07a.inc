    for day_start in days:
        boundary_ms = int((day_start + pd.Timedelta(days=1)).timestamp() * 1000)
        boundary_ms = min(boundary_ms, end_exclusive_ms)
        equity = realized_cash
        for record in executed_records:
            entry_time = int(record["entry_time_ms"])
            exit_time = record.get("exit_time_ms")
            if exit_time is not None and int(exit_time) < boundary_ms:
                realized_cash = float(record["nav_after"])
                equity = realized_cash
                continue
            if entry_time < boundary_ms and (exit_time is None or int(exit_time) >= boundary_ms):
                symbol = str(record["symbol"])
                direction = int(record["direction"])
                qty = float(record["quantity"])
                entry_price = float(record["entry_price"])
                mark = _minute_value_at(symbol_data[symbol], boundary_ms - 1)
                if np.isfinite(mark):
                    close_price = _adverse_price(mark, direction, execution.mark_close_slippage_bps, is_entry=False)
                    mark_fee = qty * execution.taker_fee_rate * abs(close_price)
                    mark_impact = abs(qty * close_price) * _impact_rate(abs(qty * close_price), _turnover_at(symbol_data[symbol], boundary_ms - 1), execution)
                    plan = plans_by_id[str(record["candidate_id"])]
                    funding_to_boundary = qty * _funding_cash_until(plan, symbol_data[symbol], boundary_ms - 1)
                    equity = float(record["cash_after_entry"]) + qty * direction * (close_price - entry_price) + funding_to_boundary - mark_fee - mark_impact
                break
        nav_rows.append({"date": day_start, "nav": equity})
    daily_nav = pd.DataFrame(nav_rows)
    if daily_nav.empty:
        terminal_nav = float(nav)
        daily_geometric = math.nan
        max_drawdown = 0.0
        min_nav = initial_nav
    else:
        terminal_nav = float(daily_nav.iloc[-1]["nav"])
        count_days = len(daily_nav)
        daily_geometric = math.exp(math.log(terminal_nav / initial_nav) / count_days) - 1.0 if terminal_nav > 0 else -1.0
        running_max = daily_nav["nav"].cummax()
        drawdown = 1.0 - daily_nav["nav"] / running_max
        max_drawdown = float(drawdown.max())
        min_nav = float(daily_nav["nav"].min())
    executed_count = int(sum(bool(row.get("executed")) for row in selected))
    return BacktestResult(
        start_ms=start_ms,
        end_exclusive_ms=end_exclusive_ms,
        initial_nav=initial_nav,
        terminal_nav=terminal_nav,
        daily_geometric_growth=daily_geometric,
        max_drawdown=max_drawdown,
        min_nav=min_nav,
        selected_orders=len(selected),
        executed_trades=executed_count,
        wins=wins,
        losses=losses,
        canceled_orders=canceled,
        unresolved_orders=unresolved,
        gross_pnl=gross_pnl_total,
        fees_and_execution_cost=fees_execution_total,
        funding_pnl=funding_total,
        liquidation_count=liquidation_count,
        rejected_for_margin=rejected_for_margin,
        risk_fraction=risk_fraction,
        score_threshold=score_threshold,
        score_quantile=score_quantile,
        daily_nav=daily_nav,
        trades=trades,
    )


def choose_calibrated_policy(
    scored_rows: pd.DataFrame,
    plans_by_id: Mapping[str, TradePlan],
    symbol_data: Mapping[str, SymbolData],
    execution: FeeExecutionConfig,
    *,
    calibration_start_ms: int,
    calibration_end_exclusive_ms: int,
    quantile_grid: Sequence[float] = (0.50, 0.60, 0.70, 0.78, 0.84, 0.89, 0.93, 0.96),
    risk_grid: Sequence[float] = (0.005, 0.01, 0.02, 0.04, 0.08, 0.12, 0.16, 0.24),
    initial_nav: float = 10_000.0,
) -> tuple[dict[str, Any], pd.DataFrame]:
    calibration = scored_rows[
        (scored_rows["activation_ms"] >= calibration_start_ms)
        & (scored_rows["activation_ms"] < calibration_end_exclusive_ms)
        & scored_rows["score"].notna()
    ]
    if calibration.empty:
        raise ValueError("calibration interval has no scored candidates")
    records: list[dict[str, Any]] = []
    # First establish that candidate ranking has positive cost-net alpha at a
    # modest risk. Only then search the larger risk grid.
    preliminary: list[tuple[float, float, BacktestResult]] = []
    for quantile in quantile_grid:
        threshold = float(calibration["score"].quantile(quantile))
        result = run_single_slot_backtest(
            calibration,
            plans_by_id,
            symbol_data,
            execution,
            start_ms=calibration_start_ms,
            end_exclusive_ms=calibration_end_exclusive_ms,
            risk_fraction=0.01,
            score_threshold=threshold,
            score_quantile=quantile,
            initial_nav=initial_nav,
        )
        preliminary.append((quantile, threshold, result))
