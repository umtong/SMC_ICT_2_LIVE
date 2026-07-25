# Amendment 002 — memory-bounded exact evaluation and CI fixture

The original all-clock implementation exceeded runtime memory while constructing the 576-bars/day clock. The replacement preserves the economic contract, prepares one clock at a time, retains causal events only, loads OHLC for execution, and uses vectorized exact next-open/stop/target/horizon replay.

The original completed run recorded real BTC event equality against the scalar executor across multiple costs and equity levels. The repository CI regression uses a deterministic fixture covering target, stop, horizon with funding, and gap-stop paths so it can run without distributing the large registered market datasets. This changes verification transport only, not the economic result or execution semantics.
