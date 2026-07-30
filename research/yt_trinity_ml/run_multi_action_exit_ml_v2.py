#!/usr/bin/env python3
"""Adapter that accepts the current raw-alpha parquet labels for exit-action ML."""
from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from run_multi_action_exit_ml_v1 import run


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--labels', type=Path, required=True)
    parser.add_argument('--btc-bars', type=Path, required=True)
    parser.add_argument('--eth-bars', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.labels.suffix == '.parquet':
        converted = args.output / 'CURRENT_EVENT_LABELS.pkl.gz'
        args.output.mkdir(parents=True, exist_ok=True)
        pd.read_parquet(args.labels).to_pickle(converted, compression='gzip')
        args.labels = converted
    return run(args)


if __name__ == '__main__':
    raise SystemExit(main())
