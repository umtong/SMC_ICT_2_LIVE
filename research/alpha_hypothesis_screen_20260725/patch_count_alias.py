from __future__ import annotations

"""Deterministically add Binance 2022+ `count` header compatibility.

The public USD-M kline archive changed the header label for trade count from
`number_of_trades`/headerless position 9 to `count` for some monthly files.
All three names represent the same official kline field.  No strategy,
parameter, data split, cost, or execution rule is modified.
"""

import hashlib
import sys
from pathlib import Path

EXPECTED_INPUT_SHA256 = "a50075e4b6b236ae7b70002952c234e233b12f22dd05177cd589dc6639b0fe65"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: patch_count_alias.py PATH_TO_liquidity_state_5m.py")
    path = Path(sys.argv[1])
    actual = sha256(path)
    if actual != EXPECTED_INPUT_SHA256:
        raise SystemExit(f"unexpected input source SHA-256: {actual}")
    text = path.read_text(encoding="utf-8")
    old = "aliases={'number_of_trades':'trade_count'}; df=df.rename(columns=aliases)"
    new = "aliases={'number_of_trades':'trade_count','count':'trade_count'}; df=df.rename(columns=aliases)"
    if text.count(old) != 1:
        raise SystemExit("trade-count alias anchor missing or non-unique")
    path.write_text(text.replace(old, new), encoding="utf-8")
    print(sha256(path))


if __name__ == "__main__":
    main()
