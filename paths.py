"""Default file locations, built from the repo root so scripts work from any working directory.

Change a location here and every script, run_all.sh default and the dashboard follow.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parent

DATA_DIR = ROOT / "data"
PRICES_CSV = DATA_DIR / "nifty500_5yr_data.csv"        # downloaded input (Option A), not in git
CORP_ACTIONS = DATA_DIR / "corp_actions.csv"           # reviewed split/bonus fixes, in git
DETECTED_ACTIONS = DATA_DIR / "detected_actions.csv"   # written by the build, for review
DB = DATA_DIR / "smallcap.duckdb"                      # built by the pipeline, not in git
RAW_DIR = DATA_DIR / "raw"                             # NSE bhavcopy downloads (Option B)
UNIVERSE_CSV = DATA_DIR / "universe.csv"               # selected universe (Option B)

RESULTS_DIR = ROOT / "results"                         # everything run_all.sh writes

# Optional 10-year Yahoo dataset (DATASET=10y ./run_all.sh; README section 6.6)
DB_10Y = DATA_DIR / "nifty500_10y.duckdb"
RESULTS_10Y_DIR = RESULTS_DIR / "10y"
