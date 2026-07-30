            continue

        loss_budget = plan.loss_budget_per_unit
        qty = nav * risk_fraction / loss_budget
        turnover_entry = _turnover_at(symbol_data[plan.candidate.symbol], plan.entry_time_ms)
        for _ in range(3):
            notional = abs(qty * plan.entry_price)
            impact_entry_rate = _impact_rate(notional, turnover_entry, execution)
            stop_notional = abs(qty * plan.candidate.stop_price)
            impact_stop_rate = _impact_rate(stop_notional, turnover_entry, execution)
            impact_loss_per_unit = impact_entry_rate * abs(plan.entry_price) + impact_stop_rate * abs(plan.candidate.stop_price)
            qty = nav * risk_fraction / max(loss_budget + impact_loss_per_unit, 1e-12)
        notional = abs(qty * plan.entry_price)
        leverage, liquidation = _choose_leverage(
            notional=notional,
            nav=nav,
            entry_price=plan.entry_price,
            stop_price=plan.candidate.stop_price,
            direction=plan.candidate.direction,
            config=execution,
        )
        if leverage is None or liquidation is None:
            rejected_for_margin += 1
            record["order_status"] = "rejected_margin_or_liquidation"
            selected.append(record)
            continue

        entry_fee = qty * float(plan.entry_fee_rate or 0.0) * abs(plan.entry_price)
        entry_impact_rate = _impact_rate(notional, turnover_entry, execution)
        entry_impact = notional * entry_impact_rate
        cash_after_entry = nav - entry_fee - entry_impact
        realized_nav: float | None = None
        exit_fee = exit_impact = price_pnl = 0.0
        funding_cash = 0.0
        if plan.resolved and plan.exit_price is not None and plan.exit_time_ms is not None and plan.exit_time_ms < end_exclusive_ms:
            liquidated = (
                plan.exit_reason == "stop"
                and (
                    (plan.candidate.direction == 1 and plan.exit_price <= liquidation)
                    or (plan.candidate.direction == -1 and plan.exit_price >= liquidation)
                )
            )
            effective_exit_price = plan.exit_price
            exit_notional = abs(qty * effective_exit_price)
            turnover_exit = _turnover_at(symbol_data[plan.candidate.symbol], plan.exit_time_ms)
            exit_impact_rate = _impact_rate(exit_notional, turnover_exit, execution) if plan.exit_reason == "stop" else 0.0
            exit_impact = exit_notional * exit_impact_rate
            exit_fee = qty * float(plan.exit_fee_rate or 0.0) * abs(effective_exit_price)
            price_pnl = qty * plan.candidate.direction * (effective_exit_price - plan.entry_price)
            funding_cash = qty * plan.funding_cash_per_unit
            realized_nav = cash_after_entry + price_pnl + funding_cash - exit_fee - exit_impact
            if liquidated:
                # The project treats any forced liquidation as a fatal account-path
                # failure. We therefore do not grant isolated-margin recovery credit.
                liquidation_count += 1
                realized_nav = 0.0
            nav = max(0.0, realized_nav)
            gross_pnl_total += price_pnl
            fees_execution_total += entry_fee + entry_impact + exit_fee + exit_impact
            funding_total += funding_cash
            if nav > record["nav_before"]:
                wins += 1
            else:
                losses += 1
        else:
            # Account remains in the open position at the evaluation boundary.
            funding_cash = qty * _funding_cash_until(plan, symbol_data[plan.candidate.symbol], end_exclusive_ms - 1)
            mark = _minute_value_at(symbol_data[plan.candidate.symbol], end_exclusive_ms - 1)
            if np.isfinite(mark):
                estimated_exit = _adverse_price(mark, plan.candidate.direction, execution.mark_close_slippage_bps, is_entry=False)
                exit_fee = qty * execution.taker_fee_rate * abs(estimated_exit)
                exit_impact = abs(qty * estimated_exit) * _impact_rate(abs(qty * estimated_exit), _turnover_at(symbol_data[plan.candidate.symbol], end_exclusive_ms - 1), execution)
                price_pnl = qty * plan.candidate.direction * (estimated_exit - plan.entry_price)
                nav = cash_after_entry + price_pnl + funding_cash - exit_fee - exit_impact
                gross_pnl_total += price_pnl
                fees_execution_total += entry_fee + entry_impact + exit_fee + exit_impact
                funding_total += funding_cash
            unresolved += 1

        record.update(
            {
                "executed": True,
                "entry_time_ms": plan.entry_time_ms,
                "entry_price": plan.entry_price,
                "exit_time_ms": plan.exit_time_ms,
                "exit_price": plan.exit_price,
                "exit_reason": plan.exit_reason,
                "quantity": qty,
                "notional": notional,
                "leverage": leverage,
                "liquidation_price": liquidation,
                "entry_fee": entry_fee,
                "entry_impact": entry_impact,
                "exit_fee": exit_fee,
                "exit_impact": exit_impact,
                "funding_pnl": funding_cash,
                "price_pnl": price_pnl,
                "cash_after_entry": cash_after_entry,
                "nav_after": nav,
                "liquidated": bool(plan.resolved and plan.exit_reason == "stop" and plan.exit_price is not None and ((plan.candidate.direction == 1 and plan.exit_price <= liquidation) or (plan.candidate.direction == -1 and plan.exit_price >= liquidation))),
            }
        )
        selected.append(record)

    trades = pd.DataFrame(selected)
    days = pd.date_range(ms_to_timestamp(start_ms).floor("D"), ms_to_timestamp(end_exclusive_ms), freq="D", inclusive="left")
    nav_rows: list[dict[str, Any]] = []
    realized_cash = initial_nav
    executed_records = [row for row in selected if row.get("executed")]
    executed_records.sort(key=lambda row: int(row["entry_time_ms"]))
