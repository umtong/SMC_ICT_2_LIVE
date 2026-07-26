"use strict";

const fs = require("fs");
const path = require("path");
const { getHistoricalRates } = require("dukascopy-node");

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
  const data = await getHistoricalRates({
    instrument,
    dates: { from: new Date(`${from}T00:00:00.000Z`), to: new Date(`${to}T00:00:00.000Z`) },
    timeframe: "m1",
    priceType: "bid",
    format: "json",
    volumes: true,
    ignoreFlats: false,
  });
  if (!Array.isArray(data) || data.length === 0) {
    throw new Error(`no Dukascopy rows for ${instrument} ${from} ${to}`);
  }
  fs.mkdirSync(path.dirname(output), { recursive: true });
  fs.writeFileSync(output, JSON.stringify(data));
  process.stdout.write(JSON.stringify({ instrument, from, to, rows: data.length, output }) + "\n");
}

main().catch((error) => {
  console.error(error && error.stack ? error.stack : String(error));
  process.exit(1);
});
