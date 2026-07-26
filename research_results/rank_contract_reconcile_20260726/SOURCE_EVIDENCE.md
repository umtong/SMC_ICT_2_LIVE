# Ranking-contract source evidence

Result: `RES-20260726-RANK-CONTRACT-RECONCILE-001`

## Former first place — verified dynamic state-exit source

Source artifact: workflow `30160153706`, artifact `8620014408`, digest `sha256:d1677e1bb776dfe6d52db913d4a689b6bfd95a5bad648b1b8e92c7846ef7ad20`.

Verified `state_exit.py` SHA-256: `7ed8ebda8e8744f4dcefb6405b5576582fe682b03ad586fc8576e89cf80eedb0`.

```text
0043: @dataclass(frozen=True, slots=True)
0044: class ExitCandidate:
0045:     entry_index: int
0046:     exit_mode: str
0047:     minimum_hold_bars: int
0048:     maximum_hold_bars: int
...
0062:     base = itertools.product(range(len(ENTRY_RULES)), (1, 3, 6), (12, 24, 48, 96), (1.5, 2.5, 4.0))
...
0125:         entry_index = signal_bar + 1
0126:         timeout_index = entry_index + maximum_hold
...
0141:         exit_index = timeout_index
0142:         exit_price = op[symbol, timeout_index]
...
0146:         for bar in range(entry_index, timeout_index):
...
0182:             if condition:
0183:                 next_open = bar + 1
...
0187:                 exit_index = next_open
0188:                 exit_price = op[symbol, next_open]
0189:                 state_exited = 1
0190:                 break
```

The ranked candidate uses `maximum_hold_bars=96` on five-minute bars. Unless an ATR stop or state condition exits earlier, the implementation closes at the open exactly 480 minutes after entry. The recorded state-exit rate is `0.3041237113402061`. This is an elapsed-time liquidation and fails the current project contract. Historical evidence is retained; current active ranking eligibility is removed.

## New provisional first place — Donchian structural exit

GitHub source blob: `816d388b682e012308309457828508ab3b362463`.

```text
0061: def exit_path(d,entry_idx,entry_price,side,stop,exit_low,exit_high,end_idx=None):
0062:     last=len(d["open_time_ms"])-1 if end_idx is None else min(end_idx,len(d["open_time_ms"])-1)
0063:     for j in range(entry_idx,last+1):
...
0066:             if o<=stop:return ... "gap_stop"
0067:             if l<=stop:return ... "stop"
...
0073:         if hit:
0074:             if j+1<=last:return ... "channel_exit"
0075:             return ... "evaluation_mtm"
0076:     return ... "evaluation_mtm"
```

No maximum holding duration exists. Operational exits are ATR stop or completed Donchian channel exit. `evaluation_mtm` is only terminal account valuation at the fixed evidence boundary.

The compact result records for specification `a70626d9e484285f2cb4`:

- all-breakout comparator: `0.0900854440%/day` at 12 bp and `0.0700188721%/day` at 24 bp;
- fully recorded after-loser path: `0.0829995553%/day` at 12 bp and `0.0631844619%/day` at 24 bp.

The all-breakout comparator becomes provisional rank 1 because it has the highest recorded growth among current-exit-contract-audited paths. Its missing complete risk and concentration fields force `VERY_LOW` comparison confidence, not silent exclusion.
