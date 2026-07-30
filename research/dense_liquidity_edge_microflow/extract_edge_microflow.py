#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import math
import shutil
import statistics
import tempfile
import time
import urllib.request
from collections import deque
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path


def args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument('--symbol', required=True, choices=['BTCUSDT', 'ETHUSDT'])
    p.add_argument('--month', required=True, type=int)
    p.add_argument('--year', default=2023, type=int)
    p.add_argument('--output-dir', required=True)
    return p.parse_args()


def pick_field(fields: list[str], options: list[str]) -> str:
    norm = {f.strip().lower(): f for f in fields}
    for opt in options:
        if opt.lower() in norm:
            return norm[opt.lower()]
    raise KeyError(f'missing {options}; got {fields}')


def to_ms(value: str) -> int:
    x = float(value)
    ax = abs(x)
    if ax >= 1e17:
        return int(round(x / 1e6))
    if ax >= 1e14:
        return int(round(x / 1e3))
    if ax >= 1e11:
        return int(round(x))
    return int(round(x * 1000.0))


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as f:
        for b in iter(lambda: f.read(1024 * 1024), b''):
            h.update(b)
    return h.hexdigest()


def download(url: str, path: Path, attempts: int = 6) -> None:
    last: Exception | None = None
    for i in range(attempts):
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'SMC-ICT-research/1.0'})
            with urllib.request.urlopen(req, timeout=180) as r, path.open('wb') as out:
                shutil.copyfileobj(r, out, length=1024 * 1024)
            if path.stat().st_size == 0:
                raise RuntimeError('empty response')
            return
        except Exception as exc:
            last = exc
            path.unlink(missing_ok=True)
            time.sleep(min(2 ** i, 30))
    raise RuntimeError(f'download failed: {url}: {last}')


@dataclass
class Bar:
    start_ms: int
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0
    turnover: float = 0.0
    trades: int = 0

    def add(self, price: float, size: float) -> None:
        self.high = max(self.high, price)
        self.low = min(self.low, price)
        self.close = price
        self.volume += size
        self.turnover += price * size
        self.trades += 1


@dataclass
class Sensor:
    event_id: str
    symbol: str
    day: str
    side: str
    level: float
    prev_high: float
    prev_low: float
    atr15m20: float
    seq: int
    anchor_ms: int
    anchor_price: float
    sensor: list[tuple[int, float, float, str]] = field(default_factory=list)
    entry_ms: int | None = None
    entry_price: float | None = None

    @property
    def direction(self) -> float:
        return 1.0 if self.side == 'HIGH' else -1.0

    @property
    def decision_ms(self) -> int:
        return self.anchor_ms + 10_000

    @property
    def activation_ms(self) -> int:
        return self.decision_ms + 500


def safe_div(a: float, b: float) -> float:
    return a / b if math.isfinite(b) and b != 0 else float('nan')


