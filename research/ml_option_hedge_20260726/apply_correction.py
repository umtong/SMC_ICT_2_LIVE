from __future__ import annotations

import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / "run.py"
ORIGINAL_SHA256 = "cfd0d7c72ebd71d0dc479341fab10fb427033535590260a9016bd85ed438bb4a"
PATCHED_SHA256 = "122c2f8e1d49d77a8aa9fa3fe9b074232b6c6af04b66efe6f9f83bf94f85c4d6"

OLD = '''def fit_model(train: pd.DataFrame, calibration: pd.DataFrame) -> tuple[HistGradientBoostingClassifier, IsotonicRegression]:
    train_resolved = train[train["label"].isin([0, 1])]
    calibration_resolved = calibration[calibration["label"].isin([0, 1])]
    if len(train_resolved) < 300 or len(calibration_resolved) < 100:
        raise RuntimeError("insufficient resolved rows for one-model fit")
'''

NEW = '''def fit_model(train: pd.DataFrame, calibration: pd.DataFrame) -> tuple[HistGradientBoostingClassifier, IsotonicRegression]:
    train_resolved = train[train["label"].isin([0, 1])]
    calibration_resolved = calibration[calibration["label"].isin([0, 1])]
    train_counts = train_resolved["label"].value_counts().to_dict()
    calibration_counts = calibration_resolved["label"].value_counts().to_dict()
    feasible = (
        len(train_resolved) >= 200
        and len(calibration_resolved) >= 50
        and min(int(train_counts.get(0, 0)), int(train_counts.get(1, 0))) >= 20
        and min(int(calibration_counts.get(0, 0)), int(calibration_counts.get(1, 0))) >= 10
    )
    if not feasible:
        raise RuntimeError(
            "insufficient resolved rows for one-model fit: "
            f"train={len(train_resolved)} classes={train_counts}; "
            f"calibration={len(calibration_resolved)} classes={calibration_counts}"
        )
'''


def sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def main() -> int:
    raw = SOURCE.read_bytes()
    if sha256(raw) != ORIGINAL_SHA256:
        raise RuntimeError("unexpected reconstructed source identity")
    text = raw.decode("utf-8")
    if text.count(OLD) != 1:
        raise RuntimeError("expected feasibility block not found exactly once")
    patched = text.replace(OLD, NEW, 1).encode("utf-8")
    if sha256(patched) != PATCHED_SHA256:
        raise RuntimeError("patched source identity mismatch")
    compile(patched, str(SOURCE), "exec")
    SOURCE.write_bytes(patched)
    print(f"applied premodel correction bytes={len(patched)} sha256={sha256(patched)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
