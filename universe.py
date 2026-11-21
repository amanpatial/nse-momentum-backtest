"""Point-in-time universe selection.

Input CSV (the Nifty 500 constituents as of Dec 2015 / Jan 2016, from NSE archives,
joined with full market cap on that date from your data source):
    symbol, mcap_cr [, status_today]
Ranks by market cap and keeps ranks start_rank..end_rank (default 251-600 = the
Smallcap-250 zone plus a buffer, ~350 names).
"""
import pandas as pd

import paths


def select(constituents_csv: str, start_rank: int = 251, end_rank: int = 600,
           out: str = str(paths.UNIVERSE_CSV)) -> pd.DataFrame:
    """Rank constituents by market cap and save those ranked start_rank..end_rank."""
    df = pd.read_csv(constituents_csv)
    missing = {"symbol", "mcap_cr"} - set(df.columns)
    if missing:
        raise SystemExit(f"constituents file needs columns symbol, mcap_cr (missing {missing})")
    df = df.sort_values("mcap_cr", ascending=False).reset_index(drop=True)
    df["rank"] = df.index + 1
    sel = df[(df["rank"] >= start_rank) & (df["rank"] <= end_rank)]
    sel.to_csv(out, index=False)
    return sel