def sensor_features(s: Sensor, status: str) -> dict[str, object]:
    base: dict[str, object] = {
        'event_id': s.event_id, 'symbol': s.symbol, 'day': s.day, 'side': s.side,
        'level': s.level, 'prev_high': s.prev_high, 'prev_low': s.prev_low,
        'prev_mid': (s.prev_high + s.prev_low) / 2.0,
        'prev_range': s.prev_high - s.prev_low, 'atr15m20': s.atr15m20,
        'anchor_ms': s.anchor_ms, 'anchor_price': s.anchor_price,
        'decision_ms': s.decision_ms, 'activation_ms': s.activation_ms,
        'entry_ms': '' if s.entry_ms is None else s.entry_ms,
        'entry_price': '' if s.entry_price is None else s.entry_price,
        'status': status,
    }
    if not s.sensor:
        return base
    direction = s.direction
    times = [r[0] for r in s.sensor]
    prices = [r[1] for r in s.sensor]
    sizes = [r[2] for r in s.sensor]
    sides = [r[3] for r in s.sensor]
    quote = [abs(p * q) for p, q in zip(prices, sizes)]
    aggr = [1.0 if x.startswith('B') else -1.0 for x in sides]
    signed = [direction * a * q for a, q in zip(aggr, quote)]
    total = sum(quote); signed_total = sum(signed)
    half = s.anchor_ms + 5_000
    f_total = sum(q for q, t in zip(quote, times) if t < half)
    s_total = sum(q for q, t in zip(quote, times) if t >= half)
    f_signed = sum(q for q, t in zip(signed, times) if t < half)
    s_signed = sum(q for q, t in zip(signed, times) if t >= half)
    from_anchor = [direction * (p - s.anchor_price) / s.anchor_price * 1e4 for p in prices]
    from_level = [direction * (p - s.level) / s.level * 1e4 for p in prices]
    outside = sum(q for p, q in zip(prices, quote) if direction * (p - s.level) >= 0)
    crossings = 0; last_sign = None
    for p in prices:
        sign = 1 if direction * (p - s.level) >= 0 else -1
        if last_sign is not None and sign != last_sign:
            crossings += 1
        last_sign = sign
    move = from_anchor[-1]
    hhi = sum((q / total) ** 2 for q in quote) if total else float('nan')
    base.update({
        'sensor_trade_count': len(times),
        'sensor_first_trade_ms': times[0], 'sensor_last_trade_ms': times[-1],
        'sensor_observed_span_ms': times[-1] - times[0],
        'sensor_total_turnover': total,
        'sensor_outward_signed_turnover': signed_total,
        'flow_imbalance': safe_div(signed_total, total),
        'first_half_flow_imbalance': safe_div(f_signed, f_total),
        'second_half_flow_imbalance': safe_div(s_signed, s_total),
        'flow_acceleration': safe_div(s_signed, s_total) - safe_div(f_signed, f_total),
        'outside_turnover_share': safe_div(outside, total),
        'last_outward_from_level_bps': from_level[-1],
        'last_outward_from_anchor_bps': move,
        'max_favorable_bps': max(from_anchor), 'max_adverse_bps': min(from_anchor),
        'sensor_high': max(prices), 'sensor_low': min(prices),
        'hold_beyond_level': int(direction * (prices[-1] - s.level) >= 0),
        'level_crossing_count': crossings,
        'impact_per_million_signed_turnover_bps': safe_div(move, abs(signed_total) / 1e6),
        'median_trade_quote': statistics.median(quote),
        'max_trade_quote_share': max(quote) / total if total else float('nan'),
        'trade_quote_hhi': hhi,
        'unique_size_ratio': len(set(round(x, 12) for x in sizes)) / len(sizes),
    })
    return base


