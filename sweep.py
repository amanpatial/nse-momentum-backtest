"""Parameter sweeps on the main backtest (backtest.run), saved as CSV.

Usage:
  python sweep.py costs     --db smallcap.duckdb --costs 12 20 40          --out results/sweeps
  python sweep.py volfilter --db smallcap.duckdb --cost-bps 12              --out results/sweeps
  python sweep.py volfilter --pctiles 1.0 0.9 0.8 --windows 63 --freqs daily weekly

costs     : strategy at each cost per side, plus buy and hold -> costs.csv
volfilter : grid of --vol-freq x --vol-window x --max-vol-pctile (1.0 = filter off) -> volfilter.csv
            (all settings scored on the same common period)
"""
import argparse
import pathlib

import pandas as pd

import backtest as bt


def row(out: pd.DataFrame, col: str = "net") -> dict:
    """Rounded stats of one return column of a backtest run."""
    return bt.stats_row(out[col])


def turnover(out: pd.DataFrame) -> float:
    """Average annual turnover (x portfolio value) of a backtest run."""
    return round(float(out["turnover"].mean() * 252), 1)


def costs(px, to, a):
    """Run the strategy at each cost level and compare with buy-and-hold and the benchmark."""
    rows = []
    for c in a.costs:
        out, _ = bt.run(px, to, bt.Cfg(cost_bps=c))
        cost_drag = out["turnover"].mean() * 252 * c / 100
        rows.append({"variant": f"strategy @ {c:g} bps/side", "cost_bps": c, **row(out),
                     "annual_turnover_x": turnover(out), "annual_cost_drag_%": round(cost_drag, 2)})
    rows.append({"variant": "buy and hold (no costs)", "cost_bps": None, **row(out, "buy_hold")})
    rows.append({"variant": "equal-weight benchmark (no costs)", "cost_bps": None, **row(out, "bench")})
    return pd.DataFrame(rows), out


def volfilter(px, to, a):
    """Run every volatility-filter setting and compare them on a common period.
    All settings are scored on the same common period: longer vol windows need more history,
    so their first review is later; every run is cut to the latest first date."""
    runs = []
    for f in a.freqs:
        for w in a.windows:
            for p in a.pctiles:
                off = p >= 1.0
                if off and any(r[0]["max_vol_pctile"] >= 1.0 for r in runs):
                    continue                                   # filter off: same result for every freq/window
                cfg = bt.Cfg(cost_bps=a.cost_bps, max_vol_pctile=p, vol_window=w, vol_freq=f)
                out, _ = bt.run(px, to, cfg)
                runs.append(({"vol_freq": "-" if off else f, "vol_window": "-" if off else w,
                              "max_vol_pctile": p, "drop_most_volatile_%": round((1 - p) * 100),
                              "own_start": str(out.index[0].date())}, out))
                print(runs[-1][0], flush=True)
    common = max(out.index[0] for _, out in runs)
    rows = [{**k, **row(out.loc[common:]), "annual_turnover_x": turnover(out.loc[common:])} for k, out in runs]
    return pd.DataFrame(rows), runs[0][1].loc[common:]


def main():
    """CLI: run the costs or volfilter sweep and save the table to CSV."""
    ap = argparse.ArgumentParser()
    ap.add_argument("sweep", choices=["costs", "volfilter"])
    ap.add_argument("--db", default="smallcap.duckdb")
    ap.add_argument("--out", default="results/sweeps")
    ap.add_argument("--costs", type=float, nargs="+", default=[12, 20, 40])
    ap.add_argument("--cost-bps", type=float, default=12.0, help="cost for the volfilter sweep")
    ap.add_argument("--pctiles", type=float, nargs="+", default=[1.0, 0.95, 0.9, 0.85, 0.8, 0.7, 0.5])
    ap.add_argument("--windows", type=int, nargs="+", default=[63, 126])
    ap.add_argument("--freqs", nargs="+", choices=["daily", "weekly"], default=["daily", "weekly"])
    a = ap.parse_args()

    px, to = bt.load_panel(a.db)
    df, out = costs(px, to, a) if a.sweep == "costs" else volfilter(px, to, a)
    d = pathlib.Path(a.out)
    d.mkdir(parents=True, exist_ok=True)
    df.to_csv(d / f"{a.sweep}.csv", index=False)
    print(f"\nPeriod {out.index[0].date()} to {out.index[-1].date()}\n")
    print(df.to_string(index=False))
    print(f"\n-> {d / (a.sweep + '.csv')}")


if __name__ == "__main__":
    main()
