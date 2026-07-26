"use strict";

const fs = require("fs");
const path = require("path");
const { getHistoricalRates } = require("dukascopy-node");

const DAY_MS = 24 * 60 * 60 * 1000;
const CHUNK_DAYS = 7;
const MAX_ATTEMPTS = 8;

function isoDate(date) {
  return date.toISOString().slice(0, 10);
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function rowTimestamp(row) {
  const value = Array.isArray(row) ? row[0] : row && row.timestamp;
  const numeric = typeof value === "number" ? value : Number(value);
  if (Number.isFinite(numeric)) {
    return numeric;
  }
  const parsed = Date.parse(String(value));
  if (!Number.isFinite(parsed)) {
    throw new Error(`Dukascopy row has no parseable timestamp: ${JSON.stringify(row).slice(0, 200)}`);
  }
  return parsed;
}

async function fetchChunk(instrument, fromDate, toDate) {
  let lastError = null;
  for (let attempt = 1; attempt <= MAX_ATTEMPTS; attempt += 1) {
    try {
      const data = await getHistoricalRates({
        instrument,
        dates: { from: fromDate, to: toDate },
        timeframe: "m1",
        priceType: "bid",
        format: "json",
        volumes: true,
        ignoreFlats: false,
      });
      if (!Array.isArray(data) || data.length === 0) {
        throw new Error(`no rows returned for ${instrument} ${isoDate(fromDate)} ${isoDate(toDate)}`);
      }
      return { data, attempts: attempt };
    } catch (error) {
      lastError = error;
      const delayMs = Math.min(20_000, 750 * (2 ** (attempt - 1)));
      console.error(JSON.stringify({
        event: "dukascopy_retry",
        instrument,
        from: isoDate(fromDate),
        to: isoDate(toDate),
        attempt,
        max_attempts: MAX_ATTEMPTS,
        delay_ms: attempt === MAX_ATTEMPTS ? 0 : delayMs,
        error: error && error.message ? error.message : String(error),
      }));
      if (attempt < MAX_ATTEMPTS) {
        await sleep(delayMs);
      }
    }
  }
  throw lastError || new Error(`Dukascopy fetch failed for ${instrument}`);
}

async function main() {
  const [instrument, from, to, output] = process.argv.slice(2);
  if (!instrument || !from || !to || !output) {
    throw new Error("usage: node download_dukascopy.js <instrument> <from> <to> <output>");
  }
  if (!["usatechidxusd", "usa500idxusd"].includes(instrument)) {
    throw new Error(`prohibited instrument: ${instrument}`);
  }
  for (const value of [from, to]) {
    const year = Number(value.slice(0, 4));
    if ([2024, 2025, 2026].includes(year)) {
      throw new Error(`sealed year requested: ${year}`);
    }
  }

  const start = new Date(`${from}T00:00:00.000Z`);
  const end = new Date(`${to}T00:00:00.000Z`);
  if (!Number.isFinite(start.getTime()) || !Number.isFinite(end.getTime()) || start >= end) {
    throw new Error(`invalid date interval: ${from} ${to}`);
  }

  const rowsByTimestamp = new Map();
  let cursor = start;
  let chunks = 0;
  let totalAttempts = 0;
  while (cursor < end) {
    const next = new Date(Math.min(end.getTime(), cursor.getTime() + CHUNK_DAYS * DAY_MS));
    const { data, attempts } = await fetchChunk(instrument, cursor, next);
    chunks += 1;
    totalAttempts += attempts;
    for (const row of data) {
      rowsByTimestamp.set(rowTimestamp(row), row);
    }
    cursor = next;
  }

  const timestamps = [...rowsByTimestamp.keys()].sort((a, b) => a - b);
  if (timestamps.length === 0) {
    throw new Error(`no Dukascopy rows for ${instrument} ${from} ${to}`);
  }
  if (timestamps[0] < start.getTime() || timestamps[timestamps.length - 1] >= end.getTime()) {
    throw new Error(`Dukascopy rows escaped requested interval for ${instrument} ${from} ${to}`);
  }
  for (let index = 1; index < timestamps.length; index += 1) {
    if (timestamps[index] <= timestamps[index - 1]) {
      throw new Error(`non-monotonic Dukascopy timestamp for ${instrument}`);
    }
  }

  const data = timestamps.map((timestamp) => rowsByTimestamp.get(timestamp));
  fs.mkdirSync(path.dirname(output), { recursive: true });
  fs.writeFileSync(output, JSON.stringify(data));
  process.stdout.write(JSON.stringify({
    instrument,
    from,
    to,
    rows: data.length,
    chunks,
    total_attempts: totalAttempts,
    output,
  }) + "\n");
}

main().catch((error) => {
  console.error(error && error.stack ? error.stack : String(error));
  process.exit(1);
});
