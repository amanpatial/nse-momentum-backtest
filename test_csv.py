"""Tests the single-CSV loader on a synthetic file in the IITKGP format."""
import pathlib
import tempfile

import duckdb
import numpy as np
import pandas as pd

import data

tmp = pathlib.Path(tempfile.mkdtemp())
days = pd.bdate_range("2021-06-09", "2023-06-09")
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
pd.DataFrame(rows, columns=["Date", "Ticker", "Open", "High", "Low", "Close", "Volume", "Notes"]).to_csv(tmp / "x.csv", index=False)

n, k = data.build_db_from_csv(str(tmp / "x.csv"), str(tmp / "t.duckdb"), auto_adjust=True,
                              detected_out=str(tmp / "det.csv"))
det = pd.read_csv(tmp / "det.csv")
print(n, k); print(det)
assert k == 1 and det.iloc[0]["symbol"] == "AAA" and abs(det.iloc[0]["factor"] - 0.2) < 1e-9
con = duckdb.connect(str(tmp / "t.duckdb"), read_only=True)
assert con.execute("select count(*) from ohlc where symbol='CCC'").fetchone()[0] == len(days)  # .NS stripped
m = con.execute("""select max(abs(r)) from (select adj_close/lag(adj_close) over (order by date)-1 r
                   from ohlc where symbol='AAA')""").fetchone()[0]
assert m < 0.1, m
print("CSV LOADER OK")
