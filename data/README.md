# data/

Inputs and the database for the backtest. Only `corp_actions.csv` (and this README) are in git;
everything else is downloaded or rebuilt, so the folder looks almost empty on GitHub.

| File | In git? | Where it comes from |
|---|---|---|
| `corp_actions.csv` | yes | Hand-reviewed split / bonus / demerger fixes (see main README, section 4) |
| `nifty500_5yr_data.csv` | no (52 MB) | **Download it** (step below) |
| `smallcap.duckdb` | no (~90 MB) | Built by `./run_all.sh` from the CSV |
| `detected_actions.csv` | no | Written by every build: suspected unadjusted splits, for review |
| `raw/`, `universe.csv` | no | Only for the NSE bhavcopy route (Option B in the main README) |

## Get the data and rebuild

1. Download `nifty500_5yr_data.csv` from the
   [IITKGP Nifty500 dataset](https://huggingface.co/datasets/IITKGP/Nifty500_companies_5_years_data)
   ("Files and versions" tab) and save it here as `data/nifty500_5yr_data.csv`.
2. From the repo root run `./run_all.sh`. It builds `smallcap.duckdb` and `detected_actions.csv` here
   and writes every result to `results/` (about a minute).

Default locations are set in `paths.py`; change them there if you keep the data elsewhere.
