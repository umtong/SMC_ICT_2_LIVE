from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from urllib.parse import quote

import requests

REPO_ROOT = Path(__file__).resolve().parents[2]
ENGINE_ROOT = REPO_ROOT / "research" / "ml_hl_liquidation_20260726"
sys.path.insert(0, str(ENGINE_ROOT))

import probe_hl_liquidations as engine  # noqa: E402

REVISION_REF = "refs/convert/parquet"
CORRECTION_PATH = (
    REPO_ROOT
    / "sourcefix"
    / "ml_hl_liquidation_convert_ref_20260726"
    / "CORRECTION_004_CONVERT_PARQUET_REVISION_BEFORE_DATA.json"
)


def stable_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def resolve_convert_parquet_revision() -> tuple[str, dict[str, object], bytes]:
    correction = json.loads(CORRECTION_PATH.read_text(encoding="utf-8"))
    assert correction["status"] == "PRE_OUTCOME_SOURCE_ONLY"
    assert correction["hyperliquid_event_row_opened_before_correction"] is False
    assert correction["market_outcome_opened_before_correction"] is False
    encoded_ref = quote(REVISION_REF, safe="")
    url = f"https://huggingface.co/api/datasets/{engine.REMOTE_DATASET}/revision/{encoded_ref}"
    with requests.Session() as session:
        session.headers["User-Agent"] = "SMC_ICT_2_LIVE-hl-liquidation-convert-ref/1.0"
        response = session.get(url, timeout=120)
        response.raise_for_status()
        metadata = response.json()
    if not isinstance(metadata, dict):
        raise RuntimeError("convert/parquet revision metadata is not an object")
    resolved = str(metadata.get("sha") or "").strip()
    if len(resolved) < 12:
        raise RuntimeError("convert/parquet revision did not resolve to an immutable SHA")
    siblings = metadata.get("siblings")
    if not isinstance(siblings, list):
        raise RuntimeError("convert/parquet revision metadata has no sibling inventory")
    matching = [
        item
        for item in siblings
        if isinstance(item, dict) and str(item.get("rfilename")) == engine.REMOTE_PARQUET_PATH
    ]
    if len(matching) != 1:
        raise RuntimeError(
            f"expected one {engine.REMOTE_PARQUET_PATH} sibling in convert/parquet revision, found {len(matching)}"
        )
    raw = stable_json(metadata).encode("utf-8")
    print(
        stable_json(
            {
                "correction_id": correction["correction_id"],
                "revision_ref": REVISION_REF,
                "resolved_revision": resolved,
                "parquet_path": engine.REMOTE_PARQUET_PATH,
                "metadata_sha256": hashlib.sha256(raw).hexdigest(),
            }
        ),
        flush=True,
    )
    return resolved, metadata, raw


engine._resolve_repo_revision = resolve_convert_parquet_revision


if __name__ == "__main__":
    raise SystemExit(engine.main())
