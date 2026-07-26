#!/usr/bin/env bash
set -euo pipefail

: "${OUT:?OUT is required}"
: "${CACHE:?CACHE is required}"

mkdir -p runtime "$OUT/self_test" "$OUT/result"
git fetch --depth=1 origin agent/r11-altlag-opportunity-001
git show FETCH_HEAD:research/bybit_altlag_opportunity_20260726/probe.py.zlib.b64 > runtime/base_probe.py.zlib.b64
python - <<'PY'
import base64, hashlib, pathlib, zlib
root = pathlib.Path("runtime")
source = zlib.decompress(base64.b64decode((root / "base_probe.py.zlib.b64").read_text().strip()))
observed = hashlib.sha256(source).hexdigest()
expected = "5ecbfddf8443fd37b76514e30ab91028dda68e16a5e51eb63f7f76f0c073ad0f"
assert observed == expected, (observed, expected)
(root / "base_probe.py").write_bytes(source)
print("base_probe_sha256", observed)
PY
python research/smt_acceptance_continuation_20260726/reconstruct.py
cp research/smt_acceptance_continuation_20260726/run.py runtime/acceptance.py
python -m py_compile runtime/base_probe.py runtime/acceptance.py
PYTHONPATH=runtime python runtime/acceptance.py self-test --output "$OUT/self_test"
python scripts/validate_project.py
sha256sum \
  runtime/base_probe.py \
  runtime/acceptance.py \
  research/smt_acceptance_continuation_20260726/WORK_CLAIM.json \
  research/smt_acceptance_continuation_20260726/preregistration.json \
  research/smt_acceptance_continuation_20260726/reconstruct.py \
  > "$OUT/INPUT_SHA256SUMS.txt"

PYTHONPATH=runtime python runtime/acceptance.py run \
  --output "$OUT/result" \
  --cache "$CACHE" \
  2>&1 | tee "$OUT/run.log"

python - <<'PY'
import json, os
from pathlib import Path
root = Path(os.environ["OUT"])
result = json.loads((root / "result" / "RESULT.json").read_text())
assert result["claim_id"] == "CLM-20260726-1630-SMT-ACCEPTANCE-CONTINUATION-001"
assert result["candidate_count"] == 9
assert result["2024_opened"] is False
assert result["2025_opened"] is False
assert result["2026_opened"] is False
assert result["orders_submitted"] is False
assert result["paper_live_enabled"] is False
assert result["ranking_role"] == "NOT_RANK_ELIGIBLE_TRADE_PRINT_FATAL_SCREEN"
assert (root / "result" / "EVENTS.csv").exists()
assert (root / "result" / "LEDGER.csv").exists()
print("SEALED_DECISION_READY_RESULT=" + json.dumps({
    "status": result["status"],
    "unique_physical_event_count": result["unique_physical_event_count"],
    "gate_pass_count": result["gate_pass_count"],
    "best_candidate_id": result["best_candidate"]["candidate_id"] if result["best_candidate"] else None,
}, sort_keys=True))
PY

find "$OUT" -type f ! -name OUTPUT_SHA256SUMS.txt -print0 \
  | sort -z | xargs -0 sha256sum > "$OUT/OUTPUT_SHA256SUMS.txt"