class MonthProcessor:
    def __init__(self, symbol: str, year: int, month: int):
        self.symbol = symbol; self.year = year; self.month = month
        self.tr15: deque[float] = deque(maxlen=20)
        self.last15close: float | None = None
        self.atr: float | None = None
        self.minbar: Bar | None = None
        self.qbar: Bar | None = None
        self.prev_high: float | None = None
        self.prev_low: float | None = None
        self.day_high: float | None = None
        self.day_low: float | None = None
        self.day_str: str = ''
        self.armed = {'HIGH': True, 'LOW': True}
        self.seq = {'HIGH': 0, 'LOW': 0}
        self.active: list[Sensor] = []
        self.features: list[dict[str, object]] = []
        self.raw_manifest: list[dict[str, object]] = []
        self.last_ts: int | None = None

    def _finish_15m(self) -> None:
        b = self.qbar
        if b is None: return
        tr = b.high - b.low
        if self.last15close is not None:
            tr = max(tr, abs(b.high - self.last15close), abs(b.low - self.last15close))
        self.tr15.append(tr)
        self.last15close = b.close
        self.atr = sum(self.tr15) / 20.0 if len(self.tr15) == 20 else None
        self.qbar = None

    def _finish_minute(self) -> None:
        b = self.minbar
        if b is None: return
        if self.prev_high is not None and self.prev_low is not None and self.atr and self.atr > 0:
            if b.close <= self.prev_high - 0.5 * self.atr:
                self.armed['HIGH'] = True
            if b.close >= self.prev_low + 0.5 * self.atr:
                self.armed['LOW'] = True
        self.minbar = None

    def _roll_bars(self, ts: int) -> None:
        mstart = ts // 60_000 * 60_000
        qstart = ts // 900_000 * 900_000
        if self.qbar is not None and qstart != self.qbar.start_ms:
            self._finish_15m()
        if self.minbar is not None and mstart != self.minbar.start_ms:
            self._finish_minute()

    def _add_bars(self, ts: int, price: float, size: float) -> None:
        mstart = ts // 60_000 * 60_000
        qstart = ts // 900_000 * 900_000
        if self.minbar is None:
            self.minbar = Bar(mstart, price, price, price, price); self.minbar.add(price, size)
        else: self.minbar.add(price, size)
        if self.qbar is None:
            self.qbar = Bar(qstart, price, price, price, price); self.qbar.add(price, size)
        else: self.qbar.add(price, size)

    def _update_sensors(self, ts: int, price: float, size: float, side: str) -> None:
        retained: list[Sensor] = []
        for s in self.active:
            if ts < s.decision_ms:
                s.sensor.append((ts, price, size, side))
                retained.append(s)
            elif s.entry_ms is None and ts >= s.activation_ms:
                s.entry_ms = ts; s.entry_price = price
                self.features.append(sensor_features(s, 'ok'))
            else:
                retained.append(s)
        self.active = retained

    def _new_events(self, ts: int, price: float, size: float, side: str, collect: bool) -> None:
        if not collect or self.prev_high is None or self.prev_low is None or not self.atr or self.atr <= 0:
            return
        candidates: list[tuple[str, float]] = []
        if self.armed['HIGH'] and price >= self.prev_high:
            candidates.append(('HIGH', self.prev_high))
        if self.armed['LOW'] and price <= self.prev_low:
            candidates.append(('LOW', self.prev_low))
        for edge, level in candidates:
            self.seq[edge] += 1
            ev = Sensor(
                event_id=f'{self.symbol}:{self.day_str}:{edge}:{self.seq[edge]}',
                symbol=self.symbol, day=self.day_str, side=edge, level=float(level),
                prev_high=float(self.prev_high), prev_low=float(self.prev_low), atr15m20=float(self.atr),
                seq=self.seq[edge], anchor_ms=ts, anchor_price=price,
                sensor=[(ts, price, size, side)],
            )
            self.active.append(ev)
            self.armed[edge] = False

    def process_trade(self, ts: int, price: float, size: float, side: str, collect: bool) -> None:
        if self.last_ts is not None and ts < self.last_ts:
            raise RuntimeError(f'nonmonotone raw trades: {ts} < {self.last_ts}')
        self.last_ts = ts
        self._roll_bars(ts)
        self._add_bars(ts, price, size)
        self.day_high = price if self.day_high is None else max(self.day_high, price)
        self.day_low = price if self.day_low is None else min(self.day_low, price)
        self._update_sensors(ts, price, size, side)
        self._new_events(ts, price, size, side, collect)

    def start_day(self, day: date, prev_high: float | None, prev_low: float | None) -> None:
        self.day_str = day.isoformat(); self.prev_high = prev_high; self.prev_low = prev_low
        self.day_high = None; self.day_low = None
        self.armed = {'HIGH': True, 'LOW': True}; self.seq = {'HIGH': 0, 'LOW': 0}
        self.last_ts = None

    def end_day(self) -> tuple[float, float]:
        self._finish_15m(); self._finish_minute()
        for s in self.active:
            self.features.append(sensor_features(s, 'no_entry' if s.sensor else 'no_sensor'))
        self.active = []
        if self.day_high is None or self.day_low is None:
            raise RuntimeError(f'no valid trades for {self.day_str}')
        return self.day_high, self.day_low


