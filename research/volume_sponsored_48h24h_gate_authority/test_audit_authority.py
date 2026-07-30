from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("audit_authority", HERE / "audit_authority.py")
assert SPEC and SPEC.loader
m = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = m
SPEC.loader.exec_module(m)


def test_parent_parity_fails_closed_even_when_count_matches() -> None:
    observed = {"multiple": 1.01, "trades": 10}
    expected = {"multiple": 1.02, "trades": 10}
    check = m.compare(observed, expected)
    assert check["trade_count_match"] is True
    assert check["multiple_match_1e_8"] is False


def test_schema_patch_is_exact_and_limited() -> None:
    source = b"""m=load_concat(symbol,'trade_bars/1m.parquet',[\n            'start_time_ms','open','high','low','close','is_complete','available_at_ms'\n        ])\n        m=m[m.is_complete & m.available_at_ms.notna()]\n        mark=load_concat(symbol,'streams/mark_price_1m.parquet',[\n            'start_time_ms','open','close','is_complete','available_at_ms'\n        ])\n        mark=mark[mark.is_complete & mark.available_at_ms.notna()]\n"""
    patched = m.patch_accessible_canonical_schema(source).decode("utf-8")
    assert patched.count("observed") == 4
    assert "is_complete" not in patched


def test_parent_source_identity_is_frozen() -> None:
    assert m.PARENT_COMMIT == "c9e805493048b9a0d8e9dab4cc05a0d3ae69853"
    assert m.PARENT_SOURCE_SHA256 == "e3bcb07a605fe3c6b8a20894f14ef820c60a48b3e9b8b633b4cebe76c8ff49ef"
    assert m.EXPECTED["official_24bp"] == {"multiple": 1.3525318555240424, "trades": 143}
