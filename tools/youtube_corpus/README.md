# YouTube caption corpus collector

This utility enumerates the public `videos`, `shorts`, and `streams` tabs for
three named SMC/ICT education channels, deduplicates every discovered video ID,
and records either a caption transcript or an explicit failure reason.

The raw caption corpus is an ephemeral GitHub Actions artifact. It is not
committed to the repository. Derived research should retain video/channel IDs,
run hashes, and compact paraphrased findings rather than republishing complete
captions.

## Local invocation

```bash
python -m pip install yt-dlp youtube-transcript-api requests urllib3
python tools/youtube_corpus/collect_channels.py \
  --output artifacts/youtube_corpus
```

Outputs:

- `videos.jsonl`: every discovered public video ID and enumeration provenance
- `transcripts.jsonl.gz`: successful transcript records
- `failures.jsonl`: videos without a usable transcript and the exact reason
- `manifest.json`, `summary.md`, `SHA256SUMS`: coverage and reproducibility data

A video without captions is still counted as discovered. Therefore
`discovered = transcript_success + explicit_failure` is the primary coverage
invariant.
