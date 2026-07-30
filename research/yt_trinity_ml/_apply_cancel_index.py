from pathlib import Path

path = Path("research/yt_trinity_ml/run_causal_action_fast.py")
text = path.read_text(encoding="utf-8")
helper = Path("research/yt_trinity_ml/_cancel_index_helper.txt").read_text(encoding="utf-8")
marker = "def _label(candidate: EventCandidate, action: str, exit_variant: str, bars: PreparedBars,\n"
if marker not in text:
    raise SystemExit("label insertion point mismatch")
text = text.replace(marker, helper + "\n\n" + marker, 1)
start = text.index("def _rows_fast(")
local_start = text.index("    def narrative_key(", start)
rows_start = text.index("    rows: list[dict[str, Any]] = []", local_start)
old = text[local_start:rows_start]
if "for later in passive_by_symbol" not in old:
    raise SystemExit("quadratic cancellation block not found")
text = text[:local_start] + "    cancel_times = _structural_cancel_times(candidates)\n\n" + text[rows_start:]
old_call = '                cancel_at = structural_cancel_at(candidate) if action == "EARLY_PASSIVE" else None\n'
new_call = '                cancel_at = cancel_times.get(id(candidate)) if action == "EARLY_PASSIVE" else None\n'
if old_call not in text:
    raise SystemExit("cancel call mismatch")
path.write_text(text.replace(old_call, new_call, 1), encoding="utf-8")
