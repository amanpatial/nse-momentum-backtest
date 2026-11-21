#!/usr/bin/env bash
# Rebuild the database and regenerate every result in the README.
# Usage: ./run_all.sh                  main dataset (Option A, 2021-2026) -> results/      (about a minute)
#        DATASET=10y ./run_all.sh      10-year Yahoo dataset (Option C)   -> results/10y/
#        SKIP_BUILD=1 ./run_all.sh     reuse the existing database (works with either dataset)
# Inputs and the databases live in data/ (same defaults as paths.py). Both datasets show in the dashboard.
set -euo pipefail
cd "$(dirname "$0")"
PY="${PY:-.venv/bin/python}"
export PYTHONWARNINGS=ignore     # hides the urllib3/LibreSSL warning on macOS system Python

case "${DATASET:-main}" in
  main)
    CSV=data/nifty500_5yr_data.csv; DB=data/smallcap.duckdb; OUT=results
    BUILD_ARGS=(--corp-actions data/corp_actions.csv) ;;
  10y)
    CSV=data/nifty500_2016_2026.csv; DB=data/nifty500_10y.duckdb; OUT=results/10y
    BUILD_ARGS=(--corp-actions data/corp_actions_10y.csv --drop-rows data/bad_rows_10y.csv
                --detected-out data/detected_actions_10y.csv) ;;
  *) echo "Unknown DATASET=${DATASET} (use main or 10y)"; exit 1 ;;
esac

echo "== self-tests"
$PY tests/test_rules.py
$PY tests/test_csv_loader.py

if [ -z "${SKIP_BUILD:-}" ]; then
  if [ ! -f "$CSV" ]; then
    if [ "${DATASET:-main}" = "10y" ]; then
      echo "Missing $CSV. Download it first (needs pip install yfinance, ~40 s):"
      echo "  $PY nifty500_downloader.py --start 2016-11-22 --end 2026-11-22"
      exit 1
    fi
    echo "== download price data (Hugging Face, ~55 MB, checksum-verified)"
    $PY pipeline.py download --out "$CSV" || { echo "Download failed: get $CSV by hand (see data/README.md)"; exit 1; }
  fi
  echo "== build database $DB (reviewed fixes: ${BUILD_ARGS[*]})"
  $PY pipeline.py build-csv --csv "$CSV" --db "$DB" "${BUILD_ARGS[@]}"
  $PY pipeline.py check --db "$DB"
fi

echo "== main backtest (40 bps, rules as in README)"
$PY pipeline.py backtest --db "$DB" --out "$OUT/"

echo "== cost sensitivity + volatility-filter grid"
$PY sweep.py costs --db "$DB" --out "$OUT/sweeps"
$PY sweep.py volfilter --db "$DB" --cost-bps 12 --out "$OUT/sweeps"

echo "== volatility filter, recommended setting (drop top 10%, daily, 63d)"
$PY pipeline.py backtest --db "$DB" --out "$OUT/volfilter" --cost-bps 12 --max-vol-pctile 0.9

echo "== trade logs"
$PY export_trades.py --db "$DB" --cost-bps 12 --out "$OUT/trades.csv"
$PY export_trades.py --db "$DB" --cost-bps 12 --max-vol-pctile 0.9 --out "$OUT/trades_volfilter90.csv"

echo "== stop-loss test"
$PY stoploss_backtest.py --db "$DB" --cost-bps 12 --stops 0 0.20 0.25 --out "$OUT/stoploss"

echo "== lookback / review-frequency variants"
$PY variants.py --db "$DB" --cost-bps 12 --out "$OUT/variants"

echo "== zerodha cost check"
$PY costs.py --order 500000 --slippage-bps 9

echo "Done. Results in $OUT/"
