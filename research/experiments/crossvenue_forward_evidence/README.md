# Cross-venue recovery and forward execution evidence bundle

Claim: `CLM-20260725-2045-CROSSVENUE-FWD-001`

This directory preserves a deterministic source bundle for two linked but separately judged outputs:

1. a valid negative result for the recovered ten-day cross-venue liquidation/replenishment specification; and
2. a deployable, observation-only forward public/private capture plus exact-prefix Shadow A/B evidence layer.

`source-bundle.tar.gz` contains readable Python source, tests, result summaries and a per-file SHA-256 manifest. It intentionally excludes the 101 MB historical panel and all credentials. The large immutable panel remains an external/Drive artifact identified by its archive hash.

## Extract and verify

```bash
python research/experiments/crossvenue_forward_evidence/extract_bundle.py \
  --archive research/experiments/crossvenue_forward_evidence/source-bundle.tar.gz \
  --destination /tmp/crossvenue-forward-source
cd /tmp/crossvenue-forward-source
python -m pytest
```

The repository test validates the archive SHA-256, safe member paths, the embedded manifest and Python compilation. The full extracted suite passed locally with 16 tests.

## Decision

- Strategy Champion: unchanged.
- Historical cross-venue policy families: zero strict or exploratory survivors.
- Forward evidence layer: implemented and locally validated, but no forward observations yet.
- Live order permission: unchanged; the capture process has no order-placement path.
