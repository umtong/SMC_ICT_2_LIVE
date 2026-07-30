#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import pandas as pd


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--parts", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    feature_files = sorted(args.parts.rglob("*_features.csv.gz"))
    manifest_files = sorted(args.parts.rglob("*_manifest.json"))
    if len(feature_files) != 24 or len(manifest_files) != 24:
        raise RuntimeError(f"expected 24 feature and manifest files, got {len(feature_files)} / {len(manifest_files)}")
    frames = []
    for p in feature_files:
        f = pd.read_csv(p)
        if len(f):
            frames.append(f)
    combined = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    if len(combined):
        combined = combined.sort_values(["event_ts", "symbol", "level_side"], kind="mergesort")
        dup = combined["event_id"].duplicated(keep=False)
        if bool(dup.any()):
            conflicts = combined.loc[dup, "event_id"].tolist()[:20]
            raise RuntimeError(f"duplicate event ids: {conflicts}")
    sources: dict[str, dict] = {}
    failures = []
    part_meta = []
    for p in manifest_files:
        obj = json.loads(p.read_text(encoding="utf-8"))
        part_meta.append({k: obj.get(k) for k in ["symbol", "year", "month", "event_count", "feature_sha256"]})
        failures.extend(obj.get("failures", []))
        for s in obj.get("source_files", []):
            old = sources.get(s["url"])
            if old and old["sha256"] != s["sha256"]:
                raise RuntimeError(f"source hash conflict: {s['url']}")
            sources[s["url"]] = s
    if failures:
        raise RuntimeError(f"source failures present: {failures[:20]}")
    out_features = args.out / "dense_edge_microflow_2023_features.csv.gz"
    combined.to_csv(out_features, index=False, compression="gzip")
    summary = {
        "schema": "DENSE-LIQUIDITY-EDGE-MICROFLOW-V3",
        "event_count": int(len(combined)),
        "symbols": combined["symbol"].value_counts().to_dict() if len(combined) else {},
        "sides": combined["level_side"].value_counts().to_dict() if len(combined) else {},
        "months": combined.assign(month=pd.to_datetime(combined["event_ts"], utc=True).dt.strftime("%Y-%m"))["month"].value_counts().sort_index().to_dict() if len(combined) else {},
        "source_file_count": len(sources),
        "feature_sha256": sha256_file(out_features),
        "parts": part_meta,
        "sources": [sources[k] for k in sorted(sources)],
    }
    (args.out / "dense_edge_microflow_2023_manifest.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8"
    )
    readback = pd.read_csv(out_features)
    if len(readback) != len(combined):
        raise RuntimeError("readback row count mismatch")
    if readback["event_id"].duplicated().any():
        raise RuntimeError("readback duplicate event ids")
    print(json.dumps({"events": len(combined), "sources": len(sources)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
