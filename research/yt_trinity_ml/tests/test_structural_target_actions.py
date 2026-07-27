from __future__ import annotations

from run_entry_exit_action_ml_v2 import actions


def test_internal_target_actions_are_present_and_distinct() -> None:
    mapping = {action.identifier: action for action in actions()}
    action = mapping['MARKET_CONFIRM__INTERNAL50_BE']
    assert action.partial_mode == 'INTERNAL_TARGET'
    assert action.partial_fraction == 0.5
    assert action.break_even_after_partial
    assert action.partial_r is None
