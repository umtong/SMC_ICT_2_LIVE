from __future__ import annotations

import math


def scaled_path_bounds(*, multiple: float, trade_count: int, mean_account_return: float, scale: float, calendar_days: int) -> dict[str, float]:
    """Bound the compounded path after linearly scaling every trade return.

    For each original account return r > -1 and 0 <= t <= 1:
      log(1 + t*r) >= t*log(1 + r)  (concavity)
      log(1 + t*r) <= t*r           (log(1+x) <= x)

    This applies when the selected trade tape and slot chronology are unchanged
    and quantity is continuous and scales linearly without a binding cap.
    """
    if not 0 <= scale <= 1:
        raise ValueError("scale must be in [0, 1]")
    if multiple <= 0 or trade_count < 0 or calendar_days <= 0:
        raise ValueError("invalid path inputs")
    lower_multiple = multiple ** scale
    upper_multiple = math.exp(scale * trade_count * mean_account_return)
    return {
        "lower_multiple": lower_multiple,
        "upper_multiple": upper_multiple,
        "lower_geometric_daily_growth": lower_multiple ** (1 / calendar_days) - 1,
        "upper_geometric_daily_growth": upper_multiple ** (1 / calendar_days) - 1,
    }


def main() -> None:
    ordinary = scaled_path_bounds(
        multiple=2.6784945607515005,
        trade_count=80,
        mean_account_return=0.025712590960645487,
        scale=0.1,
        calendar_days=912,
    )
    winner_removed = scaled_path_bounds(
        multiple=1.327081646445777,
        trade_count=81,
        mean_account_return=0.014221882187367389,
        scale=0.1,
        calendar_days=912,
    )
    assert abs(ordinary["lower_multiple"] - 1.1035425339563436) < 1e-12
    assert abs(ordinary["upper_multiple"] - 1.228385527200077) < 1e-12
    assert abs(winner_removed["lower_multiple"] - 1.0287024266029716) < 1e-12
    assert abs(winner_removed["upper_multiple"] - 1.1220947441284415) < 1e-12
    print({"ordinary": ordinary, "winner_removed": winner_removed})


if __name__ == "__main__":
    main()
