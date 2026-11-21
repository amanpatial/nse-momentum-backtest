# data/

Inputs and the database for the backtest. Only `corp_actions.csv` (and this README) are in git;
everything else is downloaded or rebuilt, so the folder looks almost empty on GitHub.

| File | In git? | Where it comes from |
|---|---|---|
| `corp_actions.csv` | yes | Hand-reviewed split / bonus / demerger fixes (see main README, section 4) |
| `nifty500_5yr_data.csv` | no (55 MB) | Downloaded automatically by `./run_all.sh` (checksum-verified) |
| `smallcap.duckdb` | no (~90 MB) | Built by `./run_all.sh` from the CSV |
| `detected_actions.csv` | no | Written by every build: suspected unadjusted splits, for review |
| `raw/`, `universe.csv` | no | Only for the NSE bhavcopy route (Option B in the main README) |
| `nifty500_2016_2026.csv` | no (95 MB) | Optional 10-year Yahoo Finance prices: `python nifty500_downloader.py --start 2016-11-22` |
| `corp_actions_10y.csv` | yes | Reviewed fixes for the 10-year data: 6 reused from `corp_actions.csv` + ABREL, HEG demergers |
| `bad_rows_10y.csv` | yes | Reviewed bad rows dropped from the 10-year data (stale frozen quotes, mispriced sessions), with reasons |
| `nifty500_10y.duckdb`, `detected_actions_10y.csv` | no | Built from the 10-year CSV (command below) |

## Get the data and rebuild

From the repo root run `./run_all.sh`. On the first run it downloads `nifty500_5yr_data.csv` from the
[IITKGP Nifty500 dataset](https://huggingface.co/datasets/IITKGP/Nifty500_companies_5_years_data)
(MIT license), verifies its SHA-256, then builds `smallcap.duckdb` and `detected_actions.csv` here and
writes every result to `results/`.

- Download only: `python pipeline.py download` (skips if a verified copy exists; `--force` re-downloads).
- Offline / proxy: download the file by hand ("Files and versions" tab on the link above) and save it
  here as `data/nifty500_5yr_data.csv`; `run_all.sh` then uses it as is.
- The pinned URL and checksum live in `ingest.py` (`PRICES_URL`, `PRICES_SHA256`).

Optional 10-year database (separate from the default one):
```bash
python pipeline.py build-csv --csv data/nifty500_2016_2026.csv --db data/nifty500_10y.duckdb \
    --detected-out data/detected_actions_10y.csv --corp-actions data/corp_actions_10y.csv \
    --drop-rows data/bad_rows_10y.csv
python pipeline.py backtest --db data/nifty500_10y.duckdb --out results/10y/base_12bps --cost-bps 12
```
It uses today's Nifty 500 list, so survivorship bias is larger than in the default 4.6-year data.

Default locations are set in `paths.py`; change them there if you keep the data elsewhere.
