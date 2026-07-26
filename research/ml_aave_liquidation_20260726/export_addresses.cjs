'use strict';

const markets = require('@aave-dao/aave-address-book');

function required(path, value) {
  if (typeof value !== 'string' || !/^0x[0-9a-fA-F]{40}$/.test(value)) {
    throw new Error(`missing or invalid ${path}: ${String(value)}`);
  }
  return value;
}

const output = {
  schema_version: 1,
  package: '@aave-dao/aave-address-book',
  package_version: '4.61.0',
  source_repository: 'aave-dao/aave-address-book',
  source_commit: '67c777be17e782c2f961a44e085ec55b39e63639',
  ethereum_chain_id: 1,
  pools: {
    v2: required('AaveV2Ethereum.POOL', markets.AaveV2Ethereum && markets.AaveV2Ethereum.POOL),
    v3: required('AaveV3Ethereum.POOL', markets.AaveV3Ethereum && markets.AaveV3Ethereum.POOL),
  },
};

process.stdout.write(`${JSON.stringify(output, null, 2)}\n`);
