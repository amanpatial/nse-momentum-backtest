"""Momentum backtest with an optional fixed stop-loss, simulated with real share holdings.

Usage: python stoploss_backtest.py --cost-bps 12 --stops 0 0.20 0.25 --out results/stoploss

Rules = backtest.py (3M rank, top 20, keep to rank 30, month-end review, liquidity filter) plus:
  * Stop: exit when the day's LOW touches entry_price * (1 - stop). Fill at the stop price, or at the
    OPEN if the stock gaps below the stop. Entry price = rank-date close (same as backtest.py).
  * Cash from a stop stays idle until the next month-end review.
  * Re-entry: a stopped stock is no longer held, so at the next review it can be bought again under
    the base rule (it must be in the top 20 and there must be a free slot).
  * Positions are share holdings that drift with price between reviews; every review resets all
    holdings to equal weight (1/top_n of equity). Costs are charged on every rupee traded.
stop = 0 runs the same engine with no stop (the like-for-like baseline).
"""
import argparse
import pathlib

import duckdb
import pandas as pd

import backtest as bt
import paths


def load(db):
    """Load adjusted close, open, low and traded value from DuckDB as date x symbol tables."""
    con = duckdb.connect(db, read_only=True)
    df = con.execute("select date, symbol, adj_open, adj_low, adj_close, turnover from ohlc").df()
    con.close()
    piv = lambda c: df.pivot(index="date", columns="symbol", values=c).sort_index()
    return piv("adj_close"), piv("adj_open"), piv("adj_low"), piv("turnover")


def simulate(close, opn, low, to, cfg: bt.Cfg, stop: float, reb_dates=None):
    """Share-based momentum backtest with an optional stop-loss; returns daily returns, turnover, trades.
    reb_dates: optional review dates; default = last trading day of each month."""
    c = cfg.cost_bps / 1e4
    px_f, sig, adtv, vol = bt.signals(close, to, cfg)
    reb = set(reb_dates if reb_dates is not None else bt.month_ends(close.index))
    dates = close.index
    nxt = dict(zip(dates[:-1], dates[1:]))

    cash, shares, info = 1.0, {}, {}     # info[sym] = dict(entry_price, ranking_date, entry_rank, ...)
    trades, eq, turn_log = [], [], []
    started = False
    last_px = {}

    def close_trade(sym, d, price, reason, rank=None):
        """Record the exit of an open position and move it to the trade log."""
        t = info.pop(sym)
        t.update(exit_rank_date=d.date() if reason != "stop" else None, exit_rank=rank,
                 exit_reason=reason, sell_date=(d if reason == "stop" else nxt.get(d, d)).date(),
                 exit_price=price)
        trades.append(t)

    for d in dates:
        traded = 0.0
        row_c, row_o, row_l = px_f.loc[d], opn.loc[d], low.loc[d]
        # 1) intraday stop checks (positions bought at a previous close)
        if stop > 0:
            for sym in list(shares):
                lvl = info[sym]["entry_price"] * (1 - stop)
                o, l = row_o.get(sym), row_l.get(sym)
                if pd.isna(l) or pd.isna(o):
                    continue
                if l <= lvl:
                    fill = o if o <= lvl else lvl            # gap below the stop -> fill at open
                    val = shares.pop(sym) * fill
                    cash += val * (1 - c)
                    traded += val
                    info[sym]["stop_fill"] = "gap at open" if o <= lvl else "at stop"
                    close_trade(sym, d, fill, "stop")
        # 2) mark to market at the close
        for sym in shares:
            if not pd.isna(row_c.get(sym)):
                last_px[sym] = row_c[sym]
        V = cash + sum(n * last_px[s] for s, n in shares.items())

        # 3) month-end review at the close
        if d in reb:
            s = bt.ranked_eligible(d, sig, adtv, close, vol, cfg)
            if len(s) >= cfg.buffer:
                started = True
                rank = {k: i + 1 for i, k in enumerate(s.index)}
                new = bt.select_holdings(set(shares), list(s.index), cfg.top_n, cfg.buffer)
                for sym in list(shares):                       # sells
                    if sym not in new:
                        val = shares.pop(sym) * last_px[sym]
                        cash += val * (1 - c)
                        traded += val
                        r = rank.get(sym)
                        close_trade(sym, d, last_px[sym], "rank > %d" % cfg.buffer if r else bt.EXIT_INELIGIBLE, r)
                V = cash + sum(n * last_px[x] for x, n in shares.items())
                tgt = V / len(new)
                for sym in new:                                # buys + resize to equal weight
                    p = row_c[sym]
                    cur = shares.get(sym, 0.0) * p
                    diff = tgt - cur
                    traded += abs(diff)
                    cash -= diff + abs(diff) * c
                    shares[sym] = tgt / p
                    last_px[sym] = p
                    if sym not in info:
                        info[sym] = dict(symbol=sym, ranking_date=d.date(), buy_date=nxt.get(d, d).date(),
                                         entry_rank=rank[sym], entry_3m_return_pct=round(s[sym] * 100, 2),
                                         entry_price=p, stop_price=p * (1 - stop) if stop > 0 else None)
                V = cash + sum(n * last_px[x] for x, n in shares.items())
        if started:
            eq.append((d, V))
            turn_log.append((d, traded / V if V else 0.0))

    last = dates[-1]
    for sym in list(info):
        t = info.pop(sym)
        t.update(exit_rank_date=None, exit_rank=None, exit_reason="OPEN (marked at %s)" % last.date(),
                 sell_date=None, exit_price=last_px[sym])
        trades.append(t)

    eq = pd.Series(dict(eq)).sort_index()
    ret = eq.pct_change().fillna(eq.iloc[0] - 1)
    turn = pd.Series(dict(turn_log)).sort_index()
    td = bt.add_trade_pnl(pd.DataFrame(trades), cfg.cost_bps, last)
    if "stop_fill" not in td:
        td["stop_fill"] = None
    td["exit_rank"] = td["exit_rank"].astype("Int64")
    for col in ("entry_price", "exit_price", "stop_price"):
        td[col] = pd.to_numeric(td[col]).round(2)
    cols = ["symbol", "ranking_date", "entry_rank", "entry_3m_return_pct", "buy_date", "entry_price",
            "stop_price", "exit_rank_date", "exit_rank", "exit_reason", "stop_fill", "sell_date",
            "exit_price", "holding_days", "gross_pnl_pct", "net_pnl_pct"]
    td = td[cols].sort_values(["buy_date", "entry_rank"]).reset_index(drop=True)
    return ret, turn, td


