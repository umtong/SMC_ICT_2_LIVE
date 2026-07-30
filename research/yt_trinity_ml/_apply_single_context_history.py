from pathlib import Path

path = Path("research/yt_trinity_ml/run_causal_action_history.py")
text = path.read_text(encoding="utf-8")
old = '''    decision_pre, execution_pre, funding_pre = load_canonical_frames(
        args.data_root,
        args.repo_root,
        PRIMARY,
        PRE2024_SEGMENTS,
    )
    _, candidates_pre, diagnostics_pre = generate_causal_action_candidates_by_symbol(
        decision_pre,
        FeatureConfig(),
    )
    rows_pre = _rows_fast(
        candidates_pre,
        execution_pre,
        funding_pre,
        SELECTION_END,
        EXIT_VARIANTS,
        screen,
    )
'''
new = '''    # Build causal state once through H1, then slice prefix actions by timestamp.
    # Future rows cannot change earlier candidates, while duplicate multi-year state
    # generation and duplicate data memory are removed.
    evaluation_context_segments = (*PRE2024_SEGMENTS, "2024_H1")
    decision_context, execution_context, funding_context = load_canonical_frames(
        args.data_root,
        args.repo_root,
        PRIMARY,
        evaluation_context_segments,
    )
    _, candidates_context, diagnostics_context = generate_causal_action_candidates_by_symbol(
        decision_context,
        FeatureConfig(),
    )
    candidates_pre = [
        candidate for candidate in candidates_context
        if pd.Timestamp(candidate.timestamp) < SELECTION_END
    ]
    diagnostics_pre = {
        "context_segments": list(evaluation_context_segments),
        "full_context_candidate_count": len(candidates_context),
        "pre2024_candidate_count": len(candidates_pre),
        "by_symbol": diagnostics_context,
    }
    rows_pre = _rows_fast(
        candidates_pre,
        execution_context,
        funding_context,
        SELECTION_END,
        EXIT_VARIANTS,
        screen,
    )
'''
if old not in text:
    raise SystemExit("pre-2024 generation block mismatch")
text = text.replace(old, new, 1)
old = '''    # Rebuild the exact information state available at 2024-01-01. Loading the
    # evaluation shard alone would reset rolling indicators, prior-session liquidity
    # and still-valid SMC narrative states at the boundary. Pre-2024 rows warm the
    # causal state machine, but only actions whose activation is inside H1 may trade.
    evaluation_context_segments = (*PRE2024_SEGMENTS, "2024_H1")
    decision_context, execution_context, funding_context = load_canonical_frames(
        args.data_root,
        args.repo_root,
        PRIMARY,
        evaluation_context_segments,
    )
    _, candidates_context, diagnostics_context = generate_causal_action_candidates_by_symbol(
        decision_context,
        FeatureConfig(),
    )
'''
new = '''    # The same context replay carries rolling indicators, session liquidity and
    # still-valid narratives into 2024-01-01. Only H1 actions may trade.
'''
if old not in text:
    raise SystemExit("duplicate H1 context block mismatch")
path.write_text(text.replace(old, new, 1), encoding="utf-8")
