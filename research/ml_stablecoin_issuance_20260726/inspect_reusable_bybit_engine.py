from __future__ import annotations

import ast
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "ml_liquidity_draw_20260726" / "run.py"
OUTPUT = Path(__file__).resolve().parent / "REUSABLE_BYBIT_ENGINE_AST.json"


def annotation_text(node: ast.expr | None) -> str | None:
    if node is None:
        return None
    return ast.unparse(node)


def main() -> int:
    if not SOURCE.exists():
        raise FileNotFoundError(f"reconstruct reusable source first: {SOURCE}")
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"), filename=str(SOURCE))
    records: list[dict[str, object]] = []
    constants: list[dict[str, object]] = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            records.append({
                "kind": "function",
                "name": node.name,
                "args": [arg.arg for arg in node.args.args],
                "defaults": [ast.unparse(item) for item in node.args.defaults],
                "returns": annotation_text(node.returns),
                "line": node.lineno,
            })
        elif isinstance(node, ast.ClassDef):
            methods = [
                {
                    "name": item.name,
                    "args": [arg.arg for arg in item.args.args],
                    "returns": annotation_text(item.returns),
                    "line": item.lineno,
                }
                for item in node.body
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
            ]
            records.append({
                "kind": "class",
                "name": node.name,
                "bases": [ast.unparse(base) for base in node.bases],
                "methods": methods,
                "line": node.lineno,
            })
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            value = node.value if isinstance(node, ast.AnnAssign) else node.value
            targets = [node.target] if isinstance(node, ast.AnnAssign) else node.targets
            if value is None:
                continue
            for target in targets:
                if isinstance(target, ast.Name) and target.id.isupper():
                    try:
                        rendered = ast.unparse(value)
                    except Exception:
                        continue
                    if len(rendered) <= 2_000:
                        constants.append({
                            "name": target.id,
                            "value": rendered,
                            "line": node.lineno,
                        })
    payload = {
        "schema_version": 1,
        "source": str(SOURCE.relative_to(ROOT.parent)),
        "market_data_read": False,
        "model_fit": False,
        "trade_or_pnl_opened": False,
        "records": records,
        "constants": constants,
    }
    OUTPUT.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "source": str(SOURCE),
        "functions": sum(item["kind"] == "function" for item in records),
        "classes": sum(item["kind"] == "class" for item in records),
        "constants": len(constants),
        "output": str(OUTPUT),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
