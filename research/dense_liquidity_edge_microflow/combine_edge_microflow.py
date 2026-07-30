#!/usr/bin/env python3
from __future__ import annotations
import argparse, csv, gzip, hashlib, json
from pathlib import Path


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as f:
        for b in iter(lambda: f.read(1024 * 1024), b''):
            h.update(b)
    return h.hexdigest()


def read_csvs(paths):
    rows = []
    for p in paths:
        with p.open(newline='', encoding='utf-8') as f:
            rows.extend(csv.DictReader(f))
    return rows


def write_gz(path, rows):
    keys, seen = [], set()
    for r in rows:
        for k in r:
            if k not in seen:
                seen.add(k)
                keys.append(k)
    with gzip.open(path, 'wt', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        w.writerows(rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--parts', required=True)
    ap.add_argument('--out', required=True)
    a = ap.parse_args()
    parts, out = Path(a.parts), Path(a.out)
    out.mkdir(parents=True, exist_ok=True)

    features = read_csvs(sorted(parts.glob('features_*.csv')))
    raw_all = read_csvs(sorted(parts.glob('raw_manifest_*.csv')))
    statuses = [json.loads(p.read_text()) for p in sorted(parts.glob('status_*.json'))]

    features.sort(key=lambda r: (int(r['anchor_ms']), r['symbol'], r['event_id']))
    ids = [r['event_id'] for r in features]
    dup = len(ids) - len(set(ids))
    if dup:
        raise SystemExit(f'duplicate event ids: {dup}')

    # Adjacent monthly workers intentionally include the same boundary day as
    # warmup/lookahead. Keep one immutable identity per symbol/day/SHA and
    # prefer its event-month role when available.
    role_priority = {'event': 0, 'warmup': 1, 'lookahead': 2}
    raw_all.sort(key=lambda r: (
        r['symbol'], r['day'], r['sha256'], role_priority.get(r.get('role', ''), 9)
    ))
    raw_unique = {}
    for r in raw_all:
        raw_unique.setdefault((r['symbol'], r['day'], r['sha256']), r)
    raw = list(raw_unique.values())
    raw.sort(key=lambda r: (r['day'], r['symbol'], role_priority.get(r.get('role', ''), 9)))

    fpath = out / 'combined_features.csv.gz'
    rpath = out / 'raw_source_manifest.csv.gz'
    write_gz(fpath, features)
    write_gz(rpath, raw)
    counts = {k: sum(1 for r in features if r.get('status') == k)
              for k in ['ok', 'no_sensor', 'no_entry']}
    result = {
        'result_id': 'SOURCE-20260730-DENSE-LIQUIDITY-EDGE-MICROFLOW-001',
        'candidate_events': len(features),
        'unique_events': len(set(ids)),
        'raw_manifest_rows_before_boundary_dedup': len(raw_all),
        'raw_unique_symbol_days': len(raw),
        'status_counts': counts,
        'raw_total_bytes_unique': sum(int(r['size_bytes']) for r in raw),
        'feature_sha256': sha(fpath),
        'raw_manifest_sha256': sha(rpath),
        'part_statuses': statuses,
    }
    (out / 'EXTRACTION_RESULT.json').write_text(
        json.dumps(result, indent=2, sort_keys=True), encoding='utf-8'
    )
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
