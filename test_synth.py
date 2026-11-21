"""End-to-end test on synthetic NSE-format data (no network needed).
Checks: legacy parsing, series filter, ticker rename mapping, split adjustment,
universe filter, DuckDB build, data checks, backtest runs with finite output."""
import pathlib
import shutil
import tempfile

import numpy as np
import pandas as pd

import backtest as bt
import data


def gen(raw: pathlib.Path, n=150, start="2015-01-01", end="2018-12-31"):
    """Write synthetic daily bhavcopy CSVs (with a split, a rename and junk rows) into raw."""
    rng = np.random.default_rng(7)
    days = pd.bdate_range(start, end)
    syms = np.array([f"SYM{i:03d}" for i in range(n)], dtype=object)
    close = rng.uniform(50, 2000, n) * np.exp(rng.normal(0.0003, 0.025, (len(days), n)).cumsum(0))
    split_ex = pd.Timestamp("2017-06-01")
    raw_close = close.copy()
    raw_close[days < split_ex, 0] *= 5          # SYM000: 5-for-1 split, raw prices unadjusted
    for k, d in enumerate(days):
        s = syms.copy()
        if d < pd.Timestamp("2016-01-01"):
            s[1] = "OLD001"                      # ticker renamed to SYM001 on 2016-01-01
        c = raw_close[k]
        o = raw_close[k - 1] if k else c
        vol = rng.integers(10_000, 1_000_000, n)
        df = pd.DataFrame({
            "SYMBOL": s, "SERIES": "EQ", "OPEN": o,
            "HIGH": np.maximum(o, c) * 1.01, "LOW": np.minimum(o, c) * 0.99,
            "CLOSE": c, "LAST": c, "PREVCLOSE": o, "TOTTRDQTY": vol,
            "TOTTRDVAL": vol * c, "TIMESTAMP": d.strftime("%d-%b-%Y").upper(),
            "TOTALTRADES": 100, "ISIN": "INE000000000",
        })
        junk = df.iloc[[0]].copy()               # non-equity series row that must be filtered out
        junk[["SYMBOL", "SERIES"]] = ["JUNK", "N1"]
        df = pd.concat([df, junk], ignore_index=True)
        df.to_csv(raw / f"{d:%Y%m%d}.csv", index=False)
    return days


def main():
    """Build a DB from synthetic data, run checks and a backtest, and assert the results."""
    tmp = pathlib.Path(tempfile.mkdtemp())
    raw = tmp / "raw"
    raw.mkdir()
    days = gen(raw)
    pd.DataFrame({"symbol": ["SYM000"], "ex_date": ["2017-06-01"], "factor": [0.2]}).to_csv(tmp / "ca.csv", index=False)
    pd.DataFrame({"old": ["OLD001"], "new": ["SYM001"]}).to_csv(tmp / "map.csv", index=False)
    db = str(tmp / "t.duckdb")
    print("build:", data.build_db(str(raw), db, str(tmp / "ca.csv"), str(tmp / "map.csv")))

    import duckdb
    con = duckdb.connect(db, read_only=True)
    assert con.execute("select count(*) from ohlc where symbol in ('JUNK','OLD001')").fetchone()[0] == 0
    assert con.execute("select count(*) from ohlc where symbol='SYM001'").fetchone()[0] == len(days)
    raw_max = con.execute("""select max(abs(r)) from (select close/lag(close) over (order by date) - 1 as r
                             from ohlc where symbol='SYM000')""").fetchone()[0]
    adj_max = con.execute("""select max(abs(r)) from (select adj_close/lag(adj_close) over (order by date) - 1 as r
                             from ohlc where symbol='SYM000')""").fetchone()[0]
    con.close()
    print(f"SYM000 max daily move raw={raw_max:.2f} adjusted={adj_max:.2f}")
    assert raw_max > 0.5 and adj_max < 0.3, "split adjustment failed"

    chk = data.checks(db)
    print("big_moves rows (>30%):", len(chk["big_moves"]))

    cfg = bt.Cfg(start="2016-03-01", top_n=20, min_adtv_cr=0.5)
    px, to = bt.load_panel(db)
    out, pos = bt.run(px, to, cfg)
    rep = bt.report(out, cfg)
    print({k: v for k, v in rep.items() if k != "config"})
    assert np.isfinite(rep["strategy_net"]["CAGR"]) and (pos.sum(axis=1).max() <= 1.0 + 1e-9)
    print("ALL CHECKS PASSED")
    shutil.rmtree(tmp)


if __name__ == "__main__":
    main()
