from __future__ import annotations

import hashlib
import runpy
from pathlib import Path


def test_funding_settlement_runner_reconstructs_and_compiles() -> None:
    root = Path(__file__).resolve().parents[1] / "research" / "funding_settlement"
    runpy.run_path(str(root / "restore_runner.py"), run_name="__main__")
    source = (root / "runner.py").read_bytes()
    assert hashlib.sha256(source).hexdigest() == "bb8d25c19d5c1a5f44467f2b23b4782ba552e5ae3c8dbb93dd11fa173499f7b5"
    compile(source, str(root / "runner.py"), "exec")
