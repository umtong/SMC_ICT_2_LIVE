from __future__ import annotations

import hashlib
import io
import zipfile
from pathlib import Path

import pandas as pd

from liquidity_state_5m import load_month


def test_official_count_header_maps_to_trade_count(tmp_path: Path) -> None:
    symbol = "BTCUSDT"
    month = "2022-01"
    idx = pd.date_range(f"{month}-01", periods=31 * 288, freq="5min", tz="UTC")
    frame = pd.DataFrame(
        {
            "open_time": (idx.view("int64") // 1_000_000).astype("int64"),
            "open": 100.0,
            "high": 101.0,
            "low": 99.0,
            "close": 100.5,
            "volume": 10.0,
            "close_time": ((idx + pd.Timedelta(minutes=5) - pd.Timedelta(milliseconds=1)).view("int64") // 1_000_000).astype("int64"),
            "quote_volume": 1000.0,
            "count": 42,
            "taker_buy_volume": 5.0,
            "taker_buy_quote_volume": 500.0,
            "ignore": 0,
        }
    )
    cache = tmp_path / symbol
    cache.mkdir(parents=True)
    stem = f"{symbol}-5m-{month}.zip"
    zpath = cache / stem
    with zipfile.ZipFile(zpath, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(stem.replace(".zip", ".csv"), frame.to_csv(index=False).encode())
    digest = hashlib.sha256(zpath.read_bytes()).hexdigest()
    (cache / f"{stem}.CHECKSUM").write_text(f"{digest}  {stem}\n", encoding="utf-8")
    loaded, meta = load_month(symbol, month, tmp_path)
    assert "trade_count" in loaded.columns
    assert "count" not in loaded.columns
    assert int(loaded.trade_count.iloc[0]) == 42
    assert meta["rows"] == 31 * 288
