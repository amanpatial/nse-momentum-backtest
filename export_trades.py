"""Export a trade log from the momentum backtest.

Usage: python export_trades.py --cost-bps 12 --out results/trades.csv   (--db defaults to data/smallcap.duckdb)

One row per holding period (buy -> sell) of a stock. Prices are adjusted closes.
Timing matches backtest.run(): ranks use the rank-date close, and the position earns returns
from that close onward (exposure starts the next trading day). So entry price = close on the
ranking date and exit price = close on the ranking date when the stock was dropped.
buy_date / sell_date = the next trading day (when the order would actually be placed);
the backtest assumes it fills at the ranking-date close, which is mildly optimistic.
"""
import argparse

import numpy as np
import pandas as pd

import backtest as bt
import paths


def main():
    """CLI: rerun the backtest and write one row per holding period to a CSV."""
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(paths.DB))
    ap.add_argument("--cost-bps", type=float, default=12.0)
    ap.add_argument("--max-vol-pctile", type=float, default=1.0, help="volatility filter, 1.0 = off")
    ap.add_argument("--vol-window", type=int, default=63, help="trading days for volatility")
    ap.add_argument("--vol-freq", choices=["daily", "weekly"], default="daily", help="returns used for volatility")
    ap.add_argument("--out", default=str(paths.RESULTS_DIR / "trades.csv"))
    a = ap.parse_args()

    cfg = bt.Cfg(cost_bps=a.cost_bps, max_vol_pctile=a.max_vol_pctile,
                 vol_window=a.vol_window, vol_freq=a.vol_freq)
    px, to = bt.load_panel(a.db)
    out, pos = bt.run(px, to, cfg)

    px_f, sig, adtv, vol = bt.signals(px, to, cfg)     # same ranking inputs as backtest.run()
    reb = bt.month_ends(px.index)
    nxt = pd.Series(px.index[1:], index=px.index[:-1])  # next trading day

    w = pos.shift(-1)  # weights decided on each date
    open_tr, trades = {}, []
    for d in reb:
        if d not in w.index or not (w.loc[d] > 0).any():
            continue
        s = bt.ranked_eligible(d, sig, adtv, px, vol, cfg)
        rank = s.rank(ascending=False, method="first")
        held = set(w.loc[d][w.loc[d] > 0].index)
        for sym in list(open_tr):            # exits
            if sym not in held:
                t = open_tr.pop(sym)
                r = rank.get(sym, np.nan)
                t.update(exit_rank_date=d.date(), sell_date=nxt.get(d, d).date(),
                         exit_rank=None if pd.isna(r) else int(r),
                         exit_reason="rank > %d" % cfg.buffer if not pd.isna(r) else bt.EXIT_INELIGIBLE,
                         exit_price=px_f.loc[d, sym])
                trades.append(t)
        for sym in held - set(open_tr):      # entries
            open_tr[sym] = dict(symbol=sym, ranking_date=d.date(),
                                buy_date=nxt.get(d, d).date(),
                                entry_rank=int(rank[sym]), entry_3m_return_pct=round(s[sym] * 100, 2),
                                entry_price=px_f.loc[d, sym])
    last = out.index[-1]
    for sym, t in open_tr.items():           # still held at the end
        t.update(exit_rank_date=None, sell_date=None, exit_rank=None,
                 exit_reason="OPEN (marked at %s)" % last.date(), exit_price=px_f.loc[last, sym])
        trades.append(t)

    df = bt.add_trade_pnl(pd.DataFrame(trades), a.cost_bps, last)
    df[["entry_price", "exit_price"]] = df[["entry_price", "exit_price"]].round(2)
    cols = ["symbol", "ranking_date", "entry_rank", "entry_3m_return_pct", "buy_date", "entry_price",
            "exit_rank_date", "exit_rank", "exit_reason", "sell_date", "exit_price",
            "holding_days", "gross_pnl_pct", "net_pnl_pct"]
    df = df[cols].sort_values(["buy_date", "entry_rank"]).reset_index(drop=True)
    df["exit_rank"] = df["exit_rank"].astype("Int64")
    df.to_csv(a.out, index=False)

    closed = df[df["sell_date"].notna()]
    print(f"{len(df)} trades ({len(closed)} closed, {len(df) - len(closed)} open) -> {a.out}")
    print(f"closed: win rate {(closed.net_pnl_pct > 0).mean():.1%}, avg net P&L {closed.net_pnl_pct.mean():.2f}%, "
          f"median {closed.net_pnl_pct.median():.2f}%, avg hold {closed.holding_days.mean():.0f} days")
    print(f"avg win {closed[closed.net_pnl_pct > 0].net_pnl_pct.mean():.2f}% | "
          f"avg loss {closed[closed.net_pnl_pct <= 0].net_pnl_pct.mean():.2f}%")
    print("strategy net CAGR check:", round(bt.stats(out["net"])["CAGR"] * 100, 1), "%")


if __name__ == "__main__":
    main()
