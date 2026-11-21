"""Compare lookback / review-frequency variants of the momentum strategy (no stop-loss).

Usage: python variants.py --cost-bps 12 --out results/variants

Lookback: 3M = 63, 6M = 126, 12M = 252 trading days. Review every N calendar days (first trading
day on/after each date). All variants start on the same date (first day a 12M signal exists) so they
cover the same period. Uses the share-based engine in stoploss_backtest.simulate (stop = 0).
Robustness: each variant is also re-run with the review schedule shifted (different start offsets),
because results for a fixed N-day cycle depend on which days the reviews happen to fall on.
"""
import argparse
import pathlib

import pandas as pd

import backtest as bt
import paths
from stoploss_backtest import load, simulate

LOOKBACK = {"3M": 63, "6M": 126, "12M": 252}
VARIANTS = [("3M", "month-end"), ("3M", 30), ("3M", 45), ("6M", 30), ("6M", 45), ("12M", 30), ("12M", 45)]


def every_n_days(dates, start, n):
    """Review dates: first trading day on/after start, then every n calendar days."""
    out, t = [], pd.Timestamp(start)
    while True:
        later = dates[dates >= t]
        if not len(later):
            return out
        out.append(later[0])
        t = later[0] + pd.Timedelta(days=n)


def main():
    """CLI: backtest each lookback / review-frequency variant on a common period and compare."""
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(paths.DB))
    ap.add_argument("--cost-bps", type=float, default=12.0)
    ap.add_argument("--max-vol-pctile", type=float, default=1.0, help="volatility filter, 1.0 = off")
    ap.add_argument("--vol-window", type=int, default=63, help="trading days for volatility")
    ap.add_argument("--vol-freq", choices=["daily", "weekly"], default="daily", help="returns used for volatility")
    ap.add_argument("--out", default=str(paths.RESULTS_DIR / "variants"))
    a = ap.parse_args()
    out = pathlib.Path(a.out)
    out.mkdir(parents=True, exist_ok=True)

    close, opn, low, to = load(a.db)
    dates = close.index
    start = dates[max(LOOKBACK.values())]          # first date with a 12M signal
    month_end = [d for d in bt.month_ends(dates) if d >= start]

    rows, daily = [], {}
    for lb, rev in VARIANTS:
        name = f"{lb}_{rev if rev == 'month-end' else str(rev) + 'd'}"
        cfg = bt.Cfg(lookback=LOOKBACK[lb], cost_bps=a.cost_bps, max_vol_pctile=a.max_vol_pctile,
                 vol_window=a.vol_window, vol_freq=a.vol_freq)
        reb = month_end if rev == "month-end" else every_n_days(dates, start, rev)
        ret, turn, td = simulate(close, opn, low, to, cfg, 0.0, reb)
        ret = ret[ret.index >= start]
        td.to_csv(out / f"trades_{name}.csv", index=False)
        daily[name] = ret
        closed = td[td["sell_date"].notna()]
        yrs = len(ret) / 252
        # schedule-offset robustness (not for month-end)
        offs = []
        if rev != "month-end":
            for k in (1, 2):
                sh = start + pd.Timedelta(days=round(rev * k / 3))
                r2, _, _ = simulate(close, opn, low, to, cfg, 0.0, [start] + every_n_days(dates, sh, rev))
                offs.append(bt.stats(r2[r2.index >= start])["CAGR"])
        all_c = [bt.stats(ret)["CAGR"]] + offs
        rows.append({
            "variant": name, "lookback_days": LOOKBACK[lb], "review": rev, **bt.stats_row(ret),
            "reviews": len(reb), "trades": len(td),
            "win_rate_%": round((closed.net_pnl_pct > 0).mean() * 100, 1),
            "avg_hold_days": round(closed.holding_days.mean()),
            "annual_turnover_x": round(turn[turn.index >= start].sum() / yrs, 2),
            "CAGR_range_other_schedules_%": "" if not offs else
                f"{min(all_c) * 100:.1f} to {max(all_c) * 100:.1f}",
        })
    summ = pd.DataFrame(rows)
    summ.to_csv(out / "summary.csv", index=False)
    d = pd.DataFrame(daily)
    bench = close.ffill(limit=5).pct_change(fill_method=None).mean(axis=1)
    d["equal_weight_bench"] = bench.reindex(d.index)
    d.to_csv(out / "daily_returns.csv")
    eqy = (1 + d).cumprod()
    ye = eqy.groupby(eqy.index.year).last().round(2)
    ye.to_csv(out / "year_end_value_per_1cr.csv")
    bs = bt.stats(d["equal_weight_bench"])
    print(f"Common period: {d.index[0].date()} to {d.index[-1].date()} ({len(d) / 252:.2f} yrs), cost {a.cost_bps} bps/side")
    print(summ.drop(columns=["lookback_days", "review"]).to_string(index=False))
    print(f"\nEqual-weight benchmark: CAGR {bs['CAGR']:.1%}  Vol {bs['Vol']:.1%}  Sharpe {bs['Sharpe(rf=0)']:.2f}  MaxDD {bs['MaxDD']:.1%}")
    print("\nYear-end value of Rs 1 cr:\n" + ye.to_string())


if __name__ == "__main__":
    main()