def iter_raw(path: Path):
    with gzip.open(path, 'rt', newline='', encoding='utf-8-sig') as f:
        r = csv.DictReader(f)
        if not r.fieldnames: raise RuntimeError(f'no header: {path}')
        tf = pick_field(r.fieldnames, ['timestamp', 'time', 'trade_time_ms', 'trade_time'])
        sf = pick_field(r.fieldnames, ['side'])
        qf = pick_field(r.fieldnames, ['size', 'qty', 'quantity'])
        pf = pick_field(r.fieldnames, ['price'])
        for row in r:
            try:
                ts = to_ms(row[tf]); price = float(row[pf]); qty = float(row[qf]); side = row[sf].strip().upper()
            except (ValueError, TypeError, KeyError):
                continue
            if math.isfinite(price) and math.isfinite(qty) and qty > 0:
                yield ts, price, qty, side


def month_days(year: int, month: int) -> list[date]:
    first = date(year, month, 1)
    nxt = date(year + (month == 12), 1 if month == 12 else month + 1, 1)
    return [first + timedelta(days=i) for i in range((nxt - first).days)]


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    keys: list[str] = []; seen: set[str] = set()
    for r in rows:
        for k in r:
            if k not in seen: seen.add(k); keys.append(k)
    with path.open('w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=keys); w.writeheader(); w.writerows(rows)


def main() -> int:
    a = args()
    if not 1 <= a.month <= 12: raise SystemExit('month must be 1..12')
    out = Path(a.output_dir); out.mkdir(parents=True, exist_ok=True)
    proc = MonthProcessor(a.symbol, a.year, a.month)
    days = month_days(a.year, a.month)
    all_days = [days[0] - timedelta(days=1)] + days
    prev_high = prev_low = None
    with tempfile.TemporaryDirectory(prefix='edge-raw-') as td:
        td = Path(td)
        for idx, day in enumerate(all_days):
            url = f'https://public.bybit.com/trading/{a.symbol}/{a.symbol}{day.isoformat()}.csv.gz'
            raw = td / f'{a.symbol}{day.isoformat()}.csv.gz'
            download(url, raw)
            digest = sha256(raw); size = raw.stat().st_size
            proc.start_day(day, prev_high, prev_low)
            rows = 0; min_ts = max_ts = None
            collect = idx > 0
            for ts, price, qty, side in iter_raw(raw):
                rows += 1; min_ts = ts if min_ts is None else min(min_ts, ts); max_ts = ts if max_ts is None else max(max_ts, ts)
                proc.process_trade(ts, price, qty, side, collect)
            prev_high, prev_low = proc.end_day()
            proc.raw_manifest.append({
                'symbol': a.symbol, 'day': day.isoformat(), 'role': 'event' if collect else 'warmup',
                'url': url, 'sha256': digest, 'size_bytes': size, 'rows': rows,
                'min_timestamp_ms': min_ts, 'max_timestamp_ms': max_ts,
            })
            raw.unlink(missing_ok=True)
    prefix = f'{a.symbol}_{a.year}_{a.month:02d}'
    write_csv(out / f'features_{prefix}.csv', proc.features)
    write_csv(out / f'raw_manifest_{prefix}.csv', proc.raw_manifest)
    counts = {k: sum(1 for r in proc.features if r['status'] == k) for k in ['ok', 'no_sensor', 'no_entry']}
    status = {
        'symbol': a.symbol, 'year': a.year, 'month': a.month,
        'candidate_events': len(proc.features), 'status_counts': counts,
        'raw_days': len(proc.raw_manifest), 'raw_total_bytes': sum(int(r['size_bytes']) for r in proc.raw_manifest),
    }
    (out / f'status_{prefix}.json').write_text(json.dumps(status, indent=2, sort_keys=True), encoding='utf-8')
    print(json.dumps(status, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
