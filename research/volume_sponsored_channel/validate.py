from __future__ import annotations

import base64
import hashlib
import io
import json
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
RESULT = json.loads((ROOT / "RESULT.json").read_text())
CONTRACT = json.loads((ROOT / "CONTRACT.json").read_text())
MANIFEST = json.loads((ROOT / "SOURCE_MANIFEST.json").read_text())

paths = RESULT["official_selected_growth_path"]
checks = {
    "ids_match": RESULT["result_id"] == CONTRACT["result_id"] and RESULT["claim_id"] == CONTRACT["claim_id"],
    "target_not_met": RESULT["target_status"] == "NOT_MET" and all(paths[key]["geometric_daily_growth"] < 0.01 for key in ("13bp", "18bp", "24bp")),
    "cost_monotone": paths["13bp"]["end_nav"] > paths["18bp"]["end_nav"] > paths["24bp"]["end_nav"],
    "same_trade_count": len({paths[key]["completed_trades"] for key in ("13bp", "18bp", "24bp")}) == 1,
    "one_global_slot": CONTRACT["one_global_slot"] is True,
    "no_elapsed_time_exit": "no elapsed-time" in CONTRACT["exit"],
    "fixed_latency": "500ms" in CONTRACT["entry"],
    "selected_risk_pre2024": abs(CONTRACT["risk"]["planned_loss_fraction"] - 0.1) < 1e-12,
    "selected_cap": CONTRACT["risk"]["notional_cap"] == 12.0,
    "actual_funding": CONTRACT["actual_signed_funding"] is True,
    "official_interval": CONTRACT["evaluation"] == ["2024-01-01T00:00:00Z", "2026-07-01T00:00:00Z"],
    "no_live_authority": RESULT["live_permission"] is False and RESULT["orders_submitted"] is False,
    "candidate_inventory": RESULT["programization_validity"]["candidate_count_total"] == 2855,
    "pre2024_risk_guard": RESULT["pre2024"]["risk_selection"]["conservative_liquidation_guard_pass"] is True,
}

raw = base64.b64decode((ROOT / "SOURCE_BUNDLE.tar.gz.b64").read_text().strip())
checks["source_size"] = len(raw) == MANIFEST["archive_bytes"]
checks["source_hash"] = hashlib.sha256(raw).hexdigest() == MANIFEST["archive_sha256"]
with tarfile.open(fileobj=io.BytesIO(raw), mode="r:gz") as archive:
    names = sorted(member.name for member in archive.getmembers() if member.isfile())
checks["source_members"] = names == sorted(item["path"] for item in MANIFEST["files"])
checks["all_pass"] = all(checks.values())

attestation = {
    "schema_version": 1,
    "result_id": RESULT["result_id"],
    "status": "PASS" if checks["all_pass"] else "FAIL",
    "checks": checks,
}
(ROOT / "VALIDATION_ATTESTATION.json").write_text(json.dumps(attestation, indent=2, sort_keys=True) + "\n")
print(json.dumps(attestation, indent=2, sort_keys=True))
if not checks["all_pass"]:
    raise SystemExit(1)