def stop_impact(td: pd.DataFrame, base: pd.DataFrame) -> dict:
    """Compare every stopped trade with the same trade (symbol, buy_date) in the no-stop run."""
    st = td[td["exit_reason"] == "stop"]
    m = st.merge(base[["symbol", "buy_date", "net_pnl_pct"]], on=["symbol", "buy_date"],
                 suffixes=("", "_nostop"))
    saved = int((m["net_pnl_pct_nostop"] < m["net_pnl_pct"]).sum())
    reentered = sum(((td["symbol"] == r.symbol) & (td["buy_date"] > r.sell_date)).any()
                    for r in st.itertuples())
    return {"stops_saved_money": saved, "stops_cost_money": len(m) - saved,
            "avg_stopped_trade_%": round(m["net_pnl_pct"].mean(), 1) if len(m) else None,
            "same_trades_without_stop_%": round(m["net_pnl_pct_nostop"].mean(), 1) if len(m) else None,
            "stopped_then_rebought": int(reentered)}


def main():
    """CLI: run the backtest for each stop level and print/save the comparison."""
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(paths.DB))
    ap.add_argument("--cost-bps", type=float, default=12.0)
    ap.add_argument("--stops", type=float, nargs="+", default=[0.0, 0.20, 0.25])
    ap.add_argument("--max-vol-pctile", type=float, default=1.0, help="volatility filter, 1.0 = off")
    ap.add_argument("--vol-window", type=int, default=63, help="trading days for volatility")
    ap.add_argument("--vol-freq", choices=["daily", "weekly"], default="daily", help="returns used for volatility")
    ap.add_argument("--out", default=str(paths.RESULTS_DIR / "stoploss"))
    a = ap.parse_args()
    out = pathlib.Path(a.out)
    out.mkdir(parents=True, exist_ok=True)

    cfg = bt.Cfg(cost_bps=a.cost_bps, max_vol_pctile=a.max_vol_pctile,
                 vol_window=a.vol_window, vol_freq=a.vol_freq)
    close, opn, low, to = load(a.db)
    rows, daily = [], {}
    base = None
    if any(st > 0 for st in a.stops):            # no-stop trades, to judge each stop exit
        base = simulate(close, opn, low, to, cfg, 0.0)[2]
    for st in a.stops:
        name = "no_stop" if st == 0 else f"stop_{int(round(st * 100))}"
        ret, turn, td = simulate(close, opn, low, to, cfg, st)
        td.to_csv(out / f"trades_{name}.csv", index=False)
        daily[name] = ret
        closed = td[td["sell_date"].notna()]
        yrs = len(ret) / 252
        rows.append({
            "variant": name, **bt.stats_row(ret),
            "trades": len(td), "stop_exits": int((td["exit_reason"] == "stop").sum()),
            "stop_gap_fills": int((td["stop_fill"] == "gap at open").sum()),
            "win_rate_%": round((closed.net_pnl_pct > 0).mean() * 100, 1),
            "avg_win_%": round(closed[closed.net_pnl_pct > 0].net_pnl_pct.mean(), 2),
            "avg_loss_%": round(closed[closed.net_pnl_pct <= 0].net_pnl_pct.mean(), 2),
            "worst_trade_%": round(closed.net_pnl_pct.min(), 2),
            "annual_turnover_x": round(turn.sum() / yrs, 2),
            "start": str(ret.index[0].date()), "end": str(ret.index[-1].date()),
            **(stop_impact(td, base) if st > 0 else {}),
        })
    summ = pd.DataFrame(rows)
    summ.to_csv(out / "summary.csv", index=False)
    pd.DataFrame(daily).to_csv(out / "daily_returns.csv")
    eqy = (1 + pd.DataFrame(daily)).cumprod()
    eqy.groupby(eqy.index.year).last().round(2).to_csv(out / "year_end_value_per_1cr.csv")
    print(summ.T.to_string(header=False))
    print("\nYear-end value of Rs 1 cr:\n", eqy.groupby(eqy.index.year).last().round(2).to_string())


if __name__ == "__main__":
    main()
