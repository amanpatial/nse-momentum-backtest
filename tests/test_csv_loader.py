"""Tests the single-CSV loader (Option A) on a synthetic file in the IITKGP format.

Run: python -m pytest tests/   or   python tests/test_csv_loader.py
"""
import pathlib
import shutil
import sys
import tempfile

import duckdb
import numpy as np
import pandas as pd

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))   # import the repo-root modules
import ingest  # noqa: E402


def write_synthetic_csv(path: pathlib.Path, days: pd.DatetimeIndex):
    """AAA has an unadjusted 5:1 split (volume x5), BBB a genuine -50% crash, CCC a '.NS' ticker suffix."""
    rows = []
    rng = np.random.default_rng(1)
    for t in ["AAA", "BBB", "CCC"]:
        c = 100 * np.exp(rng.normal(0, 0.01, len(days)).cumsum())
        v = rng.integers(1e5, 2e5, len(days)).astype(float)
        if t == "AAA":                    # unadjusted 5:1 split, volume x5
            k = 300; c[k:] *= 0.2; v[k:] *= 5
        if t == "BBB":                    # genuine -50% crash, NO volume spike -> must not be flagged
            k = 200; c[k:] *= 0.5
        for d, ci, vi in zip(days, c, v):
            rows.append((d.strftime("%Y-%m-%d"), t + ".NS" if t == "CCC" else t, ci, ci * 1.01, ci * 0.99, ci, vi, ""))
    cols = ["Date", "Ticker", "Open", "High", "Low", "Close", "Volume", "Notes"]
    pd.DataFrame(rows, columns=cols).to_csv(path, index=False)


def test_csv_loader_flags_only_the_split_and_adjusts_it():
    """Only the split (not the crash) is flagged; auto-adjust removes it; the '.NS' suffix is stripped."""
    tmp = pathlib.Path(tempfile.mkdtemp())
    try:
        days = pd.bdate_range("2021-06-09", "2023-06-09")
        write_synthetic_csv(tmp / "x.csv", days)
        n, k = ingest.build_db_from_csv(str(tmp / "x.csv"), str(tmp / "t.duckdb"), auto_adjust=True,
                                        detected_out=str(tmp / "det.csv"))
        det = pd.read_csv(tmp / "det.csv")
        print(n, k)
        print(det)
        assert k == 1 and det.iloc[0]["symbol"] == "AAA" and abs(det.iloc[0]["factor"] - 0.2) < 1e-9

        con = duckdb.connect(str(tmp / "t.duckdb"), read_only=True)
        assert con.execute("select count(*) from ohlc where symbol='CCC'").fetchone()[0] == len(days)  # .NS stripped
        m = con.execute("""select max(abs(r)) from (select adj_close/lag(adj_close) over (order by date)-1 r
                           from ohlc where symbol='AAA')""").fetchone()[0]
        con.close()
        assert m < 0.1, m
    finally:
        shutil.rmtree(tmp)


def test_drop_rows_removes_listed_ranges_only():
    """--drop-rows removes exactly the listed symbol/date ranges (inclusive) and nothing else."""
    tmp = pathlib.Path(tempfile.mkdtemp())
    try:
        days = pd.bdate_range("2021-06-09", "2023-06-09")
        write_synthetic_csv(tmp / "x.csv", days)
        pd.DataFrame({"symbol": ["AAA", "BBB"], "start": [str(days[0].date()), str(days[10].date())],
                      "end": [str(days[4].date()), str(days[10].date())],
                      "reason": ["stale quotes", "mispriced session"]}).to_csv(tmp / "bad.csv", index=False)
        ingest.build_db_from_csv(str(tmp / "x.csv"), str(tmp / "t.duckdb"), detected_out=str(tmp / "det.csv"),
                                 drop_csv=str(tmp / "bad.csv"))
        con = duckdb.connect(str(tmp / "t.duckdb"), read_only=True)
        n = dict(con.execute("select symbol, count(*) from ohlc group by 1").fetchall())
        gone = con.execute(f"select count(*) from ohlc where symbol='BBB' and date = date '{days[10].date()}'").fetchone()[0]
        con.close()
        assert n == {"AAA": len(days) - 5, "BBB": len(days) - 1, "CCC": len(days)}, n
        assert gone == 0
    finally:
        shutil.rmtree(tmp)


if __name__ == "__main__":
    test_csv_loader_flags_only_the_split_and_adjusts_it()
    test_drop_rows_removes_listed_ranges_only()
    print("CSV LOADER OK")
