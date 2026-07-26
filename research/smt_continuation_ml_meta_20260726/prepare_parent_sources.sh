#!/usr/bin/env bash
set -euo pipefail

repo_root="${1:-$PWD}"
out_root="${2:-$RUNNER_TEMP/smt-cont-parent}"
acceptance_sha="4473b45971bc1388e09a76d0510bc21978a7f5b4"
base_sha="23ee353103551708c9e5181f69a9a2381d389587"

rm -rf "$out_root"
mkdir -p "$out_root/acceptance" "$out_root/base"

cd "$repo_root"
git fetch --no-tags --depth=1 origin "$acceptance_sha"
for file in reconstruct.py implementation.b64.part00 implementation.b64.part01 implementation.b64.part02; do
  git show "${acceptance_sha}:research/smt_acceptance_continuation_20260726/${file}" > "$out_root/acceptance/$file"
done
python "$out_root/acceptance/reconstruct.py"
mv "$out_root/acceptance/run.py" "$out_root/acceptance/acceptance_engine.py"

git fetch --no-tags --depth=1 origin "$base_sha"
git show "${base_sha}:research/bybit_altlag_opportunity_20260726/probe.py.zlib.b64" > "$out_root/base/probe.py.zlib.b64"
python - "$out_root/base" <<'PY'
import base64
import pathlib
import sys
import zlib
root = pathlib.Path(sys.argv[1])
source = zlib.decompress(base64.b64decode((root / 'probe.py.zlib.b64').read_text().strip()))
(root / 'base_probe.py').write_bytes(source)
PY

python -m py_compile "$out_root/acceptance/acceptance_engine.py" "$out_root/base/base_probe.py"
sha256sum "$out_root/acceptance/acceptance_engine.py" "$out_root/base/base_probe.py" > "$out_root/PARENT_SHA256SUMS.txt"
cat "$out_root/PARENT_SHA256SUMS.txt"
