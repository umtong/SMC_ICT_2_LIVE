# 08:00 UTC Option-Settlement SMT Reversal

This directory contains the frozen, pre-2024 fatal-alpha screen for
`CLM-20260726-1543-EXPIRY-SMT-001`.

## Economic mechanism

Deribit uses a mechanically fixed 07:30–08:00 UTC delivery window. The screen
therefore treats 08:00 UTC as a known hedging and liquidity transition rather
than a generic clock effect. It asks whether BTCUSDT or ETHUSDT raids completed
04:00–07:25 UTC external liquidity during the settlement window while the peer
fails to confirm the raid. A trade becomes eligible only after a completed
post-08:00 displacement/reclaim, and entry is at the following Bybit 5-minute
open.

SMC/ICT translation:

1. external-liquidity raid;
2. BTC/ETH SMT non-confirmation;
3. post-settlement displacement or micro structure break;
4. structural stop beyond the raid;
5. target at prior equilibrium or opposing external liquidity.

## Frozen research boundary

- Bybit linear BTCUSDT and ETHUSDT only;
- fit year 2022, development year 2023;
- hard code prohibition on 2024–2026 data;
- one global position slot;
- next-open entry, adverse gap handling and same-bar stop-first handling;
- 12/18/24 bp all-in cost replays;
- actual Bybit funding when available, otherwise a conservative fixed charge;
- no risk or leverage search until the pre-registered fit and development gates
  pass;
- no credentials and no orders.

## Source reconstruction

`expiry_smt.py.zlib.b64` is the zlib-compressed, Base64-encoded source. The
workflow reconstructs `runtime/expiry_smt.py` and rejects execution unless its
SHA-256 is exactly:

```text
51e2ed49aec3b94576eea32e9d3394384968711974c0bebcaccdc890322ef521
```

Local reconstruction:

```bash
python - <<'PY'
import base64, zlib
from pathlib import Path
encoded = Path('expiry_smt.py.zlib.b64').read_text().strip()
Path('expiry_smt.py').write_bytes(zlib.decompress(base64.b64decode(encoded)))
PY
python expiry_smt.py --self-test
```

The exact policy grid, causal boundaries, selection gates, costs, and output
contract are in `preregistration.json`.
