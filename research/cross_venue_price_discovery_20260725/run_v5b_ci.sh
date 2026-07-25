#!/usr/bin/env bash
set -euo pipefail

root=research/cross_venue_price_discovery_20260725
runroot=research_runs/cross_venue_price_discovery_20260725/exact_arrival_v5b
cache=${RUNNER_TEMP:-/tmp}/xvenue-v5b-cache
mkdir -p "$runroot"

python - <<'PY'
import json, numpy, pandas, platform, requests, sys
from pathlib import Path
root=Path('research_runs/cross_venue_price_discovery_20260725/exact_arrival_v5b')
(root/'environment.json').write_text(json.dumps({
    'python':sys.version,
    'platform':platform.platform(),
    'numpy':numpy.__version__,
    'pandas':pandas.__version__,
    'requests':requests.__version__,
    'credentials_used':False,
    'orders_submitted':False,
    'paper_live_started':False,
    'selection_opened':False,
    'confirmation_opened':False,
    '2026_opened':False,
},indent=2,sort_keys=True)+'\n',encoding='utf-8')
PY

python -m py_compile \
  "$root/cross_venue_pilot.py" \
  "$root/cross_venue_pilot_v2.py" \
  "$root/cross_venue_development_v2.py" \
  "$root/source_probe.py" \
  "$root/source_probe_v2.py" \
  "$root/cross_venue_execution_v5.py" \
  "$root/cross_venue_signals_v5b.py" \
  "$root/cross_venue_execution_v5b.py" \
  "$root/cross_venue_pilot_v5.py" \
  "$root/cross_venue_pilot_v5b.py" \
  "$root/cross_venue_development_v5.py" \
  "$root/cross_venue_development_v5b.py" \
  "$root/test_cross_venue_execution_v5.py" \
  "$root/test_cross_venue_execution_v5b.py"

PYTHONPATH="$root" pytest -q \
  "$root/test_cross_venue_execution_v5.py" \
  "$root/test_cross_venue_execution_v5b.py" \
  2>&1 | tee "$runroot/tests.log"
PYTHONPATH="$root" python "$root/source_probe_v2.py" --self-test \
  --output "$runroot" 2>&1 | tee "$runroot/probe_self_test.log"
python scripts/validate_project.py

sha256sum \
  "$root/CAUSAL_EXECUTION_CORRECTION_V5.md" \
  "$root/FUNDING_BOUNDARY_CORRECTION_V5B.md" \
  "$root/cross_venue_execution_v5.py" \
  "$root/cross_venue_signals_v5b.py" \
  "$root/cross_venue_execution_v5b.py" \
  "$root/cross_venue_pilot_v5.py" \
  "$root/cross_venue_pilot_v5b.py" \
  "$root/cross_venue_development_v5.py" \
  "$root/cross_venue_development_v5b.py" \
  "$root/test_cross_venue_execution_v5.py" \
  "$root/test_cross_venue_execution_v5b.py" \
  "$root/run_v5b_ci.sh" \
  > "$runroot/INPUT_SHA256SUMS.txt"

set +e
PYTHONPATH="$root" python "$root/source_probe_v2.py" \
  --date 2023-07-01 \
  --output "$runroot/probe" \
  2>&1 | tee "$runroot/probe.log"
probe_rc=${PIPESTATUS[0]}
set -e

usable=$(python - <<'PY'
import json, pathlib
p=pathlib.Path('research_runs/cross_venue_price_discovery_20260725/exact_arrival_v5b/probe/SOURCE_PROBE_V2.json')
print('true' if p.exists() and json.loads(p.read_text())['all_required_sources_usable'] else 'false')
PY
)
if [[ "$probe_rc" -ne 0 || "$usable" != "true" ]]; then
  python - <<'PY'
import json, pathlib
root=pathlib.Path('research_runs/cross_venue_price_discovery_20260725/exact_arrival_v5b')
payload={
    'schema_version':1,
    'claim_id':'CLM-20260725-1850-XVENUE-001',
    'stage':'SOURCE_UNAVAILABLE_V5B',
    'causal_version':5,
    'causal_engine_version':'5B',
    'strategy_or_pnl_computed':False,
    'development_opened':False,
    'selection_opened':False,
    'confirmation_opened':False,
    '2026_opened':False,
    'orders_submitted':False,
    'paper_live_started':False,
    'ranking_eligible':False,
}
(root/'V5B_SEQUENTIAL_RESULT.json').write_text(json.dumps(payload,indent=2,sort_keys=True)+'\n')
PY
  exit 0
fi

PYTHONPATH="$root" python "$root/cross_venue_pilot_v5b.py" \
  --output "$runroot/pilot" \
  --cache "$cache" \
  2>&1 | tee "$runroot/pilot.log"
PYTHONPATH="$root" python "$root/cross_venue_development_v5b.py" \
  --pilot-dir "$runroot/pilot" \
  --output "$runroot/development" \
  --cache "$cache" \
  2>&1 | tee "$runroot/development.log"

python - <<'PY'
import json, pathlib
root=pathlib.Path('research_runs/cross_venue_price_discovery_20260725/exact_arrival_v5b')
pilot=json.loads((root/'pilot'/'PILOT_RESULT.json').read_text())
development=json.loads((root/'development'/'DEVELOPMENT_RESULT.json').read_text())
payload={
    'schema_version':1,
    'claim_id':'CLM-20260725-1850-XVENUE-001',
    'stage':development['stage'],
    'causal_version':5,
    'causal_engine_version':'5B',
    'pilot_fatal_edge_pass_count':int(pilot.get('fatal_edge_pass_count',0)),
    'development_opened':bool(development.get('development_opened',False)),
    'development_gate_pass_count':int(development.get('development_gate_pass_count',0)),
    'selection_opened':False,
    'confirmation_opened':False,
    '2026_opened':False,
    'orders_submitted':False,
    'paper_live_started':False,
    'ranking_eligible':False,
    'earlier_engine_outputs_admissible':False,
}
(root/'V5B_SEQUENTIAL_RESULT.json').write_text(json.dumps(payload,indent=2,sort_keys=True)+'\n')
print(json.dumps(payload,indent=2,sort_keys=True))
PY
