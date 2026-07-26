# Stablecoin issuance forced-liquidity ML

## Profit mechanism

A large USDT or USDC mint creates crypto-dollar inventory that can be deployed into spot and derivatives markets. A burn removes that inventory. The source event is external to the four traded Bybit contracts and is known from an Ethereum block before any later market outcome.

The intended trader-readable route is:

1. causally observe an ERC-20 USDT/USDC mint or burn;
2. wait for the frozen 12-block confirmation delay, with 64 blocks as stress;
3. freeze the already-known BTCUSDT and ETHUSDT upper/lower 60-minute external liquidity;
4. use one HGBT plus one calibration map to estimate which pool is reached first;
5. take only a positive 24-bp expected-value LONG or SHORT in one global Bybit slot;
6. exit at the frozen target, the opposite frozen liquidity invalidation, or a punitive source-boundary stop—never because time elapsed.

## Current phase

Only the outcome-sealed Ethereum source gate is open. It tests canonical USDT/USDC bytecode, fixed pre-2024 month-to-block mapping, mint/burn log decoding, block timestamps, event density and causal availability.

The source gate is prohibited from opening cryptocurrency prices, future labels, model metrics, trades, PnL, risk/leverage search, 2024-2026 data, credentials or orders.

## Non-overlap

This is not Aave forced liquidation flow, CEX liquidation data, OI/funding, stable-quote fragmentation, ordinary CEX order flow, spot/perpetual lead-lag, maker execution or a named candle setup. Its information unit is stablecoin supply issuance and destruction recorded on Ethereum.

## Reproduction

```bash
python -m pip install requests==2.32.4 pytest==8.3.5
python -m py_compile research/ml_stablecoin_issuance_20260726/source_gate.py
PYTHONPATH=research/ml_stablecoin_issuance_20260726 \
  pytest -q research/ml_stablecoin_issuance_20260726/test_source_gate.py
PYTHONPATH=research/ml_stablecoin_issuance_20260726 \
  python research/ml_stablecoin_issuance_20260726/source_gate.py --self-test
PYTHONPATH=research/ml_stablecoin_issuance_20260726 \
  python research/ml_stablecoin_issuance_20260726/source_gate.py \
    --output research_runs/ml_stablecoin_issuance_20260726/source_gate
```
