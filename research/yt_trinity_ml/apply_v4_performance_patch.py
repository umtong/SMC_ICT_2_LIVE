#!/usr/bin/env python3
"""Apply semantics-preserving unified-SMC v4 compute reductions."""
from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path

EXPECTED_BEFORE = {
    "research/yt_trinity_ml/system/corpus_alpha.py": "5bd7f343906672d02fcd792508fe4b9b219388fdf961efea61296c699872c929",
    "research/yt_trinity_ml/system/research_pipeline.py": "b11942b34067e263c1096e76bdb8f70d8828fc60dc914392dbc27c39499819b7",
}
EXPECTED_AFTER = {
    "research/yt_trinity_ml/system/corpus_alpha.py": "be7fb89cce7b55b62692eb7f8869334f06cb1628047c1932b326ea97bf2f2be9",
    "research/yt_trinity_ml/system/research_pipeline.py": "111c218c0015a0e4c78e6179a2c48c5231e9b13745202001fac82fdd0a60354e",
}
PATCH = r"""--- a/research/yt_trinity_ml/system/corpus_alpha.py
+++ b/research/yt_trinity_ml/system/corpus_alpha.py
@@ -934,6 +934,10 @@
 def _new_reversal_states(
     features: pd.DataFrame,
     pos: int,
+    high_pools: list[_LiquidityPool],
+    low_pools: list[_LiquidityPool],
+    decision_high_pools: list[_LiquidityPool],
+    decision_low_pools: list[_LiquidityPool],
     consumed_high: set[tuple[str, float]],
     consumed_low: set[tuple[str, float]],
     config: CorpusAlphaConfig,
@@ -943,20 +947,6 @@
     previous = features.iloc[pos - 1]
     atr = float(row["atr"])
     buffer = config.sweep_buffer_atr * atr
-    bar_start_ns = _row_time_ns(features, pos, "bar_start_ns")
-    decision_ns = _row_time_ns(features, pos, "decision_time_ns")
-    high_pools = _liquidity_pools(
-        row, True, atr, config.liquidity_dedup_tolerance_atr, cutoff_ns=bar_start_ns
-    )
-    low_pools = _liquidity_pools(
-        row, False, atr, config.liquidity_dedup_tolerance_atr, cutoff_ns=bar_start_ns
-    )
-    decision_high_pools = _liquidity_pools(
-        row, True, atr, config.liquidity_dedup_tolerance_atr, cutoff_ns=decision_ns
-    )
-    decision_low_pools = _liquidity_pools(
-        row, False, atr, config.liquidity_dedup_tolerance_atr, cutoff_ns=decision_ns
-    )
     swept_highs = [
         pool
         for pool in high_pools
@@ -1082,6 +1072,8 @@
     features: pd.DataFrame,
     pos: int,
     side: int,
+    decision_pools: list[_LiquidityPool],
+    decision_ns: int,
     consumed_high: set[tuple[str, float]],
     consumed_low: set[tuple[str, float]],
     config: CorpusAlphaConfig,
@@ -1089,7 +1081,6 @@
 ) -> _NarrativeState | None:
     row = features.iloc[pos]
     previous = features.iloc[pos - 1]
-    decision_ns = _row_time_ns(features, pos, "decision_time_ns")
     if not _displacement(row, side, config):
         return None
     bias = float(row.get("htf_bias_score", 0.0)) if _finite(row.get("htf_bias_score")) else 0.0
@@ -1101,27 +1092,17 @@
         if not _finite(break_level) or not (float(row["close"]) > float(break_level) and float(previous["close"]) <= float(break_level)):
             return None
         stop_anchor = row.get("micro_last_swing_low")
-        high_pools = _liquidity_pools(
-            row,
-            True,
-            float(row["atr"]),
-            config.liquidity_dedup_tolerance_atr,
-            cutoff_ns=decision_ns,
+        target = _select_draw_target(
+            decision_pools, 1, float(row["high"]), float(row["low"]), consumed_high
         )
-        target = _select_draw_target(high_pools, 1, float(row["high"]), float(row["low"]), consumed_high)
     else:
         break_level = previous.get("last_swing_low")
         if not _finite(break_level) or not (float(row["close"]) < float(break_level) and float(previous["close"]) >= float(break_level)):
             return None
         stop_anchor = row.get("micro_last_swing_high")
-        low_pools = _liquidity_pools(
-            row,
-            False,
-            float(row["atr"]),
-            config.liquidity_dedup_tolerance_atr,
-            cutoff_ns=decision_ns,
+        target = _select_draw_target(
+            decision_pools, -1, float(row["high"]), float(row["low"]), consumed_low
         )
-        target = _select_draw_target(low_pools, -1, float(row["high"]), float(row["low"]), consumed_low)
     _bump(diagnostics, "continuation_first_break_displacements")
     if target is None:
         _bump(diagnostics, "continuation_missing_external_draw")
@@ -1247,23 +1228,62 @@
                 surviving.append(updated)
         states = surviving
 
-        new_reversals = _new_reversal_states(features, pos, consumed_high, consumed_low, config, diagnostics)
-        continuation_long = _new_continuation_state(features, pos, 1, consumed_high, consumed_low, config, diagnostics)
-        continuation_short = _new_continuation_state(features, pos, -1, consumed_high, consumed_low, config, diagnostics)
-        states.extend(new_reversals)
-        if continuation_long is not None:
-            states.append(continuation_long)
-        if continuation_short is not None:
-            states.append(continuation_short)
-
         atr = float(row["atr"])
         bar_start_ns = _row_time_ns(features, pos, "bar_start_ns")
+        decision_ns = _row_time_ns(features, pos, "decision_time_ns")
         high_pools = _liquidity_pools(
             row, True, atr, config.liquidity_dedup_tolerance_atr, cutoff_ns=bar_start_ns
         )
         low_pools = _liquidity_pools(
             row, False, atr, config.liquidity_dedup_tolerance_atr, cutoff_ns=bar_start_ns
         )
+        decision_high_pools = _liquidity_pools(
+            row, True, atr, config.liquidity_dedup_tolerance_atr, cutoff_ns=decision_ns
+        )
+        decision_low_pools = _liquidity_pools(
+            row, False, atr, config.liquidity_dedup_tolerance_atr, cutoff_ns=decision_ns
+        )
+
+        new_reversals = _new_reversal_states(
+            features,
+            pos,
+            high_pools,
+            low_pools,
+            decision_high_pools,
+            decision_low_pools,
+            consumed_high,
+            consumed_low,
+            config,
+            diagnostics,
+        )
+        continuation_long = _new_continuation_state(
+            features,
+            pos,
+            1,
+            decision_high_pools,
+            decision_ns,
+            consumed_high,
+            consumed_low,
+            config,
+            diagnostics,
+        )
+        continuation_short = _new_continuation_state(
+            features,
+            pos,
+            -1,
+            decision_low_pools,
+            decision_ns,
+            consumed_high,
+            consumed_low,
+            config,
+            diagnostics,
+        )
+        states.extend(new_reversals)
+        if continuation_long is not None:
+            states.append(continuation_long)
+        if continuation_short is not None:
+            states.append(continuation_short)
+
         _mark_consumed(row, high_pools, low_pools, consumed_high, consumed_low)
 
         # Structural dominance only.  At one decision point there is one current
--- a/research/yt_trinity_ml/system/research_pipeline.py
+++ b/research/yt_trinity_ml/system/research_pipeline.py
@@ -232,17 +232,26 @@
     pending: tuple[pd.Timestamp, ChronologicalEventModel, tuple[float, float, float, float], int, pd.Timestamp] | None = None
     scored: list[ScoredCandidate] = []
     ledger: list[ModelUpdateRecord] = []
+    last_attempted_training_signature: tuple[int, int] | None = None
 
     def start_update(update_start: pd.Timestamp) -> tuple[pd.Timestamp, ChronologicalEventModel, tuple[float, float, float, float], int, pd.Timestamp] | None:
+        nonlocal last_attempted_training_signature
         training = _purged_rows_asof(label_rows, update_start)
         minimum = max(50, configuration.model.min_samples_leaf * 2)
         if len(training) < minimum:
             return None
+        latest = pd.Timestamp(training["event_end"].max())
+        signature = (int(len(training)), int(latest.value))
+        # Expanding data are immutable. Re-fitting a deterministic model when no
+        # additional resolved label has arrived produces the same model and only
+        # burns research/live compute. Keep the currently active or pending copy.
+        if signature == last_attempted_training_signature:
+            return None
+        last_attempted_training_signature = signature
         try:
             model = ChronologicalEventModel(configuration.model).fit(training)
         except ValueError:
             return None
-        latest = pd.Timestamp(training["event_end"].max())
         return update_start + lag, model, _action_distributions(training), len(training), latest
 
     initial_started = evaluation_start - lag
"""

def digest(path: str) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main() -> int:
    before = {path: digest(path) for path in EXPECTED_BEFORE}
    if before == EXPECTED_AFTER:
        print("unified SMC v4 performance patch already applied")
        return 0
    if before != EXPECTED_BEFORE:
        raise RuntimeError(f"unexpected pre-patch sources: {before}")
    completed = subprocess.run(
        ["patch", "-p1", "--forward", "--batch"],
        input=PATCH,
        text=True,
        check=False,
        capture_output=True,
    )
    print(completed.stdout)
    if completed.returncode != 0:
        print(completed.stderr)
        raise SystemExit(completed.returncode)
    after = {path: digest(path) for path in EXPECTED_AFTER}
    if after != EXPECTED_AFTER:
        raise RuntimeError(f"unexpected post-patch sources: {after}")
    print({"status": "PASS", "hashes": after})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
