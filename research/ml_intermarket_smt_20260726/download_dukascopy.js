"use strict";

const fs = require("fs");
const path = require("path");
const { getHistoricalRates } = require("dukascopy-node");

const DAY_MS = 24 * 60 * 60 * 1000;
const PRIMARY_CHUNK_DAYS = 28;
const MIN_CHUNK_DAYS = 7;
const PRIMARY_ATTEMPTS = 4;
const LEAF_ATTEMPTS = 6;
const SEALED_START_MS = Date.parse("2024-01-01T00:00:00.000Z");

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

async function fetchDirect(instrument, fromDate, toDate, maxAttempts) {
  let lastError = null;
  for (let attempt = 1; attempt <= maxAttempts; attempt += 1) {
    try {
      const data = await getHistoricalRates({
        instrument,
        dates: { from: fromDate, to: toDate },
        timeframe: "m1",
        priceType: "bid",
        format: "array",
      });
      if (!Array.isArray(data) || data.length === 0) {
        throw new Error(`no rows returned for ${instrument} ${isoDate(fromDate)} ${isoDate(toDate)}`);
      }
      return { data, attempts: attempt };
    } catch (error) {
      lastError = error;
      const delayMs = Math.min(12_000, 750 * (2 ** (attempt - 1)));
      console.error(JSON.stringify({
        event: "dukascopy_retry",
        instrument,
        from: isoDate(fromDate),
        to: isoDate(toDate),
        attempt,
        max_attempts: maxAttempts,
        delay_ms: attempt === maxAttempts ? 0 : delayMs,
        error: error && error.message ? error.message : String(error),
      }));
      if (attempt < maxAttempts) {
        await sleep(delayMs);
      }
    }
  }
  throw lastError || new Error(`Dukascopy fetch failed for ${instrument}`);
}

function splitRange(fromDate, toDate) {
  const spanDays = Math.round((toDate.getTime() - fromDate.getTime()) / DAY_MS);
  let leftDays = Math.floor(spanDays / 2);
  leftDays = Math.max(MIN_CHUNK_DAYS, leftDays);
  if (spanDays - leftDays < MIN_CHUNK_DAYS) {
    leftDays = spanDays - MIN_CHUNK_DAYS;
  }
  const split = new Date(fromDate.getTime() + leftDays * DAY_MS);
  if (!(fromDate < split && split < toDate)) {
    throw new Error(`cannot split Dukascopy range ${isoDate(fromDate)} ${isoDate(toDate)}`);
  }
  return split;
}

async function fetchAdaptive(instrument, fromDate, toDate, depth = 0) {
  const spanDays = Math.round((toDate.getTime() - fromDate.getTime()) / DAY_MS);
  const maxAttempts = spanDays <= MIN_CHUNK_DAYS ? LEAF_ATTEMPTS : PRIMARY_ATTEMPTS;
  try {
    const direct = await fetchDirect(instrument, fromDate, toDate, maxAttempts);
    return {
      data: direct.data,
      attempts: direct.attempts,
      networkRanges: 1,
      leafChunks: 1,
      maxDepth: depth,
    };
  } catch (error) {
    if (spanDays <= MIN_CHUNK_DAYS) {
      throw error;
    }
    const split = splitRange(fromDate, toDate);
    console.error(JSON.stringify({
      event: "dukascopy_split_failed_range",
      instrument,
      from: isoDate(fromDate),
      to: isoDate(toDate),
      split: isoDate(split),
      depth,
      error: error && error.message ? error.message : String(error),
    }));
    const left = await fetchAdaptive(instrument, fromDate, split, depth + 1);
    const right = await fetchAdaptive(instrument, split, toDate, depth + 1);
    return {
      data: left.data.concat(right.data),
      attempts: maxAttempts + left.attempts + right.attempts,
      networkRanges: 1 + left.networkRanges + right.networkRanges,
      leafChunks: left.leafChunks + right.leafChunks,
      maxDepth: Math.max(left.maxDepth, right.maxDepth),
    };
  }
}

async function main() {
  const [instrument, from, to, output] = process.argv.slice(2);
  if (!instrument || !from || !to || !output) {
    throw new Error("usage: node download_dukascopy.js <instrument> <from> <to> <output>");
  }
  if (!["usatechidxusd", "usa500idxusd"].includes(instrument)) {
    throw new Error(`prohibited instrument: ${instrument}`);
  }

  const start = new Date(`${from}T00:00:00.000Z`);
  const end = new Date(`${to}T00:00:00.000Z`);
  if (!Number.isFinite(start.getTime()) || !Number.isFinite(end.getTime()) || start >= end) {
    throw new Error(`invalid date interval: ${from} ${to}`);
  }
  if (start.getTime() >= SEALED_START_MS || end.getTime() > SEALED_START_MS) {
    throw new Error(`sealed interval requested: ${from} ${to}`);
  }

  const rowsByTimestamp = new Map();
  let cursor = start;
  let primaryChunks = 0;
  let leafChunks = 0;
  let networkRanges = 0;
  let totalAttempts = 0;
  let maxSplitDepth = 0;
  while (cursor < end) {
    const next = new Date(Math.min(end.getTime(), cursor.getTime() + PRIMARY_CHUNK_DAYS * DAY_MS));
    const fetched = await fetchAdaptive(instrument, cursor, next);
    primaryChunks += 1;
    leafChunks += fetched.leafChunks;
    networkRanges += fetched.networkRanges;
    totalAttempts += fetched.attempts;
    maxSplitDepth = Math.max(maxSplitDepth, fetched.maxDepth);
    for (const row of fetched.data) {
      rowsByTimestamp.set(rowTimestamp(row), row);
    }
    console.error(JSON.stringify({
      event: "dukascopy_primary_range_complete",
      instrument,
      from: isoDate(cursor),
      to: isoDate(next),
      rows_received: fetched.data.length,
      rows_unique_so_far: rowsByTimestamp.size,
      leaf_chunks: fetched.leafChunks,
      network_ranges: fetched.networkRanges,
      attempts: fetched.attempts,
      max_split_depth: fetched.maxDepth,
    }));
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
    primary_chunks: primaryChunks,
    leaf_chunks: leafChunks,
    network_ranges: networkRanges,
    total_attempts: totalAttempts,
    max_split_depth: maxSplitDepth,
    output,
  }) + "\n");
}

main().catch((error) => {
  console.error(error && error.stack ? error.stack : String(error));
  process.exit(1);
});
