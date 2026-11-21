#!/usr/bin/env bash
# Rebuild the database and regenerate every result in the README (Option A data).
# Usage: ./run_all.sh            (from the repo root, with .venv set up; about a minute)
#        SKIP_BUILD=1 ./run_all.sh   to reuse an existing data/smallcap.duckdb
# Inputs and the database live in data/, outputs in results/ (same defaults as paths.py).
set -euo pipefail
cd "$(dirname "$0")"
PY="${PY:-.venv/bin/python}"
export PYTHONWARNINGS=ignore     # hides the urllib3/LibreSSL warning on macOS system Python
DB=data/smallcap.duckdb
CSV=data/nifty500_5yr_data.csv

echo "== self-tests"
$PY tests/test_rules.py
$PY tests/test_csv_loader.py

if [ -z "${SKIP_BUILD:-}" ]; then
  [ -f "$CSV" ] || { echo "Missing $CSV (download it, see README section 1)"; exit 1; }
  echo "== build database (data/corp_actions.csv = reviewed split/bonus fixes)"
  $PY pipeline.py build-csv --csv "$CSV" --db "$DB" --corp-actions data/corp_actions.csv
  $PY pipeline.py check --db "$DB"
fi

echo "== main backtest (40 bps, rules as in README)"
$PY pipeline.py backtest --db "$DB" --out results/

echo "== cost sensitivity + volatility-filter grid"
$PY sweep.py costs --db "$DB" --out results/sweeps
$PY sweep.py volfilter --db "$DB" --cost-bps 12 --out results/sweeps

echo "== volatility filter, recommended setting (drop top 10%, daily, 63d)"
$PY pipeline.py backtest --db "$DB" --out results/volfilter --cost-bps 12 --max-vol-pctile 0.9

echo "== trade logs"
$PY export_trades.py --db "$DB" --cost-bps 12 --out results/trades.csv
$PY export_trades.py --db "$DB" --cost-bps 12 --max-vol-pctile 0.9 --out results/trades_volfilter90.csv

echo "== stop-loss test"
$PY stoploss_backtest.py --db "$DB" --cost-bps 12 --stops 0 0.20 0.25 --out results/stoploss

echo "== lookback / review-frequency variants"
$PY variants.py --db "$DB" --cost-bps 12 --out results/variants

echo "== zerodha cost check"
$PY costs.py --order 500000 --slippage-bps 9

echo "Done. Results in results/"
